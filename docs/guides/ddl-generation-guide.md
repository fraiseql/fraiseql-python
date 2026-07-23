---
title: "Writing DDL for Table-Backed Views"
description: How to hand-write the PostgreSQL DDL for FraiseQL's table-backed read views (tv_*).
keywords: ["ddl", "table-backed-views", "postgresql", "best-practices", "tutorial"]
tags: ["documentation", "guide"]
---

# Writing DDL for Table-Backed Views

**Status:** Production Ready
**Audience:** DBAs, Developers, Architects
**Reading Time:** 12-15 minutes

---

## Prerequisites

**Required Knowledge:**

- SQL fundamentals (SELECT, JOIN, WHERE clauses)
- View concepts (logical views, materialized data, triggers)
- FraiseQL schema definition and view selection
- Performance implications of different read strategies
- Index design and query optimization basics
- PostgreSQL schema design patterns

**Required Software:**

- PostgreSQL 14+
- `psql` (or another PostgreSQL client)
- Python 3.13+ (for the FraiseQL application itself)
- A text editor for SQL scripts

**Required Infrastructure:**

- Access to your PostgreSQL database
- A database user with DDL permissions (`CREATE TABLE`, `CREATE VIEW`, `CREATE FUNCTION`)
- Your normalized write tables (`tb_*`) already deployed
- Your own migration tooling for applying DDL (plain `.sql` files, or a tool such as
  Flyway / Liquibase / Alembic — whatever your team already uses)

**Optional but Recommended:**

- The [View Selection Guide](../architecture/database/view-selection-guide.md) for decision making
- Database performance monitoring tools
- Version control for tracking DDL changes
- Schema visualization tools
- Query performance analysis (`EXPLAIN ANALYZE`)

**Time Estimate:** 15-30 minutes to write the DDL, 30-60 minutes for validation and testing.

## Overview

In FraiseQL v1 **you write your own PostgreSQL DDL by hand** (or with your own migration
tooling). FraiseQL does **not** generate tables, views, or functions for you — there is no
CLI and no code generator. At application startup FraiseQL reads the read views and functions
you have defined and serves them over GraphQL.

This guide shows the DDL you write for a **table-backed read view** (`tv_*`): a real table that
holds pre-composed JSONB, kept up to date by a refresh function and trigger. Use this pattern when
a logical `v_*` view is too slow because it composes deeply nested relationships on every read.

### What This Guide Covers

- The full DDL you write for a `tv_*` table-backed view
- The supporting composition helper views, indexes, refresh function, trigger, and monitoring helpers
- When to use a table-backed view versus a plain logical view
- Links to the decision-making and schema-design guides

### What This Guide Does NOT Cover

- It does **not** describe an automatic generator — there isn't one in v1; you write the SQL.
- It does **not** make optimization decisions for you.
- It does **not** deploy anything; apply the DDL with your own migration process.

**Philosophy:** Decide *whether* you need a table-backed view using the
[View Selection Guide](../architecture/database/view-selection-guide.md). Once you've decided,
use the patterns here to write the SQL.

---

## Quick Start

A minimal table-backed view for a `User` entity looks like this. You write it once, apply it with
your migration tooling, and point your `@fraiseql.type` at the resulting view.

```sql
-- Physical table holding pre-composed JSONB for each user
CREATE TABLE tv_user_profile (
    id          UUID NOT NULL PRIMARY KEY,
    data        JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Refresh one user's row from the normalized write tables
CREATE OR REPLACE FUNCTION refresh_tv_user_profile(p_id UUID)
RETURNS void
LANGUAGE sql AS $$
    INSERT INTO tv_user_profile (id, data, updated_at)
    SELECT u.id,
           jsonb_build_object('id', u.id, 'name', u.name, 'email', u.email),
           NOW()
    FROM tb_user u
    WHERE u.id = p_id
    ON CONFLICT (id) DO UPDATE
        SET data = EXCLUDED.data, updated_at = NOW();
$$;
```

Then expose it in Python:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="tv_user_profile", jsonb_column="data")
class User:
    id: ID
    name: str
    email: str
```

---

## When to Use a Table-Backed View

**Use a `tv_*` table-backed view when:**

- You've read the [View Selection Guide](../architecture/database/view-selection-guide.md)
- A logical `v_*` view composes deeply nested relationships and is too slow on the read path
- You can tolerate a small, controlled refresh delay (trigger-based is near real-time)
- You want to review and own the SQL before deploying

**Stick with a plain logical `v_*` view when:**

- The composition is cheap enough to run on every read
- You want zero refresh machinery to maintain
- You're still evaluating performance

---

## Design Parameters

When you write a table-backed view by hand, these are the decisions you make. They are not
function arguments — they are choices reflected directly in the DDL you write.

| Decision | Options | Notes |
|----------|---------|-------|
| Refresh strategy | trigger-based or scheduled | See below |
| Composition helper views | include or inline | Helper views keep the refresh function readable |
| Monitoring helpers | include or skip | Staleness / row-count functions for production observability |

### Entity and View Naming

Follow the FraiseQL PostgreSQL naming conventions:

- `tb_*` — normalized **write tables** (the source of truth; never exposed in GraphQL)
- `v_*` — logical **read views** (a `SELECT` that builds a `data` JSONB column)
- `tv_*` — **table-backed read views**: a real table holding pre-composed JSONB, refreshed by
  functions/triggers; used for heavy nested reads
- `fn_*` — PostgreSQL **functions** implementing mutation write logic

Every read view (logical or table-backed) carries an `id` UUID column (for `WHERE id = $1`) **plus**
a `data` JSONB column built with `jsonb_build_object(...)`. Never put internal `pk_*` BIGINT keys
inside `data` or expose them in GraphQL.

### Refresh Strategy

Choose based on your workload:

| Strategy | Best For | Overhead | Latency |
|----------|----------|----------|---------|
| **trigger-based** | High-change data, low tolerance for stale data | Medium (per-row) | <100ms |
| **scheduled** | Batch processes, can tolerate stale data | Low (batched) | 1-60 minutes |

**Trigger-based** — a trigger on the source `tb_*` table calls the refresh function on every
insert/update, so the table-backed view stays fresh within milliseconds.

**Scheduled** — a cron job, `pg_cron` task, or external scheduler calls a "refresh all" function
on an interval. Lower overhead, but the data is as stale as your interval allows.

### Composition Helper Views

For deeply nested relationships, write small helper `v_*` views that pre-compose each level into
JSONB. The refresh function then joins those helpers instead of building the whole tree inline:

```sql
-- Helper views: pre-compose each nested level into JSONB
CREATE VIEW v_user_posts_composed AS
    SELECT p.fk_user AS user_id,
           jsonb_agg(jsonb_build_object('id', p.id, 'title', p.title)) AS posts
    FROM tb_post p
    GROUP BY p.fk_user;

-- Main table-backed view, fed by the helper above
CREATE TABLE tv_user_profile (
    id          UUID NOT NULL PRIMARY KEY,
    data        JSONB NOT NULL,   -- contains nested posts + comments
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

If you prefer to inline the composition directly in the refresh function, skip the helper views.

### Monitoring Helpers

Optionally add functions to track staleness and row counts. These are useful for production
monitoring:

```sql
-- Monitoring helpers
CREATE OR REPLACE FUNCTION tv_user_profile_staleness()
RETURNS interval
LANGUAGE sql AS $$
    SELECT NOW() - MIN(updated_at) FROM tv_user_profile;
$$;

CREATE OR REPLACE FUNCTION tv_user_profile_row_count()
RETURNS bigint
LANGUAGE sql AS $$
    SELECT COUNT(*) FROM tv_user_profile;
$$;
```

Skip them if you monitor staleness separately.

---

## Full DDL Structure

A complete table-backed view typically contains six sections. Here is the full set written out
for `tv_user_profile`:

```sql
-- 1. Composition Helper Views
-- Pre-compose nested relationships into JSONB.
CREATE VIEW v_user_posts_composed AS
    SELECT p.fk_user AS user_id,
           jsonb_agg(jsonb_build_object('id', p.id, 'title', p.title)) AS posts
    FROM tb_post p
    GROUP BY p.fk_user;

-- 2. Physical Table
-- The actual table that stores pre-composed JSONB.
CREATE TABLE tv_user_profile (
    id          UUID NOT NULL PRIMARY KEY,
    data        JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (id) REFERENCES tb_user(id) ON DELETE CASCADE
);

-- 3. Indexes
-- Optimize common queries.
CREATE INDEX idx_tv_user_profile_data_gin ON tv_user_profile USING GIN(data);
CREATE INDEX idx_tv_user_profile_updated ON tv_user_profile(updated_at);

-- 4. Refresh Function
-- Maintains a row based on source data.
CREATE OR REPLACE FUNCTION refresh_tv_user_profile(p_id UUID)
RETURNS void
LANGUAGE sql AS $$
    INSERT INTO tv_user_profile (id, data, updated_at)
    SELECT u.id,
           jsonb_build_object(
               'id', u.id,
               'name', u.name,
               'email', u.email,
               'posts', COALESCE(pc.posts, '[]'::jsonb)
           ),
           NOW()
    FROM tb_user u
    LEFT JOIN v_user_posts_composed pc ON pc.user_id = u.id
    WHERE u.id = p_id
    ON CONFLICT (id) DO UPDATE
        SET data = EXCLUDED.data, updated_at = NOW();
$$;

-- 5. Refresh Trigger (trigger-based strategy)
-- Automatically calls the refresh function on source changes.
CREATE OR REPLACE FUNCTION trg_refresh_tv_user_profile()
RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM refresh_tv_user_profile(NEW.id);
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_tv_user_profile_refresh
    AFTER INSERT OR UPDATE ON tb_user
    FOR EACH ROW
    EXECUTE FUNCTION trg_refresh_tv_user_profile();

-- 6. Monitoring Helpers
-- Track view health and staleness.
CREATE OR REPLACE FUNCTION tv_user_profile_staleness()
RETURNS interval
LANGUAGE sql AS $$
    SELECT NOW() - MIN(updated_at) FROM tv_user_profile;
$$;

CREATE OR REPLACE FUNCTION tv_user_profile_row_count()
RETURNS bigint
LANGUAGE sql AS $$
    SELECT COUNT(*) FROM tv_user_profile;
$$;
```

---

## Applying the DDL

Save the SQL in a migration file and apply it with `psql` (or your migration tool):

```bash
# Apply to staging first
psql -h staging-db -U postgres mydb < tv_user_profile.sql
```

Combine multiple views into one migration by concatenating the files:

```bash
cat tv_user_profile.sql tv_order_summary.sql > 0007_table_backed_views.sql
```

---

## Next Steps

### 1. Write the DDL

Write the table, indexes, refresh function, trigger, and (optionally) monitoring helpers using the
patterns above.

### 2. Review the SQL

Read through your DDL carefully:

- Does the composition match what your GraphQL type expects?
- Are all relationships included in the JSONB?
- Is the refresh strategy appropriate for the data's change rate?
- Are the indexes reasonable for your query patterns?

### 3. Test in Staging

Apply the DDL to a staging database, then back-fill and verify it:

```sql
-- Back-fill all rows once (or call refresh per id)
INSERT INTO tv_user_profile (id, data, updated_at)
SELECT u.id, jsonb_build_object('id', u.id, 'name', u.name, 'email', u.email), NOW()
FROM tb_user u
ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = NOW();

-- Check row count
SELECT COUNT(*) FROM tv_user_profile;

-- Check staleness
SELECT tv_user_profile_staleness();

-- Spot-check a few rows
SELECT * FROM tv_user_profile LIMIT 5;
```

### 4. Point Your Type at the View

Set `sql_source="tv_user_profile"` on the `@fraiseql.type` and let FraiseQL serve it.

### 5. Deploy to Production

Once staging verification passes, apply the same migration to production.

---

## Common Patterns

### User Profile with Nested Posts

Build the user's posts (and their comments) into the `data` JSONB so the read path is a single
indexed lookup:

```sql
SELECT u.id,
       jsonb_build_object(
           'id', u.id,
           'name', u.name,
           'email', u.email,
           'posts', COALESCE(pc.posts, '[]'::jsonb)
       )
FROM tb_user u
LEFT JOIN v_user_posts_composed pc ON pc.user_id = u.id;
```

**Resulting `data` shape:**

```json
{
  "id": "user-123",
  "name": "Alice",
  "email": "alice@example.com",
  "posts": [
    {
      "id": "post-1",
      "title": "Hello",
      "comments": []
    }
  ]
}
```

### Order Summary with Line Items

```sql
SELECT o.id,
       jsonb_build_object(
           'id', o.id,
           'customer_id', o.fk_customer,
           'total', o.total,
           'status', o.status,
           'line_items', COALESCE(li.items, '[]'::jsonb)
       )
FROM tb_order o
LEFT JOIN v_order_line_items_composed li ON li.order_id = o.id;
```

**Resulting `data` shape:**

```json
{
  "id": "order-123",
  "customer_id": "cust-456",
  "total": 99.99,
  "status": "shipped",
  "line_items": [
    {
      "product_id": "prod-789",
      "quantity": 2,
      "price": 49.99
    }
  ]
}
```

---

## Troubleshooting

### Issue: GraphQL type returns null fields

**Symptom:** A queried field is always `null` even though the source data exists.

**Solution:**

- Confirm the field name in `jsonb_build_object(...)` matches the GraphQL field (FraiseQL maps
  `data` JSONB keys to type fields).
- Re-run the refresh function for that row and re-check `SELECT data FROM tv_user_profile WHERE id = ...`.

### Issue: Stale data after writes

**Symptom:** Writes to `tb_*` aren't reflected in the table-backed view.

**Solution:**

- For trigger-based refresh, verify the trigger exists on the source table:
  `\d tb_user` in `psql`.
- For scheduled refresh, verify your scheduler is actually calling the refresh function.

### Issue: Generated SQL has syntax errors

**Symptom:** `psql` reports a syntax error when applying the migration.

**Solution:**

- Apply the file incrementally and read the line reported in the error.
- Check for unbalanced `$$ ... $$` function bodies.
- Report a framework issue: [GitHub Issues](https://github.com/fraiseql/fraiseql/issues)

---

## Validation

Before deploying, sanity-check the DDL yourself:

- Valid PostgreSQL syntax (apply it to a throwaway database first)
- Table and view definitions match the GraphQL types they back
- Column types are correct (`id` UUID, `data` JSONB)
- Indexes match your query patterns (GIN on `data`, btree on `updated_at`)
- The refresh function and trigger fire as expected

A quick smoke test in staging:

```sql
-- Apply, back-fill, then verify a representative row
SELECT data FROM tv_user_profile WHERE id = 'user-123';
```

---

## Performance Considerations

### Trigger-Based Refresh

**Best for:**

- Small to medium tables (< 100K rows)
- High query volume (> 1000 req/sec)
- Sub-second data freshness requirements

**Cost:**

- A small per-row refresh cost on every source write
- Scales linearly with the update rate

### Scheduled Refresh

**Best for:**

- Large tables (> 1M rows)
- Batch processes
- Tolerance for 1-60 minute staleness

**Cost:**

- A fixed batch cost per run, largely independent of read volume
- Freshness bounded by the schedule (hourly, nightly, etc.)

---

## See Also

- **[View Selection Guide](../architecture/database/view-selection-guide.md)** — decide whether to use table-backed views
- **[TV Table Pattern](../architecture/database/tv-table-pattern.md)** — deep dive into table-backed read views
- **[Schema Design Best Practices](./schema-design-best-practices.md)** — naming conventions and DDL design

---

## Questions?

For issues or questions:

1. Check the [troubleshooting section](#troubleshooting)
2. Review the [View Selection Guide](../architecture/database/view-selection-guide.md)
3. Open an issue: [GitHub Issues](https://github.com/fraiseql/fraiseql/issues)

---
title: "tv_* Table Pattern: Table-Backed JSON Views"
description: Physically stored, pre-composed JSONB projections for high-performance nested GraphQL reads.
keywords: ["design", "scalability", "performance", "patterns", "postgresql"]
tags: ["documentation", "reference"]
---

# tv_* Table Pattern: Table-Backed JSON Views

## Overview

**`tv_*` tables** are PostgreSQL tables that pre-compute and physically store a
pre-composed `data` JSONB column for high-performance GraphQL reads over complex,
deeply nested data. A `tv_*` table looks exactly like a `v_*` read view to FraiseQL
(`id` + `data` JSONB), but the JSONB is materialized on disk instead of being
composed on every query.

**Key difference from logical views (`v_*`):** unlike a logical view, a `tv_*`
relation is a real table with:

- Physical storage on disk (materialized `data` JSONB)
- A trigger-based or scheduled refresh mechanism
- Denormalized JSONB composition for complex nested queries
- Substantially faster read performance on deeply nested data

FraiseQL queries a `tv_*` table the same way it queries a `v_*` view — via
`db.find("tv_user_profile")` / `db.find_one(...)` from a `@fraiseql.query`
resolver. Choosing between `v_*` and `tv_*` is purely a database design decision;
the GraphQL layer is unchanged.

## When to Use tv_* Tables

### Use tv_* when

- **Complex JSONB composition** with multiple JOINs (3+ related entities)
- **Deep nesting** is required (e.g., User → Posts → Comments → Likes)
- **High-frequency read, low-frequency write** workloads
- **Pre-aggregated dashboards** with complex data structures
- **GraphQL queries** follow consistent nested patterns
- **GraphQL subscriptions** need fast access to composed data

### Don't use tv_* when

- **Simple queries** (single or 2-table joins) — use a `v_*` logical view instead
- **Frequently changing data** with millisecond freshness requirements
- **Storage is constrained** (a `tv_*` table duplicates the JSONB data)
- **Dynamic query patterns** where the composition varies per request

## Performance Comparison

### Scenario: complex user profile with posts, comments, and likes (10K users)

| Metric | `v_user_full` (view) | `tv_user_profile` (table) | Improvement |
|--------|----------------------|---------------------------|-------------|
| Query time | 2–5 s | 100–200 ms | 10–50x faster |
| JSONB composition | Real-time (multiple JOINs) | Pre-computed | Zero JOIN cost |
| Memory usage | 500 MB–1 GB | 150–300 MB | 3–6x lower |
| CPU | 50–80% | 5–10% | 5–16x reduction |

### Query breakdown

**Logical view (`v_user_full`)** — real-time composition:

```text
1. Fetch user (1ms)
2. Fetch posts (2-3s via JOIN)
3. Compose posts array (500-800ms)
4. Fetch comments per post (1-2s via subqueries)
5. Compose comments array (300-500ms)
6. Fetch likes per comment (1-2s)
7. Build final JSONB (200-300ms)
Total: 5-10 seconds
```

**Table-backed view (`tv_user_profile`)** — pre-computed:

```text
1. Fetch pre-composed JSONB (100-200ms)
Total: 100-200ms
```

## DDL Pattern

### Basic structure

```sql
-- 1. Create physical table with pre-composed JSONB
CREATE TABLE tv_user_profile (
    id TEXT NOT NULL PRIMARY KEY,
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (id) REFERENCES tb_user(id) ON DELETE CASCADE
);

-- 2. Create index for faster lookups
CREATE INDEX idx_tv_user_profile_data_gin
    ON tv_user_profile USING GIN(data);

-- 3. Create refresh trigger for near-real-time updates
CREATE TRIGGER trg_refresh_tv_user_profile
    AFTER INSERT OR UPDATE OR DELETE ON tb_user
    FOR EACH ROW
    EXECUTE FUNCTION refresh_tv_user_profile_trigger();
```

### JSONB composition pattern

```sql
-- Helper view to compose nested data (intermediate step)
CREATE VIEW v_user_posts_composed AS
SELECT
    fk_user,
    jsonb_agg(
        jsonb_build_object(
            'id', p.id,
            'title', p.title,
            'content', p.content,
            'createdAt', p.created_at,
            'comments', COALESCE(comments.data, '[]'::jsonb)
        )
        ORDER BY p.created_at DESC
    ) AS posts_data
FROM v_post p
LEFT JOIN (
    -- Pre-aggregate comments per post
    SELECT
        fk_post,
        jsonb_agg(
            jsonb_build_object(
                'id', c.id,
                'text', c.text,
                'createdAt', c.created_at
            )
            ORDER BY c.created_at DESC
        ) AS data
    FROM v_comment
    GROUP BY fk_post
) comments ON comments.fk_post = p.pk_post
GROUP BY fk_user;

-- Main table-backed view with pre-composed JSONB
CREATE TABLE tv_user_profile (
    id TEXT NOT NULL PRIMARY KEY,
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (id) REFERENCES tb_user(id) ON DELETE CASCADE
);

-- Insert pre-composed data
INSERT INTO tv_user_profile (id, data)
SELECT
    u.id,
    u.data || jsonb_build_object(
        'posts', COALESCE(p.posts_data, '[]'::jsonb)
    ) AS data,
    NOW()
FROM v_user u
LEFT JOIN v_user_posts_composed p ON p.fk_user = u.pk_user
ON CONFLICT (id) DO UPDATE SET
    data = EXCLUDED.data,
    updated_at = NOW();
```

## Refresh Strategies

Choose based on your latency and overhead requirements.

### Option 1: Trigger-based (real-time)

**Best for:** GraphQL subscriptions, sub-minute latency requirements.

**Characteristics:**

- Fires after every INSERT/UPDATE/DELETE on source tables
- Latency: <100 ms per operation
- Overhead: per-row cost (scales with write volume)
- Control: fully automatic

**Implementation:**

```sql
CREATE OR REPLACE FUNCTION refresh_tv_user_profile_trigger()
RETURNS TRIGGER AS $$
BEGIN
    -- Recompute JSONB for affected user
    INSERT INTO tv_user_profile (id, data, updated_at)
    SELECT
        u.id,
        u.data || jsonb_build_object(
            'posts', COALESCE(p.posts_data, '[]'::jsonb)
        ) AS data,
        NOW()
    FROM v_user u
    LEFT JOIN v_user_posts_composed p ON p.fk_user = u.pk_user
    WHERE u.id = NEW.id OR (TG_OP = 'DELETE' AND u.id = OLD.id)
    ON CONFLICT (id) DO UPDATE SET
        data = EXCLUDED.data,
        updated_at = NOW();

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_refresh_tv_user_profile
    AFTER INSERT OR UPDATE OR DELETE ON tb_user
    FOR EACH ROW
    EXECUTE FUNCTION refresh_tv_user_profile_trigger();

-- Also trigger on related table changes
CREATE TRIGGER trg_refresh_tv_user_profile_on_post
    AFTER INSERT OR UPDATE OR DELETE ON tb_post
    FOR EACH ROW
    EXECUTE FUNCTION refresh_tv_user_profile_trigger();

CREATE TRIGGER trg_refresh_tv_user_profile_on_comment
    AFTER INSERT OR UPDATE OR DELETE ON tb_comment
    FOR EACH ROW
    EXECUTE FUNCTION refresh_tv_user_profile_trigger();
```

### Option 2: Scheduled batch (low overhead)

**Best for:** nightly dashboards, acceptable staleness (minutes to hours).

**Characteristics:**

- Batched refresh at fixed intervals
- Latency: minutes to hours
- Overhead: batch cost (no per-row overhead)
- Control: scheduled via pg_cron

**Implementation:**

```sql
-- Enable pg_cron extension
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- Schedule refresh every 5 minutes
SELECT cron.schedule(
    'refresh-tv-user-profile',
    '*/5 * * * *',  -- Every 5 minutes
    'SELECT refresh_tv_user_profile();'
);

-- Batch refresh function
CREATE OR REPLACE FUNCTION refresh_tv_user_profile()
RETURNS TABLE(rows_inserted BIGINT, rows_updated BIGINT) AS $$
DECLARE
    v_inserted BIGINT := 0;
    v_updated BIGINT := 0;
BEGIN
    -- Upsert all user profiles
    WITH upsert AS (
        INSERT INTO tv_user_profile (id, data, updated_at)
        SELECT
            u.id,
            u.data || jsonb_build_object(
                'posts', COALESCE(p.posts_data, '[]'::jsonb)
            ) AS data,
            NOW()
        FROM v_user u
        LEFT JOIN v_user_posts_composed p ON p.fk_user = u.pk_user
        ON CONFLICT (id) DO UPDATE SET
            data = EXCLUDED.data,
            updated_at = NOW()
        RETURNING (xmax = 0) AS inserted
    )
    SELECT COUNT(*) FILTER (WHERE inserted) INTO v_inserted FROM upsert;

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_updated := v_updated - v_inserted;

    RETURN QUERY SELECT v_inserted, v_updated;
END;
$$ LANGUAGE plpgsql;
```

### Option 3: Command-based explicit refresh

**Best for:** development, bulk data loads, manual ETL.

**Characteristics:**

- Manual refresh on demand
- Latency: on-demand
- Overhead: only when called
- Control: explicit invocation

**Implementation:**

```sql
CREATE OR REPLACE FUNCTION refresh_tv_user_profile(user_id_filter UUID DEFAULT NULL)
RETURNS TABLE(rows_inserted BIGINT, rows_updated BIGINT) AS $$
DECLARE
    v_inserted BIGINT := 0;
    v_updated BIGINT := 0;
BEGIN
    -- Upsert specified profiles (or all if no filter)
    WITH upsert AS (
        INSERT INTO tv_user_profile (id, data, updated_at)
        SELECT
            u.id,
            u.data || jsonb_build_object(
                'posts', COALESCE(p.posts_data, '[]'::jsonb)
            ) AS data,
            NOW()
        FROM v_user u
        LEFT JOIN v_user_posts_composed p ON p.fk_user = u.pk_user
        WHERE user_id_filter IS NULL OR u.id = user_id_filter
        ON CONFLICT (id) DO UPDATE SET
            data = EXCLUDED.data,
            updated_at = NOW()
        RETURNING (xmax = 0) AS inserted
    )
    SELECT COUNT(*) FILTER (WHERE inserted) INTO v_inserted FROM upsert;

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_updated := v_updated - v_inserted;

    RETURN QUERY SELECT v_inserted, v_updated;
END;
$$ LANGUAGE plpgsql;

-- Usage: Refresh specific user profile
SELECT * FROM refresh_tv_user_profile('550e8400-e29b-41d4-a716-446655440000'::UUID);

-- Usage: Refresh all profiles
SELECT * FROM refresh_tv_user_profile();
```

## Refresh Strategy Decision Matrix

| Write Volume | Read Volume | Data Complexity | Recommended |
|--------------|-------------|-----------------|-------------|
| Low (<100/min) | High | Complex (3+ JOINs) | Trigger-based |
| Low (<100/min) | High | Simple | Scheduled (15 min) |
| Medium (100–1K/min) | High | Complex | Trigger-based + batch cleanup |
| Medium (100–1K/min) | High | Simple | Scheduled (5–15 min) |
| High (>1K/min) | High | Any | Batch refresh only |

## Migration Guide

### Step 1: Create intermediate views

Create helper views for the composition logic (reusable across `tv_*` tables,
other reports, etc.):

```bash
psql -h localhost -U postgres fraiseql_dev < examples/sql/v_user_posts_composed.sql
psql -h localhost -U postgres fraiseql_dev < examples/sql/v_user_profile_composed.sql
```

### Step 2: Create the tv_* table

```bash
psql -h localhost -U postgres fraiseql_dev < examples/sql/tv_user_profile.sql
```

### Step 3: Initial population

```sql
-- Populate table from logical view
SELECT * FROM refresh_tv_user_profile();

-- Verify row counts
SELECT COUNT(*) AS tv_profile_count FROM tv_user_profile;
SELECT COUNT(*) AS v_user_count FROM v_user;

-- They should be equal
```

### Step 4: Point the GraphQL type at the table

Bind the `User` type to `tv_user_profile` instead of `v_user`. The `data` JSONB
column is read exactly as for a logical view, so only `sql_source` changes:

```python
import fraiseql
from fraiseql.types import ID

# Before: reads v_user (logical view, real-time composition)
@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    posts: list[Post]

# After: reads tv_user_profile (table-backed, pre-composed JSONB)
@fraiseql.type(sql_source="tv_user_profile", jsonb_column="data")
class User:
    id: ID
    name: str
    posts: list[Post]
```

Query resolvers do not change — they still call `db.find(...)` against the
configured source at runtime:

```python
@fraiseql.query
async def users(info) -> list[User]:
    db = info.context["db"]
    return await db.find("tv_user_profile")
```

### Step 5: Monitor performance

```sql
-- Check staleness (how old is the pre-computed data?)
SELECT MAX(updated_at) - NOW() AS staleness
FROM tv_user_profile;

-- Monitor refresh function performance
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM refresh_tv_user_profile();

-- Check data accuracy (profile count should match user count)
SELECT
    (SELECT COUNT(*) FROM tv_user_profile) AS profiles,
    (SELECT COUNT(*) FROM v_user) AS users,
    (SELECT COUNT(*) FROM tv_user_profile) = (SELECT COUNT(*) FROM v_user) AS counts_match;
```

## Limitations and Considerations

### Storage

- **Data duplication**: `tv_*` tables duplicate JSONB derived from `tb_*` tables.
- **Storage overhead**: typically 20–50% of source data size.
- **Index overhead**: GIN indexes add roughly 5–10% overhead.

### Refresh latency

- **Trigger-based**: <100 ms per operation (suitable for real-time GraphQL).
- **Scheduled batch**: minutes (suitable for dashboards).
- **Manual refresh**: on-demand (suitable for development/testing).

### Staleness risk

- **Trigger-based**: nearly real-time (slight delay during high-volume writes).
- **Scheduled batch**: by design (e.g., 5-minute staleness).
- **Manual refresh**: stale until explicitly refreshed.

### Schema drift risk

- **JSONB structure must match the GraphQL schema**: a mismatch causes validation errors.
- **Nested entity changes**: changes to related entities (Post, Comment) require trigger updates.
- **Mitigation**: unit and integration tests verify schema consistency.

### Cascading triggers

- Multiple triggers (on user, post, comment) can create overhead.
- Consider batch refresh when write volume is very high (>1K/min).
- Monitor trigger execution time.

## Best Practices

1. **Use intermediate composed views** for reusability.
2. **Test trigger logic** before deploying to high-volume write workloads.
3. **Monitor staleness** with the `updated_at` column.
4. **Use command-based refresh** for bulk-import verification.
5. **Schedule a batch refresh** as a fallback for trigger failures.
6. **Keep the `tv_*` JSONB shape synchronized** with the GraphQL type definition.
7. **Document the chosen refresh strategy** in architecture decisions.
8. **Use GIN indexes** on the `data` column for faster queries.
9. **Benchmark against the logical view** to confirm the performance gain.

## Troubleshooting

### Issue: tv_* table empty after trigger creation

**Cause:** the trigger only fires on future changes, not existing data.

**Solution:** run the initial population.

```sql
SELECT * FROM refresh_tv_user_profile();
```

### Issue: tv_* data stale after writes

**Cause:** the trigger is not firing or is delayed.

**Solution:** check trigger status.

```sql
SELECT * FROM information_schema.triggers
WHERE trigger_name LIKE 'trg_refresh_tv%';

-- Manually refresh
SELECT * FROM refresh_tv_user_profile();
```

### Issue: high CPU from cascading triggers

**Cause:** multiple triggers (on related tables) cause many refreshes.

**Solution:** switch to a batched refresh.

```sql
-- Drop per-row triggers
DROP TRIGGER IF EXISTS trg_refresh_tv_user_profile_on_post ON tb_post;
DROP TRIGGER IF EXISTS trg_refresh_tv_user_profile_on_comment ON tb_comment;

-- Schedule batch refresh instead
SELECT cron.schedule('refresh-tv-profile', '*/5 * * * *', 'SELECT refresh_tv_user_profile();');
```

### Issue: JSONB composition mismatch with the GraphQL schema

**Cause:** the DDL changed without updating the type binding.

**Solution:**

1. Update the PostgreSQL DDL (helper views + `tv_*` table).
2. Update the `@fraiseql.type` binding (`sql_source` / field set).
3. Re-populate the `tv_*` table.
4. Run integration tests to verify.

## Examples

See `examples/sql/` for complete DDL examples:

- `tv_user_profile.sql` — user profile with nested posts and comments
- `tv_order_summary.sql` — order with line items and customer details

## See Also

- [View Selection Guide](./view-selection-guide.md)
- [Schema Conventions](../../specs/schema-conventions.md)
- [Naming Patterns](../../reference/naming-patterns.md)
- [Database-Centric Architecture](../../foundation/03-database-centric-architecture.md)
</content>
</invoke>

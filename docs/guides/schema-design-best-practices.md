<!-- Skip to main content -->
---

title: Schema Design Best Practices for FraiseQL
description: Best practices and patterns for designing performant, maintainable FraiseQL schemas backed by PostgreSQL views and the data JSONB convention.
keywords: ["debugging", "implementation", "best-practices", "deployment", "schema", "tutorial"]
tags: ["documentation", "reference"]
---

# Schema Design Best Practices for FraiseQL

**Status:** ✅ Production Ready
**Audience:** Architects, Developers
**Reading Time:** 30-40 minutes
**Last Updated:** 2026-02-05

Best practices and patterns for designing performant, maintainable FraiseQL schemas backed by PostgreSQL.

---

## Overview

FraiseQL builds your GraphQL schema **in memory at application startup** and serves it
over FastAPI. There is no build step and no generated artifact: your Python types and
resolvers are registered with `create_fraiseql_app(...)`, and queries are translated to
SQL **at runtime** against your PostgreSQL views.

Effective schema design therefore centres on shaping the underlying PostgreSQL so that
each read maps cleanly to a single view. The recommended layout follows the CQRS split:

- **Write side** — normalized `tb_` tables are the source of truth.
- **Read side** — `v_` and `tv_` views expose a public `id` (UUID) and a `data` JSONB
  column built with `jsonb_build_object(...)`. GraphQL types read from these views.
- **Mutations** — `fn_` PostgreSQL functions perform validation and writes; `@fraiseql.mutation`
  resolvers call them via `db.execute_function(...)`.

**Key principle**: Design the PostgreSQL view that backs each type. FraiseQL selects only
the requested fields out of the view's `data` JSONB at runtime.

---

## 1. View Type Selection: `v_*` vs `tv_*`

### Decision Matrix

| View Type | Computation | Storage | Performance | Use Case | Indexing |
|---|---|---|---|---|---|
| **`v_*`** (Logical) | Per-query | None | Slower (computed each read) | Simple fields, real-time | Indexes on source tables |
| **`tv_*`** (Table-backed) | Refreshed by functions/triggers | Real table holding pre-composed JSONB | Fast (pre-computed) | Heavy nested reads, aggregations | Native indexes on the table |

A `v_` view is a plain `CREATE VIEW` that assembles `data` on every read. A `tv_` view is a
real table that stores the already-composed `data` JSONB, refreshed by your `fn_` functions or
triggers — ideal when the composition is expensive or deeply nested.

### When to Use Each

#### `v_*` (Logical Views) — For Simple, Real-Time Data

#### Use when

- Simple computed fields (concatenation, math)
- Data changes frequently
- Storage overhead not acceptable
- Real-time accuracy critical

#### Example

```sql
-- v_user_profile: logical view, composed on every read
CREATE VIEW v_user_profile AS
SELECT
    u.id,                                       -- public UUID, used for WHERE id = $1
    jsonb_build_object(
        'id', u.id,
        'firstName', u.first_name,
        'lastName', u.last_name,
        'fullName', concat_ws(' ', u.first_name, u.last_name),
        'age', extract(YEAR FROM age(u.birth_date))::int
    ) AS data
FROM tb_user u;
```

```python
import fraiseql
from fraiseql.types import ID


@fraiseql.type(sql_source="v_user_profile", jsonb_column="data")
class UserProfile:
    """Logical view - composed per query from tb_user."""

    id: ID
    first_name: str
    last_name: str
    full_name: str
    age: int
```

### Performance characteristics

- Query latency: 50-200ms (depends on the computation in the view)
- Storage: None (composed in the view)
- Scalability: Degrades linearly with row count

### When NOT to use

- ❌ Aggregating millions of rows (GROUP BY on a large table)
- ❌ Complex joins (>3 tables)
- ❌ Expensive calculations (trigonometry, encoding) on every read

#### `tv_*` (Table-Backed Views) — For Complex, Pre-Computed Data

#### Use when

- Complex aggregations (GROUP BY, JOINs)
- Computation expensive (complex math)
- Performance more important than freshness
- Refresh cycle acceptable (hourly/daily)

#### Example

```sql
-- tv_user_stats: a real table holding pre-composed JSONB
CREATE TABLE tv_user_stats (
    id          UUID PRIMARY KEY,
    data        JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

```python
import fraiseql
from datetime import datetime
from decimal import Decimal

from fraiseql.types import ID


@fraiseql.type(sql_source="tv_user_stats", jsonb_column="data")
class UserStats:
    """Table-backed view - pre-composed and refreshed daily."""

    id: ID
    post_count: int
    comment_count: int
    like_count: int
    avg_post_length: Decimal
    updated_at: datetime
```

### Refresh strategy

Populate the `tv_` table from your `tb_` tables in an `fn_` function (called on a schedule
or from triggers):

```sql
-- Refresh query (runs hourly via fn_refresh_user_stats / a scheduler)
INSERT INTO tv_user_stats (id, data, updated_at)
SELECT
    u.id,
    jsonb_build_object(
        'id', u.id,
        'postCount', count(DISTINCT p.pk_post),
        'commentCount', count(DISTINCT c.pk_comment),
        'likeCount', count(DISTINCT l.pk_like),
        'avgPostLength', avg(length(p.content))
    ) AS data,
    now()
FROM tb_user u
LEFT JOIN tb_post p     ON p.fk_user = u.pk_user
LEFT JOIN tb_comment c  ON c.fk_post = p.pk_post
LEFT JOIN tb_like l     ON l.fk_comment = c.pk_comment
GROUP BY u.id, u.pk_user
ON CONFLICT (id) DO UPDATE
    SET data = EXCLUDED.data, updated_at = EXCLUDED.updated_at;
```

### Performance characteristics

- Query latency: 1-10ms (indexed table lookup)
- Storage: ~10-20% of source data
- Scalability: Constant (O(1) lookup by `id`)
- Refresh lag: 1 hour (configurable)

### Refresh strategies

- **Full refresh**: Recompute the entire table daily
- **Incremental refresh**: Only update changed rows
- **Trigger refresh**: Update on each relevant mutation (more expensive, fresher)

For deeper guidance see the
[View Selection Guide](../architecture/database/view-selection-guide.md) and the
[`tv_` Table Pattern](../architecture/database/tv-table-pattern.md).

---

## 2. Naming Conventions

### Table & View Naming

FraiseQL follows the PostgreSQL CQRS conventions throughout:

| Prefix | What it is | Exposed in GraphQL? | Example |
|---|---|---|---|
| `tb_` | Normalized **write table** (source of truth) | No (write side) | `tb_user` |
| `v_` | Logical **read view** building a `data` JSONB | Yes (query source) | `v_user_profile` |
| `tv_` | **Table-backed view**: real table holding pre-composed JSONB | Yes (query source) | `tv_user_stats` |
| `fn_` | PostgreSQL **function** implementing a mutation's write logic | Called by mutations | `fn_create_user` |
| `pk_` | Internal `BIGINT` primary key (fast joins) | **NEVER** exposed | `pk_user` |
| `fk_` | Internal `BIGINT` foreign key | **NEVER** exposed | `fk_user` |
| `id` | Public `UUID` column | Yes (the GraphQL `id`) | `id` |
| `identifier` | Optional human-readable `TEXT UNIQUE` slug | Yes (optional) | `identifier` |

Every read view carries an `id` column (so FraiseQL can issue `WHERE id = $1`) **plus** a
`data` JSONB column. Never place `pk_*` columns inside `data`.

### Field Naming (inside the `data` JSONB)

#### Conventions

```python
import fraiseql
from datetime import datetime
from decimal import Decimal

from fraiseql.types import ID


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    # Identifiers: public UUIDs only (never pk_/fk_)
    id: ID                          # public UUID
    tenant_id: ID                   # tenant reference (UUID)
    organization_id: ID             # related entity reference

    # Timestamps: always with timezone (timestamptz in PostgreSQL)
    created_at: datetime            # When created
    updated_at: datetime            # Last update
    deleted_at: datetime | None     # Soft delete

    # Status: use enums
    status: UserStatus              # enum (active, inactive, banned)

    # Booleans: use "is_" or "has_" prefix
    is_active: bool                 # Current state
    has_verified_email: bool        # Capability

    # Counts: use "count" or "total_"
    post_count: int                 # Number of posts
    total_followers: int            # Total followers

    # Amounts: use Decimal for money
    account_balance: Decimal        # Never float!
    price_per_unit: Decimal

    # Relationships: use a noun, not a verb
    organization: Organization      # Not: organizationOf
    creator: User                   # Not: createdBy
```

The Python field names map to the keys you emit in `jsonb_build_object(...)`. FraiseQL
camelCases them for GraphQL by default.

### Enum Naming

**Pattern:** `{Entity}{Property}`

```python
import enum


class UserStatus(enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    BANNED = "banned"


class OrderStatus(enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
```

---

## 3. Field Type Selection

### Strings: When to Use What

FraiseQL ships a large set of PostgreSQL-backed scalars (see the
[Scalar Types Reference](../reference/scalars.md)). Common choices:

| Type | When to Use | Example | Notes |
|---|---|---|---|
| `str` | Short text (< 255 chars) | username, name | ✅ Most fields |
| `str` | Long text (> 255 chars) | description, bio, content | ✅ Backed by `TEXT` in PostgreSQL |
| `EmailAddress` | Email addresses | contact@example.com | ✅ Validated scalar |
| `UUID` | Unique identifiers | 550e8400-e29b-41d4 | ✅ Recommended for IDs |
| `Slug` | URL-safe names | "my-product", "my-post" | ✅ URLs |
| `URL` | Web addresses | https://example.com | ✅ Links |

### Anti-pattern

```python
from fraiseql.types import ID, UUID

# ❌ Wrong: plain string ID
id: str = "abc123"

# ✅ Correct: ID / UUID scalar for identifiers
id: ID
```

### Numbers: Precision Matters

| Type | When to Use | Example | Precision |
|---|---|---|---|
| `int` | Integers (counts, IDs) | user_count, age | 64-bit (`BIGINT`) |
| `float` | Scientific/non-financial | temperature, ratio | IEEE 754 (~7 digits) |
| `Decimal` | Money, accounting | price, balance | Arbitrary (use this!) |

### Anti-pattern

```python
from decimal import Decimal

# ❌ Wrong: float for money (precision loss!)
account_balance: float = 99.99

# ✅ Correct: Decimal for money (PostgreSQL NUMERIC)
account_balance: Decimal = Decimal("99.99")
```

### Dates & Times

| Type | When to Use | Example | Timezone |
|---|---|---|---|
| `Date` | Date only (no time) | 2026-02-05 | None |
| `DateTime` | Date + time | 2026-02-05T10:30:00Z | Always UTC (`timestamptz`) |
| `Time` | Time only (no date) | 10:30:00 | None |

### Best practice

```python
import fraiseql
from datetime import date, datetime, time

from fraiseql.types import ID


@fraiseql.type(sql_source="v_event", jsonb_column="data")
class Event:
    id: ID
    created_at: datetime  # Always use a timestamptz for created/updated
    event_date: date      # Use Date if time is not needed
    event_time: time      # Rare; prefer DateTime instead
```

---

## 4. Relationship Design

Relationships are composed inside the view's `data` JSONB using `jsonb_build_object` and
`jsonb_agg`. FraiseQL reads whatever the view returns.

### One-to-Many Relationships

**Pattern:** Embed the children as a JSONB array in the parent view

```python
import fraiseql

from fraiseql.types import ID


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    posts: list[Post]  # One-to-many: User has many Posts


@fraiseql.type(sql_source="v_post", jsonb_column="data")
class Post:
    id: ID
    user_id: ID  # the related user's public UUID
    content: str
```

```sql
-- v_user composes its posts inline via jsonb_agg
CREATE VIEW v_user AS
SELECT
    u.id,
    jsonb_build_object(
        'id', u.id,
        'name', u.name,
        'posts', coalesce(
            jsonb_agg(
                jsonb_build_object('id', p.id, 'content', p.content)
            ) FILTER (WHERE p.pk_post IS NOT NULL),
            '[]'::jsonb
        )
    ) AS data
FROM tb_user u
LEFT JOIN tb_post p ON p.fk_user = u.pk_user
GROUP BY u.id, u.name;
```

### Performance consideration

- Composing children inline in the view avoids N+1 round trips entirely.
- Use a `tv_` table if the composition is expensive and freshness can lag.
- For large or paginated child sets, expose a dedicated `@fraiseql.query` for the children
  instead of embedding the whole list, or use `@fraiseql.dataloader_field` to batch a
  separately resolved relationship.

### Many-to-Many Relationships

**Pattern:** Join table on the write side, composed into JSONB on the read side

```python
import fraiseql

from fraiseql.types import ID


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    groups: list[Group]  # Many-to-many via join table


@fraiseql.type(sql_source="v_group", jsonb_column="data")
class Group:
    id: ID
    name: str
    members: list[User]
```

```sql
-- Write-side join table (never exposed directly in GraphQL)
-- CREATE TABLE tb_user_group (
--     pk_user_group BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
--     fk_user       BIGINT NOT NULL REFERENCES tb_user(pk_user),
--     fk_group      BIGINT NOT NULL REFERENCES tb_group(pk_group),
--     joined_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
--     UNIQUE (fk_user, fk_group)
-- );

-- Read-side: v_user (or a tv_user table) composes the groups array
CREATE VIEW v_user AS
SELECT
    u.id,
    jsonb_build_object(
        'id', u.id,
        'name', u.name,
        'groups', coalesce(
            jsonb_agg(
                jsonb_build_object(
                    'id', g.id,
                    'name', g.name,
                    'joinedAt', ug.joined_at
                )
            ) FILTER (WHERE g.pk_group IS NOT NULL),
            '[]'::jsonb
        )
    ) AS data
FROM tb_user u
LEFT JOIN tb_user_group ug ON ug.fk_user = u.pk_user
LEFT JOIN tb_group g       ON g.pk_group = ug.fk_group
GROUP BY u.id, u.name;
```

### Self-Referential Relationships

**Pattern:** Foreign key to the same table

```python
import fraiseql

from fraiseql.types import ID


@fraiseql.type(sql_source="v_category", jsonb_column="data")
class Category:
    id: ID
    name: str
    parent_id: ID | None       # Can be null (root category)
    children: list[Category]   # Subcategories
```

**Query limitation:** Prevent runaway recursion by bounding nesting depth in your view SQL
(e.g. a recursive CTE with a `WHERE depth < N` guard), and cap incoming GraphQL query
complexity at the app level:

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[Category],
    max_query_depth=10,  # Prevent Category -> Category -> Category...
)
```

---

## 5. Index Design for Performance

### When to Add Indexes

#### ADD indexes for

- ✅ All foreign keys (`fk_user`, `fk_org`)
- ✅ The public `id` UUID column (`UNIQUE`, used for `WHERE id = $1`)
- ✅ Fields in WHERE clauses (filters)
- ✅ Frequently sorted fields (ORDER BY)
- ✅ Unique fields (a `UNIQUE` constraint is an index)
- ✅ High cardinality fields (many distinct values)

### AVOID indexing

- ❌ Very low cardinality fields (boolean, status with 3 values)
- ❌ Fields that are never filtered
- ❌ Non-selective indexes (>50% of rows match)
- ❌ Oversized TEXT fields (use full-text search instead)

### Index Strategies by Query Pattern

#### Pattern: Simple WHERE clause

```sql
-- Query: users WHERE created_at >= '2026-01-01'
CREATE INDEX idx_tb_user_created_at ON tb_user(created_at);
```

### Pattern: Composite filters

```sql
-- Query: users WHERE tenant_id = ? AND is_active = true
CREATE INDEX idx_tb_user_tenant_active ON tb_user(tenant_id, is_active);
```

### Pattern: Foreign key joins

```sql
-- Query: posts WHERE fk_user = ?
CREATE INDEX idx_tb_post_fk_user ON tb_post(fk_user);
```

### Pattern: Full-text / fuzzy search

```sql
-- Query: products WHERE name ILIKE '%search%'  (requires pg_trgm)
CREATE INDEX idx_tb_product_name_trgm
    ON tb_product USING GIN (name gin_trgm_ops);
```

### Pattern: JSONB lookups inside data

```sql
-- Filtering on keys inside the data JSONB of a view-backing table
CREATE INDEX idx_tv_user_stats_data ON tv_user_stats USING GIN (data jsonb_path_ops);
```

---

## 6. Computed Fields: When & How

Computed fields are produced **in the PostgreSQL view**, inside the `data` JSONB — not via
a decorator parameter. The Python type simply declares the field; the view supplies the
value.

#### Pattern 1: Simple concatenation (use `v_*`)

```python
import fraiseql

from fraiseql.types import ID


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    first_name: str
    last_name: str
    full_name: str   # composed in the view
```

```sql
-- inside v_user's jsonb_build_object:
--   'fullName', concat_ws(' ', u.first_name, u.last_name)
```

### Pattern 2: Complex aggregation (use `tv_*`)

```python
import fraiseql

from fraiseql.types import ID


@fraiseql.type(sql_source="tv_user_stats", jsonb_column="data")
class User:
    id: ID
    post_count: int        # pre-computed, refreshed hourly
    comment_count: int
    total_engagement: int  # = post_count + comment_count, computed at refresh time
```

#### Pattern 3: Conditional logic (use `CASE` in the view)

```sql
-- inside the view's jsonb_build_object:
'statusLabel', CASE o.status
    WHEN 'pending'   THEN 'Waiting for payment'
    WHEN 'confirmed' THEN 'Order confirmed'
    WHEN 'shipped'   THEN 'In transit'
    WHEN 'delivered' THEN 'Delivered'
END
```

```python
import fraiseql

from fraiseql.types import ID


@fraiseql.type(sql_source="v_order", jsonb_column="data")
class Order:
    id: ID
    status: OrderStatus
    status_label: str  # supplied by the CASE expression in v_order
```

---

## 7. Authorization & Security in Schema

FraiseQL enforces access control in two complementary layers: PostgreSQL **Row-Level
Security (RLS)** for tenant/row isolation, and an application-level **`Authorizer`** for
operation/field decisions.

### Field-Level Authorization

Mark sensitive fields with `authorize_fields` on the type. Authorization decisions are made
at runtime by the `Authorizer` wired into your app.

```python
import fraiseql
from decimal import Decimal

from fraiseql.types import ID


@fraiseql.type(
    sql_source="v_user",
    jsonb_column="data",
    authorize_fields=["email", "salary"],
)
class User:
    id: ID
    name: str
    email: str
    salary: Decimal
```

See [RBAC & Field Authorization](../enterprise/rbac.md) for the directive/middleware setup.

### Row-Level Security (Multi-Tenancy)

For multi-tenant isolation, keep a `tenant_id` column on the write tables and enforce it with
a PostgreSQL RLS policy. FraiseQL's repository sets the session GUC from the request context
(`info.context["tenant_id"]`) by issuing `SET LOCAL app.tenant_id = …` per transaction, so the
policy sees the current tenant automatically.

```sql
ALTER TABLE tb_post ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON tb_post
    USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

You can also constrain reads explicitly with `mandatory_filters`:

```python
@fraiseql.query
async def posts(info) -> list[Post]:
    db = info.context["db"]
    return await db.find(
        "v_post",
        mandatory_filters={"tenant_id": info.context["tenant_id"]},
    )
```

---

## 8. Backward Compatibility & Schema Evolution

### Adding Fields (✅ Safe)

```python
import fraiseql

from fraiseql.types import ID


# Old type
@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str


# New type (existing clients still work!)
@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: str  # ← New field; add the key to v_user's data JSONB
```

Remember to also emit the new key in the view's `jsonb_build_object(...)`.

### Removing Fields (❌ Breaking)

```python
import fraiseql

from fraiseql.types import ID


# Old type
@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    legacy_field: str


# New type (breaks clients still selecting legacy_field!)
@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
```

### Safe alternative: Deprecate first

Use the GraphQL `@deprecated` directive via the field description so clients see the warning
in introspection before you remove the field:

```python
import fraiseql

from fraiseql.fields import fraise_field
from fraiseql.types import ID


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    legacy_field: str = fraise_field(
        description="Deprecated: use 'name' instead. Removal scheduled for a later release.",
    )
```

### Renaming Fields (❌ Breaking)

#### Workaround: keep both names during a transition window

Expose the new key alongside the old one in the view's `data` JSONB for a release or two, then
drop the old key once clients have migrated.

```python
import fraiseql

from fraiseql.types import ID


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str       # legacy key, kept temporarily
    full_name: str  # new key (both emitted by v_user during migration)
```

---

## 9. Testing Schema Performance

### Load Testing View Performance

```sql
-- Generate test data
INSERT INTO tb_user (id, name)
SELECT gen_random_uuid(), 'user_' || g
FROM generate_series(1, 1000000) AS g;

-- Time the logical view query
EXPLAIN ANALYZE SELECT * FROM v_user_profile LIMIT 100;

-- If > 100ms, switch to a table-backed view (tv_user_profile)
```

### Index Effectiveness

```sql
-- Check if an index is used
EXPLAIN SELECT * FROM tb_user WHERE created_at >= '2026-01-01';
-- Should show "Index Scan", not "Seq Scan"

-- Check index size
SELECT pg_size_pretty(pg_relation_size('idx_tb_user_created_at'));
```

---

## 10. Monitoring Schema Health

### Query for Unused Indexes

```sql
-- PostgreSQL: find indexes that are never scanned
SELECT schemaname, relname AS tablename, indexrelname AS indexname
FROM pg_stat_user_indexes
WHERE idx_scan = 0
ORDER BY relname, indexrelname;
```

### Query for Slow Queries

```sql
-- Requires the pg_stat_statements extension
SELECT query, calls, mean_exec_time
FROM pg_stat_statements
WHERE mean_exec_time > 100  -- Queries averaging > 100ms
ORDER BY mean_exec_time DESC;

-- Use the slow queries to spot missing indexes
```

---

## 11. Schema Documentation

### Document Each Type

```python
import fraiseql
from datetime import datetime

from fraiseql.types import ID


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    """
    User account and profile information (read from v_user).

    Fields:
    - id: Unique user identifier (public UUID)
    - email: User's email (unique, case-insensitive)
    - name: User's display name
    - created_at: Account creation timestamp
    - posts: User's published posts (1-to-many, composed inline)

    Source:
    - v_user composes data from tb_user (+ tb_post for the posts array)

    Indexes (on tb_user):
    - id (unique)
    - created_at (for pagination)

    Row-Level Security:
    - RLS on tb_user / tb_post restricts rows to the current tenant
    - Sensitive fields gated via authorize_fields + Authorizer

    Related:
    - Post (1-to-many relationship)
    - Organization (many-to-one)
    """

    id: ID
    email: str
    name: str
    created_at: datetime
    posts: list[Post]
```

### Document View Materialization

```python
import fraiseql

from fraiseql.types import ID


@fraiseql.type(sql_source="tv_user_stats", jsonb_column="data")
class UserStats:
    """
    User engagement statistics (table-backed, refreshed daily).

    Refresh:
    - Cadence: daily at 02:00 UTC (fn_refresh_user_stats)
    - Source: aggregate from tb_post, tb_comment, tb_like
    - Latency: ~1-24 hours (yesterday's data)
    - Storage: ~5GB for 10M users

    Use cases:
    - User rankings / leaderboards
    - Engagement trends
    - NOT for real-time stats

    updated_at:
    - Indicates when the row was last refreshed
    - Use for cache invalidation
    """

    id: ID
```

---

## See Also

### Related Guides

- **[Common Gotchas](./common-gotchas.md)** — Schema pitfalls to avoid
- **[Performance Tuning Runbook](../operations/performance-tuning-runbook.md)** — Optimizing schema performance
- **[View Selection Guide](../architecture/database/view-selection-guide.md)** — Choosing `v_` vs `tv_`
- **[Common Patterns](./patterns.md)** — Pattern implementations using best practices

### Architecture & Specifications

- **[`tv_` Table Pattern](../architecture/database/tv-table-pattern.md)** — Table-backed read models
- **[Scalar Types Reference](../reference/scalars.md)** — All available scalar types
- **[Specs: Schema Conventions](../specs/schema-conventions.md)** — Naming conventions

### Security

- **[RBAC & Field Authorization](../enterprise/rbac.md)** — Field-level access control
- **[Production Security Checklist](./production-security-checklist.md)** — Security hardening

---

**Last Updated:** 2026-02-05

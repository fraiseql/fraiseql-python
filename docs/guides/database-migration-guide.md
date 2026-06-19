---
title: Database Schema Migration Guide
description: Step-by-step guide for evolving a FraiseQL PostgreSQL schema with versioned DDL migrations.
keywords: ["migrations", "ddl", "alembic", "schema", "postgresql", "tutorial"]
tags: ["documentation", "reference"]
---

# Database Schema Migration Guide

**Status:** ✅ Production Ready
**Audience:** Developers, Database Administrators
**Reading Time:** 25-30 minutes

Step-by-step guide for evolving a FraiseQL PostgreSQL schema with versioned DDL migrations — adding and changing the `tb_` write tables, `v_`/`tv_` read views, and `fn_` functions that back your GraphQL API.

---

## Overview

FraiseQL builds its GraphQL schema **at application startup** from your Python decorators, and serves it against PostgreSQL. There is no compile step and no schema artifact: when you change your PostgreSQL objects and your decorators, you simply restart the app.

A "database migration" in FraiseQL therefore means **evolving your PostgreSQL schema** — DDL changes to your tables, views, and functions — applied with ordinary migration tooling such as [Alembic](https://alembic.sqlalchemy.org/) or plain numbered `.sql` files run by `psql`.

This guide covers two common situations:

- **Evolving an existing FraiseQL schema** — adding columns, new entities, or new views as the application grows.
- **Adopting FraiseQL on an existing PostgreSQL database** — wrapping pre-existing tables in the `v_`/`tv_` read-view layer that FraiseQL queries.

**Key principle:** A schema migration is a **data structure change**, not a bulk data migration. Your existing rows stay in place; you restructure how FraiseQL reads and writes them through views and functions.

> FraiseQL v1 is **PostgreSQL only**. All examples use standard PostgreSQL DDL.

### The FraiseQL object trinity

Every entity is represented by three kinds of PostgreSQL object. Migrations almost always touch one or more of them:

| Prefix | What it is | Exposed in GraphQL? |
|--------|-----------|---------------------|
| `tb_`  | normalized **write table** (source of truth) | no (write side) |
| `v_`   | logical **read view** building a `data` JSONB column | yes (query source) |
| `tv_`  | **table-backed projection view** holding pre-composed JSONB, refreshed by functions/triggers | yes (query source) |
| `fn_`  | PostgreSQL **function** implementing a mutation's write logic | called by mutations |

Identifier columns follow the trinity pattern: `pk_<entity>` (internal `BIGINT`, hidden), `id` (public `UUID`, stable), and an optional `identifier` (`TEXT UNIQUE` slug). GraphQL exposes `id` (and optionally `identifier`) but **never** `pk_`/`fk_`.

---

## Pre-Migration Planning

### 1. Assess the current schema

**Answer these questions:**

- [ ] Total tables: < 50 / 50-200 / 200-1000 / > 1000?
- [ ] Database size: < 1GB / 1-10GB / 10-100GB / > 100GB?
- [ ] Peak QPS (queries per second): < 100 / 100-1000 / > 1000?
- [ ] Uptime requirement: Best-effort / 99% / 99.9% / 99.99%?
- [ ] Are there existing tables to wrap in `v_`/`tv_` views, or is this a greenfield schema?
- [ ] Which read paths are hot enough to need `tv_` projection views?

### 2. Create a migration plan

**Template:**

```markdown
## Migration Plan: [Project Name]

### Timeline
- Phase 1 (Week 1): Schema analysis and naming-convention mapping
- Phase 2 (Week 2): Write tables, views, and functions (DDL migrations)
- Phase 3 (Week 3): Wire up FraiseQL types/queries/mutations and test
- Phase 4 (Week 4): Staging deployment and verification
- Phase 5 (Week 5): Production rollout

### Rollback Plan
- Every DDL migration ships with a matching down-migration
- Take a backup before applying migrations in production
- Keep new views additive where possible (drop old objects only after cutover)

### Team
- Schema Designer: [Name]
- DevOps Lead: [Name]
- QA Lead: [Name]
- Database Admin: [Name]
```

### 3. Audit the current schema

**Generate a schema export so you can diff before and after:**

```bash
# Dump the schema only (no data) for review and version control
pg_dump --schema-only "$DATABASE_URL" > schema.sql
```

---

## Phase 1: Analyze the Existing Schema

### Step 1.1: Document tables & views

**Create an inventory:**

```sql
-- List all base tables
SELECT tablename FROM pg_tables WHERE schemaname = 'public';

-- List all views
SELECT viewname FROM pg_views WHERE schemaname = 'public';
```

**Output format:**

```text
TABLE_NAME | COLUMNS | ROWS | SIZE  | INDEXES | PK | NOTES
tb_user    | 12      | 2M   | 500MB | 3       | id | Active users
tb_post    | 8       | 10M  | 2GB   | 4       | id | Needs tv_* projection
```

### Step 1.2: Identify access patterns

**Analyze queries with `pg_stat_statements`:**

```sql
-- Find most frequent queries
SELECT query, calls FROM pg_stat_statements
ORDER BY calls DESC LIMIT 20;

-- Find slow queries
SELECT query, mean_exec_time FROM pg_stat_statements
WHERE mean_exec_time > 100
ORDER BY mean_exec_time DESC LIMIT 20;
```

**Use this to decide:**

- Which columns inside your views need indexes (often on the underlying `tb_` tables).
- Which read views need a `tv_` projection (pre-composed JSONB).
- Which queries need restructuring in the view SQL.

### Step 1.3: Map relationships

**Sketch the relationships so your `data` JSONB views embed the right nested objects:**

```text
tb_user (pk_user, id, name, email)
  ├─ 1:M → tb_post (pk_post, id, fk_user, content)
  │          ├─ 1:M → tb_comment (pk_comment, id, fk_post, text)
  │          └─ M:M → tb_tag (join: tb_post_tag)
  ├─ M:M → tb_group (join: tb_user_group)
  └─ M:1 ← tb_organization (fk_organization)

tb_organization (pk_organization, id, name)
  ├─ 1:M → tb_user
  └─ 1:M → tb_team
```

---

## Phase 2: Build the PostgreSQL Schema

This phase is a sequence of DDL migrations. Keep each step in its own numbered migration file (e.g. `0001_create_user.sql`) or Alembic revision so it is reviewable and reversible.

### Step 2.1: Write tables (`tb_`)

The write tables are the source of truth. They use the identifier trinity: a hidden `pk_` BIGINT, a public `id` UUID, and `fk_` foreign keys (never exposed).

```sql
CREATE TABLE tb_organization (
    pk_organization BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id              UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    name            TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tb_user (
    pk_user         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id              UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    fk_organization BIGINT NOT NULL REFERENCES tb_organization (pk_organization),
    name            TEXT NOT NULL,
    email           TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tb_post (
    pk_post    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id         UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    fk_user    BIGINT NOT NULL REFERENCES tb_user (pk_user),
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Step 2.2: Read views (`v_`)

A read view always exposes the public `id` column **plus** a `data` JSONB column built with `jsonb_build_object(...)`. Embed relationships directly in the JSONB so a single read returns the nested shape your GraphQL type needs. Never put `pk_`/`fk_` inside `data`.

```sql
CREATE VIEW v_user AS
SELECT
    u.id,                          -- WHERE id = $1 lookups
    jsonb_build_object(
        'id', u.id,
        'name', u.name,
        'email', u.email,
        'createdAt', u.created_at,
        'organization', jsonb_build_object(
            'id', o.id,
            'name', o.name
        ),
        'posts', COALESCE(
            (SELECT jsonb_agg(jsonb_build_object('id', p.id, 'content', p.content))
             FROM tb_post p
             WHERE p.fk_user = u.pk_user),
            '[]'::jsonb
        )
    ) AS data
FROM tb_user u
JOIN tb_organization o ON o.pk_organization = u.fk_organization;
```

The matching FraiseQL types and queries point at the view via `sql_source`:

```python
import fraiseql
from fraiseql.types import ID, DateTime
from fraiseql.fastapi import create_fraiseql_app


@fraiseql.type(sql_source="v_organization", jsonb_column="data")
class Organization:
    id: ID
    name: str
    created_at: DateTime


@fraiseql.type(sql_source="v_post", jsonb_column="data")
class Post:
    id: ID
    content: str
    created_at: DateTime


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: str
    created_at: DateTime
    organization: Organization      # embedded by the view's JSONB
    posts: list[Post]               # embedded by the view's JSONB


@fraiseql.query
async def users(info) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user")


@fraiseql.query
async def user(info, id: ID) -> User | None:
    db = info.context["db"]
    return await db.find_one("v_user", id=id)
```

### Step 2.3: Multi-tenancy with Row-Level Security

For tenant isolation, add a tenant column to your write tables and enforce it with PostgreSQL **Row-Level Security (RLS)**. FraiseQL's CQRS repository sets the session GUCs from the request context — when `info.context` carries `tenant_id`, it issues `SET LOCAL app.tenant_id = …` per transaction, so your RLS policies see the current tenant.

```sql
-- Add the tenant key to write tables
ALTER TABLE tb_post ADD COLUMN fk_organization BIGINT
    REFERENCES tb_organization (pk_organization);

-- Enable RLS and a policy that reads the session GUC FraiseQL sets
ALTER TABLE tb_post ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON tb_post
    USING (fk_organization = (
        SELECT pk_organization FROM tb_organization
        WHERE id = current_setting('app.tenant_id')::uuid
    ));
```

You can additionally pin a filter on the read side:

```python
@fraiseql.query
async def posts(info) -> list[Post]:
    db = info.context["db"]
    # Belt-and-braces: enforce the tenant on the query as well as via RLS
    return await db.find("v_post", mandatory_filters={"organization_id": info.context["tenant_id"]})
```

### Step 2.4: Field authorization

FraiseQL enforces operation authorization through an `Authorizer`, wired either globally on the app or per query/subscription:

```python
from fraiseql.security import Authorizer


class OrgAuthorizer(Authorizer):
    async def authorize(self, info, operation):
        # Reject anonymous access, check roles from info.context, etc.
        if not info.context.get("user_id"):
            raise PermissionError("authentication required")


@fraiseql.query(authorizer=OrgAuthorizer())
async def users(info) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user")
```

For row- and field-level access control, rely on PostgreSQL RLS policies (Step 2.3) and on what the view exposes: simply omit sensitive columns (for example, never select `password_hash` into `data`).

### Step 2.5: Mutations via `fn_` functions

All write business logic lives in PostgreSQL functions. The function validates, writes, and returns JSONB indicating success or failure.

```sql
CREATE FUNCTION fn_create_user(input_name TEXT, input_email TEXT, input_org UUID)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
    new_user tb_user;
BEGIN
    INSERT INTO tb_user (fk_organization, name, email)
    SELECT o.pk_organization, input_name, input_email
    FROM tb_organization o WHERE o.id = input_org
    RETURNING * INTO new_user;

    RETURN jsonb_build_object(
        'success', true,
        'user', jsonb_build_object('id', new_user.id, 'name', new_user.name, 'email', new_user.email)
    );
EXCEPTION WHEN unique_violation THEN
    RETURN jsonb_build_object('success', false, 'message', 'email already exists');
END;
$$;
```

```python
@fraiseql.input
class CreateUserInput:
    name: str
    email: str
    organization_id: ID


@fraiseql.success
class CreateUserSuccess:
    user: User


@fraiseql.error
class CreateUserError:
    message: str
    code: str = "VALIDATION_ERROR"


@fraiseql.mutation
async def create_user(info, input: CreateUserInput) -> CreateUserSuccess | CreateUserError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_create_user",
        {"name": input.name, "email": input.email, "org": input.organization_id},
    )
    if not result.get("success"):
        return CreateUserError(message=result.get("message", "failed"))
    return CreateUserSuccess(user=User(**result["user"]))
```

### Step 2.6: Projection views (`tv_`) for hot reads

When a logical `v_` view is too expensive for a hot read path, replace it with a `tv_` projection: a real table holding the pre-composed JSONB, refreshed by functions or triggers.

```sql
-- A table-backed projection: refreshed, not recomputed on every read
CREATE TABLE tv_user_stats (
    id              UUID PRIMARY KEY,
    data            JSONB NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- (Re)build the projection from the base tables
INSERT INTO tv_user_stats (id, data)
SELECT
    u.id,
    jsonb_build_object(
        'id', u.id,
        'postCount', COUNT(DISTINCT p.pk_post),
        'commentCount', COUNT(DISTINCT c.pk_comment),
        'avgLikesPerPost', COALESCE(AVG(l.like_count), 0)
    )
FROM tb_user u
LEFT JOIN tb_post p ON p.fk_user = u.pk_user
LEFT JOIN tb_comment c ON c.fk_post = p.pk_post
LEFT JOIN (
    SELECT fk_post, COUNT(*) AS like_count
    FROM tb_like
    GROUP BY fk_post
) l ON l.fk_post = p.pk_post
GROUP BY u.id
ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = now();
```

FraiseQL queries a `tv_` view exactly like a `v_` view — only the `sql_source` name differs:

```python
@fraiseql.type(sql_source="tv_user_stats", jsonb_column="data")
class UserStats:
    id: ID
    post_count: int
    comment_count: int
```

---

## Phase 3: Integration Testing

### Step 3.1: Set up a staging environment

**Clone the production database:**

```bash
# Dump production and restore into staging
pg_dump "$PROD_DATABASE_URL" | psql "$STAGING_DATABASE_URL"
```

### Step 3.2: Apply the migrations

Run your migration tool against staging. With Alembic:

```bash
DATABASE_URL="$STAGING_DATABASE_URL" alembic upgrade head
```

Or with plain numbered SQL files:

```bash
for f in migrations/*.sql; do
  psql "$STAGING_DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
done
```

### Step 3.3: Start the FraiseQL app

The schema is assembled in memory at startup — just point the FastAPI app at the staging database and run it:

```python
# app.py
app = create_fraiseql_app(
    database_url="postgresql://localhost/staging_db",
    types=[Organization, User, Post, UserStats],
    queries=[users, user, posts],
    mutations=[create_user],
    production=False,   # enables the GraphQL playground
)
```

```bash
# Run the FastAPI app
uvicorn app:app --port 8000

# Smoke-test the GraphQL endpoint
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ users { id name } }"}'
```

### Step 3.4: Query verification

**Confirm the migrated views return the shape you expect:**

```graphql
query {
  users {
    id
    name
    email
    posts {
      id
      content
      createdAt
    }
  }
}
```

**Test harness:**

```python
# test_migration.py
import httpx

NEW_SERVER = "http://localhost:8000/graphql"

queries = [
    "{ users { id name } }",
    "{ posts(first: 100) { id content user { name } } }",
    "{ organizations { id users { id posts { id } } } }",
]

for q in queries:
    resp = httpx.post(NEW_SERVER, json={"query": q})
    body = resp.json()
    assert "errors" not in body, f"Query failed: {q} -> {body['errors']}"

print("✅ All queries returned data")
```

### Step 3.5: Performance baseline

**Measure query performance against staging before cutover:**

```bash
# Run a load test against the staging app
wrk -t4 -c100 -d60s \
  -s load_test.lua \
  http://localhost:8000/graphql

# Record: latency (P50, P95, P99), throughput, errors
```

If P95 latency is too high on a hot path, convert the relevant `v_` view to a `tv_` projection (Step 2.6) and re-measure.

---

## Phase 4: Production Rollout

### Step 4.1: Apply migrations to production

DDL migrations are the cutover. Back up first, then apply the same reviewed migrations you ran on staging:

```bash
# Back up before applying
pg_dump "$PROD_DATABASE_URL" > backup_pre_migration.dump

# Apply migrations (Alembic)
DATABASE_URL="$PROD_DATABASE_URL" alembic upgrade head
```

Keep migrations **additive** where possible: create the new `tb_`/`v_`/`tv_`/`fn_` objects alongside the old ones, deploy the app, verify, and only drop the old objects in a later migration once you are confident.

### Step 4.2: Deploy the app

Roll out the FraiseQL FastAPI app (which now references the new objects). Because the schema is built at startup, a rolling restart picks up the new schema with no compile step.

**Monitor after deploy:**

- [ ] Error rate < 0.1%
- [ ] Response latency acceptable
- [ ] No data inconsistencies
- [ ] No unauthorized access

### Step 4.3: Decommission old objects

Once the new schema is stable, ship a follow-up migration that drops the now-unused views/columns/functions.

```sql
-- Example follow-up migration once cutover is confirmed
DROP VIEW IF EXISTS v_user_legacy;
```

**Post-cutover monitoring:**

- [ ] Error rate < 0.1%
- [ ] Latency acceptable
- [ ] All metrics normal
- [ ] Rollback plan ready if needed

---

## Phase 5: Production Validation

### Step 5.1: Health checks

```bash
# Check app health
curl http://localhost:8000/health

# Check database connectivity through GraphQL
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ users { id } }"}'
```

### Step 5.2: Monitoring setup

**Set up observability around the FastAPI app and PostgreSQL:**

```yaml
# Prometheus metrics
fraiseql_queries_total{method="query", status="success"}
fraiseql_query_duration_seconds{method="query", quantile="0.95"}
fraiseql_errors_total{error_code="E_*"}
fraiseql_db_connections{state="active"}

# Alert thresholds
error_rate > 1%
response_latency_p95 > 500ms
db_connection_exhaustion > 80%
```

### Step 5.3: Rollback plan

**If issues arise after a migration:**

1. **Immediate:** Roll the app back to the previous deploy.
2. **Down-migration:** Apply the matching down-migration (or restore from `backup_pre_migration.dump` if the change was destructive).
3. **Investigate:** Reproduce and fix the issue in staging.
4. **Re-test:** Validate the corrected migration on staging.
5. **Retry:** Re-run the rollout.

```bash
# Revert the last Alembic migration
DATABASE_URL="$PROD_DATABASE_URL" alembic downgrade -1
```

---

## Validation Checklist

### Pre-Migration

- [ ] Schema audit complete
- [ ] Relationship diagram documented
- [ ] Access patterns identified
- [ ] Migration plan approved by team
- [ ] Rollback (down-migration) plan documented

### Schema Development

- [ ] All entities have `tb_` write tables with the `pk_`/`id`/`identifier` trinity
- [ ] All read views (`v_`/`tv_`) expose an `id` column and a `data` JSONB
- [ ] Relationships embedded in the view JSONB
- [ ] Mutations implemented as `fn_` functions
- [ ] Row-Level Security policies configured for multi-tenant tables
- [ ] Authorization wired via `Authorizer`
- [ ] Indexes identified and created on the underlying tables

### Testing

- [ ] Staging database cloned from production
- [ ] Migrations apply cleanly on staging
- [ ] Query verification passes
- [ ] Performance baseline established
- [ ] Load testing passed
- [ ] Authorization tested

### Cutover

- [ ] Backup taken before applying production migrations
- [ ] Migrations kept additive where possible
- [ ] Monitoring alerts set up
- [ ] On-call team briefed
- [ ] Down-migrations tested
- [ ] Stakeholders notified

### Post-Migration

- [ ] Error rate < 0.1%
- [ ] Latency within acceptable range
- [ ] All health checks passing
- [ ] No customer-facing issues reported
- [ ] Old objects decommissioned in a follow-up migration
- [ ] Documentation updated

---

## Common Issues & Solutions

### Issue: Data Type Mismatches

**Symptom:** Query returns an error or unexpected values.

**Cause:** The GraphQL type doesn't match the value built in the view's JSONB.

**Solution:** Use precise types — for money, build a string/Decimal-friendly value in the view and map it to a precise Python type, never a float.

```python
from decimal import Decimal

# Wrong
@fraiseql.type(sql_source="v_product", jsonb_column="data")
class Product:
    price: float    # ❌ float loses precision

# Correct
@fraiseql.type(sql_source="v_product", jsonb_column="data")
class Product:
    price: Decimal  # ✅ use Decimal for money
```

### Issue: Relationship Not Loading

**Symptom:** A nested relationship field returns null.

**Cause:** The view's JSONB never built that key, or the foreign key join is wrong.

**Solution:** Make sure the join and the `jsonb_build_object` key both exist, and check for orphaned foreign keys.

```sql
-- The view must embed the nested object under the field name the type expects
-- e.g. jsonb_build_object('user', jsonb_build_object('id', ...))

-- Look for broken foreign keys
SELECT COUNT(*) FROM tb_post WHERE fk_user IS NULL;
```

### Issue: Authorization Denying All Queries

**Symptom:** Every query returns "Unauthorized" even for public data.

**Cause:** An RLS policy on the underlying table is too restrictive, or the session GUC isn't set.

**Solution:** Verify the request context carries `tenant_id`/`user_id` so FraiseQL issues `SET LOCAL app.tenant_id`, and loosen the policy to allow public rows:

```sql
-- Allow public rows OR rows owned by the current tenant
CREATE POLICY post_visibility ON tb_post
    USING (
        is_public
        OR fk_organization = (
            SELECT pk_organization FROM tb_organization
            WHERE id = current_setting('app.tenant_id')::uuid
        )
    );
```

---

## Performance Tuning Post-Migration

### Step 1: Identify slow queries

```sql
SELECT query, calls, mean_exec_time FROM pg_stat_statements
WHERE mean_exec_time > 100
ORDER BY mean_exec_time DESC LIMIT 20;
```

### Step 2: Add indexes

```sql
-- From slow queries, index the foreign keys and filter columns on the base tables
CREATE INDEX idx_tb_post_fk_user ON tb_post (fk_user);
CREATE INDEX idx_tb_post_created_at ON tb_post (created_at);
```

For JSONB filtering, a GIN index on the `data` column of a view-backing table helps:

```sql
CREATE INDEX idx_tv_user_stats_data ON tv_user_stats USING GIN (data);
```

### Step 3: Materialize expensive views

Convert a hot logical `v_` view into a `tv_` projection (see Step 2.6) and point the type's `sql_source` at it:

```python
# Changed from v_user_stats (logical) to tv_user_stats (projection)
@fraiseql.type(sql_source="tv_user_stats", jsonb_column="data")
class UserStats:
    id: ID
    post_count: int
    total_engagement: int
```

### Step 4: Enable query caching

FraiseQL ships PostgreSQL-backed result caching with cascade invalidation, exposed through the
`fraiseql.caching` module (`PostgresCache`, `ResultCache`, `CachedRepository`, `CacheConfig`,
and `setup_auto_cascade_rules`). Wrap the repository with a `CacheConfig` to cache hot read
paths and invalidate them when the underlying tables change:

```python
from fraiseql.caching import CacheConfig, CachedRepository, PostgresCache

cache = PostgresCache(...)                      # PostgreSQL-backed cache backend
config = CacheConfig(default_ttl=300)           # cache reads for 5 minutes
cached_db = CachedRepository(db, cache, config)
```

---

## See Also

**Related Guides:**

- **[Schema Design Best Practices](./schema-design-best-practices.md)** — Designing effective schemas
- **[Common Gotchas](./common-gotchas.md)** — Pitfalls to avoid during migration
- **[Performance Tuning Runbook](../operations/performance-tuning-runbook.md)** — Optimizing post-migration
- **[Production Deployment](./production-deployment.md)** — Deployment procedures
- **[Performance Optimization](./performance-optimization.md)** — Optimizing view types and reads

**Architecture & Reference:**

- **[Authorization Quick Start](./authorization-quick-start.md)** — Row-level security setup

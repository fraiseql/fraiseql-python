---
title: Multi-Tenant SaaS with Row-Level Security
description: Building a production-grade multi-tenant SaaS application with FraiseQL v1 using PostgreSQL Row-Level Security (RLS).
keywords: ["saas", "multi-tenant", "row-level-security", "rls", "postgresql", "security"]
tags: ["documentation", "patterns"]
---

# Multi-Tenant SaaS with Row-Level Security

**Status:** Production Ready
**Complexity:** Advanced
**Audience:** SaaS architects, backend developers
**Reading Time:** 30-35 minutes

A blueprint for building a multi-tenant SaaS application on FraiseQL v1. Tenant
isolation is enforced where it belongs — inside PostgreSQL — using **Row-Level
Security (RLS)** policies. FraiseQL sets a per-transaction session variable from the
request context, and every RLS policy reads it. Application code never has to
remember to add `WHERE tenant_id = ...`; the database does it for you.

---

## How Isolation Works

Tenant context flows from the HTTP request all the way down to the row filter:

```text
GraphQL request (+ JWT)
   │  your auth middleware verifies the token
   ▼
info.context["tenant_id"]   (also "user_id", "is_super_admin", role, …)
   │  FraiseQL CQRS repository issues, per transaction:
   ▼
SET LOCAL app.tenant_id = '<uuid>'
   │  PostgreSQL evaluates RLS policies:
   ▼
USING (tenant_id = current_setting('app.tenant_id')::uuid)
   ▼
Only the current tenant's rows are visible / writable
```

The mechanism has three moving parts:

1. **A `tenant_id` column** on every tenant-scoped `tb_*` table.
2. **RLS policies** on those tables that compare `tenant_id` against
   `current_setting('app.tenant_id')`.
3. **FraiseQL's CQRS repository** (`info.context["db"]`), which reads `tenant_id`
   (and `user_id`, `is_super_admin`, and any role claims) out of `info.context` and
   emits `SET LOCAL app.tenant_id = …` at the start of each transaction. Because the
   GUC is set with `SET LOCAL`, it is scoped to that transaction and resets cleanly —
   safe to use with pooled connections.

There is no separate server process and no build step. FraiseQL is a runtime,
PostgreSQL-only framework: you run a FastAPI app, and tenant isolation lives entirely
in PostgreSQL.

---

## Schema Design

FraiseQL v1 follows a CQRS layout. Writes target normalized `tb_*` tables through
`fn_*` functions; reads come from `v_*`/`tv_*` views that expose a `data` JSONB
column. RLS is applied to the `tb_*` tables — and because views run with the
querying role's privileges, the same policies transparently filter the views too.

### Write Tables (`tb_*`)

```sql
-- Tenants (the SaaS customers). Not tenant-scoped itself.
CREATE TABLE tb_tenant (
  pk_tenant          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id                 UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  identifier         TEXT UNIQUE NOT NULL,        -- slug, e.g. "acme"
  name               TEXT NOT NULL,
  plan               TEXT NOT NULL DEFAULT 'free', -- free, starter, pro, enterprise
  stripe_customer_id TEXT,
  status             TEXT NOT NULL DEFAULT 'active', -- active, suspended, cancelled
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Users (tenant members).
CREATE TABLE tb_user (
  pk_user       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id            UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  tenant_id     UUID NOT NULL REFERENCES tb_tenant(id) ON DELETE CASCADE,
  email         TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  full_name     TEXT,
  role          TEXT NOT NULL DEFAULT 'member', -- owner, admin, member, viewer
  status        TEXT NOT NULL DEFAULT 'invited', -- active, invited, deactivated
  last_login    TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, email)
);
CREATE INDEX ix_user_tenant ON tb_user (tenant_id);

-- Projects (tenant workspace items).
CREATE TABLE tb_project (
  pk_project  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id          UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  tenant_id   UUID NOT NULL REFERENCES tb_tenant(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  description TEXT,
  owner_id    UUID NOT NULL REFERENCES tb_user(id),
  status      TEXT NOT NULL DEFAULT 'active', -- active, archived
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_project_tenant ON tb_project (tenant_id);
CREATE INDEX ix_project_owner ON tb_project (owner_id);

-- Project members (who can access each project).
CREATE TABLE tb_project_member (
  pk_project_member BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id                UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  tenant_id         UUID NOT NULL REFERENCES tb_tenant(id) ON DELETE CASCADE,
  project_id        UUID NOT NULL REFERENCES tb_project(id) ON DELETE CASCADE,
  user_id           UUID NOT NULL REFERENCES tb_user(id) ON DELETE CASCADE,
  role              TEXT NOT NULL DEFAULT 'viewer', -- editor, viewer, admin
  invited_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  joined_at         TIMESTAMPTZ,
  UNIQUE (project_id, user_id)
);
CREATE INDEX ix_project_member_tenant ON tb_project_member (tenant_id);

-- Tasks (project work items).
CREATE TABLE tb_task (
  pk_task     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id          UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  tenant_id   UUID NOT NULL REFERENCES tb_tenant(id) ON DELETE CASCADE,
  project_id  UUID NOT NULL REFERENCES tb_project(id) ON DELETE CASCADE,
  title       TEXT NOT NULL,
  description TEXT,
  status      TEXT NOT NULL DEFAULT 'todo', -- todo, in_progress, done
  assigned_to UUID REFERENCES tb_user(id),
  priority    TEXT NOT NULL DEFAULT 'medium', -- low, medium, high
  due_date    DATE,
  created_by  UUID NOT NULL REFERENCES tb_user(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_task_tenant ON tb_task (tenant_id);
CREATE INDEX ix_task_project ON tb_task (project_id);
CREATE INDEX ix_task_status ON tb_task (status);

-- Audit log (compliance & debugging).
CREATE TABLE tb_audit_log (
  pk_audit_log BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id           UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  tenant_id    UUID NOT NULL REFERENCES tb_tenant(id) ON DELETE CASCADE,
  user_id      UUID REFERENCES tb_user(id),
  entity_type  TEXT NOT NULL,
  entity_id    UUID NOT NULL,
  action       TEXT NOT NULL, -- created, updated, deleted
  old_values   JSONB,
  new_values   JSONB,
  ip_address   INET,
  user_agent   TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_tenant ON tb_audit_log (tenant_id);
CREATE INDEX ix_audit_created ON tb_audit_log (created_at);

-- Subscription (one per tenant, drives billing).
CREATE TABLE tb_subscription (
  pk_subscription        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id                     UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  tenant_id              UUID NOT NULL UNIQUE REFERENCES tb_tenant(id) ON DELETE CASCADE,
  stripe_subscription_id TEXT,
  plan                   TEXT NOT NULL,
  status                 TEXT NOT NULL, -- active, past_due, cancelled
  current_period_start   DATE,
  current_period_end     DATE,
  cancel_at_period_end   BOOLEAN NOT NULL DEFAULT false,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Usage metrics (for metered billing).
CREATE TABLE tb_usage_metric (
  pk_usage_metric BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id              UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  tenant_id       UUID NOT NULL REFERENCES tb_tenant(id) ON DELETE CASCADE,
  metric_name     TEXT NOT NULL, -- api_calls, storage_gb, …
  metric_value    NUMERIC(15, 2) NOT NULL DEFAULT 0,
  period_start    DATE NOT NULL,
  period_end      DATE NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, metric_name, period_start, period_end)
);
CREATE INDEX ix_usage_tenant ON tb_usage_metric (tenant_id);
```

Note the trinity identifier pattern: `pk_*` is an internal `BIGINT` for fast joins
(never exposed), `id` is the public `UUID`, and `identifier` is an optional
human-readable slug. GraphQL only ever sees `id` and `identifier`.

### Read Views (`v_*`)

Reads come from views that build a `data` JSONB column. RLS on the underlying
`tb_*` tables is enforced automatically when the view runs as the querying role.

```sql
CREATE VIEW v_project AS
SELECT
  p.id,
  p.tenant_id,
  jsonb_build_object(
    'id',          p.id,
    'name',        p.name,
    'description', p.description,
    'status',      p.status,
    'ownerId',     p.owner_id,
    'createdAt',   p.created_at
  ) AS data
FROM tb_project p;

CREATE VIEW v_task AS
SELECT
  t.id,
  t.tenant_id,
  t.project_id,
  jsonb_build_object(
    'id',         t.id,
    'title',      t.title,
    'status',     t.status,
    'priority',   t.priority,
    'assignedTo', t.assigned_to,
    'dueDate',    t.due_date,
    'createdAt',  t.created_at
  ) AS data
FROM tb_task t;
```

The view exposes `id` (for `WHERE id = $1` lookups), `tenant_id` (for optional
`mandatory_filters`), and the `data` JSONB. The internal `pk_*` columns never leave
the table.

---

## Row-Level Security Policies

This is the heart of tenant isolation. Enable RLS, then write policies that read the
session GUC FraiseQL sets for you.

### Enable RLS

```sql
ALTER TABLE tb_user           ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_project        ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_project_member ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_task           ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_audit_log      ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_subscription   ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_usage_metric   ENABLE ROW LEVEL SECURITY;

-- Force RLS even for the table owner, so no role bypasses isolation.
ALTER TABLE tb_user           FORCE ROW LEVEL SECURITY;
ALTER TABLE tb_project        FORCE ROW LEVEL SECURITY;
ALTER TABLE tb_task           FORCE ROW LEVEL SECURITY;
ALTER TABLE tb_subscription   FORCE ROW LEVEL SECURITY;
ALTER TABLE tb_usage_metric   FORCE ROW LEVEL SECURITY;
```

### Session Context Helpers

FraiseQL emits `SET LOCAL app.tenant_id = …`, `SET LOCAL app.user_id = …`, and
`SET LOCAL app.is_super_admin = …` from `info.context`. Thin SQL helpers make the
policies readable. The second `true` argument to `current_setting` returns `NULL`
instead of erroring when the GUC is unset.

```sql
CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS UUID AS $$
  SELECT NULLIF(current_setting('app.tenant_id', true), '')::UUID;
$$ LANGUAGE SQL STABLE;

CREATE OR REPLACE FUNCTION current_user_id() RETURNS UUID AS $$
  SELECT NULLIF(current_setting('app.user_id', true), '')::UUID;
$$ LANGUAGE SQL STABLE;

-- Populate this GUC from a role claim in your auth middleware
-- (info.context["user_role"]) if you want role checks inside RLS.
CREATE OR REPLACE FUNCTION current_user_role() RETURNS TEXT AS $$
  SELECT NULLIF(current_setting('app.user_role', true), '');
$$ LANGUAGE SQL STABLE;
```

### Users Table

```sql
-- See only users in the current tenant.
CREATE POLICY user_tenant_isolation ON tb_user
  FOR SELECT
  USING (tenant_id = current_tenant_id());

-- Update your own profile; admins and owners can update anyone in the tenant.
CREATE POLICY user_self_update ON tb_user
  FOR UPDATE
  USING (
    tenant_id = current_tenant_id()
    AND (id = current_user_id() OR current_user_role() IN ('owner', 'admin'))
  );

-- Only owners/admins delete users.
CREATE POLICY user_delete ON tb_user
  FOR DELETE
  USING (
    tenant_id = current_tenant_id()
    AND current_user_role() IN ('owner', 'admin')
  );

-- New users must be created inside the active tenant.
CREATE POLICY user_insert ON tb_user
  FOR INSERT
  WITH CHECK (tenant_id = current_tenant_id());
```

### Projects Table

```sql
-- See projects in your tenant that you own or are a member of.
CREATE POLICY project_visibility ON tb_project
  FOR SELECT
  USING (
    tenant_id = current_tenant_id()
    AND (
      owner_id = current_user_id()
      OR id IN (
        SELECT project_id FROM tb_project_member
        WHERE user_id = current_user_id()
      )
    )
  );

-- Owners and tenant admins can update.
CREATE POLICY project_update ON tb_project
  FOR UPDATE
  USING (
    tenant_id = current_tenant_id()
    AND (owner_id = current_user_id() OR current_user_role() IN ('owner', 'admin'))
  );

-- Only the project owner deletes.
CREATE POLICY project_delete ON tb_project
  FOR DELETE
  USING (tenant_id = current_tenant_id() AND owner_id = current_user_id());

-- Create only inside the active tenant.
CREATE POLICY project_insert ON tb_project
  FOR INSERT
  WITH CHECK (tenant_id = current_tenant_id());
```

### Tasks Table

```sql
-- See tasks in projects you can access.
CREATE POLICY task_visibility ON tb_task
  FOR SELECT
  USING (
    tenant_id = current_tenant_id()
    AND project_id IN (
      SELECT id FROM tb_project
      WHERE owner_id = current_user_id()
         OR id IN (
           SELECT project_id FROM tb_project_member
           WHERE user_id = current_user_id()
         )
    )
  );

-- Project participants and tenant admins update tasks.
CREATE POLICY task_update ON tb_task
  FOR UPDATE
  USING (
    tenant_id = current_tenant_id()
    AND (
      project_id IN (
        SELECT id FROM tb_project
        WHERE owner_id = current_user_id()
           OR id IN (
             SELECT project_id FROM tb_project_member
             WHERE user_id = current_user_id()
           )
      )
      OR current_user_role() IN ('owner', 'admin')
    )
  );
```

### Audit Logs

```sql
-- Only tenant admins read audit logs, scoped to their tenant.
CREATE POLICY audit_log_visibility ON tb_audit_log
  FOR SELECT
  USING (
    tenant_id = current_tenant_id()
    AND current_user_role() IN ('owner', 'admin')
  );

-- Audit logs are append-only: no policy allows UPDATE or DELETE,
-- so RLS denies them outright once FORCE ROW LEVEL SECURITY is on.
```

### Cross-Tenant Reads with `mandatory_filters`

RLS is your defense-in-depth baseline. For an extra explicit guard — or for code
paths where you want belt-and-braces filtering on the read side — FraiseQL's
repository accepts `mandatory_filters`, which are AND-ed into every generated query
and cannot be overridden by client arguments:

```python
projects = await db.find(
    "v_project",
    mandatory_filters={"tenant_id": info.context["tenant_id"]},
)
```

With RLS in place this is redundant, but it documents intent and protects you if a
table ever ships without a policy.

---

## FraiseQL Types and Queries (Python)

Define types against the read views and let RLS handle tenant scoping. The
namespaced API (`import fraiseql`) avoids shadowing builtins.

```python
import fraiseql
from fraiseql.types import ID, DateTime

@fraiseql.type(sql_source="v_tenant", jsonb_column="data")
class Tenant:
    id: ID
    identifier: str
    name: str
    plan: str
    status: str
    created_at: DateTime

@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    email: str
    full_name: str | None
    role: str            # owner, admin, member, viewer
    status: str
    created_at: DateTime

@fraiseql.type(sql_source="v_project", jsonb_column="data")
class Project:
    id: ID
    name: str
    description: str | None
    status: str
    created_at: DateTime

@fraiseql.type(sql_source="v_task", jsonb_column="data")
class Task:
    id: ID
    title: str
    description: str | None
    status: str
    priority: str
    due_date: str | None
    created_at: DateTime
```

Queries read from the views. Because the repository has already issued
`SET LOCAL app.tenant_id`, every row returned belongs to the caller's tenant — no
manual filtering required.

```python
@fraiseql.query
async def me(info) -> User | None:
    db = info.context["db"]
    return await db.find_one("v_user", id=info.context["user_id"])

@fraiseql.query
async def projects(info, status: str | None = None) -> list[Project]:
    db = info.context["db"]
    filters = {"status": status} if status else {}
    return await db.find("v_project", **filters)

@fraiseql.query
async def tasks(
    info,
    project_id: ID,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Task]:
    db = info.context["db"]
    filters = {"project_id": project_id}
    if status:
        filters["status"] = status
    return await db.find("v_task", limit=limit, offset=offset, **filters)
```

### Authorization Beyond Tenant Isolation

RLS already enforces *tenant* boundaries. For coarser operation-level checks (for
example, "only owners may view billing"), use one of two real v1 mechanisms:

**1. Role checks inside RLS.** If your auth middleware populates `app.user_role` (or
checks `current_user_id()` against a role table), the policies above already gate
SELECT/UPDATE/DELETE by role. This keeps authorization in one place — the database.

**2. An `Authorizer` on the query.** FraiseQL accepts an authorizer callable that
runs before the resolver and can reject the request based on `info.context`:

```python
def require_roles(*allowed: str):
    async def authorizer(info) -> bool:
        return info.context.get("user_role") in allowed
    return authorizer

@fraiseql.query(authorizer=require_roles("owner", "admin"))
async def audit_logs(info, limit: int = 100, offset: int = 0) -> list[AuditLog]:
    db = info.context["db"]
    return await db.find("v_audit_log", limit=limit, offset=offset)
```

v1 has no role-based authorization decorator — authorization is expressed through
RLS policies and/or `@fraiseql.query(authorizer=...)`.

### Mutations via `fn_*` Functions

Writes call PostgreSQL functions through `db.execute_function`. The function runs
inside the same transaction, so `app.tenant_id` is set and any RLS `WITH CHECK`
clauses apply.

```python
@fraiseql.input
class CreateProjectInput:
    name: str
    description: str = ""

@fraiseql.success
class CreateProjectSuccess:
    project: Project

@fraiseql.error
class CreateProjectError:
    message: str
    code: str = "VALIDATION_ERROR"

@fraiseql.mutation
async def create_project(
    info, input: CreateProjectInput
) -> CreateProjectSuccess | CreateProjectError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_create_project",
        {
            "tenant_id": info.context["tenant_id"],
            "owner_id": info.context["user_id"],
            "name": input.name,
            "description": input.description,
        },
    )
    if not result.get("success"):
        return CreateProjectError(message=result.get("message", "failed"))
    return CreateProjectSuccess(project=Project(**result["project"]))
```

---

## Wiring Tenant Context (FastAPI)

Tenant isolation only works if `info.context["tenant_id"]` is populated. You do that
in FastAPI middleware (or a context getter) that verifies the JWT and copies its
claims into the GraphQL context. FraiseQL then turns those context keys into session
GUCs automatically.

```python
import fraiseql
from fraiseql.fastapi import create_fraiseql_app

async def build_context(request) -> dict:
    # Verify the JWT however you like (PyJWT, Auth0, etc.).
    claims = verify_jwt(request.headers.get("authorization"))
    return {
        "tenant_id": claims["tenant_id"],
        "user_id": claims["user_id"],
        "user_role": claims["role"],
        "is_super_admin": claims.get("is_super_admin", False),
    }

app = create_fraiseql_app(
    database_url="postgresql://localhost/saas",
    types=[Tenant, User, Project, Task],
    queries=[me, projects, tasks, audit_logs],
    mutations=[create_project],
    context_getter=build_context,
    production=True,
)
```

Run it like any FastAPI app:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

The critical rule: **never trust a `tenant_id` sent by the client.** It must come
from the verified token. The client cannot forge `info.context["tenant_id"]` because
it is derived server-side from a signed JWT before any query runs.

---

## JWT Token Structure

```json
{
  "sub": "user_123",
  "email": "alice@acme.com",
  "tenant_id": "9f1c2b...",
  "user_id": "3a7e9d...",
  "role": "admin",
  "iat": 1640000000,
  "exp": 1640086400
}
```

Your middleware verifies the signature and expiry, then maps `tenant_id`, `user_id`,
and `role` into the GraphQL context. From there FraiseQL handles the
`SET LOCAL app.*` calls and PostgreSQL handles the rest.

---

## Billing and Usage Tracking

Plan limits and metered usage live in PostgreSQL functions, so they run in the same
transaction as the rest of the request and respect tenant isolation.

```sql
-- Increment a usage counter for the current billing period.
CREATE OR REPLACE FUNCTION fn_increment_usage(
  p_tenant_id  UUID,
  p_metric     TEXT,
  p_amount     NUMERIC
) RETURNS void AS $$
BEGIN
  INSERT INTO tb_usage_metric (tenant_id, metric_name, metric_value, period_start, period_end)
  VALUES (
    p_tenant_id,
    p_metric,
    p_amount,
    DATE_TRUNC('month', now())::DATE,
    (DATE_TRUNC('month', now()) + INTERVAL '1 month' - INTERVAL '1 day')::DATE
  )
  ON CONFLICT (tenant_id, metric_name, period_start, period_end)
  DO UPDATE SET metric_value = tb_usage_metric.metric_value + EXCLUDED.metric_value;
END;
$$ LANGUAGE plpgsql;

-- Enforce a per-plan API limit.
CREATE OR REPLACE FUNCTION fn_check_api_limit(p_tenant_id UUID) RETURNS BOOLEAN AS $$
DECLARE
  v_usage NUMERIC;
  v_plan  TEXT;
  v_limit NUMERIC;
BEGIN
  SELECT plan INTO v_plan FROM tb_tenant WHERE id = p_tenant_id;

  SELECT metric_value INTO v_usage
  FROM tb_usage_metric
  WHERE tenant_id = p_tenant_id
    AND metric_name = 'api_calls'
    AND period_start = DATE_TRUNC('month', now())::DATE;

  v_usage := COALESCE(v_usage, 0);
  v_limit := CASE v_plan
    WHEN 'free'       THEN 1000
    WHEN 'starter'    THEN 10000
    WHEN 'pro'        THEN 100000
    WHEN 'enterprise' THEN 999999999
    ELSE 0
  END;

  RETURN v_usage < v_limit;
END;
$$ LANGUAGE plpgsql;
```

---

## Provisioning a New Tenant

Tenant signup is a single `fn_*` function that creates the tenant, its first user
(the owner), and a default subscription atomically. Because the new tenant has no
prior rows, you typically run provisioning with a super-admin context
(`info.context["is_super_admin"] = True`) or a dedicated service role whose policies
permit the initial inserts.

```sql
CREATE OR REPLACE FUNCTION fn_provision_tenant(
  p_slug       TEXT,
  p_name       TEXT,
  p_owner_email TEXT,
  p_owner_hash  TEXT
) RETURNS JSONB AS $$
DECLARE
  v_tenant_id UUID;
  v_user_id   UUID;
BEGIN
  INSERT INTO tb_tenant (identifier, name, plan, status)
  VALUES (p_slug, p_name, 'free', 'active')
  RETURNING id INTO v_tenant_id;

  INSERT INTO tb_user (tenant_id, email, password_hash, role, status)
  VALUES (v_tenant_id, p_owner_email, p_owner_hash, 'owner', 'active')
  RETURNING id INTO v_user_id;

  INSERT INTO tb_subscription (tenant_id, plan, status, current_period_start, current_period_end)
  VALUES (
    v_tenant_id, 'free', 'active',
    now()::DATE, (now() + INTERVAL '1 month')::DATE
  );

  RETURN jsonb_build_object('success', true, 'tenantId', v_tenant_id, 'ownerId', v_user_id);
END;
$$ LANGUAGE plpgsql;
```

---

## Audit Logging

A single trigger function reads the session GUCs and records who changed what. It
relies on the same `current_tenant_id()` / `current_user_id()` helpers, so the audit
trail is automatically tenant-scoped.

```sql
CREATE OR REPLACE FUNCTION fn_audit_trigger() RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO tb_audit_log (
    tenant_id, user_id, entity_type, entity_id, action, old_values, new_values
  ) VALUES (
    current_tenant_id(),
    current_user_id(),
    TG_TABLE_NAME,
    CASE WHEN TG_OP = 'DELETE' THEN OLD.id ELSE NEW.id END,
    lower(TG_OP),
    CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN row_to_json(OLD)::jsonb END,
    CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN row_to_json(NEW)::jsonb END
  );
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER user_audit
  AFTER INSERT OR UPDATE OR DELETE ON tb_user
  FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

CREATE TRIGGER project_audit
  AFTER INSERT OR UPDATE OR DELETE ON tb_project
  FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

CREATE TRIGGER task_audit
  AFTER INSERT OR UPDATE OR DELETE ON tb_task
  FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();
```

---

## Testing Tenant Isolation

The cheapest, most convincing test is at the SQL layer: set a tenant GUC and confirm
you cannot see another tenant's rows. This exercises the exact mechanism FraiseQL
uses at runtime.

```sql
-- Seed two tenants, then prove isolation.
SET LOCAL app.tenant_id = '<tenant-a-uuid>';
SET LOCAL app.user_id   = '<tenant-a-owner-uuid>';
SET LOCAL app.user_role = 'owner';

-- Returns only tenant A's projects; tenant B's rows are invisible.
SELECT count(*) FROM tb_project;            -- only A
SELECT count(*) FROM tb_project WHERE tenant_id = '<tenant-b-uuid>';  -- 0
```

At the application level, drive two different JWTs through the GraphQL endpoint and
assert each only ever sees its own data:

```python
import pytest

@pytest.mark.asyncio
async def test_tenant_isolation(client):
    token_a = make_jwt(tenant_id=TENANT_A, user_id=OWNER_A, role="owner")
    resp = await client.post(
        "/graphql",
        json={"query": "{ projects { id name } }"},
        headers={"authorization": f"Bearer {token_a}"},
    )
    project_ids = {p["id"] for p in resp.json()["data"]["projects"]}
    assert project_ids <= TENANT_A_PROJECT_IDS  # never tenant B's
```

---

## Scaling Considerations

### Connection Pooling

- PgBouncer in **transaction** pooling mode pairs well with `SET LOCAL`: the GUC is
  scoped to the transaction, so it never leaks to the next request on a reused
  connection.
- Size the pool to your concurrency, not your tenant count — tenants share the pool.

### Caching

- FraiseQL ships PostgreSQL-backed result caching (`PostgresCache`, `ResultCache`,
  `CachedRepository`) with cascade invalidation rules. Cache keys include the query
  and arguments; keep tenant context out of cached payloads or scope keys per tenant.
- Cache slow-changing tenant configuration (plan limits, feature flags) and
  invalidate on plan or role changes.

### Read Replicas

- Route read-only queries to a streaming replica. RLS policies and the `app.*` GUCs
  apply identically on replicas, so tenant isolation holds for replica reads too.

---

## Common Pitfalls

### Trusting a client-supplied `tenant_id`

Always derive `tenant_id` from the verified JWT in your context getter, never from a
GraphQL argument or header the client controls.

### Relying only on application-level filtering

App filters are easy to forget on one code path. Make RLS the baseline so a missing
`WHERE` clause still cannot leak data. Use `mandatory_filters` as an additional
explicit guard.

### Forgetting `FORCE ROW LEVEL SECURITY`

Plain `ENABLE ROW LEVEL SECURITY` is bypassed by the table owner. Add `FORCE` so no
role — including the one your app connects as, if it owns the tables — escapes the
policies.

### Leaving a GUC set between requests

`SET LOCAL` (which FraiseQL uses) resets at transaction end. Avoid plain `SET`, which
persists on the connection and can leak one tenant's context into the next request on
a pooled connection.

---

## See Also

- [Patterns Overview](./README.md)
- [Analytics OLAP Platform](./analytics-olap-platform.md)
- [Extension Points](../architecture/integration/extension-points.md)
- [Consistency Model](../architecture/reliability/consistency-model.md)
- [Database-Centric Architecture](../foundation/03-database-centric-architecture.md)

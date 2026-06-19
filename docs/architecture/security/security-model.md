---

title: FraiseQL Security Model: Authorization, Row-Level Security, Field Masking, and Audit
description: FraiseQL security operates on five pillars.
keywords: ["design", "scalability", "performance", "patterns", "security"]
tags: ["documentation", "reference"]
---

# FraiseQL Security Model: Authorization, Row-Level Security, Field Masking, and Audit

**Status:** System overview for v1 (PostgreSQL, Python/FastAPI runtime)
**Audience:** Security architects, compliance engineers, application developers, operations teams

---

## Executive Summary

FraiseQL security operates on five pillars:

1. **Authentication** — Verify user identity (an `AuthProvider`, e.g. Auth0 or a custom JWT issuer)
2. **Operation & role authorization** — Control which operations a user may run (an app-supplied `Authorizer` plus the `requires_*` resolver decorators)
3. **Row-Level Security (RLS)** — Filter data per user/tenant (PostgreSQL-enforced policies)
4. **Field-level authorization & redaction** — Hide sensitive fields per user (`authorize_field`, and view-layer redaction)
5. **Audit Logging** — Track who did what and when (durable rows in PostgreSQL)

**Core principle**: Enforcement is layered. The Python runtime gates operations and fields; PostgreSQL enforces row scoping. FraiseQL never returns data the authorization layer denies, and the fail-closed enforcement applies even on the Rust/turbo/APQ resolver-bypass paths.

**Security properties:**

- ✅ **Runtime enforcement** — Authorization is evaluated on every request, at app startup the schema is wired with the enforcement layer.
- ✅ **No resolver bypasses** — Operation and field gates are re-applied on the Rust passthrough, turbo, and APQ chokepoints, so they fail closed.
- ✅ **Deterministic** — The same context + operation + arguments produce the same decision (and may be cached by a `DecisionCache`).
- ✅ **Database-enforced row scoping** — RLS policies live in PostgreSQL, so even a direct database session honors them.
- ✅ **Auditable** — Access attempts can be recorded as durable rows.

### Security Pipeline

**Diagram: Security Architecture** — Multi-layer pipeline from request to response.

```d2
direction: right

Request: "GraphQL Request\n(with JWT token)" {
  shape: box
  style.fill: "#e3f2fd"
}

Authn: "1. Authentication\n(Verify identity)" {
  shape: box
  style.fill: "#f3e5f5"
}

QueryAuth: "2. Operation Authorization\n(Authorizer / requires_*)" {
  shape: box
  style.fill: "#fff3e0"
}

RLS: "3. Row-Level Security\n(PostgreSQL filters rows)" {
  shape: box
  style.fill: "#f1f8e9"
}

FieldAuth: "4. Field Authorization\n(authorize_field / view redaction)" {
  shape: box
  style.fill: "#ffe0b2"
}

Audit: "5. Audit Logging\n(Record access)" {
  shape: box
  style.fill: "#ffccbc"
}

Response: "Response\n(Authorized data)" {
  shape: box
  style.fill: "#c8e6c9"
}

Denied: "Access Denied" {
  shape: box
  style.fill: "#ffebee"
}

Request -> Authn
Authn -> QueryAuth: "UserContext"
Authn -> Denied: "Token invalid"
QueryAuth -> RLS: "Operation allowed"
QueryAuth -> Denied: "Operation denied"
RLS -> FieldAuth: "Row-filtered data"
FieldAuth -> Audit: "Authorized fields"
Audit -> Response: "Log recorded"
```

---

## 1. Authentication Context

### 1.1 User Context

Authenticated requests carry a `UserContext` at `info.context["user"]`. It is a plain
dataclass (`fraiseql.auth.UserContext`):

```python
from fraiseql.auth import UserContext

# Built by your AuthProvider after the JWT is validated.
user = UserContext(
    user_id="user-456",                       # subject claim
    email="alice@company.com",
    name="Alice",
    roles=["user", "member", "team-lead"],
    permissions=["read:posts", "write:own:posts"],
    metadata={"organization_id": "org-123", "department": "engineering"},
)

user.has_role("team-lead")                     # True
user.has_permission("read:posts")              # True
user.has_any_role(["admin", "team-lead"])      # True
user.has_any_permission(["write:posts", "write:own:posts"])  # True
```

`UserContext` exposes `has_role`, `has_permission`, `has_any_role`, `has_any_permission`,
`has_all_roles`, and `has_all_permissions`. Anything not modeled as a role or permission
(organization, department, tenant) lives in `metadata`.

### 1.2 Context Binding

A provider validates the token and builds the `UserContext`; FastAPI's request lifecycle
places it on `info.context["user"]`. v1 ships **Auth0** (`Auth0Provider`/`Auth0Config`)
and a generic/native path, plus a Rust-accelerated JWT validator
(`RustCustomJWTProvider`) — all Python-facing:

```python
from fraiseql.auth import AuthProvider, UserContext


class MyProvider(AuthProvider):
    async def validate_token(self, token: str) -> dict:
        # Verify signature/issuer/audience against your JWKS, return the claims.
        ...

    async def get_user_from_token(self, token: str) -> UserContext:
        claims = await self.validate_token(token)
        return UserContext(
            user_id=claims["sub"],
            email=claims.get("email"),
            roles=claims.get("roles", []),
            permissions=claims.get("permissions", []),
            metadata={"organization_id": claims.get("org_id")},
        )
```

Wire it in when building the app:

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User, Post],
    queries=[users, user],
    mutations=[create_post],
    auth=MyProvider(),
    production=True,
)
```

For any OIDC issuer (Google, Keycloak, Okta, ...) there are two honest paths: front it
with **Auth0** as a broker (`auth_provider="auth0"`), or set `auth_provider="custom"`
and subclass `AuthProvider` to validate that issuer's JWTs. v1 does not ship per-vendor
provider classes.

### 1.3 Context Immutability

Treat the `UserContext` as **read-only** for the lifetime of a request. It is built once
during authentication; resolvers read it but must never mutate it to escalate roles or
impersonate another user. Tenant/row-scoping decisions derived from it are pushed into
PostgreSQL session variables (Section 3) inside the request transaction, so privilege
cannot be changed mid-request.

---

## 2. Operation Authorization

v1 gives you two complementary mechanisms for operation-level (query/mutation/subscription)
authorization. Both are Python and both surface a denial as a GraphQL error with
`extensions.code` (no HTTP 4xx from a separate router).

### 2.1 `requires_*` resolver decorators

The quickest gate: decorate a resolver with one of the decorators from
`fraiseql.auth`. They read `info.context["user"]` (a `UserContext`) and raise a
`GraphQLError` when the check fails.

```python
import fraiseql
from fraiseql.auth import (
    requires_auth,
    requires_role,
    requires_permission,
)
from fraiseql.auth.decorators import requires_any_role, requires_any_permission
from fraiseql.types import ID


@fraiseql.query
@requires_auth
async def me(info) -> "User":
    """Any authenticated user."""
    db = info.context["db"]
    user = info.context["user"]
    return await db.find_one("v_user", id=user.user_id)


@fraiseql.query
@requires_role("admin")
async def all_users(info) -> list["User"]:
    """Only users with the 'admin' role."""
    db = info.context["db"]
    return await db.find("v_user")


@fraiseql.mutation
@requires_permission("posts:write")
async def create_post(info, input: "CreatePostInput") -> "CreatePostSuccess":
    """Requires the 'posts:write' permission."""
    db = info.context["db"]
    result = await db.execute_function("fn_create_post", {...})
    ...


@fraiseql.mutation
@requires_any_role("admin", "moderator")
async def delete_post(info, id: ID) -> "DeletePostSuccess":
    """Either 'admin' or 'moderator'."""
    ...
```

| Decorator | Denies with `extensions.code` | Passes when |
|-----------|-------------------------------|-------------|
| `requires_auth` | `UNAUTHENTICATED` (no `UserContext`) | a `UserContext` is present |
| `requires_role("admin")` | `UNAUTHENTICATED` or `FORBIDDEN` | `user.has_role("admin")` |
| `requires_permission("posts:write")` | `UNAUTHENTICATED` or `FORBIDDEN` | `user.has_permission(...)` |
| `requires_any_role("admin", "mod")` | `UNAUTHENTICATED` or `FORBIDDEN` | `user.has_any_role([...])` |
| `requires_any_permission(...)` | `UNAUTHENTICATED` or `FORBIDDEN` | `user.has_any_permission([...])` |

### 2.2 The `Authorizer` policy contract

For richer, centralized policy (RBAC/ABAC, per-operation decisions, row-scoping filters,
decision caching), supply an **`Authorizer`**. It is a structural protocol
(`fraiseql.security.Authorizer`) with a single method; the framework enforces, the
authorizer decides:

```python
from typing import Any

from fraiseql.security import Authorizer, AuthorizationDecision


class PolicyAuthorizer:
    async def authorize_operation(
        self,
        *,
        context: dict[str, Any],
        operation_type: str,        # "query" | "mutation" | "subscription"
        operation_name: str,
        arguments: dict[str, Any],
    ) -> AuthorizationDecision | bool:
        user = context.get("user")
        if user is None:
            return AuthorizationDecision.deny(
                code="UNAUTHENTICATED", message="Login required"
            )

        if operation_name == "all_users" and not user.has_role("admin"):
            return AuthorizationDecision.deny(message="Admins only")

        # Allow, and AND a row-scoping filter into the read path:
        return AuthorizationDecision.allow(
            filters={"organization_id": user.metadata["organization_id"]}
        )
```

`AuthorizationDecision` is an immutable value with two constructors:

- `AuthorizationDecision.allow(filters=None)` — allow; optional `filters` are AND-ed into
  the repository's `mandatory_filters` on the **read** path (ignored on mutations and
  bypass paths).
- `AuthorizationDecision.deny(code="FORBIDDEN", message=None)` — deny; `code` is surfaced
  as the GraphQL error's `extensions.code`.

A plain `bool` is sugar: `True` → `allow()`, `False` → `deny()`. Implementations may be
sync or async.

Attach an authorizer per operation or globally:

```python
# Per operation — overrides the global default for this resolver:
@fraiseql.query(authorizer=PolicyAuthorizer())
async def all_users(info) -> list["User"]: ...

@fraiseql.subscription(authorizer=PolicyAuthorizer())
async def order_events(info): ...

# Globally — applied to every top-level operation:
app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[all_users],
    authorizer=PolicyAuthorizer(),
    authorization_cache=...,   # optional DecisionCache
)
```

**Fail-closed semantics (verified).** Enforcement lives in one place so every site
inherits it: if no authorizer is configured the operation is allowed (no-op fast path);
an authorizer that *raises* anything other than a `GraphQLError` is treated as **deny**
(never falls through to allow) and the raw exception is logged but never surfaced. The
same enforcement is re-applied at the Rust passthrough, turbo-router, and APQ chokepoints
so those bypass paths cannot fail open.

**Decision caching.** When an `authorization_cache` (a `DecisionCache`) is supplied, a
fresh cache hit replays the prior allow/deny **without** re-invoking the authorizer; an
authorizer that raises hits the fail-closed branch and is **never** cached, so a transient
error can neither pin a deny nor leak an allow.

---

## 3. Row-Level Security (RLS)

Row scoping in v1 is **PostgreSQL Row-Level Security** — raw SQL policies on the
underlying tables, not a FraiseQL decorator. The framework's job is to push request
context into PostgreSQL session variables so your policies can read it.

### 3.1 How tenant/user context reaches the database

The CQRS repository (`FraiseQLRepository`) issues `SET LOCAL` for known keys in
`info.context` at the start of each transaction (verified in `src/fraiseql/db.py`,
`_set_session_variables`). When the context carries `tenant_id`, `user_id`,
`is_super_admin`, etc., it sets matching GUCs:

```sql
-- Emitted automatically per transaction when present in info.context:
SET LOCAL app.tenant_id = '...' ;
SET LOCAL app.user_id   = '...' ;
SET LOCAL app.is_super_admin = ... ;
```

So tenant context flows: request → `info.context["tenant_id"]` → `SET LOCAL app.tenant_id`
→ your RLS policy via `current_setting('app.tenant_id')`. Populate `info.context` from the
`UserContext` in your `context_getter`.

### 3.2 Writing the policies (PostgreSQL)

RLS lives on the write tables (`tb_`) and is inherited by the read views (`v_`/`tv_`) that
select from them. Enable RLS and write policies that read the session GUCs:

```sql
-- Multi-tenant isolation: a row is visible only to its tenant.
ALTER TABLE tb_post ENABLE ROW LEVEL SECURITY;

CREATE POLICY post_tenant_isolation ON tb_post
    USING (tenant_id = current_setting('app.tenant_id')::uuid);

-- Owner-or-admin: see your own rows, or all rows if super admin.
ALTER TABLE tb_user ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_owner_or_admin ON tb_user
    USING (
        id = current_setting('app.user_id')::uuid
        OR current_setting('app.is_super_admin', true)::boolean
    );

-- Team access: same tenant AND (owner OR team member OR admin).
CREATE POLICY task_team_access ON tb_task
    USING (
        tenant_id = current_setting('app.tenant_id')::uuid
        AND (
            owner_id = current_setting('app.user_id')::uuid
            OR team_id = ANY(
                string_to_array(current_setting('app.team_ids', true), ',')::uuid[]
            )
            OR current_setting('app.is_super_admin', true)::boolean
        )
    );
```

Use the two-argument form `current_setting('app.x', true)` (the `true` = "missing OK")
for variables that may be absent, so an unauthenticated/system query degrades to a safe
default rather than erroring.

### 3.3 RLS at query time

A `@query` resolver reads a `v_`/`tv_` view via `db.find` / `db.find_one`. The repository
opens a transaction, sets the session GUCs, then runs the SELECT — and PostgreSQL applies
the policies transparently:

```python
@fraiseql.query
async def posts(info) -> list[Post]:
    db = info.context["db"]
    return await db.find("v_post")   # RLS filters rows by app.tenant_id
```

```sql
-- What PostgreSQL effectively executes (policy AND-ed in by the engine):
SELECT id, data FROM v_post
WHERE tenant_id = current_setting('app.tenant_id')::uuid
ORDER BY ...;
```

A caller who supplies `where: { tenant_id: "other-org" }` still cannot widen the result:
the RLS policy is AND-ed in by PostgreSQL itself, so the predicate is `tenant_id = <mine>
AND tenant_id = 'other-org'` — empty for a different tenant.

### 3.4 Belt-and-braces: `mandatory_filters`

In addition to (not instead of) database RLS, reads can pass explicit
`mandatory_filters` to `db.find`/`db.count`, and an `Authorizer` can return
row-scoping `filters` that the repository AND-merges into `mandatory_filters`:

```python
return await db.find("v_post", mandatory_filters={"tenant_id": tenant_id})
```

RLS is the authoritative, database-enforced control; `mandatory_filters` and authorizer
`filters` are application-level reinforcement.

---

## 4. Field-Level Authorization and Redaction

"Field masking" in v1 is achieved two ways — pick per field:

1. **`authorize_field`** — a field-level authorization gate. When the check fails, the
   field raises a `FieldAuthorizationError` (GraphQL error with
   `extensions.code = "FIELD_AUTHORIZATION_ERROR"`); it does **not** silently return a
   substitute value.
2. **View-layer redaction** — design the `v_`/`tv_` view's `data` JSONB to exclude or
   replace sensitive keys per role/tenant in SQL, so unauthorized callers never receive
   the value at all.

### 4.1 `authorize_field`

`authorize_field` (from `fraiseql.security`) wraps a computed `@fraiseql.field` resolver
with a permission check. The check receives `info` (and optionally the parent `root`) and
returns a `bool` or an `AuthorizationDecision`:

```python
import fraiseql
from fraiseql.security import authorize_field, any_permission, combine_permissions


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    username: str

    @fraiseql.field
    @authorize_field(
        any_permission(
            lambda info, root: info.context["user"].user_id == root.id,  # owner
            lambda info: info.context["user"].has_role("admin"),          # or admin
        ),
        error_message="You can only view your own email",
    )
    def email(self) -> str:
        return self._email

    @fraiseql.field
    @authorize_field(lambda info: info.context["user"].has_role("admin"))
    def ssn(self) -> str:
        return self._ssn
```

Two combinators ship with it:

- `combine_permissions(*checks)` — **AND**, every check must pass.
- `any_permission(*checks)` — **OR**, at least one check must pass.

Checks may be sync or async, plain lambdas or named functions; they can read roles and
permissions off `info.context["user"]`.

### 4.2 Declaring authorized fields on a type

`@fraiseql.type(..., authorize_fields=[...])` marks fields that require the per-field gate.
This list is the per-field authorization gate that the runtime re-applies even on the
Rust/turbo/APQ bypass paths (so JSONB served directly still honors it):

```python
@fraiseql.type(
    sql_source="v_user",
    jsonb_column="data",
    authorize_fields=["email", "ssn"],
)
class User:
    id: ID
    username: str
    email: str
    ssn: str
```

### 4.3 Redaction at the view layer

For data that should never reach an unauthorized client, redact in the view's `data`
JSONB rather than fetching then hiding. The view can branch on the session GUCs RLS uses:

```sql
CREATE VIEW v_customer AS
SELECT
    c.id,
    jsonb_build_object(
        'id', c.id,
        'name', c.name,
        -- Full card number only for admins; everyone else gets the last 4.
        'cardNumber',
            CASE
                WHEN current_setting('app.is_super_admin', true)::boolean
                    THEN c.card_number
                ELSE '**** **** **** ' || right(c.card_number, 4)
            END
    ) AS data
FROM tb_customer c;
```

This keeps the sensitive value inside PostgreSQL and out of the wire entirely for
unauthorized callers — the most robust form of "masking" in v1.

---

## 5. Built-In Role and Permission Checks

v1's authorization is **role- and permission-based**, evaluated against the
`UserContext`. There is no registry of named string rules; you compose checks from the
`UserContext` predicates, the `requires_*` decorators, and your `Authorizer`:

```python
# "authenticated"
user = info.context.get("user")
if user is None:
    raise GraphQLError("Login required", extensions={"code": "UNAUTHENTICATED"})

# "admin only"
@requires_role("admin")

# "owner or admin" (field check)
any_permission(
    lambda info, root: info.context["user"].user_id == root.owner_id,
    lambda info: info.context["user"].has_role("admin"),
)

# "organization member" (in an Authorizer)
if arguments["org_id"] != user.metadata.get("organization_id"):
    return AuthorizationDecision.deny(message="Not a member of this organization")
```

Centralize business-specific policy in one `Authorizer` so it is testable headless and
reused across operations.

---

## 6. Audit Logging

Audit logging in v1 is an application pattern backed by PostgreSQL: you record access
attempts as durable rows (and optionally export them). FraiseQL gives you the hooks —
the `UserContext`, the operation name in resolver/authorizer context, and `fn_`
functions — to write those rows.

### 6.1 Audit log table

```sql
CREATE TABLE tb_audit_log (
    pk_audit_log     BIGSERIAL PRIMARY KEY,
    id               UUID NOT NULL DEFAULT gen_random_uuid(),
    occurred_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id          UUID NOT NULL,
    tenant_id        UUID,
    action           TEXT NOT NULL,            -- 'query' | 'mutation' | 'subscription'
    resource_type    TEXT NOT NULL,            -- 'Post', 'User', ...
    resource_id      UUID,
    operation_name   TEXT NOT NULL,
    authorized       BOOLEAN NOT NULL,
    fields_accessed  JSONB,
    error_code       TEXT,
    ip_address       INET,
    trace_id         UUID
);

CREATE INDEX idx_audit_user_time ON tb_audit_log (user_id, occurred_at DESC);
CREATE INDEX idx_audit_resource  ON tb_audit_log (resource_type, resource_id);
```

### 6.2 Writing audit rows

Record allow/deny from your `Authorizer` or inside a mutation `fn_` function. Example
JSONB payload your `fn_audit_log` might persist:

```json
{
  "occurredAt": "2026-01-15T10:30:45.123Z",
  "userId": "user-456",
  "action": "query",
  "resourceType": "Post",
  "resourceId": "post-789",
  "operationName": "GetUserPosts",
  "authorized": true,
  "fieldsAccessed": ["id", "title", "author"],
  "errorCode": null,
  "ipAddress": "203.0.113.45",
  "traceId": "trace-abc123"
}
```

A denied attempt records the failure mode:

```json
{
  "occurredAt": "2026-01-15T10:30:46.456Z",
  "userId": "user-456",
  "action": "mutation",
  "resourceType": "Post",
  "resourceId": "post-789",
  "operationName": "DeletePost",
  "authorized": false,
  "errorCode": "FORBIDDEN",
  "ipAddress": "203.0.113.45",
  "traceId": "trace-def456"
}
```

### 6.3 Querying the audit trail

```sql
-- Who accessed this sensitive record?
SELECT * FROM tb_audit_log
WHERE resource_type = 'User' AND resource_id = 'user-123'
ORDER BY occurred_at DESC;

-- Did authorization ever fail for this user?
SELECT * FROM tb_audit_log
WHERE user_id = 'user-456' AND authorized = false
ORDER BY occurred_at DESC;

-- What did anyone do in the last 24 hours?
SELECT * FROM tb_audit_log
WHERE occurred_at > now() - INTERVAL '1 day'
ORDER BY occurred_at DESC;

-- When was a sensitive field accessed?
SELECT * FROM tb_audit_log
WHERE fields_accessed @> '["ssn", "credit_card"]'
ORDER BY occurred_at DESC;
```

Make the table append-only with a `BEFORE UPDATE`/`BEFORE DELETE` trigger (or restricted
grants) if your compliance regime requires immutability.

---

## 7. Compliance & Security Standards

The same primitives map onto common compliance requirements.

### 7.1 GDPR

- **Right to erasure** — a `@fraiseql.mutation` guarded by `@requires_auth` (and an
  ownership check) calls an `fn_request_data_deletion` function that marks the record for
  deletion while preserving the audit trail.
- **Access logging** — every data access is recorded in `tb_audit_log` (Section 6).
- **Data portability** — an owner-scoped `@fraiseql.query` returning a `JSON` scalar
  exports the user's data from a `v_user_export` view.

```python
import fraiseql
from fraiseql.auth import requires_auth
from fraiseql.types import ID, JSON


@fraiseql.mutation
@requires_auth
async def request_data_deletion(info, user_id: ID) -> "DeletionSuccess":
    """Mark personal data for deletion (audit trail preserved)."""
    db = info.context["db"]
    return await db.execute_function("fn_request_data_deletion", {"user_id": user_id})


@fraiseql.query
@requires_auth
async def export_user_data(info, user_id: ID) -> JSON:
    """Export all data for the authenticated owner."""
    db = info.context["db"]
    return await db.find_one("v_user_export", id=user_id)
```

### 7.2 HIPAA

- **Access controls** — restrict PHI types to clinical roles with `@requires_role`/an
  `Authorizer`; enforce patient/provider row scoping with RLS on the underlying tables.
- **Field-level protection** — gate sensitive columns with `authorize_field`, or redact
  in the `v_` view so PHI never leaves PostgreSQL for unauthorized callers.
- **Audit trail** — log all PHI access to `tb_audit_log`; retain per policy.
- **Transport/at-rest** — terminate TLS at the app, encrypt sensitive columns in
  PostgreSQL (e.g. `pgcrypto`).

```python
@fraiseql.type(
    sql_source="v_patient_record",
    jsonb_column="data",
    authorize_fields=["medical_history"],
)
class PatientRecord:
    id: ID
    patient_id: ID
    medical_history: str
```

### 7.3 PCI-DSS

- **Never log cardholder data** — keep card numbers out of audit payloads.
- **Field redaction** — show only a masked PAN to non-admins via the view's `data` JSONB
  (Section 4.3), or gate `card_number` with `authorize_field`.
- **Tokenization** — store a token reference (the `ApiKey`/`HashSHA256`-style scalars and
  `pgcrypto` help), not the raw card data.

```sql
CREATE VIEW v_payment AS
SELECT
    p.id,
    jsonb_build_object(
        'id', p.id,
        'cardNumber',
            CASE
                WHEN current_setting('app.is_super_admin', true)::boolean
                    THEN p.card_number
                ELSE '**** **** **** ' || right(p.card_number, 4)
            END
    ) AS data
FROM tb_payment p;
```

---

## 8. Security Best Practices

### 8.1 Authorization

**DO:**

- ✅ Gate sensitive operations with `@requires_*` and/or a central `Authorizer`.
- ✅ Enforce row scoping with PostgreSQL RLS — it survives even a direct DB session.
- ✅ Derive every decision from `info.context["user"]`, never from client-supplied claims.
- ✅ Keep policy in one testable `Authorizer` and unit-test it headless.
- ✅ Test authorization with multiple roles, including the unauthenticated case.

**DON'T:**

- ❌ Rely on client-side authorization checks.
- ❌ Trust user-provided role/organization/tenant claims from the request body.
- ❌ Use overly permissive defaults — fail closed.
- ❌ Hardcode user IDs; always read from the `UserContext`.

### 8.2 Field Protection

**DO:**

- ✅ Redact PII/PHI/financial fields at the view layer when they should never leave the DB.
- ✅ Gate computed-field access with `authorize_field` + `authorize_fields=[...]`.
- ✅ Test field access with unauthorized users; confirm bypass paths fail closed.
- ✅ Document which fields are protected and why.

**DON'T:**

- ❌ Rely on field gates instead of RLS for row-level secrets.
- ❌ Return misleading substitute values where a clear denial is expected.
- ❌ Skip protection for "less important" data.

### 8.3 Audit Logging

**DO:**

- ✅ Record access (allow and deny) for sensitive resources.
- ✅ Retain audit rows per your compliance requirements.
- ✅ Make the audit table append-only; alert on suspicious patterns.

**DON'T:**

- ❌ Log secrets or cardholder data in the audit trail.
- ❌ Allow audit rows to be silently modified or deleted.

---

## 9. Security Configuration

Security in v1 is configured through `create_fraiseql_app(...)` keyword arguments,
`FraiseQLConfig` (pydantic, `FRAISEQL_` env vars), and PostgreSQL itself — not a TOML
file or a separate config object.

### 9.1 Application wiring

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User, Post],
    queries=[users, user],
    mutations=[create_post],
    auth=MyProvider(),              # authentication
    authorizer=PolicyAuthorizer(),  # global operation authorization
    authorization_cache=...,        # optional DecisionCache
    production=True,                # disables the playground / introspection conveniences
)
```

`create_fraiseql_app` has **no** `middleware=` kwarg — add FastAPI middleware (CORS,
security headers, rate limiting) with `app.add_middleware(...)` on the returned app, or
pass your own app via `create_fraiseql_app(app=...)`. The `fraiseql.security` module also
ships rate-limiting, CSRF, and security-header middleware helpers.

### 9.2 Environment variables

Authentication and related settings live in `FraiseQLConfig` and are overridable via
`FRAISEQL_`-prefixed environment variables, for example:

```bash
# Provider selection: "auth0" | "custom" | "none" (default "none")
FRAISEQL_AUTH_PROVIDER=auth0
FRAISEQL_AUTH0_DOMAIN=your-tenant.auth0.com
FRAISEQL_AUTH0_API_IDENTIFIER=https://api.example.com

# Database connection (PostgreSQL); enforce TLS + scram-sha-256 in pg_hba.conf
FRAISEQL_DATABASE_URL=postgresql://user@host/db?sslmode=require
```

Database connection authentication (SCRAM-SHA-256, TLS) is configured in PostgreSQL's
`pg_hba.conf` and the `database_url`/`sslmode`, not in FraiseQL code.

---

## 10. Troubleshooting Security Issues

### 10.1 User getting "Access Denied"

1. **Authenticated?** Confirm `info.context["user"]` is a `UserContext` — a missing user
   denies with `extensions.code = "UNAUTHENTICATED"`.
2. **Right role/permission?** Inspect `user.roles` / `user.permissions`; a
   `requires_role("admin")` gate denies with `FORBIDDEN` and an `extensions.required_role`.
3. **Authorizer decision?** Log the `AuthorizationDecision` for the operation — an
   `Authorizer` that *raises* fails closed (deny) by design.
4. **Owns the resource?** For ownership rules, compare `user.user_id` against the row's
   owner column.
5. **Audit row?** Query `tb_audit_log WHERE user_id = ... AND authorized = false`.

### 10.2 User seeing data they shouldn't see

1. **RLS enabled?** `SELECT relrowsecurity FROM pg_class WHERE relname = 'tb_post';` — and
   confirm a policy exists with `SELECT * FROM pg_policies WHERE tablename = 'tb_post';`.
2. **Session GUC set?** Verify `info.context` carries `tenant_id`/`user_id` so
   `SET LOCAL app.tenant_id` is emitted — an unset GUC with a one-arg `current_setting`
   would error; with the two-arg form it falls to a default.
3. **Field gate present?** Check the field is listed in `authorize_fields` or wrapped with
   `authorize_field`, and that the view redacts it where required.
4. **Bypass path?** Confirm the operation/field gate is re-applied on the relevant
   Rust/turbo/APQ chokepoint (these are the historical fail-open risk).

---

## 11. Summary: Security Architecture

```text
┌──────────────────────────────────────────┐
│ User Request (with JWT token)            │
└────────────┬─────────────────────────────┘
             │
      ┌──────▼──────┐
      │ Authenticate│ AuthProvider validates JWT, builds UserContext
      │  (Python)   │
      └──────┬──────┘
             │
      ┌──────▼──────────────┐
      │ Operation Authz     │ requires_* decorators / Authorizer
      │ (runtime, Python)   │ — fail closed, re-applied on bypass paths
      └──────┬──────────────┘
             │
      ┌──────▼──────────────┐
      │ Row-Level Security  │ PostgreSQL policies read SET LOCAL app.* GUCs
      │ (PostgreSQL)        │
      └──────┬──────────────┘
             │
      ┌──────▼──────────────┐
      │ Field Authorization │ authorize_field / authorize_fields / view redaction
      │ (runtime + SQL)     │
      └──────┬──────────────┘
             │
      ┌──────▼──────────────┐
      │ Audit Log           │ durable rows in tb_audit_log (append-only)
      └──────┬──────────────┘
             │
      ┌──────▼──────────────┐
      │ Response            │ Authorized data to client
      └─────────────────────┘
```

---

FraiseQL v1 provides defense-in-depth: authentication (`AuthProvider`), operation
authorization (`requires_*` / `Authorizer`, fail-closed across bypass paths), PostgreSQL
Row-Level Security for row scoping, field-level authorization and view-layer redaction for
sensitive columns, and PostgreSQL-backed audit logging. Enforcement is layered across the
Python runtime and the database.

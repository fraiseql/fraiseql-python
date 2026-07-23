<!-- Skip to main content -->
---
title: Authorization & RBAC Quick Start (5 Minutes)
description: Get field-level and operation-level authorization working in 5 minutes.
keywords: ["debugging", "implementation", "best-practices", "deployment", "tutorial"]
tags: ["documentation", "reference"]
---

# Authorization & RBAC Quick Start (5 Minutes)

Get field-level and operation-level authorization working in 5 minutes with FraiseQL's PostgreSQL-backed runtime.

## Prerequisites

- Basic FraiseQL project setup (see [Getting Started](../../))
- Understanding of roles (admin, user, guest)
- Knowledge of your authentication provider (see [Auth Provider Selection](../integrations/authentication/provider-selection-guide.md))

## Step 1: Define Field-Level Authorization Rules (1 minute)

Protect individual fields with `@authorize_field`. The permission check is any callable
that receives the GraphQL `info` (and optionally the resolved `root` object) and returns
a `bool`. Combine checks with `any_permission` (OR) or `combine_permissions` (AND).

```python
# users_service/schema.py
import fraiseql
from fraiseql import field
from fraiseql.security import authorize_field, any_permission
from fraiseql.types import ID

def is_admin(info) -> bool:
    user = info.context.get("user")
    return bool(user and user.has_role("admin"))

@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str

    @field
    @authorize_field(any_permission(
        is_admin,
        # Owner: the requesting user is viewing their own record
        lambda info, root: info.context.get("user_id") == root.id,
    ))
    def email(self) -> str:
        return self._email

    @field
    @authorize_field(is_admin)
    def salary(self) -> float:
        return self._salary

    @field
    @authorize_field(is_admin)
    def role(self) -> str:
        return self._role

@fraiseql.type(sql_source="v_order", jsonb_column="data")
class Order:
    id: ID
    user_id: ID

    @field
    @authorize_field(any_permission(
        is_admin,
        # Owner: the order belongs to the requesting user
        lambda info, root: info.context.get("user_id") == root.user_id,
    ))
    def total(self) -> float:
        return self._total
```

---

## Step 2: Add Authorization to Operations (1 minute)

There are two complementary ways to gate whole queries and mutations.

### Option A: Role/permission decorators (simple)

For straightforward role or permission checks, wrap the resolver with the auth
decorators. They read `info.context["user"]` (a `UserContext`) and raise a
`GraphQLError` when the check fails.

```python
# users_service/schema.py (continued)
import fraiseql
from fraiseql.auth import requires_auth, requires_role
from fraiseql.auth.decorators import requires_any_role

@fraiseql.query
@requires_any_role("admin", "user")
async def users(info, limit: int = 10) -> list[User]:
    """List users - requires admin or user role."""
    db = info.context["db"]
    return await db.find("v_user", limit=limit)

@fraiseql.query
@requires_role("admin")
async def all_users(info, limit: int = 100) -> list[User]:
    """List all users with sensitive data - admin only."""
    db = info.context["db"]
    return await db.find("v_user", limit=limit)

@fraiseql.query
@requires_auth  # Must be authenticated; user_id flows from context
async def my_orders(info, limit: int = 50) -> list[Order]:
    """List the current user's orders."""
    db = info.context["db"]
    return await db.find("v_order", user_id=info.context["user_id"], limit=limit)
```

### Option B: An `Authorizer` (centralized policy)

For richer or centralized policy, implement the `Authorizer` protocol and attach it
per-operation with `@fraiseql.query(authorizer=...)` (also available on
`@fraiseql.mutation` and `@fraiseql.subscription`), or globally via
`create_fraiseql_app(authorizer=...)`. An allow decision can carry `filters`, which are
AND-ed into the read path's mandatory filters for row scoping.

```python
import fraiseql
from fraiseql.security import Authorizer, AuthorizationDecision

class RoleAuthorizer:
    """Implements the Authorizer protocol (structural; no base class required)."""

    def __init__(self, *, allowed_roles: set[str]) -> None:
        self._allowed_roles = allowed_roles

    async def authorize_operation(
        self,
        *,
        context: dict,
        operation_type: str,
        operation_name: str,
        arguments: dict,
    ) -> AuthorizationDecision:
        user = context.get("user")
        if user and any(user.has_role(r) for r in self._allowed_roles):
            return AuthorizationDecision.allow()
        return AuthorizationDecision.deny(message="Operation not authorized")

admin_only: Authorizer = RoleAuthorizer(allowed_roles={"admin"})

@fraiseql.query(authorizer=admin_only)
async def all_users(info, limit: int = 100) -> list[User]:
    """List all users with sensitive data - admin only."""
    db = info.context["db"]
    return await db.find("v_user", limit=limit)
```

---

## Step 3: Wire Up Authentication and Build the App (1 minute)

There is no config file and no compile step. You configure FraiseQL by passing keyword
arguments to `create_fraiseql_app(...)` (or building a `FraiseQLConfig`); the schema is
assembled in memory at app startup. Roles and permissions come from the authenticated
`UserContext`, which your auth provider populates from JWT claims.

```python
# users_service/app.py
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.auth import Auth0Config, Auth0Provider

# Validate tokens against your Auth0 tenant (claims become the UserContext)
auth = Auth0Provider(Auth0Config(
    domain="myapp.auth0.com",
    api_identifier="https://api.myapp.com",
))

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User, Order],
    queries=[users, all_users, my_orders],
    auth=auth,
    # Attach a global default operation authorizer (optional; see Step 2 Option B)
    authorizer=admin_only,
    production=True,
)
```

Run it with any ASGI server, for example `uvicorn users_service.app:app`.

### Row scoping with PostgreSQL RLS

For tenant or per-user data isolation, push enforcement into the database with
Row-Level Security. FraiseQL's CQRS repository issues `SET LOCAL app.tenant_id = …`
(and `app.user_id`, `app.is_super_admin`, …) per transaction from `info.context`, so
your RLS policies see the current principal:

```sql
ALTER TABLE tb_order ENABLE ROW LEVEL SECURITY;

CREATE POLICY order_tenant_isolation ON tb_order
    USING (fk_tenant = current_setting('app.tenant_id')::uuid);
```

Have your `context_getter` place `tenant_id` (and `user_id`) into `info.context`, and
every read/write is automatically scoped — no application-side filtering required.

---

## Step 4: Run and Test (2 minutes)

```bash
# Start the FastAPI app (schema is built in memory at startup)
uvicorn users_service.app:app --port 8000

# Test: Query as admin (should see all fields)
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin_token>" \
  -d '{
    "query": "{ users(limit: 1) { id name email salary } }"
  }'

# Expected response (admin sees everything):
# {
#   "data": {
#     "users": [
#       {
#         "id": "1",
#         "name": "Alice",
#         "email": "alice@example.com",
#         "salary": 100000
#       }
#     ]
#   }
# }

# Test: Query as regular user (should NOT see salary)
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <user_token>" \
  -d '{
    "query": "{ users(limit: 1) { id name email salary } }"
  }'

# Expected response (user blocked from the salary field):
# {
#   "errors": [
#     {
#       "message": "Not authorized to access field 'salary'",
#       "path": ["users", 0, "salary"],
#       "extensions": {
#         "code": "FORBIDDEN"
#       }
#     }
#   ],
#   "data": {
#     "users": [
#       {
#         "id": "...",
#         "name": "Alice",
#         "email": "alice@example.com",
#         "salary": null
#       }
#     ]
#   }
# }
```

---

## That's It

You now have role-based, field-level, and operation-level authorization.

### Next Steps

- Set up an authentication provider such as Auth0 (see [Auth Provider Selection](../integrations/authentication/provider-selection-guide.md))
- Configure audit logging for compliance (see [Observability Guide](../guides/observability.md))
- Implement attribute-based access control (ABAC) for fine-grained control (see [RBAC Patterns](./patterns.md#role-based-access-control))
- Cache authorization decisions with `AuthorizationCacheConfig` for hot paths

### Common Issues

**"Operation not authorized"**
→ Token missing or expired, or the principal lacks the required role/permission. Check the
`Authorization: Bearer <token>` header and verify the JWT claims populate the `UserContext`.

**"Field shows null instead of an error"**
→ The field resolver was denied. Confirm the `@authorize_field` check reads the right value
from `info.context`, and that your `context_getter` set `user`/`user_id` correctly.

**"Same token works in dev, fails in production"**
→ Verify your provider config (for example the Auth0 `domain`/`api_identifier`) is correct in
production, and that CORS headers are configured on `create_fraiseql_app(...)`.

**"Authorization too slow"**
→ Enable decision caching by passing `authorization_cache=AuthorizationCacheConfig(...)` to
`create_fraiseql_app(...)`, or read roles directly from JWT claims instead of an external call.

See [Troubleshooting](./troubleshooting.md) for the complete troubleshooting guide.

---

## See Also

- **[Auth Provider Selection](../integrations/authentication/provider-selection-guide.md)** - Choosing your auth provider
- **[Observability](./observability.md)** - Logging and monitoring authorization
- **[RBAC Patterns](./patterns.md#role-based-access-control)** - Real-world RBAC examples

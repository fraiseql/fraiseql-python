---
title: FraiseQL Authentication & Authorization
description: Overview of FraiseQL v1 authentication and authorization — Auth0, native, and custom JWT providers, resolver decorators, operation/field authorization, and PostgreSQL row-level security, all running inside your FastAPI app.
keywords: ["fraiseql", "authentication", "authorization", "auth0", "jwt", "rbac", "row-level-security"]
tags: ["documentation", "integrations", "authentication"]
---

# FraiseQL Authentication & Authorization

This section covers how to authenticate users and authorize operations in a
FraiseQL v1 application. FraiseQL is a Python runtime GraphQL framework for
PostgreSQL, served over FastAPI. **Authentication and authorization run inside
your Python/FastAPI app** — there is no separate auth server to deploy.

At a high level you choose an **auth provider** (Auth0, the built-in native
provider, or a custom one you implement), and FraiseQL puts an authenticated
`UserContext` into `info.context["user"]` for every resolver. You then enforce
access with decorators, an operation-level `Authorizer`, field authorization,
and PostgreSQL Row-Level Security (RLS).

## What you should already know

- OAuth 2.0 / OIDC and JWT validation basics (if you use Auth0 or another issuer)
- GraphQL resolvers and how FraiseQL types/queries/mutations are defined
- PostgreSQL — especially Row-Level Security if you need multi-tenancy

**Required tools:**

- FraiseQL v1 installed (`pip install fraiseql` / `uv add fraiseql`)
- A PostgreSQL 14+ database
- Your chosen identity provider's console (for Auth0 or another OIDC issuer)

---

## Provider model

FraiseQL has exactly **three provider modes**, selected by
`auth_provider` (a `Literal["auth0", "custom", "none"]`, default `"none"`):

| Mode | Provider class | When to use |
|------|----------------|-------------|
| `"auth0"` | `Auth0Provider` / `Auth0ProviderWithRevocation` | Auth0 (or any OIDC issuer fronted by Auth0) |
| `"custom"` | a subclass of the `AuthProvider` ABC (e.g. `NativeAuthProvider`, `RustCustomJWTProvider`, or your own) | username/password, or any JWT issuer you validate yourself |
| `"none"` | — | no authentication (development / public APIs) |

There is **no** per-vendor provider class (no `GoogleProvider`,
`KeycloakProvider`, or `OidcProvider`). To use Google, Keycloak, or any other
OIDC issuer you have two honest paths:

1. **Front it with Auth0** (Auth0 as the broker) and use `auth_provider="auth0"`.
2. **Set `auth_provider="custom"`** and implement an `AuthProvider` subclass that
   validates that issuer's JWTs against its JWKS / issuer / audience.

All providers implement the `AuthProvider` ABC from `fraiseql.auth`:

```python
from typing import Any

from fraiseql.auth import AuthProvider, UserContext


class MyJWTProvider(AuthProvider):
    async def validate_token(self, token: str) -> dict[str, Any]:
        # Verify signature/issuer/audience and return the decoded claims.
        ...

    async def get_user_from_token(self, token: str) -> UserContext:
        payload = await self.validate_token(token)
        return UserContext(
            user_id=payload["sub"],
            email=payload.get("email"),
            roles=payload.get("roles", []),
            permissions=payload.get("permissions", []),
        )
```

`UserContext` carries `user_id`, optional `email`/`name`, `roles`,
`permissions`, and a free-form `metadata` dict, with helpers
`has_role`, `has_permission`, `has_any_role`, and `has_any_permission`.

---

## Wiring auth into your app

Auth is configured through `create_fraiseql_app(...)` kwargs (or, equivalently,
through `FraiseQLConfig` / `FRAISEQL_*` environment variables). There is no
`fraiseql.toml` and no `[auth]` config block.

### Auth0

```python
import fraiseql
from fraiseql.auth import Auth0Config
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users, user],
    mutations=[create_user],
    auth=Auth0Config(
        domain="myapp.auth0.com",
        api_identifier="https://api.myapp.com",
    ),
    production=True,
)
```

Equivalent environment configuration:

```bash
FRAISEQL_AUTH_PROVIDER=auth0
FRAISEQL_AUTH0_DOMAIN=myapp.auth0.com
FRAISEQL_AUTH0_API_IDENTIFIER=https://api.myapp.com
# FRAISEQL_AUTH0_ALGORITHMS defaults to ["RS256"]
```

### Custom / native provider

Pass any `AuthProvider` instance as `auth=...`:

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users, user],
    auth=MyJWTProvider(),
    production=True,
)
```

The built-in `NativeAuthProvider` (in `fraiseql.auth.native`) supports
username/password auth with a FastAPI router for register/login/refresh/logout
flows. See the [native auth provider guide](./scram.md) for the
PostgreSQL connection-auth story, and the [API reference](./api-reference.md)
for endpoint details.

### Run the app

FraiseQL apps are ordinary ASGI/FastAPI apps — run them with Uvicorn:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

---

## Authorizing operations

Once `info.context["user"]` holds a `UserContext`, you have several enforcement
points. They compose — use whichever fits the layer of the check.

### Resolver decorators

`requires_auth`, `requires_permission`, and `requires_role` (plus
`requires_any_role` / `requires_any_permission`) gate a single resolver:

```python
import fraiseql
from fraiseql.auth import requires_auth, requires_permission, requires_role


@fraiseql.query
@requires_auth
async def me(info) -> User:
    user = info.context["user"]  # guaranteed authenticated
    db = info.context["db"]
    return await db.find_one("v_user", id=user.user_id)


@fraiseql.mutation
@requires_permission("users:write")
async def create_user(info, input: CreateUserInput) -> CreateUserSuccess | CreateUserError:
    ...


@fraiseql.mutation
@requires_role("admin")
async def delete_user(info, id: ID) -> DeleteUserSuccess | DeleteUserError:
    ...
```

A failed check raises a GraphQL error whose `extensions.code` is
`UNAUTHENTICATED` (missing user) or `FORBIDDEN` (insufficient role/permission).

### Operation-level `Authorizer`

For policy that lives outside the resolver, supply an `Authorizer` — a small
object that decides whether a top-level operation may run. Attach it per
operation or globally:

```python
from fraiseql.security import AuthorizationDecision


class TenantAuthorizer:
    async def authorize_operation(
        self, *, context, operation_type, operation_name, arguments
    ) -> AuthorizationDecision:
        user = context.get("user")
        if user is None:
            return AuthorizationDecision.deny(message="Authentication required")
        return AuthorizationDecision.allow()


# Per operation:
@fraiseql.query(authorizer=TenantAuthorizer())
async def tenant_report(info) -> list[Report]:
    ...


# Globally (also works on build_fraiseql_schema):
app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[Report],
    queries=[tenant_report],
    authorizer=TenantAuthorizer(),
)
```

The framework enforces decisions **fail-closed**: if the authorizer raises, the
operation is denied. `AuthorizationDecision.allow(filters=...)` can also carry
row-scoping filters that are AND-ed into the read path. An optional
`authorization_cache` can memoize decisions for pure-function authorizers.

### Field authorization

Gate individual fields with `authorize_field` (composable via
`combine_permissions` / `any_permission`), or list them on the type via
`@fraiseql.type(..., authorize_fields=...)`:

```python
from fraiseql.security import authorize_field


@authorize_field(lambda info: info.context.get("user") is not None)
async def email(user: User, info) -> str:
    return user.email
```

### Row-Level Security (multi-tenancy)

For tenant isolation, enforce it in PostgreSQL with RLS. FraiseQL's CQRS
repository sets session GUCs from the request context: when `info.context`
carries `tenant_id` (and `user_id`, `is_super_admin`, …), it issues
`SET LOCAL app.tenant_id = …` per transaction, so your RLS policies see the
current tenant:

```sql
ALTER TABLE tb_invoice ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON tb_invoice
    USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

Reads can additionally pass `mandatory_filters={"tenant_id": ...}` to
`db.find` / `db.count`.

---

## Token revocation

For Auth0 (or native) deployments that need logout/blacklisting, FraiseQL ships
a revocation subsystem in `fraiseql.auth`: `TokenRevocationService` plus an
`InMemoryRevocationStore` or `PostgreSQLRevocationStore` (configured by
`RevocationConfig`). `Auth0ProviderWithRevocation` wires revocation checks into
Auth0 token validation. Revocation behavior is also controllable via
`FRAISEQL_REVOCATION_*` settings.

---

## Documentation in this section

| Document | Purpose |
|----------|---------|
| [Provider selection guide](./provider-selection-guide.md) | Choosing between Auth0, native, and custom providers |
| [Auth0 setup](./setup-auth0.md) | Configure Auth0 as your provider |
| [Google OAuth setup](./setup-google-oauth.md) | Use Google (via Auth0 or a custom provider) |
| [Keycloak setup](./setup-keycloak.md) | Use Keycloak (via Auth0 or a custom provider) |
| [SCRAM / database connection auth](./scram.md) | PostgreSQL `scram-sha-256` connection authentication |
| [API reference](./api-reference.md) | Auth endpoints, request/response shapes, error codes |
| [Deployment](./deployment.md) | Deploying an authenticated FraiseQL app |
| [Monitoring](./monitoring.md) | Logging, metrics, and health checks for auth |
| [Troubleshooting](./troubleshooting.md) | Common auth issues and fixes |
| [Security checklist](./security-checklist.md) | Pre-production security review |

---

## Security considerations

- **Always use HTTPS / TLS** in production (and `sslmode` on the database URL).
- **Never expose secrets** in client code or commit them to source control.
- **Validate issuer, audience, and signature** for every JWT.
- **Handle token expiry** gracefully; use refresh where the provider supports it.
- **Enforce tenant isolation in the database** (RLS), not only in resolvers.
- **Prefer fail-closed authorizers** — the framework already denies on error.

See the [Security checklist](./security-checklist.md) for the full list.

---

## See also

- [Production Deployment](../../guides/production-deployment.md) — deploying an authenticated app
- [Security Model](../../architecture/security/security-model.md) — authorization architecture
- [Monitoring](./monitoring.md) — observing authentication events
- [Troubleshooting](./troubleshooting.md) — common authentication issues

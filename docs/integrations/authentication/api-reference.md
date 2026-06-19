---

title: FraiseQL Authentication API Reference
description: Complete reference for FraiseQL's Python authentication and authorization API.
keywords: ["framework", "authentication", "authorization", "providers", "decorators", "api"]
tags: ["documentation", "reference"]
---

# FraiseQL Authentication API Reference

FraiseQL's authentication and authorization run **inside your FastAPI app, in
Python**. There is no Rust auth router and no separate auth server: you pass a
provider (or configuration) to `create_fraiseql_app(...)`, and FraiseQL resolves
the bearer token on each GraphQL request into a `UserContext` available at
`info.context["user"]`. Denied access surfaces as a GraphQL error whose
`extensions.code` is `UNAUTHENTICATED` or `FORBIDDEN` — never an out-of-band HTTP
status from a router you do not control.

This page documents the public Python surface. For step-by-step setup, see the
[Auth0](./setup-auth0.md), [Google OAuth](./setup-google-oauth.md), and
[Keycloak](./setup-keycloak.md) guides.

---

## Providers

A provider validates an incoming token and turns it into a `UserContext`. All
providers subclass `AuthProvider`.

### `AuthProvider` (base ABC)

```python
from fraiseql.auth import AuthProvider
```

`AuthProvider` (`src/fraiseql/auth/base.py`) is the abstract base every provider
implements. Subclass it to support any OIDC/JWT issuer.

| Method | Signature | Description |
|--------|-----------|-------------|
| `validate_token` | `async validate_token(self, token: str) -> dict` | Validate the token and return its decoded payload. Raise `AuthenticationError` on failure. **Abstract.** |
| `get_user_from_token` | `async get_user_from_token(self, token: str) -> UserContext` | Build a `UserContext` for the bearer of `token`. **Abstract.** |
| `refresh_token` | `async refresh_token(self, refresh_token: str) -> tuple[str, str]` | Optional. Returns `(new_access_token, new_refresh_token)`. Raises `NotImplementedError` by default. |
| `revoke_token` | `async revoke_token(self, token: str) -> None` | Optional. Raises `NotImplementedError` by default. |

```python
from typing import Any

import jwt

from fraiseql.auth import AuthProvider, UserContext


class CustomJWTProvider(AuthProvider):
    def __init__(self, secret: str) -> None:
        self.secret = secret

    async def validate_token(self, token: str) -> dict[str, Any]:
        return jwt.decode(token, self.secret, algorithms=["HS256"])

    async def get_user_from_token(self, token: str) -> UserContext:
        payload = await self.validate_token(token)
        return UserContext(
            user_id=payload["sub"],
            email=payload.get("email"),
            roles=payload.get("roles", []),
            permissions=payload.get("permissions", []),
        )
```

Pass any provider instance to `create_fraiseql_app(auth=...)`.

### `Auth0Provider` / `Auth0Config`

```python
from fraiseql.auth import Auth0Config, Auth0Provider
```

`Auth0Provider` (`src/fraiseql/auth/auth0.py`) validates Auth0-issued JWTs.
It fetches and caches the tenant JWKS, validates with `RS256` by default, and
extracts roles/permissions from Auth0 claims.

```python
provider = Auth0Provider(
    domain="myapp.auth0.com",
    api_identifier="https://api.myapp.com",
    algorithms=["RS256"],   # default
    cache_jwks=True,        # default
)
```

`Auth0Config` is a plain configuration holder you can pass to
`create_fraiseql_app(auth=...)` (FraiseQL builds the provider from it):

```python
config = Auth0Config(
    domain="myapp.auth0.com",
    api_identifier="https://api.myapp.com",
    client_id=None,         # optional, Management API only
    client_secret=None,     # optional, Management API only
    algorithms=None,        # defaults to ["RS256"]
)
```

### `Auth0ProviderWithRevocation`

```python
from fraiseql.auth import Auth0ProviderWithRevocation
```

`Auth0ProviderWithRevocation` (`src/fraiseql/auth/auth0_with_revocation.py`) is
an `Auth0Provider` mixed with `TokenRevocationMixin`, so validated tokens are
additionally checked against a revocation store (see
[Token revocation](#token-revocation)).

### `NativeAuthProvider`

```python
from fraiseql.auth.native import NativeAuthProvider, TokenManager
```

`NativeAuthProvider` (`src/fraiseql/auth/native/provider.py`) implements
PostgreSQL-backed username/password authentication using its own `TokenManager`
and a `psycopg` connection pool. It ships with a FastAPI router
(`src/fraiseql/auth/native/router.py`, tag `"auth"`) exposing endpoints such as
`/register`, `/login`, `/refresh`, `/me`, and `/logout`.

```python
provider = NativeAuthProvider(
    token_manager=token_manager,   # TokenManager instance
    db_pool=pool,                  # AsyncConnectionPool
    schema="public",               # default
)
```

### `RustCustomJWTProvider`

```python
from fraiseql.auth.rust_provider import RustCustomJWTProvider
```

`RustCustomJWTProvider` (`src/fraiseql/auth/rust_provider.py`) validates JWTs
from a custom issuer using the optional `fraiseql_rs` extension for faster
validation. It is still a Python-facing `AuthProvider`.

```python
provider = RustCustomJWTProvider(
    issuer="https://issuer.example.com/",
    audience="https://api.myapp.com",
    jwks_url="https://issuer.example.com/.well-known/jwks.json",  # must be HTTPS
    roles_claim="roles",            # default
    permissions_claim="permissions",  # default
)
```

> Any OIDC/JWT issuer (Google, Keycloak, Okta, …) is supported through one of two
> honest paths: front it with Auth0 and use `Auth0Provider`, or set
> `auth_provider="custom"` and implement an `AuthProvider` subclass that validates
> that issuer's tokens via its JWKS/issuer/audience. There is no dedicated
> `GoogleProvider`, `KeycloakProvider`, or `OidcProvider` class.

---

## `UserContext`

```python
from fraiseql.auth import UserContext
```

`UserContext` (`src/fraiseql/auth/base.py`) is the authenticated principal
available at `info.context["user"]` in every resolver.

```python
UserContext(
    user_id: str,
    email: str | None = None,
    name: str | None = None,
    roles: list[str] = [],
    permissions: list[str] = [],
    metadata: dict[str, Any] = {},
)
```

| Method | Returns | Description |
|--------|---------|-------------|
| `has_role(role)` | `bool` | User has the given role. |
| `has_permission(permission)` | `bool` | User has the given permission. |
| `has_any_role(roles)` | `bool` | User has at least one of `roles`. |
| `has_any_permission(permissions)` | `bool` | User has at least one of `permissions`. |
| `has_all_roles(roles)` | `bool` | User has every role in `roles`. |
| `has_all_permissions(permissions)` | `bool` | User has every permission in `permissions`. |

```python
@fraiseql.query
async def my_profile(info) -> User | None:
    user = info.context.get("user")
    if user is None or not user.has_role("member"):
        return None
    db = info.context["db"]
    return await db.find_one("v_user", id=user.user_id)
```

---

## Resolver decorators

```python
from fraiseql.auth import requires_auth, requires_permission, requires_role
from fraiseql.auth.decorators import requires_any_permission, requires_any_role
```

These decorators (`src/fraiseql/auth/decorators.py`) guard a resolver by reading
`info.context["user"]`. A missing/invalid user raises a `GraphQLError` with
`extensions.code = "UNAUTHENTICATED"`; an authenticated-but-unauthorized user
raises one with `extensions.code = "FORBIDDEN"`.

| Decorator | Signature | Guard |
|-----------|-----------|-------|
| `requires_auth` | `@requires_auth` (bare) | A `UserContext` is present. |
| `requires_permission` | `@requires_permission("posts:write")` | `user.has_permission(...)`. |
| `requires_role` | `@requires_role("admin")` | `user.has_role(...)`. |
| `requires_any_permission` | `@requires_any_permission("a", "b")` | `user.has_any_permission([...])`. |
| `requires_any_role` | `@requires_any_role("admin", "moderator")` | `user.has_any_role([...])`. |

```python
@fraiseql.mutation
@requires_permission("posts:write")
async def create_post(info, input: CreatePostInput) -> CreatePostSuccess | CreatePostError:
    db = info.context["db"]
    result = await db.execute_function("fn_create_post", {...})
    ...
```

---

## Operation authorization

For richer, context-driven decisions (row scoping, multi-tenant rules), supply an
`Authorizer` instead of, or in addition to, the decorators above.

```python
from fraiseql.security import Authorizer, AuthorizationDecision
```

`Authorizer` and `AuthorizationDecision` live in
`src/fraiseql/security/authorization.py`.

### `Authorizer`

`Authorizer` is a structural protocol — implement a single method (sync or async):

```python
async def authorize_operation(
    self,
    *,
    context: dict[str, Any],
    operation_type: str,    # "query" | "mutation" | "subscription"
    operation_name: str,
    arguments: dict[str, Any],
) -> AuthorizationDecision | bool:
    ...
```

Return `True`/`False` (sugar) or an `AuthorizationDecision`. Enforcement is
**fail-closed**: if no authorizer is configured the operation is allowed, but if
your authorizer raises (anything other than a `GraphQLError`) the operation is
**denied**, and the raw exception is logged, never surfaced to the client.

### `AuthorizationDecision`

`AuthorizationDecision` is an immutable value with two constructors:

| Constructor | Effect |
|-------------|--------|
| `AuthorizationDecision.allow(*, filters=None)` | Allow. Optional `filters` are AND-ed into the repository's `mandatory_filters` on the read path (ignored on mutations). |
| `AuthorizationDecision.deny(*, code="FORBIDDEN", message=None)` | Deny. `code` is surfaced as `extensions.code`. |

```python
class TenantAuthorizer:
    async def authorize_operation(self, *, context, operation_type, operation_name, arguments):
        user = context.get("user")
        if user is None:
            return AuthorizationDecision.deny(code="UNAUTHENTICATED")
        tenant_id = context.get("tenant_id")
        if tenant_id is None:
            return AuthorizationDecision.deny()
        # Scope every read to the caller's tenant.
        return AuthorizationDecision.allow(filters={"tenant_id": tenant_id})
```

Attach an authorizer per operation or globally:

```python
@fraiseql.query(authorizer=TenantAuthorizer())
async def documents(info) -> list[Document]:
    ...

# Or as the global default for every operation:
app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[Document],
    queries=[documents],
    authorizer=TenantAuthorizer(),
)
```

`@fraiseql.mutation(authorizer=...)` and `@fraiseql.subscription(authorizer=...)`
work the same way. A per-operation authorizer overrides the global default.
`create_fraiseql_app(..., authorization_cache=...)` (and
`build_fraiseql_schema(authorizer=...)`) are also available; caching is opt-in
because always-evaluating is the safe default.

---

## Field authorization

Gate individual fields with `authorize_field` and the combinators in
`src/fraiseql/security/field_auth.py`.

```python
from fraiseql.security import authorize_field, any_permission, combine_permissions
```

| Symbol | Signature | Description |
|--------|-----------|-------------|
| `authorize_field` | `authorize_field(permission_check, *, error_message=None)` | Decorator wrapping a field resolver; runs `permission_check(info, ...)` first and denies with a `FieldAuthorizationError` if it returns falsy. |
| `any_permission` | `any_permission(*checks)` | Combine checks with **OR** — passes if any check passes. |
| `combine_permissions` | `combine_permissions(*checks)` | Combine checks with **AND** — passes only if all checks pass. |

A *check* is any callable taking `info` (and optionally `root`) that returns a
`bool` or an `AuthorizationDecision` (sync or async).

```python
@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str

    @fraiseql.field
    @authorize_field(any_permission(
        lambda info: info.context.get("is_admin", False),
        lambda info, root: info.context.get("user_id") == root.id,
    ))
    def email(self) -> str:
        return self._email
```

You can also list fields to gate automatically against the configured
`Authorizer` via the type decorator:

```python
@fraiseql.type(sql_source="v_user", jsonb_column="data", authorize_fields=["email", "phone"])
class User:
    id: ID
    email: str
    phone: str
```

Each listed field is checked with `operation_type="field"` and
`operation_name="User.email"` (etc.) before its resolver runs. This is a no-op
unless an authorizer is configured.

---

## Token revocation

For stateful logout / "revoke all sessions", use the revocation API in
`src/fraiseql/auth/token_revocation.py`.

```python
from fraiseql.auth import (
    InMemoryRevocationStore,
    PostgreSQLRevocationStore,
    RevocationConfig,
    TokenRevocationService,
)
```

| Symbol | Purpose |
|--------|---------|
| `InMemoryRevocationStore` | `InMemoryRevocationStore()` — process-local store, for development/tests. |
| `PostgreSQLRevocationStore` | `PostgreSQLRevocationStore(pool, table_name="tb_token_revocation")` — production store; creates and indexes its table on first use. |
| `RevocationConfig` | `RevocationConfig(enabled=True, check_revocation=True, ttl=86400, cleanup_interval=3600)` — service configuration. |
| `TokenRevocationService` | `TokenRevocationService(store, config=None)` — orchestrates revocation and periodic cleanup. |
| `TokenRevocationMixin` | Mix into a provider to check revocation during `validate_token` (used by `Auth0ProviderWithRevocation`). |

Both stores implement the same async interface: `revoke_token(token_id, user_id)`,
`is_revoked(token_id)`, `revoke_all_user_tokens(user_id)`, `cleanup_expired()`,
and `get_revoked_count()`.

```python
store = PostgreSQLRevocationStore(pool)
service = TokenRevocationService(store, RevocationConfig(ttl=3600))

await service.start()                       # begins the background cleanup loop
await service.revoke_token(token_payload)   # token_payload must carry "jti" and "sub"
revoked = await service.is_token_revoked(token_payload)
await service.revoke_all_user_tokens(user_id)
await service.stop()
```

---

## Rate limiting

FraiseQL ships a Python rate limiter in `src/fraiseql/security/rate_limiting.py`
(an ASGI middleware — there is no Rust/`tower` limiter). Use it to protect auth
endpoints from brute force.

```python
from fraiseql.security import (
    RateLimit,
    RateLimitRule,
    RateLimitStrategy,
    RateLimitStore,
    RedisRateLimitStore,
)
```

| Symbol | Signature / fields |
|--------|--------------------|
| `RateLimit` | `RateLimit(requests, window, burst=None, strategy=RateLimitStrategy.FIXED_WINDOW)` — `window` is in seconds. |
| `RateLimitRule` | `RateLimitRule(path_pattern, rate_limit, key_func=None, exempt_func=None, message=None)`. |
| `RateLimitStrategy` | `FIXED_WINDOW`, `SLIDING_WINDOW`, `TOKEN_BUCKET`. |
| `RateLimitStore` | In-memory store with TTL (default backend). |
| `RedisRateLimitStore` | `RedisRateLimitStore(redis_client)` — distributed backend for multi-process deployments. |

```python
login_rule = RateLimitRule(
    path_pattern="/auth/login",
    rate_limit=RateLimit(requests=5, window=60, strategy=RateLimitStrategy.SLIDING_WINDOW),
    message="Too many login attempts, please try again shortly.",
)
```

`create_default_rate_limit_rules()` and `setup_rate_limiting(...)` provide a
ready-made set of rules and wiring.

---

## Configuration

Auth is configured through `FraiseQLConfig` (pydantic, `FRAISEQL_`-prefixed
environment variables) or directly via `create_fraiseql_app(...)` keyword
arguments — never a TOML file.

| Field | Type / default | Description |
|-------|----------------|-------------|
| `auth_enabled` | `bool = True` | Enable authentication. |
| `auth_provider` | `Literal["auth0", "custom", "none"] = "none"` | Which provider mode to use. |
| `auth0_domain` | `str \| None = None` | Auth0 tenant domain (required when `auth_provider="auth0"`). |
| `auth0_api_identifier` | `str \| None = None` | Auth0 API identifier / audience. |
| `auth0_algorithms` | `list[str] = ["RS256"]` | Allowed JWT algorithms. |
| `dev_auth_username` | `str \| None = None` | Development login username. |
| `dev_auth_password` | `str \| None = None` | Development login password. |
| `revocation_enabled` | `bool = True` | Enable token revocation checks. |

```python
from fraiseql.auth import Auth0Config
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    auth=Auth0Config(
        domain="myapp.auth0.com",
        api_identifier="https://api.myapp.com",
    ),
)
```

Equivalent environment-variable configuration:

```bash
FRAISEQL_AUTH_ENABLED=true
FRAISEQL_AUTH_PROVIDER=auth0
FRAISEQL_AUTH0_DOMAIN=myapp.auth0.com
FRAISEQL_AUTH0_API_IDENTIFIER=https://api.myapp.com
FRAISEQL_DATABASE_URL=postgresql://user:pass@localhost/mydb
```

> Only three provider modes exist (`auth0`, `custom`, `none`). For a custom
> issuer, set `auth_provider="custom"` and pass your `AuthProvider` subclass to
> `create_fraiseql_app(auth=...)`.

---

## Error handling

Authentication and authorization failures are returned as standard GraphQL
errors with a stable `extensions.code`:

```json
{
  "errors": [
    {
      "message": "Permission 'posts:write' required",
      "extensions": {
        "code": "FORBIDDEN"
      }
    }
  ]
}
```

| `extensions.code` | Raised by | Meaning |
|-------------------|-----------|---------|
| `UNAUTHENTICATED` | `requires_auth` and the other resolver decorators | No valid `UserContext` on the request. |
| `FORBIDDEN` | resolver decorators, `Authorizer` deny, `AuthorizationDecision.deny()` | Authenticated but not permitted. |
| `FIELD_AUTHORIZATION_ERROR` | `authorize_field` | Field-level check denied access. |

---

## Security best practices

1. **Always use HTTPS** in production.
2. **Never expose client secrets** in client-side code.
3. **Validate audience and issuer** in custom `AuthProvider` subclasses.
4. **Rate-limit auth endpoints** with the Python rate limiter above.
5. **Use token revocation** for logout and "revoke all sessions".
6. **Fail closed** — rely on the built-in fail-closed authorizer enforcement;
   never let an exception in an authorizer turn into an allow.
7. **Log authentication events** for your audit trail.

---

## See Also

- [Auth0 Setup](./setup-auth0.md)
- [Google OAuth Setup](./setup-google-oauth.md)
- [Keycloak Setup](./setup-keycloak.md)
- [Provider Selection Guide](./provider-selection-guide.md)
- [Security Checklist](./security-checklist.md)
- [PostgreSQL Connection Auth (SCRAM)](./scram.md)

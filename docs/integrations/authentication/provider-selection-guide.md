---

title: OAuth Provider Selection Guide
description: Choose between Auth0, a custom AuthProvider, or no auth in FraiseQL v1.
keywords: ["framework", "sdk", "monitoring", "database", "authentication"]
tags: ["documentation", "reference"]
---

# OAuth Provider Selection Guide

**Status:** Production Ready
**Audience:** Architects, DevOps, Security Engineers
**Reading Time:** 10-15 minutes
**Last Updated:** 2026-06-19

## The Three Provider Modes

FraiseQL v1 authentication runs **inside the FastAPI app** (Python). There is exactly one
configuration knob that selects how tokens are validated — `auth_provider` on
`FraiseQLConfig`:

```python
auth_provider: Literal["auth0", "custom", "none"] = "none"
```

Everything else (Google, Keycloak, Cognito, Okta, Azure AD, your own issuer) is a *choice of
who issues the JWT*, not a separate FraiseQL provider class. You reach those issuers through
**one of two paths**:

- **Auth0** brokers them for you (`auth_provider="auth0"`), or
- a **custom `AuthProvider`** validates that issuer's JWTs directly (`auth_provider="custom"`).

There is no `GoogleProvider`, `KeycloakProvider`, or `OidcProvider` class in FraiseQL.

```text
                      auth_provider = ?

   "auth0"  ───────────────────────────────────────────────
      Managed broker. Set auth0_domain / auth0_api_identifier.
      Auth0 fronts Google, GitHub, social, SAML, enterprise OIDC.

   "custom" ───────────────────────────────────────────────
      Subclass AuthProvider and validate any OIDC/JWT issuer
      (Keycloak, Cognito, Azure AD, Okta, your own).
      RustCustomJWTProvider = accelerated JWT validation.
      NativeAuthProvider    = built-in username/password.

   "none"   ───────────────────────────────────────────────
      Auth disabled. Dev / internal only.
```

---

## Quick Decision

```text
Do you want to write/operate token validation yourself?
├─ NO, give me a managed service that brokers Google/social/SAML
│     └─ auth_provider = "auth0"
│
├─ YES, I have my own OIDC/JWT issuer (Keycloak, Cognito, Azure AD, Okta, in-house)
│     └─ auth_provider = "custom"  → subclass AuthProvider
│         (use RustCustomJWTProvider for fast JWKS-based JWT validation)
│
├─ I just need built-in username/password stored in PostgreSQL
│     └─ auth_provider = "custom"  → NativeAuthProvider
│
└─ Local dev / fully internal, no auth needed yet
      └─ auth_provider = "none"
```

---

## Comparison Matrix

| Mode | What it is | Effort | Brokers external IdPs? | Self-hosted? |
|------|-----------|--------|------------------------|--------------|
| **auth0** | Managed Auth0 tenant validates RS256 JWTs | Low | Yes (Google, social, SAML, enterprise OIDC) | No |
| **custom** | Your `AuthProvider` subclass validates JWTs | Medium | Yes (any OIDC/JWT issuer you point it at) | Yes (your issuer) |
| **custom + `NativeAuthProvider`** | Built-in username/password backed by PostgreSQL | Low | No (self-contained) | Yes |
| **none** | Authentication disabled | None | N/A | N/A |

### Capabilities by issuer (reached via the mode above)

| Feature | Auth0 | Keycloak (custom) | Cognito (custom) | Azure AD (custom) | Native (custom) |
|---------|-------|-------------------|------------------|-------------------|-----------------|
| **OIDC / JWT** | Yes | Yes | Yes | Yes | JWT (built-in) |
| **MFA / 2FA** | Yes | Yes | Yes | Yes | No |
| **Social login** | Yes (20+) | Setup | No | No | No |
| **SAML** | Yes | Yes | No | Yes | No |
| **LDAP / AD** | Yes | Yes | No | Yes | No |
| **Self-hosted** | No | Yes | No | No | Yes |
| **Managed service** | Yes | No | Yes | Yes | No |

The FraiseQL-side wiring is the same in every "custom" column: validate the issuer's JWTs
against its JWKS, issuer, and audience inside your `AuthProvider`.

---

## Mode: `auth0` (managed broker)

**Best for:**

- You want a managed service and no token-validation code.
- You need to broker Google, GitHub, other social logins, SAML, or enterprise OIDC behind a
  single tenant.
- Public users, SaaS, or enterprise customers wanting SSO.

**How to configure** — set three fields on `FraiseQLConfig` (env vars are `FRAISEQL_*`):

```python
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.auth import Auth0Config

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[...],
    queries=[...],
    auth=Auth0Config(
        domain="your-tenant.auth0.com",
        api_identifier="https://api.myapp.com",
        algorithms=["RS256"],            # default
    ),
)
```

Equivalent via configuration / environment:

```bash
FRAISEQL_AUTH_PROVIDER=auth0
FRAISEQL_AUTH0_DOMAIN=your-tenant.auth0.com
FRAISEQL_AUTH0_API_IDENTIFIER=https://api.myapp.com
# FRAISEQL_AUTH0_ALGORITHMS defaults to ["RS256"]
```

Auth0 then handles Google, social, SAML, MFA, and enterprise OIDC for you — FraiseQL only
validates the RS256 JWT that Auth0 issues.

**Trade-offs:** managed (no ops), broad feature set, but a hosted third party and a cost tier
beyond the free plan.

See **[Auth0 Setup](./setup-auth0.md)** for the full walkthrough.

---

## Mode: `custom` (any OIDC / JWT issuer)

When your tokens come from Keycloak, AWS Cognito, Azure AD, Okta, or your own issuer, set
`auth_provider="custom"` and supply an `AuthProvider`. The base class
(`fraiseql.auth.AuthProvider`) defines two abstract methods you implement:

```python
from typing import Any

from fraiseql.auth import AuthProvider, UserContext


class MyIssuerProvider(AuthProvider):
    async def validate_token(self, token: str) -> dict[str, Any]:
        # Validate against your issuer's JWKS / issuer / audience and return the payload.
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

Pass the instance to the app:

```python
app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[...],
    auth=MyIssuerProvider(...),
)
```

`UserContext` carries `user_id`, optional `email` / `name`, `roles`, `permissions`, and free
-form `metadata`, with helpers `.has_role()`, `.has_permission()`, `.has_any_role()`, and
`.has_any_permission()`. It is available to every resolver as `info.context["user"]`.

### Accelerated JWT validation: `RustCustomJWTProvider`

For standard JWKS-based JWT validation you do not have to hand-roll `validate_token`.
`RustCustomJWTProvider` validates JWTs from any custom issuer using the optional `fraiseql_rs`
extension:

```python
from fraiseql.auth.rust_provider import RustCustomJWTProvider

provider = RustCustomJWTProvider(
    issuer="https://keycloak.example.com/realms/production",
    audience="my-api",
    jwks_url="https://keycloak.example.com/realms/production/protocol/openid-connect/certs",
)
```

The same shape works for Cognito, Azure AD, Okta, or any OIDC issuer — point `issuer`,
`audience`, and `jwks_url` at that provider's well-known endpoints. The `jwks_url` must be
HTTPS.

### Built-in username/password: `NativeAuthProvider`

If you only need self-contained username/password auth backed by your PostgreSQL database
(no external IdP, no social login), use `NativeAuthProvider`. It ships a FastAPI router for
login/registration endpoints and stores credentials in your database. This is the FraiseQL-
native equivalent of "simplest possible auth" for an internal team.

**Trade-offs of `custom`:** full control and self-hosting, no third-party dependency for your
issuer, but you operate the issuer (Keycloak, your DB) and own its availability and backups.

See **[Keycloak Setup](./setup-keycloak.md)** and
**[Google OAuth Setup](./setup-google-oauth.md)** for issuer-specific walkthroughs (both route
through Auth0 or a custom provider — there is no dedicated class for either).

---

## Mode: `none` (auth disabled)

`auth_provider="none"` is the default. Every request is unauthenticated and
`info.context["user"]` is absent. Use it for local development or fully internal/trusted
deployments. Do not ship `none` to a public surface.

For development you can also enable a dev login via `dev_auth_username` /
`dev_auth_password` instead of standing up a real provider.

---

## Decision Table

| Use case | Mode | Why |
|----------|------|-----|
| Public users, want managed | `auth0` | No token code; brokers Google/social |
| SaaS needing SSO / SAML | `auth0` | SAML + enterprise OIDC via one tenant |
| Self-hosted Keycloak | `custom` | Validate Keycloak JWTs (RustCustomJWTProvider) |
| AWS Cognito user pool | `custom` | Validate Cognito JWTs via its JWKS |
| Azure AD / Okta | `custom` | Validate that issuer's JWTs |
| Your own JWT issuer | `custom` | Subclass `AuthProvider` |
| Internal team, username/password | `custom` + `NativeAuthProvider` | Self-contained, PostgreSQL-backed |
| Local dev / internal only | `none` | Auth disabled |

---

## Switching Modes

Provider choice is configuration, not architecture — switching modes is a config change plus a
redeploy. The main user-facing effect is that existing tokens issued by the old provider stop
validating, so users re-authenticate once after cutover.

### Example: Native/custom issuer to Auth0

```python
# Before: custom issuer
auth=MyIssuerProvider(...)

# After: Auth0 brokers it
auth=Auth0Config(
    domain="your-tenant.auth0.com",
    api_identifier="https://api.myapp.com",
)
```

Deploy the change; on first request after cutover users authenticate against Auth0. No data
migration is required on the FraiseQL side — `UserContext` is rebuilt from the new tokens.

---

## Authorization (after authentication)

Selecting a provider only establishes *who the user is*. To control *what they can do*,
FraiseQL gives you:

- **Decorators** (`from fraiseql.auth`): `requires_auth`, `requires_permission`,
  `requires_role`, `requires_any_role`, `requires_any_permission` — they read
  `info.context["user"]`.
- **Operation authorization**: an `Authorizer` attached via
  `@fraiseql.query(authorizer=...)` / `@fraiseql.mutation(authorizer=...)` /
  `@fraiseql.subscription(authorizer=...)`, or globally with
  `create_fraiseql_app(authorizer=..., authorization_cache=...)`.
- **Field authorization**: `@fraiseql.type(..., authorize_fields=...)` plus `authorize_field`
  / `any_permission` / `combine_permissions`.
- **PostgreSQL Row-Level Security** keyed on `tenant_id` / `user_id` flowed from
  `info.context` into session GUCs.

Denied access surfaces as a GraphQL error with `extensions.code = "FORBIDDEN"`.

---

## A note on SCRAM

SCRAM-SHA-256 is **not** a FraiseQL authentication scheme. It is PostgreSQL's own
connection authentication — the psycopg/libpq client negotiates `scram-sha-256` based on your
`pg_hba.conf` and `database_url`. It secures the database connection, not your GraphQL users,
and is configured in PostgreSQL rather than in FraiseQL. See
**[SCRAM / Database Connection Auth](./scram.md)** if you are hardening the PostgreSQL
connection.

---

## See Also

- **[Auth0 Setup](./setup-auth0.md)** — `auth_provider="auth0"` walkthrough
- **[Google OAuth Setup](./setup-google-oauth.md)** — Google via Auth0 or a custom provider
- **[Keycloak Setup](./setup-keycloak.md)** — Keycloak via a custom provider
- **[SCRAM / Database Connection Auth](./scram.md)** — PostgreSQL connection security
- **[Security Checklist](./security-checklist.md)** — pre-production verification
- **[API Reference](./api-reference.md)** — auth providers, decorators, `UserContext`

---

**Remember:** provider choice is a config setting (`auth_provider` plus a few `FRAISEQL_`
fields or `create_fraiseql_app(auth=...)` kwargs), and switching is a redeploy away. Choose
based on current needs and scale up as you grow.

<!-- Skip to main content -->
---

title: Keycloak OAuth 2.0 / OIDC Setup Guide
description: This guide walks you through using Keycloak as the identity provider for a FraiseQL application.
keywords: ["framework", "sdk", "authentication", "keycloak", "oidc"]
tags: ["documentation", "reference"]
---

# Keycloak OAuth 2.0 / OIDC Setup Guide

This guide walks you through using Keycloak as the identity provider for a FraiseQL application.

FraiseQL v1 is a Python runtime GraphQL framework served over FastAPI, and its
authentication runs **inside the FastAPI app** (Python). It ships exactly three
provider modes — `auth_provider="auth0"`, `auth_provider="custom"`, and
`auth_provider="none"`. There is **no built-in Keycloak provider class**. To use
Keycloak you have two honest paths:

- **Path A — Auth0 as a broker.** Add Keycloak as an OIDC/enterprise connection
  upstream of Auth0. FraiseQL still uses `auth_provider="auth0"`; Keycloak issues
  identities into Auth0, and your app validates Auth0 tokens. Good when you already
  use Auth0 or want zero custom code.
- **Path B — Custom provider (natural for Keycloak).** Set `auth_provider="custom"`
  and implement an `AuthProvider` subclass that validates Keycloak's own JWTs
  directly against Keycloak's JWKS/issuer/audience, mapping Keycloak realm and
  client roles onto `UserContext.roles`. Good when you talk to Keycloak directly,
  with no Auth0 in the middle.

Both paths reuse the same Keycloak realm, client, and role setup, covered first.

## Why Keycloak?

- **Self-hosted**: Full control over authentication infrastructure
- **Open source**: No vendor lock-in
- **Multi-protocol**: OAuth 2.0, OIDC, SAML, LDAP
- **Enterprise features**: Role-based access, user federation, realms
- **Docker**: Easy to run locally or in production

## Prerequisites

**Required Knowledge:**

- OAuth 2.0 and OIDC fundamentals (authorization code flow with PKCE, ID tokens, access tokens, refresh tokens)
- JWT token structure and RS256 signature verification
- Keycloak concepts (realms, clients, scopes, user roles)
- Docker and Docker Compose basics
- HTTP/REST APIs and callback URLs
- Basic networking and DNS resolution

**Required Software:**

- FraiseQL v1
- Docker 20.10+ and Docker Compose (for local Keycloak)
  - OR: Keycloak 20+ server (if self-hosted separately)
- curl or Postman (for API testing)
- A code editor for configuration files
- Bash or similar shell for environment variables
- PostgreSQL 14+ (for FraiseQL, and for Keycloak's own state)

**Required Infrastructure:**

*For Local Development (Docker):*

- Docker daemon running
- ~2GB available disk space for images and volumes
- Port 8080 available for Keycloak UI
- Port 5432 available for PostgreSQL (or modify docker-compose)

*For Production:*

- Keycloak server instance (self-hosted or cloud-hosted)
- PostgreSQL 14+ database for Keycloak state
- PostgreSQL database for your FraiseQL application
- A deployed FraiseQL FastAPI app (`uvicorn app:app`)
- Publicly accessible URL for OAuth callbacks
- Load balancer (optional, for HA)
- TLS/HTTPS certificate

**Optional but Recommended:**

- Keycloak Themes for branding
- Custom Keycloak User Federation for integrating with LDAP/Active Directory
- Keycloak Realm Backup (for production recovery)
- Nginx reverse proxy with SSL (for production)

**Time Estimate:** 25-45 minutes (15 min for Keycloak setup + 10-30 min for client/realm configuration and FraiseQL wiring)

## Step 1: Run Keycloak

### Option 1: Local Keycloak (Docker)

Create `docker-compose.yml`:

```yaml
version: '3.8'
services:
  keycloak:
    image: quay.io/keycloak/keycloak:latest
    environment:
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: admin123
      KC_DB: postgres
      KC_DB_URL: jdbc:postgresql://postgres:5432/keycloak
      KC_DB_USERNAME: keycloak
      KC_DB_PASSWORD: keycloak123
    ports:
      - "8080:8080"
    command:
      - start-dev
    depends_on:
      - postgres

  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: keycloak
      POSTGRES_USER: keycloak
      POSTGRES_PASSWORD: keycloak123
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

Start it:

```bash
docker-compose up -d
```

Access Keycloak at `http://localhost:8080`.

### Option 2: Managed / Self-Hosted Keycloak (Production)

If using a hosted Keycloak service, skip the Docker step and note your base URL
(for example `https://keycloak.example.com`). The realm, client, and role steps
below are identical.

## Step 2: Create Realm

1. Go to `http://localhost:8080`
2. Click "Administration Console"
3. Login with `admin` / `admin123`
4. Hover over "Master" (top left) → Click "Create Realm"
5. Enter realm name: `fraiseql`
6. Click "Create"

## Step 3: Create Client

1. In the `fraiseql` realm, go to "Clients" (left sidebar)
2. Click "Create client"
3. Client ID: `fraiseql-api`
4. Client Protocol: `openid-connect`
5. Click "Next"
6. Enable:
   - Client authentication
   - Authorization
7. Click "Next"
8. Root URL: `http://localhost:8000`
9. Valid redirect URIs:
   - `http://localhost:8000/auth/callback`
   - `http://localhost:3000/*` (if frontend on a different port)
10. Valid post logout redirect URIs:
    - `http://localhost:3000`
11. Click "Save"

This client ID (`fraiseql-api`) is also the **audience** your FraiseQL app will
require on incoming access tokens.

## Step 4: Get Client Secret

1. In the client settings, go to "Credentials" tab
2. Copy the **Client Secret** (your frontend or broker uses this to exchange codes)

## Step 5: Create Roles

Create custom roles for RBAC:

1. Go to "Realm roles" (left sidebar)
2. Click "Create role"
3. Role name: `api-admin`
4. Click "Create"
5. Assign the role to a user:
   - Go to "Users" → click a user
   - Go to "Role mapping" → "Assign role"
   - Select `api-admin`

You can also create **client roles** under the client's "Roles" tab. Keycloak
places realm roles under `realm_access.roles` and client roles under
`resource_access.<client>.roles` in the token; the custom provider in Path B maps
both onto `UserContext.roles`.

## Step 6: Create Test User (Optional)

1. Go to "Users" (left sidebar)
2. Click "Add user"
3. Username: `testuser`
4. Email: `test@example.com`
5. Click "Create"
6. Go to "Credentials" tab
7. Click "Set password", enter a password, and confirm

## Useful Keycloak URLs

For realm `fraiseql` and base URL `{base}` (e.g. `http://localhost:8080`):

| Purpose | URL |
|---------|-----|
| OIDC discovery | `{base}/realms/fraiseql/.well-known/openid-configuration` |
| Issuer (token `iss`) | `{base}/realms/fraiseql` |
| JWKS (signing keys) | `{base}/realms/fraiseql/protocol/openid-connect/certs` |
| Token endpoint | `{base}/realms/fraiseql/protocol/openid-connect/token` |

You will need the **issuer**, **JWKS**, and **audience** (your client ID) to
validate tokens in Path B.

## Path A: Auth0 as a Broker

Use this path when you already run Auth0, or want FraiseQL to do zero custom
token-validation work. Keycloak becomes an upstream **enterprise / OIDC
connection** in Auth0; users authenticate against Keycloak, Auth0 mints the
tokens your app actually sees.

1. In the Auth0 dashboard, add an **Enterprise → OpenID Connect** connection (or
   a Social/Custom OIDC connection) pointing at your Keycloak realm's discovery
   URL: `{base}/realms/fraiseql/.well-known/openid-configuration`.
2. Supply the Keycloak client ID and secret from Step 3/Step 4 as the connection's
   credentials, and enable the connection for your Auth0 application.
3. Configure FraiseQL to validate **Auth0** tokens — Keycloak is invisible to the
   app at this point:

```python
import fraiseql
from fraiseql.auth import Auth0Config
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[...],
    queries=[...],
    mutations=[...],
    auth=Auth0Config(
        domain="myapp.auth0.com",
        api_identifier="https://api.myapp.com",  # the Auth0 API audience
    ),
)
```

Equivalently, via environment variables / `FraiseQLConfig`:

```bash
FRAISEQL_AUTH_PROVIDER=auth0
FRAISEQL_AUTH0_DOMAIN=myapp.auth0.com
FRAISEQL_AUTH0_API_IDENTIFIER=https://api.myapp.com
```

See the [Auth0 setup guide](./setup-auth0.md) for the full Auth0-side
configuration. Map the Keycloak roles you created in Step 5 into the Auth0 token
(via an Auth0 Action/rule that copies the upstream claims) so they land in the
`UserContext` your resolvers see.

## Path B: Custom `AuthProvider` (validate Keycloak directly)

Use this path when your app talks to Keycloak directly, with no Auth0 in the
middle. You set `auth_provider="custom"` and pass an `AuthProvider` subclass that
validates Keycloak's JWTs against Keycloak's JWKS, issuer, and your client as the
audience.

### The `AuthProvider` interface

The base class lives in `src/fraiseql/auth/base.py`. A custom provider must
implement two coroutines:

```python
from abc import ABC, abstractmethod
from typing import Any


class AuthProvider(ABC):
    @abstractmethod
    async def validate_token(self, token: str) -> dict[str, Any]:
        """Validate a token and return its decoded payload."""

    @abstractmethod
    async def get_user_from_token(self, token: str) -> UserContext:
        """Validate a token and return the UserContext for the request."""
```

`UserContext` (also in `base.py`) is what every resolver receives at
`info.context["user"]`:

```python
@dataclass
class UserContext:
    user_id: str
    email: str | None = None
    name: str | None = None
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    # .has_role(...) / .has_permission(...) / .has_any_role(...) / .has_any_permission(...)
```

### A Keycloak provider implementation

```python
import time

import httpx
from jose import jwt
from jose.exceptions import JWTError

from fraiseql.auth.base import AuthProvider, AuthenticationError, UserContext


class KeycloakAuthProvider(AuthProvider):
    """Validate Keycloak-issued JWTs directly (no Auth0 broker).

    Keycloak realm roles arrive under ``realm_access.roles`` and client roles
    under ``resource_access.<client>.roles``; both are mapped onto
    ``UserContext.roles``.
    """

    def __init__(self, base_url: str, realm: str, audience: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.realm = realm
        self.audience = audience  # your Keycloak client ID
        self.issuer = f"{self.base_url}/realms/{realm}"
        self.jwks_url = (
            f"{self.base_url}/realms/{realm}/protocol/openid-connect/certs"
        )
        self._jwks: dict[str, Any] | None = None
        self._jwks_fetched_at: float = 0.0

    async def _get_jwks(self) -> dict[str, Any]:
        # Cache the signing keys briefly; refresh on rotation.
        if self._jwks is None or time.monotonic() - self._jwks_fetched_at > 3600:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.jwks_url)
                response.raise_for_status()
                self._jwks = response.json()
                self._jwks_fetched_at = time.monotonic()
        return self._jwks

    async def validate_token(self, token: str) -> dict[str, Any]:
        jwks = await self._get_jwks()
        try:
            return jwt.decode(
                token,
                jwks,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
            )
        except JWTError as exc:
            raise AuthenticationError(f"Invalid Keycloak token: {exc}") from exc

    async def get_user_from_token(self, token: str) -> UserContext:
        payload = await self.validate_token(token)

        realm_roles = payload.get("realm_access", {}).get("roles", [])
        client_roles = (
            payload.get("resource_access", {})
            .get(self.audience, {})
            .get("roles", [])
        )

        return UserContext(
            user_id=payload["sub"],
            email=payload.get("email"),
            name=payload.get("name") or payload.get("preferred_username"),
            roles=[*realm_roles, *client_roles],
            permissions=payload.get("scope", "").split(),
            metadata={"issuer": payload.get("iss")},
        )
```

> The token-decode call uses `python-jose` here for illustration; any JWT/JWKS
> library works as long as you verify the signature against Keycloak's JWKS and
> check the `issuer` and `audience`.

### Wire it into the app

`create_fraiseql_app(auth=...)` accepts either an `Auth0Config` or any
`AuthProvider` instance, so you pass your provider directly:

```python
import os

import fraiseql
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[...],
    queries=[...],
    mutations=[...],
    auth=KeycloakAuthProvider(
        base_url=os.environ["KEYCLOAK_URL"],          # e.g. http://localhost:8080
        realm=os.environ["KEYCLOAK_REALM"],           # e.g. fraiseql
        audience=os.environ["KEYCLOAK_CLIENT_ID"],    # e.g. fraiseql-api
    ),
    production=False,  # False enables the GraphQL playground
)
```

A matching `.env`:

```bash
# Keycloak Configuration (consumed by KeycloakAuthProvider)
KEYCLOAK_URL=http://localhost:8080
KEYCLOAK_REALM=fraiseql
KEYCLOAK_CLIENT_ID=fraiseql-api

# FraiseQL application database
DATABASE_URL=postgresql://user:password@localhost/mydb
```

Run the app like any FastAPI service:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

### Enforce roles in resolvers

Once the provider populates `UserContext.roles`, use FraiseQL's auth decorators
(from `fraiseql.auth`) or check the context directly:

```python
import fraiseql
from fraiseql.auth import requires_role


@fraiseql.query
@requires_role("api-admin")
async def admin_stats(info) -> AdminStats:
    db = info.context["db"]
    return await db.find_one("v_admin_stats")


@fraiseql.query
async def my_profile(info) -> User | None:
    user = info.context["user"]  # UserContext, or None if unauthenticated
    if user is None:
        return None
    db = info.context["db"]
    return await db.find_one("v_user", id=user.user_id)
```

Denied access surfaces as a GraphQL error with `extensions.code = "FORBIDDEN"`.

## Testing the Flow

### 1. Obtain a token from Keycloak

For a quick test, use Keycloak's token endpoint with the direct-access grant
(enable "Direct access grants" on the client first):

```bash
curl -X POST \
  "http://localhost:8080/realms/fraiseql/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=fraiseql-api" \
  -d "client_secret=<client-secret>" \
  -d "username=testuser" \
  -d "password=<password>"
```

The response includes an `access_token`.

### 2. Call the GraphQL endpoint

```bash
curl -X POST http://localhost:8000/graphql \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ myProfile { id } }"}'
```

A valid token returns data; an invalid or expired one returns a GraphQL error.

## Advanced: User Federation

Keycloak can federate users from:

- LDAP/Active Directory
- Database (custom providers)
- Other identity providers

To set up LDAP federation:

1. Go to "User Federation" (left sidebar)
2. Click "Add provider" → "ldap"
3. Configure the LDAP connection:
   - Vendor: `Active Directory` or `LDAP`
   - Connection URL: `ldap://your-ldap-server`
   - Bind DN: `cn=admin,dc=example,dc=com`
   - Bind credential: (password)
4. Configure user mapping
5. Click "Save"

Federated users still authenticate against your `fraiseql` realm, so neither path
above changes.

## Troubleshooting

### Error: "Realm not found"

**Cause**: Realm doesn't exist or wrong URL.

**Solution**:

- Verify the realm name in Keycloak
- Check the `KEYCLOAK_REALM` environment variable
- Try `http://localhost:8080/realms/fraiseql/.well-known/openid-configuration`

### Error: "Invalid Client"

**Cause**: Client ID or secret is wrong.

**Solution**:

- Verify the client ID in Keycloak
- Copy the client secret from the "Credentials" tab
- Check that environment variables match exactly

### Error: "Invalid Keycloak token" / signature failures

**Cause**: Wrong issuer, audience, or stale signing keys.

**Solution**:

- Confirm the `issuer` matches `{base}/realms/{realm}` exactly (including http vs https)
- Confirm the `audience` matches your client ID
- Re-fetch JWKS from `{base}/realms/{realm}/protocol/openid-connect/certs` after a key rotation

### Keycloak Container Won't Start

**Solution**:

```bash
# Check logs
docker-compose logs keycloak

# Restart
docker-compose restart keycloak

# Recreate if needed
docker-compose down
docker-compose up -d
```

## Production Deployment

For production Keycloak:

1. Use PostgreSQL (not H2) for Keycloak state
2. Enable HTTPS with valid certificates
3. Use strong passwords
4. Configure backup and restore procedures
5. Set up monitoring and alerting
6. Use environment-specific realms
7. Enable audit logging

Example production `.env`:

```bash
# .env.prod
KEYCLOAK_URL=https://keycloak.example.com
KEYCLOAK_REALM=production
KEYCLOAK_CLIENT_ID=fraiseql-prod

DATABASE_URL=postgresql://user:strong-pass@db.internal/mydb
```

## Multi-Realm Setup

For different environments, create separate realms:

```text
Keycloak
├── development (uses test users)
├── staging (mirrors production)
└── production (uses enterprise LDAP)
```

Each realm has:

- Separate clients with different credentials
- Different OIDC configurations
- Environment-specific roles and policies

Point each deployment's `KEYCLOAK_REALM` (and `KEYCLOAK_URL`) at the right realm.

## See Also

- [Keycloak Documentation](https://www.keycloak.org/documentation)
- [Keycloak Admin Guide](https://www.keycloak.org/docs/latest/server_admin/)
- [Auth0 Setup Guide](./setup-auth0.md)
- [Provider Selection Guide](./provider-selection-guide.md)
- [FraiseQL Auth API Reference](./api-reference.md)

---

**Next Step**: See [API Reference](./api-reference.md) for the full authentication API.

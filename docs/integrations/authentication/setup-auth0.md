---
title: Auth0 OAuth 2.0 / OIDC Setup Guide
description: This guide walks you through setting up Auth0 authentication with FraiseQL.
keywords: ["framework", "authentication", "auth0", "oidc", "jwt", "fastapi"]
tags: ["documentation", "reference"]
---

# Auth0 OAuth 2.0 / OIDC Setup Guide

This guide walks you through setting up Auth0 authentication with FraiseQL. Auth0 is a
first-class, built-in provider in FraiseQL v1: you configure it in Python (via
`Auth0Config` / `Auth0Provider`) and authentication runs **inside your FastAPI app**.

## Why Auth0?

- **Managed service**: No infrastructure to maintain
- **Enterprise-grade**: Proven by thousands of companies
- **Fast setup**: Minutes to configure
- **Rich features**: MFA, social login, passwordless auth
- **Scalability**: Handles millions of authentications

## How it works in FraiseQL

FraiseQL validates the **access token** (a JWT) that Auth0 issues for your API. On every
GraphQL request, the `Auth0Provider`:

1. Fetches and caches Auth0's JWKS (public signing keys).
2. Verifies the token's RS256 signature, `audience` (your API identifier), and `issuer`
   (`https://your-domain.auth0.com/`).
3. Builds a `UserContext` (user id, email, roles, permissions) and places it at
   `info.context["user"]`.

Your resolvers then enforce access with the `@requires_auth` / `@requires_permission` /
`@requires_role` decorators. FraiseQL does **not** mint or store tokens itself — Auth0 (or
your frontend SDK) handles the login redirect, callback, and token exchange; FraiseQL only
**verifies** the bearer token on incoming requests.

## Prerequisites

**Required Knowledge:**

- OAuth 2.0 and OIDC fundamentals (authorization code flow, ID tokens, access tokens)
- JWT token structure and RS256 signature verification
- HTTP/REST APIs and bearer-token authorization
- Auth0 tenant management and application concepts
- Basic Python / FastAPI

**Required Software:**

- FraiseQL v1
- Python 3.13+
- curl or Postman (for API testing)
- A code editor

**Required Infrastructure:**

- Auth0 account (free tier available at <https://auth0.com/signup>)
- Auth0 tenant/domain (created automatically with account)
- A FraiseQL FastAPI app (local or deployed)
- PostgreSQL database
- An Auth0 Application (for the frontend login flow — created in Step 1)
- An Auth0 API definition (defines the audience your tokens target — created in Step 3)

**Optional but Recommended:**

- A frontend Auth0 SDK (auth0-react, auth0-spa-js, etc.) to drive the login flow
- Auth0 Actions for custom claims (roles/permissions in the token)
- Auth0 Logs page for debugging authentication issues

**Time Estimate:** 20-40 minutes for complete setup and first authenticated request

## Step 1: Create Auth0 Application

This application represents the client (your frontend) that logs users in.

1. Go to [Auth0 Dashboard](https://manage.auth0.com)
2. Click "Applications" (left sidebar)
3. Click "Create Application"
4. Enter a name, e.g. "MyApp Frontend"
5. Choose the application type that matches your frontend
   (**Single Page Application** for a SPA, **Regular Web Application** for server-rendered)
6. Click "Create"

## Step 2: Configure Application Settings

1. In the application settings, go to the "Settings" tab
2. Note these values (the frontend SDK needs them):
   - **Domain**: `your-domain.auth0.com`
   - **Client ID**: (copy this)
   - **Client Secret**: (only for Regular Web Applications)

3. Under "Allowed Callback URLs" add the URLs your frontend redirects back to after login:

   ```text
   http://localhost:3000/callback
   https://yourdomain.com/callback
   ```

4. Under "Allowed Logout URLs" add:

   ```text
   http://localhost:3000
   https://yourdomain.com
   ```

5. Under "Allowed Web Origins" add:

   ```text
   http://localhost:3000
   https://yourdomain.com
   ```

6. Click "Save Changes"

> The login redirect and callback are handled by your **frontend** and Auth0. Your FraiseQL
> backend only receives the resulting access token as a `Bearer` header — it has no callback
> route of its own.

## Step 3: Create API (defines the token audience)

The **API identifier** becomes the `audience` of the access tokens FraiseQL validates.

1. Go to "Applications" → "APIs" (left sidebar)
2. Click "Create API"
3. Enter a name, e.g. "MyApp API"
4. Identifier (audience): `https://api.myapp.com` (any stable URI — it does not need to resolve)
5. Signing algorithm: **RS256** (default)
6. Click "Create"

Keep this identifier handy — it maps to FraiseQL's `api_identifier` / `auth0_api_identifier`.

## Step 4: Configure FraiseQL

Set your settings via environment variables (prefixed with `FRAISEQL_`). For example, in a
`.env` file:

```bash
# Database
FRAISEQL_DATABASE_URL=postgresql://user:password@localhost/myapp

# Auth0 (audience = the API Identifier from Step 3)
FRAISEQL_AUTH_PROVIDER=auth0
FRAISEQL_AUTH0_DOMAIN=your-domain.auth0.com
FRAISEQL_AUTH0_API_IDENTIFIER=https://api.myapp.com
# FRAISEQL_AUTH0_ALGORITHMS defaults to ["RS256"]
```

These map onto the `FraiseQLConfig` fields `auth_provider="auth0"`, `auth0_domain`,
`auth0_api_identifier`, and `auth0_algorithms` (default `["RS256"]`).

## Step 5: Wire up the FraiseQL app

Pass an `Auth0Config` (or an `Auth0Provider`) to `create_fraiseql_app` via the `auth`
argument. FraiseQL builds the provider and validates tokens in-process.

```python
import os

from fraiseql.auth import Auth0Config
from fraiseql.fastapi import create_fraiseql_app

from myapp.schema import User, Post, users, user, create_user

auth = Auth0Config(
    domain=os.environ["FRAISEQL_AUTH0_DOMAIN"],          # "your-domain.auth0.com"
    api_identifier=os.environ["FRAISEQL_AUTH0_API_IDENTIFIER"],  # "https://api.myapp.com"
    algorithms=["RS256"],
)

app = create_fraiseql_app(
    database_url=os.environ["FRAISEQL_DATABASE_URL"],
    types=[User, Post],
    queries=[users, user],
    mutations=[create_user],
    auth=auth,
    production=True,   # False enables the GraphQL playground
)
```

Run it with any ASGI server:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

> **Alternative wiring.** You can construct the provider directly and pass it instead:
>
> ```python
> from fraiseql.auth import Auth0Provider
>
> auth = Auth0Provider(
>     domain="your-domain.auth0.com",
>     api_identifier="https://api.myapp.com",
>     algorithms=["RS256"],
>     cache_jwks=True,
> )
>
> app = create_fraiseql_app(database_url=..., types=[...], auth=auth)
> ```
>
> Or skip the `auth=` argument entirely and rely on the `FRAISEQL_AUTH0_*` environment
> variables from Step 4 (with `FRAISEQL_AUTH_PROVIDER=auth0`).

## Step 6: Protect resolvers

Authorization is enforced **per resolver** in Python. The decorators read the authenticated
`UserContext` from `info.context["user"]`.

```python
import fraiseql
from fraiseql.auth import requires_auth, requires_permission, requires_role


@fraiseql.query
@requires_auth
async def me(info) -> User:
    user = info.context["user"]          # a UserContext (guaranteed authenticated)
    db = info.context["db"]
    return await db.find_one("v_user", id=user.user_id)


@fraiseql.mutation
@requires_permission("users:write")
async def create_user(info, input: CreateUserInput) -> CreateUserSuccess | CreateUserError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_create_user", {"name": input.name, "email": input.email}
    )
    if not result.get("success"):
        return CreateUserError(message=result.get("message", "failed"))
    return CreateUserSuccess(user=User(**result["user"]))


@fraiseql.mutation
@requires_role("admin")
async def delete_user(info, input: DeleteUserInput) -> DeleteUserSuccess | DeleteUserError:
    db = info.context["db"]
    result = await db.execute_function("fn_delete_user", {"id": str(input.id)})
    if not result.get("success"):
        return DeleteUserError(message=result.get("message", "failed"))
    return DeleteUserSuccess(id=input.id)
```

`UserContext` exposes `.user_id`, `.email`, `.name`, `.roles`, `.permissions`, `.metadata`,
plus helpers `.has_role(...)`, `.has_permission(...)`, `.has_any_role(...)`, and
`.has_any_permission(...)` for ad-hoc checks inside a resolver.

When access is denied, FraiseQL returns a GraphQL error with `extensions.code` set to
`"UNAUTHENTICATED"` (no/invalid token) or `"FORBIDDEN"` (missing role/permission) — not an
HTTP 4xx redirect.

## Testing

### 1. Obtain an access token

In development you can request a token for your API directly from Auth0 using the
client-credentials grant (enable a Machine-to-Machine application authorized for your API,
or use the "Test" tab on the API page in the dashboard):

```bash
curl -X POST https://your-domain.auth0.com/oauth/token \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "YOUR_M2M_CLIENT_ID",
    "client_secret": "YOUR_M2M_CLIENT_SECRET",
    "audience": "https://api.myapp.com",
    "grant_type": "client_credentials"
  }'
```

In production, your **frontend** obtains the access token via the Auth0 login flow and sends
it to the GraphQL endpoint.

### 2. Call the GraphQL endpoint with the token

```bash
curl -X POST http://localhost:8000/graphql \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ me { id email } }"}'
```

A request without a valid token to a protected resolver returns a GraphQL error with
`extensions.code = "UNAUTHENTICATED"`.

## Advanced: Roles and permissions in tokens

For `@requires_role` / `@requires_permission` to work, the user's roles and permissions must
be present in the access token. Configure this in Auth0:

1. Go to "User Management" → "Roles", create roles (e.g. `admin`) and attach permissions
   (e.g. `users:read`, `users:write`, `users:delete`) defined on your API.
2. Assign roles to users under "User Management" → "Users".
3. Enable "Add Permissions in the Access Token" (and optionally RBAC) on your API's settings
   so `permissions` appears in the token. FraiseQL reads the token's `permissions` claim
   directly into `UserContext.permissions`.

For roles, add a custom claim via an Auth0 **Action** (Post-Login trigger). FraiseQL reads
roles from a namespaced claim derived from your API identifier:

```javascript
exports.onExecutePostLogin = async (event, api) => {
  const namespace = 'https://api.myapp.com/';
  const roles = event.authorization?.roles ?? [];
  api.accessToken.setCustomClaim(`${namespace}roles`, roles);
};
```

Then check roles in any resolver:

```python
@fraiseql.query
@requires_auth
async def admin_dashboard(info) -> Dashboard:
    user = info.context["user"]
    if not user.has_role("admin"):
        raise PermissionError("admin role required")
    ...
```

## Advanced: Social login

Auth0 supports social login (Google, GitHub, etc.). To enable:

1. Go to "Authentication" → "Social"
2. Enable the desired providers and supply their credentials
3. Auth0 handles the OAuth flow automatically

No FraiseQL change is needed — tokens still arrive as a `Bearer` access token validated the
same way.

## Advanced: Multi-Factor Authentication (MFA)

To require MFA:

1. Go to "Security" → "Multi-factor Authentication"
2. Enable the desired factors (SMS, Email, Authenticator app)
3. Configure enrollment

Auth0 prompts for MFA during login; FraiseQL is unaffected.

## Troubleshooting

### Error: "Invalid token" / `INVALID_TOKEN`

**Cause**: The token signature, audience, or issuer doesn't match.

**Solution**:

- Verify `auth0_domain` matches your tenant exactly (no scheme, no trailing slash).
- Verify `auth0_api_identifier` equals the token's `aud` claim (the API Identifier from
  Step 3).
- Confirm the token was issued for **this** API, not just an ID token from the application.

### Error: "Token has expired" / `TOKEN_EXPIRED`

**Cause**: The access token's `exp` has passed.

**Solution**: Have the frontend refresh the token (Auth0 SDK handles this) and retry.

### Error: `FORBIDDEN` (permission/role required)

**Cause**: The user is authenticated but lacks the required permission or role.

**Solution**:

- Confirm the role/permission is assigned in Auth0.
- Confirm "Add Permissions in the Access Token" is enabled (for `permissions`) and your
  Post-Login Action sets the namespaced `roles` claim (for roles).

### Tokens validate but roles are empty

**Cause**: Roles aren't in the access token.

**Solution**: Add the namespaced `roles` claim via an Auth0 Action (see "Roles and
permissions in tokens" above). The namespace FraiseQL reads is
`https://<api_identifier>/roles`.

### Connectivity check

```bash
# Confirm the tenant's OIDC metadata and JWKS are reachable
curl https://your-domain.auth0.com/.well-known/openid-configuration
curl https://your-domain.auth0.com/.well-known/jwks.json
```

## Production Deployment

### Environment configuration

```bash
# .env.prod
FRAISEQL_DATABASE_URL=postgresql://user:pass@prod-db/myapp

FRAISEQL_AUTH_PROVIDER=auth0
FRAISEQL_AUTH0_DOMAIN=your-domain.auth0.com
FRAISEQL_AUTH0_API_IDENTIFIER=https://api.myapp.com
```

Run with a production ASGI setup (for example multiple Uvicorn workers behind a proxy):

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4
```

Set `production=True` on `create_fraiseql_app` (or `FRAISEQL_ENVIRONMENT=production`) to
disable the playground and enable production hardening.

### Auth0 tenant configuration

1. Go to "Tenant Settings"
2. Set a friendly name for production
3. Configure session timeout
4. Set a custom domain (optional but recommended): use `auth.example.com` instead of
   `your-domain.auth0.com` — this also keeps the issuer stable if you migrate tenants

### Monitoring

Auth0 provides logs under "Monitoring" → "Logs": authentication events, failures, and
anomaly detection. FraiseQL additionally emits security audit events (auth success/failure,
token expired/invalid) through its audit logger.

## Cost

Auth0 pricing:

- **Free tier**: Up to 7,000 active users
- **Pro**: Pay-as-you-go, starts around $13/month
- **Enterprise**: Custom pricing

Most applications fit in the free tier initially.

## See Also

- [Auth0 Documentation](https://auth0.com/docs)
- [Auth0 API Reference](https://auth0.com/docs/api)
- [Auth0 Actions](https://auth0.com/docs/customize/actions)
- [FraiseQL Authentication API Reference](./api-reference.md)

---

**Next Step**: See [API Reference](./api-reference.md) for the full authentication API.

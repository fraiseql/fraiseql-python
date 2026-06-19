---
title: Google OAuth 2.0 Setup Guide
description: This guide walks you through using Google as the identity provider for a FraiseQL API.
keywords: ["framework", "authentication", "oauth", "google", "auth0", "postgresql"]
tags: ["documentation", "reference"]
---

# Google OAuth 2.0 Setup Guide

This guide walks you through using **Google** as the identity provider for a FraiseQL
v1 API. FraiseQL is a Python runtime GraphQL framework that runs inside your FastAPI
app; it validates the **JWT/ID tokens** that arrive on each GraphQL request and turns
them into a `UserContext` your resolvers can read. It does **not** run an OAuth
authorization server itself — the browser redirect/consent dance is handled by Google
together with either Auth0 (Path A) or your own client app (Path B).

There are two honest ways to wire Google into FraiseQL:

- **Path A (recommended): Auth0 as a broker.** Add Google as a *social connection* in
  Auth0. Your users log in with Google, Auth0 mints its own JWT, and FraiseQL simply
  uses `auth_provider="auth0"`. You write zero token-validation code.
- **Path B: custom provider.** Set `auth_provider="custom"` and implement an
  `AuthProvider` subclass that validates Google's ID tokens directly (Google's JWKS,
  issuer, and your OAuth client ID as the audience).

FraiseQL ships an `Auth0Provider` and a base `AuthProvider` ABC. There is **no**
`GoogleProvider`/`OidcProvider` class — you use one of the two paths above.

## Prerequisites

**Required Knowledge:**

- OAuth 2.0 / OIDC fundamentals (authorization code flow, ID tokens, access tokens)
- JWT token structure and claims (`iss`, `aud`, `sub`, `exp`)
- HTTP/REST APIs and redirect URIs
- Google Cloud Console navigation and project management

**Required Software:**

- FraiseQL v1 (`pip install fraiseql` / `uv add fraiseql`)
- curl or a GraphQL client (for testing the API)
- A PostgreSQL database (FraiseQL is PostgreSQL-only)
- For Path A: an Auth0 tenant (free tier is fine)

**Required Infrastructure:**

- Active Google Cloud account (free tier available)
- A Google Cloud Project (created in Step 1)
- A redirect URI that Google can call back — this points at **Auth0** (Path A) or at
  **your client application** (Path B), never at FraiseQL itself

**Time Estimate:** 15-30 minutes for complete setup and testing

## Step 1: Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Click the project dropdown at the top
3. Click "NEW PROJECT"
4. Enter a project name, e.g. "FraiseQL Auth"
5. Click "CREATE"

## Step 2: Configure the OAuth Consent Screen

1. In the Cloud Console, open "APIs & Services" → "OAuth consent screen"
2. User Type: **External**
3. App name: e.g. "My FraiseQL App"
4. User support email and developer contact: your email
5. Add the scopes you need (typically `openid`, `email`, `profile`)
6. Click "SAVE AND CONTINUE" through the remaining screens

## Step 3: Create OAuth Credentials

1. In the Cloud Console, go to "Credentials" (left sidebar)
2. Click "Create Credentials" → "OAuth client ID"
3. Application type: **Web application**
4. Name: e.g. "My FraiseQL Web Client"
5. **Authorized JavaScript origins** (your front-end origins):
   - `http://localhost:3000` (local development)
   - `https://yourdomain.com` (production)
6. **Authorized redirect URIs** — point these at whoever completes the OAuth flow:
   - **Path A (Auth0):** `https://YOUR_TENANT.auth0.com/login/callback`
   - **Path B (your client app):** `http://localhost:3000/auth/callback` (dev) and
     `https://yourdomain.com/auth/callback` (production)
7. Click "CREATE"

You'll see your credentials. Note:

- **Client ID**: `YOUR_CLIENT_ID.apps.googleusercontent.com`
- **Client Secret**: `YOUR_CLIENT_SECRET`

> The redirect URI **never** points at the FraiseQL/GraphQL endpoint. FraiseQL only
> receives the resulting token on the `Authorization: Bearer ...` header of GraphQL
> requests — it does not handle the `?code=...` callback.

---

## Path A (recommended): Auth0 as a broker

Let Auth0 handle the OAuth dance with Google and issue its own JWTs. FraiseQL then
validates Auth0 tokens with the built-in `Auth0Provider`.

### A.1 Add Google as a social connection in Auth0

1. In the Auth0 dashboard, go to "Authentication" → "Social" → "Create Connection"
2. Choose **Google / Gmail**
3. Paste the **Client ID** and **Client Secret** from Step 3
4. Enable the connection for your Auth0 application
5. Confirm the Google redirect URI in Auth0 matches what you registered in Step 3
   (`https://YOUR_TENANT.auth0.com/login/callback`)

Create an **API** in Auth0 (Applications → APIs) and note its **Identifier** — this is
the `audience` of the tokens Auth0 will issue and what FraiseQL validates against.

### A.2 Configure FraiseQL to trust Auth0

Auth0 tokens are standard RS256 JWTs validated against Auth0's JWKS. Configure FraiseQL
via environment variables (`FRAISEQL_` prefix) or directly in code.

```bash
# PostgreSQL connection
FRAISEQL_DATABASE_URL=postgresql://user:password@localhost/mydb

# Auth0 (tokens are Auth0-issued; Google is upstream)
FRAISEQL_AUTH_PROVIDER=auth0
FRAISEQL_AUTH0_DOMAIN=YOUR_TENANT.auth0.com
FRAISEQL_AUTH0_API_IDENTIFIER=https://api.yourdomain.com
```

```python
import fraiseql
from fraiseql.auth import Auth0Provider
from fraiseql.fastapi import create_fraiseql_app

# Validate Auth0-issued JWTs (RS256 by default, JWKS fetched automatically)
auth = Auth0Provider(
    domain="YOUR_TENANT.auth0.com",
    api_identifier="https://api.yourdomain.com",
)

app = create_fraiseql_app(
    database_url="postgresql://user:password@localhost/mydb",
    types=[User],
    queries=[me],
    auth=auth,
    production=False,  # False enables the GraphQL playground
)
```

Run it with uvicorn like any FastAPI app:

```bash
uvicorn app:app --reload
```

That's it — your users sign in with Google through Auth0, and every GraphQL request
carrying a valid Auth0 `Authorization: Bearer <jwt>` header gets a populated
`info.context["user"]` (a `UserContext`).

---

## Path B: custom provider validating Google ID tokens

If you don't want Auth0, run the OAuth flow in **your own client application** and send
Google's **ID token** to FraiseQL. Set `auth_provider="custom"` and implement an
`AuthProvider` subclass that validates that ID token directly.

### B.1 The `AuthProvider` interface

This is the real interface from `src/fraiseql/auth/base.py`. A custom provider must
implement two async methods; `get_user_context` is a helper you call from them.

```python
from abc import ABC, abstractmethod
from typing import Any


class AuthProvider(ABC):
    @abstractmethod
    async def validate_token(self, token: str) -> dict[str, Any]:
        """Validate a token and return its decoded payload (or raise)."""

    @abstractmethod
    async def get_user_from_token(self, token: str) -> UserContext:
        """Validate a token and return the resolved UserContext."""
```

`UserContext` (also from `base.py`) is what your resolvers read off
`info.context["user"]`:

```python
UserContext(
    user_id="...",          # required — use Google's `sub`
    email=None,             # str | None
    name=None,              # str | None
    roles=[],               # list[str]
    permissions=[],         # list[str]
    metadata={},            # dict[str, Any]
)
# Helpers: .has_role(...), .has_permission(...), .has_any_role(...), .has_any_permission(...)
```

### B.2 Implement a Google ID-token provider

Validate Google's ID tokens against Google's JWKS
(`https://www.googleapis.com/oauth2/v3/certs`), with issuer
`https://accounts.google.com` and your OAuth **client ID** as the audience.

```python
from typing import Any

import jwt  # PyJWT
from jwt import PyJWKClient

from fraiseql.auth import AuthProvider, UserContext
from fraiseql.auth.base import InvalidTokenError

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUER = "https://accounts.google.com"


class GoogleIDTokenProvider(AuthProvider):
    """Validate Google ID tokens directly (no Auth0 broker)."""

    def __init__(self, client_id: str) -> None:
        self.client_id = client_id  # your OAuth client ID == the token audience
        self._jwks_client = PyJWKClient(GOOGLE_JWKS_URL, cache_keys=True)

    async def validate_token(self, token: str) -> dict[str, Any]:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=GOOGLE_ISSUER,
            )
        except jwt.PyJWTError as exc:
            msg = f"Invalid Google ID token: {exc}"
            raise InvalidTokenError(msg) from exc

    async def get_user_from_token(self, token: str) -> UserContext:
        payload = await self.validate_token(token)
        return self.get_user_context(payload)

    def get_user_context(self, payload: dict[str, Any]) -> UserContext:
        return UserContext(
            user_id=payload["sub"],            # Google's stable subject id
            email=payload.get("email"),
            name=payload.get("name"),
            metadata={"email_verified": payload.get("email_verified", False)},
        )
```

> `PyJWKClient.get_signing_key_from_jwt` is synchronous; for high-throughput services
> wrap it (e.g. `asyncio.to_thread`) so it doesn't block the event loop.

### B.3 Wire the custom provider into the app

```python
import fraiseql
from fraiseql.fastapi import create_fraiseql_app

auth = GoogleIDTokenProvider(
    client_id="YOUR_CLIENT_ID.apps.googleusercontent.com",
)

app = create_fraiseql_app(
    database_url="postgresql://user:password@localhost/mydb",
    types=[User],
    queries=[me],
    auth=auth,            # auth_provider="custom" semantics — pass your AuthProvider
    production=False,
)
```

Your front-end runs the Google authorization-code flow (or Google Identity Services),
obtains the ID token, and sends it on GraphQL requests as
`Authorization: Bearer <google_id_token>`.

---

## Reading the user in a resolver

Once either path is wired, the authenticated user is available on the GraphQL context.
You can also gate operations with FraiseQL's auth decorators.

```python
import fraiseql
from fraiseql.auth import requires_auth


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: fraiseql.ID
    email: str
    name: str | None


@fraiseql.query
@requires_auth
async def me(info) -> User | None:
    user = info.context["user"]            # a UserContext (Google `sub` -> user_id)
    db = info.context["db"]
    return await db.find_one("v_user", id=user.user_id)
```

Denied access surfaces as a GraphQL error with `extensions.code = "FORBIDDEN"`.

## Testing the flow

Send a GraphQL request with the token your chosen path issued (an Auth0 JWT for Path A,
a Google ID token for Path B):

```bash
curl -X POST http://localhost:8000/graphql \
  -H "Authorization: Bearer <your_token>" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ me { id email name } }"}'
```

A valid token returns the current user; a missing or invalid token returns a GraphQL
error with `extensions.code = "FORBIDDEN"` (or an authentication error).

## Troubleshooting

### Error: "Invalid Redirect URI"

**Cause**: The redirect URI used in the OAuth flow doesn't match what's registered in
Google Cloud Console.

**Solution**:

- Path A: the redirect URI must be your Auth0 callback
  (`https://YOUR_TENANT.auth0.com/login/callback`).
- Path B: the redirect URI must be your client app's callback.
- Match `http://` vs `https://`, the host, the port, and trailing slashes exactly.

### Error: "Invalid audience" / "Invalid issuer"

**Cause**: The token's `aud` or `iss` claim doesn't match what your provider expects.

**Solution**:

- Path A: `auth0_api_identifier` must equal the Auth0 API Identifier (the `aud`).
- Path B: pass your Google OAuth **client ID** as the audience and verify
  `iss == https://accounts.google.com`.

### Error: "Token signature verification failed"

**Cause**: The token isn't signed by the expected key, or JWKS is stale.

**Solution**:

- Confirm the JWKS URL: Auth0 (`https://YOUR_TENANT.auth0.com/.well-known/jwks.json`)
  or Google (`https://www.googleapis.com/oauth2/v3/certs`).
- Ensure you're validating RS256 tokens; both Auth0 and Google use RS256 here.

### Error: "FORBIDDEN" on every request

**Cause**: No `Authorization` header, an expired token, or the wrong provider configured.

**Solution**:

- Send `Authorization: Bearer <jwt>` on the GraphQL request.
- Check token expiry (`exp`) and re-authenticate.
- Verify `auth_provider` / the `auth=` provider matches the token issuer.

## Security Considerations

1. **Client Secret**: Never expose it in client-side code. With Path A it lives only in
   Auth0; with Path B it lives only in your server-side OAuth exchange.
2. **HTTPS**: Always use HTTPS in production. HTTP is acceptable only for localhost.
3. **Redirect URIs**: Register only the exact redirect URIs you use.
4. **Audience & issuer**: Always validate both `aud` and `iss` — never accept a token
   just because its signature is valid.
5. **Token expiry**: Honor `exp`; refresh upstream (via Auth0 or Google) as needed.

## Additional Resources

- [Google OAuth 2.0 Documentation](https://developers.google.com/identity/protocols/oauth2)
- [OpenID Connect with Google](https://developers.google.com/identity/openid-connect)
- [Auth0 Google Social Connection](https://auth0.com/docs/authenticate/identity-providers/social-identity-providers/google)
- [FraiseQL Auth API Reference](./api-reference.md)

---

**Next Step**: See [API Reference](./api-reference.md) for the full authentication API.

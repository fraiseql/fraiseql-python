---
title: FraiseQL Authentication Troubleshooting Guide
description: Common issues and solutions for FraiseQL authentication.
keywords: ["framework", "authentication", "auth0", "jwt", "fastapi", "postgresql"]
tags: ["documentation", "reference"]
---

# FraiseQL Authentication Troubleshooting Guide

Common issues and solutions for FraiseQL authentication.

FraiseQL v1 auth runs **inside your FastAPI application** (Python). You start the app
with `uvicorn app:app` and validate tokens with an `AuthProvider` (Auth0, a native
provider, or a custom `AuthProvider` subclass). Denied operations surface as a GraphQL
error with `extensions.code = "FORBIDDEN"` — there is no separate authentication server.

## Login Issues

### "Invalid Redirect URI" Error

**Symptoms**: OAuth provider returns "Invalid Redirect URI"

**Causes**:

- Redirect URI not registered with provider
- Protocol mismatch (http vs https)
- Port number incorrect
- Trailing slash mismatch

**Solutions**:

```bash
# Check configured redirect URI
echo $FRAISEQL_OAUTH_REDIRECT_URI

# Compare with provider settings
# Auth0 → Application Settings → Allowed Callback URLs
# (Any OIDC issuer behind a custom AuthProvider → that issuer's callback config)

# Exact match required:
# Bad:  http://localhost:8000/auth/callback  (different port than registered)
# Good: http://localhost:8000/auth/callback

# Bad:  http://example.com/auth/callback     (no https)
# Good: https://example.com/auth/callback
```

### "Invalid State" Error

**Symptoms**: After the OAuth provider redirects, you get an "Invalid State" error

**Causes**:

- State parameter expired (the provider's login took too long)
- User took too long to authenticate
- State cache cleared (app restarted mid-flow)
- Multiple browsers/tabs

**Solutions**:

```bash
# If state keeps expiring, check for:
# - Server clock skew (see "Token Expired" below)
# - Network delays
# - Browser/user delay

# Test with a fast round-trip:
# 1. Start auth flow
# 2. Authenticate immediately
# 3. Should succeed

# If a fast round-trip works, the state lifetime is fine and the
# original failure was just a slow user/login. State lifetime is
# controlled by your OAuth/OIDC provider settings (e.g. Auth0).
```

### "Invalid Code" or "Code Expired"

**Symptoms**: Authorization code rejected by the OAuth provider

**Causes**:

- Code already used (codes are single-use)
- Code expired
- Wrong client credentials
- Network issues during the token exchange

**Solutions**:

```bash
# Check Auth0 (or your issuer) credentials
echo "Domain: $FRAISEQL_AUTH0_DOMAIN"
echo "API identifier: $FRAISEQL_AUTH0_API_IDENTIFIER"

# Verify they match the provider dashboard exactly.
# Don't transcribe by hand — copy from the provider.

# Run the app with auth debug logging (see "Debugging" below) and watch
# for the token-exchange failure:
uvicorn app:app --reload

# If it's a network issue, check:
# - DNS resolution to the provider
# - TLS certificate validity
# - Network connectivity

curl -v https://YOUR_TENANT.auth0.com/oauth/token
```

### "User Not Found" or "Invalid Credentials"

**Symptoms**: The user reaches the provider login but fails there

**Causes**:

- User account doesn't exist
- Wrong username/password
- Account locked/disabled
- Provider not recognizing the user

**Solutions**:

```bash
# For Auth0:
# - Verify the user exists in the Auth0 dashboard
# - Check the user is not blocked
# - If using a database connection, check it's enabled
# - If using social login, check that connection is enabled

# For a custom OIDC issuer (behind a custom AuthProvider subclass):
# - Verify the user exists in that issuer
# - Check the account is enabled
# - Verify the password / federation source

# For the built-in native provider:
# - Verify the account exists and is_active = true
# - A disabled account returns 403 "Account is disabled"
```

## Token Issues

### "Token Expired" on a Valid Token

**Symptoms**: A token was just issued but you get a "Token Expired" error

**Causes**:

- Server clock skew
- Token actually expired
- Wrong JWT issuer
- Validation config mismatch (`auth0_domain` / `auth0_api_identifier`)

**Solutions**:

```bash
# Check the server clock
date -u
# Should be within a few seconds of an NTP source

# Fix if needed
sudo systemctl restart chrony   # or: sudo ntpdate -s time.nist.gov

# Check the configured issuer/audience match the provider
echo "Auth0 domain:        $FRAISEQL_AUTH0_DOMAIN"
echo "Auth0 API identifier: $FRAISEQL_AUTH0_API_IDENTIFIER"
```

Decode the token and inspect the `exp` claim (use [jwt.io](https://jwt.io) or):

```python
import base64
import json
import time

token = "your_token_here"
payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
print(f"Expires in: {payload['exp'] - int(time.time())} seconds")
```

### "Invalid Signature" on a Token

**Symptoms**: Token rejected with "Invalid Signature"

**Causes**:

- JWKS public-key mismatch
- Token modified in transit
- Wrong signing algorithm
- Key rotation (provider rotated keys, the app cached the old set)

**Solutions**:

```bash
# Verify the provider's JWKS endpoint responds
curl https://YOUR_TENANT.auth0.com/.well-known/jwks.json | jq .

# Check the configured algorithms (default: ["RS256"])
echo "Algorithms: $FRAISEQL_AUTH0_ALGORITHMS"
# Should be RS256 for Auth0 / most OIDC providers

# Verify the issuer/audience match
echo "Domain:         $FRAISEQL_AUTH0_DOMAIN"
echo "API identifier: $FRAISEQL_AUTH0_API_IDENTIFIER"

# If the provider rotated keys, restart the app to re-fetch JWKS:
# stop uvicorn, then
uvicorn app:app
```

### Can't Refresh Token

**Symptoms**: The refresh endpoint returns "Token Not Found" or "Invalid token"

This applies when you use FraiseQL's **native** auth provider (it issues and tracks
refresh tokens in PostgreSQL via the token-revocation store). Pure Auth0/OIDC setups
refresh against the provider, not FraiseQL.

**Causes**:

- Refresh token revoked
- Session expired
- Database connection issue
- Wrong token format

**Solutions**:

```bash
# Verify your database connection
echo $FRAISEQL_DATABASE_URL
psql "$FRAISEQL_DATABASE_URL" -c "SELECT 1;"

# Check whether the token was revoked (PostgreSQLRevocationStore).
# The exact table name comes from your RevocationConfig; inspect with:
psql "$FRAISEQL_DATABASE_URL" -c "\dt *revocation*"

# If the refresh token was revoked or expired, the user must log in again.
```

## Database Issues

### "Connection Refused"

**Symptoms**: The app fails to start with "Connection refused" to the database

**Causes**:

- PostgreSQL not running
- Wrong host/port
- Firewall blocking
- Wrong credentials

**Solutions**:

```bash
# Check the connection string
echo $FRAISEQL_DATABASE_URL
# Should be: postgresql://user:pass@host:5432/dbname

# Test the connection directly
psql "$FRAISEQL_DATABASE_URL" -c "SELECT 1;"

# If still failing, check the network path
telnet prod-db.internal 5432

# Then start the app with debug logging to see the pool error:
FRAISEQL_LOG_LEVEL=DEBUG uvicorn app:app
```

### "FATAL: database does not exist"

**Symptoms**: PostgreSQL reports the database is not found

**Solutions**:

```bash
# Create the database if it's missing
createdb -h localhost -U postgres mydb

# Verify your read views / functions exist
psql "$FRAISEQL_DATABASE_URL" -c "\dv v_*"
psql "$FRAISEQL_DATABASE_URL" -c "\df fn_*"
```

### Revocation / Session Table Missing

**Symptoms**: Errors about a missing token-revocation table when using the native
provider with `PostgreSQLRevocationStore`

**Solutions**:

The `PostgreSQLRevocationStore` creates and manages its own table from your
`RevocationConfig`. Make sure the configured database user can create tables, then
let the store initialize at startup. To inspect what exists:

```bash
psql "$FRAISEQL_DATABASE_URL" -c "\dt *revocation*"
```

If you provisioned the schema separately, confirm the table the store expects is
present (its name is set in `RevocationConfig`); otherwise grant `CREATE` on the
schema and restart the app so the store can create it.

## Performance Issues

### Login Is Slow

**Symptoms**: The auth flow takes more than ~2 seconds

**Causes**:

- OAuth/OIDC provider slow (or first JWKS fetch)
- Network latency
- Database slow (native provider session lookups)
- App process overloaded

**Solutions**:

```bash
# Check provider latency
time curl -I https://YOUR_TENANT.auth0.com/

# Check database query time
psql "$FRAISEQL_DATABASE_URL" -c \
  "SELECT query, calls, total_exec_time/calls AS avg_time \
   FROM pg_stat_statements \
   ORDER BY avg_time DESC LIMIT 10;"

# If the connection pool is the bottleneck, raise it in your config:
export FRAISEQL_DATABASE_POOL_SIZE=50

# Then enable debug logging to confirm where the time goes:
FRAISEQL_LOG_LEVEL=DEBUG uvicorn app:app
```

### High CPU Usage

**Symptoms**: The app process uses a lot of CPU

**Causes**:

- Many simultaneous logins
- Repeated JWKS fetches (key cache disabled/misconfigured)
- Brute-force attempts

**Solutions**:

```bash
# Check active database connections
psql "$FRAISEQL_DATABASE_URL" -c \
  "SELECT count(*) FROM pg_stat_activity;"

# Look for repeated auth failures (brute force) in the app logs
# (see "Debugging" below for how to surface auth logs)

# Mitigate abuse at the edge with a reverse-proxy rate limit, e.g. nginx:
#   limit_req_zone $binary_remote_addr zone=auth:10m rate=1r/s;

# For legitimate load, run more uvicorn workers / app instances:
uvicorn app:app --workers 4
```

### High Memory Usage

**Symptoms**: Memory grows over time

**Causes**:

- Native-provider sessions / revoked tokens not being pruned
- Unbounded in-process caches (e.g. `InMemoryRevocationStore`)

**Solutions**:

```bash
# If using PostgreSQLRevocationStore, prune expired revocations periodically.
# The TokenRevocationService / store exposes cleanup; you can also age out
# rows directly once you confirm the table name from RevocationConfig:
psql "$FRAISEQL_DATABASE_URL" -c "\dt *revocation*"

# Prefer PostgreSQLRevocationStore over InMemoryRevocationStore for any
# long-running or multi-process deployment — the in-memory store grows
# unbounded and is not shared across workers.
```

## OAuth Provider Issues

### "OAuth Provider Unreachable"

**Symptoms**: The app can't reach the OAuth/OIDC provider

**Causes**:

- Provider down
- Network connectivity
- Firewall/proxy blocking
- DNS resolution failure

**Solutions**:

```bash
# Check provider reachability
curl -I https://YOUR_TENANT.auth0.com/

# Check DNS resolution
nslookup YOUR_TENANT.auth0.com

# Check network connectivity
ping YOUR_TENANT.auth0.com

# Check firewall rules
sudo ufw status

# If the app runs behind a proxy:
export https_proxy=http://proxy.internal:3128
```

### "Cannot Get Public Keys"

**Symptoms**: JWT validation fails because the app can't fetch JWKS public keys

**Solutions**:

```bash
# Check the OIDC discovery metadata
curl https://YOUR_TENANT.auth0.com/.well-known/openid-configuration

# Check the JWKS endpoint directly
curl https://YOUR_TENANT.auth0.com/.well-known/jwks.json

# If both respond, restart the app to clear the cached key set:
uvicorn app:app

# Check for TLS/certificate issues
curl -v https://YOUR_TENANT.auth0.com/ 2>&1 | grep -i "certificate"
```

## Authorization Issues

### Operation Denied with `extensions.code = "FORBIDDEN"`

**Symptoms**: A query/mutation returns a GraphQL error whose
`extensions.code` is `"FORBIDDEN"`, often with `required_role`,
`required_roles`, or `required_permission`.

**Causes**:

- The resolver is guarded by `@requires_auth` / `@requires_role` /
  `@requires_permission` (and `@requires_any_role` / `@requires_any_permission`)
  and the request's `UserContext` lacks the needed role/permission.
- An `Authorizer` attached via `@fraiseql.query(authorizer=...)` (or `mutation` /
  `subscription`, or app-wide via `create_fraiseql_app(authorizer=...)`) returned
  `AuthorizationDecision.deny(...)`.
- The token validated, but the roles/permissions claims weren't mapped onto the
  `UserContext`.

**Solutions**:

Inspect the `UserContext` that the resolver actually sees. It lives at
`info.context["user"]`:

```python
@fraiseql.query
async def whoami(info) -> str:
    user = info.context["user"]  # a UserContext
    return (
        f"user_id={user.user_id} "
        f"roles={user.roles} "
        f"permissions={user.permissions}"
    )
```

`UserContext` exposes `has_role`, `has_permission`, `has_any_role`,
`has_any_permission` (plus `has_all_roles` / `has_all_permissions`). If
`roles`/`permissions` are empty, the problem is in your provider's claim mapping,
not the guard:

- **Auth0**: ensure the roles/permissions are present in the token (add them via an
  Auth0 Action/rule, or enable RBAC + "Add Permissions in the Access Token" on the
  API). The provider maps `roles` and `permissions` claims onto the `UserContext`.
- **Custom provider**: in your `AuthProvider.get_user_from_token`, populate
  `UserContext(user_id=..., roles=[...], permissions=[...])` from the decoded payload.

### 401 vs 403 (Unauthenticated vs Forbidden)

- **No / invalid token → unauthenticated.** `@requires_auth` raises when
  `info.context["user"]` is missing, and the native provider's HTTP routes return
  `401` for bad credentials.
- **Valid token but insufficient role/permission → forbidden.** The role/permission
  guards raise a GraphQL error with `extensions.code = "FORBIDDEN"`; the native
  provider's HTTP routes return `403` (e.g. "Account is disabled").

If you expect 403 but get 401, the token isn't being parsed at all — check the
`Authorization: Bearer <token>` header and the provider config. If you expect 401 but
get 403, the token *is* valid; the user simply lacks the role/permission.

## Debugging

### Enable Debug Logging

FraiseQL auth uses the standard Python `logging` module. Raise the level on the
`fraiseql` parent logger (or the `fraiseql.auth` subtree) to see token validation and
authorization decisions:

```python
import logging

# Everything FraiseQL emits
logging.getLogger("fraiseql").setLevel(logging.DEBUG)

# Or just the auth subtree (token validation, revocation, providers)
logging.getLogger("fraiseql.auth").setLevel(logging.DEBUG)
```

You can also set the level via the `FRAISEQL_LOG_LEVEL` environment variable when
launching the app:

```bash
FRAISEQL_LOG_LEVEL=DEBUG uvicorn app:app --reload
```

### Check Detailed Logs

```bash
# Run the app in the foreground and watch the logs
uvicorn app:app --reload

# Save logs to a file
uvicorn app:app > logs.txt 2>&1

# Search for auth errors/warnings
grep -iE "error|warn" logs.txt
```

### Test the GraphQL Endpoint Manually

```bash
# Send an authenticated query to the FraiseQL GraphQL endpoint
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query":"{ whoami }"}' | jq .

# A FORBIDDEN response looks like:
# { "errors": [ { "message": "...", "extensions": { "code": "FORBIDDEN", ... } } ] }
```

When `production=False`, you can also open the GraphQL playground in a browser at
`/graphql` and add an `Authorization` header to experiment interactively.

## Getting Help

1. **Enable debug logging**: set `logging.getLogger("fraiseql.auth")` to `DEBUG`, or
   launch with `FRAISEQL_LOG_LEVEL=DEBUG uvicorn app:app`.
2. **Inspect the `UserContext`**: log `info.context["user"]` to confirm roles/permissions.
3. **Decode the token**: check `iss`, `aud`, `exp`, and the roles/permissions claims.
4. **Check the issue tracker** and open an issue with:
   - The error message and any `extensions.code` (no secrets!)
   - Steps to reproduce
   - Environment (OS, Python version, FraiseQL version)
   - Logs with debug enabled

---

See Also:

- [Deployment Guide](./deployment.md)
- [Monitoring Guide](./monitoring.md)
- [Security Checklist](./security-checklist.md)
- [API Reference](./api-reference.md)

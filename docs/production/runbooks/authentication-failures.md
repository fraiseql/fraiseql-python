# Authentication Failures Runbook

**Last Updated**: 2026-10-25
**Severity**: HIGH
**MTTR Target**: 15 minutes

---

## 📋 Overview

This runbook guides you through diagnosing and resolving authentication failures in FraiseQL applications. Authentication issues can indicate security attacks, misconfiguration, or service degradation.

---

## 🚨 Symptoms

### Primary Indicators

- Spike in 401 Unauthorized errors
- Increase in 403 Forbidden errors
- Valid users unable to access API
- Token validation failures
- Authentication service degradation

### Prometheus Metrics to Monitor

FraiseQL has no authentication metric. With the metrics middleware installed
(`setup_metrics(app)`, see [Metrics](./README.md#metrics-quick-reference)), a
request rejected for a missing or invalid token is counted with status `401`:

```promql
# Rejected requests per second
sum(rate(fraiseql_http_requests_total{status="401"}[5m]))

# Percentage of requests rejected
sum(rate(fraiseql_http_requests_total{status="401"}[5m]))
  / sum(rate(fraiseql_http_requests_total[5m])) * 100

# 403s (permission checks that answer with HTTP 403)
sum(rate(fraiseql_http_requests_total{status="403"}[5m]))
```

The metric has no user, IP or reason label; use the logs for those.

### Log Entries

`Auth0Provider` logs each token it rejects on the `fraiseql.security` logger at
`WARNING`, as a JSON security event:

```json
{
  "event_type": "auth.token_expired",
  "severity": "warning",
  "timestamp": "2026-10-25T14:22:05.789012+00:00",
  "user_id": null,
  "user_email": null,
  "ip_address": null,
  "user_agent": null,
  "request_id": null,
  "resource": null,
  "action": null,
  "result": null,
  "reason": "Token has expired",
  "metadata": {}
}
```

The other event types are `auth.token_invalid` (`reason` is `"Invalid token: ..."`,
e.g. a bad signature, audience or issuer), `auth.failure` (any other validation
error; `metadata.error_type` names it) and `auth.success` (`user_id` is the token's
`sub`). The events have no IP address. A provider of your own logs only what it
logs itself.

With an auth provider, a GraphQL request without a valid token gets a 401
`{"detail": "Authentication required"}`.

---

## 🔍 Diagnostic Steps

### Step 1: Classify Authentication Failures

**Via Prometheus**:

```promql
sum(rate(fraiseql_http_requests_total{status="401"}[5m]))
```

**Via the security log** (`security_events.log`, or wherever your handler writes
the `fraiseql.security` logger):

```bash
# Count rejections by event type
grep -o '"event_type": "auth\.[a-z_]*"' security_events.log | sort | uniq -c | sort -rn

# Example output:
#  450 "event_type": "auth.token_invalid"
#  120 "event_type": "auth.token_expired"
#   12 "event_type": "auth.failure"

# Reasons of the invalid tokens
grep '"auth.token_invalid"' security_events.log | grep -o '"reason": "[^"]*"' \
  | sort | uniq -c | sort -rn
```

**Common causes, by event**:

- `auth.token_expired`: a valid token past its `exp`
- `auth.token_invalid`: bad signature, wrong audience or issuer, malformed token
- `auth.failure`: the JWKS couldn't be fetched, or another validation error
- no event, but a 401: the request had no `Authorization: Bearer` header
- 403: authenticated, but a permission or role check refused it

### Step 2: Identify Affected Clients

The security events have no client address. Find the clients in your access logs
(reverse proxy, load balancer, or uvicorn's access log), which have the status:

```bash
# uvicorn access log: client addresses of the 401s
grep '" 401' access.log | awk '{print $1}' | sort | uniq -c | sort -rn | head -20
```

### Step 3: Determine Root Cause Category

#### A. Token Expiration Issues

**Symptoms**:

- Many `auth.token_expired` events
- Concentrated around specific time period
- Affects multiple users simultaneously

**Check**:

```bash
# Count expired tokens
grep -c '"auth.token_expired"' security_events.log

# Lifetime of a failing token, in seconds (exp - iat); the issuer sets it,
# fraiseql only checks exp
echo "$TOKEN" | cut -d. -f2 | tr '_-' '/+' | base64 -d 2>/dev/null | jq '.exp - .iat'
```

**Likely Causes**:

- Token lifetime too short
- Frontend not refreshing tokens
- Clock skew between services

#### B. Token Signature Failures

**Symptoms**:

- Many `auth.token_invalid` events with `"reason": "Invalid token: Signature verification failed"`
- Started after deployment or config change
- All tokens failing validation

**Check**:

```bash
# Check the signing secret your auth provider validates with (here JWT_SECRET,
# the variable the provider below reads; fraiseql reads none itself)
echo $JWT_SECRET | wc -c  # Should be 32+ characters

# Check if key changed recently
git log --since="24 hours ago" --grep="JWT_SECRET" --oneline

# Verify key consistency across instances
# (All instances must use same secret!)
```

**Likely Causes**:

- JWT secret key mismatch between services
- Key rotation without grace period
- Configuration drift across instances

#### C. Brute Force Attack

**Symptoms**:

- Same IP trying multiple passwords
- Failed attempts for many different usernames
- Rapid succession of failures

**Check**:

fraiseql never sees passwords (your identity provider checks them), so a
credential attack shows at the provider (Auth0 logs, anomaly detection). Against
the API, it shows as many 401s from few clients:

```bash
# 401s per client address in the access log; a high count from one address
grep '" 401' access.log | awk '{print $1}' | sort | uniq -c | sort -rn | head -10
```

**Likely Causes**:

- Credential stuffing attack
- Password spraying attack
- Compromised credential database

#### D. Service Degradation

**Symptoms**:

- All authentication failing suddenly
- Service health check failing
- External auth service unreachable

**Check**:

```bash
# Check auth service health
curl -s http://localhost:8000/health | jq .

# Check external OAuth provider (if used)
curl -s https://oauth.provider.com/.well-known/openid-configuration

# Check database connectivity
psql -c "SELECT 1" postgresql://localhost/fraiseql
```

**Likely Causes**:

- Database connectivity issues
- External OAuth provider down
- Redis/cache service unavailable
- Rate limiting on auth service

---

## 🔧 Resolution Steps

### For Token Expiration Issues (5-10 minutes)

fraiseql validates tokens through the provider passed as `create_fraiseql_app(auth=...)`;
it doesn't issue them. Token lifetimes and the refresh flow belong to the issuer:
with Auth0 (`auth=Auth0Config(...)`), set the API's token expiration in the Auth0
dashboard; with your own issuer, in its configuration.

#### 1. Increase Token Lifetime (If Too Short)

Raise the access token lifetime at the issuer (e.g. Auth0 > APIs > your API >
Token Expiration), then have clients log in again. Existing tokens keep their old
`exp`.

#### 2. Make Sure Clients Refresh Tokens

The issuer's refresh endpoint (Auth0: `POST https://<domain>/oauth/token` with
`grant_type=refresh_token`) returns a new access token; the client should call it
before `exp`, or on a 401, and retry with the new token.

#### 3. Allow a Little Clock Skew

A provider of your own can accept tokens that expired a few seconds to minutes ago
with PyJWT's `leeway` (the provider below takes `leeway_seconds`). Keep it small:
it extends every token's life.

### For Token Signature Issues (10-15 minutes)

#### 1. Verify JWT Secret Consistency

```bash
# Check current secret (all instances must match!)
echo $JWT_SECRET

# Update secret if needed (COORDINATED ROLLOUT REQUIRED)
export JWT_SECRET="new-secret-key-at-least-32-chars-long"

# Restart all instances simultaneously
kubectl rollout restart deployment fraiseql
```

#### 2. Implement Key Rotation with Grace Period

With Auth0, signing keys rotate through the tenant's JWKS, which `Auth0Provider`
fetches, so there's nothing to do in fraiseql. A provider of your own that checks
an HS256 secret can accept the previous secret while tokens signed with it are
still alive:

```python
import os

import jwt

from fraiseql.auth import AuthProvider, UserContext
from fraiseql.auth.base import AuthenticationError
from fraiseql.fastapi import create_fraiseql_app


class RotatingJWTProvider(AuthProvider):
    """Validate HS256 tokens signed with the current or the previous secret."""

    def __init__(self, secrets: list[str], leeway_seconds: int = 0) -> None:
        self.secrets = [secret for secret in secrets if secret]
        self.leeway_seconds = leeway_seconds

    async def validate_token(self, token: str) -> dict:
        for secret in self.secrets:
            try:
                return jwt.decode(
                    token, secret, algorithms=["HS256"], leeway=self.leeway_seconds
                )
            except jwt.InvalidSignatureError:
                continue  # Try the next secret
            except jwt.InvalidTokenError as e:
                raise AuthenticationError(str(e)) from e
        raise AuthenticationError("Invalid token signature")

    async def get_user_from_token(self, token: str) -> UserContext:
        payload = await self.validate_token(token)
        return UserContext(
            user_id=payload["sub"],
            roles=payload.get("roles", []),
            permissions=payload.get("permissions", []),
        )


auth_provider = RotatingJWTProvider(
    secrets=[os.environ["JWT_SECRET"], os.environ.get("JWT_SECRET_OLD", "")],
    leeway_seconds=30,
)
app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[me],
    auth=auth_provider,
)
```

With an auth provider, a request whose token fails validation (or that has none)
gets a 401 `{"detail": "Authentication required"}`.

**Rotation Process**:

```bash
# Step 1: Keep the current key as the old one, sign new tokens with the new key
export JWT_SECRET_OLD="$JWT_SECRET"
export JWT_SECRET="new-key-here"
kubectl rollout restart deployment fraiseql

# Step 2: Switch the issuer to the new key; wait until every token signed with the
# old key has expired (the longest token lifetime)

# Step 3: Remove the old key
unset JWT_SECRET_OLD
kubectl rollout restart deployment fraiseql
```

#### 3. Fix Clock Skew (If Present)

```bash
# Check clock skew between services
date -u  # On application server
date -u  # On auth service

# Sync time with NTP
sudo ntpdate -s time.nist.gov

# Enable NTP daemon
sudo systemctl enable ntpd
sudo systemctl start ntpd
```

### For Brute Force Attacks (5 minutes)

fraiseql has no block list, account lockout or CAPTCHA: credentials are checked by
your identity provider (Auth0 has brute-force protection and bot detection settings
for this), and fraiseql only sees tokens.

#### 1. Block Attacking IPs

```bash
# Block at firewall level
sudo iptables -A INPUT -s 203.0.113.88 -j DROP

# Or use cloud provider firewall
# AWS Security Group, GCP Firewall Rule, etc.
```

#### 2. Rate Limit Authentication Endpoints

If the login endpoints are served by this app, limit them per client with
`RateLimitMiddleware` (5 requests every 5 minutes on `/auth/*` with the defaults of
`setup_rate_limiting`; see [Rate Limiting](./rate-limiting-triggered.md)):

```python
from fraiseql.security import RateLimit, RateLimitRule, setup_rate_limiting

setup_rate_limiting(
    app,
    custom_rules=[
        RateLimitRule(
            path_pattern="/auth/*",
            rate_limit=RateLimit(requests=5, window=300),
            message="Too many login attempts",
        ),
    ],
)
```

### For Service Degradation (15 minutes)

#### 1. Check External Dependencies

**OAuth Provider Health**:

```bash
# Check OAuth provider status
curl -s https://status.oauth-provider.com

# Test OAuth endpoints
curl -s https://oauth.provider.com/.well-known/openid-configuration
```

**Database Health**:

```bash
# Check database connectivity
psql -c "SELECT 1" $DATABASE_URL

# Check that the app reaches the database (503 with the failing check if not)
curl -s http://localhost:8000/ready | jq .checks
```

**Cache/Redis Health** (if the app uses Redis, e.g. for rate limit counters):

```bash
# Check Redis connectivity
redis-cli ping
```

#### 2. Ride Out an Identity Provider Outage

fraiseql has no fallback authentication or circuit breaker. `Auth0Provider` caches
the JWKS signing keys it has fetched (`cache_jwks=True`, the default; the key set for
an hour), so validating tokens already issued keeps working through a short Auth0
outage. New logins wait for the provider to recover.

---

## 📊 Monitoring & Alerts

### Prometheus Alert Rules

```yaml
# alerts/authentication.yml
groups:
  - name: authentication
    interval: 30s
    rules:
      - alert: HighAuthRejectionRate
        expr: |
          sum(rate(fraiseql_http_requests_total{status="401"}[5m])) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High rate of rejected (401) requests"
          description: "{{ $value }} rejections/sec"

      - alert: MostRequestsRejected
        expr: |
          sum(rate(fraiseql_http_requests_total{status="401"}[5m]))
          / sum(rate(fraiseql_http_requests_total[5m])) > 0.5
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "50%+ of requests rejected with 401"
          description: "Possible identity provider outage or signing key mismatch"
```

Alerts per client address or per reason need your log stack (Loki, ELK): count the
`auth.*` security events, and the 401s of the access log by client.

### Grafana Dashboard Panels

**1. Rejected Requests**:

```promql
sum(rate(fraiseql_http_requests_total{status="401"}[5m]))
```

**2. Percentage of Requests Rejected**:

```promql
sum(rate(fraiseql_http_requests_total{status="401"}[5m]))
  / sum(rate(fraiseql_http_requests_total[5m])) * 100
```

**3. Rejections by Event Type** (log panel): the `fraiseql.security` events whose
`event_type` starts with `auth.`, grouped by `event_type`.

---

## 🔍 Verification

After applying fixes, verify authentication is working:

### 1. Check Metrics

```promql
# Should decrease
sum(rate(fraiseql_http_requests_total{status="401"}[5m]))
```

### 2. Test Authentication

```bash
# A token from your identity provider
curl -i http://localhost:8000/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ __typename }"}'

# Should return 200, not 401
```

### 3. Check Logs

```bash
# Successful validations (Auth0Provider)
grep '"auth.success"' security_events.log | tail -10

# No ongoing rejections
grep -E '"auth\.(failure|token_expired|token_invalid)"' security_events.log | tail -10
```

---

## 📝 Post-Incident Review

After resolving the incident:

1. **Analyze Root Cause**:
   - Configuration issue?
   - External service degradation?
   - Security attack?
   - Code bug?

2. **Implement Preventive Measures**:
   - Add monitoring for early detection
   - Implement circuit breakers
   - Add fallback authentication
   - Improve key rotation process

3. **Security Improvements**:
   - Review token lifetime settings
   - Implement account lockout
   - Add brute force protection
   - Enable multi-factor authentication

4. **Update Documentation**:
   - Document token rotation process
   - Update troubleshooting guides
   - Share lessons learned

---

## 📚 Related Resources

- [Authentication Configuration](../security.md#authentication)
- [Rate Limiting](./rate-limiting-triggered.md)
- [Security Hardening](../security.md)

---

## 🆘 Escalation

If issue persists after following this runbook:

1. **Gather Evidence**:
   - Auth failure graphs (last 24 hours)
   - Top failing users/IPs
   - Sample failed requests
   - External service status

2. **Escalate To**:
   - Security Team (for attack investigation)
   - Platform Team (for service health)
   - Engineering Team (for code fixes)

3. **Emergency Contact**:
   - Security On-call: [Contact info]
   - Platform On-call: [Contact info]
   - Engineering Manager: [Contact info]

---

**Version**: 1.0
**Last Tested**: 2025-12-29
**Next Review**: 2026-03-29

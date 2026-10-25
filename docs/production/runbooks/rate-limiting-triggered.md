# Rate Limiting Triggered Runbook

**Last Updated**: 2025-12-29
**Severity**: MEDIUM
**MTTR Target**: 10 minutes

---

## 📋 Overview

This runbook guides you through investigating and responding to rate limiting events in FraiseQL applications. Rate limiting protects your application from abuse, but legitimate users may occasionally trigger limits.

---

## 🚨 Symptoms

### Primary Indicators

- Users receiving 429 Too Many Requests errors
- Increase in rate limit violations
- Spike in blocked requests
- Legitimate traffic patterns triggering limits

### Prometheus Metrics to Monitor

```promql
# Rate limit violations
rate(fraiseql_rate_limit_exceeded_total[5m])

# Blocked requests percentage
(rate(fraiseql_rate_limit_exceeded_total[5m])
/ rate(fraiseql_http_requests_total[5m])) * 100

# Rate limit violations by user
topk(10, sum by (user_id) (fraiseql_rate_limit_exceeded_total))
```

### Structured Logs Examples

```json
{
  "timestamp": "2025-12-29T12:30:45.123Z",
  "level": "WARNING",
  "event": "security.rate_limit",
  "message": "Rate limit exceeded for user",
  "context": {
    "user_id": "user_789",
    "ip_address": "203.0.113.42",
    "endpoint": "/graphql",
    "limit": 100,
    "window_seconds": 60,
    "current_count": 105,
    "exceeded_by": 5
  },
  "trace_id": "trace_rate123"
}
```

```json
{
  "timestamp": "2025-12-29T12:31:15.456Z",
  "level": "ERROR",
  "event": "security.rate_limit_abuse",
  "message": "Potential abuse detected - excessive rate limit violations",
  "context": {
    "user_id": "user_999",
    "ip_address": "198.51.100.23",
    "violations_count": 50,
    "time_window_minutes": 5,
    "action": "temporary_block"
  },
  "trace_id": "trace_abuse456"
}
```

---

## 🔍 Diagnostic Steps

### Step 1: Identify Affected Users

**Via Prometheus**:

```promql
# Top users triggering rate limits
topk(10,
  sum by (user_id) (
    rate(fraiseql_rate_limit_exceeded_total[5m])
  )
)

# Top IP addresses
topk(10,
  sum by (ip_address) (
    rate(fraiseql_rate_limit_exceeded_total[5m])
  )
)
```

**Via Structured Logs**:

```bash
# Find rate limit events in last hour
jq -r 'select(.event == "security.rate_limit") |
  "\(.timestamp) \(.context.user_id) \(.context.ip_address) \(.context.current_count)/\(.context.limit)"' \
  /var/log/fraiseql/app.log | tail -100

# Count violations per user
jq -r 'select(.event == "security.rate_limit") | .context.user_id' \
  /var/log/fraiseql/app.log | sort | uniq -c | sort -rn | head -20

# Count violations per IP
jq -r 'select(.event == "security.rate_limit") | .context.ip_address' \
  /var/log/fraiseql/app.log | sort | uniq -c | sort -rn | head -20
```

### Step 2: Analyze Traffic Patterns

**Check Request Rate**:

```promql
# Requests per second by endpoint
sum by (endpoint) (
  rate(fraiseql_http_requests_total[5m])
)

# Requests per second by user
sum by (user_id) (
  rate(fraiseql_http_requests_total[5m])
)
```

**Check Request Distribution**:

```bash
# Timeline of rate limit events
jq -r 'select(.event == "security.rate_limit") |
  "\(.timestamp) \(.context.user_id)"' \
  /var/log/fraiseql/app.log | \
  cut -d'T' -f2 | cut -d':' -f1-2 | uniq -c

# Example output:
#  15 12:30  # 15 events at 12:30
#  42 12:31  # 42 events at 12:31 (spike!)
#   8 12:32  # Back to normal
```

### Step 3: Classify Traffic Type

**Legitimate vs. Abuse**:

```bash
# Legitimate user pattern (gradual increase)
jq -r 'select(.event == "security.rate_limit" and .context.user_id == "user_789") |
  "\(.timestamp) \(.context.current_count)"' \
  /var/log/fraiseql/app.log

# Example legitimate:
# 12:30:10 85   # Approaching limit
# 12:30:45 101  # Slightly over
# 12:31:20 90   # Back under

# Abuse pattern (sustained high volume)
jq -r 'select(.event == "security.rate_limit" and .context.user_id == "user_999") |
  "\(.timestamp) \(.context.current_count)"' \
  /var/log/fraiseql/app.log

# Example abuse:
# 12:30:10 150  # Consistently over
# 12:30:15 145
# 12:30:20 152
# 12:30:25 148  # No reduction
```

**User Agent Analysis**:

```bash
# Check if rate-limited requests have unusual User-Agent
jq -r 'select(.event == "security.rate_limit") |
  .context.user_agent // "unknown"' \
  /var/log/fraiseql/app.log | sort | uniq -c | sort -rn

# Look for:
# - Bot/crawler agents
# - Automated tool signatures
# - Missing User-Agent headers
```

### Step 4: Review Current Rate Limits

fraiseql's rate limits are whatever the app passes to `RateLimitMiddleware` (or
`setup_rate_limiting`) where it builds the app; look there. There are no
environment variables for them: `FraiseQLConfig` declares `rate_limit_*` settings,
but nothing reads them.

`setup_rate_limiting(app)` without arguments installs these limits, per client:

| Path | Limit |
|------|-------|
| `/graphql` | 60 requests a minute |
| `/auth/*` | 5 requests every 5 minutes |
| `/api/*` | 100 requests a minute |
| Any path (`default_limit`) | 100 requests a minute |
| `/graphql`, by operation type | 100 queries, 20 mutations, 10 subscriptions a minute |
| `/graphql`, by estimated cost | 200 cheap, 100 medium, 20 expensive requests a minute |

A client is `request.state.user_id` when a middleware of yours sets it, otherwise the
IP (the first `X-Forwarded-For` address, then `X-Real-IP`, then the peer address).
Windows are fixed (the count resets when a window ends), and the counters live in
each instance's memory. `/health`, `/ready` and `/metrics` are never limited.

---

## 🔧 Resolution Steps

### For Legitimate Users (5 minutes)

#### 1. Raise the Limit

There is no per-user override at runtime: raise the rule's limit and redeploy.

```python
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.security import RateLimit, RateLimitRule, setup_rate_limiting

app = create_fraiseql_app(database_url="postgresql://localhost/mydb", types=[User], queries=[users])

setup_rate_limiting(
    app,
    custom_rules=[
        RateLimitRule(
            path_pattern="/graphql",
            rate_limit=RateLimit(requests=200, window=60),  # Increased from 60
            message="GraphQL rate limit exceeded",
        ),
    ],
    default_limit=RateLimit(requests=200, window=60),
)
```

`custom_rules` replaces the default rules, so list every path you want limited.

#### 2. Exempt a Trusted Client (If Safe)

A rule's `exempt_func` lets a request through every limit when it returns `True`:

```python
TRUSTED_IPS = {"203.0.113.42"}  # Partner API integration


def is_trusted(request) -> bool:
    return request.client is not None and request.client.host in TRUSTED_IPS


setup_rate_limiting(
    app,
    custom_rules=[
        RateLimitRule(
            path_pattern="/graphql",
            rate_limit=RateLimit(requests=60, window=60),
            exempt_func=is_trusted,
        ),
    ],
)
```

#### 3. Notify User

fraiseql has no user notification API; tell the user through your usual support
channel what limit they hit and when it resets (`Retry-After` on the 429 response).

### For Abusive Traffic (10 minutes)

#### 1. Temporary Block

fraiseql has no block list. Block an authenticated user with an operation
authorizer that denies them (see
[Block Attacking User/IP](./graphql-query-dos.md#2-block-attacking-userip)).

#### 2. IP-Based Blocking

Block the address at the firewall or load balancer:

```bash
# Add iptables rule (requires root)
sudo iptables -A INPUT -s 198.51.100.23 -j DROP

# Or use cloud provider firewall
# AWS Security Group, GCP Firewall Rule, etc.
```

### Adjusting Global Rate Limits (30 minutes)

#### 1. Analyze Legitimate Traffic Patterns

```promql
# 95th percentile request rate (legitimate users)
histogram_quantile(0.95,
  sum by (le) (
    rate(fraiseql_http_requests_total{
      status!="429"
    }[1h])
  )
)
```

```bash
# Average requests per user per minute
jq -r 'select(.event == "http.request" and .context.status != 429) |
  "\(.context.user_id) \(.timestamp)"' \
  /var/log/fraiseql/app.log | \
  awk '{print $1, substr($2,1,16)}' | \
  sort | uniq -c | \
  awk '{sum+=$1; count++} END {print sum/count}'
```

#### 2. Update Rate Limit Configuration

Set the new limits where the app installs the middleware, and redeploy:

```python
from fraiseql.security import RateLimit, RateLimitMiddleware, RateLimitRule

app.add_middleware(
    RateLimitMiddleware,
    rules=[
        # Increase if legitimate traffic is being blocked
        RateLimitRule(path_pattern="/graphql", rate_limit=RateLimit(requests=150, window=60)),
        RateLimitRule(path_pattern="/auth/*", rate_limit=RateLimit(requests=5, window=300)),
    ],
    default_limit=RateLimit(requests=150, window=60),
)
```

#### 3. Tiered Rate Limits

`RateLimitMiddleware` applies the same limits to every client; it has no per-tier
limits. Enforce plan quotas at your API gateway, or run a separate deployment with
higher limits for the clients that need them.

---

## 📊 Monitoring & Alerts

### Prometheus Alert Rules

```yaml
# alerts/rate_limiting.yml
groups:
  - name: rate_limiting
    interval: 30s
    rules:
      - alert: HighRateLimitViolations
        expr: |
          rate(fraiseql_rate_limit_exceeded_total[5m]) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High rate of rate limit violations"
          description: "{{ $value }} violations/sec in last 5 minutes"

      - alert: RateLimitAbuseDetected
        expr: |
          sum by (user_id) (
            rate(fraiseql_rate_limit_exceeded_total[5m])
          ) > 10
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Potential abuse detected for user {{ $labels.user_id }}"
          description: "User triggering {{ $value }} violations/sec"

      - alert: RateLimitingImpactingUsers
        expr: |
          (rate(fraiseql_rate_limit_exceeded_total[5m])
          / rate(fraiseql_http_requests_total[5m])) * 100 > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Rate limiting affecting {{ $value }}% of requests"
          description: "Consider increasing limits or investigating abuse"
```

### Grafana Dashboard Panels

**1. Rate Limit Violations Timeline**:

```promql
rate(fraiseql_rate_limit_exceeded_total[5m])
```

**2. Top Violators (Users)**:

```promql
topk(10,
  sum by (user_id) (fraiseql_rate_limit_exceeded_total)
)
```

**3. Top Violators (IPs)**:

```promql
topk(10,
  sum by (ip_address) (fraiseql_rate_limit_exceeded_total)
)
```

**4. Percentage of Blocked Requests**:

```promql
(rate(fraiseql_rate_limit_exceeded_total[5m])
/ rate(fraiseql_http_requests_total[5m])) * 100
```

---

## 🔍 Verification

After applying fixes, verify rate limiting is working correctly:

### 1. Check Violation Rate

```promql
# Should decrease after adjustments
rate(fraiseql_rate_limit_exceeded_total[5m])
```

### 2. Verify User Can Access

```bash
# Test as affected user
curl -X POST http://localhost:8000/graphql \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ users { id name } }"}'

# Should return 200, not 429
```

### 3. Monitor Logs

```bash
# Check for continued violations (fraiseql logs each one on the fraiseql.security
# logger, with "event_type": "rate_limit.exceeded")
grep 'rate_limit.exceeded' /var/log/fraiseql/app.log | tail -10

# Should see no recent events for whitelisted/increased limit users
```

---

## 📝 Post-Incident Review

After resolving the incident:

1. **Analyze Root Cause**:
   - Legitimate traffic spike?
   - Misconfigured limits?
   - Actual abuse attempt?
   - Integration misconfiguration?

2. **Update Rate Limits**:
   - Adjust limits based on real traffic patterns
   - Exempt trusted integrations with `exempt_func`

3. **Improve Detection**:
   - Add monitoring for specific endpoints
   - Implement user behavior analytics
   - Set up automated abuse detection

4. **User Communication**:
   - Document rate limits in API docs
   - Document `Retry-After` handling for clients
   - Provide user-facing rate limit dashboard

---

## 💡 Best Practices

### 1. Tell Clients When to Retry

A 429 from `RateLimitMiddleware` carries `Retry-After` (seconds), `X-RateLimit-Limit`
and `X-RateLimit-Window`; on the GraphQL endpoint, by operation type or cost, its
body is a GraphQL error with `"extensions": {"code": "RATE_LIMITED"}`. Clients should
wait `Retry-After` seconds before retrying.

### 2. Share Counters Across Instances

The default store keeps the counters in each instance's memory, so N instances allow
N times the limit. Pass a Redis-backed store to count across instances:
`setup_rate_limiting(app, redis_client=redis_client)` or
`RateLimitMiddleware(..., store=RedisRateLimitStore(redis_client))`.

---

## 📚 Related Resources

- [Security Configuration](../security.md#rate-limiting)
- [User Authentication](./authentication-failures.md)
- [GraphQL Query DoS Protection](./graphql-query-dos.md)

---

## 🆘 Escalation

If issue persists after following this runbook:

1. **Gather Evidence**:
   - Rate limit violation graphs (last 24 hours)
   - Top violators list (users and IPs)
   - Traffic pattern analysis
   - Sample of rate-limited requests

2. **Escalate To**:
   - Security Team (for abuse investigation)
   - Product Team (for limit adjustment decisions)
   - Engineering Team (for implementation changes)

3. **Emergency Contact**:
   - Security On-call: [Contact info]
   - Product Manager: [Contact info]
   - Engineering Manager: [Contact info]

---

**Version**: 1.0
**Last Tested**: 2025-12-29
**Next Review**: 2026-03-29

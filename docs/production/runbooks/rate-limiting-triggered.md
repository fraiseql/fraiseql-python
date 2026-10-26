# Rate Limiting Triggered Runbook

**Last Updated**: 2026-10-25
**Severity**: MEDIUM
**MTTR Target**: 10 minutes

---

## 📋 Overview

This runbook guides you through investigating and responding to rate limiting events in FraiseQL applications. Rate limiting protects your application from abuse, but legitimate users may occasionally trigger limits.

FraiseQL limits requests only when the app turns it on, in one of two ways (see
[Rate Limiting](../../configuration/rate-limiting.md)):

- **`FraiseQLConfig(rate_limit_enabled=True)`**: `create_fraiseql_app` installs
  `RateLimiterMiddleware`, per client IP, per minute and per hour.
- **`setup_rate_limiting(app)`**: installs `RateLimitMiddleware`, per path rule and
  per GraphQL operation type and cost.

Find out which one your app uses first: the limits, the responses and the log
entries differ.

---

## 🚨 Symptoms

### Primary Indicators

- Users receiving 429 Too Many Requests errors
- Increase in `rate_limit.exceeded` security log entries
- Legitimate traffic patterns triggering limits

### Prometheus Metrics to Monitor

FraiseQL has no rate-limit metric. With the Prometheus metrics middleware installed
outside the rate limiter, rejected requests are counted with status `429`:

```promql
# Rejected requests per second, by endpoint
sum by (endpoint) (rate(fraiseql_http_requests_total{status="429"}[5m]))

# Percentage of requests rejected
sum(rate(fraiseql_http_requests_total{status="429"}[5m]))
  / sum(rate(fraiseql_http_requests_total[5m])) * 100
```

The metric has no user or IP label; use the logs for those.

### Log Entries

Each rejection is logged on the `fraiseql.security` logger at `WARNING`, as a JSON
security event. From `RateLimiterMiddleware` (the `FraiseQLConfig` settings):

```json
{
  "event_type": "rate_limit.exceeded",
  "severity": "warning",
  "timestamp": "2026-10-25T12:30:45.123456+00:00",
  "user_id": null,
  "ip_address": null,
  "resource": null,
  "metadata": {"key": "203.0.113.42", "minute_requests": 60, "hour_requests": 412}
}
```

From `RateLimitMiddleware` (`setup_rate_limiting`):

```json
{
  "event_type": "rate_limit.exceeded",
  "severity": "warning",
  "timestamp": "2026-10-25T12:30:45.123456+00:00",
  "user_id": "user_789",
  "ip_address": "203.0.113.42",
  "resource": "/graphql",
  "result": "blocked",
  "reason": "Rate limit exceeded: 60 requests per 60s",
  "metadata": {"limit": 60, "window": "60s", "rule_pattern": "/graphql", "method": "POST"}
}
```

The examples below assume your log handler writes one JSON object per line with this
event in a `security_event` field (the logger passes it as `extra={"security_event": ...}`);
adapt the `jq` paths to your log format.

---

## 🔍 Diagnostic Steps

### Step 1: Identify Affected Clients

```bash
# Rate limit events in the log
jq -c 'select(.security_event.event_type == "rate_limit.exceeded") | .security_event' \
  /var/log/fraiseql/app.log | tail -100

# Count rejections per client: RateLimiterMiddleware (FraiseQLConfig settings)
jq -r 'select(.security_event.event_type == "rate_limit.exceeded")
  | .security_event.metadata.key // empty' \
  /var/log/fraiseql/app.log | sort | uniq -c | sort -rn | head -20

# Count rejections per IP or user: RateLimitMiddleware (setup_rate_limiting)
jq -r 'select(.security_event.event_type == "rate_limit.exceeded")
  | "\(.security_event.user_id // "-") \(.security_event.ip_address)"' \
  /var/log/fraiseql/app.log | sort | uniq -c | sort -rn | head -20
```

If every rejection names the same address and that address is your proxy or load
balancer, all clients share one limit: see [Behind a proxy](#behind-a-proxy).

### Step 2: Analyze Traffic Patterns

```bash
# Rejections per minute
jq -r 'select(.security_event.event_type == "rate_limit.exceeded")
  | .security_event.timestamp[0:16]' \
  /var/log/fraiseql/app.log | uniq -c
```

A client that hits the limit now and then and drops back is usually legitimate; one
that stays over the limit minute after minute is a script or abuse.

### Step 3: Review Current Rate Limits

**With `FraiseQLConfig`**: the limits are `rate_limit_requests_per_minute` (default
60), `rate_limit_requests_per_hour` (default 1000) and `rate_limit_burst_size`
(default 10), per client IP, in code or in `FRAISEQL_RATE_LIMIT_*` environment
variables. Counts are kept in each process's memory, so each worker counts on its own.

**With `setup_rate_limiting`**: the limits are the rules the app passes. Without
`custom_rules`:

| Path | Limit |
|------|-------|
| `/graphql` | 60 requests a minute |
| `/auth/*` | 5 requests every 5 minutes |
| `/api/*` | 100 requests a minute |
| Any path (`default_limit`) | 100 requests a minute |
| `/graphql`, by operation type | 100 queries, 20 mutations, 10 subscriptions a minute |
| `/graphql`, by estimated cost | 200 cheap, 100 medium, 20 expensive requests a minute |

A client is `request.state.user_id` when a middleware of yours sets it, otherwise the
IP: the peer address, or, when the peer is listed in `trusted_proxies`, the right-most
`X-Forwarded-For` address that is not a trusted proxy.
Windows are fixed (the count resets when a window ends), and the counters live in
each instance's memory unless the app passes `redis_client`.

Both never limit `/health`, `/ready` and `/metrics`.

---

## 🔧 Resolution Steps

### For Legitimate Users (5 minutes)

#### 1. Raise the Limit

There is no per-user override at runtime: raise the limit and redeploy.

With `FraiseQLConfig`:

```bash
FRAISEQL_RATE_LIMIT_REQUESTS_PER_MINUTE=200
FRAISEQL_RATE_LIMIT_REQUESTS_PER_HOUR=5000
```

With `setup_rate_limiting`:

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

`custom_rules` replaces the default rules, so list every path you want limited. The
per-operation-type and per-cost GraphQL limits are fixed and stay in place.

#### 2. Exempt a Trusted Client (If Safe)

With `FraiseQLConfig`, list its IP in `rate_limit_whitelist`:

```bash
FRAISEQL_RATE_LIMIT_WHITELIST='["203.0.113.42"]'
```

With `setup_rate_limiting`, a rule's `exempt_func` lets a request through every limit
when it returns `True`:

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

### Behind a proxy

With `FraiseQLConfig`, the client key is `request.client.host`. Behind a proxy that
is the proxy's address unless the server takes the forwarded one; with uvicorn, run
it with `--proxy-headers --forwarded-allow-ips="<proxy address>"`.

With `setup_rate_limiting`, the key is the peer address too: either run uvicorn as
above, or pass the proxy addresses or networks as
`setup_rate_limiting(app, trusted_proxies=["10.0.0.0/8"])`, and the forwarded address
is used. Without either, every client shares the proxy's limit (one IP in the
rejection logs, the proxy's).

### For Abusive Traffic (10 minutes)

#### 1. Block the Client

With `FraiseQLConfig`, list the IP in `rate_limit_blacklist`: its requests get `403`.

```bash
FRAISEQL_RATE_LIMIT_BLACKLIST='["198.51.100.23"]'
```

`setup_rate_limiting` has no block list. Block an authenticated user with an
operation authorizer that denies them (see
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
# Accepted requests per second, by endpoint
sum by (endpoint) (rate(fraiseql_http_requests_total{status!="429"}[1h]))
```

Per-client rates aren't in the metrics; use your proxy's access logs.

#### 2. Update Rate Limit Configuration

Set the new limits (`FRAISEQL_RATE_LIMIT_*`, or the rules passed to
`setup_rate_limiting` / `RateLimitMiddleware`) and redeploy:

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

Neither middleware has per-tier limits: they apply the same limits to every client.
Enforce plan quotas at your API gateway, or run a separate deployment with higher
limits for the clients that need them.

---

## 📊 Monitoring & Alerts

### Prometheus Alert Rules

```yaml
# alerts/rate_limiting.yml
groups:
  - name: rate_limiting
    interval: 30s
    rules:
      - alert: HighRateLimitRejections
        expr: |
          sum(rate(fraiseql_http_requests_total{status="429"}[5m])) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High rate of rate-limited requests"
          description: "{{ $value }} rejections/sec in the last 5 minutes"

      - alert: RateLimitingImpactingUsers
        expr: |
          sum(rate(fraiseql_http_requests_total{status="429"}[5m]))
          / sum(rate(fraiseql_http_requests_total[5m])) * 100 > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Rate limiting affecting {{ $value }}% of requests"
          description: "Consider increasing limits or investigating abuse"
```

### Grafana Dashboard Panels

**1. Rejections Timeline**:

```promql
sum by (endpoint) (rate(fraiseql_http_requests_total{status="429"}[5m]))
```

**2. Percentage of Rejected Requests**:

```promql
sum(rate(fraiseql_http_requests_total{status="429"}[5m]))
  / sum(rate(fraiseql_http_requests_total[5m])) * 100
```

For top clients, chart the `rate_limit.exceeded` log entries in your log stack
(Loki, ELK) by `metadata.key` or `ip_address`.

---

## 🔍 Verification

After applying fixes, verify rate limiting is working correctly:

### 1. Check Rejection Rate

```promql
# Should decrease after adjustments
sum(rate(fraiseql_http_requests_total{status="429"}[5m]))
```

### 2. Verify User Can Access

```bash
# Test as affected user
curl -i -X POST http://localhost:8000/graphql \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ __typename }"}'

# Should return 200, not 429. With the FraiseQLConfig settings, the
# X-RateLimit-Remaining header shows the requests left this minute.
```

### 3. Monitor Logs

```bash
# Check for continued rejections
grep 'rate_limit.exceeded' /var/log/fraiseql/app.log | tail -10

# Should see no recent events for whitelisted/increased limit users
```

---

## 📝 Post-Incident Review

After resolving the incident:

1. **Analyze Root Cause**:
   - Legitimate traffic spike?
   - Misconfigured limits, or all clients sharing the proxy's address?
   - Actual abuse attempt?
   - Integration misconfiguration?

2. **Update Rate Limits**:
   - Adjust limits based on real traffic patterns
   - Exempt trusted integrations (`rate_limit_whitelist` or `exempt_func`)

3. **Improve Detection**:
   - Alert on `status="429"` in `fraiseql_http_requests_total`
   - Chart `rate_limit.exceeded` log entries per client

4. **User Communication**:
   - Document rate limits in API docs
   - Document `Retry-After` handling for clients

---

## 💡 Best Practices

### 1. Tell Clients When to Retry

Both middlewares send `Retry-After` (seconds) on a 429. `RateLimiterMiddleware` also
sends `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset` on every
counted response; `RateLimitMiddleware` sends `X-RateLimit-Limit` and
`X-RateLimit-Window` on a 429, and on the GraphQL endpoint, by operation type or cost,
its body is a GraphQL error with `"extensions": {"code": "RATE_LIMITED"}`. Clients
should wait `Retry-After` seconds before retrying.

### 2. Share Counters Across Instances

Both keep counts in each instance's memory by default, so N instances allow N times
the limit. `setup_rate_limiting(app, redis_client=redis_client)` (or
`RateLimitMiddleware(..., store=RedisRateLimitStore(redis_client))`) counts across
instances; the `FraiseQLConfig` settings have no shared store.

---

## 📚 Related Resources

- [Rate Limiting](../../configuration/rate-limiting.md)
- [Security Configuration](../security.md#rate-limiting)
- [User Authentication](./authentication-failures.md)
- [GraphQL Query DoS Protection](./graphql-query-dos.md)

---

## 🆘 Escalation

If issue persists after following this runbook:

1. **Gather Evidence**:
   - Rejection graphs (last 24 hours)
   - Top rejected clients (from the logs)
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

**Version**: 1.1
**Last Tested**: 2026-10-25
**Next Review**: 2027-01-25

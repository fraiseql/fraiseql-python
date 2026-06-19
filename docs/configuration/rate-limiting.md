<!-- Skip to main content -->
---

title: Rate Limiting
description: FraiseQL implements request rate limiting to prevent denial-of-service (DoS) attacks and resource exhaustion.
keywords: []
tags: ["documentation", "reference"]
---

# Rate Limiting

FraiseQL implements request rate limiting to prevent denial-of-service (DoS) attacks and resource exhaustion.

## Prerequisites

**Required Knowledge:**

- HTTP request fundamentals (status codes, headers)
- Rate limiting strategies (fixed window, sliding window, token bucket)
- Python and FastAPI basics
- Authentication concepts (IP-based vs user-based rate limiting)
- DoS attack patterns and mitigation strategies

**Required Software:**

- FraiseQL v1 (PostgreSQL)
- Python 3.13+
- curl or Postman (for testing rate limit headers)

**Required Infrastructure:**

- A FraiseQL FastAPI application (built with `create_fraiseql_app`)
- PostgreSQL (FraiseQL's database)
- Redis (optional, for shared rate limit state across multiple app instances)

**Optional but Recommended:**

- Monitoring tools (Prometheus, Grafana) to track rate limit violations
- API gateway (Kong, Tyk) for additional rate limiting at proxy level
- Redis for distributed rate limiting in multi-instance deployments
- Logging aggregation (ELK, Splunk) for rate limit event analysis

**Time Estimate:** 15-30 minutes for basic configuration, 1-2 hours for production tuning

## Overview

Rate limiting in FraiseQL is implemented as FastAPI middleware
(`fraiseql.security.RateLimitMiddleware`). It supports:

- **Per-IP rate limiting**: limits requests from individual client IPs
- **Per-user rate limiting**: limits requests from authenticated users (keyed on
  `request.state.user_id` when set by the auth layer, falling back to IP)
- **Multiple strategies**: fixed window, sliding window, and token bucket
- **GraphQL-aware limits**: separate limits per operation type (query / mutation /
  subscription) and per estimated query complexity
- **Response headers**: clients can check their quota via HTTP headers
- **Pluggable stores**: in-memory by default, or Redis for shared state

## Configuration

The simplest way to enable rate limiting is through `FraiseQLConfig`. Settings can be
provided in code or via `FRAISEQL_`-prefixed environment variables, then passed to
`create_fraiseql_app(config=...)`.

```python
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    # Rate limiting (defaults shown)
    rate_limit_enabled=True,
    rate_limit_requests_per_minute=60,
    rate_limit_requests_per_hour=1000,
    rate_limit_burst_size=10,
    rate_limit_window_type="sliding",   # "sliding" or "fixed"
    rate_limit_whitelist=[],            # IPs/keys never rate limited
    rate_limit_blacklist=[],            # IPs/keys always rejected
)

app = create_fraiseql_app(config=config, types=[...], queries=[...])
```

The same settings as environment variables:

```bash
FRAISEQL_RATE_LIMIT_ENABLED=true
FRAISEQL_RATE_LIMIT_REQUESTS_PER_MINUTE=60
FRAISEQL_RATE_LIMIT_REQUESTS_PER_HOUR=1000
FRAISEQL_RATE_LIMIT_BURST_SIZE=10
FRAISEQL_RATE_LIMIT_WINDOW_TYPE=sliding
```

### Configuration Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `rate_limit_enabled` | `bool` | `True` | Enable/disable rate limiting |
| `rate_limit_requests_per_minute` | `int` | `60` | Allowed requests per minute |
| `rate_limit_requests_per_hour` | `int` | `1000` | Allowed requests per hour |
| `rate_limit_burst_size` | `int` | `10` | Burst capacity (token-bucket strategy) |
| `rate_limit_window_type` | `str` | `"sliding"` | Window strategy: `"sliding"` or `"fixed"` |
| `rate_limit_whitelist` | `list[str]` | `[]` | IPs/keys never rate limited |
| `rate_limit_blacklist` | `list[str]` | `[]` | IPs/keys always rejected |

## Programmatic Setup

For finer control (custom per-path rules, a Redis-backed store, multi-instance
deployments) wire the middleware yourself with `setup_rate_limiting`. It is exported from
`fraiseql.security`, takes the FastAPI app returned by `create_fraiseql_app`, and installs
`RateLimitMiddleware`.

```python
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.security import (
    RateLimit,
    RateLimitRule,
    RateLimitStrategy,
    setup_rate_limiting,
)

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[...],
    queries=[...],
)

custom_rules = [
    # Throttle the GraphQL endpoint
    RateLimitRule(
        path_pattern="/graphql",
        rate_limit=RateLimit(requests=60, window=60),
        message="GraphQL rate limit exceeded",
    ),
    # Tighter limit on auth endpoints (5 requests / 5 minutes)
    RateLimitRule(
        path_pattern="/auth/*",
        rate_limit=RateLimit(requests=5, window=300),
        message="Authentication rate limit exceeded",
    ),
]

setup_rate_limiting(
    app,
    custom_rules=custom_rules,
    default_limit=RateLimit(requests=100, window=60),
)
```

`RateLimit` accepts a `strategy` (`RateLimitStrategy.FIXED_WINDOW`,
`RateLimitStrategy.SLIDING_WINDOW`, or `RateLimitStrategy.TOKEN_BUCKET`) and an optional
`burst` value for the token-bucket strategy:

```python
RateLimit(
    requests=100,
    window=60,
    burst=20,
    strategy=RateLimitStrategy.TOKEN_BUCKET,
)
```

If you do not pass `custom_rules`, FraiseQL installs a sensible set via
`create_default_rate_limit_rules()` (GraphQL, `/auth/*`, and `/api/*` patterns).

### Multi-Instance Deployments (Redis)

The in-memory store keeps counters per process, so each app instance enforces limits
independently. To share state across instances, pass a Redis client — `setup_rate_limiting`
then uses `RedisRateLimitStore` automatically:

```python
import redis.asyncio as redis

from fraiseql.security import setup_rate_limiting

redis_client = redis.from_url("redis://localhost:6379/0")

setup_rate_limiting(app, redis_client=redis_client)
```

## Key Extraction Strategy

Rate limits are applied using the following key extraction logic:

### 1. Authenticated Requests

For requests with an authenticated user (the auth layer sets `request.state.user_id`):

- **Key**: `user:<user_id>`
- **Use case**: authenticated users are tracked individually

### 2. Unauthenticated Requests

For requests without authentication:

- **Key**: `ip:<client_ip>`
- **Use case**: protects against anonymous abuse

### 3. IP Address Resolution

When extracting the client IP address, the middleware checks, in order:

1. The first entry of the `X-Forwarded-For` header (if present)
2. The `X-Real-IP` header (if present)
3. The direct socket peer address (`request.client.host`)

> **Security note:** `X-Forwarded-For` and `X-Real-IP` are client-supplied and can be
> spoofed. Only trust them when your application sits behind a proxy you control that
> overwrites these headers. When exposed directly, strip or ignore them at the proxy so the
> socket peer address is used.

## Response Headers

When a request is rejected, the middleware returns HTTP `429` with the following headers:

```text
Retry-After: 60           # Seconds to wait before retrying
X-RateLimit-Limit: 100    # Maximum requests in the window
X-RateLimit-Window: 60    # Window length in seconds
```

The JSON body of a rejected non-GraphQL request looks like:

```json
{
  "error": "Rate Limit Exceeded",
  "message": "Rate limit exceeded",
  "retry_after": 60
}
```

GraphQL operations that exceed a limit return a GraphQL error with
`extensions.code = "RATE_LIMITED"`.

Example client handling:

```python
import time

import requests


def graphql_request(url, query):
    while True:
        response = requests.post(url, json={"query": query})

        if response.status_code == 429:  # Too Many Requests
            wait_time = int(response.headers.get("Retry-After", "60"))
            print(f"Rate limited, retrying in {wait_time}s")
            time.sleep(wait_time)
            continue

        return response.json()
```

## GraphQL-Aware Limits

For `POST /graphql`, the middleware applies additional limits via `GraphQLRateLimiter`:

- **Per operation type**: separate buckets for `query`, `mutation`, and `subscription`.
- **Per estimated complexity**: queries are bucketed into `low` / `medium` / `high` tiers
  (based on nesting depth and field count), each with its own limit.

A request must pass both the operation-type limit and the complexity limit. These limits
are keyed on the authenticated user when available, otherwise on the client IP.

## Strategies

`RateLimitStrategy` controls how requests are counted:

1. **Fixed window** (`FIXED_WINDOW`): a counter resets at the start of each window.
2. **Sliding window** (`SLIDING_WINDOW`): smooths counting across the window boundary.
3. **Token bucket** (`TOKEN_BUCKET`): each key gets a bucket of up to `burst` tokens that
   refills over the window; each request consumes one token. This allows short bursts while
   bounding the long-run rate.

Set the application-wide strategy with `rate_limit_window_type`, or per rule via the
`strategy` argument to `RateLimit`.

## Disabling Rate Limiting

To disable rate limiting (not recommended for production), set the flag in config:

```python
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    rate_limit_enabled=False,
)
```

Or via environment variable:

```bash
FRAISEQL_RATE_LIMIT_ENABLED=false
```

## Monitoring

Rate limit violations are recorded through FraiseQL's security logger (see
`fraiseql.audit.get_security_logger`). Each violation logs the client IP, endpoint, the
limit and window, and — when known — the user ID and operation metadata.

Configure visibility through Python's standard `logging`:

```python
import logging

logging.getLogger("fraiseql.security").setLevel(logging.DEBUG)
```

Pipe these logs into your aggregation stack (ELK, Splunk, etc.) and alert on spikes in
`429` responses to catch abuse or misconfigured clients.

## Security Considerations

1. **DoS Protection**: Rate limiting helps prevent DoS attacks but should be combined with
   other protections (firewall rules, WAF).

2. **Proxy Spoofing**: `X-Forwarded-For` / `X-Real-IP` are client-controlled. Only trust
   them behind a proxy you control that overwrites them; otherwise strip them at the proxy.

3. **Distributed Attacks**: the in-memory store is per app instance. Use a Redis-backed
   store (`RedisRateLimitStore`) for shared limits across multiple instances.

4. **User ID Extraction**: ensure authentication is correct and `request.state.user_id`
   cannot be forged before relying on per-user limits.

5. **Clock Skew**: counting uses system time. Significant clock skew between instances can
   affect accuracy when sharing state.

## Testing Rate Limiting

Test the implementation against the default per-minute limit:

```bash
# Send more requests than the per-minute limit allows
for i in $(seq 1 110); do
    curl -s http://localhost:8000/graphql \
         -H "Content-Type: application/json" \
         -d '{"query":"{ users { id } }"}'
    echo "Request $i"
done
```

Once the configured limit is exceeded, further requests return HTTP `429` (Too Many
Requests).

## References

- [RFC 6585 - HTTP 429 Too Many Requests](https://tools.ietf.org/html/rfc6585)
- [Token Bucket Algorithm](https://en.wikipedia.org/wiki/Token_bucket)
- [OWASP API Security - Rate Limiting](https://owasp.org/www-project-api-security/)

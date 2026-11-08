<!-- Skip to main content -->
---

title: Rate Limiting
description: How FraiseQL limits the number of requests a client can make, and how to turn it on.
keywords: []
tags: ["documentation", "reference"]
---

# Rate Limiting

FraiseQL can reject a client that sends too many requests, with HTTP `429 Too Many
Requests`. Rate limiting is **off by default**. There are two ways to turn it on:

| | `FraiseQLConfig` settings | `setup_rate_limiting()` |
|---|---|---|
| Middleware | `fraiseql.middleware.RateLimiterMiddleware` | `fraiseql.security.RateLimitMiddleware` |
| Turned on by | `rate_limit_enabled=True` | calling `setup_rate_limiting(app)` |
| Client key | the client IP (`request.client.host`) | `request.state.user_id`, else the client IP (`request.client.host`, or the forwarded address from a proxy listed in `trusted_proxies`) |
| Limits | per minute and per hour, for every path | per path pattern, plus per GraphQL operation type and estimated cost |
| Counting | sliding window | fixed window (the count resets when the window ends) |
| Shared across instances | no (memory of each process) | with Redis (`redis_client=`) |
| IP allow / deny lists | yes | no (use a rule's `exempt_func`) |

Use one of them, not both.

## Prerequisites

- A FraiseQL FastAPI application built with `create_fraiseql_app`
- Redis, only if you want `setup_rate_limiting` to share counts across instances

## With `FraiseQLConfig`

Set `rate_limit_enabled=True`, in code or with `FRAISEQL_`-prefixed environment
variables, and pass the config to `create_fraiseql_app`. It then installs
`RateLimiterMiddleware`.

```python
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    rate_limit_enabled=True,
    rate_limit_requests_per_minute=60,
    rate_limit_requests_per_hour=1000,
    rate_limit_burst_size=10,
    rate_limit_whitelist=["10.0.0.5"],   # client IPs never limited
    rate_limit_blacklist=["203.0.113.9"],  # client IPs always rejected (403)
)

app = create_fraiseql_app(config=config, types=[...], queries=[...])
```

The same settings as environment variables (lists are JSON):

```bash
FRAISEQL_RATE_LIMIT_ENABLED=true
FRAISEQL_RATE_LIMIT_REQUESTS_PER_MINUTE=60
FRAISEQL_RATE_LIMIT_REQUESTS_PER_HOUR=1000
FRAISEQL_RATE_LIMIT_BURST_SIZE=10
FRAISEQL_RATE_LIMIT_WHITELIST='["10.0.0.5"]'
```

### Settings

| Field | Type | Default | What it does |
|-------|------|---------|--------------|
| `rate_limit_enabled` | `bool` | `False` | Install `RateLimiterMiddleware` |
| `rate_limit_requests_per_minute` | `int` | `60` | Requests a client may make in any 60 seconds |
| `rate_limit_requests_per_hour` | `int` | `1000` | Requests a client may make in any hour |
| `rate_limit_burst_size` | `int` | `10` | Requests a minute always allowed, even above `rate_limit_requests_per_minute` (the hour limit still applies) |
| `rate_limit_window_type` | `str` | `"sliding"` | Only `"sliding"` is implemented; another value logs a warning and counts in a sliding window |
| `rate_limit_whitelist` | `list[str]` | `[]` | Client IPs that are never limited |
| `rate_limit_blacklist` | `list[str]` | `[]` | Client IPs that always get `403 Forbidden` |

In effect, a client may make `max(rate_limit_requests_per_minute,
rate_limit_burst_size)` requests in any 60 seconds, and `rate_limit_requests_per_hour`
in any hour.

### What a client sees

Every request counted carries:

```text
X-RateLimit-Limit: 60          # rate_limit_requests_per_minute
X-RateLimit-Remaining: 59      # requests left in the current minute
X-RateLimit-Reset: 1793000000  # Unix time when the oldest counted request leaves the window
```

A request over the limit gets `429` with `Retry-After` (seconds, at least 1), the same
`X-RateLimit-*` headers (`X-RateLimit-Remaining: 0`) and this body:

```json
{"detail": "Rate limit exceeded. Retry after 42 seconds."}
```

A blacklisted IP gets `403` with `{"detail": "Forbidden"}`.

`/health`, `/ready`, `/metrics` and `/` are never counted. With `cors_enabled`, the
CORS middleware wraps the limiter, so a `429` carries the CORS headers and the browser
lets the client read it.

### Behind a proxy

The key is `request.client.host`. Behind a reverse proxy or load balancer that is the
proxy's address, so every client would share one limit, unless the server replaces it
with the forwarded address. With uvicorn:

```bash
uvicorn app:app --proxy-headers --forwarded-allow-ips="10.0.0.1"
```

`--forwarded-allow-ips` lists the proxies whose `X-Forwarded-For` header uvicorn
trusts; don't use `*` when clients can reach the app directly.

### Several instances

Counts are kept in the memory of each process. With N workers or instances, a client
can make up to N times the limit. For one limit across instances, use
`setup_rate_limiting` with Redis (below), or limit at the proxy or API gateway.

## With `setup_rate_limiting`

`setup_rate_limiting` (exported from `fraiseql.security`) installs
`RateLimitMiddleware` on the app returned by `create_fraiseql_app`. It limits per path
pattern, and adds limits on `POST /graphql` by operation type and estimated cost.

```python
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.security import RateLimit, RateLimitRule, setup_rate_limiting

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[...],
    queries=[...],
)

setup_rate_limiting(
    app,
    custom_rules=[
        RateLimitRule(
            path_pattern="/graphql",
            rate_limit=RateLimit(requests=60, window=60),
            message="GraphQL rate limit exceeded",
        ),
        # 5 requests every 5 minutes on the auth endpoints
        RateLimitRule(
            path_pattern="/auth/*",
            rate_limit=RateLimit(requests=5, window=300),
            message="Authentication rate limit exceeded",
        ),
    ],
    default_limit=RateLimit(requests=100, window=60),
)
```

`custom_rules` replaces the default rules. Without it, `setup_rate_limiting` uses
`create_default_rate_limit_rules()`:

| Path | Limit |
|------|-------|
| `/graphql` | 60 requests a minute |
| `/auth/*` | 5 requests every 5 minutes |
| `/api/*` | 100 requests a minute |
| any path (`default_limit`) | 100 requests a minute |

A request counts against every rule whose pattern matches its path and against
`default_limit`; it is rejected when one of them is exceeded. Patterns are exact paths,
or `fnmatch` patterns when they contain `*`.

`RateLimit` also takes `burst` and `strategy` (`RateLimitStrategy.FIXED_WINDOW`,
`SLIDING_WINDOW`, `TOKEN_BUCKET`), but they are not implemented: every limit is a
fixed window of `window` seconds, and setting `burst` or another strategy logs a
warning. For a sliding window, use the `FraiseQLConfig` settings above.

A rule's `exempt_func(request) -> bool` lets a request through every limit when it
returns `True`:

```python
TRUSTED_IPS = {"203.0.113.42"}


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

`/health`, `/ready` and `/metrics` are never limited.

### GraphQL limits

On `POST /graphql`, `RateLimitMiddleware` also counts each request, per client, by:

- **operation type**, read from how the query text starts: 100 queries, 20 mutations,
  10 subscriptions a minute;
- **estimated cost** (brace nesting depth × 10, plus the number of newlines and
  commas): 200 requests a minute under 50, 100 from 50 to 199, 20 from 200.

Change them with `graphql_operation_limits` (keys `query`, `mutation`,
`subscription`) and `graphql_complexity_limits` (keys `low`, `medium`, `high`); the
keys you pass replace those defaults, the others stay:

```python
setup_rate_limiting(
    app,
    graphql_operation_limits={"mutation": RateLimit(requests=5, window=60)},
    graphql_complexity_limits={"high": RateLimit(requests=5, window=60)},
)
```

`RateLimitMiddleware` takes the same two arguments. To turn a limit off in effect,
give it a large `requests`. A request over one of them gets `429` with a GraphQL
error body:

```json
{
  "errors": [
    {
      "message": "Rate limit exceeded for mutation operations",
      "extensions": {"code": "RATE_LIMITED", "limit": 20, "window": 60}
    }
  ]
}
```

### Rejected requests

A request over a path rule or `default_limit` gets `429` with this body (also on
`/graphql`):

```json
{"error": "Rate Limit Exceeded", "message": "GraphQL rate limit exceeded", "retry_after": 60}
```

Every `429` from `RateLimitMiddleware` carries:

```text
Retry-After: 60         # the rule's window, in seconds
X-RateLimit-Limit: 60   # the rule's request count
X-RateLimit-Window: 60  # the rule's window, in seconds
```

Successful responses carry no rate-limit headers.

### Client key

The key is `user:<request.state.user_id>` when a middleware of yours sets
`request.state.user_id`, otherwise `ip:<address>`, where the address is the socket
peer (`request.client.host`). `X-Forwarded-For` and `X-Real-IP` are ignored unless
the peer is a proxy you list in `trusted_proxies`: a client that reaches the app
directly could otherwise send a new value on every request and never be limited.

Behind a reverse proxy or load balancer, the peer is the proxy, so every client
would share one limit. Do one of these:

- **Let uvicorn rewrite the peer.** `uvicorn app:app --proxy-headers
  --forwarded-allow-ips="10.0.0.1"` replaces `request.client` with the address the
  listed proxies forward (uvicorn does this for `127.0.0.1` by default). Nothing to
  set in FraiseQL. This also fixes the key of the `FraiseQLConfig` limiter, its
  allow and deny lists, and every other use of `request.client.host`.
- **List the proxies in `trusted_proxies`** (addresses or CIDR networks):

  ```python
  setup_rate_limiting(app, trusted_proxies=["10.0.0.0/8", "192.168.1.5"])
  ```

  When the peer is one of them, the client IP is the right-most `X-Forwarded-For`
  address that is not a trusted proxy (each proxy appends the address it received
  the request from, so the entries left of that one may be forged). With no
  `X-Forwarded-For`, `X-Real-IP` is used, else the peer. `"*"` is refused.
  `setup_security(..., trusted_proxies=...)` passes the list on.

Don't trust a proxy address that clients can also connect from directly.

### Several instances (Redis)

The default store keeps counts in each process's memory. Pass an async Redis client
to share them; `setup_rate_limiting` then uses `RedisRateLimitStore`:

```python
import redis.asyncio as redis

from fraiseql.security import setup_rate_limiting

redis_client = redis.from_url("redis://localhost:6379/0")

setup_rate_limiting(app, redis_client=redis_client)
```

## Client handling

Wait `Retry-After` seconds before retrying:

```python
import time

import requests


def graphql_request(url, query):
    while True:
        response = requests.post(url, json={"query": query})

        if response.status_code == 429:  # Too Many Requests
            wait_time = int(response.headers.get("Retry-After", "60"))
            time.sleep(wait_time)
            continue

        return response.json()
```

## Monitoring

Both middlewares log every rejection on the `fraiseql.security` logger, at `WARNING`,
as a JSON security event with `"event_type": "rate_limit.exceeded"`:

- `RateLimiterMiddleware` (the `FraiseQLConfig` settings): `metadata` holds the client
  `key` and its `minute_requests` and `hour_requests`.
- `RateLimitMiddleware` (`setup_rate_limiting`): `ip_address`, `user_id`, `resource`
  (the path, or `/graphql:<type>` / `/graphql:complexity:<tier>`), `reason`, and
  `metadata` with `limit`, `window` and the rule or operation.

```python
import logging

logging.getLogger("fraiseql.security").setLevel(logging.INFO)
```

FraiseQL has no rate-limit metric. With the Prometheus metrics middleware installed
outside the limiter, rejections show as `fraiseql_http_requests_total{status="429"}`.

## Testing

With `rate_limit_requests_per_minute=60` and the default `rate_limit_burst_size`:

```bash
for i in $(seq 1 61); do
    curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/graphql \
         -H "Content-Type: application/json" \
         -d '{"query":"{ __typename }"}'
done
# 60 lines of 200, then 429
```

## References

- [RFC 6585 - HTTP 429 Too Many Requests](https://tools.ietf.org/html/rfc6585)
- [OWASP API Security - Unrestricted Resource Consumption](https://owasp.org/API-Security/editions/2023/en/0xa4-unrestricted-resource-consumption/)

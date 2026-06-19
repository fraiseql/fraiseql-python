---
title: Authentication Monitoring and Observability
description: This guide covers monitoring, logging, and observability for FraiseQL's authentication system.
keywords: ["framework", "monitoring", "observability", "prometheus", "authentication"]
tags: ["documentation", "reference"]
---

# Authentication Monitoring and Observability

This guide covers monitoring, logging, and observability for FraiseQL's
authentication system.

FraiseQL v1 runs inside your FastAPI application (Python). Auth observability is
built from two real, exported subsystems:

- **`fraiseql.audit`** — a structured **security event logger**
  (`SecurityLogger` / `SecurityEvent` / `SecurityEventType`) that records
  authentication and authorization events as JSON.
- **`fraiseql.monitoring`** — **Prometheus metrics** (`setup_metrics`,
  `MetricsConfig`, `FraiseQLMetrics`), **health checks** (`HealthCheck`), and
  **PostgreSQL-native error tracking** (`init_error_tracker`).

Everything below uses those APIs plus standard Prometheus/Grafana/log-based
alerting. There is no separate auth server to operate — you scrape and log the
FastAPI app.

## Overview

What you should observe for authentication:

- **Login success / failure** — track outcomes and the failure reason.
- **Token-validation errors** — expired and invalid JWTs.
- **JWKS / provider errors** — failures fetching keys or reaching the IdP.
- **Rate-limit hits** — repeated failures from a single IP or user.
- **Latency** — token validation and provider round-trips.

## Structured Security Logging

FraiseQL ships a centralized security logger. Authentication code paths already
emit events through it — for example, `Auth0Provider.validate_token` logs
`AUTH_TOKEN_EXPIRED`, `AUTH_TOKEN_INVALID`, and generic auth failures
automatically. You can also emit your own events from custom providers or
resolvers.

### Configuring the Security Logger

```python
from fraiseql.audit import SecurityLogger, set_security_logger

# JSON security events to stdout and a rotating-friendly file path.
logger = SecurityLogger(
    log_to_stdout=True,
    log_to_file=True,
    log_file_path="/var/log/fraiseql/security_events.log",
)
set_security_logger(logger)
```

The file path also reads from the `FRAISEQL_SECURITY_LOG_PATH` environment
variable when `log_file_path` is not given. Anywhere in the app you can fetch the
global instance with `get_security_logger()`.

### Event Types

`SecurityEventType` (from `fraiseql.audit`) covers the auth surface you want to
monitor:

| Event type | Meaning |
|------------|---------|
| `AUTH_SUCCESS` | Successful authentication |
| `AUTH_FAILURE` | Failed login attempt |
| `AUTH_TOKEN_EXPIRED` | JWT was expired |
| `AUTH_TOKEN_INVALID` | JWT failed validation (signature, audience, issuer) |
| `AUTH_LOGOUT` | Session / token logout |
| `AUTHZ_DENIED` | Operation authorization denied |
| `AUTHZ_PERMISSION_DENIED` | Missing permission |
| `AUTHZ_ROLE_DENIED` | Missing role |
| `RATE_LIMIT_EXCEEDED` | Auth/endpoint rate limit hit |

### Logging Auth Events

Convenience methods cover the common cases:

```python
from fraiseql.audit import get_security_logger

security = get_security_logger()

# Successful login
security.log_auth_success(
    user_id="user-123",
    user_email="alice@example.com",
    ip_address="203.0.113.10",
    user_agent=request.headers.get("user-agent"),
)

# Failed login attempt
security.log_auth_failure(
    reason="invalid_credentials",
    ip_address="203.0.113.10",
    attempted_username="alice@example.com",
)

# Rate limit exceeded on an auth endpoint
security.log_rate_limit_exceeded(
    ip_address="203.0.113.10",
    endpoint="/graphql",
    limit=10,
    window="1m",
)
```

For full control, build a `SecurityEvent` directly:

```python
from fraiseql.audit import (
    SecurityEvent,
    SecurityEventSeverity,
    SecurityEventType,
    get_security_logger,
)

get_security_logger().log_event(
    SecurityEvent(
        event_type=SecurityEventType.AUTH_TOKEN_INVALID,
        severity=SecurityEventSeverity.WARNING,
        user_id=None,
        ip_address="203.0.113.10",
        reason="JWKS key not found for kid",
        metadata={"provider": "auth0", "kid": "abc123"},
    ),
)
```

### Log Format (JSON)

Each event is serialized to a single JSON line, ready for ingestion into Loki,
ELK, Datadog, or any log pipeline:

```json
{
  "event_type": "auth.success",
  "severity": "info",
  "timestamp": "2026-01-21T10:30:45+00:00",
  "user_id": "user-123",
  "user_email": "alice@example.com",
  "ip_address": "203.0.113.10",
  "user_agent": "Mozilla/5.0",
  "request_id": null,
  "resource": null,
  "action": null,
  "result": "success",
  "reason": null,
  "metadata": {}
}
```

## Metrics with Prometheus

FraiseQL exposes Prometheus metrics for the FastAPI app via `setup_metrics`,
which installs collection middleware and a `/metrics` endpoint.

### Enabling Metrics

```python
from fastapi import FastAPI

from fraiseql.monitoring import MetricsConfig, setup_metrics

app = FastAPI()

metrics = setup_metrics(
    app,
    MetricsConfig(
        enabled=True,
        namespace="fraiseql",      # metric name prefix
        metrics_path="/metrics",   # Prometheus scrape path
    ),
)
```

`FraiseQLMetrics` records GraphQL operations, database queries, HTTP requests,
cache activity, and errors. Because v1 auth runs as GraphQL operations and HTTP
requests against the FastAPI app, these built-in metrics already capture auth
traffic and latency. For example:

- `fraiseql_http_requests_total{method,endpoint,status}` — request volume and
  status codes for the GraphQL endpoint.
- `fraiseql_http_request_duration_seconds` — request latency histogram (use
  `histogram_quantile` for p95/p99).
- `fraiseql_errors_total{error_type,error_code,operation}` — error counts; auth
  failures surface here when a resolver raises.

### Auth-Specific Counters

For dedicated auth signals (login success/failure rate, token-validation errors,
JWKS failures), expose your own Prometheus counters and histograms alongside the
FraiseQL registry. These are standard `prometheus_client` objects — FraiseQL does
not invent a fixed auth metric set:

```python
from prometheus_client import Counter, Histogram

AUTH_ATTEMPTS = Counter(
    "fraiseql_auth_attempts_total",
    "Total authentication attempts",
    ["result"],  # success | failure
)
TOKEN_VALIDATION_ERRORS = Counter(
    "fraiseql_auth_token_errors_total",
    "Token validation errors",
    ["kind"],  # expired | invalid | jwks_error
)
AUTH_VALIDATION_LATENCY = Histogram(
    "fraiseql_auth_validation_duration_seconds",
    "Token validation latency",
)
```

Increment them from your auth code (or a custom `AuthProvider` subclass), keeping
the security logger as the audit trail and Prometheus as the time series:

```python
import time

from fraiseql.audit import get_security_logger

security = get_security_logger()
start = time.perf_counter()
try:
    payload = await provider.validate_token(token)
    AUTH_ATTEMPTS.labels(result="success").inc()
    security.log_auth_success(user_id=payload["sub"])
except TokenExpiredError:
    AUTH_ATTEMPTS.labels(result="failure").inc()
    TOKEN_VALIDATION_ERRORS.labels(kind="expired").inc()
    raise
except InvalidTokenError:
    AUTH_ATTEMPTS.labels(result="failure").inc()
    TOKEN_VALIDATION_ERRORS.labels(kind="invalid").inc()
    raise
finally:
    AUTH_VALIDATION_LATENCY.observe(time.perf_counter() - start)
```

### Scraping Metrics

Once `setup_metrics` is installed, Prometheus scrapes the app directly:

```bash
curl http://localhost:8000/metrics
```

```text
# HELP fraiseql_http_requests_total Total HTTP requests
# TYPE fraiseql_http_requests_total counter
fraiseql_http_requests_total{method="POST",endpoint="/graphql",status="200"} 95
# HELP fraiseql_auth_attempts_total Total authentication attempts
# TYPE fraiseql_auth_attempts_total counter
fraiseql_auth_attempts_total{result="success"} 95
fraiseql_auth_attempts_total{result="failure"} 5
```

## Performance Expectations

Use these as starting points for alert thresholds; tune to your IdP and network.

| Operation | Typical | Alert threshold |
|-----------|---------|-----------------|
| JWT validation (cached JWKS) | 1-5 ms | > 10 ms |
| JWKS key fetch (cold) | 50-300 ms | > 1000 ms |
| Provider token exchange | 200-500 ms | > 1000 ms |
| User info retrieval | 100-300 ms | > 500 ms |

## Alerting Rules

### Prometheus Alerts

Define alerts on the counters and histograms you expose. Create `alerts.yml`:

```yaml
groups:
  - name: fraiseql_auth
    interval: 30s
    rules:
      # High auth failure rate
      - alert: AuthHighFailureRate
        expr: |
          sum(rate(fraiseql_auth_attempts_total{result="failure"}[5m]))
            / sum(rate(fraiseql_auth_attempts_total[5m])) > 0.1
        for: 5m
        annotations:
          summary: "High authentication failure rate"
          description: "Auth failure rate > 10% for 5 minutes"

      # Spike in token-validation errors (possible attack or IdP outage)
      - alert: TokenValidationErrorSpike
        expr: |
          sum(increase(fraiseql_auth_token_errors_total[5m])) > 100
        annotations:
          summary: "Spike in token validation errors"
          description: "More than 100 token errors in 5 minutes"

      # Slow token validation
      - alert: SlowTokenValidation
        expr: |
          histogram_quantile(
            0.99,
            sum(rate(fraiseql_auth_validation_duration_seconds_bucket[5m])) by (le)
          ) > 0.010
        for: 5m
        annotations:
          summary: "Token validation is slow"
          description: "p99 validation latency > 10ms"
```

### Log-Based Alerting

When you do not expose a dedicated counter, alert on the security event stream.
In Loki, ELK, or Datadog, match the JSON `event_type` field:

```text
# Failure spike (Loki LogQL example)
sum(count_over_time({app="fraiseql"} | json | event_type="auth.failure" [5m])) > 100

# Repeated failures from one IP (credential stuffing)
{app="fraiseql"} | json | event_type="auth.failure" | ip_address="203.0.113.10"
```

## Grafana Dashboard

Build panels from the metrics you expose:

```json
{
  "dashboard": {
    "title": "FraiseQL Authentication",
    "panels": [
      {
        "title": "Auth Attempts (by result)",
        "targets": [
          {"expr": "sum(rate(fraiseql_auth_attempts_total[5m])) by (result)"}
        ]
      },
      {
        "title": "Failure Rate",
        "targets": [
          {
            "expr": "sum(rate(fraiseql_auth_attempts_total{result=\"failure\"}[5m])) / sum(rate(fraiseql_auth_attempts_total[5m]))"
          }
        ]
      },
      {
        "title": "Token Validation Latency (p95)",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, sum(rate(fraiseql_auth_validation_duration_seconds_bucket[5m])) by (le))"
          }
        ]
      },
      {
        "title": "Token Errors (by kind)",
        "targets": [
          {"expr": "sum(rate(fraiseql_auth_token_errors_total[5m])) by (kind)"}
        ]
      }
    ]
  }
}
```

## Error Tracking

For capturing unexpected exceptions in auth code, FraiseQL provides a
PostgreSQL-native error tracker (a Sentry-style sink that writes to your own
database):

```python
from fraiseql.monitoring import get_error_tracker, init_error_tracker

# At startup
init_error_tracker(db_pool, environment="production")

# In an auth code path
tracker = get_error_tracker()
try:
    payload = await provider.validate_token(token)
except Exception as exc:
    if tracker:
        await tracker.capture_exception(exc, context={"ip": request.client.host})
    raise
```

## Health Checks

Use `HealthCheck` to expose readiness, including reachability of your auth
provider's JWKS endpoint:

```python
import httpx

from fraiseql.monitoring import (
    CheckResult,
    HealthCheck,
    HealthStatus,
    check_database,
)

health = HealthCheck()
health.add_check("database", check_database)


async def check_idp() -> CheckResult:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(
                "https://YOUR_DOMAIN/.well-known/jwks.json",
            )
        resp.raise_for_status()
        return CheckResult(
            name="idp",
            status=HealthStatus.HEALTHY,
            message="JWKS endpoint reachable",
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="idp",
            status=HealthStatus.UNHEALTHY,
            message=f"JWKS endpoint unreachable: {exc}",
        )


health.add_check("idp", check_idp)
```

Wire it into a FastAPI route:

```python
from fastapi import FastAPI

app = FastAPI()


@app.get("/health/auth")
async def health_auth() -> dict:
    return await health.run_checks()
```

```bash
curl http://localhost:8000/health/auth
```

```json
{
  "status": "healthy",
  "checks": {
    "database": {"status": "healthy", "message": "Database connection successful"},
    "idp": {"status": "healthy", "message": "JWKS endpoint reachable"}
  }
}
```

## Docker Compose with Monitoring

Run the FastAPI app (for example with `uvicorn app:app`) next to Prometheus,
Grafana, and Loki:

```yaml
services:
  app:
    build: .
    command: uvicorn app:app --host 0.0.0.0 --port 8000
    environment:
      DATABASE_URL: postgresql://user:pass@db/mydb
      FRAISEQL_SECURITY_LOG_PATH: /var/log/fraiseql/security_events.log
    ports:
      - "8000:8000"

  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:latest
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
    ports:
      - "3000:3000"

  loki:
    image: grafana/loki:latest
    ports:
      - "3100:3100"

  promtail:
    image: grafana/promtail:latest
    volumes:
      - /var/log:/var/log
    command: -config.file=/etc/promtail/config.yml
```

Point Prometheus at the app's `/metrics` path in `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: fraiseql
    metrics_path: /metrics
    static_configs:
      - targets: ["app:8000"]
```

## Best Practices

1. **Log in JSON format** — the security logger already emits JSON lines.
2. **Include a request ID** — set `SecurityEvent.request_id` for tracing.
3. **Monitor success/failure rates** continuously.
4. **Alert on anomalies** — sudden spikes in `AUTH_FAILURE` or token errors.
5. **Track latency percentiles** (p50, p95, p99) with histograms.
6. **Audit sensitive events** — login, logout, authorization denials.
7. **Retain logs** for compliance (90+ days).
8. **Never log secrets** — do not put passwords or raw tokens in metadata.
9. **Set up dashboards** for on-call teams.
10. **Review security events regularly** for incidents.

## Troubleshooting with Logs

### Users Cannot Log In

Filter the security event stream by `event_type`:

```text
event_type: "auth.token_invalid"   # signature / audience / issuer mismatch
event_type: "auth.token_expired"   # token already expired
event_type: "auth.failure"         # credential or provider error
```

### Slow Authentication

Check the validation latency histogram and provider round-trips:

```text
histogram_quantile(0.95, sum(rate(fraiseql_auth_validation_duration_seconds_bucket[5m])) by (le))
```

A high p95 with low local CPU usually points at JWKS fetches or IdP latency.

### Authorization Denials

Track denied operations to spot over-restrictive policies or probing:

```text
event_type: "authz.denied"
event_type: "authz.permission_denied"
event_type: "authz.role_denied"
```

## See Also

- [Deployment Guide](./deployment.md)
- [Security Checklist](./security-checklist.md)
- [API Reference](./api-reference.md)

---

**Next Step**: Set up a monitoring dashboard and alerts for your deployment.

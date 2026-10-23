---
title: Production Monitoring
description: PostgreSQL-native error tracking, caching, and observability without external services
tags:
  - monitoring
  - production
  - observability
  - error-tracking
  - PostgreSQL
  - metrics
---

# Production Monitoring

Comprehensive monitoring strategy for FraiseQL applications with **PostgreSQL-native error tracking, caching, and observability**—eliminating the need for external services like Sentry or Redis.

## Overview

FraiseQL implements the **"In PostgreSQL Everything"** philosophy: all monitoring, error tracking, caching, and observability run directly in PostgreSQL, saving $300-3,000/month and simplifying operations.

**PostgreSQL-Native Stack:**

- **Error Tracking**: PostgreSQL-based alternative to Sentry
- **Caching**: UNLOGGED tables alternative to Redis
- **Metrics**: Prometheus or PostgreSQL-native metrics
- **Traces**: OpenTelemetry stored in PostgreSQL
- **Dashboards**: Grafana querying PostgreSQL directly

**Cost Savings:**

```
Traditional Stack:
- Sentry: $300-3,000/month
- Redis Cloud: $50-500/month
- Total: $350-3,500/month

FraiseQL Stack:
- PostgreSQL: Already running
- Total: $0/month additional
```

**Key Components:**

- PostgreSQL-native error tracking (recommended)
- Prometheus metrics
- Structured logging
- Query performance monitoring
- Database pool monitoring
- Alerting strategies

## PostgreSQL Error Tracking

**Recommended alternative to Sentry.** FraiseQL includes PostgreSQL-native error tracking with automatic fingerprinting, grouping, and notifications—saving $300-3,000/month.

### Setup

```python
import fraiseql

from fraiseql.monitoring import init_error_tracker, ErrorNotificationChannel

# Initialize error tracker
tracker = init_error_tracker(
    db_pool,
    environment="production",
    notification_channels=[
        ErrorNotificationChannel.EMAIL,
        ErrorNotificationChannel.SLACK
    ]
)

# Capture exceptions
try:
    await process_payment(order_id)
except Exception as error:
    await tracker.capture_exception(
        error,
        context={
            "user_id": user.id,
            "order_id": order_id,
            "request_id": request.state.request_id,
            "operation": "process_payment"
        }
    )
    raise
```

### Features

**Automatic Error Fingerprinting:**

```python
# Errors are automatically grouped by fingerprint
# Similar to Sentry's issue grouping

# Example: All "payment timeout" errors grouped together
SELECT
    fingerprint,
    COUNT(*) as occurrences,
    MAX(occurred_at) as last_seen,
    MIN(occurred_at) as first_seen
FROM monitoring.errors
WHERE environment = 'production'
  AND resolved_at IS NULL
GROUP BY fingerprint
ORDER BY occurrences DESC;
```

**Full Stack Trace Capture:**

```sql
-- View complete error details
SELECT
    id,
    fingerprint,
    message,
    exception_type,
    stack_trace,
    context,
    occurred_at
FROM monitoring.errors
WHERE fingerprint = 'payment_timeout_error'
ORDER BY occurred_at DESC
LIMIT 10;
```

**OpenTelemetry Correlation:**

```sql
-- Correlate errors with distributed traces
SELECT
    e.message as error,
    e.context->>'user_id' as user_id,
    t.trace_id,
    t.duration_ms,
    t.status_code
FROM monitoring.errors e
LEFT JOIN monitoring.traces t ON e.trace_id = t.trace_id
WHERE e.fingerprint = 'database_connection_error'
ORDER BY e.occurred_at DESC;
```

**Issue Management:**

```python
# Resolve errors
await tracker.resolve_error(fingerprint="payment_timeout_error")

# Ignore specific errors
await tracker.ignore_error(fingerprint="known_external_api_issue")

# Assign errors to team members
await tracker.assign_error(
    fingerprint="critical_bug",
    assignee="dev@example.com"
)
```

**Custom Notifications:**

```python
from fraiseql.monitoring.notifications import EmailNotifier, SlackNotifier, WebhookNotifier

# Configure email notifications
email_notifier = EmailNotifier(
    smtp_host="smtp.gmail.com",
    smtp_port=587,
    from_email="alerts@myapp.com",
    to_emails=["team@myapp.com"]
)

# Configure Slack notifications
slack_notifier = SlackNotifier(
    webhook_url="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
)

# Add to tracker
tracker.add_notification_channel(email_notifier)
tracker.add_notification_channel(slack_notifier)

# Rate limiting: Only notify on first occurrence and every 100th occurrence
tracker.set_notification_rate_limit(
    fingerprint="payment_timeout_error",
    notify_on_occurrence=[1, 100, 200, 300]  # 1st, 100th, 200th, etc.
)
```

### Query Examples

```sql
-- Top 10 most frequent errors (last 24 hours)
SELECT
    fingerprint,
    exception_type,
    message,
    COUNT(*) as count,
    MAX(occurred_at) as last_seen
FROM monitoring.errors
WHERE occurred_at > NOW() - INTERVAL '24 hours'
  AND resolved_at IS NULL
GROUP BY fingerprint, exception_type, message
ORDER BY count DESC
LIMIT 10;

-- Errors by user
SELECT
    context->>'user_id' as user_id,
    COUNT(*) as error_count,
    array_agg(DISTINCT exception_type) as error_types
FROM monitoring.errors
WHERE occurred_at > NOW() - INTERVAL '7 days'
GROUP BY context->>'user_id'
ORDER BY error_count DESC
LIMIT 20;

-- Error rate over time (hourly)
SELECT
    date_trunc('hour', occurred_at) as hour,
    COUNT(*) as error_count
FROM monitoring.errors
WHERE occurred_at > NOW() - INTERVAL '24 hours'
GROUP BY hour
ORDER BY hour;
```

### Performance

- **Write Performance**: Sub-millisecond error capture (PostgreSQL INSERT)
- **Query Performance**: Indexed by fingerprint, timestamp, environment
- **Storage**: JSONB compression for stack traces and context
- **Retention**: Configurable (default: 90 days)

### Comparison to Sentry

| Feature | PostgreSQL Error Tracker | Sentry |
|---------|-------------------------|--------|
| Cost | $0 (included) | $300-3,000/month |
| Error Grouping | ✅ Automatic fingerprinting | ✅ Automatic fingerprinting |
| Stack Traces | ✅ Full capture | ✅ Full capture |
| Notifications | ✅ Email, Slack, Webhook | ✅ Email, Slack, Webhook |
| OpenTelemetry | ✅ Native correlation | ⚠️ Requires integration |
| Data Location | ✅ Self-hosted | ❌ SaaS only |
| Query Flexibility | ✅ Direct SQL access | ⚠️ Limited API |
| Business Context | ✅ Join with app tables | ❌ Separate system |

## PostgreSQL Caching

**Recommended alternative to Redis.** FraiseQL uses PostgreSQL UNLOGGED tables for high-performance caching—saving $50-500/month while matching Redis performance.

### Setup

```python
from fraiseql.caching import PostgresCache

# Initialize cache
cache = PostgresCache(db_pool)

# Basic operations
await cache.set("user:123", user_data, ttl=3600)  # 1 hour TTL
value = await cache.get("user:123")
await cache.delete("user:123")

# Pattern-based deletion
await cache.delete_pattern("user:*")  # Clear all user caches

# Batch operations
await cache.set_many({
    "product:1": product1,
    "product:2": product2,
    "product:3": product3
}, ttl=1800)

values = await cache.get_many(["product:1", "product:2", "product:3"])
```

### Features

**UNLOGGED Tables:**

```sql
-- FraiseQL automatically creates UNLOGGED tables
-- No WAL overhead = Redis-level write performance

CREATE UNLOGGED TABLE cache_entries (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_cache_expires ON cache_entries (expires_at)
WHERE expires_at IS NOT NULL;
```

**Automatic Expiration:**

```python
# TTL-based expiration (automatic cleanup)
await cache.set("session:abc", session_data, ttl=900)  # 15 minutes

# Cleanup runs periodically (configurable)
# DELETE FROM cache_entries WHERE expires_at < NOW();
```

**Shared Across Instances:**

```python
# Unlike in-memory cache, PostgreSQL cache is shared
# All app instances see the same cached data

# Instance 1
await cache.set("config:feature_flags", flags)

# Instance 2 (immediately available)
flags = await cache.get("config:feature_flags")
```

### Performance

**UNLOGGED Table Benefits:**

- No WAL (Write-Ahead Log) = 2-5x faster writes than logged tables
- Same read performance as regular PostgreSQL tables
- Data survives crashes (unlike Redis default mode)
- No replication overhead

**Benchmarks:**
| Operation | PostgreSQL UNLOGGED | Redis | Regular PostgreSQL |
|-----------|-------------------|-------|-------------------|
| SET (write) | 0.3-0.8ms | 0.2-0.5ms | 1-3ms |
| GET (read) | 0.2-0.5ms | 0.1-0.3ms | 0.2-0.5ms |
| DELETE | 0.3-0.6ms | 0.2-0.4ms | 1-2ms |

### Comparison to Redis

| Feature | PostgreSQL Cache | Redis |
|---------|-----------------|-------|
| Cost | $0 (included) | $50-500/month |
| Write Performance | ✅ 0.3-0.8ms | ✅ 0.2-0.5ms |
| Read Performance | ✅ 0.2-0.5ms | ✅ 0.1-0.3ms |
| Persistence | ✅ Survives crashes | ⚠️ Optional (slower) |
| Shared Instances | ✅ Automatic | ✅ Automatic |
| Backup | ✅ Same as DB | ❌ Separate |
| Monitoring | ✅ Same tools | ❌ Separate tools |
| Query Correlation | ✅ Direct joins | ❌ Separate system |

## Migration Guides

### Migrating from Sentry

**Before (Sentry):**

```python
import sentry_sdk

sentry_sdk.init(
    dsn="https://key@sentry.io/project",
    environment="production",
    traces_sample_rate=0.1
)

# Capture exception
sentry_sdk.capture_exception(error)
```

**After (PostgreSQL):**

```python
from fraiseql.monitoring import init_error_tracker

tracker = init_error_tracker(db_pool, environment="production")

# Capture exception (same interface)
await tracker.capture_exception(error, context={
    "user_id": user.id,
    "request_id": request_id
})
```

**Migration Steps:**

1. Install monitoring schema: `psql -f src/fraiseql/monitoring/schema.sql`
2. Initialize error tracker in application startup
3. Replace `sentry_sdk.capture_exception()` calls with `tracker.capture_exception()`
4. Configure notification channels (Email, Slack, Webhook)
5. Remove Sentry SDK and DSN configuration
6. Update deployment to remove Sentry environment variables

### Migrating from Redis

**Before (Redis):**

```python
import redis.asyncio as redis

redis_client = redis.from_url("redis://localhost:6379")

await redis_client.set("key", "value", ex=3600)
value = await redis_client.get("key")
```

**After (PostgreSQL):**

```python
from fraiseql.caching import PostgresCache

cache = PostgresCache(db_pool)

await cache.set("key", "value", ttl=3600)
value = await cache.get("key")
```

**Migration Steps:**

1. Initialize PostgresCache with database pool
2. Replace redis operations with cache operations:
   - `redis.set()` → `cache.set()`
   - `redis.get()` → `cache.get()`
   - `redis.delete()` → `cache.delete()`
   - `redis.keys(pattern)` → `cache.delete_pattern(pattern)`
3. Remove Redis connection configuration
4. Update deployment to remove Redis service
5. Remove Redis from requirements.txt

## Metrics Collection

### Prometheus Integration

```python
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from fastapi import FastAPI, Response

app = FastAPI()

# Metrics
graphql_requests_total = Counter(
    'graphql_requests_total',
    'Total GraphQL requests',
    ['operation', 'status']
)

graphql_request_duration = Histogram(
    'graphql_request_duration_seconds',
    'GraphQL request duration',
    ['operation'],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

graphql_query_complexity = Histogram(
    'graphql_query_complexity',
    'GraphQL query complexity score',
    buckets=[10, 25, 50, 100, 250, 500, 1000]
)

db_pool_connections = Gauge(
    'db_pool_connections',
    'Database pool connections',
    ['state']  # active, idle
)

cache_hits = Counter('cache_hits_total', 'Cache hits')
cache_misses = Counter('cache_misses_total', 'Cache misses')

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type="text/plain"
    )

# Middleware to track metrics
@app.middleware("http")
async def metrics_middleware(request, call_next):
    import time

    start_time = time.time()

    response = await call_next(request)

    duration = time.time() - start_time

    # Track request duration
    if request.url.path == "/graphql":
        operation = request.headers.get("X-Operation-Name", "unknown")
        status = "success" if response.status_code < 400 else "error"

        graphql_requests_total.labels(operation=operation, status=status).inc()
        graphql_request_duration.labels(operation=operation).observe(duration)

    return response
```

### Custom Metrics

```python
from fraiseql.monitoring.metrics import MetricsCollector

class FraiseQLMetrics:
    """Custom metrics for FraiseQL operations."""

    def __init__(self):
        self.turbo_router_hits = Counter(
            'fraiseql_turbo_router_hits_total',
            'TurboRouter cache hits'
        )

        self.apq_cache_hits = Counter(
            'fraiseql_apq_cache_hits_total',
            'APQ cache hits'
        )

        self.mutation_duration = Histogram(
            'fraiseql_mutation_duration_seconds',
            'Mutation execution time',
            ['mutation_name']
        )

    def track_query_execution(self, operation: str, duration: float, complexity: int):
        """Track query execution metrics."""
        graphql_request_duration.labels(operation=operation).observe(duration)
        graphql_query_complexity.observe(complexity)

metrics = FraiseQLMetrics()
```

## Logging

### Structured Logging

```python
import logging
import json
from datetime import datetime

class StructuredFormatter(logging.Formatter):
    """JSON structured logging formatter."""

    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add extra fields
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "query_id"):
            log_data["query_id"] = record.query_id
        if hasattr(record, "duration"):
            log_data["duration_ms"] = record.duration

        # Add exception info
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.StreamHandler()
    ]
)

# Set formatter
for handler in logging.root.handlers:
    handler.setFormatter(StructuredFormatter())

logger = logging.getLogger(__name__)

# Usage
logger.info(
    "GraphQL query executed",
    extra={
        "user_id": "user-123",
        "query_id": "query-456",
        "duration": 125.5,
        "complexity": 45
    }
)
```

### Request Logging Middleware

```python
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import time
import uuid

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Log request
        logger.info(
            "Request started",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "client_ip": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent")
            }
        )

        start_time = time.time()

        try:
            response = await call_next(request)

            duration = (time.time() - start_time) * 1000

            # Log response
            logger.info(
                "Request completed",
                extra={
                    "request_id": request_id,
                    "status_code": response.status_code,
                    "duration_ms": duration
                }
            )

            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id

            return response

        except Exception as e:
            duration = (time.time() - start_time) * 1000

            logger.error(
                "Request failed",
                extra={
                    "request_id": request_id,
                    "duration_ms": duration,
                    "error": str(e)
                },
                exc_info=True
            )
            raise

app.add_middleware(RequestLoggingMiddleware)
```

## External APM Integration

**Note:** PostgreSQL-native error tracking is recommended for most use cases. Use external APM only if you have specific requirements for SaaS-based monitoring.

### Sentry Integration (Legacy/Optional)

**⚠️ Consider [PostgreSQL Error Tracking](#postgresql-error-tracking) instead** (saves $300-3,000/month, better integration with FraiseQL).

If you still need Sentry:

```python
import sentry_sdk

# Initialize Sentry
sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    environment="production",
    traces_sample_rate=0.1,  # 10% of traces
    profiles_sample_rate=0.1,
    release=f"fraiseql@{VERSION}"
)

# In GraphQL context
@app.middleware("http")
async def sentry_middleware(request: Request, call_next):
    # Set user context
    if hasattr(request.state, "user"):
        user = request.state.user
        sentry_sdk.set_user({
            "id": user.user_id,
            "email": user.email,
            "username": user.name
        })

    # Set GraphQL context
    if request.url.path == "/graphql":
        query = await request.body()
        sentry_sdk.set_context("graphql", {
            "query": query.decode()[:1000],  # Limit size
            "operation": request.headers.get("X-Operation-Name")
        })

    response = await call_next(request)
    return response
```

**Migration to PostgreSQL:** See [Migration Guides](#migration-guides) above.

### Datadog Integration

```python
import fraiseql

from ddtrace import tracer, patch_all
from ddtrace.contrib.fastapi import patch as patch_fastapi

# Patch all supported libraries
patch_all()

# FastAPI tracing
patch_fastapi(app)

# Custom span
@fraiseql.query
async def get_user(info, id: ID) -> User:
    with tracer.trace("get_user", service="fraiseql") as span:
        span.set_tag("user.id", id)
        span.set_tag("operation", "query")

        user = await fetch_user(id)

        span.set_tag("user.found", user is not None)

        return user
```

## Query Performance

### Query Timing

```python
from fraiseql.monitoring.metrics import query_duration_histogram

@app.middleware("http")
async def query_timing_middleware(request: Request, call_next):
    if request.url.path != "/graphql":
        return await call_next(request)

    import time
    start_time = time.time()

    # Parse query
    body = await request.json()
    query = body.get("query", "")
    operation_name = body.get("operationName", "unknown")

    response = await call_next(request)

    duration = time.time() - start_time

    # Track timing
    query_duration_histogram.labels(
        operation=operation_name
    ).observe(duration)

    # Log slow queries
    if duration > 1.0:  # Slower than 1 second
        logger.warning(
            "Slow query detected",
            extra={
                "operation": operation_name,
                "duration_ms": duration * 1000,
                "query": query[:500]
            }
        )

    return response
```

### Complexity Tracking

```python
from fraiseql.analysis.complexity import analyze_query_complexity

async def track_query_complexity(query: str, operation_name: str):
    """Track query complexity metrics."""
    complexity = analyze_query_complexity(query)

    graphql_query_complexity.observe(complexity.score)

    if complexity.score > 500:
        logger.warning(
            "High complexity query",
            extra={
                "operation": operation_name,
                "complexity": complexity.score,
                "depth": complexity.depth,
                "fields": complexity.field_count
            }
        )
```

## Database Monitoring

### Connection Pool Metrics

```python
from fraiseql.db import get_db_pool

async def collect_pool_metrics():
    """Collect database pool metrics."""
    pool = get_db_pool()
    stats = pool.get_stats()

    # Update Prometheus gauges
    db_pool_connections.labels(state="active").set(
        stats["pool_size"] - stats["pool_available"]
    )
    db_pool_connections.labels(state="idle").set(
        stats["pool_available"]
    )

    # Log if pool is saturated
    utilization = (stats["pool_size"] / pool.max_size) * 100
    if utilization > 90:
        logger.warning(
            "Database pool highly utilized",
            extra={
                "pool_size": stats["pool_size"],
                "max_size": pool.max_size,
                "utilization_pct": utilization
            }
        )

# Collect metrics periodically
import asyncio

async def metrics_collector():
    while True:
        await collect_pool_metrics()
        await asyncio.sleep(15)  # Every 15 seconds

asyncio.create_task(metrics_collector())
```

### Query Logging

```python
# Log all SQL queries in development
from fraiseql.fastapi.config import FraiseQLConfig

config = FraiseQLConfig(
    database_url="postgresql://...",
    database_echo=True  # Development only
)

# Production: Log slow queries only
# PostgreSQL: log_min_duration_statement = 1000  # Log queries > 1s
```

## Alerting

### Prometheus Alerts

```yaml
# prometheus-alerts.yml
groups:
  - name: fraiseql
    interval: 30s
    rules:
      # High error rate
      - alert: HighErrorRate
        expr: rate(graphql_requests_total{status="error"}[5m]) > 0.05
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "High GraphQL error rate"
          description: "Error rate is {{ $value }} errors/sec"

      # High latency
      - alert: HighLatency
        expr: histogram_quantile(0.99, rate(graphql_request_duration_seconds_bucket[5m])) > 1.0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High GraphQL latency"
          description: "P99 latency is {{ $value }}s"

      # Database pool saturation
      - alert: DatabasePoolSaturated
        expr: db_pool_connections{state="active"} / db_pool_max_connections > 0.9
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Database pool saturated"
          description: "Pool utilization is {{ $value }}%"

      # Low cache hit rate
      - alert: LowCacheHitRate
        expr: rate(cache_hits_total[5m]) / (rate(cache_hits_total[5m]) + rate(cache_misses_total[5m])) < 0.5
        for: 10m
        labels:
          severity: info
        annotations:
          summary: "Low cache hit rate"
          description: "Cache hit rate is {{ $value }}"
```

### PagerDuty Integration

```python
import httpx

async def send_pagerduty_alert(
    summary: str,
    severity: str,
    details: dict
):
    """Send alert to PagerDuty."""
    payload = {
        "routing_key": os.getenv("PAGERDUTY_ROUTING_KEY"),
        "event_action": "trigger",
        "payload": {
            "summary": summary,
            "severity": severity,
            "source": "fraiseql",
            "custom_details": details
        }
    }

    async with httpx.AsyncClient() as client:
        await client.post(
            "https://events.pagerduty.com/v2/enqueue",
            json=payload
        )

# Example usage
if error_rate > 0.1:
    await send_pagerduty_alert(
        summary="High GraphQL error rate detected",
        severity="error",
        details={
            "error_rate": error_rate,
            "time_window": "5m",
            "affected_operations": ["getUser", "getOrders"]
        }
    )
```

## Dashboards

### Grafana Dashboard

```json
{
  "dashboard": {
    "title": "FraiseQL Production Metrics",
    "panels": [
      {
        "title": "Request Rate",
        "targets": [
          {
            "expr": "rate(graphql_requests_total[5m])",
            "legendFormat": "{{operation}}"
          }
        ]
      },
      {
        "title": "Latency (P50, P95, P99)",
        "targets": [
          {
            "expr": "histogram_quantile(0.50, rate(graphql_request_duration_seconds_bucket[5m]))",
            "legendFormat": "P50"
          },
          {
            "expr": "histogram_quantile(0.95, rate(graphql_request_duration_seconds_bucket[5m]))",
            "legendFormat": "P95"
          },
          {
            "expr": "histogram_quantile(0.99, rate(graphql_request_duration_seconds_bucket[5m]))",
            "legendFormat": "P99"
          }
        ]
      },
      {
        "title": "Error Rate",
        "targets": [
          {
            "expr": "rate(graphql_requests_total{status=\"error\"}[5m])",
            "legendFormat": "Errors/sec"
          }
        ]
      },
      {
        "title": "Database Pool",
        "targets": [
          {
            "expr": "db_pool_connections{state=\"active\"}",
            "legendFormat": "Active"
          },
          {
            "expr": "db_pool_connections{state=\"idle\"}",
            "legendFormat": "Idle"
          }
        ]
      }
    ]
  }
}
```

## Next Steps

- [Deployment](deployment.md) - Production deployment patterns
- [Security](security.md) - Security monitoring
- [Performance](../performance/index.md) - Performance optimization

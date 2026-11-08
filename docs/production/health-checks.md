---
title: Health Checks
description: Composable health check patterns for monitoring application dependencies
tags:
  - health-checks
  - production
  - monitoring
  - kubernetes
  - liveness
  - readiness
---

# Health Checks

Composable health check patterns for monitoring application dependencies and system health.

## Overview

FraiseQL provides **built-in health and readiness endpoints** for production deployments, plus a **composable health check utility** for custom monitoring needs.

**Key Features:**

- **Built-in endpoints**: `/health` (liveness) and `/ready` (readiness) included automatically
- **Kubernetes-ready**: Works out-of-the-box with Kubernetes probes
- **Composable custom checks**: Extend with application-specific monitoring
- **Pre-built checks**: Ready-to-use functions for common dependencies
- **Async-first**: Built for modern Python async applications

## Built-in Health Endpoints

FraiseQL automatically provides two health check endpoints for production deployments:

### `/health` - Liveness Probe

**Purpose**: Check if the application process is alive (for Kubernetes liveness probes).

**Response**:

```json
{
  "status": "healthy",
  "service": "fraiseql"
}
```

**Status Codes**:

- `200 OK`: Process is running

**Use Case**: Kubernetes liveness probe - restart pod if this endpoint fails (process crashed).

**Kubernetes Configuration**:

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 30
  timeoutSeconds: 5
  failureThreshold: 3
```

---

### `/ready` - Readiness Probe

**Purpose**: Check if the application is ready to serve traffic (for Kubernetes readiness probes).

**What it checks**:

- Database connection pool is available
- Database is reachable (simple SELECT 1 query)
- GraphQL schema is loaded

**Response (Ready)**:

```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "schema": "ok"
  },
  "timestamp": 1670500000.0
}
```

**Response (Not Ready)**:

```json
{
  "status": "not_ready",
  "checks": {
    "database": "failed: connection timeout",
    "schema": "ok"
  },
  "timestamp": 1670500000.0
}
```

**Status Codes**:

- `200 OK`: Application ready to serve traffic
- `503 Service Unavailable`: Application not ready (database down, schema not loaded)

**Use Case**: Kubernetes readiness probe - remove pod from load balancer if dependencies are not ready.

**Kubernetes Configuration**:

```yaml
readinessProbe:
  httpGet:
    path: /ready
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 2
```

---

### Why Both Probes?

| Probe | Endpoint | Purpose | Failure Action |
|-------|----------|---------|----------------|
| **Liveness** | `/health` | Is the process alive? | **Restart pod** (process crashed) |
| **Readiness** | `/ready` | Can it serve traffic? | **Remove from load balancer** (database down) |

**Example Scenario**:

- Database connection fails
- `/health` returns `200` (process is still alive)
- `/ready` returns `503` (database not ready)
- Kubernetes removes pod from service but **doesn't restart it**
- Pod reconnects to database
- `/ready` returns `200` again
- Kubernetes adds pod back to service

This prevents unnecessary pod restarts during temporary database outages.

## Quick Start

### Basic Health Endpoint

```python
from fastapi import FastAPI
from fraiseql.monitoring import HealthCheck, check_database, check_pool_stats

app = FastAPI()

# Create health check instance
health = HealthCheck()

# Register pre-built checks
health.add_check("database", check_database)
health.add_check("pool", check_pool_stats)

@app.get("/health")
async def health_endpoint():
    """Health check endpoint for monitoring and orchestration."""
    return await health.run_checks()
```

**Response Example:**

```json
{
  "status": "healthy",
  "checks": {
    "database": {
      "status": "healthy",
      "message": "Database connection successful (PostgreSQL 16.3)",
      "metadata": {
        "database_version": "16.3",
        "full_version": "PostgreSQL 16.3 (Ubuntu 16.3-1.pgdg22.04+1) on x86_64-pc-linux-gnu"
      }
    },
    "pool": {
      "status": "healthy",
      "message": "Pool healthy (45.0% utilized - 9/20 active)",
      "metadata": {
        "pool_size": 9,
        "active_connections": 9,
        "idle_connections": 0,
        "max_connections": 20,
        "min_connections": 5,
        "usage_percentage": 45.0
      }
    }
  }
}
```

## Core Concepts

### HealthCheck Class

The `HealthCheck` class is a runner that executes registered checks and aggregates results:

```python
from fraiseql.monitoring import HealthCheck

health = HealthCheck()
```

**Methods:**

- `add_check(name: str, check_fn: CheckFunction)` - Register a health check
- `run_checks() -> dict` - Execute all checks and return aggregated results

### CheckResult Dataclass

Health checks return a `CheckResult` with status and metadata:

```python
from fraiseql.monitoring import CheckResult, HealthStatus

result = CheckResult(
    name="database",
    status=HealthStatus.HEALTHY,
    message="Connection successful",
    metadata={"version": "16.3", "pool_size": 10}
)
```

**Attributes:**

- `name` - Check identifier
- `status` - `HealthStatus.HEALTHY`, `UNHEALTHY`, or `DEGRADED`
- `message` - Human-readable description
- `metadata` - Optional dictionary with additional context

### Health Statuses

```python
from fraiseql.monitoring import HealthStatus

# Individual check statuses
HealthStatus.HEALTHY    # Check passed
HealthStatus.UNHEALTHY  # Check failed
HealthStatus.DEGRADED   # Partial failure (unused in individual checks)

# Overall system status (from run_checks)
# - HEALTHY: All checks passed
# - DEGRADED: One or more checks failed
```

## Pre-built Checks

FraiseQL provides ready-to-use health checks for common dependencies.

### check_database

Verifies database connectivity and retrieves version information.

**Import:**

```python
from fraiseql.monitoring.health_checks import check_database
```

**What it checks:**

- Database connection pool availability
- Ability to execute queries (SELECT version())
- PostgreSQL version

**Usage:**

```python
health = HealthCheck()
health.add_check("database", check_database)
```

**Returns:**

```json
{
  "status": "healthy",
  "message": "Database connection successful (PostgreSQL 16.3)",
  "metadata": {
    "database_version": "16.3",
    "full_version": "PostgreSQL 16.3..."
  }
}
```

### check_pool_stats

Monitors database connection pool health and utilization.

**Import:**

```python
from fraiseql.monitoring.health_checks import check_pool_stats
```

**What it checks:**

- Pool availability
- Connection utilization (active vs idle)
- Pool saturation percentage

**Usage:**

```python
health = HealthCheck()
health.add_check("pool", check_pool_stats)
```

**Returns:**

```json
{
  "status": "healthy",
  "message": "Pool healthy (45.0% utilized - 9/20 active)",
  "metadata": {
    "pool_size": 9,
    "active_connections": 9,
    "idle_connections": 0,
    "max_connections": 20,
    "min_connections": 5,
    "usage_percentage": 45.0
  }
}
```

**Interpretation:**

- `< 75%` - "Pool healthy"
- `75-90%` - "Pool moderately utilized"
- `> 90%` - "Pool highly utilized" (consider scaling)

## Custom Checks

Create application-specific health checks following the pattern.

### Basic Custom Check

```python
from fraiseql.monitoring import CheckResult, HealthStatus

async def check_redis() -> CheckResult:
    """Check Redis cache connectivity."""
    try:
        redis = get_redis_client()
        await redis.ping()

        return CheckResult(
            name="redis",
            status=HealthStatus.HEALTHY,
            message="Redis connection successful"
        )

    except Exception as e:
        return CheckResult(
            name="redis",
            status=HealthStatus.UNHEALTHY,
            message=f"Redis connection failed: {e}"
        )

# Register the check
health.add_check("redis", check_redis)
```

### Check with Metadata

```python
async def check_s3_bucket() -> CheckResult:
    """Check S3 bucket accessibility."""
    try:
        s3_client = get_s3_client()

        # Test bucket access
        response = s3_client.head_bucket(Bucket="my-bucket")

        # Get bucket metadata
        objects = s3_client.list_objects_v2(
            Bucket="my-bucket",
            MaxKeys=1
        )
        object_count = objects.get('KeyCount', 0)

        return CheckResult(
            name="s3",
            status=HealthStatus.HEALTHY,
            message="S3 bucket accessible",
            metadata={
                "bucket": "my-bucket",
                "region": s3_client.meta.region_name,
                "object_count": object_count
            }
        )

    except Exception as e:
        return CheckResult(
            name="s3",
            status=HealthStatus.UNHEALTHY,
            message=f"S3 bucket check failed: {e}"
        )
```

### External Service Check

```python
import httpx

async def check_payment_gateway() -> CheckResult:
    """Check external payment gateway availability."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.stripe.com/v1/health",
                timeout=5.0
            )

            if response.status_code == 200:
                return CheckResult(
                    name="stripe",
                    status=HealthStatus.HEALTHY,
                    message="Payment gateway operational",
                    metadata={
                        "latency_ms": response.elapsed.total_seconds() * 1000,
                        "status_code": response.status_code
                    }
                )
            else:
                return CheckResult(
                    name="stripe",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Payment gateway returned {response.status_code}"
                )

    except httpx.TimeoutException:
        return CheckResult(
            name="stripe",
            status=HealthStatus.UNHEALTHY,
            message="Payment gateway timeout (> 5s)"
        )

    except Exception as e:
        return CheckResult(
            name="stripe",
            status=HealthStatus.UNHEALTHY,
            message=f"Payment gateway error: {e}"
        )
```

## FastAPI Integration

### Standard Health Endpoint

```python
from fastapi import FastAPI
from fraiseql.monitoring import HealthCheck, check_database, check_pool_stats

app = FastAPI()
health = HealthCheck()

# Register checks
health.add_check("database", check_database)
health.add_check("pool", check_pool_stats)

@app.get("/health")
async def health_check():
    """Kubernetes/orchestrator health check endpoint."""
    return await health.run_checks()
```

### Kubernetes-Style Liveness/Readiness

```python
from fastapi import FastAPI, Response, status
from fraiseql.monitoring import HealthCheck, check_database

app = FastAPI()

# Liveness: Is the app running?
@app.get("/health/live")
async def liveness():
    """Liveness probe - always returns 200 if app is running."""
    return {"status": "alive"}

# Readiness: Can the app serve traffic?
readiness_checks = HealthCheck()
readiness_checks.add_check("database", check_database)

@app.get("/health/ready")
async def readiness(response: Response):
    """Readiness probe - returns 200 if dependencies are healthy."""
    result = await readiness_checks.run_checks()

    if result["status"] != "healthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return result
```

### Comprehensive Health with Versioning

```python
from fastapi import FastAPI
from fraiseql.monitoring import HealthCheck, check_database, check_pool_stats
import os

app = FastAPI()

# Different check sets for different purposes
liveness = HealthCheck()  # Minimal checks

readiness = HealthCheck()  # Critical dependencies
readiness.add_check("database", check_database)

comprehensive = HealthCheck()  # All dependencies
comprehensive.add_check("database", check_database)
comprehensive.add_check("pool", check_pool_stats)
# ... add custom checks

@app.get("/health")
async def health():
    """Comprehensive health check with version info."""
    result = await comprehensive.run_checks()

    # Add application metadata
    result["version"] = os.getenv("APP_VERSION", "unknown")
    result["environment"] = os.getenv("ENV", "development")

    return result

@app.get("/health/live")
async def live():
    """Liveness - minimal check."""
    return await liveness.run_checks()

@app.get("/health/ready")
async def ready(response: Response):
    """Readiness - critical dependencies."""
    result = await readiness.run_checks()

    if result["status"] != "healthy":
        response.status_code = 503

    return result
```

## Production Patterns

### Monitoring Integration

```python
from fraiseql.monitoring import HealthCheck, check_database, check_pool_stats
import logging

logger = logging.getLogger(__name__)

health = HealthCheck()
health.add_check("database", check_database)
health.add_check("pool", check_pool_stats)

@app.get("/health")
async def health_endpoint():
    """Health check with monitoring integration."""
    result = await health.run_checks()

    # Log degraded status for alerting
    if result["status"] == "degraded":
        failed_checks = [
            name
            for name, check in result["checks"].items()
            if check["status"] != "healthy"
        ]
        logger.warning(
            f"Health check degraded: {', '.join(failed_checks)}",
            extra={
                "failed_checks": failed_checks,
                "health_status": result
            }
        )

    return result
```

### Alerting on Degradation

FraiseQL has no Sentry integration; record the degradation with the PostgreSQL error
tracker (`init_error_tracker`, see [Observability](./observability.md#error-tracking)),
whose notification rules can alert by email, Slack or webhook:

```python
from fraiseql.monitoring import HealthCheck, get_error_tracker

health = HealthCheck()
# ... register checks

@app.get("/health/detailed")
async def health_with_alerts():
    """Health check with automatic alerting."""
    result = await health.run_checks()

    if result["status"] == "degraded":
        failed_checks = {
            name: check
            for name, check in result["checks"].items()
            if check["status"] != "healthy"
        }

        tracker = get_error_tracker()
        if tracker is not None:
            await tracker.capture_message(
                f"Health check degraded: {len(failed_checks)} checks failing",
                level="warning",
                context={"application": {"failed_checks": failed_checks}},
            )

    return result
```

On an app from `create_fraiseql_app`, `GET /health` and `GET /ready` are FraiseQL's
own: a route you add on those paths is never reached, so use another path.

### Response Caching

```python
from fastapi import FastAPI
from fraiseql.monitoring import HealthCheck, check_database
import time

app = FastAPI()
health = HealthCheck()
health.add_check("database", check_database)

# Cache for high-frequency health checks
_health_cache = {"result": None, "timestamp": 0}
CACHE_TTL = 5  # seconds

@app.get("/health")
async def cached_health():
    """Health check with caching to reduce database load."""
    now = time.time()

    # Return cached result if fresh
    if _health_cache["result"] and (now - _health_cache["timestamp"]) < CACHE_TTL:
        return _health_cache["result"]

    # Run checks
    result = await health.run_checks()

    # Update cache
    _health_cache["result"] = result
    _health_cache["timestamp"] = now

    return result
```

### Environment-Specific Checks

```python
from fraiseql.monitoring import HealthCheck, check_database
import os

def create_health_checks() -> HealthCheck:
    """Create health checks based on environment."""
    health = HealthCheck()

    # Always check database
    health.add_check("database", check_database)

    # Production-specific checks
    if os.getenv("ENV") == "production":
        health.add_check("redis", check_redis)
        health.add_check("s3", check_s3_bucket)
        health.add_check("stripe", check_payment_gateway)

    return health

health = create_health_checks()
```

## Best Practices

### 1. Separate Liveness and Readiness

```python
# Liveness: App is running (no external dependencies)
@app.get("/health/live")
async def liveness():
    return {"status": "alive"}

# Readiness: App can serve traffic (check dependencies)
@app.get("/health/ready")
async def readiness():
    return await health.run_checks()
```

### 2. Include Metadata for Debugging

```python
async def check_with_metadata() -> CheckResult:
    """Include diagnostic information."""
    return CheckResult(
        name="service",
        status=HealthStatus.HEALTHY,
        message="Service operational",
        metadata={
            "version": "1.2.3",
            "uptime_seconds": get_uptime(),
            "last_request": get_last_request_time()
        }
    )
```

### 3. Timeout Long-Running Checks

```python
import asyncio

async def check_with_timeout() -> CheckResult:
    """Prevent health checks from hanging."""
    try:
        # Timeout after 5 seconds
        async with asyncio.timeout(5.0):
            result = await slow_external_check()

        return CheckResult(
            name="external_api",
            status=HealthStatus.HEALTHY,
            message="External API responding"
        )

    except asyncio.TimeoutError:
        return CheckResult(
            name="external_api",
            status=HealthStatus.UNHEALTHY,
            message="External API timeout (> 5s)"
        )
```

### 4. Don't Check on Every Request

```python
# ❌ Bad: Health check runs on every GraphQL request
@app.middleware("http")
async def health_middleware(request, call_next):
    await health.run_checks()  # Expensive!
    return await call_next(request)

# ✅ Good: Dedicated health endpoint
@app.get("/health")
async def health_endpoint():
    return await health.run_checks()
```

## See Also

- [Production Deployment](../production/deployment.md) - Kubernetes health probes
- [Monitoring](../production/monitoring.md) - Metrics and observability
- [Sentry Integration](../production/monitoring.md#sentry-integration-legacyoptional) - Error tracking

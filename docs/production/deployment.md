---
title: Production Deployment
description: Complete guide for deploying FraiseQL with Docker, Kubernetes, and scaling strategies
tags:
  - deployment
  - production
  - docker
  - kubernetes
  - scaling
  - CI/CD
---

# Production Deployment

Complete production deployment guide for FraiseQL: Docker, Kubernetes, environment management, health checks, scaling strategies, and rollback procedures.

## Overview

Deploy FraiseQL applications to production with confidence using battle-tested patterns for Docker containers, Kubernetes orchestration, and zero-downtime deployments.

**Deployment Targets:**

- Docker (standalone or Compose)
- Kubernetes (with Helm charts)
- Cloud platforms (GCP, AWS, Azure)
- Edge/CDN deployments

## Docker Deployment

### Production Dockerfile

Multi-stage build optimized for security and size:

```dockerfile
# Stage 1: Builder
FROM python:3.13-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy dependency files
COPY pyproject.toml README.md ./
COPY src ./src

# Build wheel
RUN pip install --no-cache-dir build && \
    python -m build --wheel

# Stage 2: Runtime
FROM python:3.13-slim

# Runtime dependencies only
RUN apt-get update && apt-get install -y \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r fraiseql && useradd -r -g fraiseql fraiseql

WORKDIR /app

# Copy wheel from builder
COPY --from=builder /build/dist/*.whl /tmp/

# Install FraiseQL + production dependencies
RUN pip install --no-cache-dir \
    /tmp/*.whl \
    uvicorn[standard]==0.24.0 \
    gunicorn==21.2.0 \
    prometheus-client==0.19.0 \
    sentry-sdk[fastapi]==1.38.0 \
    && rm -rf /tmp/*.whl

# Copy application code
COPY app /app

# Set permissions
RUN chown -R fraiseql:fraiseql /app

# Switch to non-root user
USER fraiseql

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FRAISEQL_ENVIRONMENT=production

# Run with Gunicorn
CMD ["gunicorn", "app:app", \
     "-w", "4", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info"]
```

### Docker Compose Production

```yaml
version: '3.8'

services:
  fraiseql:
    build:
      context: .
      dockerfile: Dockerfile
    image: fraiseql:${VERSION:-latest}
    container_name: fraiseql-app
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:${DB_PASSWORD}@postgres:5432/fraiseql
      - ENVIRONMENT=production
      - LOG_LEVEL=INFO
      - SENTRY_DSN=${SENTRY_DSN}
    env_file:
      - .env.production
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 3s
      retries: 3
      start_period: 10s
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 1G
        reservations:
          cpus: '0.5'
          memory: 512M
    networks:
      - fraiseql-network

  postgres:
    image: postgres:16-alpine
    container_name: fraiseql-postgres
    restart: unless-stopped
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=${DB_PASSWORD}
      - POSTGRES_DB=fraiseql
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - fraiseql-network

  redis:
    image: redis:7-alpine
    container_name: fraiseql-redis
    restart: unless-stopped
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    networks:
      - fraiseql-network

  nginx:
    image: nginx:alpine
    container_name: fraiseql-nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    depends_on:
      - fraiseql
    networks:
      - fraiseql-network

volumes:
  postgres_data:
  redis_data:

networks:
  fraiseql-network:
    driver: bridge
```

## Kubernetes Deployment

### Complete Deployment Manifest

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fraiseql
  namespace: production
  labels:
    app: fraiseql
    tier: backend
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: fraiseql
  template:
    metadata:
      labels:
        app: fraiseql
        version: v1.0.0
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: fraiseql
      containers:
      - name: fraiseql
        image: gcr.io/your-project/fraiseql:1.0.0
        imagePullPolicy: IfNotPresent
        ports:
        - name: http
          containerPort: 8000
          protocol: TCP
        - name: metrics
          containerPort: 8000

        # Environment from ConfigMap
        envFrom:
        - configMapRef:
            name: fraiseql-config
        # Secrets
        env:
        - name: DATABASE_PASSWORD
          valueFrom:
            secretKeyRef:
              name: fraiseql-secrets
              key: database-password
        - name: SENTRY_DSN
          valueFrom:
            secretKeyRef:
              name: fraiseql-secrets
              key: sentry-dsn

        # Resource requests/limits
        resources:
          requests:
            cpu: 250m
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 1Gi

        # Liveness probe
        livenessProbe:
          httpGet:
            path: /health
            port: http
          initialDelaySeconds: 10
          periodSeconds: 30
          timeoutSeconds: 5
          failureThreshold: 3

        # Readiness probe
        readinessProbe:
          httpGet:
            path: /ready
            port: http
          initialDelaySeconds: 5
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 2

        # Startup probe
        startupProbe:
          httpGet:
            path: /health
            port: http
          initialDelaySeconds: 0
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 30

        # Security context
        securityContext:
          runAsNonRoot: true
          runAsUser: 1000
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: false
          capabilities:
            drop:
            - ALL

      # Graceful shutdown
      terminationGracePeriodSeconds: 30

      # Pod-level security
      securityContext:
        fsGroup: 1000

---
apiVersion: v1
kind: Service
metadata:
  name: fraiseql
  namespace: production
  labels:
    app: fraiseql
spec:
  type: ClusterIP
  ports:
  - name: http
    port: 80
    targetPort: http
    protocol: TCP
  - name: metrics
    port: 8000
    targetPort: metrics
  selector:
    app: fraiseql
```

### Horizontal Pod Autoscaler

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: fraiseql
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: fraiseql
  minReplicas: 3
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  - type: Pods
    pods:
      metric:
        name: graphql_requests_per_second
      target:
        type: AverageValue
        averageValue: "100"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 30
      policies:
      - type: Percent
        value: 50
        periodSeconds: 15
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 10
        periodSeconds: 60
```

## Environment Configuration

### Environment Variables

```bash
# .env.production
# Core
FRAISEQL_ENVIRONMENT=production
FRAISEQL_APP_NAME="FraiseQL API"
FRAISEQL_APP_VERSION=1.0.0

# Database
FRAISEQL_DATABASE_URL=postgresql://user:password@localhost:5432/fraiseql
FRAISEQL_DATABASE_POOL_SIZE=20
FRAISEQL_DATABASE_MAX_OVERFLOW=10
FRAISEQL_DATABASE_POOL_TIMEOUT=30

# Security
FRAISEQL_AUTH_ENABLED=true
FRAISEQL_AUTH_PROVIDER=auth0
FRAISEQL_AUTH0_DOMAIN=your-tenant.auth0.com
FRAISEQL_AUTH0_API_IDENTIFIER=https://api.yourapp.com

# Performance (the Rust pipeline and TurboRouter are always on)
FRAISEQL_TURBO_ROUTER_CACHE_SIZE=1000

# GraphQL
FRAISEQL_INTROSPECTION_POLICY=disabled
FRAISEQL_ENABLE_PLAYGROUND=false
FRAISEQL_QUERY_TIMEOUT=30

# Monitoring: /metrics comes from setup_metrics(app) in code, not a variable
SENTRY_DSN=https://...@sentry.io/...
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.1

# CORS
FRAISEQL_CORS_ENABLED=true
FRAISEQL_CORS_ORIGINS='["https://app.yourapp.com","https://www.yourapp.com"]'
```

List values such as `FRAISEQL_CORS_ORIGINS` are JSON. `FraiseQLConfig` also declares
`cache_ttl`, which nothing reads (deprecated), so it is left out here. To limit
requests per client IP, add `FRAISEQL_RATE_LIMIT_ENABLED=true` (see
[Rate Limiting](../configuration/rate-limiting.md)). To limit query depth and size, add `FRAISEQL_MAX_QUERY_DEPTH=10` and
`FRAISEQL_COMPLEXITY_MAX_SCORE=1000` (no limit by default).

### Kubernetes Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: fraiseql-secrets
  namespace: production
type: Opaque
stringData:
  database-password: "your-secure-password"
  sentry-dsn: "https://...@sentry.io/..."
  auth0-client-secret: "your-auth0-secret"
```

## Database Migrations

### Migration Strategy

```python
# migrations/run_migrations.py
import asyncio
import sys
from alembic import command
from alembic.config import Config

async def run_migrations():
    """Run database migrations before deployment."""
    alembic_cfg = Config("alembic.ini")

    try:
        # Check current version
        command.current(alembic_cfg)

        # Run migrations
        command.upgrade(alembic_cfg, "head")

        print("✓ Migrations completed successfully")
        return 0

    except Exception as e:
        print(f"✗ Migration failed: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(run_migrations()))
```

### Kubernetes Init Container

```yaml
spec:
  initContainers:
  - name: migrate
    image: gcr.io/your-project/fraiseql:1.0.0
    command: ["python", "migrations/run_migrations.py"]
    envFrom:
    - configMapRef:
        name: fraiseql-config
    env:
    - name: DATABASE_PASSWORD
      valueFrom:
        secretKeyRef:
          name: fraiseql-secrets
          key: database-password
```

## Health Checks

### Health Check Endpoint

```python
from fraiseql.monitoring import HealthCheck, CheckResult, HealthStatus
from fraiseql.monitoring.health_checks import check_database, check_pool_stats

# Create health check
health = HealthCheck()
health.add_check("database", check_database)
health.add_check("pool", check_pool_stats)

# FastAPI endpoints
from fastapi import FastAPI, Response

app = FastAPI()

@app.get("/health")
async def health_check():
    """Simple liveness check."""
    return {"status": "healthy", "service": "fraiseql"}

@app.get("/ready")
async def readiness_check():
    """Comprehensive readiness check."""
    result = await health.run_checks()

    if result["status"] == "healthy":
        return result
    else:
        return Response(
            content=json.dumps(result),
            status_code=503,
            media_type="application/json"
        )
```

## Scaling Strategies

### Horizontal Scaling

```bash
# Manual scaling
kubectl scale deployment fraiseql --replicas=10 -n production

# Check autoscaler status
kubectl get hpa fraiseql -n production

# View scaling events
kubectl describe hpa fraiseql -n production
```

### Vertical Scaling

```yaml
# Update resource limits
resources:
  requests:
    cpu: 500m
    memory: 1Gi
  limits:
    cpu: 2000m
    memory: 2Gi

# Apply changes
kubectl apply -f deployment.yaml
```

### Database Connection Pool Scaling

```python
# Adjust pool size based on replicas
# Rule: total_connections = replicas * pool_size
# PostgreSQL max_connections should be: total_connections + buffer

# 3 replicas * 20 connections = 60 total
# Set PostgreSQL max_connections = 100

config = FraiseQLConfig(
    database_pool_size=20,
    database_max_overflow=10
)
```

## Zero-Downtime Deployment

### Rolling Update Strategy

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1         # Max pods above desired count
    maxUnavailable: 0   # No downtime
```

### Deployment Process

```bash
# 1. Build new image
docker build -t gcr.io/your-project/fraiseql:1.0.1 .
docker push gcr.io/your-project/fraiseql:1.0.1

# 2. Update deployment
kubectl set image deployment/fraiseql \
  fraiseql=gcr.io/your-project/fraiseql:1.0.1 \
  -n production

# 3. Watch rollout
kubectl rollout status deployment/fraiseql -n production

# 4. Verify new version
kubectl get pods -n production -l app=fraiseql
```

### Blue-Green Deployment

```yaml
# Green deployment (new version)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fraiseql-green
spec:
  replicas: 3
  selector:
    matchLabels:
      app: fraiseql
      version: green
  template:
    metadata:
      labels:
        app: fraiseql
        version: green
    spec:
      containers:
      - name: fraiseql
        image: gcr.io/your-project/fraiseql:1.0.1

---
# Switch service to green
apiVersion: v1
kind: Service
metadata:
  name: fraiseql
spec:
  selector:
    app: fraiseql
    version: green  # Changed from blue to green
```

## Rollback Procedures

### Kubernetes Rollback

```bash
# View rollout history
kubectl rollout history deployment/fraiseql -n production

# Rollback to previous version
kubectl rollout undo deployment/fraiseql -n production

# Rollback to specific revision
kubectl rollout undo deployment/fraiseql --to-revision=2 -n production

# Verify rollback
kubectl rollout status deployment/fraiseql -n production
```

### Database Rollback

```python
# migrations/rollback.py
from alembic import command
from alembic.config import Config

def rollback_migration(steps: int = 1):
    """Rollback database migrations."""
    alembic_cfg = Config("alembic.ini")
    command.downgrade(alembic_cfg, f"-{steps}")
    print(f"✓ Rolled back {steps} migration(s)")

# Rollback one migration
rollback_migration(1)
```

### Emergency Rollback Script

```bash
#!/bin/bash
# rollback.sh

set -e

echo "🚨 Emergency rollback initiated"

# 1. Rollback Kubernetes deployment
echo "Rolling back deployment..."
kubectl rollout undo deployment/fraiseql -n production

# 2. Wait for rollback
echo "Waiting for rollback to complete..."
kubectl rollout status deployment/fraiseql -n production

# 3. Verify health
echo "Checking health..."
kubectl exec -n production deployment/fraiseql -- curl -f http://localhost:8000/health

echo "✓ Rollback completed successfully"
```

## Next Steps

- [Monitoring](monitoring.md) - Metrics, logs, and alerting
- [Security](security.md) - Production security hardening
- [Performance](../performance/index.md) - Production optimization

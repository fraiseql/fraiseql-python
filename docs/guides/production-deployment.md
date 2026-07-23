---
title: Production Deployment Guide
description: Deploying the FraiseQL FastAPI application to production with Docker, Kubernetes, and PostgreSQL
keywords: ["deployment", "production", "kubernetes", "docker", "postgresql"]
tags: ["documentation", "guide"]
---

# Production Deployment Guide

**Status:** ✅ Production Ready
**Audience:** DevOps, SREs, Infrastructure Engineers
**Reading Time:** 20-30 minutes
**Platforms**: Kubernetes, Docker Compose, bare metal

FraiseQL is a Python (FastAPI) application. You deploy it the same way you deploy
any ASGI app: install the package with `pip`/`uv`, then run it under an ASGI server
such as `uvicorn` or `gunicorn` with the uvicorn worker. The GraphQL schema is built
in memory at application startup from your Python decorators — there is no separate
build step and no generated artifact to ship.

## Prerequisites

**Required Knowledge:**

- Docker containerization and image management
- Kubernetes fundamentals (Pods, Deployments, Services, ConfigMaps, Secrets)
- Linux/Unix system administration
- PostgreSQL/database administration
- TLS/SSL certificate management
- Basic networking (DNS, ports, firewalls)

**Required Software:**

- Python 3.13+ and the `fraiseql` package (install via `pip` or `uv`)
- Docker 20.10+ (if using containers)
- kubectl 1.24+ (if using Kubernetes)
- PostgreSQL 14+ client tools
- OpenSSL for certificate management

**Required Infrastructure:**

- PostgreSQL 14+ database (managed or self-hosted)
- Kubernetes cluster 1.24+ or Docker host
- Container registry (Docker Hub, AWS ECR, Google GCR, etc.)
- Domain name with DNS records
- TLS/SSL certificates

**Recommended Tools:**

- Helm 3+ (for Kubernetes package management)
- kube-ops (for operational dashboards)
- ArgoCD (for GitOps deployments)
- Prometheus + Grafana (for monitoring)

**Time Estimate:** 2-4 hours for initial deployment

---

## Overview

This guide covers deploying FraiseQL to production environments with:

- **Security hardening** - TLS, mTLS, view-based security, rate limiting
- **Performance optimization** - Connection pooling, caching, APQ
- **High availability** - Multi-replica deployments, health checks, graceful shutdown
- **Observability** - Prometheus metrics, OpenTelemetry tracing, structured logging
- **Compliance** - Audit logging, security headers, access controls
- **Kubernetes** - Native integration with HPA, Pod Security Standards, Network Policies

---

## Pre-Deployment Checklist

### Infrastructure Requirements

- [ ] PostgreSQL 13+ instance (managed or self-hosted)
- [ ] SSL/TLS certificates for domain
- [ ] Container registry (Docker Hub, ECR, GCR, or self-hosted)
- [ ] Kubernetes cluster (1.24+) or Docker Compose environment
- [ ] Monitoring infrastructure (Prometheus, Grafana)
- [ ] Logging infrastructure (optional: Loki, ELK)
- [ ] Tracing backend (optional: Jaeger, Zipkin)

### Credentials & Secrets

- [ ] PostgreSQL connection credentials
- [ ] Auth provider credentials (Auth0, JWT, etc.)
- [ ] TLS certificates (fullchain.pem, private.key)
- [ ] API keys for external services
- [ ] Environment-specific configuration

### Application Configuration

- [ ] Database schema migrated to target environment
- [ ] Graphql queries registered (if using APQ in REQUIRED mode)
- [ ] Security profiles configured (STANDARD/REGULATED/RESTRICTED)
- [ ] Rate limiting thresholds set
- [ ] APQ storage backend configured

---

## Configuration Management

### Environment Variables

`FraiseQLConfig` is a Pydantic settings object: every field can be set with a
matching `FRAISEQL_`-prefixed environment variable, or passed directly as a keyword
argument to `create_fraiseql_app(...)`.

```bash
# Application
FRAISEQL_ENVIRONMENT=production

# Database
FRAISEQL_DATABASE_URL=postgresql://user:pass@db.example.com:5432/fraiseql

# GraphQL
FRAISEQL_INTROSPECTION_POLICY=disabled
FRAISEQL_ENABLE_PLAYGROUND=false

# Security
FRAISEQL_AUTH_ENABLED=true
FRAISEQL_AUTH_PROVIDER=auth0
FRAISEQL_RATE_LIMIT_ENABLED=true
FRAISEQL_RATE_LIMIT_REQUESTS_PER_MINUTE=100
FRAISEQL_COMPLEXITY_MAX_SCORE=1000

# APQ
FRAISEQL_APQ_MODE=required
FRAISEQL_APQ_STORAGE_BACKEND=postgresql
FRAISEQL_APQ_RESPONSE_CACHE_TTL=600

# Caching
FRAISEQL_CACHE_TTL=300
FRAISEQL_TURBO_ROUTER_CACHE_SIZE=1000
```

### Kubernetes ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: fraiseql-config
  namespace: default
data:
  FRAISEQL_ENVIRONMENT: "production"
  FRAISEQL_INTROSPECTION_POLICY: "disabled"
  FRAISEQL_RATE_LIMIT_REQUESTS_PER_MINUTE: "100"
  FRAISEQL_APQ_MODE: "required"
  FRAISEQL_APQ_STORAGE_BACKEND: "postgresql"
```

### Kubernetes Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: fraiseql-secrets
  namespace: default
type: Opaque
stringData:
  FRAISEQL_DATABASE_URL: "postgresql://user:pass@db:5432/fraiseql"
  AUTH0_DOMAIN: "your-tenant.auth0.com"
  AUTH0_API_IDENTIFIER: "https://api.example.com"
```

---

## Container Deployment

### Docker Image

FraiseQL ships as a normal Python wheel. The optional `fraiseql_rs` acceleration
extension is published as a prebuilt wheel, so installing `fraiseql` does **not**
require a Rust toolchain in your image.

#### Building the Image

```dockerfile
# Multi-stage build
FROM python:3.13-slim AS builder

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

# Install dependencies (fraiseql and your application requirements)
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.13-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl && rm -rf /var/lib/apt/lists/*
COPY --from=builder /install /usr/local
COPY . /app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# app:app is your module exposing the FraiseQL FastAPI app from create_fraiseql_app(...)
CMD ["gunicorn", "app:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]
```

#### Building & Pushing

```bash
# Build
docker build -t myregistry/fraiseql-app:1.0.0 .
docker build -t myregistry/fraiseql-app:latest .

# Push
docker push myregistry/fraiseql-app:1.0.0
docker push myregistry/fraiseql-app:latest

# Scan for vulnerabilities
trivy image myregistry/fraiseql-app:1.0.0
```

#### Hardened Image

For high-security environments, build on a distroless or hardened base image with:

- Non-root user (UID: 65532)
- Reduced attack surface
- CVE fixes
- Read-only root filesystem compatible
- No shell access

```bash
docker build -f Dockerfile.hardened -t myregistry/fraiseql-app:hardened .
```

---

## Kubernetes Deployment

### Standard Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fraiseql
  namespace: default
  labels:
    app: fraiseql
    version: "1.0"
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
        version: "1.0"
    spec:
      serviceAccountName: fraiseql
      securityContext:
        runAsNonRoot: true
        runAsUser: 65532
        fsGroup: 65532
        seccompProfile:
          type: RuntimeDefault

      containers:
      - name: fraiseql
        image: myregistry/fraiseql-app:1.0.0
        imagePullPolicy: IfNotPresent

        ports:
        - name: http
          containerPort: 8000
          protocol: TCP

        # Environment from ConfigMap and Secret
        envFrom:
        - configMapRef:
            name: fraiseql-config
        - secretRef:
            name: fraiseql-secrets

        # Resource constraints
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "1000m"

        # Health checks (/health is built in; /health/ready is your custom check)
        livenessProbe:
          httpGet:
            path: /health
            port: http
          initialDelaySeconds: 30
          periodSeconds: 30
          timeoutSeconds: 5
          failureThreshold: 3

        readinessProbe:
          httpGet:
            path: /health/ready
            port: http
          initialDelaySeconds: 10
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 2

        startupProbe:
          httpGet:
            path: /health
            port: http
          initialDelaySeconds: 5
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 30  # 150 seconds total

        # Security
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          runAsNonRoot: true
          runAsUser: 65532
          capabilities:
            drop: [ALL]

        # Volume mounts for temp files
        volumeMounts:
        - name: tmp
          mountPath: /tmp
        - name: var-run
          mountPath: /var/run

      volumes:
      - name: tmp
        emptyDir: {}
      - name: var-run
        emptyDir: {}

      # Pod disruption budget
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: app
                  operator: In
                  values: [fraiseql]
              topologyKey: kubernetes.io/hostname

      terminationGracePeriodSeconds: 30
```

### Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: fraiseql
  namespace: default
  labels:
    app: fraiseql
spec:
  type: ClusterIP
  selector:
    app: fraiseql
  ports:
  - name: http
    port: 8000
    targetPort: http
    protocol: TCP
  sessionAffinity: None  # Round-robin, no sticky sessions
```

### Horizontal Pod Autoscaler

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: fraiseql
  namespace: default
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: fraiseql
  minReplicas: 3
  maxReplicas: 20
  metrics:
  # CPU-based scaling
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  # Memory-based scaling
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  # Custom GraphQL metrics (if metrics exposed)
  - type: Pods
    pods:
      metric:
        name: graphql_requests_per_second
      target:
        type: AverageValue
        averageValue: "100"  # Scale at 100 req/s per pod
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 50
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
      - type: Percent
        value: 100
        periodSeconds: 15
      - type: Pods
        value: 4
        periodSeconds: 15
      selectPolicy: Max
```

### Pod Disruption Budget

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: fraiseql
  namespace: default
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: fraiseql
```

### Network Policies (Zero Trust)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: fraiseql
  namespace: default
spec:
  podSelector:
    matchLabels:
      app: fraiseql
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # Allow from ingress controller
  - from:
    - namespaceSelector:
        matchLabels:
          name: ingress-nginx
    ports:
    - protocol: TCP
      port: 8000
  # Allow from Prometheus scraper
  - from:
    - namespaceSelector:
        matchLabels:
          name: monitoring
    ports:
    - protocol: TCP
      port: 8000
  egress:
  # Allow to PostgreSQL
  - to:
    - podSelector: {}
    ports:
    - protocol: TCP
      port: 5432
  # Allow DNS
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
  # Allow to external APIs (if needed)
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: TCP
      port: 443
```

### Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: fraiseql
  namespace: default
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/rate-limit: "100"
    nginx.ingress.kubernetes.io/rate-limit-window: "1m"
    nginx.ingress.kubernetes.io/ssl-protocols: "TLSv1.2 TLSv1.3"
    nginx.ingress.kubernetes.io/add-headers: "true"
    nginx.ingress.kubernetes.io/configuration-snippet: |
      more_set_headers "X-Frame-Options: DENY";
      more_set_headers "X-Content-Type-Options: nosniff";
      more_set_headers "X-XSS-Protection: 1; mode=block";
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - api.example.com
    secretName: fraiseql-tls
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: fraiseql
            port:
              number: 8000
```

---

## Database Configuration

### PostgreSQL Setup

```sql
-- Create database
CREATE DATABASE fraiseql
  WITH ENCODING 'UTF8'
       LC_COLLATE 'en_US.UTF-8'
       LC_CTYPE 'en_US.UTF-8'
       TEMPLATE template0;

-- Create application user
CREATE USER fraiseql_app WITH PASSWORD 'secure_password';

-- Grant permissions
GRANT CONNECT ON DATABASE fraiseql TO fraiseql_app;
GRANT USAGE ON SCHEMA public TO fraiseql_app;
GRANT CREATE ON SCHEMA public TO fraiseql_app;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO fraiseql_app;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO fraiseql_app;

-- Set default privileges for future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO fraiseql_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO fraiseql_app;
```

### Connection Pool Configuration

```python
# Optimal pool settings for production
pool_config = {
    "host": "db.example.com",
    "port": 5432,
    "database": "fraiseql",
    "user": "fraiseql_app",
    "password": os.getenv("DB_PASSWORD"),
    "min_size": 20,          # Maintain minimum connections
    "max_size": 100,         # Scale up to 100
    "max_idle_time": 60,     # Recycle idle connections
    "max_lifetime": 1800,    # Renew connections every 30 min
    "command_timeout": 30,   # 30 second query timeout
    "timeout": 30,           # 30 second connection timeout
    "ssl": "require",        # Require SSL/TLS
    "ssl_certificate": "/etc/ssl/certs/ca-bundle.crt"
}
```

### Indexing Strategy

```sql
-- User-related indexes
CREATE INDEX idx_user_id ON users(id);
CREATE INDEX idx_user_email ON users(email) WHERE deleted_at IS NULL;
CREATE INDEX idx_user_created_at ON users(created_at DESC);

-- Order-related indexes (composite)
CREATE INDEX idx_orders_user_date ON orders(user_id, created_at DESC) WHERE status != 'deleted';
CREATE INDEX idx_orders_status ON orders(status) WHERE created_at > now() - interval '90 days';

-- JSONB indexes
CREATE INDEX idx_user_metadata ON users USING gin(metadata);
CREATE INDEX idx_user_metadata_tags ON users USING gin(metadata->'tags');

-- Full-text search
CREATE INDEX idx_products_content ON products USING gin(to_tsvector('english', name || ' ' || description));

-- Soft delete queries
CREATE INDEX idx_active_records ON (table_name) WHERE deleted_at IS NULL;
```

---

## Security Hardening

### Introspection Control

```python
# Disable introspection in production
config = FraiseQLConfig(
    introspection_policy=IntrospectionPolicy.DISABLED
)
```

**Introspection Policies**:

- `DISABLED` - No introspection (recommended for production)
- `AUTHENTICATED` - Only authenticated users can introspect
- `PUBLIC` - Anyone can introspect (development only)

### Rate Limiting

```python
config = FraiseQLConfig(
    rate_limit_enabled=True,
    rate_limit_requests_per_minute=100,      # 100 req/min = ~1.67 req/sec
    rate_limit_requests_per_hour=5000,       # 5000 req/hour
    rate_limit_burst_size=10,                # Allow 10 concurrent
    rate_limit_window_type="sliding",        # More accurate
    rate_limit_whitelist=["internal.ips"],
    rate_limit_blacklist=["malicious.ips"]
)
```

### Query Complexity Limits

```python
config = FraiseQLConfig(
    complexity_enabled=True,
    complexity_max_score=1000,     # Reject complex queries
    complexity_max_depth=10,       # Prevent deep nesting
    complexity_default_list_size=10,
    complexity_field_multipliers={
        "users": 2,                # More expensive
        "orders": 3,
        "analytics": 10,           # Very expensive
        "reports": 15
    }
)
```

### TLS/mTLS Configuration

```python
# Connection string with TLS
DATABASE_URL = "postgresql://user:pass@db.example.com:5432/fraiseql?sslmode=require"

# Kubernetes pod with client certificates
containers:

- name: fraiseql
  env:
  - name: SSL_CERT_FILE
    value: /etc/ssl/certs/ca-bundle.crt
  - name: SSL_CLIENT_CERT_FILE
    value: /etc/ssl/certs/client-cert.pem
  - name: SSL_CLIENT_KEY_FILE
    value: /etc/ssl/private/client-key.pem
  volumeMounts:
  - name: tls-certs
    mountPath: /etc/ssl/certs
    readOnly: true
  - name: tls-keys
    mountPath: /etc/ssl/private
    readOnly: true
volumes:

- name: tls-certs
  secret:
    secretName: fraiseql-tls-certs
- name: tls-keys
  secret:
    secretName: fraiseql-tls-keys
```

### Security Headers

```yaml
# Nginx Ingress annotations
annotations:
  nginx.ingress.kubernetes.io/configuration-snippet: |
    more_set_headers "X-Frame-Options: DENY";
    more_set_headers "X-Content-Type-Options: nosniff";
    more_set_headers "X-XSS-Protection: 1; mode=block";
    more_set_headers "Referrer-Policy: strict-origin-when-cross-origin";
    more_set_headers "Permissions-Policy: geolocation=(), microphone=(), camera=()";
    more_set_headers "Strict-Transport-Security: max-age=31536000; includeSubDomains";
```

### CORS Configuration

```python
config = FraiseQLConfig(
    cors_enabled=False  # Disable by default, handle at Ingress
)

# Or if enabling at application level:
cors_enabled=True
cors_origins=["https://app.example.com", "https://admin.example.com"]
cors_methods=["GET", "POST"]
cors_headers=["Content-Type", "Authorization"]
cors_allow_credentials=True
cors_max_age=3600
```

---

## Performance Optimization

### APQ (Automatic Persisted Queries)

**For bandwidth optimization**:

```python
config = FraiseQLConfig(
    apq_mode=APQMode.REQUIRED,           # Only persisted queries
    apq_storage_backend="postgresql",     # Persistent storage
    apq_cache_responses=True,             # Cache responses
    apq_response_cache_ttl=600            # 10 minutes
)
```

**Register queries at deploy time**:

```bash
# Move GraphQL files to directory
FRAISEQL_APQ_QUERIES_DIR=/app/graphql/queries

# Queries in /app/graphql/queries/*.graphql are auto-registered
```

**Expected performance**:

- Payload reduction: 95%+
- Cache hit rate: 85-95%
- Bandwidth savings: 10-50x

### Caching Strategy

```python
# Multi-level caching
config = FraiseQLConfig(
    cache_ttl=300,                           # Query cache TTL: 5 minutes
    apq_response_cache_ttl=600,              # APQ response cache: 10 minutes
    turbo_router_cache_size=1000             # TurboRouter cache size
)
```

FraiseQL also ships a PostgreSQL-backed result cache with cascade invalidation
(`PostgresCache`, `ResultCache`, `CachedRepository`) for caching query results
directly in your database — see the caching reference for details.

**Expected hit rates**:

- Stable APIs: 95%+
- Dynamic queries: 80-90%
- Admin interfaces: 70-85%

### Connection Pooling

FraiseQL manages an async PostgreSQL connection pool (psycopg) internally. Tune it
through `FraiseQLConfig` (or the matching `FRAISEQL_` environment variables):

```python
config = FraiseQLConfig(
    database_url=database_url,
    database_pool_size=20,        # Connections to maintain
    database_pool_timeout=30,     # Seconds to wait for a free connection
    database_pool_recycle=1800,   # Recycle connections after 30 min
)
```

---

## Monitoring & Observability

### Prometheus Metrics

```python
from fraiseql.monitoring import setup_metrics, MetricsConfig

# app is the FastAPI app returned by create_fraiseql_app(...)
setup_metrics(app, MetricsConfig(
    enabled=True,
    namespace="myapp",
    metrics_path="/metrics"
))
```

### OpenTelemetry Tracing

```python
from fraiseql.tracing import setup_tracing, TracingConfig

setup_tracing(app, TracingConfig(
    enabled=True,
    service_name="fraiseql-api",
    export_format="otlp",
    export_endpoint="jaeger:4317",
    sample_rate=0.1  # 10% sampling in production
))
```

### Health Checks

`create_fraiseql_app(...)` automatically registers a built-in `GET /health`
endpoint that returns a process-level liveness status — point your Kubernetes
liveness, readiness, and startup probes at it.

For deeper checks (database connectivity, pool stats), build a composable
`HealthCheck` and expose it on your own route:

```python
from fraiseql.monitoring import HealthCheck, check_database, check_pool_stats

health = HealthCheck()
health.add_check("database", check_database)
health.add_check("pool", check_pool_stats)

@app.get("/health/ready")
async def readiness():
    return await health.run_checks()
```

**Available endpoints**:

- `GET /health` - Built-in process liveness check
- `GET /health/ready` - Readiness with custom `HealthCheck` (example above)

---

## Deployment Automation

### GitOps Workflow

```bash
# 1. Create feature branch
git checkout -b feature/new-feature

# 2. Make changes and commit
git add .
git commit -m "feat: new feature"

# 3. Push and create PR
git push -u origin feature/new-feature
gh pr create

# 4. CI/CD pipeline runs:
#    - Build Docker image
#    - Scan for vulnerabilities
#    - Run tests
#    - Push to registry
#    - Update Kubernetes manifests (ArgoCD)

# 5. PR merged to main
# 6. ArgoCD syncs changes to production
```

### Helm Chart Deployment

```bash
# Install
helm install fraiseql ./helm-chart \
  --namespace default \
  --values values-prod.yaml

# Upgrade
helm upgrade fraiseql ./helm-chart \
  --namespace default \
  --values values-prod.yaml

# Rollback
helm rollback fraiseql 1
```

---

## Disaster Recovery

### Backup Strategy

```sql
-- Daily backup
pg_dump fraiseql > /backups/fraiseql_$(date +%Y%m%d).sql

-- With compression
pg_dump -Fc fraiseql > /backups/fraiseql_$(date +%Y%m%d).dump

-- With parallel jobs
pg_dump -Fd -j 4 fraiseql > /backups/fraiseql_$(date +%Y%m%d)_parallel/
```

### Restore Procedure

```sql
-- From SQL dump
psql fraiseql < /backups/fraiseql_20250111.sql

-- From custom format dump
pg_restore -d fraiseql /backups/fraiseql_20250111.dump

-- Verify
SELECT COUNT(*) FROM users;
SELECT MAX(created_at) FROM audit_events;
```

### Database Replication

```sql
-- Primary-Replica setup
-- On primary:
CREATE PUBLICATION fraiseql FOR ALL TABLES;

-- On replica:
CREATE SUBSCRIPTION fraiseql CONNECTION 'postgresql://primary:5432/fraiseql' PUBLICATION fraiseql;

-- Monitor replication lag
SELECT now() - pg_last_wal_receive_lsn()::text::pg_lsn / 1000000 AS replication_lag_seconds;
```

---

## Scaling Recommendations

### Single-Region (Recommended Starting Point)

```
3 fraiseql pods (minimum)
1 PostgreSQL instance (managed)
Prometheus (1 instance)
```

**Capacity**:

- Up to 1,000 requests/second
- Sub-100ms P95 latency
- Database: 100-500GB

### Multi-Region

```
3 fraiseql pods per region (3+ regions)
PostgreSQL primary + replicas
Cross-region failover
```

**Capacity**:

- Up to 10,000+ requests/second
- <50ms P95 latency globally
- Database: 500GB-10TB

---

## Troubleshooting

### High CPU Usage

1. Check query complexity scores
2. Enable slow query logging
3. Analyze database query plans
4. Scale up horizontally

### Memory Leaks

1. Check cache configuration
2. Monitor pool connections
3. Review APQ storage size
4. Increase memory limits

### Database Connection Pool Exhaustion

1. Check active query count
2. Review query timeouts
3. Increase pool size
4. Optimize slow queries

### High Latency

1. Check database performance
2. Verify indexes are in place
3. Analyze query complexity
4. Check network latency

---

## Summary

FraiseQL production deployments include:

✅ **Zero-trust security** - View-based access, rate limiting, introspection control
✅ **High availability** - Multi-replica Kubernetes, health checks, graceful shutdown
✅ **Performance** - APQ, caching, connection pooling, optional `fraiseql_rs` acceleration
✅ **Observability** - Prometheus, OpenTelemetry, structured logging
✅ **Scalability** - HPA, load balancing, multi-region ready
✅ **Compliance** - Audit logging, security headers, standards-compliant
✅ **Disaster recovery** - Backup/restore procedures, replication

Start with the standard Kubernetes deployment template and scale to multi-region as needed.

---

## See Also

- **[Performance Tuning Runbook](../operations/performance-tuning-runbook.md)** - Day-2 operations and tuning
- **[Monitoring & Observability Guide](./monitoring.md)** - Setting up Prometheus, Grafana, and OpenTelemetry
- **[Security Checklist](../integrations/authentication/security-checklist.md)** - Pre-production security verification
- **[Troubleshooting Guide](./troubleshooting.md)** - Common production issues and solutions
- **[Scaling Guide](./README.md)** - Horizontal and vertical scaling strategies

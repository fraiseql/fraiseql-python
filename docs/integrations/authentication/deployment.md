---
title: FraiseQL Authentication Deployment Guide
description: Production deployment guide for FraiseQL's authentication system.
keywords: ["framework", "python", "fastapi", "postgresql", "authentication"]
tags: ["documentation", "reference"]
---

# FraiseQL Authentication Deployment Guide

Production deployment guide for FraiseQL's authentication system.

FraiseQL is a Python runtime GraphQL framework served over FastAPI. Authentication
runs **inside the FastAPI app** (pure Python) — there is no separate auth server and
no compile step. You deploy a standard Python ASGI application and configure auth
through `FraiseQLConfig` / `FRAISEQL_`-prefixed environment variables.

## Prerequisites

**Required Knowledge:**

- OAuth 2.0 / OIDC and JWT validation
- Containerization (Docker) and your orchestrator (Kubernetes, ECS, etc.)
- Python application packaging and ASGI servers (uvicorn / gunicorn)
- SSL/TLS certificate management
- PostgreSQL administration and backups
- Load balancing and reverse proxy configuration
- Security best practices and compliance

**Required Software:**

- FraiseQL (latest stable release) and Python 3.13+
- `uvicorn` (and optionally `gunicorn` for multi-worker process management)
- Docker 20.10+ (and Docker Compose 2+) or your container runtime
- Kubernetes 1.24+ (kubectl configured), if deploying to Kubernetes
- PostgreSQL 14+ database
- OpenSSL or a certificate management tool
- Nginx or another reverse proxy (optional)

**Required Infrastructure:**

- A container host or orchestrator (for deployment)
- PostgreSQL 14+ database (primary + replica for HA)
- An OIDC/JWT issuer for production auth (Auth0, or any issuer you front with Auth0
  or validate with a custom `AuthProvider`)
- Domain with DNS setup
- SSL/TLS certificate (Let's Encrypt, commercial CA, or internal)
- Load balancer or Ingress controller
- Persistent storage for the database
- Backup storage system

**Optional but Recommended:**

- Kubernetes cert-manager for automatic certificate renewal
- Container registry (Docker Hub, ECR, GCR, etc.)
- A secrets management system (HashiCorp Vault, AWS Secrets Manager, GCP Secret Manager)
- Monitoring, alerting, and log aggregation infrastructure
- Disaster recovery and backup testing
- Autoscaling configuration

**Time Estimate:** 2-4 hours for a Kubernetes deployment, 1-2 hours for Docker Compose.

## Pre-Deployment Checklist

- [ ] Auth provider (Auth0 or custom JWT issuer) configured
- [ ] Database schema and migrations applied
- [ ] SSL/TLS certificates installed
- [ ] `FRAISEQL_` environment variables configured (secrets via secret manager)
- [ ] Token revocation store selected (`PostgreSQLRevocationStore` for production)
- [ ] Monitoring and logging configured
- [ ] Backup strategy defined
- [ ] Security audit completed
- [ ] Load testing performed
- [ ] Runbook created

## Environment Configuration

All FraiseQL settings can be supplied as environment variables prefixed with
`FRAISEQL_`. They map directly onto fields of `FraiseQLConfig`
(`src/fraiseql/fastapi/config.py`), e.g. `FRAISEQL_AUTH_PROVIDER` →
`auth_provider`, `FRAISEQL_AUTH0_DOMAIN` → `auth0_domain`.

### Production Environment Variables

```bash
# Database (PostgreSQL only)
FRAISEQL_DATABASE_URL=postgresql://fraiseql_app:strong_password@prod-db.internal:5432/fraiseql
FRAISEQL_DATABASE_POOL_SIZE=20
FRAISEQL_DATABASE_POOL_RECYCLE=1800

# Environment (disables playground/introspection automatically)
FRAISEQL_ENVIRONMENT=production

# Authentication
FRAISEQL_AUTH_ENABLED=true
FRAISEQL_AUTH_PROVIDER=auth0            # auth0 | custom | none

# Auth0 settings (when FRAISEQL_AUTH_PROVIDER=auth0)
FRAISEQL_AUTH0_DOMAIN=myapp.auth0.com
FRAISEQL_AUTH0_API_IDENTIFIER=https://api.yourdomain.com
# FRAISEQL_AUTH0_ALGORITHMS=["RS256"]   # defaults to RS256

# Token revocation
FRAISEQL_REVOCATION_ENABLED=true
FRAISEQL_REVOCATION_CHECK_ENABLED=true
FRAISEQL_REVOCATION_TTL=86400

# Server (uvicorn / gunicorn) — standard ASGI server settings
PORT=8000
```

When `FRAISEQL_AUTH_PROVIDER=auth0`, FraiseQL auto-creates an `Auth0Provider` from
`auth0_domain` / `auth0_api_identifier` at startup — you do not write provider code.
For any other OIDC issuer (Google, Keycloak, etc.), either front it with Auth0 or set
`FRAISEQL_AUTH_PROVIDER=custom` and supply an `AuthProvider` subclass that validates
that issuer's JWTs via its JWKS/issuer/audience.

> **Secrets:** never bake credentials into the image. Inject `FRAISEQL_DATABASE_URL`
> and any provider secrets at runtime from your platform's secret manager
> (Kubernetes Secrets, Vault, AWS/GCP Secrets Manager). The values above show shape,
> not real secrets.

### .env file

For non-container hosts, FraiseQL loads a `.env` file automatically (pydantic-settings):

```bash
# Load deployment secrets into the process environment
source /etc/fraiseql/auth.env

# Verify critical variables (avoid printing secret values)
echo "Auth provider: $FRAISEQL_AUTH_PROVIDER"
echo "Auth0 domain:  $FRAISEQL_AUTH0_DOMAIN"
echo "Environment:   $FRAISEQL_ENVIRONMENT"
```

## Database Setup

### 1. Create Database

```bash
# On the PostgreSQL server
sudo -u postgres psql

CREATE DATABASE fraiseql;
CREATE USER fraiseql_app WITH PASSWORD 'strong_password_here';
ALTER ROLE fraiseql_app SET client_encoding TO 'utf8';
ALTER ROLE fraiseql_app SET default_transaction_isolation TO 'read committed';
ALTER ROLE fraiseql_app SET timezone TO 'UTC';

GRANT ALL PRIVILEGES ON DATABASE fraiseql TO fraiseql_app;

\c fraiseql
GRANT ALL PRIVILEGES ON SCHEMA public TO fraiseql_app;
```

### 2. Token Revocation Table

In production, use `PostgreSQLRevocationStore`
(`src/fraiseql/auth/token_revocation.py`) so revocations survive restarts and are
shared across instances. The store creates and manages its own table
(default name `tb_token_revocation`) on first use:

```python
from psycopg_pool import AsyncConnectionPool

from fraiseql.auth.token_revocation import PostgreSQLRevocationStore

pool = AsyncConnectionPool(conninfo="postgresql://...")
revocation_store = PostgreSQLRevocationStore(pool, table_name="tb_token_revocation")
# The table is created lazily on first revocation/check.
```

The in-memory store (`InMemoryRevocationStore`) is for development/testing only —
revocations are lost on restart and are not shared between processes.

### 3. Verify Connection

```bash
export FRAISEQL_DATABASE_URL="postgresql://fraiseql_app:strong_password_here@prod-db.internal:5432/fraiseql"
psql "$FRAISEQL_DATABASE_URL" -c "SELECT 1;"
```

## Docker Deployment

FraiseQL is a Python package — the image installs `fraiseql` and runs the FastAPI
app with an ASGI server. The optional `fraiseql-rs` acceleration ships as a prebuilt
wheel, so **no Rust toolchain and no compile step are needed**.

### Dockerfile

```dockerfile
FROM python:3.13-slim

# libpq is needed by psycopg at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install FraiseQL (prebuilt wheels — no build step)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Your application code (types, queries, mutations, the FastAPI app object)
COPY app/ ./app/

EXPOSE 8000

# Run the ASGI app with multiple workers via gunicorn + uvicorn workers.
CMD ["gunicorn", "app.main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-w", "4", "-b", "0.0.0.0:8000"]
```

`requirements.txt` pins `fraiseql` (and `fraiseql-rs` for the acceleration wheel).
For a single worker (or local development) you can run `uvicorn app.main:app --host 0.0.0.0 --port 8000` instead.

> `app.main:app` refers to the FastAPI app returned by `create_fraiseql_app(...)`
> in your `app/main.py`. Auth is configured there (or via `FRAISEQL_` env vars).

### Docker Compose Production

```yaml
services:
  fraiseql:
    build: .
    container_name: fraiseql-auth
    restart: always
    environment:
      FRAISEQL_DATABASE_URL: ${FRAISEQL_DATABASE_URL}
      FRAISEQL_ENVIRONMENT: production
      FRAISEQL_AUTH_ENABLED: "true"
      FRAISEQL_AUTH_PROVIDER: auth0
      FRAISEQL_AUTH0_DOMAIN: ${FRAISEQL_AUTH0_DOMAIN}
      FRAISEQL_AUTH0_API_IDENTIFIER: ${FRAISEQL_AUTH0_API_IDENTIFIER}
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  postgres:
    image: postgres:15-alpine
    container_name: fraiseql-db
    restart: always
    environment:
      POSTGRES_DB: fraiseql
      POSTGRES_USER: fraiseql_app
      POSTGRES_PASSWORD: ${DATABASE_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U fraiseql_app"]
      interval: 10s
      timeout: 5s
      retries: 5

  nginx:
    image: nginx:alpine
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on:
      - fraiseql

volumes:
  postgres_data:
```

## Nginx Configuration

FraiseQL serves GraphQL at `/graphql` and exposes `/health` (liveness) and
`/ready` (readiness) probes. Put TLS termination and rate limiting at the proxy.

```nginx
upstream fraiseql {
    server fraiseql:8000;
}

# Rate-limit zones (declared at http context in your nginx.conf)
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
limit_req_zone $binary_remote_addr zone=auth_limit:10m rate=1r/s;

server {
    listen 80;
    server_name api.yourdomain.com;

    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-XSS-Protection "1; mode=block" always;

    location /graphql {
        limit_req zone=api_limit burst=20;
        proxy_pass http://fraiseql;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location ~ ^/(health|ready)$ {
        access_log off;
        proxy_pass http://fraiseql;
    }
}
```

> Apply a stricter `auth_limit` zone to any native-auth login routes you expose
> (from `fraiseql.auth.native`'s FastAPI router) if you use the native provider.

## SSL/TLS Setup

### Using Let's Encrypt

```bash
# Install certbot
sudo apt-get install certbot python3-certbot-nginx

# Get certificate
sudo certbot certonly --standalone -d api.yourdomain.com

# Auto-renewal
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer

# Verify renewal
sudo certbot renew --dry-run
```

For PostgreSQL connection security (TLS + SCRAM-SHA-256), configure `pg_hba.conf`
and add `?sslmode=require` to your `FRAISEQL_DATABASE_URL`.

## Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fraiseql
  labels:
    app: fraiseql
spec:
  replicas: 3
  selector:
    matchLabels:
      app: fraiseql
  template:
    metadata:
      labels:
        app: fraiseql
    spec:
      containers:
      - name: fraiseql
        image: your-registry/fraiseql:latest
        ports:
        - containerPort: 8000
        env:
        - name: FRAISEQL_ENVIRONMENT
          value: production
        - name: FRAISEQL_AUTH_PROVIDER
          value: auth0
        - name: FRAISEQL_DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: fraiseql-secrets
              key: database-url
        - name: FRAISEQL_AUTH0_DOMAIN
          valueFrom:
            secretKeyRef:
              name: fraiseql-secrets
              key: auth0-domain
        - name: FRAISEQL_AUTH0_API_IDENTIFIER
          valueFrom:
            secretKeyRef:
              name: fraiseql-secrets
              key: auth0-api-identifier
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
---
apiVersion: v1
kind: Service
metadata:
  name: fraiseql
spec:
  selector:
    app: fraiseql
  type: ClusterIP
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: fraiseql
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: fraiseql
  minReplicas: 3
  maxReplicas: 10
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
```

## Monitoring Setup

### Prometheus Configuration

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'fraiseql'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
```

Use the `/health` and `/ready` endpoints for liveness/readiness, and your standard
ASGI/FastAPI metrics for latency and error-rate dashboards.

## Backup Strategy

### Database Backups

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/backups/fraiseql"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DB_NAME="fraiseql"

mkdir -p "$BACKUP_DIR"

# Full backup
pg_dump -h "$DB_HOST" -U fraiseql_app "$DB_NAME" | \
  gzip > "$BACKUP_DIR/fraiseql_$TIMESTAMP.sql.gz"

# Keep only last 30 days
find "$BACKUP_DIR" -name "fraiseql_*.sql.gz" -mtime +30 -delete

# Upload to S3
aws s3 cp "$BACKUP_DIR/fraiseql_$TIMESTAMP.sql.gz" \
  s3://fraiseql-backups/
```

Schedule with cron:

```bash
# Run daily at 2 AM
0 2 * * * /scripts/backup.sh
```

### Restore from Backup

```bash
gunzip -c fraiseql_20260121_020000.sql.gz | \
  psql -h prod-db.internal -U fraiseql_app fraiseql
```

## Scaling

### Horizontal Scaling

- Run multiple FraiseQL app instances behind a load balancer.
- Each instance connects to the same PostgreSQL database.
- Use `PostgreSQLRevocationStore` so token revocations are shared across instances.
- The app is stateless (auth state lives in JWTs + PostgreSQL), so scaling is simple.
- Within a single instance, run multiple worker processes via
  `gunicorn -k uvicorn.workers.UvicornWorker -w N`.

### Vertical Scaling

Adjust resource limits, for example in Kubernetes:

```bash
kubectl set resources deployment fraiseql \
  --limits=memory=1Gi,cpu=1000m \
  --requests=memory=512Mi,cpu=500m
```

## Performance Tuning

### PostgreSQL Connection Pool

Tune the pool via `FraiseQLConfig` / env vars:

```bash
FRAISEQL_DATABASE_POOL_SIZE=50
FRAISEQL_DATABASE_MAX_OVERFLOW=20
FRAISEQL_DATABASE_POOL_RECYCLE=1800
```

### JWKS Caching

When using Auth0 (or any JWKS-based issuer), the provider fetches and caches the
issuer's signing keys (JWKS) so per-request token validation does not hit the issuer
every time. Keep the app reachable to the issuer's `.well-known/jwks.json` endpoint,
and allow outbound egress from your pods/containers to the issuer. Cached keys are
refreshed automatically when an unknown key ID is seen (e.g. after key rotation).

## High Availability

### Multi-Region Setup

```text
Region 1: Primary database
Region 2: Read replica
Region 3: Standby replica

Failover: managed PostgreSQL service or your replication tooling
```

Because auth runs inside each stateless app instance and revocations live in
PostgreSQL, app-tier HA is just "run more replicas across zones". Database HA is the
critical piece — use a primary + replica with automated failover.

### Disaster Recovery

- RPO (Recovery Point Objective): 5 minutes
- RTO (Recovery Time Objective): 15 minutes
- Test failover monthly

## Cost Optimization

**Development**:

- Single app instance / single worker
- Shared database
- In-memory revocation store

**Production**:

- 3x app instances (HA), multiple workers each
- Managed PostgreSQL (primary + replica)
- `PostgreSQLRevocationStore`, monitoring, and backups

## Monitoring Dashboard

Key metrics to monitor:

1. **Availability**: % uptime (target: 99.9%)
2. **Latency**: p50, p95, p99 (target: <100ms)
3. **Errors**: error rate (target: <1%)
4. **Capacity**: CPU, memory, database connections

## Troubleshooting

### App Won't Start

```bash
# Check logs
docker logs fraiseql

# Check database connection
psql "$FRAISEQL_DATABASE_URL" -c "SELECT 1"

# Check the auth issuer is reachable (Auth0 example)
curl "https://${FRAISEQL_AUTH0_DOMAIN}/.well-known/openid-configuration"
```

A missing `auth0_domain`/`auth0_api_identifier` with `FRAISEQL_AUTH_PROVIDER=auth0`
raises a configuration error at startup — set both env vars.

### High Latency

```sql
-- Check database slow queries (requires pg_stat_statements)
SELECT * FROM pg_stat_statements ORDER BY total_exec_time DESC;
```

```bash
# Check auth issuer latency (Auth0 example)
time curl "https://${FRAISEQL_AUTH0_DOMAIN}/.well-known/jwks.json"
```

### Database Connection Pool Exhausted

```bash
# Increase pool size
FRAISEQL_DATABASE_POOL_SIZE=100
```

```sql
-- Check active connections
SELECT count(*) FROM pg_stat_activity;
```

### Access Denied

Denied operations surface as a GraphQL error with
`extensions.code = "FORBIDDEN"` (not an HTTP 4xx). Check the user's roles/permissions
in the JWT and the `@requires_permission` / `@requires_role` / `Authorizer` rules on
the affected operations.

## See Also

- [Monitoring Guide](./monitoring.md)
- [Security Checklist](./security-checklist.md)
- [Troubleshooting](./troubleshooting.md)

---

**Next Step**: Deploy to production and monitor performance.

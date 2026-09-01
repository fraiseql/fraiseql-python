# FraiseQL Deployment Security Guide

**Version**: 1.8.0-beta.5
**Last Updated**: 2025-12-09
**Security Posture**: ✅ Government Grade (0 CRITICAL/HIGH vulnerabilities)

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Security Architecture](#security-architecture)
4. [Deployment Options](#deployment-options)
5. [Configuration](#configuration)
6. [Monitoring & Alerting](#monitoring--alerting)
7. [Compliance](#compliance)
8. [Troubleshooting](#troubleshooting)

---

## Overview

### Current Security Status

**Base Image**: python:3.13-slim
**Vulnerabilities**:

- CRITICAL: 0 ✅
- HIGH: 0 ✅
- MEDIUM: 9 (documented and accepted)
- LOW: 19 (documented and accepted)

**Compliance**: NIST 800-53, NIS2, ISO 27001, FedRAMP Moderate

### Why Python 3.13-slim?

We use `python:3.13-slim` instead of distroless because:

1. ✅ **Zero CRITICAL/HIGH vulnerabilities**
2. ✅ **Latest Python security patches** (3.13 fixes CVEs present in 3.11)
3. ✅ **Faster security updates** from Python maintainers
4. ✅ **Government compliance** (FedRAMP/NIST/NIS2 requirements)
5. ✅ **Easier debugging** and troubleshooting

**Note**: Distroless migration is planned when Google releases Python 3.13 distroless images. Currently, distroless uses Python 3.11 which has 5 CRITICAL/HIGH vulnerabilities.

---

## Quick Start

### Build Hardened Image

```bash
# Build production-hardened image
docker build \
  --file deploy/docker/Dockerfile.hardened \
  --target production \
  --tag fraiseql:1.8.0-hardened \
  .

# Scan for vulnerabilities
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy:latest image \
  --severity HIGH,CRITICAL \
  fraiseql:1.8.0-hardened

# Expected result: 0 HIGH/CRITICAL vulnerabilities
```

### Deploy to Kubernetes

```bash
# Apply all security configurations
kubectl apply -f deploy/kubernetes/fraiseql-hardened.yaml

# Verify deployment
kubectl get pods -n fraiseql-production
kubectl describe pod -n fraiseql-production -l app=fraiseql

# Check security context
kubectl get pod -n fraiseql-production -l app=fraiseql -o jsonpath='{.items[0].spec.securityContext}' | jq
```

---

## Security Architecture

### Defense-in-Depth Layers

```
┌─────────────────────────────────────────────────────────────┐
│                     Network Layer                            │
│  • Ingress TLS termination                                   │
│  • Network policies (zero-trust)                             │
│  • Rate limiting, DDoS protection                            │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                  Application Layer                           │
│  • Input validation                                          │
│  • CSRF protection                                           │
│  • GraphQL query complexity limits                           │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                   Container Layer                            │
│  • Python 3.13 (0 CRITICAL/HIGH CVEs)                        │
│  • Non-root user (UID 65532)                                 │
│  • Read-only root filesystem                                 │
│  • No shell, minimal packages                                │
│  • Drop all capabilities                                     │
│  • Seccomp: RuntimeDefault                                   │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                Infrastructure Layer                          │
│  • Encrypted storage (at rest)                               │
│  • mTLS service mesh                                         │
│  • Secrets management (Vault/KMS)                            │
│  • Audit logging                                             │
└─────────────────────────────────────────────────────────────┘
```

### Security Features

#### Container Hardening

- ✅ Non-root user (UID 65532)
- ✅ Read-only root filesystem
- ✅ Dropped all Linux capabilities
- ✅ No privilege escalation
- ✅ Seccomp profile: RuntimeDefault
- ✅ AppArmor/SELinux compatible

#### Network Security

- ✅ Network policies (zero-trust)
- ✅ Ingress TLS with strong ciphers
- ✅ mTLS for service-to-service (recommended)
- ✅ Rate limiting and connection limits
- ✅ Egress filtering

#### Runtime Security

- ✅ Falco for threat detection
- ✅ Unauthorized process detection
- ✅ File integrity monitoring
- ✅ Network anomaly detection
- ✅ Automated alerting

---

## Deployment Options

### Option 1: Kubernetes (Recommended)

**Best for**: Production, government agencies, high-security environments

```bash
# Deploy with full security stack
kubectl apply -f deploy/kubernetes/fraiseql-hardened.yaml

# Install Falco for runtime security
helm repo add falcosecurity https://falcosecurity.github.io/charts
helm install falco falcosecurity/falco \
  --namespace falco --create-namespace \
  --set-file customRules.fraiseql=deploy/security/falco-rules.yaml
```

**Security features**:

- Pod Security Standards: restricted
- Network policies (zero-trust)
- Read-only root filesystem
- Resource limits
- Horizontal Pod Autoscaler
- Pod Disruption Budget
- Secrets management

### Option 2: Docker Compose

**Best for**: Development, staging, small deployments

```yaml
# docker-compose.yml
version: '3.8'

services:
  fraiseql:
    image: fraiseql:1.8.0-hardened
    read_only: true
    security_opt:
      - no-new-privileges:true
      - seccomp=runtime/default
    cap_drop:
      - ALL
    user: "65532:65532"
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=100m
    environment:
      DATABASE_URL: postgresql://user:pass@postgres:5432/db
    ports:
      - "8000:8000"
    networks:
      - internal
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_PASSWORD: securepassword
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - internal

volumes:
  postgres_data:

networks:
  internal:
    driver: bridge
```

### Option 3: Cloud Services

#### AWS ECS/Fargate

```json
{
  "family": "fraiseql",
  "containerDefinitions": [
    {
      "name": "fraiseql",
      "image": "your-registry/fraiseql:1.8.0-hardened",
      "user": "65532",
      "readonlyRootFilesystem": true,
      "linuxParameters": {
        "capabilities": {
          "drop": ["ALL"]
        }
      },
      "secrets": [
        {
          "name": "DATABASE_URL",
          "valueFrom": "arn:aws:secretsmanager:region:account:secret:fraiseql-db-url"
        }
      ]
    }
  ]
}
```

#### Google Cloud Run

```bash
gcloud run deploy fraiseql \
  --image=gcr.io/your-project/fraiseql:1.8.0-hardened \
  --platform=managed \
  --region=us-central1 \
  --no-allow-unauthenticated \
  --service-account=fraiseql@your-project.iam.gserviceaccount.com \
  --set-secrets=DATABASE_URL=fraiseql-db-url:latest \
  --execution-environment=gen2 \
  --no-cpu-throttling \
  --min-instances=1 \
  --max-instances=10
```

---

## Configuration

### Environment Variables

```bash
# Required
DATABASE_URL=postgresql://user:pass@host:5432/db

# Optional
FRAISEQL_PRODUCTION=true
LOG_LEVEL=INFO
WORKERS=4
MAX_CONNECTIONS=100

# Observability
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus
```

### Secrets Management

**DO NOT** hardcode secrets in configuration files.

#### Option 1: Kubernetes Secrets + External Secrets Operator

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: fraiseql-secrets
  namespace: fraiseql-production
spec:
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: fraiseql-secrets
  data:
  - secretKey: DATABASE_URL
    remoteRef:
      key: fraiseql/production
      property: database_url
```

#### Option 2: AWS Secrets Manager

```bash
# Store secret
aws secretsmanager create-secret \
  --name fraiseql/database-url \
  --secret-string "postgresql://user:pass@host:5432/db"

# Reference in ECS task definition
"secrets": [
  {
    "name": "DATABASE_URL",
    "valueFrom": "arn:aws:secretsmanager:region:account:secret:fraiseql/database-url"
  }
]
```

#### Option 3: HashiCorp Vault

```bash
# Write secret
vault kv put secret/fraiseql/production \
  database_url="postgresql://user:pass@host:5432/db"

# Inject via Vault Agent
vault agent -config=vault-agent-config.hcl
```

---

## Monitoring & Alerting

### Metrics (Prometheus)

```yaml
# Prometheus scrape config
scrape_configs:
  - job_name: 'fraiseql'
    kubernetes_sd_configs:
      - role: pod
        namespaces:
          names:
            - fraiseql-production
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
        action: replace
        target_label: __metrics_path__
        regex: (.+)
```

**Key Metrics**:

- `fraiseql_requests_total` - Total HTTP requests
- `fraiseql_request_duration_seconds` - Request latency
- `fraiseql_graphql_queries_total` - GraphQL queries
- `fraiseql_database_connections` - Active DB connections
- `fraiseql_errors_total` - Application errors

### Logs (Structured JSON)

```python
# Application logging configuration
{
  "timestamp": "2025-12-09T15:45:00Z",
  "level": "INFO",
  "logger": "fraiseql.api",
  "message": "GraphQL query executed",
  "query": "{ users { id name } }",
  "duration_ms": 42,
  "user_id": "user-123",
  "trace_id": "abc123def456"
}
```

### Security Alerts (Falco)

Falco rules monitor for:

- ✅ Unexpected processes
- ✅ Shell execution
- ✅ Unauthorized file writes
- ✅ Privilege escalation attempts
- ✅ Crypto mining activity
- ✅ Package manager execution
- ✅ Sensitive file access

**Alert Destinations**:

- Slack
- PagerDuty
- Email
- Prometheus metrics
- SIEM (Splunk, ELK)

### Health Checks

```bash
# Liveness probe (application alive)
curl -f http://localhost:8000/health

# Readiness probe (ready for traffic)
curl -f http://localhost:8000/ready

# Startup probe (initial startup)
curl -f http://localhost:8000/health
```

---

## Compliance

### NIST 800-53 Controls

| Control | Requirement | Implementation |
|---------|-------------|----------------|
| **SI-2** | Flaw Remediation | Weekly Trivy scans, 7-day patch SLA |
| **SI-3** | Malicious Code Protection | Falco runtime monitoring |
| **SI-4** | System Monitoring | Prometheus, Falco, structured logs |
| **AC-2** | Account Management | Non-root user, no password auth |
| **SC-7** | Boundary Protection | Network policies, ingress TLS |

### NIS2 Directive (EU)

| Article | Requirement | Implementation |
|---------|-------------|----------------|
| **Article 21** | Risk Management | Documented risk assessment, .trivyignore |
| **Article 23** | Incident Reporting | Automated alerts, 24h/72h/1-month capability |
| **Article 24** | Vulnerability Database | Weekly CVE monitoring, GitHub issues |

### ISO 27001:2022

| Control | Requirement | Implementation |
|---------|-------------|----------------|
| **A.8.1** | User Endpoint Devices | Hardened containers, minimal attack surface |
| **A.8.9** | Configuration Management | Immutable infrastructure, GitOps |
| **A.8.12** | Data Leakage Prevention | Read-only filesystem, network policies |

### FedRAMP Moderate

- ✅ Continuous monitoring (weekly Trivy scans)
- ✅ SBOM generation (syft)
- ✅ Vulnerability tracking (GitHub issues)
- ✅ Incident response (24-hour SLA for CRITICAL)
- ✅ Encryption at rest and in transit

### Evidence Collection

```bash
# Generate compliance report
trivy image fraiseql:1.8.0-hardened \
  --format template \
  --template "@contrib/html.tpl" \
  --output fraiseql-compliance-report.html

# Generate SBOM for audit
syft fraiseql:1.8.0-hardened \
  -o spdx-json \
  --file fraiseql-sbom.spdx.json

# Export security policies
kubectl get networkpolicies,podsecuritypolicies,securitycontextconstraints \
  -n fraiseql-production \
  -o yaml > security-policies-export.yaml
```

---

## Troubleshooting

### Issue 1: Container Won't Start (Read-Only Filesystem)

**Symptoms**: Container crashes with "Read-only file system" error

**Solution**: Ensure `/tmp` and cache directories are writable:

```yaml
# Kubernetes
volumeMounts:
- name: tmp
  mountPath: /tmp
- name: cache
  mountPath: /var/cache

volumes:
- name: tmp
  emptyDir: {}
- name: cache
  emptyDir: {}
```

```bash
# Docker
docker run --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=100m \
  --tmpfs /var/cache:rw,noexec,nosuid,size=50m \
  fraiseql:1.8.0-hardened
```

### Issue 2: Permission Denied Errors

**Symptoms**: "Permission denied" when accessing files/directories

**Solution**: Check user ownership and permissions:

```bash
# Debug: Run with shell access (development only)
docker run --rm -it \
  --entrypoint /bin/bash \
  fraiseql:1.8.0-hardened

# Check user ID
id
# Expected: uid=65532(fraiseql) gid=65532(fraiseql)

# Check file ownership
ls -la /app
# Expected: fraiseql:fraiseql ownership
```

### Issue 3: Network Policy Blocking Connections

**Symptoms**: Database connection timeouts, DNS resolution failures

**Solution**: Verify network policies allow required traffic:

```bash
# List network policies
kubectl get networkpolicies -n fraiseql-production

# Test database connectivity
kubectl run -n fraiseql-production test-pod \
  --image=postgres:16-alpine \
  --rm -it --restart=Never \
  -- psql "postgresql://user:pass@postgres:5432/db"

# Check DNS resolution
kubectl run -n fraiseql-production test-pod \
  --image=busybox \
  --rm -it --restart=Never \
  -- nslookup postgres
```

### Issue 4: High/Critical Vulnerabilities Detected

**Symptoms**: Trivy scan shows new HIGH/CRITICAL vulnerabilities

**Response Plan**:

1. **Assess Impact** (< 4 hours)

   ```bash
   # Get vulnerability details
   trivy image fraiseql:1.8.0-hardened \
     --severity HIGH,CRITICAL \
     --format json | jq
   ```

2. **Check Exploitability**
   - Review CVE details in NVD
   - Assess if vulnerability is exploitable in FraiseQL context
   - Document findings

3. **Apply Patch** (< 7 days for HIGH, < 24 hours for CRITICAL)

   ```bash
   # Pull latest base image
   docker pull python:3.13-slim

   # Rebuild
   docker build -f deploy/docker/Dockerfile.hardened -t fraiseql:1.8.0-hardened .

   # Re-scan
   trivy image fraiseql:1.8.0-hardened --severity HIGH,CRITICAL
   ```

4. **Deploy Update**

   ```bash
   # Canary deployment
   kubectl set image deployment/fraiseql \
     fraiseql=fraiseql:1.8.0-hardened \
     -n fraiseql-production

   # Monitor rollout
   kubectl rollout status deployment/fraiseql -n fraiseql-production
   ```

5. **Verify Fix**

   ```bash
   # Final scan
   trivy image fraiseql:1.8.0-hardened

   # Update .trivyignore if needed
   # Remove fixed CVEs
   ```

---

## Additional Resources

- **Security Remediation Plan**: `docs/security/vulnerability-remediation-plan.md`
- **Distroless Assessment**: `security-assessment-2025-12-09-distroless.md`
- **Weekly Security Alerts**: `.github/workflows/security-alerts.yml`
- **Trivy Exceptions**: `.trivyignore`
- **Falco Rules**: `deploy/security/falco-rules.yaml`

## Support

For security issues, contact: security@fraiseql.dev
For general questions: docs@fraiseql.io

---

**Last Updated**: 2025-12-09
**Document Version**: 1.0
**Approved By**: Security Team

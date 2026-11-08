# Production Deployment Checklist

**Version:** 1.0
**Last Updated:** 2025-12-08
**Audience:** DevOps engineers, platform engineers, SREs
**Time to Complete:** 1-3 hours (depending on profile)

---

## Overview

This comprehensive checklist ensures your FraiseQL application is production-ready before launch. Complete all relevant items for your security profile (STANDARD, REGULATED, or RESTRICTED) before deploying.

**Checklist Sections:**

1. [Pre-Deployment Planning](#1-pre-deployment-planning)
2. [Security & Compliance](#2-security--compliance)
3. [Database Configuration](#3-database-configuration)
4. [Application Configuration](#4-application-configuration)
5. [Observability & Monitoring](#5-observability--monitoring)
6. [Performance Optimization](#6-performance-optimization)
7. [Deployment Infrastructure](#7-deployment-infrastructure)
8. [Incident Readiness](#8-incident-readiness)
9. [Post-Deployment Validation](#9-post-deployment-validation)
10. [Final Go/No-Go Decision](#10-final-gono-go-decision)

**Profile-Specific Requirements:**

- 🟢 **STANDARD**: Basic production requirements
- 🟡 **REGULATED**: + Compliance and audit requirements
- 🔴 **RESTRICTED**: + High-security and cryptographic requirements

---

## 1. Pre-Deployment Planning

### 1.1 Requirements Definition

- [ ] **Business Requirements Documented**
  - Expected traffic volume (requests/day, peak load)
  - Availability target (uptime percentage, SLA)
  - Data retention requirements
  - Compliance requirements identified

- [ ] **Technical Requirements Documented**
  - Infrastructure capacity (CPU, memory, storage)
  - Network topology (VPC, subnets, security groups)
  - Backup and recovery strategy (RPO, RTO targets)
  - Disaster recovery plan

- [ ] **Security Profile Selected**
  - STANDARD, REGULATED, or RESTRICTED chosen
  - Decision documented with justification

**Verification:**

```bash
# Document answers to these questions
echo "Expected peak traffic: ______ requests/second"
echo "Uptime target: ______ % (e.g., 99.9% = 8.76h downtime/year)"
echo "Backup RPO: ______ (max data loss acceptable)"
echo "Backup RTO: ______ (max recovery time acceptable)"
echo "Security Profile: ______ (STANDARD/REGULATED/RESTRICTED)"
```

---

## 2. Security & Compliance

### 2.1 Security Profile Configuration

- [ ] 🟢 **Security Profile Configured**

  `create_fraiseql_app` takes no security profile. Apply the profile's settings
  yourself: its introspection policy through `FraiseQLConfig`, and its body-size and
  rate limits with the middleware (see the note under STANDARD Profile in
  [Security & Compliance](../specs/security-compliance.md#standard-profile-default)):

  ```python
  from fraiseql.middleware import (
      BodySizeLimiterMiddleware,
      InMemoryRateLimiter,
      RateLimiterMiddleware,
  )
  from fraiseql.security.profiles import ProfileEnforcer, get_profile

  profile = get_profile("regulated")  # "standard" / "regulated" / "restricted"
  enforcer = ProfileEnforcer(profile)
  app.add_middleware(BodySizeLimiterMiddleware, config=enforcer.get_body_size_config())
  app.add_middleware(
      RateLimiterMiddleware,
      rate_limiter=InMemoryRateLimiter(enforcer.get_rate_limit_config()),
  )
  ```

- [ ] 🟡 **Multi-Factor Authentication (MFA) Enabled** (REGULATED+)
  - External IdP integration configured (Auth0, Okta, Cognito)
  - MFA enforcement tested for all users
  - Backup authentication method configured

- [ ] 🔴 **Mutual TLS (mTLS) Configured** (RESTRICTED)
  - Client certificates generated and distributed
  - Server CA certificate configured
  - Certificate validation tested

**Verification:**

```bash
# Check security profile
fraiseql security audit

# Test MFA enforcement (REGULATED+)
curl -X POST https://api.yourapp.com/graphql \
  -H "Authorization: Bearer TOKEN_WITHOUT_MFA" \
  -d '{"query": "{ user { id } }"}' \
  # Should return 403 Forbidden

# Test mTLS (RESTRICTED)
curl --cert client.crt --key client.key --cacert ca.crt \
  https://api.yourapp.com/health
  # Should return 200 OK
```

### 2.2 TLS/HTTPS Configuration

- [ ] 🟢 **HTTPS Enforced** (all profiles)
  - Valid TLS certificate installed
  - HTTP → HTTPS redirect enabled
  - Certificate auto-renewal configured (Let's Encrypt or cert-manager)

- [ ] 🟢 **TLS Version Validated**
  - STANDARD/REGULATED: TLS 1.2+ only
  - RESTRICTED: TLS 1.3 only

- [ ] 🟡 **HSTS Headers Enabled** (REGULATED+)
  - `Strict-Transport-Security` header configured
  - Max-age set to 2 years (63072000 seconds)

**Verification:**

```bash
# Test HTTPS enforcement
curl -I http://api.yourapp.com
# Should return 301/308 redirect to https://

# Check TLS version
openssl s_client -connect api.yourapp.com:443 -tls1_2
# Should succeed for STANDARD/REGULATED

openssl s_client -connect api.yourapp.com:443 -tls1_3
# Should succeed for all profiles

# Check HSTS header (REGULATED+)
curl -I https://api.yourapp.com | grep -i strict-transport-security
# Expected: Strict-Transport-Security: max-age=63072000; includeSubDomains
```

### 2.3 Authentication & Authorization

- [ ] 🟢 **JWT Configuration Secured**
  - `JWT_SECRET_KEY` stored in secrets manager (never hardcoded)
  - Token expiration configured (60min STANDARD, 15min REGULATED, 5min RESTRICTED)
  - Refresh token rotation enabled

- [ ] 🟢 **Row-Level Security (RLS) Policies Created**
  - Tenant isolation policies implemented
  - User access policies defined and tested
  - Policy tests passing

- [ ] 🟢 **Field-Level Authorization Tested**
  - Sensitive fields protected (PII, PHI, payment data)
  - Authorization resolver tests passing

**Verification:**

```bash
# Check JWT secret is not hardcoded
grep -r "jwt_secret" app/ --exclude-dir=.git
# Should return no matches with actual secrets

# Test RLS policies
psql $DATABASE_URL -c "
  SET LOCAL app.current_user_id = 'user-123';
  SELECT COUNT(*) FROM v_order;
" # Should only return user-123's orders

# Test field-level auth
curl -X POST https://api.yourapp.com/graphql \
  -H "Authorization: Bearer USER_TOKEN" \
  -d '{"query": "{ user { ssn } }"}' \
  # Should return null or error for non-admin users
```

### 2.4 KMS Integration (REGULATED+ only)

- [ ] 🟡 **KMS Provider Configured** (REGULATED+)
  - Provider selected (AWS KMS, Azure Key Vault, GCP KMS, HashiCorp Vault)
  - Master key created and accessible
  - Key rotation policy configured (30 days REGULATED, 7 days RESTRICTED)

- [ ] 🔴 **HSM-Backed KMS** (RESTRICTED)
  - Hardware Security Module (HSM) provisioned
  - FIPS 140-2 Level 3 compliance verified
  - PKCS#11 integration tested

**Verification:**

```bash
# Test KMS connectivity (AWS example)
aws kms describe-key --key-id arn:aws:kms:region:account:key/key-id

# Test encryption/decryption
fraiseql kms test --provider aws

# Check key rotation schedule
aws kms get-key-rotation-status --key-id key-id
# Should show Enabled: true
```

### 2.5 Audit Logging

- [ ] 🟡 **Audit Logging Enabled** (REGULATED+)
  - Audit table created (`audit_events`)
  - Field-level access tracking enabled
  - Retention period configured (365 days REGULATED, 2555 days RESTRICTED)

- [ ] 🔴 **Cryptographic Audit Chain** (RESTRICTED)
  - Event hashing enabled (SHA-256)
  - HMAC chain integrity verification
  - Tamper-proof audit log tested

**Verification:**

```bash
# Check audit table exists
psql $DATABASE_URL -c "SELECT COUNT(*) FROM audit_events;"

# Test audit logging
curl -X POST https://api.yourapp.com/graphql \
  -H "Authorization: Bearer TOKEN" \
  -d '{"query": "mutation { updateUser(id: \"123\", name: \"Test\") { id } }"}'

# Verify event logged
psql $DATABASE_URL -c "
  SELECT event_type, user_id, created_at
  FROM audit_events
  ORDER BY created_at DESC
  LIMIT 1;
"

# Test cryptographic chain (RESTRICTED)
fraiseql audit verify-chain --from "2025-12-01" --to "2025-12-08"
# Should return: Chain integrity: VALID
```

### 2.6 Compliance Verification

- [ ] 🟡 **Compliance Framework Requirements Met** (REGULATED+)
  - Checklist completed for required framework(s)
  - Evidence documented for auditors

- [ ] 🟡 **SLSA Provenance Verified** (REGULATED+)
  - Software Bill of Materials (SBOM) generated
  - Provenance cryptographically signed

**Verification:**

```bash
# Generate compliance report
fraiseql compliance report --framework [iso27001|gdpr|hipaa|pci-dss|soc2]

# Verify SLSA provenance
gh attestation verify fraiseql-*.whl --owner fraiseql
```

---

## 3. Database Configuration

### 3.1 Connection Management

- [ ] 🟢 **Connection Pooling Configured**
  - Pool size: 20-50 connections (adjust based on traffic)
  - Max overflow: 10 connections
  - Pool timeout: 30 seconds
  - Pool recycle: 3600 seconds (1 hour)

- [ ] 🟢 **Connection String Secured**
  - Database credentials in secrets manager
  - SSL/TLS enabled for database connections
  - No credentials in code or config files

**Verification:**

```bash
# Check connection pool settings (if using pgBouncer)
psql -h pgbouncer-host -p 6432 -c "SHOW CONFIG;"

# Test connection pool exhaustion
ab -n 1000 -c 100 https://api.yourapp.com/health
# Should not see "connection pool exhausted" errors

# Verify SSL connection
psql "$DATABASE_URL?sslmode=require" -c "SELECT version();"
```

### 3.2 Database Schema

- [ ] 🟢 **Migrations Applied**
  - Latest migrations run on production database
  - Migration history table verified
  - No pending migrations

- [ ] 🟢 **Trinity Pattern Implemented**
  - Base tables (`tb_*`) created
  - Views (`v_*`) created for GraphQL access
  - Computed views (`tv_*`) created for complex queries

- [ ] 🟢 **Indexes Created**
  - Primary key indexes exist
  - Foreign key indexes created
  - Query-specific indexes for high-traffic tables
  - Vector indexes created (if using pgvector)

**Verification:**

```bash
# Check migrations
psql $DATABASE_URL -c "SELECT * FROM alembic_version;" # or your migration tool

# List all tables and views
psql $DATABASE_URL -c "
  SELECT schemaname, tablename, 'table' as type FROM pg_tables
  WHERE schemaname = 'public'
  UNION ALL
  SELECT schemaname, viewname, 'view' as type FROM pg_views
  WHERE schemaname = 'public'
  ORDER BY type, tablename;
"

# Check indexes
psql $DATABASE_URL -c "
  SELECT schemaname, tablename, indexname, indexdef
  FROM pg_indexes
  WHERE schemaname = 'public'
  ORDER BY tablename, indexname;
"

# Verify trinity pattern
psql $DATABASE_URL -c "
  SELECT COUNT(*) FROM pg_tables WHERE tablename LIKE 'tb_%';
  SELECT COUNT(*) FROM pg_views WHERE viewname LIKE 'v_%';
"
```

### 3.3 Backup & Recovery

- [ ] 🟢 **Automated Backups Configured**
  - Backup schedule defined (e.g., daily full + hourly incremental)
  - Backup retention policy set (30 days minimum)
  - Backup storage location secured and encrypted

- [ ] 🟢 **Backup Restoration Tested**
  - Test restore performed successfully
  - Restore time meets RTO target
  - Backup integrity verified

- [ ] 🟡 **Point-in-Time Recovery (PITR) Enabled** (REGULATED+)
  - WAL archiving configured
  - PITR tested successfully

**Verification:**

```bash
# Check backup schedule (AWS RDS example)
aws rds describe-db-instances --db-instance-identifier mydb \
  --query 'DBInstances[0].[BackupRetentionPeriod,PreferredBackupWindow]'

# List recent backups
aws rds describe-db-snapshots --db-instance-identifier mydb \
  --query 'DBSnapshots[*].[DBSnapshotIdentifier,SnapshotCreateTime]' \
  --output table

# Test restore (in staging)
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier mydb-restore-test \
  --db-snapshot-identifier mydb-snapshot-2025-12-08
```

### 3.4 Database Performance

- [ ] 🟢 **Query Performance Analyzed**
  - `pg_stat_statements` extension enabled
  - Slow queries identified and optimized
  - Query execution plans reviewed

- [ ] 🟢 **Database Monitoring Enabled**
  - Connection count monitored
  - Query latency tracked
  - Disk usage monitored

**Verification:**

```bash
# Check slow queries
psql $DATABASE_URL -c "
  SELECT query, calls, mean_exec_time, total_exec_time
  FROM pg_stat_statements
  ORDER BY mean_exec_time DESC
  LIMIT 10;
"

# Check database size
psql $DATABASE_URL -c "
  SELECT pg_size_pretty(pg_database_size(current_database()));
"

# Check connection count
psql $DATABASE_URL -c "
  SELECT count(*) FROM pg_stat_activity;
"
```

---

## 4. Application Configuration

### 4.1 Environment Variables

- [ ] 🟢 **Environment Variables Secured**
  - All secrets in secrets manager (AWS Secrets Manager, Vault, etc.)
  - No `.env` files in production containers
  - Environment-specific configs separated (dev/staging/prod)

- [ ] 🟢 **Required Variables Set**
  - `DATABASE_URL`
  - `JWT_SECRET_KEY`
  - `FRAISEQL_ENVIRONMENT=production`
  - Profile-specific variables (KMS keys, audit settings, etc.)

**Verification:**

```bash
# Check environment variables (in pod/container)
kubectl exec -it fraiseql-pod -- env | grep -E "DATABASE_URL|JWT_SECRET|FRAISEQL"

# Verify secrets not in image
docker history fraiseql:latest | grep -i secret
# Should return no matches
```

### 4.2 CORS Configuration

- [ ] 🟢 **CORS Configured for Production**
  - Only production domains allowed
  - No wildcard (`*`) origins in production
  - Credentials allowed only for trusted origins

**Verification:**

```bash
# Test CORS headers
curl -I https://api.yourapp.com/graphql \
  -H "Origin: https://app.yourapp.com"
# Should include: Access-Control-Allow-Origin: https://app.yourapp.com

# Test unauthorized origin
curl -I https://api.yourapp.com/graphql \
  -H "Origin: https://malicious.com"
# Should NOT include Access-Control-Allow-Origin header
```

### 4.3 Rate Limiting

- [ ] 🟢 **Rate Limiting Enabled**
  - STANDARD: 100 requests/minute
  - REGULATED: 50 requests/minute
  - RESTRICTED: 10 requests/minute

  - Off by default: `rate_limit_enabled=True` (`FRAISEQL_RATE_LIMIT_ENABLED=true`),
    `setup_rate_limiting(app)`, or the profile's middleware as in 2.1 (see
    [Rate Limiting](../configuration/rate-limiting.md))

- [ ] 🟢 **Rate Limit Storage Configured**
  - In-memory counts are per process: N workers allow N times the limit
  - Redis (`setup_rate_limiting(app, redis_client=...)`) for one count across instances

**Verification:**

```bash
# Test rate limiting (/health is never limited, so test /graphql)
for i in {1..101}; do
  curl -s -o /dev/null -w "%{http_code}\n" https://api.yourapp.com/graphql \
    -H "Content-Type: application/json" -d '{"query": "{ __typename }"}'
done
# Last requests should return 429 (Too Many Requests)
```

### 4.4 GraphQL Security

- [ ] 🟢 **Query Complexity Limits Configured**
  - Depth limit: 15 (STANDARD), 10 (REGULATED), 5 (RESTRICTED)
  - Complexity limit: 1000 (STANDARD/REGULATED), 500 (RESTRICTED)

- [ ] 🟡 **Introspection Disabled** (REGULATED+)
  - GraphQL introspection endpoint disabled in production

- [ ] 🟢 **Request Body Size Limited**
  - Max size: 1 MB (STANDARD/REGULATED), 512 KB (RESTRICTED)
  - `create_fraiseql_app` sets no limit: add `BodySizeLimiterMiddleware` (as in 2.1)
    or limit the body at the proxy (`client_max_body_size` in nginx)

**Verification:**

```bash
# Test query depth limit
curl -X POST https://api.yourapp.com/graphql \
  -d '{"query": "{ user { posts { comments { author { posts { ... } } } } } }"}'
# Should return error: "Query depth exceeds maximum"

# Test introspection disabled (REGULATED+)
curl -X POST https://api.yourapp.com/graphql \
  -d '{"query": "{ __schema { types { name } } }"}'
# Should return error: "Introspection is disabled"

# Test body size limit
dd if=/dev/zero bs=2M count=1 | curl -X POST https://api.yourapp.com/graphql \
  --data-binary @-
# Should return 413 (Payload Too Large)
```

---

## 5. Observability & Monitoring

### 5.1 Health Checks

- [ ] 🟢 **Health Endpoints Configured**
  - `/health` (liveness probe) - checks process health
  - `/ready` (readiness probe) - checks database connectivity
  - Health check interval: 30 seconds

**Verification:**

```bash
# Test liveness probe
curl http://api.yourapp.com/health
# Expected: {"status": "healthy", "timestamp": "..."}

# Test readiness probe
curl http://api.yourapp.com/ready
# Expected: {"status": "ready", "database": "connected", "timestamp": "..."}

# Test failed database connection
# (temporarily break DB connection)
curl http://api.yourapp.com/ready
# Expected: {"status": "not_ready", "database": "disconnected"} (503 status)
```

### 5.2 Logging

- [ ] 🟢 **Structured Logging Enabled**
  - JSON log format configured
  - Log level set to INFO (or WARN for production)
  - PII sanitization enabled

- [ ] 🟡 **Log Aggregation Configured** (REGULATED+)
  - Logs forwarded to centralized system (Loki, Elasticsearch, CloudWatch)
  - Log retention policy set (365 days REGULATED+)

**Verification:**

```bash
# Check log format
kubectl logs fraiseql-pod | head -1 | jq .
# Should parse as valid JSON

# Check log level
kubectl logs fraiseql-pod | grep -c DEBUG
# Should be 0 or very low in production

# Test PII sanitization
kubectl logs fraiseql-pod | grep -E "ssn|credit_card|password"
# Should return no matches or masked values
```

### 5.3 Metrics & Monitoring

- [ ] 🟢 **Prometheus Metrics Exposed**
  - `/metrics` endpoint enabled
  - Application metrics exported (request count, latency, errors)
  - Database metrics exported (connection pool, query latency)

- [ ] 🟡 **Grafana Dashboards Configured** (REGULATED+)
  - Pre-built dashboards imported
  - Key metrics visualized (latency p50/p95/p99, error rate, throughput)

- [ ] 🟡 **Alerts Configured** (REGULATED+)
  - High error rate alert (>1%)
  - High latency alert (p95 >1000ms)
  - Database connection pool exhaustion alert
  - Disk space alert (<20% free)

**Verification:**

```bash
# Check Prometheus metrics
curl http://api.yourapp.com/metrics | grep -E "http_requests_total|http_request_duration"

# Test alert firing (if using Alertmanager)
curl http://alertmanager:9093/api/v1/alerts | jq '.data[] | select(.state == "firing")'
```

### 5.4 Distributed Tracing

- [ ] 🟡 **OpenTelemetry Configured** (REGULATED+)
  - Tracing exporter configured (Jaeger, Tempo, Cloud Trace)
  - Trace sampling rate set (1% or 100 traces/sec for high traffic)
  - End-to-end traces visible (API → Database)

**Verification:**

```bash
# Check tracing endpoint configured
kubectl describe pod fraiseql-pod | grep -i OTEL_EXPORTER

# Query traces (Jaeger example)
curl "http://jaeger:16686/api/traces?service=fraiseql&limit=10"
```

---

## 6. Performance Optimization

### 6.1 Caching

- [ ] 🟢 **Caching Strategy Implemented**
  - Query result caching enabled
  - Cache TTL configured appropriately
  - Cache invalidation strategy defined

- [ ] 🟢 **Automatic Persisted Queries (APQ) Enabled**
  - APQ cache configured (Redis or in-memory)
  - Cache hit rate monitored

**Verification:**

```bash
# Test APQ
curl -X POST https://api.yourapp.com/graphql \
  -d '{"extensions": {"persistedQuery": {"version": 1, "sha256Hash": "HASH"}}}'
# First request: 200 + executed query
# Second request: 200 + cache hit

# Check cache hit rate
redis-cli INFO stats | grep keyspace_hits
```

### 6.2 Rust Pipeline

- [ ] 🟢 **Rust Pipeline Enabled** (if performance critical)
  - `rust_pipeline_enabled=True` in config
  - 7-10x JSON serialization performance verified

**Verification:**

```bash
# Check Rust pipeline status
curl http://api.yourapp.com/health | jq '.rust_pipeline_enabled'
# Expected: true
```

### 6.3 Load Testing

- [ ] 🟢 **Load Testing Completed**
  - Target load achieved (e.g., 1000 req/sec)
  - Latency targets met (p95 <500ms, p99 <1000ms)
  - No errors under load
  - Resource utilization acceptable (CPU <70%, Memory <80%)

**Verification:**

```bash
# Run load test
ab -n 10000 -c 100 https://api.yourapp.com/graphql

# Or use k6
k6 run --vus 100 --duration 5m load-test.js

# Check results
# - Requests/sec: ______ (target achieved?)
# - p95 latency: ______ ms (< 500ms?)
# - p99 latency: ______ ms (< 1000ms?)
# - Error rate: ______ % (< 0.1%?)
```

---

## 7. Deployment Infrastructure

### 7.1 Container Security

- [ ] 🟢 **Container Image Scanned**
  - Vulnerability scan completed (Trivy, Snyk, or Docker Scout)
  - No critical vulnerabilities
  - SBOM generated for container

- [ ] 🟢 **Non-Root User Configured**
  - Container runs as non-root user
  - Filesystem permissions set correctly

- [ ] 🔴 **Read-Only Filesystem** (RESTRICTED)
  - Root filesystem mounted read-only
  - Writable volumes for tmp/cache only

**Verification:**

```bash
# Scan container image
trivy image fraiseql:latest --severity CRITICAL,HIGH

# Check user
docker inspect fraiseql:latest | jq '.[0].Config.User'
# Expected: "fraiseql" (not "root")

# Check filesystem (in running container)
kubectl exec fraiseql-pod -- touch /test-write
# Should fail with "Read-only file system" (RESTRICTED)
```

### 7.2 Kubernetes Configuration

- [ ] 🟢 **Resource Limits Set**
  - CPU request/limit configured
  - Memory request/limit configured
  - No unlimited resources

- [ ] 🟢 **Health Probes Configured**
  - Liveness probe pointing to `/health`
  - Readiness probe pointing to `/ready`
  - Startup probe configured (if needed)

- [ ] 🟢 **Deployment Strategy Defined**
  - Rolling update strategy configured
  - maxUnavailable: 1 (or 25%)
  - maxSurge: 1 (or 25%)

- [ ] 🟢 **Horizontal Pod Autoscaler (HPA) Configured**
  - Target CPU utilization: 70%
  - Min replicas: 2 (for HA)
  - Max replicas: 10 (or based on capacity)

**Verification:**

```bash
# Check resource limits
kubectl describe pod fraiseql-pod | grep -A 5 "Limits:"

# Check probes
kubectl describe pod fraiseql-pod | grep -A 5 "Liveness:"

# Check HPA
kubectl get hpa fraiseql-hpa
kubectl describe hpa fraiseql-hpa

# Test autoscaling
kubectl run -i --tty load-generator --rm --image=busybox --restart=Never -- /bin/sh
# Inside pod: while true; do wget -q -O- http://fraiseql-service; done
# Watch HPA scale up: kubectl get hpa -w
```

### 7.3 Networking

- [ ] 🟢 **Load Balancer Configured**
  - Health checks configured
  - SSL termination at load balancer (or ingress)
  - Connection timeout: 30-60 seconds

- [ ] 🟡 **Network Policies Defined** (REGULATED+)
  - Ingress policies (only allow traffic from load balancer)
  - Egress policies (only allow traffic to database)

- [ ] 🔴 **IP Allowlisting Configured** (RESTRICTED)
  - Only trusted IPs allowed
  - Firewall rules tested

**Verification:**

```bash
# Check load balancer health
kubectl get svc fraiseql-service
curl http://<EXTERNAL-IP>/health

# Test network policies (REGULATED+)
# From unauthorized pod:
kubectl run -it test-pod --rm --image=busybox -- wget -O- http://fraiseql-service:8000
# Should timeout or fail

# Test IP allowlist (RESTRICTED)
curl https://api.yourapp.com/health
# From unauthorized IP: Should return 403 Forbidden
```

### 7.4 Rollback Plan

- [ ] 🟢 **Rollback Strategy Documented**
  - Previous deployment tagged and available
  - Rollback procedure tested
  - Database migration rollback plan (if needed)

- [ ] 🟢 **Rollback Tested in Staging**
  - Successfully rolled back to previous version
  - No data loss during rollback

**Verification:**

```bash
# Test rollback (in staging)
kubectl rollout history deployment/fraiseql
kubectl rollout undo deployment/fraiseql
kubectl rollout status deployment/fraiseql

# Verify previous version running
kubectl get pods -l app=fraiseql -o jsonpath='{.items[0].spec.containers[0].image}'
```

---

## 8. Incident Readiness

### 8.1 Runbook

- [ ] 🟢 **Incident Runbook Created**
  - Common incidents documented
  - Escalation procedures defined
  - Contact information current

**Runbook Template:**

```markdown
# FraiseQL Incident Runbook

## Common Incidents

### High Error Rate
**Symptoms**: Error rate >1%
**Diagnosis**: Check logs, database connectivity, external API status
**Resolution**: Restart pods, check database, rollback if needed
**Escalation**: After 15 minutes, page on-call engineer

### High Latency
**Symptoms**: p95 latency >1000ms
**Diagnosis**: Check database queries, connection pool, cache hit rate
**Resolution**: Scale horizontally, optimize queries, increase cache TTL
**Escalation**: After 30 minutes, page on-call engineer

### Database Connection Pool Exhausted
**Symptoms**: "connection pool exhausted" errors
**Diagnosis**: Check active connections, long-running queries
**Resolution**: Increase pool size, kill long-running queries, scale app
**Escalation**: Immediate if production traffic affected
```

### 8.2 On-Call Setup

- [ ] 🟢 **On-Call Rotation Defined**
  - On-call schedule created (PagerDuty, Opsgenie, etc.)
  - Team members trained
  - Backup on-call designated

- [ ] 🟢 **Alert Routing Configured**
  - Critical alerts page on-call engineer
  - Warning alerts notify team channel
  - Informational alerts logged only

### 8.3 Recovery Time Objectives

- [ ] 🟢 **SLO/SLA Defined**
  - Uptime target: _____ % (e.g., 99.9%)
  - Max response time (p95): _____ ms (e.g., 500ms)
  - Max error rate: _____ % (e.g., 0.1%)

- [ ] 🟢 **MTTR Goal Set**
  - Mean Time To Recovery (MTTR): _____ minutes (recommended: <15min for P0)

---

## 9. Post-Deployment Validation

### 9.1 Smoke Tests

- [ ] 🟢 **Core Functionality Tested**

  ```bash
  # Test health endpoint
  curl https://api.yourapp.com/health
  # Expected: 200 OK

  # Test GraphQL query
  curl -X POST https://api.yourapp.com/graphql \
    -H "Content-Type: application/json" \
    -d '{"query": "{ __typename }"}'
  # Expected: {"data": {"__typename": "Query"}}

  # Test authentication
  curl -X POST https://api.yourapp.com/graphql \
    -H "Authorization: Bearer VALID_TOKEN" \
    -d '{"query": "{ user { id } }"}'
  # Expected: 200 OK with user data

  # Test rate limiting (/health is never limited)
  for i in {1..101}; do
    curl -s -o /dev/null -w "%{http_code}\n" https://api.yourapp.com/graphql \
      -H "Content-Type: application/json" -d '{"query": "{ __typename }"}'
  done
  # Expected: Last requests return 429
  ```

### 9.2 Monitoring Validation

- [ ] 🟢 **Metrics Flowing to Dashboards**
  - Grafana dashboards show live data
  - No gaps in metrics (>1 minute)

- [ ] 🟢 **Logs Appearing in Aggregation System**
  - Logs visible in Loki/Elasticsearch/CloudWatch
  - Log volume as expected

- [ ] 🟢 **Alerts Not Firing**
  - No active alerts in Alertmanager
  - Test alerts verified to work (manually trigger)

### 9.3 Performance Validation

- [ ] 🟢 **Response Times Within SLA**
  - p50 latency: _____ ms
  - p95 latency: _____ ms (target: <500ms)
  - p99 latency: _____ ms (target: <1000ms)

- [ ] 🟢 **Error Rate Acceptable**
  - Error rate: _____ % (target: <0.1%)

- [ ] 🟢 **Resource Utilization Normal**
  - CPU usage: _____ % (target: <70%)
  - Memory usage: _____ % (target: <80%)
  - Database connections: _____ / _____ (target: <80% of pool)

**Verification:**

```bash
# Check metrics
curl http://prometheus:9090/api/v1/query?query=http_request_duration_seconds{quantile="0.95"}
curl http://prometheus:9090/api/v1/query?query=rate(http_requests_total{status=~"5.."}[5m])

# Check resource usage
kubectl top pods -l app=fraiseql
kubectl top nodes
```

---

## 10. Final Go/No-Go Decision

### 10.1 Critical Blockers (Must be DONE)

- [ ] ✅ **Security profile configured and tested**
- [ ] ✅ **HTTPS enforced with valid certificate**
- [ ] ✅ **Database backups automated and tested**
- [ ] ✅ **Health checks responding correctly**
- [ ] ✅ **Monitoring and alerting configured**
- [ ] ✅ **Load testing passed**
- [ ] ✅ **Rollback plan tested**
- [ ] ✅ **Smoke tests passed**

### 10.2 Non-Blocking Issues (Can be addressed post-launch)

- [ ] ⚠️ **Performance optimizations** (if within acceptable range)
- [ ] ⚠️ **Additional dashboards** (if core monitoring works)
- [ ] ⚠️ **Documentation updates** (if runbook exists)

### 10.3 Launch Decision

**GO / NO-GO:** _____

**Decision Maker:** _____
**Date:** _____
**Sign-off:** _____

**If NO-GO, blockers to resolve:**

1. _____
2. _____
3. _____

---

## Profile-Specific Checklists

### STANDARD Profile Summary

**Minimum Requirements:**

- [x] HTTPS configured
- [x] Basic authentication
- [x] Health checks
- [x] Database backups
- [x] Basic monitoring

**Optional:**

- [ ] MFA
- [ ] Audit logging
- [ ] Advanced monitoring

**Setup Time:** 1-2 hours

---

### REGULATED Profile Summary

**All STANDARD Requirements Plus:**

- [x] MFA enforced
- [x] KMS integration
- [x] Comprehensive audit logging
- [x] Introspection disabled
- [x] Log aggregation
- [x] Real-time alerts
- [x] Compliance report generated

**Setup Time:** 2-4 hours

---

### RESTRICTED Profile Summary

**All REGULATED Requirements Plus:**

- [x] mTLS configured
- [x] HSM-backed KMS
- [x] Cryptographic audit chain
- [x] IP allowlisting
- [x] Network segmentation
- [x] Anomaly detection
- [x] Read-only filesystem
- [x] Penetration testing completed

**Setup Time:** 4-8 hours

---

## Troubleshooting Common Issues

### Issue: Health check failing after deployment

**Cause:** Application not fully started or database unreachable

**Solution:**

```bash
# Check pod logs
kubectl logs fraiseql-pod

# Check database connectivity
kubectl exec fraiseql-pod -- psql $DATABASE_URL -c "SELECT 1;"

# Increase startupProbe initialDelaySeconds
kubectl edit deployment fraiseql
# Set startupProbe.initialDelaySeconds: 30
```

### Issue: High memory usage after deployment

**Cause:** Connection pool too large or memory leak

**Solution:**

```bash
# Check connection pool size
kubectl describe deployment fraiseql | grep DATABASE_URL

# Reduce pool size if needed
# Update environment variable: DATABASE_URL=...?pool_size=20&max_overflow=5

# Check for memory leaks
kubectl exec fraiseql-pod -- python -m memory_profiler app.py
```

### Issue: Deployment stuck in "Rolling Update"

**Cause:** New pods failing readiness check

**Solution:**

```bash
# Check rollout status
kubectl rollout status deployment/fraiseql

# Check new pod logs
kubectl logs -l app=fraiseql --tail=100

# If needed, rollback
kubectl rollout undo deployment/fraiseql
```

---

## Related Documentation

- **[Deployment Guide](./deployment.md)** - Detailed deployment instructions
- **[Monitoring Guide](./monitoring.md)** - Observability setup
- **[Security Guide](./security.md)** - Security hardening

---

## Checklist Template Download

Save this checklist for your deployment:

```bash
# Download as markdown
curl -o deployment-checklist.md \
  https://raw.githubusercontent.com/fraiseql/fraiseql/main/docs/production/deployment-checklist.md

# Convert to PDF (requires pandoc)
pandoc deployment-checklist.md -o deployment-checklist.pdf
```

---

**For Questions or Support:**

- **Email:** support@fraiseql.com
- **Enterprise Support:** Available for REGULATED/RESTRICTED deployments
- **GitHub Discussions:** Community support for deployment questions

---

*This checklist ensures production-ready deployments across all security profiles. Complete relevant sections for your profile and document any deviations with justification.*

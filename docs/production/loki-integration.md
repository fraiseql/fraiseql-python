# Loki Log Aggregation Integration

Integration guide for Loki log aggregation with FraiseQL applications.

## Overview

**Loki** is a horizontally-scalable, highly-available log aggregation system inspired by Prometheus. It indexes metadata (labels) rather than full-text, making it cost-effective for large-scale deployments.

**Architecture:**

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│   FraiseQL      │      │    Promtail     │      │      Loki       │
│   Application   │─────▶│  (Log Agent)    │─────▶│  (Aggregation)  │
│                 │ logs │                 │ push │                 │
└─────────────────┘      └─────────────────┘      └────────┬────────┘
                                                            │
                                                            ▼
                                                   ┌─────────────────┐
                                                   │    Grafana      │
                                                   │   (Query/UI)    │
                                                   └─────────────────┘
```

**Components:**

- **Loki:** Log storage and indexing engine
- **Promtail:** Log collection agent (tails log files)
- **Grafana:** Query interface and dashboards

**Benefits:**

- Label-based indexing (cost-effective at scale)
- Native Grafana integration
- LogQL query language (similar to PromQL)
- Correlation with OpenTelemetry traces via `trace_id`
- No full-text indexing overhead

---

## Quick Start

### 1. Start Loki Stack (Docker Compose)

```bash
# Navigate to examples directory
cd examples/observability

# Start Loki, Promtail, and Grafana
docker-compose -f docker-compose.loki.yml up -d

# Verify Loki is running
curl http://localhost:3100/ready

# Verify Promtail is running
curl http://localhost:9080/ready

# Access Grafana
open http://localhost:3000
# Login: admin / admin
```

### 2. Verify Log Ingestion

```bash
# Send test log to Loki
curl -X POST http://localhost:3100/loki/api/v1/push \
  -H "Content-Type: application/json" \
  -d '{
    "streams": [{
      "stream": {
        "job": "test",
        "level": "info"
      },
      "values": [
        ["'$(date +%s)000000000'", "Test log message from FraiseQL"]
      ]
    }]
  }'

# Query logs via LogQL
curl -G http://localhost:3100/loki/api/v1/query \
  --data-urlencode 'query={job="test"}' | jq
```

### 3. Query Logs in Grafana

1. Open Grafana: http://localhost:3000
2. Go to **Explore** → Select **Loki** data source
3. Run query: `{job="fraiseql-app"}`

---

## Configuration

### Development Configuration

The provided `docker-compose.loki.yml` uses:

- **Filesystem storage:** Logs stored in Docker volume
- **Single instance:** No replication
- **30-day retention:** Automatic log deletion after 30 days

**Files:**

- `examples/observability/loki/loki-config.yaml` - Loki server config
- `examples/observability/loki/promtail-config.yaml` - Promtail agent config
- `examples/observability/docker-compose.loki.yml` - Docker Compose stack

### Production Configuration

For production deployments, update `loki-config.yaml`:

```yaml
storage_config:
  aws:
    s3: s3://us-east-1/your-loki-bucket
    s3forcepathstyle: false
    bucketnames: your-loki-bucket
    region: us-east-1

# Or for GCS
storage_config:
  gcs:
    bucket_name: your-loki-bucket
    chunk_buffer_size: 10485760  # 10MB
    request_timeout: 60s

# Scale with multiple instances
common:
  replication_factor: 3
  ring:
    kvstore:
      store: consul
      consul:
        host: consul:8500
```

**Production Recommendations:**

- Use S3/GCS for object storage (not filesystem)
- Deploy 3+ Loki instances for HA
- Use Consul or etcd for ring coordination
- Increase retention to 90+ days
- Configure compaction for storage efficiency
- Enable query caching for performance

---

## FraiseQL Log Format

FraiseQL logs should be in **JSON format** for efficient parsing by Promtail.

### Expected Log Format

```json
{
  "timestamp": "2025-12-04T10:15:30.123Z",
  "level": "error",
  "message": "Database connection failed",
  "trace_id": "abc123def456",
  "span_id": "789ghi012jkl",
  "exception_type": "DatabaseConnectionError",
  "fingerprint": "db_connection_timeout",
  "context": {
    "user_id": "user_789",
    "tenant_id": "tenant_123",
    "operation": "create_post"
  }
}
```

### Configure Python Logging

```python
import logging
import json
from datetime import datetime

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname.lower(),
            "message": record.getMessage(),
            "logger": record.name,
        }

        # Add trace context if available
        if hasattr(record, "trace_id"):
            log_data["trace_id"] = record.trace_id
        if hasattr(record, "span_id"):
            log_data["span_id"] = record.span_id

        # Add exception info if present
        if record.exc_info:
            log_data["exception_type"] = record.exc_info[0].__name__
            log_data["stack_trace"] = self.formatException(record.exc_info)

        return json.dumps(log_data)

# Configure logger
handler = logging.FileHandler("/var/log/fraiseql/app.log")
handler.setFormatter(JSONFormatter())
logger = logging.getLogger("fraiseql")
logger.addHandler(handler)
logger.setLevel(logging.INFO)
```

---

## LogQL Query Examples

### 1. All Errors in Last Hour

```logql
{job="fraiseql-app"} | json | level="error"
```

**Note:** Time range is set in Grafana UI, not in the query. For range queries, use `count_over_time`.

### 2. Logs for Specific Trace

```logql
{job="fraiseql-app"} | json | trace_id="abc123def456"
```

**Use Case:** Jump from trace in Tempo to related logs in Loki.

### 3. Rate of Errors Per Minute

```logql
rate(count_over_time({job="fraiseql-app"} | json | level="error" [5m]))
```

### 4. Top 10 Error Types

```logql
topk(10,
  sum by (exception_type) (
    count_over_time({job="fraiseql-app"} | json | level="error" [1h])
  )
)
```

### 5. Filter by User or Tenant

```logql
{job="fraiseql-app"} | json | context_user_id="user_789"
```

### 6. Slow Query Detection

```logql
{job="postgresql"}
  | regexp "duration: (?P<duration>\\d+\\.\\d+) ms"
  | unwrap duration
  | __error__=""
  | duration > 1000
```

### 7. Database Connection Errors

```logql
{job="fraiseql-app"} | json | exception_type="DatabaseConnectionError"
```

### 8. Pattern Matching in Messages

```logql
{job="fraiseql-app"} |~ "authentication failed|unauthorized access"
```

### 9. Aggregate by Tenant

```logql
sum by (context_tenant_id) (
  count_over_time({job="fraiseql-app"} | json [1h])
)
```

### 10. Correlation with Metrics

```logql
# Count errors by fingerprint
sum by (fingerprint) (
  count_over_time({job="fraiseql-errors"} | json [5m])
)
```

---

## Correlation with OpenTelemetry Traces

### Enable Trace-Log Correlation

**1. Configure Grafana Data Source** (already done in `grafana-datasources.yaml`):

```yaml
derivedFields:
  - datasourceUid: tempo
    matcherRegex: "trace_id=(\\w+)"
    name: TraceID
    url: "$${__value.raw}"
```

**2. Ensure `trace_id` in Logs:**

FraiseQL logs must include `trace_id` field:

```python
import logging
from opentelemetry import trace

def log_with_trace_context(message, level="info"):
    span = trace.get_current_span()
    trace_id = span.get_span_context().trace_id

    extra = {"trace_id": format(trace_id, "032x")}
    logger.log(getattr(logging, level.upper()), message, extra=extra)
```

**3. Jump from Trace to Logs:**

In Grafana:

1. Open trace in Tempo
2. Click on span with errors
3. Click **"Logs for this span"** → Opens Loki with filtered query

**4. Jump from Logs to Trace:**

In Grafana Explore (Loki):

1. View log entry with `trace_id`
2. Click on trace_id link → Opens trace in Tempo

---

## Dashboards

### Pre-built Grafana Dashboards

**1. Log Volume Dashboard:**

- Total log rate by job
- Log levels distribution (info, warn, error)
- Top 10 loggers by volume

**2. Error Dashboard:**

- Error rate over time
- Top error types
- Error distribution by tenant
- Recent errors table

**3. Performance Dashboard:**

- Slow query logs (PostgreSQL)
- High-latency requests (FraiseQL)
- Database connection pool usage

**Import Dashboards:**

- Grafana Dashboard ID: 13639 (Loki + Promtail)
- Grafana Dashboard ID: 12611 (Logs / App / Loki)

---

## Retention and Storage

### Default Retention

**Development:** 30 days (720 hours)
**Production:** 90 days recommended

### Configure Retention

Edit `loki-config.yaml`:

```yaml
limits_config:
  retention_period: 2160h  # 90 days

table_manager:
  retention_deletes_enabled: true
  retention_period: 2160h  # 90 days

compactor:
  retention_enabled: true
  retention_delete_delay: 2h
```

### Storage Estimates

**Assumptions:**

- 100 req/sec = ~8.6M requests/day
- Average **5-10 log entries per request** (start, end, DB queries, errors)
- Average log entry: 500 bytes
- Compression ratio: 10:1 (Loki uses efficient compression)

**Calculations:**

```
Logs per day:
  100 req/sec × 5 logs/req × 86,400 sec/day = 43M logs/day

Raw size:
  43M logs × 500 bytes = 21.5 GB/day (uncompressed)

Compressed (Loki storage):
  21.5 GB ÷ 10 = 2.15 GB/day
```

**Storage Requirements:**

| Retention | Compressed Size | Raw Size (if exported) |
|-----------|----------------|------------------------|
| 7 days    | ~15 GB         | ~150 GB                |
| 30 days   | ~65 GB         | ~645 GB                |
| 90 days   | ~195 GB        | ~1.9 TB                |

**For production monitoring:**

- Check actual storage usage: `docker exec fraiseql-loki du -sh /loki/chunks`
- Monitor ingestion rate: `curl http://localhost:3100/metrics | grep loki_distributor_bytes_received_total`
- Set alerts if usage exceeds estimates by 50%
- Use S3/GCS with lifecycle policies (archive to Glacier after 90 days)

---

## Performance Tuning

### Optimize Log Volume

**1. Drop Debug Logs in Production:**

Edit `promtail-config.yaml`:

```yaml
pipeline_stages:
  - drop:
      source: level
      expression: "debug"
```

**2. Sample High-Volume Logs:**

```yaml
pipeline_stages:
  - match:
      selector: '{job="fraiseql-app",level="info"}'
      stages:
        - sampling:
            rate: 0.1  # Keep 10% of info logs
```

**3. Increase Ingestion Limits:**

Edit `loki-config.yaml`:

```yaml
limits_config:
  ingestion_rate_mb: 32  # Default: 16
  ingestion_burst_size_mb: 64  # Default: 32
```

### Query Performance

**1. Use Label Filters First:**

```logql
# Good: Filter by labels first
{job="fraiseql-app", level="error"} | json

# Bad: Filter after parsing
{job="fraiseql-app"} | json | level="error"
```

**2. Limit Time Range:**

- Prefer shorter time ranges (1h instead of 24h)
- Use `[5m]` range vectors for rate calculations

**3. Use Parallelization:**

Edit `loki-config.yaml`:

```yaml
limits_config:
  max_query_parallelism: 64  # Default: 32
```

---

## Troubleshooting

### Loki Not Receiving Logs

**Check Promtail:**

```bash
# View Promtail logs
docker logs fraiseql-promtail

# Check Promtail targets
curl http://localhost:9080/targets | jq
```

**Common Issues:**

- Log file path incorrect in `promtail-config.yaml`
- Log file permissions (Promtail needs read access)
- Loki URL incorrect (should be `http://loki:3100`)

### Promtail Parsing Errors

**Test Regex Parsing:**

```bash
# Check Promtail metrics
curl http://localhost:9080/metrics | grep promtail_read_errors_total
```

**Fix JSON Parsing:**

If logs aren't JSON, use regex instead:

```yaml
pipeline_stages:
  - regex:
      expression: '^(?P<timestamp>\S+) (?P<level>\S+) (?P<message>.*)$'
  - labels:
      level:
```

### Storage Issues

**Check Disk Usage:**

```bash
docker exec fraiseql-loki du -sh /loki/chunks
docker exec fraiseql-loki df -h /loki
```

**Compaction Not Running:**

```bash
# Check compactor logs
docker logs fraiseql-loki | grep compactor

# Force compaction
docker exec fraiseql-loki wget -O- http://localhost:3100/compactor/ring
```

---

## Security

### Authentication

For production, enable authentication:

```yaml
auth_enabled: true

server:
  http_listen_port: 3100
  grpc_listen_port: 9096

# Add basic auth or OAuth
auth:
  type: basic
  basic_auth:
    username: admin
    password_file: /etc/loki/.htpasswd
```

### TLS/SSL

Enable TLS for Loki and Promtail:

```yaml
server:
  http_tls_config:
    cert_file: /etc/loki/tls/server.crt
    key_file: /etc/loki/tls/server.key
```

### Network Isolation

Use Docker networks or VPC:

```yaml
networks:
  observability:
    internal: true  # No external access
```

---

## Migration from Other Systems

### From ELK Stack

**Differences:**

- Loki indexes labels, not full-text (cheaper at scale)
- LogQL vs Lucene query syntax
- No Kibana (use Grafana)

**Migration Steps:**

1. Run Loki + ELK in parallel
2. Configure Promtail to tail same logs
3. Validate queries in Grafana
4. Switch queries to Loki
5. Decommission ELK

### From Splunk

**Cost Savings:**

- Splunk: ~$150/GB ingested
- Loki: ~$0.023/GB (S3 storage) + compute

**Migration:**

- Loki is not a Splunk replacement (no full-text search)
- Best for structured logs (JSON)
- Use labels for filtering, not grep-style searches

---

## Query Optimization Best Practices

Efficient LogQL queries are critical for performance at scale. Follow these patterns to minimize query time and resource usage.

### Label Filters vs JSON Filters

**Rule**: Always filter by labels first, then use JSON filters.

```logql
# ❌ SLOW: JSON filter only (scans all logs)
{job="fraiseql"} | json | user_id="123"

# ✅ FAST: Label filter first (uses index)
{job="fraiseql", env="production"} | json | user_id="123"
```

**Why**: Label filters use Loki's index (instant), JSON filters require parsing (slow).

**Performance Impact**:

- Label filters: <10ms (indexed lookup)
- JSON filters: 100-1000ms+ (full scan + parse)

### Line Filters Before JSON Parsing

**Rule**: Use simple string matching before parsing JSON.

```logql
# ❌ SLOW: Parse all logs, then filter
{job="fraiseql"} | json | level="error"

# ✅ FAST: Filter lines first, then parse
{job="fraiseql"} |= "error" | json | level="error"
```

**Why**: Line filters (`|=`, `!=`, `|~`, `!~`) don't require parsing.

**Performance Impact**: 5-10x faster for selective queries.

### Time Range Optimization

**Rule**: Use the smallest time range possible.

```logql
# ❌ SLOW: Wide time range
{job="fraiseql"}[24h]

# ✅ FAST: Narrow time range
{job="fraiseql"}[5m]
```

**Best Practices**:

- Default to last 1 hour in dashboards
- Use 5-15 minute ranges for debugging
- Only use 24h+ for historical analysis
- Loki performance degrades linearly with time range

### Cardinality Management

**Rule**: Keep label cardinality low (<100 unique values per label).

```yaml
# ❌ HIGH CARDINALITY: user_id as label (millions of users)
labels:
  job: fraiseql
  user_id: "{{ user_id }}"  # DON'T DO THIS

# ✅ LOW CARDINALITY: user_id in JSON
labels:
  job: fraiseql
  env: production
# user_id goes in log message as JSON
```

**High cardinality labels** (> 1000 unique values):

- ❌ user_id, session_id, request_id, trace_id
- ❌ IP addresses, URLs
- ❌ Timestamps, UUIDs

**Low cardinality labels** (< 100 unique values):

- ✅ environment (dev, staging, prod)
- ✅ service name (fraiseql, postgres, nginx)
- ✅ log level (debug, info, warn, error)
- ✅ region (us-east-1, eu-west-1)

**Impact**: High cardinality causes:

- Slow queries (more chunks to scan)
- High memory usage
- Index bloat

### Common Query Patterns with Performance

**Pattern 1: Recent Errors**

```logql
# Fast: Labels + line filter + small time range
{job="fraiseql", env="production"} |= "error" [15m]
```

**Performance**: <100ms for millions of logs

**Pattern 2: Specific User Activity**

```logql
# Fast: Labels + line filter + JSON filter
{job="fraiseql"} |= "user_id" | json | user_id="123" [1h]
```

**Performance**: <500ms

**Pattern 3: Error Rate (Metrics Query)**

```logql
# Fast: Count errors per minute
sum(rate({job="fraiseql"} |= "error" [5m]))
```

**Performance**: <200ms (aggregated)

**Pattern 4: Top Error Messages**

```logql
# Moderate: TopK with JSON parsing
topk(10, sum by (error_message)
  (count_over_time({job="fraiseql"} |= "error" | json [1h]))
)
```

**Performance**: 1-3 seconds (acceptable for dashboards)

### Query Performance Checklist

Before deploying a query to production:

- [ ] Uses label filters (not just `{job="fraiseql"}`)
- [ ] Time range ≤ 1 hour (or documented reason for longer)
- [ ] Line filters (`|=`) before JSON parsing when possible
- [ ] No high-cardinality labels (user_id, trace_id, etc.)
- [ ] Tested with production data volume
- [ ] Query time < 5 seconds (dashboards should be < 1s)

### Performance Debugging

If a query is slow:

1. **Check time range**: Reduce to 5 minutes and re-test
2. **Add line filters**: Use `|= "keyword"` before `| json`
3. **Review labels**: Ensure you're filtering by indexed labels
4. **Check cardinality**: Run `{job="fraiseql"}` and count unique label values
5. **Use Grafana query inspector**: See actual query time and data volume

---

## PostgreSQL vs Loki: When to Use Each

FraiseQL supports both PostgreSQL error tables and Loki log aggregation. Each serves different purposes - use them together for comprehensive observability.

### PostgreSQL Errors Table

**Purpose**: Structured error tracking with management and analytics.

**Table Structure**: fraiseql's error tracker (`fraiseql.monitoring.init_error_tracker`)
writes to `tb_error_log`, created by `src/fraiseql/monitoring/schema.sql`. The columns
this page uses:

```sql
CREATE TABLE IF NOT EXISTS tb_error_log (
    error_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    error_fingerprint TEXT NOT NULL,  -- Error grouping
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    stack_trace TEXT,
    user_context JSONB DEFAULT '{}'::jsonb,
    application_context JSONB DEFAULT '{}'::jsonb,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    occurrence_count INT DEFAULT 1,
    status TEXT DEFAULT 'unresolved'
        CHECK (status IN ('unresolved', 'resolved', 'ignored', 'investigating')),
    trace_id TEXT,
    -- ... plus request_context, severity, tags, environment, resolution columns
);
```

**Use PostgreSQL errors for**:

- ✅ **Error management**: Track status (new, investigating, resolved)
- ✅ **Deduplication**: Group identical errors by fingerprint
- ✅ **Long-term storage**: Keep error history (months to years)
- ✅ **Analytics**: Query error trends, count by type, resolution time
- ✅ **Alerting**: Trigger on new error fingerprints or spike in occurrences
- ✅ **Team workflow**: Assign errors, add notes, mark as resolved

**Example Query**:

```sql
-- Top 10 unresolved errors
SELECT error_fingerprint, error_message, occurrence_count, last_seen
FROM tb_error_log
WHERE status = 'unresolved'
ORDER BY occurrence_count DESC
LIMIT 10;
```

### Loki Logs

**Purpose**: Full-context debugging with trace correlation.

**Use Loki for**:

- ✅ **Log context**: See all logs around an error (before/after)
- ✅ **Trace correlation**: Link logs to OpenTelemetry traces via trace_id
- ✅ **Debugging**: Search logs by user_id, request_id, session_id
- ✅ **Real-time monitoring**: Live log tailing, immediate visibility
- ✅ **Cost-effective storage**: Label-indexed, no full-text index overhead
- ✅ **Short-term retention**: Keep detailed logs for 7-30 days

**Example Query**:

```logql
-- All logs for a specific trace
{job="fraiseql"} | json | trace_id="abc123" [15m]

-- User activity logs
{job="fraiseql"} |= "user_id" | json | user_id="456" [1h]
```

### Decision Matrix

| Use Case | PostgreSQL | Loki | Both |
|----------|-----------|------|------|
| Error tracking & management | ✅ | | |
| Error deduplication | ✅ | | |
| Long-term error history (1+ year) | ✅ | | |
| Team workflow (assign, resolve) | ✅ | | |
| Error analytics & trends | ✅ | | |
| | | | |
| Full log context around errors | | ✅ | |
| Trace correlation (OpenTelemetry) | | ✅ | |
| Real-time log tailing | | ✅ | |
| Search by user/session/request | | ✅ | |
| Cost-effective short-term storage | | ✅ | |
| | | | |
| **Production debugging workflow** | | | ✅ |
| **Compliance & audit** | ✅ | | ✅ (archive Loki to PG) |

### Recommended Workflow

**0. Initialize the error tracker at startup** (after loading
`src/fraiseql/monitoring/schema.sql`), with a psycopg pool of its own:

```python
from psycopg_pool import AsyncConnectionPool
from fraiseql.monitoring import init_error_tracker

tracker_pool = AsyncConnectionPool(DATABASE_URL, open=False)
await tracker_pool.open()
init_error_tracker(tracker_pool, environment="production")
```

**1. Capture errors in both systems**:

```python
import logging
from fraiseql.monitoring import get_error_tracker

logger = logging.getLogger(__name__)

try:
    result = await process_user_action(user_id, action)
except Exception as e:
    # PostgreSQL: Structured error tracking (grouped by fingerprint;
    # the stack trace is taken from the exception)
    error_id = await get_error_tracker().capture_exception(
        e,
        context={
            "user": {"user_id": user_id},
            "application": {"action": action},
        },
    )

    # Loki: Full context via structured logging
    logger.error(
        "User action failed",
        extra={
            "user_id": user_id,
            "action": action,
            "error_id": error_id,  # Links to tb_error_log
            "error": str(e),
            "trace_id": current_trace_id()  # For correlation
        }
    )
    raise
```

**2. Investigation workflow**:

```
Step 1: Check PostgreSQL errors dashboard
  ↓ See: New error fingerprint "UserNotFoundError"
  ↓ Occurrence count: 47 times in last hour
  ↓ Metadata shows: user_id pattern

Step 2: Search Loki for context
  ↓ Query: {job="fraiseql"} |= "UserNotFoundError" | json | user_id="123" [1h]
  ↓ See: Full request logs, what user was doing
  ↓ Find: trace_id from logs

Step 3: View trace in Jaeger/Tempo
  ↓ See: Complete request flow across services
  ↓ Identify: Which service caused the error

Step 4: Mark error as resolved in PostgreSQL
  ↓ await get_error_tracker().resolve_error(error_id, resolved_by="alice")
```

**3. Retention strategy**:

```
PostgreSQL Errors:
  - Keep: All errors indefinitely (or 2+ years)
  - Storage: ~1KB per error = minimal
  - Purpose: Historical trends, compliance

Loki Logs:
  - Keep: 7-30 days (configurable)
  - Storage: ~100-500 bytes per log line
  - Purpose: Active debugging, context
  - Archive critical logs to PostgreSQL if needed
```

### When to Use Only One

**Only PostgreSQL** (no Loki):

- Small applications (<10 requests/sec)
- Minimal logging needs
- Cost-sensitive (avoid Loki infrastructure)
- **Limitation**: No log context, harder debugging

**Only Loki** (no PostgreSQL):

- Prototyping/development
- No error management workflow needed
- Short-term applications
- **Limitation**: No error deduplication, no analytics

**Both** (recommended):

- Production applications
- Team collaboration needed
- Compliance requirements
- Complex debugging scenarios

### Integration Example

**Store the error id in both systems**:

```python
from fraiseql.monitoring import get_error_tracker


async def handle_error(error: Exception, context: dict):
    # PostgreSQL: insert the error, or bump occurrence_count for its fingerprint
    error_id = await get_error_tracker().capture_exception(
        error, context={"application": context}
    )

    # Loki: Log with the error id for correlation
    logger.error(
        "Error occurred",
        extra={
            **context,
            "error_id": error_id,  # Links to tb_error_log
            "error_message": str(error)
        }
    )
```

**Query both systems together**:

```python
# Get error from PostgreSQL
error = await get_error_tracker().get_error(error_id)

# Get logs from Loki for that error
logs = await loki_client.query(
    f'{{job="fraiseql"}} | json | error_id="{error["error_id"]}" [24h]'
)

# Show: Error details + all log context
return {
    "error": error,
    "recent_occurrences": logs
}
```

---

## Monitoring Loki Itself

Production deployments must monitor Loki's health and performance to prevent log loss and ensure query availability.

### Health Check Endpoints

Loki exposes several HTTP endpoints for health monitoring:

```bash
# Ready check (Loki is ready to accept traffic)
curl http://localhost:3100/ready
# Response: "ready" (HTTP 200) or "not ready" (HTTP 503)

# Metrics endpoint (Prometheus format)
curl http://localhost:3100/metrics

# Ring status (distributed deployments)
curl http://localhost:3100/ring

# Configuration (verify settings)
curl http://localhost:3100/config | jq
```

**Kubernetes Liveness/Readiness Probes:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: loki
spec:
  containers:
  - name: loki
    image: grafana/loki:2.9.0
    livenessProbe:
      httpGet:
        path: /ready
        port: 3100
      initialDelaySeconds: 45
      periodSeconds: 10
      timeoutSeconds: 5
      failureThreshold: 3
    readinessProbe:
      httpGet:
        path: /ready
        port: 3100
      initialDelaySeconds: 30
      periodSeconds: 5
      timeoutSeconds: 3
```

**Docker Compose Health Check:**

```yaml
services:
  loki:
    image: grafana/loki:2.9.0
    healthcheck:
      test: ["CMD-SHELL", "wget --no-verbose --tries=1 --spider http://localhost:3100/ready || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

### Key Metrics to Monitor

**1. Ingestion Metrics**

Monitor log ingestion rate and errors:

```promql
# Ingestion rate (bytes/sec)
rate(loki_distributor_bytes_received_total[5m])

# Ingestion rate (logs/sec)
rate(loki_distributor_lines_received_total[5m])

# Ingestion errors
rate(loki_ingester_append_failures_total[5m])

# Samples rejected (exceeds limits)
rate(loki_discarded_samples_total[5m])
```

**2. Query Performance**

Track query latency and failures:

```promql
# Query latency (P99)
histogram_quantile(0.99,
  sum(rate(loki_request_duration_seconds_bucket{route="loki_api_v1_query_range"}[5m]))
  by (le)
)

# Query rate
rate(loki_request_duration_seconds_count{route="loki_api_v1_query_range"}[5m])

# Query errors
rate(loki_request_duration_seconds_count{status_code=~"5.."}[5m])

# Slow queries (>10s)
loki_query_duration_seconds_bucket{le="10"}
```

**3. Storage Metrics**

Monitor disk usage and chunk operations:

```promql
# Disk usage (filesystem storage)
loki_ingester_chunks_stored_total

# Chunk flush rate
rate(loki_ingester_chunk_stored_total[5m])

# Storage backend errors (S3/GCS)
rate(loki_store_chunk_request_duration_seconds_count{status_code=~"5.."}[5m])

# Active streams (cardinality)
loki_ingester_memory_streams
```

**4. Compactor Metrics**

For production deployments with compaction:

```promql
# Compaction runs
rate(loki_compactor_runs_completed_total[1h])

# Compaction failures
rate(loki_compactor_runs_failed_total[1h])

# Retention deletes
rate(loki_compactor_deleted_lines_total[1h])
```

**5. Resource Usage**

Monitor Loki container resources:

```promql
# CPU usage
rate(process_cpu_seconds_total{job="loki"}[5m])

# Memory usage
process_resident_memory_bytes{job="loki"}

# File descriptors
process_open_fds{job="loki"}

# Go heap allocations
go_memstats_heap_alloc_bytes{job="loki"}
```

### Prometheus Scrape Configuration

Configure Prometheus to scrape Loki metrics:

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'loki'
    static_configs:
      - targets: ['loki:3100']
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        replacement: 'loki-server'

  - job_name: 'promtail'
    static_configs:
      - targets: ['promtail:9080']
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        replacement: 'promtail-agent'
```

### Alert Rules

Critical alerts for Loki operations:

```yaml
# loki_alerts.yml
groups:
  - name: loki_alerts
    interval: 30s
    rules:
      # Ingestion stopped
      - alert: LokiIngestionStopped
        expr: rate(loki_distributor_bytes_received_total[5m]) == 0
        for: 5m
        labels:
          severity: critical
          component: loki
        annotations:
          summary: "Loki is not receiving any logs"
          description: "Loki ingestion rate is 0 for the last 5 minutes. Check Promtail connectivity."

      # High ingestion error rate
      - alert: LokiHighIngestionErrors
        expr: |
          (
            rate(loki_ingester_append_failures_total[5m])
            /
            rate(loki_distributor_lines_received_total[5m])
          ) > 0.05
        for: 5m
        labels:
          severity: warning
          component: loki
        annotations:
          summary: "High Loki ingestion error rate (>5%)"
          description: "{{ $value | humanizePercentage }} of log entries are failing to be ingested."

      # Samples rejected (rate limiting)
      - alert: LokiRateLimitExceeded
        expr: rate(loki_discarded_samples_total[5m]) > 100
        for: 5m
        labels:
          severity: warning
          component: loki
        annotations:
          summary: "Loki is rejecting samples due to rate limits"
          description: "{{ $value }} samples/sec are being rejected. Increase ingestion_rate_mb in limits_config."

      # High query latency
      - alert: LokiHighQueryLatency
        expr: |
          histogram_quantile(0.99,
            sum(rate(loki_request_duration_seconds_bucket{route="loki_api_v1_query_range"}[5m]))
            by (le)
          ) > 10
        for: 5m
        labels:
          severity: warning
          component: loki
        annotations:
          summary: "Loki query P99 latency >10s"
          description: "99th percentile query latency is {{ $value }}s. Check query complexity and time ranges."

      # High query error rate
      - alert: LokiHighQueryErrors
        expr: |
          (
            rate(loki_request_duration_seconds_count{status_code=~"5.."}[5m])
            /
            rate(loki_request_duration_seconds_count[5m])
          ) > 0.05
        for: 5m
        labels:
          severity: warning
          component: loki
        annotations:
          summary: "High Loki query error rate (>5%)"
          description: "{{ $value | humanizePercentage }} of queries are failing."

      # Compaction failures (production)
      - alert: LokiCompactionFailing
        expr: rate(loki_compactor_runs_failed_total[1h]) > 0
        for: 15m
        labels:
          severity: warning
          component: loki
        annotations:
          summary: "Loki compaction is failing"
          description: "Compaction has failed {{ $value }} times in the last hour. Check compactor logs."

      # Storage backend errors
      - alert: LokiStorageErrors
        expr: rate(loki_store_chunk_request_duration_seconds_count{status_code=~"5.."}[5m]) > 10
        for: 5m
        labels:
          severity: critical
          component: loki
        annotations:
          summary: "Loki storage backend errors"
          description: "{{ $value }} storage errors/sec. Check S3/GCS connectivity and permissions."

      # High cardinality warning
      - alert: LokiHighCardinality
        expr: loki_ingester_memory_streams > 100000
        for: 10m
        labels:
          severity: warning
          component: loki
        annotations:
          summary: "Loki has high cardinality (>100k streams)"
          description: "Active streams: {{ $value }}. Review label usage to reduce cardinality."

      # Disk space running low (filesystem storage)
      - alert: LokiDiskSpaceLow
        expr: |
          (
            node_filesystem_avail_bytes{mountpoint="/loki"}
            /
            node_filesystem_size_bytes{mountpoint="/loki"}
          ) < 0.15
        for: 10m
        labels:
          severity: warning
          component: loki
        annotations:
          summary: "Loki disk space <15%"
          description: "Only {{ $value | humanizePercentage }} disk space remaining. Increase retention or storage."

      # Loki instance down
      - alert: LokiDown
        expr: up{job="loki"} == 0
        for: 2m
        labels:
          severity: critical
          component: loki
        annotations:
          summary: "Loki instance is down"
          description: "Loki has been unavailable for 2 minutes. Check container/pod status."

      # Promtail down
      - alert: PromtailDown
        expr: up{job="promtail"} == 0
        for: 2m
        labels:
          severity: critical
          component: promtail
        annotations:
          summary: "Promtail agent is down"
          description: "Promtail has been unavailable for 2 minutes. Logs are not being collected."
```

**Deploy alerts to Prometheus:**

```bash
# Add to prometheus.yml
rule_files:
  - '/etc/prometheus/loki_alerts.yml'

# Reload Prometheus
curl -X POST http://localhost:9090/-/reload
```

### Grafana Dashboards for Loki Operations

**Import Official Dashboards:**

1. **Loki Operational Dashboard** (ID: 13407)
   - Ingestion rate, query performance, storage usage
   - Import: Grafana UI → Dashboards → Import → 13407

2. **Loki Logs Dashboard** (ID: 13639)
   - Log volume by job and level
   - Top log producers
   - Import: Grafana UI → Dashboards → Import → 13639

**Custom Dashboard Panels:**

```json
{
  "title": "Loki Ingestion Rate",
  "targets": [{
    "expr": "rate(loki_distributor_bytes_received_total[5m])",
    "legendFormat": "{{ instance }}"
  }],
  "yaxis": {
    "format": "Bps"
  }
}
```

```json
{
  "title": "Query Latency (P50, P95, P99)",
  "targets": [
    {
      "expr": "histogram_quantile(0.50, sum(rate(loki_request_duration_seconds_bucket{route=\"loki_api_v1_query_range\"}[5m])) by (le))",
      "legendFormat": "P50"
    },
    {
      "expr": "histogram_quantile(0.95, sum(rate(loki_request_duration_seconds_bucket{route=\"loki_api_v1_query_range\"}[5m])) by (le))",
      "legendFormat": "P95"
    },
    {
      "expr": "histogram_quantile(0.99, sum(rate(loki_request_duration_seconds_bucket{route=\"loki_api_v1_query_range\"}[5m])) by (le))",
      "legendFormat": "P99"
    }
  ],
  "yaxis": {
    "format": "s"
  }
}
```

### Common Issues and Troubleshooting

**Issue 1: Ingestion Rate is Zero**

**Symptoms:**

- `rate(loki_distributor_bytes_received_total[5m]) == 0`
- Logs not appearing in Grafana

**Diagnosis:**

```bash
# Check Promtail logs
docker logs fraiseql-promtail --tail 100

# Check Promtail targets
curl http://localhost:9080/targets | jq

# Test Loki API directly
curl -X POST http://localhost:3100/loki/api/v1/push \
  -H "Content-Type: application/json" \
  -d '{"streams":[{"stream":{"job":"test"},"values":[["'$(date +%s)000000000'","test"]]}]}'
```

**Resolution:**

- Verify Promtail can reach log files (permissions)
- Check Promtail → Loki network connectivity
- Verify Loki URL in `promtail-config.yaml`
- Check firewall rules (port 3100)

**Issue 2: High Query Latency**

**Symptoms:**

- Query P99 latency >10 seconds
- Grafana dashboards slow to load

**Diagnosis:**

```promql
# Identify slow queries
topk(10,
  loki_request_duration_seconds_bucket{le="10"}
)
```

**Resolution:**

- Reduce time range (use 1h instead of 24h)
- Add label filters to queries
- Increase `max_query_parallelism` in `loki-config.yaml`
- Check if high cardinality is causing chunk scanning

**Issue 3: Samples Rejected (Rate Limiting)**

**Symptoms:**

- `rate(loki_discarded_samples_total[5m]) > 0`
- Alert: `LokiRateLimitExceeded`

**Resolution:**

Edit `loki-config.yaml`:

```yaml
limits_config:
  ingestion_rate_mb: 32      # Increase from 16
  ingestion_burst_size_mb: 64  # Increase from 32
```

Restart Loki:

```bash
docker-compose -f docker-compose.loki.yml restart loki
```

**Issue 4: Storage Backend Errors (S3/GCS)**

**Symptoms:**

- `rate(loki_store_chunk_request_duration_seconds_count{status_code=~"5.."}) > 0`
- Logs: "failed to put chunk"

**Diagnosis:**

```bash
# Check Loki logs for storage errors
docker logs fraiseql-loki | grep -i "storage error"

# Verify S3/GCS credentials
aws s3 ls s3://your-loki-bucket  # AWS
gsutil ls gs://your-loki-bucket  # GCS
```

**Resolution:**

- Verify IAM permissions (S3: PutObject, GetObject, DeleteObject)
- Check network connectivity to cloud provider
- Verify bucket exists and is accessible
- Check S3/GCS credentials in Loki config

**Issue 5: High Cardinality**

**Symptoms:**

- `loki_ingester_memory_streams > 100000`
- Slow queries
- High memory usage

**Diagnosis:**

```logql
# Count unique label combinations
{job="fraiseql"} | json | label_format unique_labels="{{ __labels__ }}"
```

**Resolution:**

- Remove high-cardinality labels (user_id, trace_id, request_id)
- Move high-cardinality fields to JSON (not labels)
- Use static labels only (env, service, level)

**Issue 6: Compaction Not Running**

**Symptoms:**

- `rate(loki_compactor_runs_completed_total[1h]) == 0`
- Disk usage increasing

**Diagnosis:**

```bash
# Check compactor logs
docker logs fraiseql-loki | grep compactor

# Check compactor ring status
curl http://localhost:3100/compactor/ring
```

**Resolution:**

```yaml
# Enable compaction in loki-config.yaml
compactor:
  working_directory: /loki/compactor
  shared_store: filesystem
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
```

### Performance Benchmarks

Expected performance for production Loki deployment:

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Ingestion rate | 10-50 MB/sec | Drop to 0 for >5m |
| Query P99 latency | <5s | >10s |
| Ingestion errors | <1% | >5% |
| Query errors | <1% | >5% |
| Disk usage growth | <5 GB/day (100 req/sec) | >20 GB/day |
| Active streams | <50k | >100k |
| Compaction runs | 6/hour (every 10m) | 0 for >1h |

### Monitoring Checklist

Before deploying Loki to production:

- [ ] Prometheus scraping Loki metrics (`http://localhost:3100/metrics`)
- [ ] Prometheus scraping Promtail metrics (`http://localhost:9080/metrics`)
- [ ] Health check endpoints tested (`/ready`)
- [ ] Alert rules deployed to Prometheus
- [ ] Grafana dashboards imported (13407, 13639)
- [ ] Test alert firing (trigger `LokiIngestionStopped` by stopping Promtail)
- [ ] PagerDuty/Slack/email alerting configured
- [ ] Runbooks documented for each alert
- [ ] On-call team trained on Loki troubleshooting

---

## Security Hardening

Production Loki deployments must protect sensitive log data and prevent unauthorized access.

### Authentication Options

**Option 1: Multi-Tenancy (Recommended for Production)**

Loki supports multi-tenancy via X-Scope-OrgID header:

```yaml
# loki-config.yaml
auth_enabled: true

# Each tenant gets isolated data
# Queries require X-Scope-OrgID header
```

**Configure Promtail for multi-tenancy:**

```yaml
# promtail-config.yaml
clients:
  - url: http://loki:3100/loki/api/v1/push
    tenant_id: fraiseql-prod  # Tenant identifier

    # Optionally use different tenants per service
    # tenant_id: ${TENANT_ID}  # From environment variable
```

**Query with tenant isolation:**

```bash
# Query as specific tenant
curl -H "X-Scope-OrgID: fraiseql-prod" \
  http://localhost:3100/loki/api/v1/query \
  -G --data-urlencode 'query={job="fraiseql"}'

# Different tenant sees different data
curl -H "X-Scope-OrgID: fraiseql-staging" \
  http://localhost:3100/loki/api/v1/query \
  -G --data-urlencode 'query={job="fraiseql"}'
```

**Configure Grafana data source:**

```yaml
# grafana-datasources.yaml
datasources:
  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    jsonData:
      httpHeaderName1: 'X-Scope-OrgID'
    secureJsonData:
      httpHeaderValue1: 'fraiseql-prod'
```

**Benefits:**

- Complete data isolation between tenants
- Single Loki instance for multiple environments
- Cost-effective (no separate Loki deployments)
- Query isolation (tenant A can't see tenant B's logs)

**Option 2: Basic Authentication**

Use nginx or Traefik as reverse proxy with basic auth:

```yaml
# nginx.conf
server {
    listen 80;
    server_name loki.example.com;

    auth_basic "Loki Access";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://loki:3100;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**Create .htpasswd file:**

```bash
# Install htpasswd
apt-get install apache2-utils

# Create user
htpasswd -c /etc/nginx/.htpasswd admin

# Add more users
htpasswd /etc/nginx/.htpasswd developer
```

**Configure Promtail with basic auth:**

```yaml
# promtail-config.yaml
clients:
  - url: http://loki.example.com/loki/api/v1/push
    basic_auth:
      username: promtail
      password_file: /etc/promtail/password.txt
```

**Option 3: OAuth2/OpenID Connect (Enterprise)**

Use OAuth2 Proxy for SSO integration:

```yaml
# docker-compose.yml
services:
  oauth2-proxy:
    image: quay.io/oauth2-proxy/oauth2-proxy:latest
    command:
      - --provider=google
      - --email-domain=your-company.com
      - --upstream=http://loki:3100
      - --http-address=0.0.0.0:4180
      - --cookie-secret=RANDOM_SECRET
      - --client-id=YOUR_OAUTH_CLIENT_ID
      - --client-secret=YOUR_OAUTH_CLIENT_SECRET
    ports:
      - "4180:4180"
```

**Access flow:**

```
User → OAuth2 Proxy (Google/Okta/Azure AD) → Loki
```

**Option 4: API Keys (Custom)**

Implement API key validation via reverse proxy:

```lua
-- nginx with Lua
location /loki {
    access_by_lua_block {
        local api_key = ngx.req.get_headers()["X-API-Key"]
        if api_key ~= "expected_key_here" then
            ngx.exit(ngx.HTTP_FORBIDDEN)
        end
    }
    proxy_pass http://loki:3100;
}
```

### TLS/SSL Encryption

**Encrypt Loki API (HTTPS)**

Generate TLS certificates:

```bash
# Self-signed certificate (development)
openssl req -x509 -nodes -days 365 \
  -newkey rsa:2048 \
  -keyout loki-key.pem \
  -out loki-cert.pem \
  -subj "/CN=loki.example.com"

# Production: Use Let's Encrypt
certbot certonly --standalone -d loki.example.com
```

**Configure Loki with TLS:**

```yaml
# loki-config.yaml
server:
  http_listen_port: 3100
  grpc_listen_port: 9096
  http_tls_config:
    cert_file: /etc/loki/tls/loki-cert.pem
    key_file: /etc/loki/tls/loki-key.pem
    client_auth_type: NoClientCert  # Or RequireAndVerifyClientCert
  grpc_tls_config:
    cert_file: /etc/loki/tls/loki-cert.pem
    key_file: /etc/loki/tls/loki-key.pem
```

**Mount certificates in Docker Compose:**

```yaml
services:
  loki:
    image: grafana/loki:2.9.0
    volumes:
      - ./loki/loki-config.yaml:/etc/loki/local-config.yaml
      - ./tls:/etc/loki/tls:ro  # Read-only certificates
```

**Configure Promtail to use TLS:**

```yaml
# promtail-config.yaml
clients:
  - url: https://loki.example.com:3100/loki/api/v1/push
    tls_config:
      ca_file: /etc/promtail/ca-cert.pem
      # Optional: Client certificate authentication
      cert_file: /etc/promtail/client-cert.pem
      key_file: /etc/promtail/client-key.pem
      insecure_skip_verify: false  # Always false in production
```

**Mutual TLS (mTLS) - Client Certificate Authentication:**

```yaml
# loki-config.yaml
server:
  http_tls_config:
    cert_file: /etc/loki/tls/server-cert.pem
    key_file: /etc/loki/tls/server-key.pem
    client_auth_type: RequireAndVerifyClientCert
    client_ca_file: /etc/loki/tls/ca-cert.pem
```

**Benefits:**

- Encrypted log data in transit
- Prevents man-in-the-middle attacks
- Client authentication (mTLS)
- Compliance with security policies

### Network Isolation

**Docker Networks (Development/Staging):**

```yaml
# docker-compose.yml
version: '3.8'

services:
  loki:
    image: grafana/loki:2.9.0
    networks:
      - observability
    # No ports exposed to host

  promtail:
    image: grafana/promtail:2.9.0
    networks:
      - observability

  grafana:
    image: grafana/grafana:latest
    networks:
      - observability
      - public  # Only Grafana has external access
    ports:
      - "3000:3000"

networks:
  observability:
    internal: true  # No internet access
  public:
    # Allow external access
```

**Kubernetes Network Policies:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: loki-network-policy
  namespace: observability
spec:
  podSelector:
    matchLabels:
      app: loki
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Only allow traffic from Promtail and Grafana
    - from:
      - podSelector:
          matchLabels:
            app: promtail
      - podSelector:
          matchLabels:
            app: grafana
      ports:
        - protocol: TCP
          port: 3100
  egress:
    # Allow Loki to reach S3/GCS
    - to:
      - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 443
```

**Firewall Rules (Cloud VMs):**

```bash
# AWS Security Group
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxx \
  --protocol tcp \
  --port 3100 \
  --source-group sg-yyyyy  # Only from Promtail/Grafana

# GCP Firewall
gcloud compute firewall-rules create allow-loki \
  --direction=INGRESS \
  --priority=1000 \
  --network=default \
  --action=ALLOW \
  --rules=tcp:3100 \
  --source-tags=promtail,grafana \
  --target-tags=loki
```

### Log Sanitization (Remove PII/Secrets)

**Sanitize logs before sending to Loki:**

**Option 1: Filter in Application Code**

```python
import re
import logging

class SanitizingFormatter(logging.Formatter):
    """Remove sensitive data from logs before sending to Loki"""

    PATTERNS = [
        # Credit cards
        (re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'), '[CREDIT_CARD]'),
        # SSN
        (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), '[SSN]'),
        # Email addresses
        (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), '[EMAIL]'),
        # API keys (common patterns)
        (re.compile(r'(api[_-]?key|apikey|api[_-]?secret)[\s:=]+["\']?([a-zA-Z0-9_\-]{20,})["\']?', re.IGNORECASE), r'\1=[REDACTED]'),
        # JWT tokens
        (re.compile(r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'), '[JWT_TOKEN]'),
        # AWS keys
        (re.compile(r'(A3T[A-Z0-9]|AKIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASIA)[A-Z0-9]{16}'), '[AWS_KEY]'),
        # Passwords in URLs
        (re.compile(r'://[^:]+:([^@]+)@'), r'://[REDACTED]@'),
    ]

    def format(self, record):
        message = super().format(record)
        for pattern, replacement in self.PATTERNS:
            message = pattern.sub(replacement, message)
        return message

# Configure logger with sanitizing formatter
handler = logging.FileHandler('/var/log/fraiseql/app.log')
handler.setFormatter(SanitizingFormatter())
logger.addHandler(handler)
```

**Option 2: Filter in Promtail (Pipeline Stages)**

```yaml
# promtail-config.yaml
scrape_configs:
  - job_name: fraiseql-app
    static_configs:
      - targets:
          - localhost
        labels:
          job: fraiseql-app
          __path__: /var/log/fraiseql/*.log

    pipeline_stages:
      # Parse JSON logs
      - json:
          expressions:
            message: message

      # Redact credit cards
      - replace:
          expression: '(?P<before>.*)\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b(?P<after>.*)'
          replace: '{{ .before }}[CREDIT_CARD]{{ .after }}'

      # Redact API keys
      - replace:
          expression: '(?P<before>.*)(api[_-]?key|apikey)[\s:=]+["\']?[a-zA-Z0-9_\-]{20,}["\']?(?P<after>.*)'
          replace: '{{ .before }}{{ .Value }}=[REDACTED]{{ .after }}'

      # Redact email addresses
      - replace:
          expression: '(?P<before>.*)\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b(?P<after>.*)'
          replace: '{{ .before }}[EMAIL]{{ .after }}'

      # Drop logs containing secrets (don't send to Loki)
      - drop:
          source: message
          expression: '.*password.*|.*secret.*|.*token.*'
          drop_counter_reason: contains_secrets
```

**Option 3: Drop Sensitive Logs Entirely**

```yaml
# promtail-config.yaml
pipeline_stages:
  # Don't send authentication logs to Loki
  - drop:
      source: logger
      expression: 'auth|login|session'

  # Don't send debug logs in production
  - drop:
      source: level
      expression: 'debug'
      drop_counter_reason: debug_logs_in_prod
```

**Test sanitization:**

```bash
# Send test log with PII
echo '{"message": "User email is user@example.com, CC: 4532-1234-5678-9010"}' \
  | promtail --stdin --client.url http://localhost:3100/loki/api/v1/push

# Query Loki to verify redaction
curl -G http://localhost:3100/loki/api/v1/query \
  --data-urlencode 'query={job="test"}' | jq
# Should show: "User email is [EMAIL], CC: [CREDIT_CARD]"
```

### Docker Socket Security

**Problem:** Promtail typically mounts `/var/run/docker.sock` to discover containers, which grants root access to the Docker daemon.

**Solution 1: Use Docker Socket Proxy (Recommended)**

```yaml
# docker-compose.yml
services:
  # Socket proxy with read-only access
  docker-socket-proxy:
    image: tecnativa/docker-socket-proxy:latest
    container_name: docker-socket-proxy
    environment:
      CONTAINERS: 1  # Allow container queries
      NETWORKS: 0
      VOLUMES: 0
      IMAGES: 0
      SERVICES: 0
      TASKS: 0
      EVENTS: 1
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - observability

  promtail:
    image: grafana/promtail:2.9.0
    volumes:
      - ./promtail-config.yaml:/etc/promtail/config.yml:ro
      - /var/log:/var/log:ro
      # NO direct docker.sock mount
    environment:
      DOCKER_HOST: tcp://docker-socket-proxy:2375
    networks:
      - observability

networks:
  observability:
    internal: true
```

**Benefits:**

- Promtail can't execute arbitrary Docker commands
- Read-only container discovery
- Reduces attack surface

**Solution 2: File-based Discovery (No Docker Socket)**

```yaml
# promtail-config.yaml
scrape_configs:
  - job_name: fraiseql-app
    static_configs:
      - targets:
          - localhost
        labels:
          job: fraiseql-app
          __path__: /var/log/containers/fraiseql-*.log

    # No docker service discovery needed
```

**Solution 3: Kubernetes (No Docker Socket Access)**

In Kubernetes, use native service discovery:

```yaml
# promtail-daemonset.yaml
scrape_configs:
  - job_name: kubernetes-pods
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        target_label: app
      - source_labels: [__meta_kubernetes_namespace]
        target_label: namespace

# No docker.sock mount needed
```

### Secrets Management

**Never hardcode secrets in configuration files.**

**Option 1: Environment Variables**

```yaml
# docker-compose.yml
services:
  promtail:
    image: grafana/promtail:2.9.0
    environment:
      LOKI_URL: http://loki:3100
      LOKI_USERNAME: ${LOKI_USERNAME}  # From .env file
      LOKI_PASSWORD: ${LOKI_PASSWORD}
    volumes:
      - ./promtail-config.yaml:/etc/promtail/config.yml:ro
```

```yaml
# promtail-config.yaml
clients:
  - url: ${LOKI_URL}/loki/api/v1/push
    basic_auth:
      username: ${LOKI_USERNAME}
      password: ${LOKI_PASSWORD}
```

```bash
# .env (DO NOT COMMIT)
LOKI_USERNAME=promtail
LOKI_PASSWORD=super-secret-password
```

**Option 2: Docker Secrets (Swarm/Compose)**

```yaml
# docker-compose.yml
version: '3.8'

services:
  promtail:
    image: grafana/promtail:2.9.0
    secrets:
      - loki_password
    volumes:
      - ./promtail-config.yaml:/etc/promtail/config.yml:ro

secrets:
  loki_password:
    file: ./secrets/loki_password.txt
```

```yaml
# promtail-config.yaml
clients:
  - url: http://loki:3100/loki/api/v1/push
    basic_auth:
      username: promtail
      password_file: /run/secrets/loki_password
```

**Option 3: Kubernetes Secrets**

```yaml
# Create secret
apiVersion: v1
kind: Secret
metadata:
  name: loki-credentials
type: Opaque
stringData:
  username: promtail
  password: super-secret-password
---
# Use in Promtail pod
apiVersion: v1
kind: Pod
metadata:
  name: promtail
spec:
  containers:
  - name: promtail
    image: grafana/promtail:2.9.0
    env:
      - name: LOKI_USERNAME
        valueFrom:
          secretKeyRef:
            name: loki-credentials
            key: username
      - name: LOKI_PASSWORD
        valueFrom:
          secretKeyRef:
            name: loki-credentials
            key: password
```

**Option 4: HashiCorp Vault**

```yaml
# promtail-config.yaml
clients:
  - url: http://loki:3100/loki/api/v1/push
    basic_auth:
      username: ${VAULT_USERNAME}  # Fetched from Vault
      password: ${VAULT_PASSWORD}
```

```bash
# Fetch secrets from Vault on startup
vault kv get -field=username secret/loki > /tmp/loki_user
vault kv get -field=password secret/loki > /tmp/loki_pass

export VAULT_USERNAME=$(cat /tmp/loki_user)
export VAULT_PASSWORD=$(cat /tmp/loki_pass)

# Start Promtail with secrets
promtail -config.file=/etc/promtail/config.yml
```

### Security Best Practices Summary

**Checklist:**

- [ ] **Authentication enabled** (multi-tenancy or basic auth)
- [ ] **TLS/SSL encryption** for Loki API and Promtail
- [ ] **Network isolation** (Docker networks, Kubernetes NetworkPolicies, or firewalls)
- [ ] **Log sanitization** (remove PII, secrets, credit cards)
- [ ] **Docker socket proxied** (not directly mounted in Promtail)
- [ ] **Secrets in environment variables** (not hardcoded)
- [ ] **Regular security audits** (review access logs, check for unauthorized queries)
- [ ] **Rate limiting** configured to prevent DoS
- [ ] **Monitoring alerts** for failed auth attempts
- [ ] **Least privilege** (Promtail has read-only file access)

**Compliance Considerations:**

| Regulation | Requirement | Implementation |
|------------|-------------|----------------|
| **GDPR** | No PII in logs | Sanitize email, names, IPs before Loki |
| **PCI-DSS** | No credit card data | Redact CC numbers in Promtail pipeline |
| **HIPAA** | Encrypt logs in transit | Enable TLS for Loki and Promtail |
| **SOC 2** | Access controls | Multi-tenancy + audit logs |
| **CCPA** | Right to deletion | Retention policies + manual deletion API |

**Audit Logging:**

Enable query logging in Loki to track who accessed what:

```yaml
# loki-config.yaml
query_range:
  results_cache:
    cache:
      enable_fifocache: true

# Log all queries to file
log_queries_longer_than: 0s  # Log all queries
```

Query audit logs:

```bash
# View Loki's own logs (includes query logs)
docker logs fraiseql-loki | grep "query"
```

**Example secure production configuration:**

```yaml
# loki-config.yaml (production)
auth_enabled: true  # Multi-tenancy

server:
  http_listen_port: 3100
  grpc_listen_port: 9096
  http_tls_config:
    cert_file: /etc/loki/tls/server-cert.pem
    key_file: /etc/loki/tls/server-key.pem
    client_auth_type: RequireAndVerifyClientCert
    client_ca_file: /etc/loki/tls/ca-cert.pem

limits_config:
  ingestion_rate_mb: 16
  ingestion_burst_size_mb: 32
  max_query_length: 721h  # 30 days max
  max_query_parallelism: 32

storage_config:
  aws:
    s3: s3://us-east-1/loki-logs-encrypted
    s3forcepathstyle: false
    sse_encryption: true  # Server-side encryption

chunk_store_config:
  max_look_back_period: 720h  # 30 days retention

table_manager:
  retention_deletes_enabled: true
  retention_period: 720h
```

---

## References

**Official Documentation:**

- Loki: https://grafana.com/docs/loki/latest/
- Promtail: https://grafana.com/docs/loki/latest/clients/promtail/
- LogQL: https://grafana.com/docs/loki/latest/logql/

**FraiseQL Integration:**

- Observability Overview: `docs/production/observability.md`
- OpenTelemetry Setup: `docs/production/monitoring.md`
- Error Tracking: `docs/production/observability.md#error-tracking`

**Configuration Files:**

- Loki Config: `examples/observability/loki/loki-config.yaml`
- Promtail Config: `examples/observability/loki/promtail-config.yaml`
- Docker Compose: `examples/observability/docker-compose.loki.yml`

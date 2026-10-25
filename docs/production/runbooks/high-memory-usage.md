# High Memory Usage Runbook

**Last Updated**: 2025-12-29
**Severity**: HIGH
**MTTR Target**: 20 minutes

---

## 📋 Overview

This runbook guides you through diagnosing and resolving high memory usage in FraiseQL applications. Memory issues can lead to application crashes, OOM (Out of Memory) kills, and degraded performance.

---

## 🚨 Symptoms

### Primary Indicators

- Application memory usage > 80% of limit
- OOMKilled events in container logs
- Swap usage increasing
- Application slowness/unresponsiveness
- Memory usage growing over time (memory leak)

### Prometheus Metrics to Monitor

```promql
# Memory usage percentage
(process_resident_memory_bytes / node_memory_MemTotal_bytes) * 100 > 80

# Memory growth rate
rate(process_resident_memory_bytes[5m]) > 10485760  # 10MB/5min

# Python garbage collection frequency
rate(python_gc_collections_total[5m]) > 10
```

### Structured Logs Examples

```json
{
  "timestamp": "2025-12-29T11:15:42.789Z",
  "level": "WARNING",
  "event": "system.high_memory",
  "message": "Application memory usage exceeds threshold",
  "context": {
    "memory_used_bytes": 1610612736,
    "memory_limit_bytes": 2147483648,
    "memory_usage_percent": 75.0,
    "threshold_percent": 70.0
  },
  "trace_id": "trace_mem123"
}
```

```json
{
  "timestamp": "2025-12-29T11:20:15.456Z",
  "level": "ERROR",
  "event": "system.memory_critical",
  "message": "Critical memory usage - OOM risk",
  "context": {
    "memory_used_bytes": 2013265920,
    "memory_limit_bytes": 2147483648,
    "memory_usage_percent": 93.75,
    "swap_used_bytes": 524288000
  },
  "trace_id": "trace_mem456"
}
```

---

## 🔍 Diagnostic Steps

### Step 1: Check Current Memory Usage

**Via Prometheus**:

```promql
# Current memory usage
process_resident_memory_bytes

# Memory usage percentage
(process_resident_memory_bytes / node_memory_MemTotal_bytes) * 100

# Virtual memory size
process_virtual_memory_bytes
```

**Via System Commands**:

```bash
# Check container memory usage (Docker)
docker stats --no-stream <container_id>

# Check process memory (Linux)
ps aux | grep fraiseql | awk '{print $4, $6, $11}'

# Check system memory
free -h
```

**Via Application Endpoint**:

fraiseql's `/health` only reports that the process is up, and `/ready` that the
database answers; neither reports memory. Read memory from the system commands
above, or from `process_resident_memory_bytes` on `/metrics` when the app exposes
Prometheus metrics (`fraiseql.monitoring.metrics.setup_metrics(app)`).

```bash
curl http://localhost:8000/health
# {"status": "healthy", "service": "fraiseql"}
```

### Step 2: Identify Memory Consumers

**Via Prometheus - Component Breakdown**:

```promql
# Database connection pool memory
fraiseql_db_connections_total * 10485760  # ~10MB per connection estimate

# Cache memory (if using in-memory cache)
fraiseql_cache_size_bytes

# Active GraphQL operations
fraiseql_graphql_queries_total - fraiseql_graphql_queries_success - fraiseql_graphql_queries_errors
```

**Via Python Memory Profiler** (development only):

```python
import tracemalloc

# Enable memory tracking
tracemalloc.start()

# ... run application ...

# Get memory snapshot
snapshot = tracemalloc.take_snapshot()
top_stats = snapshot.statistics('lineno')

# Display top 10 memory consumers
for stat in top_stats[:10]:
    print(stat)
```

**Via Structured Logs**:

```bash
# Find memory-related events
jq -r 'select(.event | startswith("system.memory")) |
  "\(.timestamp) \(.event) \(.context.memory_usage_percent)%"' \
  /var/log/fraiseql/app.log | tail -50

# Find large request payloads
jq -r 'select(.context.request_size_bytes > 1048576) |
  "\(.timestamp) \(.context.request_size_bytes) bytes"' \
  /var/log/fraiseql/app.log | tail -20
```

### Step 3: Check for Memory Leaks

**Python Garbage Collection Stats**:

```promql
# GC collection frequency (high = potential leak)
rate(python_gc_collections_total[5m])

# Uncollectable objects (memory leak indicator)
python_gc_objects_uncollectable_total
```

**Check Object Count Growth**:

```promql
# Total Python objects
python_gc_objects_collected_total

# Object growth rate
rate(python_gc_objects_collected_total[10m])
```

**Via Application Code**:

```python
import gc

# Force garbage collection
gc.collect()

# Get object counts by type
from collections import defaultdict
type_counts = defaultdict(int)
for obj in gc.get_objects():
    type_counts[type(obj).__name__] += 1

# Display top 10 object types
for obj_type, count in sorted(type_counts.items(), key=lambda x: -x[1])[:10]:
    print(f"{obj_type}: {count}")
```

### Step 4: Check Database Connection Pool

**Via Prometheus**:

```promql
# Active connections (each uses ~10MB)
fraiseql_db_connections_active

# Total pool size
fraiseql_db_connections_total

# Idle connections (still use memory)
fraiseql_db_connections_idle
```

**Via PostgreSQL**:

```sql
-- Check connection count
SELECT count(*) AS connections FROM pg_stat_activity;

-- Check connections by application
SELECT
  application_name,
  count(*) AS conn_count
FROM pg_stat_activity
GROUP BY application_name;
```

### Step 5: Check Request Processing

**Large Requests/Responses**:

```promql
# HTTP request size histogram
histogram_quantile(0.95,
  rate(fraiseql_http_request_size_bytes_bucket[5m])
)

# Response size histogram
histogram_quantile(0.95,
  rate(fraiseql_http_response_size_bytes_bucket[5m])
)
```

**Active Operations**:

```bash
# Count in-flight GraphQL operations
curl http://localhost:8000/metrics | grep fraiseql_graphql | grep -v "#"
```

---

## 🔧 Resolution Steps

### Immediate Actions (5 minutes)

#### 1. Restart Application (If Critical)

```bash
# Docker
docker restart <container_id>

# Kubernetes
kubectl rollout restart deployment fraiseql-app

# Systemd
systemctl restart fraiseql
```

**Note**: Only restart if memory usage > 90% and application is unresponsive.

#### 2. Force Garbage Collection

fraiseql has no endpoint for this; run it in a Python REPL attached to the process
(e.g. with `py-spy` or a debugger), or restart the pod:

```python
import gc
gc.collect()
```

#### 3. Reduce Connection Pool Size (Temporary)

The pool opens at most `database_pool_size + database_max_overflow` connections:

```python
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    database_pool_size=5,  # Default: 20 (create_fraiseql_app uses 10 in development)
    database_max_overflow=2,  # Default: 10
)
app = create_fraiseql_app(config=config, types=[User], queries=[users])
```

**Environment Variable** (read when the app is built from a `FraiseQLConfig`, as above;
`create_fraiseql_app(database_url=...)` without `config` sets the pool size itself):

```bash
export FRAISEQL_DATABASE_POOL_SIZE=5
export FRAISEQL_DATABASE_MAX_OVERFLOW=2
```

### Short-Term Fixes (15-30 minutes)

#### 1. Analyze Memory Usage Pattern

**Check for Memory Leak**:

```bash
# Compare memory usage over time
curl http://localhost:8000/metrics | grep process_resident_memory

# Wait 5 minutes, check again
sleep 300
curl http://localhost:8000/metrics | grep process_resident_memory

# Memory should stabilize, not grow continuously
```

**Identify Leak Source**:

```python
# Use objgraph to find memory leaks (development)
import objgraph

# Show growth in object count
objgraph.show_growth()

# Wait for operations
# ... run GraphQL queries ...

# Show growth again
objgraph.show_growth()

# Objects growing unexpectedly indicate leak
```

#### 2. Optimize Connection Pool Settings

**Right-size Based on Actual Usage**:

```python
# Calculate optimal pool size
# Formula: pool_size = concurrent_requests / avg_query_time

# Example: 100 req/sec, 0.1s avg query time
concurrent_requests = 100 * 0.1  # = 10
pool_size = concurrent_requests * 1.5  # Safety margin = 15

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    database_pool_size=15,
    database_max_overflow=5,
    database_pool_timeout=30,  # Seconds a request waits for a free connection
)
```

**Memory Impact**:

```
Each connection ≈ 10MB
pool_size=20 → ~200MB
pool_size=10 → ~100MB
```

#### 3. Implement Connection Recycling

```python
from fraiseql.fastapi import FraiseQLConfig

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    database_pool_recycle=3600,  # Close and replace connections after 1 hour (default)
)
```

**Benefits**:

- Prevents connection memory bloat
- Releases idle connection memory

#### 4. Move In-Process Caches Out of the Process

fraiseql's result cache (`fraiseql.caching.PostgresCache`, see
[Caching](../../performance/caching.md)) lives in a PostgreSQL UNLOGGED table, not
in application memory. What does live in the process is the automatic persisted
queries (APQ) store, which defaults to memory and grows with each distinct query
(and each cached response, with `apq_cache_responses=True`). Keep it in PostgreSQL
instead:

```python
from fraiseql.fastapi import FraiseQLConfig

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    apq_storage_backend="postgresql",  # Default: "memory"
)
```

### Long-Term Solutions (1+ days)

#### 1. Implement Memory Limits

**Docker/Kubernetes**:

```yaml
# docker-compose.yml
services:
  fraiseql:
    image: fraiseql:latest
    deploy:
      resources:
        limits:
          memory: 2G
        reservations:
          memory: 1G
```

```yaml
# kubernetes deployment
resources:
  limits:
    memory: "2Gi"
  requests:
    memory: "1Gi"
```

**Set OOM Score** (Linux):

```bash
# Prevent OOM killer from targeting this process
echo -1000 > /proc/<pid>/oom_score_adj
```

#### 2. Implement Request Size Limits

Cap request bodies before they reach the app, at the reverse proxy or ingress:

```nginx
# nginx: answer 413 to bodies over 10MB
client_max_body_size 10m;
```

```yaml
# ingress-nginx
metadata:
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
```

#### 3. Cap Result Set Sizes

```python
import fraiseql


@fraiseql.query
async def users(info, limit: int = 100) -> list[User]:
    # Limit result set size
    if limit > 1000:
        raise ValueError("Limit cannot exceed 1000")

    db = info.context["db"]
    return await db.find("v_user", limit=limit)
```

**Pagination for Large Results**:

```python
@fraiseql.query
async def orders(info, page: int = 1, page_size: int = 100) -> list[Order]:
    # Validate page_size
    if page_size > 500:
        raise ValueError("Page size cannot exceed 500")

    db = info.context["db"]
    return await db.find(
        "v_order",
        order_by=[{"created_at": "DESC"}],
        limit=page_size,
        offset=(page - 1) * page_size,
    )
```

#### 4. Horizontal Scaling

```yaml
# kubernetes deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fraiseql
spec:
  replicas: 3  # Distribute load across instances
  template:
    spec:
      containers:
      - name: fraiseql
        resources:
          limits:
            memory: "1Gi"  # Lower per-instance limit
```

**Benefits**:

- Reduced memory per instance
- Better fault tolerance
- Higher total capacity

---

## 📊 Monitoring & Alerts

### Prometheus Alert Rules

```yaml
# alerts/memory.yml
groups:
  - name: memory_usage
    interval: 30s
    rules:
      - alert: HighMemoryUsage
        expr: |
          (process_resident_memory_bytes / node_memory_MemTotal_bytes) * 100 > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High memory usage (> 80%)"
          description: "Memory usage: {{ $value | humanizePercentage }}"

      - alert: CriticalMemoryUsage
        expr: |
          (process_resident_memory_bytes / node_memory_MemTotal_bytes) * 100 > 90
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Critical memory usage (> 90%)"
          description: "Memory usage: {{ $value | humanizePercentage }} - OOM risk!"

      - alert: MemoryLeak
        expr: |
          rate(process_resident_memory_bytes[30m]) > 10485760  # 10MB growth per 30min
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Potential memory leak detected"
          description: "Memory growing at {{ $value | humanize }}bytes/sec"

      - alert: ExcessiveGarbageCollection
        expr: |
          rate(python_gc_collections_total[5m]) > 10
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Excessive garbage collection activity"
          description: "GC running {{ $value }} times/sec"
```

### Grafana Dashboard Panels

**1. Memory Usage Timeline**:

```promql
process_resident_memory_bytes
process_virtual_memory_bytes
```

**2. Memory Usage Percentage**:

```promql
(process_resident_memory_bytes / node_memory_MemTotal_bytes) * 100
```

**3. Memory Growth Rate**:

```promql
rate(process_resident_memory_bytes[10m])
```

**4. Garbage Collection Activity**:

```promql
rate(python_gc_collections_total[5m])
python_gc_objects_uncollectable_total
```

---

## 🔍 Verification

After applying fixes, verify memory usage is stable:

### 1. Check Metrics

```promql
# Memory usage should be < 80%
(process_resident_memory_bytes / node_memory_MemTotal_bytes) * 100

# Memory should not be growing
rate(process_resident_memory_bytes[10m]) < 1048576  # < 1MB per 10min
```

### 2. Load Test

```bash
# Run load test for 10 minutes
ab -n 10000 -c 100 http://localhost:8000/graphql

# Monitor memory during test
watch -n 5 'curl -s http://localhost:8000/metrics | grep process_resident_memory'

# Memory should stabilize, not grow continuously
```

### 3. Check Logs

```bash
# Verify no memory warnings
jq -r 'select(.event | startswith("system.memory"))' /var/log/fraiseql/app.log | tail -10

# Should see no recent warnings
```

---

## 📝 Post-Incident Review

After resolving the incident:

1. **Identify Root Cause**:
   - Memory leak in code?
   - Oversized connection pool?
   - Excessive caching?
   - Large request payloads?

2. **Implement Permanent Fix**:
   - Fix memory leak in code
   - Right-size connection pool
   - Implement request size limits
   - Add pagination for large results

3. **Update Monitoring**:
   - Adjust alert thresholds
   - Add component-specific memory tracking
   - Set up memory profiling in staging

4. **Capacity Planning**:
   - Document normal memory usage baseline
   - Calculate memory needs for expected growth
   - Plan for horizontal scaling

---

## 📚 Related Resources

- [Container Memory Limits](../deployment.md#resource-limits)
- [Connection Pool Configuration](./database-performance-degradation.md#connection-pool)
- [Caching Best Practices](../../performance/caching.md)
- [Python Memory Management](https://docs.python.org/3/library/gc.html)

---

## 🆘 Escalation

If issue persists after following this runbook:

1. **Gather Evidence**:
   - Memory usage graphs (last 24 hours)
   - Garbage collection stats
   - Connection pool stats
   - Memory profiler output (if available)

2. **Escalate To**:
   - Platform Team (for infrastructure scaling)
   - Development Team (for memory leak investigation)
   - SRE Team (for capacity planning)

3. **Emergency Contact**:
   - Platform On-call: [Contact info]
   - Engineering Manager: [Contact info]
   - SRE On-call: [Contact info]

---

**Version**: 1.0
**Last Tested**: 2025-12-29
**Next Review**: 2026-03-29

# High Memory Usage Runbook

**Last Updated**: 2026-10-25
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

FraiseQL exports no memory metric, and its `/metrics` endpoint (`setup_metrics(app)`)
serves its own registry, without the `process_*` and `python_gc_*` metrics that
`prometheus_client` puts in its default one. Register those collectors on it:

```python
from prometheus_client import GCCollector, PlatformCollector, ProcessCollector

from fraiseql.monitoring import setup_metrics

metrics = setup_metrics(app)
ProcessCollector(registry=metrics.registry)   # process_resident_memory_bytes, process_cpu_seconds_total, ...
GCCollector(registry=metrics.registry)        # python_gc_collections_total, python_gc_objects_*
PlatformCollector(registry=metrics.registry)  # python_info
```

Then (each worker process has its own registry and series):

```promql
# Resident memory over 1.5 GiB
process_resident_memory_bytes > 1.5 * 1024 * 1024 * 1024

# Memory growth: more than 10 MiB over 5 minutes
delta(process_resident_memory_bytes[5m]) > 10 * 1024 * 1024

# Garbage collections per second, by generation
rate(python_gc_collections_total[5m])
```

On Kubernetes, the container's own metrics (cAdvisor, kube-state-metrics) compare
memory with the limit, with nothing to add to the app:

```promql
sum by (pod) (container_memory_working_set_bytes{container="fraiseql"})
  / sum by (pod) (kube_pod_container_resource_limits{container="fraiseql", resource="memory"}) > 0.8
```

### Log Entries

FraiseQL logs nothing about memory. An OOM kill shows in the platform's events
(`kubectl describe pod`, `docker inspect --format '{{.State.OOMKilled}}'`, the
kernel log), not in the app's logs.

---

## 🔍 Diagnostic Steps

### Step 1: Check Current Memory Usage

**Via Prometheus** (with `ProcessCollector` registered as above):

```promql
# Current memory usage
process_resident_memory_bytes

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
Prometheus metrics with a `ProcessCollector`.

```bash
curl http://localhost:8000/health
# {"status": "healthy", "service": "fraiseql"}
```

### Step 2: Identify Memory Consumers

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

**Common consumers in a FraiseQL app**:

- Large list queries: a `find()` without `limit` builds the whole result in memory
  (check the resolvers, and the `limit` arguments clients send).
- The in-memory APQ store (`apq_storage_backend="memory"`, the default) keeps every
  persisted query, and with `apq_cache_responses=True` every cached response, for
  the life of the process.
- The in-memory rate limit counters, one entry per client key.

### Step 3: Check for Memory Leaks

**Python Garbage Collection Stats** (with `GCCollector` registered):

```promql
# GC collection frequency, by generation
rate(python_gc_collections_total[5m])

# Uncollectable objects (memory leak indicator)
python_gc_objects_uncollectable_total
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

**Via Prometheus** (only if the app feeds the pool gauges with
`update_db_connections`, see [Metrics](./README.md#metrics-quick-reference)):

```promql
fraiseql_db_connections_active
fraiseql_db_connections_idle
fraiseql_db_connections_total
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

FraiseQL has no request or response size metric; sizes show in your proxy's access
log. Slow requests, which hold their results in memory longer, show in the duration
histogram:

```promql
histogram_quantile(0.95,
  sum by (le, endpoint) (rate(fraiseql_http_request_duration_seconds_bucket[5m]))
)
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

These need the `ProcessCollector` and `GCCollector` registered on FraiseQL's
registry (see Symptoms); the first two use Kubernetes container metrics instead.

```yaml
# alerts/memory.yml
groups:
  - name: memory_usage
    interval: 30s
    rules:
      - alert: HighMemoryUsage
        expr: |
          sum by (pod) (container_memory_working_set_bytes{container="fraiseql"})
          / sum by (pod) (kube_pod_container_resource_limits{container="fraiseql", resource="memory"}) > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High memory usage (> 80% of the limit)"
          description: "Memory usage: {{ $value | humanizePercentage }}"

      - alert: CriticalMemoryUsage
        expr: |
          sum by (pod) (container_memory_working_set_bytes{container="fraiseql"})
          / sum by (pod) (kube_pod_container_resource_limits{container="fraiseql", resource="memory"}) > 0.9
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Critical memory usage (> 90% of the limit)"
          description: "Memory usage: {{ $value | humanizePercentage }} - OOM risk!"

      - alert: MemoryLeak
        expr: |
          delta(process_resident_memory_bytes[30m]) > 10 * 1024 * 1024  # 10 MiB growth per 30min
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Potential memory leak detected"
          description: "Memory grew {{ $value | humanize1024 }}B in 30 minutes"

      - alert: ExcessiveGarbageCollection
        expr: |
          sum by (instance) (rate(python_gc_collections_total[5m])) > 10
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

**2. Memory Usage Against the Limit** (Kubernetes):

```promql
sum by (pod) (container_memory_working_set_bytes{container="fraiseql"})
  / sum by (pod) (kube_pod_container_resource_limits{container="fraiseql", resource="memory"})
```

**3. Memory Growth Rate**:

```promql
deriv(process_resident_memory_bytes[10m])
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
# Memory should not be growing: < 1 MiB over 10 minutes
delta(process_resident_memory_bytes[10m]) < 1024 * 1024
```

### 2. Load Test

```bash
# Run load test for 10 minutes
ab -n 10000 -c 100 http://localhost:8000/graphql

# Monitor memory during test
watch -n 5 'curl -s http://localhost:8000/metrics | grep process_resident_memory'

# Memory should stabilize, not grow continuously
```

### 3. Check the Platform

```bash
# No new OOM kills (Kubernetes)
kubectl get pods -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.containerStatuses[0].lastState.terminated.reason}{"\n"}{end}'

# Should show no recent "OOMKilled"
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

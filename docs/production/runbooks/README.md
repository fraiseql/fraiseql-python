# FraiseQL Operational Runbooks

**Last Updated**: 2026-10-25
**Status**: Production-Ready

---

## 📋 Overview

This directory contains operational runbooks for diagnosing and resolving common production incidents in FraiseQL applications. Each runbook provides step-by-step guidance for:

- Symptom identification
- Root cause diagnosis
- Resolution steps (immediate, short-term, long-term)
- Monitoring and alerts
- Post-incident review

---

## 📚 Available Runbooks

### 🗄️ Database & Performance

#### [Database Performance Degradation](./database-performance-degradation.md)

**Severity**: HIGH | **MTTR**: 15 minutes

**When to use**:

- GraphQL queries taking > 5 seconds
- Database connection pool exhausted
- Query timeout errors
- High database CPU usage

**Key Metrics**:

```promql
# Request latency, p95
histogram_quantile(0.95, sum by (le) (rate(fraiseql_http_request_duration_seconds_bucket[5m])))

# Pool use (only if the app feeds the pool gauges, see Metrics below)
fraiseql_db_connections_active / fraiseql_db_connections_total
```

**Quick Actions**:

1. Check query duration metrics
2. Identify slow queries in PostgreSQL
3. Add missing indexes
4. Optimize connection pool settings

---

#### [High Memory Usage](./high-memory-usage.md)

**Severity**: HIGH | **MTTR**: 20 minutes

**When to use**:

- Application memory usage > 80%
- OOMKilled events in logs
- Memory growing over time
- Application slowness

**Key Metrics**:

```promql
# Resident memory (only if the app registers a ProcessCollector, see Metrics below)
process_resident_memory_bytes

# Memory growth rate
deriv(process_resident_memory_bytes[10m])
```

**Quick Actions**:

1. Check current memory usage
2. Identify memory consumers
3. Force garbage collection
4. Reduce connection pool size temporarily

---

### 🔒 Security

#### [Rate Limiting Triggered](./rate-limiting-triggered.md)

**Severity**: MEDIUM | **MTTR**: 10 minutes

**When to use**:

- Users receiving 429 Too Many Requests
- Spike in rate limit violations
- Legitimate traffic being blocked
- Suspected abuse patterns

**Key Metrics**:

```promql
# Rate-limited requests (FraiseQL has no rate-limit metric; count the 429s)
sum by (endpoint) (rate(fraiseql_http_requests_total{status="429"}[5m]))

# Top rejected clients: from the "rate_limit.exceeded" security log entries
```

**Quick Actions**:

1. Identify affected users/IPs
2. Classify traffic (legitimate vs. abuse)
3. Temporarily increase limits or whitelist
4. Block abusive IPs

---

#### [Authentication Failures](./authentication-failures.md)

**Severity**: HIGH | **MTTR**: 15 minutes

**When to use**:

- Spike in 401/403 errors
- Users unable to log in
- Token validation failures
- Suspected brute force attack

**Key Metrics**:

```promql
# Rejected requests (FraiseQL has no auth metric; count the 401s)
sum(rate(fraiseql_http_requests_total{status="401"}[5m]))

# Failure reasons: from the "auth.*" security log entries
```

**Quick Actions**:

1. Check failure reasons (expired, invalid, missing)
2. Verify JWT secret consistency
3. Block brute force attackers
4. Check auth service health

---

### 🚨 Attacks & DoS

#### [GraphQL Query DoS](./graphql-query-dos.md)

**Severity**: CRITICAL | **MTTR**: 10 minutes

**When to use**:

- Sudden spike in query execution time
- Expensive/complex queries detected
- CPU/memory exhaustion
- Database overload

**Key Metrics**:

```promql
# Average request duration on /graphql
sum(rate(fraiseql_http_request_duration_seconds_sum{endpoint="/graphql"}[5m]))
  / sum(rate(fraiseql_http_request_duration_seconds_count{endpoint="/graphql"}[5m]))

# Rejected queries: from the "query.depth_exceeded" / "query.complexity_exceeded"
# security log entries (there is no metric for them)
```

**Quick Actions**:

1. Enable query complexity limits
2. Block attacking user/IP
3. Kill long-running queries
4. Implement query depth limiting

---

## 🎯 Quick Reference

### Severity Levels

| Severity | Description | MTTR Target | Example |
|----------|-------------|-------------|---------|
| **CRITICAL** | Service down or severely degraded | 10 minutes | GraphQL DoS, complete auth failure |
| **HIGH** | Significant impact to users | 15-20 minutes | Database degradation, high memory |
| **MEDIUM** | Limited impact, workarounds available | 30 minutes | Rate limiting issues |
| **LOW** | Minor issues, no immediate impact | 1-2 hours | Warning threshold breaches |

### Common Symptoms → Runbooks

| Symptom | Likely Runbook | Quick Check |
|---------|---------------|-------------|
| Queries timing out | [Database Performance](./database-performance-degradation.md) | Check `fraiseql_http_request_duration_seconds`, `pg_stat_activity` |
| 429 errors | [Rate Limiting](./rate-limiting-triggered.md) | Check `fraiseql_http_requests_total{status="429"}` |
| 401/403 errors | [Authentication](./authentication-failures.md) | Check `fraiseql_http_requests_total{status="401"}` |
| OOMKilled | [Memory Usage](./high-memory-usage.md) | Check the container's memory metrics |
| CPU spike | [GraphQL DoS](./graphql-query-dos.md) | Check `fraiseql_http_request_duration_seconds{endpoint="/graphql"}` |

### Metrics Quick Reference

These are the Prometheus metrics FraiseQL has; the queries in every runbook use
only them. `create_fraiseql_app` doesn't turn them on: call `setup_metrics(app)`
(it needs `prometheus_client`), which adds `MetricsMiddleware` and a `GET /metrics`
endpoint.

```python
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.monitoring import setup_metrics

app = create_fraiseql_app(database_url="postgresql://localhost/mydb", types=[User], queries=[users])
metrics = setup_metrics(app)
```

**Recorded on every request** (except `/metrics`, `/health`, `/ready`, `/startup`):

| Metric | Type | Labels |
|--------|------|--------|
| `fraiseql_http_requests_total` | counter | `method`, `endpoint` (the path), `status` |
| `fraiseql_http_request_duration_seconds` | histogram | `method`, `endpoint` |
| `fraiseql_response_time_seconds` | histogram | none |
| `fraiseql_errors_total` | counter | `error_type`, `error_code`, `operation`: an exception that escaped the app (`error_code="HTTP_ERROR"`, counted as status `500`) |

A GraphQL error in the response body (a failed resolver, a query over the depth
or complexity limit) doesn't change the HTTP status, so it shows up in none of
these.

**Recorded only when your code records them** (nothing in FraiseQL does):

| Metric | How it gets values |
|--------|--------------------|
| `fraiseql_graphql_queries_total`, `fraiseql_graphql_queries_success_total`, `fraiseql_graphql_queries_errors_total`, `fraiseql_graphql_query_duration_seconds` | functions decorated with `@with_metrics("query")` or `@with_metrics("mutation")` (labels `operation_type`, `operation_name` = the function name), or `metrics.record_query(...)` |
| `fraiseql_db_connections_active`, `_idle`, `_total` | `metrics.update_db_connections(active, idle, total)`; they read 0 otherwise |
| `fraiseql_db_queries_total`, `fraiseql_db_query_duration_seconds` | `metrics.record_db_query(...)` |
| `fraiseql_graphql_mutations_total`, `fraiseql_graphql_mutations_success_total`, `fraiseql_graphql_mutations_errors_total`, `fraiseql_graphql_mutation_duration_seconds` | `metrics.record_mutation(...)` |
| `fraiseql_cache_hits_total`, `fraiseql_cache_misses_total` | `metrics.record_cache_hit(...)` / `record_cache_miss(...)` |

To feed the pool gauges, sample the app's psycopg pool (`get_db_pool()` from
`fraiseql.fastapi.dependencies`, once the app has started) from a background task:

```python
import asyncio


async def report_pool(pool, metrics) -> None:
    while True:
        stats = pool.get_stats()
        size, idle = stats.get("pool_size", 0), stats.get("pool_available", 0)
        metrics.update_db_connections(active=size - idle, idle=idle, total=size)
        await asyncio.sleep(15)
```

**Not exported**: there are no metrics for authentication, rate limiting, query
complexity or memory. `/metrics` serves FraiseQL's own registry, without the
`process_*` metrics of `prometheus_client`'s default registry; add them with
`ProcessCollector(registry=metrics.registry)` (from `prometheus_client`), or use
your platform's container metrics. Database metrics come from PostgreSQL itself
(`pg_stat_activity`, `pg_stat_statements`) or an exporter of your own.

**Core health queries**:

```promql
# Request rate
sum(rate(fraiseql_http_requests_total[5m]))

# 5xx rate
sum(rate(fraiseql_http_requests_total{status=~"5.."}[5m]))

# Unhandled exceptions, by type
sum by (error_type) (rate(fraiseql_errors_total[5m]))

# Response time p95
histogram_quantile(0.95, sum by (le) (rate(fraiseql_response_time_seconds_bucket[5m])))

# Rejected requests: 401 (authentication), 429 (rate limiting)
sum by (status) (rate(fraiseql_http_requests_total{status=~"401|429"}[5m]))
```

---

## 🔧 General Troubleshooting Workflow

### Step 1: Identify the Incident (2 minutes)

1. **Check Monitoring Dashboards**:
   - Your Prometheus (and the Grafana panels you built on the metrics above)

2. **Check Alert Notifications**:
   - PagerDuty/Slack alerts
   - Email notifications

3. **Classify Severity**:
   - CRITICAL: Service down, use-case broken
   - HIGH: Significant degradation
   - MEDIUM: Partial impact
   - LOW: Warning threshold

### Step 2: Gather Context (3 minutes)

1. **Check Metrics** (Prometheus):

   ```promql
   # Request rate
   rate(fraiseql_http_requests_total[5m])

   # Error rate
   rate(fraiseql_errors_total[5m])

   # Response time
   histogram_quantile(0.95, rate(fraiseql_response_time_seconds_bucket[5m]))
   ```

2. **Check Logs** (Structured):

   ```bash
   # Recent errors
   jq -r 'select(.level == "ERROR")' /var/log/fraiseql/app.log | tail -20

   # Recent warnings
   jq -r 'select(.level == "WARNING")' /var/log/fraiseql/app.log | tail -50
   ```

3. **Check Recent Changes**:

   ```bash
   # Recent deployments
   git log --since="2 hours ago" --oneline

   # Recent config changes
   kubectl get events --sort-by='.lastTimestamp' | head -20
   ```

### Step 3: Select Runbook

Based on symptoms, choose the appropriate runbook:

- [Database Performance](./database-performance-degradation.md)
- [High Memory Usage](./high-memory-usage.md)
- [Rate Limiting](./rate-limiting-triggered.md)
- [Authentication Failures](./authentication-failures.md)
- [GraphQL DoS](./graphql-query-dos.md)

### Step 4: Execute Runbook

Follow the selected runbook's steps:

1. Diagnostic Steps
2. Immediate Actions
3. Short-Term Fixes
4. Verification
5. Post-Incident Review

### Step 5: Document and Review

After incident resolution:

1. Create incident report
2. Update runbook if needed
3. Schedule post-mortem
4. Implement preventive measures

---

## 📊 Monitoring Setup

### Prometheus Alerts

Each runbook lists alert rules in a `groups:` block. FraiseQL ships no alert files:
copy the rules you want into a rules file of your own, list it under `rule_files`
in `prometheus.yml`, and reload Prometheus:

```bash
curl -X POST http://prometheus:9090/-/reload  # needs --web.enable-lifecycle
```

### Grafana Dashboards

There is no FraiseQL operational dashboard to import. Build panels from the
queries in each runbook's "Grafana Dashboard Panels" section, with your Prometheus
as the data source.

### Structured Logging

fraiseql logs through the standard `logging` module, on loggers named `fraiseql.*`
(security events on `fraiseql.security`); it doesn't install handlers or choose a
format. Write them as JSON lines with a formatter of your own (or a library such as
python-json-logger):

```python
import json
import logging


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": self.formatTime(record),
                "level": record.levelname,
                "logger": record.name,
                "event": record.getMessage(),
            }
        )


handler = logging.FileHandler("/var/log/fraiseql/app.log")
handler.setFormatter(JSONFormatter())
fraiseql_logger = logging.getLogger("fraiseql")
fraiseql_logger.addHandler(handler)
fraiseql_logger.setLevel(logging.INFO)
```

Query logs with `jq`:

```bash
# Find errors
jq -r 'select(.level == "ERROR")' /var/log/fraiseql/app.log

# Security events: the message is the event as JSON
jq -r 'select(.logger == "fraiseql.security") | .event | fromjson | .event_type' \
  /var/log/fraiseql/app.log | sort | uniq -c | sort -rn
```

The security events FraiseQL logs are `auth.success`, `auth.failure`,
`auth.token_expired`, `auth.token_invalid` (from `Auth0Provider`),
`rate_limit.exceeded`, `query.depth_exceeded`, `query.complexity_exceeded` and
`query.timeout`. The `fraiseql.security` logger also writes them to
`security_events.log` in the working directory (`FRAISEQL_SECURITY_LOG_PATH`) and
to stderr, as `<time> - fraiseql.security - <LEVEL> - <event JSON>` lines.

---

## 🆘 Escalation Paths

### Level 1: On-Call Engineer (You)

- Follow applicable runbook
- Gather diagnostics
- Attempt immediate fixes
- **Escalate if**: Issue persists after 30 minutes

### Level 2: Subject Matter Expert

- **Database Issues** → DBA Team
- **Security Issues** → Security Team
- **Infrastructure Issues** → Platform Team
- **Code Issues** → Engineering Team
- **Escalate if**: Root cause unclear or fix requires expertise

### Level 3: Engineering Manager

- **Critical Production Outage** → Immediate escalation
- **Security Incident** → Immediate escalation
- **Data Loss Risk** → Immediate escalation

### Emergency Contacts

| Role | Contact | When to Contact |
|------|---------|----------------|
| DBA On-Call | [Phone/Slack] | Database performance, corruption |
| Security On-Call | [Phone/Slack] | Security incidents, breaches |
| Platform On-Call | [Phone/Slack] | Infrastructure, networking |
| Engineering Manager | [Phone/Slack] | Critical outages, escalations |

---

## 📚 Additional Resources

### FraiseQL Documentation

- [Production Deployment Guide](../deployment.md)
- [Monitoring & Observability](../monitoring.md)
- [Security Best Practices](../security.md)
- [Health Checks](../health-checks.md)

### PostgreSQL Resources

- [Performance Tuning](https://wiki.postgresql.org/wiki/Performance_Optimization)
- [Monitoring](https://www.postgresql.org/docs/current/monitoring.html)
- [Troubleshooting](https://wiki.postgresql.org/wiki/Troubleshooting)

### Prometheus & Grafana

- [Prometheus Querying](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Grafana Dashboards](https://grafana.com/docs/grafana/latest/dashboards/)
- [Alert Rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)

---

## 🔄 Runbook Maintenance

### Review Schedule

- **Monthly**: Review metrics and thresholds
- **Quarterly**: Update runbooks based on incidents
- **After Major Incidents**: Update relevant runbook

### Contribution Process

1. Test runbook steps in staging
2. Create PR with updates
3. Review with ops team
4. Merge and deploy

### Version Control

Each runbook includes:

- **Version**: Semantic version number
- **Last Tested**: Date of last verification
- **Next Review**: Scheduled review date

---

## 📝 Feedback

Have suggestions for improving these runbooks?

- **GitHub Issues**: Create an issue in the FraiseQL repository
- **Slack**: #fraiseql-ops channel
- **Email**: ops-team@example.com

---

**Runbooks Status**: ✅ Production-Ready
**Coverage**: 5 critical scenarios
**Last Updated**: 2026-10-25
**Total Documentation**: ~4,000 lines
**MTTR Targets**: 10-20 minutes

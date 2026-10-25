# FraiseQL Operational Runbooks

**Last Updated**: 2025-12-29
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
# Query duration
fraiseql_db_query_duration_seconds

# Connection pool utilization
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
# Memory usage percentage
(process_resident_memory_bytes / node_memory_MemTotal_bytes) * 100

# Memory growth rate
rate(process_resident_memory_bytes[10m])
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
# Rate limit violations
rate(fraiseql_rate_limit_exceeded_total[5m])

# Top violators
topk(10, sum by (user_id) (fraiseql_rate_limit_exceeded_total))
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
# Auth failure rate
rate(fraiseql_auth_failures_total[5m])

# Failures by reason
sum by (failure_reason) (rate(fraiseql_auth_failures_total[5m]))
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
# Query duration spike
avg(rate(fraiseql_graphql_query_duration_seconds_sum[5m]))

# Query complexity violations
rate(fraiseql_graphql_query_complexity_exceeded_total[5m])
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
| Queries timing out | [Database Performance](./database-performance-degradation.md) | Check `fraiseql_db_query_duration_seconds` |
| 429 errors | [Rate Limiting](./rate-limiting-triggered.md) | Check `fraiseql_rate_limit_exceeded_total` |
| 401/403 errors | [Authentication](./authentication-failures.md) | Check `fraiseql_auth_failures_total` |
| OOMKilled | [Memory Usage](./high-memory-usage.md) | Check `process_resident_memory_bytes` |
| CPU spike | [GraphQL DoS](./graphql-query-dos.md) | Check `fraiseql_graphql_query_duration_seconds` |

### Metrics Quick Reference

**Core Health Metrics**:

```promql
# Overall request rate
rate(fraiseql_http_requests_total[5m])

# Error rate
rate(fraiseql_errors_total[5m])

# Response time p95
histogram_quantile(0.95, rate(fraiseql_response_time_seconds_bucket[5m]))
```

**Database Metrics**:

```promql
# Query duration
fraiseql_db_query_duration_seconds

# Connection pool
fraiseql_db_connections_active
fraiseql_db_connections_idle
fraiseql_db_connections_total
```

**Security Metrics**:

```promql
# Auth failures
rate(fraiseql_auth_failures_total[5m])

# Rate limit violations
rate(fraiseql_rate_limit_exceeded_total[5m])
```

**Performance Metrics**:

```promql
# Memory usage
process_resident_memory_bytes

# CPU usage
rate(process_cpu_seconds_total[5m])

# GraphQL query duration
fraiseql_graphql_query_duration_seconds
```

---

## 🔧 General Troubleshooting Workflow

### Step 1: Identify the Incident (2 minutes)

1. **Check Monitoring Dashboards**:
   - Grafana: http://grafana.example.com/d/fraiseql
   - Prometheus: http://prometheus.example.com

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

All runbooks include Prometheus alert rules. To import:

```bash
# Copy alert files to Prometheus
cp docs/production/runbooks/alerts/*.yml /etc/prometheus/alerts/

# Reload Prometheus
curl -X POST http://prometheus:9090/-/reload
```

### Grafana Dashboards

Import the FraiseQL operational dashboard:

```bash
# Import dashboard JSON
curl -X POST http://grafana:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -d @docs/production/runbooks/grafana/fraiseql-ops.json
```

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

# Find specific events
jq -r 'select(.event == "database.slow_query")' /var/log/fraiseql/app.log

# Count events by type
jq -r '.event' /var/log/fraiseql/app.log | sort | uniq -c | sort -rn
```

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
**Last Updated**: 2025-12-29
**Total Documentation**: ~4,000 lines
**MTTR Targets**: 10-20 minutes

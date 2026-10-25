# GraphQL Query DoS Runbook

**Last Updated**: 2025-12-29
**Severity**: CRITICAL
**MTTR Target**: 10 minutes

---

## 📋 Overview

This runbook guides you through detecting, mitigating, and preventing GraphQL query-based Denial of Service (DoS) attacks. GraphQL's flexible query language can be exploited to create expensive queries that consume excessive resources.

---

## 🚨 Symptoms

### Primary Indicators

- Sudden spike in query execution time
- High CPU usage (> 90%)
- Database connection pool exhaustion
- Query timeout errors
- Application unresponsiveness
- Memory usage climbing rapidly

### Prometheus Metrics to Monitor

```promql
# Query execution time spike
avg(rate(fraiseql_graphql_query_duration_seconds_sum[5m])
    / rate(fraiseql_graphql_query_duration_seconds_count[5m])) > 10

# High query timeout rate
rate(fraiseql_errors_total{error_code="QUERY_TIMEOUT"}[5m]) > 1

# Database CPU usage
rate(pg_stat_database_blks_read[5m]) > 1000

# Expensive query patterns (deep nesting, large limits)
fraiseql_graphql_query_complexity_total > 1000
```

### Structured Logs Examples

```json
{
  "timestamp": "2025-12-29T13:45:10.123Z",
  "level": "WARNING",
  "event": "graphql.expensive_query",
  "message": "Query complexity exceeds threshold",
  "context": {
    "user_id": "user_attack",
    "ip_address": "192.0.2.50",
    "query_complexity": 1500,
    "max_complexity": 1000,
    "query_depth": 8,
    "max_depth": 5,
    "query_hash": "abc123def456"
  },
  "trace_id": "trace_dos123"
}
```

```json
{
  "timestamp": "2025-12-29T13:45:15.456Z",
  "level": "ERROR",
  "event": "database.query_timeout",
  "message": "Query exceeded timeout limit",
  "context": {
    "user_id": "user_attack",
    "query_duration_ms": 30000,
    "timeout_ms": 30000,
    "query_type": "SELECT",
    "table_name": "users",
    "rows_examined": 1000000
  },
  "trace_id": "trace_dos456"
}
```

```json
{
  "timestamp": "2025-12-29T13:45:20.789Z",
  "level": "CRITICAL",
  "event": "security.dos_detected",
  "message": "Potential DoS attack detected",
  "context": {
    "user_id": "user_attack",
    "ip_address": "192.0.2.50",
    "expensive_queries_count": 10,
    "time_window_seconds": 60,
    "action": "automatic_block"
  },
  "trace_id": "trace_dos789"
}
```

---

## 🔍 Diagnostic Steps

### Step 1: Identify Attack Pattern

**Via Prometheus - Query Complexity**:

```promql
# Top users by query complexity
topk(10,
  sum by (user_id) (fraiseql_graphql_query_complexity_total)
)

# Queries with deep nesting
count(fraiseql_graphql_query_depth > 5)

# Large result set requests
count(fraiseql_graphql_query_limit > 1000)
```

**Via Structured Logs**:

```bash
# Find expensive queries in last 10 minutes
jq -r 'select(.event == "graphql.expensive_query") |
  "\(.timestamp) \(.context.user_id) complexity=\(.context.query_complexity) depth=\(.context.query_depth)"' \
  /var/log/fraiseql/app.log | tail -50

# Find query timeouts
jq -r 'select(.event == "database.query_timeout") |
  "\(.timestamp) \(.context.user_id) \(.context.query_duration_ms)ms"' \
  /var/log/fraiseql/app.log | tail -50

# Identify attack source
jq -r 'select(.event == "graphql.expensive_query") |
  .context.user_id + " " + .context.ip_address' \
  /var/log/fraiseql/app.log | sort | uniq -c | sort -rn | head -10
```

### Step 2: Analyze Query Patterns

**Common Attack Patterns**:

**1. Deep Nesting (Circular Queries)**:

```graphql
# Attack query - deeply nested relationships
query {
  users {
    posts {
      comments {
        author {
          posts {
            comments {
              author {
                posts {
                  # ... continues deep
                }
              }
            }
          }
        }
      }
    }
  }
}
```

**2. Large Batch Requests**:

```graphql
# Attack query - requesting huge result sets
query {
  users(limit: 10000) {
    id
    name
    posts(limit: 10000) {
      id
      comments(limit: 10000) {
        id
      }
    }
  }
}
# Potentially returns 10,000 * 10,000 * 10,000 = 1 trillion items!
```

**3. Expensive Field Combinations**:

```graphql
# Attack query - combining expensive computed fields
query {
  users {
    id
    expensiveCalculation1  # Takes 1s per user
    expensiveCalculation2  # Takes 1s per user
    expensiveCalculation3  # Takes 1s per user
  }
}
```

**Extract Query from Logs**:

```bash
# Get actual query that caused issue
jq -r 'select(.event == "graphql.expensive_query" and .context.user_id == "user_attack") |
  .context.query // .context.query_hash' \
  /var/log/fraiseql/app.log | head -1
```

### Step 3: Check System Resources

**Database Load**:

```sql
-- Check active queries
SELECT
  pid,
  usename,
  query_start,
  state,
  left(query, 100) AS query_preview
FROM pg_stat_activity
WHERE state = 'active'
ORDER BY query_start;

-- Check database CPU and I/O
SELECT
  datname,
  blks_read,
  blks_hit,
  tup_returned,
  tup_fetched
FROM pg_stat_database
WHERE datname = current_database();
```

**Application Resources**:

```promql
# CPU usage
rate(process_cpu_seconds_total[5m])

# Memory usage
process_resident_memory_bytes

# Active connections
fraiseql_db_connections_active
```

### Step 4: Determine Attack vs. Misconfiguration

**Attack Indicators**:

- Same user/IP sending many expensive queries
- Queries with unusual complexity
- Sudden pattern change (normal → expensive)
- Distributed source IPs (coordinated attack)

**Misconfiguration Indicators**:

- Frontend sending overly broad queries
- Integration fetching unnecessary data
- Missing pagination in production code
- Recent deployment with bad queries

```bash
# Check if recent deployment
git log --since="1 hour ago" --oneline

# Check if queries match known frontend patterns
jq -r 'select(.event == "graphql.expensive_query") | .context.query_hash' \
  /var/log/fraiseql/app.log | sort | uniq -c | sort -rn

# High count of same query_hash = likely misconfiguration
# Many different query_hashes = likely attack
```

---

## 🔧 Resolution Steps

### Immediate Actions (< 5 minutes)

#### 1. Throttle GraphQL Traffic

Cap query depth and size: with `FRAISEQL_MAX_QUERY_DEPTH` (or `max_query_depth`) and
`FRAISEQL_COMPLEXITY_MAX_SCORE` (or `complexity_max_score`) set, a deeper or costlier
query gets a `QUERY_TOO_DEEP` / `QUERY_TOO_COMPLEX` GraphQL error before any resolver
or SQL runs. No limit is on by default, and the settings are read at startup, so
restart the app after changing them. Rate limiting, statement timeouts (below) and
argument caps in resolvers are the other levers.

`RateLimitMiddleware` counts requests per client (`request.state.user_id` when set,
otherwise the IP) for each rule's path and for every request (`default_limit`). On
the GraphQL endpoint it also limits each client per operation type (100 queries,
20 mutations a minute) and per estimated cost tier (200 cheap, 100 medium, 20
expensive requests a minute). Over a limit, the client gets a 429 with `Retry-After`:

```python
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.security import RateLimit, RateLimitMiddleware, RateLimitRule

app = create_fraiseql_app(database_url="postgresql://localhost/mydb", types=[User], queries=[users])

# Emergency strict limits
app.add_middleware(
    RateLimitMiddleware,
    rules=[RateLimitRule(path_pattern="/graphql", rate_limit=RateLimit(requests=30, window=60))],
    default_limit=RateLimit(requests=100, window=60),
)
```

The counters live in process memory, one set per instance; pass
`store=RedisRateLimitStore(redis_client)` to share them. Changing the limits means a
redeploy.

#### 2. Block Attacking User/IP

fraiseql has no block list. Block an IP at the edge:

```bash
# Firewall, or the equivalent deny rule on your ingress / load balancer / WAF
sudo iptables -A INPUT -s 192.0.2.50 -j DROP
```

Block an authenticated user with an operation authorizer, which runs before every
top-level query and mutation field:

```python
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.security import AuthorizationDecision

BLOCKED_USER_IDS = {"7d0c3c4e-0000-4000-8000-000000000001"}


class BlockedUserAuthorizer:
    async def authorize_operation(self, *, context, operation_type, operation_name, arguments):
        user = context.get("user")
        if user is not None and str(user.user_id) in BLOCKED_USER_IDS:
            return AuthorizationDecision.deny(code="BLOCKED", message="Access suspended")
        return True


app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users],
    auth=auth_provider,
    authorizer=BlockedUserAuthorizer(),
)
```

A blocked user's operations come back with a `BLOCKED` error. The set above changes
with a redeploy; read it from a table instead to block without one.

#### 3. Kill Long-Running Queries

```sql
-- Find long-running GraphQL queries
SELECT
  pid,
  query_start,
  state,
  query
FROM pg_stat_activity
WHERE state = 'active'
  AND query_start < now() - interval '10 seconds'
  AND query LIKE '%graphql%';

-- Kill specific queries
SELECT pg_cancel_backend(<pid>);

-- Force terminate if cancel doesn't work
SELECT pg_terminate_backend(<pid>);
```

### Short-Term Fixes (5-15 minutes)

#### 1. Limit Query Depth

A fraiseql type's nested fields are keys of the JSONB `data` column its view builds,
so a client can only nest as deep as that column goes. Keep cycles out of the views
(a post embedding its author embedding their posts...), and nested selections stay
bounded by the view, not by the client.

#### 2. Reject Expensive Queries in the Resolver

`fraiseql.validation.validate_query_complexity` scores the selection under a resolver:
1 per field (or the cost you give it in `field_costs`), multiplied by 10 under each
field whose name ends in "s":

```python
import fraiseql
from graphql import GraphQLError

from fraiseql.validation import validate_query_complexity


@fraiseql.query
async def users(info, limit: int = 100) -> list[User]:
    score, errors = validate_query_complexity(
        info,
        max_complexity=200,
        field_costs={"posts": 10},  # Expensive relationship
    )
    if errors:
        raise GraphQLError(errors[0])

    db = info.context["db"]
    return await db.find("v_user", limit=limit)
```

#### 3. Implement Query Timeout Enforcement

`query_timeout` (seconds, default 30) becomes a `SET LOCAL statement_timeout` on the
statements the repository runs through `db.run()` and on mutation functions
(`execute_function`), so PostgreSQL cancels one that runs longer:

```python
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    query_timeout=10,  # seconds
)
app = create_fraiseql_app(config=config, types=[User], queries=[users])
```

```bash
# Or, when the app is built from a FraiseQLConfig as above
export FRAISEQL_QUERY_TIMEOUT=10
```

`find()`, `find_one()` and the other reads don't get it, so bound every statement
the app sends with a timeout on its database role as well; new pool connections
pick it up:

```sql
ALTER ROLE app_user SET statement_timeout = '10s';
```

#### 4. Implement Pagination Enforcement

```python
import fraiseql


@fraiseql.query
async def users(info, limit: int = 100, offset: int = 0) -> list[User]:
    # Enforce maximum limit
    if limit > 1000:
        raise ValueError("Limit cannot exceed 1000")

    # Refuse very deep offsets (PostgreSQL still reads the skipped rows)
    if offset > 10000:
        raise ValueError("Offset cannot exceed 10000; narrow the query with where instead")

    db = info.context["db"]
    return await db.find("v_user", order_by=[{"id": "ASC"}], limit=limit, offset=offset)
```

### Long-Term Solutions (1+ days)

#### 1. Implement Operation Allowlisting

An operation authorizer can allow only the top-level fields (and argument values) you
expect, and deny the rest:

```python
ALLOWED_OPERATIONS = {
    ("query", "users"),
    ("query", "user"),
    ("mutation", "createUser"),
}


class AllowListAuthorizer:
    async def authorize_operation(self, *, context, operation_type, operation_name, arguments):
        if (operation_type, operation_name) not in ALLOWED_OPERATIONS:
            return False
        # Cap list sizes for every client, whatever the resolver does
        return arguments.get("limit", 0) <= 100


app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users, user],
    mutations=[create_user],
    authorizer=AllowListAuthorizer(),
)
```

`operation_name` is the top-level field's GraphQL name; `arguments` are its
arguments. See [Authorization](../../security/authorization.md).

#### 2. Persisted Queries

Automatic persisted queries (APQ, on by default: `apq_mode="optional"`) let clients
send a query's hash instead of its text, and with `apq_cache_responses=True` serve
cached responses. They save bandwidth and parsing, but they don't restrict which
queries run: with `apq_mode="required"`, requests without a hash are rejected, yet a
client that sends a new query together with its hash registers and runs it.

#### 3. Compose Related Rows in the View (N+1 Prevention)

A fraiseql query reads one view: embed related rows in its `data` JSONB and the whole
tree comes back from a single SQL statement:

```sql
CREATE VIEW v_post AS
SELECT
    p.id,
    jsonb_build_object(
        'id', p.id,
        'title', p.title,
        'comments', COALESCE(
            (SELECT jsonb_agg(jsonb_build_object('id', c.id, 'body', c.body) ORDER BY c.created_at)
             FROM tb_comment c
             WHERE c.fk_post = p.pk_post),
            '[]'::jsonb
        )
    ) AS data
FROM tb_post p;
```

```python
import fraiseql
from fraiseql.types import ID


@fraiseql.type
class Comment:
    id: ID
    body: str


@fraiseql.type(sql_source="v_post", jsonb_column="data")
class Post:
    id: ID
    title: str
    comments: list[Comment]


@fraiseql.query
async def posts(info, limit: int = 20) -> list[Post]:
    db = info.context["db"]
    return await db.find("v_post", limit=limit)
```

---

## 📊 Monitoring & Alerts

### Prometheus Alert Rules

```yaml
# alerts/graphql_dos.yml
groups:
  - name: graphql_dos
    interval: 30s
    rules:
      - alert: GraphQLQueryDurationSpike
        expr: |
          avg(rate(fraiseql_graphql_query_duration_seconds_sum[5m])
              / rate(fraiseql_graphql_query_duration_seconds_count[5m])) > 10
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "GraphQL query duration spike (avg > 10s)"
          description: "Average query time: {{ $value }}s"

      - alert: GraphQLQueryTimeouts
        expr: |
          rate(fraiseql_errors_total{error_code="QUERY_TIMEOUT"}[5m]) > 1
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "High GraphQL query timeout rate"
          description: "{{ $value }} timeouts/sec"

      - alert: GraphQLComplexityViolations
        expr: |
          rate(fraiseql_graphql_query_complexity_exceeded_total[5m]) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Queries exceeding complexity limits"
          description: "{{ $value }} complex queries/sec"

      - alert: GraphQLDoSDetected
        expr: |
          sum by (user_id) (
            rate(fraiseql_errors_total{error_code="QUERY_TIMEOUT"}[5m])
          ) > 5
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Potential GraphQL DoS from user {{ $labels.user_id }}"
          description: "{{ $value }} timeouts/sec from single user"
```

### Grafana Dashboard Panels

**1. Query Duration Histogram**:

```promql
histogram_quantile(0.95,
  rate(fraiseql_graphql_query_duration_seconds_bucket[5m])
)
```

**2. Query Complexity Distribution**:

```promql
histogram_quantile(0.95,
  rate(fraiseql_graphql_query_complexity_bucket[5m])
)
```

**3. Top Expensive Queries (by user)**:

```promql
topk(10,
  sum by (user_id) (
    rate(fraiseql_graphql_query_duration_seconds_sum[5m])
  )
)
```

**4. Timeout Rate**:

```promql
rate(fraiseql_errors_total{error_code="QUERY_TIMEOUT"}[5m])
```

---

## 🔍 Verification

After applying mitigations, verify the attack is stopped:

### 1. Check Query Duration

```promql
# Should return to normal (< 1s)
avg(rate(fraiseql_graphql_query_duration_seconds_sum[5m])
    / rate(fraiseql_graphql_query_duration_seconds_count[5m]))
```

### 2. Check Timeout Rate

```promql
# Should drop to near zero
rate(fraiseql_errors_total{error_code="QUERY_TIMEOUT"}[5m])
```

### 3. Verify Blocked User

```bash
# Attempt query as blocked user
curl -X POST http://localhost:8000/graphql \
  -H "Authorization: Bearer $BLOCKED_USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ users { id } }"}'

# Should return an error with "extensions": {"code": "BLOCKED"}, and null for the field
```

### 4. Check Logs

```bash
# Verify no recent expensive queries
jq -r 'select(.event == "graphql.expensive_query")' \
  /var/log/fraiseql/app.log | tail -10

# Should see no recent events
```

---

## 📝 Post-Incident Review

After resolving the incident:

1. **Analyze Attack**:
   - Query patterns used
   - Attack source (IPs, users)
   - Entry point (API, frontend)
   - Duration and impact

2. **Implement Permanent Protections**:
   - Rate limits per client and per operation type
   - Complexity checks in the resolvers of expensive queries
   - Views without nesting cycles (bounded depth)
   - Operation allowlisting with an authorizer (if feasible)

3. **Update Monitoring**:
   - Add alerts for complexity violations
   - Monitor query patterns
   - Track query costs by user

4. **Security Improvements**:
   - Review authentication
   - Tighten the rate limits on expensive operations
   - Add WAF rules if applicable

---

## 📚 Related Resources

- [GraphQL Security Best Practices](../security.md#graphql-security)
- [Query Complexity Analysis](../../performance/performance-guide.md)
- [Database Performance](./database-performance-degradation.md)
- [Rate Limiting](./rate-limiting-triggered.md)

---

## 🆘 Escalation

If attack persists after following this runbook:

1. **Gather Evidence**:
   - Sample attack queries
   - User/IP information
   - Metrics screenshots
   - Database query logs

2. **Escalate To**:
   - Security Team (for attack investigation)
   - Infrastructure Team (for DDoS mitigation)
   - Engineering Team (for code-level fixes)

3. **Emergency Contact**:
   - Security On-call: [Contact info]
   - Infrastructure On-call: [Contact info]
   - Engineering Manager: [Contact info]

---

**Version**: 1.0
**Last Tested**: 2025-12-29
**Next Review**: 2026-03-29

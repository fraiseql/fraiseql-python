# GraphQL Query DoS Runbook

**Last Updated**: 2026-10-25
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

FraiseQL has no query complexity or timeout metric. With the metrics middleware
installed (`setup_metrics(app)`, see [Metrics](./README.md#metrics-quick-reference)),
watch the latency and the error statuses of the GraphQL endpoint:

```promql
# Average request duration on /graphql, in seconds
sum(rate(fraiseql_http_request_duration_seconds_sum{endpoint="/graphql"}[5m]))
  / sum(rate(fraiseql_http_request_duration_seconds_count{endpoint="/graphql"}[5m])) > 10

# p99 request duration on /graphql
histogram_quantile(0.99,
  sum by (le) (rate(fraiseql_http_request_duration_seconds_bucket{endpoint="/graphql"}[5m]))
)

# 5xx on /graphql
sum(rate(fraiseql_http_requests_total{endpoint="/graphql", status=~"5.."}[5m]))
```

A query rejected for its depth or complexity, or one PostgreSQL cancels, comes back
as a GraphQL error in an HTTP 200 response, so it doesn't show in these: use the logs.

### Log Entries

With `max_query_depth` or `complexity_max_score` set, each rejected query is logged
on the `fraiseql.security` logger at `WARNING`, as a JSON security event (`metadata`
holds the measured depth or score, the limit, and the start of the query):

```json
{
  "event_type": "query.complexity_exceeded",
  "severity": "warning",
  "timestamp": "2026-10-25T13:45:10.123456+00:00",
  "user_id": null,
  "user_email": null,
  "ip_address": null,
  "user_agent": null,
  "request_id": null,
  "resource": null,
  "action": null,
  "result": null,
  "reason": null,
  "metadata": {"complexity": 1500, "limit": 1000, "query": "{ users { posts { comments { id } } } }"}
}
```

`query.depth_exceeded` has `"depth"` in place of `"complexity"`. A statement that
`query_timeout` cancels in `db.run()` is logged at `ERROR` as `query.timeout`, with
the request's `user_id` and `metadata.error`.

---

## 🔍 Diagnostic Steps

### Step 1: Identify Attack Pattern

**Via Prometheus**:

```promql
# Which paths are slow
topk(5,
  sum by (endpoint) (rate(fraiseql_http_request_duration_seconds_sum[5m]))
)

# Request rate on /graphql
sum(rate(fraiseql_http_requests_total{endpoint="/graphql"}[5m]))
```

The metrics have no user or query label. If your resolvers are decorated with
`@with_metrics("query")`, `fraiseql_graphql_query_duration_seconds` has one series
per resolver (`operation_name`), which names the slow one.

**Via the security log** (`security_events.log`, or wherever your handler writes
the `fraiseql.security` logger):

```bash
# Rejected queries, by kind
grep -oE '"event_type": "query\.(depth|complexity)_exceeded"' security_events.log \
  | sort | uniq -c

# The rejected queries themselves (first 200 characters), most frequent first
grep -E '"query\.(depth|complexity)_exceeded"' security_events.log \
  | grep -o '"query": "[^"]*"' | sort | uniq -c | sort -rn | head -10

# Statements cancelled by the timeout
grep '"query.timeout"' security_events.log | tail -20
```

For the source address, use your access logs (proxy, load balancer, uvicorn).

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

**Extract Query from Logs**: a rejected query's first 200 characters are in its
security event (`metadata.query`, see Step 1). FraiseQL doesn't log the text of the
queries it runs; PostgreSQL has the SQL they became (`pg_stat_activity` below,
`log_min_duration_statement`).

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

**Application Resources**: CPU and memory come from your platform's container
metrics, or from `process_*` metrics if the app registers a `ProcessCollector`; the
pool gauges only if the app feeds them (see [Metrics](./README.md#metrics-quick-reference)):

```promql
# CPU and memory (ProcessCollector registered)
rate(process_cpu_seconds_total[5m])
process_resident_memory_bytes

# Pool in use (update_db_connections fed)
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

# Do the rejected queries match known frontend queries?
grep -E '"query\.(depth|complexity)_exceeded"' security_events.log \
  | grep -o '"query": "[^"]*"' | sort | uniq -c | sort -rn

# High count of one query = likely misconfiguration
# Many different queries = likely attack
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
      - alert: GraphQLRequestDurationSpike
        expr: |
          sum(rate(fraiseql_http_request_duration_seconds_sum{endpoint="/graphql"}[5m]))
          / sum(rate(fraiseql_http_request_duration_seconds_count{endpoint="/graphql"}[5m])) > 10
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "GraphQL request duration spike (avg > 10s)"
          description: "Average request time: {{ $value }}s"

      - alert: GraphQLServerErrors
        expr: |
          sum(rate(fraiseql_http_requests_total{endpoint="/graphql", status=~"5.."}[5m])) > 1
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "GraphQL endpoint answering with 5xx"
          description: "{{ $value }} errors/sec"
```

Rejected and cancelled queries have no metric: alert on the `query.depth_exceeded`,
`query.complexity_exceeded` and `query.timeout` security events in your log stack
(Loki, ELK).

### Grafana Dashboard Panels

**1. GraphQL Request Duration (p95)**:

```promql
histogram_quantile(0.95,
  sum by (le) (rate(fraiseql_http_request_duration_seconds_bucket{endpoint="/graphql"}[5m]))
)
```

**2. GraphQL Request Rate**:

```promql
sum(rate(fraiseql_http_requests_total{endpoint="/graphql"}[5m]))
```

**3. Slowest Resolvers** (resolvers decorated with `@with_metrics("query")`):

```promql
topk(10,
  sum by (operation_name) (rate(fraiseql_graphql_query_duration_seconds_sum[5m]))
  / sum by (operation_name) (rate(fraiseql_graphql_query_duration_seconds_count[5m]))
)
```

**4. Rejected Queries** (log panel): the `query.depth_exceeded` and
`query.complexity_exceeded` security events over time.

---

## 🔍 Verification

After applying mitigations, verify the attack is stopped:

### 1. Check Request Duration

```promql
# Should return to normal (< 1s)
sum(rate(fraiseql_http_request_duration_seconds_sum{endpoint="/graphql"}[5m]))
  / sum(rate(fraiseql_http_request_duration_seconds_count{endpoint="/graphql"}[5m]))
```

### 2. Check Cancelled Statements

```bash
# Should stop growing
grep -c '"query.timeout"' security_events.log
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
# Rejected queries in the last entries
grep -E '"query\.(depth|complexity)_exceeded"' security_events.log | tail -10

# Should see no recent events from the attack's queries
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
   - Alert on the `query.complexity_exceeded` / `query.depth_exceeded` log events
   - Monitor query patterns
   - Decorate expensive resolvers with `@with_metrics("query")` to time them

4. **Security Improvements**:
   - Review authentication
   - Tighten the rate limits on expensive operations
   - Add WAF rules if applicable

---

## 📚 Related Resources

- [GraphQL Security Best Practices](../security.md#query-complexity-limits)
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

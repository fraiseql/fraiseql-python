<!-- Skip to main content -->
---

title: Troubleshooting Decision Tree
description: Use this decision tree to quickly identify which troubleshooting guide applies to your problem.
keywords: ["debugging", "implementation", "best-practices", "deployment", "tutorial"]
tags: ["documentation", "reference"]
---

# Troubleshooting Decision Tree

**Status:** ✅ Production Ready
**Audience:** Developers, DevOps, Support Engineers
**Reading Time:** 5 minutes

Use this decision tree to quickly identify which troubleshooting guide applies to your problem.

---

## 🎯 Start Here: What's Your Problem?

### Step 1: Identify the Symptom Category

**Select the one that best describes your situation:**

```text
Does your problem involve...

1. Starting the app or deployment?
   → Go to: DEPLOYMENT ISSUES

2. GraphQL queries returning errors?
   → Go to: QUERY EXECUTION ISSUES

3. Mutations not working or failing?
   → Go to: MUTATION ISSUES

4. Real-time updates or subscriptions?
   → Go to: SUBSCRIPTION ISSUES

5. Authentication or authorization problems?
   → Go to: AUTHENTICATION & AUTHORIZATION

6. Slow queries or performance issues?
   → Go to: PERFORMANCE ISSUES

7. Database connection problems?
   → Go to: DATABASE CONNECTIVITY

8. Configuration issues?
   → Go to: CONFIGURATION ISSUES

9. Specific error codes?
   → Go to: ERROR CODE LOOKUP
```

---

## 🚀 DEPLOYMENT ISSUES

**Container fails to start:**

- Check Docker image build: `docker build . --no-cache`
- Verify dependencies are installed: `uv sync`
- Review startup logs: `docker logs <container_id>`
- → **Full guide:** [Production Deployment](./production-deployment.md)

**App fails to start:**

- Read the startup traceback — the schema is built in memory at startup, so a bad
  type/query/mutation definition raises here, not at request time
- Verify `create_fraiseql_app(...)` arguments (`database_url`, `types`, `queries`, `mutations`)
- Check environment variables: `env | grep FRAISEQL`
- → **Full guide:** [Production Deployment](./production-deployment.md)

**App starts but no requests work:**

- Verify the ASGI server is bound to the expected port: `uvicorn app:app --host 0.0.0.0 --port 8000`
- Check that the port is listening: `netstat -an | grep 8000`
- Check firewall rules: `sudo iptables -L`
- Test with curl: `curl -i http://localhost:8000/health`
- → **Full guide:** [Production Deployment](./production-deployment.md)

**Service won't connect to database:**

- → Go to: **DATABASE CONNECTIVITY** (below)

---

## 🔍 QUERY EXECUTION ISSUES

**Query returns GraphQL error:**

**Error type:**

```text
Is the error about...

a) "Field X doesn't exist"?
   - Verify the field name in the @fraiseql.type definition
   - Confirm the field is selected in the view's data JSONB (jsonb_build_object)
   - Restart the app so the schema is rebuilt from the updated definitions
   → [Troubleshooting Guide: Schema Errors](./troubleshooting.md#schema-errors)

b) "Unauthorized" or "Permission denied"?
   → Go to: AUTHENTICATION & AUTHORIZATION

c) Database error (SQL error in message)?
   → Go to: DATABASE CONNECTIVITY

d) "Query timeout"?
   → Go to: PERFORMANCE ISSUES

e) Something else?
   → Go to: ERROR CODE LOOKUP
```

**Query returns null when expecting data:**

- Verify data exists in database: `SELECT * FROM table_name LIMIT 1;`
- Check WHERE clause filters: `SELECT * FROM table_name WHERE ... LIMIT 1;`
- Verify authorization isn't hiding data (row-level filters)
- Check pagination offset: Is `skip` too high?
- → [Troubleshooting Guide: No Results](./troubleshooting.md#no-results)

**Query response is incomplete or truncated:**

- Check pagination limit: Default is 100, max is 1000
- Increase limit in query: `users(first: 500) { ... }`
- Check response size: Very large responses may be truncated
- → [Troubleshooting Guide: Incomplete Results](./troubleshooting.md#incomplete-results)

**Query takes too long:**

- → Go to: **PERFORMANCE ISSUES**

---

## ✏️ MUTATION ISSUES

**Mutation fails or returns error:**

**Error type:**

```text
Is the error about...

a) "Constraint violation" (duplicate key, foreign key)?
   - Check unique constraints in the underlying tb_ table
   - Verify foreign key exists: SELECT * FROM referenced_table WHERE id = ...
   → [Troubleshooting Guide: Constraint Violations](./troubleshooting.md#constraint-violations)

b) "Invalid input" or "Validation error"?
   - Review the input validation error message returned by the fn_ function
   - Check input field types match the @fraiseql.input definition
   → [Troubleshooting Guide: Input Validation](./troubleshooting.md#input-validation)

c) "Permission denied"?
   → Go to: AUTHENTICATION & AUTHORIZATION

d) Database error?
   → Go to: DATABASE CONNECTIVITY

e) Something else?
   → Go to: ERROR CODE LOOKUP
```

**Mutation succeeds but data looks wrong:**

- Verify mutation result in GraphQL response
- Query database directly: `SELECT * FROM table_name WHERE id = ...`
- Check for triggers or stored procedures modifying data
- → [Troubleshooting Guide: Data Integrity](./troubleshooting.md#data-integrity)

**Mutation is very slow:**

- → Go to: **PERFORMANCE ISSUES**

---

## 🔄 SUBSCRIPTION ISSUES

**Subscription not connecting:**

- Verify the WebSocket endpoint: `ws://localhost:8000/graphql`
- Check WebSocket proxy configuration (the proxy must forward the `Upgrade` header)
- Verify the authentication token in the subscription connection params
- → [Troubleshooting Guide: WebSocket Connection](./troubleshooting.md#websocket)

**Subscription connects but no events:**

- Confirm your `@fraiseql.subscription` async generator actually yields values
- Check the event source backing the generator (PostgreSQL `LISTEN/NOTIFY`, polling, or
  an external stream) is producing updates
- Check event filtering: a `subscription_filter` may be hiding events
- → [Subscriptions Architecture](../architecture/realtime/subscriptions.md#debugging)

**Subscription receives stale data:**

- Check the event timestamp vs current time
- Confirm the generator re-reads fresh data (e.g. re-`db.find` on each tick) rather than
  yielding a cached value
- → [Troubleshooting Guide: Event Delivery](./troubleshooting.md#event-delivery)

---

## 🔐 AUTHENTICATION & AUTHORIZATION

**Can't log in:**

- Verify OAuth provider is configured
- Check client ID and secret in vault: `echo $OAUTH_CLIENT_ID`
- Verify redirect URI matches OAuth provider settings
- Check OAuth provider health: Can you log in directly to provider?
- → [Authentication Provider Guide](../integrations/authentication/provider-selection-guide.md)

**Token rejected or expired:**

- Check token expiry: JWT tokens expire after 1 hour
- Verify token refresh working: Is refresh token valid?
- Check token signature: Token might be from different issuer
- → [Authentication Security Checklist](../integrations/authentication/security-checklist.md)

**Query or mutation denied with "Unauthorized":**

- Verify user is authenticated: Check Authorization header
- Check user has the required role in your `Authorizer` / RBAC configuration
- Check field-level permissions: Some fields might be restricted via `authorize_fields`
- → [RBAC & Field Authorization](./authorization-quick-start.md)

**Row-level data hidden or unauthorized:**

- Verify your PostgreSQL Row-Level Security (RLS) policies on the underlying tables
- Check tenant/org filtering: the request context must carry `tenant_id` so the repository
  issues `SET LOCAL app.tenant_id = …` for RLS
- Verify context values are passed: is the `x-tenant-id` header set?
- → [RBAC Guide](./authorization-quick-start.md)

---

## ⚡ PERFORMANCE ISSUES

**Single query is slow (>1 second):**

1. Is it the first query? (Cold start, connection pool warm-up)
2. Is database responding slowly? Test database directly: `time psql -c "SELECT COUNT(*) FROM table"`
3. Is query complex (many nested fields)?
   - Simplify query, remove nested selections
   - Add filtering to reduce rows scanned
   - → [Performance Tuning Runbook](../operations/performance-tuning-runbook.md)

**Specific query always slow:**

- Analyze query: `EXPLAIN ANALYZE ...` on database
- Check indexes exist on filtered columns
- Check database statistics: `ANALYZE table_name;`
- Consider table-backed views (tv_*) for frequently accessed data
- → [View Selection Guide](../architecture/database/view-selection-guide.md)

**All queries getting slower over time:**

- Check database connection pool: `SHOW max_connections;`
- Check for connection leaks: Count open connections
- Verify indexes haven't fragmented: `REINDEX;`
- Check disk space: `df -h`
- → [Database Connectivity](#database-connectivity)

**Memory usage increasing:**

- Check for memory leaks: Monitor `top -p <pid>`
- Verify connection pooling: Connections should be reused
- Check query result caching: Cache size might be too large
- → [Performance Tuning Runbook](../operations/performance-tuning-runbook.md)

---

## 🗄️ DATABASE CONNECTIVITY

**Can't connect to database:**

- Verify database server is running: `ping db-host`
- Check database port: `telnet db-host 5432`
- Verify credentials: Username, password, database name
- Check connection string: `postgresql://user:pass@host:5432/db`
- → [Production Deployment](./production-deployment.md)

**Connection times out:**

- Increase timeout: `connect_timeout=30`
- Check firewall rules: `telnet db-host 5432`
- Check network latency: `ping db-host`
- Verify database isn't overloaded
- → [Production Deployment](./production-deployment.md)

**"Too many connections" error:**

- Check connection pool size: Default 10, max 100
- Check for connection leaks: `SELECT COUNT(*) FROM pg_stat_activity;`
- Increase database `max_connections` if needed
- Enable connection pooling: PgBouncer or the built-in pool
- → [Production Deployment](./production-deployment.md)

**SSL/TLS connection errors:**

- Verify SSL mode: `sslmode=require` in connection string
- Check certificate chain: `openssl s_client -connect db-host:5432`
- Verify certificate not expired: `openssl x509 -enddate`
- → [Production Deployment](./production-deployment.md)

**Authentication errors:**

- Check database user password (special characters might need escaping)
- Verify database user has SELECT/INSERT/UPDATE permissions
- Check `pg_hba.conf` (PostgreSQL) for connection restrictions
- → [Database Hardening](./production-security-checklist.md#database-hardening)

---

## ⚙️ CONFIGURATION ISSUES

**Configuration not taking effect:**

- Confirm where the setting lives: a `create_fraiseql_app(...)` keyword argument, a
  `FraiseQLConfig` field, or a `FRAISEQL_*` environment variable
- Verify precedence: explicit `create_fraiseql_app` / `FraiseQLConfig` values override env vars
- Restart the app after a config change — config is read at startup
- → [Production Deployment](./production-deployment.md)

**Environment variables not recognized:**

- Check variable name: `FRAISEQL_*` prefix required (e.g. `FRAISEQL_DATABASE_URL`)
- Verify case sensitivity: `FRAISEQL_RATE_LIMIT_ENABLED` (not camelCase)
- Check for typos: List all set variables: `env | grep FRAISEQL`
- → [Production Deployment](./production-deployment.md)

**Config value has the wrong type:**

- `FraiseQLConfig` validates types at startup — read the validation error in the traceback
- Booleans must be `true`/`false`, ports/limits must be integers
- → [Production Deployment](./production-deployment.md)

---

## 🔢 ERROR CODE LOOKUP

**Have an error code?** (Format: E_XXXXX_NNN)

```text
Error Category:
- E_PARSE_* → GraphQL parsing errors
- E_BINDING_* → Schema binding/type errors
- E_VALIDATION_* → Request validation errors
- E_AUTH_* → Authentication/authorization errors
- E_DB_* → Database errors
- E_INTERNAL_* → Internal server errors

To find your error:
1. Copy error code: "E_BINDING_UNKNOWN_FIELD_202"
2. Search GitHub issues: "E_BINDING_UNKNOWN_FIELD_202"
3. Refer to [Main Troubleshooting Guide](./troubleshooting.md)
```

**Don't see your error?**

- → Go to: **[Main Troubleshooting Guide](./troubleshooting.md)**

---

## 📞 Still Having Issues?

**If you can't find your problem:**

1. **Check if you have an error code:**
   - Search: [GitHub Issues](https://github.com/FraiseQL/FraiseQL/issues)
   - Refer to: [Troubleshooting Guide](./troubleshooting.md)

2. **Review comprehensive guides:**
   - **[Main Troubleshooting Guide](./troubleshooting.md)** — All FAQs and common issues
   - **[Production Deployment](./production-deployment.md)** — Deployment procedures
   - **[Performance Tuning](../operations/performance-tuning-runbook.md)** — Performance optimization

3. **Get help:**
   - **Open a GitHub Issue:** [GitHub Issues](https://github.com/FraiseQL/FraiseQL/issues)
   - **Include:** Error code, steps to reproduce, environment details (PostgreSQL version, Python version, OS)
   - **Tag:** `troubleshooting` label for visibility

---

## See Also

**Complete Troubleshooting Guides:**

- **[Main Troubleshooting Guide](./troubleshooting.md)** — Comprehensive FAQ
- **[Mutation Troubleshooting](./troubleshooting-mutations.md)** — Mutation-specific issues
- **[Authentication Troubleshooting](../integrations/authentication/troubleshooting.md)** — Auth-specific issues

**Related Guides:**

- **[Production Deployment](./production-deployment.md)** — Deployment and operations
- **[Performance Tuning](../operations/performance-tuning-runbook.md)** — Optimization
- **[Monitoring & Observability](./monitoring.md)** — Observability setup
- **[Common Gotchas](./common-gotchas.md)** — Pitfalls and solutions

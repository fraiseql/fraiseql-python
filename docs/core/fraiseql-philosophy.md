---
title: FraiseQL Philosophy
description: Design principles, PostgreSQL-native patterns, and developer experience focus
tags:
  - philosophy
  - principles
  - design
  - PostgreSQL
  - architecture
---

# FraiseQL Philosophy

Understanding FraiseQL's design principles and innovative approaches.

## Overview

FraiseQL is built on forward-thinking design principles that prioritize **developer experience**, **security by default**, and **PostgreSQL-native patterns**. Unlike traditional GraphQL frameworks, FraiseQL embraces conventions that reduce boilerplate while maintaining flexibility.

**Core Principles:**

1. **Automatic Database Injection** - Zero-config data access
2. **JSONB-First Architecture** - Embrace PostgreSQL's strengths
3. **Auto-Documentation** - Single source of truth
4. **Session Variable Injection** - Security without complexity
5. **Composable Patterns** - Framework provides tools, you control composition

## Beginner Introduction

### If You're New to FraiseQL

FraiseQL might seem different if you're used to traditional web frameworks. Here's what makes it special:

**Think "Database-First"**: Instead of starting with your API and figuring out the database later, FraiseQL starts with PostgreSQL and builds your API on top. Your database becomes the foundation of your application.

**Key Concepts to Know**:

- **[CQRS](../core/concepts-glossary.md#cqrs-command-query-responsibility-segregation)**: Separate reading data from writing data
- **[JSONB Views](../core/concepts-glossary.md#view)**: Pre-packaged data ready for GraphQL
- **[Database-First](../core/concepts-glossary.md)**: Business logic lives in PostgreSQL

**Why This Matters**: Traditional frameworks often fight against the database. FraiseQL works *with* PostgreSQL, using its strengths (JSONB, functions, views) to build faster, more maintainable APIs.

### Quick Philosophy Check

Before diving deep, ask yourself:

- Do you want your database to do more heavy lifting?
- Are you tired of ORM complexity?
- Do you want automatic multi-tenancy and security?
- Would you like 10-100x performance improvements?

If yes, FraiseQL's philosophy might be perfect for you.

## Automatic Database Injection

### The Problem with Traditional Frameworks

Most GraphQL frameworks require manual database setup in every resolver:

```python
import fraiseql
from fraiseql.types import ID

# ❌ Traditional approach - repetitive and error-prone
@fraiseql.query
async def get_user(info, id: ID) -> User:
    # Must manually get database from somewhere
    db = get_database_from_somewhere()
    # Or pass it through complex dependency injection
    return await db.find_one("users", {"id": id})
```

### FraiseQL's Solution

**FraiseQL automatically injects the database into `info.context["db"]`**:

```python
import fraiseql
from fraiseql.types import ID

# ✅ FraiseQL - database automatically available
@fraiseql.query
async def get_user(info, id: ID) -> User:
    db = info.context["db"]  # Always available!
    return await db.find_one("v_user", where={"id": id})
```

### How It Works

1. **Configuration** - Specify database URL once:

   ```python
   config = FraiseQLConfig(
       database_url="postgresql://localhost/mydb"
   )
   ```

2. **Automatic Setup** - FraiseQL creates and manages connection pool:

   ```python
   app = create_fraiseql_app(config=config)
   # Database pool created automatically
   ```

3. **Context Injection** - Every resolver gets `db` in context:
   ```python

import fraiseql

   @fraiseql.query
   async def any_query(info) -> Any:
       db = info.context["db"]  # FraiseQLRepository instance
       # Ready to use immediately

   ```

### Benefits

- **Zero boilerplate** - No manual connection management
- **Type-safe** - `db` is always `FraiseQLRepository`
- **Connection pooling** - Automatic pool management
- **Transaction support** - Built-in transaction handling
- **Consistent** - Same API across all resolvers

### Advanced: Custom Context

You can extend context while keeping auto-injection:

```python
async def get_context(request: Request) -> dict:
    """Custom context with user + auto database injection."""
    return {
        # Your custom context
        "user_id": extract_user_from_jwt(request),
        "tenant_id": extract_tenant_from_jwt(request),
        # No need to add "db" - FraiseQL adds it automatically!
    }

app = create_fraiseql_app(
    config=config,
    context_getter=get_context  # Database still auto-injected
)
```

## JSONB-First Architecture

### Philosophy

FraiseQL embraces **PostgreSQL's JSONB** as a first-class storage mechanism, not just for flexible schemas, but as a performance and developer experience optimization.

### Traditional vs JSONB-First

**Traditional ORM Approach**:

```sql
-- Rigid schema, many columns
CREATE TABLE tb_user (
    id UUID PRIMARY KEY,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    email VARCHAR(255),
    phone VARCHAR(20),
    address_line1 VARCHAR(255),
    address_line2 VARCHAR(255),
    city VARCHAR(100),
    -- ... 20 more columns
);
```

**FraiseQL JSONB-First Approach**:

```sql
-- Flexible, indexed, performant
CREATE TABLE tb_user (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    data JSONB NOT NULL
);

-- Indexes for commonly queried fields
CREATE INDEX idx_user_email ON tb_user USING GIN ((data->'email'));
CREATE INDEX idx_user_name ON tb_user USING GIN ((data->'name'));

-- View for GraphQL
CREATE VIEW v_user AS
SELECT
    id,
    tenant_id,
    data->>'first_name' as first_name,
    data->>'last_name' as last_name,
    data->>'email' as email,
    data
FROM tb_user;
```

### Why JSONB-First?

**1. Schema Evolution Without Migrations**:

```python
import fraiseql
from fraiseql.types import ID

# Add new field - no migration needed!
@fraiseql.type(sql_source="v_user")
class User:
    """User account.

    Fields:
        id: User identifier
        email: Email address
        name: Full name
        preferences: User preferences (NEW! Just add it)
    """
    id: ID
    email: str
    name: str
    preferences: UserPreferences | None = None  # Added without ALTER TABLE
```

**2. JSON Passthrough Performance**:

```python
import fraiseql
from fraiseql.types import ID

# PostgreSQL JSONB → GraphQL JSON directly
# No Python object instantiation needed!
@fraiseql.query
async def user(info, id: ID) -> User:
    db = info.context["db"]
    # Returns JSONB directly - 10-100x faster
    return await db.find_one("v_user", where={"id": id})
```

**3. Flexible Data Models**:

```sql
-- Different tenants can have different user fields
-- Tenant A users
{"first_name": "John", "last_name": "Doe", "department": "Sales"}

-- Tenant B users (different structure!)
{"full_name": "Jane Smith", "division": "Marketing", "employee_id": "E123"}
```

### JSONB Best Practices

**1. Use Views for GraphQL**:

```sql
CREATE VIEW v_product AS
SELECT
    id,
    tenant_id,
    data->>'name' as name,
    (data->>'price')::decimal as price,
    data->>'sku' as sku,
    data  -- Full JSONB for passthrough
FROM tb_product;
```

**2. Index Frequently Queried Fields**:

```sql
-- GIN index for contains queries
CREATE INDEX idx_product_search ON tb_product
USING GIN ((data->'name') gin_trgm_ops);

-- B-tree for exact matches
CREATE INDEX idx_product_sku ON tb_product ((data->>'sku'));
```

**3. Validate in PostgreSQL, Not Python**:

```sql
CREATE FUNCTION validate_user_data(data jsonb) RETURNS boolean AS $$
BEGIN
    -- Email required
    IF NOT (data ? 'email') THEN
        RAISE EXCEPTION 'email is required';
    END IF;

    -- Email format
    IF NOT (data->>'email' ~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$') THEN
        RAISE EXCEPTION 'invalid email format';
    END IF;

    RETURN true;
END;
$$ LANGUAGE plpgsql;

-- Use in constraint
ALTER TABLE tb_user
ADD CONSTRAINT check_user_data
CHECK (validate_user_data(data));
```

### When NOT to Use JSONB

- **High-cardinality numeric queries** - Use regular columns for complex numeric aggregations
- **Foreign key relationships** - Use UUID columns, not nested JSONB
- **Frequently joined data** - Extract to separate table with foreign keys

```sql
-- ❌ Don't do this
CREATE TABLE tb_order (
    id UUID,
    data JSONB  -- Contains user_id, product_id
);

-- ✅ Do this
CREATE TABLE tb_order (
    id UUID,
    user_id UUID REFERENCES tb_user(id),      -- FK for joins
    product_id UUID REFERENCES tb_product(id), -- FK for joins
    data JSONB  -- Additional flexible data
);
```

## Auto-Documentation from Code

### Single Source of Truth

FraiseQL extracts documentation from Python docstrings, eliminating manual schema documentation:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user")
class User:
    """User account with authentication and profile information.

    Users are created during registration and can access the system
    based on their assigned roles and permissions.

    Fields:
        id: Unique user identifier (UUID v4)
        email: Email address used for login (must be unique)
        first_name: User's first name
        last_name: User's last name
        created_at: Account creation timestamp
        is_active: Whether user account is active
    """

    id: ID
    email: str
    first_name: str
    last_name: str
    created_at: datetime
    is_active: bool
```

**Result** - GraphQL schema includes all documentation:

```graphql
"""
User account with authentication and profile information.

Users are created during registration and can access the system
based on their assigned roles and permissions.
"""
type User {
  "Unique user identifier (UUID v4)"
  id: ID!

  "Email address used for login (must be unique)"
  email: String!

  "User's first name"
  firstName: String!

  # ... etc
}
```

### Benefits for LLM Integration

This auto-documentation is perfect for LLM-powered applications:

1. **Rich Context** - LLMs see full descriptions via introspection
2. **Always Updated** - Docs can't get out of sync with code
3. **Consistent Format** - Standardized across entire API
4. **Zero Maintenance** - No separate documentation files

## Session Variable Injection

### Security by Default

FraiseQL **automatically sets PostgreSQL session variables** from GraphQL context:

```python
# Context from authenticated request
async def get_context(request: Request) -> dict:
    token = extract_jwt(request)
    return {
        "tenant_id": token["tenant_id"],
        "user_id": token["user_id"]
    }

# FraiseQL automatically executes:
# SET LOCAL app.tenant_id = '<tenant_id>';
# SET LOCAL app.contact_id = '<user_id>';
```

### Multi-Tenant Isolation

Views automatically filter by tenant:

```sql
CREATE VIEW v_order AS
SELECT *
FROM tb_order
WHERE tenant_id = current_setting('app.tenant_id')::uuid;
```

Now all queries are automatically tenant-isolated:

```python
import fraiseql

@fraiseql.query
async def orders(info) -> list[Order]:
    db = info.context["db"]
    # Automatically filtered by tenant from JWT!
    return await db.find("v_order")
```

**Security Benefits**:

- ✅ Tenant ID from verified JWT, not user input
- ✅ Impossible to query other tenant's data
- ✅ Works at database level (defense in depth)
- ✅ Zero application-level filtering logic

## In PostgreSQL Everything

### One Database to Rule Them All

FraiseQL eliminates external dependencies by implementing **caching, error tracking, and observability** directly in PostgreSQL. This "In PostgreSQL Everything" philosophy delivers cost savings, operational simplicity, and consistent performance.

**Cost Savings:**

```
Traditional Stack:
- Sentry: $300-3,000/month
- Redis Cloud: $50-500/month
- Total: $350-3,500/month

FraiseQL Stack:
- PostgreSQL: Already running (no additional cost)
- Total: $0/month additional
```

**Operational Simplicity:**

```
Before: FastAPI + PostgreSQL + Redis + Sentry + Grafana = 5 services
After:  FastAPI + PostgreSQL + Grafana = 3 services
```

### PostgreSQL-Native Caching (Redis Alternative)

```python
from fraiseql.caching import PostgresCache

cache = PostgresCache(db_pool)
await cache.set("user:123", user_data, ttl=3600)

# Features:
# - UNLOGGED tables for Redis-level performance
# - No WAL overhead = fast writes
# - Shared across app instances
# - TTL-based automatic expiration
# - Pattern-based deletion
```

**Performance:** UNLOGGED tables skip write-ahead logging, providing Redis-level write performance while maintaining read speed. Data survives crashes (unlike Redis default) and is automatically shared across all app instances.

### PostgreSQL-Native Error Tracking (Sentry Alternative)

```python
from fraiseql.monitoring import init_error_tracker

tracker = init_error_tracker(db_pool, environment="production")
await tracker.capture_exception(error, context={
    "user": {"user_id": str(user.id)},
    "request": {"request_id": request_id, "operation": "create_order"},
})

# Features:
# - Error fingerprinting and grouping (like Sentry)
# - Full stack trace capture
# - Request/user context preservation
# - OpenTelemetry trace ids (trace_id=, span_id=) stored with each error
# - Issue management (resolve, ignore, assign)
# - Notification rules (email, Slack, webhook)
```

**Observability:** Errors are rows in PostgreSQL (`tb_error_log`, one per fingerprint,
and `tb_error_occurrence`, one per capture), created by the `schema.sql` of
`fraiseql.monitoring`. Query them directly for debugging:

```sql
-- Find all errors for a user
SELECT e.error_type, e.error_message, o.occurred_at
FROM tb_error_occurrence o
JOIN tb_error_log e ON e.error_id = o.error_id
WHERE o.user_context->>'user_id' = '123'
ORDER BY o.occurred_at DESC;

-- Most frequent unresolved errors
SELECT error_type, error_message, occurrence_count, last_seen
FROM v_top_errors
LIMIT 10;
```

### Integrated Observability Stack

**OpenTelemetry Integration:** `fraiseql.tracing.setup_tracing` opens a span per HTTP
request and sends spans to an exporter (OTLP, Jaeger, Zipkin or the console), not to
PostgreSQL. Pass a span's `trace_id` to `capture_exception` and an error row links to
its trace in your tracing backend:

```sql
-- Errors of the last hour, with the trace to open in your tracing backend
SELECT e.error_type, e.error_message, o.occurred_at, o.trace_id
FROM tb_error_occurrence o
JOIN tb_error_log e ON e.error_id = o.error_id
WHERE o.occurred_at > NOW() - INTERVAL '1 hour'
  AND o.trace_id IS NOT NULL
ORDER BY o.occurred_at DESC
LIMIT 10;
```

**Metrics:** `fraiseql.monitoring.setup_metrics` exports Prometheus metrics
(`fraiseql_http_requests_total`, `fraiseql_http_request_duration_seconds`,
`fraiseql_errors_total`, ...) on `/metrics`.

**Grafana Dashboards:**
Pre-built dashboards in `grafana/`:

- Error monitoring (grouping, rates, trends), from `tb_error_log` / `tb_error_occurrence`
- Database (connections, slow queries), from PostgreSQL's statistics views
- APQ storage, from the PostgreSQL APQ backend's tables
- Performance metrics (latency, throughput), from the Prometheus metrics of `setup_metrics`

### Why "In PostgreSQL Everything"?

**1. Cost-Effective**: Save $300-3,000/month by eliminating SaaS services
**2. Operational Simplicity**: One database to manage, backup, and monitor
**3. Consistent Performance**: No external network calls for caching or error tracking
**4. Full Control**: Self-hosted, no vendor lock-in, complete data ownership
**5. Correlation**: Errors and business events in one query, each error carrying its trace id
**6. ACID Guarantees**: All observability data benefits from PostgreSQL transactions

## Composable Over Opinionated

### Framework Provides Tools

FraiseQL gives you composable utilities, not rigid patterns:

```python
from fraiseql.monitoring import HealthCheck, check_database

# Create health check
health = HealthCheck()

# Add only checks you need
health.add_check("database", check_database)

# Optionally add custom checks
health.add_check("s3", my_s3_check)

# Use in your endpoints
@app.get("/health")
async def health_endpoint():
    return await health.run_checks()
```

### You Control Composition

Unlike opinionated frameworks that dictate:

- ❌ Where files go
- ❌ How to structure modules
- ❌ What patterns to use

FraiseQL provides:

- ✅ Building blocks (HealthCheck, @mutation, @query)
- ✅ Clear interfaces (CheckResult, CheckFunction)
- ✅ Flexibility in composition

## Performance Through Simplicity

### JSON Passthrough

Skip Python object creation entirely:

```python
import fraiseql

# PostgreSQL JSONB → GraphQL JSON
# No intermediate Python objects!

@fraiseql.query
async def users(info) -> list[User]:
    db = info.context["db"]
    # Returns JSONB directly - 10-100x faster
    return await db.find("v_user")

# With Rust transformer: 80x faster
# With APQ: 3-5x additional speedup
# With TurboRouter: 2-3x additional speedup
```

### Database-First Operations

Move logic to PostgreSQL when possible:

```sql
-- Complex business logic in database
CREATE FUNCTION calculate_order_totals(order_id uuid)
RETURNS jsonb AS $$
    -- SQL aggregations, JOINs, window functions
    -- Much faster than Python loops
$$ LANGUAGE sql;
```

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.query
async def order_totals(info, id: ID) -> OrderTotals:
    db = info.context["db"]
    # Database does the heavy lifting
    return await db.execute_function(
        "calculate_order_totals",
        {"order_id": id}
    )
```

## See Also

- [Database API](../reference/database.md) - Auto-injected database methods
- [Session Variables](../reference/database.md#context-and-session-variables) - Automatic injection details
- [Decorators](../reference/decorators.md) - FraiseQL decorator patterns
- [Performance](../performance/index.md) - JSON passthrough and optimization layers

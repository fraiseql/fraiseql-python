# In PostgreSQL, Everything

FraiseQL eliminates the need for separate infrastructure services by leveraging PostgreSQL's advanced capabilities. Instead of maintaining Redis, Sentry, APM tools, and complex caching layers, FraiseQL keeps everything in your primary database.

## Replace External Services with PostgreSQL

### APQ Storage in PostgreSQL

FraiseQL stores Automatic Persisted Queries (APQ) directly in PostgreSQL tables, eliminating the need for Redis:

```sql
-- APQ queries stored in PostgreSQL
CREATE TABLE persisted_queries (
    query_hash varchar(64) PRIMARY KEY,
    query_text text NOT NULL,
    created_at timestamp DEFAULT now(),
    last_used_at timestamp DEFAULT now(),
    use_count integer DEFAULT 0
);

-- APQ responses can also be cached in PostgreSQL
CREATE TABLE query_cache (
    cache_key varchar(64) PRIMARY KEY,
    query_hash varchar(64) REFERENCES persisted_queries(query_hash),
    response_data jsonb,
    created_at timestamp DEFAULT now(),
    expires_at timestamp
);
```

**Benefits:**

- **ACID Consistency**: Query storage and caching have the same transactional guarantees as your data
- **Backup Included**: APQ data is automatically included in your database backups
- **No Redis Management**: One less service to deploy, monitor, and scale

### Error Tracking and Observability

Replace external error tracking services with PostgreSQL tables:

```sql
-- Structured error logging
CREATE TABLE graphql_errors (
    id serial PRIMARY KEY,
    query_hash varchar(64),
    error_type varchar(100),
    error_message text,
    stack_trace text,
    user_id integer,
    occurred_at timestamp DEFAULT now(),
    request_context jsonb
);

-- Performance metrics
CREATE TABLE query_performance (
    id serial PRIMARY KEY,
    query_hash varchar(64),
    execution_time_ms integer,
    result_size_bytes integer,
    recorded_at timestamp DEFAULT now()
);

-- Index for efficient analytics
CREATE INDEX idx_graphql_errors_type_time
ON graphql_errors(error_type, occurred_at DESC);
```

### Audit Logging

Centralize all audit trails in PostgreSQL:

```sql
-- Comprehensive audit log
CREATE TABLE audit_log (
    id serial PRIMARY KEY,
    table_name varchar(100),
    operation varchar(10), -- INSERT, UPDATE, DELETE
    old_values jsonb,
    new_values jsonb,
    user_id integer,
    changed_at timestamp DEFAULT now(),
    query_id varchar(64) -- Links to GraphQL query
);
```

## Cost Savings: $5K - $48K Annual Reduction

### Infrastructure Cost Comparison

| Service | Traditional Stack | FraiseQL | Annual Savings |
|---------|-------------------|----------|----------------|
| Redis (APQ Cache) | $500-2,000/month | $0 | $6K-24K |
| Error Tracking (Sentry) | $99-299/month | $0 | $1.2K-3.6K |
| APM/Monitoring | $200-1,000/month | $0 | $2.4K-12K |
| **Total Annual Savings** | | | **$9.6K-39.6K** |

### Operational Cost Reduction

**70% Fewer Services to Operate:**

- No Redis deployment, scaling, backups
- No external monitoring setup
- No API key management for third-party services
- No vendor lock-in and pricing surprises

**One Database to Backup:**

- Single backup strategy for all data
- Consistent backup windows
- Simplified disaster recovery
- No cross-service data consistency issues

## ACID Guarantees Everywhere

### Transactional Consistency

All FraiseQL operations maintain ACID properties:

```sql
-- Example: Atomic query execution with audit logging
BEGIN;
    -- Execute the GraphQL query
    INSERT INTO query_log (query_hash, user_id, executed_at)
    VALUES ($1, $2, now());

    -- Log the result
    INSERT INTO query_performance (query_hash, execution_time_ms)
    VALUES ($1, $3);

    -- Update usage statistics
    UPDATE persisted_queries
    SET use_count = use_count + 1, last_used_at = now()
    WHERE query_hash = $1;
COMMIT;
```

### Cross-Component Consistency

Traditional stacks suffer from eventual consistency issues between services:

**❌ Traditional Stack Problems:**

- Redis cache might be stale
- Error logs might not match database state
- Metrics might be lost during service restarts
- Backup consistency across multiple services

**✅ FraiseQL Consistency:**

- All data changes atomically
- Audit logs match exactly with data changes
- Metrics collection is transactional
- Single backup contains everything

## Migration Strategy

### Phase 1: Consolidate APQ Storage

Replace Redis APQ storage with PostgreSQL:

```python
# Before: a Redis-backed APQ store, plugged in as a custom backend
config = FraiseQLConfig(
    database_url="postgresql://localhost/db",
    apq_storage_backend="custom",
    apq_backend_config={"backend_class": "myapp.apq.RedisAPQBackend"},
)

# After: PostgreSQL-based APQ (the default backend is "memory")
config = FraiseQLConfig(
    database_url="postgresql://localhost/db",
    apq_storage_backend="postgresql",
)
```

> **Note:** the `postgresql` backend doesn't open a database connection of its own
> yet. Persisted queries are kept in the process's memory, as with `memory`, so they
> don't survive a restart and aren't shared between instances.

### Phase 2: Replace Error Tracking

Migrate from external services to PostgreSQL tables:

```bash
# Create the error tracking tables (tb_error_log, tb_error_occurrence, ...)
psql "$DATABASE_URL" -f src/fraiseql/monitoring/schema.sql
```

Error tracking is not a `FraiseQLConfig` setting: start the tracker on a psycopg
pool and capture exceptions with it.

```python
from fraiseql.monitoring import init_error_tracker

tracker = init_error_tracker(pool, environment="production")

try:
    ...
except Exception as exc:
    await tracker.capture_exception(exc, context={"operation": "createOrder"})
    raise
```

### Phase 3: Consolidate Monitoring

Replace APM tools with PostgreSQL-based metrics:

```sql
-- Performance monitoring tables
CREATE TABLE performance_metrics (
    id serial PRIMARY KEY,
    metric_name varchar(100),
    metric_value numeric,
    tags jsonb,
    recorded_at timestamp DEFAULT now()
);

-- Query performance tracking
CREATE TABLE query_metrics (
    id serial PRIMARY KEY,
    query_hash varchar(64),
    execution_time_ms integer,
    result_rows integer,
    recorded_at timestamp DEFAULT now()
);
```

## Operational Benefits

### Simplified Deployment

**Before:**

```yaml
# docker-compose.yml with multiple services
services:
  app:
  redis:
  postgres:
  sentry-proxy:
  monitoring-agent:
```

**After:**

```yaml
# Simplified deployment
services:
  app:
  postgres:  # Everything in one database
```

### Easier Scaling

- Scale PostgreSQL instead of multiple services
- Consistent performance characteristics
- Simplified load balancing
- Easier horizontal scaling

### Better Reliability

- Fewer points of failure
- ACID transactions across all operations
- Consistent backup and recovery
- No cross-service communication issues

This architecture reduces operational complexity while maintaining enterprise-grade reliability and performance.

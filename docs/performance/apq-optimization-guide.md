# APQ Optimization Guide

**FraiseQL Automatic Persisted Queries - Performance Tuning & Best Practices**

---

## Overview

APQ (Automatic Persisted Queries) is a GraphQL optimization technique that eliminates query parsing overhead by caching parsed queries by their SHA256 hash. FraiseQL's APQ implementation provides **two layers of caching**:

1. **Query Cache**: Stores query strings by hash (always active)
2. **Response Cache**: Stores complete query responses (optional)

## APQ vs TurboRouter: Understanding the Performance Stack

FraiseQL offers multiple performance optimizations that work together:

### APQ (Automatic Persisted Queries)

- **What it does**: Caches GraphQL query parsing by SHA256 hash
- **Performance gain**: Eliminates 20-80ms parsing overhead per request
- **Scope**: All queries (automatic)
- **Storage**: Query text in database or memory

### TurboRouter

- **What it does**: Bypasses GraphQL parsing and validation entirely for registered queries
- **Performance gain**: 2-3x additional speedup beyond APQ
- **Scope**: Pre-registered queries only
- **Storage**: Pre-compiled SQL templates with parameter mapping

### How They Work Together

```python
# Request flow with both optimizations
query MyQuery($id: ID!) {
  user(id: $id) { name email }
}

# 1. APQ: Check if query hash exists (avoids parsing)
# 2. TurboRouter: If query is registered, execute SQL directly
# 3. Otherwise: Fall back to normal GraphQL execution with APQ caching
```

**Performance Stack:**

- Base GraphQL: 100ms average response
- + APQ: 20-80ms faster (eliminates parsing)
- + TurboRouter: Additional 2-3x speedup (bypasses GraphQL entirely)
- **Total**: Up to 6-9x faster for registered queries

### Performance Impact

**Query Cache Benefits:**

- Eliminates 20-80ms query parsing overhead per request
- Reduces network payload (hash instead of full query)
- Target: 90%+ hit rate in production

**Response Cache Benefits:**

- Can provide 260-460x speedup for identical queries
- Bypasses GraphQL execution entirely
- Best for read-heavy, cacheable data

---

## Understanding APQ

### Two-Layer Caching Strategy

FraiseQL uses a sophisticated caching approach:

```
┌──────────────────────────────────────────────────────────┐
│                    APQ Request Flow                       │
└──────────────────────────────────────────────────────────┘

1. Client sends: {"extensions": {"persistedQuery": {"sha256Hash": "abc123..."}}}

2. FraiseQL checks Response Cache (if enabled)
   ├─ HIT  → Return cached response immediately (fastest)
   └─ MISS → Continue to step 3

3. FraiseQL checks Query Cache
   ├─ HIT  → Use cached query string, execute GraphQL
   └─ MISS → Request full query from client, store it

4. Execute GraphQL query → Generate response

5. Store response in Response Cache (if enabled, for future requests)

6. Return response to client
```

### When to Use Each Layer

**Query Cache (Always Use):**

- ✅ All production environments
- ✅ Development (helpful for debugging)
- ✅ No downside, minimal overhead
- ✅ Automatic query string deduplication

**Response Cache (Selective Use):**

- ✅ Read-heavy APIs with cacheable data
- ✅ Public data that doesn't change frequently
- ✅ Queries without user-specific data
- ❌ User-specific queries (unless using tenant isolation)
- ❌ Real-time data requirements
- ❌ High mutation rate data

---

## APQ Modes

*New in FraiseQL v1.6.1*

FraiseQL supports three APQ modes to control how queries are accepted:

### Mode Overview

| Mode | Description | Use Case |
|------|-------------|----------|
| `optional` | Accept both persisted queries and arbitrary queries (default) | Standard deployments |
| `required` | **Only** accept persisted query hashes, reject arbitrary queries | Security-hardened deployments |
| `disabled` | Ignore APQ extensions entirely, always require full query | Debugging, APQ bypass |

### Security Hardening with `required` Mode

For security-sensitive deployments, use `apq_mode="required"` to ensure only pre-approved queries can execute:

```python
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

# Security-hardened configuration
config = FraiseQLConfig(
    database_url="postgresql://localhost/db",
    apq_mode="required",              # Only allow persisted queries
)
# Register the allowed queries at startup: see Query Registration Methods

app = create_fraiseql_app(config=config, types=[User, Post])
```

In `required` mode a client cannot get a query approved: a hash the server doesn't
know is refused even when the request carries the query text (`PERSISTED_QUERY_NOT_IN_LIST`,
nothing is stored), and a known hash runs the text the server stored, never the text sent
with it. The queries that run are the ones you register (below) and, with the
`postgresql` backend, whatever is already in its table.

**Benefits of `required` mode:**

- ✅ **Prevent arbitrary queries** - Block query exploration/introspection attacks
- ✅ **Audit all queries** - Know exactly which queries can run in production
- ✅ **Control API surface** - Only approved queries from the codebase can execute
- ✅ **Reduce attack surface** - Eliminate GraphQL injection vectors

### Query Registration Methods

#### Method 1: Auto-register from Directory

Load all `.graphql` and `.gql` files at startup:

```python
config = FraiseQLConfig(
    database_url="postgresql://localhost/db",
    apq_mode="required",
    apq_queries_dir="./graphql/queries/",  # Meant to load all .graphql files (see the note)
)
```

> **Note:** nothing reads `apq_queries_dir` in 1.31, so the directory isn't loaded and
> hash-only requests for its queries get `PERSISTED_QUERY_NOT_FOUND`. Use Method 3
> until it is.

**Directory structure example:**

```
graphql/
├── users/
│   ├── queries.graphql
│   └── mutations.graphql
├── posts/
│   └── operations.graphql
└── shared/
    └── fragments.graphql
```

#### Method 2: Programmatic Registration

Register queries at startup using the backend API:

```python
from fraiseql.middleware.apq_caching import get_apq_backend

# Get the APQ backend the /graphql route uses for this config
# (create_apq_backend(config) builds a separate one the route never reads)
backend = get_apq_backend(config)

# Register allowed queries
queries = [
    "query GetUsers { users { id name } }",
    "query GetUser($id: ID!) { user(id: $id) { id name email } }",
    "mutation CreateUser($input: CreateUserInput!) { createUser(input: $input) { id } }",
]

# Returns dict mapping hash -> query
registered = backend.register_queries(queries)
print(f"Registered {len(registered)} queries")
```

#### Method 3: Load from Files Programmatically

```python
from fraiseql.middleware.apq_caching import get_apq_backend
from fraiseql.storage.query_loader import load_queries_from_directory

# Load queries from directory
queries = load_queries_from_directory("./graphql/")

# Register with the backend the /graphql route uses
get_apq_backend(config).register_queries(queries)
```

### Error Response for Rejected Queries

When `apq_mode="required"` and an arbitrary query is sent:

```json
{
  "errors": [
    {
      "message": "Persisted queries required. Arbitrary queries are not allowed.",
      "extensions": {
        "code": "ARBITRARY_QUERY_NOT_ALLOWED",
        "details": "Configure your client to use Automatic Persisted Queries (APQ) or register queries at build time."
      }
    }
  ]
}
```

### Disabled Mode

Use `apq_mode="disabled"` to completely bypass APQ processing:

```python
config = FraiseQLConfig(
    apq_mode="disabled",  # APQ extensions ignored
)
```

This is useful for:

- Debugging APQ issues
- Temporary bypass during development
- Legacy client compatibility

---

## When to Enable APQ

### Query Cache (Default: Enabled)

**Always enable query caching** - it provides pure performance benefits with no downsides.

Benefits:

- Eliminates query parsing overhead
- Reduces network payload size
- Improves response time consistency
- Automatic deduplication of queries

### Response Cache (Default: Disabled)

**Enable response caching** when you have:

1. **Cacheable Data Patterns:**
   - Public data (blogs, docs, product catalogs)
   - Reference data (countries, currencies, categories)
   - Aggregated statistics
   - Infrequently changing data

2. **Traffic Patterns:**
   - Repeated identical queries
   - High read-to-write ratio (>10:1)
   - Predictable query patterns

3. **Performance Requirements:**
   - Sub-10ms response time targets
   - High throughput requirements (>1000 req/s)
   - Cost optimization (reduce compute)

**Do NOT enable response caching** when:

- Data changes frequently (real-time updates)
- Queries are highly personalized
- Strong consistency requirements
- Complex authorization rules

---

## Configuration Guide

### Basic Configuration

```python
from fraiseql.fastapi.config import FraiseQLConfig

# Query cache only (recommended starting point)
config = FraiseQLConfig(
    database_url="postgresql://...",
    apq_storage_backend="memory",  # or "postgresql"
    apq_cache_responses=False,     # Response caching disabled
)

# Full APQ with response caching
config = FraiseQLConfig(
    database_url="postgresql://...",
    apq_storage_backend="memory",
    apq_cache_responses=True,      # Enable response caching
)
```

Cached responses have no TTL: one stays in the backend until the backend is
cleared or the process stops. (`apq_response_cache_ttl` is a `FraiseQLConfig` field,
but nothing reads it.)

> **Note:** in 1.31 the `/graphql` route returns the Rust-built response before it
> reaches the step that stores it, so with `apq_cache_responses=True` the response
> cache stays empty and every hash-only request is executed. The persisted-query
> (hash → query text) cache is unaffected.

### Storage Backend Options

#### 1. Memory Backend (Default)

**Best for:** Development, small deployments, single-instance apps

```python
config = FraiseQLConfig(
    apq_storage_backend="memory",
)
```

**Pros:**

- Fastest performance (<0.1ms lookup)
- Zero external dependencies
- Simple configuration

**Cons:**

- Lost on restart
- Not shared across instances
- Memory consumption grows with queries

**Recommended:** Development and single-server production

#### 2. PostgreSQL Backend

**Best for:** Production, multi-instance deployments, persistence

```python
config = FraiseQLConfig(
    database_url="postgresql://...",
    apq_storage_backend="postgresql",
    apq_backend_config={
        "table_prefix": "apq_",  # Tables apq_queries and apq_responses (the default)
    }
)
```

> **Note:** the `postgresql` backend doesn't open a database connection of its own
> yet. Persisted queries are kept in the process's memory, as with `memory`, so they
> don't survive a restart and aren't shared between instances; clients re-register
> a hash they get `PERSISTED_QUERY_NOT_FOUND` for.

**Pros (once the backend has its connection):**

- Shared across instances
- Survives restarts
- Leverages existing PostgreSQL infrastructure

**Cons:**

- Slightly slower than memory (~1-2ms)
- Requires database connection
- Additional database load

**Recommended:** Production with multiple app instances



---

## Monitoring & Metrics

### Dashboard Access

Access the interactive monitoring dashboard:

```
http://your-server:port/admin/apq/dashboard
```

Features:

- Real-time hit rate visualization
- Top queries analysis
- Health status monitoring
- Performance trends

### Key Metrics to Monitor

#### 1. Query Cache Hit Rate

**Target:** >70% (ideally >90%)

```bash
curl http://localhost:8000/admin/apq/health
```

**What it means:**

- **>90%**: Excellent - queries are being reused effectively
- **70-90%**: Good - normal for varied query patterns
- **50-70%**: Warning - high query diversity or cache warming needed
- **<50%**: Critical - investigate query patterns or cache configuration

#### 2. Response Cache Hit Rate

**Target:** >50% (when enabled)

**What it means:**

- **>80%**: Excellent - significant performance gains
- **50-80%**: Good - response caching is beneficial
- **30-50%**: Marginal - consider disabling if overhead isn't worth it
- **<30%**: Poor - disable response caching

#### 3. Top Queries

Monitor the top queries endpoint:

```bash
curl http://localhost:8000/admin/apq/top-queries?limit=10
```

**Look for:**

- High miss rate on frequent queries (cache warming opportunity)
- Queries with long parse times (optimization candidates)
- Unexpected query patterns (potential issues)

### Prometheus Integration

Add to your Prometheus configuration:

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'fraiseql-apq'
    metrics_path: '/admin/apq/metrics'
    scrape_interval: 15s
    static_configs:
      - targets: ['localhost:8000']
```

Available metrics:

- `apq_query_cache_hit_rate`: Query cache effectiveness
- `apq_response_cache_hit_rate`: Response cache effectiveness
- `apq_requests_total`: Total APQ requests
- `apq_storage_bytes_total`: Cache memory usage
- `apq_health_status`: System health status

---

## Optimization Strategies

### 1. Improve Query Cache Hit Rate

#### Strategy: Cache Warming

Pre-populate the cache with common queries:

```python
from fraiseql.storage.apq_store import store_persisted_query, compute_query_hash

# Get top queries from analytics
top_queries = [
    "query GetUsers { users { id name email } }",
    "query GetPosts { posts { id title content } }",
    # ... more queries
]

# Pre-warm the cache
for query in top_queries:
    hash_value = compute_query_hash(query)
    store_persisted_query(hash_value, query)
```

#### Strategy: Client-Side APQ

Configure your GraphQL client to use APQ:

**Apollo Client:**

```javascript
import { createPersistedQueryLink } from "@apollo/client/link/persisted-queries";
import { sha256 } from "crypto-hash";

const link = createPersistedQueryLink({ sha256 });
```

**urql:**

```javascript
import { Client, cacheExchange, fetchExchange } from "urql";
import { persistedExchange } from "@urql/exchange-persisted";

const client = new Client({
  exchanges: [persistedExchange({ generateHash: sha256 }), cacheExchange, fetchExchange],
});
```

### 2. Optimize Response Cache Hit Rate

#### Strategy: Tenant Isolation

For multi-tenant applications:

```python
from fraiseql.middleware.apq_caching import handle_apq_request_with_cache

# Add tenant context
context = {"tenant_id": request.headers.get("X-Tenant-ID")}

cached_response = handle_apq_request_with_cache(
    request=graphql_request,
    backend=backend,
    config=config,
    context=context,  # Tenant-specific caching
)
```

#### Strategy: Clearing Cached Responses

There is no response TTL to tune. A cached response stays until you clear the
backend's cached responses:

```python
from fraiseql.middleware.apq_caching import get_apq_backend

get_apq_backend(config).clear_storage()  # memory backend
```

#### Strategy: Selective Caching

Cache only specific query types:

```python
from fraiseql.middleware.apq_caching import is_cacheable_response

def custom_is_cacheable(response: dict, query_string: str) -> bool:
    """Custom caching logic."""
    # Only cache read-only queries
    if "mutation" in query_string.lower():
        return False

    # Don't cache queries with specific directives
    if "@nocache" in query_string:
        return False

    # Use default logic
    return is_cacheable_response(response)
```

### 3. Storage Optimization

#### Monitor Cache Size

```python
from fraiseql.storage.apq_store import get_storage_stats

stats = get_storage_stats()
print(f"Stored queries: {stats['stored_queries']}")
print(f"Total size: {stats['total_size_bytes'] / 1024:.1f} KB")
```

#### Implement Eviction (PostgreSQL/Redis)

PostgreSQL backend automatically cleans up expired entries. For memory backend, implement periodic cleanup:

```python
import asyncio
from fraiseql.storage.apq_store import clear_storage

async def periodic_cleanup():
    """Clear cache every 24 hours."""
    while True:
        await asyncio.sleep(86400)  # 24 hours
        clear_storage()
        print("APQ cache cleared")

# Run in background
asyncio.create_task(periodic_cleanup())
```

---

## Troubleshooting

### Problem: Low Query Cache Hit Rate (<70%)

**Diagnosis:**

```bash
curl http://localhost:8000/admin/apq/top-queries?limit=20
```

**Common Causes:**

1. **Client not configured for APQ**
   - Solution: Configure GraphQL client to send `persistedQuery` extension
   - Verify: Check network requests for `extensions.persistedQuery.sha256Hash`

2. **High query diversity**
   - Solution: This is expected for APIs with many unique queries
   - Target: Optimize the most frequent queries instead of all queries

3. **Cache cleared frequently**
   - Solution: Use PostgreSQL or Redis backend instead of memory
   - Verify: Check `apq_stored_queries_total` metric over time

4. **Development environment**
   - Solution: Low hit rates are normal during development
   - Action: Focus on production metrics

### Problem: Response Cache Not Working

**Diagnosis:**

```bash
curl http://localhost:8000/admin/apq/health
# Check response_cache_hit_rate
```

**Common Causes:**

1. **Response caching disabled**

   ```python
   # Check config
   config = FraiseQLConfig(apq_cache_responses=True)  # Must be True
   ```

2. **Queries with errors**
   - Responses with errors are never cached
   - Solution: Fix query errors or validation issues

3. **User-specific queries**
   - Different users get different responses
   - Solution: Implement tenant isolation with context

### Problem: High Memory Usage

**Diagnosis:**

```bash
curl http://localhost:8000/admin/apq/metrics | grep storage_bytes
```

**Solutions:**

1. **Turn response caching off** if responses dominate:

   ```python
   config = FraiseQLConfig(database_url="postgresql://...", apq_cache_responses=False)
   ```

2. **Implement cache size limits:**

   ```python
   from fraiseql.storage.apq_store import get_storage_stats, clear_storage

   stats = get_storage_stats()
   if stats["total_size_bytes"] > 100 * 1024 * 1024:  # 100MB
       clear_storage()
   ```

### Problem: Stale Data Being Served

**Diagnosis:**
Response cache serving outdated data after mutations

**Solutions:**

1. **Disable response caching:**

   ```python
   config = FraiseQLConfig(apq_cache_responses=False)
   ```

2. **Clear the cached responses after a mutation:**

   ```python
   from fraiseql.middleware.apq_caching import get_apq_backend

   get_apq_backend(config).clear_storage()  # Drops the cached responses
   ```

3. **Use materialized views instead:**
   - FraiseQL already uses `tv_{entity}` materialized views
   - These provide data-level caching at PostgreSQL layer
   - More appropriate for frequently changing data

---

## Production Best Practices

### 1. Configuration Checklist

✅ **Always Enable:**

- [ ] Query caching (`apq_storage_backend` configured)
- [ ] Metrics tracking (automatic)
- [ ] Health monitoring endpoint
- [ ] Dashboard access for operations team

✅ **Consider Enabling:**

- [ ] Response caching (if read-heavy workload)
- [ ] PostgreSQL/Redis backend (if multi-instance)
- [ ] Prometheus integration (if using monitoring)

✅ **Never Do:**

- [ ] Enable response caching for user-specific data without tenant isolation
- [ ] Use memory backend in multi-instance deployments
- [ ] Ignore health warnings (hit rate <50%)

### 2. Monitoring Setup

**Set up alerts for:**

1. **Critical Alert: Hit Rate <50%**

   ```yaml
   # Prometheus alert
   - alert: APQHitRateCritical
     expr: apq_query_cache_hit_rate < 0.5
     for: 10m
     labels:
       severity: critical
   ```

2. **Warning Alert: Hit Rate <70%**

   ```yaml
   - alert: APQHitRateWarning
     expr: apq_query_cache_hit_rate < 0.7
     for: 30m
     labels:
       severity: warning
   ```

3. **Storage Alert: High Memory Usage**

   ```yaml
   - alert: APQHighStorage
     expr: apq_storage_bytes_total > 100 * 1024 * 1024
     for: 5m
     labels:
       severity: warning
   ```

### 3. Performance Testing

Before enabling in production:

1. **Baseline without APQ:**

   ```bash
   # Disable APQ (hashes are ignored, every request sends its query)
   config = FraiseQLConfig(database_url="postgresql://...", apq_mode="disabled")

   # Run load test
   ab -n 10000 -c 100 http://localhost:8000/graphql
   ```

2. **Test with query cache only:**

   ```bash
   config = FraiseQLConfig(
       apq_storage_backend="memory",
       apq_cache_responses=False,
   )
   ```

3. **Test with full APQ:**

   ```bash
   config = FraiseQLConfig(
       apq_storage_backend="memory",
       apq_cache_responses=True,
   )
   ```

4. **Compare metrics:**
   - Response time percentiles (p50, p95, p99)
   - Throughput (requests/second)
   - Memory usage
   - CPU usage

### 4. Rollout Strategy

**Phase 1: Query Cache Only**

1. Enable memory backend in production
2. Monitor for 1 week
3. Verify hit rate >70%
4. No rollback needed (pure performance gain)

**Phase 2: PostgreSQL Backend** (if multi-instance)

1. Deploy PostgreSQL backend to canary
2. Monitor for 48 hours
3. Verify no increased latency
4. Roll out to production

**Phase 3: Response Caching** (if applicable)

1. Enable for read-only, public queries only
2. Clear the backend after the mutations that change those queries' data
3. Monitor for stale data issues
4. Rollback plan: Set `apq_cache_responses=False`

### 5. Maintenance

**Daily:**

- Check dashboard for warnings
- Monitor hit rates
- Review top queries

**Weekly:**

- Analyze hit rate trends
- Review storage usage
- Check for query pattern changes

**Monthly:**

- Review and optimize top queries
- Audit cache effectiveness

**Quarterly:**

- Performance benchmark comparison
- Review backend choice (memory vs PostgreSQL vs Redis)
- Consider cache warming strategies

---

## Advanced Topics

### Custom Cache Backends

Implement custom storage backend:

```python
from fraiseql.storage.backends.base import APQStorageBackend

class CustomBackend(APQStorageBackend):
    def get_persisted_query(self, hash_value: str) -> str | None:
        # Your implementation
        pass

    def store_persisted_query(self, hash_value: str, query: str) -> None:
        # Your implementation
        pass

    def get_cached_response(self, hash_value: str, context=None) -> dict | None:
        # Your implementation
        pass

    def store_cached_response(self, hash_value: str, response: dict, context=None) -> None:
        # Your implementation
        pass
```

### Integration with CDN

For public APIs, combine with CDN caching:

```python
from fastapi import Response

@app.post("/graphql")
async def graphql_endpoint(request: GraphQLRequest, response: Response):
    # Add cache headers for CDN
    if is_public_query(request):
        response.headers["Cache-Control"] = "public, max-age=300"

    # APQ handles query and response caching
    return await execute_graphql(request)
```

### Multi-Tier Caching Strategy

Combine FraiseQL caching layers:

```
┌────────────────────────────────────────────────────┐
│ CDN Layer (Cloudflare, Fastly)                    │
│ • Full response caching                            │
│ • 5-15 minute TTL                                  │
│ • Public queries only                              │
└─────────────────┬──────────────────────────────────┘
                  │ CDN miss
                  ↓
┌────────────────────────────────────────────────────┐
│ APQ Response Cache                                 │
│ • FraiseQL in-process                              │
│ • No TTL: cleared explicitly                       │
│ • All cacheable queries                            │
└─────────────────┬──────────────────────────────────┘
                  │ Response cache miss
                  ↓
┌────────────────────────────────────────────────────┐
│ APQ Query Cache                                    │
│ • Eliminates parsing overhead                      │
│ • Permanent (no TTL)                               │
│ • All queries                                      │
└─────────────────┬──────────────────────────────────┘
                  │ Query cache miss
                  ↓
┌────────────────────────────────────────────────────┐
│ PostgreSQL Materialized Views (tv_{entity})       │
│ • Data-level caching                               │
│ • Refresh strategy configured per entity           │
│ • All queries                                      │
└─────────────────┬──────────────────────────────────┘
                  │ Materialized view miss
                  ↓
┌────────────────────────────────────────────────────┐
│ PostgreSQL Base Tables                             │
│ • Source of truth                                  │
│ • Full query execution                             │
└────────────────────────────────────────────────────┘
```

---

## Further Reading

- [FraiseQL Performance Guide](./index.md)
- [Caching Guide](./caching.md)
- [GraphQL APQ Specification](https://www.apollographql.com/docs/react/api/link/persisted-queries/)

---

*Last Updated: 2025-10-23 | FraiseQL v1.6.1*

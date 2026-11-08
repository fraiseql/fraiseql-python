# Multi-Tenant APQ (Automatic Persisted Queries)

🟡 INTERMEDIATE | ⏱️ 20 min | 🎯 Performance | 🏷️ Multi-Tenant

Production-ready example demonstrating FraiseQL's built-in tenant-aware APQ caching for multi-tenant SaaS applications.

**What you'll learn:**

- Automatic Persisted Queries (APQ) for bandwidth reduction
- Multi-tenant cache isolation
- Performance optimization techniques
- Cache hit rate monitoring

**Prerequisites:**

- `../blog_simple/` - Basic FraiseQL patterns
- Understanding of multi-tenant architecture

**Next steps:**

- `../caching_example.py` - Alternative caching approaches
- `../turbo_router_with_complexity.py` - Pre-compiled query routing
- `../saas-starter/` - Complete SaaS foundation

## What is APQ?

**Automatic Persisted Queries (APQ)** is a GraphQL optimization technique where:

1. Client sends a **hash** of the query instead of the full query string
2. Server looks up the query in cache using the hash
3. If found, executes it immediately (saves bandwidth + parsing time)
4. If not found, client sends full query + server caches it

**Benefits:**

- ⚡ **Reduced bandwidth:** Hash is ~64 bytes vs. full query (often 1-5KB)
- 🚀 **Faster parsing:** Pre-parsed queries execute immediately
- 💾 **Lower memory:** Deduplicated queries across all clients
- 📱 **Better mobile experience:** Less data transfer

## Multi-Tenant Challenges

In SaaS applications with multiple tenants sharing the same infrastructure:

**Problem:** Traditional APQ caches queries globally, but different tenants might have:

- Different permissions (can't share cached results)
- Different data isolation requirements
- Different query patterns

**FraiseQL Solution:** Tenant-aware APQ that automatically:

- ✅ Isolates cached responses per tenant
- ✅ Prevents data leakage between tenants
- ✅ Maintains high cache hit rates per tenant
- ✅ Works out-of-the-box with context passing

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│ Client Request (Tenant A)                                    │
│ Hash: abc123...                                              │
│ Context: { user: { metadata: { tenant_id: "acme-corp" } } } │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ APQ Cache (Tenant-Aware)                                     │
│                                                              │
│ Key: hash + tenant_id                                        │
│ abc123...@acme-corp  → { users: [...] }  ✅ Hit!            │
│ abc123...@globex-inc → { users: [...] }  (Different data)   │
└─────────────────────────────────────────────────────────────┘
```

## Features Demonstrated

- ✅ **Tenant Isolation:** Each tenant's cached responses are isolated
- ✅ **Cache Statistics:** Track hit rates per tenant
- ✅ **Custom Backend:** Extend built-in backends with stats
- ✅ **Context Propagation:** Extract tenant_id from request context
- ✅ **Data Leakage Prevention:** Automatic tenant-key prefixing

## Setup

### 1. Install Dependencies

```bash
pip install fraiseql
```

### 2. Run the Example

```bash
python main.py
```

### Output

```
============================================================
Multi-Tenant APQ Caching Example
============================================================

--- Phase 1: Initial Requests (Cache Misses) ---
✗ Cache MISS for tenant 'acme-corp'
✗ Cache MISS for tenant 'acme-corp'
✗ Cache MISS for tenant 'globex-inc'
✗ Cache MISS for tenant 'globex-inc'

--- Phase 2: Repeated Requests (Cache Hits) ---
✓ Cache HIT for tenant 'acme-corp'
✓ Cache HIT for tenant 'acme-corp'
✓ Cache HIT for tenant 'globex-inc'
✓ Cache HIT for tenant 'globex-inc'

--- Phase 3: Verify Tenant Isolation ---
✓ Cache HIT for tenant 'acme-corp'
✓ Cache HIT for tenant 'globex-inc'
✅ Tenant isolation verified - no data leakage

--- Cache Statistics ---
acme-corp    - Hits:   3, Misses:   2, Hit Rate: 60.0%
globex-inc   - Hits:   3, Misses:   2, Hit Rate: 60.0%
```

## Architecture

### Tenant Context Extraction

The APQ backends read the tenant from the request context: `context["tenant_id"]`,
`context["user"]["tenant_id"]` or `context["user"]["metadata"]["tenant_id"]`. Put it
there with a `context_getter`, from the verified token (see
[Production Configuration](#production-configuration)).

### Cache Key Format

**Without tenant isolation (traditional APQ):**

```
Key: hash
abc123... → { users: [...] }  # All tenants share same cache
```

**With tenant isolation (FraiseQL):**

```
Key: tenant_id:hash
acme-corp:abc123...  → { users: [...acme data...] }
globex-inc:abc123... → { users: [...globex data...] }
```

The response cache built from `apq_cache_responses` also keys on the variables and,
for an authenticated request, the user's id (`user_id`, `id` or `sub` of
`context["user"]`).

### Built-in Backend Support

`apq_storage_backend` is `"memory"` (one process; development, testing, a single
instance), `"postgresql"` (tables `apq_queries` / `apq_responses` in the app's
database, created on first use, shared between instances) or `"custom"` (your own
class, named in `apq_backend_config["backend_class"]`, for Redis say):

```python
config = FraiseQLConfig(
    database_url="postgresql://localhost/myapp",
    apq_storage_backend="postgresql",
    apq_cache_responses=True,
    apq_response_cache_ttl=3600,  # 1 hour; 0 keeps responses
)
```

## Custom Backend with Statistics

The example shows how to extend built-in backends:

```python
class APQBackendWithStats(MemoryAPQBackend):
    """Track cache hit/miss rates per tenant."""

    def __init__(self):
        super().__init__()
        self._stats = {
            "cache_hits": {},
            "cache_misses": {},
            "total_requests": 0
        }

    def get_cached_response(self, hash_value: str, context):
        tenant_id = self.extract_tenant_id(context)
        response = super().get_cached_response(hash_value, context)

        if response:
            self._stats["cache_hits"][tenant_id] += 1
        else:
            self._stats["cache_misses"][tenant_id] += 1

        return response
```

## Production Configuration

### Complete FastAPI Setup

```python
import jwt
from fastapi import Request

from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

config = FraiseQLConfig(
    database_url="postgresql://localhost/myapp",
    apq_storage_backend="memory",  # or "postgresql" to share it between instances
    apq_cache_responses=True,
    apq_response_cache_ttl=3600,  # 1 hour
)


async def get_context(request: Request) -> dict:
    """Tenant and user from the verified JWT."""
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return {}
    return {"tenant_id": payload["tenant_id"], "user_id": payload["sub"]}


app = create_fraiseql_app(
    config=config,
    types=[User, Product],
    queries=[users, products],
    context_getter=get_context,
)
```

`tenant_id` keys the APQ cache and is also set as `app.tenant_id` for each query, so a
view or an RLS policy can filter on `current_setting('app.tenant_id')`.

### Apollo Client Integration

FraiseQL APQ is compatible with Apollo Client's APQ implementation:

```javascript
import { ApolloClient, InMemoryCache, HttpLink } from '@apollo/client';
import { createPersistedQueryLink } from '@apollo/client/link/persisted-queries';
import { sha256 } from 'crypto-hash';

const httpLink = new HttpLink({ uri: 'http://localhost:8000/graphql' });

const client = new ApolloClient({
  cache: new InMemoryCache(),
  link: createPersistedQueryLink({ sha256 }).concat(httpLink),
});

// Apollo automatically sends hash first, falls back to full query
const { data } = await client.query({
  query: GET_USERS_QUERY,
  context: {
    headers: {
      Authorization: `Bearer ${jwtToken}`  // Contains tenant_id
    }
  }
});
```

## Performance Metrics

### Expected Cache Hit Rates

| Scenario | Expected Hit Rate | Notes |
|----------|-------------------|-------|
| Mobile app (stable queries) | 95-99% | Limited query variations |
| Web SPA (moderate) | 85-95% | More query variations |
| Dynamic dashboards | 70-85% | Frequent filter changes |
| Development | 30-50% | Constantly changing queries |

### Bandwidth Savings

**Example query:**

```graphql
query GetUserDashboard($filters: UserFilters!) {
  users(where: $filters, limit: 50) {
    id
    name
    email
    profile {
      avatar
      bio
      settings
    }
    posts(limit: 10) {
      id
      title
      content
      createdAt
    }
  }
}
```

- **Full query:** ~450 bytes
- **APQ hash:** 64 bytes
- **Savings:** 86% reduction per request
- **At 1M requests/day:** 386 MB saved

### Performance Comparison

| Metric | Without APQ | With APQ | Improvement |
|--------|-------------|----------|-------------|
| Request size | 450 bytes | 64 bytes | 86% smaller |
| Parsing time | 0.5-1ms | 0ms (cached) | 100% faster |
| Bandwidth (1M req) | 450 MB | 64 MB | 86% reduction |
| Mobile latency | +20-50ms | +0ms | Significant |

## Monitoring & Observability

### Track Cache Performance

Subclass the backend you use and count in its `get_cached_response`, as
`APQBackendWithStats` in `main.py` does, then run it with
`apq_storage_backend="custom"` and
`apq_backend_config={"backend_class": "myapp.apq.MonitoredAPQBackend"}`. A custom
backend class is called with `apq_backend_config`:

```python
from prometheus_client import Counter

from fraiseql.storage.backends.memory import MemoryAPQBackend

apq_cache_hits = Counter("apq_cache_hits_total", "APQ cache hits", ["tenant_id"])
apq_cache_misses = Counter("apq_cache_misses_total", "APQ cache misses", ["tenant_id"])


class MonitoredAPQBackend(MemoryAPQBackend):
    def __init__(self, backend_config: dict) -> None:
        super().__init__(response_ttl=backend_config.get("response_ttl"))

    def get_cached_response(self, hash_value, context=None):
        tenant_id = self.extract_tenant_id(context) or "global"
        response = super().get_cached_response(hash_value, context)

        if response:
            apq_cache_hits.labels(tenant_id=tenant_id).inc()
        else:
            apq_cache_misses.labels(tenant_id=tenant_id).inc()

        return response
```

### Grafana Dashboard

Monitor per-tenant cache performance:

- Hit rate by tenant (target: >85%)
- Cache size by tenant
- Average response time with/without cache
- Bandwidth saved

## Security Considerations

### 1. Tenant Isolation

**FraiseQL automatically ensures:**

- ✅ Cache keys include tenant_id
- ✅ No cross-tenant cache hits
- ✅ Context validation before caching

**Your responsibility:**

- ✅ Validate JWT signatures
- ✅ Extract tenant_id securely
- ✅ Don't trust client-provided tenant_id

### 2. Cache Poisoning Prevention

FraiseQL hashes a query's text itself: a request whose query doesn't hash to its
`sha256Hash` gets HTTP 400 (`provided sha does not match query`) and nothing is stored.
With `apq_mode="required"`, only hashes the server already knows run (register them
with `apq_queries_dir`).

### 3. TTL Configuration

```python
# Production recommendation
config = FraiseQLConfig(
    database_url="postgresql://localhost/myapp",
    apq_cache_responses=True,
    apq_response_cache_ttl=3600,  # 1 hour
)

# Considerations:
# - Too short: Low hit rate
# - Too long: Stale data risk
# - Invalidate on schema changes
```

## Troubleshooting

### Low Cache Hit Rates

**Problem:** Cache hit rate <50%

**Possible causes:**

1. **Queries not stable** - Use fragments, avoid inline queries
2. **TTL too short** - Increase `apq_response_cache_ttl`
3. **Too many tenants** - Scale the storage backend
4. **Development mode** - Expected, ignore

### Data Leakage

**Problem:** Tenant seeing another tenant's data

**Debug:**

```python
# Add logging to extract_tenant_id
def extract_tenant_id(self, context):
    tenant_id = super().extract_tenant_id(context)
    print(f"🔍 Extracted tenant_id: {tenant_id}")
    return tenant_id
```

**Check:**

- JWT contains correct tenant_id
- Middleware extracts it properly
- Context passes through to APQ backend

### Cache Misses After Deployment

**Problem:** All cache misses after deploying new code

**Cause:** Query strings changed (different hash)

**Solutions:**

1. **Pre-warm cache** - Send queries from CI/CD
2. **Gradual rollout** - Blue/green deployment
3. **Accept temporary miss rate** - Cache rebuilds quickly

## Advanced Patterns

### Cache Warming

Pre-populate the cache by sending the common queries once per tenant, from CI/CD or a
startup task, with a token for that tenant: the first APQ request with a query's text
stores it, and with `apq_cache_responses` stores its response for the tenant.

### Cache Invalidation

`apq_response_cache_ttl` expires cached responses. To drop them all, clear the
backend's storage (`clear_storage()` on the memory backend), or, with the
`postgresql` backend, delete rows from `apq_responses`.

## Testing

### Unit Tests

```python
import pytest
from examples.apq_multi_tenant.main import APQBackendWithStats

@pytest.mark.asyncio
async def test_tenant_isolation():
    """Verify tenants can't access each other's cache."""
    backend = APQBackendWithStats()

    # Tenant A caches a response
    hash_value = "abc123"
    context_a = {"user": {"metadata": {"tenant_id": "tenant-a"}}}
    backend.store_cached_response(hash_value, {"data": "A"}, context_a)

    # Tenant B requests same hash
    context_b = {"user": {"metadata": {"tenant_id": "tenant-b"}}}
    result = backend.get_cached_response(hash_value, context_b)

    # Should be cache miss (isolated)
    assert result is None
```

### Integration Tests

```bash
# Run the example
pytest tests/integration/test_apq_multi_tenant.py -v
```

## Related Examples

- [`../turbo_router_with_complexity.py`](../turbo_router_with_complexity.py) - Pre-compiled queries for even better performance
- [`../security/`](../security/README.md) - JWT authentication patterns

## References

- [Apollo APQ Specification](https://www.apollographql.com/docs/apollo-server/performance/apq/)
- [GraphQL Best Practices - Persisted Queries](https://graphql.org/learn/best-practices/#persisted-queries)
- [Multi-Tenancy Patterns](https://docs.microsoft.com/en-us/azure/architecture/patterns/multitenancy)

## Next Steps

1. **Add monitoring** - Track hit rates per tenant
2. **Benchmark** - Measure actual bandwidth savings
3. **Scale Redis** - Add replicas for high availability
4. **Cache warming** - Pre-populate common queries
5. **Custom TTL** - Per-query TTL configuration

---

**This example demonstrates production-ready multi-tenant APQ caching with FraiseQL. Zero configuration needed - just pass context with tenant_id!** ✨

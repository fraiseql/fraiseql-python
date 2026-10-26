<!-- Skip to main content -->
---

title: Automatic Persisted Queries (APQ) Specification
description: - **Reduced Bandwidth**: Send 64-character hash instead of multi-kilobyte queries
keywords: ["format", "compliance", "protocol", "specification", "standard"]
tags: ["documentation", "reference"]
---

# Automatic Persisted Queries (APQ) Specification

**Status:** Stable
**Version**: 1.0
**Last Updated**: 2026-01-11

## Overview

**Automatic Persisted Queries (APQ)** is a protocol for optimizing GraphQL requests by allowing clients to send only a stable hash instead of the full query string. FraiseQL provides comprehensive APQ support with three distinct security modes and multiple storage backends for the query hash→query string mapping.

### Key Benefits

- **Reduced Bandwidth**: Send 64-character hash instead of multi-kilobyte queries
- **Query Allowlisting**: Enforce only pre-approved queries in production
- **Query String Storage**: Persistent hash→query mapping across restarts and instances
- **Security**: Cryptographic validation of query integrity
- **Production Safety**: Prevent arbitrary query injection attacks
- **Compatible with Query Result Caching**: Works seamlessly with optional response caching layer (see Caching Specification)

### Architecture

```text
<!-- Code example in TEXT -->
Client
  ↓
APQ Request (hash ± optional query for registration)
  ↓
FraiseQL Router
  ├─ [Mode Enforcement] Check if arbitrary queries allowed
  ├─ [Hash Validation] Extract and validate SHA-256 hash
  ├─ [Query Resolution] Look up query string in APQ store
  │  ├─ If registration: Store hash→query mapping for future use
  │  └─ Get full query string from storage
  ├─ [Query Result Cache Lookup] (Optional) Try cached result
  ├─ [GraphQL Execution] Parse, validate, execute query with variables
  └─ [Store Result Cache] (Optional) Cache query result if enabled
  ↓
Return Result (from cache or freshly computed)
```
<!-- Code example in TEXT -->

---

## Important: APQ vs Query Result Caching

**APQ (this specification)**: Stores the **hash → query string mapping**. Clients send only the 64-character hash instead of the full query string, reducing bandwidth. The server looks up the full query before execution.

**Query Result Caching** (separate feature, see Caching Specification): Optionally caches the **computed results** of queries to avoid re-execution. This is a completely separate feature that works alongside APQ.

**How they work together**:

1. Client sends: APQ hash + variables
2. Server looks up query string from hash
3. Server checks query result cache with (query + variables)
4. If cache hit → return cached result (fastest path, no execution)
5. If cache miss → execute query with variables → optionally cache result

This spec focuses on APQ (steps 1-2). See the Caching Specification for query result caching (steps 3-5).

---

## Security Modes

FraiseQL supports three APQ security modes, allowing you to balance flexibility with security based on your deployment environment.

### OPTIONAL Mode (Default)

**Configuration**:

```python
<!-- Code example in Python -->
config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    apq_mode="optional"
)
```
<!-- Code example in TEXT -->

**Behavior**:

- ✅ Accepts both persisted query hashes and full query strings
- ✅ Allows new query registration (hash + query) on first request; the query must
  hash to `sha256Hash` (see Hash Mismatch below)
- ✅ Automatically stores queries for future hash-only requests
- ✅ Useful for development and gradual client migration

**Request Examples**:

*First request - register and execute*:

```json
<!-- Code example in JSON -->
{
  "extensions": {
    "persistedQuery": {
      "version": 1,
      "sha256Hash": "e4c7e8f5a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7"
    }
  },
  "query": "query { users { id name } }"
}
```
<!-- Code example in TEXT -->

*Subsequent request - hash only*:

```json
<!-- Code example in JSON -->
{
  "extensions": {
    "persistedQuery": {
      "version": 1,
      "sha256Hash": "e4c7e8f5a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7"
    }
  }
}
```
<!-- Code example in TEXT -->

**Use Cases**:

- Development environments
- Client SDKs during initial rollout
- Mixed deployment scenarios (some clients updated, others not)

---

### REQUIRED Mode

**Configuration**:

```python
<!-- Code example in Python -->
config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    apq_mode="required"
)
```
<!-- Code example in TEXT -->

**Behavior**:

- ✅ Only runs persisted queries the server already knows: loaded from
  `apq_queries_dir` at startup, registered by the operator
  (`register_queries` / `store_persisted_query`), or already in the `postgresql`
  backend's table
- ❌ Rejects all arbitrary (non-hash) queries
- ❌ Clients cannot register queries: a request with a hash the server doesn't know
  and the query text is refused (`PERSISTED_QUERY_NOT_IN_LIST`), and nothing is stored
- ✅ A query text sent with a hash must hash to it (see Hash Mismatch below), so a
  known hash always runs the text the server stored
- ✅ Prevents query injection attacks and unauthorised GraphQL exploration
- ❌ `POST /graphql/rust` (when `enable_rust_endpoint=True`) takes query text only, so
  it refuses every request with `ARBITRARY_QUERY_NOT_ALLOWED`

**Request Examples**:

*Hash-only request (runs if the hash is registered)*:

```json
<!-- Code example in JSON -->
{
  "extensions": {
    "persistedQuery": {
      "version": 1,
      "sha256Hash": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1"
    }
  }
}
```
<!-- Code example in TEXT -->

An unknown hash gets the usual `PERSISTED_QUERY_NOT_FOUND`. An Apollo client then
sends the hash with the query text once; in `required` mode that request gets:

```json
<!-- Code example in JSON -->
{
  "errors": [
    {
      "message": "PersistedQueryNotInList",
      "extensions": {
        "code": "PERSISTED_QUERY_NOT_IN_LIST",
        "details": "This server only runs pre-registered persisted queries (apq_mode='required'); this hash is not registered."
      }
    }
  ]
}
```
<!-- Code example in TEXT -->

The code is neither `PERSISTED_QUERY_NOT_FOUND` (the client would send the text again)
nor `PERSISTED_QUERY_NOT_SUPPORTED` (the client would stop sending hashes).

*Arbitrary query (REJECTED)*:

```json
<!-- Code example in JSON -->
{
  "query": "query { __schema { types { name } } }"
}
```
<!-- Code example in TEXT -->

**Response to Rejected Request**:

```json
<!-- Code example in JSON -->
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
<!-- Code example in TEXT -->

**Use Cases**:

- Production environments
- Regulated industries (compliance/audit requirements)
- High-security deployments
- Preventing introspection-based attacks

---

### DISABLED Mode

**Configuration**:

```python
<!-- Code example in Python -->
config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    apq_mode="disabled"
)
```
<!-- Code example in TEXT -->

**Behavior**:

- ✅ Accepts only full query strings (regular GraphQL requests)
- ❌ Completely ignores APQ extensions
- ❌ Queries with APQ hashes are treated as regular requests
- ✅ Useful when APQ infrastructure is not needed

**Request Examples**:

*Regular query (processed normally)*:

```json
<!-- Code example in JSON -->
{
  "query": "query { articles { id title content } }"
}
```
<!-- Code example in TEXT -->

*APQ request with hash (treated as regular, hash ignored)*:

```json
<!-- Code example in JSON -->
{
  "extensions": {
    "persistedQuery": {
      "version": 1,
      "sha256Hash": "..."
    }
  },
  "query": "query { articles { id title content } }"
}
```
<!-- Code example in TEXT -->

*APQ hash-only request (FAILS - no query)*:

```json
<!-- Code example in JSON -->
{
  "extensions": {
    "persistedQuery": {
      "version": 1,
      "sha256Hash": "..."
    }
  }
}
```
<!-- Code example in TEXT -->

**Response to Hash-Only Request**:

```json
<!-- Code example in JSON -->
{
  "errors": [
    {
      "message": "No query provided",
      "extensions": {"code": "GRAPHQL_PARSE_FAILED"}
    }
  ]
}
```
<!-- Code example in TEXT -->

**Use Cases**:

- Backward compatibility during migration
- Environments without APQ infrastructure
- Explicit opt-out of APQ features

---

## Query Hash Generation

FraiseQL uses **SHA-256** hashing for deterministic query identification and security validation.

### Hash Algorithm

```python
<!-- Code example in Python -->
import hashlib

def compute_query_hash(query: str) -> str:
    """Compute SHA-256 hash of a GraphQL query."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()
```
<!-- Code example in TEXT -->

**Properties**:

- **Algorithm**: SHA-256 (FIPS 180-4 standard)
- **Output Length**: 64 hexadecimal characters (256 bits)
- **Deterministic**: Same query → same hash
- **Collision Resistant**: Different queries produce different hashes (cryptographically guaranteed)
- **Case Sensitive**: `{ user { id } }` ≠ `{ user { ID } }`
- **Whitespace Sensitive**: `{user{id}}` ≠ `{ user { id } }`

### Variable-Aware Hashing (Security Critical)

When variables are present in requests, they **must be included in the response cache key** to prevent data leakage between requests with different variables.

```python
<!-- Code example in Python -->
import json

def compute_response_cache_key(
    query_hash: str,
    variables: dict[str, Any] | None = None,
) -> str:
    """Compute response cache key including variables for security."""
    if not variables or variables == {}:
        return query_hash

    # Normalize variables: sort keys for consistent hashing
    var_json = json.dumps(variables, sort_keys=True, separators=(",", ":"))
    combined = f"{query_hash}:{var_json}"
    return hashlib.sha256(combined.encode()).hexdigest()
```
<!-- Code example in TEXT -->

### Security Example: Preventing Data Leakage

**Scenario**: Cached response from User A's request leaks to User B

```python
<!-- Code example in Python -->
# User A requests: query getUser($userId: ID!) with userId: "alice-123"
query_hash = "e4c7e8f5a1b2c3d4..."
variables_a = {"userId": "alice-123"}
cache_key_a = compute_response_cache_key(query_hash, variables_a)

# User B requests: same query with userId: "bob-456"
variables_b = {"userId": "bob-456"}
cache_key_b = compute_response_cache_key(query_hash, variables_b)

# CRITICAL: Different cache keys prevent data leakage!
assert cache_key_a != cache_key_b
# Result: cache_key_a = "hash:{"userId":"alice-123"}" (SHA-256)
# Result: cache_key_b = "hash:{"userId":"bob-456"}" (SHA-256)
```
<!-- Code example in TEXT -->

Without variable-aware cache keys, both users would receive the same cached response containing Alice's data.

### Computing Hashes in Clients

**JavaScript/Apollo Client**:

```javascript
<!-- Code example in JAVASCRIPT -->
import crypto from 'crypto';

function computeAPQHash(query) {
  return crypto
    .createHash('sha256')
    .update(query)
    .digest('hex');
}

const hash = computeAPQHash(query);
```
<!-- Code example in TEXT -->

**Python Client**:

```python
<!-- Code example in Python -->
import hashlib

def compute_apq_hash(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()
```
<!-- Code example in TEXT -->

---

## APQ Query Storage Backends

FraiseQL provides three storage backend options for the hash→query string mapping: in-memory (development), database (production), and pluggable custom backends. These store the association between query hashes and their full GraphQL query strings.

### Memory Backend (Development)

**Configuration**:

```python
<!-- Code example in Python -->
config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    apq_storage_backend="memory",  # Default for local development
)
```
<!-- Code example in TEXT -->

**Characteristics**:

- ✅ **No external dependencies** - uses Python dict
- ✅ **Fast** - < 1µs lookups
- ✅ **Simple** - zero configuration
- ❌ **Non-persistent** - queries lost on process restart
- ❌ **Non-scalable** - single process only
- ❌ **No cluster support** - each pod has separate storage

**Data Storage**:

```python
<!-- Code example in Python -->
# In-process dictionary: hash → query string mapping
_query_storage = {
    "e4c7e8f5...": "query { users { id name } }",
    "a1b2c3d4...": "query { products { id price } }",
}
```
<!-- Code example in TEXT -->

**Purpose**:

- Maps query hashes to full GraphQL query strings
- Enables clients to send only hash in subsequent requests
- No tenant isolation needed (queries are not sensitive data; they're the schema contract)

**Use Cases**:

- Local development
- CI/CD pipelines
- Single-instance deployments
- Testing environments

---

### Database Backend (Production)

**Configuration**:

```python
<!-- Code example in Python -->
config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    apq_storage_backend="postgresql",
    apq_backend_config={
        "table_prefix": "apq_",
        "auto_create_tables": True,
        "connection_timeout": 30,
    }
)
```
<!-- Code example in TEXT -->

> **Note:** the `postgresql` backend opens its own small connection pool to
> `database_url` (or `apq_backend_config["database_url"]`) on the first APQ request,
> and creates its tables if they don't exist (`auto_create_tables`, default on).
> Persisted queries survive a restart and are shared by every instance using that
> database. Its methods are synchronous (one indexed query each; a persisted query's
> text is kept in process once read), so the `/graphql` route calls them in a worker
> thread: a slow or unavailable database doesn't stall the event loop. Up to
> `pool_max_size` lookups run at once; the others wait for a connection, at most
> `connection_timeout` seconds.

`apq_backend_config` keys: `database_url` (default: the app's `database_url`),
`table_prefix` (default `"apq_"`, may include a schema: `"myschema.apq_"`),
`auto_create_tables` (default `True`), `connection_timeout` (seconds, default 30) and
`pool_max_size` (default 4).

**Database Tables**:

#### apq_queries Table

```sql
<!-- Code example in SQL -->
CREATE TABLE apq_queries (
    hash VARCHAR(64) PRIMARY KEY,
    query TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for efficient storage
CREATE INDEX idx_apq_queries_created ON apq_queries (created_at);
```
<!-- Code example in TEXT -->

**Columns**:

- `hash`: SHA-256 hash (64 chars) - unique identifier
- `query`: Full GraphQL query string - text field for storage
- `created_at`: Registration timestamp (UTC)
- `updated_at`: Last access timestamp (UTC)

**Purpose**: Stores the hash→query string mapping for all registered persisted queries. This is NOT a response cache, but a lookup table that persists across restarts and instances.

**Characteristics**:

- ✅ **Persistent** - survives process restarts
- ✅ **Scalable** - shared across multiple instances
- ✅ **Cluster-ready** - all pods use same database
- ✅ **Observable** - can query storage via SQL
- ⚠️ **Latency** - 10-50ms lookups (vs < 1µs in-memory)
- ⚠️ **Dependencies** - requires compatible database (PostgreSQL 13+, or other supported databases)

**Performance**:

- Query lookup: ~15-30ms (cold cache), < 2ms (warm)
- Memory usage: Minimal (queries stored in database, not process memory)

**Use Cases**:

- Production deployments
- Multi-instance/cluster setups
- Long-running services (> 24 hours)
- High-availability requirements

**Maintenance**:

Monitor storage usage (PostgreSQL example):

```sql
<!-- Code example in SQL -->
-- Check APQ query table size
SELECT
    pg_size_pretty(pg_total_relation_size('apq_queries')) as table_size,
    count(*) as query_count
FROM apq_queries;
```
<!-- Code example in TEXT -->

Clean up unused queries (optional):

```sql
<!-- Code example in SQL -->
-- View queries by registration date
SELECT hash, created_at, length(query) as query_size
FROM apq_queries
ORDER BY created_at DESC;

-- Delete very old queries if needed (careful: clients may still reference)
DELETE FROM apq_queries
WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '30 days';
```
<!-- Code example in TEXT -->

---

### Custom Backend (Pluggable)

For specialized use cases (Redis, DynamoDB, custom cache), implement a custom backend:

**Configuration**:

```python
<!-- Code example in Python -->
config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    apq_storage_backend="custom",
    apq_backend_config={
        "backend_class": "myapp.storage.RedisAPQBackend",
        "redis_url": "redis://localhost:6379/0",
        "ttl": 3600,  # 1 hour
    }
)
```
<!-- Code example in TEXT -->

**Custom Backend Interface**:

Custom backends must implement the APQ storage interface with the following methods:

- `get_persisted_query(hash_value)` → query string or None
- `store_persisted_query(hash_value, query)` → None; raise `ValueError` when
  `hash_value` is not the SHA-256 of `query`
  (`fraiseql.storage.apq_store.check_query_hash` does it), as the built-in backends do
- `register_queries(queries)` → dict mapping hash to query
- `get_storage_stats()` → dict with backend statistics

The methods are synchronous. A backend whose methods do blocking I/O (a database, a
network cache) sets the class attribute `blocking_io = True`, and the `/graphql` route
then calls them in a worker thread (`asyncio.to_thread`) instead of on the event loop;
such a backend must be thread-safe. The default, `False`, calls them on the event loop.

**Example Use Cases**:

- Redis backend for distributed systems
- DynamoDB for AWS deployments
- Memcached for lightweight caching
- Custom database backends

**Backend Discovery**:

- FraiseQL dynamically imports backend class via reflection
- Class must be importable from full path (module.ClassName)
- Receives the `apq_backend_config` dict as the constructor's first argument
- Also receives `response_ttl=` (`apq_response_cache_ttl`) and `database_url=` (the
  app's `database_url`) if the constructor has a parameter of that name; `**kwargs`
  gets neither
- A subclass of `MemoryAPQBackend` that keeps its `__init__(response_ttl=None)` gets
  only `response_ttl=`, and a constructor without parameters is called without
  arguments

---

## Query Registration Workflow

### Build-Time Registration (Recommended for Production)

Pre-register all queries at application startup for zero-latency registration:

**File Structure**:

```text
<!-- Code example in TEXT -->
src/
├── graphql/
│   ├── queries/
│   │   ├── user.graphql
│   │   ├── products.graphql
│   │   └── orders.graphql
│   └── mutations/
│       ├── createUser.graphql
│       └── updateProduct.graphql
```
<!-- Code example in TEXT -->

**Configuration**:

```python
<!-- Code example in Python -->
config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    apq_mode="required",
    apq_storage_backend="postgresql",
    apq_queries_dir="./src/graphql",  # Operations registered as persisted queries
)
```
<!-- Code example in TEXT -->

**Behavior**:

1. At startup, the app fails (`FileNotFoundError`) if `apq_queries_dir` doesn't exist
2. When the first APQ request creates the APQ backend, FraiseQL scans
   `apq_queries_dir` recursively for `.graphql` and `.gql` files
3. Splits each file into its operations (`query`, `mutation`, `subscription`)
4. Stores each operation under the SHA-256 of its text as written in the file, without
   surrounding whitespace (for a file with one operation: the whole file, stripped)
5. Ready to serve hash-only APQ requests (in `required` mode: only these, plus what
   the backend already holds)

The hash is the SHA-256 of the exact text the client sends, so the files must hold
each operation the way your client's build emits it. A fragment is kept with the
operation written before it in the same file; put each operation in its own file,
followed by the fragments it uses. In `disabled` mode the directory isn't read.

**Benefits**:

- ✅ Zero registration latency (pre-loaded)
- ✅ Deterministic hashes (reproducible builds)
- ✅ Enforces "known queries only" in production
- ✅ Enables build-time optimization

### Runtime Registration (Dynamic)

Allow clients to register new queries on first request:

**Configuration**:

```python
<!-- Code example in Python -->
config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    apq_mode="optional",  # Allows registration
    apq_storage_backend="postgresql",
    # No apq_queries_dir - start empty
)
```
<!-- Code example in TEXT -->

**Registration Flow**:

*First request (register)*:

```json
<!-- Code example in JSON -->
POST /graphql HTTP/1.1

{
  "extensions": {
    "persistedQuery": {
      "version": 1,
      "sha256Hash": "e4c7e8f5a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7"
    }
  },
  "query": "query GetUser($id: ID!) { user(id: $id) { id name email } }",
  "variables": {"id": "user-123"}
}
```
<!-- Code example in TEXT -->

*Server processes*:

1. Extracts hash: `e4c7e8f5...`
2. Stores query in backend: `e4c7e8f5... → "query GetUser..."`
3. Executes request normally
4. Stores response in cache (if enabled)
5. Returns response

*Subsequent requests (cached)*:

```json
<!-- Code example in JSON -->
POST /graphql HTTP/1.1

{
  "extensions": {
    "persistedQuery": {
      "version": 1,
      "sha256Hash": "e4c7e8f5a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7"
    }
  },
  "variables": {"id": "user-456"}
}
```
<!-- Code example in TEXT -->

*Server processes*:

1. Extracts hash: `e4c7e8f5...`
2. Looks up query in backend: Found!
3. Tries response cache with variables hash
4. If cache miss, executes query
5. Stores response in cache
6. Returns response

**Benefits**:

- ✅ Client-driven optimization
- ✅ Gradual adoption (mixed deployment)
- ✅ Flexible (no pre-registration needed)
- ⚠️ First request slower (registration + execution)

---

## Query Result Caching Integration (Optional Feature)

APQ can optionally work with Query Result Caching (a separate feature described in the Caching Specification). Query result caching provides a fast path that bypasses GraphQL execution entirely for previously computed results. This section describes how APQ integrates with query result caching when enabled.

### Architecture

**Two-Layer System**:

```text
<!-- Code example in TEXT -->
Request
  ↓
Layer 1: Response Cache (JSON passthrough)
  ├─ Hit: Return pre-computed JSON response directly (fastest!)
  └─ Miss: Continue to query execution
  ↓
Layer 2: GraphQL Execution
  ├─ Parse query
  ├─ Validate
  ├─ Execute through Rust pipeline
  └─ Compute response
  ↓
Store in Response Cache
  ↓
Return Response
```
<!-- Code example in TEXT -->

**Performance Impact**:

- Response cache hit: ~1-50ms (depending on backend)
- Cache miss: Normal execution time (100-500ms+)
- Overall improvement: 5-20x throughput increase (with 60-80% hit rate)

### Configuration

```python
<!-- Code example in Python -->
config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    apq_mode="optional",
    apq_storage_backend="postgresql",
)
```
<!-- Code example in TEXT -->

**Note**: Query result caching is not a `FraiseQLConfig` setting; it is configured separately from APQ. See the Caching Specification for complete configuration options including TTL, backends, and complexity-aware settings.

### Cache Key Generation (Query Result Caching)

When query result caching is enabled, the cache key includes:

- Query hash (SHA-256 of normalized query)
- Variables (normalized, sorted JSON)
- Tenant ID (for multi-tenant isolation)
- Complexity tier (for complexity-aware TTL)

**Key Construction**:

```text
<!-- Code example in TEXT -->
cache_key = sha256(query_hash + ":" + sorted_variables_json + ":" + tenant_id + ":" + complexity)
```
<!-- Code example in TEXT -->

**Security Property**:

Each unique combination of (query + variables + tenant) produces a different cache key. This prevents data leakage:

- Request A: query hash + variables `{"userId": "alice"}` → cache key A
- Request B: query hash + variables `{"userId": "bob"}` → cache key B
- Result: Different cache keys, no data leakage between users

### Storing Query Results (Query Result Caching)

When query result caching is enabled:

**Automatic Flow**:

1. GraphQL query executes normally
2. Result computed
3. If no errors and result has data:
   - Filter result by requested fields (defense in depth)
   - Include tenant_id for multi-tenant isolation
   - Store in cache backend with TTL
4. Subsequent requests with same query + variables hit cache (no execution needed)

### Field Selection Filtering (Defense in Depth)

Both APQ and Query Result Caching implement field selection filtering as a security measure. When processing a persisted query request, FraiseQL automatically filters the response to include only the fields requested in the original query.

**Where Applied**:

1. APQ responses (even if hash-only request) - before returning to client
2. Query result cache entries (before caching) - prevent over-caching of sensitive data

**Process**:

1. Parse query's selection set (which fields were requested)
2. Identify requested fields from GraphQL AST
3. Remove non-requested fields from response
4. Return filtered response to client or cache

**Example**:

Query: `query GetUser { user { id name } }` (only `id` and `name` requested)

Response before filtering:

```json
<!-- Code example in JSON -->
{"data": {"user": {"id": "123", "name": "Alice", "email": "alice@example.com", "ssn": "123-45-6789"}}}
```
<!-- Code example in TEXT -->

Response after field selection filtering:

```json
<!-- Code example in JSON -->
{"data": {"user": {"id": "123", "name": "Alice"}}}
```
<!-- Code example in TEXT -->

**Benefits**:

- Even if database response includes sensitive fields (email, SSN, etc.), only requested fields are returned
- Prevents accidental data leakage via responses
- Applied consistently whether using APQ or not
- Query result cache entries are also filtered, preventing over-caching of sensitive data

### Query Result Cache Invalidation

Query result cache invalidation is managed by the query result caching system. See the Caching Specification for details on:

- TTL-based automatic expiration
- Complexity-aware TTL policies
- Manual cache invalidation
- graphql-cascade integration for mutation-based invalidation

---

## Production Configuration Examples

### Development Environment

```python
<!-- Code example in Python -->
config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    apq_mode="optional",                    # Allow registration
    apq_storage_backend="memory",           # Fast, no persistence needed
    apq_cache_responses=True,               # Optimization
)
```
<!-- Code example in TEXT -->

A cached response is served for `apq_response_cache_ttl` seconds after it was stored
(default 600; 0 means it does not expire), then the query runs again and its new
response is stored.

A response is cached when an APQ request runs a query (never a mutation or a
subscription) without errors, whichever execution path built it. The key is the
query's hash, its variables, the tenant (`tenant_id` in the request context) and, for
an authenticated request, the user's id (`user_id`, `id` or `sub` of
`context["user"]`): a user is only served their own cached responses. An authenticated
request whose user has no such id is not cached. Anonymous requests share entries
(hash, variables and tenant).

**Environment Variables**:

```bash
<!-- Code example in BASH -->
FRAISEQL_DATABASE_URL=postgresql://localhost/fraiseql_db
FRAISEQL_APQ_MODE=optional
FRAISEQL_APQ_STORAGE_BACKEND=memory
FRAISEQL_APQ_CACHE_RESPONSES=true
```
<!-- Code example in TEXT -->

### Staging Environment

```python
<!-- Code example in Python -->
config = FraiseQLConfig(
    database_url="postgresql://pg-staging/fraiseql_db",
    apq_mode="optional",                    # Allow client registration
    apq_storage_backend="postgresql",       # Persistent
    apq_cache_responses=True,
    apq_backend_config={
        "auto_create_tables": True,
    }
)
```
<!-- Code example in TEXT -->

### Production Environment

```python
<!-- Code example in Python -->
config = FraiseQLConfig(
    database_url="postgresql://pg-prod-1/fraiseql_db",
    apq_mode="required",                    # Only persisted queries
    apq_storage_backend="postgresql",       # Persistent, shared
    apq_cache_responses=True,
    apq_queries_dir="./dist/graphql",       # Pre-built queries
    apq_backend_config={
        "table_prefix": "apq_",
        "auto_create_tables": False,        # Pre-created for safety
        "connection_timeout": 30,
    }
)
```
<!-- Code example in TEXT -->

**Environment Variables**:

```bash
<!-- Code example in BASH -->
# Production APQ configuration
FRAISEQL_APQ_MODE=required
FRAISEQL_APQ_STORAGE_BACKEND=postgresql
FRAISEQL_APQ_CACHE_RESPONSES=true
FRAISEQL_APQ_QUERIES_DIR=/app/dist/graphql
```
<!-- Code example in TEXT -->

---

## Metrics and Monitoring

FraiseQL provides comprehensive metrics for APQ operations.

### Key Metrics

**Query Cache Metrics** (persisted query lookup):

- `query_cache_hits`: Number of successful hash lookups
- `query_cache_misses`: Hashes not found (PERSISTED_QUERY_NOT_FOUND errors)
- `query_cache_hit_rate`: Percentage of successful lookups (0.0 to 1.0)

**Response Cache Metrics** (JSON passthrough cache):

- `response_cache_hits`: Number of cached responses returned
- `response_cache_misses`: Cache misses requiring execution
- `response_cache_hit_rate`: Percentage of responses from cache
- `response_cache_stores`: New responses cached

**Storage Metrics**:

- `stored_queries_count`: Total persisted queries
- `cached_responses_count`: Total cached responses
- `total_storage_bytes`: Approximate storage size

**Performance Metrics**:

- `avg_query_parse_time_ms`: Average time to parse queries
- `cache_lookup_time_ms`: Time to look up in backend

### Monitoring Integration

**Prometheus Metrics** (exported automatically):

```prometheus
<!-- Code example in PROMETHEUS -->
fraiseql_apq_query_cache_hits_total
fraiseql_apq_query_cache_misses_total
fraiseql_apq_response_cache_hits_total
fraiseql_apq_response_cache_misses_total
fraiseql_apq_stored_queries_count
fraiseql_apq_response_cache_size_bytes
```
<!-- Code example in TEXT -->

**Health Check Endpoint**:

```python
<!-- Code example in Python -->
# GET /health includes APQ metrics
{
    "status": "healthy",
    "apq": {
        "query_cache_hit_rate": 0.85,
        "response_cache_hit_rate": 0.72,
        "stored_queries_count": 342,
        "cached_responses_count": 15234
    }
}
```
<!-- Code example in TEXT -->

### Dashboard Recommendations

1. **Cache Hit Rates**
   - Monitor trend over time
   - Target: > 70% response cache hit rate
   - Low hit rate indicates:
     - Too many unique queries (APQ not effective)
     - Queries executed infrequently
     - TTL too short

2. **Error Rates**
   - Monitor PERSISTED_QUERY_NOT_FOUND errors
   - Sudden spike indicates:
     - Client misconfiguration
     - Query hash mismatch
     - Backend storage issue

3. **Storage Usage**
   - Monitor stored_queries_count trend
   - Monitor response cache size
   - Set alerts for runaway storage growth

4. **Performance**
   - p99 query cache lookup: < 10ms
   - p99 response cache hit: < 50ms
   - p99 response cache miss + execution: 100-500ms+

---

## Troubleshooting

### PERSISTED_QUERY_NOT_FOUND Error

**Symptom**: Clients receive "PersistedQueryNotFound" errors

**Causes**:

1. Query hash mismatch between client and server
2. Query not registered
3. Storage backend lost data (memory backend restart)
4. Whitespace differences in query string

**Solutions**:

1. Verify hash matches: recompute SHA-256 of query string
2. In `optional` mode, send query with hash to register; in `required` mode, register
   it on the server
3. Use persistent backend (PostgreSQL) instead of memory
4. Ensure query strings are identical (whitespace sensitive!)

### Response Cache Misses (Low Hit Rate)

**Symptom**: Response cache hit rate < 50%

**Causes**:

1. Each query executes with different variables (unique cache keys)
2. Response caching disabled
3. Queries have errors (not cached)

**Solutions**:

1. Verify queries are reused with same variables (use APQ registration metrics)
2. Enable with `apq_cache_responses=true`
3. Check for errors in responses (not cached by design)

### ARBITRARY_QUERY_NOT_ALLOWED Error

**Symptom**: Clients in `required` mode send queries without hashes

**Causes**:

1. Client not configured for APQ
2. Client APQ support disabled

**Solutions**:

1. Configure client for APQ (Apollo Client, Relay, etc.)
2. Enable APQ in client SDK

### Hash Mismatch (`provided sha does not match query`)

**Symptom**: a request carrying both `sha256Hash` and `query` gets HTTP 400 with
`provided sha does not match query` (code `BAD_REQUEST`, as Apollo Server answers)

**Cause**: the SHA-256 of the query text is not `sha256Hash`. In `optional` and
`required` mode such a request is refused and nothing is stored, so no client can store
a text under the hash of another query. (`disabled` mode ignores the extension and
stores nothing.)

**Solution**: hash the exact text you send (UTF-8, SHA-256, lowercase hex).

### PERSISTED_QUERY_NOT_IN_LIST Error

**Symptom**: In `required` mode, a client sends a hash with its query text and gets
`PersistedQueryNotInList`

**Cause**: the hash is not registered on the server; `required` mode doesn't let
clients register queries.

**Solution**: register the operation on the server (put it in `apq_queries_dir`, or call
`register_queries` at startup), with the exact text the client hashes.

### Backend Storage Issues (Database)

**Symptom**: Queries stored but not retrievable

**Causes**:

1. Table not created (auto_create_tables=false but table missing)
2. Permission denied on apq_queries or apq_responses table
3. Disk full
4. Connection pool exhausted

**Solutions**:

1. Create tables manually (see Schema section above)
2. Grant permissions (example for PostgreSQL): `GRANT ALL ON apq_* TO fraiseql_user`
3. Check disk space (example for PostgreSQL): `SELECT pg_database_size('fraiseql_db')`
4. Increase connection pool size

### Memory Backend Queries Lost After Restart

**Symptom**: Hash-only requests fail after pod restart

**Causes**:

1. Using memory backend in production
2. Queries not pre-registered

**Solutions**:

1. Pre-register queries with `apq_queries_dir` (see Build-Time Registration)
2. Use a persistent backend: `apq_storage_backend="postgresql"

---

## Security Considerations

### Query Allowlisting Security

APQ in `required` mode provides defense-in-depth against:

**Introspection Attacks**:

- Arbitrary queries rejected in required mode
- Cannot execute `{ __schema { ... } }` queries
- Prevents schema inference by malicious actors

**Injection Attacks**:

- Only pre-approved queries execute
- Prevents dynamic query construction
- Cannot execute unexpected operations

**DoS Attacks**:

- Complex query expressions blocked
- Only pre-registered queries allowed
- Prevents algorithmic complexity attacks

### Variable Handling

**Security**: Variables are included in response cache keys

```python
<!-- Code example in Python -->
# User A
query_hash = "abc123..."
variables = {"userId": "alice"}
cache_key_a = sha256(f"{query_hash}:{json.dumps(variables)}")

# User B (different variables)
variables = {"userId": "bob"}
cache_key_b = sha256(f"{query_hash}:{json.dumps(variables)}")

# assert cache_key_a != cache_key_b  ✅ Prevents data leakage
```
<!-- Code example in TEXT -->

### Multi-Tenant Isolation

**Tenant ID in Cache Keys**:

```python
<!-- Code example in Python -->
# Query hash: e4c7e8f5...
# Tenant A: caches response with tenant_id="tenant-123"
# Tenant B: caches response with tenant_id="tenant-456"
# Never mixed
```
<!-- Code example in TEXT -->

### Sensitive Data in Error Responses

**Safe**:

```json
<!-- Code example in JSON -->
{
  "errors": [{
    "message": "PersistedQueryNotFound",
    "extensions": {"code": "PERSISTED_QUERY_NOT_FOUND"}
  }]
}
```
<!-- Code example in TEXT -->

**Unsafe** (avoid):

```json
<!-- Code example in JSON -->
{
  "errors": [{
    "message": "Query 'SELECT * FROM users' not found",
    "extensions": {"provided_query": "SELECT * FROM users"}
  }]
}
```
<!-- Code example in TEXT -->

---

## Migration Guide: From Arbitrary Queries to APQ

### Preparation (Week 1)

1. Enable APQ in `optional` mode (accept both)
2. Deploy client-side APQ support
3. Monitor metrics (should see 0% response cache hits initially)
4. Create `graphql/` directory with `.graphql` files

### Adoption (Week 2-3)

1. Deploy production build with APQ-enabled clients
2. Monitor query registration (new hashes appearing)
3. Verify response cache hit rate increases
4. Pre-register high-frequency queries

### Enforcement (Week 4)

1. Switch to `required` mode on staging
2. Test that only registered queries execute. With the `postgresql` backend, every hash
   clients registered while in `optional` mode is still in `apq_queries` and keeps
   running: empty the table (or use a new `table_prefix`) and register only the
   approved operations
3. Verify client handles ARBITRARY_QUERY_NOT_ALLOWED
4. Plan rollout schedule

### Production Rollout (Week 5)

1. Switch to `required` mode in production
2. Enable APQ in all client builds
3. Monitor error rate (should be 0 if done correctly)
4. Maintain `optional` mode for legacy clients temporarily

### Optimization (Ongoing)

1. Monitor response cache hit rate
2. Adjust TTL based on usage patterns
3. Gradually migrate legacy clients
4. Remove deprecated endpoints

---

## Client Integration Examples

### Apollo Client (JavaScript)

```javascript
<!-- Code example in JAVASCRIPT -->
import { ApolloClient, InMemoryCache } from '@apollo/client';
import { createPersistedQueryLink } from '@apollo/client/link/persisted-queries';
import { HttpLink } from '@apollo/client/link/http';
import sha256 from 'crypto-js/sha256';

const client = new ApolloClient({
  link: createPersistedQueryLink({
    useGETForHashedQueries: true,
    sha256: (query) => sha256(query).toString(),
  }).concat(
    new HttpLink({
      uri: 'https://api.example.com/graphql',
      credentials: 'include',
    })
  ),
  cache: new InMemoryCache(),
});
```
<!-- Code example in TEXT -->

### Relay (JavaScript)

```javascript
<!-- Code example in JAVASCRIPT -->
import { createRelayNetworkLayer } from 'react-relay-network-layer/lib/index.js';

const network = createRelayNetworkLayer(
  [
    {
      url: () => Promise.resolve('https://api.example.com/graphql'),
      init: () => ({
        credentials: 'include',
      }),
      apq: {
        sha256Hash: (query) => crypto.createHash('sha256').update(query).digest('hex'),
      },
    },
  ],
  { disableBatching: false }
);
```
<!-- Code example in TEXT -->

### Python Client

Python GraphQL clients (e.g., `gql`, `sgqlc`) support APQ through transport options:

```text
<!-- Code example in TEXT -->
transport = HttpTransport(
    url='https://api.example.com/graphql',
    apq_enabled=True,
)
client = Client(transport=transport)
```
<!-- Code example in TEXT -->

The client library automatically:

- Computes SHA-256 hash of each query
- Sends hash-only requests
- Falls back to hash + query on first request (registration)
- Caches registered queries locally

---

## Conclusion

Automatic Persisted Queries (APQ) in FraiseQL provides a bandwidth optimization mechanism by storing hash→query string mappings. APQ allows clients to send only a 64-character hash instead of multi-kilobyte query strings, while improving security through query allowlisting in production.

APQ is a standalone feature separate from Query Result Caching, though they work well together:

- **APQ** (this spec) = Reduce request size by sending hash instead of query string
- **Query Result Caching** (see Caching Spec) = Optionally avoid execution by caching results

**Key Takeaways**:

- ✅ **APQ Storage**:
  - Development: `optional` mode + memory backend
  - Staging: `optional` mode + database backend
  - Production: `required` mode + database backend + pre-registered queries
- ✅ **Query Result Caching** (separate feature):
  - Enable for 5-20x throughput improvement
  - Complexity-aware TTL for smart cache duration
  - Automatic invalidation via graphql-cascade
  - See Caching Specification for details
- ✅ **Security**: Variable-inclusive cache keys prevent data leakage between requests
- ✅ **Monitoring**: Track APQ query registration and query result cache hit rates separately

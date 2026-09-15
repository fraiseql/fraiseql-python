# Rust Pipeline Usage Guide

This guide explains how to use FraiseQL's exclusive Rust pipeline for optimal GraphQL performance.

## Overview

The Rust pipeline is **always active** in FraiseQL. It automatically handles all GraphQL response processing:

- ✅ **Concatenates** JSON rows into arrays
- ✅ **Wraps** in GraphQL response structure
- ✅ **Transforms** snake_case → camelCase
- ✅ **Injects** __typename fields
- ✅ **Returns** UTF-8 bytes for HTTP

**Performance**: 7-10x faster than Python string operations.

---

## Prerequisites

To use the Rust pipeline, ensure you have:

- [ ] FraiseQL installed
- [ ] Rust extensions installed: `pip install "fraiseql[rust]<2"`
- [ ] PostgreSQL database with JSONB views
- [ ] GraphQL schema with proper type definitions

---

## Basic Usage

### Repository Methods

Use the Rust pipeline methods for optimal performance:

```python
from fraiseql.db import FraiseQLRepository

repo = FraiseQLRepository(pool)

# List queries - use find_rust
users = await repo.find_rust("v_user", "users", info)

# Single object queries - use find_one_rust
user = await repo.find_one_rust("v_user", "user", info, id=user_id)

# With filtering
active_users = await repo.find_rust(
    "v_user", "users", info,
    status="active",
    created_at__min="2024-01-01"
)
```

### GraphQL Resolvers

Update your GraphQL resolvers to use Rust pipeline methods:

```python
import fraiseql
from fraiseql.core.rust_pipeline import RustResponseBytes

@fraiseql.query
async def users(info) -> RustResponseBytes:
    """Get all users using Rust pipeline."""
    db = info.context["db"]
    return await repo.find_rust("v_user", "users", info)

@fraiseql.query
async def user(info, id: ID) -> RustResponseBytes:
    """Get single user using Rust pipeline."""
    db = info.context["db"]
    return await repo.find_one_rust("v_user", "user", info, id=id)

@fraiseql.query
async def search_users(
    info,
    query: str | None = None,
    limit: int = 20
) -> RustResponseBytes:
    """Search users with filtering."""
    db = info.context["db"]
    filters = {}
    if query:
        filters["name__icontains"] = query

    return await repo.find_rust(
        "v_user", "users", info,
        **filters,
        limit=limit
    )
```

### Field Resolvers

Use Rust pipeline methods in field resolvers:

```python
import fraiseql

@fraiseql.type
class User:
    id: ID

    @field
    async def posts(self, info) -> RustResponseBytes:
        """Get user's posts."""
        db = info.context["db"]
        return await repo.find_rust("v_post", "posts", info, user_id=self.id)
```

---

## Advanced Usage

### Field Projection

The Rust pipeline automatically handles GraphQL field selection:

```python
# Client queries only specific fields
query {
  users {
    id
    firstName  # Only these fields processed
  }
}

# Rust automatically filters JSONB response
# No Python overhead for unused fields
```

### Type Transformation

GraphQL types are automatically transformed:

```python
# Database: {"first_name": "John", "last_name": "Doe"}
# GraphQL: {"firstName": "John", "lastName": "Doe", "__typename": "User"}
```

### Error Handling

The Rust pipeline provides consistent error handling:

```python
try:
    result = await repo.find_rust("v_user", "users", info)
    return result  # RustResponseBytes
except Exception as e:
    # Handle database errors, etc.
    logger.error(f"Query failed: {e}")
    # Return appropriate GraphQL error
```

---

## Configuration

The Rust pipeline is always active:

```python
from fraiseql import FraiseQLConfig

config = FraiseQLConfig(
    # Standard configuration
    apq_enabled=True,
    field_projection=True,
)
```

### Verification

Check that Rust pipeline is working:

```python
# In your application
from fraiseql.core.rust_pipeline import RustResponseBytes
import fraiseql_rs

# Verify Rust extension loaded
print("Rust pipeline available:", hasattr(fraiseql_rs, 'build_list_response'))

# Check repository methods
result = await repo.find_rust("v_user", "users", info)
print("Using Rust pipeline:", isinstance(result, RustResponseBytes))
```

---

## Performance Monitoring

### Metrics to Track

```python
# All queries use the exclusive Rust pipeline
result = await repo.find_rust("v_user", "users", info)

# Performance benefits:
# - Pre-allocated buffers, no Python GC pressure
# - Direct UTF-8 encoding for HTTP responses
# - 7-10x faster than traditional JSON processing
```

### Performance Verification

```python
import time

# Benchmark current Rust pipeline performance
start = time.perf_counter()
for _ in range(100):
    result = await repo.find_rust("v_user", "users", info)
total_time = time.perf_counter() - start

print(f"Rust Pipeline: {total_time:.3f}s for 100 queries")
print(f"Average: {total_time/100:.4f}s per query")
```

---

## Troubleshooting

### Common Issues

**"fraiseql_rs not found"**

```bash
# Install Rust extensions
pip install "fraiseql[rust]<2"

# Or with uv
uv add "fraiseql[rust]<2"
```

**Performance optimization**

```python
# Always use Rust pipeline methods for best performance
result = await repo.find_rust("table", "field", info)  # Optimal
```

**Type errors**

```python
# Update return types
async def users(info) -> RustResponseBytes:  # Correct
async def users(info) -> list[User]:         # Wrong for Rust pipeline
```

**Field selection not working**

```python
# Ensure GraphQL info is passed
return await repo.find_rust("v_user", "users", info)  # info required
# Not: return await repo.find_rust("v_user", "users") # Missing info
```

---

## Best Practices

### When to Use Rust Pipeline

✅ **Always use for GraphQL resolvers**
✅ **Use for high-throughput endpoints**
✅ **Use for complex queries with large result sets**

### Repository Method Selection

```python
# Rust pipeline methods
find_rust()      # List queries
find_one_rust()  # Single object queries

# Direct database access
find()           # Raw Python objects
find_one()       # Raw Python objects
```

### Error Handling

```python
import fraiseql

@fraiseql.query
async def users(info) -> RustResponseBytes:
    try:
        return await repo.find_rust("v_user", "users", info)
    except Exception as e:
        logger.error(f"Failed to fetch users: {e}")
        # Return GraphQL error
        raise GraphQLError("Failed to fetch users")
```

### Testing

```python
# Test Rust pipeline responses
result = await repo.find_rust("v_user", "users", info)
assert isinstance(result, RustResponseBytes)
assert result.bytes.startswith(b'{"data"')

# Test GraphQL integration
response = client.post("/graphql", json={"query": "{ users { id } }"})
assert response.json()["data"]["users"]  # Works seamlessly
```

---

## Examples

### Complete GraphQL Schema

```python
import fraiseql
from fraiseql.core.rust_pipeline import RustResponseBytes
from fraiseql.types import ID

@fraiseql.type
class User:
    id: ID
    first_name: str
    last_name: str

    @field
    async def posts(self, info) -> RustResponseBytes:
        db = info.context["db"]
        return await repo.find_rust("v_post", "posts", info, user_id=self.id)

@fraiseql.query
async def users(info, limit: int = 20) -> RustResponseBytes:
    db = info.context["db"]
    return await repo.find_rust("v_user", "users", info, limit=limit)

@fraiseql.query
async def user(info, id: ID) -> RustResponseBytes:
    db = info.context["db"]
    return await repo.find_one_rust("v_user", "user", info, id=id)
```

### FastAPI Integration

```python
from fastapi import FastAPI
from fraiseql.fastapi import make_graphql_app
from fraiseql.fastapi.response_handlers import handle_graphql_response

app = FastAPI()
graphql_app = make_graphql_app()

@app.post("/graphql")
async def graphql_endpoint(request):
    result = await graphql_app.execute(request)
    return handle_graphql_response(result)  # Automatic RustResponseBytes handling
```

---

## Summary

The Rust pipeline is FraiseQL's core execution engine:

- **Performance**: 7-10x faster JSON processing
- **Usage**: Simple method calls with `find_rust()` and `find_one_rust()`
- **Integration**: Automatic with GraphQL schemas
- **Architecture**: PostgreSQL → Rust → HTTP

Use `find_rust()` and `find_one_rust()` methods for optimal performance.

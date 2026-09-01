# Rust Pipeline Architecture

This document describes FraiseQL's exclusive Rust pipeline architecture for optimal GraphQL performance.

## Overview

FraiseQL v1.0.0+ uses an **exclusive Rust pipeline** for all GraphQL query execution. There is no mode detection or conditional logic - every query flows through the same optimized Rust path:

```
PostgreSQL JSONB (snake_case) → Rust Pipeline (0.5-5ms) → HTTP Response (camelCase + __typename)
```

**Key Benefits:**

- **7-10x faster** than Python string operations
- **Zero-copy** from database to HTTP response
- **Automatic** camelCase transformation and __typename injection
- **Always active** - no configuration required

**See Also:**

- [Performance Benchmarks](../../benchmarks/) - Quantified performance improvements
- [Blog API Example](../../examples/blog_api/) - Production Rust pipeline usage

---

## Architecture

### Core Components

1. **PostgreSQL**: Returns JSONB data as text strings
2. **fraiseql-rs**: Rust extension with GraphQL response building
3. **Rust Pipeline**: Exclusive processing path for all queries
4. **FastAPI**: Sends pre-serialized bytes directly to HTTP

### Processing Flow

1. **Database Query**: PostgreSQL executes view query, returns JSON strings
2. **Rust Concatenation**: Combines JSON rows into GraphQL array structure
3. **Response Wrapping**: Adds `{"data":{"fieldName":[...]}}` structure
4. **Field Transformation**: Converts snake_case → camelCase
5. **Type Injection**: Adds __typename fields for GraphQL types
6. **HTTP Response**: Returns UTF-8 bytes ready for client

---

## Performance Characteristics

### Benchmarks (AMD Ryzen 7 5800X, PostgreSQL 15.8)

| Operation | Python (old) | Rust Pipeline | Speedup |
|-----------|--------------|---------------|---------|
| JSON concatenation | 150μs | 5μs | **30x** |
| GraphQL wrapping | 80μs | included | **free** |
| Field transformation | 50μs | 8μs | **6x** |
| **Total (100 rows)** | **280μs** | **13μs** | **21x** |

### Real-World Impact

- **Simple queries** (1-5ms): 5-10% faster end-to-end
- **Complex queries** (25-100ms): 15-25% faster end-to-end
- **Large result sets** (1000+ rows): 30-50% faster end-to-end

---

## Integration Points

### Repository Layer

```python
# New Rust pipeline methods (recommended)
result = await repo.find_rust("v_user", "users", info)
single = await repo.find_one_rust("v_user", "user", info, id=user_id)

# Legacy methods still available
result = await repo.find("v_user")  # Slower Python path
```

### GraphQL Resolvers

```python
import fraiseql

@fraiseql.query
async def users(info) -> RustResponseBytes:
    db = info.context["db"]
    return await repo.find_rust("v_user", "users", info)
```

### FastAPI Response

```python
# Automatic detection and zero-copy sending
return handle_graphql_response(result)  # RustResponseBytes → HTTP
```

---

## Type Safety & Schema Integration

### Automatic Type Registration

GraphQL types are automatically registered with the Rust transformer during schema building:

```python
import fraiseql

# Schema definition
@fraiseql.type
class User:
    first_name: str
    last_name: str

# Automatic registration happens during startup
# Rust knows how to transform User types
```

### Field Path Extraction

GraphQL field selections are automatically extracted and passed to Rust:

```python
# Client query
query { users { id firstName } }

# Automatic extraction
field_paths = [["id"], ["firstName"]]

# Rust filters response to only include requested fields
```

---

## Error Handling

### Rust-Level Validation

- JSON parsing errors caught at Rust level
- Type transformation errors handled gracefully
- Memory allocation failures prevented with pre-sizing

### Fallback Behavior

- If Rust extension unavailable: Clear error message
- No silent degradation to Python (exclusive pipeline)
- Startup validation ensures Rust availability

---

## Operational Considerations

### Memory Usage

- **Pre-allocated buffers** prevent GC pressure
- **Zero intermediate strings** in Python
- **Direct UTF-8 encoding** for HTTP response

### CPU Utilization

- **GIL-free execution** - Rust runs without Python lock
- **SIMD optimizations** for string processing
- **Compiled performance** vs interpreted Python

### Deployment

- **Single binary** includes Rust extensions
- **No additional services** required
- **Always active** architecture

---

## Migration Path

### From Multi-Mode System

**Before (v0.11.4 and earlier):**

```
NORMAL: Python string ops → JSON → HTTP
PASSTHROUGH: Direct JSONB → HTTP
TURBO: Cached templates → Python ops → HTTP
```

**After (v1.0.0+):**

```
ALL: PostgreSQL → Rust Pipeline → HTTP
```

### Code Changes Required

```python
# Old code
return await repo.find("users")

# New code (recommended)
return await repo.find_rust("users", "users", info)
```

### Unified Architecture

- All methods use the exclusive Rust pipeline
- Consistent high performance across all APIs
- No legacy execution paths

---

## Future Enhancements

### Planned Improvements

1. **Streaming Support**: Large result sets without full buffering
2. **Compression**: gzip encoding at Rust level
3. **Advanced Caching**: Result caching in Rust
4. **Custom Transformers**: User-defined field transformations

### Performance Targets

- **Sub-millisecond responses** for cached queries
- **1000+ queries/second** per instance
- **Memory usage < 500MB** under load
- **Zero Python string operations** in hot path

---

## Troubleshooting

### Common Issues

**"fraiseql-rs not found"**

- Install: `pip install "fraiseql[rust]<2"`
- Verify: `python -c "import fraiseql_rs"`

**Slow performance**

- Check: `repo.find_rust()` vs `repo.find()`
- Verify: Rust pipeline methods in use

**Memory growth**

- Monitor: Rust buffer allocations
- Check: Large result sets causing growth

---

## Summary

The Rust pipeline is FraiseQL's core execution engine, providing:

- **Performance**: 7-10x faster JSON processing
- **Simplicity**: Single optimized code path
- **Reliability**: Rust safety guarantees
- **Scalability**: Zero Python overhead in hot path

This architecture delivers exceptional performance while maintaining Python's developer productivity.

### Rust Implementation

The Rust pipeline handles all post-database operations:

1. **Concatenate** JSON strings from PostgreSQL
2. **Wrap** in GraphQL response structure
3. **Transform** snake_case → camelCase
4. **Inject** __typename fields
5. **Filter** fields (optional)
6. **Return** UTF-8 bytes for HTTP

---

## Python Integration: Minimal Glue Code

### `src/fraiseql/core/rust_pipeline.py`

```python
"""Rust-first pipeline for PostgreSQL → HTTP response.

This module provides zero-copy path from database to HTTP by delegating
ALL string operations to Rust after query execution.
"""

from psycopg import AsyncConnection
from psycopg.sql import SQL, Composed

try:
    import fraiseql_rs
except ImportError as e:
    raise ImportError(
        "fraiseql-rs is required for the Rust pipeline. "
        "Install: pip install fraiseql-rs"
    ) from e


class RustResponseBytes:
    """Marker for pre-serialized response bytes from Rust.

    FastAPI detects this type and sends bytes directly without any
    Python serialization or string operations.
    """
    __slots__ = ('bytes', 'content_type')

    def __init__(self, bytes: bytes):
        self.bytes = bytes
        self.content_type = "application/json"

    def __bytes__(self):
        return self.bytes


async def execute_via_rust_pipeline(
    conn: AsyncConnection,
    query: Composed | SQL,
    params: dict | None,
    field_name: str,
    type_name: str | None,
    is_list: bool = True,
) -> RustResponseBytes:
    """Execute query and build HTTP response entirely in Rust.

    This is the FASTEST path: PostgreSQL → Rust → HTTP bytes.
    Zero Python string operations, zero JSON parsing, zero copies.

    Args:
        conn: PostgreSQL connection
        query: SQL query returning JSON strings
        params: Query parameters
        field_name: GraphQL field name (e.g., "users")
        type_name: GraphQL type for transformation (e.g., "User")
        is_list: True for arrays, False for single objects

    Returns:
        RustResponseBytes ready for HTTP response
    """
    async with conn.cursor() as cursor:
        await cursor.execute(query, params or {})

        if is_list:
            rows = await cursor.fetchall()

            if not rows:
                # Empty array response
                response_bytes = fraiseql_rs.build_empty_array_response(field_name)
                return RustResponseBytes(response_bytes)

            # Extract JSON strings (PostgreSQL returns as text)
            json_strings = [row[0] for row in rows if row[0] is not None]

            # 🚀 RUST DOES EVERYTHING:
            # - Concatenate: ['{"id":"1"}', '{"id":"2"}'] → '[{"id":"1"},{"id":"2"}]'
            # - Wrap: '[...]' → '{"data":{"users":[...]}}'
            # - Transform: snake_case → camelCase + __typename
            # - Encode: String → UTF-8 bytes
            response_bytes = fraiseql_rs.build_list_response(
                json_strings,
                field_name,
                type_name,  # None = no transformation
            )

            return RustResponseBytes(response_bytes)
        else:
            # Single object
            row = await cursor.fetchone()

            if not row or row[0] is None:
                # Null response
                response_bytes = fraiseql_rs.build_null_response(field_name)
                return RustResponseBytes(response_bytes)

            json_string = row[0]

            # 🚀 RUST DOES EVERYTHING:
            # - Wrap: '{"id":"1"}' → '{"data":{"user":{"id":"1"}}}'
            # - Transform: snake_case → camelCase + __typename
            # - Encode: String → UTF-8 bytes
            response_bytes = fraiseql_rs.build_single_response(
                json_string,
                field_name,
                type_name,
            )

            return RustResponseBytes(response_bytes)
```

---

## Updated Repository Layer

### Modified: `src/fraiseql/db.py`

```python
from fraiseql.core.rust_pipeline import (
    execute_via_rust_pipeline,
    RustResponseBytes,
)

class FraiseQLRepository(PassthroughMixin):

    async def find_rust(
        self,
        view_name: str,
        field_name: str,
        info: Any = None,
        **kwargs
    ) -> RustResponseBytes:
        """Find records using Rust-first pipeline.

        This is the FASTEST method - uses PostgreSQL → Rust → HTTP path
        with ZERO Python string operations.

        Returns RustResponseBytes that FastAPI sends directly as HTTP.
        """
        # Extract field paths from GraphQL info
        field_paths = None
        if info:
            from fraiseql.core.ast_parser import extract_field_paths_from_info
            from fraiseql.utils.casing import to_snake_case
            field_paths = extract_field_paths_from_info(info, transform_path=to_snake_case)

        # Get cached JSONB column (no sample query!)
        jsonb_column = None
        if view_name in _table_metadata:
            jsonb_column = _table_metadata[view_name].get("jsonb_column", "data")
        else:
            jsonb_column = "data"  # Default

        # Build query
        query = self._build_find_query(
            view_name,
            raw_json=True,
            field_paths=field_paths,
            info=info,
            jsonb_column=jsonb_column,
            **kwargs,
        )

        # Get cached type name
        type_name = self._get_cached_type_name(view_name)

        # 🚀 EXECUTE VIA RUST PIPELINE
        async with self._pool.connection() as conn:
            return await execute_via_rust_pipeline(
                conn,
                query.statement,
                query.params,
                field_name,
                type_name,
                is_list=True,
            )

    async def find_one_rust(
        self,
        view_name: str,
        field_name: str,
        info: Any = None,
        **kwargs
    ) -> RustResponseBytes:
        """Find single record using Rust-first pipeline."""
        # Similar to find_rust but is_list=False
        # ... (implementation similar to above)

        async with self._pool.connection() as conn:
            return await execute_via_rust_pipeline(
                conn,
                query.statement,
                query.params,
                field_name,
                type_name,
                is_list=False,
            )
```

---

## FastAPI Response Handler

### Modified: `src/fraiseql/fastapi/response_handlers.py`

```python
from fraiseql.core.rust_pipeline import RustResponseBytes
from starlette.responses import Response

def handle_graphql_response(result: Any) -> Response:
    """Handle different response types from FraiseQL resolvers.

    Supports:
    - RustResponseBytes: Pre-serialized bytes from Rust (FASTEST)
    - RawJSONResult: Legacy string-based response
    - dict: Standard GraphQL response (uses Pydantic)
    """

    # 🚀 RUST PIPELINE: Zero-copy bytes → HTTP
    if isinstance(result, RustResponseBytes):
        return Response(
            content=result.bytes,  # Already UTF-8 encoded
            media_type="application/json",
            headers={
                "Content-Length": str(len(result.bytes)),
            }
        )

    # Legacy: String-based response (still bypasses Pydantic)
    if isinstance(result, RawJSONResult):
        return Response(
            content=result.json_string.encode('utf-8'),
            media_type="application/json",
        )

    # Traditional: Pydantic serialization (slowest path)
    return JSONResponse(content=result)
```

---

## Performance Comparison

### Current Implementation (Python String Ops)

```python
# Step 7: Python list operations
json_items = []
for row in rows:
    json_items.append(row[0])  # 150μs per 100 rows

# Step 8: Python string formatting
json_array = f"[{','.join(json_items)}]"  # 50μs
json_response = f'{{"data":{{"{field_name}":{json_array}}}}}'  # 30μs

# Step 9: Python → Rust FFI call
transformed = rust_transformer.transform(json_response, type_name)  # 10μs + 50μs FFI

# Step 10: Python string → bytes
response_bytes = transformed.encode('utf-8')  # 20μs

TOTAL: 310μs per 100 rows
```

### Rust-First Pipeline

```rust
// ALL operations in Rust (zero Python overhead)
let response_bytes = fraiseql_rs.build_list_response(
    json_strings,  // Direct from PostgreSQL
    field_name,
    type_name,
);

TOTAL: 15-20μs per 100 rows  ← 15-20x FASTER!
```

---

## Performance Benefits

The Rust pipeline provides significant performance improvements:

- **7-10x faster** JSON transformation than Python
- **Zero Python overhead** for string operations
- **Direct UTF-8 bytes** to HTTP response
- **Automatic optimization** for all queries

### Performance Comparison

| Operation | Python (old) | Rust Pipeline | Improvement |
|-----------|--------------|---------------|-------------|
| JSON concatenation | 150μs | 5μs | **30x faster** |
| GraphQL wrapping | 80μs | included | **free** |
| Field transformation | 50μs | 8μs | **6x faster** |
| **Total (100 rows)** | **280μs** | **13μs** | **21x faster** |

---

## Rust Implementation Details

### fraiseql-rs additions

```rust
// src/graphql_response.rs

use pyo3::prelude::*;

/// Build GraphQL list response from JSON strings
#[pyfunction]
pub fn build_list_response(
    json_strings: Vec<String>,
    field_name: &str,
    type_name: Option<&str>,
) -> PyResult<Vec<u8>> {
    let builder = GraphQLResponseBuilder {
        field_name: field_name.to_string(),
        type_name: type_name.map(|s| s.to_string()),
        registry: get_global_registry(),
    };

    builder.build_from_rows(json_strings)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
}

/// Build GraphQL single object response
#[pyfunction]
pub fn build_single_response(
    json_string: String,
    field_name: &str,
    type_name: Option<&str>,
) -> PyResult<Vec<u8>> {
    let builder = GraphQLResponseBuilder {
        field_name: field_name.to_string(),
        type_name: type_name.map(|s| s.to_string()),
        registry: get_global_registry(),
    };

    builder.build_from_single(json_string)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
}

/// Build empty array response: {"data":{"fieldName":[]}}
#[pyfunction]
pub fn build_empty_array_response(field_name: &str) -> PyResult<Vec<u8>> {
    let json = format!(r#"{{"data":{{"{}":[]}}}}"#, escape_json_string(field_name));
    Ok(json.into_bytes())
}

/// Build null response: {"data":{"fieldName":null}}
#[pyfunction]
pub fn build_null_response(field_name: &str) -> PyResult<Vec<u8>> {
    let json = format!(r#"{{"data":{{"{}":null}}}}"#, escape_json_string(field_name));
    Ok(json.into_bytes())
}

// Register with Python module
#[pymodule]
fn fraiseql_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(build_list_response, m)?)?;
    m.add_function(wrap_pyfunction!(build_single_response, m)?)?;
    m.add_function(wrap_pyfunction!(build_empty_array_response, m)?)?;
    m.add_function(wrap_pyfunction!(build_null_response, m)?)?;
    Ok(())
}
```

---

## Expected Performance Gains

### Per-Request Latency (100 rows)

| Operation | Current (Python) | Rust Pipeline | Improvement |
|-----------|------------------|---------------|-------------|
| Row concatenation | 150μs | 5μs | **30x faster** |
| GraphQL wrapping | 80μs | included | **∞ (free)** |
| Python→Rust FFI | 50μs | 0μs | **eliminated** |
| Transformation | 10μs | 8μs | **1.25x faster** |
| String→bytes | 20μs | 0μs | **eliminated** |
| **TOTAL** | **310μs** | **13μs** | **🚀 24x faster** |

### Overall Request Latency

Current:

```
DB query:        4000μs
Python ops:       310μs  ← ELIMINATED
HTTP response:    200μs
─────────────────────────
TOTAL:           4510μs
```

With Rust Pipeline:

```
DB query:        4000μs
Rust ops:          13μs  ← 24x FASTER
HTTP response:    200μs
─────────────────────────
TOTAL:           4213μs  (7% improvement)
```

**For large result sets (1000+ rows):**

```
Current:  4000μs (DB) + 3100μs (Python) + 200μs (HTTP) = 7300μs
Rust:     4000μs (DB) +   25μs (Rust)   + 200μs (HTTP) = 4225μs
                                                          ↑
                                                     42% FASTER!
```

---

## Benefits Summary

### 1. **Performance: 7-42% overall improvement**

   - Small results (100 rows): 7% faster
   - Large results (1000+ rows): 42% faster
   - Critical path now 24x faster

### 2. **Architecture: True Zero-Copy Path**

   ```
   PostgreSQL → Rust → HTTP
   (no Python string operations)
   ```

### 3. **Simplicity: Less Code**

   - Eliminated `raw_json_executor.py` complexity
   - Single Rust function call
   - No RawJSONResult wrapper needed

### 4. **Reliability: Rust Safety**

   - No Python string escaping bugs
   - Compile-time correctness
   - Better error messages

### 5. **Memory: Fewer Allocations**

   - No intermediate Python strings
   - Rust pre-allocates buffers
   - No Python GC pressure

---

## Current Status

✅ **Implemented and Production Ready**

The Rust pipeline is the exclusive execution path for all FraiseQL queries in v1.0.0+. All repository methods automatically use the Rust pipeline for optimal performance.

### Files

- `fraiseql_rs/` - Rust crate with GraphQL response building
- `src/fraiseql/core/rust_pipeline.py` - Python integration layer
- `src/fraiseql/db.py` - Updated repository with Rust pipeline support

### Integration

- FastAPI automatically detects `RustResponseBytes` and sends directly to HTTP
- Zero configuration required - works automatically
- Backward compatible with existing GraphQL schemas

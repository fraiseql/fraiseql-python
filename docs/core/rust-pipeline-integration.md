---
title: Rust Pipeline Architecture
description: How FraiseQL integrates Python and Rust for 5-7x faster JSON transformation and zero-copy performance
tags:
  - rust
  - python
  - architecture
  - performance
  - PyO3
  - pipeline
  - integration
---

# Python ↔ Rust Integration

This guide explains how FraiseQL's Python code integrates with the Rust pipeline.

## Overview

FraiseQL's architecture separates responsibilities: Python handles GraphQL schema, resolvers, and PostgreSQL queries, while an **exclusive Rust pipeline** handles all JSON transformation, field projection, and HTTP response generation. Every query flows through the Rust pipeline—there is no fallback or mode detection.

## Competitive Advantage: Exclusive Architecture

**Other frameworks can't do this—they're locked into ORM serialization.** Traditional GraphQL frameworks serialize ORM objects to JSON in Python, creating unavoidable performance bottlenecks. FraiseQL's exclusive Rust pipeline bypasses Python entirely for JSON processing, delivering **7-10x faster** response times.

This architecture is unique to FraiseQL. No other GraphQL framework combines:

- PostgreSQL-native JSONB views
- Zero Python serialization overhead
- Rust-powered JSON transformation
- Direct UTF-8 byte output to HTTP

```mermaid
graph TB
    Client[GraphQL Client]
    Python[Python Layer<br/>GraphQL Schema, Resolvers, Business Logic]
    Postgres[(PostgreSQL<br/>JSONB Views)]
    Rust[Rust Pipeline fraiseql-rs<br/>JSON Transform, camelCase, __typename]
    HTTP[FastAPI HTTP Response]

    Client -->|GraphQL Query| Python
    Python -->|SQL Query| Postgres
    Postgres -->|JSONB Strings| Python
    Python -->|Vec&lt;String&gt;| Rust
    Rust -->|UTF-8 Bytes| HTTP
    HTTP -->|JSON Response| Client

    style Rust fill:#f96,stroke:#333,stroke-width:4px
    style Python fill:#69f,stroke:#333,stroke-width:2px
    style Postgres fill:#336791,stroke:#333,stroke-width:2px,color:#fff
```

## Request Flow Diagram

```mermaid
sequenceDiagram
    participant Client
    participant FastAPI
    participant Python as Python Resolver
    participant PostgreSQL
    participant Rust as fraiseql_rs

    Client->>FastAPI: POST /graphql<br/>{query: "{ users { id firstName } }"}
    FastAPI->>Python: Execute GraphQL query
    Python->>PostgreSQL: SELECT data FROM v_user
    PostgreSQL->>Python: [<br/> '{"id": "...", "first_name": "Alice"}',<br/> '{"id": "...", "first_name": "Bob"}'<br/>]
    Python->>Rust: build_graphql_response(<br/> json_strings=Vec&lt;String&gt;,<br/> field_name="users",<br/> type_name="User"<br/>)
    Rust->>Rust: Concatenate JSON array
    Rust->>Rust: Transform snake_case → camelCase
    Rust->>Rust: Inject __typename="User"
    Rust->>Python: Vec&lt;u8&gt; (UTF-8 bytes)
    Python->>FastAPI: RustResponseBytes
    FastAPI->>Client: HTTP 200 OK<br/>{"data": {"users": [...]}}
```

## The Boundary

### What Python Does

- Define GraphQL types and queries
- Execute PostgreSQL queries
- Collect JSONB strings from database
- Call Rust pipeline with JSON strings

### What Rust Does

- Concatenate JSON array
- Transform JSONB to GraphQL JSON
- Keep the selected fields only, each under its response key (alias)
- Write `__typename` where the query selects it
- Return UTF-8 bytes directly for HTTP

### `__typename` is included where the query selects it

A response built by the Rust pipeline holds exactly the selected fields, as the
GraphQL spec requires: `__typename` too is written only where the query selects
it, under its alias if it has one. A mutation selecting `post { id title }`
returns `{"id": ..., "title": ...}`; `post { __typename id }` returns
`{"__typename": "Post", "id": ...}`. This applies to query results (`db.find`,
`db.find_one`, several root fields) and to mutation results, including nested
entities. Clients that normalize by type (Apollo Client, urql's Graphcache,
Relay) add `__typename` to the queries they send, so they get it.

Where graphql-core completes the result instead (a `find` below the root, or a
mutation outside HTTP mode), the data Rust hands it keeps `__typename` on every
object of a known type: graphql-core reads it to resolve unions and interfaces,
and leaves it out of the response where it isn't selected. Cascade entities
(`cascade.updated`, `cascade.deleted`) keep the `__typename` their data has, the
entity's type, as the GraphQL Cascade format defines it.

A mutation entity's `__typename` comes from the SQL function's `entity_type`, a
`__typename` key in the entity's data, or the schema type of the success type's
entity field when that type is concrete (`location: Location`). When none of these
applies, `__typename` is left out, and a warning names the SQL function once.

For a field whose type is an interface or a union, the object behind it can be
one of several types. FraiseQL never guesses the type from the schema there:
`__typename` is included only when the data provides it (a `__typename` key in
the JSONB).

In a mutation entity, fragments under an interface or union field
(`owner { ... on Person { name } ... on Org { title } }`) select the union of
their fields for every object: a `Person` owner keeps `title` too if its data has
one. Per-type filtering, which would keep only `name` for a `Person`, isn't done
yet.

## Code Example

### Python Side

```python
import fraiseql
from fraiseql.types import ID

# 1. Define GraphQL type
@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    first_name: str  # Python uses snake_case
    created_at: datetime

# 2. Define query resolver
@fraiseql.query
async def users(info) -> list[User]:
    db = info.context["db"]

    # 3. Execute PostgreSQL query (returns JSONB)
    # Rust pipeline handles transformation automatically
    return await repo.find("v_user")
```

### Under the Hood

`FraiseQLRepository.find()` reads the view's `data` column as JSON text, one string per
row, and hands the strings to the Rust extension (shipped inside the `fraiseql` package)
with the selection of the query; it returns the bytes as a `RustResponseBytes`, which
the `/graphql` route sends as the HTTP response. The call, on its own (applications
don't make it; `find` does):

```python
from fraiseql import fraiseql_rs

# What the view's data column holds, one JSON string per row
json_strings = ['{"id": 1, "first_name": "Ada"}']

response_bytes = fraiseql_rs.build_graphql_response(
    json_strings=json_strings,
    field_name="users",
    type_name="User",
    field_paths=None,
)
print(response_bytes)
# b'{"data":{"users":[{"__typename":"User","id":1,"firstName":"Ada"}]}}'
```

Without a selection, as here, every key is kept and the row gets its `__typename`.
`find` passes the query's `field_selections`, and `inject_typename=False` when the
response goes to the client as is (HTTP mode), so it holds exactly the selected fields,
`__typename` included only where selected.

### Rust Side (fraiseql_rs crate)

```rust
#[pyfunction]
pub fn build_graphql_response(
    json_strings: Vec<String>,
    field_name: String,
    type_name: Option<String>,
    field_paths: Option<Vec<Vec<String>>>,
) -> PyResult<Vec<u8>> {
    // 1. Concatenate JSON strings
    let array = format!("[{}]", json_strings.join(","));

    // 2. Wrap in GraphQL response
    let response = format!(
        r#"{{"data":{{"{}":{}}}}}"#,
        field_name, array
    );

    // 3. Transform to camelCase + inject __typename
    let transformed = transform_json(&response, type_name);

    // 4. Return UTF-8 bytes
    Ok(transformed.into_bytes())
}
```

## Performance Benefits

By delegating to Rust:

- **7-10x faster** JSON transformation
- **Zero Python overhead** for string operations
- **Direct UTF-8 bytes** to HTTP (no Python serialization)

## Type Safety

The Python/Rust boundary is type-safe via PyO3:

- Python `list[str]` → Rust `Vec<String>`
- Python `str | None` → Rust `Option<String>`
- Rust `Vec<u8>` → Python `bytes`

## Debugging

### Enable Rust Logs

```bash
RUST_LOG=fraiseql_rs=debug python app.py
```

### Inspect Rust Output

```python
from fraiseql.core.rust_pipeline import RustResponseBytes
import json

result = await repo.find("v_user")
if isinstance(result, RustResponseBytes):
    # Convert bytes to string for inspection
    json_str = result.bytes.decode('utf-8')
    print(json_str)  # See what Rust produced

    # Parse to verify structure
    data = json.loads(json_str)
    print(json.dumps(data, indent=2))
```

## Contributing to Rust Code

The Rust code lives in `fraiseql_rs/` directory:

```
fraiseql_rs/
├── Cargo.toml           # Rust dependencies
├── src/
│   ├── lib.rs          # Main entry point
│   ├── transform.rs    # CamelCase transformation
│   ├── typename.rs     # __typename injection
│   └── response.rs     # GraphQL response building
└── tests/              # Rust tests
```

See [Contributing Guide](../../CONTRIBUTING.md) for Rust development setup.

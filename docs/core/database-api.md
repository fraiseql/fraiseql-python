# Database API

Repository pattern for async database operations with type safety, structured queries, and JSONB views.

**📍 Navigation**: [← Queries & Mutations](queries-and-mutations.md) • [Performance →](../performance/index.md) • [Database Patterns →](../advanced/database-patterns.md)

## Overview

FraiseQL provides a repository layer (`FraiseQLRepository`, in `fraiseql.db`) for database operations that:

- Executes structured queries against JSONB views
- Supports dynamic filtering with operators
- Handles pagination and ordering
- Sets per-request PostgreSQL session variables (tenant, user) for Row-Level Security
- Returns RustResponseBytes for automatic GraphQL processing

This page is a guide. The full method reference, with every parameter, is
[Database API Reference](../reference/database.md).

## Query Flow Architecture

### Repository Query Execution

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ GraphQL     │───▶│ Repository  │───▶│ PostgreSQL  │───▶│   Rust      │
│ Resolver    │    │  Method     │    │   View      │    │ Pipeline    │
│             │    │             │    │             │    │             │
│ @query      │    │ find()      │    │ SELECT data │    │ Transform   │
│ def users:  │    │             │    │ FROM v_user │    │ JSONB→GraphQL│
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

**Query Flow Steps:**

1. **GraphQL Resolver** calls repository method with filters
2. **Repository** builds SQL query with WHERE clauses and pagination
3. **PostgreSQL** executes view and returns JSONB results
4. **Rust Pipeline** transforms JSONB to GraphQL response format


## FraiseQLRepository

Core repository class for async database operations with exclusive Rust pipeline integration.

### Getting a Repository

`create_fraiseql_app()` opens the connection pool and puts a repository in every
request's context. Resolvers read it from `info.context["db"]`:

```python
@fraiseql.query
async def users(info) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user")
```

Outside a request (scripts, background jobs), build one from a psycopg pool:

```python
from psycopg_pool import AsyncConnectionPool

from fraiseql.db import FraiseQLRepository

pool = AsyncConnectionPool("postgresql://localhost/mydb", min_size=5, max_size=20, open=False)
await pool.open()

db = FraiseQLRepository(pool)
total = await db.count("v_user")
```

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| pool | AsyncConnectionPool | Yes | psycopg connection pool |
| context | dict | No | Request context; `tenant_id`, `user_id`, `contact_id` and `roles` become session variables |

### Key Methods

#### find(view_name, field_name, **kwargs)

Execute query using the exclusive Rust pipeline with automatic field selection.

**Fastest path** - PostgreSQL → Rust → HTTP with zero Python string operations.

```python
@fraiseql.query
async def users(info, limit: int = 100) -> list[User]:
    db = info.context["db"]
    # Rust pipeline automatically used
    # field_name auto-inferred from function name "users"
    return await db.find("v_user", limit=limit)

@fraiseql.query
async def filtered_users(info, min_age: int = 18) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user", "filteredUsers", where={"age": {"gte": min_age}})
```

**Parameters:**

- `view_name: str` - Database view name (e.g., "v_user")
- `field_name: str` - GraphQL field name for response wrapping (e.g., "users")
- `**kwargs` - Query parameters: `where`, `limit`, `offset`, `order_by`, `mandatory_filters`

**Returns:** Result handled automatically by framework (annotate resolver with `list[User]`)

> **Note**: The `info` parameter is auto-injected from context for field selection.

#### find_one(view_name, field_name, **kwargs)

Execute single-result query using the exclusive Rust pipeline.

```python
from fraiseql.types import ID

@fraiseql.query
async def user(info, id: ID) -> User | None:
    db = info.context["db"]
    return await db.find_one("v_user", "user", mandatory_filters={"id": id})
```

**Parameters:**

- `view_name: str` - Database view name
- `field_name: str` - GraphQL field name for response wrapping
- `**kwargs` - `mandatory_filters={column: value}` (equality on view columns), `where={...}`

**Returns:** Result handled automatically (annotate with `User | None`)

#### Other methods

| Method | Returns | Use |
|--------|---------|-----|
| `count(view, where=..., mandatory_filters=...)` | `int` | Row count for the same filters as `find()` |
| `exists(view, where=..., mandatory_filters=...)` | `bool` | Whether any row matches |
| `execute_function(name, input)` | `dict` | Call a PostgreSQL mutation function |
| `run(DatabaseQuery(...))` | `list[dict]` | Raw SQL with session variables applied |
| `run_in_transaction(func, *args)` | result of `func` | Several statements in one transaction |
| `get_pool()` | `AsyncConnectionPool` | The underlying psycopg pool |

See the [reference](../reference/database.md) for each.

### Standard GraphQL Query Pattern

A query returning `list[T]` gets `where`, `orderBy`, `limit` and `offset` arguments in
the schema whether or not the resolver declares them. `db.find()` on `T`'s view applies
the values the client sent:

```python
@fraiseql.query
async def users(info) -> list[User]:
    """List users with filtering, pagination, and ordering."""
    db = info.context["db"]
    return await db.find("v_user")
```

**GraphQL Usage**:

```graphql
query {
  users(
    where: { isActive: { eq: true } }
    orderBy: [{ createdAt: DESC }]
    limit: 10
    offset: 0
  ) {
    id
    name
    email
  }
}
```

A keyword you pass to `db.find()` yourself wins over the client's value.

### ⚠️ Default Ordering for List Queries

**IMPORTANT**: List queries should have a default ordering for consistent pagination.
Declare `order_by` on the resolver (FraiseQL then passes the client's value to it) and
fall back to your default:

```python
from fraiseql.sql import create_graphql_order_by_input

UserOrderByInput = create_graphql_order_by_input(User)

@fraiseql.query
async def users(
    info,
    order_by: list[UserOrderByInput] | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[User]:
    """List users with default ordering."""
    db = info.context["db"]

    # ✅ CORRECT: Default ordering if not specified
    return await db.find(
        "v_user",
        order_by=order_by or {"created_at": "DESC"},
        limit=limit,
        offset=offset,
    )
```

**Why Default Ordering Matters**:

- Without ordering, pagination results are **non-deterministic**
- Database may return rows in different order between requests
- Users may see duplicates or miss items when paginating

**Best Practices**:

- Use `created_at DESC` for "most recent first" lists
- Use `name ASC` for alphabetical lists
- Use `id ASC` for stable ordering

## Dynamic Filters

`where` takes a dict of `{field: {operator: value}}` (or a generated `WhereInput`,
below). Field names are the GraphQL/JSONB field names; camelCase is converted to
snake_case.

> **💡 Advanced Filtering**: For comprehensive PostgreSQL operator support including arrays, full-text search, JSONB queries, and regex, see **[Filter Operators Reference](../advanced/filter-operators.md)** and **[Advanced Filtering Examples](../examples/advanced-filtering.md)**.

### Supported Operators

| Operator | SQL Equivalent | Example | Description |
|----------|----------------|---------|-------------|
| (plain value) | = | `{"status": "active"}` | Exact match |
| `eq` / `neq` | = / != | `{"status": {"neq": "deleted"}}` | Equality |
| `gt` / `gte` / `lt` / `lte` | > / >= / < / <= | `{"age": {"gte": 18}}` | Comparison |
| `in` / `nin` | IN / NOT IN | `{"status": {"in": ["active", "pending"]}}` | Match any value in list |
| `contains` / `icontains` | LIKE / ILIKE | `{"name": {"icontains": "john"}}` | Substring |
| `startswith` / `endswith` | LIKE | `{"email": {"endswith": "@example.com"}}` | Prefix / suffix |
| `isnull` | IS NULL / IS NOT NULL | `{"deleted_at": {"isnull": True}}` | Null check |

### Filter Examples

**Range queries**:

```python
orders = await db.find(
    "v_order",
    where={
        "created_at": {"gte": "2024-01-01", "lte": "2024-12-31"},
        "total_amount": {"gte": 10, "lte": 100},
    },
)
```

**Multiple conditions** (combined with AND):

```python
products = await db.find(
    "v_product",
    where={
        "category": {"eq": "electronics"},
        "price": {"lte": 500},
        "in_stock": {"eq": True},
        "vendor": {"in": ["vendor-a", "vendor-b"]},
    },
)
```

## Nested Object Filtering

FraiseQL supports filtering on nested objects stored in JSONB columns.

### Dict-Based vs Typed Filters

FraiseQL supports both dict-based and typed filter inputs. **Typed inputs are recommended** for type safety.

#### Dict-Based Filters (Simple, but no type checking)

```python
# ⚠️ Works, but no IDE autocomplete or type checking
where = {
    "machine": {
        "name": {"eq": "Server-01"}
    }
}
results = await db.find("v_allocation", where=where)
# SQL: WHERE data->'machine'->>'name' = 'Server-01'
```

#### Typed Filters (Recommended - Type Safe)

```python
# ✅ RECOMMENDED: Full type safety and IDE support
from fraiseql.sql import StringFilter, create_graphql_where_input

AllocationWhereInput = create_graphql_where_input(Allocation)
MachineWhereInput = create_graphql_where_input(Machine)

where = AllocationWhereInput(
    machine=MachineWhereInput(
        name=StringFilter(eq="Server-01")
    )
)
results = await db.find("v_allocation", where=where)
# Same SQL, but with type checking!
```

**Benefits of Typed Filters**:

- ✅ IDE autocomplete shows available fields
- ✅ Type checker catches typos: `nmae` → error
- ✅ Invalid operators rejected: `StringFilter(gte=...)` → error
- ✅ Better documentation through types

**When to Use Each**:

- **Typed**: Production code, complex filters, team projects
- **Dict**: Quick scripts, simple filters, prototyping

### Multiple Nesting Levels

```python
# Dict-based (for typed alternative, see "Dict-Based vs Typed Filters" above)
where = {
    "location": {
        "address": {
            "city": {"eq": "Seattle"}
        }
    }
}
# SQL: WHERE data->'location'->'address'->>'city' = 'Seattle'
```

### Combined Filters

Mix flat and nested filters:

```python
# Dict-based (for typed alternative, see "Dict-Based vs Typed Filters" above)
where = {
    "status": {"eq": "active"},
    "machine": {
        "type": {"eq": "Server"},
        "power": {"gte": 100}
    }
}
# SQL: WHERE data->>'status' = 'active'
#      AND data->'machine'->>'type' = 'Server'
#      AND data->'machine'->>'power' >= 100
```

### Type Naming Conventions

FraiseQL uses consistent naming patterns for generated types:

| Type Category | Suffix | Example | Usage |
|--------------|--------|---------|-------|
| **Input Types** | `Input` | `CreateUserInput` | Mutation inputs |
| **Filter Types** | `WhereInput` | `UserWhereInput` | Query filtering |
| **Field Filters** | `Filter` | `StringFilter`, `IntFilter` | Individual field filters |
| **Ordering** | `OrderByInput` | `UserOrderByInput` | Sorting |
| **Success Types** | `Success` | `CreateUserSuccess` | Successful mutation result |
| **Error Types** | `Error` | `CreateUserError` | Failed mutation result |

**Example - Complete Type Usage**:

```python
from fraiseql.sql import BooleanFilter, IntFilter, StringFilter, create_graphql_where_input

# Generated WhereInput types (always end with 'WhereInput')
UserWhereInput = create_graphql_where_input(User)

# Field filters always end with 'Filter'
where = UserWhereInput(
    name=StringFilter(contains="John"),      # StringFilter for text
    age=IntFilter(gte=18),                   # IntFilter for numbers
    is_active=BooleanFilter(eq=True)         # BooleanFilter for booleans
)

results = await db.find("v_user", where=where)
```

### Supported Operators

All standard operators work with nested objects:

- `eq`, `neq` - equality/inequality
- `gt`, `gte`, `lt`, `lte` - comparisons
- `in`, `nin` - list membership
- `contains`, `startswith`, `endswith` - string patterns
- `isnull` - null checks

## Pagination

Pass `limit` and `offset` to `find()`, with an `order_by` so pages are stable, and
`count()` with the same `where` for the total:

```python
page, page_size = 2, 20
where = {"status": {"eq": "active"}}

orders = await db.find(
    "v_order",
    where=where,
    order_by={"created_at": "DESC"},
    limit=page_size,
    offset=(page - 1) * page_size,
)
total = await db.count("v_order", where=where)
has_next_page = page * page_size < total
```

## Ordering

`order_by` takes a dict for one field, a list of dicts for several (applied in order),
or a generated `OrderByInput`. Nested JSONB paths use dots:

```python
# One field
await db.find("v_order", order_by={"created_at": "DESC"})

# Several fields
await db.find("v_order", order_by=[{"status": "ASC"}, {"total_amount": "DESC"}])

# Nested field
await db.find("v_order", order_by={"customer.name": "ASC"})
```

## Multi-Tenancy

Two mechanisms, usually combined:

**Session variables for Row-Level Security.** When the request context carries
`tenant_id` (and `user_id`, `roles`), the repository sets `app.tenant_id` (and
`app.user_id`, `app.is_super_admin`) with `set_config(..., true)` before each
`find`/`find_one`/`count`/`exists`/`run`/`execute_function` query. RLS policies read
them with `current_setting('app.tenant_id', true)`. See
[Context and Session Variables](../reference/database.md#context-and-session-variables).

**Explicit filters.** `mandatory_filters` adds an equality condition on a view column
that the client's `where` can't remove:

```python
@fraiseql.query
async def orders(info) -> list[Order]:
    db = info.context["db"]
    return await db.find("v_order", mandatory_filters={"tenant_id": info.context["tenant_id"]})
```

There is no switch that bypasses tenant filtering: an admin query simply leaves out
`mandatory_filters`, and RLS policies can let `app.is_super_admin` through.

## Raw SQL

For SQL that isn't a read of a view, `run()` executes a statement with the request's
session variables applied, and `get_pool()` gives you the psycopg pool:

```python
from psycopg.sql import SQL

from fraiseql.db import DatabaseQuery

rows = await db.run(
    DatabaseQuery(
        SQL("SELECT status, count(*) AS n FROM tb_order WHERE total_amount >= %(min)s GROUP BY status"),
        {"min": 100},
    )
)
# [{"status": "pending", "n": 1}, ...]

async with db.get_pool().connection() as conn:
    await conn.execute(
        "UPDATE tb_order SET status = %s WHERE id = %s", ("shipped", order_id)
    )
# The pool commits when the block exits without an exception
```

Placeholders are psycopg's (`%s`, `%(name)s`), never string formatting. Use
`run_in_transaction()` to run several statements in one transaction; mutations should
normally go through PostgreSQL functions and `execute_function()`.

## Error Handling

Repository methods raise psycopg's exceptions (`psycopg.errors.*`, subclasses of
`psycopg.Error`) for SQL errors, `psycopg_pool.PoolTimeout` when no connection is free,
and `TypeError` / `ValueError` for a malformed `where` or an unknown keyword argument:

```python
import psycopg

try:
    total = await db.count("v_order", where={"status": {"eq": "active"}})
except psycopg.errors.UndefinedTable:
    logger.error("v_order is missing - run the migrations")
    raise
except psycopg.Error as e:
    logger.error(f"Query failed: {e}")
    raise
```

## Best Practices

**Use structured queries**:

```python
# Good: filters, ordering and pagination through find()
orders = await db.find(
    "v_order",
    where={"status": {"eq": "active"}},
    order_by={"created_at": "DESC"},
    limit=50,
)

# Avoid: Raw SQL strings for view reads
query = "SELECT * FROM v_order WHERE status = 'active' LIMIT 50"
```

**Use the shared connection pool**: take `info.context["db"]` (or `db.get_pool()`)
rather than opening a connection per request.

**Handle pagination correctly**: compare `offset + page_size` with `db.count()` instead
of assuming more results exist.

**Use tenant isolation**: put `tenant_id` in the request context so RLS sees it, and use
`mandatory_filters` where the view has a `tenant_id` column.

## Complete Example

```python
import fraiseql
from fraiseql.types import ID


@fraiseql.type(sql_source="v_order", jsonb_column="data")
class Order:
    id: ID
    status: str
    total_amount: float
    created_at: str


@fraiseql.query
async def recent_orders(
    info,
    statuses: list[str],
    min_total: float = 100,
    limit: int = 20,
    offset: int = 0,
) -> list[Order]:
    """The tenant's recent orders with a status in `statuses`."""
    db = info.context["db"]
    return await db.find(
        "v_order",
        where={
            "status": {"in": statuses},
            "created_at": {"gte": "2024-01-01"},
            "total_amount": {"gte": min_total},
        },
        mandatory_filters={"tenant_id": info.context["tenant_id"]},
        order_by={"created_at": "DESC"},
        limit=limit,
        offset=offset,
    )
```

```graphql
query {
  recentOrders(statuses: ["active", "pending"]) {
    id
    status
    totalAmount
  }
}
```

## See Also

- [Database API Reference](../reference/database.md) - Every repository method and parameter
- [Queries & Mutations](queries-and-mutations.md) - Using repository methods in GraphQL resolvers
- [Database Patterns](../advanced/database-patterns.md) - View design and N+1 prevention
- [Performance](../performance/index.md) - Query optimization
- [Multi-Tenancy](../advanced/multi-tenancy.md) - Tenant isolation patterns

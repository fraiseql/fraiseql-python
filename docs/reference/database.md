---
title: Database API Reference
description: Complete reference for FraiseQLRepository and database operations
tags:
  - database
  - API
  - repository
  - queries
  - PostgreSQL
  - CRUD
---

# Database API Reference

Complete reference for FraiseQL database operations and repository methods.

## Overview

FraiseQL provides a high-performance database API through the `FraiseQLRepository` class, which is automatically available in GraphQL resolvers via `info.context["db"]`.

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.query
async def user(info, id: ID) -> User:
    db = info.context["db"]
    # field_name auto-inferred as "user" from function name
    return await db.find_one("v_user", mandatory_filters={"id": id})
```

> **Note**: FraiseQL has two repository classes: `FraiseQLRepository` (modern, recommended) and `CQRSRepository` (legacy). See [Repository Classes Comparison](repositories.md) for details on when to use each.

## Accessing the Database

**In Resolvers**:

```python
db = info.context["db"]  # FraiseQLRepository instance
```

**Repository Instance**: Automatically injected into GraphQL context by FraiseQL

## Query Methods

### find()

**Purpose**: Find multiple records with automatic GraphQL field selection

**Signature**:

```python
async def find(
    view_name: str,
    field_name: str | None = None,
    **kwargs: Any
) -> Any
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| view_name | str | Yes | Database view or table name (e.g., "v_user") |
| field_name | str \| None | No | GraphQL field name for response wrapping. **Auto-inferred** from `info.field_name` (your resolver function name). Only specify if you need to override. |
| **kwargs | Any | No | Query parameters: `where`, `limit`, `offset`, `order_by` |

> **Note**: The `info` parameter is automatically injected from the GraphQL context. The `field_name` is also **automatically extracted from `info.field_name`**, so you typically don't need to specify it!

**Modern API (recommended)**:

```python
@fraiseql.query
async def users(info, limit: int = 100) -> list[User]:
    db = info.context["db"]
    # field_name auto-inferred from function name "users"
    return await db.find("v_user", limit=limit)
```

**Explicit field_name (only if needed)**:

```python
# Only specify field_name if it differs from the function name
return await db.find("v_user", "userList", limit=limit)
```

**Returns**: The result is handled automatically by the framework. In your resolver, annotate the return type with your GraphQL type (e.g., `list[User]`).

**Examples**:

```python
# Simple query (field_name auto-inferred from function name)
@fraiseql.query
async def users(info, limit: int = 100) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user", limit=limit)

# With filter
@fraiseql.query
async def active_users(info) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user", where={"is_active": True})

# With pagination
@fraiseql.query
async def paginated_users(info, page: int = 1, page_size: int = 20) -> list[User]:
    db = info.context["db"]
    offset = (page - 1) * page_size
    return await db.find("v_user", limit=page_size, offset=offset)

# With ordering (list of tuples format)
@fraiseql.query
async def recent_users(info, limit: int = 10) -> list[User]:
    db = info.context["db"]
    return await db.find(
        "v_user",
        order_by=[("created_at", "DESC")],
        limit=limit
    )

# Complex filter (dict-based)
@fraiseql.query
async def search_users(info, name: str) -> list[User]:
    db = info.context["db"]
    return await db.find(
        "v_user",
        where={
            "name__icontains": name,
            "created_at__gte": datetime(2025, 1, 1)
        }
    )

# Using typed WhereInput (auto-generated)
@fraiseql.query
async def filtered_users(info, where: UserWhereInput | None = None) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user", where=where)
```

**Filter Operators** (dict-based):

| Operator | Description | Example |
|----------|-------------|---------|
| `field` | Exact match | `{"status": "active"}` |
| `field__eq` | Equals | `{"age__eq": 25}` |
| `field__neq` | Not equals | `{"status__neq": "deleted"}` |
| `field__gt` | Greater than | `{"age__gt": 18}` |
| `field__gte` | Greater than or equal | `{"age__gte": 18}` |
| `field__lt` | Less than | `{"age__lt": 65}` |
| `field__lte` | Less than or equal | `{"age__lte": 65}` |
| `field__in` | In list | `{"status__in": ["active", "pending"]}` |
| `field__contains` | Contains substring (case-sensitive) | `{"name__contains": "John"}` |
| `field__icontains` | Contains substring (case-insensitive) | `{"name__icontains": "john"}` |
| `field__startswith` | Starts with | `{"email__startswith": "admin"}` |
| `field__endswith` | Ends with | `{"email__endswith": "@example.com"}` |
| `field__isnull` | Is null | `{"deleted_at__isnull": True}` |

### find_one()

**Purpose**: Find a single record with automatic GraphQL field selection

**Signature**:

```python
async def find_one(
    view_name: str,
    field_name: str | None = None,
    **kwargs: Any
) -> Any | None
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| view_name | str | Yes | Database view or table name (e.g., "v_user") |
| field_name | str \| None | No | GraphQL field name for response wrapping. **Auto-inferred** from `info.field_name`. Only specify if needed. |
| **kwargs | Any | No | Filter conditions (e.g., `id=user_id`, `where={...}`) |

> **Note**: Both `info` and `field_name` are automatically handled. You typically only need to specify `view_name` and filter conditions.

**Returns**: The result is handled automatically by the framework. In your resolver, annotate the return type with your GraphQL type (e.g., `User | None`). Returns `None` if not found.

**Examples**:

```python
from fraiseql.types import ID

# Find by ID (field_name auto-inferred from function name "user")
@fraiseql.query
async def user(info, id: ID) -> User | None:
    db = info.context["db"]
    return await db.find_one("v_user", mandatory_filters={"id": id})

# Using where parameter
@fraiseql.query
async def user_by_email(info, email: str) -> User | None:
    db = info.context["db"]
    return await db.find_one("v_user", where={"email": email})

# Find with complex filter
@fraiseql.query
async def active_user_by_email(info, email: str) -> User | None:
    db = info.context["db"]
    return await db.find_one(
        "v_user",
        where={"email": email, "is_active": True}
    )

# Handle not found case
@fraiseql.query
async def get_user(info, id: ID) -> User:
    db = info.context["db"]
    user = await db.find_one("v_user", mandatory_filters={"id": id})
    if user is None:
        raise GraphQLError("User not found")
    return user
```

### count()

**Purpose**: Count records matching filter criteria

**Signature**:

```python
async def count(
    view_name: str,
    **kwargs: Any
) -> int
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| view_name | str | Yes | Database view or table name |
| where | dict \| WhereType \| None | No | Filter conditions |
| **kwargs | Any | No | Additional filter conditions (e.g., tenant_id) |

**Returns**: Integer count of matching records

**Examples**:

```python
# Count all users
total = await db.count("v_users")
# Returns: 1523

# Count with filter
active_count = await db.count(
    "v_users",
    where={"status": {"eq": "active"}}
)
# Returns: 842

# Count with tenant_id
tenant_users = await db.count(
    "v_users",
    tenant_id="tenant-123"
)
# Returns: 67

# Count with complex filters
electronics_count = await db.count(
    "v_products",
    where={
        "price": {"gt": 100, "lt": 500},
        "category": {"eq": "electronics"},
        "in_stock": {"eq": True}
    }
)
# Returns: 23

# In GraphQL resolver
@fraiseql.query
async def users_count(info, where: UserWhereInput | None = None) -> int:
    """Count users with optional filtering."""
    db = info.context["db"]
    return await db.count("v_users", where=where)

@fraiseql.query
async def tenant_stats(info) -> TenantStats:
    """Get statistics for current tenant."""
    db = info.context["db"]
    tenant_id = info.context["tenant_id"]

    return TenantStats(
        total_users=await db.count("v_users", tenant_id=tenant_id),
        active_users=await db.count(
            "v_users",
            tenant_id=tenant_id,
            where={"status": {"eq": "active"}}
        ),
        total_orders=await db.count("v_orders", tenant_id=tenant_id),
    )
```

**Performance**:

- Uses optimized `COUNT(*)` SQL query
- Returns plain `int` (not `RustResponseBytes`)
- Supports same filter syntax as `find()`
- Efficient for large datasets

**Note**: Unlike `find()` and `find_one()`, `count()` returns a plain Python `int` instead of `RustResponseBytes` because count is a simple scalar value.

## Pagination Methods

### paginate()

**Purpose**: Cursor-based pagination following Relay specification

**Signature**:

```python
async def paginate(
    view_name: str,
    first: int | None = None,
    after: str | None = None,
    last: int | None = None,
    before: str | None = None,
    filters: dict | None = None,
    order_by: str = "id",
    include_total: bool = True,
    jsonb_extraction: bool | None = None,
    jsonb_column: str | None = None
) -> dict[str, Any]
```

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| view_name | str | - | Database view or table name |
| first | int \| None | None | Number of items to fetch forward |
| after | str \| None | None | Cursor to fetch after |
| last | int \| None | None | Number of items to fetch backward |
| before | str \| None | None | Cursor to fetch before |
| filters | dict \| None | None | Filter conditions |
| order_by | str | "id" | Field to order by |
| include_total | bool | True | Include total count in result |
| jsonb_extraction | bool \| None | None | Enable JSONB extraction |
| jsonb_column | str \| None | None | JSONB column name |

**Returns**: Dictionary with edges, page_info, and total_count

**Result Structure**:

```python
{
    "edges": [
        {
            "node": {"id": "...", "name": "...", ...},
            "cursor": "cursor_string"
        },
        ...
    ],
    "page_info": {
        "has_next_page": True,
        "has_previous_page": False,
        "start_cursor": "first_cursor",
        "end_cursor": "last_cursor",
        "total_count": 100
    },
    "total_count": 100
}
```

**Examples**:

```python
# Forward pagination
result = await db.paginate("v_user", first=20)

# With cursor
result = await db.paginate("v_user", first=20, after="cursor_xyz")

# Backward pagination
result = await db.paginate("v_user", last=10, before="cursor_abc")

# With filters
result = await db.paginate(
    "v_user",
    first=20,
    filters={"is_active": True},
    order_by="created_at"
)

# Convert to typed Connection
from fraiseql.types import create_connection

connection = create_connection(result, User)
```

**Note**: Usually accessed via `@connection` decorator rather than directly

## Mutation Patterns

FraiseQL follows the CQRS (Command Query Responsibility Segregation) pattern. Mutations are handled by PostgreSQL functions, not direct repository methods.

### Creating Records

Use `execute_function()` with a PostgreSQL function, then fetch the result with `find_one()`:

```python
import fraiseql

@fraiseql.mutation
async def create_user(info, input: CreateUserInput) -> User:
    db = info.context["db"]

    # Execute PostgreSQL function to create record
    result = await db.execute_function("fn_create_user", {
        "name": input.name,
        "email": input.email
    })

    # Fetch created record via Rust pipeline
    # field_name auto-inferred from function name "create_user" → "user"
    return await db.find_one("v_user", mandatory_filters={"id": result["id"]})
```

**PostgreSQL Function**:

See [canonical fn_create_user()](../examples/canonical-examples.md#create-user-function) for a complete example with validation and error handling.

Simple version:

```sql
CREATE OR REPLACE FUNCTION fn_create_user(input jsonb) RETURNS jsonb AS $$
BEGIN
    RETURN jsonb_build_object('id',
        (INSERT INTO tb_user (name, email)
         VALUES (input->>'name', input->>'email')
         RETURNING id)
    );
END;
$$ LANGUAGE plpgsql;
```

### Updating Records

```python
from fraiseql.types import ID

@fraiseql.mutation
async def update_user(info, id: ID, input: UpdateUserInput) -> User:
    db = info.context["db"]

    # Execute PostgreSQL function to update record
    result = await db.execute_function("fn_update_user", {
        "id": id,
        **input.__dict__
    })

    # Fetch updated record
    return await db.find_one("v_user", mandatory_filters={"id": id})
```

### Deleting Records

```python
from fraiseql.types import ID

@fraiseql.mutation
async def delete_user(info, id: ID) -> bool:
    db = info.context["db"]

    # Execute PostgreSQL function to delete record
    result = await db.execute_function("fn_delete_user", {"id": id})

    return result.get("success", False)
```

## PostgreSQL Function Execution

### execute_function()

**Purpose**: Execute a PostgreSQL function with JSONB input

**Signature**:

```python
async def execute_function(
    function_name: str,
    input_data: dict[str, Any]
) -> dict[str, Any]
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| function_name | str | Yes | Fully qualified function name (e.g., 'graphql.create_user') |
| input_data | dict | Yes | Dictionary to pass as JSONB to the function |

**Returns**: Dictionary result from the function

**Examples**:

```python
# Execute mutation function
result = await db.execute_function(
    "graphql.create_user",
    {"name": "John", "email": "john@example.com"}
)

# With schema prefix
result = await db.execute_function(
    "auth.register_user",
    {"email": "user@example.com", "password": "secret"}
)
```

**PostgreSQL Function Format**:

```sql
CREATE OR REPLACE FUNCTION graphql.create_user(input jsonb)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
BEGIN
    -- Function implementation
    RETURN jsonb_build_object(
        'success', true,
        'data', ...
    );
END;
$$;
```

### execute_function_with_context()

**Purpose**: Execute a PostgreSQL function with context parameters

**Signature**:

```python
async def execute_function_with_context(
    function_name: str,
    context_args: list[Any],
    input_data: dict[str, Any]
) -> dict[str, Any]
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| function_name | str | Yes | Fully qualified function name |
| context_args | list | Yes | List of context arguments (e.g., [tenant_id, user_id]) |
| input_data | dict | Yes | Dictionary to pass as JSONB |

**Returns**: Dictionary result from the function

**Examples**:

```python
# With tenant isolation
result = await db.execute_function_with_context(
    "app.create_location",
    [tenant_id, user_id],
    {"name": "Office", "address": "123 Main St"}
)

# Function signature in PostgreSQL
# CREATE FUNCTION app.create_location(
#     p_tenant_id uuid,
#     p_user_id uuid,
#     input jsonb
# ) RETURNS jsonb
```

**Note**: Automatically called by class-based `@fraiseql.mutation` decorator with `context_params`

## Raw SQL Execution

### execute_raw()

**Purpose**: Execute raw SQL queries

**Signature**:

```python
async def execute_raw(
    query: str,
    *params
) -> list[dict[str, Any]]
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| query | str | Yes | SQL query with parameter placeholders ($1, $2, etc.) |
| *params | Any | No | Query parameters |

**Returns**: List of dictionaries (query results)

**Examples**:

```python
# Simple query
results = await db.execute_raw("SELECT * FROM users")

# With parameters
results = await db.execute_raw(
    "SELECT * FROM users WHERE id = $1",
    user_id
)

# Complex aggregation
stats = await db.execute_raw(
    """
    SELECT
        count(*) as total_users,
        count(*) FILTER (WHERE is_active) as active_users
    FROM users
    WHERE created_at > $1
    """,
    datetime(2025, 1, 1)
)
```

**Security**: Always use parameterized queries to prevent SQL injection

## Transaction Methods

### run_in_transaction()

**Purpose**: Run operations within a database transaction

**Signature**:

```python
async def run_in_transaction(
    func: Callable[..., Awaitable[T]],
    *args,
    **kwargs
) -> T
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| func | Callable | Yes | Async function to execute in transaction |
| *args | Any | No | Arguments to pass to func |
| **kwargs | Any | No | Keyword arguments to pass to func |

**Returns**: Result of the function

**Examples**:

```python
import fraiseql

async def transfer_funds(conn, source_id, dest_id, amount):
    # Deduct from source
    await conn.execute(
        "UPDATE accounts SET balance = balance - $1 WHERE id = $2",
        amount,
        source_id
    )

    # Add to destination
    await conn.execute(
        "UPDATE accounts SET balance = balance + $1 WHERE id = $2",
        amount,
        dest_id
    )

    return True

# Execute in transaction
@fraiseql.mutation
async def transfer(info, input: TransferInput) -> bool:
    db = info.context["db"]
    return await db.run_in_transaction(
        transfer_funds,
        input.source_id,
        input.dest_id,
        input.amount
    )
```

**Note**: Transaction is automatically rolled back on exception

## Connection Pool

### get_pool()

**Purpose**: Access the underlying connection pool

**Signature**:

```python
def get_pool() -> AsyncConnectionPool
```

**Returns**: psycopg AsyncConnectionPool instance

**Example**:

```python
pool = db.get_pool()
print(f"Pool size: {pool.max_size}")
```

## Context and Session Variables

**Automatic Session Variable Injection**:

FraiseQL **automatically sets PostgreSQL session variables** from GraphQL context on every request. This is a powerful feature for multi-tenant applications and row-level security.

**Automatically Set Variables**:

| Session Variable | Source | Type | Purpose |
|-----------------|--------|------|---------|
| `app.tenant_id` | `info.context["tenant_id"]` | UUID | Multi-tenant isolation |
| `app.contact_id` | `info.context["contact_id"]` or `info.context["user"]` | UUID | User identification |

**How It Works**:

1. You provide context in your FastAPI app:

```python
async def get_context(request: Request) -> dict:
    return {
        "tenant_id": extract_tenant_from_jwt(request),
        "contact_id": extract_user_from_jwt(request)
    }

app = create_fraiseql_app(
    config=config,
    context_getter=get_context,
    # ... other params
)
```

2. FraiseQL automatically executes before each database operation:

```sql
SET LOCAL app.tenant_id = '<tenant_id_from_context>';
SET LOCAL app.contact_id = '<contact_id_from_context>';
```

3. Your PostgreSQL functions can access these variables:

```sql
SELECT current_setting('app.tenant_id')::uuid;
SELECT current_setting('app.contact_id')::uuid;
```

### Using Session Variables in PostgreSQL

**In Views (Multi-Tenant Data Filtering)**:

```sql
-- View that automatically filters by tenant
CREATE VIEW v_order AS
SELECT
    id,
    tenant_id,
    customer_id,
    data
FROM tb_order
WHERE tenant_id = current_setting('app.tenant_id')::uuid;
```

Now all queries to `v_order` automatically see only their tenant's data:

```python
import fraiseql

@fraiseql.query
async def orders(info) -> list[Order]:
    db = info.context["db"]
    # Automatically filtered by tenant_id from context!
    return await db.find("v_order")
```

**In Functions (Audit Logging)**:

```sql
CREATE FUNCTION graphql.create_order(input jsonb)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
    v_tenant_id uuid;
    v_user_id uuid;
    v_order_id uuid;
BEGIN
    -- Get session variables
    v_tenant_id := current_setting('app.tenant_id')::uuid;
    v_user_id := current_setting('app.contact_id')::uuid;

    -- Insert with automatic tenant_id and created_by
    INSERT INTO tb_order (tenant_id, data)
    VALUES (
        v_tenant_id,
        jsonb_set(
            input,
            '{created_by}',
            to_jsonb(v_user_id)
        )
    )
    RETURNING id INTO v_order_id;

    RETURN jsonb_build_object(
        'success', true,
        'id', v_order_id
    );
END;
$$;
```

**In Row-Level Security Policies**:

```sql
-- Enable RLS on table
ALTER TABLE tb_document ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see their tenant's documents
CREATE POLICY tenant_isolation_policy ON tb_document
    FOR ALL
    TO PUBLIC
    USING (tenant_id = current_setting('app.tenant_id')::uuid);

-- Policy: Users can only modify documents they created
CREATE POLICY user_modification_policy ON tb_document
    FOR UPDATE
    TO PUBLIC
    USING (
        tenant_id = current_setting('app.tenant_id')::uuid
        AND (data->>'created_by')::uuid = current_setting('app.contact_id')::uuid
    );
```

**In Triggers (Automatic Audit Fields)**:

```sql
CREATE FUNCTION fn_set_audit_fields()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    -- Automatically set created_by on insert
    IF (TG_OP = 'INSERT') THEN
        NEW.data := jsonb_set(
            NEW.data,
            '{created_by}',
            to_jsonb(current_setting('app.contact_id')::uuid)
        );
    END IF;

    -- Automatically set updated_by on update
    IF (TG_OP = 'UPDATE') THEN
        NEW.data := jsonb_set(
            NEW.data,
            '{updated_by}',
            to_jsonb(current_setting('app.contact_id')::uuid)
        );
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_set_audit_fields
    BEFORE INSERT OR UPDATE ON tb_order
    FOR EACH ROW
    EXECUTE FUNCTION fn_set_audit_fields();
```

### Complete Multi-Tenant Example

**1. Context Provider (Python)**:

```python
from fastapi import Request
import jwt

async def get_context(request: Request) -> dict:
    """Extract tenant and user from JWT."""
    auth_header = request.headers.get("authorization", "")

    if not auth_header.startswith("Bearer "):
        return {}  # Anonymous request

    token = auth_header.replace("Bearer ", "")
    decoded = jwt.decode(token, options={"verify_signature": False})

    return {
        "tenant_id": decoded.get("tenant_id"),
        "contact_id": decoded.get("user_id")
    }
```

**2. Database View (SQL)**:

```sql
CREATE VIEW v_product AS
SELECT
    id,
    tenant_id,
    data->>'name' as name,
    (data->>'price')::decimal as price,
    data
FROM tb_product
WHERE tenant_id = current_setting('app.tenant_id')::uuid;
```

**3. GraphQL Query (Python)**:

```python
import fraiseql

@fraiseql.query
async def products(info) -> list[Product]:
    """Get products for current tenant.

    Automatically filtered by tenant_id from JWT token.
    No need to pass tenant_id explicitly!
    """
    db = info.context["db"]
    return await db.find("v_product")
```

**4. Result**:

- User from Tenant A sees only Tenant A's products
- User from Tenant B sees only Tenant B's products
- **No tenant_id filtering needed in application code**

### Error Handling

If session variables are not set (e.g., unauthenticated request):

```sql
-- Handle missing session variable gracefully
CREATE VIEW v_public_product AS
SELECT *
FROM tb_product
WHERE
    CASE
        WHEN current_setting('app.tenant_id', true) IS NULL
        THEN is_public = true  -- Show only public products
        ELSE tenant_id = current_setting('app.tenant_id')::uuid
    END;
```

### Custom Session Variables

You can add custom session variables by including them in context:

```python
async def get_context(request: Request) -> dict:
    return {
        "tenant_id": extract_tenant(request),
        "contact_id": extract_user(request),
        "user_role": extract_role(request),  # Custom variable
    }
```

Access in PostgreSQL (note: FraiseQL only auto-sets `app.tenant_id` and `app.contact_id`, so you'll need to set others manually if needed):

```sql
-- In your function
SELECT current_setting('app.tenant_id')::uuid;  -- Auto-set by FraiseQL
SELECT current_setting('app.contact_id')::uuid; -- Auto-set by FraiseQL
```

### Best Practices

1. **Always use session variables for tenant isolation** - Don't pass tenant_id as query parameters
2. **Combine with RLS policies** - Defense in depth for security
3. **Set variables at transaction scope** - FraiseQL uses `SET LOCAL` automatically
4. **Handle missing variables gracefully** - Use `current_setting('var', true)` to avoid errors
5. **Don't use session variables for high-cardinality data** - They're perfect for tenant/user context, not for dynamic query data

## Performance Modes

**Repository Modes**:

FraiseQL repository operates in two modes:

1. **Production Mode** (default)
   - Returns raw dictionaries
   - Optimized JSON passthrough
   - Minimal object instantiation

2. **Development Mode**
   - Full type instantiation
   - Enhanced debugging
   - Slower but more developer-friendly

**Mode Selection**:

```python
# Explicit mode setting
context = {
    "db": repository,
    "mode": "production"  # or "development"
}
```

## Best Practices

**Query Optimization**:

```python
# Use specific fields instead of SELECT *
users = await db.find("v_user", where={"is_active": True}, limit=100)

# Use pagination for large datasets
result = await db.paginate("v_user", first=50)

# Use database views for complex queries
# Create view: CREATE VIEW v_user_stats AS SELECT ...
stats = await db.find("v_user_stats")
```

**Error Handling**:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.query
async def get_user(info, id: ID) -> User | None:
    try:
        db = info.context["db"]
        return await db.find_one("v_user", mandatory_filters={"id": id})
    except Exception as e:
        logger.error(f"Failed to fetch user {id}: {e}")
        raise GraphQLError("Failed to fetch user")
```

**Security**:

```python
# Always use parameterized queries
results = await db.execute_raw(
    "SELECT * FROM users WHERE email = $1",  # Safe
    email
)

# NEVER do this (SQL injection risk):
# results = await db.execute_raw(f"SELECT * FROM users WHERE email = '{email}'")
```

**Transactions**:

```python
# Use transactions for multi-step operations
async def complex_operation(conn, data):
    # All operations succeed or all fail
    await conn.execute("INSERT INTO table1 ...")
    await conn.execute("UPDATE table2 ...")
    await conn.execute("DELETE FROM table3 ...")

result = await db.run_in_transaction(complex_operation, data)
```

## See Also

- [Queries and Mutations](../core/queries-and-mutations.md) - Using database in resolvers
- [Configuration](../core/configuration.md) - Database configuration options
- [PostgreSQL Functions](../core/database-api.md) - Writing database functions

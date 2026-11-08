---
title: API Reference
description: Complete Python API reference for FraiseQL decorators, classes, and functions
tags:
  - API
  - reference
  - decorators
  - classes
  - Python
---

# API Reference

Complete reference for FraiseQL's Python API, decorators, and core classes.

---

## 📚 Quick Navigation

| Category | Purpose | Link |
|----------|---------|------|
| **Decorators** | `@fraiseql.type`, `@fraiseql.query`, `@fraiseql.mutation` | [Decorators](#decorators) |
| **Database** | Connection, queries, transactions | [Database API](#database-api) |
| **Schema** | GraphQL schema building | [Schema](#schema) |
| **Security** | Authentication, authorization, rate limiting | [Security](#security) |
| **Filters** | WHERE clauses, operators | [Filters](#filters) |
| **Types** | Input types, response types | [Types](#types) |

---

## Decorators

### `@fraiseql.type`

Define a GraphQL type mapped to a PostgreSQL view or table.

**Signature:**

```python
def type(
    sql_source: str,
    jsonb_column: str = "data",
    description: str | None = None
) -> Callable
```

**Parameters:**

- `sql_source`: PostgreSQL view or table name (e.g., `"v_user"`)
- `jsonb_column`: Column containing JSONB data (default: `"data"`)
- `description`: Optional GraphQL type description

**Example:**

```python
from uuid import UUID
from datetime import datetime
import fraiseql

@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    """A user in the system."""
    id: UUID
    name: str
    email: str
    created_at: datetime
```

**See Also:**

- [Types & Schema Guide](../core/types-and-schema.md)
- [Quick Reference](../reference/quick-reference.md)

---

### `@fraiseql.query`

Define a GraphQL query resolver.

**Signature:**

```python
def query(func: Callable) -> Callable
```

**Example:**

```python
@fraiseql.query
async def users(info) -> list[User]:
    """Get all users."""
    db = info.context["db"]
    return await db.find("v_user", "users", info)

@fraiseql.query
async def user(info, id: UUID) -> User | None:
    """Get user by ID."""
    db = info.context["db"]
    return await db.find_one("v_user", "user", info, mandatory_filters={"id": id})
```

**Info Object:**

- `info.context["db"]`: Database connection
- `info.context["user"]`: Authenticated user (if auth enabled)
- `info.field_name`: GraphQL field name
- `info.return_type`: Expected return type

**See Also:**

- [Queries Guide](../core/queries-and-mutations.md)
- [Filtering Guide](../guides/filtering.md)

---

### `@fraiseql.mutation`

Define a GraphQL mutation resolver.

**Signature:**

```python
def mutation(func: Callable) -> Callable
```

**Example:**

```python
@fraiseql.input
class CreateUserInput:
    name: str
    email: str


@fraiseql.success
class CreateUserSuccess:
    user: User


@fraiseql.error
class CreateUserError:
    message: str


@fraiseql.mutation
class CreateUser:
    """Create a new user: calls the SQL function create_user(input jsonb)."""
    input: CreateUserInput
    success: CreateUserSuccess
    error: CreateUserError
```

The SQL function returns a `mutation_response` row; fraiseql turns it into
`CreateUserSuccess` or `CreateUserError` (see [Mutation SQL Requirements](../guides/mutation-sql-requirements.md)).
A plain `async def` resolver decorated with `@fraiseql.mutation` works too, and can
call any function with `db.execute_function(...)`.

**See Also:**

- [Mutation SQL Requirements](../guides/mutation-sql-requirements.md)
- [Error Handling Patterns](../guides/error-handling-patterns.md)

---

### `@fraiseql.input`

Define a GraphQL input type for mutations.

**Example:**

```python
@fraiseql.input
class CreateUserInput:
    """Input for creating a user."""
    name: str
    email: str
    age: int | None = None
```

---

### Authorization Decorators

#### `@requires_auth`

Require authentication for a query/mutation.

```python
from fraiseql.auth import requires_auth

@fraiseql.query
@requires_auth
async def current_user(info) -> User:
    user_context = info.context["user"]
    # user_context is guaranteed to exist
    db = info.context["db"]
    return await db.find_one(
        "v_user", "currentUser", info, mandatory_filters={"id": user_context.user_id}
    )
```

#### `@requires_role`

Require specific role(s).

```python
from fraiseql.auth import requires_role

@fraiseql.query
@requires_role("admin")
async def all_users(info) -> list[User]:
    # Only admin users can call this
    db = info.context["db"]
    return await db.find("v_user", "allUsers", info)
```

#### `@requires_permission`

Require specific permission(s).

```python
from uuid import UUID

from fraiseql.auth import requires_permission

@fraiseql.mutation
@requires_permission("user:delete")
async def delete_user(info, id: UUID) -> bool:
    # Only users with "user:delete" permission
    db = info.context["db"]
    # fn_delete_user(input jsonb, OUT deleted boolean)
    result = await db.execute_function("fn_delete_user", {"id": str(id)})
    return result["deleted"]
```

**See Also:**

- [Authentication Guide](../advanced/authentication.md)

---

## Database API

### `FraiseQLRepository`

Main interface for database operations.

**Methods:**

#### `find(source, field_name, info, **filters)`

Query multiple records.

```python
users = await db.find(
    "v_user",
    "users",
    info,
    where={"status": {"eq": "active"}},
    order_by=[{"created_at": "DESC"}],
    limit=10
)
```

**Parameters:**

- `source`: View/table name
- `field_name`: GraphQL field name
- `info`: GraphQL info object
- `where`: Filter conditions (dict or WhereInput)
- `order_by`: List of `{field: "ASC" | "DESC"}` dicts
- `limit`: Maximum records to return
- `offset`: Records to skip

**Returns:** `list[T]`

---

#### `find_one(source, field_name, info, **filters)`

Query single record.

```python
user = await db.find_one(
    "v_user",
    "user",
    info,
    mandatory_filters={"id": user_id},
)
```

**Returns:** `T | None`

---

#### `execute_function(function_name, params)`

Call PostgreSQL function.

```python
result = await db.execute_function(
    "fn_create_user",
    {"name": "Alice", "email": "alice@example.com"}
)
```

**Returns:** `dict[str, Any]`

---

### Connection Management

`create_fraiseql_app` creates and opens the pool. In a resolver, `db.get_pool()`
returns it (a psycopg `AsyncConnectionPool`):

```python
@fraiseql.query
async def user_emails(info) -> list[str]:
    db = info.context["db"]
    async with db.get_pool().connection() as conn:
        cursor = await conn.execute("SELECT email FROM tb_user ORDER BY email")
        return [row[0] for row in await cursor.fetchall()]
```

Outside the app, `create_db_pool` from `fraiseql.fastapi.app` builds the same kind of
pool (it returns date and time values as text, as fraiseql expects):

```python
from fraiseql.fastapi.app import create_db_pool

pool = await create_db_pool("postgresql://localhost/mydb", min_size=5, max_size=20)
async with pool.connection() as conn:
    cursor = await conn.execute("SELECT email FROM tb_user")
    rows = await cursor.fetchall()
await pool.close()
```

**See Also:**

- [Database API Guide](../core/database-api.md)

---

## Application

### `create_fraiseql_app`

Build the FastAPI application that serves the GraphQL schema.

**Signature** (main parameters):

```python
from fraiseql.fastapi import create_fraiseql_app

def create_fraiseql_app(
    *,
    database_url: str | None = None,
    types: Sequence[type] = (),
    mutations: Sequence[Callable] = (),
    queries: Sequence[Callable] = (),
    config: FraiseQLConfig | None = None,
    auth: Auth0Config | AuthProvider | None = None,
    context_getter: Callable[[Request], Awaitable[dict]] | None = None,
    production: bool = False,
    # ... see the function's docstring for the rest
) -> FastAPI
```

**Example:**

```python
from fastapi.testclient import TestClient

from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users, user],
    mutations=[CreateUser],
)

# Serve it with uvicorn, or execute a query in a test:
with TestClient(app) as client:
    response = client.post("/graphql", json={"query": "{ users { id name } }"})
    print(response.json()["data"]["users"])
```

**See Also:**

- [Quick Reference](../reference/quick-reference.md)
- [Configuration](../core/configuration.md)

---

## Security

### Rate Limiting

`RateLimitMiddleware` (from `fraiseql.security`) limits requests per client; add it
to the app like any Starlette middleware:

```python
from fraiseql.security import RateLimit, RateLimitMiddleware

app = create_fraiseql_app(database_url="...", types=[User], queries=[users])
app.add_middleware(
    RateLimitMiddleware,
    default_limit=RateLimit(requests=60, window=60),  # 60 requests per minute
)
```

A client over the limit gets HTTP 429.

### Query Timeout

```python
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    query_timeout=30,  # seconds: statement_timeout for db.run() and db.execute_function()
)
app = create_fraiseql_app(config=config, types=[User], queries=[users])
```

**See Also:**

- [Security Architecture](../features/security-architecture.md)
- [Production Security](../production/security.md)

---

## Filters

### Filter Operators

All available filter operators for WHERE clauses:

**String Operators:**

```python
where={
    "name": {"eq": "Alice"},              # Equals
    "email": {"contains": "@example"},     # Contains substring
    "name": {"startswith": "Dr."},        # Starts with
    "email": {"endswith": ".com"},         # Ends with
    "status": {"in": ["active", "pending"]}, # In list
    "phone": {"isnull": False}             # Is not null
}
```

**Numeric Operators:**

```python
where={
    "age": {"gte": 18},                    # Greater than or equal
    "price": {"lt": 100.0},                # Less than
    "stock": {"between": [10, 100]}        # Between values
}
```

**Date Operators:**

```python
where={
    "created_at": {"gte": "2024-01-01T00:00:00Z"},
    "updated_at": {"lte": "2024-12-31T23:59:59Z"}
}
```

**Logical Operators:**

```python
where={
    "AND": [
        {"status": {"eq": "active"}},
        {"age": {"gte": 18}}
    ],
    "OR": [
        {"role": {"eq": "admin"}},
        {"role": {"eq": "moderator"}}
    ],
    "NOT": {"status": {"eq": "deleted"}}
}
```

**See Also:**

- [Filter Operators Reference](../advanced/filter-operators.md)
- [Filtering Guide](../guides/filtering.md)

---

## Types

### Mutation results: `@fraiseql.success` / `@fraiseql.error`

A class-based mutation names a success type and an error type; GraphQL exposes them
as a union, and fraiseql picks one from the `status` of the SQL function's
`mutation_response`:

```python
@fraiseql.success
class CreateUserSuccess:
    user: User  # the function's entity, under the field named after its type


@fraiseql.error
class CreateUserError:
    message: str
```

`@fraiseql.success` adds `status`, `message`, `updated_fields` and `id`; `@fraiseql.error`
adds `status`, `message`, `errors` and `code` (an HTTP-style number derived from the
status, such as 409 for `conflict:`). A `status` with an error prefix (`failed:`,
`validation:`, `not_found:`, `conflict:`, ...) selects the error type.

---

### `UserContext`

User context available in authenticated requests.

```python
from fraiseql.auth import UserContext
from uuid import UUID

@dataclass
class UserContext:
    user_id: UUID
    email: str | None
    name: str | None
    roles: list[str]
    permissions: list[str]
    metadata: dict[str, Any]
```

**Methods:**

- `has_role(role: str) -> bool`
- `has_permission(permission: str) -> bool`

---

## Common Patterns

### Pagination

```python
@fraiseql.query
async def users(
    info,
    limit: int = 10,
    offset: int = 0
) -> list[User]:
    db = info.context["db"]
    return await db.find(
        "v_user",
        "users",
        info,
        limit=limit,
        offset=offset,
        order_by=[{"created_at": "DESC"}]
    )
```

### Relationships

```python
@fraiseql.type(sql_source="v_user")
class User:
    id: UUID
    name: str
    posts: list['Post']  # Automatically resolved via v_user.posts

@fraiseql.type(sql_source="v_post")
class Post:
    id: UUID
    title: str
    author: User  # Automatically resolved via v_post.author
```

### Error Handling

Validate in the SQL function and return a failure status; fraiseql returns the error
type of the mutation instead of raising:

```sql
CREATE OR REPLACE FUNCTION create_user(input jsonb)
RETURNS mutation_response AS $$
DECLARE
    new_id uuid;
BEGIN
    IF EXISTS (SELECT 1 FROM tb_user WHERE email = input->>'email') THEN
        RETURN ROW('conflict:email', 'Email already registered', NULL, 'User',
                   NULL, NULL, NULL, NULL)::mutation_response;
    END IF;

    INSERT INTO tb_user (name, email)
    VALUES (input->>'name', input->>'email')
    RETURNING id INTO new_id;

    RETURN ROW('new', 'User created', new_id::text, 'User',
               (SELECT data FROM v_user WHERE id = new_id),
               NULL, NULL, NULL)::mutation_response;
END;
$$ LANGUAGE plpgsql;
```

**See Also:**

- [Error Handling Patterns](../guides/error-handling-patterns.md)

---

## Further Reading

- **[Quick Reference](../reference/quick-reference.md)** - One-page cheatsheet
- **[Database API](../core/database-api.md)** - Complete database guide
- **[Types & Schema](../core/types-and-schema.md)** - Type system deep dive
- **[Recipes Index](../recipes/index.md)** - Copy-paste solutions

---

## Need Help?

- Browse [Recipes & Examples](../recipes/index.md)
- Check [Troubleshooting Guide](../guides/troubleshooting.md)
- Ask in [GitHub Discussions](https://github.com/fraiseql/fraiseql/discussions)

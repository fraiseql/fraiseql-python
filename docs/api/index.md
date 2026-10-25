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
@fraiseql.mutation
async def create_user(info, name: str, email: str) -> MutationResponse[User]:
    """Create a new user."""
    db = info.context["db"]

    result = await db.execute_function(
        "fn_create_user",
        {"name": name, "email": email}
    )

    return MutationResponse.from_db(result)
```

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
    order_by=[("created_at", "DESC")],
    limit=10
)
```

**Parameters:**

- `source`: View/table name
- `field_name`: GraphQL field name
- `info`: GraphQL info object
- `where`: Filter conditions (dict or WhereInput)
- `order_by`: List of (field, direction) tuples
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

```python
from fraiseql.db import create_database_pool

# Create connection pool
pool = await create_database_pool(
    "postgresql://localhost/mydb",
    min_size=5,
    max_size=20
)

# Get connection from pool
async with pool.acquire() as conn:
    result = await conn.fetch("SELECT * FROM users")
```

**See Also:**

- [Database API Guide](../core/database-api.md)

---

## Schema

### `Schema`

Main GraphQL schema class.

**Signature:**

```python
class Schema:
    def __init__(
        self,
        database_url: str,
        types: list[type] | None = None,
        queries: list[Callable] | None = None,
        mutations: list[Callable] | None = None,
        auth_provider: AuthProvider | None = None,
        max_query_complexity: int = 1000,
        query_timeout_seconds: int = 30
    )
```

**Example:**

```python
from fraiseql import Schema

schema = Schema(
    database_url="postgresql://localhost/mydb",
    types=[User, Post, Comment],
    queries=[users, user, posts],
    mutations=[create_user, update_user],
    max_query_complexity=1000
)

# Execute query
result = await schema.execute("""
    {
      users {
        id
        name
      }
    }
""")
```

**See Also:**

- [Quick Reference](../reference/quick-reference.md)

---

## Security

### Rate Limiting

```python
from fraiseql.security import RateLimiter

rate_limiter = RateLimiter(
    requests_per_minute=60,
    burst=10
)

# Use in schema
schema = Schema(
    database_url="...",
    rate_limiter=rate_limiter
)
```

### Query Complexity Analysis

```python
schema = Schema(
    database_url="...",
    max_query_complexity=1000,  # Prevent DoS via complex queries
    query_timeout_seconds=30     # Maximum query execution time
)
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

### `MutationResponse[T]`

Standard mutation response type.

```python
from fraiseql.types import MutationResponse

@fraiseql.mutation
async def create_user(info, ...) -> MutationResponse[User]:
    result = await db.execute_function("fn_create_user", ...)
    return MutationResponse.from_db(result)
```

**Fields:**

- `status`: Status code string (e.g., "created", "validation:error")
- `message`: Human-readable message
- `entity`: The created/updated entity (type `T`)
- `errors`: List of error objects

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
        order_by=[("created_at", "DESC")]
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

```python
@fraiseql.mutation
async def create_user(info, name: str) -> MutationResponse[User]:
    try:
        result = await db.execute_function("fn_create_user", {"name": name})
        return MutationResponse.from_db(result)
    except ValidationError as e:
        return MutationResponse(
            status="validation:error",
            message=str(e),
            errors=[{"code": 422, "message": str(e)}]
        )
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

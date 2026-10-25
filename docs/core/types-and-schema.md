---
title: Types & Schema
description: GraphQL type system, schema building, and Python type mappings
tags:
  - types
  - schema
  - GraphQL
  - Python
  - decorators
---

# Types and Schema

Type system for GraphQL schema definition using Python decorators and dataclasses.

**📍 Navigation**: [← Beginner Path](../tutorials/beginner-path.md) • [Queries & Mutations →](queries-and-mutations.md) • [Database API →](database-api.md)

## @fraiseql.type

**Purpose**: Define GraphQL object types from Python classes

**Signature**:

```python
import fraiseql

@fraiseql.type(
    sql_source: str | None = None,
    jsonb_column: str | None = "data",
    implements: list[type] | None = None,
    resolve_nested: bool = False
)
class TypeName:
    field1: str
    field2: int | None = None
```

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| sql_source | str \| None | None | Database table/view name for automatic query generation |
| jsonb_column | str \| None | "data" | JSONB column name containing type data. Use None for regular column tables |
| implements | list[type] \| None | None | List of GraphQL interface types this type implements |
| resolve_nested | bool | False | If True, resolve nested instances via separate database queries |

**Field Type Mappings**:

| Python Type | GraphQL Type | Notes |
|-------------|--------------|-------|
| str | String! | Non-nullable string |
| str \| None | String | Nullable string |
| int | Int! | 32-bit signed integer |
| float | Float! | Double precision float |
| bool | Boolean! | True/False |
| UUID | ID! | Auto-converted to string |
| datetime | DateTime! | ISO 8601 format |
| date | Date! | YYYY-MM-DD format |
| list[T] | [T!]! | Non-null list of non-null items |
| list[T] \| None | [T!] | Nullable list of non-null items |
| list[T \| None] | [T]! | Non-null list of nullable items |
| Decimal | Decimal! | High precision numbers, serialized as a string |

## Type Mapping Flow

### Python Class to GraphQL Schema

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Python     │───▶│ Type        │───▶│ GraphQL     │───▶│  Client     │
│  Class      │    │ Decorator   │    │  Schema     │    │  Query      │
│             │    │             │    │             │    │             │
│ @type       │    │ @type(      │    │ type User { │    │ { user {    │
│ class User: │    │   sql_      │    │   id: ID!   │    │   id        │
│   id: ID  │    │   source=   │    │   name:     │    │   name      │
│   name: str │    │   "v_user") │    │   String!   │    │ } }         │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

**Type Mapping Process:**

1. **Python Class** with type hints and `@type` decorator
2. **Type Decorator** processes annotations and metadata
3. **GraphQL Schema** generated with proper types and nullability
4. **Client Queries** validated against generated schema


**Examples**:

Basic type without database binding:

```python
import fraiseql
from fraiseql.types import ID
from datetime import datetime

@fraiseql.type
class User:
    id: ID
    email: str
    name: str | None
    created_at: datetime
    is_active: bool = True
    tags: list[str] = []
```

**Generated GraphQL Schema**:

```graphql
type User {
  id: ID!
  email: String!
  name: String
  createdAt: DateTime!
  isActive: Boolean!
  tags: [String!]!
}
```

Type with SQL source for automatic queries:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    email: str
    name: str
```

Type with regular table columns (no JSONB):

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="users", jsonb_column=None)
class User:
    id: ID
    email: str
    name: str
    created_at: datetime
```

Type with custom JSONB column:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="tv_machine", jsonb_column="machine_data")
class Machine:
    id: ID
    identifier: str
    serial_number: str
```

**With Custom Fields** (using @field decorator):

```python
import fraiseql
from fraiseql.types import ID
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import Post

@fraiseql.type
class User:
    id: ID
    first_name: str
    last_name: str

    @fraiseql.field(description="Full display name")
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @fraiseql.field(description="User's posts")
    async def posts(self, info) -> list[Post]:
        db = info.context["db"]
        return await db.find("v_post", where={"user_id": self.id})
```

With nested object resolution:

```python
import fraiseql
from fraiseql.types import ID

# Department will be resolved via separate query
@fraiseql.type(sql_source="departments", resolve_nested=True)
class Department:
    id: ID
    name: str

# Employee with department as a relation
@fraiseql.type(sql_source="employees")
class Employee:
    id: ID
    name: str
    department_id: ID  # Foreign key
    department: Department | None  # Will query departments table
```

With embedded nested objects (default):

```python
import fraiseql
from fraiseql.types import ID

# Department data is embedded in parent's JSONB
@fraiseql.type(sql_source="departments")
class Department:
    id: ID
    name: str

# Employee view includes embedded department in JSONB
@fraiseql.type(sql_source="v_employees_with_dept")
class Employee:
    id: ID
    name: str
    department: Department | None  # Uses embedded JSONB data
```

## Field Documentation

**Purpose**: Add descriptions to GraphQL schema fields for better API documentation and introspection

FraiseQL supports **four ways** to document your GraphQL fields, with automatic extraction in priority order:

### 1. Class Docstring - Google/Sphinx Style (Recommended ⭐)

The most common and Pythonic way to document fields - all documentation in one place:

```python
import fraiseql
from fraiseql.types import ID
from datetime import datetime

@fraiseql.type
class User:
    """A user account in the system.

    Fields:
        id: Unique user identifier
        name: User's full name
        email: User's email address
        created_at: Account creation timestamp
    """
    id: ID
    name: str
    email: str
    created_at: datetime
```

**Generated GraphQL Schema:**

```graphql
"""A user account in the system."""
type User {
  """Unique user identifier."""
  id: ID!

  """User's full name."""
  name: String!

  """User's email address."""
  email: String!

  """Account creation timestamp."""
  createdAt: DateTime!
}
```

**Advantages:**

- ✅ Clean, compact Python code (no blank lines needed)
- ✅ All documentation in one place
- ✅ Standard Google/Sphinx docstring format
- ✅ Familiar to most Python developers
- ✅ Works well with auto-documentation tools

**Use when:**

- Writing most production code (recommended default)
- Following team Python style guides
- Working with code generators
- Documenting many fields at once

### 2. Attribute-Level Docstrings (Advanced)

For detailed, multi-line field documentation:

```python
@fraiseql.type
class Article:
    """A blog article."""

    id: ID
    """
    Unique article identifier.

    Generated automatically when the article is created.
    Cannot be changed after creation.
    """

    title: str
    """
    Article title.

    Should be concise and descriptive.
    Must be unique within the blog.
    Maximum length: 200 characters.
    """

    content: str
    """Article content in markdown format."""
```

**Advantages:**

- ✅ Multi-line descriptions with details
- ✅ IDE hover support on individual fields
- ✅ Good for complex fields needing explanation

**Disadvantages:**

- ❌ Requires blank lines between fields (less compact)
- ❌ Only works for file-based classes (not dynamically created)

**Use when:**

- Individual fields need detailed multi-line explanations
- You want IDE hover to show field-specific docs
- Working with complex domain models

### 3. Inline Comments

Quick, single-line descriptions:

```python
@fraiseql.type
class User:
    id: ID  # Unique user identifier
    name: str  # User's full name
    email: str  # User's email address
```

**Note:** Inline comments have **highest priority** and will override other documentation methods.

### 4. Explicit `fraise_field` (Legacy)

For backward compatibility and special cases:

```python
from fraiseql import fraise_field

@fraiseql.type
class User:
    id: ID
    name: str = fraise_field(description="User's full name")
    email: str = fraise_field(
        description="User's email address",
        graphql_name="emailAddress"
    )
```

**Use when:**

- Need to override GraphQL field name
- Migrating from older FraiseQL versions
- Need other `fraise_field` options (purpose, init, etc.)

### Documentation Priority Order

When multiple documentation methods are used, FraiseQL applies them in this priority:

1. **Inline comments** (highest priority)
2. **Attribute-level docstrings**
3. **Type annotations** (`Annotated[str, "description"]`)
4. **Class docstring** (Google/Sphinx style)
5. **Explicit `fraise_field(description="...")`** (backward compatibility)

**Example with priorities:**

```python
@fraiseql.type
class User:
    """User account.

    Fields:
        name: From class docstring (lowest priority)
        email: From class docstring
    """

    id: ID  # From inline comment (highest priority)

    name: str
    """From attribute docstring (overrides class docstring)."""

    email: str
    # Uses class docstring (no attribute docstring)

    phone: str = fraise_field(description="Explicit description")
```

**Result:**

- `id`: "From inline comment (highest priority)"
- `name`: "From attribute docstring (overrides class docstring)."
- `email`: "From class docstring"
- `phone`: "Explicit description"

### Best Practices

1. **Be consistent** - Pick one style and use it throughout your project
2. **Use class docstrings** (Google/Sphinx style) for most code - clean and compact
3. **Use attribute docstrings** only when fields need detailed multi-line explanations
4. **Keep descriptions concise** - Focus on what, not how
5. **Document required fields** - Especially those without obvious names
6. **Avoid mixing styles** - Stick to one approach per class

### GraphQL Introspection

All field descriptions automatically appear in:

- GraphQL introspection queries
- GraphQL Playground / GraphiQL documentation
- Generated TypeScript/client code
- API documentation tools

**Introspection Example:**

```graphql
query IntrospectUser {
  __type(name: "User") {
    fields {
      name
      description
    }
  }
}
```

**Response:**

```json
{
  "data": {
    "__type": {
      "fields": [
        {
          "name": "id",
          "description": "Unique user identifier."
        },
        {
          "name": "name",
          "description": "User's full name."
        }
      ]
    }
  }
}
```

## @input

**Purpose**: Define GraphQL input types for mutations and queries

**Signature**:

```python
import fraiseql

@fraiseql.input
class InputName:
    field1: str
    field2: int | None = None
```

**Examples**:

Basic input type:

```python
import fraiseql
from fraiseql.types import ID
from datetime import datetime

@fraiseql.type
class User:
    id: ID
    name: str
    role: UserRole

@fraiseql.type
class Order:
    id: ID
    status: OrderStatus
    created_at: datetime
```

Enum with integer values:

```python
@fraiseql.enum
class Priority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4
```

## @interface

**Purpose**: Define GraphQL interface types for polymorphism

**Signature**:

```python
import fraiseql

@fraiseql.interface
class InterfaceName:
    field1: str
    field2: int
```

**Examples**:

Basic Node interface:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.interface
class Node:
    id: ID

@fraiseql.type(implements=[Node])
class User:
    id: ID
    email: str
    name: str

@fraiseql.type(implements=[Node])
class Post:
    id: ID
    title: str
    content: str
```

Interface with computed fields:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.interface
class Timestamped:
    created_at: datetime
    updated_at: datetime

    @fraiseql.field(description="Time since creation")
    def age(self) -> timedelta:
        return datetime.utcnow() - self.created_at

@fraiseql.type(implements=[Timestamped])
class Article:
    id: ID
    title: str
    created_at: datetime
    updated_at: datetime

    @fraiseql.field(description="Time since creation")
    def age(self) -> timedelta:
        return datetime.utcnow() - self.created_at
```

Multiple interface implementation:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.interface
class Searchable:
    search_text: str

@fraiseql.interface
class Taggable:
    tags: list[str]

@fraiseql.type(implements=[Node, Searchable, Taggable])
class Document:
    id: ID
    title: str
    content: str
    tags: list[str]

    @fraiseql.field
    def search_text(self) -> str:
        return f"{self.title} {self.content}"
```

## Scalar Types

**Built-in Scalars**:

| Import | GraphQL Type | Python Type | Format | Example |
|--------|--------------|-------------|--------|---------|
| UUID | ID | UUID | UUID string | "123e4567-..." |
| Date | Date | date | YYYY-MM-DD | "2025-10-09" |
| DateTime | DateTime | datetime | ISO 8601 | "2025-10-09T10:30:00Z" |
| EmailAddress | EmailAddress | str | RFC 5322 | "user@example.com" |
| JSON | JSON | dict/list/Any | JSON value | {"key": "value"} |

**Network Scalars**:

| Import | GraphQL Type | Description | Example |
|--------|--------------|-------------|---------|
| IpAddress | IpAddress | IPv4 or IPv6 address | "192.168.1.1" |
| CIDR | CIDR | CIDR notation network | "192.168.1.0/24" |
| MacAddress | MacAddress | MAC address | "00:1A:2B:3C:4D:5E" |
| Port | Port | Network port number | 8080 |
| Hostname | Hostname | DNS hostname | "api.example.com" |

**Other Scalars**:

| Import | GraphQL Type | Description | Example |
|--------|--------------|-------------|---------|
| LTree | LTree | PostgreSQL ltree path | "top.science.astronomy" |
| DateRange | DateRange | Date range | "[2025-01-01,2025-12-31]" |

**Usage Example**:

```python
import fraiseql

from fraiseql.types import (
    IpAddress,
    CIDR,
    MacAddress,
    Port,
    Hostname,
    LTree
)

@fraiseql.type
class NetworkConfig:
    ip_address: IpAddress
    cidr_block: CIDR
    gateway: IpAddress
    mac_address: MacAddress
    port: Port
    hostname: Hostname

@fraiseql.type
class Category:
    path: LTree  # PostgreSQL ltree for hierarchical data
    name: str
```

## Generic Types

### Connection / Edge / PageInfo (Relay Pagination)

**Purpose**: Cursor-based pagination following Relay specification

**Types**:

```python
import fraiseql

@fraiseql.type
class PageInfo:
    has_next_page: bool
    has_previous_page: bool
    start_cursor: str | None = None
    end_cursor: str | None = None
    total_count: int | None = None

@fraiseql.type
class Edge[T]:
    node: T
    cursor: str

@fraiseql.type
class Connection[T]:
    edges: list[Edge[T]]
    page_info: PageInfo
    total_count: int | None = None
```

**Usage with @connection decorator**:

```python
import fraiseql
from fraiseql.types import Connection
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    name: str
    email: str

@fraiseql.connection(node_type=User)
@fraiseql.query
async def users_connection(
    info,
    first: int | None = None,
    after: str | None = None
) -> Connection[User]:
    pass  # Implementation handled by decorator
```

### PaginatedResponse (Offset Pagination)

**Alias**: `PaginatedResponse = Connection`

**Usage**:

```python
import fraiseql

@fraiseql.query
async def users_paginated(
    info,
    page: int = 1,
    limit: int = 20
) -> Connection[User]:
    db = info.context["db"]
    offset = (page - 1) * limit
    users = await db.find("v_user", limit=limit, offset=offset)
    total = await db.count("v_user")

    # Manual construction
    from fraiseql.types import PageInfo, Edge, Connection

    edges = [Edge(node=user, cursor=str(i)) for i, user in enumerate(users)]
    page_info = PageInfo(
        has_next_page=offset + limit < total,
        has_previous_page=page > 1,
        total_count=total
    )

    return Connection(edges=edges, page_info=page_info, total_count=total)
```

## UNSET Sentinel

**Purpose**: Distinguish between "field not provided" and "field explicitly set to None"

**Import**:

```python
from fraiseql import UNSET
```

**Usage in Input Types**:

```python
import fraiseql
from fraiseql import UNSET
from fraiseql.types import ID

@fraiseql.input
class UpdateUserInput:
    id: ID
    name: str | None = UNSET  # Not provided by default
    email: str | None = UNSET
    bio: str | None = UNSET
```

**Usage in Mutations**:

```python
import fraiseql

@fraiseql.mutation
async def update_user(info, input: UpdateUserInput) -> User:
    db = info.context["db"]
    updates = {"id": str(input.id)}

    # Only include fields that were explicitly provided
    if input.name is not UNSET:
        updates["name"] = input.name  # Could be None (clear) or str (update)
    if input.email is not UNSET:
        updates["email"] = input.email
    if input.bio is not UNSET:
        updates["bio"] = input.bio

    # fn_update_user sets only the keys present in its input: a null clears a column,
    # an absent key leaves it alone. (input.to_dict() builds the same dict: it skips UNSET.)
    await db.execute_function("fn_update_user", updates)
    return await db.find_one("v_user", "updateUser", info, mandatory_filters={"id": input.id})
```

**GraphQL Example**:

```graphql
# Mutation that only updates name (sets it to null)
mutation {
  updateUser(input: {
    id: "123"
    name: null    # Explicitly set to null - will update
    # email not provided - will not update
  }) {
    id
    name
    email
  }
}
```

## Best Practices

**Type Design**:

- Use descriptive names (User, CreateUserInput, UserConnection)
- Separate input types from output types
- Use UNSET for optional update fields
- Define enums for fixed value sets
- Use interfaces for shared behavior

**Field Naming**:

- Use snake_case in Python (auto-converts to camelCase in GraphQL)
- Prefix inputs with operation name (CreateUserInput, UpdateUserInput)
- Suffix connections with Connection (UserConnection)

**Nullability**:

- Make fields non-nullable by default (better type safety)
- Use `| None` only when field can truly be absent
- Use UNSET for "not provided" vs None for "clear this field"

**SQL Source Configuration**:

- Set sql_source for queryable types
- Set jsonb_column=None for regular table columns
- Use jsonb_column="data" (default) for CQRS/JSONB tables
- Use custom jsonb_column for non-standard column names

**Performance**:

- Use resolve_nested=True only for types that need separate database queries
- Default (resolve_nested=False) assumes data is embedded in parent JSONB
- Embedded data is faster (single query) vs nested resolution (multiple queries)

## See Also

- [Queries and Mutations](./queries-and-mutations.md) - Using types in resolvers
- [Decorators Reference](../reference/decorators.md) - Complete decorator API
- [Configuration](./configuration.md) - Type system configuration options

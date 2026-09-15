---
title: Quick Reference
description: One-page cheatsheet for common FraiseQL patterns and commands
tags:
  - quick-reference
  - cheatsheet
  - patterns
  - commands
  - examples
---

# FraiseQL Quick Reference

One-page cheatsheet for common FraiseQL patterns, commands, and advanced type operations.

## 💡 Import Best Practices

**Always use namespaced imports to avoid shadowing Python builtins:**

```python
# ✅ RECOMMENDED (safe, clear)
import fraiseql

@fraiseql.type(sql_source="v_user")
class User: ...

@fraiseql.input
class CreateUserInput: ...
```

**Alternative - explicit imports:**

```python
# ✅ SAFE (explicit names don't shadow builtins)
from fraiseql import fraise_type, fraise_input, query, mutation

@fraise_type(sql_source="v_user")
class User: ...
```

**⚠️ AVOID - Shadows Python builtins:**

```python
# ❌ DANGEROUS - shadows builtin type() and input()
from fraiseql import type, input  # Don't do this!

@type  # Now you can't use Python's type() function!
class User: ...
```

## Essential Commands

```bash
# Database setup
createdb mydb                                    # Create database
psql mydb < schema.sql                          # Load schema
psql mydb -c "\dv v_*"                          # List views
psql mydb -c "\dt tb_*"                         # List tables

# Run application
pip install "fraiseql[all]<2"                   # Install
uvicorn app:app --reload                        # Start server
curl http://localhost:8000/graphql              # Test endpoint

# Development
python -c "import app; print('OK')"             # Test imports
make test                                       # Run tests
```

## Essential Patterns

### Define a Type

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    name: str
    email: str
    posts: list['Post']  # Forward reference for relationships
```

### Query - Get All Items

```python
import fraiseql

@fraiseql.query
async def users(info) -> list[User]:
    """Get all users."""
    db = info.context["db"]
    return await db.find("users")
```

### Query - Get by ID

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.query
async def user(info, id: ID) -> User | None:
    """Get user by ID."""
    db = info.context["db"]
    # field_name auto-inferred from function name "user"
    return await db.find_one("v_user", id=id)
```

### Query - Filter with Where Input Types

```python
import fraiseql
from fraiseql.sql import create_graphql_where_input

# Generate automatic Where input type
UserWhereInput = create_graphql_where_input(User)

@fraiseql.query
async def users(info, where: UserWhereInput | None = None) -> list[User]:
    """Get users with optional filtering."""
    db = info.context["db"]
    return await db.find("users", where=where)
```

### Mutation - Create

```python
import fraiseql

@fraiseql.input
class CreateUserInput:
    name: str
    email: str

@fraiseql.mutation
def create_user(input: CreateUserInput) -> User:
    """Create a new user."""
    pass  # Framework calls fn_create_user
```

### Mutation - Update

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.input
class UpdateUserInput:
    name: str | None = None
    email: str | None = None

@fraiseql.mutation
def update_user(id: ID, input: UpdateUserInput) -> User:
    """Update user."""
    pass  # Framework calls fn_update_user
```

### Mutation - Delete

```python
import fraiseql
from fraiseql.types import ID

class DeleteResult:
    success: bool
    error: str | None

@fraiseql.mutation
def delete_user(id: ID) -> DeleteResult:
    """Delete user."""
    pass  # Framework calls fn_delete_user
```

## Where Input Types & Filtering

FraiseQL automatically generates powerful Where input types for type-safe filtering:

### Automatic Where Input Generation

```python
from fraiseql.sql import create_graphql_where_input

# Generate Where input type for any @type decorated class
UserWhereInput = create_graphql_where_input(User)
PostWhereInput = create_graphql_where_input(Post)

@fraiseql.query
async def users(info, where: UserWhereInput | None = None) -> list[User]:
    db = info.context["db"]
    return await db.find("users", where=where)
```

### Filter Operators by Type

**String Fields:**

```graphql
where: {
  name: { eq: "John", contains: "Jo", startswith: "J" }
  email: { endswith: "@example.com", in: ["a@example.com", "b@example.com"] }
}
```

**Numeric Fields:**

```graphql
where: {
  age: { gt: 18, lte: 65, in: [25, 30, 35] }
  score: { gte: 85.5, lt: 100 }
}
```

**Boolean Fields:**

```graphql
where: {
  isActive: { eq: true }
  isDeleted: { neq: true, isnull: false }
}
```

**Array/List Fields:**

```graphql
where: {
  tags: { contains: "urgent" }  # Array contains this value
  categories: { in: ["work", "personal"] }  # Array intersects with this list
}
```

### Logical Operators

```graphql
# AND - all conditions must be true
where: {
  AND: [
    { age: { gte: 18 } },
    { status: { eq: "active" } }
  ]
}

# OR - any condition must be true
where: {
  OR: [
    { role: { eq: "admin" } },
    { department: { eq: "engineering" } }
  ]
}

# NOT - negate a condition
where: {
  NOT: { isDeleted: { eq: true } }
}

# Complex nested logic
where: {
  AND: [
    { age: { gte: 18 } },
    {
      OR: [
        { role: { eq: "admin" } },
        { department: { eq: "engineering" } }
      ]
    }
  ]
}
```

### Usage in GraphQL

```graphql
query GetFilteredUsers {
  users(where: {
    AND: [
      { age: { gte: 21 } },
      { isActive: { eq: true } },
      { name: { contains: "Smith" } }
    ]
  }) {
    id
    name
    email
    age
  }
}
```

## Type System & Custom Types

All custom types available in `/home/lionel/code/fraiseql/src/fraiseql/types/scalars/`:

```python
from fraiseql.types import (
    IpAddress,      # IPv4/IPv6 - PostgreSQL inet/cidr
    LTree,          # Hierarchical paths - PostgreSQL ltree
    DateRange,      # Date ranges - PostgreSQL daterange
    MacAddress,     # MAC addresses - PostgreSQL macaddr
    Port,           # Network ports (1-65535) - smallint
    CIDR,           # CIDR notation - cidr type
    Date,           # ISO 8601 dates - date
    DateTime,       # ISO 8601 timestamps - timestamp
    EmailAddress,   # Email validation - text
    Hostname,       # DNS hostnames - text
    UUID,           # UUIDs - uuid
    JSON,           # JSON objects - jsonb
)
```

### Type Detection Priority

1. **Explicit type hint** (from @fraise_type decorator)
2. **Field name patterns** (contains "ip_address", "mac", "ltree", "daterange", etc.)
3. **Value heuristics** (IP address patterns, MAC formats, LTree notation, DateRange format)
4. **Default to STRING**

## Advanced Type Operators

### IP Address Operations (NetworkOperatorStrategy)

```python
# Basic
"eq", "neq", "in", "notin", "nin"

# Network operations
"inSubnet",     # IP is in CIDR subnet
"inRange",      # IP in range {"from": "...", "to": "..."}
"isPrivate",    # RFC 1918 private
"isPublic",     # Non-private
"isIPv4",       # IPv4 only
"isIPv6",       # IPv6 only

# Classification (RFC-based)
"isLoopback",       # 127.0.0.0/8, ::1
"isLinkLocal",      # 169.254.0.0/16, fe80::/10
"isMulticast",      # 224.0.0.0/4, ff00::/8
"isDocumentation",  # RFC 3849/5737
"isCarrierGrade",   # RFC 6598 (100.64.0.0/10)
```

### LTree Hierarchical Paths (LTreeOperatorStrategy)

```python
# Basic
"eq", "neq", "in", "notin"

# Hierarchical
"ancestor_of",     # path1 @> path2
"descendant_of",   # path1 <@ path2

# Pattern matching
"matches_lquery",      # path ~ lquery
"matches_ltxtquery"    # path ? ltxtquery

# RESTRICTED (throws error)
"contains", "startswith", "endswith"
```

### DateRange Operations (DateRangeOperatorStrategy)

```python
# Basic
"eq", "neq", "in", "notin"

# Range relationships
"contains_date",   # range @> date
"overlaps",        # range1 && range2
"adjacent",        # range1 -|- range2
"strictly_left",   # range1 << range2
"strictly_right",  # range1 >> range2
"not_left",        # range1 &> range2
"not_right"        # range1 &< range2

# RESTRICTED (throws error)
"contains", "startswith", "endswith"
```

### Other Type Operations

**MAC Address (MacAddressOperatorStrategy):**

```python
"eq", "neq", "in", "notin", "isnull"
```

**Generic Types (ComparisonOperatorStrategy):**

```python
"eq", "neq", "gt", "gte", "lt", "lte"
```

**String Operations (PatternMatchingStrategy):**

```python
"matches",      # Regex pattern
"startswith",   # LIKE 'prefix%'
"contains",     # LIKE '%substr%'
"endswith"      # LIKE '%suffix'
```

**List Operations (ListOperatorStrategy):**

```python
"in",   # Value in list
"notin" # Value not in list
```

**All Types:**

```python
"isnull"  # IS NULL / IS NOT NULL
```

## GraphQL Query Examples

### Get all items

```graphql
query {
  users {
    id
    name
    email
  }
}
```

### Get by ID

```graphql
query {
  user(id: "123e4567-e89b-12d3-a456-426614174000") {
    name
    email
  }
}
```

### Filter results

```graphql
query {
  usersByStatus(status: "active") {
    id
    name
  }
}
```

### Create item

```graphql
mutation {
  createUser(input: { name: "Alice", email: "alice@example.com" }) {
    id
    name
    email
  }
}
```

### Update item

```graphql
mutation {
  updateUser(
    id: "123e4567-e89b-12d3-a456-426614174000"
    input: { name: "Alice Smith" }
  ) {
    id
    name
    email
  }
}
```

### Delete item

```graphql
mutation {
  deleteUser(id: "123e4567-e89b-12d3-a456-426614174000") {
    success
    error
  }
}
```

## PostgreSQL Patterns

### Table (Write Model)

```sql
-- tb_user - Write operations (trinity pattern)
CREATE TABLE tb_user (
    pk_user INT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,  -- Internal only
    id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),         -- Public API
    identifier TEXT UNIQUE,                                     -- Optional human-readable
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### View (Read Model)

```sql
-- v_user - Read operations (uses public id, not pk_user)
CREATE VIEW v_user AS
SELECT
    jsonb_build_object(
        'id', id,              -- Use public UUID, not internal pk_user
        'name', name,
        'email', email,
        'status', status,
        'createdAt', created_at,
        'updatedAt', updated_at
    ) as data
FROM tb_user
WHERE status != 'deleted';
```

### Function (Business Logic)

See [canonical fn_create_user()](../examples/canonical-examples.md#create-user-function) for complete example with validation.

### Trigger (Auto-updates)

```sql
-- Auto-update updated_at
CREATE OR REPLACE FUNCTION fn_update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_user_updated_at
    BEFORE UPDATE ON tb_user
    FOR EACH ROW
    EXECUTE FUNCTION fn_update_updated_at();
```

## FastAPI Integration

### Basic App

```python
from fastapi import FastAPI
from fraiseql.fastapi import FraiseQLRouter
from fraiseql.db import FraiseQLRepository
import asyncpg

# Database connection
pool = await asyncpg.create_pool("postgresql://user:pass@localhost/mydb")
repo = FraiseQLRepository(pool)

# FastAPI app
app = FastAPI()
router = FraiseQLRouter(repo=repo, schema=fraiseql.build_schema())
app.include_router(router, prefix="/graphql")
```

### With Custom Context

```python
from fraiseql.fastapi import FraiseQLRouter

# Add custom context
router = FraiseQLRouter(
    repo=repo,
    schema=fraiseql.build_schema(),
    context={"user_id": "current_user"}  # Available in resolvers
)
```

## File Structure

```
my-api/
├── app.py              # Main application
├── db/
│   ├── schema.sql     # Database schema
│   └── migrations/    # Schema changes
├── types.py           # GraphQL types
├── resolvers.py       # Queries & mutations
└── config.py          # Configuration
```

## Import Reference

```python
# Core decorators
import fraiseql

# Database
from fraiseql.db import FraiseQLRepository

# FastAPI integration
from fraiseql.fastapi import FraiseQLRouter

# Types
from fraiseql.types import ID
from datetime import datetime
```

## Need More Help?

- [First Hour Guide](../getting-started/first-hour.md) - Progressive tutorial
- [Troubleshooting](../guides/troubleshooting.md) - Common issues
- [Understanding FraiseQL](../guides/understanding-fraiseql.md) - Architecture overview
- [Examples](../../examples/) - Working applications

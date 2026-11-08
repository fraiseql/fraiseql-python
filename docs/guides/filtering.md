---
title: Filtering & Querying Guide
description: Complete guide to filtering data in FraiseQL with WHERE clauses, nested filters, and logical operators
tags:
  - filtering
  - queries
  - where clause
  - dict-based filtering
  - WhereType
  - operators
---

# Filtering Guide

> **Choose the right filtering approach for your use case**

FraiseQL provides powerful, flexible filtering capabilities for both GraphQL queries and programmatic data access. This guide helps you choose the right approach and get started quickly.

## Quick Start - Complete Example

```python
"""
Complete runnable example showing FraiseQL filtering.

Prerequisites:
- PostgreSQL with a v_user view (id, data JSONB)
- FraiseQL installed: pip install "fraiseql<2"
"""

from datetime import datetime
from uuid import UUID

from fastapi.testclient import TestClient

import fraiseql
from fraiseql.fastapi import create_fraiseql_app


# 1. Define your GraphQL type
@fraiseql.type(sql_source="v_user")
class User:
    id: UUID
    name: str
    email: str
    status: str
    is_verified: bool
    created_at: datetime


# 2. Create a filtered query resolver
@fraiseql.query
async def active_verified_users(info) -> list[User]:
    """Get all active, verified users created since 2024."""
    db = info.context["db"]
    return await db.find(
        "v_user",
        "activeVerifiedUsers",
        info,
        where={
            "status": {"eq": "active"},
            "is_verified": {"eq": True},
            "created_at": {"gte": "2024-01-01T00:00:00Z"},
        },
    )


# 3. Serve it, and run the query
app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[active_verified_users],
)

if __name__ == "__main__":
    query = "{ activeVerifiedUsers { id name email createdAt } }"
    with TestClient(app) as client:
        result = client.post("/graphql", json={"query": query}).json()

    if "errors" in result:
        print(f"❌ Errors: {result['errors']}")
    else:
        users = result["data"]["activeVerifiedUsers"]
        print(f"✅ Found {len(users)} users")
        for user in users:
            print(f"  - {user['name']} ({user['email']})")
```

**Expected Output:**

```
✅ Found 2 users
  - Alice Johnson (alice@example.com)
  - Bob Smith (bob@example.com)
```

A list query also gets a `where` argument of its own (`UserWhereInput`), so clients
can filter without a resolver of yours (see [Where Input Types](../advanced/where-input-types.md)).

---

## Quick Decision

| Use Case | Syntax | Link |
|----------|--------|------|
| Static queries with IDE autocomplete | WhereType | [WhereType Guide](../advanced/where-input-types.md) |
| Dynamic/runtime-built filters | Dict-based | [Dict-Based Syntax](#dict-based-filtering) |
| Need operator reference | Both | [Filter Operators](../advanced/filter-operators.md) |
| Side-by-side comparison | Both | [Syntax Comparison](../reference/where-clause-syntax-comparison.md) |
| Real-world patterns | Both | [Advanced Examples](../examples/advanced-filtering.md) |

---

## WhereType Syntax (Recommended for Static Queries)

WhereType provides type-safe filtering with full IDE autocomplete support. Use this when your filter structure is known at development time.

```python
import fraiseql
from fraiseql.sql import BooleanFilter, StringFilter, create_graphql_where_input

UserWhereInput = create_graphql_where_input(User)


@fraiseql.query
async def active_users(info) -> list[User]:
    db = info.context["db"]
    return await db.find(
        "v_user",
        "activeUsers",
        info,
        where=UserWhereInput(
            status=StringFilter(eq="active"),
            is_verified=BooleanFilter(eq=True),
        ),
    )
```

**Benefits:**

- Full IDE autocomplete and type checking
- Type-checker error detection
- Self-documenting code

For complete documentation: **[Where Input Types Guide](../advanced/where-input-types.md)**

---

## Dict-Based Filtering

Dict-based filters are ideal for dynamic, runtime-built queries. Use this when filter criteria come from user input or configuration.

```python
@fraiseql.query
async def search_users(info, status: str | None = None, verified_only: bool = False) -> list[User]:
    where = {}
    if status:
        where["status"] = {"eq": status}
    if verified_only:
        where["is_verified"] = {"eq": True}
    db = info.context["db"]
    return await db.find("v_user", "searchUsers", info, where=where or None)
```

### Simple Filter Example

```python
where_dict = {
    "status": {"eq": "active"},
    "created_at": {"gte": "2024-01-01T00:00:00Z"}
}
results = await db.find("v_user", where=where_dict)
```

### Nested Object Filtering

Filter on properties of related objects stored in JSONB:

```python
where_dict = {
    "status": {"eq": "active"},
    "device": {
        "is_active": {"eq": True},
        "name": {"contains": "router"}
    }
}
results = await db.find("v_assignment", where=where_dict)
```

**Generated SQL:**

```sql
SELECT "data"::text FROM "v_assignment"
WHERE "data" ->> 'status' = $1
  AND "data" -> 'device' ->> 'is_active' = $2
  AND "data" -> 'device' ->> 'name' LIKE $3  -- contains is case-sensitive; icontains uses ILIKE
```

### CamelCase Support

Dict-based filters automatically convert GraphQL-style camelCase to database snake_case:

```python
# GraphQL-style input
where_dict = {"device": {"isActive": {"eq": True}}}

# Automatically converts to:
# data->'device'->>'is_active' = 'true'
```

### Mixed FK + JSONB Filtering

Filter by both foreign key relationship and JSONB properties:

```python
where_dict = {
    "device": {
        "id": {"eq": device_uuid},     # FK: device_id = 'uuid'
        "is_active": {"eq": True}      # JSONB: data->'device'->>'is_active'
    }
}
```

---

## Nested Array Filtering

FraiseQL supports filtering nested array elements in GraphQL queries with full AND/OR/NOT logical operator support.

### Enable Where Filtering on Fields

```python
import fraiseql
from fraiseql.fields import fraise_field
from fraiseql.types import ID

@fraiseql.type(sql_source="v_network", jsonb_column="data")
class NetworkConfiguration:
    id: ID
    name: str
    print_servers: list[PrintServer] = fraise_field(
        default_factory=list,
        supports_where_filtering=True,
        nested_where_type=PrintServer,
        description="Network print servers with optional filtering"
    )
```

### Query with Complex Filters

```graphql
query {
  network(id: "123e4567-e89b-12d3-a456-426614174000") {
    name
    printServers(where: {
      AND: [
        { operatingSystem: { in: ["Linux", "Windows"] } }
        { OR: [
            { nTotalAllocations: { gte: 100 } }
            { hostname: { contains: "critical" } }
          ]
        }
        { NOT: { ipAddress: { isnull: true } } }
      ]
    }) {
      hostname
      ipAddress
      operatingSystem
    }
  }
}
```

### Logical Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `AND` | All conditions must be true | `AND: [{ status: { eq: "active" } }, { age: { gte: 18 } }]` |
| `OR` | Any condition can be true | `OR: [{ role: { eq: "admin" } }, { role: { eq: "moderator" } }]` |
| `NOT` | Inverts the condition | `NOT: { status: { eq: "deleted" } }` |

**Unlimited nesting depth** - Combine operators freely for complex logic.

---

## Common Filter Operators

### String Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `eq` | Equals | `{"name": {"eq": "Alice"}}` |
| `neq` | Not equals | `{"status": {"neq": "deleted"}}` |
| `contains` | Contains substring | `{"email": {"contains": "@example"}}` |
| `startswith` | Starts with | `{"name": {"startswith": "Dr."}}` |
| `endswith` | Ends with | `{"email": {"endswith": ".org"}}` |
| `in` | In list | `{"role": {"in": ["admin", "mod"]}}` |
| `isnull` | Is null check | `{"phone": {"isnull": true}}` |

### Numeric Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `eq`, `neq` | Equals, not equals | `{"age": {"eq": 25}}` |
| `gt`, `gte` | Greater than (or equal) | `{"price": {"gte": 10.0}}` |
| `lt`, `lte` | Less than (or equal) | `{"stock": {"lt": 100}}` |
| `in`, `nin` | In/not in list | `{"status_code": {"in": [200, 201]}}` |

For the complete operator reference: **[Filter Operators](../advanced/filter-operators.md)**

---

## Performance Tips

### Index Strategy

For JSONB nested filtering, create appropriate indexes:

```sql
-- Basic GIN index for JSONB column
CREATE INDEX idx_table_data ON table_name USING gin (data);

-- Path-specific index for frequently filtered fields
CREATE INDEX idx_assignments_device_active
ON assignments USING gin ((data->'device'->'is_active'));
```

### Performance Characteristics

| Query Type | Typical Latency |
|------------|-----------------|
| Simple filter with index | < 2ms |
| Multiple nested fields | < 5ms |
| Complex nested queries | < 10ms |

### Nested Array Performance

For nested array filtering (client-side):

- Efficient for arrays with < 1000 items
- No N+1 queries - filtering happens after fetch
- For larger arrays, consider database-level filtering

---

## Troubleshooting

### Where Parameter Not Available

Make sure you've set both required parameters:

```python
field_name: list[Type] = fraise_field(
    default_factory=list,
    supports_where_filtering=True,  # Required!
    nested_where_type=Type          # Required!
)
```

### Nested Filters Not Working

A nested filter follows the JSONB path of each level, as deep as the document goes:
`{"device": {"location": {"address": {"city": {"eq": "Seattle"}}}}}` filters on
`data -> 'device' -> 'location' -> 'address' ->> 'city'`. Check that the keys of the
view's JSONB are snake_case (`is_active`, not `isActive`): the filter looks the
snake_case key up. An unknown operator raises `ValueError` naming the supported
ones, and an empty nested filter (`{"device": {}}`) raises too.

---

## Next Steps

- **[Filter Operators Reference](../advanced/filter-operators.md)** - Complete operator documentation
- **[WhereType Deep Dive](../advanced/where-input-types.md)** - Type-safe filtering patterns
- **[Syntax Comparison](../reference/where-clause-syntax-comparison.md)** - WhereType vs Dict side-by-side
- **[Advanced Examples](../examples/advanced-filtering.md)** - Real-world filtering patterns

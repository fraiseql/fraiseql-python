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
- PostgreSQL with a users table/view
- FraiseQL installed: pip install "fraiseql<2"
"""

import asyncio
from datetime import datetime
from uuid import UUID
import fraiseql
from fraiseql.filters import StringFilter, BooleanFilter, DateTimeFilter

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
    """Get all active, verified users created after 2024."""
    db = info.context["db"]
    repo = fraiseql.FraiseQLRepository(db)

    return await repo.find(
        "v_user",
        where={
            "status": {"eq": "active"},
            "is_verified": {"eq": True},
            "created_at": {"gte": "2024-01-01T00:00:00Z"}
        }
    )

# 3. Execute the query
async def main():
    schema = fraiseql.Schema("postgresql://localhost/mydb")

    query = """
    {
      activeVerifiedUsers {
        id
        name
        email
        createdAt
      }
    }
    """

    result = await schema.execute(query)

    if result.errors:
        print(f"❌ Errors: {result.errors}")
    else:
        print(f"✅ Found {len(result.data['activeVerifiedUsers'])} users")
        for user in result.data['activeVerifiedUsers']:
            print(f"  - {user['name']} ({user['email']})")

if __name__ == "__main__":
    asyncio.run(main())
```

**Expected Output:**

```
✅ Found 3 users
  - Alice Johnson (alice@example.com)
  - Bob Smith (bob@example.com)
  - Carol White (carol@example.com)
```

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
from fraiseql.filters import StringFilter, BooleanFilter

@fraiseql.query
async def active_users(info) -> list[User]:
    return await repo.find(
        "v_user",
        where=UserWhere(
            status=StringFilter(eq="active"),
            is_verified=BooleanFilter(eq=True)
        )
    )
```

**Benefits:**

- Full IDE autocomplete and type checking
- Compile-time error detection
- Self-documenting code

For complete documentation: **[Where Input Types Guide](../advanced/where-input-types.md)**

---

## Dict-Based Filtering

Dict-based filters are ideal for dynamic, runtime-built queries. Use this when filter criteria come from user input or configuration.

```python
@fraiseql.query
async def search_users(info, filters: dict) -> list[User]:
    return await repo.find("v_user", where=filters)

# Usage: {"status": {"eq": "active"}, "age": {"gte": 18}}
```

### Simple Filter Example

```python
where_dict = {
    "status": {"eq": "active"},
    "created_at": {"gte": "2024-01-01T00:00:00Z"}
}
results = await repo.find("v_user", where=where_dict)
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
results = await repo.find("assignments", where=where_dict)
```

**Generated SQL:**

```sql
SELECT * FROM assignments
WHERE data->>'status' = 'active'
  AND data->'device'->>'is_active' = 'true'
  AND data->'device'->>'name' ILIKE '%router%'  -- icontains operator (case-insensitive)
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

Dict-based filters support 2-level nesting only:

```python
# ✅ Supported: 2 levels
{"device": {"location": {"eq": "Seattle"}}}

# ❌ Not supported: 3+ levels
{"device": {"location": {"address": {"city": {"eq": "Seattle"}}}}}
```

---

## Next Steps

- **[Filter Operators Reference](../advanced/filter-operators.md)** - Complete operator documentation
- **[WhereType Deep Dive](../advanced/where-input-types.md)** - Type-safe filtering patterns
- **[Syntax Comparison](../reference/where-clause-syntax-comparison.md)** - WhereType vs Dict side-by-side
- **[Advanced Examples](../examples/advanced-filtering.md)** - Real-world filtering patterns

# Nested Array Where Filtering in FraiseQL v1.0+

## Overview

FraiseQL provides comprehensive nested array where filtering with complete AND/OR/NOT logical operator support. This feature enables sophisticated GraphQL queries to filter nested array elements based on their properties using intuitive WhereInput types.

## Features

- ✅ **Complete Logical Operators** - Full AND/OR/NOT support with unlimited nesting depth
- ✅ **All Field Operators** - equals, contains, gte, isnull, and more
- ✅ **Type Safe** - Full TypeScript/Python type safety with generated WhereInput types
- ✅ **Performance Optimized** - Client-side filtering with efficient evaluation

## Quick Start

### 1. Enable Where Filtering on Fields

To enable where filtering on a nested array field, use the `fraise_field` function with the `supports_where_filtering` and `nested_where_type` parameters:

```python
import fraiseql
from fraiseql.fields import fraise_field
from fraiseql.types import ID
from typing import Optional

@fraiseql.type
class PrintServer:
    id: ID
    hostname: str
    ip_address: Optional[str] = None
    operating_system: str
    n_total_allocations: int = 0

@fraiseql.type(sql_source="v_network", jsonb_column="data")
class NetworkConfiguration:
    id: ID
    name: str
    # Enable where filtering on this field
    print_servers: list[PrintServer] = fraise_field(
        default_factory=list,
        supports_where_filtering=True,
        nested_where_type=PrintServer,
        description="Network print servers with optional filtering"
    )
```

### 2. Generated GraphQL Schema

FraiseQL automatically generates the WhereInput types:

```graphql
type NetworkConfiguration {
  id: ID!
  name: String!
  printServers(where: PrintServerWhereInput): [PrintServer!]!
}

input PrintServerWhereInput {
  # Field operators
  hostname: StringWhereInput
  ipAddress: StringWhereInput
  operatingSystem: StringWhereInput
  nTotalAllocations: IntWhereInput

  # Logical operators
  AND: [PrintServerWhereInput!]  # All conditions must be true
  OR: [PrintServerWhereInput!]   # Any condition can be true
  NOT: PrintServerWhereInput     # Invert condition result
}

input StringWhereInput {
  eq: String
  neq: String
  in: [String!]
  nin: [String!]
  contains: String
  startswith: String
  endswith: String
  isnull: Boolean
}

input IntWhereInput {
  eq: Int
  neq: Int
  gt: Int
  gte: Int
  lt: Int
  lte: Int
  in: [Int!]
  nin: [Int!]
  isnull: Boolean
}
```

### 3. Query with Complex Filters

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
      nTotalAllocations
    }
  }
}
```

## Complete Example

```python
import fraiseql
from fraiseql.fields import fraise_field
from fraiseql.types import ID
from datetime import datetime
from typing import Optional
from enum import Enum

# Define enums
@fraiseql.enum
class ServerStatus(str, Enum):
    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    OFFLINE = "offline"

# Define nested types
@fraiseql.type
class Server:
    id: ID
    hostname: str
    ip_address: Optional[str] = None
    status: ServerStatus = ServerStatus.ACTIVE
    last_check: datetime
    cpu_usage: float
    memory_gb: int

@fraiseql.type(sql_source="v_datacenter", jsonb_column="data")
class Datacenter:
    id: ID
    name: str
    location: str

    # Enable where filtering
    servers: list[Server] = fraise_field(
        default_factory=list,
        supports_where_filtering=True,
        nested_where_type=Server,
        description="Servers in this datacenter"
    )

# Define query
@fraiseql.query
async def datacenter(id: ID) -> Datacenter:
    """Get datacenter by ID."""
    # Your implementation here
    pass
```

Query example:

```graphql
query {
  datacenter(id: "...") {
    name
    location
    # Filter servers with complex conditions
    servers(where: {
      AND: [
        { status: { eq: "active" } }
        { cpuUsage: { lt: 80.0 } }
        { memoryGb: { gte: 16 } }
        { NOT: { ipAddress: { isnull: true } } }
      ]
    }) {
      hostname
      ipAddress
      status
      cpuUsage
      memoryGb
    }
  }
}
```

## Logical Operators

### AND

All conditions must be true:

```graphql
where: {
  AND: [
    { hostname: { contains: "prod" } }
    { status: { eq: "active" } }
  ]
}
```

### OR

At least one condition must be true:

```graphql
where: {
  OR: [
    { cpuUsage: { gte: 90 } }
    { memoryGb: { lte: 4 } }
  ]
}
```

### NOT

Inverts the condition:

```graphql
where: {
  NOT: { status: { eq: "offline" } }
}
```

### Complex Nesting

You can combine all operators with unlimited depth:

```graphql
where: {
  AND: [
    { status: { eq: "active" } }
    {
      OR: [
        { cpuUsage: { gte: 90 } }
        {
          AND: [
            { memoryGb: { lte: 4 } }
            { hostname: { contains: "critical" } }
          ]
        }
      ]
    }
    { NOT: { ipAddress: { isnull: true } } }
  ]
}
```

## Field Operators

The elements are filtered in Python, after the row is read, with the operators
below. An enum field takes the enum's values (`{ status: { eq: "active" } }`). The
filter types offer more operators than these (`ilike`, `matches`...); one outside
these lists is a GraphQL error naming the supported ones, rather than a filter
that matches every element.

### String Operators

- `eq`: Equals
- `neq`: Not equals
- `contains`: Contains substring
- `startswith`: Starts with prefix
- `endswith`: Ends with suffix
- `in`: Value is in list
- `nin`: Value is not in list
- `isnull`: Field is null/not null

### Numeric Operators (Int, Float, Decimal)

- `eq`: Equals
- `neq`: Not equals
- `gt`: Greater than
- `gte`: Greater than or equal
- `lt`: Less than
- `lte`: Less than or equal
- `in`: Value is in list
- `nin`: Value is not in list
- `isnull`: Field is null/not null

### Boolean Operators

- `eq`: Equals
- `neq`: Not equals
- `isnull`: Field is null/not null

### UUID/Date/DateTime Operators

- `eq`: Equals
- `neq`: Not equals
- `gt`: Greater than
- `gte`: Greater than or equal
- `lt`: Less than
- `lte`: Less than or equal
- `in`: Value is in list
- `nin`: Value is not in list
- `isnull`: Field is null/not null

## Performance Considerations

FraiseQL's nested array where filtering is implemented efficiently:

1. **Client-Side Filtering**: Filtering happens after data is fetched from the database
2. **Efficient Evaluation**: The filter logic is optimized for quick evaluation
3. **Lazy Evaluation**: Filters are only applied when the field is requested
4. **No N+1 Queries**: Filtering doesn't trigger additional database queries

For very large arrays (1000+ items), consider:

- Adding database-level filtering in your SQL views
- Using pagination
- Implementing cursor-based pagination for large result sets

## Common Patterns

### Filter Active Items

```graphql
items(where: { status: { eq: "active" } })
```

### Search by Name

```graphql
users(where: { name: { contains: "john" } })
```

### Range Queries

```graphql
products(where: {
  AND: [
    { price: { gte: 10.0 } }
    { price: { lte: 100.0 } }
  ]
})
```

### Exclude Nulls

```graphql
servers(where: { ipAddress: { isnull: false } })
```

### Multiple Options

```graphql
servers(where: {
  status: { in: ["active", "maintenance"] }
})
```

## Troubleshooting

### Where Parameter Not Available

**Problem**: The `where` parameter doesn't appear on your field.

**Solution**: Make sure you've set both `supports_where_filtering=True` and `nested_where_type=YourType` on the field:

```python
field_name: list[Type] = fraise_field(
    default_factory=list,
    supports_where_filtering=True,  # Required!
    nested_where_type=Type          # Required!
)
```

### WhereInput Type Not Generated

**Problem**: The WhereInput type doesn't exist in your schema.

**Solution**: The WhereInput type is automatically generated from the `nested_where_type`. Ensure:

1. The nested type is decorated with `@type`
2. The nested type has properly typed fields
3. The schema is being rebuilt after your changes

### Filters Not Working

**Problem**: Filters are applied but don't filter correctly.

**Solution**: Check:

1. Field names match exactly (case-sensitive)
2. Types match (string vs int vs UUID, etc.)
3. Enum values are correct (if using enums)
4. Data exists in the parent object before filtering

## Best Practices

1. **Use Type Hints**: Always properly type your fields for accurate WhereInput generation
2. **Document Fields**: Add descriptions to help API consumers understand filtering options
3. **Test Filters**: Write tests to verify complex filter logic works as expected
4. **Consider Performance**: For large arrays, evaluate if database-level filtering is more appropriate
5. **Use Enums**: Enums provide type-safe filtering for categorical data

---

**Next Steps:**

- [See the end-to-end test](../../tests/test_end_to_end_nested_array_where.py) for complete examples
- [Check logical operators test](../../tests/test_nested_array_logical_operators.py) for complex filter patterns
- [Review the schema builder](../../src/fraiseql/core/graphql_type.py) to understand internals

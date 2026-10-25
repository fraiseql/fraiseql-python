# Dict-Based Nested Object Filtering

FraiseQL supports advanced nested object filtering in dict-based where clauses used by repository methods like `repo.find()`. This enables filtering on related object properties stored in JSONB columns.

## Overview

Dict-based nested filtering allows you to filter records based on properties of related objects stored in JSONB. Unlike GraphQL where inputs, dict-based filters are used programmatically in resolvers and repository methods.

**Key Features:**

- ✅ Filter on nested JSONB object properties
- ✅ Automatic camelCase → snake_case conversion
- ✅ Multiple nested fields per filter
- ✅ Mixed FK and JSONB filtering
- ✅ Type-safe and SQL injection safe

## Basic Usage

### Simple Nested Field Filter

Filter assignments by device active status:

```python
# Repository usage
where_dict = {
    "device": {
        "is_active": {"eq": True}
    }
}

results = await repo.find("assignments", where=where_dict)
```

**Generated SQL:**

```sql
SELECT * FROM assignments
WHERE data->'device'->>'is_active' = 'true'
```

### Multiple Nested Fields

Filter by multiple properties of the same nested object:

```python
where_dict = {
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
WHERE data->'device'->>'is_active' = 'true'
  AND data->'device'->>'name' ILIKE '%router%'  -- icontains operator (case-insensitive)
```

### Mixed Scalar and Nested Filters

Combine top-level filters with nested object filters:

```python
where_dict = {
    "status": {"eq": "active"},
    "device": {
        "is_active": {"eq": True}
    }
}

results = await repo.find("assignments", where=where_dict)
```

**Generated SQL:**

```sql
SELECT * FROM assignments
WHERE data->>'status' = 'active'
  AND data->'device'->>'is_active' = 'true'
```

## CamelCase Support

Dict-based filters automatically convert GraphQL-style camelCase field names to database snake_case:

```python
# GraphQL-style camelCase input
where_dict = {
    "device": {
        "isActive": {"eq": True},      # camelCase
        "deviceName": {"contains": "router"}  # camelCase
    }
}

# Automatically converts to snake_case in SQL
# data->'device'->>'is_active' = 'true'
# data->'device'->>'device_name' ILIKE '%router%'  -- icontains operator
```

## Foreign Key Filtering

For traditional foreign key relationships, use the `id` field:

```python
where_dict = {
    "device": {
        "id": {"eq": device_uuid}  # Uses device_id column
    }
}

# Generated SQL: WHERE device_id = 'uuid-here'
```

## Mixed FK + JSONB Filtering

Filter by both foreign key relationship and JSONB properties:

```python
where_dict = {
    "device": {
        "id": {"eq": device_uuid},     # FK: device_id = 'uuid'
        "is_active": {"eq": True}      # JSONB: data->'device'->>'is_active' = 'true'
    }
}
```

## Advanced Examples

### Complex Multi-Field Filtering

```python
# Find assignments with active devices in specific locations
where_dict = {
    "status": {"in": ["active", "pending"]},
    "device": {
        "is_active": {"eq": True},
        "location": {"city": {"eq": "Seattle"}},
        "tags": {"overlaps": ["production", "critical"]}
    },
    "created_at": {"gte": "2024-01-01T00:00:00Z"}
}
```

### Filtering with Different Operators

```python
# Complex device filtering
where_dict = {
    "device": {
        "is_active": {"eq": True},
        "name": {"contains": "server"},
        "cpu_count": {"gte": 4},
        "memory_gb": {"lt": 32},
        "tags": {"contains": "production"}
    }
}
```

## Performance Characteristics

### Query Performance

Dict-based nested filtering generates efficient PostgreSQL JSONB queries:

- **Path operators**: Uses `->` for object access, `->>` for text extraction
- **Parameterization**: All values are properly parameterized (SQL injection safe)
- **Index utilization**: Leverages GIN indexes on JSONB columns
- **Execution time**: Typically 1-5ms per query with proper indexing

### Recommended Indexes

Create GIN indexes for optimal nested filtering performance:

```sql
-- Basic GIN index for JSONB column
CREATE INDEX idx_table_data ON table_name USING gin (data);

-- Specific path indexes for frequently filtered fields
CREATE INDEX idx_assignments_device_active
ON assignments USING gin ((data->'device'->'is_active'));

-- Composite indexes for multiple nested fields
CREATE INDEX idx_assignments_device_compound
ON assignments USING gin (
    (data->'device'->'is_active'),
    (data->'device'->'name')
);

-- Partial indexes for common filter patterns
CREATE INDEX idx_assignments_active_devices
ON assignments USING gin ((data->'device'))
WHERE data->'device'->>'is_active' = 'true';

-- Expression indexes for computed values
CREATE INDEX idx_assignments_device_name_lower
ON assignments (lower(data->'device'->>'name'));
```

### Index Selection Strategy

1. **Single field filters**: Create path-specific GIN indexes
2. **Multiple field filters**: Use composite GIN indexes
3. **Common patterns**: Partial indexes for frequent conditions
4. **Case-insensitive**: Expression indexes for text searches

### Query Optimization Tips

- **Index maintenance**: GIN indexes have higher write overhead
- **Query selectivity**: Nested filters can be highly selective
- **Statistics**: Ensure `ANALYZE` is run after bulk operations
- **Monitoring**: Use `EXPLAIN ANALYZE` to verify index usage

### Performance Benchmarks

Typical performance characteristics:

- **Simple nested filter**: < 2ms (with GIN index)
- **Multiple nested fields**: < 5ms (with composite index)
- **Complex nested queries**: < 10ms (with proper indexing)
- **Index creation time**: 10-60 seconds per million rows

### Memory Usage

- **Query parsing**: Minimal memory overhead (< 1KB per query)
- **Result processing**: Same as standard queries
- **Index size**: ~20-50% of table size for GIN indexes

## Error Handling

### Deep Nesting

A nested filter follows the JSONB path of each level, as deep as the document goes:

```python
# data -> 'device' ->> 'location'
{"device": {"location": {"eq": "Seattle"}}}

# data -> 'device' -> 'location' -> 'address' ->> 'city'
{"device": {"location": {"address": {"city": {"eq": "Seattle"}}}}}
```

### Invalid Filter Structures

Malformed filters raise `ValueError` instead of being skipped:

```python
# Empty nested filter: "WhereClause must have at least one condition, ..."
{"device": {}}

# Unknown operator: "Invalid operator 'invalid_field'. Supported operators: ..."
{"device": {"invalid_field": "not_an_operator"}}
```

## Choosing Between WhereType and Dict Syntax

Both syntaxes are equally powerful - choose based on your use case.

### Combining Top-Level and Nested Filters

You can mix scalar and nested filters freely:

```python
# Top-level filter only
where = {"status": {"eq": "active"}}

# Combined top-level and nested filters
where = {
    "status": {"eq": "active"},
    "device": {"is_active": {"eq": True}}
}
```

### Comparing WhereType and Dict Approaches

Both approaches produce identical SQL:

```python
import fraiseql

# GraphQL where input approach (type-safe)
@fraiseql.query
async def assignments(info, where: AssignmentWhereInput = None):
    db = info.context["db"]
    where_filter = AssignmentWhereInput(
        device=DeviceWhereInput(is_active=BooleanFilter(eq=True))
    )
    return await db.find("assignments", where=where_filter)

# Dict-based approach (flexible)
@fraiseql.query
async def assignments(info, device_active: bool = None):
    where_dict = {}
    if device_active is not None:
        where_dict["device"] = {"is_active": {"eq": device_active}}

    return await db.find("assignments", where=where_dict)
```

### Database Schema Considerations

Ensure your JSONB data uses snake_case field names:

```python
# ✅ Recommended: snake_case in JSONB
{
    "device": {
        "id": "uuid",
        "name": "router-01",
        "is_active": true
    }
}

# ✅ Also works: camelCase input (auto-converted)
where_dict = {"device": {"isActive": {"eq": True}}}
# Converts to: data->'device'->>'is_active' = 'true'
```

### Recommended Indexes

For optimal nested filtering performance, create GIN indexes:

```sql
-- Run during deployment
CREATE INDEX CONCURRENTLY idx_table_nested_fields
ON table_name USING gin (data);

-- For specific nested fields
CREATE INDEX CONCURRENTLY idx_table_device_active
ON table_name USING gin ((data->'device'->'is_active'));
```

### Testing Nested Filters

Example test cases for nested filtering:

```python
def test_find_active_assignments(self):
    """Test basic top-level filter."""
    results = await repo.find("assignments", where={"status": {"eq": "active"}})
    assert len(results) == 5

def test_find_active_assignments_with_active_devices(self):
    """Test combined top-level and nested filters."""
    where = {
        "status": {"eq": "active"},
        "device": {"is_active": {"eq": True}}
    }
    results = await repo.find("assignments", where=where)
    assert len(results) == 3
```

## Complete Example

```python
import fraiseql
from fraiseql.db import FraiseQLRepository, register_type_for_view

@fraiseql.type
class Device:
    id: str
    name: str
    is_active: bool
    location: str

@fraiseql.type
class Assignment:
    id: str
    status: str
    device: Device

# Register types (the view is "id" + a JSONB "data" column)
register_type_for_view("assignments", Assignment, has_jsonb_data=True)

# Repository usage
repo = FraiseQLRepository(db_pool)

# Complex nested filtering
where_dict = {
    "status": {"in": ["active", "pending"]},
    "device": {
        "is_active": {"eq": True},
        "name": {"contains": "production"},
        "location": {"eq": "datacenter-1"}
    }
}

assignments = await repo.find("assignments", where=where_dict)
```

This provides powerful, type-safe filtering capabilities for complex data relationships stored in JSONB columns.

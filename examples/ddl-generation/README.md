# FraiseQL DDL Generation Examples

This directory contains examples and test schemas for the FraiseQL DDL generation helper library.

## Overview

The fraiseql_tools package provides utilities to generate production-ready PostgreSQL DDL for table-backed views. It lives in the repository's `tools/` directory and is not part of the installed `fraiseql` package: put `tools/` on `sys.path` (or `PYTHONPATH`) before importing it, as the example scripts do:

- **tv_\* (JSON Views)**: Store entities as JSONB for efficient JSON queries
- **ta_\* (Arrow Views)**: Store entities as Arrow IPC RecordBatches for columnar analytics

## Files

### Test Schemas

Located in `test_schemas/`:

- **user.json**: Simple User entity (id, name, email, created_at)
- **user_with_posts.json**: User with related Posts (demonstrates composition views)
- **orders.json**: Order with LineItems (complex nested structure)

### Example Scripts

- **example_basic.py**: Generate JSON view for simple User entity
- **example_arrow.py**: Generate Arrow columnar view for Order entity
- **example_refresh_strategy.py**: Demonstrate refresh strategy selection

## Running Examples

### Prerequisites

```bash
cd /home/lionel/code/fraiseql
```

### Example 1: Basic JSON View Generation

```bash
python3 examples/ddl-generation/example_basic.py
```

Output:

- Loads `user.json` schema
- Generates `tv_user` table-backed view with trigger-based refresh
- Validates DDL
- Outputs to `ddl_user_view.sql`

### Example 2: Arrow Columnar View

```bash
python3 examples/ddl-generation/example_arrow.py
```

Output:

- Loads `orders.json` schema
- Generates `ta_order` Arrow columnar view with scheduled refresh
- Includes monitoring functions
- Outputs to `ddl_order_arrow_view.sql`

### Example 3: Refresh Strategy Selection

```bash
python3 examples/ddl-generation/example_refresh_strategy.py
```

Demonstrates automatic refresh strategy selection for different workload patterns.

## Generated DDL Overview

### tv_* (JSON Views) Include

1. **Base Table**
   - Entity ID and JSONB payload storage
   - Materialization metadata (created_at, updated_at, view_generated_at)
   - Staleness tracking (is_stale, staleness_detected_at)
   - Composition tracking (composition_ids)

2. **Indexes**
   - Primary key on view_id
   - Unique index on entity_id
   - Index on updated_at for time-based queries
   - Index on is_stale for staleness checks
   - GIN index on JSONB for efficient JSON queries
   - Index on composition_ids for relationship queries

3. **Refresh Functions**

   **Trigger-based refresh:**
   - `refresh_tv_*_on_change()`: Trigger fires on source changes
   - `refresh_tv_*_entry()`: Single-entity synchronous refresh
   - `refresh_tv_*_batch()`: Batch refresh for multiple entities

   **Scheduled refresh:**
   - `refresh_ta_*_full()`: Complete materialization
   - `refresh_ta_*_incremental()`: Update only stale entries

4. **Monitoring Functions**
   - `get_view_statistics_*()`: Size, staleness, quality metrics
   - `analyze_staleness_*()`: Staleness analysis
   - `analyze_query_performance_*()`: Performance recommendations
   - `health_check_*_summary()`: Health status check

### ta_* (Arrow Views) Include

1. **Base Table**
   - Batch storage with columnar per-field encoding
   - Arrow IPC RecordBatch format
   - Batch metadata (row_count, batch_size_bytes, compression)
   - Flight protocol metadata (dictionary_encoded_fields, field_compression_codecs)
   - Materialization tracking

2. **Refresh Functions**
   - `refresh_ta_*_full()`: Complete batch materialization
   - `refresh_ta_*_incremental()`: Update stale batches
   - `check_refresh_health_*()`: Batch refresh health

3. **Monitoring**
   - Arrow-specific statistics (batch count, total rows, decode time)
   - Compression codec tracking
   - Health monitoring dashboard

## Refresh Strategy Guide

### Trigger-based (Real-time)

**Best for:**

- Read-heavy workloads (1000+ reads per write)
- Strict latency requirements (<100ms)
- Low write volume (<10 writes/sec)
- Mission-critical data freshness

**Mechanism:**

- Trigger fires on source table changes
- Immediately marks view entry as stale
- Entry refreshed on next access or via scheduled worker

**Trade-offs:**

- ✓ Data freshness (near real-time)
- ✗ Higher trigger overhead
- ✗ Not ideal for bulk operations

### Scheduled (Batch)

**Best for:**

- Batch import systems
- Acceptable staleness windows (30+ minutes)
- High write volume (>1000/min)
- Read-mostly aggregations

**Mechanism:**

- Runs at fixed intervals (default: 30 minutes)
- Full or incremental refresh based on staleness
- Tracks refresh state and health

**Trade-offs:**

- ✓ Lower overhead for bulk operations
- ✓ Predictable resource usage
- ✗ Data lag (up to refresh interval)

## Python API

### Load Schema

```python
from fraiseql_tools import load_schema

schema = load_schema("schema.json")
```

### Generate JSON View

```python
from fraiseql_tools import generate_tv_ddl

tv_ddl = generate_tv_ddl(
    schema,
    entity="User",
    view="user",
    refresh_strategy="trigger-based",
    include_composition_views=True,
    include_monitoring_functions=True
)

with open("ddl_user_view.sql", "w") as f:
    f.write(tv_ddl)
```

### Generate Arrow View

```python
from fraiseql_tools import generate_ta_ddl

ta_ddl = generate_ta_ddl(
    schema,
    entity="Order",
    view="order",
    refresh_strategy="scheduled"
)
```

### Suggest Refresh Strategy

```python
from fraiseql_tools import suggest_refresh_strategy

strategy = suggest_refresh_strategy(
    write_volume=100,           # writes per minute
    latency_requirement_ms=500, # acceptable staleness
    read_volume=10000          # reads per minute
)
# Returns: "trigger-based" or "scheduled"
```

### Validate Generated DDL

```python
from fraiseql_tools import validate_generated_ddl

errors = validate_generated_ddl(tv_ddl)
if errors:
    for error in errors:
        print(f"Warning: {error}")
else:
    print("DDL validation passed")
```

### Generate Composition Views

```python
from fraiseql_tools import generate_composition_views

composition_ddl = generate_composition_views(
    schema,
    entity="User",
    relationships=["posts", "comments"]
)
```

## Schema Format

FraiseQL schemas are standard JSON with this structure:

```json
{
  "$schema": "https://fraiseql.dev/schema/v2.json",
  "version": "2.0",
  "types": [
    {
      "name": "User",
      "description": "A user in the system",
      "fields": [
        {"name": "id", "type": "Int", "nullable": false},
        {"name": "name", "type": "String", "nullable": false},
        {"name": "email", "type": "String", "nullable": false},
        {"name": "created_at", "type": "DateTime", "nullable": false}
      ]
    }
  ],
  "queries": [
    {
      "name": "users",
      "return_type": "User",
      "returns_list": true,
      "sql_source": "v_users"
    }
  ],
  "mutations": []
}
```

## Output Files

When you run the examples, the following files are created:

- `ddl_user_view.sql`: JSON view DDL for User entity
- `ddl_order_arrow_view.sql`: Arrow view DDL for Order entity

These files can be executed directly against PostgreSQL:

```sql
-- Load and execute generated DDL
\i ddl_user_view.sql

-- Then use the views
SELECT entity_json FROM tv_user WHERE entity_id = 1;

-- Check health
SELECT * FROM health_check_user_summary();

-- Get statistics
SELECT * FROM get_view_statistics_user();
```

## Performance Considerations

### JSON Views (tv_*)

- **GIN Index**: Fast JSONB queries but higher insert overhead
- **Staleness Tracking**: Allows incremental refresh with zero downtime
- **Composition Views**: Efficient multi-entity loading

### Arrow Views (ta_*)

- **Batch Storage**: Efficient for columnar analytics (10-100x compression)
- **Arrow Flight**: Native streaming integration for remote clients
- **Scheduled Refresh**: Bulk load patterns work well

## Troubleshooting

### Missing Template Variables

If you see errors like `Undefined template variable: entity_name`:

- Ensure all required context is passed to `generate_tv_ddl()` or `generate_ta_ddl()`
- Check schema is valid and contains the specified entity

### Validation Warnings

Common validation warnings:

- "Low comment count": Add more COMMENT ON statements (normal for small views)
- "Low index count": Consider field types and query patterns
- "Unresolved template syntax": Check for malformed {{ }} or {% %} in output

### Invalid Entity

If you get "Entity 'User' not found in schema":

- Verify entity name matches exactly (case-sensitive)
- Check schema file is valid JSON
- Ensure types are defined in schema

## Documentation

For more details, see:

- [FraiseQL Documentation](https://fraiseql.dev)
- [PostgreSQL DDL Syntax](https://www.postgresql.org/docs/current/sql-syntax.html)
- [JSONB Operations](https://www.postgresql.org/docs/current/datatype-json.html)
- [Arrow IPC Format](https://arrow.apache.org/docs/format/Columnar.html)

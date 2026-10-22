# Database Migrations Example

🟠 ADVANCED | ⏱️ 15 min | 🎯 Database Operations | 🏷️ Migrations

A comprehensive example of PostgreSQL database migrations for FraiseQL applications, focusing on datetime UTC normalization and best practices for schema evolution.

**What you'll learn:**

- PostgreSQL migration patterns for JSONB data
- UTC timestamp normalization with 'Z' suffix
- Helper functions for consistent data formatting
- Migration testing and validation strategies

**Prerequisites:**

- `../blog_simple/` - Basic FraiseQL concepts
- PostgreSQL knowledge and migration experience

**Next steps:**

- `../blog_simple/` - Tables, views and mutation functions in one schema

## Overview

This example demonstrates essential database migration patterns for FraiseQL applications, particularly focusing on datetime handling in JSONB columns. The migration ensures consistent UTC timestamp formatting across all GraphQL responses.

### Key Migration: DateTime UTC Normalization

The main migration (`datetime_utc_normalization.sql`) addresses a critical issue: inconsistent timestamp formatting in JSONB data. PostgreSQL's `timestamptz` type stores UTC internally but can format timestamps differently based on client settings.

**Problem Solved:**

- Ensures all timestamps in GraphQL responses use ISO 8601 format with 'Z' suffix
- Provides consistent datetime handling across different PostgreSQL configurations
- Prevents timezone-related bugs in client applications

## Migration Details

### Helper Function: `to_utc_z()`

```sql
CREATE OR REPLACE FUNCTION to_utc_z(ts timestamptz)
RETURNS text AS $$
BEGIN
    IF ts IS NULL THEN
        RETURN NULL;
    END IF;
    RETURN to_char(ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"');
END;
$$ LANGUAGE plpgsql IMMUTABLE;
```

This function:

- Converts any `timestamptz` to UTC
- Formats as ISO 8601 with milliseconds and 'Z' suffix
- Handles NULL values gracefully
- Is marked `IMMUTABLE` for query optimization

### View Updates

The migration updates all views to use `to_utc_z()` for timestamp fields:

```sql
-- Before (inconsistent formatting)
created_at timestamptz

-- After (consistent UTC with Z suffix)
to_utc_z(created_at) AS created_at
```

### Affected Fields

- `created_at` - Record creation timestamp
- `updated_at` - Last modification timestamp
- `published_at` - Content publication timestamp
- `email_verified_at` - Account verification timestamp
- `last_login_at` - User authentication timestamp

## When to Apply This Migration

### Required For

- ✅ Production deployments with multiple timezones
- ✅ Applications serving international users
- ✅ Systems requiring consistent timestamp formatting
- ✅ GraphQL APIs with datetime fields

### Optional For

- 🟡 Development environments with single timezone
- 🟡 Internal applications with controlled timezone settings
- 🟡 Systems not exposing timestamps in APIs

## Testing the Migration

### 1. Setup Test Database

```bash
createdb migration_test
psql -d migration_test -f datetime_utc_normalization.sql
```

### 2. Test the Helper Function

```sql
-- Test with different timezones
SELECT
    '2025-01-15 12:00:00+00:00'::timestamptz as utc_time,
    to_utc_z('2025-01-15 12:00:00+00:00'::timestamptz) as formatted_utc,

    '2025-01-15 12:00:00-05:00'::timestamptz as est_time,
    to_utc_z('2025-01-15 12:00:00-05:00'::timestamptz) as formatted_est,

    '2025-01-15 12:00:00+01:00'::timestamptz as cet_time,
    to_utc_z('2025-01-15 12:00:00+01:00'::timestamptz) as formatted_cet;
```

Expected output:

```
utc_time          | formatted_utc          | est_time          | formatted_est         | cet_time          | formatted_cet
-------------------+-----------------------+-------------------+-----------------------+-------------------+------------------------
2025-01-15 12:00:00+00 | 2025-01-15T12:00:00.000Z | 2025-01-15 17:00:00+00 | 2025-01-15T17:00:00.000Z | 2025-01-15 11:00:00+00 | 2025-01-15T11:00:00.000Z
```

### 3. Verify View Updates

```sql
-- Check that views use the new formatting
SELECT
    id,
    to_utc_z(created_at) as formatted_created_at,
    created_at as raw_created_at
FROM users LIMIT 1;
```

## Migration Best Practices

### 1. Test in Staging First

```bash
# Create staging database
createdb staging_db
psql -d staging_db -f datetime_utc_normalization.sql

# Run your application tests against staging
# Verify GraphQL responses show consistent timestamps
```

### 2. Backup Before Migration

```bash
# Backup production database
pg_dump production_db > production_backup.sql

# Test restore on backup
createdb production_restore
psql -d production_restore < production_backup.sql
```

### 3. Gradual Rollout

```sql
-- Option 1: Create new views alongside old ones
CREATE VIEW users_v2 AS SELECT ...;
CREATE VIEW posts_v2 AS SELECT ...;

-- Test application with new views
-- Switch over when confident

-- Option 2: Update in-place during maintenance window
-- Apply migration during low-traffic period
-- Monitor for any issues
```

### 4. Rollback Plan

```sql
-- If issues arise, rollback views to original format
CREATE OR REPLACE VIEW users AS
SELECT
    id,
    -- Remove to_utc_z() calls
    created_at,  -- Instead of to_utc_z(created_at)
    updated_at,  -- Instead of to_utc_z(updated_at)
    -- ... other fields
FROM users;
```

## Performance Considerations

### Benefits

- ✅ Consistent formatting reduces client-side processing
- ✅ ISO 8601 format is widely supported
- ✅ 'Z' suffix clearly indicates UTC
- ✅ Millisecond precision maintained

### Costs

- ⚠️ Slight performance overhead for `to_utc_z()` calls
- ⚠️ Increased index size (text vs timestamptz)
- ⚠️ Cannot use timestamptz operators on formatted strings

### Optimization Strategies

```sql
-- Create functional indexes for common queries
CREATE INDEX idx_posts_published_at ON posts (published_at)
WHERE published_at IS NOT NULL;

-- Keep original timestamptz columns for internal operations
-- Only format for JSONB output
ALTER TABLE posts ADD COLUMN published_at_raw timestamptz;
```

## Integration with FraiseQL

### GraphQL Schema Impact

```python
@fraiseql.type
class Post:
    id: UUID
    title: str
    content: str
    created_at: datetime  # Now consistently formatted as ISO 8601
    updated_at: datetime  # Always UTC with Z suffix
    published_at: datetime | None
```

### Client Benefits

```javascript
// Before: Inconsistent formatting
const post = {
  createdAt: "2025-01-15T12:00:00+00:00",  // Server timezone
  // or
  createdAt: "2025-01-15T07:00:00-05:00",  // Client timezone
}

// After: Consistent UTC formatting
const post = {
  createdAt: "2025-01-15T12:00:00.000Z",  // Always UTC with Z
  updatedAt: "2025-01-15T12:30:00.000Z",  // Predictable format
}
```

## Advanced Migration Patterns

### 1. Conditional Updates

```sql
-- Only update records that need formatting
UPDATE table_name
SET jsonb_data = jsonb_set(
    jsonb_data,
    '{createdAt}',
    to_jsonb(to_utc_z(jsonb_data->>'createdAt'::timestamptz))
)
WHERE jsonb_data->>'createdAt' NOT LIKE '%Z';
```

### 2. Batch Processing

```sql
-- Process large tables in batches
UPDATE table_name
SET jsonb_data = jsonb_data || jsonb_build_object(
    'createdAt', to_utc_z(jsonb_data->>'createdAt'::timestamptz),
    'updatedAt', to_utc_z(jsonb_data->>'updatedAt'::timestamptz)
)
WHERE id IN (
    SELECT id FROM table_name
    WHERE jsonb_data->>'createdAt' NOT LIKE '%Z'
    LIMIT 1000
);
```

## Monitoring and Validation

### Post-Migration Checks

```sql
-- Verify all timestamps have Z suffix
SELECT COUNT(*) as total_records,
       COUNT(*) FILTER (WHERE jsonb_data->>'createdAt' LIKE '%Z') as utc_formatted
FROM table_name;

-- Check for any malformed timestamps
SELECT id, jsonb_data->>'createdAt' as created_at
FROM table_name
WHERE jsonb_data->>'createdAt' NOT LIKE '____-__-__T__:__:__.__Z';
```

## Next Steps

After applying this migration:

1. **Update client applications** to expect consistent UTC formatting
2. **Add timestamp validation** in your GraphQL input types
3. **Consider timezone handling** for user-specific timezones
4. **Implement audit logging** for timestamp changes
5. **Add monitoring** for timestamp format consistency

---

**PostgreSQL Database Migrations for FraiseQL**. Demonstrates datetime UTC normalization and migration best practices for consistent GraphQL timestamp handling.

## Support

- **Issues**: [GitHub Issues](../../issues)
- **Discussions**: [GitHub Discussions](../../discussions)
- **Discord**: [FraiseQL Community](https://discord.gg/fraiseql)
- **Documentation**: [FraiseQL Docs](../../docs)

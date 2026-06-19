<!-- Skip to main content -->
---

title: tv_* Table Pattern: Table-Backed JSON Views
description: - Physical storage on disk (materialized JSONB data)
keywords: ["design", "scalability", "performance", "patterns", "security"]
tags: ["documentation", "reference"]
---

# tv_* Table Pattern: Table-Backed JSON Views

## Overview

**tv_* tables** are PostgreSQL-specific, materialized table-backed views that pre-compute and physically store pre-composed JSONB data structures for high-performance GraphQL query execution on complex nested data.

**Analogous to**: `ta_*` tables for Arrow plane (analytics), but `tv_*` for JSON plane (GraphQL).

**Key difference**: Unlike logical views (`v_*`), tv_* tables are actual PostgreSQL tables with:

- Physical storage on disk (materialized JSONB data)
- Trigger-based or scheduled refresh mechanism
- Denormalized JSONB composition for complex queries
- 5-50x faster query performance on deeply nested data

## When to Use tv_* Tables

### ✅ **Use tv_* when**

- **Complex JSONB composition** with multiple JOINs (3+ related entities)
- **Deep nesting** required (e.g., User → Posts → Comments → Likes)
- **High-frequency read, low-frequency write** workloads
- **Pre-aggregated dashboards** with complex data structures
- **GraphQL queries** with consistent nested patterns
- **GraphQL subscriptions** need fast access to composed data

### ❌ **Don't use tv_* when**

- **Simple queries** (single or 2-table joins) - use `v_*` logical views instead
- **Frequently changing data** with millisecond latency requirements
- **Storage is constrained** (tv_* duplicates JSONB data)
- **Dynamic query patterns** where composition varies by request

## Performance Comparison

### Scenario: Complex User Profile with Posts, Comments, and Likes (10K users)

| Metric | v_user_full (View) | tv_user_profile (Table) | Improvement |
|--------|-------------------|------------------------|-------------|
| Query time | 2-5s | 100-200ms | **10-50x faster** |
| JSONB composition | Real-time (multiple JOINs) | Pre-computed | **Zero JOIN cost** |
| Memory usage | 500MB-1GB | 150-300MB | **3-6x lower** |
| CPU | 50-80% | 5-10% | **5-16x reduction** |

### Query Breakdown

**Logical view (v_user_full)** - Real-time composition:

```text
<!-- Code example in TEXT -->

1. Fetch user (1ms)
2. Fetch posts (2-3s via JOIN)
3. Compose posts array (500-800ms)
4. Fetch comments per post (1-2s via subqueries)
5. Compose comments array (300-500ms)
6. Fetch likes per comment (1-2s)
7. Build final JSONB (200-300ms)
Total: 5-10 seconds
```text
<!-- Code example in TEXT -->

**Table-backed view (tv_user_profile)** - Pre-computed:

```text
<!-- Code example in TEXT -->

1. Fetch pre-composed JSONB (100-200ms)
Total: 100-200ms
```text
<!-- Code example in TEXT -->

## DDL Pattern

### Basic Structure

```sql
<!-- Code example in SQL -->
-- 1. Create physical table with pre-composed JSONB
CREATE TABLE tv_user_profile (
    id TEXT NOT NULL PRIMARY KEY,
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (id) REFERENCES tb_user(id) ON DELETE CASCADE
);

-- 2. Create index for faster lookups
CREATE INDEX idx_tv_user_profile_data_gin
    ON tv_user_profile USING GIN(data);

-- 3. Create refresh trigger for near-real-time updates
CREATE TRIGGER trg_refresh_tv_user_profile
    AFTER INSERT OR UPDATE OR DELETE ON tb_user
    FOR EACH ROW
    EXECUTE FUNCTION refresh_tv_user_profile_trigger();
```text
<!-- Code example in TEXT -->

### JSONB Composition Pattern

```sql
<!-- Code example in SQL -->
-- Helper view to compose nested data (intermediate step)
CREATE VIEW v_user_posts_composed AS
SELECT
    fk_user,
    jsonb_agg(
        jsonb_build_object(
            'id', p.id,
            'title', p.title,
            'content', p.content,
            'createdAt', p.created_at,
            'comments', COALESCE(comments.data, '[]'::jsonb)
        )
        ORDER BY p.created_at DESC
    ) AS posts_data
FROM v_post p
LEFT JOIN (
    -- Pre-aggregate comments per post
    SELECT
        fk_post,
        jsonb_agg(
            jsonb_build_object(
                'id', c.id,
                'text', c.text,
                'createdAt', c.created_at
            )
            ORDER BY c.created_at DESC
        ) AS data
    FROM v_comment
    GROUP BY fk_post
) comments ON comments.fk_post = p.pk_post
GROUP BY fk_user;

-- Main table-backed view with pre-composed JSONB
CREATE TABLE tv_user_profile (
    id TEXT NOT NULL PRIMARY KEY,
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (id) REFERENCES tb_user(id) ON DELETE CASCADE
);

-- Insert pre-composed data
INSERT INTO tv_user_profile (id, data)
SELECT
    u.id,
    u.data || jsonb_build_object(
        'posts', COALESCE(p.posts_data, '[]'::jsonb)
    ) AS data,
    NOW()
FROM v_user u
LEFT JOIN v_user_posts_composed p ON p.fk_user = u.pk_user
ON CONFLICT (id) DO UPDATE SET
    data = EXCLUDED.data,
    updated_at = NOW();
```text
<!-- Code example in TEXT -->

## Refresh Strategies

Choose based on your latency and overhead requirements:

### Option 1: Trigger-Based (Real-Time)

**Best for**: GraphQL subscriptions, <1min latency requirements

**Characteristics**:

- Fires after every INSERT/UPDATE/DELETE on source tables
- Latency: <100ms per operation
- Overhead: Per-row cost (scales with write volume)
- Control: Fully automatic

**Implementation**:

```sql
<!-- Code example in SQL -->
CREATE OR REPLACE FUNCTION refresh_tv_user_profile_trigger()
RETURNS TRIGGER AS $$
BEGIN
    -- Recompute JSONB for affected user
    INSERT INTO tv_user_profile (id, data, updated_at)
    SELECT
        u.id,
        u.data || jsonb_build_object(
            'posts', COALESCE(p.posts_data, '[]'::jsonb)
        ) AS data,
        NOW()
    FROM v_user u
    LEFT JOIN v_user_posts_composed p ON p.fk_user = u.pk_user
    WHERE u.id = NEW.id OR (TG_OP = 'DELETE' AND u.id = OLD.id)
    ON CONFLICT (id) DO UPDATE SET
        data = EXCLUDED.data,
        updated_at = NOW();

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_refresh_tv_user_profile
    AFTER INSERT OR UPDATE OR DELETE ON tb_user
    FOR EACH ROW
    EXECUTE FUNCTION refresh_tv_user_profile_trigger();

-- Also trigger on related table changes
CREATE TRIGGER trg_refresh_tv_user_profile_on_post
    AFTER INSERT OR UPDATE OR DELETE ON tb_post
    FOR EACH ROW
    EXECUTE FUNCTION refresh_tv_user_profile_trigger();

CREATE TRIGGER trg_refresh_tv_user_profile_on_comment
    AFTER INSERT OR UPDATE OR DELETE ON tb_comment
    FOR EACH ROW
    EXECUTE FUNCTION refresh_tv_user_profile_trigger();
```text
<!-- Code example in TEXT -->

### Option 2: Scheduled Batch (Low Overhead)

**Best for**: Nightly dashboards, acceptable staleness (minutes to hours)

**Characteristics**:

- Batched refresh at fixed intervals
- Latency: Minutes to hours
- Overhead: Batch cost (no per-row overhead)
- Control: Scheduled via pg_cron

**Implementation**:

```sql
<!-- Code example in SQL -->
-- Enable pg_cron extension
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- Schedule refresh every 5 minutes
SELECT cron.schedule(
    'refresh-tv-user-profile',
    '*/5 * * * *',  -- Every 5 minutes
    'SELECT refresh_tv_user_profile();'
);

-- Batch refresh function
CREATE OR REPLACE FUNCTION refresh_tv_user_profile()
RETURNS TABLE(rows_inserted BIGINT, rows_updated BIGINT) AS $$
DECLARE
    v_inserted BIGINT := 0;
    v_updated BIGINT := 0;
BEGIN
    -- Upsert all user profiles
    WITH upsert AS (
        INSERT INTO tv_user_profile (id, data, updated_at)
        SELECT
            u.id,
            u.data || jsonb_build_object(
                'posts', COALESCE(p.posts_data, '[]'::jsonb)
            ) AS data,
            NOW()
        FROM v_user u
        LEFT JOIN v_user_posts_composed p ON p.fk_user = u.pk_user
        ON CONFLICT (id) DO UPDATE SET
            data = EXCLUDED.data,
            updated_at = NOW()
        RETURNING (xmax = 0) AS inserted
    )
    SELECT COUNT(*) FILTER (WHERE inserted) INTO v_inserted FROM upsert;

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_updated := v_updated - v_inserted;

    RETURN QUERY SELECT v_inserted, v_updated;
END;
$$ LANGUAGE plpgsql;
```text
<!-- Code example in TEXT -->

### Option 3: Command-Based Explicit Refresh

**Best for**: Development, bulk data loads, manual ETL

**Characteristics**:

- Manual refresh on demand
- Latency: On-demand
- Overhead: Only when called
- Control: Explicit API calls

**Implementation**:

```sql
<!-- Code example in SQL -->
CREATE OR REPLACE FUNCTION refresh_tv_user_profile(user_id_filter UUID DEFAULT NULL)
RETURNS TABLE(rows_inserted BIGINT, rows_updated BIGINT) AS $$
DECLARE
    v_inserted BIGINT := 0;
    v_updated BIGINT := 0;
BEGIN
    -- Upsert specified profiles (or all if no filter)
    WITH upsert AS (
        INSERT INTO tv_user_profile (id, data, updated_at)
        SELECT
            u.id,
            u.data || jsonb_build_object(
                'posts', COALESCE(p.posts_data, '[]'::jsonb)
            ) AS data,
            NOW()
        FROM v_user u
        LEFT JOIN v_user_posts_composed p ON p.fk_user = u.pk_user
        WHERE user_id_filter IS NULL OR u.id = user_id_filter
        ON CONFLICT (id) DO UPDATE SET
            data = EXCLUDED.data,
            updated_at = NOW()
        RETURNING (xmax = 0) AS inserted
    )
    SELECT COUNT(*) FILTER (WHERE inserted) INTO v_inserted FROM upsert;

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_updated := v_updated - v_inserted;

    RETURN QUERY SELECT v_inserted, v_updated;
END;
$$ LANGUAGE plpgsql;

-- Usage: Refresh specific user profile
SELECT * FROM refresh_tv_user_profile('550e8400-e29b-41d4-a716-446655440000'::UUID);

-- Usage: Refresh all profiles
SELECT * FROM refresh_tv_user_profile();
```text
<!-- Code example in TEXT -->

## Refresh Strategy Decision Matrix

| Write Volume | Read Volume | Data Complexity | Recommended |
|-------------|-------------|-----------------|------------|
| Low (<100/min) | High | Complex (3+ JOINs) | Trigger-based |
| Low (<100/min) | High | Simple | Scheduled (15min) |
| Medium (100-1K/min) | High | Complex | Trigger-based + batch cleanup |
| Medium (100-1K/min) | High | Simple | Scheduled (5-15min) |
| High (>1K/min) | High | Any | Batch refresh only |

## Migration Guide

### Step 1: Create Intermediate Views

Create helper views for composition logic (reusable across tv_*, REST APIs, etc.):

```bash
<!-- Code example in BASH -->
psql -h localhost -U postgres fraiseql_dev < examples/sql/postgres/v_user_posts_composed.sql
psql -h localhost -U postgres fraiseql_dev < examples/sql/postgres/v_user_profile_composed.sql
```text
<!-- Code example in TEXT -->

### Step 2: Create tv_* Table

```bash
<!-- Code example in BASH -->
psql -h localhost -U postgres fraiseql_dev < examples/sql/postgres/tv_user_profile.sql
```text
<!-- Code example in TEXT -->

### Step 3: Initial Population

```sql
<!-- Code example in SQL -->
-- Populate table from logical view
SELECT * FROM refresh_tv_user_profile();

-- Verify row counts
SELECT COUNT(*) as tv_profile_count FROM tv_user_profile;
SELECT COUNT(*) as v_user_count FROM v_user;

-- They should be equal
```text
<!-- Code example in TEXT -->

### Step 4: Update GraphQL Schema

In your authoring layer (Python/TypeScript), bind the `User` type to use `tv_user_profile` instead of `v_user`:

```python
<!-- Code example in Python -->
# Before: Uses v_user (logical view)
@FraiseQL.type()
class User:
    id: UUID  # UUID v4 for GraphQL ID
    name: str
    posts: list[Post]

# After: Uses tv_user_profile (table-backed view)
@FraiseQL.type(view="tv_user_profile")
class User:
    id: UUID  # UUID v4 for GraphQL ID
    name: str
    posts: list[Post]
```text
<!-- Code example in TEXT -->

### Step 5: Monitor Performance

```sql
<!-- Code example in SQL -->
-- Check staleness (how old is the pre-computed data?)
SELECT MAX(updated_at) - NOW() as staleness
FROM tv_user_profile;

-- Monitor refresh function performance
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM refresh_tv_user_profile();

-- Check data accuracy (profile count should match user count)
SELECT
    (SELECT COUNT(*) FROM tv_user_profile) as profiles,
    (SELECT COUNT(*) FROM v_user) as users,
    (SELECT COUNT(*) FROM tv_user_profile) = (SELECT COUNT(*) FROM v_user) as counts_match;
```text
<!-- Code example in TEXT -->

## Limitations and Considerations

### Storage

- **Data duplication**: tv_*tables duplicate JSONB from tb_* tables
- **Storage overhead**: Typically 20-50% of source data size (JSONB is less dense than columnar)
- **Index overhead**: GIN indexes add ~5-10% overhead

### Refresh Latency

- **Trigger-based**: <100ms per operation (suitable for real-time GraphQL)
- **Scheduled batch**: Minutes (suitable for dashboards)
- **Manual refresh**: On-demand (suitable for development/testing)

### Staleness Risk

- **Trigger-based**: Nearly real-time (slight delay during high-volume writes)
- **Scheduled batch**: By design (e.g., 5-minute staleness)
- **Manual refresh**: Until explicitly called

### Schema Drift Risk

- **JSONB structure must match GraphQL schema**: Mismatch causes validation errors
- **Nested entity changes**: Changes to related entities (Post, Comment) require trigger updates
- **Mitigation**: Comprehensive unit and integration tests verify schema consistency

### Cascading Triggers

- Multiple triggers (on user, post, comment) can create overhead
- Consider batch refresh if write volume is very high (>1K/min)
- Monitor trigger execution time

## Best Practices

1. **Use intermediate composed views** for reusability (also useful for REST APIs)
2. **Test trigger logic** before production deployment with high-volume writes
3. **Monitor staleness** with `updated_at` column
4. **Use command-based refresh** for bulk import verification
5. **Schedule batch refresh** as fallback for trigger failures
6. **Keep tv_* schema synchronized** with GraphQL schema definitions
7. **Document refresh strategy** in architecture decisions
8. **Use JSONB indexes** (GIN) for faster queries
9. **Benchmark vs. logical view** to confirm performance improvement

## Troubleshooting

### Issue: tv_* table empty after trigger creation

**Cause**: Trigger only fires on future changes, not existing data.

**Solution**: Run initial population:

```sql
<!-- Code example in SQL -->
SELECT * FROM refresh_tv_user_profile();
```text
<!-- Code example in TEXT -->

### Issue: tv_* data stale after writes

**Cause**: Trigger not firing or delayed.

**Solution**: Check trigger status:

```sql
<!-- Code example in SQL -->
SELECT * FROM information_schema.triggers
WHERE trigger_name LIKE 'trg_refresh_tv%';

-- Manually refresh
SELECT * FROM refresh_tv_user_profile();
```text
<!-- Code example in TEXT -->

### Issue: High CPU from cascading triggers

**Cause**: Multiple triggers (on related tables) causing many refreshes.

**Solution**: Switch to batched refresh:

```sql
<!-- Code example in SQL -->
-- Drop per-row triggers
DROP TRIGGER IF EXISTS trg_refresh_tv_user_profile_on_post ON tb_post;
DROP TRIGGER IF EXISTS trg_refresh_tv_user_profile_on_comment ON tb_comment;

-- Schedule batch refresh instead
SELECT cron.schedule('refresh-tv-profile', '*/5 * * * *', 'SELECT refresh_tv_user_profile();');
```text
<!-- Code example in TEXT -->

### Issue: JSONB composition mismatch with GraphQL schema

**Cause**: DDL changed without updating schema binding.

**Solution**:

1. Update PostgreSQL DDL (helper views + tv_* table)
2. Update GraphQL schema binding (authoring layer)
3. Re-populate tv_* table
4. Run integration tests to verify

## Examples

See `/home/lionel/code/FraiseQL/examples/sql/postgres/` for complete DDL examples:

- `tv_user_profile.sql` - User profile with nested posts and comments
- `tv_order_summary.sql` - Order with line items and customer details

## See Also

- [View Selection Guide](./view-selection-guide.md)
- [Schema Conventions](../../specs/schema-conventions.md)
- [FraiseQL Database Architecture](../../architecture/)

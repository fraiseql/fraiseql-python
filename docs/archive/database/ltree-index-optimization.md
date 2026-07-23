# LTREE Index Optimization Guide

## Overview

PostgreSQL LTREE columns require specialized indexing for optimal query performance. This guide covers GiST index creation, maintenance, and performance monitoring for hierarchical data.

## GiST Index Fundamentals

### Why GiST for LTREE?

LTREE operations are hierarchical and require specialized indexing:

- **B-tree indexes** work for equality but not hierarchy
- **GiST indexes** support all LTREE operators (`<@`, `@>`, `~`, `@`, etc.)
- **Performance**: 10-100x faster for hierarchical queries

### Index Creation

```sql
-- Basic GiST index
CREATE INDEX idx_category_path ON categories USING GIST (category_path);

-- Index with fill factor for write-heavy tables
CREATE INDEX idx_category_path ON categories USING GIST (category_path)
WITH (fillfactor = 70);

-- Composite index with additional columns
CREATE INDEX idx_category_path_name ON categories USING GIST (category_path)
WHERE active = true;
```

## Index Maintenance

### Monitoring Index Health

```sql
-- Check index size and usage
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan,  -- Number of index scans
    idx_tup_read,  -- Tuples read via index
    idx_tup_fetch  -- Tuples fetched via index
FROM pg_stat_user_indexes
WHERE indexname LIKE '%ltree%';

-- Index bloat check
SELECT
    schemaname,
    tablename,
    indexname,
    pg_size_pretty(pg_relation_size(indexrelid)) as index_size,
    idx_scan
FROM pg_stat_user_indexes
WHERE idx_scan > 0
ORDER BY pg_relation_size(indexrelid) DESC;
```

### Index Rebuilding

```sql
-- Rebuild index (online, doesn't block reads)
REINDEX INDEX CONCURRENTLY idx_category_path;

-- Rebuild with different parameters
DROP INDEX idx_category_path;
CREATE INDEX CONCURRENTLY idx_category_path ON categories USING GIST (category_path)
WITH (fillfactor = 80, autovacuum_enabled = true);
```

### Vacuum and Analyze

```sql
-- Update table statistics for query planner
ANALYZE categories;

-- Aggressive vacuum for LTREE tables
VACUUM (VERBOSE, ANALYZE) categories;
```

## Performance Optimization

### Query-Specific Indexes

```sql
-- For depth-based queries
CREATE INDEX idx_category_depth ON categories (nlevel(category_path));

-- For parent path queries
CREATE INDEX idx_category_parent ON categories (subpath(category_path, 0, -1));

-- For pattern matching optimization
CREATE INDEX idx_category_pattern ON categories USING GIST (category_path)
WHERE nlevel(category_path) <= 5;
```

### Index-Only Scans

```sql
-- Include frequently queried columns in index
CREATE INDEX idx_category_path_covering ON categories USING GIST (category_path)
INCLUDE (name, active, created_at);
```

## Query Optimization Techniques

### Efficient LTREE Queries

```sql
-- ✅ Good: Uses GiST index
SELECT * FROM categories
WHERE category_path <@ 'electronics'::ltree;

-- ✅ Good: Depth filtering
SELECT * FROM categories
WHERE category_path <@ 'electronics'::ltree
AND nlevel(category_path) = 3;

-- ❌ Bad: Functions on indexed column
SELECT * FROM categories
WHERE nlevel(category_path) = 3;

-- ✅ Good: Pre-computed depth
ALTER TABLE categories ADD COLUMN depth INTEGER GENERATED ALWAYS AS (nlevel(category_path)) STORED;
CREATE INDEX idx_category_depth ON categories (depth);
```

### Batch Operations

```sql
-- Efficient bulk updates
UPDATE categories
SET category_path = category_path || 'deprecated'::ltree
WHERE category_path <@ 'old_category'::ltree;

-- Efficient bulk deletes
DELETE FROM categories
WHERE category_path <@ 'obsolete'::ltree;
```

## Monitoring and Alerting

### Performance Metrics

```sql
-- Query performance monitoring
SELECT
    query,
    calls,
    total_time,
    mean_time,
    rows
FROM pg_stat_statements
WHERE query LIKE '%ltree%'
ORDER BY mean_time DESC;

-- Index hit ratios
SELECT
    schemaname,
    tablename,
    idx_scan / (seq_scan + idx_scan + 1.0) * 100 as index_hit_ratio
FROM pg_stat_user_tables
WHERE schemaname = 'public';
```

### Automated Maintenance

```sql
-- Create maintenance function
CREATE OR REPLACE FUNCTION maintain_ltree_indexes()
RETURNS void AS $$
DECLARE
    idx_record RECORD;
BEGIN
    -- Reindex indexes with low scan counts
    FOR idx_record IN
        SELECT indexname
        FROM pg_stat_user_indexes
        WHERE idx_scan < 1000
        AND indexname LIKE '%ltree%'
    LOOP
        EXECUTE format('REINDEX INDEX CONCURRENTLY %I', idx_record.indexname);
    END LOOP;

    -- Analyze tables
    ANALYZE categories;
END;
$$ LANGUAGE plpgsql;

-- Schedule with pg_cron or cron
SELECT cron.schedule('ltree-maintenance', '0 2 * * *', 'SELECT maintain_ltree_indexes();');
```

## Troubleshooting

### Common Issues

#### 1. Slow Queries Despite Index

```sql
-- Check if index is being used
EXPLAIN ANALYZE SELECT * FROM categories WHERE category_path <@ 'root'::ltree;

-- Force index usage (temporary)
SET enable_seqscan = off;
SELECT * FROM categories WHERE category_path <@ 'root'::ltree;
SET enable_seqscan = on;
```

#### 2. Index Bloat

```sql
-- Check bloat
SELECT
    schemaname,
    tablename,
    n_dead_tup,
    n_live_tup,
    (n_dead_tup::float / (n_live_tup + n_dead_tup)) * 100 as bloat_ratio
FROM pg_stat_user_tables
WHERE schemaname = 'public';

-- Rebuild bloated indexes
REINDEX INDEX idx_category_path;
```

#### 3. Memory Issues During Index Creation

```sql
-- For large tables, increase maintenance memory
SET maintenance_work_mem = '256MB';
CREATE INDEX CONCURRENTLY idx_category_path ON categories USING GIST (category_path);
SET maintenance_work_mem = default;
```

### Performance Comparison

```sql
-- Test query performance with/without index
CREATE TABLE test_performance AS SELECT * FROM categories LIMIT 10000;

-- Without index
EXPLAIN ANALYZE SELECT count(*) FROM test_performance WHERE category_path <@ 'root'::ltree;

-- With index
CREATE INDEX idx_test_path ON test_performance USING GIST (category_path);
EXPLAIN ANALYZE SELECT count(*) FROM test_performance WHERE category_path <@ 'root'::ltree;
```

## Production Deployment

### Index Creation Strategy

```sql
-- Safe production deployment
BEGIN;

-- Create index concurrently (doesn't block)
CREATE INDEX CONCURRENTLY idx_category_path_temp ON categories USING GIST (category_path);

-- Rename to production name
ALTER INDEX idx_category_path_temp RENAME TO idx_category_path;

-- Update statistics
ANALYZE categories;

COMMIT;
```

### Monitoring Setup

```sql
-- Create monitoring view
CREATE VIEW ltree_index_health AS
SELECT
    schemaname,
    tablename,
    indexname,
    pg_size_pretty(pg_relation_size(indexrelid)) as size,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch,
    CASE
        WHEN idx_scan = 0 THEN 'Unused'
        WHEN idx_scan < 100 THEN 'Low Usage'
        WHEN idx_scan < 1000 THEN 'Moderate Usage'
        ELSE 'High Usage'
    END as usage_category
FROM pg_stat_user_indexes
WHERE indexname LIKE '%ltree%';

-- Alert on unused indexes
SELECT * FROM ltree_index_health WHERE usage_category = 'Unused';
```

## Integration with FraiseQL

### Automatic Index Detection

FraiseQL automatically detects LTREE columns and suggests appropriate indexes:

```python
# FraiseQL will detect LTREE columns and recommend indexes
from fraiseql import FraiseQL

# Automatic index suggestions for LTREE fields
# GiST indexes are created automatically for LTREE columns
```

### Query Optimization

FraiseQL optimizes LTREE queries automatically:

- Uses appropriate operators based on query patterns
- Leverages GiST indexes for hierarchical operations
- Applies query rewriting for better performance

## Best Practices Summary

1. **Always create GiST indexes** on LTREE columns
2. **Monitor index usage** and rebuild when necessary
3. **Use CONCURRENTLY** for production index creation
4. **Regular ANALYZE** to maintain query planner statistics
5. **Consider composite indexes** for common query patterns
6. **Monitor for bloat** and reindex as needed
7. **Test query performance** before and after index changes

Following these practices ensures optimal performance for hierarchical data operations with PostgreSQL LTREE.

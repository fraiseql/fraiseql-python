<!-- Skip to main content -->
---

title: Aggregation Model
description: FraiseQL v2 supports **database-native aggregations** through compile-time schema analysis and runtime SQL generation. All aggregations execute server-side in t
keywords: ["design", "scalability", "performance", "patterns", "security"]
tags: ["documentation", "reference"]
---

# Aggregation Model

**Version:** 1.0
**Status:** Complete
**Audience:** Compiler developers, runtime engineers, SDK users
**Date:** January 12, 2026

---

## Overview

FraiseQL v2 supports **database-native aggregations** through compile-time schema analysis and runtime SQL generation. All aggregations execute server-side in the database, leveraging native SQL performance.

**Key Principle**: No joins. All dimensions must be denormalized into the `data` JSONB column at ETL time.

---

## Aggregate Functions

### Supported Functions (All Databases)

**Basic Aggregates**:

- `COUNT(*)` - Count all rows
- `COUNT(field)` - Count non-null values in field
- `COUNT(DISTINCT field)` - Count unique values
- `SUM(field)` - Sum all values
- `AVG(field)` - Average of values
- `MIN(field)` - Minimum value
- `MAX(field)` - Maximum value

**Example**:

```sql
<!-- Code example in SQL -->
SELECT
    COUNT(*) AS total_count,
    COUNT(DISTINCT customer_id) AS unique_customers,
    SUM(revenue) AS total_revenue,
    AVG(revenue) AS avg_revenue,
    MIN(revenue) AS min_revenue,
    MAX(revenue) AS max_revenue
FROM tf_sales;
```text
<!-- Code example in TEXT -->

### Database-Specific Extensions

**PostgreSQL**:

- `STDDEV(field)` - Standard deviation
- `VARIANCE(field)` - Variance
- `PERCENTILE_CONT(fraction)` - Continuous percentile
- `PERCENTILE_DISC(fraction)` - Discrete percentile

**MySQL**:

- `GROUP_CONCAT(field)` - Concatenate values with delimiter
- `STDDEV(field)` - Standard deviation (limited support)

**SQLite**:

- Limited to basic functions only (COUNT, SUM, AVG, MIN, MAX)

**SQL Server**:

- `STDEV(field)` / `STDEVP(field)` - Standard deviation (sample/population)
- `VAR(field)` / `VARP(field)` - Variance (sample/population)

---

## GROUP BY Semantics

### Compilation Strategy

When the compiler encounters a fact table (marked with `fact_table=True` in schema):

1. **Introspect Table Structure**:
   - Identify measure columns (numeric types: INT, BIGINT, DECIMAL, FLOAT)
   - Detect `data` JSONB column for dimensions
   - Identify denormalized filter columns (indexed SQL columns)

2. **Generate GroupByExecutionPlan**:
   - GROUP BY clause with JSONB extraction for dimensions
   - Aggregate function calls on measure columns
   - Optional HAVING filters on aggregated results
   - Optional temporal bucketing (DATE_TRUNC, DATE_FORMAT, strftime)

3. **Validate**:
   - Grouping columns exist in table structure
   - Measure columns are numeric types
   - JSONB paths are valid for database target

### Runtime Execution

1. Parse GraphQL GROUP BY request
2. Generate SELECT statement with:
   - GROUP BY clause extracting JSONB dimensions
   - Aggregate functions on SQL measure columns
   - Optional HAVING filters
   - Optional temporal bucketing
3. Lower to database-specific SQL dialect
4. Execute on database (server-side aggregation)
5. Return aggregated results

**Example**:

GraphQL:

```graphql
<!-- Code example in GraphQL -->
query {
  sales_aggregate(
    groupBy: { category: true, region: true }
  ) {
    category
    region
    revenue_sum
    count
  }
}
```text
<!-- Code example in TEXT -->

Generated SQL (PostgreSQL):

```sql
<!-- Code example in SQL -->
SELECT
    data->>'category' AS category,
    data->>'region' AS region,
    SUM(revenue) AS revenue_sum,
    COUNT(*) AS count
FROM tf_sales
GROUP BY data->>'category', data->>'region';
```text
<!-- Code example in TEXT -->

---

## HAVING Clause

The HAVING clause filters aggregated results after GROUP BY.

### Compilation

1. **Validate**: Ensure HAVING references only aggregated fields or grouping keys
2. **Generate**: Post-aggregation WHERE clause
3. **Lower**: Database-specific HAVING syntax

### Example

GraphQL:

```graphql
<!-- Code example in GraphQL -->
query {
  sales_aggregate(
    groupBy: { category: true },
    having: { revenue_sum_gte: 10000 }
  ) {
    category
    revenue_sum
  }
}
```text
<!-- Code example in TEXT -->

Generated SQL (PostgreSQL):

```sql
<!-- Code example in SQL -->
SELECT
    data->>'category' AS category,
    SUM(revenue) AS revenue_sum
FROM tf_sales
GROUP BY data->>'category'
HAVING SUM(revenue) >= $1;
-- Parameters: [10000]
```text
<!-- Code example in TEXT -->

---

## Temporal Bucketing

Temporal bucketing groups timestamps into intervals (day, week, month, etc.).

### Database-Specific Functions

**PostgreSQL**:

```sql
<!-- Code example in SQL -->
DATE_TRUNC('day', occurred_at)    -- Day bucket
DATE_TRUNC('week', occurred_at)   -- Week bucket
DATE_TRUNC('month', occurred_at)  -- Month bucket
DATE_TRUNC('quarter', occurred_at) -- Quarter bucket
DATE_TRUNC('year', occurred_at)   -- Year bucket
```text
<!-- Code example in TEXT -->

**MySQL**:

```sql
<!-- Code example in SQL -->
DATE_FORMAT(occurred_at, '%Y-%m-%d')      -- Day bucket
DATE_FORMAT(occurred_at, '%Y-%m')         -- Month bucket
DATE_FORMAT(occurred_at, '%Y')            -- Year bucket
```text
<!-- Code example in TEXT -->

**SQLite**:

```sql
<!-- Code example in SQL -->
strftime('%Y-%m-%d', occurred_at)  -- Day bucket
strftime('%Y-%m', occurred_at)     -- Month bucket
strftime('%Y', occurred_at)        -- Year bucket
```text
<!-- Code example in TEXT -->

**SQL Server**:

```sql
<!-- Code example in SQL -->
DATEPART(day, occurred_at)     -- Day component
DATEPART(week, occurred_at)    -- Week component
DATEPART(month, occurred_at)   -- Month component
DATEPART(quarter, occurred_at) -- Quarter component
DATEPART(year, occurred_at)    -- Year component
```text
<!-- Code example in TEXT -->

### Supported Buckets

- `second` - PostgreSQL only
- `minute` - PostgreSQL, SQL Server
- `hour` - PostgreSQL, SQL Server
- `day` - All databases
- `week` - All databases
- `month` - All databases
- `quarter` - PostgreSQL, SQL Server
- `year` - All databases

### Example

GraphQL:

```graphql
<!-- Code example in GraphQL -->
query {
  sales_aggregate(
    groupBy: { occurred_at_day: true }
  ) {
    occurred_at_day
    revenue_sum
  }
}
```text
<!-- Code example in TEXT -->

Generated SQL (PostgreSQL):

```sql
<!-- Code example in SQL -->
SELECT
    DATE_TRUNC('day', occurred_at) AS occurred_at_day,
    SUM(revenue) AS revenue_sum
FROM tf_sales
GROUP BY DATE_TRUNC('day', occurred_at)
ORDER BY occurred_at_day;
```text
<!-- Code example in TEXT -->

---

## Conditional Aggregates

Conditional aggregates apply filters to individual aggregate functions.

### PostgreSQL (FILTER Clause)

PostgreSQL supports the native `FILTER (WHERE ...)` syntax:

```sql
<!-- Code example in SQL -->
SELECT
    COUNT(*) AS total_orders,
    SUM(revenue) FILTER (WHERE data->>'status' = 'completed') AS completed_revenue,
    SUM(revenue) FILTER (WHERE data->>'status' = 'cancelled') AS cancelled_revenue
FROM tf_sales;
```text
<!-- Code example in TEXT -->

### MySQL/SQLite/SQL Server (CASE WHEN Emulation)

Other databases emulate with CASE WHEN:

```sql
<!-- Code example in SQL -->
SELECT
    COUNT(*) AS total_orders,
    SUM(CASE WHEN data->>'status' = 'completed' THEN revenue ELSE 0 END) AS completed_revenue,
    SUM(CASE WHEN data->>'status' = 'cancelled' THEN revenue ELSE 0 END) AS cancelled_revenue
FROM tf_sales;
```text
<!-- Code example in TEXT -->

### GraphQL API

```graphql
<!-- Code example in GraphQL -->
query {
  sales_aggregate {
    count
    revenue_sum
    completed_revenue: revenue_sum(
      filter: { status: { _eq: "completed" } }
    )
    cancelled_revenue: revenue_sum(
      filter: { status: { _eq: "cancelled" } }
    )
  }
}
```text
<!-- Code example in TEXT -->

---

## Performance Characteristics

### SQL Column Aggregation

**10-100x faster than JSONB aggregation**:

- Direct access to typed numeric columns
- B-tree indexes on measure columns
- Database native aggregation optimizations

**Example**:

```sql
<!-- Code example in SQL -->
-- ✅ FAST: SQL column aggregation
SELECT SUM(revenue) FROM tf_sales;
-- Execution time: 0.2ms (1M rows)

-- ❌ SLOW: JSONB aggregation (if measures were in JSONB)
SELECT SUM((data->>'revenue')::numeric) FROM tf_sales;
-- Execution time: 45ms (1M rows)
-- 225x slower!
```text
<!-- Code example in TEXT -->

### Indexed Measures

For common aggregation queries, create indexes on measure columns:

```sql
<!-- Code example in SQL -->
CREATE INDEX idx_sales_revenue ON tf_sales(revenue);
CREATE INDEX idx_sales_quantity ON tf_sales(quantity);
```text
<!-- Code example in TEXT -->

**Result**: Near-instantaneous aggregations for queries with selective filters.

### JSONB Dimensions

JSONB extraction for GROUP BY is slower than SQL columns, but provides flexibility:

```sql
<!-- Code example in SQL -->
-- Moderate speed: JSONB extraction for grouping
SELECT
    data->>'category' AS category,
    SUM(revenue) AS revenue_sum
FROM tf_sales
GROUP BY data->>'category';
```text
<!-- Code example in TEXT -->

**Optimization**: Use GIN index on `data` column (PostgreSQL):

```sql
<!-- Code example in SQL -->
CREATE INDEX idx_sales_data_gin ON tf_sales USING GIN(data);
```text
<!-- Code example in TEXT -->

---

## Native Dimensions

When a view mixes native SQL columns (e.g. `period_date DATE`, `category_id UUID`) with a JSONB `data` column, native columns can be declared as **native dimensions** to avoid JSONB extraction overhead.

### Problem

By default, all dimension columns in auto-aggregation are extracted from JSONB:

```sql
-- Default: extracts from JSONB even though period_date is a real column
SELECT json_build_object('period_date', "data"->>'period_date', ...)
FROM v_orders_by_period
GROUP BY "data"->>'period_date'
ORDER BY "data" -> 'period_date'
```

This has two issues:

1. **Performance**: btree indexes on native columns cannot be used
2. **Correctness**: `ORDER BY "data" -> 'period_date'` references the raw `data` column, which is not in `GROUP BY` — PostgreSQL rejects the query

### Solution

Declare native columns in the `native_dimensions` key of the aggregation metadata:

```python
register_type_for_view(
    "v_orders_by_period", OrderPeriodType,
    has_jsonb_data=True,
    aggregation={
        "native_dimensions": ["period_date", "category_id"],
        "dimensions": "dimensions",
        "measures": {"measures.total": "SUM", "measures.count": "SUM"},
    },
)
```

FraiseQL generates correct SQL using column references instead of JSONB extraction:

```sql
-- Native dimensions: uses column refs and table alias
SELECT json_build_object(
    'period_date', t."period_date",
    'category_id', t."category_id",
    'dimensions', json_build_object('subcategory', "data"->'dimensions'->>'subcategory'),
    'measures', json_build_object('total', SUM(("data"->'measures'->>'total')::numeric))
)::text
FROM v_orders_by_period AS t
GROUP BY t."period_date", t."category_id", "data"->'dimensions'->>'subcategory'
ORDER BY t."period_date"
```

### Mixed Grouping

Native and JSONB dimensions coexist in the same query. Native dimensions use `t."col"`, JSONB dimensions use `"data"->>'field'`. The table automatically receives an `AS t` alias when native dimensions are present.

### Backward Compatibility

Existing metadata without `native_dimensions` behaves identically. The key is optional and defaults to an empty list.

---

## No Joins Principle

**Critical**: FraiseQL does not support joins. All dimensional data must be denormalized into the `data` JSONB column at ETL time.

**Example**:

```sql
<!-- Code example in SQL -->
-- ❌ NOT SUPPORTED: Joining dimension tables
SELECT
    s.revenue,
    p.category
FROM tf_sales s
JOIN td_products p ON s.product_id = p.id;

-- ✅ CORRECT: Denormalized dimensions in JSONB
SELECT
    revenue,
    data->>'product_category' AS category
FROM tf_sales;
-- Category was denormalized at ETL time by DBA/data team
```text
<!-- Code example in TEXT -->

**ETL Responsibility**:

- FraiseQL provides GraphQL query interface over existing tables
- DBA/data team creates ETL pipelines to populate `tf_` tables
- Dimensional data is denormalized from `td_` tables into `tf_` tables' `data` column

---

## Related Specifications

- **Fact-Dimension Pattern** (`fact-dimension-pattern.md`) - Fact table structure and patterns
- **Aggregation Operators** (`../specs/aggregation-operators.md`) - Complete operator reference by database
- **Capability Manifest** (`../specs/capability-manifest.md`) - Database-specific operator availability
- **Window Functions** (`window-functions.md`) - Phase 5 analytical functions

---

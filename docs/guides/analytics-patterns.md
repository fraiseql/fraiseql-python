---
title: Analytics Patterns Guide
description: Runtime auto-aggregation patterns over PostgreSQL v_/tv_ views (SUM, AVG, COUNT, GROUP BY, HAVING, FILTER).
keywords: ["workflow", "debugging", "implementation", "best-practices", "saas", "realtime", "ecommerce"]
tags: ["documentation", "reference"]
---

# Analytics Patterns Guide

**Status:** Stable
**Audience:** Developers, Data Engineers, Architects
**Database:** PostgreSQL
**Reading Time:** 15-20 minutes

---

## Prerequisites

### Required Knowledge

- SQL aggregation functions (SUM, AVG, COUNT, GROUP BY, HAVING)
- Fact tables and dimension tables (star schema/data warehouse concepts)
- JSONB data types and querying
- Window functions (ROW_NUMBER, RANK, LAG, LEAD) — as raw PostgreSQL inside views
- Time-series analysis and bucketing
- Filtering and WHERE clause optimization
- Query performance considerations
- GraphQL query syntax and execution

### Required Software

- FraiseQL v1 (Python runtime GraphQL framework for PostgreSQL)
- Python 3.13+
- PostgreSQL 14+
- A SQL client for schema inspection (psql)
- A code editor for defining types and views

### Required Infrastructure

- A FastAPI app built with `create_fraiseql_app(...)`
- `v_`/`tv_` read views exposing measures and dimensions in a `data` JSONB column
- PostgreSQL database with appropriate analytical indexes (GIN on `data`, B-tree on filter columns)
- Sample data loaded in your analytics tables/views

#### Optional but Recommended

- Data warehouse ETL tooling (dbt, Airflow) to refresh pre-aggregated `tv_` views
- A BI platform for visualization and dashboarding
- Query performance profiling tools (`EXPLAIN (ANALYZE, BUFFERS)`)
- Data modeling documentation

**Time Estimate:** 20-40 minutes per pattern example, 2-4 hours to adapt patterns to your schema

## Overview

This guide provides practical examples of common analytical query patterns in FraiseQL v1, showing GraphQL queries and the SQL that FraiseQL executes against your PostgreSQL views.

FraiseQL v1 performs **runtime auto-aggregation**: when a GraphQL query selects aggregate fields on a view-backed type, FraiseQL inspects the field selection and derives the matching `GROUP BY` + aggregate SQL **at request time** (`_derive_auto_aggregation` / `_parse_aggregation_expr` in `src/fraiseql/db.py`), then runs it server-side against your `v_`/`tv_` view. There is no compiler and no build step — the field selection drives the SQL, and PostgreSQL does the heavy lifting.

You define the analytics type with a normal `@fraiseql.type` decorator pointing at a read view:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_sales", jsonb_column="data")
class Sales:
    id: ID
    category: str
    region: str
    revenue: float
    quantity: int
```

**Key principle**: aggregation happens inside the database. You model the measures (numeric values) and dimensions in a `v_`/`tv_` view's `data` JSONB column (plus native columns where useful), and FraiseQL pushes the grouping and aggregate functions down to that view. Anything beyond the derived set can always be written by hand inside the view's SQL.

The supported aggregate functions are standard PostgreSQL aggregates: `COUNT`, `SUM`, `AVG`, `MIN`, `MAX` (plus `STDDEV` / `VARIANCE` and others written directly in view SQL).

---

## Pattern 1: Simple Aggregation

**Use Case**: Total revenue and average order value

### GraphQL Query

```graphql
query {
  sales {
    count
    revenueSum
    revenueAvg
  }
}
```

### SQL Execution (PostgreSQL)

```sql
SELECT
    COUNT(*) AS count,
    SUM((data->>'revenue')::numeric) AS revenue_sum,
    AVG((data->>'revenue')::numeric) AS revenue_avg
FROM v_sales;
```

**Performance**: ~0.2ms for 1M rows (with no WHERE clause, uses table statistics)

---

## Pattern 2: GROUP BY Single Dimension

**Use Case**: Revenue by category

### GraphQL Query

```graphql
query {
  sales {
    category
    revenueSum
    count
  }
}
```

### SQL Execution (PostgreSQL)

```sql
SELECT
    data->>'category' AS category,
    SUM((data->>'revenue')::numeric) AS revenue_sum,
    COUNT(*) AS count
FROM v_sales
GROUP BY data->>'category';
```

**Performance**: ~1-2ms for 1M rows (with a GIN index on `data`)

---

## Pattern 3: GROUP BY Multiple Dimensions

**Use Case**: Revenue by category and region

### GraphQL Query

```graphql
query {
  sales {
    category
    region
    revenueSum
    quantitySum
  }
}
```

### SQL Execution (PostgreSQL)

```sql
SELECT
    data->>'category' AS category,
    data->>'region' AS region,
    SUM((data->>'revenue')::numeric) AS revenue_sum,
    SUM((data->>'quantity')::numeric) AS quantity_sum
FROM v_sales
GROUP BY data->>'category', data->>'region';
```

**Performance**: ~2-3ms for 1M rows

---

## Pattern 4: Temporal Bucketing (Daily)

**Use Case**: Daily sales trend

Bucket the timestamp **inside the view's SQL** with `DATE_TRUNC` so the truncated value becomes a stable grouping dimension exposed in `data`.

### View Definition (PostgreSQL)

```sql
CREATE VIEW v_sales_daily AS
SELECT
    id,
    jsonb_build_object(
        'occurred_at_day', DATE_TRUNC('day', occurred_at),
        'revenue', revenue
    ) AS data
FROM tb_sales;
```

### GraphQL Query

```graphql
query {
  salesDaily {
    occurredAtDay
    revenueSum
    count
  }
}
```

### SQL Execution (PostgreSQL)

```sql
SELECT
    data->>'occurred_at_day' AS occurred_at_day,
    SUM((data->>'revenue')::numeric) AS revenue_sum,
    COUNT(*) AS count
FROM v_sales_daily
GROUP BY data->>'occurred_at_day'
ORDER BY occurred_at_day;
```

**Performance**: ~5-10ms for 1M rows (with an index on the source `occurred_at` column)

---

## Pattern 5: Filtered Aggregation

**Use Case**: Revenue for a specific customer

Filters are passed as GraphQL `where` arguments; FraiseQL translates them into a parameterized `WHERE` clause. PostgreSQL WHERE operators use bare names (`eq`, `gte`, `lt`, `in`, ...).

### GraphQL Query

```graphql
query {
  sales(where: { customerId: { eq: "uuid-123" } }) {
    count
    revenueSum
  }
}
```

### SQL Execution (PostgreSQL)

```sql
SELECT
    COUNT(*) AS count,
    SUM((data->>'revenue')::numeric) AS revenue_sum
FROM v_sales
WHERE data->>'customer_id' = $1;
-- Parameters: ["uuid-123"]
```

**Performance**: ~0.05ms when `customer_id` is a native indexed column (B-tree index)

---

## Pattern 6: HAVING Clause

**Use Case**: Categories with revenue > $10,000

`HAVING` filters aggregated results after `GROUP BY`. Express it inside the view's SQL, where it filters on aggregate expressions or grouping keys.

### View Definition (PostgreSQL)

```sql
CREATE VIEW v_top_categories AS
SELECT
    data->>'category' AS id,
    jsonb_build_object(
        'category', data->>'category',
        'revenue_sum', SUM((data->>'revenue')::numeric)
    ) AS data
FROM v_sales
GROUP BY data->>'category'
HAVING SUM((data->>'revenue')::numeric) > 10000;
```

### GraphQL Query

```graphql
query {
  topCategories {
    category
    revenueSum
  }
}
```

`HAVING` references only aggregated fields or grouping keys — the same rule PostgreSQL enforces.

**Performance**: ~1-2ms for 1M rows

---

## Pattern 7: Conditional Aggregates with FILTER (PostgreSQL)

**Use Case**: Revenue by payment method using `FILTER`

PostgreSQL's `FILTER (WHERE ...)` clause computes conditional aggregates in a single pass. Write these directly in the view's SQL.

### View Definition (PostgreSQL)

```sql
CREATE VIEW v_sales_by_payment AS
SELECT
    1 AS id,
    jsonb_build_object(
        'count', COUNT(*),
        'revenue_sum', SUM((data->>'revenue')::numeric),
        'revenue_sum_credit_card',
            SUM((data->>'revenue')::numeric)
            FILTER (WHERE data->>'payment_method' = 'credit_card'),
        'revenue_sum_paypal',
            SUM((data->>'revenue')::numeric)
            FILTER (WHERE data->>'payment_method' = 'paypal')
    ) AS data
FROM v_sales;
```

### GraphQL Query

```graphql
query {
  salesByPayment {
    count
    revenueSum
    revenueSumCreditCard
    revenueSumPaypal
  }
}
```

---

## Pattern 8: Time-Series with Multiple Dimensions

**Use Case**: Monthly revenue by category and region

### View Definition (PostgreSQL)

```sql
CREATE VIEW v_sales_monthly AS
SELECT
    id,
    jsonb_build_object(
        'occurred_at_month', DATE_TRUNC('month', occurred_at),
        'category', category,
        'region', region,
        'revenue', revenue
    ) AS data
FROM tb_sales;
```

### GraphQL Query

```graphql
query {
  salesMonthly {
    occurredAtMonth
    category
    region
    revenueSum
    count
  }
}
```

### SQL Execution (PostgreSQL)

```sql
SELECT
    data->>'occurred_at_month' AS occurred_at_month,
    data->>'category' AS category,
    data->>'region' AS region,
    SUM((data->>'revenue')::numeric) AS revenue_sum,
    COUNT(*) AS count
FROM v_sales_monthly
GROUP BY
    data->>'occurred_at_month',
    data->>'category',
    data->>'region'
ORDER BY occurred_at_month, category, region;
```

**Performance**: ~10-20ms for 1M rows

---

## Pattern 9: Nested Dimension Paths

**Use Case**: Revenue by customer segment (nested JSONB)

FraiseQL extracts nested dimension paths from the `data` JSONB column using the `#>>` path operator. Declare the field on the type and shape the path in your view.

### Schema Definition

```python
@fraiseql.type(sql_source="v_sales", jsonb_column="data")
class Sales:
    id: ID
    customer_segment: str  # Maps to data#>>'{customer,segment}'
    revenue: float
```

### GraphQL Query

```graphql
query {
  sales {
    customerSegment
    revenueSum
  }
}
```

### SQL Execution (PostgreSQL)

```sql
SELECT
    data#>>'{customer,segment}' AS customer_segment,
    SUM((data->>'revenue')::numeric) AS revenue_sum
FROM v_sales
GROUP BY data#>>'{customer,segment}';
```

---

## Pattern 10: Combining Filters and Grouping

**Use Case**: Revenue by region for Q1 2024

### GraphQL Query

```graphql
query {
  sales(
    where: {
      occurredAt: {
        gte: "2024-01-01",
        lt: "2024-04-01"
      }
    }
  ) {
    region
    revenueSum
    quantitySum
  }
}
```

### SQL Execution (PostgreSQL)

```sql
SELECT
    data->>'region' AS region,
    SUM((data->>'revenue')::numeric) AS revenue_sum,
    SUM((data->>'quantity')::numeric) AS quantity_sum
FROM v_sales
WHERE occurred_at >= $1 AND occurred_at < $2
GROUP BY data->>'region';
-- Parameters: ["2024-01-01", "2024-04-01"]
```

**Performance**: ~0.5-1ms (using an index on a native `occurred_at` column)

---

## Performance Optimization

### Use Native Columns for Filters

Expose frequently-filtered fields as **native indexed columns** in your view (alongside the `data` JSONB), not just JSONB paths.

Slower (JSONB filter):

```sql
WHERE data->>'customer_id' = 'uuid-123'
-- ~5-10ms (even with a GIN index)
```

Faster (indexed native column):

```sql
WHERE customer_id = 'uuid-123'
-- ~0.05ms (B-tree index)
```

This can be 100-200x faster for selective filters.

### Pre-Compute Common Aggregates

For frequently-used rollups, use a **table-backed projection view** (`tv_`): a real table holding pre-composed rows, refreshed by a function/trigger or an ETL job. FraiseQL reads it like any other view.

```sql
-- Pre-aggregated projection table (daily granularity)
CREATE TABLE tv_sales_daily (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    day DATE NOT NULL UNIQUE,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Populate / refresh via a scheduled job (ETL) or a fn_ function
INSERT INTO tv_sales_daily (day, data)
SELECT
    DATE_TRUNC('day', occurred_at)::DATE AS day,
    jsonb_build_object(
        'revenue', SUM(revenue),
        'quantity', SUM(quantity),
        'transaction_count', COUNT(*)
    ) AS data
FROM tb_sales
GROUP BY DATE_TRUNC('day', occurred_at)::DATE
ON CONFLICT (day) DO UPDATE SET
    data = EXCLUDED.data;
```

**Query Speed**: ~0.1ms (reading from a pre-aggregated `tv_` view vs ~10ms from raw rows)

### Statistical Aggregates and Window Functions

PostgreSQL statistical aggregates (`STDDEV`, `VARIANCE`) and window functions (`ROW_NUMBER`, `RANK`, `LAG`, `LEAD`, `OVER (PARTITION BY ...)`) are **not** a FraiseQL GraphQL API — they are standard PostgreSQL that you embed in your `v_`/`tv_` view SQL. The view then exposes the computed result as an ordinary field that GraphQL can select.

```sql
SELECT
    data->>'category' AS category,
    SUM((data->>'revenue')::numeric) AS revenue_sum,
    STDDEV((data->>'revenue')::numeric) AS revenue_stddev
FROM v_sales
WHERE data @> '{"region": "North America"}'
GROUP BY data->>'category';
```

```sql
-- Window function inside a view: rank categories by revenue
CREATE VIEW v_category_rank AS
SELECT
    data->>'category' AS id,
    jsonb_build_object(
        'category', data->>'category',
        'revenue_sum', SUM((data->>'revenue')::numeric),
        'revenue_rank', RANK() OVER (ORDER BY SUM((data->>'revenue')::numeric) DESC)
    ) AS data
FROM v_sales
GROUP BY data->>'category';
```

### PostgreSQL JSONB Features for Analytics

- Full JSONB support: `@>`, `?`, `?&` for complex filters
- Native `DATE_TRUNC` for all temporal buckets
- `FILTER (WHERE ...)` for conditional aggregates
- Statistical functions (`STDDEV`, `VARIANCE`) inside views
- GIN indexes on the `data` column, B-tree indexes on native filter columns

---

## Common Use Cases

### E-Commerce Analytics

**Daily Sales Trend** (reads a daily-bucketed view):

```graphql
query {
  salesDaily(orderBy: { occurredAtDay: ASC }) {
    occurredAtDay
    revenueSum
    count
  }
}
```

**Top Products by Revenue**:

```graphql
query {
  sales(orderBy: { revenueSum: DESC }, limit: 10) {
    productName
    revenueSum
    quantitySum
  }
}
```

### SaaS Metrics

**Monthly Recurring Revenue by Plan**:

```graphql
query {
  subscriptions(where: { status: { eq: "active" } }) {
    plan
    occurredAtMonth
    revenueSum
    count
  }
}
```

**Churn Rate**:

```graphql
query {
  subscriptions(where: { status: { eq: "cancelled" } }) {
    occurredAtMonth
    count
  }
}
```

### API Monitoring

**Requests by Endpoint**:

```graphql
query {
  apiRequests {
    endpoint
    count
    durationMsAvg
  }
}
```

**Error Rate by Status Code** (HAVING expressed in the view):

```graphql
query {
  apiRequests {
    statusCode
    count
    durationMsAvg
  }
}
```

---

## Troubleshooting

### "Aggregation query returns zero rows"

**Cause:** Usually a schema mismatch or missing data in the source table/view.

#### Diagnosis

1. Verify the source has rows: `SELECT COUNT(*) FROM v_sales;`
2. Check column/JSONB keys match your type: `SELECT jsonb_object_keys(data) FROM v_sales LIMIT 1;`
3. Verify the date range has data: `SELECT COUNT(*) FROM tb_sales WHERE occurred_at > NOW() - INTERVAL '30 days';`

#### Solutions

- Ensure the source table is populated and the view reflects it
- Verify the view name in `sql_source=` matches exactly
- Check date/time filters in the query
- Ensure the dimension key exists in `data` for the fields you group on

### "Aggregation query is very slow (>30 seconds)"

**Cause:** Missing indexes on the GROUP BY or WHERE clause columns.

#### Diagnosis

1. Run `EXPLAIN (ANALYZE, BUFFERS)` on the underlying SQL
2. Look for `Seq Scan` on the source table — indicates a missing index
3. Check cardinality of grouping columns: `SELECT COUNT(DISTINCT data->>'category') FROM v_sales;`

#### Solutions

- Add a GIN index on the `data` column and B-tree indexes on native filter columns
- Add a composite index on the source table: `CREATE INDEX idx_sales_date_cat ON tb_sales (occurred_at, category);`
- Partition large source tables by date
- Use a pre-aggregated `tv_` projection view for common rollups
- Reduce the date range or add more specific WHERE filters

### "JSON dimension data not being extracted in aggregation"

**Cause:** Dimension data stored in JSONB but the path is wrong.

#### Diagnosis

1. Check the value exists: `SELECT data FROM v_sales LIMIT 1;`
2. Verify JSON structure: `SELECT jsonb_pretty(data) FROM v_sales LIMIT 1;`
3. Test extraction: `SELECT data->>'customer_id' FROM v_sales LIMIT 1;`

#### Solutions

- Extract scalar paths with `data->>'field'` and nested paths with `data#>>'{a,b}'`
- Confirm the GraphQL field name maps to the right JSONB key in your view
- For complex JSON, use `jsonb_to_record()` for deeper access in the view SQL
- Consider promoting frequently-accessed fields to native columns

### "GROUP BY returning too many rows (millions)"

**Cause:** Grouping by a high-cardinality dimension (near-unique values per row).

#### Diagnosis

1. Check cardinality: `SELECT COUNT(DISTINCT data->>'category') FROM v_sales;`
2. If > 100K distinct values, the grouping is likely too granular

#### Solutions

- Add a `HAVING COUNT(*) > N` clause in the view to filter small groups
- Add a grouping hierarchy (day → week → month)
- Limit to the top-K results by count
- Reconsider whether grouping by a per-row id makes sense (group by a category instead)

### "Window function not producing expected results"

**Cause:** Window functions are raw PostgreSQL written inside the view — a mistake in the `OVER (...)` clause yields wrong partitions or ordering.

#### Diagnosis

1. Test the window function directly: `SELECT id, ROW_NUMBER() OVER (ORDER BY occurred_at) FROM tb_sales LIMIT 5;`
2. Verify the `PARTITION BY` / `ORDER BY` keys are correct
3. Confirm your PostgreSQL version (window functions require PostgreSQL 8.4+; modern features assume 12+)

#### Solutions

- Use `ROW_NUMBER()`, `RANK()`, `DENSE_RANK()`, `LAG()`, `LEAD()` inside the view's SELECT
- Wrap the windowed expression in `jsonb_build_object(...)` so it surfaces as a GraphQL field
- Pre-aggregate first, then apply window functions over the aggregated result

### "Timeouts in analytics queries"

**Cause:** The query scans too much data or the database is under load.

#### Diagnosis

1. Check query complexity with `EXPLAIN (ANALYZE, BUFFERS)`
2. Verify database server resources: CPU, memory, disk I/O
3. Check for concurrent load: `SELECT COUNT(*) FROM pg_stat_activity;`

#### Solutions

- Add a date-range filter to limit data scanned
- Pre-aggregate using a table-backed `tv_` view
- Add or tune indexes on grouping and filter columns
- Scale the database (add resources or read replicas)

---

## See Also

### Architecture & Design

- **[Aggregation Model](../architecture/analytics/aggregation-model.md)** — Runtime derivation and execution of aggregations
- **[Fact-Dimension Pattern](../architecture/analytics/fact-dimension-pattern.md)** — Table and view structure for analytics
- **[Window Functions](../architecture/analytics/window-functions.md)** — Raw PostgreSQL window functions inside views
- **[Calendar Dimensions](../architecture/analytics/calendar-dimensions.md)** — Calendar fields and time-bucketing patterns

### Schema & Specifications

- **[Analytical Schema Conventions](../specs/analytical-schema-conventions.md)** — Naming patterns for analytics views
- **[Aggregation Operators](../specs/aggregation-operators.md)** — Supported aggregate functions
- **[Scalar Types Reference](../reference/scalars.md)** — Data types for analytical fields

### Related Guides

- **[Common Patterns](./patterns.md)** — Real-world patterns including analytics
- **[Common Gotchas](./common-gotchas.md)** — Analytics pitfalls and solutions

### Operations & Optimization

- **[Performance Tuning Runbook](../operations/performance-tuning-runbook.md)** — Optimizing slow queries
- **[Monitoring Guide](./monitoring.md)** — Observing analytics in production

### Troubleshooting

- **[Common Gotchas](./common-gotchas.md)** — Analytics pitfalls and solutions
- **[Troubleshooting Decision Tree](./troubleshooting-decision-tree.md)** — Route to the correct guide

---

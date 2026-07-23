---
title: Fact-Dimension Pattern
description: A PostgreSQL data-modeling pattern for analytical workloads in FraiseQL v1.
keywords: ["design", "scalability", "performance", "patterns", "analytics"]
tags: ["documentation", "reference"]
---

# Fact-Dimension Pattern

**Audience:** Database architects, data engineers, FraiseQL users

---

## Overview

The **fact table pattern** is a data-modeling approach for analytical workloads. You
design the tables and the ETL/refresh process yourself; FraiseQL queries them at runtime
through PostgreSQL views, deriving `GROUP BY` and aggregate SQL automatically from the
GraphQL selection (see [Aggregation Model](./aggregation-model.md)).

- One record = one immutable fact (transaction, measurement, event)
- Measures stored as SQL columns (much faster aggregation)
- Dimensions stored in a JSONB `data` column (flexible grouping)
- Denormalized filters as indexed SQL columns

**Critical principle:** No joins at query time. All dimensional data must be denormalized
at ETL time so the read view is a single standalone table.

---

## Fact Table Structure

### Required Columns

1. **Primary Key**: `id` (UUID or BIGSERIAL)
2. **Measure Columns**: numeric types for aggregation
   - `INT`, `BIGINT`, `DECIMAL`, `FLOAT`, `NUMERIC`
   - Examples: `revenue`, `quantity`, `duration_ms`
3. **Dimensions Column**: `data` JSONB (the default column name FraiseQL reads, configurable
   via `jsonb_column`)
   - Contains all grouping dimensions
   - Examples: category, region, customer_segment

### Optional Columns

1. **Denormalized Filter Columns**: indexed SQL columns for fast `WHERE` filtering
   - UUIDs, `VARCHAR`, `DATE`, enum
   - Examples: `customer_id`, `product_id`, `occurred_at`, `status`
2. **Timestamps**: `created_at`, `occurred_at`, etc.

### Example: Sales Fact Table

```sql
CREATE TABLE tf_sales (
    -- Primary key
    id BIGSERIAL PRIMARY KEY,

    -- Measures (SQL columns for fast aggregation)
    revenue DECIMAL(10,2) NOT NULL,
    quantity INT NOT NULL,
    cost DECIMAL(10,2) NOT NULL,

    -- Dimensions (JSONB for flexible grouping)
    data JSONB NOT NULL,
    -- Example data content:
    -- {
    --   "category": "Electronics",
    --   "region": "North America",
    --   "product_name": "Laptop Pro",
    --   "customer_segment": "Enterprise"
    -- }

    -- Denormalized filters (indexed SQL columns for fast WHERE)
    customer_id UUID NOT NULL,
    product_id UUID NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(50) NOT NULL,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for fast filtering
CREATE INDEX idx_sales_customer ON tf_sales(customer_id);
CREATE INDEX idx_sales_product ON tf_sales(product_id);
CREATE INDEX idx_sales_occurred ON tf_sales(occurred_at);
CREATE INDEX idx_sales_status ON tf_sales(status);

-- GIN index for JSONB dimensions
CREATE INDEX idx_sales_data_gin ON tf_sales USING GIN(data);

-- Composite index for common query pattern
CREATE INDEX idx_sales_customer_occurred
    ON tf_sales(customer_id, occurred_at DESC);
```

### Exposing the Fact Table to GraphQL

FraiseQL reads the table through a view (or directly through a table that already carries an
`id` plus a `data` JSONB column). Define a plain type over the read source — there is no
special "fact table" decorator parameter:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_sales", jsonb_column="data")
class Sale:
    id: ID
    revenue: float
    quantity: int
    category: str
    region: str
```

When a query selects measure and dimension fields, FraiseQL derives the `GROUP BY` and the
aggregate SQL at runtime against this view. The aggregate functions available are the
standard PostgreSQL ones: `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, `STDDEV`, `VARIANCE`.

---

## Measures vs Dimensions vs Filters

### Measures (SQL Columns)

**Purpose**: aggregation targets (`SUM`, `AVG`, `COUNT`, etc.)

**Storage**: dedicated SQL columns with numeric types.

**Performance**: much faster than aggregating over JSONB.

**Examples**:

- `revenue DECIMAL(10,2)` — total sale amount
- `quantity INT` — number of items
- `duration_ms BIGINT` — event duration in milliseconds
- `error_count INT` — number of errors

**Why SQL columns?**:

```sql
-- FAST: direct aggregation on a SQL column
SELECT SUM(revenue) FROM tf_sales WHERE customer_id = $1;

-- SLOW: aggregation on a JSONB field (avoid this)
SELECT SUM((data->>'revenue')::numeric) FROM tf_sales WHERE customer_id = $1;
```

The JSONB form must cast text to numeric per row and cannot use a plain numeric index, so it
is dramatically slower on large tables.

### Dimensions (JSONB Paths)

**Purpose**: `GROUP BY` grouping keys.

**Storage**: the `data` JSONB column, with a flexible schema.

**Performance**: slower than SQL columns, but flexible (no `ALTER TABLE` needed to add a
dimension).

**Examples**:

- `data->>'category'` — product category
- `data->>'region'` — geographic region
- `data->>'product_type'` — product classification
- `data#>>'{customer,segment}'` — nested path for customer segment

**Why JSONB?**:

- Schema flexibility (add dimensions without `ALTER TABLE`)
- Sparse dimensions (not all facts have all dimensions)
- Nested structures (hierarchical dimensions)
- No need to create columns for rarely-used dimensions

**Query pattern**:

```sql
SELECT
    data->>'category' AS category,
    data->>'region' AS region,
    SUM(revenue) AS total_revenue
FROM tf_sales
GROUP BY data->>'category', data->>'region';
```

### Denormalized Filters (Indexed SQL Columns)

**Purpose**: fast `WHERE` filtering (avoid JSONB for high-selectivity filters).

**Storage**: dedicated indexed SQL columns.

**Performance**: B-tree index access.

**Examples**:

- `customer_id UUID` — filter by customer (high cardinality)
- `product_id UUID` — filter by product
- `occurred_at TIMESTAMPTZ` — filter by time range
- `status VARCHAR(50)` — filter by status (low cardinality but frequently filtered)

**Why denormalized?**:

```sql
-- FAST: indexed SQL column filter, uses the composite index
SELECT * FROM tf_sales
WHERE customer_id = 'uuid-123' AND occurred_at >= '2024-01-01';

-- SLOWER: JSONB filter for a high-selectivity exact match (avoid this)
SELECT * FROM tf_sales
WHERE data->>'customer_id' = 'uuid-123';
```

---

## No Joins Principle

**Architecture decision**: the read view is a single standalone table — FraiseQL queries it
directly without joining other tables at query time.

### Implications

1. All dimensional data must be denormalized into the `data` JSONB at ETL time
2. Dimension tables (`td_*`) are used at ETL time only, never at query time
3. Each fact table is completely standalone
4. Pre-aggregated tables follow the same pattern (not joined to anything)

### Example

```sql
-- NOT the pattern: joining dimension tables at query time
SELECT
    s.revenue,
    p.category,
    c.segment
FROM tf_sales s
JOIN td_products p ON s.product_id = p.id
JOIN td_customers c ON s.customer_id = c.id;

-- CORRECT: dimensions denormalized into JSONB at ETL time
SELECT
    revenue,
    data->>'product_category' AS category,
    data->>'customer_segment' AS segment
FROM tf_sales;
```

### ETL Process (Managed by the DBA / Data Team)

```sql
-- Step 1: ETL loads the raw transaction
INSERT INTO staging_sales (transaction_id, product_id, customer_id, revenue)
VALUES ('txn-001', 'prod-123', 'cust-456', 99.99);

-- Step 2: ETL enriches with dimensional data from td_* tables
INSERT INTO tf_sales (
    id,
    revenue,
    quantity,
    cost,
    data,  -- dimensions denormalized from td_products, td_customers
    customer_id,
    product_id,
    occurred_at
)
SELECT
    gen_random_uuid(),
    s.revenue,
    s.quantity,
    s.cost,
    jsonb_build_object(
        'product_category', p.category,
        'product_name', p.name,
        'customer_segment', c.segment,
        'customer_region', c.region
    ) AS data,  -- denormalization happens here
    s.customer_id,
    s.product_id,
    s.occurred_at
FROM staging_sales s
JOIN td_products p ON s.product_id = p.id
JOIN td_customers c ON s.customer_id = c.id;

-- Step 3: truncate the staging table
TRUNCATE staging_sales;
```

This ETL process is owned by the DBA / data team. FraiseQL does not generate or run it; it
only queries the resulting view at runtime.

---

## How FraiseQL Queries the Fact Table

You design the fact table and its read view; FraiseQL handles the query side at runtime.

1. **Define a read view** that exposes an `id` and a `data` JSONB column (a `v_` logical view
   over the fact table, or a `tv_` projection table for heavy reads — see
   [View Selection Guide](../database/view-selection-guide.md) and
   [tv_ Table Pattern](../database/tv-table-pattern.md)).
2. **Declare a plain `@fraiseql.type`** over that view with `sql_source` and `jsonb_column`.
3. **Let auto-aggregation derive the SQL.** When a GraphQL query selects aggregate fields,
   FraiseQL builds the `SELECT`, the aggregate functions, and the `GROUP BY` from the
   requested dimensions automatically.

For example, a GraphQL selection grouping by `category` and `region` and summing `revenue`
produces, at runtime, SQL equivalent to:

```sql
SELECT
    data->>'category' AS category,
    data->>'region' AS region,
    SUM(revenue) AS revenue_sum,
    COUNT(*) AS count
FROM tf_sales
GROUP BY data->>'category', data->>'region';
```

See [Aggregation Model](./aggregation-model.md) for the full `GROUP BY` / `HAVING` /
`FILTER` semantics.

---

## PostgreSQL JSONB Features

FraiseQL v1 targets PostgreSQL, which gives the fact-dimension pattern a rich toolset:

- Full JSONB support: `->`, `->>`, `#>`, `#>>`, `@>`, `?`, `?&`
- Native `DATE_TRUNC` for temporal bucketing
- `FILTER (WHERE ...)` for conditional aggregates
- GIN indexes for efficient JSONB queries
- Statistical functions (`STDDEV`, `VARIANCE`)

**Example**:

```sql
-- Conditional aggregates over JSONB dimensions
SELECT
    data->>'category' AS category,
    SUM(revenue) FILTER (WHERE data @> '{"region": "North America"}') AS na_revenue,
    SUM(revenue) FILTER (WHERE data @> '{"region": "Europe"}') AS eu_revenue
FROM tf_sales
WHERE data ? 'category'  -- has the 'category' key
GROUP BY data->>'category';
```

---

## Pre-Aggregated Fact Tables = Same Structure, Coarser Granularity

**Key insight**: pre-aggregated tables follow the same pattern as fact tables, just at a
coarser granularity. Use the `tf_` prefix with a descriptive suffix.

### Example: Daily Aggregates

```sql
-- Pre-aggregated fact table: same structure as tf_sales, daily granularity
CREATE TABLE tf_sales_daily (
    id BIGSERIAL PRIMARY KEY,
    day DATE NOT NULL,  -- granularity dimension

    -- Pre-aggregated measures
    revenue DECIMAL(10,2) NOT NULL,      -- SUM(revenue) from tf_sales
    quantity INT NOT NULL,               -- SUM(quantity) from tf_sales
    transaction_count INT NOT NULL,      -- COUNT(*) from tf_sales

    -- Dimensions (same JSONB pattern)
    data JSONB NOT NULL,
    -- Can still group by category, region, etc. from the data column

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_sales_daily_day ON tf_sales_daily(day);
CREATE INDEX idx_sales_daily_data_gin ON tf_sales_daily USING GIN(data);
```

**Populated via ETL** (managed by the DBA / data team):

```sql
INSERT INTO tf_sales_daily (id, day, revenue, quantity, transaction_count, data)
SELECT
    gen_random_uuid(),
    DATE_TRUNC('day', occurred_at)::DATE AS day,
    SUM(revenue) AS revenue,
    SUM(quantity) AS quantity,
    COUNT(*) AS transaction_count,
    jsonb_build_object() AS data  -- can preserve dimensions if needed
FROM tf_sales
GROUP BY DATE_TRUNC('day', occurred_at)::DATE
ON CONFLICT (day) DO UPDATE SET
    revenue = EXCLUDED.revenue,
    quantity = EXCLUDED.quantity,
    transaction_count = EXCLUDED.transaction_count;
```

A daily-rollup view is queried exactly like any other fact-table view — FraiseQL does not
treat it specially. See [Calendar Dimensions](./calendar-dimensions.md) for modeling time
buckets, and [Window Functions](./window-functions.md) for running totals and ranking inside
your view SQL.

---

## Best Practices

### When to Use Fact Tables (`tf_*`)

Use for:

- High-volume transactional data (sales, events, logs)
- Any granularity (raw transactions or pre-aggregated rollups)
- Real-time or near-real-time data ingestion
- Data requiring full history retention

Avoid for:

- Low-volume reference data (use regular tables)
- Frequently updated records (facts are immutable)
- Data requiring query-time joins (denormalize at ETL time instead)

### When to Use Pre-Aggregated Fact Tables (`tf_sales_daily`, `tf_sales_monthly`, etc.)

Use for:

- Pre-computed aggregates for common queries
- Coarser granularity (daily, monthly, per-category, etc.)
- Query performance optimization
- Materialized rollups refreshed periodically
- The same structure as fact tables (measures + `data` JSONB)

### When to Use Dimension Tables (`td_*`)

Use for:

- Reference data for ETL denormalization (products, customers, locations)
- Lookup data used to enrich fact tables during data loading
- Master data management

Avoid for:

- Query-time joins (denormalize into the fact table's `data` instead)
- Direct GraphQL exposure (expose the denormalized fact view instead)

### Index Strategy

**Denormalized filter columns**:

```sql
-- High-cardinality filters
CREATE INDEX idx_sales_customer ON tf_sales(customer_id);
CREATE INDEX idx_sales_product ON tf_sales(product_id);

-- Temporal filters
CREATE INDEX idx_sales_occurred ON tf_sales(occurred_at);

-- Composite indexes for common patterns
CREATE INDEX idx_sales_customer_occurred
    ON tf_sales(customer_id, occurred_at DESC);
```

**JSONB dimensions**:

```sql
-- GIN index for JSONB queries
CREATE INDEX idx_sales_data_gin ON tf_sales USING GIN(data);

-- Expression index for a frequently-queried dimension
CREATE INDEX idx_sales_category
    ON tf_sales ((data->>'category'));
```

**Don't over-index**:

- Every index slows `INSERT`/`UPDATE` operations
- Index only frequently-filtered columns
- Monitor query patterns before adding indexes

---

## Related Pages

- [Aggregation Model](./aggregation-model.md) — `GROUP BY`, aggregates, `HAVING`
- [Calendar Dimensions](./calendar-dimensions.md) — modeling time buckets in JSONB
- [Window Functions](./window-functions.md) — running totals and ranking in view SQL
- [View Selection Guide](../database/view-selection-guide.md) — choosing `v_` vs `tv_`
- [tv_ Table Pattern](../database/tv-table-pattern.md) — projection tables for heavy reads

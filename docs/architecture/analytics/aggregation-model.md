---
title: Aggregation Model
description: FraiseQL v1 derives GROUP BY and aggregate SQL at runtime from the GraphQL field selection, executing server-side against your PostgreSQL v_/tv_ views.
keywords: ["design", "scalability", "performance", "patterns", "security"]
tags: ["documentation", "reference"]
---

# Aggregation Model

**Status:** Stable
**Audience:** Runtime engineers, SDK users, DBAs
**Database:** PostgreSQL

---

## Overview

FraiseQL v1 supports **runtime auto-aggregation**. When a GraphQL query selects
aggregate fields on a view-backed type, FraiseQL inspects the field selection and
derives the corresponding `GROUP BY` + aggregate SQL **at request time**, then
executes it server-side against your PostgreSQL `v_`/`tv_` view. The aggregation
logic lives in `_derive_auto_aggregation` / `_parse_aggregation_expr` in
`src/fraiseql/db.py`.

There is no compiler and no build step: nothing is generated ahead of time. The
GraphQL field selection drives the SQL, and PostgreSQL does the heavy lifting.

**Key principle**: aggregation happens inside the database. You model the
measures and dimensions in a `v_`/`tv_` view, and FraiseQL pushes the grouping
and aggregate functions down to that view.

You define the type with a normal `@fraiseql.type` decorator pointing at the
view:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_sales", jsonb_column="data")
class Sales:
    id: ID
    category: str
    region: str
    revenue: float
```

When you run a query that selects aggregate fields, FraiseQL builds the
`GROUP BY` query for you. You can always fall back to writing the aggregation
directly in the view's SQL if you need full control.

---

## Aggregate Functions

FraiseQL derives the following PostgreSQL aggregate functions from the field
selection:

- `COUNT(*)` — count all rows
- `COUNT(field)` — count non-null values in a field
- `COUNT(DISTINCT field)` — count unique values
- `SUM(field)` — sum of values
- `AVG(field)` — average of values
- `MIN(field)` — minimum value
- `MAX(field)` — maximum value
- `STDDEV(field)` — standard deviation
- `VARIANCE(field)` — variance

These are standard PostgreSQL aggregates. Any aggregate expression PostgreSQL
understands can also be written by hand inside a `v_`/`tv_` view if you need
something beyond the derived set.

**Example** — an aggregate query expressed directly in SQL:

```sql
SELECT
    COUNT(*) AS total_count,
    COUNT(DISTINCT customer_id) AS unique_customers,
    SUM(revenue) AS total_revenue,
    AVG(revenue) AS avg_revenue,
    MIN(revenue) AS min_revenue,
    MAX(revenue) AS max_revenue,
    STDDEV(revenue) AS revenue_stddev,
    VARIANCE(revenue) AS revenue_variance
FROM v_sales;
```

---

## GROUP BY Semantics

### How auto-aggregation works at runtime

When a GraphQL query selects aggregate fields on a view-backed type, FraiseQL:

1. **Parses the field selection**: it identifies which selected fields are
   dimensions (grouping keys) and which are aggregate expressions (e.g.
   `SUM(revenue)`).

2. **Derives the `GROUP BY`**: dimensions become the `GROUP BY` keys. JSONB
   dimensions are extracted with `data->>'field'`; native SQL columns declared
   as native dimensions use direct column references (see
   [Native Dimensions](#native-dimensions)).

3. **Builds the aggregate SELECT**: each aggregate field becomes an aggregate
   function call on the underlying measure column or JSONB measure path.

4. **Executes server-side**: the derived SQL runs against your PostgreSQL view
   and returns aggregated rows.

The function names are validated against an allowlist before SQL is built, so a
field selection can never inject an arbitrary function.

**Example**

GraphQL:

```graphql
query {
  sales {
    category
    region
    revenueSum
    count
  }
}
```

Derived SQL (PostgreSQL):

```sql
SELECT
    data->>'category' AS category,
    data->>'region' AS region,
    SUM((data->>'revenue')::numeric) AS revenue_sum,
    COUNT(*) AS count
FROM v_sales
GROUP BY data->>'category', data->>'region';
```

If you prefer, you can encapsulate exactly the same shape inside a `tv_` view
and have FraiseQL read pre-aggregated rows directly.

---

## HAVING Clause

The `HAVING` clause filters aggregated results after `GROUP BY`. Express it
inside the view's SQL, where it filters on aggregate expressions or grouping
keys.

```sql
SELECT
    data->>'category' AS category,
    SUM((data->>'revenue')::numeric) AS revenue_sum
FROM v_sales
GROUP BY data->>'category'
HAVING SUM((data->>'revenue')::numeric) >= 10000;
```

`HAVING` references only aggregated fields or grouping keys — the same rule
PostgreSQL enforces.

---

## Temporal Bucketing

Group timestamps into intervals (day, week, month, quarter, year) using
PostgreSQL's `DATE_TRUNC`. Bucket inside the view's SQL so the truncated value
becomes a stable grouping key.

```sql
DATE_TRUNC('day', occurred_at)     -- Day bucket
DATE_TRUNC('week', occurred_at)    -- Week bucket
DATE_TRUNC('month', occurred_at)   -- Month bucket
DATE_TRUNC('quarter', occurred_at) -- Quarter bucket
DATE_TRUNC('year', occurred_at)    -- Year bucket
```

**Example** — a per-day revenue view:

```sql
SELECT
    DATE_TRUNC('day', occurred_at) AS occurred_at_day,
    SUM(revenue) AS revenue_sum
FROM v_sales
GROUP BY DATE_TRUNC('day', occurred_at)
ORDER BY occurred_at_day;
```

For richer temporal grouping (week-of-year, fiscal periods, holiday flags),
materialize the buckets as columns in your view or a calendar table — see
[Calendar Dimensions](./calendar-dimensions.md).

---

## Conditional Aggregates

Conditional aggregates apply a filter to an individual aggregate function.
PostgreSQL's native `FILTER (WHERE ...)` clause expresses these cleanly inside a
view:

```sql
SELECT
    COUNT(*) AS total_orders,
    SUM(revenue) FILTER (WHERE data->>'status' = 'completed') AS completed_revenue,
    SUM(revenue) FILTER (WHERE data->>'status' = 'cancelled') AS cancelled_revenue
FROM v_sales;
```

You can expose each filtered aggregate as a separate column in the view, then
select them as ordinary fields in GraphQL.

---

## Performance Characteristics

### Aggregate typed columns where you can

Aggregating a typed numeric column is far faster than parsing values out of
JSONB on every row. Where a measure is queried often, keep it as a real column
in the view (or in the underlying `tv_` projection table) rather than reaching
into `data`:

```sql
-- Fast: aggregating a typed column
SELECT SUM(revenue) FROM v_sales;
-- ~0.2 ms over 1M rows

-- Slower: parsing the measure out of JSONB on every row
SELECT SUM((data->>'revenue')::numeric) FROM v_sales;
-- ~45 ms over 1M rows
```

### Index measures used in aggregations

For frequent aggregations with selective filters, index the measure columns of
the backing table:

```sql
CREATE INDEX idx_sales_revenue ON tv_sales(revenue);
CREATE INDEX idx_sales_quantity ON tv_sales(quantity);
```

### JSONB dimensions

Grouping by a JSONB path is slower than grouping by a typed column, but it is
flexible. A GIN index on the `data` column helps:

```sql
CREATE INDEX idx_sales_data_gin ON tv_sales USING GIN(data);
```

When a dimension is hot, prefer promoting it to a native column and declaring it
as a native dimension (next section).

---

## Native Dimensions

When a view mixes native SQL columns (e.g. `period_date DATE`,
`category_id UUID`) with a JSONB `data` column, native columns can be declared
as **native dimensions** so auto-aggregation groups on the real column instead
of extracting it from JSONB.

### Problem

By default, dimension columns are extracted from JSONB. If `period_date` is
really a column, that is both slower (the btree index on the column can't be
used) and, for ordering, incorrect — `ORDER BY "data" -> 'period_date'`
references the raw `data` column, which is not in `GROUP BY`, and PostgreSQL
rejects the query:

```sql
-- Default: extracts from JSONB even though period_date is a real column
SELECT json_build_object('period_date', "data"->>'period_date', ...)
FROM v_orders_by_period
GROUP BY "data"->>'period_date'
ORDER BY "data" -> 'period_date'
```

### Solution

Declare the native columns in the `native_dimensions` key of the aggregation
metadata:

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

FraiseQL then groups and orders on the native columns directly, using column
references and a table alias instead of JSONB extraction:

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

### Mixed grouping

Native and JSONB dimensions coexist in the same query. Native dimensions use
`t."col"`, JSONB dimensions use `"data"->>'field'`. The table automatically
receives an `AS t` alias when native dimensions are present.

### Backward compatibility

Existing metadata without `native_dimensions` behaves identically. The key is
optional and defaults to an empty list.

---

## No Joins Principle

FraiseQL reads from a single view per query — it does not join across types at
read time. All dimensional data should already be present in the view, either as
native columns or denormalized into the `data` JSONB column. Do the joins once,
inside the view's SQL (or in the process that refreshes a `tv_` projection),
not per request.

```sql
-- The view does the join once, server-side
CREATE VIEW v_sales AS
SELECT
    s.id,
    s.revenue,
    p.category AS product_category,
    jsonb_build_object(
        'revenue', s.revenue,
        'product_category', p.category
    ) AS data
FROM tb_sales s
JOIN tb_products p ON p.pk_product = s.fk_product;
```

GraphQL queries then aggregate over `v_sales` without any further joins.

**Data-modeling responsibility**: the DBA / data team designs the `v_`/`tv_`
views and any ETL or refresh process that keeps a `tv_` projection up to date.
FraiseQL provides the runtime GraphQL interface and the auto-aggregation on top.

---

## Related Documentation

- [Fact-Dimension Pattern](./fact-dimension-pattern.md) — fact and dimension table design for analytics views
- [Calendar Dimensions](./calendar-dimensions.md) — temporal dimensions and calendar tables
- [Window Functions](./window-functions.md) — ranking and running totals as raw-SQL view patterns
- [View Selection Guide](../database/view-selection-guide.md) — choosing between `v_` and `tv_` views
- [Aggregation Operators](../../specs/aggregation-operators.md) — operator reference
- [Schema Conventions](../../specs/schema-conventions.md) — naming and schema conventions

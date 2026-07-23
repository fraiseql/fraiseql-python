---
title: Aggregation Operators Reference
description: PostgreSQL aggregate functions supported by FraiseQL v1 runtime auto-aggregation, plus the standard SQL aggregates you can use directly inside your views.
keywords: ["aggregation", "group by", "having", "postgresql", "analytics", "reference"]
tags: ["documentation", "reference"]
---

# Aggregation Operators Reference

**Status:** Stable

---

## Overview

FraiseQL v1 performs **runtime auto-aggregation** against PostgreSQL. When a GraphQL
query selects aggregate fields on a view-backed type, FraiseQL derives the matching
`GROUP BY` and aggregate SQL automatically and runs it against your `v_`/`tv_` view.
There is no build step, no compiler, and no schema artifact — everything happens at
app startup and request time. FraiseQL v1 targets **PostgreSQL only**.

Auto-aggregation is implemented by `_derive_auto_aggregation` (with
`_parse_aggregation_expr`) in `src/fraiseql/db.py`. The aggregate expressions you
declare per type are parsed and validated against an allowlist, then composed into a
parameterized `SELECT ... GROUP BY` statement against the registered view.

This document covers two related things:

1. The aggregate functions FraiseQL knows how to **derive automatically** at runtime.
2. The standard PostgreSQL aggregate, grouping, and bucketing constructs you write
   **directly in your view SQL** when you need behavior beyond auto-aggregation.

---

## Supported aggregate functions

The following PostgreSQL aggregates are available for analytics over view-backed types:

| Function   | SQL          | Returns          | Notes |
|------------|--------------|------------------|-------|
| `COUNT`    | `COUNT(...)` | integer          | Row counts; `COUNT(DISTINCT col)` for distinct counts. |
| `SUM`      | `SUM(...)`   | numeric          | Totals over a measure column. |
| `AVG`      | `AVG(...)`   | double precision | Mean of a measure column. |
| `MIN`      | `MIN(...)`   | same as input    | Smallest value in the group. |
| `MAX`      | `MAX(...)`   | same as input    | Largest value in the group. |
| `STDDEV`   | `STDDEV(...)`| double precision | Sample standard deviation. |
| `VARIANCE` | `VARIANCE(...)` | double precision | Sample variance. |

`COUNT`, `SUM`, `AVG`, `MIN`, and `MAX` are wired into runtime auto-aggregation and can
be derived from the field selection (see below). `STDDEV` and `VARIANCE` are standard
PostgreSQL aggregates: compute them in your view SQL (or a dedicated analytics view) and
expose the result as an ordinary field.

`SUM` and `AVG` operate on numeric inputs. When a measure is read from a JSONB `data`
column, FraiseQL casts the extracted text to `numeric` before applying the aggregate;
when the measure is a native numeric column (see `native_measures`), it aggregates the
column directly and avoids the cast.

---

## How runtime auto-aggregation works

Auto-aggregation kicks in when a query selects only **dimensions** and **measures** on a
view-backed type — that is, when no identity field (such as `id`) is requested. FraiseQL
then:

1. Reads the field selection from the GraphQL query.
2. Looks up the type's aggregation metadata (registered via `register_type_for_view`).
3. Splits the selected fields into `GROUP BY` dimensions and aggregate measures.
4. Builds a parameterized `SELECT <dimensions>, <aggregates> FROM <view> GROUP BY
   <dimensions>` and executes it.

Aggregate expressions are declared as strings like `SUM(cost)` or `AVG(volume)` and are
validated against the allowlist before any SQL is composed, so the function name can
never be injected.

### Registering aggregation metadata

Attach aggregation metadata to a view-backed type with `register_type_for_view`:

```python
from fraiseql.db import register_type_for_view

register_type_for_view(
    view_name="v_sales_summary",
    type_class=SalesSummary,
    aggregation={
        "measures": {
            "measures.revenue": "SUM",
            "measures.quantity": "SUM",
        },
        "dimensions": "dimensions",
        "native_dimensions": ["period_date", "category_id"],
        "native_measures": {"measures.quantity": "quantity"},
        "native_dimension_mapping": {"dimensions.category.id": "category_id"},
    },
)
```

Metadata keys:

- `measures` — maps a JSONB measure path to the aggregate function to apply
  (`"SUM"`, `"AVG"`, etc.).
- `dimensions` — the JSONB key (default `"data"` substructure) holding grouping
  attributes.
- `native_dimensions` — SQL columns that should be grouped via `t."col"` instead of
  JSONB extraction. Native columns let PostgreSQL use btree indexes and keep `ORDER BY`
  correct for dimension columns.
- `native_measures` — maps JSONB measure paths to flat SQL column names so `SUM`/`AVG`
  run on native numeric columns and skip the `::numeric` cast.
- `native_dimension_mapping` — maps deep JSONB dimension paths to flat SQL columns so
  `GROUP BY` can use native columns even for nested dimension paths.

Use `native_dimensions` whenever your view exposes a real SQL column for a grouping key:
it is the difference between a sequential scan over extracted JSONB text and an
index-backed `GROUP BY`.

---

## Aggregation in view SQL

For anything beyond derived `COUNT`/`SUM`/`AVG`/`MIN`/`MAX` — including `STDDEV`,
`VARIANCE`, conditional aggregates, time bucketing, and the array/JSON/string aggregates
below — write standard PostgreSQL in your `v_`/`tv_` view. FraiseQL reads the resulting
rows like any other view.

### GROUP BY

```sql
SELECT
    data->>'category'          AS category,
    SUM((data->>'revenue')::numeric)  AS revenue_sum,
    AVG((data->>'revenue')::numeric)  AS revenue_avg,
    COUNT(*)                   AS order_count
FROM tv_sales
GROUP BY data->>'category';
```

### HAVING

Filter groups after aggregation with `HAVING`:

```sql
SELECT
    data->>'category'                 AS category,
    SUM((data->>'revenue')::numeric)  AS revenue_sum
FROM tv_sales
GROUP BY data->>'category'
HAVING SUM((data->>'revenue')::numeric) > 10000;
```

### Conditional aggregates with FILTER

`FILTER (WHERE ...)` computes an aggregate over a subset of rows in the same pass — the
idiomatic PostgreSQL way to do conditional sums and counts:

```sql
SELECT
    data->>'region'                                          AS region,
    COUNT(*)                                                 AS total_orders,
    COUNT(*) FILTER (WHERE (data->>'status') = 'shipped')    AS shipped_orders,
    SUM((data->>'revenue')::numeric)
        FILTER (WHERE (data->>'on_sale')::boolean)           AS sale_revenue
FROM tv_sales
GROUP BY data->>'region';
```

### Time bucketing with DATE_TRUNC

Bucket a timestamp into fixed periods with `DATE_TRUNC`. Supported buckets include
`second`, `minute`, `hour`, `day`, `week`, `month`, `quarter`, and `year`:

```sql
SELECT
    DATE_TRUNC('month', (data->>'occurred_at')::timestamptz) AS bucket_month,
    SUM((data->>'revenue')::numeric)                         AS revenue_sum
FROM tv_sales
GROUP BY DATE_TRUNC('month', (data->>'occurred_at')::timestamptz)
ORDER BY bucket_month;
```

Expose the bucket as a regular column and group on it. For dimension columns that you
group on, prefer a native SQL column (and list it in `native_dimensions`) so the
`GROUP BY` and `ORDER BY` can use an index.

---

## Array, JSON, and string aggregates

PostgreSQL provides several aggregates that collapse a group into a single composite
value. Use them **directly in your view SQL**; expose the result as a field on the
view-backed type.

### ARRAY_AGG

Collect group values into an array:

```sql
SELECT
    data->>'category'                AS category,
    ARRAY_AGG(data->>'product_name') AS product_names
FROM tv_sales
GROUP BY data->>'category';
```

### JSON_AGG / JSONB_AGG

Collect rows into a JSON array — useful for building nested read models inside a `tv_`
projection view:

```sql
SELECT
    data->>'customer_id' AS customer_id,
    JSONB_AGG(jsonb_build_object(
        'product', data->>'product_name',
        'revenue', (data->>'revenue')::numeric
    )) AS orders
FROM tv_sales
GROUP BY data->>'customer_id';
```

### STRING_AGG

Concatenate group values with a delimiter, optionally ordered:

```sql
SELECT
    data->>'customer_id' AS customer_id,
    STRING_AGG(data->>'product_name', ', ' ORDER BY (data->>'revenue')::numeric DESC)
        AS products
FROM tv_sales
GROUP BY data->>'customer_id';
```

### BOOL_AND / BOOL_OR

Boolean aggregates — "all true" and "any true" across a group:

```sql
SELECT
    data->>'category'                       AS category,
    BOOL_AND((data->>'in_stock')::boolean)  AS all_in_stock,
    BOOL_OR((data->>'on_sale')::boolean)    AS any_on_sale
FROM tv_sales
GROUP BY data->>'category';
```

---

## Choosing measure and dimension columns

When modeling a view for aggregation:

- **Measures** are numeric values you aggregate (`revenue`, `quantity`). Store them as
  native numeric columns where possible and reference them through `native_measures` to
  avoid per-row JSONB casts.
- **Dimensions** are the attributes you group by (`category`, `region`, a `DATE_TRUNC`
  bucket). Surface them as native SQL columns and list them in `native_dimensions` so
  PostgreSQL can use btree indexes for `GROUP BY` and `ORDER BY`.
- Never expose internal keys (`pk_*`, `fk_*`) as dimensions; group on the public `id`
  (UUID), `identifier`, or a derived dimension column instead.

For the full naming conventions, see the schema conventions reference linked below.

---

## Related references

- [Aggregation Model](../architecture/analytics/aggregation-model.md) — how
  auto-aggregation derives `GROUP BY` and aggregate SQL at runtime.
- [Fact / Dimension Pattern](../architecture/analytics/fact-dimension-pattern.md) — data
  modeling for analytics views in PostgreSQL.
- [Window Functions](../architecture/analytics/window-functions.md) — `ROW_NUMBER`,
  `RANK`, `LAG`, `LEAD`, and `OVER (PARTITION BY ...)` patterns for view SQL.
- [Schema Conventions](./schema-conventions.md) — `tb_`/`v_`/`tv_`/`fn_` prefixes, the
  trinity identifier pattern, and the `data` JSONB convention.

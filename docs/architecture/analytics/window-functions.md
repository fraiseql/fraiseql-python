---
title: Window Functions in FraiseQL Views
description: How to use PostgreSQL window functions (ROW_NUMBER, RANK, LAG, LEAD, running totals, moving averages) inside your v_/tv_ view SQL and expose the computed columns through the view's data JSONB so FraiseQL serves them like any other field.
keywords: ["window functions", "postgresql", "views", "analytics", "ranking"]
tags: ["documentation", "reference"]
---

# Window Functions in FraiseQL Views

Window functions (analytical functions) perform calculations across rows related to
the current row, using an `OVER` clause to define the window. Unlike aggregate
functions with `GROUP BY`, window functions return a value for **every** row.

In FraiseQL v1, window functions are **not** a GraphQL feature — they are plain
PostgreSQL. You write them inside the `SELECT` of your `v_`/`tv_` read view, fold the
computed columns into the view's `data` JSONB with `jsonb_build_object(...)`, and
FraiseQL serves them at runtime like any other field. There is no special syntax, no
decorator, and nothing to configure: the work happens in your view SQL.

---

## The Pattern

A FraiseQL read view always exposes a public `id` (UUID) column plus a `data` JSONB
column. To surface a window function, compute it in a subquery (or CTE) and reference
its result when building `data`:

```sql
CREATE VIEW v_sales_ranked AS
SELECT
    s.id,
    jsonb_build_object(
        'id',          s.id,
        'category',    s.category,
        'product',     s.product_name,
        'revenue',     s.revenue,
        'rank_in_category',
            ROW_NUMBER() OVER (
                PARTITION BY s.category
                ORDER BY s.revenue DESC
            ),
        'running_total',
            SUM(s.revenue) OVER (
                PARTITION BY s.category
                ORDER BY s.occurred_at
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            )
    ) AS data
FROM tb_sales s;
```

A `@fraiseql.type(sql_source="v_sales_ranked")` then exposes `rankInCategory` and
`runningTotal` as ordinary scalar fields — FraiseQL reads them straight out of `data`.

For heavy or frequently-queried calculations, materialize the same SELECT as a `tv_`
table-backed view refreshed by a function or trigger (see
[tv-table pattern](../database/tv-table-pattern.md)).

---

## Window Function Categories

### 1. Ranking Functions

Assign ranks to rows within partitions.

- `ROW_NUMBER()` — Unique sequential number (1, 2, 3, 4...)
- `RANK()` — Ranking with gaps for ties (1, 2, 2, 4...)
- `DENSE_RANK()` — Ranking without gaps (1, 2, 2, 3...)
- `NTILE(n)` — Divide rows into n buckets (quartiles, deciles, etc.)
- `PERCENT_RANK()` — Relative rank from 0.0 to 1.0
- `CUME_DIST()` — Cumulative distribution (0.0 to 1.0)

```sql
CREATE VIEW v_sales_rankings AS
SELECT
    s.id,
    jsonb_build_object(
        'id',         s.id,
        'category',   s.category,
        'revenue',    s.revenue,
        'row_num',    ROW_NUMBER() OVER (PARTITION BY s.category ORDER BY s.revenue DESC),
        'rank',       RANK()       OVER (PARTITION BY s.category ORDER BY s.revenue DESC),
        'dense_rank', DENSE_RANK() OVER (PARTITION BY s.category ORDER BY s.revenue DESC)
    ) AS data
FROM tb_sales s;
```

### 2. Value Functions

Access values from other rows in the window.

- `LAG(field, offset, default)` — Access previous row value
- `LEAD(field, offset, default)` — Access next row value
- `FIRST_VALUE(field)` — First value in window
- `LAST_VALUE(field)` — Last value in window
- `NTH_VALUE(field, n)` — Nth value in window

```sql
CREATE VIEW v_sales_deltas AS
SELECT
    s.id,
    jsonb_build_object(
        'id',                s.id,
        'category',          s.category,
        'occurred_at',       s.occurred_at,
        'revenue',           s.revenue,
        'prev_day_revenue',  LAG(s.revenue, 1)  OVER (PARTITION BY s.category ORDER BY s.occurred_at),
        'next_day_revenue',  LEAD(s.revenue, 1) OVER (PARTITION BY s.category ORDER BY s.occurred_at)
    ) AS data
FROM tb_sales s;
```

### 3. Aggregate Functions as Windows

Apply aggregate functions with window semantics (running totals, moving averages).

- `SUM(field) OVER (...)` — Running total
- `AVG(field) OVER (...)` — Moving average
- `COUNT(*) OVER (...)` — Running count
- `MIN(field) OVER (...)` — Running minimum
- `MAX(field) OVER (...)` — Running maximum

```sql
CREATE VIEW v_sales_running AS
SELECT
    s.id,
    jsonb_build_object(
        'id',          s.id,
        'category',    s.category,
        'occurred_at', s.occurred_at,
        'revenue',     s.revenue,
        'running_total',
            SUM(s.revenue) OVER (
                PARTITION BY s.category
                ORDER BY s.occurred_at
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            )
    ) AS data
FROM tb_sales s;
```

---

## Window Specification

### PARTITION BY

Divides rows into partitions (groups). The window function applies separately to each
partition.

```sql
OVER (PARTITION BY column1, column2, ...)
```

```sql
-- Row number within each category
ROW_NUMBER() OVER (PARTITION BY s.category ORDER BY s.revenue DESC)

-- No partition = single global window
ROW_NUMBER() OVER (ORDER BY s.revenue DESC)
```

### ORDER BY

Defines row ordering within each partition. Required for ranking functions and frame
clauses.

```sql
OVER (PARTITION BY ... ORDER BY column1 [ASC|DESC], column2 [ASC|DESC], ...)
```

```sql
-- Rank by revenue descending within category
RANK() OVER (PARTITION BY s.category ORDER BY s.revenue DESC)

-- Running total ordered by date
SUM(s.revenue) OVER (PARTITION BY s.category ORDER BY s.occurred_at ASC)
```

### Frame Clauses

Define which rows are included in the window frame relative to the current row. Used
with aggregate window functions.

**Frame Types**:

- `ROWS` — Physical row-based window (count rows)
- `RANGE` — Logical value-based window (based on the `ORDER BY` value)
- `GROUPS` — Group-based window

**Frame Boundaries**:

- `UNBOUNDED PRECEDING` — Start of partition
- `n PRECEDING` — n rows/range units before current
- `CURRENT ROW` — Current row
- `n FOLLOWING` — n rows/range units after current
- `UNBOUNDED FOLLOWING` — End of partition

**Default Frame** (if not specified):

- With `ORDER BY`: `RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`
- Without `ORDER BY`: `ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING`

```sql
-- Cumulative sum (all rows up to current)
SUM(s.revenue) OVER (
    PARTITION BY s.category
    ORDER BY s.occurred_at
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
)

-- 7-day moving average (last 7 rows including current)
AVG(s.revenue) OVER (
    PARTITION BY s.category
    ORDER BY s.occurred_at
    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
)

-- Centered 3-row moving average (current ± 1 row)
AVG(s.revenue) OVER (
    PARTITION BY s.category
    ORDER BY s.occurred_at
    ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING
)

-- All rows in partition (default without ORDER BY)
SUM(s.revenue) OVER (
    PARTITION BY s.category
    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
)
```

---

## Evaluation Order

PostgreSQL evaluates window functions at a fixed point in the query pipeline. Knowing
this order matters when you combine them with filters and aggregates inside a view:

```text
WHERE → GROUP BY → HAVING → Window Functions → ORDER BY → LIMIT
```

- `WHERE` filters rows **before** window functions see them.
- `GROUP BY` / `HAVING` aggregate **before** window functions run, so a window can
  operate over already-aggregated rows (e.g. `LAG(SUM(revenue), 12)`).
- Because window functions run after `WHERE`, you cannot filter on a window result in
  the same query level — wrap the view (or a subquery) and filter the outer level (see
  [Top-N Per Category](#4-top-n-per-category)).

---

## PostgreSQL Support

PostgreSQL has full window-function support, which is everything these patterns need:

- All ranking functions (`ROW_NUMBER`, `RANK`, `DENSE_RANK`, `NTILE`, `PERCENT_RANK`, `CUME_DIST`)
- All value functions (`LAG`, `LEAD`, `FIRST_VALUE`, `LAST_VALUE`, `NTH_VALUE`)
- All frame types (`ROWS`, `RANGE`, `GROUPS`)
- The `EXCLUDE` clause (`EXCLUDE CURRENT ROW`, `EXCLUDE GROUP`, `EXCLUDE TIES`, `EXCLUDE NO OTHERS`)

```sql
CREATE VIEW v_sales_excluded AS
SELECT
    s.id,
    jsonb_build_object(
        'id',       s.id,
        'category', s.category,
        'revenue',  s.revenue,
        'cumulative_revenue_excluding_current',
            SUM(s.revenue) OVER (
                PARTITION BY s.category
                ORDER BY s.occurred_at
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                EXCLUDE CURRENT ROW
            )
    ) AS data
FROM tb_sales s;
```

---

## Use Cases

Each example below is the body of a view's `SELECT`. Wrap it in
`CREATE VIEW v_... AS SELECT s.id, jsonb_build_object(...) AS data FROM ...` to expose
the result through FraiseQL.

### 1. Running Totals

Calculate a cumulative sum up to the current row.

```sql
SELECT
    s.category,
    s.occurred_at,
    s.revenue,
    SUM(s.revenue) OVER (
        PARTITION BY s.category
        ORDER BY s.occurred_at
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_revenue
FROM tb_sales s
ORDER BY s.category, s.occurred_at;
```

### 2. Moving Averages

Calculate an average over a sliding window (e.g. a 7-day moving average). Note the
window runs over already-aggregated daily totals.

```sql
SELECT
    s.category,
    s.occurred_at::DATE AS day,
    SUM(s.revenue) AS daily_revenue,
    AVG(SUM(s.revenue)) OVER (
        PARTITION BY s.category
        ORDER BY s.occurred_at::DATE
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS moving_avg_7d
FROM tb_sales s
GROUP BY s.category, s.occurred_at::DATE
ORDER BY s.category, s.occurred_at::DATE;
```

### 3. Year-Over-Year Comparison

Compare the current period to the same period last year using `LAG`.

```sql
SELECT
    DATE_TRUNC('month', s.occurred_at) AS month,
    SUM(s.revenue) AS monthly_revenue,
    LAG(SUM(s.revenue), 12) OVER (ORDER BY DATE_TRUNC('month', s.occurred_at)) AS same_month_last_year,
    SUM(s.revenue) - LAG(SUM(s.revenue), 12) OVER (ORDER BY DATE_TRUNC('month', s.occurred_at)) AS yoy_change
FROM tb_sales s
GROUP BY DATE_TRUNC('month', s.occurred_at)
ORDER BY month;
```

### 4. Top-N Per Category

Rank items within each category and filter to the top N. Because window results cannot
be filtered at the same query level, compute the rank in an inner subquery and filter
the outer one.

```sql
SELECT * FROM (
    SELECT
        s.category,
        s.product_name AS product,
        SUM(s.revenue) AS total_revenue,
        ROW_NUMBER() OVER (
            PARTITION BY s.category
            ORDER BY SUM(s.revenue) DESC
        ) AS rank
    FROM tb_sales s
    GROUP BY s.category, s.product_name
) ranked
WHERE rank <= 10
ORDER BY category, rank;
```

### 5. Percentile Ranking

Assign percentile ranks and quartiles to rows.

```sql
SELECT
    s.product_name AS product,
    SUM(s.revenue) AS total_revenue,
    PERCENT_RANK() OVER (ORDER BY SUM(s.revenue) DESC) AS percentile_rank,
    NTILE(4)       OVER (ORDER BY SUM(s.revenue) DESC) AS quartile
FROM tb_sales s
GROUP BY s.product_name
ORDER BY total_revenue DESC;
```

### 6. Trend Analysis

Compare to the previous period to identify trends.

```sql
SELECT
    s.occurred_at::DATE AS day,
    SUM(s.revenue) AS daily_revenue,
    LAG(SUM(s.revenue), 1) OVER (ORDER BY s.occurred_at::DATE) AS prev_day_revenue,
    SUM(s.revenue) - LAG(SUM(s.revenue), 1) OVER (ORDER BY s.occurred_at::DATE) AS day_over_day_change,
    ROUND(
        100.0 * (SUM(s.revenue) - LAG(SUM(s.revenue), 1) OVER (ORDER BY s.occurred_at::DATE)) /
        NULLIF(LAG(SUM(s.revenue), 1) OVER (ORDER BY s.occurred_at::DATE), 0),
        2
    ) AS day_over_day_pct
FROM tb_sales s
GROUP BY s.occurred_at::DATE
ORDER BY s.occurred_at::DATE;
```

---

## Performance Considerations

### Indexing Strategy

Index the columns your windows partition and order by. Window functions read the table
in partition/order sequence, so matching indexes let PostgreSQL avoid extra sorts.

```sql
-- Index columns used in PARTITION BY
CREATE INDEX idx_sales_category ON tb_sales (category);

-- Index columns used in ORDER BY within the window
CREATE INDEX idx_sales_occurred ON tb_sales (occurred_at);

-- Composite index for a common (partition, order) pattern
CREATE INDEX idx_sales_category_occurred ON tb_sales (category, occurred_at);
```

### Cost Notes

- Window functions are evaluated **after** `WHERE`/`GROUP BY`/`HAVING`, so filtering
  early reduces the rows the window has to scan.
- Large frames (`UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING`) are more expensive than
  bounded frames.
- Proper indexes on `PARTITION BY` and `ORDER BY` columns are critical for large tables.

### Optimization Tips

1. **Use specific frame clauses** — bound the frame whenever the calculation allows it:

   ```sql
   -- Slower: unbounded frame
   SUM(s.revenue) OVER (
       ORDER BY s.occurred_at
       ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
   )

   -- Faster: bounded frame
   SUM(s.revenue) OVER (
       ORDER BY s.occurred_at
       ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
   )
   ```

2. **Partition data appropriately** — balance partition size (not too large, not too
   many) and use meaningful partitions (category, region, etc.).

3. **Promote heavy views to `tv_` table-backed views** — for window calculations that
   are queried often, precompute them into a `tv_` projection table refreshed by a
   function or trigger, rather than recomputing on every read. See
   [tv-table pattern](../database/tv-table-pattern.md) and the
   [view-selection guide](../database/view-selection-guide.md) for when to choose a
   plain `v_` view versus a `tv_` table.

4. **Reduce data volume first** — prefer `ROWS BETWEEN 6 PRECEDING` over
   `UNBOUNDED PRECEDING` when possible, and use a `WHERE` clause to shrink the input
   before window computation.

---

## Related Documentation

- [Aggregation Model](./aggregation-model.md) — `GROUP BY`, `HAVING`, and basic aggregates
- [Fact / Dimension Pattern](./fact-dimension-pattern.md) — modeling fact tables for analytics
- [Calendar Dimensions](./calendar-dimensions.md) — date attributes for time-based windows
- [tv-table Pattern](../database/tv-table-pattern.md) — materializing heavy views into projection tables
- [View Selection Guide](../database/view-selection-guide.md) — choosing `v_` vs `tv_`

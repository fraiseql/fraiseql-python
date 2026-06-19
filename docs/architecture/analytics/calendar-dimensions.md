---
title: Calendar Dimensions for High-Performance Analytics
description: Calendar dimensions provide 10-20x performance improvements for time-based aggregations by using pre-computed temporal fields stored in JSONB columns instead of runtime DATE_TRUNC operations.
keywords: ["design", "scalability", "performance", "patterns", "postgresql"]
tags: ["documentation", "reference"]
---

# Calendar Dimensions for High-Performance Analytics

**Status:** Stable
**Audience:** DBAs, data engineers, FraiseQL users

---

## Overview

Calendar dimensions provide **10-20x performance improvements** for time-based
aggregations by storing pre-computed temporal fields in JSONB columns instead of
re-deriving them with `DATE_TRUNC()` on every read.

This is a **PostgreSQL data-modeling pattern**, not a FraiseQL API. You compute the
calendar fields in your table or view SQL (a DBA / data-modeling responsibility), and
FraiseQL simply queries the resulting `v_`/`tv_` view at runtime through its CQRS
repository. There is no build step and no auto-detection — the speedup comes entirely
from the SQL you write.

**Performance impact:**

- **Without calendar dimensions:** ~500ms for 1M rows (runtime `DATE_TRUNC`)
- **With calendar dimensions:** ~30ms for 1M rows (pre-computed JSONB extraction)
- **Speedup:** ~16x faster temporal aggregations

---

## Quick Start

### 1. Add a calendar column to your fact table

**Simplest approach** — a single `date_info` column:

```sql
ALTER TABLE tf_sales ADD COLUMN date_info JSONB;
```

**Advanced approach** — multiple granularity columns:

```sql
ALTER TABLE tf_sales
  ADD COLUMN date_info JSONB,
  ADD COLUMN week_info JSONB,
  ADD COLUMN month_info JSONB,
  ADD COLUMN quarter_info JSONB,
  ADD COLUMN year_info JSONB;
```

### 2. Populate calendar fields on write

Create a trigger (or ETL function) that populates the calendar fields on insert/update,
so the work happens once per row rather than on every read:

```sql
CREATE OR REPLACE FUNCTION populate_calendar_fields()
RETURNS TRIGGER AS $$
BEGIN
    -- Populate date_info with all temporal buckets
    NEW.date_info = jsonb_build_object(
        'date', NEW.occurred_at::date::text,
        'week', EXTRACT(WEEK FROM NEW.occurred_at),
        'month', EXTRACT(MONTH FROM NEW.occurred_at),
        'quarter', EXTRACT(QUARTER FROM NEW.occurred_at),
        'year', EXTRACT(YEAR FROM NEW.occurred_at)
    );

    -- Optional: populate month_info for month-level queries
    NEW.month_info = jsonb_build_object(
        'month', EXTRACT(MONTH FROM NEW.occurred_at),
        'quarter', EXTRACT(QUARTER FROM NEW.occurred_at),
        'year', EXTRACT(YEAR FROM NEW.occurred_at)
    );

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_calendar_fields
  BEFORE INSERT OR UPDATE ON tf_sales
  FOR EACH ROW
  EXECUTE FUNCTION populate_calendar_fields();
```

### 3. Expose the pre-computed buckets through a read view

Surface the calendar buckets in the `v_`/`tv_` view that FraiseQL reads. The `data`
JSONB column already carries the bucket values, so temporal aggregations group by a
plain JSONB extraction instead of `DATE_TRUNC`:

```sql
CREATE VIEW v_sales AS
SELECT
    s.id,
    jsonb_build_object(
        'id', s.id,
        'revenue', s.revenue,
        'occurredAt', s.occurred_at,
        'month', s.date_info->>'month',
        'quarter', s.date_info->>'quarter',
        'year', s.date_info->>'year'
    ) AS data
FROM tf_sales s;
```

Map the view to a FraiseQL type and query it at runtime:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_sales", jsonb_column="data")
class Sale:
    id: ID
    revenue: float
    occurred_at: str
    month: int
    quarter: int
    year: int

@fraiseql.query
async def sales(info) -> list[Sale]:
    db = info.context["db"]
    return await db.find("v_sales")
```

FraiseQL reads the pre-computed buckets straight from the view — no `DATE_TRUNC`
runs on the read path.

**Fast path (pre-computed, ~30ms):**

```sql
SELECT
  data->>'month' AS month,
  COUNT(*),
  SUM(revenue)
FROM v_sales
GROUP BY data->>'month';
```

**Slow path (runtime DATE_TRUNC, ~500ms):**

```sql
SELECT
  DATE_TRUNC('month', occurred_at) AS month,
  COUNT(*),
  SUM(revenue)
FROM tf_sales
GROUP BY DATE_TRUNC('month', occurred_at);
```

---

## Calendar Column Structure

### Single-column approach (recommended for most cases)

A single `date_info` column can serve all temporal queries:

```json
{
  "date": "2024-03-15",
  "week": 11,
  "month": 3,
  "quarter": 1,
  "year": 2024
}
```

**Supports these buckets** via JSONB extraction in your view:

- day → `date_info->>'date'`
- week → `date_info->>'week'`
- month → `date_info->>'month'`
- quarter → `date_info->>'quarter'`
- year → `date_info->>'year'`

**Storage:** ~150 bytes per row (negligible overhead).

### Multi-column approach (advanced pattern)

For maximum flexibility and organization, use separate columns per granularity:

| Column | Buckets available | Use case |
|--------|------------------|----------|
| `date_info` | date, week, month, quarter, year | Day-level queries |
| `week_info` | week, month, quarter, year | Week-level queries |
| `month_info` | month, quarter, year | Month-level queries |
| `quarter_info` | quarter, year | Quarter-level queries |
| `semester_info` | semester, year | Semester-level queries |
| `year_info` | year | Year-level queries |
| `decade_info` | decade | Decade-level queries (optional) |

**Example `month_info`:**

```json
{
  "month": 3,
  "quarter": 1,
  "year": 2024
}
```

**Advantages:**

- Clear separation of granularity levels
- Easier to manage in complex ETL pipelines
- Proven pattern for high-performance analytics

**Storage:** ~800 bytes per row (7 columns × ~120 bytes average).

---

## Flexible Coverage

Calendar columns are entirely under your control — add whatever combination of
granularities your workload needs and reference them from your view SQL.

### Single column

```sql
-- Only date_info
ALTER TABLE tf_sales ADD COLUMN date_info JSONB;
```

- One granularity with five buckets (day, week, month, quarter, year)
- All temporal queries extract from this column

### Selective columns

```sql
-- Only the columns you need
ALTER TABLE tf_sales
  ADD COLUMN date_info JSONB,
  ADD COLUMN month_info JSONB;
```

- Two granularities
- Day/week queries use `date_info`
- Month/quarter queries use `month_info`

### Full multi-column structure

```sql
-- All seven columns
ALTER TABLE tf_sales
  ADD COLUMN date_info JSONB,
  ADD COLUMN week_info JSONB,
  ADD COLUMN month_info JSONB,
  ADD COLUMN quarter_info JSONB,
  ADD COLUMN semester_info JSONB,
  ADD COLUMN year_info JSONB,
  ADD COLUMN decade_info JSONB;
```

- Seven granularities
- Maximum flexibility and organization

### Custom columns

```sql
-- Any JSONB column works; reference it from your view
ALTER TABLE tf_sales ADD COLUMN my_custom_info JSONB;
```

- Use JSONB so PostgreSQL can index and extract it efficiently
- Surface the buckets you care about in the `v_`/`tv_` view's `data` column

---

## Backward Compatibility

Calendar dimensions are an **opt-in** optimization. A view that uses `DATE_TRUNC`
keeps working exactly as before; adding calendar columns only changes the SQL inside
your view, never the GraphQL contract.

### Without calendar columns

```sql
-- Traditional fact table (no calendar columns)
CREATE TABLE tf_sales (
    revenue DECIMAL(10,2),
    occurred_at TIMESTAMPTZ
);
```

The view derives buckets at read time:

```sql
SELECT DATE_TRUNC('month', occurred_at) AS month
FROM tf_sales
GROUP BY DATE_TRUNC('month', occurred_at);
```

### With calendar columns

```sql
-- Enhanced table (with calendar optimization)
CREATE TABLE tf_sales (
    revenue DECIMAL(10,2),
    occurred_at TIMESTAMPTZ,
    date_info JSONB  -- added
);
```

The same view now reads pre-computed buckets — **~16x faster**:

```sql
SELECT date_info->>'month' AS month
FROM tf_sales
GROUP BY date_info->>'month';
```

The GraphQL type and query stay identical; only the view SQL changes.

---

## Best Practices

### 1. Start simple, optimize later

1. **Profile first** — use plain `DATE_TRUNC()` in your view and identify slow temporal queries.
2. **Add a single column** — introduce `date_info`, populate it via trigger/ETL, and measure the speedup.
3. **Expand if needed** — add `month_info`, `quarter_info`, etc. only for the granularities you actually query.

### 2. Populate on write, not on read

Good — populate on `INSERT`/`UPDATE`:

```sql
CREATE TRIGGER trg_calendar_fields
  BEFORE INSERT OR UPDATE ON tf_sales
  FOR EACH ROW
  EXECUTE FUNCTION populate_calendar_fields();
```

Bad — compute on `SELECT` (this defeats the purpose):

```sql
-- Re-derives the buckets on every read; no benefit over DATE_TRUNC
SELECT
  jsonb_build_object('month', EXTRACT(MONTH FROM occurred_at)) AS date_info
FROM tf_sales;
```

### 3. Backfill existing data

After adding calendar columns, backfill historical rows:

```sql
-- Backfill date_info for existing rows
UPDATE tf_sales
SET date_info = jsonb_build_object(
    'date', occurred_at::date::text,
    'week', EXTRACT(WEEK FROM occurred_at),
    'month', EXTRACT(MONTH FROM occurred_at),
    'quarter', EXTRACT(QUARTER FROM occurred_at),
    'year', EXTRACT(YEAR FROM occurred_at)
)
WHERE date_info IS NULL;
```

For large tables, batch the update:

```sql
DO $$
DECLARE
    batch_size INT := 10000;
    rows_updated INT;
BEGIN
    LOOP
        UPDATE tf_sales
        SET date_info = jsonb_build_object(
            'date', occurred_at::date::text,
            'week', EXTRACT(WEEK FROM occurred_at),
            'month', EXTRACT(MONTH FROM occurred_at),
            'quarter', EXTRACT(QUARTER FROM occurred_at),
            'year', EXTRACT(YEAR FROM occurred_at)
        )
        WHERE ctid IN (
            SELECT ctid
            FROM tf_sales
            WHERE date_info IS NULL
            LIMIT batch_size
        );

        GET DIAGNOSTICS rows_updated = ROW_COUNT;
        EXIT WHEN rows_updated = 0;

        RAISE NOTICE 'Updated % rows', rows_updated;
        COMMIT;
    END LOOP;
END $$;
```

### 4. Index calendar columns

Add indexes for the temporal buckets you query most:

```sql
-- GIN index for flexible JSONB containment queries
CREATE INDEX idx_sales_date_info ON tf_sales USING GIN (date_info);

-- Expression index for a specific bucket
CREATE INDEX idx_sales_month
ON tf_sales ((date_info->>'month'));

-- Composite index for a common query pattern
CREATE INDEX idx_sales_year_month
ON tf_sales ((date_info->>'year'), (date_info->>'month'));
```

### 5. Monitor storage impact

Calendar dimensions add minimal storage overhead:

```sql
-- Check table size before/after
SELECT
    pg_size_pretty(pg_total_relation_size('tf_sales')) AS total_size,
    pg_size_pretty(pg_relation_size('tf_sales')) AS table_size,
    pg_size_pretty(pg_indexes_size('tf_sales')) AS indexes_size;
```

Typical impact:

- Single `date_info` column: ~150 bytes/row (~3% overhead for typical fact tables)
- Full seven-column structure: ~800 bytes/row (~15% overhead)

---

## Performance Characteristics

### Query performance

| Rows | Without calendar | With calendar | Speedup |
|------|-----------------|---------------|---------|
| 100K | 50ms | 5ms | 10x |
| 1M | 500ms | 30ms | 16x |
| 10M | 5000ms | 300ms | 16x |
| 100M | 50000ms | 3000ms | 16x |

**Benchmark:** PostgreSQL 16, single-node, temporal `GROUP BY` query.

### Storage trade-offs

**Single `date_info` column:**

- Storage: +3% table size
- Performance: 10-16x faster temporal queries
- ROI: excellent for most use cases

**Full seven-column structure:**

- Storage: +15% table size
- Performance: 10-16x faster temporal queries
- ROI: best for complex analytics workloads

### Write performance impact

Calendar columns add **minimal write overhead** — the trigger does a few `EXTRACT`
calls and a `jsonb_build_object` per row:

- Without calendar: ~5000 inserts/sec
- With calendar: ~4800 inserts/sec (~4% slower)

JSONB field population on write is far cheaper than re-running `DATE_TRUNC` on every read.

---

## Troubleshooting

### Queries still use DATE_TRUNC

**Problem:** Added a `date_info` column but queries still run `DATE_TRUNC()`.

**Solution:** Reference the pre-computed bucket in your view SQL. The optimization
lives in the view, not in FraiseQL — update the `v_`/`tv_` view to extract from
`date_info` instead of calling `DATE_TRUNC`:

```sql
-- Check the column exists and is JSONB
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'tf_sales' AND column_name LIKE '%\_info';
```

### Incorrect temporal results

**Problem:** Queries return wrong temporal aggregations after adding calendar columns.

**Solution:** Verify the calendar fields are correctly populated:

```sql
-- Verify date_info contents
SELECT
    occurred_at,
    date_info,
    date_info->>'date' AS extracted_date,
    date_info->>'month' AS extracted_month
FROM tf_sales
LIMIT 10;
```

Check for unpopulated rows:

```sql
SELECT COUNT(*)
FROM tf_sales
WHERE date_info IS NULL AND occurred_at IS NOT NULL;
```

### Performance not improving

**Problem:** Added calendar columns but queries are still slow.

Possible causes:

1. **Missing indexes:**

```sql
-- Add GIN index
CREATE INDEX idx_sales_date_info ON tf_sales USING GIN (date_info);
```

2. **Large result sets** — calendar optimization helps `GROUP BY`, not large output sets:

```sql
-- If returning millions of rows, limit the results
SELECT ... FROM tf_sales ... LIMIT 1000;
```

3. **Heavy WHERE clauses** — calendar columns only speed up `GROUP BY`; make sure your filter columns are indexed:

```sql
CREATE INDEX idx_sales_occurred_at ON tf_sales (occurred_at);
```

---

## Migration Guide

### From DATE_TRUNC to calendar dimensions

**Step 1 — add the calendar column:**

```sql
ALTER TABLE tf_sales ADD COLUMN date_info JSONB;
```

**Step 2 — create the populate trigger:**

```sql
CREATE OR REPLACE FUNCTION populate_calendar_fields()
RETURNS TRIGGER AS $$
BEGIN
    NEW.date_info = jsonb_build_object(
        'date', NEW.occurred_at::date::text,
        'week', EXTRACT(WEEK FROM NEW.occurred_at),
        'month', EXTRACT(MONTH FROM NEW.occurred_at),
        'quarter', EXTRACT(QUARTER FROM NEW.occurred_at),
        'year', EXTRACT(YEAR FROM NEW.occurred_at)
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_calendar_fields
  BEFORE INSERT OR UPDATE ON tf_sales
  FOR EACH ROW
  EXECUTE FUNCTION populate_calendar_fields();
```

**Step 3 — backfill (batch large tables):**

```sql
-- Small tables (<1M rows)
UPDATE tf_sales
SET date_info = jsonb_build_object(
    'date', occurred_at::date::text,
    'week', EXTRACT(WEEK FROM occurred_at),
    'month', EXTRACT(MONTH FROM occurred_at),
    'quarter', EXTRACT(QUARTER FROM occurred_at),
    'year', EXTRACT(YEAR FROM occurred_at)
)
WHERE date_info IS NULL;

-- Large tables: use the batching script from Best Practices
```

**Step 4 — add the index:**

```sql
CREATE INDEX idx_sales_date_info ON tf_sales USING GIN (date_info);
```

**Step 5 — update the read view** to extract pre-computed buckets:

```sql
CREATE OR REPLACE VIEW v_sales AS
SELECT
    s.id,
    jsonb_build_object(
        'id', s.id,
        'revenue', s.revenue,
        'occurredAt', s.occurred_at,
        'month', s.date_info->>'month',
        'quarter', s.date_info->>'quarter',
        'year', s.date_info->>'year'
    ) AS data
FROM tf_sales s;
```

FraiseQL already queries `v_sales` at runtime, so no application changes are required.

**Step 6 — verify the speedup:**

```sql
-- Before: ~500ms for 1M rows
EXPLAIN ANALYZE
SELECT
    DATE_TRUNC('month', occurred_at) AS month,
    COUNT(*), SUM(revenue)
FROM tf_sales
GROUP BY DATE_TRUNC('month', occurred_at);

-- After: ~30ms for 1M rows
EXPLAIN ANALYZE
SELECT
    date_info->>'month' AS month,
    COUNT(*), SUM(revenue)
FROM tf_sales
GROUP BY date_info->>'month';
```

---

## How It Fits the FraiseQL Runtime

Calendar dimensions live entirely in PostgreSQL. The database is the source of truth,
and FraiseQL reads whatever your views expose at runtime:

1. **You design the schema** — calendar columns and their populate triggers live in your
   migrations. This is a DBA / data-modeling responsibility.
2. **The view shapes the data** — your `v_`/`tv_` view builds the `data` JSONB and decides
   whether a bucket comes from a pre-computed `*_info` column or a runtime `DATE_TRUNC`.
3. **FraiseQL queries at runtime** — `db.find("v_sales")` returns the view's `data` JSONB,
   and the Rust hot path shapes it to the requested GraphQL fields. No build step, no
   schema artifact, no auto-detection.
4. **Zero overhead when absent** — if a table has no calendar columns, the view falls back
   to `DATE_TRUNC` and everything still works; the optimization is purely additive.

Because the speedup is encoded in SQL, you can adopt it table by table without touching
application code or the GraphQL contract.

---

## Advanced Topics

### Custom calendar buckets

You can add custom temporal buckets beyond the standard ones, then surface them in your view:

```sql
-- Add a fiscal year that starts April 1
NEW.date_info = NEW.date_info || jsonb_build_object(
    'fiscal_year',
    CASE
        WHEN EXTRACT(MONTH FROM NEW.occurred_at) >= 4 THEN EXTRACT(YEAR FROM NEW.occurred_at)
        ELSE EXTRACT(YEAR FROM NEW.occurred_at) - 1
    END
);
```

Expose `data->>'fiscalYear'` from the view and add a matching field on the FraiseQL type;
FraiseQL will return it like any other column.

### Partial calendar coverage

If only some rows have calendar data, fall back per-row inside the view:

```sql
-- Some rows have calendar data, others don't
SELECT
    COALESCE(date_info->>'month', DATE_TRUNC('month', occurred_at)::text) AS month,
    COUNT(*)
FROM tf_sales
GROUP BY month;
```

**Recommendation:** keep calendar fields consistent — either populate all rows or none —
so the fast path is predictable.

### Calendar dimensions with window functions

Calendar buckets speed up `GROUP BY`. For ordered window functions, partition by the
pre-computed bucket and order by the raw timestamp:

```sql
SELECT
    date_info->>'month' AS month,
    SUM(revenue) OVER (
        PARTITION BY date_info->>'month'
        ORDER BY occurred_at
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_revenue
FROM tf_sales;
```

See [Window Functions](./window-functions.md) for the full set of view-side patterns.

---

## See Also

- [Aggregation Model](./aggregation-model.md) — core aggregation concepts
- [Fact-Dimension Pattern](./fact-dimension-pattern.md) — fact table design
- [Window Functions](./window-functions.md) — view-side analytics SQL
- [tv_ Table Pattern](../database/tv-table-pattern.md) — table-backed projection views
- [View Selection Guide](../database/view-selection-guide.md) — choosing `v_` vs `tv_`
- [Schema Conventions](../../specs/schema-conventions.md) — naming and `data` JSONB rules
- [Performance Characteristics](../performance/performance-characteristics.md) — query performance analysis

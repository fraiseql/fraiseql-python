---
title: Analytics Platform with OLAP
description: Build a scalable analytics and business-intelligence platform with FraiseQL using PostgreSQL fact/dimension modelling, view-backed reads, and runtime auto-aggregation.
keywords: ["analytics", "olap", "aggregation", "fact-table", "dimension", "postgresql"]
tags: ["documentation", "patterns"]
---

# Analytics Platform with OLAP

**Status:** Production Ready
**Complexity:** Advanced
**Audience:** Data engineers, analytics architects, BI developers
**Reading Time:** 30-35 minutes

This guide shows how to build an OLAP-style analytics and business-intelligence
platform on top of FraiseQL. Everything here is **PostgreSQL-only** and runs at
**application runtime** — there is no compile step, no columnar engine, and no
separate analytics server. You model your analytics in PostgreSQL (fact and
dimension tables you maintain via ETL, plus `v_`/`tv_` read views), and FraiseQL
serves them as a GraphQL API. When a query selects dimensions and measures,
FraiseQL derives the `GROUP BY` + aggregate SQL automatically at runtime.

---

## How FraiseQL Fits OLAP

| Concern | Where it lives |
|---------|----------------|
| Raw events / fact rows | PostgreSQL tables you load via ETL (e.g. `tb_event`) |
| Reference / dimension data | PostgreSQL dimension tables (e.g. `tb_dim_product`) |
| Read model exposed to GraphQL | `v_` views (logical) or `tv_` projection tables (pre-composed) |
| Aggregation (`GROUP BY` + `SUM`/`AVG`/…) | Derived at **runtime** by FraiseQL from the selected fields |
| Heavy pre-computed rollups | Aggregate tables / materialized views you refresh on a schedule |

FraiseQL's reads always go through a view (or `tv_` projection table) that exposes
a public `id` column and a `data` JSONB column built with `jsonb_build_object(...)`.
The internal `pk_*`/`fk_*` BIGINT keys used for fast joins are **never** exposed and
**never** placed inside `data`.

---

## Runtime Auto-Aggregation

This is the core OLAP capability. When a GraphQL query against a view-backed type
selects aggregate fields, FraiseQL builds the `GROUP BY` and the aggregate
expressions for you at runtime — no compiler, no plan artifacts, no special
decorator. The supported PostgreSQL aggregates are:

`COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, `STDDEV`, `VARIANCE`

You declare which measures a view-backed type can aggregate, and which fields act
as group-by dimensions, when you register the type for its view:

```python
import fraiseql
from fraiseql.types import ID, Date

@fraiseql.type(sql_source="v_event", jsonb_column="data")
class Event:
    """A single analytics event, read from v_event."""
    id: ID
    event_date: Date
    product_id: str
    category: str
    region: str
    source: str
    device_type: str
    revenue: float
    quantity: int
    sessions: int
```

```python
from fraiseql import register_type_for_view

# Declare the aggregations FraiseQL may derive at runtime for this view.
register_type_for_view(
    Event,
    view_name="v_event",
    aggregation={
        "group_by": ["event_date", "product_id", "category", "region", "source"],
        "measures": {
            "revenue": ["SUM", "AVG", "MIN", "MAX"],
            "quantity": ["SUM", "AVG"],
            "sessions": ["SUM"],
            "id": ["COUNT"],
        },
    },
)
```

A GraphQL query then picks the dimensions and measures it wants, and FraiseQL
derives the SQL:

```graphql
query RevenueByProduct($start: Date!, $end: Date!) {
  events(
    where: { eventDate: { gte: $start, lte: $end } }
    groupBy: [PRODUCT_ID, CATEGORY]
  ) {
    productId
    category
    revenueSum
    revenueAvg
    quantitySum
    count
  }
}
```

FraiseQL's repository (`_derive_auto_aggregation` / `_parse_aggregation_expr` in
`db.py`) turns the selected dimensions into a `GROUP BY` clause and the selected
measures into the matching aggregate expressions, then executes the query against
`v_event`. The `where` clause maps to a parameterized `WHERE` on the view.

> All aggregation is plain PostgreSQL. Anything you can express with `GROUP BY`,
> `HAVING`, `FILTER (WHERE …)`, and window functions can be embedded in the view
> SQL; FraiseQL's auto-aggregation handles the common dimension/measure rollups
> on top of that.

---

## Schema Design: Fact and Dimension Tables

The classic OLAP modelling pattern works directly in PostgreSQL. You maintain the
fact and dimension tables through your own ETL/load process, and FraiseQL reads
them through views.

### Fact Table

A fact table holds the numeric measures plus the foreign keys (or denormalized
dimension values) needed to slice them.

```sql
CREATE TABLE tb_event (
    pk_event       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id             UUID NOT NULL DEFAULT gen_random_uuid(),

    -- Measures: numeric columns for fast aggregation
    revenue        NUMERIC(12, 2),
    quantity       INT,
    cost           NUMERIC(12, 2),
    sessions       INT,

    -- Dimensions: foreign keys to dimension tables + flexible JSONB attributes
    fk_product     BIGINT REFERENCES tb_dim_product (pk_product),
    fk_user        BIGINT REFERENCES tb_dim_user (pk_user),
    attributes     JSONB NOT NULL DEFAULT '{}'::jsonb,  -- utm_source, device, etc.

    -- Filters: indexed columns for fast WHERE / time-range scans
    occurred_at    TIMESTAMPTZ NOT NULL,
    event_date     DATE NOT NULL  -- partition key
) PARTITION BY RANGE (event_date);

CREATE TABLE tb_event_2026_01 PARTITION OF tb_event
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE tb_event_2026_02 PARTITION OF tb_event
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
-- ... one partition per period

CREATE INDEX idx_event_date ON tb_event (event_date);
CREATE INDEX idx_event_occurred_at ON tb_event (occurred_at);
CREATE INDEX idx_event_attributes ON tb_event USING GIN (attributes);
```

Notes on the columns:

1. **Measures** (`revenue`, `quantity`, `cost`, `sessions`): keep these as direct
   numeric columns so `SUM`/`AVG`/`COUNT` stay fast.
2. **Dimensions**: model stable, frequently-joined dimensions as foreign keys to
   dimension tables; keep sparse or fast-evolving attributes in a `JSONB` column
   so you can add slices without a schema migration.
3. **Filters**: index the columns you filter on most (`event_date`,
   `occurred_at`). Avoid hot WHERE predicates that have to dig into JSONB.
4. **Partitioning**: range-partition by `event_date` so time-range queries only
   scan the relevant partitions, and old partitions can be detached/archived.

### Dimension Tables

```sql
CREATE TABLE tb_dim_product (
    pk_product   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id           UUID NOT NULL DEFAULT gen_random_uuid(),
    identifier   TEXT UNIQUE,            -- optional human-readable slug
    product_name TEXT NOT NULL,
    category     TEXT NOT NULL,
    region       TEXT
);

CREATE TABLE tb_dim_user (
    pk_user      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id           UUID NOT NULL DEFAULT gen_random_uuid(),
    signup_date  DATE NOT NULL,
    country      VARCHAR(2)
);
```

### Calendar / Date Dimension

A date dimension is useful for fiscal periods, week numbers, and holiday flags.
Compute the calendar attributes in your table or view SQL — they are a
DBA/ETL responsibility, not something FraiseQL auto-detects.

```sql
CREATE TABLE tb_dim_date (
    pk_date     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date_value  DATE NOT NULL UNIQUE,
    year        INT  NOT NULL,
    quarter     INT  NOT NULL,
    month       INT  NOT NULL,
    week        INT  NOT NULL,
    day_of_week INT  NOT NULL,
    is_weekend  BOOLEAN NOT NULL,
    is_holiday  BOOLEAN NOT NULL DEFAULT false
);
```

---

## Read Views

FraiseQL queries a `v_` view (or a `tv_` projection table), never the raw fact
table directly. The view joins the dimensions you need and emits a `data` JSONB
payload alongside the public `id`. Aggregations are derived on top of this view at
runtime.

```sql
CREATE VIEW v_event AS
SELECT
    e.id,                               -- public UUID, required by FraiseQL
    e.event_date,
    e.occurred_at,
    p.id          AS product_id,
    p.category,
    p.region,
    e.attributes ->> 'source'      AS source,
    e.attributes ->> 'device_type' AS device_type,
    e.revenue,
    e.quantity,
    e.sessions,
    jsonb_build_object(
        'event_date',  e.event_date,
        'product_id',  p.id,
        'category',    p.category,
        'region',      p.region,
        'source',      e.attributes ->> 'source',
        'device_type', e.attributes ->> 'device_type',
        'revenue',     e.revenue,
        'quantity',    e.quantity,
        'sessions',    e.sessions
    ) AS data
FROM tb_event e
LEFT JOIN tb_dim_product p ON p.pk_product = e.fk_product;
```

### `tv_` Projection Tables for Heavy Reads

When a read is too expensive to compute per request — deep nesting, wide joins, or
large rollups — materialize it into a `tv_` projection table: a real table holding
pre-composed JSONB, refreshed by functions, triggers, or a schedule. FraiseQL
queries a `tv_` table exactly like a `v_` view.

```sql
CREATE TABLE tv_daily_product_metrics (
    id           UUID NOT NULL DEFAULT gen_random_uuid(),
    metric_date  DATE NOT NULL,
    product_id   UUID NOT NULL,
    data         JSONB NOT NULL,        -- pre-composed payload
    PRIMARY KEY (metric_date, product_id)
);
```

---

## Aggregation Patterns in View SQL

Beyond the runtime auto-aggregation, the heavy lifting of OLAP lives in plain
PostgreSQL that you embed in your `v_`/`tv_` views.

### Time Bucketing with `DATE_TRUNC`

```sql
SELECT
    DATE_TRUNC('day', e.occurred_at)::DATE AS bucket,
    SUM(e.revenue)                          AS revenue,
    COUNT(*)                                AS events,
    AVG(e.revenue)                          AS avg_order_value
FROM tb_event e
WHERE e.event_date BETWEEN $1 AND $2
GROUP BY DATE_TRUNC('day', e.occurred_at)
ORDER BY bucket;
```

### Conditional Aggregates with `FILTER (WHERE …)`

`FILTER` computes several conditional measures in a single scan — ideal for funnel
and segmentation reporting.

```sql
SELECT
    p.category,
    COUNT(*) FILTER (WHERE e.attributes ->> 'step' = 'view')        AS views,
    COUNT(*) FILTER (WHERE e.attributes ->> 'step' = 'add_to_cart') AS add_to_cart,
    COUNT(*) FILTER (WHERE e.attributes ->> 'step' = 'purchase')    AS purchases,
    SUM(e.revenue) FILTER (WHERE e.attributes ->> 'step' = 'purchase') AS revenue
FROM tb_event e
JOIN tb_dim_product p ON p.pk_product = e.fk_product
WHERE e.event_date BETWEEN $1 AND $2
GROUP BY p.category;
```

### Window Functions

Window functions (`ROW_NUMBER`, `RANK`, `LAG`, `LEAD`, running totals over
`OVER (PARTITION BY …)`) are standard PostgreSQL. Embed them in your view SQL when
you need rankings, period-over-period deltas, or moving aggregates.

```sql
CREATE VIEW v_daily_revenue_trend AS
SELECT
    gen_random_uuid() AS id,
    bucket            AS event_date,
    revenue,
    revenue - LAG(revenue) OVER (ORDER BY bucket)                 AS revenue_delta,
    AVG(revenue) OVER (ORDER BY bucket ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)
                                                                  AS revenue_7d_avg,
    jsonb_build_object(
        'event_date',     bucket,
        'revenue',        revenue,
        'revenue_delta',  revenue - LAG(revenue) OVER (ORDER BY bucket)
    ) AS data
FROM (
    SELECT DATE_TRUNC('day', occurred_at)::DATE AS bucket, SUM(revenue) AS revenue
    FROM tb_event
    GROUP BY DATE_TRUNC('day', occurred_at)
) daily;
```

### Cohort Retention

Cohort analysis is a multi-CTE query you wrap in a view (or a `tv_` projection
table if it is expensive):

```sql
CREATE VIEW v_retention_cohort AS
WITH cohort_users AS (
    SELECT DATE_TRUNC('month', u.signup_date)::DATE AS cohort_date, u.pk_user
    FROM tb_dim_user u
),
activity AS (
    SELECT
        c.cohort_date,
        c.pk_user,
        (e.event_date - c.cohort_date)::INT AS days_since_signup
    FROM cohort_users c
    JOIN tb_event e ON e.fk_user = c.pk_user AND e.event_date >= c.cohort_date
)
SELECT
    gen_random_uuid() AS id,
    cohort_date,
    days_since_signup,
    COUNT(DISTINCT pk_user) FILTER (WHERE days_since_signup = 0) AS cohort_size,
    ROUND(
        COUNT(DISTINCT pk_user)::NUMERIC
        / NULLIF(COUNT(DISTINCT pk_user) FILTER (WHERE days_since_signup = 0), 0)
        * 100, 2
    ) AS retention_rate,
    jsonb_build_object(
        'cohort_date',       cohort_date,
        'days_since_signup', days_since_signup
    ) AS data
FROM activity
GROUP BY cohort_date, days_since_signup;
```

---

## Exposing the Analytics API

Define the view-backed types and the queries that read them, then build the app.

```python
import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.types import ID, Date


@fraiseql.type(sql_source="v_daily_revenue_trend", jsonb_column="data")
class DailyRevenue:
    id: ID
    event_date: Date
    revenue: float
    revenue_delta: float | None


@fraiseql.query
async def daily_revenue(info, start: Date, end: Date) -> list[DailyRevenue]:
    """Daily revenue trend over a date range."""
    db = info.context["db"]
    return await db.find(
        "v_daily_revenue_trend",
        where={"event_date": {"gte": start, "lte": end}},
    )


@fraiseql.query
async def revenue_by_product(info, start: Date, end: Date) -> list[Event]:
    """Revenue segmented by product, aggregated at runtime."""
    db = info.context["db"]
    return await db.find(
        "v_event",
        where={"event_date": {"gte": start, "lte": end}},
    )


app = create_fraiseql_app(
    database_url="postgresql://localhost/analytics",
    types=[Event, DailyRevenue],
    queries=[daily_revenue, revenue_by_product],
    production=True,  # False enables the GraphQL playground
)
```

Run it with any ASGI server:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

---

## Performance Optimization

### Pre-Computed Aggregate Tables

For dashboards that hit the same rollups repeatedly, refresh an aggregate table on
a schedule and expose it through a `tv_`/`v_` view.

```sql
CREATE OR REPLACE FUNCTION fn_refresh_daily_aggregates()
RETURNS void AS $$
BEGIN
    DELETE FROM tv_daily_product_metrics
    WHERE metric_date >= CURRENT_DATE - INTERVAL '1 day';

    INSERT INTO tv_daily_product_metrics (metric_date, product_id, data)
    SELECT
        e.event_date,
        p.id,
        jsonb_build_object(
            'revenue',      SUM(e.revenue),
            'event_count',  COUNT(*),
            'unique_users', COUNT(DISTINCT e.fk_user)
        )
    FROM tb_event e
    JOIN tb_dim_product p ON p.pk_product = e.fk_product
    WHERE e.event_date >= CURRENT_DATE - INTERVAL '30 days'
    GROUP BY e.event_date, p.id;
END;
$$ LANGUAGE plpgsql;

-- Schedule nightly with pg_cron
SELECT cron.schedule(
    'refresh_daily_aggregates', '0 2 * * *',
    'SELECT fn_refresh_daily_aggregates()'
);
```

### Partition Pruning

Range-partitioning by `event_date` lets PostgreSQL skip irrelevant partitions:

```sql
-- Only scans the January 2026 partition
SELECT SUM(revenue) FROM tb_event
WHERE event_date BETWEEN '2026-01-01' AND '2026-01-31';
```

### Materialized Views

For expensive, slow-changing rollups, a materialized view refreshed
concurrently keeps reads fast:

```sql
CREATE MATERIALIZED VIEW mv_top_products_by_revenue AS
SELECT
    p.id          AS product_id,
    p.product_name,
    SUM(e.revenue) AS total_revenue,
    COUNT(DISTINCT e.fk_user) AS unique_customers
FROM tb_event e
JOIN tb_dim_product p ON p.pk_product = e.fk_product
WHERE e.event_date >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY p.id, p.product_name
ORDER BY total_revenue DESC
LIMIT 100;

CREATE UNIQUE INDEX idx_mv_top_products ON mv_top_products_by_revenue (product_id);

SELECT cron.schedule(
    'refresh_mv_top_products', '0 * * * *',
    'REFRESH MATERIALIZED VIEW CONCURRENTLY mv_top_products_by_revenue'
);
```

---

## Real-Time Metrics with Subscriptions

For a live dashboard, expose a subscription whose async-generator resolver yields
the latest metrics. The generator can poll a recent-window aggregate or be driven
by PostgreSQL `LISTEN/NOTIFY`; FraiseQL streams whatever it yields over WebSocket.

```python
import asyncio
from collections.abc import AsyncGenerator

import fraiseql


@fraiseql.subscription
async def realtime_metrics(info) -> AsyncGenerator[dict, None]:
    """Stream rolling metrics for the last hour every 10 seconds."""
    db = info.context["db"]
    while True:
        rows = await db.find("v_realtime_metrics")
        yield rows[0] if rows else {}
        await asyncio.sleep(10)
```

Back `v_realtime_metrics` with a view that aggregates the trailing window:

```sql
CREATE VIEW v_realtime_metrics AS
SELECT
    gen_random_uuid() AS id,
    COUNT(*)          AS events_last_hour,
    SUM(revenue)      AS revenue_last_hour,
    COUNT(DISTINCT fk_user) AS active_users,
    jsonb_build_object(
        'events_last_hour',  COUNT(*),
        'revenue_last_hour', SUM(revenue),
        'active_users',      COUNT(DISTINCT fk_user)
    ) AS data
FROM tb_event
WHERE occurred_at >= NOW() - INTERVAL '1 hour';
```

---

## Monitoring Analytical Performance

Use `pg_stat_statements` to find the slowest analytical queries and the views that
need a `tv_` projection or an extra index:

```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

SELECT query, calls, mean_exec_time, max_exec_time
FROM pg_stat_statements
WHERE query ILIKE '%v_event%'
ORDER BY mean_exec_time DESC
LIMIT 20;
```

---

## See Also

**Related Patterns:**

- [Patterns Overview](./README.md)
- [Multi-Tenant SaaS](./saas-multi-tenant.md) — per-tenant analytics with RLS
- [IoT Time-Series](./iot-timeseries.md) — specialized time-series ingestion and bucketing

**Architecture:**

- [Aggregation Model](../architecture/analytics/aggregation-model.md)
- [Fact/Dimension Pattern](../architecture/analytics/fact-dimension-pattern.md)
- [`tv_` Table Pattern](../architecture/database/tv-table-pattern.md)

**Guides:**

- [Performance Optimization](../guides/performance-optimization.md)
- [Schema Design Best Practices](../guides/schema-design-best-practices.md)
- [Production Deployment](../guides/production-deployment.md)

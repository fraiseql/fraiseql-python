---
title: IoT Platform with Time-Series Data
description: Build a scalable IoT platform on FraiseQL and PostgreSQL — collect sensor readings, bucket and roll them up with views, and serve them over GraphQL.
keywords: ["iot", "time-series", "sensors", "aggregation", "postgresql"]
tags: ["documentation", "patterns"]
---

# IoT Platform with Time-Series Data

**Status:** Production Ready
**Complexity:** Advanced
**Audience:** IoT architects, DevOps engineers, data engineers
**Reading Time:** 25-30 minutes

A blueprint for building an IoT platform on FraiseQL v1. Readings land in normalized
`tb_` tables (optionally partitioned by time range), `v_`/`tv_` views bucket and roll
them up with `DATE_TRUNC` and PostgreSQL aggregates, and `@fraiseql.query` resolvers serve
the views over GraphQL. FraiseQL is a Python runtime GraphQL framework for **PostgreSQL
only** — there is no compile step and no separate database engine. Everything below runs at
app startup against your PostgreSQL database.

---

## Architecture Overview

```text
┌──────────────┬──────────────┬──────────────┐
│   Devices    │   Devices    │   Devices    │
│  (sensors)   │  (sensors)   │  (sensors)   │
└──────────┬───┴──────┬───────┴──────┬───────┘
           │          │              │
           └──────────┼──────────────┘
                      ↓ (HTTP / MQTT bridge)
         ┌────────────────────────────┐
         │  Ingestion                 │
         │  fn_record_reading()       │
         │  or COPY (bulk)            │
         └────────────┬───────────────┘
                      ↓
         ┌────────────────────────────┐
         │  PostgreSQL                │
         │  tb_sensor_reading         │
         │  (PARTITION BY RANGE time) │
         │  tv_reading_1h / _1d       │
         │  (pre-aggregated rollups)  │
         └────────────┬───────────────┘
                      ↓  v_/tv_ views
         ┌────────────────────────────┐
         │  FraiseQL (FastAPI)        │
         │  @fraiseql.query / runtime │
         │  auto-aggregation          │
         └────────────────────────────┘
```

The message broker (MQTT/Kafka) and any stream processor live *outside* FraiseQL. They are
optional plumbing that lands readings into PostgreSQL. FraiseQL's job is the read/write path
against PostgreSQL: queries read `v_`/`tv_` views, mutations call `fn_` functions.

---

## Schema Design

FraiseQL follows a CQRS layout: normalized `tb_` write tables are the source of truth,
`v_`/`tv_` read views expose a `data` JSONB column for GraphQL, and `fn_` functions hold
write logic. Each public row carries a `pk_` internal BIGINT (hidden), a public `id` UUID,
and an optional human-readable `identifier`.

### Devices & Metadata

```sql
-- Device registry (write table)
CREATE TABLE tb_device (
    pk_device       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id              UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    identifier      TEXT UNIQUE,              -- external slug (MAC, serial)
    name            TEXT NOT NULL,
    device_type     TEXT NOT NULL,           -- temperature_sensor, humidity_sensor, ...
    location        TEXT,
    latitude        NUMERIC(10, 8),
    longitude       NUMERIC(11, 8),
    fk_owner        BIGINT NOT NULL REFERENCES tb_owner (pk_owner),
    status          TEXT NOT NULL DEFAULT 'active',  -- active, inactive, error
    last_heartbeat  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_device_status      ON tb_device (status);
CREATE INDEX idx_device_type        ON tb_device (device_type);
CREATE INDEX idx_device_owner       ON tb_device (fk_owner);

-- Per-device configuration
CREATE TABLE tb_device_config (
    pk_device_config    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fk_device           BIGINT NOT NULL UNIQUE REFERENCES tb_device (pk_device) ON DELETE CASCADE,
    read_interval_s     INT NOT NULL,                -- seconds between readings
    alert_threshold     JSONB,                       -- {"temperature": {"min": 0, "max": 100}}
    data_retention_days INT NOT NULL DEFAULT 365,
    custom_fields       JSONB,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Sensor metadata (what each device measures)
CREATE TABLE tb_sensor (
    pk_sensor   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id          UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    fk_device   BIGINT NOT NULL REFERENCES tb_device (pk_device) ON DELETE CASCADE,
    sensor_name TEXT NOT NULL,                -- temperature, humidity, pressure
    unit        TEXT,                         -- Celsius, %, hPa
    sensor_type TEXT,                         -- analog, digital, counter
    accuracy    NUMERIC(5, 2),
    UNIQUE (fk_device, sensor_name)
);

CREATE INDEX idx_sensor_device ON tb_sensor (fk_device);
```

### Time-Series Readings (Native Partitioning)

Raw readings are high-volume and append-only, which makes them a natural fit for
PostgreSQL **native range partitioning** by time. Partitioning keeps indexes small,
makes retention a metadata operation (`DROP`/`DETACH PARTITION` instead of a slow
`DELETE`), and lets the planner prune to the partitions a query touches.

```sql
-- Raw sensor readings, partitioned by month
CREATE TABLE tb_sensor_reading (
    "time"      TIMESTAMPTZ NOT NULL,
    fk_device   BIGINT NOT NULL REFERENCES tb_device (pk_device) ON DELETE CASCADE,
    sensor_name TEXT NOT NULL,
    value       NUMERIC(12, 4) NOT NULL,
    unit        TEXT,
    quality     TEXT                          -- good, poor, unknown
) PARTITION BY RANGE ("time");

-- One partition per month (create ahead of time, e.g. via cron)
CREATE TABLE tb_sensor_reading_2026_06
    PARTITION OF tb_sensor_reading
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');

CREATE TABLE tb_sensor_reading_2026_07
    PARTITION OF tb_sensor_reading
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');

-- Indexes are created on the parent and inherited by every partition
CREATE INDEX idx_reading_device_time ON tb_sensor_reading (fk_device, "time" DESC);
CREATE INDEX idx_reading_sensor_time ON tb_sensor_reading (sensor_name, "time" DESC);
```

Retention then becomes cheap — drop the partition once it ages out:

```sql
-- Retire June once it is older than the retention window
DROP TABLE tb_sensor_reading_2026_06;
-- or keep it queryable but off the hot path:
-- ALTER TABLE tb_sensor_reading DETACH PARTITION tb_sensor_reading_2026_06;
```

### Pre-Aggregated Rollups (`tv_` projection tables)

For dashboards you don't want to scan raw readings on every request. A `tv_` table holds
**pre-aggregated** rollups: a real table populated by a function (run from a trigger or a
cron job) that FraiseQL queries directly. This is the standard v1 way to serve heavy reads
fast — see [tv-table pattern](../architecture/database/tv-table-pattern.md).

```sql
-- Hourly rollup table (a real table, refreshed incrementally)
CREATE TABLE tv_reading_1h (
    bucket        TIMESTAMPTZ NOT NULL,
    fk_device     BIGINT NOT NULL,
    sensor_name   TEXT NOT NULL,
    data          JSONB NOT NULL,          -- pre-composed payload FraiseQL returns
    PRIMARY KEY (bucket, fk_device, sensor_name)
);

-- Refresh one window (call from cron, or from a trigger on tb_sensor_reading)
CREATE OR REPLACE FUNCTION fn_refresh_reading_1h(p_from TIMESTAMPTZ, p_to TIMESTAMPTZ)
RETURNS void
LANGUAGE sql
AS $$
    INSERT INTO tv_reading_1h (bucket, fk_device, sensor_name, data)
    SELECT
        DATE_TRUNC('hour', r."time")               AS bucket,
        r.fk_device,
        r.sensor_name,
        jsonb_build_object(
            'avgValue',     AVG(r.value),
            'minValue',     MIN(r.value),
            'maxValue',     MAX(r.value),
            'stddevValue',  STDDEV(r.value),
            'readingCount', COUNT(*)
        )                                          AS data
    FROM tb_sensor_reading r
    WHERE r."time" >= p_from AND r."time" < p_to
    GROUP BY DATE_TRUNC('hour', r."time"), r.fk_device, r.sensor_name
    ON CONFLICT (bucket, fk_device, sensor_name)
    DO UPDATE SET data = EXCLUDED.data;
$$;
```

A daily `tv_reading_1d` table follows the same shape with `DATE_TRUNC('day', ...)`.
For details on automatic `GROUP BY` derivation, see the
[aggregation model](../architecture/analytics/aggregation-model.md).

### Read Views

Read views always expose an `id` (for `WHERE id = $1`) plus a `data` JSONB column built
with `jsonb_build_object(...)`. `pk_`/`fk_` columns stay out of `data`.

```sql
-- Device read view
CREATE VIEW v_device AS
SELECT
    d.id,
    jsonb_build_object(
        'id',           d.id,
        'identifier',   d.identifier,
        'name',         d.name,
        'deviceType',   d.device_type,
        'location',     d.location,
        'latitude',     d.latitude,
        'longitude',    d.longitude,
        'status',       d.status,
        'lastHeartbeat', d.last_heartbeat
    ) AS data
FROM tb_device d;

-- Hourly metric view over the rollup table
CREATE VIEW v_reading_1h AS
SELECT
    t.bucket,
    dev.id AS device_id,
    t.sensor_name,
    jsonb_build_object(
        'bucket',       t.bucket,
        'sensorName',   t.sensor_name,
        'avgValue',     t.data ->> 'avgValue',
        'minValue',     t.data ->> 'minValue',
        'maxValue',     t.data ->> 'maxValue',
        'stddevValue',  t.data ->> 'stddevValue',
        'readingCount', t.data ->> 'readingCount'
    ) AS data
FROM tv_reading_1h t
JOIN tb_device dev ON dev.pk_device = t.fk_device;
```

### Moving Averages with Window Functions

Moving averages and rate-of-change are plain PostgreSQL **window functions** embedded in a
view — not a FraiseQL API. FraiseQL serves whatever the view returns. See
[window functions](../architecture/analytics/window-functions.md).

```sql
-- 3-bucket moving average of hourly readings
CREATE VIEW v_reading_1h_smoothed AS
SELECT
    dev.id AS device_id,
    t.sensor_name,
    jsonb_build_object(
        'bucket',     t.bucket,
        'sensorName', t.sensor_name,
        'avgValue',   (t.data ->> 'avgValue')::numeric,
        'movingAvg3', AVG((t.data ->> 'avgValue')::numeric) OVER (
            PARTITION BY t.fk_device, t.sensor_name
            ORDER BY t.bucket
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        )
    ) AS data
FROM tv_reading_1h t
JOIN tb_device dev ON dev.pk_device = t.fk_device;
```

### Alerts & Events

```sql
CREATE TABLE tb_device_alert (
    pk_device_alert  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id               UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    fk_device        BIGINT NOT NULL REFERENCES tb_device (pk_device),
    alert_type       TEXT NOT NULL,           -- threshold_exceeded, device_offline, low_battery
    severity         TEXT NOT NULL,           -- info, warning, critical
    value            NUMERIC(12, 4),
    threshold        NUMERIC(12, 4),
    acknowledged     BOOLEAN NOT NULL DEFAULT FALSE,
    fk_acknowledged_by BIGINT REFERENCES tb_user (pk_user),
    acknowledged_at  TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_alert_device       ON tb_device_alert (fk_device);
CREATE INDEX idx_alert_severity     ON tb_device_alert (severity);
CREATE INDEX idx_alert_open         ON tb_device_alert (acknowledged) WHERE NOT acknowledged;

CREATE VIEW v_alert AS
SELECT
    a.id,
    jsonb_build_object(
        'id',           a.id,
        'alertType',    a.alert_type,
        'severity',     a.severity,
        'value',        a.value,
        'threshold',    a.threshold,
        'acknowledged', a.acknowledged,
        'createdAt',    a.created_at
    ) AS data
FROM tb_device_alert a;
```

---

## FraiseQL Schema

Types bind to a read view via `sql_source`; FraiseQL reads the view's `data` JSONB and
shapes it to the requested GraphQL fields. Queries call `db.find`/`db.find_one`; mutations
call `fn_` functions via `db.execute_function`.

```python
# iot_schema.py
import fraiseql
from fraiseql.types import ID, DateTime
from decimal import Decimal


@fraiseql.type(sql_source="v_device", jsonb_column="data")
class Device:
    id: ID
    identifier: str | None
    name: str
    device_type: str
    location: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    status: str                       # active, inactive, error
    last_heartbeat: DateTime | None


@fraiseql.type(sql_source="v_sensor", jsonb_column="data")
class Sensor:
    id: ID
    sensor_name: str
    unit: str | None
    accuracy: Decimal | None


@fraiseql.type(sql_source="v_reading_1h", jsonb_column="data")
class SensorMetric:
    """Pre-aggregated hourly metric from tv_reading_1h."""
    bucket: DateTime
    sensor_name: str
    avg_value: Decimal | None
    min_value: Decimal | None
    max_value: Decimal | None
    stddev_value: Decimal | None
    reading_count: int


@fraiseql.type(sql_source="v_alert", jsonb_column="data")
class Alert:
    id: ID
    alert_type: str
    severity: str                     # info, warning, critical
    value: Decimal | None
    threshold: Decimal | None
    acknowledged: bool
    created_at: DateTime


@fraiseql.input
class RecordReadingInput:
    device_id: ID
    sensor_name: str
    value: Decimal
    timestamp: DateTime | None = None


@fraiseql.success
class RecordReadingSuccess:
    device_id: ID
    sensor_name: str


@fraiseql.error
class RecordReadingError:
    message: str
    code: str = "INGEST_ERROR"


@fraiseql.input
class AcknowledgeAlertInput:
    alert_id: ID


@fraiseql.success
class AcknowledgeAlertSuccess:
    alert: Alert


@fraiseql.error
class AcknowledgeAlertError:
    message: str
    code: str = "NOT_FOUND"
```

### Queries

```python
@fraiseql.query
async def devices(info, device_type: str | None = None) -> list[Device]:
    """List devices, optionally filtered by type."""
    db = info.context["db"]
    filters = {"device_type": device_type} if device_type else {}
    return await db.find("v_device", **filters)


@fraiseql.query
async def device(info, id: ID) -> Device | None:
    """Get one device by id."""
    db = info.context["db"]
    return await db.find_one("v_device", id=id)


@fraiseql.query
async def sensor_metrics(
    info,
    device_id: ID,
    sensor_name: str,
    start_time: DateTime,
    end_time: DateTime,
) -> list[SensorMetric]:
    """Pre-aggregated hourly metrics from tv_reading_1h (fast for dashboards)."""
    db = info.context["db"]
    return await db.find(
        "v_reading_1h",
        device_id=device_id,
        sensor_name=sensor_name,
        bucket__gte=start_time,
        bucket__lte=end_time,
    )


@fraiseql.query
async def active_alerts(info) -> list[Alert]:
    """Unacknowledged alerts."""
    db = info.context["db"]
    return await db.find("v_alert", acknowledged=False)
```

`start_time`/`end_time` map to the WHERE operators `bucket__gte` / `bucket__lte`, which
FraiseQL translates into a partition-prunable `BETWEEN` against the view. When a query
selects only aggregate fields, FraiseQL's **runtime auto-aggregation** derives the
`GROUP BY` and the COUNT/SUM/AVG/MIN/MAX/STDDEV/VARIANCE SQL for you against the view — so
you can aggregate `v_reading_1h` further without writing a second view. See the
[aggregation model](../architecture/analytics/aggregation-model.md).

### Mutations

```python
@fraiseql.mutation
async def record_reading(
    info, input: RecordReadingInput
) -> RecordReadingSuccess | RecordReadingError:
    """Ingest a single reading and run threshold checks (in PostgreSQL)."""
    db = info.context["db"]
    result = await db.execute_function(
        "fn_record_reading",
        {
            "device_id": str(input.device_id),
            "sensor_name": input.sensor_name,
            "value": str(input.value),
            "ts": input.timestamp,
        },
    )
    if not result.get("success"):
        return RecordReadingError(message=result.get("message", "ingest failed"))
    return RecordReadingSuccess(
        device_id=input.device_id, sensor_name=input.sensor_name
    )


@fraiseql.mutation
async def acknowledge_alert(
    info, input: AcknowledgeAlertInput
) -> AcknowledgeAlertSuccess | AcknowledgeAlertError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_acknowledge_alert", {"alert_id": str(input.alert_id)}
    )
    if not result.get("success"):
        return AcknowledgeAlertError(message=result.get("message", "not found"))
    return AcknowledgeAlertSuccess(alert=Alert(**result["alert"]))
```

### Real-Time Push (Subscriptions)

FraiseQL exposes GraphQL subscriptions over WebSocket. A `@fraiseql.subscription` decorates
an **async generator** — you write the event source, FraiseQL streams what you yield. Back
it with PostgreSQL `LISTEN/NOTIFY` (e.g. a trigger on `tb_device_alert` that runs
`pg_notify('alert', ...)`), polling, or any external stream.

```python
from collections.abc import AsyncGenerator


@fraiseql.subscription
async def alerts(info) -> AsyncGenerator[Alert, None]:
    """Stream new alerts to dashboards as they are created."""
    async for alert in watch_alerts(info.context["db"]):   # your LISTEN/NOTIFY loop
        yield alert
```

### Mounting the App

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/iot",
    types=[Device, Sensor, SensorMetric, Alert],
    queries=[devices, device, sensor_metrics, active_alerts],
    mutations=[record_reading, acknowledge_alert],
    subscriptions=[alerts],
    production=False,        # False enables the GraphQL playground
)
```

Run it with `uvicorn app:app`.

---

## Ingestion

All write logic lives in PostgreSQL. The `fn_record_reading` function validates the device,
inserts the reading, and evaluates thresholds in one transaction.

```sql
CREATE OR REPLACE FUNCTION fn_record_reading(
    device_id   UUID,
    sensor_name TEXT,
    value       NUMERIC,
    ts          TIMESTAMPTZ DEFAULT now()
) RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_pk_device BIGINT;
    v_threshold NUMERIC;
BEGIN
    SELECT pk_device INTO v_pk_device FROM tb_device WHERE id = device_id;
    IF v_pk_device IS NULL THEN
        RETURN jsonb_build_object('success', false, 'message', 'unknown device');
    END IF;

    INSERT INTO tb_sensor_reading ("time", fk_device, sensor_name, value)
    VALUES (ts, v_pk_device, sensor_name, value);

    -- Threshold check
    SELECT (alert_threshold -> sensor_name ->> 'max')::numeric
      INTO v_threshold
      FROM tb_device_config WHERE fk_device = v_pk_device;

    IF v_threshold IS NOT NULL AND value > v_threshold THEN
        INSERT INTO tb_device_alert (fk_device, alert_type, severity, value, threshold)
        VALUES (v_pk_device, 'threshold_exceeded', 'warning', value, v_threshold);
        PERFORM pg_notify('alert', jsonb_build_object(
            'device', device_id, 'sensor', sensor_name, 'value', value
        )::text);
    END IF;

    RETURN jsonb_build_object('success', true);
END;
$$;
```

### Bulk Ingestion with COPY

For backfills or high-throughput ingestion, bypass per-row mutations and stream straight
into the partitioned table with `COPY` — the fastest path PostgreSQL offers. An MQTT/Kafka
bridge can batch readings and pipe them in:

```sql
COPY tb_sensor_reading ("time", fk_device, sensor_name, value, unit)
FROM STDIN WITH (FORMAT csv);
```

```python
# Async bulk load via psycopg copy (run outside FraiseQL, in your ingestion worker)
async with pool.connection() as conn:
    async with conn.cursor().copy(
        "COPY tb_sensor_reading (\"time\", fk_device, sensor_name, value) FROM STDIN"
    ) as copy:
        for row in batch:
            await copy.write_row(row)
```

After a bulk load, refresh the affected rollup windows by calling
`fn_refresh_reading_1h(p_from, p_to)`.

> **Brokers are external.** Kafka, MQTT, and stream processors are separate systems that
> feed PostgreSQL. Dedicated time-series stores (e.g. ClickHouse, InfluxDB) are also separate
> systems — FraiseQL itself targets PostgreSQL only. Pick whichever ingestion plumbing you
> like; FraiseQL reads from the PostgreSQL tables and views.

---

## Query Examples

### Real-Time Dashboard

```graphql
query DeviceDashboard($deviceId: ID!) {
  device(id: $deviceId) {
    id
    name
    status
    lastHeartbeat
  }
  activeAlerts {
    id
    alertType
    severity
    value
  }
}
```

### Time-Series Trend

```graphql
query TemperatureTrend(
  $deviceId: ID!
  $startTime: DateTime!
  $endTime: DateTime!
) {
  sensorMetrics(
    deviceId: $deviceId
    sensorName: "temperature"
    startTime: $startTime
    endTime: $endTime
  ) {
    bucket
    avgValue
    minValue
    maxValue
  }
}
```

---

## Scaling Strategies

### Time-Based Partitioning

Native range partitioning (above) is the core scaling lever. Pre-create partitions ahead of
time with a small cron job so writes never hit a missing partition:

```sql
-- Create next month's partition (run monthly)
CREATE TABLE IF NOT EXISTS tb_sensor_reading_2026_08
    PARTITION OF tb_sensor_reading
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
```

### Data Retention

Drop or detach aged partitions — a metadata operation, far cheaper than a bulk `DELETE`:

```sql
-- Archive then drop the oldest partition
ALTER TABLE tb_sensor_reading DETACH PARTITION tb_sensor_reading_2026_06;
-- Optionally move the detached table to cheaper storage, then:
DROP TABLE tb_sensor_reading_2026_06;
```

### Downsampling

For long-term storage, keep only the daily rollup and let raw partitions expire. The
`tv_reading_1d` table (refreshed like `tv_reading_1h`) becomes the system of record for
historical trends, served through `v_reading_1d`.

```sql
-- Daily rollup window refresh
SELECT fn_refresh_reading_1d(DATE_TRUNC('day', now() - INTERVAL '1 day'),
                             DATE_TRUNC('day', now()));
```

---

## Alerting

Threshold alerts are evaluated inside `fn_record_reading` (above) so every write is checked
in the same transaction. For time-window rules (device offline, sustained anomalies) run a
periodic job that calls an `fn_` function:

```sql
-- Flag devices that haven't reported in 5 minutes (run from cron)
CREATE OR REPLACE FUNCTION fn_flag_offline_devices()
RETURNS void
LANGUAGE sql
AS $$
    INSERT INTO tb_device_alert (fk_device, alert_type, severity)
    SELECT d.pk_device, 'device_offline', 'warning'
    FROM tb_device d
    WHERE d.last_heartbeat < now() - INTERVAL '5 minutes'
      AND d.status = 'active'
      AND NOT EXISTS (
          SELECT 1 FROM tb_device_alert a
          WHERE a.fk_device = d.pk_device
            AND a.alert_type = 'device_offline'
            AND NOT a.acknowledged
      );
$$;
```

Subscribers receive new alerts in real time via the `alerts` subscription, backed by the
`pg_notify('alert', ...)` call in `fn_record_reading`.

---

## Testing

Integration tests run GraphQL operations against a real PostgreSQL database.

```python
import pytest


@pytest.mark.asyncio
async def test_record_reading_ingests(schema, db):
    """A reading is persisted and queryable."""
    result = await schema.execute(
        """
        mutation Ingest($input: RecordReadingInput!) {
          recordReading(input: $input) {
            ... on RecordReadingSuccess { deviceId sensorName }
            ... on RecordReadingError { message }
          }
        }
        """,
        variable_values={
            "input": {
                "deviceId": str(device_id),
                "sensorName": "temperature",
                "value": "23.5",
            }
        },
        context_value={"db": db},
    )
    assert result.errors is None
    assert result.data["recordReading"]["sensorName"] == "temperature"


@pytest.mark.asyncio
async def test_threshold_triggers_alert(schema, db):
    """A reading above the configured max raises an alert."""
    await schema.execute(
        "mutation { recordReading(input: "
        '{ deviceId: "%s", sensorName: "temperature", value: "120" }) '
        "{ ... on RecordReadingSuccess { sensorName } } }" % device_id,
        context_value={"db": db},
    )
    alerts = await db.find("v_alert", acknowledged=False)
    assert any(a["data"]["severity"] == "warning" for a in alerts)
```

---

## Monitoring

A status-summary view aggregates device health for an operations dashboard. Build it as a
view and let runtime auto-aggregation count the buckets, or precompute it in a `tv_` table.

```graphql
query FleetHealth {
  devices {
    id
    status
    lastHeartbeat
  }
  activeAlerts {
    severity
  }
}
```

For production deployment and observability practices, see
[Production Deployment](../guides/production-deployment.md) and
[Observability & Monitoring](../guides/observability.md).

---

## See Also

**Related Patterns:**

- [Patterns Index](./README.md)
- [Analytics / OLAP Platform](./analytics-olap-platform.md) — views + runtime aggregation for metrics
- [Real-Time Collaboration](./realtime-collaboration.md) — subscriptions over WebSocket

**Architecture:**

- [Aggregation Model](../architecture/analytics/aggregation-model.md) — runtime auto-aggregation
- [Window Functions](../architecture/analytics/window-functions.md) — moving averages in views
- [tv-table Pattern](../architecture/database/tv-table-pattern.md) — pre-aggregated projection tables

"""A captured error is delivered to its notification channels, and logged.

No mocks of the delivery path: the error tracker writes to PostgreSQL (with
``schema.sql`` loaded), the notification manager reads the configs, builds the
channel, sends (to a local HTTP server, or an in-process channel) and writes
``tb_error_notification_log``.
"""

import asyncio
import json
import threading
from collections.abc import AsyncGenerator, Iterator
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import psycopg_pool
import pytest
import pytest_asyncio

from fraiseql.monitoring.notifications import NotificationManager
from fraiseql.monitoring.postgres_error_tracker import PostgreSQLErrorTracker

pytestmark = pytest.mark.integration

SCHEMA_SQL = Path(__file__).parents[3] / "src" / "fraiseql" / "monitoring" / "schema.sql"


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def monitoring_pool(
    postgres_url: str, test_schema: str
) -> AsyncGenerator[psycopg_pool.AsyncConnectionPool]:
    """A pool whose connections all see the test schema, with schema.sql loaded."""
    pool = psycopg_pool.AsyncConnectionPool(
        postgres_url,
        min_size=1,
        max_size=4,
        kwargs={"options": f"-c search_path={test_schema},public"},
        open=False,
    )
    await pool.open()
    async with pool.connection() as conn:
        await conn.execute(SCHEMA_SQL.read_text())
        await conn.commit()
    yield pool
    await pool.close()


class _Recorder(BaseHTTPRequestHandler):
    received: list[dict[str, Any]]

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.server.received.append(json.loads(body))  # type: ignore[attr-defined]
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def webhook_server() -> Iterator[HTTPServer]:
    server = HTTPServer(("127.0.0.1", 0), _Recorder)
    server.received = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


class InProcessChannel:
    """A custom channel: records what it is sent."""

    sent: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def send(self, error: dict[str, Any], config: dict[str, Any]) -> tuple[bool, str | None]:
        self.sent.append((error, config))
        return True, None

    def format_message(self, error: dict[str, Any], template: str | None = None) -> str:
        return error["error_message"]


async def _add_config(pool, channel_type: str, config: dict[str, Any], error_type: str) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO tb_error_notification_config"
            " (error_type, channel_type, channel_config, rate_limit_minutes)"
            " VALUES (%s, %s, %s, 0)",
            (error_type, channel_type, json.dumps(config)),
        )
        await conn.commit()


async def _log_rows(pool, error_id: str, expected: int) -> list[tuple]:
    """The notification log rows of an error, once ``expected`` are there (5s at most)."""
    for _ in range(100):
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT channel_type, recipient, status, error_message"
                " FROM tb_error_notification_log WHERE error_id = %s ORDER BY channel_type",
                (error_id,),
            )
            rows = await cur.fetchall()
        if len(rows) >= expected:
            return rows
        await asyncio.sleep(0.05)
    return rows


def _capture(error_type: type[Exception], message: str):
    try:
        raise error_type(message)
    except error_type as e:
        return e


@pytest.mark.usefixtures("test_schema")
class TestNotificationDelivery:
    @pytest.mark.asyncio(loop_scope="class")
    async def test_webhook_receives_a_captured_error(self, monitoring_pool, webhook_server) -> None:
        class WebhookError(Exception):
            pass

        url = f"http://127.0.0.1:{webhook_server.server_port}/errors"
        await _add_config(monitoring_pool, "webhook", {"url": url}, "WebhookError")
        tracker = PostgreSQLErrorTracker(monitoring_pool, environment="test")

        error_id = await tracker.capture_exception(_capture(WebhookError, "disk full"))

        rows = await _log_rows(monitoring_pool, error_id, 1)
        assert rows == [("webhook", "N/A", "sent", None)]
        assert [body["error_message"] for body in webhook_server.received] == ["disk full"]

    @pytest.mark.asyncio(loop_scope="class")
    async def test_custom_channel_registered_on_the_tracker_manager(self, monitoring_pool) -> None:
        class CustomError(Exception):
            pass

        await _add_config(monitoring_pool, "inprocess", {"channel": "#ops"}, "CustomError")
        manager = NotificationManager(monitoring_pool)
        manager.register_channel("inprocess", InProcessChannel)
        tracker = PostgreSQLErrorTracker(
            monitoring_pool, environment="test", notification_manager=manager
        )

        error_id = await tracker.capture_exception(_capture(CustomError, "boom"))

        rows = await _log_rows(monitoring_pool, error_id, 1)
        assert rows == [("inprocess", "#ops", "sent", None)]
        error, config = InProcessChannel.sent[-1]
        assert (error["error_id"], error["error_message"], config) == (
            error_id,
            "boom",
            {"channel": "#ops"},
        )

    @pytest.mark.asyncio(loop_scope="class")
    async def test_failed_delivery_is_logged(self, monitoring_pool) -> None:
        class SlackError(Exception):
            pass

        # No webhook_url: SlackChannel reports the failure, which is logged
        await _add_config(monitoring_pool, "slack", {"channel": "#alerts"}, "SlackError")
        tracker = PostgreSQLErrorTracker(monitoring_pool, environment="test")

        error_id = await tracker.capture_exception(_capture(SlackError, "x"))

        rows = await _log_rows(monitoring_pool, error_id, 1)
        assert [(r[0], r[1], r[2]) for r in rows] == [("slack", "#alerts", "failed")]
        assert rows[0][3]


@pytest.mark.usefixtures("test_schema")
class TestPartitionedTablesAcceptWrites:
    @pytest.mark.parametrize("months_ahead", [0, 2])
    @pytest.mark.asyncio(loop_scope="class")
    async def test_insert_now_and_ahead(self, monitoring_pool, months_ahead: int) -> None:
        at = datetime.now(UTC) + timedelta(days=31 * months_ahead)
        async with monitoring_pool.connection() as conn:
            await conn.execute(
                "INSERT INTO otel_traces (trace_id, span_id, operation_name, service_name,"
                " start_time) VALUES ('t', %s, 'op', 'svc', %s)",
                (f"s{months_ahead}", at),
            )
            await conn.execute(
                "INSERT INTO otel_metrics (metric_name, metric_type, value, timestamp)"
                " VALUES ('m', 'gauge', 1, %s)",
                (at,),
            )
            await conn.execute(
                "INSERT INTO tb_error_notification_log"
                " (config_id, error_id, sent_at, channel_type, recipient, status)"
                " VALUES (gen_random_uuid(), gen_random_uuid(), %s, 'webhook', 'x', 'sent')",
                (at,),
            )
            await conn.commit()

    @pytest.mark.asyncio(loop_scope="class")
    async def test_ensure_monitoring_partitions(self, monitoring_pool) -> None:
        async with monitoring_pool.connection() as conn:
            cur = await conn.execute("SELECT * FROM ensure_monitoring_partitions(3)")
            created = await cur.fetchall()
            await conn.commit()
            cur = await conn.execute(
                "SELECT parent.relname, count(*) FROM pg_inherits"
                " JOIN pg_class parent ON parent.oid = inhparent"
                " JOIN pg_namespace n ON n.oid = parent.relnamespace"
                " WHERE n.nspname = current_schema() GROUP BY parent.relname"
            )
            counts = dict(await cur.fetchall())
        tables = {"tb_error_occurrence", "otel_traces", "otel_metrics", "tb_error_notification_log"}
        assert {row[0].rsplit("_", 2)[0] for row in created} <= tables
        assert all(counts[t] >= 4 for t in tables), counts

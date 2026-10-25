"""Every dashboard SQL query runs against the tables FraiseQL creates.

The schema is src/fraiseql/monitoring/schema.sql plus the tables of the PostgreSQL
APQ backend, in a test schema; Grafana's macros are replaced by concrete values.
The v_query_stats panels need pg_stat_statements, and are skipped without it.
"""

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio

from fraiseql.storage.backends.postgresql import PostgreSQLAPQBackend

pytestmark = [pytest.mark.integration, pytest.mark.database]

ROOT = Path(__file__).parent.parent.parent
SCHEMA_SQL = ROOT / "src/fraiseql/monitoring/schema.sql"
NOW = datetime.now(UTC)


def _sql_targets() -> list:
    params = []
    for path in sorted((ROOT / "grafana").glob("*.json")):
        dashboard = json.loads(path.read_text())["dashboard"]
        for panel in dashboard["panels"]:
            for target in panel["targets"]:
                if "rawSql" in target:
                    params.append(
                        pytest.param(
                            target["rawSql"],
                            id=f"{path.stem}/{panel['title']}/{target['refId']}",
                        )
                    )
    return params


def substitute_macros(sql: str) -> str:
    """Replace Grafana's macros and the dashboard variables, as Grafana would."""
    time_from = (NOW - timedelta(days=1)).isoformat()
    time_to = (NOW + timedelta(minutes=5)).isoformat()
    sql = re.sub(
        r"\$__timeGroupAlias\(([^,]+),\s*\$__interval\)",
        r'floor(extract(epoch from \1)/60)*60 AS "time"',
        sql,
    )
    sql = re.sub(r"\$__timeFilter\(([^)]+)\)", rf"\1 BETWEEN '{time_from}' AND '{time_to}'", sql)
    sql = sql.replace("$__timeFrom()", f"'{time_from}'").replace("$__timeTo()", f"'{time_to}'")
    sql = sql.replace("$environment", "production")
    assert not re.search(r"\$\w+", sql), f"Unsubstituted variable in {sql}"
    return sql


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def dashboard_db(class_db_pool, test_schema):
    """The monitoring schema and the APQ tables, with a few rows in each table."""
    apq = PostgreSQLAPQBackend({})

    async with class_db_pool.connection() as conn:
        result = await conn.execute("SHOW shared_preload_libraries")
        has_pg_stat_statements = "pg_stat_statements" in (await result.fetchone())[0]
        if has_pg_stat_statements:
            try:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
                await conn.commit()
            except psycopg.Error:
                await conn.rollback()
                has_pg_stat_statements = False

        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute(SCHEMA_SQL.read_text())
        await conn.execute(apq._get_create_queries_table_sql())
        for statement in apq._get_create_responses_table_sql().split(";"):
            if statement.strip():
                await conn.execute(statement)

        error_id = uuid.uuid4()
        await conn.execute(
            """INSERT INTO tb_error_log (error_id, error_fingerprint, error_type, error_message,
                   environment, first_seen, last_seen)
               VALUES (%s, 'fp1', 'ValueError', 'bad value', 'production', %s, %s)""",
            (error_id, NOW - timedelta(hours=2), NOW),
        )
        await conn.execute(
            """INSERT INTO tb_error_occurrence (error_id, occurred_at, user_context)
               VALUES (%s, %s, '{"user_id": "u1"}')""",
            (error_id, NOW - timedelta(minutes=5)),
        )
        await conn.execute(
            """INSERT INTO tb_error_notification_log (config_id, error_id, channel_type,
                   recipient, status)
               VALUES (%s, %s, 'slack', '#alerts', 'sent')""",
            (uuid.uuid4(), error_id),
        )
        await conn.execute(
            "INSERT INTO apq_queries (hash, query) VALUES (%s, '{ users { id } }')", ("a" * 64,)
        )
        await conn.execute(
            "INSERT INTO apq_responses (hash, tenant_id, response) VALUES (%s, 't1', '{}')",
            ("a" * 64,),
        )
        await conn.commit()

    return has_pg_stat_statements


class TestDashboardQueriesRun:
    """Each rawSql of grafana/*.json executes without error."""

    @pytest.mark.asyncio(loop_scope="class")
    @pytest.mark.parametrize("raw_sql", _sql_targets())
    async def test_query_runs(self, raw_sql, dashboard_db, class_db_pool, test_schema) -> None:
        if "v_query_stats" in raw_sql and not dashboard_db:
            pytest.skip("pg_stat_statements is not installed: schema.sql has no v_query_stats")

        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            result = await conn.execute(substitute_macros(raw_sql))
            rows = await result.fetchall()
            await conn.rollback()

        assert isinstance(rows, list)

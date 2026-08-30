"""Issue #472: schema-qualified view names, resolved by a real PostgreSQL.

A view registered as ``"myschema.v_stats"`` has to render as two identifiers —
``"myschema"."v_stats"``. Handed whole to a single-argument ``Identifier`` it
renders as ``"myschema.v_stats"``: one quoted relation name that happens to
contain a dot, which PostgreSQL cannot resolve. The partial-period UNION
branches did exactly that while every other path split the name, so one
registration worked on the single-statement path and failed on the UNION one.

The two renderings differ by a single quote character and both read as plausible
in a diff, so a text assertion cannot tell them apart — only the server can. The
schema built here is therefore deliberately kept *off* the search path (unlike
the #468 tests, which set ``search_path`` precisely to dodge this bug), so a
mis-quoted or unqualified name has nothing to resolve against.
"""

import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import date
from typing import Any

import psycopg
import pytest

from fraiseql.db import FraiseQLRepository, _build_partial_period_union_query

pytestmark = pytest.mark.database

COARSE = "v_472_month"
FINE = "v_472_day"

# Deterministic, so batch_exists() has an id to ask about.
ROW_IDS = [uuid.UUID(int=i) for i in range(1, 6)]

# (date, category, status, cost)
FINE_ROWS = [
    ("2025-01-10", "A", "active", 5),  # below the lower bound
    ("2025-01-20", "A", "active", 10),
    ("2025-02-10", "A", "active", 20),
]

# The same data pre-aggregated to month starts.
COARSE_ROWS = [
    ("2025-01-01", "A", "active", 15),
    ("2025-02-01", "A", "active", 20),
]

# Mid-January through the end of February: the lower bound is not month-aligned,
# so branch 1 is fine-grain [01-15, 02-01) and branch 2 is coarse [02-01, 03-01).
# Both branch builders run, so both Identifier sites are exercised.
UNION_QUERY: dict[str, Any] = {
    "time_grain_column": "date",
    "time_grain_trunc": "month",
    "group_by": ["date", "dimensions.category"],
    "aggregations": {"measures.cost": "SUM(measures.cost)"},
    "native_dimensions": {"date"},
    "native_measures": {"measures.cost": "cost"},
    "native_dimension_mapping": {"dimensions.category": "model_category"},
    "jsonb_col": "data",
    "extra_where": None,
    "lower_bound": date(2025, 1, 15),
    "upper_bound_exclusive": date(2025, 3, 1),
    "today": date(2025, 3, 15),
}

# One call per method that renders a view name of its own (#472 names five; the
# repository has ten). They all work today — they are here so the shared helper
# cannot regress any of them unnoticed.
SIBLING_CALLS: list[tuple[str, Callable[[FraiseQLRepository, str], Awaitable[Any]]]] = [
    ("count", lambda repo, view: repo.count(view)),
    ("exists", lambda repo, view: repo.exists(view)),
    ("sum", lambda repo, view: repo.sum(view, "cost")),
    ("avg", lambda repo, view: repo.avg(view, "cost")),
    ("min", lambda repo, view: repo.min(view, "cost")),
    ("max", lambda repo, view: repo.max(view, "cost")),
    ("distinct", lambda repo, view: repo.distinct(view, "status")),
    ("pluck", lambda repo, view: repo.pluck(view, "cost")),
    ("aggregate", lambda repo, view: repo.aggregate(view, {"total": "SUM(cost)"})),
    ("batch_exists", lambda repo, view: repo.batch_exists(view, [ROW_IDS[0]])),
]


def _snapshot(day: str, category: str, status: str, cost: int) -> dict:
    return {
        "date": day,
        "status": status,
        "dimensions": {"category": category},
        "measures": {"cost": cost},
    }


@pytest.fixture
async def qualified_views(class_db_pool, test_schema) -> AsyncIterator[None]:
    """Build the two tables inside ``test_schema`` and leave it off the search path."""
    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        for table in (COARSE, FINE):
            await cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {test_schema}.{table} (
                    id UUID PRIMARY KEY,
                    date DATE NOT NULL,
                    status TEXT NOT NULL,
                    model_category TEXT NOT NULL,
                    cost INTEGER NOT NULL,
                    data JSONB NOT NULL
                )
            """)
        for table, rows in ((FINE, FINE_ROWS), (COARSE, COARSE_ROWS)):
            for row_id, (day, category, status, cost) in zip(ROW_IDS, rows, strict=False):
                await cursor.execute(
                    f"INSERT INTO {test_schema}.{table} "
                    f"(id, date, status, model_category, cost, data) "
                    f"VALUES (%s, %s, %s, %s, %s, %s::jsonb)",
                    (
                        row_id,
                        day,
                        status,
                        category,
                        cost,
                        json.dumps(_snapshot(day, category, status, cost)),
                    ),
                )
        await conn.commit()

    yield

    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        for table in (COARSE, FINE):
            await cursor.execute(f"DROP TABLE IF EXISTS {test_schema}.{table} CASCADE")
        await conn.commit()


async def _execute(pool: Any, query: Any) -> list[tuple]:
    async with pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(query.statement, query.params)
        return await cursor.fetchall()


class TestSearchPathIsClean:
    """Without this, every test below could pass for the wrong reason."""

    async def test_the_unqualified_name_does_not_resolve(
        self, class_db_pool, test_schema, qualified_views
    ) -> None:
        repo = FraiseQLRepository(class_db_pool)

        with pytest.raises(psycopg.errors.UndefinedTable):
            await repo.count(COARSE)


class TestPartialPeriodUnionPath:
    """The reported break: both branch builders render a view name."""

    async def test_both_branches_resolve_their_qualified_view(
        self, class_db_pool, test_schema, qualified_views
    ) -> None:
        query = _build_partial_period_union_query(
            coarse_view=f"{test_schema}.{COARSE}",
            fine_grain_view=f"{test_schema}.{FINE}",
            **UNION_QUERY,
        )

        rows = [json.loads(row[0]) for row in await _execute(class_db_pool, query)]

        assert sorted(
            (r["date"], r["dimensions"]["category"], r["measures"]["cost"]) for r in rows
        ) == [
            # Branch 1, recomputed from the daily table: only 2025-01-20's 10.
            ("2025-01-01", "A", 10),
            # Branch 2, read straight from the monthly table.
            ("2025-02-01", "A", 20),
        ]


class TestSingleStatementPaths:
    """The paths that already split the name, held in place across the refactor."""

    async def test_find_resolves_the_qualified_view(
        self, class_db_pool, test_schema, qualified_views
    ) -> None:
        repo = FraiseQLRepository(class_db_pool)
        query = repo._build_find_query(f"{test_schema}.{FINE}", jsonb_column="data")

        rows = await _execute(class_db_pool, query)

        assert len(rows) == len(FINE_ROWS)

    @pytest.mark.parametrize(("name", "call"), SIBLING_CALLS, ids=[n for n, _ in SIBLING_CALLS])
    async def test_repository_method_resolves_the_qualified_view(
        self, class_db_pool, test_schema, qualified_views, name, call
    ) -> None:
        repo = FraiseQLRepository(class_db_pool)

        await call(repo, f"{test_schema}.{FINE}")

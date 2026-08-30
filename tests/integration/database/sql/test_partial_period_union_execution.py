"""Issue #468: the partial-period UNION, executed against a live database.

The regression tests assert on SQL text. They cannot say whether PostgreSQL accepts
the statement, nor which rows come back — and this change touches both:

* an ``OR``/``NOT`` group now survives into ``extra_where``, so the branches must
  actually *exclude* rows they used to return;
* a caller's ``order_by`` is projected per branch and referenced from a wrapping
  ``SELECT "u"."d" FROM (…) AS "u"("d", "s0")``. That column-alias list is new
  syntax on this path — if it is wrong the tests below fail as a syntax error
  rather than as a bad string comparison.

The fixture builds a coarse monthly view and the fine-grain daily view it is
derived from, with a lower bound mid-January so the window straddles a period
boundary and both branch kinds are exercised.
"""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import pytest

from fraiseql.db import FraiseQLRepository, _build_partial_period_union_query
from fraiseql.partial_period import _build_extra_where
from fraiseql.where_clause import FieldCondition, WhereClause

pytestmark = pytest.mark.database

COARSE = "v_468_month"
FINE = "v_468_day"

# (date, category, status, cost)
FINE_ROWS = [
    ("2025-01-10", "A", "active", 5),  # below the lower bound
    ("2025-01-20", "A", "active", 10),
    ("2025-01-25", "A", "archived", 100),
    ("2025-02-10", "A", "active", 20),
    ("2025-02-15", "B", "pending", 30),
    ("2025-03-05", "A", "archived", 200),
]

# The coarse view, pre-aggregated to month starts. Consistent with FINE_ROWS.
COARSE_ROWS = [
    ("2025-01-01", "A", "active", 15),
    ("2025-01-01", "A", "archived", 100),
    ("2025-02-01", "A", "active", 20),
    ("2025-02-01", "B", "pending", 30),
    ("2025-03-01", "A", "archived", 200),
]

# The window: mid-January (not month-aligned) through the end of March.
# Branch 1 is fine-grain [01-15, 02-01); Branch 2 is coarse [02-01, 04-01).
BASE: dict[str, Any] = {
    "coarse_view": COARSE,
    "fine_grain_view": FINE,
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
    "upper_bound_exclusive": date(2025, 4, 1),
    "today": date(2025, 4, 15),
}


def _snapshot(day: str, category: str, status: str, cost: int) -> dict:
    return {
        "date": day,
        "status": status,
        "dimensions": {"category": category},
        "measures": {"cost": cost},
    }


@pytest.fixture
async def stats_views(class_db_pool, test_schema) -> AsyncIterator[None]:
    """A coarse monthly table and the fine-grain daily table behind it."""
    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"SET search_path TO {test_schema}")
        for table in (COARSE, FINE):
            await cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id UUID PRIMARY KEY,
                    date DATE NOT NULL,
                    status TEXT NOT NULL,
                    model_category TEXT NOT NULL,
                    cost INTEGER NOT NULL,
                    data JSONB NOT NULL
                )
            """)
        for table, rows in ((FINE, FINE_ROWS), (COARSE, COARSE_ROWS)):
            for day, category, status, cost in rows:
                await cursor.execute(
                    f"INSERT INTO {table} (id, date, status, model_category, cost, data) "
                    f"VALUES (%s, %s, %s, %s, %s, %s::jsonb)",
                    (
                        uuid.uuid4(),
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
        await cursor.execute(f"SET search_path TO {test_schema}")
        for table in (COARSE, FINE):
            await cursor.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        await conn.commit()


def _condition(column: str, value: Any, operator: str = "eq") -> FieldCondition:
    return FieldCondition(
        field_path=[column],
        operator=operator,
        value=value,
        lookup_strategy="sql_column",
        target_column=column,
    )


def _lower_bound_condition() -> FieldCondition:
    """The date bound the UNION builder re-encodes per branch."""
    return _condition("date", BASE["lower_bound"], operator="gte")


async def _run(pool: Any, schema: str, **overrides: Any) -> list[dict]:
    """Execute the built UNION query and return the decoded rows, in order.

    A ``where=`` override is the caller's *whole* normalised clause, date bound
    included, and goes through ``_build_extra_where`` exactly as the dispatch in
    ``find()`` does — so these tests cover the construction that dropped the
    OR/NOT groups, not only the builder that renders them.
    """
    where = overrides.pop("where", None)
    if where is not None:
        overrides["extra_where"] = _build_extra_where(
            where, BASE["time_grain_column"], overrides.pop("mandatory", ())
        )
    query = _build_partial_period_union_query(**{**BASE, **overrides})

    async with pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"SET search_path TO {schema}")
        await cursor.execute(query.statement, query.params)
        rows = await cursor.fetchall()

    return [json.loads(row[0]) for row in rows]


def _key(row: dict) -> tuple[str, str, int]:
    return row["date"], row["dimensions"]["category"], row["measures"]["cost"]


class TestUnfiltered:
    """The baseline every filtering test is measured against."""

    async def test_both_branch_kinds_contribute(
        self, class_db_pool, test_schema, stats_views
    ) -> None:
        rows = await _run(class_db_pool, test_schema)

        assert sorted(_key(r) for r in rows) == [
            # Branch 1, recomputed from the daily view: 10 + 100, and no 2025-01-10.
            ("2025-01-01", "A", 110),
            ("2025-02-01", "A", 20),
            ("2025-02-01", "B", 30),
            ("2025-03-01", "A", 200),
        ]


class TestOrGroupFilters:
    """An OR group must exclude rows in every branch, not just survive as text."""

    async def test_or_group_excludes_rows_from_both_branches(
        self, class_db_pool, test_schema, stats_views
    ) -> None:
        """The fail-open shape: the date bound is the only top-level condition."""
        where = WhereClause(
            conditions=[_lower_bound_condition()],
            nested_clauses=[
                WhereClause(
                    nested_clauses=[
                        WhereClause(conditions=[_condition("status", "active")]),
                        WhereClause(conditions=[_condition("status", "pending")]),
                    ],
                    logical_op="OR",
                )
            ],
        )

        rows = await _run(class_db_pool, test_schema, where=where)

        assert sorted(_key(r) for r in rows) == [
            ("2025-01-01", "A", 10),  # the archived 100 is gone
            ("2025-02-01", "A", 20),
            ("2025-02-01", "B", 30),
        ]

    async def test_or_group_combines_with_a_flat_condition(
        self, class_db_pool, test_schema, stats_views
    ) -> None:
        where = WhereClause(
            conditions=[_lower_bound_condition(), _condition("model_category", "A")],
            nested_clauses=[
                WhereClause(
                    nested_clauses=[
                        WhereClause(conditions=[_condition("status", "active")]),
                        WhereClause(conditions=[_condition("status", "pending")]),
                    ],
                    logical_op="OR",
                )
            ],
        )

        rows = await _run(class_db_pool, test_schema, where=where)

        assert sorted(_key(r) for r in rows) == [
            ("2025-01-01", "A", 10),
            ("2025-02-01", "A", 20),
        ]

    async def test_mandatory_filters_and_the_group_both_apply(
        self, class_db_pool, test_schema, stats_views
    ) -> None:
        """#344's injected conditions are ANDed in front of the preserved group."""
        where = WhereClause(
            conditions=[_lower_bound_condition()],
            nested_clauses=[
                WhereClause(
                    nested_clauses=[
                        WhereClause(conditions=[_condition("status", "active")]),
                        WhereClause(conditions=[_condition("status", "pending")]),
                    ],
                    logical_op="OR",
                )
            ],
        )

        rows = await _run(
            class_db_pool,
            test_schema,
            where=where,
            mandatory=[_condition("model_category", "B")],
        )

        assert sorted(_key(r) for r in rows) == [("2025-02-01", "B", 30)]


class TestNotClauseFilters:
    async def test_not_clause_excludes_rows_from_both_branches(
        self, class_db_pool, test_schema, stats_views
    ) -> None:
        where = WhereClause(
            conditions=[_lower_bound_condition()],
            not_clause=WhereClause(conditions=[_condition("status", "active")]),
        )

        rows = await _run(class_db_pool, test_schema, where=where)

        assert sorted(_key(r) for r in rows) == [
            ("2025-01-01", "A", 100),
            ("2025-02-01", "B", 30),
            ("2025-03-01", "A", 200),
        ]


class TestOrderByAcrossTheUnion:
    """The wrapper is new SQL on this path — these fail as syntax errors if it is wrong."""

    @staticmethod
    def _order_by(pool: Any, spec: Any) -> Any:
        return FraiseQLRepository(pool)._resolve_order_by_set(spec)

    async def test_measure_alias_orders_the_whole_result(
        self, class_db_pool, test_schema, stats_views
    ) -> None:
        rows = await _run(
            class_db_pool,
            test_schema,
            order_by=self._order_by(class_db_pool, {"measures": {"cost": "desc"}}),
        )

        assert [r["measures"]["cost"] for r in rows] == [200, 110, 30, 20]

    async def test_mapped_dimension_orders_the_whole_result(
        self, class_db_pool, test_schema, stats_views
    ) -> None:
        """Ordering on the mapped path sorts on ``model_category``, across branches."""
        rows = await _run(
            class_db_pool,
            test_schema,
            order_by=self._order_by(class_db_pool, {"dimensions": {"category": "desc"}}),
        )

        assert [r["dimensions"]["category"] for r in rows] == ["B", "A", "A", "A"]

    async def test_native_dimension_orders_across_branch_kinds(
        self, class_db_pool, test_schema, stats_views
    ) -> None:
        """``date`` is truncated in the fine branch and read raw in the coarse one."""
        rows = await _run(
            class_db_pool,
            test_schema,
            order_by=self._order_by(class_db_pool, {"date": "desc"}),
        )

        assert [r["date"] for r in rows] == [
            "2025-03-01",
            "2025-02-01",
            "2025-02-01",
            "2025-01-01",
        ]

    async def test_two_sort_keys_apply_in_order(
        self, class_db_pool, test_schema, stats_views
    ) -> None:
        rows = await _run(
            class_db_pool,
            test_schema,
            order_by=self._order_by(
                class_db_pool, {"date": "asc", "dimensions": {"category": "desc"}}
            ),
        )

        assert [_key(r) for r in rows] == [
            ("2025-01-01", "A", 110),
            ("2025-02-01", "B", 30),
            ("2025-02-01", "A", 20),
            ("2025-03-01", "A", 200),
        ]

    async def test_ordering_and_filtering_compose(
        self, class_db_pool, test_schema, stats_views
    ) -> None:
        where = WhereClause(
            conditions=[_lower_bound_condition()],
            not_clause=WhereClause(conditions=[_condition("status", "active")]),
        )

        rows = await _run(
            class_db_pool,
            test_schema,
            where=where,
            order_by=self._order_by(class_db_pool, {"measures": {"cost": "asc"}}),
        )

        assert [_key(r) for r in rows] == [
            ("2025-02-01", "B", 30),
            ("2025-01-01", "A", 100),
            ("2025-03-01", "A", 200),
        ]

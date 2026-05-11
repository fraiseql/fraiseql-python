"""Regression tests for Issue #344: mandatory_filters for db.find().

Security bug: filters passed as bare keyword arguments (e.g. tenant_id=...)
were silently dropped when auto-aggregation triggered the UNION ALL code path,
causing cross-tenant data exposure.

These tests verify that the new `mandatory_filters` parameter produces WHERE
conditions in ALL query modes:
  - Normal path (_build_find_query)
  - Aggregated path (group_by without union-all)
  - Union-all path (_build_partial_period_union_query)
  - find_one path (_build_find_one_query)
  - count / exists paths
"""

import uuid
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fraiseql.core.rust_pipeline import RustResponseBytes
from fraiseql.db import (
    FraiseQLRepository,
    _build_partial_period_union_query,
    _table_metadata,
)
from fraiseql.where_clause import FieldCondition, WhereClause

TENANT_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
ORG_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_repo() -> FraiseQLRepository:
    """Create a FraiseQLRepository with a mock pool."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    ctx = mock_pool.connection.return_value
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return FraiseQLRepository(mock_pool)


def _render_sql(query: Any) -> str:
    """Render a DatabaseQuery's statement to a string."""
    return query.statement.as_string(None)


# ── Unit tests: _build_where_clause with mandatory_filters ───────────────


class TestBuildWhereClauseMandatoryFilters:
    """Test that _mandatory_parts/_mandatory_params are consumed by _build_where_clause."""

    def test_find_normal_path_includes_mandatory_filter(self) -> None:
        """mandatory_filters must appear in WHERE on the normal (non-aggregated) path."""
        repo = _make_repo()
        query = repo._build_find_query(
            "v_stats",
            mandatory_filters={"tenant_id": TENANT_ID},
        )
        rendered = _render_sql(query)
        assert "tenant_id" in rendered, f"tenant_id missing from normal-path SQL:\n{rendered}"

    def test_find_one_includes_mandatory_filter(self) -> None:
        """mandatory_filters must appear in WHERE for find_one."""
        repo = _make_repo()
        query = repo._build_find_one_query(
            "v_stats",
            mandatory_filters={"tenant_id": TENANT_ID},
        )
        rendered = _render_sql(query)
        assert "tenant_id" in rendered, f"tenant_id missing from find_one SQL:\n{rendered}"
        assert "LIMIT" in rendered

    def test_mandatory_filter_value_is_parameterised(self) -> None:
        """Value must be %s placeholder, not a UUID literal in the SQL."""
        repo = _make_repo()
        query = repo._build_find_query(
            "v_stats",
            mandatory_filters={"tenant_id": TENANT_ID},
        )
        rendered = _render_sql(query)
        # The UUID string must NOT appear in the rendered SQL
        assert str(TENANT_ID) not in rendered, (
            "tenant_id value should be parameterised, not interpolated as literal"
        )
        # The value must be in the params list
        assert TENANT_ID in query.params

    def test_multiple_mandatory_filters(self) -> None:
        """Two mandatory conditions must both appear in the SQL."""
        repo = _make_repo()
        query = repo._build_find_query(
            "v_stats",
            mandatory_filters={"tenant_id": TENANT_ID, "org_id": ORG_ID},
        )
        rendered = _render_sql(query)
        assert "tenant_id" in rendered
        assert "org_id" in rendered
        assert TENANT_ID in query.params
        assert ORG_ID in query.params

    def test_mandatory_filters_coexist_with_where(self) -> None:
        """Both mandatory_filters and user `where` must appear in SQL."""
        repo = _make_repo()
        query = repo._build_find_query(
            "v_stats",
            mandatory_filters={"tenant_id": TENANT_ID},
            where={"status": {"eq": "active"}},
        )
        rendered = _render_sql(query)
        assert "tenant_id" in rendered
        # The user where clause should also be present
        assert "status" in rendered


# ── Unit tests: UNION ALL path with mandatory_filters ────────────────────


class TestUnionAllMandatoryFilters:
    """Test that mandatory_filters appear in every branch of UNION ALL queries."""

    def test_find_union_all_includes_mandatory_filter(self) -> None:
        """All branches of UNION ALL must have tenant_id in WHERE."""
        # Build a WhereClause with a mandatory tenant_id condition
        mandatory_wc = WhereClause(
            conditions=[
                FieldCondition(
                    field_path=["tenant_id"],
                    operator="eq",
                    value=TENANT_ID,
                    lookup_strategy="sql_column",
                    target_column="tenant_id",
                ),
            ]
        )

        query = _build_partial_period_union_query(
            coarse_view="v_events_month",
            fine_grain_view="v_events_day",
            time_grain_column="date",
            time_grain_trunc="month",
            group_by=["date"],
            aggregations={"measures.volume": "SUM(measures.volume)"},
            native_dimensions={"date"},
            native_measures={"measures.volume": "volume"},
            native_dimension_mapping=None,
            jsonb_col="data",
            extra_where=mandatory_wc,
            lower_bound=date(2024, 1, 15),  # non-aligned → 3 branches
            today=date(2024, 3, 20),
        )
        rendered = _render_sql(query)

        # Split on UNION ALL to check each branch
        branches = rendered.split("UNION ALL")
        assert len(branches) == 3, f"Expected 3 branches, got {len(branches)}"

        for i, branch in enumerate(branches, 1):
            assert "tenant_id" in branch, (
                f"tenant_id missing from branch {i} of UNION ALL:\n{branch}"
            )

    def test_union_all_mandatory_filter_with_two_branches(self) -> None:
        """Aligned lower bound → 2 branches, both must have tenant_id."""
        mandatory_wc = WhereClause(
            conditions=[
                FieldCondition(
                    field_path=["tenant_id"],
                    operator="eq",
                    value=TENANT_ID,
                    lookup_strategy="sql_column",
                    target_column="tenant_id",
                ),
            ]
        )

        query = _build_partial_period_union_query(
            coarse_view="v_events_month",
            fine_grain_view="v_events_day",
            time_grain_column="date",
            time_grain_trunc="month",
            group_by=["date"],
            aggregations={"measures.volume": "SUM(measures.volume)"},
            native_dimensions={"date"},
            native_measures={"measures.volume": "volume"},
            native_dimension_mapping=None,
            jsonb_col="data",
            extra_where=mandatory_wc,
            lower_bound=date(2024, 2, 1),  # aligned → 2 branches
            today=date(2024, 3, 20),
        )
        rendered = _render_sql(query)

        branches = rendered.split("UNION ALL")
        assert len(branches) == 2
        for i, branch in enumerate(branches, 1):
            assert "tenant_id" in branch, f"tenant_id missing from branch {i}:\n{branch}"


# ── Integration tests: db.find() end-to-end with SQL capture ────────────


class TestFindMandatoryFiltersIntegration:
    """End-to-end tests that drive db.find() and capture the generated SQL."""

    def setup_method(self) -> None:
        self._original = _table_metadata.copy()

    def teardown_method(self) -> None:
        _table_metadata.clear()
        _table_metadata.update(self._original)

    @pytest.mark.asyncio
    async def test_find_normal_path_e2e(self) -> None:
        """mandatory_filters reaches the SQL in a normal (non-aggregated) find()."""
        repo = _make_repo()
        mock_result = b'{"data":{"stats":[]}}'

        with patch(
            "fraiseql.db.execute_via_rust_pipeline",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_exec:
            await repo.find(
                "v_stats",
                mandatory_filters={"tenant_id": TENANT_ID},
            )
            call_args = mock_exec.call_args
            statement = call_args[0][1]  # second positional arg is the SQL statement
            params = call_args[0][2]  # third positional arg is params
            rendered = statement.as_string(None)
            assert "tenant_id" in rendered, f"tenant_id missing from find() SQL:\n{rendered}"
            assert TENANT_ID in params

    @pytest.mark.asyncio
    async def test_find_aggregated_path_e2e(self) -> None:
        """mandatory_filters appears in SQL on the aggregated (non-union) path."""
        _table_metadata["v_stats_month"] = {
            "columns": set(),
            "has_jsonb_data": True,
            "jsonb_column": "data",
            "fk_relationships": {},
            "validate_fk_strict": True,
            "aggregation": {
                "measures": {"measures.cost": "SUM"},
                "dimensions": "dimensions",
            },
        }
        repo = _make_repo()
        mock_result = b'{"data":{"stats_month":[]}}'
        mock_info = MagicMock()
        mock_info.schema = None

        with (
            patch(
                "fraiseql.core.ast_parser.extract_field_paths_from_info",
                return_value=[
                    MagicMock(path=["dimensions", "date"]),
                    MagicMock(path=["measures", "cost"]),
                ],
            ),
            patch(
                "fraiseql.db.execute_via_rust_pipeline",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_exec,
        ):
            await repo.find(
                "v_stats_month",
                mandatory_filters={"tenant_id": TENANT_ID},
                info=mock_info,
            )
            statement = mock_exec.call_args[0][1]
            params = mock_exec.call_args[0][2]
            rendered = statement.as_string(None)
            assert "tenant_id" in rendered, (
                f"tenant_id missing from aggregated-path SQL:\n{rendered}"
            )
            assert TENANT_ID in params

    @pytest.mark.asyncio
    async def test_find_union_all_path_e2e(self) -> None:
        """mandatory_filters appears in every branch of UNION ALL SQL from find()."""
        _table_metadata["v_stats_month"] = {
            "columns": set(),
            "has_jsonb_data": True,
            "jsonb_column": "data",
            "fk_relationships": {},
            "validate_fk_strict": True,
            "aggregation": {
                "measures": {"measures.cost": "SUM"},
                "dimensions": "dimensions",
                "fine_grain_view": "v_stats_day",
                "time_grain_column": "date",
                "time_grain_trunc": "month",
            },
        }
        repo = _make_repo()
        mock_result = b'{"data":{"stats_month":[]}}'
        mock_info = MagicMock()
        mock_info.schema = None

        with (
            patch(
                "fraiseql.core.ast_parser.extract_field_paths_from_info",
                return_value=[
                    MagicMock(path=["dimensions", "date"]),
                    MagicMock(path=["measures", "cost"]),
                ],
            ),
            patch(
                "fraiseql.db.execute_via_rust_pipeline",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_exec,
        ):
            await repo.find(
                "v_stats_month",
                mandatory_filters={"tenant_id": TENANT_ID},
                where={"date": {"gte": "2024-01-15"}},
                info=mock_info,
            )
            statement = mock_exec.call_args[0][1]
            rendered = statement.as_string(None)

            # Every branch must contain tenant_id
            branches = rendered.split("UNION ALL")
            for i, branch in enumerate(branches, 1):
                assert "tenant_id" in branch, (
                    f"tenant_id missing from UNION ALL branch {i}:\n{branch}"
                )

    @pytest.mark.asyncio
    async def test_find_one_e2e(self) -> None:
        """mandatory_filters reaches the SQL in find_one()."""
        repo = _make_repo()
        mock_result = RustResponseBytes(b'{"data":{"stats":{"id":1}}}')

        with patch(
            "fraiseql.db.execute_via_rust_pipeline",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_exec:
            await repo.find_one(
                "v_stats",
                mandatory_filters={"tenant_id": TENANT_ID},
            )
            statement = mock_exec.call_args[0][1]
            params = mock_exec.call_args[0][2]
            rendered = statement.as_string(None)
            assert "tenant_id" in rendered, f"tenant_id missing from find_one SQL:\n{rendered}"
            assert TENANT_ID in params


# ── count / exists tests ─────────────────────────────────────────────────


class TestCountExistsMandatoryFilters:
    """Test mandatory_filters on count() and exists()."""

    def _make_db_repo(self) -> tuple[FraiseQLRepository, list[Any]]:
        """Create a repo with SQL-capturing cursor mock."""
        captured: list[Any] = []

        mock_cursor = AsyncMock()

        async def capture_execute(query, params=None):
            captured.append((query.as_string(None), params))

        mock_cursor.execute = AsyncMock(side_effect=capture_execute)
        mock_cursor.fetchone = AsyncMock(return_value=(42,))

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_cursor),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        mock_pool = MagicMock()
        mock_pool.connection = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        return FraiseQLRepository(mock_pool), captured

    @pytest.mark.asyncio
    async def test_count_includes_mandatory_filter(self) -> None:
        """mandatory_filters must appear in count() SQL."""
        repo, captured = self._make_db_repo()

        await repo.count(
            "v_stats",
            mandatory_filters={"tenant_id": TENANT_ID},
        )
        assert len(captured) == 1
        sql_str, _params = captured[0]
        assert "tenant_id" in sql_str, f"tenant_id missing from count() SQL:\n{sql_str}"

    @pytest.mark.asyncio
    async def test_exists_includes_mandatory_filter(self) -> None:
        """mandatory_filters must appear in exists() SQL."""
        repo, captured = self._make_db_repo()

        await repo.exists(
            "v_stats",
            mandatory_filters={"tenant_id": TENANT_ID},
        )
        assert len(captured) == 1
        sql_str, _params = captured[0]
        assert "tenant_id" in sql_str, f"tenant_id missing from exists() SQL:\n{sql_str}"


# ── Placeholder for phase 4 ─────────────────────────────────────────────


def test_bare_tenant_id_kwarg_raises_type_error() -> None:
    """Bare tenant_id= kwarg raises TypeError after refactor (#344)."""
    repo = _make_repo()
    with pytest.raises(TypeError, match="unexpected keyword"):
        repo._build_find_query("v_stats", tenant_id=TENANT_ID)

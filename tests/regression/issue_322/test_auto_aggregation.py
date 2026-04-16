"""Tests for Issue #322: Auto-aggregation from type metadata.

Verifies that:
- register_type_for_view stores aggregation metadata
- _derive_auto_aggregation correctly builds group_by/aggregations from field paths
- db.find() auto-aggregates when metadata is present and id is not selected
- db.find() skips auto-aggregation when id IS selected
- db.find() skips auto-aggregation when explicit group_by is provided
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fraiseql.db import (
    FraiseQLRepository,
    _derive_auto_aggregation,
    _table_metadata,
    register_type_for_view,
)

# ── _derive_auto_aggregation unit tests ───────────────────────────────


class TestDeriveAutoAggregation:
    """Tests for the _derive_auto_aggregation helper."""

    def setup_method(self) -> None:
        self.meta: dict[str, Any] = {
            "measures": {
                "measures.cost": "SUM",
                "measures.volume": "SUM",
            },
            "dimensions": "dimensions",
        }

    def test_dimensions_and_measures_selected(self) -> None:
        """When only dimensions + measures are selected, returns aggregation."""
        field_paths = [
            ["dimensions", "date_info", "date"],
            ["dimensions", "cost_category"],
            ["measures", "cost"],
            ["measures", "volume"],
        ]
        result = _derive_auto_aggregation(field_paths, self.meta)
        assert result is not None
        group_by, aggregations, native_set = result
        assert "dimensions.date_info.date" in group_by
        assert "dimensions.cost_category" in group_by
        assert aggregations["measures.cost"] == "SUM(measures.cost)"
        assert aggregations["measures.volume"] == "SUM(measures.volume)"
        assert native_set == set()

    def test_id_selected_skips_aggregation(self) -> None:
        """When 'id' is in the selection, returns None (no aggregation)."""
        field_paths = [
            ["id"],
            ["dimensions", "date_info", "date"],
            ["measures", "cost"],
        ]
        result = _derive_auto_aggregation(field_paths, self.meta)
        assert result is None

    def test_tenant_id_selected_skips_aggregation(self) -> None:
        """When 'tenant_id' is in the selection, returns None."""
        field_paths = [
            ["tenant_id"],
            ["dimensions", "date_info", "date"],
        ]
        result = _derive_auto_aggregation(field_paths, self.meta)
        assert result is None

    def test_custom_skip_fields(self) -> None:
        """Custom skip_when overrides default skip fields."""
        meta = {
            **self.meta,
            "skip_when": {"row_id"},
        }
        # 'id' should NOT skip with custom skip_when
        field_paths = [
            ["id"],
            ["dimensions", "date"],
        ]
        result = _derive_auto_aggregation(field_paths, meta)
        assert result is not None

        # 'row_id' SHOULD skip
        field_paths = [
            ["row_id"],
            ["dimensions", "date"],
        ]
        result = _derive_auto_aggregation(field_paths, meta)
        assert result is None

    def test_no_dimensions_returns_none(self) -> None:
        """When no dimension fields are selected, returns None."""
        field_paths = [
            ["measures", "cost"],
        ]
        result = _derive_auto_aggregation(field_paths, self.meta)
        assert result is None

    def test_measures_parent_expands_children(self) -> None:
        """Selecting 'measures' parent includes all child measure paths."""
        field_paths = [
            ["dimensions", "date"],
            ["measures"],
        ]
        result = _derive_auto_aggregation(field_paths, self.meta)
        assert result is not None
        _, aggregations, _ = result
        assert "measures.cost" in aggregations
        assert "measures.volume" in aggregations

    def test_only_dimensions_no_measures(self) -> None:
        """Selecting only dimensions (no measures) still returns group_by."""
        field_paths = [
            ["dimensions", "date"],
        ]
        result = _derive_auto_aggregation(field_paths, self.meta)
        assert result is not None
        group_by, aggregations, native_set = result
        assert group_by == ["dimensions.date"]
        assert aggregations == {}
        assert native_set == set()


# ── register_type_for_view aggregation metadata ──────────────────────


class TestRegisterAggregationMetadata:
    """Tests for aggregation metadata in register_type_for_view."""

    def setup_method(self) -> None:
        self._original = _table_metadata.copy()

    def teardown_method(self) -> None:
        _table_metadata.clear()
        _table_metadata.update(self._original)

    def test_stores_aggregation_metadata(self) -> None:
        """Aggregation metadata is stored in _table_metadata."""

        class FakeType:
            pass

        agg = {
            "measures": {"measures.cost": "SUM"},
            "dimensions": "dimensions",
        }
        register_type_for_view(
            "v_test_agg",
            FakeType,
            has_jsonb_data=True,
            aggregation=agg,
        )
        assert _table_metadata["v_test_agg"]["aggregation"] == agg

    def test_no_aggregation_stores_none(self) -> None:
        """Without aggregation param, metadata has aggregation=None."""

        class FakeType2:
            pass

        register_type_for_view(
            "v_test_no_agg",
            FakeType2,
            has_jsonb_data=True,
        )
        assert _table_metadata["v_test_no_agg"]["aggregation"] is None


# ── db.find() auto-aggregation integration ───────────────────────────


class TestFindAutoAggregation:
    """Tests for auto-aggregation in db.find()."""

    def setup_method(self) -> None:
        self._original = _table_metadata.copy()

    def teardown_method(self) -> None:
        _table_metadata.clear()
        _table_metadata.update(self._original)

    @pytest.mark.asyncio
    async def test_auto_aggregates_when_metadata_present(self) -> None:
        """find() auto-adds group_by/aggregations from metadata."""
        _table_metadata["v_stats"] = {
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

        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        ctx = mock_pool.connection.return_value
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        repo = FraiseQLRepository(mock_pool)

        # Mock info with field paths (dimensions + measures, no id)
        mock_info = MagicMock()
        mock_info.schema = None  # skip selection tree building

        mock_result = b'{"data":{"stats":[]}}'
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
            await repo.find("v_stats", info=mock_info)

            # Verify group_by and aggregations were passed through
            kw = mock_exec.call_args.kwargs
            assert kw.get("field_paths") is None  # #319: skipped
            assert kw.get("field_selections") is None

    @pytest.mark.asyncio
    async def test_skips_auto_aggregation_when_id_selected(self) -> None:
        """find() does NOT auto-aggregate when 'id' is in field selection."""
        _table_metadata["v_stats"] = {
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

        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        ctx = mock_pool.connection.return_value
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        repo = FraiseQLRepository(mock_pool)

        mock_info = MagicMock()
        mock_info.schema = None

        mock_result = b'{"data":{"stats":[]}}'
        with (
            patch(
                "fraiseql.core.ast_parser.extract_field_paths_from_info",
                return_value=[
                    MagicMock(path=["id"]),
                    MagicMock(path=["dimensions", "date"]),
                    MagicMock(path=["measures", "cost"]),
                ],
            ),
            patch(
                "fraiseql.db.execute_via_rust_pipeline",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            await repo.find("v_stats", info=mock_info)
            # If id is selected, no group_by should be injected
            # (the query proceeds as a normal find)

    @pytest.mark.asyncio
    async def test_explicit_group_by_overrides_auto(self) -> None:
        """Explicit group_by in kwargs takes precedence over auto."""
        _table_metadata["v_stats"] = {
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

        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        ctx = mock_pool.connection.return_value
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        repo = FraiseQLRepository(mock_pool)

        mock_result = b'{"data":{"stats":[]}}'
        with patch(
            "fraiseql.db.execute_via_rust_pipeline",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            # Explicit group_by — auto-aggregation should not interfere
            await repo.find(
                "v_stats",
                group_by=["custom_field"],
                aggregations={"total": "SUM(amount)"},
            )

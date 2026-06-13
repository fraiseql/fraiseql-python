"""Unit tests for native measures support in _build_find_query.

Tests the native_measures feature following TDD methodology.
This test should initially FAIL until the feature is implemented.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fraiseql.db import FraiseQLRepository, _table_metadata


class TestBuildFindQueryNativeMeasures:
    """Tests for native_measures support in _build_find_query."""

    def setup_method(self) -> None:
        self._original = _table_metadata.copy()
        self.mock_conn = MagicMock()
        self.repo = FraiseQLRepository(self.mock_conn)

    def teardown_method(self) -> None:
        _table_metadata.clear()
        _table_metadata.update(self._original)

    def test_build_find_query_uses_native_measure_column(self) -> None:
        """Native measures use t."col" instead of JSONB extraction, no ::numeric cast."""
        query = self.repo._build_find_query(
            "v_analytics_day",
            group_by=["dimensions.date"],
            aggregations={"measures.volume": "SUM(measures.volume)"},
            native_measures={"measures.volume": "volume"},
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)

        # Native measure: SUM("t"."volume") (flat column reference)
        assert 'SUM("t"."volume")' in sql_str
        # No JSONB extraction for native measure
        assert "->>'volume'" not in sql_str
        # No ::numeric cast for native measure column
        assert 'SUM(t."volume")::numeric' not in sql_str
        # JSONB dimension still uses extraction
        assert "\"data\"->'dimensions'->>'date'" in sql_str

    @pytest.mark.asyncio
    async def test_find_passes_native_measures_to_build_find_query(self) -> None:
        """find() forwards native_measures from agg_meta to _build_find_query."""
        _table_metadata["v_test"] = {
            "columns": set(),
            "has_jsonb_data": True,
            "jsonb_column": "data",
            "fk_relationships": {},
            "validate_fk_strict": True,
            "aggregation": {
                "measures": {"measures.volume": "SUM"},
                "dimensions": "dimensions",
                "native_measures": {"measures.volume": "volume"},
            },
        }

        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        ctx = mock_pool.connection.return_value
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        repo = FraiseQLRepository(mock_pool)

        # Mock info with field paths that trigger auto-aggregation
        mock_info = MagicMock()
        mock_info.schema = None  # skip selection tree building

        mock_result = b'{"data":{"stats":[]}}'
        with (
            patch(
                "fraiseql.core.ast_parser.extract_field_paths_from_info",
                return_value=[
                    MagicMock(path=["dimensions", "date"]),
                    MagicMock(path=["measures", "volume"]),
                ],
            ),
            patch.object(
                repo,
                "_build_find_query",
                return_value=MagicMock(),
            ) as mock_build,
            patch(
                "fraiseql.db.execute_via_rust_pipeline",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            await repo.find("v_test", info=mock_info)

            # Verify _build_find_query was called with native_measures
            mock_build.assert_called_once()
            call_kwargs = mock_build.call_args[1]  # kwargs dict
            assert "native_measures" in call_kwargs
            assert call_kwargs["native_measures"] == {"measures.volume": "volume"}

    @pytest.mark.asyncio
    async def test_auto_aggregation_full_native_path(self) -> None:
        """find() auto-aggregates with both native_measures and native_dimension_mapping."""
        _table_metadata["v_full_native"] = {
            "columns": set(),
            "has_jsonb_data": True,
            "jsonb_column": "data",
            "fk_relationships": {},
            "validate_fk_strict": True,
            "aggregation": {
                "measures": {"measures.volume": "SUM", "measures.cost": "SUM"},
                "dimensions": "dimensions",
                "native_measures": {"measures.volume": "volume"},
                "native_dimension_mapping": {"dimensions.category.id": "category_id"},
            },
        }

        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        ctx = mock_pool.connection.return_value
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        repo = FraiseQLRepository(mock_pool)

        # Mock info with field paths that trigger auto-aggregation
        mock_info = MagicMock()
        mock_info.schema = None  # skip selection tree building

        mock_result = b'{"data":{"stats":[]}}'
        with (
            patch(
                "fraiseql.core.ast_parser.extract_field_paths_from_info",
                return_value=[
                    MagicMock(path=["dimensions", "category", "id"]),
                    MagicMock(path=["dimensions", "date"]),
                    MagicMock(path=["measures", "volume"]),
                    MagicMock(path=["measures", "cost"]),
                ],
            ),
            patch.object(
                repo,
                "_build_find_query",
                return_value=MagicMock(),
            ) as mock_build,
            patch(
                "fraiseql.db.execute_via_rust_pipeline",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            await repo.find("v_full_native", info=mock_info)

            # Verify _build_find_query was called with both native mappings
            mock_build.assert_called_once()
            call_kwargs = mock_build.call_args[1]  # kwargs dict
            assert "native_measures" in call_kwargs
            assert call_kwargs["native_measures"] == {"measures.volume": "volume"}
            assert "native_dimension_mapping" in call_kwargs
            assert call_kwargs["native_dimension_mapping"] == {
                "dimensions.category.id": "category_id"
            }

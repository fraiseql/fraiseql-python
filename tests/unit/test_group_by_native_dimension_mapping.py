"""Unit tests for native_dimension_mapping support in _build_find_query.

Tests the native_dimension_mapping feature following TDD methodology.
This test should initially FAIL until the feature is implemented.
"""

from unittest.mock import MagicMock

from fraiseql.db import FraiseQLRepository


class TestBuildFindQueryNativeDimensionMapping:
    """Tests for native_dimension_mapping support in _build_find_query."""

    def setup_method(self) -> None:
        self.mock_conn = MagicMock()
        self.repo = FraiseQLRepository(self.mock_conn)

    def test_build_find_query_uses_native_dimension_mapping(self) -> None:
        """Mapped dimensions use t."col" instead of JSONB extraction."""
        query = self.repo._build_find_query(
            "v_analytics_day",
            group_by=["dimensions.category.id", "dimensions.date"],
            native_dimension_mapping={"dimensions.category.id": "category_id"},
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)

        # Mapped dimension: "t"."category_id" (flat column reference)
        assert '"t"."category_id"' in sql_str
        # No JSONB extraction for mapped dimension
        assert "\"data\"->'dimensions'->'category'->>'id'" not in sql_str
        # Unmapped dimension still uses JSONB extraction
        assert "\"data\"->'dimensions'->>'date'" in sql_str
        # GROUP BY uses mapped column
        assert 'GROUP BY "t"."category_id"' in sql_str

    def test_derive_auto_aggregation_passes_native_dim_mapping(self) -> None:
        """_derive_auto_aggregation returns native_dimension_mapping in 4-tuple."""
        from fraiseql.db import _derive_auto_aggregation

        meta = {
            "measures": {"measures.volume": "SUM"},
            "dimensions": "dimensions",
            "native_dimension_mapping": {"dimensions.category.id": "category_id"},
        }
        field_paths = [["dimensions", "category", "id"], ["measures", "volume"]]

        result = _derive_auto_aggregation(field_paths, meta)
        assert result is not None
        assert len(result) == 4
        group_by, aggregations, native_dims, native_dim_mapping = result
        assert "dimensions.category.id" in group_by
        assert aggregations == {"measures.volume": "SUM(measures.volume)"}
        assert native_dims == set()
        assert native_dim_mapping == {"dimensions.category.id": "category_id"}

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


class TestNativeDimensionMappingKeyCasing:
    """Mapping keys are matched against snake_case field paths (issue #467, D2).

    Field paths are built with ``transform_path=to_snake_case``, so a key
    declared in GraphQL spelling (``dimensions.dateInfo.date``) could never
    match one. Keys are normalized segment-wise at registration instead, so
    both spellings resolve to the same entry and every consumer sees one.
    """

    CAMEL = "dimensions.dateInfo.date"
    SNAKE = "dimensions.date_info.date"

    def setup_method(self) -> None:
        self.mock_conn = MagicMock()
        self.repo = FraiseQLRepository(self.mock_conn)

    def teardown_method(self) -> None:
        from fraiseql.db import _table_metadata, _type_registry

        for registry in (_table_metadata, _type_registry):
            for view in [v for v in registry if v.startswith("v_casing")]:
                del registry[view]

    def _register(self, view_name: str, key: str) -> dict:
        from fraiseql.db import _table_metadata, register_type_for_view

        register_type_for_view(
            view_name,
            type("Stats", (), {}),
            table_columns={"id", "data", "period_date"},
            aggregation={
                "measures": {"measures.cost": "SUM"},
                "dimensions": "dimensions",
                "native_dimension_mapping": {key: "period_date"},
            },
        )
        return _table_metadata[view_name]["aggregation"]

    def test_camel_case_key_is_normalized_at_registration(self) -> None:
        agg = self._register("v_casing_camel", self.CAMEL)

        assert agg["native_dimension_mapping"] == {self.SNAKE: "period_date"}

    def test_both_spellings_register_identically(self) -> None:
        camel = self._register("v_casing_camel_eq", self.CAMEL)
        snake = self._register("v_casing_snake_eq", self.SNAKE)

        assert camel["native_dimension_mapping"] == snake["native_dimension_mapping"]

    def test_registration_does_not_mutate_the_caller_dict(self) -> None:
        from fraiseql.db import register_type_for_view

        mapping = {self.CAMEL: "period_date"}
        aggregation = {"dimensions": "dimensions", "native_dimension_mapping": mapping}

        register_type_for_view(
            "v_casing_no_mutation",
            type("Stats", (), {}),
            table_columns={"id", "data", "period_date"},
            aggregation=aggregation,
        )

        assert mapping == {self.CAMEL: "period_date"}
        assert aggregation["native_dimension_mapping"] is mapping

    def test_camel_case_key_reaches_group_by_as_native_column(self) -> None:
        """End to end: the declared column lands in GROUP BY, not a JSONB path."""
        from fraiseql.db import _derive_auto_aggregation

        agg = self._register("v_casing_group_by", self.CAMEL)
        field_paths = [["dimensions", "date_info", "date"], ["measures", "cost"]]

        derived = _derive_auto_aggregation(field_paths, agg)
        assert derived is not None
        group_by, aggregations, native_dims, native_dim_mapping = derived
        assert native_dim_mapping == {self.SNAKE: "period_date"}

        query = self.repo._build_find_query(
            "v_casing_group_by",
            group_by=group_by,
            aggregations=aggregations,
            native_dimensions=native_dims,
            native_dimension_mapping=native_dim_mapping,
            jsonb_column="data",
        )
        sql_str = query.statement.as_string(None)

        assert '"t"."period_date"' in sql_str
        assert "->'date_info'" not in sql_str

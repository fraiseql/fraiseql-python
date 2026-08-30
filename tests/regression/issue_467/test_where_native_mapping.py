"""Issue #467: the declared column mapping now reaches the WHERE resolver.

The reporter registered ``native_dimension_mapping`` against an analytics view,
saw it honoured in ``GROUP BY``, and found via ``EXPLAIN`` that the same paths in
``WHERE`` were still being read out of the JSONB snapshot. One of their two
entries (``dimensions.item.id``) was already native — the ``<parent>_id``
convention reaches it — but ``dimensions.item.model.category`` was reachable by
no mechanism at all.

These tests assert on rendered SQL for the reporter's exact registration, through
``FraiseQLRepository._normalize_where``: the single site where the rewrite is
applied, and the one both query paths funnel through.
"""

import logging
from unittest.mock import MagicMock

import pytest

from fraiseql.db import FraiseQLRepository, _table_metadata, _type_registry, register_type_for_view

VIEW = "v_467_stats_month"
COLUMNS = {"id", "data", "item_id", "model_category", "date"}
MAPPING = {
    "dimensions.item.id": "item_id",
    "dimensions.item.model.category": "model_category",
}


class _Stats:
    """Stand-in for the reporter's @fraise_type analytics class."""


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    for view in [v for v in _table_metadata if v.startswith("v_467")]:
        del _table_metadata[view]
    for view in [v for v in _type_registry if v.startswith("v_467")]:
        del _type_registry[view]


def _register(view_name: str = VIEW, **overrides: object) -> None:
    """The reporter's registration: the mapping declared under ``aggregation``."""
    kwargs = {
        "table_columns": COLUMNS,
        "has_jsonb_data": True,
        "jsonb_column": "data",
        "aggregation": {
            "dimensions": "dimensions",
            "measures": {"measures.cost": "SUM"},
            "native_dimension_mapping": MAPPING,
        },
    }
    kwargs.update(overrides)
    register_type_for_view(view_name, _Stats, **kwargs)


def _sql(where: dict, view_name: str = VIEW, columns: set[str] | None = None) -> str:
    repo = FraiseQLRepository(MagicMock())
    clause = repo._normalize_where(where, view_name, columns or COLUMNS)
    sql, _params = clause.to_sql()
    return sql.as_string(None)


class TestNativeDimensionMappingInWhere:
    """The mapping declared under ``aggregation`` feeds the WHERE resolver."""

    def test_deep_mapped_path_becomes_a_column(self) -> None:
        _register()

        rendered = _sql({"dimensions": {"item": {"model": {"category": {"eq": "laser"}}}}})

        assert '"model_category" = ' in rendered
        assert "data" not in rendered

    def test_convention_resolved_path_stays_native(self) -> None:
        """``dimensions.item.id`` was already ``item_id``; the mapping must agree."""
        _register()

        rendered = _sql({"dimensions": {"item": {"id": {"eq": "abc"}}}})

        assert '"item_id" = ' in rendered

    def test_id_path_keeps_fk_column_strategy(self) -> None:
        """``fk_column`` is what the ltree ``*_of_id`` operators key on."""
        _register()
        repo = FraiseQLRepository(MagicMock())

        clause = repo._normalize_where(
            {"dimensions": {"item": {"id": {"eq": "abc"}}}}, VIEW, COLUMNS
        )

        assert clause.conditions[0].lookup_strategy == "fk_column"
        assert clause.conditions[0].target_column == "item_id"

    def test_unmapped_path_still_uses_jsonb(self) -> None:
        _register()

        rendered = _sql({"dimensions": {"item": {"model": {"name": {"eq": "X1"}}}}})

        assert "model_category" not in rendered
        assert "'model'" in rendered
        assert "'name'" in rendered

    def test_camelcase_key_spelling_fires_too(self) -> None:
        """Keys are normalized segment-wise at registration (D2)."""
        _register(
            "v_467_camel",
            aggregation={
                "dimensions": "dimensions",
                "native_dimension_mapping": {"dimensions.item.model.category": "model_category"},
            },
        )

        rendered = _sql(
            {"dimensions": {"item": {"model": {"category": {"eq": "laser"}}}}}, "v_467_camel"
        )

        assert '"model_category" = ' in rendered

    def test_or_and_not_groups_are_rewritten(self) -> None:
        _register()

        rendered = _sql(
            {
                "OR": [
                    {"dimensions": {"item": {"model": {"category": {"eq": "laser"}}}}},
                    {"dimensions": {"item": {"model": {"category": {"eq": "inkjet"}}}}},
                ]
            }
        )

        assert rendered.count('"model_category" = ') == 2
        assert "data" not in rendered


class TestTopLevelColumnMapping:
    """``column_mapping=`` is the peer of ``fk_relationships`` (D1)."""

    def test_top_level_mapping_applies_without_aggregation(self) -> None:
        register_type_for_view(
            "v_467_peer",
            _Stats,
            table_columns=COLUMNS,
            has_jsonb_data=True,
            jsonb_column="data",
            column_mapping=MAPPING,
        )

        rendered = _sql(
            {"dimensions": {"item": {"model": {"category": {"eq": "laser"}}}}}, "v_467_peer"
        )

        assert '"model_category" = ' in rendered

    def test_top_level_mapping_may_name_any_path(self) -> None:
        """The dimensions-prefix warning is aggregation-specific; a peer has no prefix."""
        register_type_for_view(
            "v_467_any_path",
            _Stats,
            table_columns=COLUMNS,
            has_jsonb_data=True,
            jsonb_column="data",
            column_mapping={"device.model.category": "model_category"},
        )

        rendered = _sql({"device": {"model": {"category": {"eq": "laser"}}}}, "v_467_any_path")

        assert '"model_category" = ' in rendered

    def test_top_level_mapping_key_casing_is_normalized(self) -> None:
        register_type_for_view(
            "v_467_peer_camel",
            _Stats,
            table_columns=COLUMNS,
            has_jsonb_data=True,
            jsonb_column="data",
            column_mapping={"dimensions.itemDetail.modelCategory": "model_category"},
        )

        rendered = _sql(
            {"dimensions": {"itemDetail": {"modelCategory": {"eq": "laser"}}}},
            "v_467_peer_camel",
        )

        assert '"model_category" = ' in rendered

    def test_unknown_column_raises_at_registration(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            register_type_for_view(
                "v_467_bad",
                _Stats,
                table_columns={"id", "data"},
                column_mapping={"dimensions.item.model.category": "nope"},
            )

        message = str(exc_info.value)
        assert "v_467_bad" in message
        assert "column_mapping" in message
        assert "nope" in message
        assert "validate_fk_strict=False" in message

    def test_no_unreachable_key_warning_for_top_level_mapping(self, caplog) -> None:
        """A peer of ``fk_relationships`` is not rooted at a dimensions prefix."""
        with caplog.at_level(logging.WARNING, logger="fraiseql.db"):
            register_type_for_view(
                "v_467_no_warn",
                _Stats,
                table_columns=COLUMNS,
                column_mapping={"device.model.category": "model_category"},
            )

        assert [r for r in caplog.records if "Unreachable" in r.message] == []

    def test_top_level_mapping_wins_over_aggregation_mapping(self) -> None:
        register_type_for_view(
            "v_467_both",
            _Stats,
            table_columns=COLUMNS | {"other_category"},
            has_jsonb_data=True,
            jsonb_column="data",
            column_mapping={"dimensions.item.model.category": "other_category"},
            aggregation={
                "dimensions": "dimensions",
                "native_dimension_mapping": {"dimensions.item.model.category": "model_category"},
            },
        )

        rendered = _sql(
            {"dimensions": {"item": {"model": {"category": {"eq": "laser"}}}}},
            "v_467_both",
            COLUMNS | {"other_category"},
        )

        assert '"other_category" = ' in rendered
        assert "model_category" not in rendered

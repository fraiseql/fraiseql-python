"""Registration-time validation of aggregation metadata (issue #467, part 2).

``fk_relationships`` declared against a column that does not exist is a
registration-time ``ValueError``.  ``native_dimension_mapping`` declared against
a missing column used to be silence — the mapping simply never fired, and the
query fell back to JSONB extraction with no diagnostic.  Same class of
declaration, so the same treatment: raise under ``validate_fk_strict=True``
(the default), warn under ``validate_fk_strict=False``.
"""

import logging

import pytest

from fraiseql.db import _table_metadata, _type_registry, register_type_for_view


@pytest.fixture(autouse=True)
def _clean_registry():
    """Keep the module-level registries clean between tests."""
    yield
    for view in [v for v in _table_metadata if v.startswith("v_agg_validation")]:
        del _table_metadata[view]
    for view in [v for v in _type_registry if v.startswith("v_agg_validation")]:
        del _type_registry[view]


class _Analytics:
    """Stand-in for a @fraise_type decorated class."""


class TestNativeDimensionMappingValidation:
    """A mapping value must name a real column."""

    def test_unknown_mapping_column_raises_in_strict_mode(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            register_type_for_view(
                "v_agg_validation_strict",
                _Analytics,
                table_columns={"id", "data"},
                aggregation={"native_dimension_mapping": {"dimensions.item.id": "nope"}},
            )

        message = str(exc_info.value)
        assert "v_agg_validation_strict" in message
        assert "dimensions.item.id" in message
        assert "nope" in message
        assert "native_dimension_mapping" in message
        assert "validate_fk_strict=False" in message

    def test_unknown_mapping_column_warns_in_lenient_mode(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="fraiseql.db"):
            register_type_for_view(
                "v_agg_validation_lenient",
                _Analytics,
                table_columns={"id", "data"},
                aggregation={"native_dimension_mapping": {"dimensions.item.id": "nope"}},
                validate_fk_strict=False,
            )

        assert "v_agg_validation_lenient" in _table_metadata
        assert any("nope" in record.message for record in caplog.records)

    def test_valid_mapping_column_is_accepted(self) -> None:
        register_type_for_view(
            "v_agg_validation_ok",
            _Analytics,
            table_columns={"id", "data", "item_id"},
            aggregation={"native_dimension_mapping": {"dimensions.item.id": "item_id"}},
        )

        assert _table_metadata["v_agg_validation_ok"]["aggregation"][
            "native_dimension_mapping"
        ] == {"dimensions.item.id": "item_id"}


class TestNativeMeasuresValidation:
    """``native_measures`` values are columns too — same guard."""

    def test_unknown_measure_column_raises(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            register_type_for_view(
                "v_agg_validation_measure",
                _Analytics,
                table_columns={"id", "data"},
                aggregation={"native_measures": {"measures.volume": "nope"}},
            )

        message = str(exc_info.value)
        assert "native_measures" in message
        assert "measures.volume" in message
        assert "nope" in message

    def test_known_measure_column_is_accepted(self) -> None:
        register_type_for_view(
            "v_agg_validation_measure_ok",
            _Analytics,
            table_columns={"id", "data", "volume"},
            aggregation={"native_measures": {"measures.volume": "volume"}},
        )


class TestNativeDimensionsValidation:
    """``native_dimensions`` entries name columns directly — same guard."""

    def test_unknown_native_dimension_raises(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            register_type_for_view(
                "v_agg_validation_dims",
                _Analytics,
                table_columns={"id", "data"},
                aggregation={"native_dimensions": ["period_date"]},
            )

        message = str(exc_info.value)
        assert "native_dimensions" in message
        assert "period_date" in message

    def test_known_native_dimension_is_accepted(self) -> None:
        register_type_for_view(
            "v_agg_validation_dims_ok",
            _Analytics,
            table_columns={"id", "data", "period_date"},
            aggregation={"native_dimensions": ["period_date"]},
        )


class TestMissingTableColumns:
    """No columns registered means nothing to validate against — warn, never raise."""

    def test_no_table_columns_warns_and_does_not_raise(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="fraiseql.db"):
            register_type_for_view(
                "v_agg_validation_no_columns",
                _Analytics,
                aggregation={"native_dimension_mapping": {"dimensions.item.id": "item_id"}},
            )

        assert "v_agg_validation_no_columns" in _table_metadata
        assert any(
            "No table_columns registered for v_agg_validation_no_columns" in record.message
            for record in caplog.records
        )

    def test_empty_table_columns_warns_and_does_not_raise(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="fraiseql.db"):
            register_type_for_view(
                "v_agg_validation_empty_columns",
                _Analytics,
                table_columns=set(),
                aggregation={"native_dimension_mapping": {"dimensions.item.id": "item_id"}},
            )

        assert any(
            "No table_columns registered for v_agg_validation_empty_columns" in record.message
            for record in caplog.records
        )

    def test_no_native_declarations_does_not_warn(self, caplog) -> None:
        """Aggregation without any column-naming key has nothing to validate."""
        with caplog.at_level(logging.WARNING, logger="fraiseql.db"):
            register_type_for_view(
                "v_agg_validation_no_natives",
                _Analytics,
                aggregation={"measures": {"measures.cost": "SUM"}, "dimensions": "dimensions"},
            )

        assert not [r for r in caplog.records if "No table_columns registered" in r.message]


class TestResolutionTimeGuard:
    """Second guard, mirroring ``where_normalization.py:409-419``.

    Registration validation can be bypassed (``validate_fk_strict=False``, or a
    view registered before its columns were known), so the resolver re-checks:
    strict views raise, lenient views warn once and fall back to JSONB.
    """

    def _register_dead_mapping(self, view_name: str, *, strict: bool) -> None:
        """Register a mapping naming a missing column, bypassing the registration guard."""
        register_type_for_view(
            view_name,
            _Analytics,
            table_columns={"id", "data"},
            has_jsonb_data=True,
            jsonb_column="data",
            aggregation={"native_dimension_mapping": {"dimensions.item.model.category": "nope"}},
            validate_fk_strict=False,
        )
        _table_metadata[view_name]["validate_fk_strict"] = strict

    @pytest.mark.xfail(
        reason="Resolution-time guard lands with Phase 02 Cycle 2 (the column-mapping pass)",
        strict=True,
    )
    def test_strict_view_raises_at_resolution(self) -> None:
        from unittest.mock import MagicMock

        from fraiseql.db import FraiseQLRepository

        self._register_dead_mapping("v_agg_validation_resolve_strict", strict=True)
        repo = FraiseQLRepository(MagicMock())

        with pytest.raises(RuntimeError) as exc_info:
            repo._normalize_where(
                {"dimensions": {"item": {"model": {"category": {"eq": "x"}}}}},
                "v_agg_validation_resolve_strict",
                {"id", "data"},
            )

        assert "should have been caught during registration" in str(exc_info.value)

    @pytest.mark.xfail(
        reason="Resolution-time guard lands with Phase 02 Cycle 2 (the column-mapping pass)",
        strict=True,
    )
    def test_lenient_view_warns_and_falls_back_to_jsonb(self, caplog) -> None:
        from unittest.mock import MagicMock

        from fraiseql.db import FraiseQLRepository

        self._register_dead_mapping("v_agg_validation_resolve_lenient", strict=False)
        repo = FraiseQLRepository(MagicMock())

        with caplog.at_level(logging.WARNING, logger="fraiseql.where_normalization"):
            clause = repo._normalize_where(
                {"dimensions": {"item": {"model": {"category": {"eq": "x"}}}}},
                "v_agg_validation_resolve_lenient",
                {"id", "data"},
            )

        warnings = [r for r in caplog.records if "nope" in r.message]
        assert len(warnings) == 1
        assert "JSONB fallback" in warnings[0].message

        condition = clause.conditions[0]
        assert condition.lookup_strategy == "jsonb_path"
        assert condition.target_column == "data"


class TestUnreachableMappingKey:
    """A key that cannot match any dimension path is dead weight — say so."""

    def test_key_outside_dimensions_prefix_warns(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="fraiseql.db"):
            register_type_for_view(
                "v_agg_validation_unreachable",
                _Analytics,
                table_columns={"id", "data", "model_category"},
                aggregation={
                    "dimensions": "dimensions",
                    "native_dimension_mapping": {"item.model.category": "model_category"},
                },
            )

        warnings = [r for r in caplog.records if "item.model.category" in r.message]
        assert len(warnings) == 1
        assert "dimensions" in warnings[0].message

    def test_custom_dimensions_prefix_is_respected(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="fraiseql.db"):
            register_type_for_view(
                "v_agg_validation_custom_prefix",
                _Analytics,
                table_columns={"id", "data", "model_category"},
                aggregation={
                    "dimensions": "dims",
                    "native_dimension_mapping": {"dims.item.model.category": "model_category"},
                },
            )

        assert not [r for r in caplog.records if "dims.item.model.category" in r.message]

    def test_reachable_key_does_not_warn(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="fraiseql.db"):
            register_type_for_view(
                "v_agg_validation_reachable",
                _Analytics,
                table_columns={"id", "data", "model_category"},
                aggregation={
                    "native_dimension_mapping": {"dimensions.item.model.category": "model_category"}
                },
            )

        assert not caplog.records

"""Issue #477: ``measures`` and ``native_measures`` keys have #467's casing trap.

#467 normalised ``native_dimension_mapping`` keys segment-wise at registration,
because field paths are built with ``transform_path=to_snake_case`` and a key in
GraphQL spelling could never match one. ``aggregation["measures"]`` and
``aggregation["native_measures"]`` are matched against the same snake_case
dot-paths and were deliberately left out of that change.

The two have to move together. A camelCase ``measures`` key fails to derive the
aggregation at all in ``_derive_auto_aggregation``, so normalising
``native_measures`` alone would produce a mapping that is correct and still
dead — with the obvious explanation eliminated.
"""

import pytest

from fraiseql.db import (
    _derive_auto_aggregation,
    _table_metadata,
    _type_registry,
    register_type_for_view,
)

pytestmark = pytest.mark.unit

CAMEL = "measures.totalCost"
SNAKE = "measures.total_cost"


@pytest.fixture(autouse=True)
def _clean_registry():
    """Keep the module-level registries clean between tests."""
    yield
    for registry in (_table_metadata, _type_registry):
        for view in [v for v in registry if v.startswith("v_measure_casing")]:
            del registry[view]


def _register(view_name: str, key: str) -> dict:
    register_type_for_view(
        view_name,
        type("Stats", (), {}),
        table_columns={"id", "data", "period_date", "total_cost"},
        aggregation={
            "dimensions": "dimensions",
            "measures": {key: "SUM"},
            "native_measures": {key: "total_cost"},
            "native_dimensions": ["period_date"],
        },
    )
    return _table_metadata[view_name]["aggregation"]


class TestMeasureKeyCasing:
    """Both measure dicts accept either spelling and store one."""

    def test_camel_case_measures_key_is_normalized_at_registration(self) -> None:
        agg = _register("v_measure_casing_measures", CAMEL)

        assert agg["measures"] == {SNAKE: "SUM"}

    def test_camel_case_native_measures_key_is_normalized_at_registration(self) -> None:
        agg = _register("v_measure_casing_native", CAMEL)

        assert agg["native_measures"] == {SNAKE: "total_cost"}

    def test_both_spellings_register_identically(self) -> None:
        camel = _register("v_measure_casing_camel_eq", CAMEL)
        snake = _register("v_measure_casing_snake_eq", SNAKE)

        assert camel["measures"] == snake["measures"]
        assert camel["native_measures"] == snake["native_measures"]

    def test_registration_does_not_mutate_the_caller_dict(self) -> None:
        measures = {CAMEL: "SUM"}
        native_measures = {CAMEL: "total_cost"}
        aggregation = {
            "dimensions": "dimensions",
            "measures": measures,
            "native_measures": native_measures,
            "native_dimensions": ["period_date"],
        }

        register_type_for_view(
            "v_measure_casing_no_mutation",
            type("Stats", (), {}),
            table_columns={"id", "data", "period_date", "total_cost"},
            aggregation=aggregation,
        )

        assert measures == {CAMEL: "SUM"}
        assert native_measures == {CAMEL: "total_cost"}
        assert aggregation["measures"] is measures
        assert aggregation["native_measures"] is native_measures


class TestMeasureKeyCasingEndToEnd:
    """The two dicts are useless apart: the measure has to derive *and* map."""

    def test_camel_case_measure_derives_and_its_native_counterpart_resolves(self) -> None:
        """One test, two reasons to fail today (#477)."""
        agg = _register("v_measure_casing_e2e", CAMEL)
        field_paths = [["dimensions", "date"], ["measures", "total_cost"]]

        derived = _derive_auto_aggregation(field_paths, agg)

        assert derived is not None
        _group_by, aggregations, _native_dims, _native_dim_mapping = derived
        # Reason one: a camelCase measures key derives no aggregation at all.
        assert aggregations == {SNAKE: f"SUM({SNAKE})"}
        # Reason two: with no aggregation derived there is nothing for the
        # native_measures entry to attach to, whatever spelling it carries.
        assert agg["native_measures"][SNAKE] == "total_cost"


class TestNativeMeasureColumnValidation:
    """The value half, already covered for native_dimension_mapping (#467)."""

    def test_unknown_native_measure_column_raises_in_strict_mode(self) -> None:
        with pytest.raises(ValueError, match="native_measures"):
            register_type_for_view(
                "v_measure_casing_bad_column",
                type("Stats", (), {}),
                table_columns={"id", "data", "period_date"},
                aggregation={
                    "dimensions": "dimensions",
                    "measures": {CAMEL: "SUM"},
                    "native_measures": {CAMEL: "no_such_column"},
                },
            )

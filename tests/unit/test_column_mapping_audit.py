"""Phase 08 audit: the properties the column-mapping work has to keep.

Three questions a reviewer of #467 / #468 would ask, answered by assertions rather
than by reading the diff:

* can a GraphQL document steer the rewrite?
* does the resolved column reach SQL as an identifier, or as text?
* is the ``fk_column`` / ``sql_column`` choice deliberate, or an accident that a
  passing integration test happens to cover?
"""

from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from psycopg.sql import Identifier

from fraiseql.db import (
    FraiseQLRepository,
    _table_metadata,
    _type_registry,
    register_type_for_view,
)
from fraiseql.sql.native_columns import resolve_native_column
from fraiseql.where_normalization import _mapped_lookup_strategy

VIEW = "v_audit_mapping"
COLUMNS = {"id", "data", "model_category", "owner_id", "status"}
MAPPING = {
    "dimensions.item.model.category": "model_category",
    "dimensions.item.owner": "owner_id",
}


class _Stats:
    """Stand-in for a registered analytics type."""


@pytest.fixture(autouse=True)
def _registered():
    register_type_for_view(
        VIEW,
        _Stats,
        table_columns=COLUMNS,
        has_jsonb_data=True,
        jsonb_column="data",
        column_mapping=MAPPING,
    )
    yield
    _table_metadata.pop(VIEW, None)
    _type_registry.pop(VIEW, None)


def _normalize(where: dict):
    return FraiseQLRepository(MagicMock())._normalize_where(where, VIEW, COLUMNS)


class TestTheMappingIsNotUserInput:
    """The rewrite reads registration metadata only. A query cannot add to it."""

    def test_a_where_key_shaped_like_a_mapping_entry_does_not_become_one(self) -> None:
        """`status` is a real column but is not declared in the mapping.

        It still resolves to a column — by the existing column rules, not by the
        mapping — which is the point: the mapping adds nothing a document asked for.
        """
        clause = _normalize({"dimensions": {"item": {"model": {"name": {"eq": "X1"}}}}})

        rendered = clause.to_sql()[0].as_string(None)
        assert "model_category" not in rendered
        assert "->" in rendered, "an undeclared deep path must stay in JSONB"

    def test_an_undeclared_path_cannot_reach_an_arbitrary_column(self) -> None:
        """Naming a real column inside a JSONB path does not redirect the lookup."""
        clause = _normalize({"dimensions": {"owner_id": {"eq": str(uuid4())}}})

        rendered = clause.to_sql()[0].as_string(None)
        assert rendered.startswith('"data"'), rendered

    def test_the_mapping_dict_is_never_mutated_by_a_query(self) -> None:
        before = dict(_table_metadata[VIEW]["column_mapping"])

        _normalize({"dimensions": {"item": {"model": {"category": {"eq": "a"}}}}})
        _normalize({"whatever": {"eq": "b"}})

        assert _table_metadata[VIEW]["column_mapping"] == before


class TestColumnsReachSqlAsIdentifiers:
    def test_a_mapped_condition_renders_the_column_quoted(self) -> None:
        clause = _normalize({"dimensions": {"item": {"model": {"category": {"eq": "a"}}}}})
        rendered = clause.to_sql()[0].as_string(None)

        assert rendered.startswith('"model_category"'), rendered

    def test_a_column_name_that_needs_quoting_is_quoted_not_interpolated(self) -> None:
        """The proof that this is `Identifier`, not string formatting.

        A column name carrying a double quote round-trips through `Identifier`'s
        escaping. Interpolated text would emit it raw and break the statement —
        or worse.
        """
        hostile = 'weird"; DROP TABLE x --'
        register_type_for_view(
            "v_audit_quoting",
            _Stats,
            table_columns={"id", "data", hostile},
            has_jsonb_data=True,
            jsonb_column="data",
            column_mapping={"dimensions.x": hostile},
        )
        try:
            clause = FraiseQLRepository(MagicMock())._normalize_where(
                {"dimensions": {"x": {"eq": "v"}}}, "v_audit_quoting", {"id", "data", hostile}
            )
            rendered = clause.to_sql()[0].as_string(None)
            assert rendered.startswith('"weird""; DROP TABLE x --"'), rendered
            assert Identifier(hostile).as_string(None) in rendered
        finally:
            _table_metadata.pop("v_audit_quoting", None)
            _type_registry.pop("v_audit_quoting", None)


class TestLookupStrategyChoice:
    """Phase 02's `fk_column` vs `sql_column` rule, asserted directly.

    `fk_column` is what the ltree `*_of_id` operators and the UUID coercion path
    key on, so downgrading a foreign key to `sql_column` breaks the hierarchy
    operators silently.
    """

    @pytest.mark.parametrize(
        ("column", "value", "expected"),
        [
            ("owner_id", "not-a-uuid", "fk_column"),
            ("model_category", uuid4(), "fk_column"),
            ("model_category", [uuid4(), uuid4()], "fk_column"),
            ("model_category", "printer", "sql_column"),
            ("model_category", 42, "sql_column"),
            ("model_category", [], "sql_column"),
            ("model_category", ["a", "b"], "sql_column"),
            ("model_category", [uuid4(), "a"], "sql_column"),
        ],
    )
    def test_strategy(self, column: str, value: object, expected: str) -> None:
        assert _mapped_lookup_strategy(column, value) == expected

    def test_a_mapped_uuid_path_keeps_fk_column_end_to_end(self) -> None:
        clause = _normalize({"dimensions": {"item": {"owner": {"eq": UUID(int=1)}}}})

        assert clause.conditions[0].lookup_strategy == "fk_column"
        assert clause.conditions[0].target_column == "owner_id"

    def test_a_mapped_text_path_uses_sql_column(self) -> None:
        clause = _normalize({"dimensions": {"item": {"model": {"category": {"eq": "a"}}}}})

        assert clause.conditions[0].lookup_strategy == "sql_column"
        assert clause.conditions[0].target_column == "model_category"


class TestOneResolverForEveryClause:
    """GROUP BY, WHERE and ORDER BY have to agree on what a path resolves to."""

    def test_a_field_that_is_itself_a_column_wins_over_a_mapped_path(self) -> None:
        assert (
            resolve_native_column(
                "date", native_columns={"date"}, column_mapping={"date": "other_column"}
            )
            == "date"
        )

    def test_a_mapped_path_wins_over_a_measure_of_the_same_name(self) -> None:
        assert (
            resolve_native_column(
                "measures.cost",
                column_mapping={"measures.cost": "mapped_cost"},
                native_measures={"measures.cost": "measure_cost"},
            )
            == "mapped_cost"
        )

    def test_an_undeclared_path_resolves_to_nothing(self) -> None:
        assert resolve_native_column("dimensions.nope", column_mapping=MAPPING) is None

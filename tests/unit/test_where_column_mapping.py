"""The column-mapping rewrite pass (issue #467, part 1).

``fk_relationships`` and the ``<parent>_id`` convention already resolve a nested
filter onto a flat column.  A declared column mapping is the same idea for paths
those two cannot reach — a leaf not named ``id``, or a column not named
``<parent>_id`` — and until now it was honoured in GROUP BY and ignored in WHERE.

This module tests the pass in isolation: given a normalized ``WhereClause`` and a
mapping of dotted field paths to flat columns, every condition on a mapped path —
at any depth, inside ``OR``/``AND``/``NOT`` groups too — is re-resolved onto its
column, and everything else is left exactly as it was.
"""

import logging
from uuid import UUID

import pytest

from fraiseql.where_clause import FieldCondition, WhereClause
from fraiseql.where_normalization import _apply_column_mapping

MAPPING = {"dimensions.item.model.category": "model_category"}
COLUMNS = {"id", "data", "model_category", "item_id"}


def _jsonb(*path: str, operator: str = "eq", value: object = "x") -> FieldCondition:
    """A condition the normalizer would have produced for a deep JSONB path."""
    return FieldCondition(
        field_path=list(path),
        operator=operator,
        value=value,
        lookup_strategy="jsonb_path",
        target_column="data",
        jsonb_path=list(path),
    )


class TestFlatConditions:
    """A mapped path at the top level of the clause."""

    def test_mapped_path_becomes_a_column(self) -> None:
        clause = WhereClause(conditions=[_jsonb("dimensions", "item", "model", "category")])

        result = _apply_column_mapping(clause, MAPPING, COLUMNS)

        condition = result.conditions[0]
        assert condition.lookup_strategy == "sql_column"
        assert condition.target_column == "model_category"
        assert condition.jsonb_path is None
        assert condition.field_path == ["dimensions", "item", "model", "category"]

    def test_unmapped_path_is_untouched(self) -> None:
        clause = WhereClause(conditions=[_jsonb("dimensions", "item", "model", "name")])

        result = _apply_column_mapping(clause, MAPPING, COLUMNS)

        condition = result.conditions[0]
        assert condition.lookup_strategy == "jsonb_path"
        assert condition.target_column == "data"
        assert condition.jsonb_path == ["dimensions", "item", "model", "name"]

    def test_partial_path_does_not_match(self) -> None:
        """Only the full dotted path counts — a suffix must not match a mapping key."""
        clause = WhereClause(conditions=[_jsonb("item", "model", "category")])

        result = _apply_column_mapping(clause, MAPPING, COLUMNS)

        assert result.conditions[0].lookup_strategy == "jsonb_path"

    def test_empty_mapping_is_a_no_op(self) -> None:
        clause = WhereClause(conditions=[_jsonb("dimensions", "item", "model", "category")])

        result = _apply_column_mapping(clause, {}, COLUMNS)

        assert result is clause


class TestNestedClauses:
    """Rewriting only ``.conditions`` would leave every OR/NOT group on JSONB."""

    def test_conditions_inside_an_or_group_are_rewritten(self) -> None:
        clause = WhereClause(
            nested_clauses=[
                WhereClause(
                    conditions=[
                        _jsonb("dimensions", "item", "model", "category", value="a"),
                        _jsonb("dimensions", "item", "model", "category", value="b"),
                    ],
                    logical_op="OR",
                )
            ]
        )

        result = _apply_column_mapping(clause, MAPPING, COLUMNS)

        rewritten = result.nested_clauses[0].conditions
        assert [c.target_column for c in rewritten] == ["model_category", "model_category"]
        assert result.nested_clauses[0].logical_op == "OR"

    def test_deeply_nested_groups_are_rewritten(self) -> None:
        clause = WhereClause(
            nested_clauses=[
                WhereClause(
                    nested_clauses=[
                        WhereClause(
                            conditions=[_jsonb("dimensions", "item", "model", "category")],
                        )
                    ],
                    logical_op="OR",
                )
            ]
        )

        result = _apply_column_mapping(clause, MAPPING, COLUMNS)

        condition = result.nested_clauses[0].nested_clauses[0].conditions[0]
        assert condition.target_column == "model_category"

    def test_conditions_inside_a_not_clause_are_rewritten(self) -> None:
        clause = WhereClause(
            conditions=[_jsonb("dimensions", "item", "model", "name")],
            not_clause=WhereClause(conditions=[_jsonb("dimensions", "item", "model", "category")]),
        )

        result = _apply_column_mapping(clause, MAPPING, COLUMNS)

        assert result.not_clause.conditions[0].target_column == "model_category"
        assert result.conditions[0].target_column == "data"


class TestStrategySelection:
    """``fk_column`` is what the ltree ``*_of_id`` operators key on — keep it."""

    def test_id_suffixed_target_keeps_fk_column(self) -> None:
        clause = WhereClause(conditions=[_jsonb("dimensions", "item", "id")])

        result = _apply_column_mapping(clause, {"dimensions.item.id": "item_id"}, COLUMNS)

        condition = result.conditions[0]
        assert condition.lookup_strategy == "fk_column"
        assert condition.target_column == "item_id"

    def test_uuid_value_keeps_fk_column(self) -> None:
        value = UUID("11111111-1111-1111-1111-111111111111")
        clause = WhereClause(conditions=[_jsonb("dimensions", "item", "ref", value=value)])

        result = _apply_column_mapping(clause, {"dimensions.item.ref": "model_category"}, COLUMNS)

        assert result.conditions[0].lookup_strategy == "fk_column"

    def test_uuid_list_value_keeps_fk_column(self) -> None:
        values = [UUID("11111111-1111-1111-1111-111111111111")]
        clause = WhereClause(
            conditions=[_jsonb("dimensions", "item", "ref", operator="in", value=values)]
        )

        result = _apply_column_mapping(clause, {"dimensions.item.ref": "model_category"}, COLUMNS)

        assert result.conditions[0].lookup_strategy == "fk_column"

    def test_plain_target_uses_sql_column(self) -> None:
        clause = WhereClause(conditions=[_jsonb("dimensions", "item", "model", "category")])

        result = _apply_column_mapping(clause, MAPPING, COLUMNS)

        assert result.conditions[0].lookup_strategy == "sql_column"


class TestPrecedence:
    """An explicit declaration beats a convention, as ``fk_relationships`` does."""

    def test_mapping_overrides_the_parent_id_convention(self) -> None:
        convention = FieldCondition(
            field_path=["dimensions", "item", "id"],
            operator="eq",
            value="x",
            lookup_strategy="fk_column",
            target_column="item_id",
        )
        clause = WhereClause(conditions=[convention])

        result = _apply_column_mapping(
            clause,
            {"dimensions.item.id": "declared_item_id"},
            COLUMNS | {"declared_item_id"},
        )

        assert result.conditions[0].target_column == "declared_item_id"
        assert result.conditions[0].lookup_strategy == "fk_column"


class TestPurity:
    """The same normalized clause is re-read by the partial-period bound extractors."""

    def test_input_clause_is_not_mutated(self) -> None:
        original = _jsonb("dimensions", "item", "model", "category")
        clause = WhereClause(
            conditions=[original],
            nested_clauses=[
                WhereClause(conditions=[_jsonb("dimensions", "item", "model", "category")])
            ],
        )

        result = _apply_column_mapping(clause, MAPPING, COLUMNS)

        assert result is not clause
        assert original.lookup_strategy == "jsonb_path"
        assert original.target_column == "data"
        assert original.jsonb_path == ["dimensions", "item", "model", "category"]
        assert clause.nested_clauses[0].conditions[0].target_column == "data"


class TestResolutionGuard:
    """Registration validation is bypassable, so the resolver re-checks the target."""

    def test_missing_column_raises_in_strict_mode(self) -> None:
        clause = WhereClause(conditions=[_jsonb("dimensions", "item", "model", "category")])

        with pytest.raises(RuntimeError) as exc_info:
            _apply_column_mapping(
                clause, {"dimensions.item.model.category": "nope"}, COLUMNS, strict=True
            )

        message = str(exc_info.value)
        assert "nope" in message
        assert "should have been caught during registration" in message

    def test_missing_column_warns_and_falls_back_in_lenient_mode(self, caplog) -> None:
        clause = WhereClause(conditions=[_jsonb("dimensions", "item", "model", "category")])

        with caplog.at_level(logging.WARNING, logger="fraiseql.where_normalization"):
            result = _apply_column_mapping(
                clause, {"dimensions.item.model.category": "nope"}, COLUMNS, strict=False
            )

        warnings = [r for r in caplog.records if "nope" in r.message]
        assert len(warnings) == 1
        assert "JSONB fallback" in warnings[0].message

        condition = result.conditions[0]
        assert condition.lookup_strategy == "jsonb_path"
        assert condition.target_column == "data"

    def test_unknown_columns_skip_validation(self) -> None:
        """With nothing to validate against, trust the declaration rather than raise."""
        clause = WhereClause(conditions=[_jsonb("dimensions", "item", "model", "category")])

        result = _apply_column_mapping(clause, MAPPING, None, strict=True)

        assert result.conditions[0].target_column == "model_category"

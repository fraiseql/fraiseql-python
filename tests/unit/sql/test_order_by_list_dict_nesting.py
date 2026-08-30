"""Issue #475: the list-of-dicts order_by form must recurse like the bare-dict one.

``order_by`` accepts several shapes, and two of them are dicts:

    {"measures": {"cost": "desc"}}      # bare dict   -> measures.cost DESC
    [{"measures": {"cost": "desc"}}]    # in a list   -> measures ASC

The bare-dict branch carried a prefix and recursed. The list branch had its own
shallower loop that fed the nested dict straight to ``_normalize_order_direction``,
which does not recognise a dict and returned the ASC default -- so the same input
sorted by the wrong field, in the wrong direction, depending only on whether the
caller wrapped it in a list. No error, no warning.

These tests pin that the two shapes agree, and that a value neither branch can
interpret is reported rather than silently defaulted.
"""

import pytest

from fraiseql.sql.graphql_order_by_generator import (
    OrderDirection,
    _convert_order_by_input_to_sql,
)


def _instructions(order_by):
    order_set = _convert_order_by_input_to_sql(order_by)
    return [] if order_set is None else list(order_set.instructions)


@pytest.mark.unit
class TestListOfDictsRecurses:
    def test_nested_dict_in_a_list_resolves_the_leaf(self) -> None:
        (instr,) = _instructions([{"measures": {"cost": "desc"}}])
        assert instr.field == "measures.cost"
        assert instr.direction == OrderDirection.DESC

    def test_list_and_bare_dict_agree(self) -> None:
        """The same nesting must not depend on being wrapped in a list."""
        nested = {"measures": {"totalCost": "desc"}}
        assert _instructions([nested]) == _instructions(nested)

    def test_deeply_nested_path(self) -> None:
        (instr,) = _instructions([{"dimensions": {"dateInfo": {"date": "asc"}}}])
        assert instr.field == "dimensions.date_info.date"
        assert instr.direction == OrderDirection.ASC

    def test_camel_case_segments_are_snake_cased_at_every_level(self) -> None:
        (instr,) = _instructions([{"orderDetails": {"unitPrice": "desc"}}])
        assert instr.field == "order_details.unit_price"

    def test_flat_list_dict_still_works(self) -> None:
        """The shape the branch was written for (#... v0.3.5) is unchanged."""
        (instr,) = _instructions([{"ipAddress": "asc"}])
        assert instr.field == "ip_address"
        assert instr.direction == OrderDirection.ASC

    def test_multiple_keys_and_items_keep_their_order(self) -> None:
        instrs = _instructions([{"status": "asc"}, {"measures": {"cost": "desc"}}])
        assert [(i.field, i.direction) for i in instrs] == [
            ("status", OrderDirection.ASC),
            ("measures.cost", OrderDirection.DESC),
        ]

    def test_enum_direction_survives_in_both_shapes(self) -> None:
        """The list branch accepted an OrderDirection; unifying must not lose that."""
        (instr,) = _instructions([{"name": OrderDirection.DESC}])
        assert instr.field == "name"
        assert instr.direction == OrderDirection.DESC

    def test_none_values_are_skipped(self) -> None:
        assert _instructions([{"name": None}]) == []


@pytest.mark.unit
class TestUninterpretableValuesWarn:
    """A silent ASC default here means "sorted by something else entirely"."""

    def test_unrecognised_value_warns_in_a_list(self) -> None:
        with pytest.warns(UserWarning, match="order_by"):
            _instructions([{"name": 42}])

    def test_unrecognised_value_warns_in_a_bare_dict(self) -> None:
        with pytest.warns(UserWarning, match="order_by"):
            _instructions({"name": 42})

    def test_unrecognised_value_is_not_silently_ascending(self) -> None:
        with pytest.warns(UserWarning):
            assert _instructions([{"name": 42}]) == []

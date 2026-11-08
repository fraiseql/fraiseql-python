"""A list ``order_by`` takes ``(field, direction)`` tuples and bare field names.

``db.find(..., order_by=[("created_at", "DESC")])`` is the obvious Python
spelling, and ``fraiseql init`` generated it, but the list branch only read
dicts and ``OrderBy``-like objects: a tuple or a string item was skipped, the
list resolved to no instructions, and the rows came back unordered without a
word. A direction it cannot read used to fall back to DESC (or ASC) silently.
"""

import pytest

from fraiseql.sql.graphql_order_by_generator import _convert_order_by_input_to_sql
from fraiseql.sql.order_by_generator import OrderDirection


def _pairs(order_by: object) -> list[tuple[str, OrderDirection]]:
    result = _convert_order_by_input_to_sql(order_by)
    assert result is not None
    return [(instr.field, instr.direction) for instr in result.instructions]


class TestTupleItems:
    def test_field_direction_tuple(self) -> None:
        assert _pairs([("created_at", "DESC")]) == [("created_at", OrderDirection.DESC)]

    def test_lowercase_direction_and_enum(self) -> None:
        assert _pairs([("age", "asc"), ("name", OrderDirection.DESC)]) == [
            ("age", OrderDirection.ASC),
            ("name", OrderDirection.DESC),
        ]

    def test_one_tuple_sorts_ascending(self) -> None:
        assert _pairs([("created_at",)]) == [("created_at", OrderDirection.ASC)]

    def test_camel_case_and_dotted_paths_like_the_dict_form(self) -> None:
        assert _pairs([("createdAt", "DESC"), ("profile.lastName", "ASC")]) == [
            ("created_at", OrderDirection.DESC),
            ("profile.last_name", OrderDirection.ASC),
        ]

    def test_mixed_with_dict_items(self) -> None:
        assert _pairs([("age", "DESC"), {"name": "ASC"}]) == [
            ("age", OrderDirection.DESC),
            ("name", OrderDirection.ASC),
        ]

    def test_bad_direction_raises(self) -> None:
        with pytest.raises(ValueError, match="'descending'"):
            _convert_order_by_input_to_sql([("created_at", "descending")])

    @pytest.mark.parametrize("item", [(), ("a", "ASC", "x"), (1, "ASC")])
    def test_malformed_tuple_raises(self, item: tuple) -> None:
        with pytest.raises(TypeError, match="order_by"):
            _convert_order_by_input_to_sql([item])


class TestStringItems:
    def test_bare_field_name_sorts_ascending(self) -> None:
        assert _pairs(["created_at", "name"]) == [
            ("created_at", OrderDirection.ASC),
            ("name", OrderDirection.ASC),
        ]


class TestUnreadableItems:
    @pytest.mark.parametrize("item", [42, object()])
    def test_unreadable_item_raises_instead_of_being_skipped(self, item: object) -> None:
        with pytest.raises(TypeError, match="order_by"):
            _convert_order_by_input_to_sql([item])

    def test_none_item_is_skipped_like_a_none_dict_value(self) -> None:
        assert _pairs([None, ("age", "DESC")]) == [("age", OrderDirection.DESC)]


class TestDirectionStrings:
    @pytest.mark.parametrize("direction", ["ascending", "up", "DESC NULLS LAST", ""])
    def test_unreadable_direction_in_a_dict_raises(self, direction: str) -> None:
        """Anything but asc/desc used to read as DESC."""
        with pytest.raises(ValueError, match="direction"):
            _convert_order_by_input_to_sql({"name": direction})

    def test_enum_like_with_upper_case_value(self) -> None:
        """An enum whose value is "ASC" read as DESC: only "asc" was compared."""
        from enum import Enum

        class Direction(Enum):
            ASC = "ASC"
            DESC = "DESC"

        assert _pairs({"name": Direction.ASC}) == [("name", OrderDirection.ASC)]
        assert _pairs({"name": Direction.DESC}) == [("name", OrderDirection.DESC)]

"""Issue #482: default_string_collation applies, to text fields only.

The setting is documented as applying to "all *text* fields in ORDER BY unless
overridden per-field", was validated against SQL injection, and had never
reached a query. #481 made an *explicit* per-field collation work on every path
and deliberately left the global default inert, because nothing in the order_by
pipeline tracked which fields were text and a blanket default would have given

* a numeric JSONB field a silently lexicographic sort -- 1, 10, 2 -- and
* a numeric flat column an outright "collations are not supported by type
  integer".

What was missing is field types. They now come from the view's registered type,
so the default lands on ``str`` fields and nothing else. Anything that cannot be
resolved to ``str`` -- an unregistered view, a container prefix, a field that is
not declared -- answers no and keeps the behaviour it has always had.
"""

from uuid import UUID

import pytest

from fraiseql.sql.graphql_order_by_generator import (
    OrderByItem,
    _convert_order_by_input_to_sql,
    create_graphql_order_by_input,
)
from fraiseql.sql.order_by_generator import OrderDirection
from fraiseql.types import fraise_type

pytestmark = pytest.mark.unit

COLLATION = "fr_FR.utf8"


class _Config:
    """Stand-in for the one FraiseQLConfig attribute that matters here."""

    def __init__(self, collation: str | None = COLLATION) -> None:
        self.default_string_collation = collation


@fraise_type
class _Profile:
    nickname: str
    age: int


@fraise_type
class _Doc:
    id: UUID
    name: str
    amount: int
    tags: list[str] | None
    profile: _Profile


def _render(order_by, config=None, source_type=None) -> str:
    order_set = _convert_order_by_input_to_sql(order_by, config=config, source_type=source_type)
    assert order_set is not None
    return order_set.to_sql().as_string(None)


class TestDictShape:
    """The shape that carries field names and nothing else."""

    def test_text_field_gets_the_default(self) -> None:
        sql = _render({"name": "ASC"}, _Config(), _Doc)

        assert sql == 'ORDER BY (t ->> \'name\') COLLATE "fr_FR.utf8" ASC'

    def test_numeric_field_is_left_alone(self) -> None:
        """The silent wrong answer #481 refused to ship: 1, 10, 2."""
        sql = _render({"amount": "ASC"}, _Config(), _Doc)

        assert sql == "ORDER BY t -> 'amount' ASC"

    def test_uuid_field_is_left_alone(self) -> None:
        sql = _render({"id": "ASC"}, _Config(), _Doc)

        assert sql == "ORDER BY t -> 'id' ASC"

    def test_list_of_text_is_not_a_text_field(self) -> None:
        """Collating a serialized JSON array is meaningless, not merely useless."""
        sql = _render({"tags": "ASC"}, _Config(), _Doc)

        assert sql == "ORDER BY t -> 'tags' ASC"

    def test_nested_text_field_gets_the_default(self) -> None:
        sql = _render({"profile": {"nickname": "ASC"}}, _Config(), _Doc)

        assert 'COLLATE "fr_FR.utf8"' in sql
        assert "profile" in sql

    def test_nested_numeric_field_is_left_alone(self) -> None:
        sql = _render({"profile": {"age": "ASC"}}, _Config(), _Doc)

        assert "COLLATE" not in sql

    def test_undeclared_field_is_left_alone(self) -> None:
        """An unknown field answers 'not text', which is the safe answer."""
        sql = _render({"whatever": "ASC"}, _Config(), _Doc)

        assert "COLLATE" not in sql

    def test_without_a_source_type_nothing_is_collated(self) -> None:
        """No type to consult is the pre-#482 behaviour, unchanged."""
        sql = _render({"name": "ASC"}, _Config(), None)

        assert "COLLATE" not in sql

    def test_without_a_config_nothing_is_collated(self) -> None:
        sql = _render({"name": "ASC"}, None, _Doc)

        assert "COLLATE" not in sql


class TestListOfOrderByItems:
    """The shape that can also carry an explicit per-field collation."""

    def test_explicit_collation_beats_the_default(self) -> None:
        item = OrderByItem(field="name", direction=OrderDirection.ASC, collation="en_US.utf8")

        sql = _render([item], _Config(), _Doc)

        assert 'COLLATE "en_US.utf8"' in sql
        assert "fr_FR" not in sql

    def test_explicit_none_beats_the_default(self) -> None:
        """Setting it to None asks for the database default, and must win."""
        item = OrderByItem(field="name", direction=OrderDirection.ASC, collation=None)

        sql = _render([item], _Config(), _Doc)

        assert "COLLATE" not in sql

    def test_numeric_field_is_left_alone(self) -> None:
        sql = _render([{"amount": "ASC"}], _Config(), _Doc)

        assert "COLLATE" not in sql

    def test_text_field_gets_the_default(self) -> None:
        sql = _render([{"name": "ASC"}], _Config(), _Doc)

        assert 'COLLATE "fr_FR.utf8"' in sql


class TestGqlFieldsShape:
    """The generated input names its own source type, so nothing is threaded in."""

    def test_text_field_gets_the_default_without_an_explicit_source_type(self) -> None:
        order_by_input = create_graphql_order_by_input(_Doc)

        sql = _render(order_by_input(name=OrderDirection.ASC), _Config())

        assert 'COLLATE "fr_FR.utf8"' in sql

    def test_numeric_field_is_left_alone(self) -> None:
        order_by_input = create_graphql_order_by_input(_Doc)

        sql = _render(order_by_input(amount=OrderDirection.ASC), _Config())

        assert "COLLATE" not in sql


class TestAllShapesAgree:
    """The same request written three ways must render the same collation."""

    @pytest.mark.parametrize(
        ("field", "collated"), [("name", True), ("amount", False)], ids=["text", "numeric"]
    )
    def test_shapes_agree(self, field: str, collated: bool) -> None:
        order_by_input = create_graphql_order_by_input(_Doc)

        rendered = {
            "dict": _render({field: "ASC"}, _Config(), _Doc),
            "list": _render([{field: "ASC"}], _Config(), _Doc),
            "gql_fields": _render(order_by_input(**{field: OrderDirection.ASC}), _Config()),
        }

        for shape, sql in rendered.items():
            assert ('COLLATE "fr_FR.utf8"' in sql) is collated, f"{shape}: {sql}"

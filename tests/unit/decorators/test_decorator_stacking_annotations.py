"""Stacked decorators keep the resolver's types, on Python 3.13 and 3.14.

Python 3.14 evaluates annotations lazily, and ``functools.wraps`` copies
``__annotate__`` instead of ``__annotations__``. A wrapper around a function whose
annotations were assigned (as ``@fraiseql.field`` and ``@fraiseql.connection`` do)
lost them, so the schema builder dropped the field or its return type.
"""

import functools
from typing import Any, get_type_hints

import pytest
from graphql import GraphQLObjectType, GraphQLResolveInfo, get_named_type

import fraiseql
from fraiseql.auth import requires_auth
from fraiseql.gql.schema_builder import SchemaRegistry, build_fraiseql_schema
from fraiseql.types.generic import Connection


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    SchemaRegistry.get_instance().clear()
    yield
    SchemaRegistry.get_instance().clear()


def _user_decorator(func: Any) -> Any:
    """A decorator from user code, written with plain ``functools.wraps``."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        return await func(*args, **kwargs)

    return wrapper


def _make_item() -> type:
    @fraiseql.type(sql_source="v_item")
    class Item:
        id: int
        name: str

        @requires_auth
        @fraiseql.field
        async def label(self, info: GraphQLResolveInfo) -> str:
            return self.name

    return Item


def test_requires_auth_over_field_keeps_the_return_type() -> None:
    item = _make_item()

    assert get_type_hints(item.label)["return"] is str

    @fraiseql.query
    async def items(info: GraphQLResolveInfo) -> list[item]:  # type: ignore[valid-type]
        return []

    schema = build_fraiseql_schema(query_types=[items])
    item_type = schema.get_type("Item")
    assert isinstance(item_type, GraphQLObjectType)
    assert "label" in item_type.fields
    assert str(item_type.fields["label"].type) == "String!"


@pytest.mark.parametrize("outer", [requires_auth, _user_decorator], ids=["fraiseql", "user"])
def test_query_over_wrapped_connection_keeps_the_connection_type(outer: Any) -> None:
    item = _make_item()

    @fraiseql.query
    @outer
    @fraiseql.connection(node_type=item)
    async def items_page(info: GraphQLResolveInfo, first: int | None = None) -> Connection[item]:  # type: ignore[valid-type]
        raise NotImplementedError

    hints = get_type_hints(items_page)
    assert hints["return"] == Connection[item]
    assert "first" in hints

    schema = build_fraiseql_schema(query_types=[items_page])
    field = schema.query_type.fields["itemsPage"]
    assert get_named_type(field.type).name == "ItemConnection"
    assert {"first", "after", "last", "before"} <= set(field.args)

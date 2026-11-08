"""Annotated fields whose name starts with ``_`` are private: not in the GraphQL schema.

The where and orderBy input generators already skipped them; the object, input and
interface types exposed them (``_email`` as ``Email``), readable without the field's
authorization check.
"""

import pytest
from graphql import graphql

import fraiseql
from fraiseql import fraise_field
from fraiseql.gql.builders import SchemaRegistry
from fraiseql.gql.schema_builder import build_fraiseql_schema
from fraiseql.security import authorize_field

pytestmark = pytest.mark.security


@pytest.fixture(autouse=True)
def _clean_registry():
    from fraiseql.core.graphql_type import _graphql_type_cache

    SchemaRegistry.get_instance().clear()
    _graphql_type_cache.clear()
    yield
    SchemaRegistry.get_instance().clear()
    _graphql_type_cache.clear()


@fraiseql.interface
class PrivateNode:
    id: int
    _secret: str | None = None


@fraiseql.type
class PrivateUser:
    """The docs sample: the protected value in a private field, exposed by a resolver."""

    id: int
    name: str
    _email: str | None = None

    @fraiseql.field
    @authorize_field(lambda info, user: info.context.get("admin", False))
    async def email(self, info) -> str | None:
        return self._email


@fraiseql.input
class PrivateInput:
    name: str
    _internal: str | None = None


@fraiseql.type
class ExplicitlyNamed:
    id: int
    _id: str = fraise_field(graphql_name="_id", default="x")


@fraiseql.query
async def private_user(info) -> PrivateUser:
    return PrivateUser(id=1, name="Ada", _email="ada@example.com")


@fraiseql.query
async def private_echo(info, input: PrivateInput) -> str:
    return input.name


@fraiseql.query
async def explicitly_named(info) -> ExplicitlyNamed:
    return ExplicitlyNamed(id=1)


@fraiseql.query
async def private_node(info) -> PrivateNode:
    return PrivateNode(id=1)


def _schema():
    return build_fraiseql_schema(
        query_types=[
            PrivateUser,
            ExplicitlyNamed,
            private_user,
            private_echo,
            explicitly_named,
            private_node,
        ]
    )


def test_private_field_is_not_in_the_object_type() -> None:
    fields = _schema().type_map["PrivateUser"].fields
    assert set(fields) == {"id", "name", "email"}


def test_private_field_is_not_in_the_input_type() -> None:
    assert set(_schema().type_map["PrivateInput"].fields) == {"name"}


def test_private_field_is_not_in_the_interface() -> None:
    assert set(_schema().type_map["PrivateNode"].fields) == {"id"}


def test_an_explicit_graphql_name_keeps_the_field() -> None:
    assert set(_schema().type_map["ExplicitlyNamed"].fields) == {"id", "_id"}


async def test_private_field_isnt_readable_around_the_check() -> None:
    schema = _schema()

    bypass = await graphql(schema, "{ privateUser { Email } }", context_value={})
    assert bypass.errors
    assert "Cannot query field 'Email'" in bypass.errors[0].message

    denied = await graphql(schema, "{ privateUser { email } }", context_value={})
    assert denied.data == {"privateUser": {"email": None}}
    assert denied.errors[0].extensions["code"] == "FIELD_AUTHORIZATION_ERROR"

    allowed = await graphql(schema, "{ privateUser { email } }", context_value={"admin": True})
    assert allowed.data == {"privateUser": {"email": "ada@example.com"}}


def test_private_field_is_still_a_constructor_argument() -> None:
    user = PrivateUser(id=1, name="Ada", _email="ada@example.com")
    assert user._email == "ada@example.com"

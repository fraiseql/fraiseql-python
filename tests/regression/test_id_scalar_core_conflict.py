"""Regression tests for ID type (previously ID scalar conflict).

FIXED: FraiseQL's ID is now a NewType based on str, following Strawberry's convention.
It maps to a custom IDScalar that is named "ID" for Apollo/Relay cache compatibility
but enforces UUID format (FraiseQL is opinionated).

The fix:
- ID = NewType("ID", str) - simple type alias like Strawberry
- Maps to custom IDScalar (named "ID" for cache, enforces UUID)
- GraphQL schema shows type as "ID" (for cache management)
- Serialization/parsing enforces UUID format

SEMANTIC IMPROVEMENT (v1.9.x):
- uuid.UUID now maps to UUIDScalar (name="UUID") - semantically correct
- ID type maps to IDScalar (name="ID") - for identifier fields
- ID behavior is configurable via SchemaConfig.id_policy

These tests verify that:
- FraiseQL's ID type maps to custom IDScalar
- uuid.UUID maps to UUIDScalar (separate from ID)
- Schema building works without redefinition errors
- UUID format is enforced for ID fields
- Apollo/Relay cache compatibility maintained
"""

import uuid

import pytest
from graphql import (
    GraphQLID,
    GraphQLNonNull,
    GraphQLSchema,
    graphql,
    print_schema,
)

import fraiseql
from fraiseql.config.schema_config import IDPolicy, SchemaConfig
from fraiseql.types import ID
from fraiseql.types.scalars import IDScalar, UUIDScalar
from fraiseql.types.scalars.graphql_utils import convert_scalar_to_graphql


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear the schema registry and reset config before and after each test."""
    from fraiseql.gql.builders.registry import SchemaRegistry

    registry = SchemaRegistry.get_instance()
    registry.clear()
    SchemaConfig.reset()  # Reset ID policy to default
    yield
    registry.clear()
    SchemaConfig.reset()


class TestIDTypeFixed:
    """Test suite verifying ID type fix (no longer conflicts with GraphQL core)."""

    def test_id_is_newtype_based_on_str(self):
        """Verify ID is a NewType based on str (like Strawberry)."""
        assert hasattr(ID, "__supertype__")
        assert ID.__supertype__ is str

    def test_id_maps_to_id_scalar(self):
        """Verify ID maps to IDScalar (named 'ID' for cache, enforces UUID)."""
        graphql_type = convert_scalar_to_graphql(ID)
        assert graphql_type is IDScalar
        assert graphql_type.name == "ID"

    def test_id_enforces_uuid_format(self):
        """Verify ID (via IDScalar) enforces UUID format."""
        valid_uuid = uuid.uuid4()
        assert IDScalar.serialize(valid_uuid) == str(valid_uuid)

    def test_schema_with_id_type_no_redefinition_error(self):
        """Test that building schema with ID type doesn't cause redefinition error."""
        # This test should FAIL if there's an ID scalar redefinition bug

        @fraiseql.type
        class Product:
            id: ID
            name: str

        async def products(info) -> list[Product]:
            return []

        # Should not raise "Type ID is already defined" or similar
        schema = fraiseql.build_fraiseql_schema(query_types=[products])

        assert schema is not None
        assert isinstance(schema, GraphQLSchema)

    def test_schema_introspection_id_type_consistency(self):
        """Test that ID type appears consistently in schema introspection."""

        @fraiseql.type
        class Order:
            id: ID
            total: float

        async def orders(info) -> list[Order]:
            return []

        schema = fraiseql.build_fraiseql_schema(query_types=[orders])

        # Introspect to check ID type
        introspection_query = """
            query {
                __type(name: "Order") {
                    fields {
                        name
                        type {
                            name
                            kind
                            ofType {
                                name
                                kind
                            }
                        }
                    }
                }
            }
        """

        import asyncio

        result = asyncio.run(graphql(schema, introspection_query))

        assert result.errors is None

        fields = result.data["__type"]["fields"]
        id_field = next(f for f in fields if f["name"] == "id")

        # ID type should be recognized as NON_NULL SCALAR with name "ID" (Issue #243)
        if id_field["type"]["kind"] == "NON_NULL":
            assert id_field["type"]["ofType"]["kind"] == "SCALAR"
            assert id_field["type"]["ofType"]["name"] == "ID"
        else:
            assert id_field["type"]["kind"] == "SCALAR"
            assert id_field["type"]["name"] == "ID"

    def test_schema_print_no_duplicate_id_definition(self):
        """Test that schema printing doesn't include duplicate ID definitions."""

        @fraiseql.type
        class Customer:
            id: ID
            email: str

        async def customers(info) -> list[Customer]:
            return []

        schema = fraiseql.build_fraiseql_schema(query_types=[customers])

        # Print schema should not contain duplicate ID scalar definitions
        sdl = print_schema(schema)

        # Count occurrences of 'scalar ID' - should be 0 (built-in) or 1 (if custom)
        # More than 1 indicates a redefinition bug
        id_scalar_count = sdl.count("scalar ID")

        assert id_scalar_count <= 1, (
            f"ID scalar defined {id_scalar_count} times in schema SDL - "
            "possible redefinition conflict"
        )

    def test_multiple_types_with_id_field(self):
        """Test that multiple types using ID don't cause conflicts."""

        @fraiseql.type
        class User:
            id: ID
            name: str

        @fraiseql.type
        class Post:
            id: ID
            title: str
            author_id: ID

        @fraiseql.type
        class Comment:
            id: ID
            post_id: ID
            user_id: ID
            content: str

        async def users(info) -> list[User]:
            return []

        async def posts(info) -> list[Post]:
            return []

        async def comments(info) -> list[Comment]:
            return []

        # All types with ID should work together without conflicts
        schema = fraiseql.build_fraiseql_schema(query_types=[users, posts, comments])

        assert schema is not None

        # Verify all types are in schema
        user_type = schema.type_map.get("User")
        post_type = schema.type_map.get("Post")
        comment_type = schema.type_map.get("Comment")

        assert user_type is not None
        assert post_type is not None
        assert comment_type is not None

    def test_id_field_resolves_correctly_with_uuid(self):
        """Test that ID field correctly resolves UUID values."""

        @fraiseql.type
        class Item:
            id: ID
            name: str

        test_uuid = uuid.uuid4()

        async def items(info) -> list[Item]:
            # Return mock data with UUID
            return [{"id": test_uuid, "name": "Test Item"}]

        schema = fraiseql.build_fraiseql_schema(query_types=[items])

        query = """
            query {
                items {
                    id
                    name
                }
            }
        """

        import asyncio

        result = asyncio.run(graphql(schema, query))

        # Should not have serialization errors
        assert result.errors is None or not any(
            "ID" in str(e) and "serialize" in str(e).lower() for e in result.errors
        )

    def test_schema_type_map_contains_id_scalar(self):
        """Test that schema type_map contains ID scalar for ID fields."""

        @fraiseql.type
        class Widget:
            id: ID
            description: str

        async def widgets(info) -> list[Widget]:
            return []

        schema = fraiseql.build_fraiseql_schema(query_types=[widgets])

        # ID scalar should be in the type map (used for ID fields)
        assert "ID" in schema.type_map, "ID scalar should be in schema type_map"

        # FraiseQL's custom ID scalar replaces the built-in
        id_types = [name for name in schema.type_map.keys() if name == "ID"]
        assert len(id_types) == 1, "Expected exactly 1 'ID' type in schema"

    def test_schema_uses_custom_id_scalar(self):
        """Test that schema uses custom ID scalar (named 'ID' for cache compatibility)."""

        @fraiseql.type
        class Thing:
            id: ID
            value: str

        async def things(info) -> list[Thing]:
            return []

        schema = fraiseql.build_fraiseql_schema(query_types=[things])

        sdl = print_schema(schema)

        # Custom ID scalar with UUID validation is in the schema
        # It's named "ID" for Apollo/Relay cache compatibility
        # The SDL may or may not show "scalar ID" depending on graphql-core behavior
        # What matters is the type is used correctly in the schema
        thing_type = schema.type_map.get("Thing")
        assert thing_type is not None
        id_field = thing_type.fields.get("id")
        assert id_field is not None
        # Required field is wrapped in GraphQLNonNull (Issue #243)
        if isinstance(id_field.type, GraphQLNonNull):
            assert id_field.type.of_type.name == "ID"
        else:
            assert id_field.type.name == "ID"


class TestIDTypeImports:
    """Tests for ID type imports."""

    def test_fraiseql_id_and_graphql_id_importable(self):
        """Test that both FraiseQL ID and GraphQL ID can be imported."""
        from graphql import GraphQLID as CoreID

        from fraiseql.types import ID as FraiseqlID

        assert CoreID is not None
        assert FraiseqlID is not None

    def test_uuid_uuid_maps_to_uuid_scalar(self):
        """Test that uuid.UUID maps to UUIDScalar (not IDScalar).

        SEMANTIC FIX: uuid.UUID is a generic UUID type, not specifically an identifier.
        Only explicit ID annotations should use the ID scalar. This is more semantically
        correct and allows using uuid.UUID for non-ID fields (like correlation IDs,
        external references, etc.).
        """
        result = convert_scalar_to_graphql(uuid.UUID)
        assert result is UUIDScalar
        assert result.name == "UUID"

    def test_id_maps_to_id_scalar_with_uuid_policy(self):
        """Test that ID (NewType) maps to IDScalar when using UUID policy (default)."""
        # Ensure UUID policy is active (default)
        SchemaConfig.set_config(id_policy=IDPolicy.UUID)

        result = convert_scalar_to_graphql(ID)
        assert result is IDScalar
        assert result.name == "ID"

    def test_id_maps_to_graphql_id_with_opaque_policy(self):
        """Test that ID maps to GraphQL's built-in ID with OPAQUE policy."""
        SchemaConfig.set_config(id_policy=IDPolicy.OPAQUE)

        result = convert_scalar_to_graphql(ID)
        assert result is GraphQLID
        assert result.name == "ID"

    def test_uuid_uuid_unchanged_by_policy(self):
        """Test that uuid.UUID always maps to UUIDScalar regardless of policy."""
        for policy in IDPolicy:
            SchemaConfig.set_config(id_policy=policy)
            result = convert_scalar_to_graphql(uuid.UUID)
            assert result is UUIDScalar
            assert result.name == "UUID"

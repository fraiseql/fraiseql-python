"""Test that Python reserved word parameters work correctly in GraphQL."""

from typing import AsyncGenerator
from uuid import UUID

import pytest

import fraiseql
from fraiseql import mutation, query, subscription
from fraiseql.config.schema_config import SchemaConfig
from fraiseql.gql.builders import SchemaComposer, SchemaRegistry
from fraiseql.types import ID


@fraiseql.type
class Item:
    id: ID
    type: str
    class_name: str


# Query with Python reserved words as parameters
@query
async def get_item(info, id_: ID, type_: str = "default") -> Item | None:
    """Get item by ID and type - uses trailing underscore for Python reserved words."""
    # IDScalar parses the id to uuid.UUID
    return Item(id=str(id_), type=type_, class_name="TestClass")


# Mutation with reserved word parameter
@mutation
async def create_item(info, id_: ID, class_: str) -> Item:
    """Create item with reserved word parameters."""
    return Item(id=str(id_), type="created", class_name=class_)


# Subscription with reserved word parameter
@subscription
async def watch_items(info, type_: str) -> AsyncGenerator[Item]:
    """Watch items of a specific type."""
    # Simulate streaming items
    for i in range(3):
        yield Item(
            id=UUID(f"12345678-1234-5678-1234-56781234567{i}"), type=type_, class_name=f"Class{i}"
        )


class TestReservedWordParameters:
    def setup_method(self) -> None:
        """Clear registry and type cache before each test."""
        SchemaRegistry._instance = None
        SchemaConfig._instance = None
        # Also clear the GraphQL type cache
        from fraiseql.core.graphql_type import _graphql_type_cache

        _graphql_type_cache.clear()

    def test_graphql_schema_removes_trailing_underscore(self) -> None:
        """Test that GraphQL schema exposes 'id' not 'id_'."""
        # Get schema
        registry = SchemaRegistry.get_instance()
        # Re-register our functions since we cleared the registry
        registry.register_type(Item)
        registry.register_query(get_item)
        registry.register_mutation(create_item)
        registry.register_subscription(watch_items)

        composer = SchemaComposer(registry)
        schema = composer.compose()

        # Check Query type
        query_type = schema.type_map.get("Query")
        assert query_type is not None

        # Check getItem field
        get_item_field = query_type.fields.get("getItem")
        assert get_item_field is not None

        # Check arguments - should be 'id' and 'type', not 'id_' and 'type_'
        assert "id" in get_item_field.args
        assert "type" in get_item_field.args
        assert "id_" not in get_item_field.args
        assert "type_" not in get_item_field.args

        # Check Mutation type
        mutation_type = schema.type_map.get("Mutation")
        assert mutation_type is not None

        # Check createItem field
        create_item_field = mutation_type.fields.get("createItem")
        assert create_item_field is not None

        # Check arguments - should be 'id' and 'class', not 'id_' and 'class_'
        assert "id" in create_item_field.args
        assert "class" in create_item_field.args
        assert "id_" not in create_item_field.args
        assert "class_" not in create_item_field.args

    @pytest.mark.asyncio
    async def test_query_execution_with_reserved_words(self) -> None:
        """Test that queries execute correctly with reserved word mapping."""
        from graphql import graphql

        # Get schema
        registry = SchemaRegistry.get_instance()
        # Re-register our functions since we cleared the registry
        registry.register_type(Item)
        registry.register_query(get_item)

        composer = SchemaComposer(registry)
        schema = composer.compose()

        # Execute query using standard GraphQL parameter names
        query_str = """
            query GetItem($itemId: ID!, $itemType: String!) {
                getItem(id: $itemId, type: $itemType) {
                    id
                    type
                    className
                }
            }
        """
        result = await graphql(
            schema,
            query_str,
            variable_values={
                "itemId": "12345678-1234-5678-1234-567812345678",
                "itemType": "special",
            },
            context_value={"db": None},
        )

        # Should work without errors
        assert result.errors is None or len(result.errors) == 0
        assert result.data is not None
        assert result.data["getItem"]["type"] == "special"

    @pytest.mark.asyncio
    async def test_mutation_execution_with_reserved_words(self) -> None:
        """Test that mutations execute correctly with reserved word mapping."""
        from graphql import graphql

        # Get schema
        registry = SchemaRegistry.get_instance()
        # Re-register our functions since we cleared the registry
        registry.register_type(Item)
        registry.register_query(get_item)  # Need at least one query
        registry.register_mutation(create_item)

        composer = SchemaComposer(registry)
        schema = composer.compose()

        # Execute mutation using standard GraphQL parameter names
        mutation_str = """
            mutation CreateItem($itemId: ID!, $className: String!) {
                createItem(id: $itemId, class: $className) {
                    id
                    type
                    className
                }
            }
        """
        result = await graphql(
            schema,
            mutation_str,
            variable_values={
                "itemId": "12345678-1234-5678-1234-567812345678",
                "className": "PremiumClass",
            },
            context_value={"db": None},
        )

        # Should work without errors
        assert result.errors is None or len(result.errors) == 0
        assert result.data is not None
        assert result.data["createItem"]["className"] == "PremiumClass"

    def test_introspection_shows_clean_names(self) -> None:
        """Test that introspection shows clean GraphQL names without underscores."""
        from graphql import graphql_sync

        registry = SchemaRegistry.get_instance()
        # Re-register our functions since we cleared the registry
        registry.register_type(Item)
        registry.register_query(get_item)

        composer = SchemaComposer(registry)
        schema = composer.compose()

        introspection_query = """
        {
            __type(name: "Query") {
                fields {
                    name
                    args {
                        name
                        type {
                            name
                        }
                    }
                }
            }
        }
        """
        result = graphql_sync(schema, introspection_query)
        assert result.data is not None

        query_type = result.data["__type"]
        for field in query_type["fields"]:
            if field["name"] == "getItem":
                arg_names = [arg["name"] for arg in field["args"]]
                # Should have clean names
                assert "id" in arg_names
                assert "type" in arg_names
                # Should NOT have underscore versions
                assert "id_" not in arg_names
                assert "type_" not in arg_names

"""Tests for SchemaSerializer class.

This module tests the serialization of GraphQL schemas to JSON IR format
that can be passed to Rust for type resolution.
"""

import uuid
from typing import Optional

import pytest

from fraiseql import query
from fraiseql.gql.schema_builder import SchemaRegistry, build_fraiseql_schema
from fraiseql.types import fraise_type


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear the schema registry and type cache before and after each test."""
    registry = SchemaRegistry.get_instance()
    registry.clear()

    # Also clear the GraphQL type cache
    from fraiseql.core.graphql_type import _graphql_type_cache

    _graphql_type_cache.clear()

    yield

    registry.clear()
    _graphql_type_cache.clear()


class TestSchemaSerializer:
    """Test suite for SchemaSerializer."""

    def test_serializes_object_type_with_scalar_fields(self) -> None:
        """Test that object types with scalar fields are correctly serialized.

        RED PHASE: This test will FAIL because SchemaSerializer is not implemented yet.
        """
        # Import will fail
        from fraiseql.core.schema_serializer import SchemaSerializer

        # Build a simple schema: type User { id: UUID!, name: String! }
        @fraise_type
        class User:
            id: uuid.UUID
            name: str

        @query
        async def users(info) -> list[User]:
            return []

        schema = build_fraiseql_schema(query_types=[User, users], mutation_resolvers=[])

        # Serialize
        serializer = SchemaSerializer()
        result = serializer.serialize_schema(schema)

        # Expected output structure
        assert "version" in result
        assert result["version"] == "1.0"
        assert "features" in result
        assert isinstance(result["features"], list)
        assert "type_resolution" in result["features"]
        assert "types" in result

        # Check User type was serialized
        assert "User" in result["types"]
        user_type = result["types"]["User"]

        assert "fields" in user_type
        assert "id" in user_type["fields"]
        assert "name" in user_type["fields"]

        # Check field metadata
        # Note: uuid.UUID maps to UUID scalar (not ID)
        # Use ID type annotation for identifier fields
        id_field = user_type["fields"]["id"]
        assert id_field["type_name"] == "UUID"
        assert id_field["is_nested_object"] is False
        assert id_field["is_list"] is False

        name_field = user_type["fields"]["name"]
        assert name_field["type_name"] == "String"
        assert name_field["is_nested_object"] is False
        assert name_field["is_list"] is False

    def test_serializes_nested_object_fields(self) -> None:
        """Test that nested object types are correctly identified.

        RED PHASE: This test will FAIL.
        """
        from fraiseql.core.schema_serializer import SchemaSerializer

        # Build schema: type Equipment { id: UUID!, name: String! }
        #               type Assignment { id: UUID!, equipment: Equipment }
        @fraise_type
        class Equipment:
            id: uuid.UUID
            name: str
            is_active: bool

        @fraise_type
        class Assignment:
            id: uuid.UUID
            start_date: str
            equipment: Optional[Equipment] = None

        @query
        async def assignments(info) -> list[Assignment]:
            return []

        schema = build_fraiseql_schema(
            query_types=[Equipment, Assignment, assignments], mutation_resolvers=[]
        )

        # Serialize
        serializer = SchemaSerializer()
        result = serializer.serialize_schema(schema)

        # Check Assignment type
        assert "Assignment" in result["types"]
        assignment_type = result["types"]["Assignment"]

        # Check equipment field is marked as nested object
        assert "equipment" in assignment_type["fields"]
        equipment_field = assignment_type["fields"]["equipment"]
        assert equipment_field["type_name"] == "Equipment"
        assert equipment_field["is_nested_object"] is True
        assert equipment_field["is_list"] is False

    def test_serializes_list_types(self) -> None:
        """Test that list types are correctly serialized.

        RED PHASE: This test will FAIL.
        """
        from fraiseql.core.schema_serializer import SchemaSerializer

        @fraise_type
        class Tag:
            id: uuid.UUID
            name: str

        @fraise_type
        class Post:
            id: uuid.UUID
            title: str
            tags: list[Tag]  # List of nested objects
            keywords: list[str]  # List of scalars

        @query
        async def posts(info) -> list[Post]:
            return []

        schema = build_fraiseql_schema(query_types=[Tag, Post, posts], mutation_resolvers=[])

        serializer = SchemaSerializer()
        result = serializer.serialize_schema(schema)

        assert "Post" in result["types"]
        post_type = result["types"]["Post"]

        # Check tags field (list of objects)
        tags_field = post_type["fields"]["tags"]
        assert tags_field["type_name"] == "Tag"
        assert tags_field["is_list"] is True
        assert tags_field["is_nested_object"] is True

        # Check keywords field (list of scalars)
        keywords_field = post_type["fields"]["keywords"]
        assert keywords_field["type_name"] == "String"
        assert keywords_field["is_list"] is True
        assert keywords_field["is_nested_object"] is False

    def test_includes_feature_flags(self) -> None:
        """Test that schema IR includes feature flags for forward compatibility.

        RED PHASE: This test will FAIL.
        """
        from fraiseql.core.schema_serializer import SchemaSerializer

        @fraise_type
        class SimpleType:
            id: uuid.UUID

        @query
        async def simple_query(info) -> list[SimpleType]:
            return []

        schema = build_fraiseql_schema(
            query_types=[SimpleType, simple_query], mutation_resolvers=[]
        )

        serializer = SchemaSerializer()
        result = serializer.serialize_schema(schema)

        # Must include version for forward compatibility
        assert "version" in result
        assert isinstance(result["version"], str)

        # Must include features array
        assert "features" in result
        assert isinstance(result["features"], list)
        assert "type_resolution" in result["features"]

    def test_serialization_performance(self) -> None:
        """Test that serialization completes within performance target.

        Target: < 10ms for 50-type schema

        RED PHASE: This test will FAIL.
        """
        import time

        from fraiseql.core.schema_serializer import SchemaSerializer

        # Build a moderately sized schema
        types = []
        for i in range(50):

            @fraise_type
            class DynamicType:
                id: uuid.UUID
                name: str
                value: int

            # Give it a unique name
            DynamicType.__name__ = f"Type{i}"
            types.append(DynamicType)

        @query
        async def dummy_query(info) -> list[types[0]]:
            return []

        schema = build_fraiseql_schema(query_types=[*types, dummy_query], mutation_resolvers=[])

        serializer = SchemaSerializer()

        # Measure serialization time
        start = time.time()
        result = serializer.serialize_schema(schema)
        duration_ms = (time.time() - start) * 1000

        # Should complete in < 10ms
        assert duration_ms < 10, f"Serialization took {duration_ms:.2f}ms (target: < 10ms)"

        # Verify it actually serialized types
        assert len(result["types"]) >= 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

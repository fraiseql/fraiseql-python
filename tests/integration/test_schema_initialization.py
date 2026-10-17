"""Integration tests for Schema Registry initialization from Python.

This module tests that the GraphQL schema can be serialized in Python
and successfully initialized in the Rust schema registry via FFI.

Tests follow the TDD RED-GREEN-REFACTOR cycle as specified in Task 1.3.
"""

import json
import uuid
from typing import Optional

import pytest

from fraiseql import query
from fraiseql.core.schema_serializer import SchemaSerializer
from fraiseql.gql.schema_builder import build_fraiseql_schema
from fraiseql.mutations.decorators import clear_mutation_registries
from fraiseql.types import fraise_type

# Import Rust extension for tests
try:
    from fraiseql import _fraiseql_rs
except ImportError:
    _fraiseql_rs = None

pytestmark = pytest.mark.integration


# Skip tests if Rust extension is not available
requires_rust = pytest.mark.skipif(_fraiseql_rs is None, reason="Rust extension not available")


class TestSchemaRegistryInitialization:
    """Integration tests for schema registry initialization via FFI.

    Note: The schema registry is a global singleton, so it can only be
    initialized once per test session. Tests are ordered to handle this.
    """

    def setup_method(self) -> None:
        """Clear mutation registries before each test to avoid pollution."""
        clear_mutation_registries()

    @requires_rust
    def test_01_initialize_simple_schema(self) -> None:
        """Test that schema can be initialized from Python with simple types.

        This test runs first and initializes the global registry.
        """

        # Build a simple test schema
        @fraise_type
        class User:
            id: uuid.UUID
            name: str
            email: str

        @query
        async def users(info) -> list[User]:
            return []

        schema = build_fraiseql_schema(query_types=[User, users], mutation_resolvers=[])

        # Serialize schema to JSON IR
        serializer = SchemaSerializer()
        schema_ir = serializer.serialize_schema(schema)
        schema_json = json.dumps(schema_ir)

        # This should call Rust FFI to initialize the registry
        # Note: Registry can only be initialized once per process
        # In full test suite runs, it may already be initialized by other tests
        try:
            result = _fraiseql_rs.initialize_schema_registry(schema_json)
            # Should not raise error and should indicate success
            assert result is None or result is True
        except RuntimeError as e:
            # Registry already initialized - this is acceptable in test suite
            if "already initialized" in str(e):
                pass  # Test passes - registry is working as designed
            else:
                raise  # Re-raise if it's a different error

    def test_02_verify_nested_objects_schema_structure(self) -> None:
        """Test that schema with nested objects can be serialized correctly.

        Note: We can't re-initialize the registry, so we just verify
        the schema serialization structure is correct.
        """

        # Build schema with nested objects (Issue #112 scenario)
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

        # Serialize and verify structure
        serializer = SchemaSerializer()
        schema_ir = serializer.serialize_schema(schema)

        # Verify the schema has the expected structure
        assert "version" in schema_ir
        assert "features" in schema_ir
        assert "types" in schema_ir
        assert "Assignment" in schema_ir["types"]
        assert "equipment" in schema_ir["types"]["Assignment"]["fields"]

        # Verify equipment field is marked as nested object
        equipment_field = schema_ir["types"]["Assignment"]["fields"]["equipment"]
        assert equipment_field["is_nested_object"] is True
        assert equipment_field["type_name"] == "Equipment"

    def test_03_verify_list_types_schema_structure(self) -> None:
        """Test that schema with list types can be serialized correctly.

        Note: We can't re-initialize the registry, so we just verify
        the schema serialization structure is correct.
        """

        @fraise_type
        class Tag:
            id: uuid.UUID
            name: str

        @fraise_type
        class Post:
            id: uuid.UUID
            title: str
            tags: list[Tag]

        @query
        async def posts(info) -> list[Post]:
            return []

        schema = build_fraiseql_schema(query_types=[Tag, Post, posts], mutation_resolvers=[])

        serializer = SchemaSerializer()
        schema_ir = serializer.serialize_schema(schema)

        # Verify list types are handled
        assert "Post" in schema_ir["types"]
        tags_field = schema_ir["types"]["Post"]["fields"]["tags"]
        assert tags_field["is_list"] is True
        assert tags_field["is_nested_object"] is True
        assert tags_field["type_name"] == "Tag"

    @requires_rust
    def test_initialize_with_malformed_json(self) -> None:
        """Test that malformed JSON raises clear error.

        RED PHASE: This test will FAIL (function doesn't exist yet).
        """
        malformed_json = '{"invalid": json}'

        # Should raise a clear Python exception
        with pytest.raises(Exception) as exc_info:
            _fraiseql_rs.initialize_schema_registry(malformed_json)

        # Error should be informative
        error_msg = str(exc_info.value).lower()
        assert "json" in error_msg or "parse" in error_msg

    @requires_rust
    def test_initialize_with_empty_json(self) -> None:
        """Test that empty JSON is rejected.

        This validates that required fields are checked.
        """
        empty_json = "{}"

        # Should raise an error about missing required fields
        with pytest.raises(Exception) as exc_info:
            _fraiseql_rs.initialize_schema_registry(empty_json)

        # Should mention missing fields
        error_msg = str(exc_info.value).lower()
        assert "version" in error_msg or "types" in error_msg or "missing" in error_msg

    @requires_rust
    def test_initialize_with_empty_string(self) -> None:
        """Test that empty string is rejected with clear error."""
        with pytest.raises(ValueError) as exc_info:
            _fraiseql_rs.initialize_schema_registry("")

        error_msg = str(exc_info.value).lower()
        assert "empty" in error_msg

    def test_performance_large_schema(self) -> None:
        """Test initialization performance with a large schema.

        Target: < 100ms for 100-type schema (from plan)
        This test creates 50+ types to verify performance is acceptable.
        """
        import time

        # Build a large schema with many types
        types = []
        for i in range(50):

            @fraise_type
            class DynamicType:
                id: uuid.UUID
                name: str
                value: int
                description: str

            # Give it a unique name
            DynamicType.__name__ = f"LargeSchemaType{i}"
            types.append(DynamicType)

        @query
        async def large_query(info) -> list[types[0]]:
            return []

        # Note: This schema has already been initialized in test_01, so we
        # just verify the serialization performance is acceptable
        schema = build_fraiseql_schema(query_types=[*types, large_query], mutation_resolvers=[])

        serializer = SchemaSerializer()

        # Measure serialization time (Python side)
        start = time.time()
        schema_ir = serializer.serialize_schema(schema)
        serialization_time_ms = (time.time() - start) * 1000

        # Serialization should be fast (< 100ms for 50+ types)
        assert serialization_time_ms < 100, (
            f"Serialization took {serialization_time_ms:.2f}ms (target: < 100ms)"
        )

        # Verify the schema structure is correct
        assert len(schema_ir["types"]) >= 50, f"Expected >= 50 types, got {len(schema_ir['types'])}"
        assert schema_ir["version"] == "1.0"
        assert "type_resolution" in schema_ir["features"]

    @requires_rust
    def test_error_message_quality(self) -> None:
        """Test that error messages are helpful for debugging."""
        # Test with JSON missing 'version' field
        invalid_schema = json.dumps({"features": [], "types": {}})

        with pytest.raises(ValueError) as exc_info:
            _fraiseql_rs.initialize_schema_registry(invalid_schema)

        error_msg = str(exc_info.value)
        # Error should mention the expected format
        assert "version" in error_msg.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

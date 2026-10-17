"""Integration tests for FraiseQL application startup.

This module tests that the schema registry is automatically initialized
when create_fraiseql_app() is called, following Task 1.4 of the schema registry plan.
"""

import json
import time
import uuid
from typing import Optional
from unittest.mock import patch

import pytest

from fraiseql import fraise_type, query
from fraiseql.fastapi import create_fraiseql_app

pytestmark = pytest.mark.integration


@pytest.fixture
def clean_registries() -> None:
    """Clean all registries before and after each test."""
    from fraiseql.gql.builders.registry import SchemaRegistry
    from fraiseql.mutations.decorators import clear_mutation_registries

    registry = SchemaRegistry.get_instance()
    registry.clear()
    clear_mutation_registries()

    yield

    # Clear after test
    registry.clear()
    clear_mutation_registries()


class TestSchemaRegistryAppStartup:
    """Tests for automatic schema registry initialization on app startup."""

    def test_schema_registry_initialized_on_app_startup(self, clean_registries) -> None:
        """Test that schema registry is automatically initialized when app is created.

        RED PHASE: This test will FAIL because we haven't added the initialization
        code to create_fraiseql_app() yet.

        Expected behavior: The schema should be serialized and the Rust registry
        should be initialized automatically during app creation.
        """

        # Define test types
        @fraise_type
        class User:
            id: uuid.UUID
            name: str
            email: str

        @query
        async def users(info) -> list[User]:
            return []

        # Mock the initialize_schema_registry function to verify it gets called
        with patch("fraiseql._fraiseql_rs.initialize_schema_registry") as mock_init:
            # Create the app
            create_fraiseql_app(
                database_url="postgresql://test@localhost/test",
                types=[User],
                queries=[users],
            )

            # Verify the registry initialization was called
            assert mock_init.call_count == 1, "Schema registry should be initialized exactly once"

            # Verify it was called with valid JSON
            call_args = mock_init.call_args[0]
            assert len(call_args) == 1, (
                "initialize_schema_registry should be called with one argument"
            )

            schema_json_str = call_args[0]
            schema_ir = json.loads(schema_json_str)

            # Verify the schema IR has the expected structure
            assert "version" in schema_ir
            assert "features" in schema_ir
            assert "types" in schema_ir
            assert "User" in schema_ir["types"]

    def test_schema_registry_with_nested_objects(self, clean_registries) -> None:
        """Test that nested object types are properly initialized.

        This ensures the Issue #112 scenario (nested JSONB) will work.
        """

        @fraise_type
        class Equipment:
            id: uuid.UUID
            name: str

        @fraise_type
        class Assignment:
            id: uuid.UUID
            equipment: Optional[Equipment] = None

        @query
        async def assignments(info) -> list[Assignment]:
            return []

        with patch("fraiseql._fraiseql_rs.initialize_schema_registry") as mock_init:
            create_fraiseql_app(
                database_url="postgresql://test@localhost/test",
                types=[Equipment, Assignment],
                queries=[assignments],
            )

            # Verify the nested object structure was captured
            call_args = mock_init.call_args[0]
            schema_ir = json.loads(call_args[0])

            assert "Assignment" in schema_ir["types"]
            assignment_fields = schema_ir["types"]["Assignment"]["fields"]
            assert "equipment" in assignment_fields

            equipment_field = assignment_fields["equipment"]
            assert equipment_field["is_nested_object"] is True
            assert equipment_field["type_name"] == "Equipment"

    def test_startup_performance_acceptable(self, clean_registries) -> None:
        """Test that schema registry initialization adds minimal overhead to startup.

        Target: < 100ms added to startup time (from plan)
        """

        @fraise_type
        class SimpleType:
            id: uuid.UUID
            name: str

        @query
        async def simple_query(info) -> list[SimpleType]:
            return []

        # Measure startup time with registry initialization
        start = time.time()
        create_fraiseql_app(
            database_url="postgresql://test@localhost/test",
            types=[SimpleType],
            queries=[simple_query],
        )
        startup_time_ms = (time.time() - start) * 1000

        # Should be very fast (< 100ms for simple schema)
        # Note: This is just the Python side, not including DB connection
        assert startup_time_ms < 100, f"Startup took {startup_time_ms:.2f}ms (target: < 100ms)"

    def test_feature_flag_can_disable_registry(self, clean_registries) -> None:
        """Test that schema registry can be disabled via feature flag.

        RED PHASE: This will FAIL because the feature flag doesn't exist yet.

        This allows for gradual rollout and easy rollback if issues are found.
        """

        @fraise_type
        class User:
            id: uuid.UUID
            name: str

        @query
        async def users(info) -> list[User]:
            return []

        with patch("fraiseql._fraiseql_rs.initialize_schema_registry") as mock_init:
            # Create app with registry disabled
            create_fraiseql_app(
                database_url="postgresql://test@localhost/test",
                types=[User],
                queries=[users],
                enable_schema_registry=False,  # Feature flag
            )

            # Registry should NOT be initialized when disabled
            assert mock_init.call_count == 0, (
                "Schema registry should not be initialized when disabled"
            )

    def test_app_logs_successful_initialization(self, clean_registries, caplog) -> None:
        """Test that successful initialization is logged.

        RED PHASE: This will FAIL because logging hasn't been added yet.
        """

        @fraise_type
        class User:
            id: uuid.UUID
            name: str

        @query
        async def users(info) -> list[User]:
            return []

        import logging

        caplog.set_level(logging.INFO)

        with patch("fraiseql._fraiseql_rs.initialize_schema_registry"):
            create_fraiseql_app(
                database_url="postgresql://test@localhost/test",
                types=[User],
                queries=[users],
            )

            # Should log successful initialization
            log_messages = [record.message for record in caplog.records]
            assert any("schema registry" in msg.lower() for msg in log_messages), (
                "Should log schema registry initialization"
            )

    def test_initialization_error_is_handled_gracefully(self, clean_registries) -> None:
        """Test that errors during initialization are handled properly.

        The app should still be created even if registry initialization fails,
        to maintain backward compatibility.

        RED PHASE: This will FAIL because error handling isn't implemented yet.
        """

        @fraise_type
        class User:
            id: uuid.UUID
            name: str

        @query
        async def users(info) -> list[User]:
            return []

        # Mock initialization to raise an error
        with patch("fraiseql._fraiseql_rs.initialize_schema_registry") as mock_init:
            mock_init.side_effect = RuntimeError("Schema registry is already initialized")

            # App creation should not fail
            app = create_fraiseql_app(
                database_url="postgresql://test@localhost/test",
                types=[User],
                queries=[users],
            )

            # App should be created successfully despite registry error
            assert app is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

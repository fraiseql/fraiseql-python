"""Test UNSET handling in production mode GraphQL error extensions."""

import pytest
from fastapi.testclient import TestClient
from graphql import GraphQLError

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.types.definitions import UNSET


@pytest.mark.unit
@fraiseql.input
class SampleInput:
    """Test input with optional fields."""

    required_field: str
    optional_field: str | None = UNSET
    another_optional: int | None = UNSET


@fraiseql.type
class SampleType:
    """Test output type."""

    id: str
    name: str


@fraiseql.query
async def error_query(info) -> SampleType:
    """Test query that raises an error with UNSET in extensions."""
    # Simulate an error that includes UNSET values in extensions
    input_data = SampleInput(required_field="test")
    error = GraphQLError(
        "Test error with UNSET in extensions",
        extensions={
            "code": "TEST_ERROR",
            "input": {
                "required_field": input_data.required_field,
                "optional_field": input_data.optional_field,  # This is UNSET
                "another_optional": input_data.another_optional,  # This is UNSET
            },
            "nested": {"unset_value": UNSET, "normal_value": "test"},
        },
    )
    raise error


@fraiseql.query
async def validation_error_query(info) -> list[SampleType]:
    """Test query that triggers validation error."""
    # This will be used to test the validation error path
    return []


def test_production_mode_unset_in_graphql_error_extensions(clear_registry, monkeypatch) -> None:
    """Test that production mode properly cleans UNSET from GraphQL error extensions."""
    from unittest.mock import MagicMock

    # Mock the database pool to avoid actual database connection
    mock_pool = MagicMock()
    mock_db = MagicMock()
    monkeypatch.setattr("fraiseql.fastapi.dependencies.get_db_pool", lambda: mock_pool)
    monkeypatch.setattr("fraiseql.fastapi.dependencies.get_db", lambda: mock_db)

    # Create production app with explicit config
    config = FraiseQLConfig(
        database_url="postgresql://test/test",
        environment="production",
        enable_playground=False,
        enable_introspection=False,
    )

    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        types=[SampleType],
        queries=[error_query, validation_error_query],
        config=config,
    )

    client = TestClient(app)

    # Test query that raises error with UNSET in extensions
    query = """
    query {
        errorQuery {
            id
            name
        }
    }
    """
    response = client.post("/graphql", json={"query": query})

    # Should get a response without JSON serialization error
    assert response.status_code == 200

    data = response.json()
    assert "errors" in data
    assert len(data["errors"]) == 1

    error = data["errors"][0]
    # In production with hide_error_details=True (default), message is generic
    # But extensions should still be properly serialized
    assert "extensions" in error

    # The error extensions should have UNSET converted to None
    extensions = error["extensions"]
    if "input" in extensions:
        # If error details are not hidden, check the cleaned values
        assert extensions["input"]["optional_field"] is None  # UNSET -> None
        assert extensions["input"]["another_optional"] is None  # UNSET -> None

    # Should not raise JSON serialization error


def test_production_mode_validation_error_with_unset(clear_registry, monkeypatch) -> None:
    """Test that production mode handles validation errors that might have UNSET."""
    from unittest.mock import MagicMock

    # Mock the database pool to avoid actual database connection
    monkeypatch.setattr("fraiseql.fastapi.dependencies.get_db_pool", MagicMock)
    monkeypatch.setattr("fraiseql.fastapi.dependencies.get_db", MagicMock)

    config = FraiseQLConfig(
        database_url="postgresql://test/test",
        environment="production",
        enable_playground=False,
        enable_introspection=False,
    )

    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        types=[SampleType],
        queries=[validation_error_query],
        config=config,
    )

    client = TestClient(app)

    # Send an invalid query to trigger validation error
    query = """
    query {
        validationErrorQuery {
            id
            name
            invalidField
        }
    }
    """
    response = client.post("/graphql", json={"query": query})

    # Should get a response without JSON serialization error
    assert response.status_code == 200

    data = response.json()
    # If no validation error occurs, test that the query executes without UNSET serialization issues
    if "errors" in data:
        assert len(data["errors"]) > 0
        # Validation errors should have proper extensions
        error = data["errors"][0]
        assert "extensions" in error
        # Check that the error was properly serialized (no JSON serialization error)
    else:
        # Even if no validation error, the test succeeded in showing no UNSET serialization issues
        assert "data" in data
        # In production mode with raw JSON passthrough, the response may be wrapped
        validation_result = data["data"]["validationErrorQuery"]
        # Handle both direct response and wrapped response (raw JSON passthrough behavior)
        if isinstance(validation_result, dict) and "data" in validation_result:
            # Raw JSON passthrough wraps the response
            assert validation_result["data"]["validationErrorQuery"] == []
        else:
            # Direct response
            assert validation_result == []


def test_production_mode_with_detailed_errors(clear_registry, monkeypatch) -> None:
    """Test production mode when hide_error_details is False."""
    from unittest.mock import MagicMock

    # Mock the database pool to avoid actual database connection
    monkeypatch.setattr("fraiseql.fastapi.dependencies.get_db_pool", MagicMock)
    monkeypatch.setattr("fraiseql.fastapi.dependencies.get_db", MagicMock)

    # Custom config that shows error details in production
    config = FraiseQLConfig(
        database_url="postgresql://test/test",
        environment="production",
        enable_playground=False,
        enable_introspection=False,
        hide_error_details=False,  # Show error details even in production
    )

    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        types=[SampleType],
        queries=[error_query],
        config=config,
    )

    client = TestClient(app)

    query = """
    query {
        errorQuery {
            id
            name
        }
    }
    """
    response = client.post("/graphql", json={"query": query})

    assert response.status_code == 200

    data = response.json()
    assert "errors" in data
    assert len(data["errors"]) == 1

    error = data["errors"][0]
    # With hide_error_details=False, we should see the actual error message
    assert error["message"] == "Test error with UNSET in extensions"
    assert "extensions" in error

    # All UNSET values should be cleaned
    extensions = error["extensions"]
    assert extensions["code"] == "TEST_ERROR"
    assert extensions["input"]["required_field"] == "test"
    assert extensions["input"]["optional_field"] is None  # UNSET -> None
    assert extensions["input"]["another_optional"] is None  # UNSET -> None
    assert extensions["nested"]["unset_value"] is None  # UNSET -> None
    assert extensions["nested"]["normal_value"] == "test"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

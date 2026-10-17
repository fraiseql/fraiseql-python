"""Test UNSET handling in GraphQL error extensions."""

import pytest
from fastapi.testclient import TestClient
from graphql import GraphQLError

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
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


@fraiseql.success
class SampleSuccess:
    """Success response."""

    item: SampleType


@fraiseql.error
class SampleError:
    """Error response."""

    code: str
    message: str


@fraiseql.mutation
class CreateTestItem:
    """Test mutation that might raise errors with UNSET in extensions."""

    input: SampleInput
    success: SampleSuccess
    error: SampleError


# Mock query that might raise an error with UNSET in extensions
@fraiseql.query
async def error_query_func(info) -> SampleType:
    """Test query that raises an error with UNSET in extensions."""
    # Simulate an error that includes input data with UNSET
    input_data = SampleInput(required_field="test")
    error = GraphQLError(
        """Test error with UNSET in extensions""",
        extensions={
            "code": "TEST_ERROR",
            "input": {
                "required_field": input_data.required_field,
                "optional_field": input_data.optional_field,  # This is UNSET
                "another_optional": input_data.another_optional,  # This is UNSET
            },
            "debug_info": {"some_value": "test", "unset_value": UNSET},
        },
    )
    raise error


@pytest.fixture
def test_app(clear_registry, monkeypatch) -> None:
    """Create test app with our test types."""
    from unittest.mock import MagicMock

    # Mock the database pool to avoid actual database connection
    mock_pool = MagicMock()
    mock_db = MagicMock()

    monkeypatch.setattr("fraiseql.fastapi.dependencies.get_db_pool", lambda: mock_pool)
    monkeypatch.setattr("fraiseql.fastapi.dependencies.get_db", lambda: mock_db)

    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        types=[SampleType],
        queries=[error_query_func],
        mutations=[CreateTestItem],
    )
    return app


@pytest.fixture
def test_client(test_app) -> None:
    """Create test client."""
    return TestClient(test_app)


def test_graphql_error_with_unset_in_extensions(test_client, clear_registry) -> None:
    """Test that UNSET values in error extensions are properly serialized."""
    query = """
    query {
        errorQueryFunc {
            id
            name
        }
    }
    """
    response = test_client.post("/graphql", json={"query": query})

    # Should get a response without JSON serialization error
    assert response.status_code == 200

    data = response.json()
    assert "errors" in data
    assert len(data["errors"]) == 1

    error = data["errors"][0]
    assert error["message"] == "Test error with UNSET in extensions"
    assert "extensions" in error

    # UNSET values should be converted to null
    extensions = error["extensions"]
    assert extensions["code"] == "TEST_ERROR"
    assert extensions["input"]["required_field"] == "test"
    assert extensions["input"]["optional_field"] is None  # UNSET -> None
    assert extensions["input"]["another_optional"] is None  # UNSET -> None
    assert extensions["debug_info"]["some_value"] == "test"
    assert extensions["debug_info"]["unset_value"] is None  # UNSET -> None


def test_mutation_error_with_unset_input(test_client, monkeypatch, clear_registry) -> None:
    """Test mutation error handling when input contains UNSET."""
    from unittest.mock import MagicMock

    # Mock the database to simulate an error
    mock_db = MagicMock()

    async def mock_execute_function(func_name, input_data) -> None:
        # Simulate error that includes the input data
        raise GraphQLError(
            "Database constraint violation",
            extensions={
                "code": "CONSTRAINT_VIOLATION",
                "input_received": input_data,  # This might contain UNSET
                "field_with_issue": "optional_field",
            },
        )

    mock_db.execute_function = mock_execute_function

    # Override the context getter to provide our mock
    async def get_test_context(request) -> None:
        return {"db": mock_db}

    # Create a new app with our context getter
    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        types=[SampleType],
        mutations=[CreateTestItem],
        context_getter=get_test_context,
    )

    client = TestClient(app)

    mutation = """
    mutation {
        createTestItem(input: {requiredField: "test"}) {
            __typename
            ... on SampleSuccess {
                item {
                    id
                    name
                }
            }
            ... on SampleError {
                code
                message
            }
        }
    }
    """
    response = client.post("/graphql", json={"query": mutation})

    # Should not fail with JSON serialization error
    assert response.status_code == 200
    data = response.json()

    # The response should contain properly serialized error
    assert "errors" in data
    assert len(data["errors"]) > 0


def test_production_mode_error_handling(monkeypatch, clear_registry) -> None:
    """Test that production mode also handles UNSET in errors."""
    from unittest.mock import MagicMock

    # Mock the database pool to avoid actual database connection
    monkeypatch.setattr("fraiseql.fastapi.dependencies.get_db_pool", MagicMock)
    monkeypatch.setattr("fraiseql.fastapi.dependencies.get_db", MagicMock)

    # Create production app
    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        types=[SampleType],
        queries=[error_query_func],
        production=True,
    )

    client = TestClient(app)

    query = """
    query {
        errorQueryFunc {
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
    # In production, error details are hidden but it should still serialize properly


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

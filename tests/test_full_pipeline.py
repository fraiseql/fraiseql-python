"""Tests for unified Rust GraphQL pipeline (Phase 9)."""

import json

import pytest
from fraiseql._fraiseql_rs import PyGraphQLPipeline


@pytest.fixture
def test_schema():
    """Test schema for Phase 9 pipeline."""
    return {
        "tables": {
            "users": {
                "view_name": "v_user",
                "sql_columns": ["id", "email", "status"],
                "jsonb_column": "data",
                "fk_mappings": {"machine": "machine_id"},
                "has_jsonb_data": True,
            }
        },
        "types": {},
    }


@pytest.fixture
def pipeline(test_schema):
    """Create PyGraphQLPipeline instance."""
    schema_json = json.dumps(test_schema)
    return PyGraphQLPipeline(schema_json)


@pytest.fixture
def user_context():
    """Standard user context for tests."""
    return {"user_id": "test_user", "permissions": ["read"], "roles": ["user"]}


def test_simple_query(pipeline, user_context):
    """Test simple GraphQL query through unified pipeline."""
    query = """
    query {
        users(limit: 10) {
            id
            email
        }
    }
    """

    result_bytes = pipeline.execute(query, {}, user_context)
    data = json.loads(result_bytes)

    assert "data" in data
    assert "users" in data["data"]
    assert isinstance(data["data"]["users"], list)
    assert len(data["data"]["users"]) > 0


def test_query_with_where(pipeline, user_context):
    """Test query with WHERE clause."""
    query = """
    query {
        users(where: {status: "active"}) {
            id
            status
        }
    }
    """

    result_bytes = pipeline.execute(query, {}, user_context)
    data = json.loads(result_bytes)

    assert "data" in data
    assert "users" in data["data"]


def test_query_with_limit(pipeline, user_context):
    """Test pagination with LIMIT."""
    query = """
    query {
        users(limit: 5) {
            id
        }
    }
    """

    result_bytes = pipeline.execute(query, {}, user_context)
    data = json.loads(result_bytes)

    assert "data" in data
    assert len(data["data"]["users"]) <= 5


def test_query_with_variables(pipeline, user_context):
    """Test query with variables (variables not yet implemented in Phase 9 mock)."""
    query = """
    query GetUsers($limit: Int) {
        users(limit: $limit) {
            id
        }
    }
    """

    result_bytes = pipeline.execute(query, {"limit": 3}, user_context)
    data = json.loads(result_bytes)

    # Variables not yet substituted in Phase 9 mock, but query should parse
    assert "data" in data
    assert "users" in data["data"]


def test_invalid_query(pipeline, user_context):
    """Test error handling for invalid queries."""
    query = "invalid graphql syntax {{{"

    with pytest.raises(Exception):
        pipeline.execute(query, {}, user_context)


def test_mutation_mock(pipeline, user_context):
    """Test mutation (mocked in Phase 9 - mutations not yet supported)."""
    query = """
    mutation {
        createUser(input: {name: "John"}) {
            id
            name
        }
    }
    """

    # Mutations not supported in Phase 9 mock, should raise error
    with pytest.raises(Exception):
        pipeline.execute(query, {}, user_context)


def test_cache_functionality(pipeline, user_context):
    """Test that caching works (same query returns same results)."""
    query = "query { users { id } }"

    # First request
    result1_bytes = pipeline.execute(query, {}, user_context)
    data1 = json.loads(result1_bytes)

    # Second request (should hit cache)
    result2_bytes = pipeline.execute(query, {}, user_context)
    data2 = json.loads(result2_bytes)

    # Results should be identical
    assert data1 == data2


def test_complex_where_clause(pipeline, user_context):
    """Test complex WHERE clause with AND/OR."""
    query = """
    query {
        users(where: {
            AND: [
                {status: "active"},
                {email: {like: "test"}}
            ]
        }) {
            id
            email
            status
        }
    }
    """

    result_bytes = pipeline.execute(query, {}, user_context)
    data = json.loads(result_bytes)

    assert "data" in data
    assert "users" in data["data"]

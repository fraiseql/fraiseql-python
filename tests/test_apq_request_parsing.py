"""Tests for APQ request parsing functionality."""

import pytest

from fraiseql.fastapi.routers import GraphQLRequest


def test_graphql_request_accepts_extensions_field() -> None:
    """Test that GraphQLRequest model accepts extensions field for APQ."""
    apq_request = {
        "query": None,
        "variables": {},
        "extensions": {
            "persistedQuery": {
                "version": 1,
                "sha256Hash": "ecf4edb46db40b5132295c0291d62fb65d6759a9eedfa4d5d612dd5ec54a6b38",
            }
        },
    }
    # Should not raise validation error
    request = GraphQLRequest(**apq_request)
    assert request.extensions is not None
    assert request.extensions["persistedQuery"]["version"] == 1
    assert (
        request.extensions["persistedQuery"]["sha256Hash"]
        == "ecf4edb46db40b5132295c0291d62fb65d6759a9eedfa4d5d612dd5ec54a6b38"
    )


def test_graphql_request_extensions_optional() -> None:
    """Test that extensions field is optional."""
    normal_request = {
        "query": "{ hello }",
        "variables": {},
    }
    request = GraphQLRequest(**normal_request)
    assert request.extensions is None
    assert request.query == "{ hello }"


def test_graphql_request_with_query_and_extensions() -> None:
    """Test that request can have both query and extensions."""
    request_data = {
        "query": "{ users { id name } }",
        "variables": {"limit": 10},
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": "abc123"}},
    }
    request = GraphQLRequest(**request_data)
    assert request.query == "{ users { id name } }"
    assert request.variables == {"limit": 10}
    assert request.extensions is not None
    assert request.extensions["persistedQuery"]["sha256Hash"] == "abc123"


def test_graphql_request_apq_validation_errors() -> None:
    """Test APQ validation catches invalid formats."""
    # Missing version
    with pytest.raises(ValueError, match=r"persistedQuery\.version is required"):
        GraphQLRequest(extensions={"persistedQuery": {"sha256Hash": "abc123"}})

    # Missing sha256Hash
    with pytest.raises(ValueError, match=r"persistedQuery\.sha256Hash is required"):
        GraphQLRequest(extensions={"persistedQuery": {"version": 1}})

    # Wrong version
    with pytest.raises(ValueError, match="Only APQ version 1 is supported"):
        GraphQLRequest(extensions={"persistedQuery": {"version": 2, "sha256Hash": "abc123"}})

    # Empty sha256Hash
    with pytest.raises(ValueError, match=r"persistedQuery\.sha256Hash must be a non-empty string"):
        GraphQLRequest(extensions={"persistedQuery": {"version": 1, "sha256Hash": ""}})

    # Non-string sha256Hash
    with pytest.raises(ValueError, match=r"persistedQuery\.sha256Hash must be a non-empty string"):
        GraphQLRequest(extensions={"persistedQuery": {"version": 1, "sha256Hash": 123}})


def test_graphql_request_non_apq_extensions() -> None:
    """Test that non-APQ extensions pass through without validation."""
    request_data = {
        "query": "{ hello }",
        "extensions": {"tracing": {"version": 1}, "complexity": {"maximumComplexity": 1000}},
    }
    request = GraphQLRequest(**request_data)
    assert request.extensions["tracing"]["version"] == 1
    assert request.extensions["complexity"]["maximumComplexity"] == 1000

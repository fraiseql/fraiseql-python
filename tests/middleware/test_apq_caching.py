"""Tests for APQ cached response support in middleware."""

from unittest.mock import Mock

import pytest

from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.storage.apq_store import compute_query_hash
from fraiseql.storage.backends.memory import MemoryAPQBackend

pytestmark = pytest.mark.integration

_QUERY = "{ user(id: $userId) { id name email } }"
_HASH = compute_query_hash(_QUERY)


class MockGraphQLSchema:
    """Mock GraphQL schema for testing."""


@pytest.fixture
def mock_config() -> None:
    """Create a mock config with APQ caching enabled."""
    return FraiseQLConfig(
        database_url="postgresql://test@localhost/test",
        apq_storage_backend="memory",
        apq_cache_responses=True,
        apq_response_cache_ttl=600,
    )


@pytest.fixture
def mock_backend() -> None:
    """Create a mock APQ backend for testing."""
    return MemoryAPQBackend()


@pytest.fixture
def mock_request() -> None:
    """Create a mock GraphQL request with APQ."""
    return Mock(
        query=None,
        variables={"userId": 123},
        operationName="GetUser",
        extensions={"persistedQuery": {"version": 1, "sha256Hash": _HASH}},
    )


@pytest.fixture
def mock_http_request() -> None:
    """Create a mock HTTP request."""
    return Mock(headers={})


@pytest.fixture
def mock_context() -> None:
    """Create a mock GraphQL context."""
    return {"user": {"id": 1}, "authenticated": True}


def test_apq_cache_hit_returns_cached_response(
    mock_config, mock_backend, mock_request, mock_http_request, mock_context
) -> None:
    """Test that cached responses are returned on cache hit."""
    # Setup: Store both query and cached response
    hash_value = _HASH
    query = _QUERY
    cached_response = {
        "data": {"user": {"id": 123, "name": "John Doe", "email": "john@example.com"}}
    }

    mock_backend.store_persisted_query(hash_value, query)

    # Compute the same cache key that handle_apq_request_with_cache will use
    from fraiseql.middleware.apq_caching import compute_response_cache_key

    cache_key = compute_response_cache_key(hash_value, mock_request.variables)
    mock_backend.store_cached_response(cache_key, cached_response)

    # Test: Should return cached response directly
    from fraiseql.middleware.apq_caching import handle_apq_request_with_cache

    result = handle_apq_request_with_cache(mock_request, mock_backend, mock_config)

    assert result == cached_response


def test_apq_cache_miss_falls_back_to_query_execution(
    mock_config, mock_backend, mock_request
) -> None:
    """Test that cache miss falls back to normal query execution."""
    # Setup: Store only query, no cached response
    hash_value = _HASH
    query = _QUERY

    mock_backend.store_persisted_query(hash_value, query)
    # No cached response stored

    # Test: Should return None to indicate cache miss
    from fraiseql.middleware.apq_caching import handle_apq_request_with_cache

    result = handle_apq_request_with_cache(mock_request, mock_backend, mock_config)

    assert result is None  # Cache miss, should fall back to normal execution


def test_apq_cache_disabled_returns_none(mock_config, mock_backend, mock_request) -> None:
    """Test that caching is bypassed when disabled in config."""
    # Setup: Store both query and cached response
    hash_value = _HASH
    query = _QUERY
    cached_response = {"data": {"user": {"id": 123}}}

    mock_backend.store_persisted_query(hash_value, query)
    mock_backend.store_cached_response(hash_value, cached_response)

    # Disable caching in config
    mock_config.apq_cache_responses = False

    # Test: Should return None (cache disabled)
    from fraiseql.middleware.apq_caching import handle_apq_request_with_cache

    result = handle_apq_request_with_cache(mock_request, mock_backend, mock_config)

    assert result is None


def test_apq_cache_response_storage(mock_config, mock_backend) -> None:
    """Test storing responses in cache after execution."""
    hash_value = _HASH
    response = {"data": {"user": {"id": 123, "name": "John Doe"}}}

    from fraiseql.middleware.apq_caching import store_response_in_cache

    store_response_in_cache(hash_value, response, mock_backend, mock_config)

    # Verify response was stored
    cached_response = mock_backend.get_cached_response(hash_value)
    assert cached_response == response


def test_apq_cache_response_storage_disabled(mock_config, mock_backend) -> None:
    """Test that response storage is skipped when caching disabled."""
    hash_value = _HASH
    response = {"data": {"user": {"id": 123}}}

    # Disable caching
    mock_config.apq_cache_responses = False

    from fraiseql.middleware.apq_caching import store_response_in_cache

    store_response_in_cache(hash_value, response, mock_backend, mock_config)

    # Verify response was NOT stored
    cached_response = mock_backend.get_cached_response(hash_value)
    assert cached_response is None


def test_apq_cache_error_responses_not_cached(mock_config, mock_backend) -> None:
    """Test that error responses are not cached."""
    hash_value = _HASH
    error_response = {
        "errors": [{"message": "User not found", "extensions": {"code": "NOT_FOUND"}}]
    }

    from fraiseql.middleware.apq_caching import store_response_in_cache

    store_response_in_cache(hash_value, error_response, mock_backend, mock_config)

    # Verify error response was NOT stored
    cached_response = mock_backend.get_cached_response(hash_value)
    assert cached_response is None


def test_apq_cache_partial_responses_not_cached(mock_config, mock_backend) -> None:
    """Test that responses with errors are not cached."""
    hash_value = _HASH
    partial_response = {
        "data": {"user": {"id": 123, "name": "John"}},
        "errors": [{"message": "Email field access denied"}],
    }

    from fraiseql.middleware.apq_caching import store_response_in_cache

    store_response_in_cache(hash_value, partial_response, mock_backend, mock_config)

    # Verify partial response was NOT stored
    cached_response = mock_backend.get_cached_response(hash_value)
    assert cached_response is None


def test_get_apq_backend_factory_integration(mock_config) -> None:
    """Test integration with backend factory."""
    from fraiseql.middleware.apq_caching import get_apq_backend

    backend = get_apq_backend(mock_config)

    assert isinstance(backend, MemoryAPQBackend)


def test_get_apq_backend_singleton_behavior(mock_config) -> None:
    """Test that get_apq_backend returns singleton instance per config."""
    from fraiseql.middleware.apq_caching import get_apq_backend

    backend1 = get_apq_backend(mock_config)
    backend2 = get_apq_backend(mock_config)

    # Should return the same instance for the same config
    assert backend1 is backend2


def test_apq_cache_with_variables_affects_caching() -> None:
    """Test that request variables affect cache key (future enhancement)."""
    # This test documents expected behavior for variable-aware caching
    # Current implementation caches by query hash only
    # Future versions might include variables in cache key

    config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test", apq_cache_responses=True
    )
    backend = MemoryAPQBackend()

    hash_value = _HASH
    response1 = {"data": {"user": {"id": 1, "name": "Alice"}}}
    response2 = {"data": {"user": {"id": 2, "name": "Bob"}}}

    from fraiseql.middleware.apq_caching import store_response_in_cache

    # Store first response
    store_response_in_cache(hash_value, response1, backend, config)

    # Store second response (should overwrite first for same hash)
    store_response_in_cache(hash_value, response2, backend, config)

    # Should get the second response
    cached = backend.get_cached_response(hash_value)
    assert cached == response2

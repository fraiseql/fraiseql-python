"""End-to-end integration tests for APQ backend abstraction."""

import pytest

from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.middleware.apq_caching import (
    clear_backend_cache,
    get_apq_backend,
    handle_apq_request_with_cache,
    store_response_in_cache,
)
from fraiseql.storage.apq_store import compute_query_hash
from fraiseql.storage.backends.factory import create_apq_backend
from fraiseql.storage.backends.memory import MemoryAPQBackend
from fraiseql.storage.backends.postgresql import PostgreSQLAPQBackend

pytestmark = pytest.mark.integration


class MockRequest:
    """Mock GraphQL request for testing."""

    def __init__(self, extensions=None) -> None:
        self.extensions = extensions or {}


def test_end_to_end_memory_backend() -> None:
    """Test complete APQ flow with memory backend."""
    config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test",
        apq_storage_backend="memory",
        apq_cache_responses=True,
        apq_response_cache_ttl=600,
    )

    # Get backend through factory
    backend = create_apq_backend(config)
    assert isinstance(backend, MemoryAPQBackend)

    # Store a persisted query
    query = "{ users { id name email } }"
    hash_value = compute_query_hash(query)
    backend.store_persisted_query(hash_value, query)

    # Verify query retrieval
    retrieved_query = backend.get_persisted_query(hash_value)
    assert retrieved_query == query

    # Create a mock request
    request = MockRequest({"persistedQuery": {"version": 1, "sha256Hash": hash_value}})

    # Test cache miss (no cached response yet)
    cached_response = handle_apq_request_with_cache(request, backend, config)
    assert cached_response is None

    # Store a response in cache
    response = {
        "data": {
            "users": [
                {"id": 1, "name": "John", "email": "john@example.com"},
                {"id": 2, "name": "Jane", "email": "jane@example.com"},
            ]
        }
    }
    store_response_in_cache(hash_value, response, backend, config)

    # Test cache hit
    cached_response = handle_apq_request_with_cache(request, backend, config)
    assert cached_response == response


def test_end_to_end_postgresql_backend() -> None:
    """Test complete APQ flow with PostgreSQL backend."""
    config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test",
        apq_storage_backend="postgresql",
        apq_cache_responses=True,
        apq_backend_config={
            "table_prefix": "test_apq_",
            "auto_create_tables": False,  # Disable for mock testing
        },
    )

    # Get backend through factory
    backend = create_apq_backend(config)
    assert isinstance(backend, PostgreSQLAPQBackend)
    assert backend._table_prefix == "test_apq_"
    assert backend._queries_table == "test_apq_queries"
    assert backend._responses_table == "test_apq_responses"


def test_backend_singleton_behavior() -> None:
    """Test that get_apq_backend returns same instance for same config."""
    clear_backend_cache()  # Clear any existing cache

    config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test", apq_storage_backend="memory"
    )

    # Get backend twice
    backend1 = get_apq_backend(config)
    backend2 = get_apq_backend(config)

    # Should be the same instance
    assert backend1 is backend2


def test_config_driven_backend_selection() -> None:
    """Test that configuration correctly drives backend selection."""
    # Memory backend
    memory_config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test", apq_storage_backend="memory"
    )
    memory_backend = create_apq_backend(memory_config)
    assert isinstance(memory_backend, MemoryAPQBackend)

    # PostgreSQL backend
    pg_config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test",
        apq_storage_backend="postgresql",
        apq_backend_config={"auto_create_tables": False},
    )
    pg_backend = create_apq_backend(pg_config)
    assert isinstance(pg_backend, PostgreSQLAPQBackend)


def test_caching_behavior_with_config() -> None:
    """Test that caching behavior respects configuration."""
    config_disabled = FraiseQLConfig(
        database_url="postgresql://test@localhost/test",
        apq_storage_backend="memory",
        apq_cache_responses=False,  # Disabled
    )

    config_enabled = FraiseQLConfig(
        database_url="postgresql://test@localhost/test",
        apq_storage_backend="memory",
        apq_cache_responses=True,  # Enabled
    )

    backend = MemoryAPQBackend()
    hash_value = "test_caching_config"
    response = {"data": {"test": True}}

    # Store response
    backend.store_cached_response(hash_value, response)

    # Create mock request
    request = MockRequest({"persistedQuery": {"version": 1, "sha256Hash": hash_value}})

    # With caching disabled, should return None
    result_disabled = handle_apq_request_with_cache(request, backend, config_disabled)
    assert result_disabled is None

    # With caching enabled, should return cached response
    result_enabled = handle_apq_request_with_cache(request, backend, config_enabled)
    assert result_enabled == response


def test_error_handling_integration() -> None:
    """Test error handling across the integration."""
    config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test",
        apq_storage_backend="memory",
        apq_cache_responses=True,
    )

    backend = MemoryAPQBackend()

    # Test with invalid hash
    request_invalid = MockRequest(
        {"persistedQuery": {"version": 1, "sha256Hash": ""}}  # Empty hash
    )

    result = handle_apq_request_with_cache(request_invalid, backend, config)
    assert result is None

    # Test with no extensions
    request_no_ext = MockRequest()
    result = handle_apq_request_with_cache(request_no_ext, backend, config)
    assert result is None

    # Test with no persistedQuery
    request_no_apq = MockRequest({"other": "extension"})
    result = handle_apq_request_with_cache(request_no_apq, backend, config)
    assert result is None


def test_response_storage_conditions() -> None:
    """Test that responses are stored only under correct conditions."""
    config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test",
        apq_storage_backend="memory",
        apq_cache_responses=True,
    )

    backend = MemoryAPQBackend()
    hash_value = "test_storage_conditions"

    # Test that error responses are not cached
    error_response = {"errors": [{"message": "Something went wrong"}]}
    store_response_in_cache(hash_value, error_response, backend, config)
    assert backend.get_cached_response(hash_value) is None

    # Test that partial responses with errors are not cached
    partial_response = {"data": {"users": []}, "errors": [{"message": "Access denied"}]}
    store_response_in_cache(hash_value, partial_response, backend, config)
    assert backend.get_cached_response(hash_value) is None

    # Test that successful responses are cached
    success_response = {"data": {"users": [{"id": 1, "name": "John"}]}}
    store_response_in_cache(hash_value, success_response, backend, config)
    assert backend.get_cached_response(hash_value) == success_response


def test_custom_backend_config() -> None:
    """Test custom backend configuration handling."""
    custom_config = {
        "table_prefix": "custom_apq_",
        "connection_timeout": 60,
        "auto_create_tables": True,
    }

    config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test",
        apq_storage_backend="postgresql",
        apq_backend_config=custom_config,
    )

    backend = create_apq_backend(config)
    assert isinstance(backend, PostgreSQLAPQBackend)
    assert backend._table_prefix == "custom_apq_"
    assert backend._connection_timeout == 60
    assert backend._auto_create_tables is True


def test_backward_compatibility() -> None:
    """Test that existing APQ functionality continues to work."""
    from fraiseql.storage.apq_store import (
        clear_storage,
        get_persisted_query,
        get_storage_stats,
        store_persisted_query,
    )

    # Clear any existing data
    clear_storage()

    # Test original functions still work
    query = "{ backward_compatibility }"
    hash_value = compute_query_hash(query)

    store_persisted_query(hash_value, query)
    retrieved = get_persisted_query(hash_value)
    assert retrieved == query

    # Test stats
    stats = get_storage_stats()
    assert stats["stored_queries"] >= 1

    # Test clearing
    clear_storage()
    assert get_persisted_query(hash_value) is None


def test_comprehensive_flow() -> None:
    """Test the complete APQ flow from request to cached response."""
    # Setup
    config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test",
        apq_storage_backend="memory",
        apq_cache_responses=True,
        apq_response_cache_ttl=300,
    )

    # Step 1: Get backend
    backend = get_apq_backend(config)
    assert isinstance(backend, MemoryAPQBackend)

    # Step 2: Store persisted query (would happen during APQ registration)
    query = "{ users(limit: 10) { id name email roles } }"
    hash_value = compute_query_hash(query)
    backend.store_persisted_query(hash_value, query)

    # Step 3: Create APQ request
    request = MockRequest({"persistedQuery": {"version": 1, "sha256Hash": hash_value}})

    # Step 4: First request - cache miss
    cached_response = handle_apq_request_with_cache(request, backend, config)
    assert cached_response is None  # No cached response yet

    # Step 5: Execute query and get response (this would happen in middleware)
    response = {
        "data": {
            "users": [
                {"id": 1, "name": "John", "email": "john@example.com", "roles": ["user"]},
                {"id": 2, "name": "Jane", "email": "jane@example.com", "roles": ["admin"]},
            ]
        }
    }

    # Step 6: Store response in cache (would happen after execution)
    store_response_in_cache(hash_value, response, backend, config)

    # Step 7: Second request - cache hit
    cached_response = handle_apq_request_with_cache(request, backend, config)
    assert cached_response == response

    # Step 8: Verify direct backend access
    direct_response = backend.get_cached_response(hash_value)
    assert direct_response == response

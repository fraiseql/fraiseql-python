"""Tests for APQ memory storage backend."""

import pytest

from fraiseql.storage.apq_store import compute_query_hash
from fraiseql.storage.backends.base import APQStorageBackend
from fraiseql.storage.backends.memory import MemoryAPQBackend


def test_memory_backend_implements_interface() -> None:
    """Test that MemoryAPQBackend implements APQStorageBackend interface."""
    backend = MemoryAPQBackend()
    assert isinstance(backend, APQStorageBackend)


def test_memory_backend_store_and_retrieve_query() -> None:
    """Test storing and retrieving persisted queries."""
    backend = MemoryAPQBackend()

    query = "{ users { id name } }"
    hash_value = compute_query_hash(query)

    # Initially should return None
    assert backend.get_persisted_query(hash_value) is None

    # Store query
    backend.store_persisted_query(hash_value, query)

    # Should retrieve successfully
    retrieved = backend.get_persisted_query(hash_value)
    assert retrieved == query


def test_memory_backend_store_and_retrieve_cached_response() -> None:
    """Test storing and retrieving cached responses."""
    backend = MemoryAPQBackend()

    hash_value = "test_hash_456"
    response = {"data": {"users": [{"id": 1, "name": "John"}]}}

    # Initially should return None
    assert backend.get_cached_response(hash_value) is None

    # Store response
    backend.store_cached_response(hash_value, response)

    # Should retrieve successfully
    retrieved = backend.get_cached_response(hash_value)
    assert retrieved == response


def test_memory_backend_multiple_queries() -> None:
    """Test storing multiple different queries."""
    backend = MemoryAPQBackend()

    queries = {
        compute_query_hash(query): query
        for query in ("{ users { id } }", "{ posts { title } }", "{ comments { content } }")
    }

    # Store all queries
    for hash_value, query in queries.items():
        backend.store_persisted_query(hash_value, query)

    # Retrieve and verify all queries
    for hash_value, expected_query in queries.items():
        retrieved = backend.get_persisted_query(hash_value)
        assert retrieved == expected_query


def test_memory_backend_multiple_responses() -> None:
    """Test storing multiple different cached responses."""
    backend = MemoryAPQBackend()

    responses = {
        "hash1": {"data": {"users": []}},
        "hash2": {"data": {"posts": [{"title": "Test"}]}},
        "hash3": {"errors": [{"message": "Not found"}]},
    }

    # Store all responses
    for hash_value, response in responses.items():
        backend.store_cached_response(hash_value, response)

    # Retrieve and verify all responses
    for hash_value, expected_response in responses.items():
        retrieved = backend.get_cached_response(hash_value)
        assert retrieved == expected_response


def test_memory_backend_refuses_another_query_under_a_stored_hash() -> None:
    """A stored hash cannot be overwritten with a different query."""
    backend = MemoryAPQBackend()

    query1 = "{ users }"
    query2 = "{ posts }"
    hash_value = compute_query_hash(query1)

    backend.store_persisted_query(hash_value, query1)
    backend.store_persisted_query(hash_value, query1)  # storing it again is fine
    assert backend.get_persisted_query(hash_value) == query1

    with pytest.raises(ValueError, match="does not match"):
        backend.store_persisted_query(hash_value, query2)
    assert backend.get_persisted_query(hash_value) == query1


def test_memory_backend_overwrite_response() -> None:
    """Test overwriting existing cached response."""
    backend = MemoryAPQBackend()

    hash_value = "test_hash_response_overwrite"
    response1 = {"data": {"users": []}}
    response2 = {"data": {"posts": []}}

    # Store first response
    backend.store_cached_response(hash_value, response1)
    assert backend.get_cached_response(hash_value) == response1

    # Overwrite with second response
    backend.store_cached_response(hash_value, response2)
    assert backend.get_cached_response(hash_value) == response2


def test_memory_backend_separate_storages() -> None:
    """Test that query and response storage are separate."""
    backend = MemoryAPQBackend()

    query = "{ users }"
    hash_value = compute_query_hash(query)
    response = {"data": {"posts": []}}

    # Store both with same hash
    backend.store_persisted_query(hash_value, query)
    backend.store_cached_response(hash_value, response)

    # Should retrieve different values
    assert backend.get_persisted_query(hash_value) == query
    assert backend.get_cached_response(hash_value) == response


def test_memory_backend_edge_cases() -> None:
    """Test edge cases for memory backend."""
    backend = MemoryAPQBackend()

    # Empty hash should return None (but not crash)
    assert backend.get_persisted_query("") is None
    assert backend.get_cached_response("") is None

    # Empty values should not crash
    backend.store_persisted_query(compute_query_hash(""), "")
    backend.store_cached_response("test", {})

    assert backend.get_persisted_query(compute_query_hash("")) == ""
    assert backend.get_cached_response("test") == {}


def test_memory_backend_isolation() -> None:
    """Test that different backend instances are isolated."""
    backend1 = MemoryAPQBackend()
    backend2 = MemoryAPQBackend()

    query = "{ users }"
    hash_value = compute_query_hash(query)

    # Store in one instance only
    backend1.store_persisted_query(hash_value, query)

    # The other instance does not see it
    assert backend1.get_persisted_query(hash_value) == query
    assert backend2.get_persisted_query(hash_value) is None


def test_memory_backend_backward_compatibility() -> None:
    """Test backward compatibility with existing apq_store functions."""
    from fraiseql.storage.apq_store import clear_storage, get_persisted_query, store_persisted_query

    # Clear existing storage
    clear_storage()

    # Test that existing functions still work
    query = "{ backward_compatibility }"
    hash_value = compute_query_hash(query)

    store_persisted_query(hash_value, query)
    retrieved = get_persisted_query(hash_value)
    assert retrieved == query

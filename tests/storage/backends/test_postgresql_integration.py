"""Integration tests for PostgreSQL APQ backend.

Note: These tests require a PostgreSQL database and are designed to work
with the existing FraiseQL database connection patterns.
"""

from unittest.mock import Mock, patch

import pytest

from fraiseql.storage.backends.postgresql import PostgreSQLAPQBackend

pytestmark = pytest.mark.integration


@pytest.fixture
def mock_config() -> None:
    """Create a mock PostgreSQL backend config."""
    return {"table_prefix": "test_apq_", "auto_create_tables": True, "connection_timeout": 30}


@pytest.fixture
def mock_db_connection() -> None:
    """Create a mock database connection."""
    return Mock()


def test_postgresql_backend_initialization(mock_config) -> None:
    """Test PostgreSQL backend initialization."""
    backend = PostgreSQLAPQBackend(mock_config)

    assert backend._config == mock_config
    assert backend._table_prefix == "test_apq_"
    assert backend._queries_table == "test_apq_queries"
    assert backend._responses_table == "test_apq_responses"


def test_postgresql_backend_table_creation() -> None:
    """Test that PostgreSQL backend can create required tables."""
    config = {"table_prefix": "apq_", "auto_create_tables": True}
    backend = PostgreSQLAPQBackend(config)

    # This would test actual table creation in a real database
    # For now, we test that the SQL generation works
    create_queries_sql = backend._get_create_queries_table_sql()
    create_responses_sql = backend._get_create_responses_table_sql()

    assert "CREATE TABLE IF NOT EXISTS apq_queries" in create_queries_sql
    assert "CREATE TABLE IF NOT EXISTS apq_responses" in create_responses_sql
    assert "hash VARCHAR(64) PRIMARY KEY" in create_queries_sql
    # Responses table now has composite key for tenant support
    assert "hash VARCHAR(64) NOT NULL" in create_responses_sql
    assert "tenant_id VARCHAR(255)" in create_responses_sql
    # One row per (hash, tenant): a unique index, since a primary key can't hold an expression
    assert "PRIMARY KEY" not in create_responses_sql
    assert "ON apq_responses (hash, COALESCE(tenant_id, ''))" in create_responses_sql


@patch("fraiseql.storage.backends.postgresql.PostgreSQLAPQBackend._execute_query")
def test_postgresql_backend_store_persisted_query(mock_execute, mock_config) -> None:
    """Test storing persisted queries in PostgreSQL."""
    # Disable auto table creation for this test
    mock_config["auto_create_tables"] = False
    backend = PostgreSQLAPQBackend(mock_config)

    hash_value = "abc123hash"
    query = "{ users { id name } }"

    backend.store_persisted_query(hash_value, query)

    # Verify the correct SQL was executed
    mock_execute.assert_called_once()
    args = mock_execute.call_args[0]
    assert "INSERT INTO test_apq_queries" in args[0]
    assert args[1] == (hash_value, query)


@patch("fraiseql.storage.backends.postgresql.PostgreSQLAPQBackend._fetch_one")
def test_postgresql_backend_get_persisted_query(mock_fetch, mock_config) -> None:
    """Test retrieving persisted queries from PostgreSQL."""
    # Disable auto table creation for this test
    mock_config["auto_create_tables"] = False
    backend = PostgreSQLAPQBackend(mock_config)

    hash_value = "abc123hash"
    expected_query = "{ users { id name } }"

    # Mock database response
    mock_fetch.return_value = (expected_query,)

    result = backend.get_persisted_query(hash_value)

    assert result == expected_query
    mock_fetch.assert_called_once()
    args = mock_fetch.call_args[0]
    assert "SELECT query FROM test_apq_queries" in args[0]
    assert args[1] == (hash_value,)


@patch("fraiseql.storage.backends.postgresql.PostgreSQLAPQBackend._fetch_one")
def test_postgresql_backend_get_persisted_query_not_found(mock_fetch, mock_config) -> None:
    """Test retrieving non-existent persisted query."""
    backend = PostgreSQLAPQBackend(mock_config)

    hash_value = "nonexistent"

    # Mock database response - no rows found
    mock_fetch.return_value = None

    result = backend.get_persisted_query(hash_value)

    assert result is None
    mock_fetch.assert_called_once()


@patch("fraiseql.storage.backends.postgresql.PostgreSQLAPQBackend._execute_query")
def test_postgresql_backend_store_cached_response(mock_execute, mock_config) -> None:
    """Test storing cached responses in PostgreSQL."""
    # Disable auto table creation for this test
    mock_config["auto_create_tables"] = False
    backend = PostgreSQLAPQBackend(mock_config)

    hash_value = "abc123hash"
    response = {"data": {"users": [{"id": 1, "name": "John"}]}}

    backend.store_cached_response(hash_value, response)

    # Verify the correct SQL was executed
    mock_execute.assert_called_once()
    args = mock_execute.call_args[0]
    assert "INSERT INTO test_apq_responses" in args[0]
    assert args[1][0] == hash_value  # hash
    assert args[1][1] is None  # tenant_id (None for global)
    assert '"data"' in args[1][2]  # JSON response


@patch("fraiseql.storage.backends.postgresql.PostgreSQLAPQBackend._fetch_one")
def test_postgresql_backend_get_cached_response(mock_fetch, mock_config) -> None:
    """Test retrieving cached responses from PostgreSQL."""
    backend = PostgreSQLAPQBackend(mock_config)

    hash_value = "abc123hash"
    expected_response = {"data": {"users": [{"id": 1, "name": "John"}]}}

    # Mock database response
    import json

    mock_fetch.return_value = (json.dumps(expected_response),)

    result = backend.get_cached_response(hash_value)

    assert result == expected_response
    mock_fetch.assert_called_once()
    args = mock_fetch.call_args[0]
    assert "SELECT response FROM test_apq_responses" in args[0]
    assert args[1] == (hash_value,)


@patch("fraiseql.storage.backends.postgresql.PostgreSQLAPQBackend._fetch_one")
def test_postgresql_backend_get_cached_response_not_found(mock_fetch, mock_config) -> None:
    """Test retrieving non-existent cached response."""
    backend = PostgreSQLAPQBackend(mock_config)

    hash_value = "nonexistent"

    # Mock database response - no rows found
    mock_fetch.return_value = None

    result = backend.get_cached_response(hash_value)

    assert result is None
    mock_fetch.assert_called_once()


def test_postgresql_backend_connection_handling(mock_config) -> None:
    """Test database connection handling."""
    backend = PostgreSQLAPQBackend(mock_config)

    # Test that the backend knows how to get connections
    # This would integrate with FraiseQL's existing database patterns
    assert hasattr(backend, "_get_connection")
    assert callable(backend._get_connection)


def test_postgresql_backend_error_handling(mock_config) -> None:
    """Test error handling in PostgreSQL operations."""
    backend = PostgreSQLAPQBackend(mock_config)

    # Test that database errors are handled gracefully
    with patch.object(backend, "_execute_query", side_effect=Exception("DB Error")):
        # Should not raise - should handle gracefully
        backend.store_persisted_query("hash", "query")
        backend.store_cached_response("hash", {"data": {}})

    with patch.object(backend, "_fetch_one", side_effect=Exception("DB Error")):
        # Should return None on errors
        assert backend.get_persisted_query("hash") is None
        assert backend.get_cached_response("hash") is None


def test_postgresql_backend_json_serialization(mock_config) -> None:
    """Test JSON serialization for cached responses."""
    backend = PostgreSQLAPQBackend(mock_config)

    # Test complex response structures
    complex_response = {
        "data": {
            "users": [
                {"id": 1, "name": "John", "metadata": {"last_login": "2023-01-01"}},
                {"id": 2, "name": "Jane", "metadata": {"last_login": "2023-01-02"}},
            ]
        },
        "extensions": {"timing": {"total": 150}, "complexity": {"score": 45}},
    }

    # Should be able to serialize and deserialize
    import json

    serialized = json.dumps(complex_response)
    deserialized = json.loads(serialized)

    assert deserialized == complex_response

    # Backend should handle this correctly
    with patch.object(backend, "_execute_query") as mock_execute:
        backend.store_cached_response("hash", complex_response)
        # Should have called with JSON string
        args = mock_execute.call_args[0]
        assert args[1][0] == "hash"  # hash
        assert args[1][1] is None  # tenant_id
        assert '"users"' in args[1][2]  # JSON response
        assert '"extensions"' in args[1][2]

"""Tests for APQ bulk query registration."""

import pytest

pytestmark = pytest.mark.integration


class TestRegisterQueries:
    """Tests for register_queries() method on storage backends."""

    def test_register_queries_method_exists_on_base(self) -> None:
        """Test that register_queries is defined on the base class."""
        from fraiseql.storage.backends.base import APQStorageBackend

        assert hasattr(APQStorageBackend, "register_queries")

    def test_memory_backend_register_queries(self) -> None:
        """Test memory backend can register multiple queries at once."""
        from fraiseql.storage.apq_store import compute_query_hash
        from fraiseql.storage.backends.memory import MemoryAPQBackend

        backend = MemoryAPQBackend()

        queries = [
            "query GetUsers { users { id name } }",
            "query GetUser($id: ID!) { user(id: $id) { id name email } }",
            "mutation CreateUser($input: CreateUserInput!) { createUser(input: $input) { id } }",
        ]

        # Register all queries
        result = backend.register_queries(queries)

        # Should return a dict mapping hash -> query
        assert isinstance(result, dict)
        assert len(result) == 3

        # Each query should be retrievable by its hash
        for query in queries:
            expected_hash = compute_query_hash(query)
            assert expected_hash in result
            assert result[expected_hash] == query

            # Should be stored and retrievable
            stored_query = backend.get_persisted_query(expected_hash)
            assert stored_query == query

    def test_memory_backend_register_queries_returns_hashes(self) -> None:
        """Test that register_queries returns the computed hashes."""
        from fraiseql.storage.apq_store import compute_query_hash
        from fraiseql.storage.backends.memory import MemoryAPQBackend

        backend = MemoryAPQBackend()

        query = "{ hello }"
        expected_hash = compute_query_hash(query)

        result = backend.register_queries([query])

        assert expected_hash in result
        assert result[expected_hash] == query

    def test_memory_backend_register_queries_empty_list(self) -> None:
        """Test registering an empty list of queries."""
        from fraiseql.storage.backends.memory import MemoryAPQBackend

        backend = MemoryAPQBackend()

        result = backend.register_queries([])

        assert result == {}

    def test_memory_backend_register_queries_duplicates(self) -> None:
        """Test registering duplicate queries only stores once."""
        from fraiseql.storage.apq_store import compute_query_hash
        from fraiseql.storage.backends.memory import MemoryAPQBackend

        backend = MemoryAPQBackend()

        query = "{ users { id } }"
        queries = [query, query, query]

        result = backend.register_queries(queries)

        # Should only have one entry
        assert len(result) == 1
        assert compute_query_hash(query) in result

    def test_postgresql_backend_has_register_queries(self) -> None:
        """Test PostgreSQL backend inherits register_queries from base."""
        from fraiseql.storage.backends.postgresql import PostgreSQLAPQBackend

        # The method should be inherited from base class
        assert hasattr(PostgreSQLAPQBackend, "register_queries")

    def test_postgresql_backend_register_queries_integration(self, postgres_url) -> None:
        """Test PostgreSQL backend can register multiple queries (integration)."""
        import uuid

        import psycopg

        from fraiseql.storage.apq_store import compute_query_hash
        from fraiseql.storage.backends.postgresql import PostgreSQLAPQBackend

        prefix = f"apq_reg_{uuid.uuid4().hex[:8]}_"
        backend = PostgreSQLAPQBackend({"table_prefix": prefix}, database_url=postgres_url)
        try:
            queries = [
                "query A { a }",
                "query B { b }",
            ]

            result = backend.register_queries(queries)

            assert len(result) == 2
            with psycopg.connect(postgres_url) as conn:
                stored = dict(conn.execute(f"SELECT hash, query FROM {prefix}queries").fetchall())
            for query in queries:
                assert result[compute_query_hash(query)] == query
                assert stored[compute_query_hash(query)] == query
        finally:
            backend.close()
            with psycopg.connect(postgres_url, autocommit=True) as conn:
                conn.execute(f"DROP TABLE IF EXISTS {prefix}queries, {prefix}responses")


class TestRegisterQueriesFromApp:
    """Tests for registering queries through the app/config."""

    def test_apq_backend_has_register_queries(self) -> None:
        """Test that APQ backend factory creates backends with register_queries."""
        from fraiseql.fastapi.config import FraiseQLConfig
        from fraiseql.storage.backends.factory import create_apq_backend

        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            apq_storage_backend="memory",
        )

        backend = create_apq_backend(config)

        assert hasattr(backend, "register_queries")
        assert callable(backend.register_queries)

    def test_register_queries_with_config_context(self) -> None:
        """Test registering queries works with config-created backend."""
        from fraiseql.fastapi.config import FraiseQLConfig
        from fraiseql.storage.apq_store import compute_query_hash
        from fraiseql.storage.backends.factory import create_apq_backend

        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            apq_storage_backend="memory",
        )

        backend = create_apq_backend(config)

        queries = ["{ users { id } }", "{ posts { title } }"]
        result = backend.register_queries(queries)

        assert len(result) == 2

        # Verify queries are stored
        for query in queries:
            hash_val = compute_query_hash(query)
            assert backend.get_persisted_query(hash_val) == query

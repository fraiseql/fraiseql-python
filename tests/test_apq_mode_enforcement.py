"""Tests for APQ mode enforcement in request handling."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fraiseql.storage.apq_store import compute_query_hash

pytestmark = pytest.mark.integration


class TestAPQDisabledMode:
    """Tests for apq_mode='disabled' - APQ extensions ignored."""

    @pytest.mark.asyncio
    async def test_disabled_mode_ignores_apq_extension(self) -> None:
        """Test that disabled mode ignores APQ extensions and requires full query."""
        from fraiseql.fastapi.config import APQMode, FraiseQLConfig
        from fraiseql.fastapi.routers import GraphQLRequest

        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            apq_mode=APQMode.DISABLED,
        )

        # APQ request with hash only - in disabled mode, this should be treated
        # as a regular request (no query), which would fail
        GraphQLRequest(
            extensions={
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": "abc123",
                }
            }
        )

        # APQ mode disabled means processes_apq() returns False
        assert config.apq_mode.processes_apq() is False

    @pytest.mark.asyncio
    async def test_disabled_mode_allows_regular_queries(self) -> None:
        """Test that disabled mode still allows regular queries."""
        from fraiseql.fastapi.config import APQMode, FraiseQLConfig

        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            apq_mode=APQMode.DISABLED,
        )

        # Disabled mode should allow arbitrary queries
        assert config.apq_mode.allows_arbitrary_queries() is True

    @pytest.mark.asyncio
    async def test_disabled_mode_apq_with_query_treated_as_regular(self) -> None:
        """Test APQ request with query is treated as regular query in disabled mode."""
        from fraiseql.fastapi.config import APQMode

        mode = APQMode.DISABLED

        # Even with APQ extensions, disabled mode ignores them
        # The query field should be used directly
        assert mode.processes_apq() is False
        assert mode.allows_arbitrary_queries() is True


class TestAPQRequiredMode:
    """Tests for apq_mode='required' - only persisted queries allowed."""

    @pytest.mark.asyncio
    async def test_required_mode_blocks_arbitrary_queries(self) -> None:
        """Test that required mode blocks arbitrary (non-APQ) queries."""
        from fraiseql.fastapi.config import APQMode, FraiseQLConfig

        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            apq_mode=APQMode.REQUIRED,
        )

        # Required mode should NOT allow arbitrary queries
        assert config.apq_mode.allows_arbitrary_queries() is False

    @pytest.mark.asyncio
    async def test_required_mode_processes_apq(self) -> None:
        """Test that required mode still processes APQ requests."""
        from fraiseql.fastapi.config import APQMode, FraiseQLConfig

        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            apq_mode=APQMode.REQUIRED,
        )

        # Required mode should process APQ
        assert config.apq_mode.processes_apq() is True


class TestAPQOptionalMode:
    """Tests for apq_mode='optional' - default behavior."""

    @pytest.mark.asyncio
    async def test_optional_mode_allows_arbitrary_queries(self) -> None:
        """Test that optional mode allows arbitrary queries."""
        from fraiseql.fastapi.config import APQMode, FraiseQLConfig

        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            apq_mode=APQMode.OPTIONAL,
        )

        assert config.apq_mode.allows_arbitrary_queries() is True

    @pytest.mark.asyncio
    async def test_optional_mode_processes_apq(self) -> None:
        """Test that optional mode processes APQ requests."""
        from fraiseql.fastapi.config import APQMode, FraiseQLConfig

        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            apq_mode=APQMode.OPTIONAL,
        )

        assert config.apq_mode.processes_apq() is True

    @pytest.mark.asyncio
    async def test_optional_mode_is_default(self) -> None:
        """Test that optional is the default mode."""
        from fraiseql.fastapi.config import APQMode, FraiseQLConfig

        config = FraiseQLConfig(database_url="postgresql://localhost/test")

        assert config.apq_mode == APQMode.OPTIONAL


class TestAPQModeMiddlewareHelpers:
    """Tests for APQ mode helper functions in middleware."""

    def test_should_process_apq_request_optional(self) -> None:
        """Test should_process_apq_request with optional mode."""
        from fraiseql.fastapi.config import APQMode
        from fraiseql.middleware.apq import should_process_apq_request

        assert should_process_apq_request(APQMode.OPTIONAL) is True

    def test_should_process_apq_request_required(self) -> None:
        """Test should_process_apq_request with required mode."""
        from fraiseql.fastapi.config import APQMode
        from fraiseql.middleware.apq import should_process_apq_request

        assert should_process_apq_request(APQMode.REQUIRED) is True

    def test_should_process_apq_request_disabled(self) -> None:
        """Test should_process_apq_request with disabled mode."""
        from fraiseql.fastapi.config import APQMode
        from fraiseql.middleware.apq import should_process_apq_request

        assert should_process_apq_request(APQMode.DISABLED) is False

    def test_create_arbitrary_query_rejected_error(self) -> None:
        """Test error response for rejected arbitrary queries."""
        from fraiseql.middleware.apq import create_arbitrary_query_rejected_error

        error = create_arbitrary_query_rejected_error()

        assert "errors" in error
        assert error["errors"][0]["extensions"]["code"] == "ARBITRARY_QUERY_NOT_ALLOWED"
        assert "persisted queries" in error["errors"][0]["message"].lower()


class TestAPQModeRouterIntegration:
    """Integration tests for APQ mode enforcement in the GraphQL router.

    These tests use mocking to bypass DB dependencies since we're testing
    the APQ mode enforcement logic, not the actual query execution.
    """

    @pytest.fixture
    def noop_lifespan(self):
        """No-op lifespan for tests that don't need a database."""
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _noop_lifespan(app: FastAPI):
            yield

        return _noop_lifespan

    @pytest.fixture
    def hello_query(self, clear_registry):
        """Create a simple hello query function."""
        import fraiseql

        @fraiseql.query
        def hello(info, name: str = "World") -> str:
            """Simple hello query."""
            return f"Hello, {name}!"

        return hello

    @pytest.fixture
    def app_required_mode(self, noop_lifespan, hello_query, clear_registry):
        """Create a FastAPI app with apq_mode='required'."""
        from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app
        from fraiseql.fastapi.config import APQMode

        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            apq_mode=APQMode.REQUIRED,
            auth_enabled=False,
        )

        return create_fraiseql_app(config=config, queries=[hello_query], lifespan=noop_lifespan)

    @pytest.fixture
    def app_disabled_mode(self, noop_lifespan, hello_query, clear_registry):
        """Create a FastAPI app with apq_mode='disabled'."""
        from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app
        from fraiseql.fastapi.config import APQMode

        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            apq_mode=APQMode.DISABLED,
            auth_enabled=False,
        )

        return create_fraiseql_app(config=config, queries=[hello_query], lifespan=noop_lifespan)

    @pytest.fixture
    def app_optional_mode(self, noop_lifespan, hello_query, clear_registry):
        """Create a FastAPI app with apq_mode='optional' (default)."""
        from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app
        from fraiseql.fastapi.config import APQMode

        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            apq_mode=APQMode.OPTIONAL,
            auth_enabled=False,
        )

        return create_fraiseql_app(config=config, queries=[hello_query], lifespan=noop_lifespan)

    def test_required_mode_rejects_arbitrary_query(self, app_required_mode) -> None:
        """Test that required mode rejects arbitrary queries."""
        # Mock the DB pool to avoid DB initialization errors
        with patch("fraiseql.fastapi.dependencies.get_db_pool") as mock_pool:
            mock_pool.return_value = MagicMock()

            with TestClient(app_required_mode) as client:
                response = client.post(
                    "/graphql",
                    json={"query": "{ hello }"},
                )

            assert response.status_code == 200
            data = response.json()
            assert "errors" in data
            assert data["errors"][0]["extensions"]["code"] == "ARBITRARY_QUERY_NOT_ALLOWED"

    def test_required_mode_accepts_apq_request(self, app_required_mode) -> None:
        """Test that required mode accepts APQ requests (doesn't reject as arbitrary)."""
        from fraiseql.storage.apq_store import clear_storage, store_persisted_query

        clear_storage()
        query = "{ hello }"
        hash_value = compute_query_hash(query)
        store_persisted_query(hash_value, query)

        with patch("fraiseql.fastapi.dependencies.get_db_pool") as mock_pool:
            mock_pool.return_value = MagicMock()

            with TestClient(app_required_mode) as client:
                response = client.post(
                    "/graphql",
                    json={
                        "extensions": {
                            "persistedQuery": {
                                "version": 1,
                                "sha256Hash": hash_value,
                            }
                        }
                    },
                )

            # Should not be rejected as arbitrary query
            data = response.json()
            if "errors" in data:
                assert data["errors"][0]["extensions"]["code"] != "ARBITRARY_QUERY_NOT_ALLOWED"

    def test_disabled_mode_accepts_arbitrary_query(self, app_disabled_mode) -> None:
        """Test that disabled mode accepts arbitrary queries."""
        with patch("fraiseql.fastapi.dependencies.get_db_pool") as mock_pool:
            mock_pool.return_value = MagicMock()

            with TestClient(app_disabled_mode) as client:
                response = client.post(
                    "/graphql",
                    json={"query": "{ hello }"},
                )

            # Should not be rejected - disabled mode allows arbitrary queries
            data = response.json()
            # Check it's not the APQ rejection error
            if "errors" in data:
                assert data["errors"][0]["extensions"].get("code") != "ARBITRARY_QUERY_NOT_ALLOWED"

    def test_disabled_mode_ignores_apq_extensions(self, app_disabled_mode) -> None:
        """Test that disabled mode ignores APQ extensions (requires query)."""
        with patch("fraiseql.fastapi.dependencies.get_db_pool") as mock_pool:
            mock_pool.return_value = MagicMock()

            with TestClient(app_disabled_mode) as client:
                # APQ hash-only request should fail because query is required
                # (APQ processing is disabled, so hash lookup won't happen)
                response = client.post(
                    "/graphql",
                    json={
                        "extensions": {
                            "persistedQuery": {
                                "version": 1,
                                "sha256Hash": "some_hash",
                            }
                        }
                    },
                )

            # Should fail because no query is provided and APQ is disabled
            data = response.json()
            # Either validation error (no query) or normal GraphQL error, but NOT APQ error
            assert "errors" in data or response.status_code == 422

    def test_optional_mode_accepts_arbitrary_query(self, app_optional_mode) -> None:
        """Test that optional mode accepts arbitrary queries."""
        with patch("fraiseql.fastapi.dependencies.get_db_pool") as mock_pool:
            mock_pool.return_value = MagicMock()

            with TestClient(app_optional_mode) as client:
                response = client.post(
                    "/graphql",
                    json={"query": "{ hello }"},
                )

            # Should not be rejected
            data = response.json()
            if "errors" in data:
                assert data["errors"][0]["extensions"].get("code") != "ARBITRARY_QUERY_NOT_ALLOWED"

    def test_optional_mode_accepts_apq_request(self, app_optional_mode) -> None:
        """Test that optional mode accepts APQ requests."""
        from fraiseql.storage.apq_store import clear_storage, store_persisted_query

        clear_storage()
        query = "{ hello }"
        hash_value = compute_query_hash(query)
        store_persisted_query(hash_value, query)

        with patch("fraiseql.fastapi.dependencies.get_db_pool") as mock_pool:
            mock_pool.return_value = MagicMock()

            with TestClient(app_optional_mode) as client:
                response = client.post(
                    "/graphql",
                    json={
                        "extensions": {
                            "persistedQuery": {
                                "version": 1,
                                "sha256Hash": hash_value,
                            }
                        }
                    },
                )

            # Should work - APQ is processed in optional mode
            data = response.json()
            if "errors" in data:
                assert data["errors"][0]["extensions"]["code"] != "ARBITRARY_QUERY_NOT_ALLOWED"

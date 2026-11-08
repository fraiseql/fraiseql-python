"""Test CORS configuration defaults and behavior."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from fraiseql.fastapi.config import FraiseQLConfig

pytestmark = pytest.mark.integration


@pytest.mark.unit
class TestCORSDefaults:
    """Test CORS default configuration values."""

    def test_cors_disabled_by_default(self) -> None:
        """Test that CORS is disabled by default."""
        config = FraiseQLConfig(database_url="postgresql://localhost/test")
        assert config.cors_enabled is False

    def test_cors_origins_empty_by_default(self) -> None:
        """Test that CORS origins list is empty by default."""
        config = FraiseQLConfig(database_url="postgresql://localhost/test")
        assert config.cors_origins == []

    def test_cors_methods_sensible_defaults(self) -> None:
        """Test that CORS methods have sensible defaults when enabled."""
        config = FraiseQLConfig(database_url="postgresql://localhost/test")
        assert config.cors_methods == ["GET", "POST"]

    def test_cors_headers_sensible_defaults(self) -> None:
        """Test that CORS headers have sensible defaults when enabled."""
        config = FraiseQLConfig(database_url="postgresql://localhost/test")
        assert config.cors_headers == ["Content-Type", "Authorization"]


class TestCORSEnvironmentBehavior:
    """Test CORS behavior based on environment."""

    def test_cors_remains_disabled_in_development(self) -> None:
        """Test that CORS remains disabled in development unless explicitly enabled."""
        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            environment="development",
        )
        assert config.cors_enabled is False

    def test_cors_remains_disabled_in_production(self) -> None:
        """Test that CORS remains disabled in production unless explicitly enabled."""
        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            environment="production",
        )
        assert config.cors_enabled is False

    def test_cors_can_be_explicitly_enabled(self) -> None:
        """Test that CORS can be explicitly enabled when needed."""
        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            cors_enabled=True,
            cors_origins=["https://example.com"],
        )
        assert config.cors_enabled is True
        assert config.cors_origins == ["https://example.com"]


class TestCORSProductionWarnings:
    """Test warnings for insecure CORS configurations in production."""

    def test_wildcard_cors_warning_in_production(self, caplog) -> None:
        """Test that enabling wildcard CORS in production logs a warning."""
        with caplog.at_level(logging.WARNING):
            config = FraiseQLConfig(
                database_url="postgresql://localhost/test",
                environment="production",
                cors_enabled=True,
                cors_origins=["*"],
            )
            # Trigger validation
            assert config.cors_enabled is True
            assert config.cors_origins == ["*"]

        # Check for warning about wildcard CORS in production
        warning_logged = any(
            "wildcard" in record.message.lower() and "production" in record.message.lower()
            for record in caplog.records
        )
        assert warning_logged, "Should warn about wildcard CORS in production"

    def test_no_warning_for_specific_origins_in_production(self, caplog) -> None:
        """Test that specific origins in production don't trigger warnings."""
        with caplog.at_level(logging.WARNING):
            config = FraiseQLConfig(
                database_url="postgresql://localhost/test",
                environment="production",
                cors_enabled=True,
                cors_origins=["https://app.example.com", "https://admin.example.com"],
            )
            assert config.cors_enabled is True

        # Should not have CORS-related warnings
        cors_warnings = [r for r in caplog.records if "cors" in r.message.lower()]
        assert len(cors_warnings) == 0

    def test_no_warning_when_cors_disabled_in_production(self, caplog) -> None:
        """Test that no warning is logged when CORS is disabled in production."""
        with caplog.at_level(logging.WARNING):
            config = FraiseQLConfig(
                database_url="postgresql://localhost/test",
                environment="production",
                cors_enabled=False,
            )
            assert config.cors_enabled is False

        # Should not have any CORS warnings
        cors_warnings = [r for r in caplog.records if "cors" in r.message.lower()]
        assert len(cors_warnings) == 0


@pytest.mark.usefixtures("clear_registry")
class TestCORSIntegration:
    """Test CORS integration with FastAPI app."""

    @pytest.fixture
    def mock_db_pool(self) -> None:
        """Mock database pool for testing."""
        pool = MagicMock()
        pool.open = MagicMock(return_value=None)
        pool.close = MagicMock(return_value=None)
        return pool

    def test_cors_middleware_not_added_when_disabled(self, mock_db_pool) -> None:
        """Test that CORS middleware is not added when CORS is disabled."""
        from fraiseql import query
        from fraiseql.fastapi import create_fraiseql_app

        # Create a minimal query for schema to be valid
        @query
        async def hello() -> str:
            return "Hello World"

        with patch("fraiseql.fastapi.app.create_db_pool", return_value=mock_db_pool):
            config = FraiseQLConfig(
                database_url="postgresql://localhost/test",
                cors_enabled=False,
            )

            app = create_fraiseql_app(config=config, queries=[hello])

            # Check that CORSMiddleware is not in the middleware stack
            # FastAPI stores middleware in app.user_middleware
            cors_middleware_found = any(
                middleware.cls.__name__ == "CORSMiddleware" for middleware in app.user_middleware
            )
            assert not cors_middleware_found

    def test_cors_middleware_added_when_enabled(self, mock_db_pool) -> None:
        """Test that CORS middleware is added when CORS is enabled."""
        from fraiseql import query
        from fraiseql.fastapi import create_fraiseql_app

        # Create a minimal query for schema to be valid
        @query
        async def hello() -> str:
            return "Hello World"

        with patch("fraiseql.fastapi.app.create_db_pool", return_value=mock_db_pool):
            config = FraiseQLConfig(
                database_url="postgresql://localhost/test",
                cors_enabled=True,
                cors_origins=["https://example.com"],
            )

            app = create_fraiseql_app(config=config, queries=[hello])

            # Check that CORSMiddleware is in the middleware stack
            # FastAPI stores middleware in app.user_middleware
            cors_middleware_found = any(
                middleware.cls.__name__ == "CORSMiddleware" for middleware in app.user_middleware
            )
            assert cors_middleware_found

    def test_cors_headers_not_present_when_disabled(self, mock_db_pool) -> None:
        """Test that CORS headers are not added when CORS is disabled."""
        from fraiseql import query
        from fraiseql.fastapi import create_fraiseql_app

        # Create a minimal query for schema to be valid
        @query
        async def hello() -> str:
            return "Hello World"

        with patch("fraiseql.fastapi.app.create_db_pool", return_value=mock_db_pool):
            config = FraiseQLConfig(
                database_url="postgresql://localhost/test",
                cors_enabled=False,
            )

            app = create_fraiseql_app(config=config, queries=[hello])
            client = TestClient(app)

            # Make a request with Origin header
            response = client.options(
                "/graphql",
                headers={"Origin": "https://example.com"},
            )

            # CORS headers should not be present
            assert "Access-Control-Allow-Origin" not in response.headers
            assert "Access-Control-Allow-Methods" not in response.headers


class TestCORSValidation:
    """Test CORS configuration validation."""

    def test_empty_origins_with_cors_enabled_is_valid(self) -> None:
        """Test that enabling CORS with empty origins is valid (blocks all cross-origin)."""
        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            cors_enabled=True,
            cors_origins=[],
        )
        assert config.cors_enabled is True
        assert config.cors_origins == []

    def test_cors_validator_warns_on_wildcard_in_production(self, caplog) -> None:
        """Test that validator warns about wildcard CORS in production."""
        with caplog.at_level(logging.WARNING):
            config = FraiseQLConfig(
                database_url="postgresql://localhost/test",
                environment="production",
                cors_enabled=True,
                cors_origins=["*"],
            )

            # Verify the config was created with the expected values
            assert config.cors_enabled is True
            assert config.cors_origins == ["*"]

        # Look for warning - the validator should have logged during initialization
        has_warning = any(
            ("wildcard" in r.message.lower() or "*" in r.message)
            and "production" in r.message.lower()
            for r in caplog.records
        )
        messages = [r.message for r in caplog.records]
        assert has_warning, f"Expected warning about wildcard CORS in production. Got: {messages}"

"""Integration tests for Rust database pool.

Tests the Python wrapper around the Rust DatabasePool implementation.
Phase 1: Basic validation and configuration tests.
"""

import pytest

from fraiseql.core.database import DatabasePool


class TestDatabasePoolInitialization:
    """Test database pool initialization and configuration."""

    def test_pool_initialization_with_valid_url(self):
        """Test that pool initializes with a valid PostgreSQL URL."""
        # Phase 1: Validation only, no actual connection
        pool = DatabasePool("postgresql://user:pass@localhost:5432/test")
        assert pool is not None
        assert isinstance(pool, DatabasePool)

    def test_pool_initialization_with_invalid_url_format(self):
        """Test that pool rejects invalid URL formats."""
        with pytest.raises(Exception) as exc_info:
            DatabasePool("invalid://not-a-postgres-url")

        # Should raise error about invalid PostgreSQL URL
        assert "Invalid PostgreSQL URL" in str(exc_info.value)

    def test_pool_initialization_with_missing_components(self):
        """Test that pool rejects URLs missing required components."""
        with pytest.raises(Exception) as exc_info:
            DatabasePool("postgresql://localhost")

        # Should raise error about URL structure
        assert "Invalid PostgreSQL URL structure" in str(exc_info.value)


class TestDatabasePoolConfiguration:
    """Test pool configuration and statistics."""

    def test_pool_default_configuration(self):
        """Test that pool uses default configuration values."""
        pool = DatabasePool("postgresql://user:pass@localhost:5432/test")

        config_summary = pool.get_config_summary()

        # Default values from Phase 1 plan: max_size=10, min_idle=1
        assert "max_size=10" in config_summary
        assert "min_idle=1" in config_summary

    def test_pool_stats_format(self):
        """Test that pool stats return expected format."""
        pool = DatabasePool("postgresql://user:pass@localhost:5432/test")

        stats = pool.get_stats()

        # Phase 1: Mock statistics (no real connections)
        assert "connections" in stats.lower()
        assert "idle" in stats.lower()

        # Phase 1 expectation: 0 connections (validation only)
        assert "0 connections" in stats

    def test_pool_repr(self):
        """Test pool string representation."""
        pool = DatabasePool("postgresql://user:pass@localhost:5432/test")

        repr_str = repr(pool)

        assert "DatabasePool" in repr_str
        assert "max_size" in repr_str


class TestDatabasePoolValidation:
    """Test URL validation and parsing."""

    def test_pool_validates_postgresql_prefix(self):
        """Test that only postgresql:// URLs are accepted."""
        # Valid
        pool = DatabasePool("postgresql://user:pass@localhost:5432/db")
        assert pool is not None

        # Invalid - wrong protocol
        with pytest.raises(Exception):
            DatabasePool("mysql://user:pass@localhost:5432/db")

    def test_pool_validates_url_structure(self):
        """Test that URL must contain @ and / characters."""
        # Valid structure: user@host/db
        pool = DatabasePool("postgresql://user:pass@localhost/db")
        assert pool is not None

        # Invalid - missing @
        with pytest.raises(Exception) as exc_info:
            DatabasePool("postgresql://localhost/db")
        assert "structure" in str(exc_info.value).lower()


class TestDatabasePoolPhase1Scope:
    """Test Phase 1 scope and limitations."""

    def test_pool_is_validation_only(self):
        """Test that Phase 1 pool is validation-only (no real connections)."""
        pool = DatabasePool("postgresql://user:pass@localhost:5432/test")

        # Phase 1: Stats should show 0 connections (no actual pool)
        stats = pool.get_stats()
        assert "0 connections" in stats
        assert "0 idle" in stats

    def test_pool_accepts_valid_connection_string(self):
        """Test various valid PostgreSQL connection string formats."""
        # Format 1: Full URL with port
        pool1 = DatabasePool("postgresql://user:pass@localhost:5432/db")
        assert pool1 is not None

        # Format 2: URL without explicit port (uses default)
        pool2 = DatabasePool("postgresql://user:pass@localhost/db")
        assert pool2 is not None

        # Format 3: URL with special characters in password
        pool3 = DatabasePool("postgresql://user:p%40ss@localhost/db")
        assert pool3 is not None


# Phase 1 Note: Async tests and real connection tests will be added in Phase 2
# when actual connection pool functionality is implemented.
#
# Skipped for Phase 1:
# - test_pool_acquire_connection() - requires async support (Phase 2)
# - test_pool_health_check() - requires real connections (Phase 2)
# - test_pool_connection_lifecycle() - requires real connections (Phase 2)
# - test_pool_concurrent_access() - requires real connections (Phase 2)

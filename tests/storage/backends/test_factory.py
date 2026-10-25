"""Tests for APQ backend factory."""

import pytest

from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.storage.backends.base import APQStorageBackend
from fraiseql.storage.backends.factory import create_apq_backend
from fraiseql.storage.backends.memory import MemoryAPQBackend

pytestmark = pytest.mark.integration


def test_factory_creates_memory_backend() -> None:
    """Test that factory creates memory backend for memory config."""
    config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test", apq_storage_backend="memory"
    )

    backend = create_apq_backend(config)

    assert isinstance(backend, MemoryAPQBackend)
    assert isinstance(backend, APQStorageBackend)


def test_factory_creates_memory_backend_by_default() -> None:
    """Test that factory creates memory backend by default."""
    config = FraiseQLConfig(database_url="postgresql://test@localhost/test")

    backend = create_apq_backend(config)

    assert isinstance(backend, MemoryAPQBackend)
    assert config.apq_storage_backend == "memory"


def test_factory_creates_postgresql_backend() -> None:
    """Test that factory creates PostgreSQL backend for postgresql config."""
    config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test",
        apq_storage_backend="postgresql",
        apq_backend_config={"table_prefix": "apq_", "pool_size": 10},
    )

    backend = create_apq_backend(config)

    # Import here to avoid circular imports
    from fraiseql.storage.backends.postgresql import PostgreSQLAPQBackend

    assert isinstance(backend, PostgreSQLAPQBackend)
    assert isinstance(backend, APQStorageBackend)


def test_factory_creates_custom_backend() -> None:
    """Test that factory creates custom backend from class path."""

    # Create a mock custom backend class for testing
    class MockCustomBackend(APQStorageBackend):
        def __init__(self, config_dict) -> None:
            self.config = config_dict

        def get_persisted_query(self, hash_value: str) -> None:
            return None

        def store_persisted_query(self, hash_value: str, query: str) -> None:
            pass

        def get_cached_response(self, hash_value: str) -> None:
            return None

        def store_cached_response(self, hash_value: str, response) -> None:
            pass

    # Temporarily add the class to the test module's globals
    import sys

    current_module = sys.modules[__name__]
    current_module.MockCustomBackend = MockCustomBackend

    config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test",
        apq_storage_backend="custom",
        apq_backend_config={
            "backend_class": f"{__name__}.MockCustomBackend",
            "custom_setting": "test_value",
        },
    )

    backend = create_apq_backend(config)

    assert isinstance(backend, MockCustomBackend)
    assert isinstance(backend, APQStorageBackend)
    assert backend.config["custom_setting"] == "test_value"


def test_factory_raises_error_for_unknown_backend() -> None:
    """Test that factory raises error for unknown backend type."""
    config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test", apq_storage_backend="memory"
    )

    # Use object.__setattr__ to bypass Pydantic validation and test error handling
    object.__setattr__(config, "apq_storage_backend", "unknown")

    with pytest.raises(ValueError, match="Unknown APQ backend: unknown"):
        create_apq_backend(config)


def test_factory_raises_error_for_invalid_custom_class() -> None:
    """Test that factory raises error for invalid custom backend class."""
    config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test",
        apq_storage_backend="custom",
        apq_backend_config={"backend_class": "nonexistent.module.NonexistentClass"},
    )

    with pytest.raises((ImportError, AttributeError)):
        create_apq_backend(config)


def test_factory_raises_error_for_missing_custom_class() -> None:
    """Test that factory raises error when custom backend class is not specified."""
    config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test",
        apq_storage_backend="custom",
        apq_backend_config={},  # Missing backend_class
    )

    with pytest.raises(ValueError, match="backend_class is required for custom backend"):
        create_apq_backend(config)


def test_factory_passes_config_to_backends() -> None:
    """Test that factory passes configuration to backend constructors."""
    backend_config = {"test_setting": "test_value", "number_setting": 42}

    config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test",
        apq_storage_backend="postgresql",
        apq_backend_config=backend_config,
    )

    backend = create_apq_backend(config)

    # The backend should have received the config
    # This test will need to be updated when we implement the actual PostgreSQL backend
    assert hasattr(backend, "_config") or hasattr(backend, "config")


def test_factory_singleton_behavior() -> None:
    """Test that factory can create multiple independent backend instances."""
    config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test", apq_storage_backend="memory"
    )

    backend1 = create_apq_backend(config)
    backend2 = create_apq_backend(config)

    # Should create separate instances
    assert backend1 is not backend2
    assert type(backend1) is type(backend2)


def test_factory_with_cache_enabled() -> None:
    """Test factory with response caching enabled."""
    config = FraiseQLConfig(
        database_url="postgresql://test@localhost/test",
        apq_storage_backend="memory",
        apq_cache_responses=True,
        apq_response_cache_ttl=1800,
    )

    backend = create_apq_backend(config)

    assert isinstance(backend, MemoryAPQBackend)
    # The backend itself doesn't need to know about caching settings
    # Those are handled at the middleware level


# Custom backends for the tests below; importable as f"{__name__}.<name>".
class SubclassedMemoryBackend(MemoryAPQBackend):
    """A custom backend that keeps MemoryAPQBackend's __init__."""


class ConfigAndTTLBackend(MemoryAPQBackend):
    """A custom backend whose __init__ takes the config dict and the TTL."""

    def __init__(self, config: dict, response_ttl: int | None = None) -> None:
        super().__init__(response_ttl=response_ttl)
        self.config = config


class NoArgumentBackend(MemoryAPQBackend):
    """A custom backend whose __init__ takes nothing."""

    def __init__(self) -> None:
        super().__init__()


def _custom_config(class_name: str, **kwargs) -> FraiseQLConfig:
    return FraiseQLConfig(
        database_url="postgresql://test@localhost/test",
        apq_storage_backend="custom",
        apq_backend_config={"backend_class": f"{__name__}.{class_name}", "setting": "x"},
        **kwargs,
    )


def test_custom_memory_subclass_gets_the_response_ttl_not_the_config_dict() -> None:
    config = _custom_config("SubclassedMemoryBackend", apq_response_cache_ttl=120)

    backend = create_apq_backend(config)

    assert isinstance(backend, SubclassedMemoryBackend)
    assert backend._response_ttl == 120
    backend.store_cached_response("h", {"data": {"ok": True}})
    assert backend.get_cached_response("h") == {"data": {"ok": True}}


def test_custom_backend_taking_config_and_response_ttl_gets_both() -> None:
    backend = create_apq_backend(_custom_config("ConfigAndTTLBackend", apq_response_cache_ttl=90))

    assert isinstance(backend, ConfigAndTTLBackend)
    assert backend.config["setting"] == "x"
    assert backend._response_ttl == 90


def test_custom_backend_taking_no_arguments_is_created() -> None:
    backend = create_apq_backend(_custom_config("NoArgumentBackend"))

    assert isinstance(backend, NoArgumentBackend)


def test_custom_postgresql_subclass_gets_config_database_url_and_ttl() -> None:
    import sys

    from fraiseql.storage.backends.postgresql import PostgreSQLAPQBackend

    class SubclassedPostgreSQLBackend(PostgreSQLAPQBackend):
        pass

    sys.modules[__name__].SubclassedPostgreSQLBackend = SubclassedPostgreSQLBackend  # type: ignore[attr-defined]

    config = _custom_config("SubclassedPostgreSQLBackend", apq_response_cache_ttl=45)
    backend = create_apq_backend(config)

    assert isinstance(backend, SubclassedPostgreSQLBackend)
    assert backend._config["setting"] == "x"
    assert backend._database_url == "postgresql://test@localhost/test"
    assert backend._response_ttl == 45

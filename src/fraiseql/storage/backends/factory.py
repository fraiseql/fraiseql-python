"""APQ storage backend factory for FraiseQL."""

import importlib
import inspect
import logging
from typing import Any

from fraiseql.fastapi.config import FraiseQLConfig

from .base import APQStorageBackend
from .memory import MemoryAPQBackend

logger = logging.getLogger(__name__)


def create_apq_backend(config: FraiseQLConfig) -> APQStorageBackend:
    """Create an APQ storage backend based on configuration.

    Args:
        config: FraiseQL configuration containing backend settings

    Returns:
        APQ storage backend instance

    Raises:
        ValueError: If backend type is unknown or configuration is invalid
        ImportError: If custom backend class cannot be imported
    """
    backend_type = config.apq_storage_backend
    backend_config = config.apq_backend_config

    logger.debug(f"Creating APQ backend: type={backend_type}")

    if backend_type == "memory":
        return MemoryAPQBackend(response_ttl=config.apq_response_cache_ttl)

    if backend_type == "postgresql":
        from .postgresql import PostgreSQLAPQBackend

        return PostgreSQLAPQBackend(
            backend_config,
            database_url=config.database_url,
            response_ttl=config.apq_response_cache_ttl,
        )

    if backend_type == "custom":
        return _create_custom_backend(
            backend_config,
            response_ttl=config.apq_response_cache_ttl,
            database_url=config.database_url,
        )

    raise ValueError(f"Unknown APQ backend: {backend_type}")


def _constructor_arguments(
    backend_class: type, backend_config: dict[str, Any], settings: dict[str, Any]
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """The arguments to construct ``backend_class`` with.

    ``backend_config`` goes first, as the documented interface has it, unless the
    constructor takes no positional argument for it: a constructor whose first
    parameter is one of ``settings`` (a ``MemoryAPQBackend`` subclass keeping its
    ``__init__(response_ttl=None)``), or none at all. Each of ``settings`` whose name the
    constructor has as a parameter is passed by keyword; ``**kwargs`` doesn't count, so
    a constructor forwarding its keywords elsewhere gets none it didn't ask for.
    """
    try:
        parameters = list(inspect.signature(backend_class).parameters.values())
    except (TypeError, ValueError):
        return (backend_config,), {}

    positional = [
        p
        for p in parameters
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    takes_config = any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in parameters) or bool(
        positional and positional[0].name not in settings
    )
    keywords = {
        p.name: settings[p.name]
        for p in parameters
        if p.name in settings
        and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return ((backend_config,) if takes_config else ()), keywords


def _create_custom_backend(
    backend_config: dict[str, Any],
    *,
    response_ttl: int | None = None,
    database_url: str | None = None,
) -> APQStorageBackend:
    """Create a custom APQ backend from configuration.

    The backend class gets ``backend_config`` as its first argument, and
    ``response_ttl`` / ``database_url`` by keyword if its constructor has a parameter
    of that name (see ``_constructor_arguments``).

    Args:
        backend_config: Configuration dict containing backend_class and other settings
        response_ttl: ``apq_response_cache_ttl`` of the app's config
        database_url: ``database_url`` of the app's config

    Returns:
        Custom APQ storage backend instance

    Raises:
        ValueError: If backend_class is not specified
        ImportError: If backend class cannot be imported
        AttributeError: If backend class doesn't exist in module
    """
    if "backend_class" not in backend_config:
        raise ValueError("backend_class is required for custom backend")

    backend_class_path = backend_config["backend_class"]
    logger.debug(f"Importing custom backend class: {backend_class_path}")

    # Split module and class name
    try:
        module_path, class_name = backend_class_path.rsplit(".", 1)
    except ValueError as e:
        raise ValueError(f"Invalid backend_class format: {backend_class_path}") from e

    # Import the module
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise ImportError(f"Cannot import module '{module_path}': {e}") from e

    # Get the class from the module
    try:
        backend_class = getattr(module, class_name)
    except AttributeError as e:
        raise AttributeError(
            f"Class '{class_name}' not found in module '{module_path}': {e}"
        ) from e

    # Create and return the backend instance
    args, kwargs = _constructor_arguments(
        backend_class,
        backend_config,
        {"response_ttl": response_ttl, "database_url": database_url},
    )
    try:
        backend = backend_class(*args, **kwargs)
        logger.debug(f"Created custom backend: {backend_class}")
        return backend
    except Exception as e:
        raise ValueError(f"Failed to instantiate custom backend '{backend_class_path}': {e}") from e


def get_backend_info(backend: APQStorageBackend) -> dict[str, Any]:
    """Get information about a backend instance.

    Args:
        backend: APQ storage backend instance

    Returns:
        Dictionary with backend information
    """
    return {
        "type": type(backend).__name__,
        "module": type(backend).__module__,
        "supports_caching": hasattr(backend, "get_cached_response"),
        "supports_queries": hasattr(backend, "get_persisted_query"),
    }

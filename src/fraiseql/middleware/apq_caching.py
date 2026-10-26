"""APQ cached response middleware for FraiseQL.

This module provides response caching functionality for APQ queries,
enabling direct JSON passthrough to bypass GraphQL execution for
pre-computed responses.
"""

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any, Optional, TypeVar

from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.fastapi.routers import GraphQLRequest
from fraiseql.middleware.apq_selection import (
    extract_fragments,
    extract_selection_set,
    filter_response_by_selection,
)
from fraiseql.monitoring import get_global_metrics
from fraiseql.storage.backends.base import APQStorageBackend
from fraiseql.storage.backends.factory import create_apq_backend

logger = logging.getLogger(__name__)

# Global backend cache to avoid recreating backends
_backend_cache: dict[str, APQStorageBackend] = {}

_T = TypeVar("_T")


async def call_backend(
    backend: APQStorageBackend | None, fn: Callable[..., _T], /, *args: Any, **kwargs: Any
) -> _T:
    """Call ``fn`` (a synchronous call that uses ``backend``) from async code.

    When the backend does blocking I/O (``backend.blocking_io``, as the ``postgresql``
    backend does), ``fn`` runs in a worker thread so the event loop keeps serving other
    requests during the lookup; otherwise it runs inline.
    """
    if backend is not None and getattr(backend, "blocking_io", False):
        return await asyncio.to_thread(fn, *args, **kwargs)
    return fn(*args, **kwargs)


def compute_response_cache_key(
    query_hash: str,
    variables: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> str:
    """Compute cache key that includes query hash, variables and the user.

    This ensures different variable values, and different users, produce different
    cache entries, preventing data leakage between requests. (The tenant is added by
    the backend, from the request context.)

    Args:
        query_hash: SHA256 hash of the persisted query
        variables: GraphQL variables from the request
        user_id: Authenticated user's id (see ``response_cache_user_id``); ``None``
            for an anonymous request

    Returns:
        Cache key combining query hash, normalized variables and user id
    """
    if user_id is not None:
        combined = json.dumps(
            [query_hash, variables or {}, user_id], sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(f"user:{combined}".encode()).hexdigest()

    if not variables:
        return query_hash

    # Normalize variables: sort keys for consistent hashing
    var_str = json.dumps(variables, sort_keys=True, separators=(",", ":"))
    combined = f"{query_hash}:{var_str}"
    return hashlib.sha256(combined.encode()).hexdigest()


_USER_ID_KEYS = ("user_id", "id", "sub")


def response_cache_user_id(context: Optional[dict[str, Any]]) -> tuple[bool, str | None]:
    """Who a cached response belongs to: ``(cacheable, user_id)``.

    An anonymous request (no ``context["user"]``, not ``authenticated``) is cacheable
    with no user id, so anonymous requests share entries. An authenticated request is
    cacheable only with a stable user id: ``user_id``, ``id`` or ``sub`` of the user
    (a ``UserContext`` or a dict). Without one it is not cached, since its response
    could otherwise be served to another user.
    """
    if not context:
        return True, None
    user = context.get("user")
    if user is None:
        return (not context.get("authenticated", False)), None

    for key in _USER_ID_KEYS:
        value = user.get(key) if isinstance(user, dict) else getattr(user, key, None)
        # A str, an int or a UUID; not a missing, boolean or structured value
        if value is None or isinstance(value, (bool, dict, list, tuple, set)):
            continue
        if text := str(value):
            return True, text
    return False, None


def get_apq_backend(config: FraiseQLConfig) -> APQStorageBackend:
    """Get APQ backend instance for the given configuration.

    Uses singleton pattern to avoid recreating backends for the same config. A new
    backend gets the queries of ``config.apq_queries_dir`` registered in it.

    Args:
        config: FraiseQL configuration

    Returns:
        APQ storage backend instance
    """
    # Create a cache key based on backend type and config
    cache_key = ":".join(
        (
            config.apq_storage_backend,
            str(hash(str(config.apq_backend_config))),
            str(hash(str(config.database_url))),
            str(config.apq_queries_dir),
        )
    )

    if cache_key not in _backend_cache:
        backend = create_apq_backend(config)
        logger.debug(f"Created APQ backend: {config.apq_storage_backend}")
        if config.apq_queries_dir:
            register_queries_from_directory(backend, config.apq_queries_dir)
        _backend_cache[cache_key] = backend

    return _backend_cache[cache_key]


def register_queries_from_directory(backend: APQStorageBackend, directory: str) -> dict[str, str]:
    """Register every operation of the ``.graphql``/``.gql`` files under ``directory``.

    Each operation is stored under the SHA-256 of its text as it appears in the file
    (one operation per file: the file's content without surrounding whitespace), so a
    client must hash and send exactly that text.

    Args:
        backend: APQ storage backend to register the queries in
        directory: Directory scanned recursively (``apq_queries_dir``)

    Returns:
        Dict mapping hash -> query for the registered queries

    Raises:
        FileNotFoundError: If the directory does not exist
    """
    from fraiseql.storage.query_loader import load_queries_from_directory

    registered = backend.register_queries(load_queries_from_directory(directory))
    logger.info(f"Registered {len(registered)} persisted queries from {directory}")
    return registered


def handle_apq_request_with_cache(
    request: GraphQLRequest,
    backend: APQStorageBackend,
    config: FraiseQLConfig,
    context: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Handle APQ request with response caching support.

    This function implements the enhanced APQ flow:
    1. Check for cached response (if caching enabled)
    2. Return cached response if found
    3. Return None if cache miss (caller should execute query)

    Args:
        request: GraphQL request with APQ extensions
        backend: APQ storage backend
        config: FraiseQL configuration
        context: Optional request context containing user/tenant information

    Returns:
        Cached response dict if found, None if cache miss or caching disabled
    """
    if not config.apq_cache_responses:
        logger.debug("APQ response caching is disabled")
        return None

    # Extract APQ hash
    if not request.extensions or "persistedQuery" not in request.extensions:
        return None

    persisted_query = request.extensions["persistedQuery"]
    sha256_hash = persisted_query.get("sha256Hash")

    if not sha256_hash:
        return None

    # Try to get cached response
    try:
        cacheable, user_id = response_cache_user_id(context)
        if not cacheable:
            logger.debug("APQ response cache skipped: authenticated request without user id")
            return None
        metrics = get_global_metrics()
        # Compute cache key including variables and user to prevent data leakage
        variables = getattr(request, "variables", None)
        response_cache_key = compute_response_cache_key(sha256_hash, variables, user_id)
        cached_response = backend.get_cached_response(response_cache_key, context=context)
        if cached_response:
            logger.debug(f"APQ cache hit: {response_cache_key[:8]}...")
            metrics.record_response_cache_hit(response_cache_key)

            # Filter cached response by field selection (defense in depth)
            query_text = backend.get_persisted_query(sha256_hash)
            if query_text:
                operation_name = getattr(request, "operationName", None)
                selection_set = extract_selection_set(query_text, operation_name)
                if selection_set:
                    fragments = extract_fragments(query_text)
                    cached_response = filter_response_by_selection(
                        cached_response, selection_set, fragments
                    )

            return cached_response
        logger.debug(f"APQ cache miss: {response_cache_key[:8]}...")
        metrics.record_response_cache_miss(response_cache_key)
        return None
    except Exception as e:
        logger.warning(f"Failed to retrieve cached response: {e}")
        return None


def store_response_in_cache(
    hash_value: str,
    response: dict[str, Any],
    backend: APQStorageBackend,
    config: FraiseQLConfig,
    variables: dict[str, Any] | None = None,
    context: Optional[dict[str, Any]] = None,
    query_text: str | None = None,
    operation_name: str | None = None,
) -> None:
    """Store GraphQL response in cache for future APQ requests.

    Only stores successful responses (no errors). Responses with errors
    are not cached to avoid serving stale error responses.

    The response is filtered based on the query's field selection before
    storing, ensuring only requested fields are cached.

    Args:
        hash_value: SHA256 hash of the persisted query
        response: GraphQL response dict to cache
        backend: APQ storage backend
        config: FraiseQL configuration
        variables: GraphQL variables from the request (for cache key)
        context: Optional request context containing user/tenant information
        query_text: Original query text (for field selection filtering)
        operation_name: Operation name (for multi-operation documents)
    """
    if not config.apq_cache_responses:
        return

    # Don't cache error responses or partial responses with errors
    if "errors" in response:
        logger.debug(f"Skipping cache for response with errors: {hash_value[:8]}...")
        return

    # Don't cache responses without data
    if "data" not in response:
        logger.debug(f"Skipping cache for response without data: {hash_value[:8]}...")
        return

    cacheable, user_id = response_cache_user_id(context)
    if not cacheable:
        logger.debug("Skipping cache for authenticated request without user id")
        return

    try:
        # Filter response by field selection before storing
        filtered_response = response
        if query_text:
            selection_set = extract_selection_set(query_text, operation_name)
            if selection_set:
                fragments = extract_fragments(query_text)
                filtered_response = filter_response_by_selection(response, selection_set, fragments)

        # Compute cache key including variables and user to prevent data leakage
        cache_key = compute_response_cache_key(hash_value, variables, user_id)
        backend.store_cached_response(cache_key, filtered_response, context=context)
        metrics = get_global_metrics()
        metrics.record_response_cache_store(cache_key)
        logger.debug(f"Stored filtered response in cache: {cache_key[:8]}...")
    except Exception as e:
        logger.warning(f"Failed to store response in cache: {e}")


def _is_query_operation(query_text: str, operation_name: str | None) -> bool:
    """Whether the operation a request runs is a query (not a mutation or subscription)."""
    from graphql import GraphQLError, OperationType, get_operation_ast, parse

    try:
        operation = get_operation_ast(parse(query_text), operation_name)
    except GraphQLError:
        return False
    return operation is not None and operation.operation == OperationType.QUERY


def store_executed_response(
    result: Any,
    *,
    hash_value: str,
    backend: APQStorageBackend,
    query_text: str,
    config: FraiseQLConfig,
    variables: dict[str, Any] | None = None,
    context: Optional[dict[str, Any]] = None,
    operation_name: str | None = None,
) -> None:
    """Cache the response the ``/graphql`` route built for an APQ request.

    The route answers with a dict or, on its Rust paths, with a ``Response`` holding
    JSON bytes; both are cached. Only queries are cached: a cached mutation would be
    answered from the cache instead of running. Responses with errors are not cached
    (see ``store_response_in_cache``), and neither are ``extensions`` (execution
    metadata of this one request).

    Args:
        result: What the route returned (dict or ``Response``)
        hash_value: SHA256 hash of the persisted query
        backend: APQ storage backend
        query_text: The query text that ran
        config: FraiseQL configuration
        variables: GraphQL variables from the request (for cache key)
        context: Request context (tenant isolation)
        operation_name: Operation name (for multi-operation documents)
    """
    if not _is_query_operation(query_text, operation_name):
        return

    if isinstance(result, dict):
        response = result
    else:
        status_code = getattr(result, "status_code", None)
        media_type = getattr(result, "media_type", None) or ""
        body = getattr(result, "body", None)
        if status_code != 200 or "json" not in media_type or not body:
            return
        try:
            response = json.loads(body)
        except (TypeError, ValueError):
            logger.debug("APQ response cache: response body is not JSON, not cached")
            return
        if not isinstance(response, dict):
            return

    response = {key: value for key, value in response.items() if key != "extensions"}
    store_response_in_cache(
        hash_value,
        response,
        backend,
        config,
        variables=variables,
        context=context,
        query_text=query_text,
        operation_name=operation_name,
    )


def get_apq_hash_from_request(request: GraphQLRequest) -> Optional[str]:
    """Extract APQ hash from GraphQL request.

    Args:
        request: GraphQL request

    Returns:
        SHA256 hash if APQ request, None otherwise
    """
    if not request.extensions or "persistedQuery" not in request.extensions:
        return None

    persisted_query = request.extensions["persistedQuery"]
    return persisted_query.get("sha256Hash")


def is_cacheable_response(response: dict[str, Any]) -> bool:
    """Check if a GraphQL response is suitable for caching.

    Args:
        response: GraphQL response dict

    Returns:
        True if response can be cached, False otherwise
    """
    # Don't cache responses with errors
    if "errors" in response:
        return False

    # Don't cache responses without data
    if "data" not in response:
        return False

    # Could add more sophisticated caching rules here
    # For example, check for cache-control directives in extensions
    return True


def clear_backend_cache() -> None:
    """Clear the global backend cache.

    This is primarily useful for testing.
    """
    global _backend_cache  # noqa: PLW0602
    _backend_cache.clear()
    logger.debug("Cleared APQ backend cache")

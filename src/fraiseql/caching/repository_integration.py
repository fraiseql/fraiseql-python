"""Integration of caching with FraiseQLRepository.

This module provides a cached wrapper for FraiseQLRepository that
automatically caches query results and invalidates cache on mutations.
"""

import hashlib
import json
import logging
import re
from typing import Any

from fraiseql.core.rust_pipeline import RustResponseBytes
from fraiseql.db import FraiseQLRepository, _root_response_key

from .result_cache import ResultCache

logger = logging.getLogger(__name__)

# How a RustResponseBytes is stored: its JSON text as a string, so the backend
# (PostgresCache keeps JSONB) can store it and the bytes come back unchanged,
# key order included.
_RUST_RESPONSE_MARKER = "__fraiseql_rust_response__"

# Verbs stripped from a function name to find the entity it writes:
# fn_update_user -> user, create_blog_post -> blog_post.
_FUNCTION_VERB = re.compile(
    r"^(?:fn_)?(?:create|insert|add|update|upsert|edit|patch|set|delete|remove|"
    r"archive|restore)_"
)


def _encode(value: Any) -> Any:
    """What the backend stores for a find / find_one result."""
    if isinstance(value, RustResponseBytes):
        return {
            _RUST_RESPONSE_MARKER: bytes(value).decode("utf-8"),
            "schema_type": value.schema_type,
        }
    return value


def _decode(value: Any) -> Any:
    """The find / find_one result a stored value stands for."""
    if isinstance(value, dict) and _RUST_RESPONSE_MARKER in value:
        return RustResponseBytes(
            value[_RUST_RESPONSE_MARKER].encode("utf-8"),
            schema_type=value.get("schema_type"),
        )
    return value


def _selection_fingerprint(info: Any) -> str | None:
    """A short hash of what a GraphQL field selects, or None without info.

    ``find`` returns only the selected fields, under the client's aliases, so two
    queries on the same view with different selections must not share a key.
    """
    if info is None:
        return None
    from graphql import print_ast

    field_nodes = getattr(info, "field_nodes", None) or []
    fragments = getattr(info, "fragments", None) or {}
    context = getattr(info, "context", None)
    parts = {
        "field": getattr(info, "field_name", None),
        "response_key": _root_response_key(info),
        "selection": [print_ast(node) for node in field_nodes],
        "fragments": {name: print_ast(node) for name, node in sorted(fragments.items())},
        "variables": getattr(info, "variable_values", None) or {},
        "multiple_root_fields": bool(
            isinstance(context, dict) and context.get("__has_multiple_root_fields__")
        ),
    }
    content = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _arguments_fingerprint(arguments: dict[str, Any]) -> str:
    """A short hash of find's other arguments (where, order_by, limit...)."""
    content = json.dumps(arguments, sort_keys=True, default=str)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class CachedRepository(FraiseQLRepository):
    """Repository wrapper that adds caching functionality.

    ``find`` and ``find_one`` take the same arguments as the wrapped repository's,
    plus ``skip_cache`` and ``cache_ttl``, and return what it returns: on a hit, a
    ``RustResponseBytes`` with the same bytes as the response that was cached.

    Keys are ``<prefix>:<tenant_id>:<view>:<hash>`` (``<prefix>:<view>:<hash>``
    without a ``tenant_id`` in the repository context), the hash covering the
    arguments and the GraphQL selection. ``execute_function`` and
    ``execute_function_with_context`` invalidate the keys of the entity the
    function writes; call ``invalidate_view`` for writes made another way.
    """

    def __init__(
        self,
        base_repository: FraiseQLRepository,
        cache: ResultCache,
    ) -> None:
        """Initialize cached repository.

        Args:
            base_repository: The underlying FraiseQLRepository
            cache: ResultCache instance to use
        """
        # Don't call super().__init__ as we're wrapping, not extending
        self._base = base_repository
        self._cache = cache
        self._key_builder = cache.key_builder

        # Copy attributes from base repository
        self._pool = base_repository._pool
        self.context = base_repository.context

    def _build_key(
        self, view_name: str, field_name: str | None, info: Any, kwargs: dict[str, Any]
    ) -> str:
        if info is None:
            info = self._base.context.get("graphql_info")
        tenant_id = self._base.context.get("tenant_id")
        parts = [_arguments_fingerprint({"field_name": field_name, **kwargs})]
        selection = _selection_fingerprint(info)
        if selection:
            parts.append(selection)
        return self._key_builder.build_key(
            query_name=view_name,
            tenant_id=tenant_id,
            q=":".join(parts),
        )

    @staticmethod
    def _keep_rust_response(result: Any, view_name: str, field_name: str | None, info: Any) -> None:
        """Do what the base find does with a response: keep it in info.context.

        The HTTP layer serves a lone root field's ``RustResponseBytes`` from there.
        """
        if not isinstance(result, RustResponseBytes) or info is None:
            return
        context = getattr(info, "context", None)
        if not isinstance(context, dict):
            return
        if not field_name and hasattr(info, "field_name"):
            field_name = info.field_name
        key = _root_response_key(info) or field_name or view_name
        context.setdefault("_rust_response", {})[key] = result

    async def _cached(
        self,
        method: str,
        view_name: str,
        field_name: str | None,
        info: Any,
        cache_ttl: int | None,
        kwargs: dict[str, Any],
    ) -> Any:
        base_method = getattr(self._base, method)
        key_view = view_name if method == "find" else f"{view_name}:one"
        cache_key = self._build_key(key_view, field_name, info, kwargs)

        async def fetch() -> Any:
            return _encode(await base_method(view_name, field_name, info, **kwargs))

        result = _decode(await self._cache.get_or_set(key=cache_key, func=fetch, ttl=cache_ttl))
        if info is None:
            info = self._base.context.get("graphql_info")
        self._keep_rust_response(result, view_name, field_name, info)
        return result

    async def find(
        self,
        view_name: str,
        field_name: str | None = None,
        info: Any = None,
        *,
        skip_cache: bool = False,
        cache_ttl: int | None = None,
        **kwargs: Any,
    ) -> RustResponseBytes:
        """Find records with caching support.

        Args:
            view_name: Name of the view to query
            field_name: GraphQL field name for response wrapping
            info: Optional GraphQL resolve info for field selection
            skip_cache: If True, bypass cache
            cache_ttl: Custom TTL for this query
            **kwargs: Query filters and options

        Returns:
            What the wrapped repository's find returns
        """
        if skip_cache:
            return await self._base.find(view_name, field_name, info, **kwargs)
        return await self._cached("find", view_name, field_name, info, cache_ttl, kwargs)

    async def find_one(
        self,
        view_name: str,
        field_name: str | None = None,
        info: Any = None,
        *,
        skip_cache: bool = False,
        cache_ttl: int | None = None,
        **kwargs: Any,
    ) -> RustResponseBytes | None:
        """Find single record with caching support.

        A record that isn't found (None) isn't cached.

        Args:
            view_name: Name of the view to query
            field_name: GraphQL field name for response wrapping
            info: Optional GraphQL resolve info for field selection
            skip_cache: If True, bypass cache
            cache_ttl: Custom TTL for this query
            **kwargs: Query filters

        Returns:
            What the wrapped repository's find_one returns
        """
        if skip_cache:
            return await self._base.find_one(view_name, field_name, info, **kwargs)
        return await self._cached("find_one", view_name, field_name, info, cache_ttl, kwargs)

    async def invalidate_view(self, view_name: str, *, all_tenants: bool = True) -> None:
        """Invalidate the cached find / find_one results of a view.

        The view's keys in any schema are invalidated (``v_user`` also covers
        ``app.v_user``), and a pattern's ``_`` matches any character, so this can
        invalidate a little more than the view: never less.

        Args:
            view_name: The view name passed to find (e.g. ``"v_user"``)
            all_tenants: If False, only the keys of the context's ``tenant_id``
        """
        prefix = self._key_builder.prefix
        name = view_name.rsplit(".", 1)[-1]
        tenant_id = self._base.context.get("tenant_id")
        if not all_tenants and tenant_id is not None:
            # prefix:tenant:view:... and prefix:tenant:schema.view:...
            patterns = [f"{prefix}:{tenant_id}:{name}:*", f"{prefix}:{tenant_id}:*.{name}:*"]
        else:
            # Also prefix:view:... (no tenant); "*." covers schema.view either way
            patterns = [f"{prefix}:{name}:*", f"{prefix}:*:{name}:*", f"{prefix}:*.{name}:*"]
        for pattern in patterns:
            await self._cache.invalidate_pattern(pattern)

    async def invalidate_for_function(self, function_name: str) -> None:
        """Invalidate the views of the entity a SQL function writes.

        ``fn_update_user`` (or ``update_user``, ``app.fn_update_user``) invalidates
        ``user``, ``users``, ``v_user``, ``v_users``, ``tv_user`` and ``tv_users``;
        ``fn_create_blog_post`` those of ``blog_post`` and of ``post``.
        """
        name = function_name.rsplit(".", 1)[-1]
        # The entity after the verb, and (as before 1.31.0) the last word of the name
        entities = dict.fromkeys(
            e for e in (_FUNCTION_VERB.sub("", name), name.rsplit("_", 1)[-1]) if e
        )
        for entity in entities:
            for view_prefix in ("", "v_", "tv_"):
                for suffix in ("", "s"):
                    await self.invalidate_view(f"{view_prefix}{entity}{suffix}")

    async def execute_function(
        self,
        function_name: str,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute SQL function and invalidate related cache.

        Args:
            function_name: Name of the function to execute
            input_data: Input data for the function

        Returns:
            Function result
        """
        result = await self._base.execute_function(function_name, input_data)
        await self.invalidate_for_function(function_name)
        return result

    async def execute_function_with_context(
        self,
        function_name: str,
        context_args: tuple[Any, ...],
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute SQL function with context and invalidate cache.

        Args:
            function_name: Name of the function to execute
            context_args: Context arguments (e.g., tenant_id)
            input_data: Input data for the function

        Returns:
            Function result
        """
        result = await self._base.execute_function_with_context(
            function_name,
            context_args,
            input_data,
        )
        await self.invalidate_for_function(function_name)
        return result

    # Delegate all other methods to base repository
    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attributes to base repository."""
        return getattr(self._base, name)

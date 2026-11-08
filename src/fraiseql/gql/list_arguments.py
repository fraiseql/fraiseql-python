"""The where/orderBy/limit/offset arguments fraiseql adds to list queries.

A query returning ``list[T]`` gets these arguments in the schema whether or not
its resolver declares them. A resolver that declares one receives it like any
argument. For one it doesn't declare, the query wrapper holds the client's value
in the GraphQL context, keyed by the field's path, and ``db.find`` on ``T``'s
view applies it: ``async def users(info) -> list[User]: return await
db.find("v_user", info=info)`` filters, sorts and paginates as asked.
"""

from __future__ import annotations

from typing import Any

from graphql.pyutils import Path

# GraphQL argument name -> resolver parameter / db.find keyword
LIST_QUERY_ARGUMENTS = {
    "where": "where",
    "orderBy": "order_by",
    "limit": "limit",
    "offset": "offset",
}

_CONTEXT_KEY = "_fraiseql_list_arguments"


def _path_key(info: Any) -> tuple[Any, ...] | None:
    path = getattr(info, "path", None)
    return tuple(path.as_list()) if isinstance(path, Path) else None


def hold_list_arguments(
    info: Any, view_name: str, gql_kwargs: dict[str, Any], names: tuple[str, ...]
) -> None:
    """Keep the client's values of ``names`` (GraphQL names) for db.find on ``view_name``."""
    context = getattr(info, "context", None)
    key = _path_key(info)
    if not isinstance(context, dict) or key is None:
        return
    values = {
        LIST_QUERY_ARGUMENTS[name]: gql_kwargs[name]
        for name in names
        if gql_kwargs.get(name) is not None
    }
    if values:
        context.setdefault(_CONTEXT_KEY, {})[key] = (view_name, values)


def held_list_arguments(info: Any, view_name: str) -> dict[str, Any]:
    """The values held for the field ``info`` resolves, if it reads ``view_name``."""
    context = getattr(info, "context", None)
    key = _path_key(info)
    if not isinstance(context, dict) or key is None:
        return {}
    held = context.get(_CONTEXT_KEY, {}).get(key)
    if held is None or held[0] != view_name:
        return {}
    return held[1]

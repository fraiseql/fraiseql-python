"""Formatting of graphql-core response paths."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graphql.pyutils import Path


def format_path(path: Path | None, *, keep_indices: bool = True) -> str:
    """Join the keys of a response path with dots.

    ``str(info.path)`` is the repr of graphql-core's ``Path`` NamedTuple, not a
    path, so use this for any text that shows where a field sits in the response.

    Args:
        path: The resolve info's ``path``, or None
        keep_indices: Keep list indices (``posts.0.author``); pass False to name
            the field once for every list item (``posts.author``)

    Returns:
        The dotted path, or ``""`` when there is no path
    """
    if path is None:
        return ""
    keys = path.as_list()
    if not keep_indices:
        keys = [key for key in keys if not isinstance(key, int)]
    return ".".join(str(key) for key in keys)

"""Warn when a query selects a field resolver the Rust pipeline won't run.

``db.find`` and ``db.find_one`` answer with the rows Rust builds from the
view's JSONB. graphql-core never resolves those rows field by field, so a
``@fraiseql.field`` (or ``@fraiseql.dataloader_field``) method on the type is
never called, and its field is missing from the response. Until that path runs
them, saying so is better than leaving the field out without a word.
"""

import inspect
import logging
import types
from collections.abc import Iterable
from typing import Any, Union, get_args, get_origin

from fraiseql.utils.naming import snake_to_camel

logger = logging.getLogger(__name__)

# (type name, field name) pairs already warned about: once per process each
_warned: set[tuple[str, str]] = set()


def _element_type(annotation: Any) -> Any:
    """``X`` for ``X``, ``X | None``, ``list[X]`` and ``list[X] | None``."""
    while True:
        origin = get_origin(annotation)
        if origin in (Union, types.UnionType):
            args = [a for a in get_args(annotation) if a is not type(None)]
            if len(args) != 1:
                return None
            annotation = args[0]
        elif origin is list:
            args = get_args(annotation)
            if not args:
                return None
            annotation = args[0]
        else:
            return annotation


def _is_field_resolver(cls: type, name: str) -> bool:
    member = inspect.getattr_static(cls, name, None)
    return bool(getattr(member, "__fraiseql_field__", False))


def selected_field_resolvers(root_type: type, paths: Iterable[list[str]]) -> list[tuple[str, str]]:
    """The ``(type name, field name)`` of each field resolver ``paths`` reach.

    ``paths`` are snake_case selection paths from the root type, as
    ``extract_field_paths_from_info`` gives them.
    """
    found: list[tuple[str, str]] = []
    for path in paths:
        cls: Any = root_type
        for name in path:
            if not isinstance(cls, type):
                break
            if _is_field_resolver(cls, name):
                if (cls.__name__, name) not in found:
                    found.append((cls.__name__, name))
                break
            hints = getattr(cls, "__gql_type_hints__", None) or {}
            cls = _element_type(hints.get(name))
    return found


def warn_unresolved_field_resolvers(view_name: str, root_type: Any, paths: Any) -> None:
    """Log, once per field, each field resolver a find on ``view_name`` won't run."""
    if not isinstance(root_type, type) or not paths:
        return
    for type_name, field_name in selected_field_resolvers(root_type, paths):
        if (type_name, field_name) in _warned:
            continue
        _warned.add((type_name, field_name))
        logger.warning(
            "%s.%s is a field resolver, and db.find/find_one on %r answer with the "
            "rows Rust builds from the view, which don't run field resolvers: %s is "
            "left out of the response. Put the value in the view's JSONB, or resolve "
            "it in a query of its own.",
            type_name,
            field_name,
            view_name,
            snake_to_camel(field_name),
        )

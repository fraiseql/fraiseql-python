"""GraphQL type annotation helpers for FraiseQL.

Provides utility functions for working with Python typing annotations used
in FraiseQL input/output type conversion. Supports detection and unwrapping of:
- `Annotated[...]` types and their metadata
- `Optional[...]` and `| None` unions
- underlying base types

These helpers are used during GraphQL schema generation.
"""

import functools
import sys
import types
from collections.abc import Callable
from typing import Annotated, Any, TypeVar, Union, get_args, get_origin


def unwrap_annotated(typ: type) -> tuple[type, list[Any]]:
    """Unwrap Annotated[...] types and return the base type and metadata.

    Args:
        typ: A type, possibly wrapped with typing.Annotated.

    Returns:
        A tuple of (base type, list of metadata annotations).
    """
    origin = get_origin(typ)
    if origin is Annotated:
        base_type = get_args(typ)[0]  # The main type, e.g., str in Annotated[str]
        annotations = list(get_args(typ)[1:])  # Any annotations after the base type
        return (
            base_type,
            annotations,
        )  # Return the base type and the list of annotations
    return typ, []


def is_optional_type(typ: type[Any]) -> bool:
    """Check if a type is Optional[...] or includes None in a union.

    Args:
        typ: The type to check.

    Returns:
        True if the type is optional (i.e., includes None).
    """
    origin = get_origin(typ)
    args = get_args(typ)
    return origin in (Union, types.UnionType) and any(a is type(None) or a is None for a in args)


def get_non_optional_type(typ: type[Any]) -> type[Any]:
    """Extract the non-None part of an Optional[...] or union type.

    Args:
        typ: A possibly optional type.

    Returns:
        The type excluding None.

    Raises:
        TypeError: If a valid non-optional type could not be determined.
    """
    if not is_optional_type(typ):
        return typ
    args = get_args(typ)
    non_none_args = [arg for arg in args if arg is not type(None) and arg is not None]
    if len(non_none_args) == 1:
        return non_none_args[0]
    if len(non_none_args) > 1:
        # Use Union instead of | syntax to avoid issues with GraphQL schema building
        # The | syntax creates a UnionType that may not be properly handled downstream
        return Union[tuple(non_none_args)]  # type: ignore[return-value]
    msg = f"Could not extract a valid non-optional type from {typ}. Arguments were: {args}"
    raise TypeError(msg)


# --- Function annotations across Python 3.13 and 3.14 -----------------------------------
#
# Python 3.14 evaluates annotations lazily (PEP 649/749): a function carries an
# ``__annotate__`` function and computes ``__annotations__`` from it on first access.
# ``functools.wraps`` copies ``__annotate__`` there, no longer ``__annotations__``. A
# function whose annotations were *assigned* (``f.__annotations__ = {...}``, as several
# fraiseql decorators do) has ``__annotate__ = None``, so a ``functools.wraps`` wrapper
# around it reports no annotations at all on 3.14: an outer ``@requires_auth`` drops the
# return type of a ``@fraiseql.field``, and the field disappears from the schema.
# ``set_annotations`` and ``wraps`` keep annotations visible through any wrapper.

_F = TypeVar("_F", bound=Callable[..., Any])

_ANNOTATE_VALUE = 1  # annotationlib.Format.VALUE
_ANNOTATE_FORWARDREF = 3  # annotationlib.Format.FORWARDREF
_ANNOTATE_STRING = 4  # annotationlib.Format.STRING


def set_annotations(func: Callable[..., Any], annotations: dict[str, Any]) -> None:
    """Give ``func`` these annotations, kept by every ``functools.wraps`` around it.

    On Python 3.14 this installs an ``__annotate__`` returning ``annotations`` (the same
    dict, so in-place changes stay visible), which ``functools.wraps`` copies onto
    wrappers; on 3.13 it assigns ``__annotations__``, which ``functools.wraps`` copies.

    Args:
        func: The function to annotate.
        annotations: Parameter name (and ``"return"``) to annotation.
    """
    if sys.version_info < (3, 14):
        func.__annotations__ = annotations
        return

    def __annotate__(format: int) -> dict[str, Any]:  # noqa: N807
        if format in (_ANNOTATE_VALUE, _ANNOTATE_FORWARDREF):
            return annotations
        if format == _ANNOTATE_STRING:
            import annotationlib

            return {name: annotationlib.type_repr(value) for name, value in annotations.items()}
        raise NotImplementedError  # VALUE_WITH_FAKE_GLOBALS: values are already evaluated

    func.__annotate__ = __annotate__  # type: ignore[attr-defined]


def wraps(wrapped: Callable[..., Any]) -> Callable[[_F], _F]:
    """``functools.wraps`` that keeps ``wrapped``'s annotations on Python 3.13 and 3.14.

    Use it instead of ``functools.wraps`` for every fraiseql wrapper: the schema builder
    reads a resolver's types from its annotations, through any number of wrappers.

    Args:
        wrapped: The function being wrapped.

    Returns:
        A decorator that copies ``wrapped``'s metadata and annotations onto the wrapper.
    """

    def decorator(wrapper: _F) -> _F:
        functools.update_wrapper(wrapper, wrapped)
        if sys.version_info >= (3, 14) and getattr(wrapped, "__annotate__", None) is None:
            # Assigned annotations: no __annotate__ for update_wrapper to copy
            annotations = getattr(wrapped, "__annotations__", None)
            if annotations:
                set_annotations(wrapper, annotations)
        return wrapper

    return decorator

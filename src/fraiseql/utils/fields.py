"""Utility function to automatically assign missing field types in FraiseQL field definitions.

This function ensures that all fields decorated with `FraiseQLField` in a class have their
`field_type` attribute set from the class's type annotations. It walks through the class's
method resolution order (`__mro__`), inspecting each class in the inheritance chain and
applying the corresponding annotation to the field if it is missing.

This is particularly useful in FraiseQL input types, where field annotations and types need
to be dynamically determined without manually setting `fraise_field` for each field.

Usage:
    - Automatically populates `field_type` for `FraiseQLField` fields when it's missing.
    - Can be used in conjunction with `@fraiseql.input` to ensure proper field processing.
    - Avoids the need to explicitly annotate every field with `fraise_field`.

Args:
    cls: The class to inspect and modify.

Returns:
    None. The function modifies the class in-place.

Example:
    class Example:
        field1: str
        field2: int = 0

    patch_missing_field_types(Example)

This function allows FraiseQL types to work seamlessly with dynamic field registration
without requiring explicit manual setup for each field type.
"""

import logging
from typing import Annotated, Any, get_args, get_origin, get_type_hints

logger = logging.getLogger(__name__)

from fraiseql.fields import FraiseQLField


def patch_missing_field_types(cls: type[Any]) -> None:
    """Ensure all FraiseQLFields on the class have their field_type set from annotations.

    This function is used to automatically populate the `field_type` for fields that
    are instances of `FraiseQLField` but don't have a `field_type` already set.

    It walks through the class' method resolution order (MRO) and applies the
    annotation to the field.

    Args:
        cls: The class to inspect and modify.

    This function is especially useful for FraiseQL types where fields can be
    automatically decorated without manually adding `fraise_field` to each attribute.

    Annotations are resolved with `get_type_hints`, as `collect_fraise_fields` does, so a
    module using `from __future__ import annotations` gets types, not strings. A field
    whose annotation can't be resolved yet is left unset; `define_fraiseql_type` fills it
    from its own resolved hints.
    """
    localns = {cls.__name__: cls}
    for base in reversed(cls.__mro__):
        annotations = getattr(base, "__annotations__", {})
        try:
            hints = get_type_hints(base, localns=localns, include_extras=True)
        except Exception:  # a forward reference that isn't defined yet
            hints = {}
        for name, raw in annotations.items():
            typ = hints.get(name, raw)
            if isinstance(typ, str):
                continue
            origin = get_origin(typ)
            args = get_args(typ)

            # Handle Annotated[T, FraiseQLField] case
            if origin is Annotated and args:
                field_type, *metadata = args
                for meta in metadata:
                    if isinstance(meta, FraiseQLField) and meta.field_type is None:
                        meta.field_type = field_type
                        logger.debug(
                            "Patched Annotated field '%s' with inferred type: %s",
                            name,
                            field_type,
                        )

            # Handle plain annotation with FraiseQLField as default value
            else:
                # Check if the attribute exists and is a FraiseQLField
                field_value = getattr(base, name, None)
                if isinstance(field_value, FraiseQLField) and field_value.field_type is None:
                    field_value.field_type = typ
                    logger.debug(
                        "Patched field '%s' with inferred type from annotation: %s",
                        name,
                        typ,
                    )


__all__ = ["patch_missing_field_types"]

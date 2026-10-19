"""FraideQL decorators for mutation result classes and input types."""

import types
import warnings
from collections.abc import Callable
from typing import (
    Annotated,
    Any,
    TypeVar,
    Union,
    cast,
    dataclass_transform,
    get_args,
    get_origin,
    overload,
)

from fraiseql.fields import fraise_field
from fraiseql.mutations.registry import register_result
from fraiseql.mutations.result_names import legacy_result_union_name
from fraiseql.utils.fields import patch_missing_field_types

T = TypeVar("T", bound=type[Any])

_success_registry: dict[str, type] = {}
_error_registry: dict[str, type] = {}


def clear_mutation_registries() -> None:
    """Clear all mutation decorator registries and SchemaRegistry mutations."""
    _success_registry.clear()
    _error_registry.clear()

    # Also clear the SchemaRegistry mutations to prevent test pollution
    try:
        from fraiseql.gql.builders.registry import SchemaRegistry

        registry = SchemaRegistry.get_instance()
        registry.mutations.clear()
    except ImportError:
        pass  # Registry may not be available in all contexts


class FraiseUnion:
    """Metadata wrapper for union result types."""

    def __init__(self, name: str, *, derived: bool = False) -> None:
        """Name a union type.

        Args:
            name: The GraphQL union name.
            derived: True when the name was derived from the success type (the 1.x
                rule) rather than chosen. On a mutation, the schema builder may then
                replace it with the mutation's own result union name.
        """
        self.name = name
        self.derived = derived


def resolve_union_annotation(annotation: object) -> object:
    """Resolve `Success | Error` into an Annotated union result.

    The union gets the 1.x name derived from the success type, marked ``derived``:
    on a mutation, the schema builder chooses the final name.
    """
    origin = get_origin(annotation)
    if origin not in (Union, types.UnionType):
        return annotation

    args = get_args(annotation)
    success = next((a for a in args if getattr(a, "__name__", "").endswith("Success")), None)
    error = next((a for a in args if getattr(a, "__name__", "").endswith("Error")), None)

    if not success or not error:
        return annotation

    return _derived_union(success, error)


def _derived_union(success_cls: type, error_cls: type) -> object:
    name = legacy_result_union_name(success_cls)
    return Annotated[success_cls | error_cls, FraiseUnion(name, derived=True)]


# ------------------------
# Decorators
# ------------------------


@dataclass_transform(field_specifiers=(fraise_field,))
@overload
def success(_cls: None = None) -> Callable[[T], T]: ...
@overload
def success(_cls: T) -> T: ...


def success(_cls: T | None = None) -> T | Callable[[T], T]:
    """Decorator to define a FraiseQL mutation success type."""

    def wrap(cls: T) -> T:
        from fraiseql.fields import FraiseQLField  # Import for gql_fields
        from fraiseql.gql.schema_builder import SchemaRegistry
        from fraiseql.types.constructor import define_fraiseql_type

        # Track which fields we're auto-injecting
        auto_injected_fields = []

        # Auto-inject standard mutation fields if not already present
        annotations = getattr(cls, "__annotations__", {})

        if "status" not in annotations:
            annotations["status"] = str
            cls.status = "success"
            auto_injected_fields.append("status")

        if "message" not in annotations:
            annotations["message"] = str | None
            cls.message = None
            auto_injected_fields.append("message")

        # NOTE: `errors` field removed from Success types in v1.9.0
        # Success responses should NOT have errors - that's semantically incorrect
        # `errors` field still exists on Error/Failure types where it belongs

        # Add updatedFields (per CTO feedback)
        if "updated_fields" not in annotations:
            annotations["updated_fields"] = list[str] | None
            cls.updated_fields = None
            auto_injected_fields.append("updated_fields")

        cls.__annotations__ = annotations

        # Detect if class has an entity field (any field that's not an auto-field)
        has_entity_field = any(
            field_name not in {"status", "message", "errors", "updated_fields", "id"}
            for field_name in annotations
        )

        if has_entity_field and "id" not in annotations:
            annotations["id"] = str | None
            cls.id = None
            auto_injected_fields.append("id")

        patch_missing_field_types(cls)
        cls = define_fraiseql_type(cls, kind="output")  # type: ignore[assignment]

        # Add auto-injected fields to __gql_fields__
        if auto_injected_fields:
            gql_fields = getattr(cls, "__gql_fields__", {})
            type_hints = getattr(cls, "__gql_type_hints__", {})

            for field_name in auto_injected_fields:
                # Don't override if user defined it explicitly
                if field_name not in gql_fields:
                    field_type = type_hints.get(field_name)
                    if field_type:
                        field = FraiseQLField(
                            field_type=field_type,
                            purpose="output",
                            description=_get_auto_field_description(field_name),
                            graphql_name=None,  # Use default camelCase
                        )
                        field.name = field_name
                        gql_fields[field_name] = field

            cls.__gql_fields__ = gql_fields

        SchemaRegistry.get_instance().register_type(cls)

        _success_registry[cls.__name__] = cls
        _maybe_register_union(cls.__name__)
        return cls

    return wrap if _cls is None else wrap(_cls)


@dataclass_transform(field_specifiers=(fraise_field,))
@overload
def error(_cls: None = None) -> Callable[[T], T]: ...
@overload
def error(_cls: T) -> T: ...


def error(_cls: T | None = None) -> T | Callable[[T], T]:
    """Decorator to define a FraiseQL mutation error type."""

    def wrap(cls: T) -> T:
        from fraiseql.fields import FraiseQLField  # Import for gql_fields
        from fraiseql.gql.schema_builder import SchemaRegistry
        from fraiseql.types.constructor import define_fraiseql_type
        from fraiseql.types.errors import Error

        # Track auto-injected fields
        auto_injected_fields = []

        # Auto-inject standard mutation fields if not already present
        annotations = getattr(cls, "__annotations__", {})

        if "status" not in annotations:
            annotations["status"] = str
            cls.status = "error"  # Default for error types
            auto_injected_fields.append("status")

        if "message" not in annotations:
            annotations["message"] = str | None
            cls.message = None
            auto_injected_fields.append("message")

        if "errors" not in annotations:
            annotations["errors"] = list[Error] | None
            # CRITICAL FIX: Don't set to None, create empty list that will be populated
            # This ensures frontend compatibility by always having an errors array
            cls.errors = []  # Empty list instead of None - populated at runtime
            auto_injected_fields.append("errors")

        # NEW: Auto-inject code field on Error types (v1.8.1)
        # Computed from status by Rust response builder (422, 404, 409, 500)
        if "code" not in annotations:
            annotations["code"] = int
            cls.code = 0  # Placeholder - Rust computes actual value from status
            auto_injected_fields.append("code")

        # NOTE: updated_fields REMOVED from Error types (v1.8.1)
        # Semantically incorrect: Errors don't update fields - operation failed
        # This field only belongs on Success types where updates actually occurred

        # NOTE: id field REMOVED from Error types (v1.8.1)
        # Semantically incorrect: Errors don't create/update entities - operation failed
        # This field only belongs on Success types where entities were created/updated

        cls.__annotations__ = annotations

        patch_missing_field_types(cls)
        cls = define_fraiseql_type(cls, kind="output")  # type: ignore[assignment]

        # Add auto-injected fields to __gql_fields__
        if auto_injected_fields:
            gql_fields = getattr(cls, "__gql_fields__", {})
            type_hints = getattr(cls, "__gql_type_hints__", {})

            for field_name in auto_injected_fields:
                if field_name not in gql_fields:
                    field_type = type_hints.get(field_name)
                    if field_type:
                        field = FraiseQLField(
                            field_type=field_type,
                            purpose="output",
                            description=_get_auto_field_description_error(field_name),
                            graphql_name=None,
                        )
                        field.name = field_name
                        gql_fields[field_name] = field

            cls.__gql_fields__ = gql_fields

        SchemaRegistry.get_instance().register_type(cls)

        _error_registry[cls.__name__] = cls
        _maybe_register_union(cls.__name__)
        return cls

    return wrap if _cls is None else wrap(_cls)


# ------------------------
# Result Union Utilities
# ------------------------


def _maybe_register_union(_: str) -> None:
    """Pair ``XSuccess`` with ``XError`` in the result registry once both exist."""
    for success_name, success_cls in _success_registry.items():
        error_name = f"{success_name.removesuffix('Success')}Error"
        if error_name in _error_registry:
            register_result(success_cls, _error_registry[error_name])


def result(success_cls: type, error_cls: type) -> type:
    """Build a success+error result union type.

    .. deprecated:: 1.29.0
        Annotate ``Success | Error`` instead. On a mutation, the schema build names
        the union after the mutation (``result_name=`` overrides it). fraiseql 1.x
        keeps it working.
    """
    warnings.warn(
        "fraiseql.result() is deprecated; "
        "annotate the mutation's return type as Success | Error instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    register_result(success_cls, error_cls)
    return cast("type", _derived_union(success_cls, error_cls))


def _get_auto_field_description(field_name: str) -> str:
    """Get description for auto-injected mutation fields."""
    descriptions = {
        "status": "Operation status (always 'success' for success types)",
        "message": "Human-readable message describing the operation result",
        "errors": "List of errors (always empty for success types)",
        "updated_fields": "List of field names that were updated in the mutation",
        "id": "ID of the created or updated entity",
    }
    return descriptions.get(field_name, f"Auto-populated {field_name} field")


def _get_auto_field_description_error(field_name: str) -> str:
    """Get description for auto-injected error fields."""
    descriptions = {
        "status": "Error status code (e.g., 'error', 'failed', 'blocked')",
        "message": "Human-readable error message",
        "code": (
            "HTTP-like error code (422=validation, 404=not_found, 409=conflict, 500=server_error)"
        ),
        "errors": "List of detailed error information",
    }
    return descriptions.get(field_name, f"Auto-populated {field_name} field")

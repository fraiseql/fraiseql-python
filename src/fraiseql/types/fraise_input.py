"""Decorator to define FraiseQL input types with flexible field ordering.

This decorator supports GraphQL schema generation and type introspection for input types,
using `fraise_field` to mark fields and store metadata.

Unlike traditional `@dataclass`, this avoids default-before-non-default limitations
by generating its own `__init__`, making it compatible with Strawberry-style field layouts.
"""

from collections.abc import Callable
from typing import TypeVar, dataclass_transform, overload

from fraiseql.fields import fraise_field
from fraiseql.types.constructor import define_fraiseql_type
from fraiseql.utils.fields import patch_missing_field_types

T = TypeVar("T", bound=type)


@dataclass_transform(kw_only_default=True, field_specifiers=(fraise_field,))
@overload
def fraise_input(_cls: None = None) -> Callable[[T], T]: ...
@overload
def fraise_input(_cls: T) -> T: ...


def fraise_input(_cls: T | None = None) -> T | Callable[[T], T]:
    """Decorator for FraiseQL input types using keyword-only init and safe field ordering.

    This decorator creates GraphQL input types that can be used as arguments in queries
    and mutations. It provides flexible field ordering and automatic type generation.

    Args:
        _cls: The class to decorate (when used without parentheses)

    Returns:
        The decorated class with FraiseQL input type capabilities

    Examples:
        Basic usage::

            @fraise_input
            class CreateUserInput:
                name: str
                email: str
                age: int = fraise_field(default=0)

        With optional fields::

            @fraise_input
            class UpdateUserInput:
                id: UUID
                name: str | None = None
                email: str | None = None
                status: UserStatus | None = None

        With field metadata::

            @fraise_input
            class SearchInput:
                query: str = fraise_field(description="Search query text")
                limit: int = fraise_field(default=10, description="Maximum results")
                offset: int = fraise_field(default=0, description="Skip results")
                filters: dict[str, Any] | None = None

        Nested input types::

            @fraise_input
            class AddressInput:
                street: str
                city: str
                country: str

            @fraise_input
            class UserProfileInput:
                bio: str | None = None
                avatar_url: str | None = None
                address: AddressInput | None = None

    Notes:
        - All fields become keyword-only in the generated __init__
        - Default values can appear before required fields
        - Supports GraphQL schema generation and introspection
        - Compatible with type hints and runtime validation
        - Can be used with fraise_field() for additional metadata
    """

    def wrap(cls: T) -> T:
        from fraiseql.gql.schema_builder import SchemaRegistry

        patch_missing_field_types(cls)
        cls = define_fraiseql_type(cls, kind="input")  # type: ignore[assignment]
        SchemaRegistry.get_instance().register_type(cls)
        return cls

    return wrap if _cls is None else wrap(_cls)

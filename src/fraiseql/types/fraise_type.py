"""Decorator to transform a class into a type suitable for use with the FraiseQL library."""

import logging
from collections.abc import Callable
from dataclasses import Field, field
from typing import Any, TypeVar, dataclass_transform, overload

logger = logging.getLogger(__name__)

from fraiseql.fields import fraise_field
from fraiseql.sql.where_generator import safe_create_where_type
from fraiseql.types.constructor import define_fraiseql_type

T = TypeVar("T", bound=type[Any])


@dataclass_transform(field_specifiers=(fraise_field, field, Field))
@overload
def fraise_type(
    _cls: None = None,
    *,
    sql_source: str | None = None,
    jsonb_column: str | None = ...,  # Use ... as sentinel for "not specified"
    implements: list[type] | None = None,
    resolve_nested: bool = False,
    authorize_fields: list[str] | None = None,
) -> Callable[[T], T]: ...


@overload
def fraise_type(_cls: T) -> T: ...


def fraise_type(  # type: ignore[misc]
    _cls: T | None = None,
    *,
    sql_source: str | None = None,
    jsonb_column: str | None = ...,  # Use ... as sentinel for "not specified"
    implements: list[type] | None = None,
    resolve_nested: bool = False,
    authorize_fields: list[str] | None = None,
) -> T | Callable[[T], T]:
    """Decorator to define a FraiseQL GraphQL output type.

    This decorator transforms a Python dataclass into a GraphQL type that can be
    used in your schema. It supports automatic SQL query generation when a sql_source
    is provided.

    Args:
        sql_source: Optional table or view name to bind this type to for automatic
            SQL query generation. When provided, the type becomes queryable and
            filterable through GraphQL.
        jsonb_column: Optional name of the JSONB column containing the type data.
            Defaults to "data" if not specified. Used in production mode to
            extract JSONB content instead of returning full database rows.
        implements: Optional list of GraphQL interface types that this type implements.
        resolve_nested: If True, when this type appears as a nested field in another
            type, FraiseQL will attempt to resolve it via a separate query to its
            sql_source. If False (default), assumes the data is embedded in the
            parent's JSONB and won't create a separate resolver.
        authorize_fields: Optional list of field names to gate automatically with the
            configured operation ``Authorizer`` (issue #366), e.g. ``["email", "phone"]``.
            Each listed field is checked with ``operation_type="field"`` and
            ``operation_name="TypeName.fieldName"`` before its resolver runs. Off by
            default (empty), and a no-op unless an authorizer is configured. Narrow opt-in
            by design — fires per resolved object, so pair with decision caching (#367).

    Returns:
        The decorated class enhanced with FraiseQL capabilities.

    Examples:
        Basic type without SQL binding:
        ```python
        @fraise_type
        @dataclass
        class User:
            id: int
            name: str
            email: str
        ```

        Type with SQL source for automatic queries:
        ```python
        @fraise_type(sql_source="users")
        @dataclass
        class User:
            id: int
            name: str
            email: str
        ```

        Type with custom JSONB column:
        ```python
        @fraise_type(sql_source="tv_machine", jsonb_column="machine_data")
        @dataclass
        class Machine:
            id: UUID
            identifier: str
            serial_number: str
        ```

        Type implementing interfaces:
        ```python
        @fraise_type(sql_source="users", implements=[Node, Timestamped])
        @dataclass
        class User:
            id: int
            name: str
            created_at: datetime
        ```

        Type with nested object resolution (for relational data):
        ```python
        # Department will be resolved via separate query when nested
        @fraise_type(sql_source="departments", resolve_nested=True)
        @dataclass
        class Department:
            id: UUID
            name: str

        # Employee with department as a relation (not embedded)
        @fraise_type(sql_source="employees")
        @dataclass
        class Employee:
            id: UUID
            name: str
            department_id: UUID  # Foreign key
            department: Department | None  # Will query departments table
        ```

        Type with embedded nested objects (default behavior):
        ```python
        # Department data is embedded in parent's JSONB (default)
        @fraise_type(sql_source="departments")
        @dataclass
        class Department:
            id: UUID
            name: str

        # Employee view includes embedded department in JSONB
        @fraise_type(sql_source="v_employees_with_dept")
        @dataclass
        class Employee:
            id: UUID
            name: str
            department: Department | None  # Uses embedded JSONB data
        ```
    """

    def wrapper(cls: T) -> T:
        from fraiseql.utils.fields import patch_missing_field_types

        logger.debug("Decorating class %s at %s", cls.__name__, id(cls))

        # Patch types *before* definition is frozen
        patch_missing_field_types(cls)

        # Infer kind: treat no SQL source as a pure type
        inferred_kind = "type" if sql_source is None else "output"
        cls = define_fraiseql_type(cls, kind=inferred_kind)

        # Automatic field-level authorization opt-in (issue #366). Read live at the
        # resolver build site; empty/absent means no field is auto-gated.
        if authorize_fields:
            cls.__fraiseql_authorize_fields__ = frozenset(authorize_fields)

        if sql_source:
            cls.__gql_table__ = sql_source
            cls.__fraiseql_definition__.sql_source = sql_source
            # Store JSONB column information for production mode extraction
            # Set JSONB column: ... means not specified (default to "data"),
            # None means no JSONB column (regular table)
            actual_jsonb_column: str | None
            if jsonb_column is ...:
                actual_jsonb_column = "data"  # Default for CQRS/JSONB tables
                cls.__fraiseql_definition__.jsonb_column = "data"
            else:
                actual_jsonb_column = jsonb_column  # None for regular tables, or custom column name
                cls.__fraiseql_definition__.jsonb_column = jsonb_column
            # Store whether nested instances should be resolved separately
            cls.__fraiseql_definition__.resolve_nested = resolve_nested
            cls.__gql_where_type__ = safe_create_where_type(cls)

            # Register type with metadata for WHERE clause JSONB path detection
            # This is CRITICAL for WHERE clause generation to know which fields are in JSONB
            from fraiseql.db import register_type_for_view

            # Determine if this table uses JSONB for data storage
            has_jsonb_data = actual_jsonb_column is not None

            # Register the type with metadata (table_columns will be introspected later if needed)
            register_type_for_view(
                view_name=sql_source,
                type_class=cls,
                has_jsonb_data=has_jsonb_data,
                jsonb_column=actual_jsonb_column,
                validate_fk_strict=False,  # Allow for flexible development
            )

            # Add lazy properties for auto-generation of WhereInput and OrderBy
            from fraiseql.types.lazy_properties import (
                LazyOrderByProperty,
                LazyWhereInputProperty,
            )

            # Only add if not already defined (allow manual override)
            if not hasattr(cls, "WhereInput"):
                cls.WhereInput = LazyWhereInputProperty()
            if not hasattr(cls, "OrderBy"):
                cls.OrderBy = LazyOrderByProperty()

        # Store interfaces this type implements
        if implements:
            cls.__fraiseql_interfaces__ = implements
            # Register type with schema builder if it implements interfaces
            from fraiseql.gql.schema_builder import SchemaRegistry

            SchemaRegistry.get_instance().register_type(cls)

        return cls

    return wrapper if _cls is None else wrapper(_cls)

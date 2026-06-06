"""Schema registry for managing GraphQL type registrations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, get_args, get_origin

from fraiseql.config.schema_config import SchemaConfig

if TYPE_CHECKING:
    from collections.abc import Callable

    from graphql import GraphQLEnumType, GraphQLScalarType

    from fraiseql.security.authorization import Authorizer

logger = logging.getLogger(__name__)


class SchemaRegistry:
    """Singleton registry for GraphQL query types and mutation resolvers."""

    _instance = None

    def __init__(self) -> None:
        """Initialize empty registries for types, mutations, enums, interfaces, and scalars."""
        self._types: dict[type, type] = {}
        self._mutations: dict[str, Callable[..., Any]] = {}
        self._queries: dict[str, Callable[..., Any]] = {}
        self._subscriptions: dict[str, Callable[..., Any]] = {}
        self._enums: dict[type, GraphQLEnumType] = {}
        self._interfaces: dict[type, type] = {}
        self._scalars: dict[str, GraphQLScalarType] = {}  # NEW: Custom scalar registry
        self._type_map: dict[str, Any] = {}  # GraphQL types cache for Connection/Edge/PageInfo
        self.config: Any = None  # FraiseQLConfig instance
        # Global default operation authorizer (issue #362). Enforcement reads this
        # slot live at resolve time; the bypass gates source it at construction.
        self._default_authorizer: Authorizer | None = None

    @classmethod
    def get_instance(cls) -> SchemaRegistry:
        """Get or create the singleton registry instance."""
        if cls._instance is None:
            logger.debug("Creating new SchemaRegistry instance")
            cls._instance = cls()
        else:
            logger.debug("Returning existing SchemaRegistry instance")
        return cls._instance

    def clear(self) -> None:
        """Clear all registries and caches.

        This method clears:
        - SchemaRegistry's internal types and mutations
        - SchemaConfig settings
        - Registered enums
        - Mutation decorator registries
        - GraphQL type caches
        """
        logger.debug("Clearing the registry...")
        # Clear SchemaRegistry's own registries
        self._types.clear()
        self._mutations.clear()
        self._queries.clear()
        self._subscriptions.clear()
        self._enums.clear()
        self._interfaces.clear()
        self._type_map.clear()
        self.config = None
        self._default_authorizer = None
        logger.debug("Registry after clearing: %s", list(self._types.keys()))

        # Clear mutation decorator registries
        from fraiseql.mutations.decorators import clear_mutation_registries

        clear_mutation_registries()

        # Reset SchemaConfig to defaults
        SchemaConfig.reset()

        # Clear GraphQL type cache since field names might change
        from fraiseql.core.graphql_type import _graphql_type_cache

        _graphql_type_cache.clear()

    def register_type(self, typ: type) -> None:
        """Register a Python type as a GraphQL query type.

        Args:
            typ: The decorated Python type to register.
        """
        if typ in self._types:
            logger.debug("Type '%s' is already registered in the schema.", typ.__name__)
        else:
            logger.debug("Registering type '%s' to the schema.", typ.__name__)

        self._types[typ] = typ
        logger.debug("Current registry: %s", list(self._types.keys()))

        # NEW: Auto-discover and register scalar types used in field annotations and attributes
        if hasattr(typ, "__annotations__"):
            for field_type in typ.__annotations__.values():
                self._discover_and_register_scalars(field_type)

        # Also check class attributes for scalar objects (for testing)
        for attr_name in dir(typ):
            if not attr_name.startswith("_"):
                continue
            attr_value = getattr(typ, attr_name)
            if self._is_custom_scalar(attr_value):
                self.register_scalar(attr_value)

        # Register type with database repository if it has sql_source
        if hasattr(typ, "__fraiseql_definition__") and typ.__fraiseql_definition__.sql_source:
            from fraiseql.db import register_type_for_view

            sql_source = typ.__fraiseql_definition__.sql_source
            jsonb_column = getattr(typ.__fraiseql_definition__, "jsonb_column", None)
            logger.debug(
                "Registering type '%s' with repository for view '%s' (jsonb_column: %s)",
                typ.__name__,
                sql_source,
                jsonb_column,
            )

            # CRITICAL FIX for Issue #124: Don't overwrite existing metadata
            # If table_columns were already registered via register_type_for_view(),
            # preserve them. Only register if metadata doesn't exist yet.
            from fraiseql.db import _table_metadata

            if sql_source not in _table_metadata:
                # First time seeing this type - register with minimal metadata
                register_type_for_view(sql_source, typ, jsonb_column=jsonb_column)
            else:
                # Type already registered - only register the type class, not the metadata
                # This prevents overwriting table_columns that were explicitly set
                register_type_for_view(sql_source, typ)

    def register_enum(self, enum_cls: type, graphql_enum: GraphQLEnumType) -> None:
        """Register a Python Enum class as a GraphQL enum type.

        Args:
            enum_cls: The Python Enum class decorated with @fraise_enum.
            graphql_enum: The corresponding GraphQL enum type.
        """
        if enum_cls in self._enums:
            logger.debug("Enum '%s' is already registered in the schema.", enum_cls.__name__)
        else:
            logger.debug("Registering enum '%s' to the schema.", enum_cls.__name__)

        self._enums[enum_cls] = graphql_enum

    def register_interface(self, interface_cls: type) -> None:
        """Register a Python class as a GraphQL interface type.

        Args:
            interface_cls: The Python class decorated with @fraise_interface.
        """
        if interface_cls in self._interfaces:
            logger.debug(
                "Interface '%s' is already registered in the schema.",
                interface_cls.__name__,
            )
        else:
            logger.debug("Registering interface '%s' to the schema.", interface_cls.__name__)

        self._interfaces[interface_cls] = interface_cls

    def register_scalar(self, scalar_class: GraphQLScalarType) -> None:
        """Register a custom scalar type.

        Args:
            scalar_class: A GraphQLScalarType instance to register.

        Raises:
            TypeError: If scalar_class is not a GraphQLScalarType.
        """
        from graphql import GraphQLScalarType

        if not isinstance(scalar_class, GraphQLScalarType):
            raise TypeError(
                f"{scalar_class} must be a GraphQLScalarType instance, got {type(scalar_class)}"
            )

        scalar_name = scalar_class.name

        if scalar_name in self._scalars:
            logger.debug("Scalar '%s' is already registered in the schema.", scalar_name)
        else:
            logger.debug("Registering scalar '%s' to the schema.", scalar_name)

        self._scalars[scalar_name] = scalar_class
        logger.debug("Total scalars registered: %d", len(self._scalars))

    def _discover_and_register_scalars(self, field_type: Any) -> None:
        """Recursively discover and register scalar types in field annotations.

        Handles:
        - Direct scalar: UUIDScalar
        - Optional scalar: UUIDScalar | None
        - List of scalars: list[UUIDScalar]
        - Complex: list[UUIDScalar | None]

        Args:
            field_type: The type annotation to analyze.
        """
        # Handle generic types (Optional, Union, list, etc.)
        origin = get_origin(field_type)

        if origin is not None:
            # Extract type arguments (e.g., [UUID, None] from UUID | None)
            args = get_args(field_type)
            for arg in args:
                if arg is type(None):  # Skip NoneType
                    continue
                # Recursively check each argument
                self._discover_and_register_scalars(arg)
            return

        # Check if this is a custom scalar
        if self._is_custom_scalar(field_type):
            # Only register if not already registered
            scalar_name = field_type.name  # GraphQLScalarType has 'name' attribute
            if scalar_name not in self._scalars:
                self.register_scalar(field_type)

    def _is_custom_scalar(self, type_obj: Any) -> bool:
        """Check if a type is a custom GraphQL scalar.

        Args:
            type_obj: The type to check.

        Returns:
            bool: True if type_obj is a GraphQLScalarType instance.
        """
        from graphql import GraphQLScalarType

        return isinstance(type_obj, GraphQLScalarType)

    def deregister(self, typename: str) -> None:
        """Deregister a type by its name to avoid name conflicts in subsequent tests."""
        types_to_remove = [key for key, value in self._types.items() if value.__name__ == typename]
        for key in types_to_remove:
            del self._types[key]
            logger.debug("Deregistered type '%s' from the schema.", typename)

    def register_mutation(self, mutation_or_fn: type | Callable[..., Any]) -> None:
        """Register a mutation class or resolver function as a GraphQL mutation.

        Args:
            mutation_or_fn: The mutation class or resolver function to register.
        """
        if hasattr(mutation_or_fn, "__fraiseql_mutation__"):
            # Check if it's a simple function-based mutation
            if (
                hasattr(mutation_or_fn, "__fraiseql_resolver__")
                and mutation_or_fn.__fraiseql_resolver__ is mutation_or_fn
            ):
                # It's a function-based mutation decorated with @mutation
                self._mutations[mutation_or_fn.__name__] = mutation_or_fn
            else:
                # It's a @mutation decorated class
                # Register the resolver function
                resolver_fn = mutation_or_fn.__fraiseql_resolver__
                self._mutations[resolver_fn.__name__] = resolver_fn
                # Also register the success and error types
                definition = mutation_or_fn.__fraiseql_mutation__
                if hasattr(definition, "success_type") and definition.success_type:
                    self.register_type(definition.success_type)
                if hasattr(definition, "error_type") and definition.error_type:
                    self.register_type(definition.error_type)
        else:
            # Legacy: direct resolver function
            self._mutations[mutation_or_fn.__name__] = mutation_or_fn

    def register_query(self, query_fn: Callable[..., Any]) -> None:
        """Register a query function as a GraphQL field."""
        name = query_fn.__name__

        # Debug logging
        if name in self._queries:
            prev_module = (
                self._queries[name].__module__
                if hasattr(self._queries[name], "__module__")
                else "unknown"
            )
            new_module = query_fn.__module__ if hasattr(query_fn, "__module__") else "unknown"
            logger.warning(
                "Query '%s' is being overwritten. Previous module: %s, New module: %s",
                name,
                prev_module,
                new_module,
            )
        else:
            logger.debug(
                "Registering query '%s' from module '%s'",
                name,
                query_fn.__module__ if hasattr(query_fn, "__module__") else "unknown",
            )

        self._queries[query_fn.__name__] = query_fn

        # Log current registry state
        logger.debug("Current queries in registry: %s", list(self._queries.keys()))

    def register_subscription(self, subscription_fn: Callable[..., Any]) -> None:
        """Register a subscription function as a GraphQL field."""
        self._subscriptions[subscription_fn.__name__] = subscription_fn

    @property
    def types(self) -> dict[type, type]:
        """Get registered types."""
        return self._types

    @property
    def mutations(self) -> dict[str, Callable[..., Any]]:
        """Get registered mutations."""
        return self._mutations

    @property
    def queries(self) -> dict[str, Callable[..., Any]]:
        """Get registered queries."""
        return self._queries

    @property
    def subscriptions(self) -> dict[str, Callable[..., Any]]:
        """Get registered subscriptions."""
        return self._subscriptions

    @property
    def enums(self) -> dict[type, GraphQLEnumType]:
        """Get registered enums."""
        return self._enums

    @property
    def interfaces(self) -> dict[type, type]:
        """Get registered interfaces."""
        return self._interfaces

    @property
    def scalars(self) -> dict[str, GraphQLScalarType]:
        """Get registered scalars."""
        return self._scalars

    @property
    def default_authorizer(self) -> Authorizer | None:
        """The global default operation authorizer, or ``None`` if unset (issue #362)."""
        return self._default_authorizer

    def set_default_authorizer(self, authorizer: Authorizer | None) -> None:
        """Set (or clear) the global default operation authorizer.

        Enforcement reads this slot at resolve time, and the resolver-bypass gates
        (TurboRouter, ``/graphql/rust``, APQ) source it as well, so one configured
        authorizer covers every execution path.
        """
        self._default_authorizer = authorizer

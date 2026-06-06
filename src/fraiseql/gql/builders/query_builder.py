"""Query type builder for GraphQL schema."""

from __future__ import annotations

import asyncio
import logging
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, List, cast, get_args, get_origin, get_type_hints

from graphql import (
    GraphQLArgument,
    GraphQLError,
    GraphQLField,
    GraphQLInt,
    GraphQLList,
    GraphQLObjectType,
    GraphQLOutputType,
    GraphQLResolveInfo,
    GraphQLString,
)

from fraiseql.config.schema_config import SchemaConfig
from fraiseql.core.graphql_type import (
    _clean_docstring,
    convert_type_to_graphql_input,
    convert_type_to_graphql_output,
)
from fraiseql.gql.enum_serializer import wrap_resolver_with_enum_serialization
from fraiseql.security.authorization import enforce_around_async, enforce_around_sync
from fraiseql.types.coercion import wrap_resolver_with_input_coercion
from fraiseql.utils.naming import snake_to_camel

if TYPE_CHECKING:
    from fraiseql.gql.builders.registry import SchemaRegistry

logger = logging.getLogger(__name__)


class QueryTypeBuilder:
    """Builds the Query type from registered query functions and types."""

    def __init__(self, registry: SchemaRegistry) -> None:
        """Initialize with a schema registry.

        Args:
            registry: The schema registry containing registered types and queries.
        """
        self.registry = registry

    def _is_fraise_type(self, field_type: Any) -> bool:
        """Check if a type is a FraiseQL type (has __fraiseql_definition__)."""
        return hasattr(field_type, "__fraiseql_definition__")

    def _should_add_where_parameter(self, return_type: Any) -> tuple[bool, Any | None]:
        """Check if query should get automatic WHERE parameter and return element type.

        Returns:
            (should_add_where, element_type)
        """
        origin = get_origin(return_type)
        if origin in (list, List):
            args = get_args(return_type)
            if args and self._is_fraise_type(args[0]):
                return True, args[0]
        return False, None

    def _add_where_parameter_if_needed(
        self, gql_args: dict[str, GraphQLArgument], return_type: Any
    ) -> None:
        """Add where parameter to GraphQL args if query returns list of Fraise types.

        If a 'where' parameter already exists (e.g., declared as `where: Any`),
        this method updates it to use the properly-typed WhereInput type.
        This ensures the WhereInput type is always referenced in the schema.
        """
        should_add, element_type = self._should_add_where_parameter(return_type)
        if should_add and element_type:
            # Generate WhereInput type for the element type
            from fraiseql.sql.graphql_where_generator import create_graphql_where_input

            where_input_type = create_graphql_where_input(element_type)

            # Register the WHERE input type with the schema registry
            self.registry.register_type(where_input_type)

            # Convert to GraphQL input type
            gql_where_type = convert_type_to_graphql_input(where_input_type)

            # Always set/update the where argument with the properly-typed WhereInput
            # This ensures the WhereInput type is referenced in the schema even if
            # the user declared `where: Any`
            gql_args["where"] = GraphQLArgument(gql_where_type)

    def _has_vector_fields(self, element_type: Any) -> bool:
        """Check if type has vector/embedding fields that use VectorOrderBy.

        VectorOrderBy uses Union types (list[float] | dict[str, Any]) that cannot
        be converted to GraphQL input types, so we skip orderBy generation for
        types containing these fields.
        """
        try:
            type_hints = get_type_hints(element_type)
        except Exception:
            type_hints = getattr(element_type, "__annotations__", {})

        # Vector field patterns that trigger VectorOrderBy usage
        vector_patterns = {
            "embedding",
            "vector",
            "_embedding",
            "_vector",
            "embedding_vector",
            "embeddingvector",
            "text_embedding",
            "textembedding",
            "image_embedding",
            "imageembedding",
        }

        # Check for vector field types
        try:
            from fraiseql.types.scalars.vector import (
                HalfVectorField,
                QuantizedVectorField,
                SparseVectorField,
            )

            vector_types = (HalfVectorField, SparseVectorField, QuantizedVectorField)
        except ImportError:
            vector_types = ()

        for field_name, field_type in type_hints.items():
            field_lower = field_name.lower()
            # Check if field name matches vector patterns
            if any(pattern in field_lower for pattern in vector_patterns):
                origin = get_origin(field_type)
                if origin is list or (vector_types and field_type in vector_types):
                    return True
            # Check if field type is a vector type
            if vector_types and field_type in vector_types:
                return True

        return False

    def _add_order_by_parameter_if_needed(
        self, gql_args: dict[str, GraphQLArgument], return_type: Any
    ) -> None:
        """Add orderBy parameter to GraphQL args if query returns list of Fraise types.

        Note: Types with vector/embedding fields are skipped because VectorOrderBy
        uses Union types that cannot be converted to GraphQL input types.
        """
        from fraiseql.sql.graphql_order_by_generator import create_graphql_order_by_input

        # Don't add if already present (check both camelCase and snake_case)
        if "orderBy" in gql_args or "order_by" in gql_args:
            return

        should_add, element_type = self._should_add_where_parameter(return_type)
        if should_add and element_type:
            # Skip types with vector fields - VectorOrderBy uses Union types
            # that can't be converted to GraphQL input types
            if self._has_vector_fields(element_type):
                logger.debug(
                    "Skipping orderBy generation for type %s (has vector fields)",
                    element_type.__name__ if hasattr(element_type, "__name__") else element_type,
                )
                return

            try:
                order_by_input_type = create_graphql_order_by_input(element_type)
                self.registry.register_type(order_by_input_type)
                gql_order_by_type = convert_type_to_graphql_input(order_by_input_type)
                gql_args["orderBy"] = GraphQLArgument(GraphQLList(gql_order_by_type))
            except (TypeError, ValueError) as e:
                # Fallback: Some types may have other fields that can't be converted
                logger.debug(
                    "Could not generate orderBy for type %s: %s",
                    element_type.__name__ if hasattr(element_type, "__name__") else element_type,
                    e,
                )

    def _add_pagination_parameters_if_needed(
        self, gql_args: dict[str, GraphQLArgument], return_type: Any
    ) -> None:
        """Add limit/offset parameters if query returns list of Fraise types."""
        should_add, _ = self._should_add_where_parameter(return_type)
        if should_add:
            if "limit" not in gql_args:
                gql_args["limit"] = GraphQLArgument(GraphQLInt)
            if "offset" not in gql_args:
                gql_args["offset"] = GraphQLArgument(GraphQLInt)

    def _should_add_relay_parameters(self, return_type: Any) -> tuple[bool, Any | None]:
        """Check if query should get Relay pagination parameters."""
        try:
            from fraiseql.types.generic import Connection
        except ImportError:
            return False, None

        origin = get_origin(return_type)
        if origin is Connection:
            args = get_args(return_type)
            if args and self._is_fraise_type(args[0]):
                return True, args[0]

        return False, None

    def _add_relay_parameters_if_needed(
        self, gql_args: dict[str, GraphQLArgument], return_type: Any
    ) -> None:
        """Add Relay pagination parameters if query returns Connection[T]."""
        from fraiseql.sql.graphql_order_by_generator import create_graphql_order_by_input
        from fraiseql.sql.graphql_where_generator import create_graphql_where_input

        should_add, element_type = self._should_add_relay_parameters(return_type)
        if not should_add or not element_type:
            return

        # Forward pagination
        if "first" not in gql_args:
            gql_args["first"] = GraphQLArgument(GraphQLInt)
        if "after" not in gql_args:
            gql_args["after"] = GraphQLArgument(GraphQLString)

        # Backward pagination
        if "last" not in gql_args:
            gql_args["last"] = GraphQLArgument(GraphQLInt)
        if "before" not in gql_args:
            gql_args["before"] = GraphQLArgument(GraphQLString)

        # Also add where
        if "where" not in gql_args:
            where_input_type = create_graphql_where_input(element_type)
            self.registry.register_type(where_input_type)
            gql_args["where"] = GraphQLArgument(convert_type_to_graphql_input(where_input_type))

        # Also add orderBy
        if "orderBy" not in gql_args and "order_by" not in gql_args:
            order_by_input_type = create_graphql_order_by_input(element_type)
            self.registry.register_type(order_by_input_type)
            gql_args["orderBy"] = GraphQLArgument(
                GraphQLList(convert_type_to_graphql_input(order_by_input_type))
            )

    def build(self) -> GraphQLObjectType:
        """Build the root Query GraphQLObjectType from registered types and query functions.

        Returns:
            The Query GraphQLObjectType.

        Raises:
            TypeError: If no fields are defined for the Query type.
        """
        fields: dict[str, GraphQLField] = {}

        # First, handle query functions if any are registered
        self._add_query_functions(fields)

        # Then, check for legacy QueryRoot type pattern
        self._add_query_root_fields(fields)

        if not fields:
            msg = "Type Query must define one or more fields."
            raise TypeError(msg)

        return GraphQLObjectType(name="Query", fields=MappingProxyType(fields))

    def _add_query_functions(self, fields: dict[str, GraphQLField]) -> None:
        """Add registered query functions to the fields dictionary.

        Args:
            fields: The fields dictionary to populate.
        """
        logger.debug(
            "Building query fields. Found %d registered queries: %s",
            len(self.registry.queries),
            list(self.registry.queries.keys()),
        )

        for name, fn in self.registry.queries.items():
            hints = get_type_hints(fn)

            if "return" not in hints:
                msg = f"Query function '{name}' is missing a return type annotation."
                raise TypeError(msg)

            # Use convert_type_to_graphql_output for the return type
            gql_return_type = convert_type_to_graphql_output(hints["return"])
            logger.debug(
                "Query %s: return type %s converted to %s",
                name,
                hints["return"],
                gql_return_type,
            )
            gql_args: dict[str, GraphQLArgument] = {}
            # Track mapping from GraphQL arg names to Python param names
            arg_name_mapping: dict[str, str] = {}

            # Detect arguments (excluding 'info' and 'root')
            for param_name, param_type in hints.items():
                if param_name in {"info", "root", "return"}:
                    continue
                # Use convert_type_to_graphql_input for input arguments
                gql_input_type = convert_type_to_graphql_input(param_type)
                # Convert argument name to camelCase if configured
                config = SchemaConfig.get_instance()
                graphql_arg_name = (
                    snake_to_camel(param_name) if config.camel_case_fields else param_name
                )

                # Special handling for Python reserved words that have trailing underscore
                if param_name.endswith("_") and graphql_arg_name == param_name:
                    # Remove trailing underscore for GraphQL (e.g., id_ -> id, class_ -> class)
                    graphql_arg_name = param_name.rstrip("_")

                gql_args[graphql_arg_name] = GraphQLArgument(gql_input_type)
                # Store mapping from GraphQL name to Python name
                arg_name_mapping[graphql_arg_name] = param_name

            # Automatically add query parameters for list/Connection returns
            # Check for Connection[T] first (Relay pagination)
            is_relay, _ = self._should_add_relay_parameters(hints["return"])
            if is_relay:
                self._add_relay_parameters_if_needed(gql_args, hints["return"])
            else:
                # Standard list[T] - add where, orderBy, limit, offset
                self._add_where_parameter_if_needed(gql_args, hints["return"])
                self._add_order_by_parameter_if_needed(gql_args, hints["return"])
                self._add_pagination_parameters_if_needed(gql_args, hints["return"])

            # Create a wrapper that adapts the GraphQL resolver signature
            wrapped_resolver = self._create_gql_resolver(fn, arg_name_mapping, name)
            wrapped_resolver = wrap_resolver_with_enum_serialization(wrapped_resolver)

            # Convert field name to camelCase if configured
            config = SchemaConfig.get_instance()
            graphql_field_name = snake_to_camel(name) if config.camel_case_fields else name

            fields[graphql_field_name] = GraphQLField(
                type_=cast("GraphQLOutputType", gql_return_type),
                args=gql_args,
                resolve=wrapped_resolver,
                description=_clean_docstring(fn.__doc__),
            )

            logger.debug(
                "Successfully added query field '%s' (GraphQL name: '%s') from function '%s'",
                name,
                graphql_field_name,
                fn.__module__ if hasattr(fn, "__module__") else "unknown",
            )

    def _create_gql_resolver(
        self,
        fn: Callable[..., Any],
        arg_name_mapping: dict[str, str] | None = None,
        field_name: str | None = None,
    ) -> Callable[..., Any]:
        """Create a GraphQL resolver from a function.

        Args:
            fn: The function to wrap as a GraphQL resolver.
            arg_name_mapping: Mapping from GraphQL argument names to Python parameter names.
            field_name: The field name for raw JSON wrapping.

        Returns:
            A GraphQL-compatible resolver function.
        """
        # Use standard resolver (Rust pipeline handles optimization internally)

        # Standard resolver fallback
        # First wrap with input coercion
        coerced_fn = wrap_resolver_with_input_coercion(fn)

        if asyncio.iscoroutinefunction(coerced_fn):

            async def async_resolver(
                root: dict[str, Any], info: GraphQLResolveInfo, **kwargs: Any
            ) -> Any:
                # Store GraphQL info and field name in context for repository
                if hasattr(info, "context") and info.context is not None:
                    info.context["graphql_info"] = info
                    info.context["graphql_field_name"] = info.field_name

                    # Also update the repository's context if it exists
                    if "db" in info.context and hasattr(info.context["db"], "context"):
                        info.context["db"].context["graphql_info"] = info
                        info.context["db"].context["graphql_field_name"] = info.field_name

                # Validate WHERE parameter if present
                if "where" in kwargs and kwargs["where"] is not None:
                    where_clause = kwargs["where"]
                    if not isinstance(where_clause, dict):
                        raise GraphQLError("WHERE parameter must be an object")

                # Validate pagination parameters are non-negative
                for param in ("limit", "offset", "first", "last"):
                    if param in kwargs and kwargs[param] is not None and kwargs[param] < 0:
                        raise GraphQLError(f"{param} must be non-negative")

                # Map GraphQL argument names to Python parameter names
                if arg_name_mapping:
                    mapped_kwargs = {}
                    for gql_name, value in kwargs.items():
                        python_name = arg_name_mapping.get(gql_name, gql_name)
                        mapped_kwargs[python_name] = value
                    kwargs = mapped_kwargs

                # Operation authorization (issue #362): enforce after WHERE/pagination
                # validation and arg-name mapping, before the resolver body.
                return await enforce_around_async(
                    coerced_fn,
                    root,
                    info,
                    kwargs,
                    fn=fn,
                    registry=self.registry,
                    operation_type="query",
                )

            return async_resolver

        def sync_resolver(root: dict[str, Any], info: GraphQLResolveInfo, **kwargs: Any) -> Any:
            # Store GraphQL info and field name in context for repository
            if hasattr(info, "context") and info.context is not None:
                info.context["graphql_info"] = info
                info.context["graphql_field_name"] = info.field_name

                # Also update the repository's context if it exists
                if "db" in info.context and hasattr(info.context["db"], "context"):
                    info.context["db"].context["graphql_info"] = info
                    info.context["db"].context["graphql_field_name"] = info.field_name

            # Validate WHERE parameter if present
            if "where" in kwargs and kwargs["where"] is not None:
                where_clause = kwargs["where"]
                if not isinstance(where_clause, dict):
                    raise GraphQLError("WHERE parameter must be an object")

            # Validate pagination parameters are non-negative
            for param in ("limit", "offset", "first", "last"):
                if param in kwargs and kwargs[param] is not None and kwargs[param] < 0:
                    raise GraphQLError(f"{param} must be non-negative")

            # Map GraphQL argument names to Python parameter names
            if arg_name_mapping:
                mapped_kwargs = {}
                for gql_name, value in kwargs.items():
                    python_name = arg_name_mapping.get(gql_name, gql_name)
                    mapped_kwargs[python_name] = value
                kwargs = mapped_kwargs

            # Operation authorization (issue #362): when an authorizer is in effect this
            # returns a coroutine that enforces before the body; otherwise pure-sync.
            return enforce_around_sync(
                coerced_fn,
                root,
                info,
                kwargs,
                fn=fn,
                registry=self.registry,
                operation_type="query",
            )

        return sync_resolver

    def _add_query_root_fields(self, fields: dict[str, GraphQLField]) -> None:
        """Add fields from QueryRoot type if it exists.

        Args:
            fields: The fields dictionary to populate.
        """
        for typ in list(self.registry.types):
            definition = getattr(typ, "__fraiseql_definition__", None)
            if definition is None:
                continue

            kind = getattr(definition, "kind", None)
            if kind != "type":
                continue

            if typ.__name__ != "QueryRoot":
                continue

            query_instance = typ()
            field_count = 0

            # First check for @field decorated methods
            self._add_field_decorated_methods(typ, query_instance, fields)

            # Then check regular fields
            self._add_regular_fields(definition, query_instance, fields)

            if field_count == 0:
                logger.warning("No fields were added from QueryRoot: %s", typ.__name__)

    def _add_field_decorated_methods(
        self,
        typ: type,
        instance: Any,
        fields: dict[str, GraphQLField],
    ) -> None:
        """Add @field decorated methods to the fields dictionary.

        Args:
            typ: The type class.
            instance: An instance of the type.
            fields: The fields dictionary to populate.
        """
        import inspect

        for attr_name in dir(typ):
            attr = getattr(typ, attr_name)
            if callable(attr) and hasattr(attr, "__fraiseql_field__"):
                # This is a @field decorated method
                sig = inspect.signature(attr)
                return_type = sig.return_annotation
                if return_type == inspect.Signature.empty:
                    logger.warning("Field method %s missing return type annotation", attr_name)
                    continue

                logger.debug("Found @field decorated method: %s", attr_name)
                gql_type = convert_type_to_graphql_output(return_type)

                # Get the bound method from the instance
                bound_method = getattr(instance, attr_name)

                # The bound method should already have the wrapped resolver from the decorator
                wrapped_resolver = wrap_resolver_with_enum_serialization(bound_method)

                # Convert field name to camelCase if configured
                config = SchemaConfig.get_instance()
                graphql_field_name = (
                    snake_to_camel(attr_name) if config.camel_case_fields else attr_name
                )

                fields[graphql_field_name] = GraphQLField(
                    type_=cast("GraphQLOutputType", gql_type),
                    resolve=wrapped_resolver,
                    description=getattr(attr, "__fraiseql_field_description__", None),
                )

    def _add_regular_fields(
        self,
        definition: Any,
        instance: Any,
        fields: dict[str, GraphQLField],
    ) -> None:
        """Add regular fields from type definition to the fields dictionary.

        Args:
            definition: The type definition containing field information.
            instance: An instance of the type.
            fields: The fields dictionary to populate.
        """
        for field_name, field_def in definition.fields.items():
            logger.debug("Field '%s' definition: %s", field_name, field_def)
            if field_def.purpose not in {"output", "both"}:
                logger.debug(
                    "Skipping field '%s' because its purpose is not 'output' or 'both'.",
                    field_name,
                )
                continue

            logger.debug("Adding field '%s' to the QueryRoot fields", field_name)

            gql_type = convert_type_to_graphql_output(field_def.field_type)
            resolver = getattr(instance, f"resolve_{field_name}", None)

            # Wrap resolver if it exists
            if resolver is not None:
                resolver = wrap_resolver_with_enum_serialization(resolver)

            if resolver is None:
                logger.warning(
                    "No resolver found for '%s', falling back to attribute lookup",
                    field_name,
                )

                def make_resolver(instance: Any, field: str) -> Any:
                    def _resolver(_: Any, __: GraphQLResolveInfo) -> Any:
                        return getattr(instance, field, None)

                    return _resolver

                resolver = make_resolver(instance, field_name)

            # Wrap resolver to handle enum serialization
            wrapped_resolver = wrap_resolver_with_enum_serialization(resolver)

            # Convert field name to camelCase if configured
            config = SchemaConfig.get_instance()
            graphql_field_name = (
                snake_to_camel(field_name) if config.camel_case_fields else field_name
            )

            fields[graphql_field_name] = GraphQLField(
                type_=cast("GraphQLOutputType", gql_type),
                resolve=wrapped_resolver,
                description=field_def.description,
            )

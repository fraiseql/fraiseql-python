"""Mutation type builder for GraphQL schema."""

from __future__ import annotations

import logging
import warnings
from collections import Counter
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, cast, get_type_hints

from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLOutputType,
    GraphQLResolveInfo,
)

from fraiseql.config.schema_config import SchemaConfig
from fraiseql.core.graphql_type import (
    _clean_docstring,
    convert_type_to_graphql_input,
    convert_type_to_graphql_output,
)
from fraiseql.mutations.decorators import resolve_union_annotation
from fraiseql.mutations.mutation_decorator import _camel_to_snake
from fraiseql.security.authorization import enforce_around_async, enforce_around_sync
from fraiseql.types.coercion import wrap_resolver_with_input_coercion
from fraiseql.utils.naming import snake_to_camel

if TYPE_CHECKING:
    from fraiseql.gql.builders.registry import SchemaRegistry
    from fraiseql.security.authorization import AuthorizationDecision

logger = logging.getLogger(__name__)


def _warn_filters_ignored_on_mutation(
    decision: AuthorizationDecision,
    root: Any,
    info: GraphQLResolveInfo,
    kwargs: dict[str, Any],
) -> None:
    """Mutations have no row-scoping semantics, so a returned ``filters`` is ignored.

    Never silently drop it — warn so the misuse is visible (issue #362).
    """
    if decision.filters:
        logger.warning(
            "authorization filters are ignored on mutations (no row-scoping semantics); "
            "operation=%s",
            getattr(info, "field_name", "<unknown>"),
        )


@dataclass(frozen=True)
class _FieldNameCandidates:
    """The names a registered mutation could get, before clashes are settled."""

    owner: str  # the class or function, for error messages
    explicit: str | None  # from name=, used as given
    legacy: str  # the 1.x name, from function=
    new: str  # the fraiseql 2.0.0 name, from the class
    from_comment: bool  # auto-discovered: the new name comes from its SQL comment


def _field_name_candidates(key: str, fn: Callable[..., Any]) -> _FieldNameCandidates:
    camel = SchemaConfig.get_instance().camel_case_fields

    def graphql_name(snake: str) -> str:
        return snake_to_camel(snake) if camel else snake

    definition = getattr(fn, "__fraiseql_mutation__", None)
    if hasattr(definition, "mutation_class"):
        return _FieldNameCandidates(
            owner=definition.name,
            explicit=definition.graphql_name,
            legacy=graphql_name(definition.function_name),
            new=definition.default_graphql_name or graphql_name(_camel_to_snake(definition.name)),
            from_comment=definition.default_graphql_name is not None,
        )
    name = graphql_name(key)
    return _FieldNameCandidates(
        owner=fn.__name__,
        explicit=getattr(fn, "__fraiseql_graphql_name__", None),
        legacy=name,
        new=name,
        from_comment=False,
    )


def _warn_renames(renames: list[tuple[str, str]], from_comment: bool) -> None:
    """Emit one FutureWarning listing every mutation name that changes in 2.0.0."""
    lines = [f"  field '{old}' -> '{new}'" for old, new in renames]
    hint = 'To keep a name, pass name="..." to @mutation.'
    if from_comment:
        hint += " For an auto-discovered mutation, set name: in its @fraiseql:mutation comment."
    warnings.warn(
        "These mutation names will change in the next major release of fraiseql (2.0.0):\n"
        + "\n".join(lines)
        + "\n"
        + hint,
        FutureWarning,
        stacklevel=3,
    )


class MutationTypeBuilder:
    """Builds the Mutation type from registered mutation resolvers."""

    def __init__(self, registry: SchemaRegistry) -> None:
        """Initialize with a schema registry.

        Args:
            registry: The schema registry containing registered mutations.
        """
        self.registry = registry

    def build(self) -> GraphQLObjectType:
        """Build the root Mutation GraphQLObjectType from registered resolvers.

        Returns:
            The Mutation GraphQLObjectType.
        """
        fields = {}
        field_names = self._field_names()

        for name, fn in self.registry.mutations.items():
            # Use include_extras=True to preserve Annotated metadata (like FraiseUnion)
            hints = get_type_hints(fn, include_extras=True)

            if "return" not in hints:
                msg = f"Mutation resolver '{name}' is missing a return type annotation."
                raise TypeError(msg)

            # Normalize return annotation (e.g., Annotated[Union[A, B], ...])
            resolved = resolve_union_annotation(hints["return"])
            fn.__annotations__["return"] = resolved  # override with resolved union

            # Use convert_type_to_graphql_output for the return type
            gql_return_type = convert_type_to_graphql_output(cast("type", resolved))
            gql_args: dict[str, GraphQLArgument] = {}
            # Track mapping from GraphQL arg names to Python param names
            arg_name_mapping: dict[str, str] = {}

            # Detect argument (usually just one input arg + info)
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

                gql_args[graphql_arg_name] = GraphQLArgument(GraphQLNonNull(gql_input_type))
                # Store mapping from GraphQL name to Python name
                arg_name_mapping[graphql_arg_name] = param_name

            resolver = self._wrap_mutation_resolver(fn, arg_name_mapping)

            graphql_field_name = field_names[name]

            description = None
            if hasattr(fn, "__fraiseql_mutation__") and hasattr(
                fn.__fraiseql_mutation__, "mutation_class"
            ):
                description = _clean_docstring(fn.__fraiseql_mutation__.mutation_class.__doc__)
            else:
                description = _clean_docstring(fn.__doc__)

            # Check if this mutation has cascade enabled
            has_cascade = False
            if hasattr(fn, "__fraiseql_mutation__"):
                mutation_def = fn.__fraiseql_mutation__
                has_cascade = getattr(mutation_def, "enable_cascade", False)

            # If cascade is enabled, we need to modify the return type
            if has_cascade:
                # Import cascade type resolver
                from fraiseql.mutations.cascade_types import add_cascade_to_union_type

                # Modify the return type to include cascade field in Success branch
                gql_return_type = add_cascade_to_union_type(
                    cast("GraphQLOutputType", gql_return_type), fn.__fraiseql_mutation__
                )

            fields[graphql_field_name] = GraphQLField(
                type_=cast("GraphQLOutputType", gql_return_type),
                args=gql_args,
                resolve=resolver,
                description=description,
            )

        return GraphQLObjectType(name="Mutation", fields=MappingProxyType(fields))

    def _field_names(self) -> dict[str, str]:
        """Pick each mutation's GraphQL field name, keyed like ``registry.mutations``.

        ``name=`` wins. Otherwise a mutation keeps its 1.x name (from ``function=``)
        unless another mutation would get the same one, which is broken today; then it
        gets the 2.0.0 name (from the class). A kept name that will change is listed in
        one FutureWarning.

        Raises:
            ValueError: If two mutations end up with the same field name.
        """
        candidates = {
            key: _field_name_candidates(key, fn) for key, fn in self.registry.mutations.items()
        }
        legacy_counts = Counter(c.legacy for c in candidates.values() if c.explicit is None)

        names: dict[str, str] = {}
        owners: dict[str, str] = {}
        renames: list[tuple[str, str]] = []
        renames_from_comment = False
        for key, c in candidates.items():
            if c.explicit is not None:
                name = c.explicit
            elif legacy_counts[c.legacy] == 1:
                name = c.legacy
                if c.legacy != c.new:
                    renames.append((c.legacy, c.new))
                    renames_from_comment |= c.from_comment
            else:
                name = c.new

            if name in owners:
                msg = (
                    f"Mutations {owners[name]} and {c.owner} both resolve to the GraphQL "
                    f"field '{name}'. Pass name=\"...\" to @mutation on one of them."
                )
                raise ValueError(msg)
            owners[name] = c.owner
            names[key] = name

        if renames:
            _warn_renames(renames, renames_from_comment)
        return names

    def _wrap_mutation_resolver(
        self, fn: Callable[..., Any], arg_name_mapping: dict[str, str] | None = None
    ) -> Callable[..., Any]:
        """Wrap a mutation function with argument mapping and input coercion.

        Args:
            fn: The mutation function to wrap.
            arg_name_mapping: Mapping from GraphQL argument names to Python parameter names.

        Returns:
            A wrapped resolver function.
        """
        # First wrap with input coercion
        coerced_fn = wrap_resolver_with_input_coercion(fn)

        # Then wrap with argument mapping
        import asyncio

        if asyncio.iscoroutinefunction(coerced_fn):

            async def async_resolver(root: Any, info: GraphQLResolveInfo, **kwargs: Any) -> Any:
                # Map GraphQL argument names to Python parameter names
                if arg_name_mapping:
                    mapped_kwargs = {}
                    for gql_name, value in kwargs.items():
                        python_name = arg_name_mapping.get(gql_name, gql_name)
                        mapped_kwargs[python_name] = value
                    kwargs = mapped_kwargs

                # Operation authorization (issue #362): enforce after arg-name mapping,
                # before the resolver body, fail-closed.
                return await enforce_around_async(
                    coerced_fn,
                    root,
                    info,
                    kwargs,
                    fn=fn,
                    registry=self.registry,
                    operation_type="mutation",
                    on_decision=_warn_filters_ignored_on_mutation,
                )

            return async_resolver

        def sync_resolver(root: Any, info: GraphQLResolveInfo, **kwargs: Any) -> Any:
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
                operation_type="mutation",
                on_decision=_warn_filters_ignored_on_mutation,
            )

        return sync_resolver

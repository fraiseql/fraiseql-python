"""Mutation type builder for GraphQL schema."""

from __future__ import annotations

import logging
import os
import warnings
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Callable,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

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
from fraiseql.mutations.decorators import FraiseUnion, resolve_union_annotation
from fraiseql.mutations.mutation_decorator import MutationDefinition, _camel_to_snake
from fraiseql.mutations.result_names import legacy_result_union_name, result_union_name
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
class _NameCandidates:
    """The names a mutation's field or result union could get, before clashes are settled."""

    owner: str  # the class or function, for error messages
    owner_path: str  # module-qualified owner, when two owners share a name
    explicit: str | None  # from name= / result_name=, used as given
    legacy: str  # the 1.x name
    new: str  # the preferred name: from the class (field) or the field (union)
    from_comment: bool  # auto-discovered: the new name comes from its SQL comment


@dataclass(frozen=True)
class _ResultUnion:
    members: Any  # the Success | Error union type
    names: _NameCandidates


@dataclass(frozen=True)
class _Rename:
    kind: str  # "field" or "result union"
    old: str
    new: str
    from_comment: bool


def _field_name_candidates(key: str, fn: Callable[..., Any]) -> _NameCandidates:
    """Field names: the legacy name comes from function=, the preferred one from the class.

    A function mutation is named after its registry key, which is the function's
    name unless code replaced the registry entry. The ``:<owner>`` suffix the
    registry adds when two mutations share a name is never part of the field name.
    """
    camel = SchemaConfig.get_instance().camel_case_fields

    def graphql_name(snake: str) -> str:
        return snake_to_camel(snake) if camel else snake

    definition = getattr(fn, "__fraiseql_mutation__", None)
    if hasattr(definition, "mutation_class"):
        cls = definition.mutation_class
        return _NameCandidates(
            owner=definition.name,
            owner_path=f"{cls.__module__}.{cls.__qualname__}",
            explicit=definition.graphql_name,
            legacy=graphql_name(definition.function_name),
            new=definition.default_graphql_name or graphql_name(_camel_to_snake(definition.name)),
            from_comment=definition.default_graphql_name is not None,
        )
    name = graphql_name(key.partition(":")[0])
    return _NameCandidates(
        owner=fn.__name__,
        owner_path=f"{fn.__module__}.{fn.__qualname__}",
        explicit=getattr(fn, "__fraiseql_graphql_name__", None),
        legacy=name,
        new=name,
        from_comment=False,
    )


def _result_union(fn: Callable[..., Any], field: _NameCandidates) -> _ResultUnion | None:
    """A mutation's result union and its names, or None if it doesn't return one.

    The legacy name comes from the success type; the preferred one from the
    mutation's preferred field name (``name=`` if given).
    """
    new = result_union_name(field.explicit or field.new)
    definition = getattr(fn, "__fraiseql_mutation__", None)
    if hasattr(definition, "mutation_class"):
        success, error = definition.success_type, definition.error_type
        if not success or not error or success is error:
            return None
        names = _NameCandidates(
            owner=field.owner,
            owner_path=field.owner_path,
            explicit=definition.result_name,
            legacy=legacy_result_union_name(success),
            new=new,
            from_comment=field.from_comment,
        )
        return _ResultUnion(success | error, names)

    resolved = resolve_union_annotation(get_type_hints(fn, include_extras=True).get("return"))
    if get_origin(resolved) is not Annotated:
        return None
    members, *metadata = get_args(resolved)
    union = next((m for m in metadata if isinstance(m, FraiseUnion)), None)
    if union is None:
        return None
    # A name derived from the success type (result(), a plain Success | Error) follows
    # the naming rule; one chosen explicitly (e.g. generate_mutation_schema) is kept.
    explicit = getattr(fn, "__fraiseql_result_name__", None)
    if explicit is None and not union.derived:
        explicit = union.name
    names = _NameCandidates(
        owner=field.owner,
        owner_path=field.owner_path,
        explicit=explicit,
        legacy=union.name,
        new=new,
        from_comment=False,
    )
    return _ResultUnion(members, names)


def _choose_names(
    candidates: dict[str, _NameCandidates], kind: str, option: str, renames: list[_Rename]
) -> dict[str, str]:
    """Pick one name per mutation: explicit, else the legacy name, else the preferred one.

    A mutation keeps its legacy name unless another mutation would get the same one,
    which is broken; then it gets the preferred name. fraiseql 1.x never renames a
    kept legacy name; one that differs from the preferred name is appended to
    ``renames`` so the warning can list it.

    Raises:
        ValueError: If two mutations end up with the same name.
    """
    legacy_counts = Counter(c.legacy for c in candidates.values() if c.explicit is None)

    names: dict[str, str] = {}
    owners: dict[str, _NameCandidates] = {}
    for key, c in candidates.items():
        if c.explicit is not None:
            name = c.explicit
        elif legacy_counts[c.legacy] == 1:
            name = c.legacy
            if c.legacy != c.new:
                renames.append(_Rename(kind, c.legacy, c.new, c.from_comment))
        else:
            name = c.new

        if name in owners:
            first, second = owners[name].owner, c.owner
            if first == second:
                first, second = owners[name].owner_path, c.owner_path
            msg = (
                f"Mutations {first} and {second} both resolve to the GraphQL "
                f"{kind} '{name}'. Pass {option}=\"...\" to @mutation on one of them."
            )
            raise ValueError(msg)
        owners[name] = c
        names[key] = name
    return names


# The fraiseql package directory: warnings skip its frames and point at the app's code.
_FRAISEQL_DIR = str(Path(__file__).parents[2]) + os.sep


def _warn_renames(renames: list[_Rename]) -> None:
    """Emit one FutureWarning listing every mutation still named by the legacy rule.

    It promises no rename: fraiseql 2.x on PyPI is the separate FraiseQL v2 product,
    and 1.x keeps these names. Passing ``name=`` / ``result_name=`` silences it.
    """
    lines = [f"  {r.kind} '{r.old}' (preferred: '{r.new}')" for r in renames]
    hint = (
        "fraiseql 1.x keeps these names. To choose a name and silence this warning, "
        'pass name="..." (field) or result_name="..." (union) to @mutation.'
    )
    if any(r.from_comment for r in renames):
        hint += (
            " For an auto-discovered mutation, set name: (field) or result_name: (union)"
            " in its @fraiseql:mutation comment."
        )
    warnings.warn(
        "These mutations are named by fraiseql's legacy rule (a field after its "
        "function=, a result union after its success type):\n" + "\n".join(lines) + "\n" + hint,
        FutureWarning,
        skip_file_prefixes=(_FRAISEQL_DIR,),
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
        self._check_class_mutations()
        fields = {}
        field_names, unions, union_names = self._names()

        for name, fn in self.registry.mutations.items():
            # Use include_extras=True to preserve Annotated metadata (like FraiseUnion)
            hints = get_type_hints(fn, include_extras=True)

            if "return" not in hints:
                msg = f"Mutation resolver '{name}' is missing a return type annotation."
                raise TypeError(msg)

            # A result union gets the name chosen for this mutation in _names()
            if name in unions:
                resolved = Annotated[unions[name].members, FraiseUnion(union_names[name])]
            else:
                resolved = hints["return"]
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

    def _check_class_mutations(self) -> None:
        """Raise one TypeError listing every class mutation with faulty members."""
        problems = [
            problem
            for fn in self.registry.mutations.values()
            if isinstance(
                definition := getattr(fn, "__fraiseql_mutation__", None), MutationDefinition
            )
            for problem in definition.member_problems()
        ]
        if problems:
            msg = "Invalid class mutations:\n" + "\n".join(f"- {p}" for p in problems)
            raise TypeError(msg)

    def _names(self) -> tuple[dict[str, str], dict[str, _ResultUnion], dict[str, str]]:
        """Pick every mutation's field name and result union name, in one place.

        Returns:
            The field names, the result unions and their names, each keyed like
            ``registry.mutations``. Mutations without a result union are absent from
            the last two.

        Raises:
            ValueError: If two mutations end up with the same field or union name.
        """
        fields = {
            key: _field_name_candidates(key, fn) for key, fn in self.registry.mutations.items()
        }
        unions = {
            key: union
            for key, fn in self.registry.mutations.items()
            if (union := _result_union(fn, fields[key])) is not None
        }

        renames: list[_Rename] = []
        field_names = _choose_names(fields, "field", "name", renames)
        union_names = _choose_names(
            {key: union.names for key, union in unions.items()},
            "result union",
            "result_name",
            renames,
        )
        if renames:
            _warn_renames(renames)
        return field_names, unions, union_names

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

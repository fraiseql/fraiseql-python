"""PostgreSQL function-based mutation decorator."""

import inspect
import json
import logging
import re
import types
from collections.abc import Callable, Iterator
from typing import Any, TypeVar, Union, get_args, get_origin, get_type_hints

from graphql import (
    FragmentSpreadNode,
    GraphQLNamedType,
    GraphQLObjectType,
    GraphQLResolveInfo,
    InlineFragmentNode,
    SelectionSetNode,
    get_named_type,
    is_abstract_type,
)

from fraiseql.mutations.error_config import MutationErrorConfig
from fraiseql.mutations.rust_executor import SELECTION_FORMAT
from fraiseql.types.definitions import UNSET
from fraiseql.utils.annotations import set_annotations
from fraiseql.utils.casing import to_camel_case, to_snake_case

T = TypeVar("T")

logger = logging.getLogger(__name__)

# The members a class mutation reads. Anything else in the class is a mistake
# (checked at schema build, see MutationDefinition.member_problems).
_CLASS_MUTATION_MEMBERS = frozenset({"input", "success", "error", "prepare_input"})
# Names used for the error type in docs and other libraries.
_ERROR_TYPE_MISNAMES = frozenset({"failure", "noop", "errors"})


def _info_fragments(info: Any) -> dict[str, Any]:
    """The query's named fragments, or {} when info carries none."""
    fragments = getattr(info, "fragments", None)
    return fragments if isinstance(fragments, dict) else {}


def _concrete_type_name(graphql_type: Any) -> str | None:
    """The name of a GraphQL object type, or None for an abstract or unknown type."""
    name = getattr(graphql_type, "name", None)
    if not isinstance(name, str) or is_abstract_type(graphql_type):
        return None
    return name


def _graphql_named_type(schema: Any, parent_type: Any, field_name: str) -> GraphQLNamedType | None:
    """The named type of parent_type's field_name in schema, unwrapped from lists and non-null.

    parent_type is a GraphQL type or a type name. Returns None when there is no schema
    or no such field. The type may be abstract: see _concrete_type_name.
    """
    type_map = getattr(schema, "type_map", None)
    if not isinstance(type_map, dict):
        return None
    if isinstance(parent_type, str):
        parent_type = type_map.get(parent_type)
    fields = getattr(parent_type, "fields", None)
    if not isinstance(fields, dict):
        return None
    field_def = fields.get(field_name)
    return get_named_type(field_def.type) if field_def is not None else None


def _request_entity_type(
    info: GraphQLResolveInfo | None,
    success_type_name: str,
    entity_field_name: str,
    annotated_type: str | None,
) -> str | None:
    """The type name Rust gives the entity when its SQL function returns no entity_type.

    It is the concrete type of the success type's entity field in the request's schema
    (the field is looked up as named and in camelCase). A field typed as an interface or
    union has none: the object is one of several types, and only its data can say which.
    Without a schema, it is the annotation's type name, which _derive_entity_info gives
    only for a concrete type.
    """
    schema = getattr(info, "schema", None)
    if not isinstance(getattr(schema, "type_map", None), dict):
        return annotated_type
    for field_name in dict.fromkeys((entity_field_name, to_camel_case(entity_field_name))):
        field_type = _graphql_named_type(schema, success_type_name, field_name)
        if field_type is not None:
            return _concrete_type_name(field_type)
    return annotated_type


def _fragment_applies(type_condition: Any, type_name: str | None, schema: Any) -> bool:
    """Whether a fragment with this type condition applies to an object of type_name.

    A fragment applies when it has no type condition, when the condition is the type
    itself, or when it is an interface or union the type belongs to.

    When the object's type isn't known (type_name None), every fragment applies: the
    selection is the union of the fields of every fragment. For a field typed as an
    interface or union, _selection also collects the fields for each possible object
    type, and Rust picks them by the object's __typename; the union is used for data
    without one.
    """
    if type_condition is None or type_name is None:
        return True
    condition = type_condition.name.value
    if condition == type_name:
        return True
    type_map = getattr(schema, "type_map", None)
    if not isinstance(type_map, dict):
        return False
    condition_type = type_map.get(condition)
    object_type = type_map.get(type_name)
    return (
        is_abstract_type(condition_type)
        and isinstance(object_type, GraphQLObjectType)
        and schema.is_sub_type(condition_type, object_type)
    )


def _iter_selected_fields(
    selection_set: Any,
    fragments: dict[str, Any],
    type_name: str | None,
    schema: Any = None,
    _expanding: frozenset[str] = frozenset(),
) -> Iterator[Any]:
    """Yield the fields of a selection set, with the fragments that apply expanded.

    A named spread (``...LocationFields``) is replaced by its fragment's fields, and an
    inline fragment (``... on Location``) by its own, when the fragment applies to an
    object of type_name (see _fragment_applies). Anything else with a name is a field.

    A spread of a fragment that isn't in fragments, or that is already being expanded,
    is skipped: graphql-core validation rejects both queries before execution.
    """
    if not selection_set or not hasattr(selection_set, "selections"):
        return
    for selection in selection_set.selections:
        if isinstance(selection, FragmentSpreadNode):
            name = selection.name.value
            fragment = fragments.get(name)
            if (
                fragment is not None
                and name not in _expanding
                and _fragment_applies(fragment.type_condition, type_name, schema)
            ):
                yield from _iter_selected_fields(
                    fragment.selection_set, fragments, type_name, schema, _expanding | {name}
                )
        elif isinstance(selection, InlineFragmentNode):
            if _fragment_applies(selection.type_condition, type_name, schema):
                yield from _iter_selected_fields(
                    selection.selection_set, fragments, type_name, schema, _expanding
                )
        elif hasattr(selection, "name"):
            yield selection


def _merged_selection_set(field_nodes: list[Any]) -> Any:
    """The selection set of a field selected one or more times, merged as GraphQL does.

    Returns None when no node has a sub-selection.
    """
    selection_sets = [node.selection_set for node in field_nodes if node.selection_set]
    if len(selection_sets) <= 1:
        return selection_sets[0] if selection_sets else None
    return SelectionSetNode(
        selections=tuple(selection for s in selection_sets for selection in s.selections)
    )


def _real_schema(info: Any) -> Any:
    """info.schema when it is a GraphQL schema (its type_map is a dict), else None."""
    schema = getattr(info, "schema", None)
    return schema if isinstance(getattr(schema, "type_map", None), dict) else None


def _selected_fields(
    selection_set: Any,
    fragments: dict[str, Any],
    schema: Any,
    type_name: str | None,
    parent_type: Any,
    *,
    by_alias: bool,
    leaf_fields: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """The fields selected on an object of type_name, one entry per response key.

    Each entry is ``{"name", "alias", "selections"?}``. With by_alias, fields are
    grouped by response key (the alias, or the name), and alias is that key. Without,
    they are grouped by name and alias is the name, for graphql-core, which reads
    fields by name and applies aliases itself. Fields with one key are merged, as
    GraphQL merges them.

    type_name None means the object's type isn't known: every fragment applies (see
    _fragment_applies). A field in leaf_fields gets no "selections": its value is
    copied as is.
    """
    groups: dict[str, list[Any]] = {}
    for node in _iter_selected_fields(selection_set, fragments, type_name, schema):
        key = node.alias.value if by_alias and node.alias else node.name.value
        groups.setdefault(key, []).append(node)
    fields = []
    for key, nodes in groups.items():
        name = nodes[0].name.value
        entry: dict[str, Any] = {"name": name, "alias": key}
        sub_selection_set = _merged_selection_set(nodes)
        if sub_selection_set is not None and name not in leaf_fields:
            field_type = _graphql_named_type(schema, parent_type, name)
            entry["selections"] = _selection(
                sub_selection_set, fragments, schema, field_type, by_alias=by_alias
            )
        fields.append(entry)
    return fields


def _selection(
    selection_set: Any, fragments: dict[str, Any], schema: Any, field_type: Any, *, by_alias: bool
) -> dict[str, Any]:
    """The selection of a field's value: ``{"fields", "__type"?, "__on"?}``.

    For an object type, "__type" names it: Rust gives it as __typename to an object
    whose data has none. For an interface or union (#573), "__on" holds, for each
    possible object type, the fields GraphQL collects for it, and Rust picks the list
    by the object's __typename. "fields" then holds the fields of every fragment, for
    data without __typename.
    """
    type_name = _concrete_type_name(field_type)
    selection: dict[str, Any] = {
        "fields": _selected_fields(
            selection_set, fragments, schema, type_name, field_type, by_alias=by_alias
        )
    }
    if type_name is not None:
        selection["__type"] = type_name
    elif schema is not None and is_abstract_type(field_type):
        selection["__on"] = {
            object_type.name: _selected_fields(
                selection_set, fragments, schema, object_type.name, object_type, by_alias=by_alias
            )
            for object_type in schema.get_possible_types(field_type)
        }
    return selection


def _response_selections(
    info: GraphQLResolveInfo | None,
    success_type_name: str,
    error_type_name: str,
    *,
    by_alias: bool,
    leaf_fields: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """The selection document for fraiseql_rs.build_mutation_response.

    ``{"format": 2, "success": Selection, "error": Selection}``: what the mutation
    field selects on its result when the result is the success type, and when it is
    the error type. That is the fields selected on the union (__typename), on the type,
    and in fragments that apply to it; nothing selected for a type means only its
    __typename comes back. A Selection is ``{"fields": [{"name", "alias",
    "selections"?}], "__type"?, "__on"?}`` (see _selected_fields and _selection), so a
    field named "fields" or "__on" can't collide with the document's own keys.

    by_alias picks response keys (HTTP mode, where Rust's response goes to the client
    as is, so the document also asks for ``__typename`` only where it is selected:
    ``"typename": "selected"``) or field names (graphql-core completes the result,
    and reads every object's ``__typename``). Fields in leaf_fields,
    such as cascade (filtered on its own), are copied without a sub-selection.
    """
    schema = _real_schema(info)
    fragments = _info_fragments(info)
    field_nodes = list(getattr(info, "field_nodes", None) or [])
    selection_set = _merged_selection_set(field_nodes) if field_nodes else None

    def for_type(type_name: str) -> dict[str, Any]:
        object_type = schema.type_map.get(type_name) if schema is not None else None
        fields = (
            _selected_fields(
                selection_set,
                fragments,
                schema,
                type_name,
                object_type,
                by_alias=by_alias,
                leaf_fields=leaf_fields,
            )
            if selection_set is not None
            else []
        )
        return {"__type": type_name, "fields": fields}

    document = {
        "format": SELECTION_FORMAT,
        "success": for_type(success_type_name),
        "error": for_type(error_type_name),
    }
    if by_alias:
        # The response goes to the client as is: __typename only where selected.
        # graphql-core, completing the result otherwise, reads it to resolve the
        # union, an interface, and drops it where it isn't selected.
        document["typename"] = "selected"
    return document


def _object_type_name(annotation: Any) -> str | None:
    """The name of an entity annotation, or None for an interface (it names no object)."""
    definition = getattr(annotation, "__fraiseql_definition__", None)
    if getattr(definition, "kind", None) == "interface":
        return None
    return annotation.__name__


def _without_none(annotation: Any) -> tuple[Any, bool]:
    """``(T, True)`` for ``T | None`` (or ``Optional[T]``), else ``(annotation, False)``."""
    if get_origin(annotation) in (Union, types.UnionType):
        members = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(members) == 1 and len(members) < len(get_args(annotation)):
            return members[0], True
    return annotation, False


def _hook_accepts_info(hook: Callable) -> bool:
    """Return whether a prepare_input hook takes info as a second positional argument."""
    try:
        params = inspect.signature(hook).parameters.values()
    except (TypeError, ValueError):
        return False
    positional = [
        p
        for p in params
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    return len(positional) >= 2 or any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)


class MutationDefinition:
    """Definition of a PostgreSQL-backed mutation."""

    def __init__(
        self,
        mutation_class: type,
        function_name: str | None = None,
        schema: str | None = None,
        context_params: dict[str, str] | None = None,
        error_config: MutationErrorConfig | None = None,
        enable_cascade: bool = False,
        graphql_name: str | None = None,
        result_name: str | None = None,
    ) -> None:
        self.mutation_class = mutation_class
        self.name = mutation_class.__name__

        # GraphQL field name chosen with name=, used as given. When None, the schema
        # builder derives it from the class name (see MutationTypeBuilder).
        self.graphql_name = graphql_name
        # The preferred field name, used as given, when it doesn't come from the
        # class name (auto-discovery sets it from the @fraiseql:mutation comment).
        # None means the class-derived name.
        self.default_graphql_name: str | None = None
        # Result union name chosen with result_name=, used as given. When None, the
        # schema builder names the union after the field (see MutationTypeBuilder).
        self.result_name = result_name

        # Store the provided schema for lazy resolution
        self._provided_schema = schema
        self._resolved_schema = None  # Will be resolved lazily
        self._provided_error_config = error_config  # Store provided value
        self._resolved_error_config = None  # Lazy resolution

        self.context_params = context_params or {}
        self.enable_cascade = enable_cascade

        # Get type hints
        hints = get_type_hints(mutation_class)
        self._annotated_members = frozenset(hints)
        self.input_type = hints.get("input")
        self.success_type = hints.get("success")
        self.error_type = hints.get("error")

        # Derive function name from class name if not provided
        if function_name:
            self.function_name = function_name
        else:
            # Convert CamelCase to snake_case
            # CreateUser -> create_user
            self.function_name = _camel_to_snake(self.name)

        # Derive entity field name and type from success type
        self.entity_nullable = False  # set by _derive_entity_info
        self.entity_field_name, self.entity_type = self._derive_entity_info()

        # Optional input hook; its signature is inspected once here, not per request
        self.prepare_input = getattr(mutation_class, "prepare_input", None)
        self.prepare_input_takes_info = self.prepare_input is not None and _hook_accepts_info(
            self.prepare_input
        )

    def member_problems(self) -> list[str]:
        """What's wrong with the class's members, one message each; empty if nothing.

        A class mutation needs ``input:`` and at least one of ``success:`` and
        ``error:``, and reads nothing but those and ``prepare_input``. Members
        inherited from base classes and mixins count. Names starting with ``_``
        are left alone, so private helpers are allowed.

        Checked when the schema is built (``MutationTypeBuilder.build``), not at
        decoration, so a schema build reports every faulty mutation at once.
        """
        problems = []
        if self.input_type is None:
            problems.append(
                f"Mutation {self.name} has no `input:` annotation. A class mutation "
                "passes one input object to its SQL function; for a mutation without "
                "arguments, write a function mutation: "
                f"`@fraiseql.mutation async def {_camel_to_snake(self.name)}(info) -> ...`."
            )
        if self.success_type is None and self.error_type is None:
            problems.append(
                f"Mutation {self.name} has neither `success:` nor `error:`: annotate "
                "its success type and error type."
            )
        for member, annotation in (("success", self.success_type), ("error", self.error_type)):
            if annotation is not None and not isinstance(annotation, type):
                problems.append(
                    f"Mutation {self.name} has `{member}: {_type_display(annotation)}`: a "
                    f"class mutation has one {member} type, a @fraiseql.{member} class. "
                    "The function's status picks the success or the error type; tell "
                    "errors apart by their `status` and `code`."
                )
        members = set(self._annotated_members)
        for klass in self.mutation_class.__mro__:
            if klass is not object:
                members.update(vars(klass))
        unknown = {member for member in members if not member.startswith("_")}
        for member in sorted(unknown - _CLASS_MUTATION_MEMBERS):
            message = (
                f"Mutation {self.name} has `{member}`, which fraiseql doesn't read: a "
                "class mutation reads only `input:`, `success:`, `error:` and "
                "`prepare_input`."
            )
            if member in _ERROR_TYPE_MISNAMES:
                message += " For the error type, use `error:`."
            elif member == "resolve":
                message += (
                    " A class mutation calls its SQL function and never calls "
                    "`resolve`. To run your own code, write a function mutation "
                    "(`@fraiseql.mutation async def ...`), or reshape the input in "
                    "`prepare_input`."
                )
            problems.append(message)
        return problems

    def _derive_entity_info(self) -> tuple[str | None, str | None]:
        """Derive entity field name and type from success type annotations.

        Returns:
            Tuple of (entity_field_name, entity_type)
        """
        if not isinstance(self.success_type, type):
            # None, or an annotation member_problems reports (success: A | B)
            return None, None

        # Get annotations from the success type; an optional entity (note: Note | None)
        # is read as its type, and remembered as nullable
        success_hints = {}
        self.entity_nullable = False
        nullable_fields = set()
        for name, hint in get_type_hints(self.success_type).items():
            success_hints[name], nullable = _without_none(hint)
            if nullable:
                nullable_fields.add(name)

        # Look for common entity field names
        entity_fields = [
            "user",
            "post",
            "comment",
            "tag",
            "organization",
            "project",
            "task",
            "location",
            "category",
            "item",
            "entity",
        ]

        for field_name, field_type in success_hints.items():
            if field_name in entity_fields:
                # Get the type name (e.g., "User" from <class 'User'>)
                type_name = getattr(field_type, "__name__", None)
                if type_name:
                    self.entity_nullable = field_name in nullable_fields
                    return field_name, _object_type_name(field_type)

        # Fallback: try to find any field that looks like an entity
        for field_name, field_type in success_hints.items():
            # Skip common non-entity fields
            if field_name in ["id", "message", "success", "error", "errors", "code", "status"]:
                continue

            # If it's a type (class), assume it's the entity
            if hasattr(field_type, "__name__"):
                self.entity_nullable = field_name in nullable_fields
                return field_name, _object_type_name(field_type)

        return None, None

    @property
    def schema(self) -> str:
        """Get the schema, resolving it lazily if needed."""
        if self._resolved_schema is None:
            self._resolved_schema = self._resolve_schema(self._provided_schema)
        return self._resolved_schema

    @schema.setter
    def schema(self, value: str) -> None:
        """Allow setting the schema directly for testing."""
        self._resolved_schema = value

    def _resolve_schema(self, provided_schema: str | None) -> str:
        """Resolve the schema to use, considering defaults from config."""
        # If schema was explicitly provided, use it
        if provided_schema is not None:
            return provided_schema

        # Try to get default from registry config
        try:
            from fraiseql.gql.builders.registry import SchemaRegistry

            registry = SchemaRegistry.get_instance()

            if registry.config and hasattr(registry.config, "default_mutation_schema"):
                return registry.config.default_mutation_schema
        except ImportError:
            pass

        # Fall back to "public" as per feature requirements
        return "public"

    @property
    def error_config(self) -> MutationErrorConfig | None:
        """Get the error config, resolving it lazily if needed."""
        if self._resolved_error_config is None:
            self._resolved_error_config = self._resolve_error_config(self._provided_error_config)
        return self._resolved_error_config

    def _resolve_error_config(
        self, provided_error_config: MutationErrorConfig | None
    ) -> MutationErrorConfig | None:
        """Resolve the error config to use, considering defaults from config.

        Resolution order:
        1. Explicit error_config parameter on decorator (highest priority)
        2. default_error_config from FraiseQLConfig
        3. None (no error configuration)
        """
        # If error_config was explicitly provided, use it (even if None)
        if provided_error_config is not None:
            return provided_error_config

        # Try to get default from registry config
        try:
            from fraiseql.gql.builders.registry import SchemaRegistry

            registry = SchemaRegistry.get_instance()

            if registry.config and hasattr(registry.config, "default_error_config"):
                return registry.config.default_error_config
        except ImportError:
            pass

        # Fall back to None (no error configuration)
        return None

    def _get_cascade_selections(self, info: GraphQLResolveInfo) -> str | None:
        """Extract CASCADE selections from GraphQL query if enabled."""
        if not self.enable_cascade:
            return None

        from fraiseql.mutations.cascade_selections import extract_cascade_selections

        return extract_cascade_selections(info)

    def validate_types(self) -> None:
        """Validate Success and Error types conform to v1.8.0 requirements."""
        # Validate Success type
        if not self.success_type:
            raise ValueError(f"Mutation {self.name} must have a success type")

        success_type_name = getattr(self.success_type, "__name__", "Success")
        if not hasattr(self.success_type, "__annotations__"):
            raise ValueError(f"Success type {success_type_name} must have annotations")

        success_annotations = self.success_type.__annotations__

        # Success must have entity field
        entity_field = self._get_entity_field_name()
        if entity_field not in success_annotations:
            raise ValueError(
                f"Success type {success_type_name} must have '{entity_field}' field. "
                f"v1.8.0 requires Success types to always have non-null entity."
            )

        # Entity field must NOT be Optional
        entity_type = success_annotations[entity_field]
        if self._is_optional(entity_type):
            raise ValueError(
                f"Success type {success_type_name} has nullable entity field. "
                f"v1.8.0 requires entity to be non-null. "
                f"Change '{entity_field}: {entity_type}' to non-nullable type."
            )

        # Validate Error type
        if not self.error_type:
            raise ValueError(f"Mutation {self.name} must have an error type")

        error_type_name = getattr(self.error_type, "__name__", "Error")
        if not hasattr(self.error_type, "__annotations__"):
            raise ValueError(f"Error type {error_type_name} must have annotations")

        error_annotations = self.error_type.__annotations__

        # NOTE: code field validation REMOVED (v1.8.1)
        # The 'code' field is now auto-injected by @fraiseql.error decorator
        # No manual definition required - automatically added to all Error types

        # Error must have status field
        if "status" not in error_annotations:
            raise ValueError(f"Error type {error_type_name} must have 'status: str' field.")

        # Error must have message field
        if "message" not in error_annotations:
            raise ValueError(f"Error type {error_type_name} must have 'message: str' field.")

    def _get_entity_field_name(self) -> str:
        """Get entity field name from Success type.

        Looks for common patterns: entity, <lowercase_type>, etc.
        """
        if not self.success_type:
            raise ValueError("Success type not set")

        annotations = self.success_type.__annotations__

        # Common patterns
        if "entity" in annotations:
            return "entity"

        # Try lowercase type name (e.g., CreateMachineSuccess → machine)
        mutation_name = getattr(self.success_type, "__name__", "").replace("Success", "")
        entity_name_candidate = mutation_name.lower()
        if entity_name_candidate in annotations:
            return entity_name_candidate

        # Fallback: first non-standard field
        standard_fields = {"cascade", "message", "updated_fields", "code", "status"}
        for field in annotations:
            if field not in standard_fields:
                return field

        raise ValueError(
            f"Could not determine entity field name for {getattr(self.success_type, '__name__', 'Success')}. "  # noqa: E501
            f"Expected 'entity' or lowercase mutation name."
        )

    def _is_optional(self, type_hint: Any) -> bool:
        """Check if type hint is Optional (includes None)."""
        import typing

        # Check for X | None (Python 3.10+)
        if hasattr(typing, "get_args") and hasattr(typing, "get_origin"):
            origin = typing.get_origin(type_hint)
            if origin is typing.Union:
                args = typing.get_args(type_hint)
                return type(None) in args

        # Check for Optional[X] (older syntax)
        return getattr(type_hint, "__origin__", None) is typing.Union and type(None) in getattr(
            type_hint, "__args__", []
        )

    def create_resolver(self) -> Callable:
        """Create the GraphQL resolver function."""

        async def resolver(info: GraphQLResolveInfo, input: dict[str, Any]) -> Any:
            """Auto-generated resolver for PostgreSQL mutation."""
            # Get database connection
            db = info.context.get("db")
            if not db:
                msg = "No database connection in context"
                raise RuntimeError(msg)

            # Convert input to dict
            input_data = _to_dict(input)

            # Call prepare_input hook if defined on mutation class. It may be async and
            # may take info (#557). It runs before a pool connection is acquired, so a
            # slow call in the hook doesn't hold one.
            if self.prepare_input is not None:
                if self.prepare_input_takes_info:
                    prepared = self.prepare_input(input_data, info)
                else:
                    prepared = self.prepare_input(input_data)
                input_data = await prepared if inspect.isawaitable(prepared) else prepared

            # Call PostgreSQL function via Rust executor
            from fraiseql.mutations.rust_executor import execute_mutation_rust

            full_function_name = f"{self.schema}.{self.function_name}"
            # In HTTP mode (set by the FastAPI routers) Rust's response goes to the client
            # as is, so it is keyed by response keys: the field's alias, or its name.
            # Otherwise graphql-core completes the result and reads fields by name, and
            # the root key only has to match below.
            http_mode = info.context.get("_http_mode", False)
            path_key = getattr(getattr(info, "path", None), "key", None)
            if http_mode and isinstance(path_key, str):
                field_name = path_key
            else:
                field_name = self.name[0].lower() + self.name[1:] if self.name else self.name
            success_type_name = getattr(self.success_type, "__name__", "Success")  # type: ignore[attr-defined]
            error_type_name = getattr(self.error_type, "__name__", "Error")

            # Extract context arguments
            context_args = []
            if self.context_params:
                for context_key in self.context_params:
                    context_value = info.context.get(context_key)
                    if context_value is None:
                        msg = (
                            f"Required context parameter '{context_key}' "
                            f"not found in GraphQL context"
                        )
                        raise RuntimeError(msg)

                    # Extract specific field if it's a UserContext object
                    if hasattr(context_value, "user_id") and context_key == "user":
                        context_args.append(context_value.user_id)
                    else:
                        context_args.append(context_value)

            # Get connection pool from repository
            # db is a FraiseQLRepository, we need to get the underlying pool
            pool = db.get_pool() if hasattr(db, "get_pool") else db._pool

            # Call Rust executor with a connection from the pool
            async with pool.connection() as conn:
                # Set session variables (started_at, tenant_id, etc.) before mutation
                async with conn.cursor() as setup_cursor:
                    await db._set_session_variables(setup_cursor)

                logger.debug(f"Executing mutation {self.name} with function {full_function_name}")
                logger.debug(f"Input data keys: {list(input_data.keys()) if input_data else None}")
                logger.debug(f"Success type: {success_type_name}, Error type: {error_type_name}")

                # What the query selects on the success and error types, down to the
                # entity's nested fields (#525, #581, #573); Rust returns only that
                selections_json = json.dumps(
                    _response_selections(
                        info,
                        success_type_name,
                        error_type_name,
                        by_alias=http_mode,
                        leaf_fields=frozenset({"cascade"}) if self.enable_cascade else frozenset(),
                    )
                )
                logger.debug(f"Response selections: {selections_json}")

                # Extract CASCADE selections from GraphQL query
                cascade_selections_json = self._get_cascade_selections(info)

                try:
                    rust_response = await execute_mutation_rust(
                        conn=conn,
                        function_name=full_function_name,
                        input_data=input_data,
                        field_name=field_name,
                        success_type=success_type_name,
                        error_type=error_type_name,
                        entity_field_name=self.entity_field_name,
                        entity_type=_request_entity_type(
                            info, success_type_name, self.entity_field_name, self.entity_type
                        )
                        if self.entity_field_name
                        else None,
                        context_args=context_args or None,
                        cascade_selections=cascade_selections_json,
                        success_type_class=self.success_type,
                        selections=selections_json,
                        entity_nullable=self.entity_nullable,
                    )
                    logger.debug(f"Mutation {self.name} executed successfully")
                except Exception as e:
                    logger.error(
                        f"Mutation {self.name} failed during execution",
                        extra={
                            "function": full_function_name,
                            "success_type": success_type_name,
                            "error_type": error_type_name,
                            "entity_field_name": self.entity_field_name,
                            "entity_type": self.entity_type,
                            "input_keys": list(input_data.keys()) if input_data else None,
                            "error": str(e),
                        },
                    )
                    raise

            # HTTP mode: return RustResponseBytes directly for performance
            # Non-HTTP mode: parse and return Python objects for direct GraphQL execution
            if http_mode:
                # RUST-FIRST PATH: Return RustResponseBytes directly to HTTP
                # This bypasses Python JSON parsing entirely for maximum performance
                # PostgreSQL → Rust → HTTP bytes (zero Python string operations)
                return rust_response

            # NON-HTTP PATH: Convert to dict for GraphQL execute()
            # Used in tests and direct GraphQL execute() calls
            try:
                graphql_response = rust_response.to_json()
                mutation_result = graphql_response["data"][field_name]
                logger.debug(f"Parsed GraphQL response for field '{field_name}'")
            except Exception as e:
                logger.error(
                    f"Failed to parse GraphQL response for mutation {self.name}",
                    extra={
                        "field_name": field_name,
                        "error": str(e),
                        "response_type": type(rust_response).__name__,
                    },
                )
                raise

            # Return dict directly (no parsing into Python objects)
            # CASCADE is already at correct level from Rust
            # Tests will work with dict access: result["user"]["id"]
            return mutation_result

        # Set metadata for GraphQL introspection
        # Create unique resolver name to prevent collisions between similar mutation names
        # Add the PostgreSQL function name as disambiguation when available
        base_name = to_snake_case(self.name)
        if hasattr(self, "function_name") and self.function_name:
            # Use function name to ensure uniqueness (e.g., create_item vs create_item_component)
            resolver_name = self.function_name
        else:
            resolver_name = base_name

        resolver.__name__ = resolver_name
        resolver.__doc__ = self.mutation_class.__doc__ or f"Mutation for {self.name}"

        # Store mutation definition for schema building
        resolver.__fraiseql_mutation__ = self

        # Set proper annotations for the resolver. The result union is named at
        # schema build (MutationTypeBuilder), where every mutation's name is known.
        if self.success_type and self.error_type:
            # Check if success and error types are the same (single result type pattern)
            if self.success_type is self.error_type:
                # Single result type used for both success and error - no union needed
                return_type = self.success_type
            else:
                return_type = self.success_type | self.error_type
        else:
            return_type = self.success_type or self.error_type

        # Create a fresh annotations dict to avoid any shared reference issues
        set_annotations(resolver, {"input": self.input_type, "return": return_type})

        return resolver


def mutation(
    _cls: type[T] | Callable[..., Any] | None = None,
    *,
    function: str | None = None,
    schema: str | None = None,
    context_params: dict[str, str] | None = None,
    error_config: MutationErrorConfig | None = None,
    enable_cascade: bool = False,
    authorizer: Any | None = None,
    name: str | None = None,
    result_name: str | None = None,
) -> type[T] | Callable[[type[T]], type[T]] | Callable[..., Any]:
    """Decorator to define GraphQL mutations with PostgreSQL function backing.

    This decorator supports both simple function-based mutations and sophisticated
    class-based mutations with structured success/error handling. Class-based mutations
    automatically call PostgreSQL functions and parse results into typed responses.

    Args:
        _cls: The mutation function or class to decorate (when used without parentheses)
        function: PostgreSQL function name (defaults to snake_case of class name).
            It only picks the SQL function: any number of mutations may share one.
        schema: PostgreSQL schema containing the function (defaults to the config's
            ``default_mutation_schema``, ``"public"``)
        context_params: Maps GraphQL context keys to PostgreSQL function parameter names
        error_config: Optional configuration for error detection behavior
        enable_cascade: Enable GraphQL cascade functionality to include side effects in response
        authorizer: Optional per-operation :class:`~fraiseql.security.Authorizer`
            override (issue #362). It takes precedence over the global default
            authorizer for this mutation only.
        name: GraphQL field name, used as given. By default a class mutation is
            named after its class (``CreatePost`` -> ``createPost``) and a function
            mutation after the function. In fraiseql 1.x, a class mutation whose
            ``function=`` differs from its class name keeps the name taken from
            ``function=`` and the schema build emits a ``FutureWarning``; pass
            ``name=`` to keep that name or choose another.
        result_name: GraphQL name of the result union (``success | error``), used as
            given. By default it is the field name plus ``Result``
            (``createPost`` -> ``CreatePostResult``), one union per mutation. In
            fraiseql 1.x, a mutation whose union was named after its success type
            (``PostSuccess`` -> ``PostResult``) keeps that name and the schema build
            emits a ``FutureWarning``; pass ``result_name=`` to keep it or choose
            another. Ignored when there is no union (same success and error type).

    Returns:
        Decorated mutation with automatic PostgreSQL function integration

    Examples:
        Simple function-based mutation::\

            @fraiseql.mutation
            async def create_user(info, input: CreateUserInput) -> User:
                db = info.context["db"]
                # Use SQL function for business logic
                result = await db.execute_function("fn_create_user", {
                    "name": input.name,
                    "email": input.email
                })
                return await db.find_one("v_user", "user", info, id=result["id"])

        Basic class-based mutation::\

            @fraiseql.mutation
            class CreateUser:
                input: CreateUserInput
                success: CreateUserSuccess
                error: CreateUserError

            # This automatically calls PostgreSQL function: public.create_user(input)
            # and parses the result into either CreateUserSuccess or CreateUserError

        Mutation with custom PostgreSQL function::\

            @fraiseql.mutation(function="register_new_user", schema="auth")
            class RegisterUser:
                input: RegistrationInput
                success: RegistrationSuccess
                error: RegistrationError

            # Calls: auth.register_new_user(input) instead of default name

        Mutation with context parameters::\

            @fraiseql.mutation(
                function="create_location",
                schema="app",
                context_params={
                    "tenant_id": "input_pk_organization",
                    "user": "input_created_by"
                }
            )
            class CreateLocation:
                input: CreateLocationInput
                success: CreateLocationSuccess
                error: CreateLocationError

            # Calls: app.create_location(tenant_id, user_id, input)
            # Where tenant_id comes from info.context["tenant_id"]
            # And user_id comes from info.context["user"].user_id

        Mutation with validation and error handling::\

            @fraise_input
            class UpdateUserInput:
                id: UUID
                name: str | None = None
                email: str | None = None

            @fraise_type
            class UpdateUserSuccess:
                user: User
                message: str

            @fraise_type
            class UpdateUserError:
                code: str
                message: str
                field: str | None = None

            @fraiseql.mutation
            async def update_user(info, input: UpdateUserInput) -> User:
                db = info.context["db"]
                user_context = info.context.get("user")

                # Authorization check
                if not user_context:
                    raise GraphQLError("Authentication required")

                # Validation
                if input.email and not is_valid_email(input.email):
                    raise GraphQLError("Invalid email format")

                # Update logic
                updates = {}
                if input.name:
                    updates["name"] = input.name
                if input.email:
                    updates["email"] = input.email

                if not updates:
                    raise GraphQLError("No fields to update")

                # Writes go through a PostgreSQL function; the view reads the result
                await db.execute_function("fn_update_user", {"id": str(input.id), **updates})
                return await db.find_one(
                    "v_user", "updateUser", info, where={"id": {"eq": input.id}}
                )

        Multi-step mutation with transaction::\

            @fraiseql.mutation
            async def transfer_funds(
                info,
                input: TransferInput
            ) -> TransferResult:
                db = info.context["db"]

                async def transfer(conn):
                    # One transaction: either both balances change or neither does
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "UPDATE tb_account SET balance = balance - %s "
                            "WHERE id = %s AND balance >= %s RETURNING balance",
                            (input.amount, input.source_account_id, input.amount),
                        )
                        source = await cur.fetchone()
                        if source is None:
                            raise GraphQLError("Insufficient funds")

                        await cur.execute(
                            "UPDATE tb_account SET balance = balance + %s "
                            "WHERE id = %s RETURNING balance",
                            (input.amount, input.destination_account_id),
                        )
                        dest = await cur.fetchone()
                        if dest is None:
                            raise GraphQLError("Destination account not found")

                        await cur.execute(
                            "INSERT INTO tb_transfer (source_account_id, "
                            "destination_account_id, amount) VALUES (%s, %s, %s) "
                            "RETURNING id",
                            (input.source_account_id, input.destination_account_id,
                             input.amount),
                        )
                        (transfer_id,) = await cur.fetchone()

                    return TransferResult(
                        transfer_id=transfer_id,
                        new_source_balance=source[0],
                        new_dest_balance=dest[0],
                    )

                # Rolled back if transfer raises
                return await db.run_in_transaction(transfer)

        Mutation with file upload handling::\

            @fraiseql.mutation
            async def upload_avatar(
                info,
                input: UploadAvatarInput  # Contains file: Upload field
            ) -> User:
                db = info.context["db"]
                storage = info.context["storage"]
                user_context = info.context["user"]

                if not user_context:
                    raise GraphQLError("Authentication required")

                # Process file upload
                file_content = await input.file.read()
                if len(file_content) > 5 * 1024 * 1024:  # 5MB limit
                    raise GraphQLError("File too large")

                # Store file
                file_url = await storage.store_user_avatar(
                    user_context.user_id,
                    file_content,
                    input.file.content_type
                )

                # Update user record
                await db.execute_function(
                    "fn_update_user",
                    {"id": str(user_context.user_id), "avatar_url": file_url},
                )
                return await db.find_one(
                    "v_user", "uploadAvatar", info, where={"id": {"eq": user_context.user_id}}
                )

        Mutation with input transformation using prepare_input hook::\

            @fraise_input
            class NetworkConfigInput:
                ip_address: str
                subnet_mask: str

            @fraiseql.mutation
            class CreateNetworkConfig:
                input: NetworkConfigInput
                success: NetworkConfigSuccess
                error: NetworkConfigError

                @staticmethod
                def prepare_input(input_data: dict) -> dict:
                    \"\"\"Transform IP + subnet mask to CIDR notation before database call.\"\"\"
                    ip = input_data.get("ip_address")
                    mask = input_data.get("subnet_mask")

                    if ip and mask:
                        # Convert subnet mask to CIDR prefix
                        cidr_prefix = {
                            "255.255.255.0": 24,
                            "255.255.0.0": 16,
                            "255.0.0.0": 8,
                        }.get(mask, 32)

                        return {
                            "ip_address": f"{ip}/{cidr_prefix}",
                            # subnet_mask field is removed
                        }
                    return input_data

            # Frontend sends: { ipAddress: "192.168.1.1", subnetMask: "255.255.255.0" }
            # Database receives: { ip_address: "192.168.1.1/24" }

        Mutation with empty string to null conversion::\

            @fraise_input
            class UpdateNoteInput:
                id: UUID
                notes: str | None = None

            @fraiseql.mutation
            class UpdateNote:
                input: UpdateNoteInput
                success: UpdateNoteSuccess
                error: UpdateNoteError

                @staticmethod
                def prepare_input(input_data: dict) -> dict:
                    \"\"\"Convert empty strings to None for nullable fields.\"\"\"
                    result = input_data.copy()

                    # Convert empty strings to None for optional string fields
                    if "notes" in result and result["notes"] == "":
                        result["notes"] = None

                    return result

            # Frontend sends: { id: "...", notes: "" }
            # Database receives: { id: "...", notes: null }

        Mutation with an async prepare_input hook that takes info::\

            @fraiseql.mutation(enable_cascade=True)
            class CreateContract:
                input: CreateContractInput
                success: CreateContractSuccess
                error: CreateContractError

                @staticmethod
                async def prepare_input(input_data: dict, info: GraphQLResolveInfo) -> dict:
                    \"\"\"Resolve the provider's company identifier before the SQL call.\"\"\"
                    registry = info.context["company_registry"]
                    provider = await registry.lookup(input_data["siret"])
                    return {**input_data, "provider": provider}

        prepare_input can take three forms:

        - ``def prepare_input(input_data: dict) -> dict``
        - ``async def prepare_input(input_data: dict) -> dict``
        - ``def`` or ``async def prepare_input(input_data: dict, info) -> dict``,
          which receives the resolver's GraphQL ``info`` (and so ``info.context``)

        A hook is passed ``info`` when it takes a second positional parameter or
        ``*args``; the signature is inspected once, when the mutation is defined.

    PostgreSQL Function Requirements:
        For class-based mutations, the PostgreSQL function should:

        1. Accept input as JSONB parameter
        2. Return a result with 'success' boolean field
        3. Include either 'data' field (success) or 'error' field (failure)

        Example PostgreSQL function::\

            CREATE OR REPLACE FUNCTION graphql.create_user(input jsonb)
            RETURNS jsonb
            LANGUAGE plpgsql
            AS $$
            DECLARE
                user_id uuid;
                result jsonb;
            BEGIN
                -- Insert user
                INSERT INTO users (name, email, created_at)
                VALUES (
                    input->>'name',
                    input->>'email',
                    now()
                )
                RETURNING id INTO user_id;

                -- Return success response
                result := jsonb_build_object(
                    'success', true,
                    'data', jsonb_build_object(
                        'id', user_id,
                        'name', input->>'name',
                        'email', input->>'email',
                        'message', 'User created successfully'
                    )
                );

                RETURN result;
            EXCEPTION
                WHEN unique_violation THEN
                    -- Return error response
                    result := jsonb_build_object(
                        'success', false,
                        'error', jsonb_build_object(
                            'code', 'EMAIL_EXISTS',
                            'message', 'Email address already exists',
                            'field', 'email'
                        )
                    );
                    RETURN result;
            END;
            $$;

    Notes:
        - Function-based mutations provide full control over implementation
        - Class-based mutations automatically integrate with PostgreSQL functions
        - Use transactions for multi-step operations to ensure data consistency
        - PostgreSQL functions handle validation and business logic at the database level
        - Context parameters enable tenant isolation and user tracking
        - Success/error types provide structured response handling
        - All mutations are automatically registered with the GraphQL schema
        - The prepare_input hook allows transforming input data before database calls
        - prepare_input is called after GraphQL validation but before the PostgreSQL function
        - prepare_input runs before a database connection is taken from the pool, so a
          slow call in an async hook doesn't hold a connection
        - An exception raised in prepare_input becomes a top-level GraphQL error
        - Use prepare_input for multi-field transformations, empty string normalization, etc.
    """

    def decorator(
        cls_or_fn: type[T] | Callable[..., Any],
    ) -> type[T] | Callable[..., Any]:
        # Import here to avoid circular imports
        from fraiseql.gql.schema_builder import SchemaRegistry

        registry = SchemaRegistry.get_instance()

        # Check if it's a function (simple mutation pattern)
        if callable(cls_or_fn) and not isinstance(cls_or_fn, type):
            # It's a function-based mutation
            fn = cls_or_fn

            # Store metadata for schema building
            fn.__fraiseql_mutation__ = True
            fn.__fraiseql_resolver__ = fn
            # Per-operation authorizer override (issue #362).
            fn.__fraiseql_authorizer__ = authorizer
            fn.__fraiseql_graphql_name__ = name
            fn.__fraiseql_result_name__ = result_name

            # Auto-register with schema
            registry.register_mutation(fn)

            return fn

        # Otherwise, it's a class-based mutation
        cls = cls_or_fn
        # Create mutation definition
        definition = MutationDefinition(
            cls,
            function,
            schema,
            context_params,
            error_config,
            enable_cascade,
            name,
            result_name,
        )

        # Store definition on the class
        cls.__fraiseql_mutation__ = definition

        # Create and store resolver
        cls.__fraiseql_resolver__ = definition.create_resolver()
        # Per-operation authorizer override (issue #362) — set on the resolver fn the
        # registry stores, so resolve_authorizer can read it at resolve time.
        cls.__fraiseql_resolver__.__fraiseql_authorizer__ = authorizer

        # Auto-register with schema
        registry.register_mutation(cls)

        return cls

    if _cls is None:
        return decorator
    return decorator(_cls)


def _type_display(annotation: Any) -> str:
    """An annotation as written: ``NotFound | Conflict``, ``list[Item]``."""
    args = get_args(annotation)
    if args and get_origin(annotation) in (Union, types.UnionType):
        return " | ".join(_type_display(arg) for arg in args)
    return getattr(annotation, "__name__", None) or repr(annotation)


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase to snake_case."""
    # Insert underscore before uppercase letters (except at start)
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    # Handle sequences of capitals
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _to_dict(obj: Any) -> dict[str, Any]:
    """Convert an object to a dictionary.

    UNSET values are excluded from the dictionary to enable partial updates.
    Only fields that were explicitly provided (including explicit None) are included.

    Empty strings are converted to None to support frontends that send "" when
    clearing text fields. This aligns with database NULL semantics and prevents
    empty string pollution in the database.
    """
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        # Convert UUIDs to strings for JSON serialization
        # Convert empty strings to None for database compatibility
        result = {}
        for k, v in obj.__dict__.items():
            if not k.startswith("_"):
                if v is UNSET:
                    # Skip UNSET fields entirely - they weren't provided
                    continue
                if hasattr(v, "hex"):  # UUID
                    result[k] = str(v)
                elif hasattr(v, "isoformat"):  # date, datetime, time
                    result[k] = v.isoformat()
                elif isinstance(v, str) and not v.strip():
                    # Convert empty strings to None for database NULL semantics
                    result[k] = None
                else:
                    result[k] = v
        return result
    if isinstance(obj, dict):
        return obj
    msg = f"Cannot convert {type(obj)} to dictionary"
    raise TypeError(msg)


def _filter_cascade_rust(cascade_data: dict, selections_json: str) -> dict:
    """Filter cascade data using Rust implementation.

    Args:
        cascade_data: Raw cascade data from PostgreSQL
        selections_json: JSON string of field selections from GraphQL query

    Returns:
        Filtered cascade data dict

    Raises:
        Exception: If Rust filtering fails (handled by caller)
    """
    import json

    from fraiseql import fraiseql_rs

    # Convert cascade data to JSON
    cascade_json = json.dumps(cascade_data, separators=(",", ":"))

    # Call Rust filter
    filtered_json = fraiseql_rs.filter_cascade_data(cascade_json, selections_json)

    # Parse back to dict
    return json.loads(filtered_json)

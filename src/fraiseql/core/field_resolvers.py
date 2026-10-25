"""Whether a query selects a field resolver, and the typed rows that run it.

``db.find`` and ``db.find_one`` answer with the rows Rust builds from the view's
JSONB, which graphql-core never resolves field by field. A ``@fraiseql.field``
(or ``@fraiseql.dataloader_field``) method of the type is a resolver of its own:
it needs the row as ``self``. So does a nested-array field given a ``where``
(``fraise_field(supports_where_filtering=True)``), which filters the elements.
When the selection holds one, at any depth, find returns typed objects instead,
and graphql-core completes them. Without one the rows still go out as Rust
wrote them, so this check has to be cheap: a schema with no field resolver
answers it without looking at the query.
"""

from collections.abc import Iterable, Mapping
from functools import lru_cache
from typing import Any
from weakref import WeakKeyDictionary

from graphql import (
    BooleanValueNode,
    DocumentNode,
    FieldNode,
    FragmentDefinitionNode,
    FragmentSpreadNode,
    GraphQLSchema,
    InlineFragmentNode,
    OperationDefinitionNode,
    OperationType,
    SelectionSetNode,
    VariableNode,
    get_named_type,
    is_abstract_type,
    is_interface_type,
    is_object_type,
    is_union_type,
    parse,
)

# GraphQLField.extensions key: the field is a method of the type (a resolver),
# or another field graphql-core has to resolve (value True)
FIELD_RESOLVER = "fraiseql_field_resolver"
# FIELD_RESOLVER value: the resolver only changes the value when the query passes
# arguments (nested-array ``where``); without them the Rust rows are right
WITH_ARGUMENTS = "with_arguments"
# GraphQLObjectType.extensions key: the Python class the type was built from
PYTHON_TYPE = "fraiseql_python_type"

# schema -> names of the types a field resolver can be reached from
_reaching_cache: WeakKeyDictionary[GraphQLSchema, frozenset[str]] = WeakKeyDictionary()


def _reaching(schema: GraphQLSchema) -> frozenset[str]:
    """The composite types with a field resolver, on them or below them."""
    cached = _reaching_cache.get(schema)
    if cached is not None:
        return cached

    composite = [
        t
        for name, t in schema.type_map.items()
        if not name.startswith("__")
        and (is_object_type(t) or is_interface_type(t) or is_union_type(t))
    ]
    reach: set[str] = set()
    changed = True
    while changed:  # until no type is added: recursive types reach through each other
        changed = False
        for t in composite:
            if t.name in reach:
                continue
            fields = getattr(t, "fields", None) or {}
            if any(
                (f.extensions or {}).get(FIELD_RESOLVER) or get_named_type(f.type).name in reach
                for f in fields.values()
            ) or (
                is_abstract_type(t) and any(p.name in reach for p in schema.get_possible_types(t))  # type: ignore[arg-type]
            ):
                reach.add(t.name)
                changed = True

    result = frozenset(reach)
    _reaching_cache[schema] = result
    return result


def _included(node: Any, variables: Mapping[str, Any]) -> bool:
    """False for a selection ``@skip(if: true)`` or ``@include(if: false)`` leaves out."""
    for directive in node.directives or ():
        name = directive.name.value
        if name not in ("skip", "include"):
            continue
        for argument in directive.arguments or ():
            if argument.name.value != "if":
                continue
            value = argument.value
            if isinstance(value, BooleanValueNode):
                condition = value.value
            elif isinstance(value, VariableNode):
                condition = variables.get(value.name.value)
            else:
                continue
            if condition is (name == "skip"):
                return False
    return True


def _selects(
    schema: GraphQLSchema,
    reach: frozenset[str],
    fragments: Mapping[str, FragmentDefinitionNode],
    variables: Mapping[str, Any],
    parent: Any,
    selection_set: SelectionSetNode | None,
    spread: frozenset[str] = frozenset(),
) -> bool:
    if selection_set is None or parent is None or parent.name not in reach:
        return False
    # A field of an interface is resolved on the object type the row is
    owners = [parent, *schema.get_possible_types(parent)] if is_abstract_type(parent) else [parent]
    for selection in selection_set.selections:
        if not _included(selection, variables):
            continue
        if isinstance(selection, FieldNode):
            name = selection.name.value
            for owner in owners:
                field = (getattr(owner, "fields", None) or {}).get(name)
                if field is None:
                    continue
                marker = (field.extensions or {}).get(FIELD_RESOLVER)
                if marker is True or (marker == WITH_ARGUMENTS and selection.arguments):
                    return True
                if _selects(
                    schema,
                    reach,
                    fragments,
                    variables,
                    get_named_type(field.type),
                    selection.selection_set,
                    spread,
                ):
                    return True
        elif isinstance(selection, InlineFragmentNode):
            condition = selection.type_condition
            target = schema.get_type(condition.name.value) if condition else parent
            if _selects(
                schema, reach, fragments, variables, target, selection.selection_set, spread
            ):
                return True
        elif isinstance(selection, FragmentSpreadNode):
            name = selection.name.value
            fragment = fragments.get(name)
            if fragment is None or name in spread:
                continue
            target = schema.get_type(fragment.type_condition.name.value)
            if _selects(
                schema,
                reach,
                fragments,
                variables,
                target,
                fragment.selection_set,
                spread | {name},
            ):
                return True
    return False


def selects_field_resolver(info: Any) -> bool:
    """Whether the field ``info`` resolves selects a field resolver, at any depth."""
    schema = getattr(info, "schema", None)
    return_type = getattr(info, "return_type", None)
    if not isinstance(schema, GraphQLSchema) or return_type is None:
        return False
    reach = _reaching(schema)
    named = get_named_type(return_type)
    if named.name not in reach:
        return False
    fragments = getattr(info, "fragments", None) or {}
    variables = getattr(info, "variable_values", None) or {}
    # graphql-core 3.3 holds them in a VariableValues, 3.2 in a dict
    variables = getattr(variables, "coerced", variables)
    return any(
        _selects(schema, reach, fragments, variables, named, node.selection_set)
        for node in getattr(info, "field_nodes", None) or ()
    )


@lru_cache(maxsize=256)
def _parse(query: str) -> DocumentNode:
    # A client sends the same few queries: parse each once (documents aren't changed)
    return parse(query, no_location=True)


def operation_selects_field_resolver(
    schema: GraphQLSchema,
    query: str | DocumentNode,
    operation_name: str | None = None,
    variables: Mapping[str, Any] | None = None,
) -> bool:
    """Whether the query operation selects a field resolver below any root field."""
    reach = _reaching(schema)
    if not reach or schema.query_type is None:
        return False
    try:
        document = _parse(query) if isinstance(query, str) else query
    except Exception:  # graphql-core reports it
        return False
    operations = [d for d in document.definitions if isinstance(d, OperationDefinitionNode)]
    if operation_name is not None:
        operations = [o for o in operations if o.name and o.name.value == operation_name]
    fragments = {
        d.name.value: d for d in document.definitions if isinstance(d, FragmentDefinitionNode)
    }
    return any(
        _selects(
            schema,
            reach,
            fragments,
            variables or {},
            schema.query_type,
            operation.selection_set,
        )
        for operation in operations
        if operation.operation == OperationType.QUERY
    )


def python_type(schema: Any, graphql_type: Any, row: Mapping[str, Any] | None = None) -> Any:
    """The Python class a row of ``graphql_type`` is built as, or None.

    For an interface or a union, the type the row's ``__typename`` names.
    """
    named = get_named_type(graphql_type) if graphql_type is not None else None
    if named is not None and is_abstract_type(named):
        typename = row.get("__typename") if row is not None else None
        named = schema.get_type(typename) if isinstance(typename, str) and schema else None
    if named is None or not is_object_type(named):
        return None
    return (named.extensions or {}).get(PYTHON_TYPE)


def typed_rows(rows: Iterable[Any], cls: Any) -> list[Any]:
    """``cls.from_dict`` of each row that is a dict; anything else as is."""
    from_dict = getattr(cls, "from_dict", None)
    if from_dict is None:
        return list(rows)
    return [from_dict(row) if isinstance(row, dict) else row for row in rows]

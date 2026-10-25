"""Query depth and complexity limits, checked before a request executes.

``FraiseQLConfig.max_query_depth`` and the ``complexity_*`` settings are read by
:meth:`QueryLimits.from_config`; the GraphQL router calls :meth:`QueryLimits.check`
on every request, after APQ has resolved the query text and before any execution
path (graphql-core, the multi-field Rust merge, TurboRouter) runs.

Depth counts nested selections: ``{ users { id } }`` has depth 1, and
``{ users { posts { id } } }`` has depth 2. Fragments add no depth of their own.

Complexity is schema-aware: a scalar costs 1 (times its multiplier), an object
field costs 1 plus its selections, and a list field costs 1 plus its selections
times the list size: the ``limit`` or ``first`` argument when the query passes
one (or its default in the schema), ``complexity_default_list_size`` otherwise.

The introspection fields ``__schema`` and ``__type`` are not counted:
``introspection_policy`` decides who may run them, and the standard introspection
query is deeper than any reasonable depth limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from graphql import (
    FieldNode,
    FragmentDefinitionNode,
    FragmentSpreadNode,
    GraphQLError,
    GraphQLInterfaceType,
    GraphQLObjectType,
    InlineFragmentNode,
    IntValueNode,
    OperationDefinitionNode,
    OperationType,
    VariableNode,
    get_named_type,
    get_nullable_type,
    is_list_type,
    parse,
)

if TYPE_CHECKING:
    from graphql import (
        GraphQLField,
        GraphQLNamedType,
        GraphQLSchema,
        SelectionSetNode,
    )

    from fraiseql.fastapi.config import FraiseQLConfig

_INTROSPECTION_FIELDS = frozenset({"__schema", "__type"})
_LIST_SIZE_ARGUMENTS = ("limit", "first")


@dataclass(frozen=True)
class QueryCost:
    """Depth and complexity of a query."""

    depth: int
    complexity: int


@dataclass(frozen=True)
class QueryLimits:
    """The query limits of a :class:`FraiseQLConfig`; ``None`` is no limit."""

    max_depth: int | None = None
    max_complexity: int | None = None
    default_list_size: int = 10
    field_multipliers: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_config(cls, config: FraiseQLConfig) -> QueryLimits | None:
        """Read the limits from ``config``; ``None`` when no limit is set."""
        if config.max_query_depth is None:
            return None
        return cls(max_depth=config.max_query_depth)

    def measure(
        self,
        schema: GraphQLSchema,
        query: str,
        operation_name: str | None = None,
        variables: dict[str, Any] | None = None,
    ) -> QueryCost | None:
        """Measure ``query``; ``None`` when it does not parse.

        A query that does not parse, or names an operation it does not have, is
        left to execution, which reports the error.
        """
        try:
            document = parse(query)
        except GraphQLError:
            return None

        fragments: dict[str, FragmentDefinitionNode] = {}
        operations: list[OperationDefinitionNode] = []
        for definition in document.definitions:
            if isinstance(definition, FragmentDefinitionNode):
                fragments[definition.name.value] = definition
            elif isinstance(definition, OperationDefinitionNode):
                operations.append(definition)
        if operation_name:
            operations = [op for op in operations if op.name and op.name.value == operation_name]
        if not operations:
            return None

        measurer = _Measurer(
            schema, fragments, variables or {}, self.default_list_size, self.field_multipliers
        )
        depth = complexity = 0
        # Without an operation name only one operation can run; measure them all.
        for operation in operations:
            op_depth, op_complexity = measurer.selection_set(
                operation.selection_set, _root_type(schema, operation.operation)
            )
            depth = max(depth, op_depth)
            complexity = max(complexity, op_complexity)
        return QueryCost(depth=depth, complexity=complexity)

    def check(
        self,
        schema: GraphQLSchema,
        query: str,
        operation_name: str | None = None,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Return a GraphQL error response when ``query`` exceeds a limit, else ``None``."""
        cost = self.measure(schema, query, operation_name, variables)
        if cost is None:
            return None
        if self.max_depth is not None and cost.depth > self.max_depth:
            _log_rejection("depth", cost.depth, self.max_depth, query)
            return _error_response(
                f"Query depth {cost.depth} exceeds the maximum depth of {self.max_depth}",
                {"code": "QUERY_TOO_DEEP", "depth": cost.depth, "maxDepth": self.max_depth},
            )
        if self.max_complexity is not None and cost.complexity > self.max_complexity:
            _log_rejection("complexity", cost.complexity, self.max_complexity, query)
            return _error_response(
                f"Query complexity {cost.complexity} exceeds the maximum complexity "
                f"of {self.max_complexity}",
                {
                    "code": "QUERY_TOO_COMPLEX",
                    "complexity": cost.complexity,
                    "maxComplexity": self.max_complexity,
                },
            )
        return None


def _root_type(schema: GraphQLSchema, operation: OperationType) -> GraphQLObjectType | None:
    if operation == OperationType.MUTATION:
        return schema.mutation_type
    if operation == OperationType.SUBSCRIPTION:
        return schema.subscription_type
    return schema.query_type


def _error_response(message: str, extensions: dict[str, Any]) -> dict[str, Any]:
    return {"errors": [{"message": message, "extensions": extensions}]}


def _log_rejection(kind: str, value: int, limit: int, query: str) -> None:
    from fraiseql.audit import get_security_logger
    from fraiseql.audit.security_logger import (
        SecurityEvent,
        SecurityEventSeverity,
        SecurityEventType,
    )

    event_type = (
        SecurityEventType.QUERY_DEPTH_EXCEEDED
        if kind == "depth"
        else SecurityEventType.QUERY_COMPLEXITY_EXCEEDED
    )
    get_security_logger().log_event(
        SecurityEvent(
            event_type=event_type,
            severity=SecurityEventSeverity.WARNING,
            metadata={kind: value, "limit": limit, "query": query[:200]},
        )
    )


class _Measurer:
    """Walk a document against the schema; each fragment is measured once."""

    def __init__(
        self,
        schema: GraphQLSchema,
        fragments: dict[str, FragmentDefinitionNode],
        variables: dict[str, Any],
        default_list_size: int,
        field_multipliers: dict[str, int],
    ) -> None:
        self.schema = schema
        self.fragments = fragments
        self.variables = variables
        self.default_list_size = default_list_size
        self.field_multipliers = field_multipliers
        self._fragment_costs: dict[str, tuple[int, int]] = {}
        self._visiting: set[str] = set()

    def selection_set(
        self, selection_set: SelectionSetNode, parent_type: GraphQLNamedType | None
    ) -> tuple[int, int]:
        """Return (depth below, complexity) of a selection set."""
        depth = complexity = 0
        for selection in selection_set.selections:
            if isinstance(selection, FieldNode):
                sel_depth, sel_complexity = self._field(selection, parent_type)
            elif isinstance(selection, InlineFragmentNode):
                fragment_type = parent_type
                if selection.type_condition is not None:
                    fragment_type = self.schema.get_type(selection.type_condition.name.value)
                sel_depth, sel_complexity = self.selection_set(
                    selection.selection_set, fragment_type
                )
            elif isinstance(selection, FragmentSpreadNode):
                sel_depth, sel_complexity = self._fragment(selection.name.value)
            else:  # pragma: no cover - graphql-core has no other selection kind
                continue
            depth = max(depth, sel_depth)
            complexity += sel_complexity
        return depth, complexity

    def _fragment(self, name: str) -> tuple[int, int]:
        if name in self._fragment_costs:
            return self._fragment_costs[name]
        fragment = self.fragments.get(name)
        if fragment is None or name in self._visiting:
            return 0, 0  # unknown or cyclic: validation rejects the query
        self._visiting.add(name)
        cost = self.selection_set(
            fragment.selection_set, self.schema.get_type(fragment.type_condition.name.value)
        )
        self._visiting.discard(name)
        self._fragment_costs[name] = cost
        return cost

    def _field(self, node: FieldNode, parent_type: GraphQLNamedType | None) -> tuple[int, int]:
        name = node.name.value
        if name in _INTROSPECTION_FIELDS or name == "__typename":
            return 0, 0
        field_def: GraphQLField | None = None
        if isinstance(parent_type, (GraphQLObjectType, GraphQLInterfaceType)):
            field_def = parent_type.fields.get(name)
        multiplier = 1
        if parent_type is not None:
            multiplier = self.field_multipliers.get(f"{parent_type.name}.{name}", multiplier)
        multiplier = self.field_multipliers.get(name, multiplier)
        if node.selection_set is None:
            return 0, multiplier

        child_type = get_named_type(field_def.type) if field_def is not None else None
        depth, complexity = self.selection_set(node.selection_set, child_type)
        size = 1
        if field_def is not None and is_list_type(get_nullable_type(field_def.type)):
            size = self._list_size(node, field_def)
        return depth + 1, multiplier + size * complexity

    def _list_size(self, node: FieldNode, field_def: GraphQLField) -> int:
        arguments = {argument.name.value: argument.value for argument in node.arguments or ()}
        for name in _LIST_SIZE_ARGUMENTS:
            value = arguments.get(name)
            size: Any = None
            if isinstance(value, IntValueNode):
                size = int(value.value)
            elif isinstance(value, VariableNode):
                size = self.variables.get(value.name.value)
            elif value is None and name in field_def.args:
                size = field_def.args[name].default_value
            if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
                return size
        return self.default_list_size

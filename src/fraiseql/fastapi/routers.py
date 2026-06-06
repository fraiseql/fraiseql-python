"""Unified adaptive GraphQL router for all environments."""

import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from graphql import (
    FieldNode,
    FragmentSpreadNode,
    GraphQLSchema,
    InlineFragmentNode,
    OperationDefinitionNode,
    parse,
)
from pydantic import BaseModel, field_validator

from fraiseql.analysis.query_analyzer import QueryAnalyzer
from fraiseql.auth.base import AuthProvider
from fraiseql.core.graphql_parser import RustGraphQLParser
from fraiseql.core.rust_pipeline import RustResponseBytes
from fraiseql.execution.mode_selector import ModeSelector
from fraiseql.execution.unified_executor import UnifiedExecutor
from fraiseql.fastapi.config import FraiseQLConfig, IntrospectionPolicy
from fraiseql.fastapi.dependencies import build_graphql_context
from fraiseql.fastapi.json_encoder import FraiseQLJSONResponse, clean_unset_values
from fraiseql.fastapi.turbo import TurboRegistry, TurboRouter
from fraiseql.graphql.execute import execute_graphql
from fraiseql.optimization.n_plus_one_detector import (
    N1QueryDetectedError,
    configure_detector,
    n1_detection_context,
)

logger = logging.getLogger(__name__)


def _count_root_query_fields(query_string: str, operation_name: str | None = None) -> int:
    """Count root-level query fields in GraphQL query.

    Args:
        query_string: GraphQL query string
        operation_name: Optional operation name for multi-operation queries

    Returns:
        Number of root-level query fields
    """
    try:
        document = parse(query_string)

        for definition in document.definitions:
            if not isinstance(definition, OperationDefinitionNode):
                continue
            if definition.operation.value != "query":
                continue
            if operation_name and definition.name and definition.name.value != operation_name:
                continue

            return sum(
                1
                for selection in definition.selection_set.selections
                if isinstance(selection, FieldNode)
                and hasattr(selection, "name")
                and selection.name
                and selection.name.value
                and not selection.name.value.startswith("__")
            )
    except Exception as e:
        logger.warning(f"Failed to count query fields: {e}")
        return 0

    return 0


def _should_include_field(field_node: Any, variables: dict[str, Any] | None) -> bool:
    """Evaluate @skip and @include directives to determine if field should be included.

    GraphQL spec:
    - @skip(if: Boolean!): Skip field if condition is true
    - @include(if: Boolean!): Include field only if condition is true
    - If both directives present, @skip takes precedence

    Args:
        field_node: GraphQL FieldNode with potential directives
        variables: Query variables for directive condition evaluation

    Returns:
        True if field should be included, False if it should be skipped
    """
    if not hasattr(field_node, "directives") or not field_node.directives:
        return True  # No directives, include by default

    variables = variables or {}

    # Check for @skip directive first (takes precedence)
    for directive in field_node.directives:
        if directive.name.value == "skip":
            # Extract the 'if' argument value
            for arg in directive.arguments:
                if arg.name.value == "if":
                    # Evaluate the condition
                    condition = _evaluate_directive_condition(arg.value, variables)
                    if condition:
                        return False  # Skip this field

    # Check for @include directive
    for directive in field_node.directives:
        if directive.name.value == "include":
            # Extract the 'if' argument value
            for arg in directive.arguments:
                if arg.name.value == "if":
                    # Evaluate the condition
                    condition = _evaluate_directive_condition(arg.value, variables)
                    if not condition:
                        return False  # Don't include this field

    return True  # Include by default


def _evaluate_directive_condition(value_node: Any, variables: dict[str, Any]) -> bool:
    """Evaluate a directive condition value (supports variables and literals).

    Args:
        value_node: GraphQL value node (Variable or BooleanValue)
        variables: Query variables

    Returns:
        Boolean condition result
    """
    from graphql import BooleanValueNode, VariableNode

    if isinstance(value_node, BooleanValueNode):
        # Literal boolean value
        return value_node.value
    if isinstance(value_node, VariableNode):
        # Variable reference
        var_name = value_node.name.value
        return bool(variables.get(var_name, False))
    # Unknown type, default to False
    return False


def _evaluate_argument_value(value_node: Any, variables: dict[str, Any] | None) -> Any:
    """Evaluate a field argument value (supports variables, literals, and complex types).

    GraphQL argument values can be:
    - Variables: $userId
    - Scalars: 10, "hello", true, null
    - Lists: [1, 2, 3]
    - Objects: {key: "value"}

    Args:
        value_node: GraphQL value node from argument
        variables: Query variables for variable resolution

    Returns:
        Python value (int, str, bool, None, list, dict)
    """
    from graphql import (
        BooleanValueNode,
        EnumValueNode,
        FloatValueNode,
        IntValueNode,
        ListValueNode,
        NullValueNode,
        ObjectValueNode,
        StringValueNode,
        VariableNode,
    )

    variables = variables or {}

    # Handle variable references
    if isinstance(value_node, VariableNode):
        var_name = value_node.name.value
        return variables.get(var_name)

    # Handle scalar literals
    if isinstance(value_node, IntValueNode):
        return int(value_node.value)
    if isinstance(value_node, FloatValueNode):
        return float(value_node.value)
    if isinstance(value_node, StringValueNode):
        return value_node.value
    if isinstance(value_node, BooleanValueNode):
        return value_node.value
    if isinstance(value_node, NullValueNode):
        return None
    if isinstance(value_node, EnumValueNode):
        return value_node.value

    # Handle list values
    if isinstance(value_node, ListValueNode):
        return [_evaluate_argument_value(item, variables) for item in value_node.values]

    # Handle object values
    if isinstance(value_node, ObjectValueNode):
        return {
            field.name.value: _evaluate_argument_value(field.value, variables)
            for field in value_node.fields
        }

    # Unknown type
    return None


def _extract_field_location(field_node: Any) -> dict[str, int] | None:
    """Extract line and column location from a GraphQL field node.

    Args:
        field_node: GraphQL FieldNode with location info

    Returns:
        Dict with 'line' and 'column' (1-indexed), or None if unavailable
    """
    if not hasattr(field_node, "loc") or not field_node.loc:
        return None

    loc = field_node.loc
    if not hasattr(loc, "source") or not loc.source:
        return None

    # Get the source text and starting offset
    source_body = loc.source.body
    start_offset = loc.start

    # Calculate line and column (both 1-indexed per GraphQL spec)
    line = 1
    column = 1

    for i, char in enumerate(source_body):
        if i >= start_offset:
            break

        if char == "\n":
            line += 1
            column = 1
        else:
            column += 1

    return {"line": line, "column": column}


def _extract_variable_defaults(
    query_string: str, operation_name: str | None = None
) -> dict[str, Any]:
    """Extract default values for variables from operation definition.

    Example:
        query GetUsers($limit: Int = 10, $status: String = "active") {
            # $limit defaults to 10 if not provided
            # $status defaults to "active" if not provided
        }

    Args:
        query_string: GraphQL query string
        operation_name: Optional operation name for multi-operation queries

    Returns:
        Dict mapping variable names to their default values
    """
    from graphql import OperationDefinitionNode, parse

    try:
        document = parse(query_string)
    except Exception:
        return {}

    defaults = {}

    for definition in document.definitions:
        # Only process operation definitions
        if not isinstance(definition, OperationDefinitionNode):
            continue

        # Skip if operation name doesn't match
        if operation_name and (not definition.name or definition.name.value != operation_name):
            continue

        # Extract variable definitions
        if not hasattr(definition, "variable_definitions") or not definition.variable_definitions:
            continue

        for var_def in definition.variable_definitions:
            var_name = var_def.variable.name.value

            # Check if default value is specified
            if hasattr(var_def, "default_value") and var_def.default_value:
                # Evaluate the default value
                default_val = _evaluate_argument_value(var_def.default_value, {})
                defaults[var_name] = default_val

    return defaults


def _expand_fragment_spread(
    spread_node: Any,
    document: Any,
    variables: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Expand a fragment spread into a list of root fields.

    Example:
        fragment UserData on Query {
            users { id name }
            posts { id }
        }

        query {
            ...UserData  # Expands to users + posts
        }

    Args:
        spread_node: FragmentSpreadNode from AST
        document: Full GraphQL document (contains fragment definitions)
        parent_selection_set: Parent selection set for context
        variables: Query variables for directive evaluation

    Returns:
        List of field dicts (same format as _extract_root_query_fields)
    """
    from graphql import FieldNode, FragmentDefinitionNode

    fragment_name = spread_node.name.value

    # Find the fragment definition in the document
    fragment_def = None
    for definition in document.definitions:
        if (
            isinstance(definition, FragmentDefinitionNode)
            and definition.name.value == fragment_name
        ):
            fragment_def = definition
            break

    if not fragment_def:
        # Fragment not found - skip
        return []

    # Check directives on fragment spread
    if not _should_include_field(spread_node, variables):
        return []

    # Extract fields from fragment's selection set
    fields = []
    for selection in fragment_def.selection_set.selections:
        if not isinstance(selection, FieldNode):
            continue

        if not _should_include_field(selection, variables):
            continue

        # Extract field info (same as main extraction logic)
        field_name = selection.name.value
        response_key = selection.alias.value if selection.alias else field_name

        # Extract sub-selections using recursive field extraction
        sub_selections = extract_field_selections(
            selection.selection_set, document, variables, None
        )

        fields.append(
            {
                "field_name": field_name,
                "response_key": response_key,
                "field_node": selection,
                "selections": sub_selections,
            }
        )

    return fields


def _expand_inline_fragment(
    inline_fragment_node: Any,
    document: Any,
    variables: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Expand an inline fragment into a list of root fields.

    Example:
        query {
            ... on Query {
                users { id }
            }
        }

    Args:
        inline_fragment_node: InlineFragmentNode from AST
        document: Full GraphQL document containing fragment definitions
        variables: Query variables for directive evaluation

    Returns:
        List of field dicts
    """
    from graphql import FieldNode

    # Check directives on inline fragment itself
    if not _should_include_field(inline_fragment_node, variables):
        return []

    # Extract fields from inline fragment's selection set
    fields = []
    for selection in inline_fragment_node.selection_set.selections:
        if not isinstance(selection, FieldNode):
            continue

        if not _should_include_field(selection, variables):
            continue

        field_name = selection.name.value
        response_key = selection.alias.value if selection.alias else field_name

        # Extract sub-selections using recursive field extraction
        sub_selections = extract_field_selections(
            selection.selection_set, document, variables, None
        )

        fields.append(
            {
                "field_name": field_name,
                "response_key": response_key,
                "field_node": selection,
                "selections": sub_selections,
            }
        )

    return fields


def _check_nested_errors(data: Any, path: list[str | int]) -> list[dict]:
    """Recursively check for error markers in nested data.

    NOTE: This function is not implemented due to FraiseQL architectural constraints.
    FraiseQL uses database views and table views that don't support partial failures.
    When a nested resolver fails, the entire parent field must fail to maintain
    data consistency with the underlying database views.

    This is a design decision rather than a technical limitation - GraphQL spec
    allows partial failures, but FraiseQL prioritizes data consistency over
    partial results when dealing with complex view-based data sources.

    Args:
        data: The resolved data structure (dict/list)
        path: Current path in the data structure

    Returns:
        Empty list (nested error recovery not supported)
    """
    # Nested field error recovery not implemented due to FraiseQL architecture
    # Database views and table views don't support partial failures
    # When nested resolvers fail, entire parent field must fail for consistency
    return []


def extract_field_selections(
    selection_set: Any,
    document: Any,
    variables: dict[str, Any] | None = None,
    visited_fragments: set[str] | None = None,
) -> list[dict[str, str]]:
    """Recursively extract field selections from a selection set, expanding fragments.

    This returns the flat list of field descriptors expected by the Rust layer:
    [{"field_name": "...", "alias": "..."}, ...]

    Args:
        selection_set: SelectionSet node from GraphQL AST
        document: Full GraphQL document containing fragment definitions
        variables: Query variables for directive evaluation
        visited_fragments: Set of fragment names currently being processed (for cycle detection)

    Returns:
        List of field descriptors with field_name and alias
    """
    from graphql import FieldNode, FragmentSpreadNode, InlineFragmentNode

    fields = []

    if not selection_set or not hasattr(selection_set, "selections"):
        return fields

    # Initialize visited fragments set if not provided
    if visited_fragments is None:
        visited_fragments = set()

    for selection in selection_set.selections:
        # Handle fragment spreads - expand recursively with cycle detection
        if isinstance(selection, FragmentSpreadNode):
            if not _should_include_field(selection, variables):
                continue

            # Find and expand the fragment
            fragment_name = selection.name.value

            # Check for cycle
            if fragment_name in visited_fragments:
                raise ValueError(f"Circular fragment reference: {fragment_name}")

            fragment_def = None
            for definition in document.definitions:
                if (
                    hasattr(definition, "__class__")
                    and definition.__class__.__name__ == "FragmentDefinitionNode"
                    and definition.name.value == fragment_name
                ):
                    fragment_def = definition
                    break

            if fragment_def:
                # Add to visited set and recursively extract fields from fragment
                updated_visited = visited_fragments | {fragment_name}
                fragment_fields = extract_field_selections(
                    fragment_def.selection_set, document, variables, updated_visited
                )
                fields.extend(fragment_fields)
            continue

        # Handle inline fragments - expand recursively
        if isinstance(selection, InlineFragmentNode):
            if not _should_include_field(selection, variables):
                continue

            # Recursively extract fields from inline fragment
            inline_fields = extract_field_selections(selection.selection_set, document, variables)
            fields.extend(inline_fields)
            continue

        # Handle regular fields
        if not isinstance(selection, FieldNode):
            continue
        if not hasattr(selection, "name") or not selection.name:
            continue
        if selection.name.value.startswith("__"):
            continue

        # Check @skip and @include directives
        if not _should_include_field(selection, variables):
            continue

        # Extract field name and alias
        field_name = selection.name.value
        alias = selection.alias.value if selection.alias else None

        fields.append(
            {
                "field_name": field_name,
                "alias": alias,
            }
        )

    return fields


def _extract_root_query_fields(
    query_string: str, operation_name: str | None = None, variables: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Extract root-level query fields with their selections, applying directive filtering.

    Args:
        query_string: GraphQL query string
        operation_name: Optional operation name for multi-operation queries
        variables: Query variables for directive evaluation

    Returns:
        List of dicts with field info:
        [
            {
                "field_name": "dnsServers",
                "field_node": FieldNode(...),
                "selections": ["id", "ipAddress", ...]
            },
            ...
        ]
    """
    try:
        document = parse(query_string)

        for definition in document.definitions:
            if not isinstance(definition, OperationDefinitionNode):
                continue
            if definition.operation.value != "query":
                continue
            if operation_name and definition.name and definition.name.value != operation_name:
                continue

            # Use the recursive selection processor
            fields = []
            for selection in definition.selection_set.selections:
                # Handle fragment spreads
                if isinstance(selection, FragmentSpreadNode):
                    # Fragment spread like: ...UserFields
                    expanded_fields = _expand_fragment_spread(selection, document, variables)
                    fields.extend(expanded_fields)
                    continue

                # Handle inline fragments
                if isinstance(selection, InlineFragmentNode):
                    # Inline fragment like: ... on Query { users { id } }
                    expanded_fields = _expand_inline_fragment(selection, document, variables)
                    fields.extend(expanded_fields)
                    continue

                # Handle regular fields
                if not isinstance(selection, FieldNode):
                    continue
                if not hasattr(selection, "name") or not selection.name:
                    continue
                if selection.name.value.startswith("__"):
                    continue

                # Check @skip and @include directives on root field
                if not _should_include_field(selection, variables):
                    continue  # Skip this field based on directives

                # Extract root field name and alias
                # For `allUsers: users`, selection.name.value = "users"
                # selection.alias.value = "allUsers"
                # Response key is alias if present, otherwise field name
                field_name = selection.name.value  # Actual field name (for resolver lookup)
                response_key = (
                    selection.alias.value if selection.alias else field_name
                )  # Response key

                # Extract sub-field selections with aliases and directives
                sub_selections = extract_field_selections(
                    selection.selection_set, document, variables, None
                )

                fields.append(
                    {
                        "field_name": field_name,  # For resolver lookup
                        "response_key": response_key,  # For response building
                        "field_node": selection,
                        "selections": sub_selections,
                    }
                )

            return fields

    except ValueError as e:
        # Re-raise ValueError for critical issues like circular fragments
        if "Circular fragment reference" in str(e):
            raise
        logger.warning(f"Failed to extract query fields: {e}")
        return []
    except Exception as e:
        logger.warning(f"Failed to extract query fields: {e}")
        return []

    return []


def _build_field_selections_recursive(
    field_node: Any,
    document: Any,
    variables: dict[str, Any] | None,
    parent_path: str = "",
    visited_fragments: frozenset[str] | None = None,
) -> list[dict[str, str | None]]:
    """Build a flat list of field selections with full materialized dot-path keys.

    Unlike extract_field_selections() which only captures immediate sub-fields
    of a root field, this function recurses into nested objects and accumulates
    selections like ``[{"materialized_path": "nested", ...},
    {"materialized_path": "nested.value", ...}]``.

    The complete path list is required by Rust's ``transform_with_selections``
    inside ``build_multi_field_response``: without a path such as
    ``"nested.value"`` in ``selected_paths``, Rust cannot include that field
    and silently returns only ``__typename`` for the nested object.

    Directive evaluation (``@skip`` / ``@include``) is applied via
    ``_should_include_field`` so excluded fields are omitted from the list.
    Fragment spreads are expanded with cycle-detection.

    Args:
        field_node: The root FieldNode (or fragment definition) whose
            selection_set to traverse.
        document: Full parsed GraphQL document for fragment lookup.
        variables: Query variables for ``@skip``/``@include`` evaluation.
        parent_path: Dot-separated path prefix for the current traversal
            level (empty string at root level).
        visited_fragments: Fragment names already expanded in the current
            traversal branch (prevents infinite recursion on circular refs).

    Returns:
        Flat list of ``{"materialized_path": "...", "alias": "..."|None}``
        dicts covering every field at every nesting depth.
    """
    from graphql import FieldNode as _FieldNode
    from graphql import FragmentSpreadNode as _FragmentSpreadNode
    from graphql import InlineFragmentNode as _InlineFragmentNode

    if visited_fragments is None:
        visited_fragments = frozenset()

    result: list[dict[str, str | None]] = []

    selection_set = getattr(field_node, "selection_set", None)
    if not selection_set or not hasattr(selection_set, "selections"):
        return result

    for sel in selection_set.selections:
        # Fragment spread: locate and expand the fragment definition.
        if isinstance(sel, _FragmentSpreadNode):
            if not _should_include_field(sel, variables):
                continue
            frag_name = sel.name.value
            if frag_name in visited_fragments:
                continue
            frag_def = next(
                (
                    d
                    for d in document.definitions
                    if hasattr(d, "name") and d.name and d.name.value == frag_name
                ),
                None,
            )
            if frag_def:
                result.extend(
                    _build_field_selections_recursive(
                        frag_def,
                        document,
                        variables,
                        parent_path,
                        visited_fragments | {frag_name},
                    )
                )
            continue

        # Inline fragment: recurse transparently.
        if isinstance(sel, _InlineFragmentNode):
            if not _should_include_field(sel, variables):
                continue
            result.extend(
                _build_field_selections_recursive(
                    sel,
                    document,
                    variables,
                    parent_path,
                    visited_fragments,
                )
            )
            continue

        # Regular field.
        if not isinstance(sel, _FieldNode):
            continue
        if not hasattr(sel, "name") or not sel.name:
            continue
        if sel.name.value.startswith("__"):
            continue
        if not _should_include_field(sel, variables):
            continue

        field_name = sel.name.value
        alias: str | None = sel.alias.value if sel.alias else None
        path = f"{parent_path}.{field_name}" if parent_path else field_name
        result.append({"materialized_path": path, "alias": alias})

        # Recurse into nested object selections.
        if getattr(sel, "selection_set", None):
            result.extend(
                _build_field_selections_recursive(
                    sel,
                    document,
                    variables,
                    path,
                    visited_fragments,
                )
            )

    return result


async def execute_multi_field_query(
    schema: GraphQLSchema,
    query_string: str,
    variables: dict[str, Any] | None,
    context: dict[str, Any],
) -> RustResponseBytes:
    """Execute multi-field query entirely in Rust - bypass graphql-core.

    This function handles multi-field queries (e.g., {dnsServers {...} gateways {...}})
    by executing each resolver independently and combining results in Rust.

    This avoids graphql-core's type validation which fails when resolvers return
    plain dicts (from json.loads()) instead of typed Python objects.

    Args:
        schema: GraphQL schema
        query_string: GraphQL query string
        variables: Query variables
        context: GraphQL context with database connection, etc.

    Returns:
        RustResponseBytes with complete {"data": {...}} response

    Raises:
        Exception: If field extraction or resolver execution fails
    """
    # Parse once; reused by _extract_variable_defaults, _extract_root_query_fields,
    # and _build_field_selections_recursive (fragment lookup for issue #288 fix).
    from graphql import parse as _gql_parse

    from fraiseql.core.rust_pipeline import fraiseql_rs

    _parsed_query = _gql_parse(query_string)

    # Extract variable defaults from operation definition
    variable_defaults = _extract_variable_defaults(query_string, None)

    # Merge defaults with provided variables (provided variables take precedence)
    if variable_defaults:
        merged_variables = {**variable_defaults, **(variables or {})}
        variables = merged_variables

    # Extract all root fields (with directive evaluation using variables)
    fields_info = _extract_root_query_fields(query_string, None, variables)

    if not fields_info:
        raise ValueError("No root query fields found in multi-field query")

    # Collect data for each field and errors
    field_data_list = []
    errors = []

    for field_info in fields_info:
        field_name = field_info["field_name"]  # For resolver lookup
        response_key = field_info["response_key"]  # For response building (alias or field_name)
        field_node = field_info["field_node"]

        # Extract field arguments from the GraphQL AST
        field_args = {}
        if hasattr(field_node, "arguments") and field_node.arguments:
            for arg_node in field_node.arguments:
                arg_name = arg_node.name.value
                arg_value = _evaluate_argument_value(arg_node.value, variables)
                field_args[arg_name] = arg_value

        # Get resolver from schema (use actual field_name, not alias)
        query_type = schema.query_type
        if not query_type:
            raise ValueError("Schema has no query type")

        field_def = query_type.fields.get(field_name)
        if not field_def:
            raise ValueError(f"Field '{field_name}' not found in schema")

        # Get type name for the field
        field_type = field_def.type
        # Unwrap NonNull and List to get the actual type
        while hasattr(field_type, "of_type"):
            field_type = field_type.of_type

        type_name = field_type.name if hasattr(field_type, "name") else None

        # Determine if this is a list field
        is_list = "[" in str(field_def.type)

        # Get resolver function
        resolver = field_def.resolve
        if not resolver:
            raise ValueError(f"No resolver found for field '{field_name}'")

        # Execute resolver
        # Resolvers expect: resolve(root, info, **args)
        # For root-level queries, root is None
        # We need to create a GraphQL ResolveInfo object, but for simplicity
        # in Phase 2, we'll call the resolver directly and hope it doesn't need full info

        # SIMPLIFIED: Assume resolver returns the data we need
        # In a real implementation, we'd need to construct proper ResolveInfo
        try:
            # Most FraiseQL resolvers are async and expect (info, **kwargs)
            # Try calling with minimal info

            # Create minimal resolve info
            # This is a simplified version - proper implementation would build full ResolveInfo
            class MinimalInfo:
                def __init__(self, field_name: str, context: dict, field_node: Any) -> None:
                    self.field_name = field_name
                    self.context = context
                    self.field_nodes = [field_node]
                    self.parent_type = query_type  # noqa: B023
                    self.path = None
                    self.return_type = field_def.type  # noqa: B023
                    self.schema = schema
                    self.fragments = {}
                    self.root_value = None
                    self.operation = None
                    self.variable_values = variables or {}

            info = MinimalInfo(field_name, context, field_node)

            # Execute resolver
            # Resolvers can have different signatures:
            # 1. Test resolvers: (info, **kwargs)
            # 2. GraphQL-wrapped resolvers: (root, info, **kwargs)

            sig = inspect.signature(resolver)

            # Filter out VAR_POSITIONAL and VAR_KEYWORD params
            positional_params = [
                name
                for name, param in sig.parameters.items()
                if param.kind
                in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]

            is_async = inspect.iscoroutinefunction(resolver)

            # Determine if first positional param is 'root'
            has_root_param = positional_params and positional_params[0] in ("root", "self")

            # If no positional params but we have VAR_POSITIONAL + VAR_KEYWORD,
            # this is likely a wrapped resolver: (root, info, **kwargs)
            # Try calling with (root, info, **kwargs) format
            has_var_positional = any(
                param.kind == inspect.Parameter.VAR_POSITIONAL for param in sig.parameters.values()
            )
            has_var_keyword = any(
                param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values()
            )

            if len(positional_params) == 0 and has_var_positional and has_var_keyword:
                # Wrapped resolver format: (*args, **kwargs) which accepts (root, info, **kwargs)
                if is_async:
                    result = await resolver(None, info, **field_args)
                else:
                    result = resolver(None, info, **field_args)
            elif len(positional_params) == 1:
                # Single parameter - likely just (info)
                if is_async:
                    result = await resolver(info)
                else:
                    result = resolver(info)
            elif len(positional_params) >= 2 and has_root_param:
                # Has root parameter - standard GraphQL resolver: (root, info, **kwargs)
                if is_async:
                    result = await resolver(None, info, **field_args)
                else:
                    result = resolver(None, info, **field_args)
            # Fallback - try with just info + field_args
            elif is_async:
                result = await resolver(info, **field_args)
            else:
                result = resolver(info, **field_args)

            # If result is RustResponseBytes, extract the raw data
            if isinstance(result, RustResponseBytes):
                # Parse the RustResponseBytes to get the actual data
                result_json = json.loads(bytes(result))
                # Extract just the field data (not the GraphQL wrapper)
                if "data" in result_json and field_name in result_json["data"]:
                    result = result_json["data"][field_name]

            # Convert result to list of JSON strings
            if is_list:
                if not isinstance(result, list):
                    msg = (
                        f"Resolver for list field '{field_name}' "
                        f"did not return a list: {type(result)}"
                    )
                    raise ValueError(msg)
                # Each item should be a dict - convert to JSON string
                json_rows = [
                    json.dumps(item) if isinstance(item, dict) else item for item in result
                ]
            else:
                # Single object
                json_rows = [json.dumps(result) if isinstance(result, dict) else result]

            # Build COMPLETE recursive field selections with full materialized paths.
            # This fixes issue #288: the previous code only captured top-level field
            # names (e.g. "nested"), causing transform_with_selections to filter out
            # nested sub-fields (e.g. "nested.value" was absent from selected_paths),
            # leaving JSONB nested objects with only __typename populated.
            # _build_field_selections_recursive() includes all paths at every depth
            # (e.g. "nested" AND "nested.value"), respects @skip/@include, and
            # preserves field aliases at any nesting level.
            recursive_selections = _build_field_selections_recursive(
                field_node, _parsed_query, variables
            )
            field_selections_json = (
                json.dumps(recursive_selections) if recursive_selections else None
            )

            # Add to field data list (use response_key for the response field name)
            field_data_list.append(
                (response_key, type_name, json_rows, field_selections_json, is_list)
            )

        except Exception as e:
            logger.error(f"Failed to execute resolver for field '{field_name}': {e}")

            # Add null field data for failed field
            field_data_list.append((response_key, type_name, [], None, is_list))

            # Collect error with GraphQL spec format
            error_dict = {
                "message": str(e),
                "path": [response_key],
            }

            # Preserve GraphQLError extensions (e.g. authorization deny carries
            # extensions={"code": "FORBIDDEN"}) so the deny shape is consistent with
            # the other execution paths (issue #362).
            error_extensions = getattr(e, "extensions", None)
            if error_extensions:
                error_dict["extensions"] = error_extensions

            # Add location info if available
            location = _extract_field_location(field_node)
            if location:
                error_dict["locations"] = [location]

            errors.append(error_dict)

            # Continue to next field instead of raising

    # NOTE: Nested field error recovery not implemented due to FraiseQL architecture
    # FraiseQL uses database views and table views that don't support partial failures.
    # When a nested resolver fails, the entire parent field must fail to maintain
    # data consistency with the underlying database views.
    #
    # This is an intentional design decision prioritizing data consistency over
    # GraphQL spec compliance for partial results. While the GraphQL spec allows
    # partial failures with independent nested field errors, FraiseQL's view-based
    # architecture makes this impractical to implement safely.

    # Call Rust to build the multi-field response
    response_bytes = fraiseql_rs.build_multi_field_response(field_data_list)

    # If there are errors, inject them into the response
    if errors:
        response_json = json.loads(bytes(response_bytes))
        response_json["errors"] = errors
        return RustResponseBytes(json.dumps(response_json).encode("utf-8"))

    return RustResponseBytes(response_bytes)


# Module-level dependency singletons to avoid B008
_default_context_dependency = Depends(build_graphql_context)


class GraphQLRequest(BaseModel):
    """GraphQL request model supporting Apollo Automatic Persisted Queries (APQ)."""

    query: str | None = None
    variables: dict[str, Any] | None = None
    operationName: str | None = None  # noqa: N815 - GraphQL spec requires this name
    extensions: dict[str, Any] | None = None

    @field_validator("extensions")
    @classmethod
    def validate_extensions(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """Validate extensions field structure for APQ compliance."""
        if v is None:
            return v

        # If extensions contains persistedQuery, validate APQ structure
        if "persistedQuery" in v:
            persisted_query = v["persistedQuery"]
            if not isinstance(persisted_query, dict):
                raise ValueError("persistedQuery must be an object")

            # APQ requires version and sha256Hash
            if "version" not in persisted_query:
                raise ValueError("persistedQuery.version is required")
            if "sha256Hash" not in persisted_query:
                raise ValueError("persistedQuery.sha256Hash is required")

            # Version must be 1 (APQ v1)
            if persisted_query["version"] != 1:
                raise ValueError("Only APQ version 1 is supported")

            # sha256Hash must be a non-empty string
            sha256_hash = persisted_query["sha256Hash"]
            if not isinstance(sha256_hash, str) or not sha256_hash:
                raise ValueError("persistedQuery.sha256Hash must be a non-empty string")

        return v


def _derive_operation_info(query_string: str | None) -> tuple[str, str]:
    """Best-effort ``(operation_type, root_field_name)`` from a query string.

    The resolver-bypass authorization gates (``/graphql/rust`` and the APQ cache hit)
    have no ``GraphQLResolveInfo``, so they derive the operation identity from the raw
    query. Defaults to ``("query", "")`` when the document cannot be parsed.
    """
    if not query_string:
        return "query", ""
    try:
        document = parse(query_string)
    except Exception:
        return "query", ""
    for definition in document.definitions:
        if isinstance(definition, OperationDefinitionNode):
            op_type = definition.operation.value
            for selection in definition.selection_set.selections:
                if isinstance(selection, FieldNode):
                    return op_type, selection.name.value
            return op_type, ""
    return "query", ""


def _registry_default_authorizer() -> Any:
    """Return the global default operation authorizer from the registry (issue #362).

    The bypass gates read this live so a configured authorizer (set at build time or
    re-applied on hot-reload) reaches them without per-request plumbing.
    """
    from fraiseql.gql.builders import SchemaRegistry

    return SchemaRegistry.get_instance().default_authorizer


def _forbidden_error_payload(exc: Any) -> dict[str, Any]:
    """Shape a denied :class:`GraphQLError` into a GraphQL error response body."""
    return {
        "errors": [
            {
                "message": getattr(exc, "message", str(exc)),
                "extensions": getattr(exc, "extensions", None) or {"code": "FORBIDDEN"},
            }
        ]
    }


def create_graphql_router(
    schema: GraphQLSchema,
    config: FraiseQLConfig,
    auth_provider: AuthProvider | None = None,
    context_getter: Callable[[Request], Awaitable[dict[str, Any]]] | None = None,
    turbo_registry: TurboRegistry | None = None,
) -> APIRouter:
    """Create unified adaptive GraphQL router.

    This router adapts its behavior based on configuration and runtime headers,
    providing appropriate features for each environment while maintaining a
    single code path.

    Args:
        schema: GraphQL schema
        config: FraiseQL configuration
        auth_provider: Optional auth provider
        context_getter: Optional custom context getter
        turbo_registry: Optional TurboRouter registry

    Returns:
        Configured router
    """
    router = APIRouter(prefix="", tags=["GraphQL"])

    # Determine base behavior from environment
    is_production_env = config.environment == "production"
    logger.info(
        f"Creating unified GraphQL router: environment={config.environment}, "
        f"turbo_enabled={turbo_registry is not None}, "
        f"turbo_registry_type={type(turbo_registry).__name__}"
    )

    # Configure N+1 detection for non-production environments
    if not is_production_env:
        from fraiseql.optimization.n_plus_one_detector import get_detector

        detector = get_detector()
        if not hasattr(detector, "_configured"):
            configure_detector(
                threshold=10,  # Warn after 10 similar queries
                time_window=1.0,  # Within 1 second
                enabled=True,
                raise_on_detection=False,  # Just warn, don't raise
            )
            detector._configured = True

    # Always create unified execution components
    turbo_router = None
    if turbo_registry is not None:
        try:
            logger.info(f"Creating TurboRouter with registry: {turbo_registry}")
            # Thread the global default authorizer into the bypass gate (issue #362).
            turbo_router = TurboRouter(
                turbo_registry, default_authorizer=_registry_default_authorizer()
            )
            logger.info(f"TurboRouter created successfully: {turbo_router}")
        except Exception:
            logger.exception("Failed to create TurboRouter")

    logger.info(
        f"TurboRouter creation final state: turbo_registry={turbo_registry is not None}, "
        f"turbo_router={turbo_router is not None}, turbo_router_value={turbo_router}"
    )
    query_analyzer = QueryAnalyzer(schema)
    mode_selector = ModeSelector(config)

    # Create unified executor
    unified_executor = None
    if getattr(config, "unified_executor_enabled", True):
        unified_executor = UnifiedExecutor(
            schema=schema,
            mode_selector=mode_selector,
            turbo_router=turbo_router,
            query_analyzer=query_analyzer,
        )
        logger.info(
            "Created UnifiedExecutor: has_turbo=%s, environment=%s",
            turbo_router is not None,
            config.environment,
        )

    # Create context dependency
    if context_getter:
        # Merge custom context with default
        async def get_merged_context(
            http_request: Request,
            default_context: dict[str, Any] = _default_context_dependency,
        ) -> dict[str, Any]:
            user = default_context.get("user")
            # Try to pass user as second argument if context_getter accepts it
            import inspect

            sig = inspect.signature(context_getter)
            if len(sig.parameters) >= 2:
                custom_context = await context_getter(http_request, user)
            else:
                custom_context = await context_getter(http_request)
            # Merge with default context (custom values override defaults)
            return {**default_context, **custom_context}

        context_dependency = Depends(get_merged_context)
    else:
        context_dependency = Depends(build_graphql_context)

    @router.post("/graphql", response_class=FraiseQLJSONResponse, response_model=None)
    async def graphql_endpoint(
        request: GraphQLRequest,
        http_request: Request,
        context: dict[str, Any] = context_dependency,
    ) -> dict[str, Any] | Response:
        """Execute GraphQL query with adaptive behavior.

        Returns either a dict (normal GraphQL response) or Response (direct Rust bytes).
        """
        # Check authentication first (before APQ processing to ensure security)
        # For APQ requests, we need to check auth regardless of query availability
        # Special case: Allow introspection queries to proceed to GraphQL layer when:
        # 1. In development mode (for easier development)
        # 2. introspection_policy is AUTHENTICATED (GraphQL layer will handle blocking)
        is_introspection_query = request.query and "__schema" in request.query
        should_allow_introspection = (
            config.environment == "development"
            or config.introspection_policy == IntrospectionPolicy.AUTHENTICATED
        )

        if (
            config.auth_enabled
            and auth_provider
            and not context.get("authenticated", False)
            and not (is_introspection_query and should_allow_introspection)
        ):
            # Return 401 for unauthenticated requests when auth is required
            raise HTTPException(status_code=401, detail="Authentication required")

        # Initialize APQ backend for potential caching
        apq_backend = None
        is_apq_request = request.extensions and "persistedQuery" in request.extensions

        # Check APQ mode enforcement
        apq_mode = config.apq_mode

        # In 'required' mode, reject non-APQ requests (arbitrary queries)
        if not apq_mode.allows_arbitrary_queries() and not is_apq_request:
            from fraiseql.middleware.apq import create_arbitrary_query_rejected_error

            logger.debug("APQ required mode: rejecting arbitrary query")
            return create_arbitrary_query_rejected_error()

        # In 'disabled' mode, skip APQ processing entirely
        should_process_apq = apq_mode.processes_apq()

        # Handle APQ (Automatic Persisted Queries) if detected and mode allows
        if is_apq_request and request.extensions and should_process_apq:
            from fraiseql.middleware.apq import create_apq_error_response, get_persisted_query
            from fraiseql.middleware.apq_caching import (
                get_apq_backend,
                handle_apq_request_with_cache,
            )
            from fraiseql.storage.apq_store import store_persisted_query

            logger.debug("APQ request detected, processing...")

            persisted_query = request.extensions["persistedQuery"]
            sha256_hash = persisted_query.get("sha256Hash")

            # Validate hash format
            if not sha256_hash or not isinstance(sha256_hash, str) or not sha256_hash.strip():
                logger.debug("APQ request failed: invalid hash format")
                return create_apq_error_response(
                    "PERSISTED_QUERY_NOT_FOUND", "PersistedQueryNotFound"
                )

            # Get APQ backend for caching
            apq_backend = get_apq_backend(config)

            # Check if this is a registration request (has both hash and query)
            if request.query:
                # This is a registration request - store the query
                logger.debug(f"APQ registration: storing query with hash {sha256_hash[:8]}...")

                # Store in the global store (for backward compatibility)
                store_persisted_query(sha256_hash, request.query)

                # Also store in the backend if available
                if apq_backend:
                    apq_backend.store_persisted_query(sha256_hash, request.query)

                # Continue with normal execution using the provided query
                # The response will be cached after execution (see lines 361-370)

            else:
                # This is a hash-only request - try to retrieve the query

                # 1. Try cached response first (JSON passthrough)
                cached_response = handle_apq_request_with_cache(
                    request, apq_backend, config, context=context
                )
                if cached_response:
                    # Operation authorization gate (issue #362): a cached (baked)
                    # response cannot be re-scoped per principal, so enforce BEFORE
                    # serving it. This path bypasses GraphQLField.resolve.
                    serve_cached = True
                    authorizer = _registry_default_authorizer()
                    if authorizer is not None:
                        from graphql import GraphQLError

                        from fraiseql.security.authorization import enforce_operation_value

                        persisted_text = (
                            apq_backend.get_persisted_query(sha256_hash) if apq_backend else None
                        )
                        op_type, op_name = _derive_operation_info(persisted_text)
                        try:
                            decision = await enforce_operation_value(
                                authorizer=authorizer,
                                context=context,
                                operation_type=op_type,
                                operation_name=op_name,
                                arguments=request.variables or {},
                            )
                        except GraphQLError as exc:
                            # Deny short-circuits: the cached response is never served.
                            return _forbidden_error_payload(exc)
                        if decision.filters:
                            # A baked cached response cannot honor per-row filters →
                            # skip the cache and fall through to normal resolver
                            # execution (which applies the filter on the read path).
                            logger.info(
                                "APQ cache skipped due to authorization scoping filters; "
                                "falling through to normal execution"
                            )
                            serve_cached = False
                    if serve_cached:
                        logger.debug(f"APQ cache hit: {sha256_hash[:8]}...")
                        return cached_response

                # 2. Fallback to query resolution from backend
                persisted_query_text = None

                # Try backend first
                if apq_backend:
                    persisted_query_text = apq_backend.get_persisted_query(sha256_hash)

                # Fallback to global store
                if not persisted_query_text:
                    persisted_query_text = get_persisted_query(sha256_hash)

                if not persisted_query_text:
                    logger.debug(f"APQ request failed: hash not found: {sha256_hash[:8]}...")
                    return create_apq_error_response(
                        "PERSISTED_QUERY_NOT_FOUND", "PersistedQueryNotFound"
                    )

                # Replace request query with persisted query for normal execution
                logger.debug(
                    f"APQ request resolved: hash {sha256_hash[:8]}... -> "
                    f"query length {len(persisted_query_text)}"
                )
                request.query = persisted_query_text

        try:
            # Determine execution mode from headers and config
            mode = config.environment
            json_passthrough = False

            # Check for mode headers
            if "x-mode" in http_request.headers:
                mode = http_request.headers["x-mode"].lower()
                context["mode"] = mode

                # Enable passthrough for production/staging/testing modes (always enabled)
                if mode in ("production", "staging", "testing"):
                    json_passthrough = True
            else:
                # Use environment as default mode
                context["mode"] = mode
                # Passthrough is always enabled in production/staging/testing
                if is_production_env or mode in ("staging", "testing"):
                    json_passthrough = True

            # Check for explicit passthrough header
            if "x-json-passthrough" in http_request.headers:
                json_passthrough = http_request.headers["x-json-passthrough"].lower() == "true"

            # Set passthrough flags in context
            if json_passthrough:
                context["execution_mode"] = "passthrough"
                context["json_passthrough"] = True

                # Update repository context if available
                if "db" in context:
                    context["db"].context["mode"] = mode
                    context["db"].context["json_passthrough"] = True
                    context["db"].mode = mode

            # Detect multi-field queries to handle RustResponseBytes pass-through correctly
            has_multiple_root_fields = (
                request.query and _count_root_query_fields(request.query, request.operationName) > 1
            )
            context["__has_multiple_root_fields__"] = has_multiple_root_fields

            # 🚀 MULTI-FIELD QUERY ROUTING (Phase 1)
            # Route multi-field queries to Rust-only merge path to avoid graphql-core type errors
            if has_multiple_root_fields:
                field_count = _count_root_query_fields(request.query, request.operationName)
                logger.info(
                    f"🚀 Multi-field query detected ({field_count} root fields) - "
                    f"using Rust-only merge path"
                )
                try:
                    result = await execute_multi_field_query(
                        schema, request.query, request.variables, context
                    )
                    # execute_multi_field_query returns RustResponseBytes
                    return Response(
                        content=bytes(result),
                        media_type="application/json",
                    )
                except Exception:
                    logger.exception("Multi-field query execution failed")
                    # Fall back to standard execution
                    logger.warning("Falling back to standard graphql-core execution")

            # Use unified executor if available
            if unified_executor:
                # Add execution metadata if in development
                if not is_production_env:
                    context["include_execution_metadata"] = True

                result = await unified_executor.execute(
                    query=request.query,
                    variables=request.variables,
                    operation_name=request.operationName,
                    context=context,
                )

                # 🚀 RUST RESPONSE BYTES PASS-THROUGH (Unified Executor):
                # Check if UnifiedExecutor returned RustResponseBytes directly (zero-copy path)
                # Only use fast path for single-field queries to avoid dropping fields
                if isinstance(result, RustResponseBytes) and not has_multiple_root_fields:
                    logger.info("🚀 Direct path: Returning RustResponseBytes from unified executor")
                    return Response(
                        content=bytes(result),
                        media_type="application/json",
                    )

                # 🚀 DIRECT PATH: Check if GraphQL rejected RustResponseBytes
                if isinstance(result, dict) and "errors" in result and "_rust_response" in context:
                    for error in result.get("errors", []):
                        error_msg = str(error.get("message", ""))
                        # Check for RustResponseBytes type errors (single objects or lists)
                        if "RustResponseBytes" in error_msg or "Expected Iterable" in error_msg:
                            # GraphQL rejected RustResponseBytes - retrieve it from context
                            rust_responses = context["_rust_response"]
                            if rust_responses:
                                # Get the first RustResponseBytes
                                first_response = next(iter(rust_responses.values()))
                                logger.info(
                                    "🚀 Direct path: Returning RustResponseBytes directly "
                                    "(unified executor)"
                                )
                                return Response(
                                    content=bytes(first_response),
                                    media_type="application/json",
                                )

                return result

            # Fallback to standard execution
            # Generate unique request ID for N+1 detection
            request_id = str(uuid4())

            # Phase 6: Parse query with Rust parser for performance
            # This sets up query info for Phase 7 (query building in Rust)
            if request.query:
                parser = RustGraphQLParser()
                parsed_query = await parser.parse(request.query)

                # Extract query info for Phase 7
                context["rust_parsed_query"] = {
                    "operation_type": parsed_query.operation_type,
                    "root_field": parsed_query.root_field,
                    "selections": parsed_query.selections,
                    "variables": parsed_query.variables,
                }

            # Execute with N+1 detection in non-production
            if not is_production_env:
                async with n1_detection_context(request_id) as detector:
                    context["n1_detector"] = detector
                    result = await execute_graphql(
                        schema,
                        request.query,
                        context_value=context,
                        variable_values=request.variables,
                        operation_name=request.operationName,
                        enable_introspection=config.enable_introspection,
                    )
            else:
                result = await execute_graphql(
                    schema,
                    request.query,
                    context_value=context,
                    variable_values=request.variables,
                    operation_name=request.operationName,
                    enable_introspection=config.enable_introspection,
                )

            # 🚀 RUST RESPONSE BYTES PASS-THROUGH (Fallback Executor):
            # Check if execute_graphql() returned RustResponseBytes directly (zero-copy path)
            # This happens when Phase 1 middleware captures RustResponseBytes from resolvers
            # Only use fast path for single-field queries to avoid dropping fields
            if isinstance(result, RustResponseBytes) and not has_multiple_root_fields:
                logger.info("🚀 Direct path: Returning RustResponseBytes from fallback executor")
                return Response(
                    content=bytes(result),
                    media_type="application/json",
                )

            # Build response (normal ExecutionResult path)
            response: dict[str, Any] = {}
            if result.data is not None:
                response["data"] = result.data
            if result.errors:
                response["errors"] = [
                    _format_error(error, is_production_env) for error in result.errors
                ]

            # 🚀 DIRECT PATH: Check for RustResponseBytes in multiple places

            # 1. Check if GraphQL rejected RustResponseBytes (type error)
            if result.errors and "_rust_response" in context:
                for error in result.errors:
                    error_msg = str(error.message)
                    if "RustResponseBytes" in error_msg or "Expected Iterable" in error_msg:
                        # GraphQL rejected RustResponseBytes - retrieve it from context
                        rust_responses = context["_rust_response"]
                        if rust_responses:
                            # Get the first RustResponseBytes
                            first_response = next(iter(rust_responses.values()))
                            logger.info(
                                "🚀 Direct path: Returning RustResponseBytes directly "
                                "(fallback executor)"
                            )
                            return Response(
                                content=bytes(first_response),
                                media_type="application/json",
                            )

            # 2. Check if result contains RustResponseBytes (fallback path)
            # Only use fast path for single-field queries to avoid dropping fields
            if result.data and isinstance(result.data, dict) and not has_multiple_root_fields:
                for value in result.data.values():
                    if isinstance(value, RustResponseBytes):
                        # Return Rust bytes directly to HTTP
                        logger.info("🚀 Direct path: Returning RustResponseBytes directly")
                        return Response(
                            content=bytes(value),
                            media_type="application/json",
                        )

            # Cache response for APQ if it was an APQ request and response is cacheable
            if is_apq_request and apq_backend:
                from fraiseql.middleware.apq_caching import (
                    get_apq_hash_from_request,
                    store_response_in_cache,
                )

                apq_hash = get_apq_hash_from_request(request)
                if apq_hash:
                    # Get query text for field selection filtering
                    query_text = apq_backend.get_persisted_query(apq_hash)

                    # Store the filtered response in cache for future requests
                    store_response_in_cache(
                        apq_hash,
                        response,
                        apq_backend,
                        config,
                        variables=request.variables,
                        context=context,
                        query_text=query_text,
                        operation_name=request.operationName,
                    )

            return response

        except N1QueryDetectedError as e:
            # N+1 query pattern detected (only in development)
            return {
                "errors": [
                    {
                        "message": str(e),
                        "extensions": clean_unset_values(
                            {
                                "code": "N1_QUERY_DETECTED",
                                "patterns": [
                                    {
                                        "field": p.field_name,
                                        "type": p.parent_type,
                                        "count": p.count,
                                    }
                                    for p in e.patterns
                                ],
                            },
                        ),
                    },
                ],
            }
        except Exception as e:
            # Format error based on environment
            logger.exception("GraphQL execution error")

            if is_production_env:
                # Minimal error info in production
                return {
                    "errors": [
                        {
                            "message": "Internal server error",
                            "extensions": {"code": "INTERNAL_SERVER_ERROR"},
                        },
                    ],
                }
            # Detailed error info in development
            return {
                "errors": [
                    {
                        "message": str(e),
                        "extensions": clean_unset_values(
                            {
                                "code": "INTERNAL_SERVER_ERROR",
                                "exception": type(e).__name__,
                            },
                        ),
                    },
                ],
            }

    @router.get("/graphql")
    async def graphql_get_endpoint(
        query: str | None = None,
        http_request: Request = None,
        variables: str | None = None,
        operationName: str | None = None,  # noqa: N803
        context: dict[str, Any] = context_dependency,
    ) -> Any:
        """Handle GraphQL GET requests."""
        # Only allow in non-production or if explicitly enabled
        if is_production_env and not config.enable_playground:
            raise HTTPException(404, "Not found")

        # If no query and playground enabled, serve it
        if query is None and config.enable_playground:
            if config.playground_tool == "apollo-sandbox":
                return HTMLResponse(content=APOLLO_SANDBOX_HTML)
            return HTMLResponse(content=GRAPHIQL_HTML)

        # If no query and playground disabled, error
        if query is None:
            raise HTTPException(400, "Query parameter is required")

        # Parse variables
        parsed_variables = None
        if variables:
            try:
                parsed_variables = json.loads(variables)
            except json.JSONDecodeError as e:
                raise HTTPException(400, "Invalid JSON in variables parameter") from e

        request_obj = GraphQLRequest(
            query=query,
            variables=parsed_variables,
            operationName=operationName,
        )

        return await graphql_endpoint(request_obj, http_request, context)

    # Phase 9: Add simplified unified Rust pipeline endpoint
    @router.post("/graphql/rust", response_class=Response)
    async def graphql_endpoint_rust(
        request: GraphQLRequest,
        http_request: Request,
        context: dict[str, Any] = context_dependency,
    ) -> Response:
        """Execute GraphQL query using unified Rust pipeline (Phase 9).

        This endpoint demonstrates the dramatic simplification achieved by
        moving all database operations to Rust. All work happens in a
        single Rust function call.
        """
        # Operation authorization gate (issue #362). This endpoint hands off to Rust
        # and never runs a Python resolver, so enforcement happens here, before the
        # Rust call. Per-operation decorator overrides do not apply on this path.
        authorizer = _registry_default_authorizer()
        if authorizer is not None:
            from graphql import GraphQLError

            from fraiseql.security.authorization import enforce_operation_value

            op_type, op_name = _derive_operation_info(request.query)
            try:
                decision = await enforce_operation_value(
                    authorizer=authorizer,
                    context=context,
                    operation_type=op_type,
                    operation_name=op_name,
                    arguments=request.variables or {},
                )
            except GraphQLError as exc:
                # Deny short-circuits: the Rust pipeline is never invoked.
                return Response(
                    content=json.dumps(_forbidden_error_payload(exc)).encode(),
                    media_type="application/json",
                )
            if decision.filters:
                # Per-row filters are impossible (work happens in Rust) → rely on
                # session variables + RLS for row scoping; never silently drop them.
                logger.warning(
                    "authorization filters are ignored on the /graphql/rust path; "
                    "rely on session variables + RLS for row scoping"
                )

        # Import the unified Rust function
        from fraiseql._fraiseql_rs import execute_graphql_query

        # Extract user context for authorization. ``context["user"]`` is None for
        # unauthenticated requests, so guard before attribute access.
        user = context.get("user") or {}
        user_context = {
            "user_id": user.get("id"),
            "permissions": user.get("permissions", []),
            "roles": user.get("roles", []),
        }

        # Call unified Rust pipeline - all work done in Rust!
        result_bytes = await execute_graphql_query(
            query_string=request.query or "",
            variables=request.variables or {},
            user_context=user_context,
        )

        # Return bytes directly (no Python JSON processing)
        return Response(
            content=result_bytes,
            media_type="application/json",
        )

    # Add metrics endpoint if enabled
    if hasattr(unified_executor, "get_metrics") and not is_production_env:

        @router.get("/graphql/metrics")
        async def metrics_endpoint() -> dict[str, Any]:
            """Get execution metrics."""
            return unified_executor.get_metrics()

    # Store turbo_registry for access by lifespan
    if turbo_registry is not None:
        router.turbo_registry = turbo_registry

    return router


def _format_error(error: Any, is_production: bool) -> dict[str, Any]:
    """Format GraphQL error based on environment."""
    if is_production:
        # Minimal info in production
        return {
            "message": "Internal server error",
            "extensions": {"code": "INTERNAL_SERVER_ERROR"},
        }

    # Full details in development
    formatted = {
        "message": error.message,
    }

    if error.locations:
        formatted["locations"] = [
            {"line": loc.line, "column": loc.column} for loc in error.locations
        ]

    if error.path:
        formatted["path"] = error.path

    if error.extensions:
        formatted["extensions"] = clean_unset_values(error.extensions)

    return formatted


# GraphiQL 2.0 HTML
GRAPHIQL_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>FraiseQL GraphiQL</title>
    <style>
        body {
            height: 100%;
            margin: 0;
            width: 100%;
            overflow: hidden;
        }
        #graphiql {
            height: 100vh;
        }
    </style>
    <script
        crossorigin
        src="https://unpkg.com/react@18/umd/react.production.min.js"
    ></script>
    <script
        crossorigin
        src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"
    ></script>
    <link rel="stylesheet" href="https://unpkg.com/graphiql/graphiql.min.css" />
</head>
<body>
    <div id="graphiql">Loading...</div>
    <script
        src="https://unpkg.com/graphiql/graphiql.min.js"
        type="application/javascript"
    ></script>
    <script>
        ReactDOM.render(
            React.createElement(GraphiQL, {
                fetcher: GraphiQL.createFetcher({
                    url: '/graphql',
                    headers: {
                        'Accept': 'application/json',
                        'Content-Type': 'application/json',
                    },
                }),
                defaultEditorToolsVisibility: true,
            }),
            document.getElementById('graphiql'),
        );
    </script>
</body>
</html>
"""

# Apollo Sandbox HTML
APOLLO_SANDBOX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>FraiseQL Apollo Sandbox</title>
    <style>
        body {
            margin: 0;
            overflow: hidden;
        }
        #sandbox {
            height: 100vh;
            width: 100vw;
        }
    </style>
</head>
<body>
    <div id="sandbox"></div>
    <script src="https://embeddable-sandbox.cdn.apollographql.com/_latest/embeddable-sandbox.umd.production.min.js"></script>
    <script>
        new window.EmbeddedSandbox({
            target: '#sandbox',
            initialEndpoint: '/graphql',
            includeCookies: true,
        });
    </script>
</body>
</html>
"""

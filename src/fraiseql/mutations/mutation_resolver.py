"""Helper utilities for mutation resolvers to extract field selections.

This module provides utilities for mutation resolvers to extract GraphQL field
selections from the GraphQL execution context (info object) and pass them to
the FFI boundary for response filtering.

The main entry point is `extract_field_selections()` which converts GraphQL
info.field_nodes into a format the Rust FFI can use to filter response fields.

Features:
- Extracts field selections from GraphQL execution info
- Builds nested selection trees for complex types
- Handles aliases correctly
- Safe for use with mutation unions (Success/Error types)

Example usage:
--------------
    from graphql import GraphQLResolveInfo

    async def resolve_create_location(
        input: CreateLocationInput,
        info: GraphQLResolveInfo,
    ) -> CreateLocationResponse:
        # Extract field selections from mutation context
        field_selections = extract_field_selections(info)

        # Pass to FFI for response filtering
        response_bytes = build_graphql_response_via_unified(
            json_strings=[json.dumps(result_data)],
            field_name="createLocation",
            type_name="CreateLocationSuccess",
            field_selections=json.dumps(field_selections) if field_selections else None,
        )
"""

import json
from typing import Any

from graphql import FieldNode, GraphQLResolveInfo, SelectionSetNode


def extract_field_selections(info: GraphQLResolveInfo | None) -> dict[str, Any] | None:
    """Extract field selections from mutation context.

    Converts GraphQL info.field_nodes into a format the Rust FFI can use to
    filter response fields. Returns a nested dictionary representing the
    requested field structure.

    Args:
        info: The GraphQL execution info from resolver context.

    Returns:
        A dictionary representing the field selection tree, or None if no
        selection info is available.

    Example:
        >>> # If mutation requests: { id, name, address { city } }
        >>> selections = extract_field_selections(info)
        >>> # Returns: {"id": True, "name": True, "address": {"city": True}}
    """
    if not info or not info.field_nodes:
        return None

    # Build selection tree from info.field_nodes
    selections = {}
    for field_node in info.field_nodes:
        if field_node.selection_set:
            selections.update(
                _traverse_selection_set(field_node.selection_set),
            )

    return selections if selections else None


def _traverse_selection_set(selection_set: SelectionSetNode) -> dict[str, Any]:
    """Recursively build selection tree from GraphQL SelectionSetNode.

    Args:
        selection_set: The GraphQL selection set to traverse.

    Returns:
        A dictionary representing the nested field selections.
    """
    selections = {}

    for selection in selection_set.selections:
        if not isinstance(selection, FieldNode):
            # Skip inline fragments and fragment spreads for now
            # (future enhancement could handle these)
            continue

        # Use alias if present, otherwise use actual field name
        field_name = selection.alias.value if selection.alias else selection.name.value

        # Skip special fields like __typename (handled automatically)
        if field_name.startswith("__"):
            continue

        if selection.selection_set:
            # Has nested selections - recurse
            selections[field_name] = _traverse_selection_set(selection.selection_set)
        else:
            # Leaf field - mark as selected
            selections[field_name] = True

    return selections


def convert_selections_to_json(selections: dict[str, Any] | None) -> str | None:
    """Convert field selections dictionary to JSON string for FFI.

    Args:
        selections: The field selections dictionary from extract_field_selections().

    Returns:
        JSON string representation, or None if selections is None/empty.
    """
    if not selections:
        return None
    return json.dumps(selections)

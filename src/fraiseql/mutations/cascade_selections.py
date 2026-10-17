"""GraphQL field selection parser for cascade data.

Extracts cascade field selections from GraphQL query and converts them
to a format that Rust can efficiently process.

This is a minimal implementation focused on the most common use cases:
- Field selection at cascade root level
- Type filtering (include/exclude) for updated entities
- Entity field selection with inline fragments
"""

import json
from typing import Any, Optional

from graphql import FieldNode, GraphQLResolveInfo, InlineFragmentNode


def extract_cascade_selections(info: GraphQLResolveInfo) -> Optional[str]:
    """Extract cascade field selections from GraphQL query.

    Parses the GraphQL selection set to determine which CASCADE fields
    were requested by the client. Returns JSON for Rust consumption.

    Args:
        info: GraphQL resolve info containing field selections

    Returns:
        JSON string with requested CASCADE fields, or None if CASCADE not selected

    Example returned JSON:
        {"fields": ["updated", "metadata"], "updated": {"fields": ["__typename", "id"]}}
    """
    if info is None or not info.field_nodes:
        return None

    for field_node in info.field_nodes:
        if not field_node.selection_set:
            continue

        for selection in field_node.selection_set.selections:
            if isinstance(selection, InlineFragmentNode):
                cascade_field = _find_cascade_in_fragment(selection)
                if cascade_field:
                    return _parse_cascade_to_json(cascade_field)
            elif (
                hasattr(selection, "name")
                and getattr(selection, "name", None)
                and selection.name.value == "cascade"  # type: ignore[attr-defined]
            ):  # type: ignore[attr-defined]
                return _parse_cascade_to_json(selection)  # type: ignore[attr-defined]

    return None


def _find_cascade_in_fragment(fragment: InlineFragmentNode) -> Optional[FieldNode]:
    """Find cascade field within an inline fragment."""
    if not fragment.selection_set:
        return None

    for selection in fragment.selection_set.selections:
        if (
            hasattr(selection, "name")
            and getattr(selection, "name", None)
            and selection.name.value == "cascade"  # type: ignore[attr-defined]
        ):  # type: ignore[attr-defined]
            return selection  # type: ignore[attr-defined]

    return None


def _parse_cascade_to_json(cascade_field: FieldNode) -> str:
    """Parse cascade field into JSON for Rust."""
    selections = {"fields": []}

    if not cascade_field.selection_set:
        return json.dumps(selections, separators=(",", ":"))

    # Parse each cascade field (updated, deleted, invalidations, metadata)
    for selection in cascade_field.selection_set.selections:
        if not hasattr(selection, "name"):
            continue

        field_name = selection.name.value  # type: ignore[attr-defined]
        selections["fields"].append(field_name)

        # Parse field-specific selections
        if field_name == "updated":
            selections["updated"] = _parse_updated_field(selection)  # type: ignore[attr-defined]
        elif field_name in ("deleted", "invalidations", "metadata"):
            selections[field_name] = _parse_simple_field(selection)  # type: ignore[attr-defined]

    return json.dumps(selections, separators=(",", ":"))


def _parse_updated_field(field_node: FieldNode) -> dict[str, Any]:
    """Parse 'updated' field with arguments and entity selections."""
    result: dict[str, Any] = {"fields": []}

    # Parse arguments (include/exclude)
    if hasattr(field_node, "arguments") and field_node.arguments:
        for arg in field_node.arguments:
            if arg.name.value in ("include", "exclude") and hasattr(arg.value, "values"):
                result[arg.name.value] = [v.value for v in arg.value.values]  # type: ignore[attr-defined]

    # Parse field selections
    if hasattr(field_node, "selection_set") and field_node.selection_set:
        entity_selections = {}

        for sel in field_node.selection_set.selections:
            if hasattr(sel, "name"):
                field_name = sel.name.value  # type: ignore[attr-defined]
                result["fields"].append(field_name)

                # Parse entity field with inline fragments
                if field_name == "entity" and hasattr(sel, "selection_set") and sel.selection_set:  # type: ignore[attr-defined]
                    entity_selections = _parse_entity_selections(sel)  # type: ignore[attr-defined]

        if entity_selections:
            result["entity_selections"] = entity_selections

    return result


def _parse_entity_selections(entity_field: FieldNode) -> dict[str, list[str]]:
    """Parse entity field selections with inline fragments."""
    selections: dict[str, list[str]] = {}
    common_fields: list[str] = []

    if not hasattr(entity_field, "selection_set") or not entity_field.selection_set:
        return selections

    for sel in entity_field.selection_set.selections:  # type: ignore[attr-defined]
        # Regular field (not in inline fragment)
        if hasattr(sel, "name"):
            common_fields.append(sel.name.value)  # type: ignore[attr-defined]
        # Inline fragment: ... on Post { id title }
        elif isinstance(sel, InlineFragmentNode) and hasattr(sel, "type_condition"):
            typename = sel.type_condition.name.value  # type: ignore[attr-defined]
            fields = _get_field_names(sel) + common_fields  # type: ignore[attr-defined]
            selections[typename] = fields

    return selections


def _parse_simple_field(field_node: FieldNode) -> dict[str, Any]:
    """Parse simple field (deleted, invalidations, metadata)."""
    return {"fields": _get_field_names(field_node)}


def _get_field_names(field_node: FieldNode) -> list[str]:
    """Extract field names from selection set."""
    if not hasattr(field_node, "selection_set") or not field_node.selection_set:
        return []

    return [sel.name.value for sel in field_node.selection_set.selections if hasattr(sel, "name")]  # type: ignore[attr-defined]

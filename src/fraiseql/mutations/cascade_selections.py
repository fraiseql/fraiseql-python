"""GraphQL field selection parser for cascade data.

Extracts cascade field selections from GraphQL query and converts them
to a format that Rust can efficiently process.

Rust filters on field names only: which cascade fields were selected, and
which subfields of each. ``Cascade.updated`` takes no arguments and its
``entity`` is a JSON scalar, so there is nothing else to send.
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

        # Rust filters each list on these field names, and reads nothing else
        if field_name in ("updated", "deleted", "invalidations", "metadata"):
            selections[field_name] = _parse_simple_field(selection)  # type: ignore[attr-defined]

    return json.dumps(selections, separators=(",", ":"))


def _parse_simple_field(field_node: FieldNode) -> dict[str, Any]:
    """Parse a cascade field (updated, deleted, invalidations, metadata)."""
    return {"fields": _get_field_names(field_node)}


def _get_field_names(field_node: FieldNode) -> list[str]:
    """Extract field names from selection set."""
    if not hasattr(field_node, "selection_set") or not field_node.selection_set:
        return []

    return [sel.name.value for sel in field_node.selection_set.selections if hasattr(sel, "name")]  # type: ignore[attr-defined]

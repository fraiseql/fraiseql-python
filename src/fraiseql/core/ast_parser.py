"""Parse GraphQL AST and extract field paths for SQL JSONB query generation."""

from collections.abc import Callable
from typing import Any, NamedTuple

from graphql import (
    DocumentNode,
    FragmentDefinitionNode,
    OperationDefinitionNode,
    SelectionSetNode,
    parse,
)

from fraiseql.core.fragment_resolver import resolve_all_fields


class FieldPath(NamedTuple):
    """Represents a flattened JSON path and alias extracted from a GraphQL selection set.

    ``path`` holds the JSON key of each field from the root to the leaf, and
    ``alias`` the leaf's response key. ``extract_flat_paths`` also gives, for each
    segment of ``path``, the field's name in the query (``names``) and its response
    key (``response_keys``: the alias, or the name). ``{ d: device { n: name } }``
    is ``FieldPath(alias="n", path=["device", "name"], names=("device", "name"),
    response_keys=("d", "n"))``. Both are None in a FieldPath built without them.
    """

    alias: str
    path: list[str]
    names: tuple[str, ...] | None = None
    response_keys: tuple[str, ...] | None = None


def parse_query_ast(
    source: str,
) -> tuple[OperationDefinitionNode, dict[str, FragmentDefinitionNode]]:
    """Parse the GraphQL query string and return the root operation and fragment map."""
    doc: DocumentNode = parse(source)
    op = next(
        (defn for defn in doc.definitions if isinstance(defn, OperationDefinitionNode)),
        None,
    )
    if op is None:
        msg = "No operation found in query"
        raise ValueError(msg)

    fragments: dict[str, FragmentDefinitionNode] = {
        defn.name.value: defn
        for defn in doc.definitions
        if isinstance(defn, FragmentDefinitionNode)
    }
    return op, fragments


def extract_flat_paths(
    selection: SelectionSetNode,
    fragments: dict[str, FragmentDefinitionNode],
    path: list[str] | None = None,
    transform_path: Callable[[str], str] | None = None,
    _names: tuple[str, ...] = (),
    _response_keys: tuple[str, ...] = (),
) -> list[FieldPath]:
    """Recursively extract flattened JSONB paths from the selection set.

    Args:
        selection: The selection set to process.
        fragments: The fragment definition map.
        path: The current path of JSON keys being built.
        transform_path: An optional function to transform each path segment
            (e.g. camelCase → snake_case).

    Returns:
        A flat list of FieldPath with alias and transformed path list, and the
        name and response key of each segment.
    """
    if path is None:
        path = []

    result: list[FieldPath] = []
    all_fields = resolve_all_fields(selection, fragments)

    for field in all_fields:
        name = field.name.value
        transformed = transform_path(name) if transform_path else name
        alias = field.alias.value if field.alias else name
        current_path = [*path, transformed]
        names = (*_names, name)
        response_keys = (*_response_keys, alias)

        if field.selection_set:
            result.extend(
                extract_flat_paths(
                    field.selection_set,
                    fragments,
                    current_path,
                    transform_path,
                    names,
                    response_keys,
                ),
            )
        else:
            result.append(
                FieldPath(alias=alias, path=current_path, names=names, response_keys=response_keys)
            )

    return result


def extract_field_paths_from_info(
    info: Any,
    transform_path: Callable[[str], str] | None = None,
) -> list[FieldPath] | None:
    """Extract field paths from GraphQL resolve info.

    Args:
        info: GraphQL resolve info object
        transform_path: Optional function to transform field names (e.g., to_snake_case)

    Returns:
        List of FieldPath objects or None if no selection set found
    """
    if not hasattr(info, "field_nodes") or not info.field_nodes:
        return None

    field_node = info.field_nodes[0]
    if not field_node.selection_set:
        return None

    fragments = getattr(info, "fragments", {})
    return extract_flat_paths(
        field_node.selection_set,
        fragments,
        transform_path=transform_path,
    )

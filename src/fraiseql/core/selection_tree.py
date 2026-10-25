"""Selection tree builder using materialized path pattern for GraphQL field selections.

This module provides data structures and functions for building field selections
with complete path information and type metadata from the schema registry.

The materialized path pattern means each FieldSelection contains the complete path
from root to leaf, making it easy to serialize and process in Rust without tree traversal.
"""

from dataclasses import dataclass
from typing import Any, Optional

from graphql import (
    GraphQLSchema,
    is_list_type,
    is_non_null_type,
    is_object_type,
)

from fraiseql.utils.casing import to_camel_case


@dataclass
class FieldInfo:
    """Information about a GraphQL field type."""

    type_name: str  # The GraphQL type name (e.g., "String", "Equipment")
    is_nested_object: bool  # True if this is an object type, False for scalars/enums
    # The field's name in the schema: "smtpServer", or "smtp_server" when the
    # schema keeps snake_case names (auto_camel_case=False)
    graphql_name: str | None = None


class GraphQLSchemaWrapper:
    """Python-side wrapper for querying GraphQL schema field types.

    This provides a simple interface for looking up field type information
    from a GraphQL schema, compatible with the schema registry interface
    expected by build_selection_tree().
    """

    def __init__(self, schema: GraphQLSchema):
        """Initialize with a GraphQL schema.

        Args:
            schema: The GraphQL schema to query
        """
        self.schema = schema

    def get_field_type(self, type_name: str, field_name: str) -> Optional[FieldInfo]:
        """Look up field type information in the GraphQL schema.

        Args:
            type_name: The parent GraphQL type name (e.g., "Assignment")
            field_name: The field name to look up (e.g., "equipment" or "network_config")

        Returns:
            FieldInfo with type information, or None if field not found

        Note:
            Field names can be in snake_case (from database) or camelCase (from GraphQL).
            This method tries both formats to find the field.

        Example:
            >>> wrapper = GraphQLSchemaWrapper(schema)
            >>> field_info = wrapper.get_field_type("Assignment", "equipment")
            >>> field_info.type_name
            'Equipment'
            >>> field_info.is_nested_object
            True
        """
        # Get the GraphQL type from schema
        graphql_type = self.schema.type_map.get(type_name)

        if not graphql_type or not is_object_type(graphql_type):
            return None

        # Get the field from the type
        fields = graphql_type.fields

        # Try original field name first
        graphql_name = field_name
        if field_name not in fields:
            # If not found, try camelCase version (GraphQL schema uses camelCase)
            graphql_name = to_camel_case(field_name)
            if graphql_name not in fields:
                return None
        field = fields[graphql_name]

        field_type = field.type

        # Unwrap NonNull and List wrappers to get the base type
        base_type = field_type
        while is_non_null_type(base_type) or is_list_type(base_type):
            base_type = base_type.of_type

        # Determine if this is a nested object
        is_nested = is_object_type(base_type)

        # Get the type name
        if hasattr(base_type, "name"):
            base_type_name = base_type.name
        else:
            base_type_name = str(base_type)

        return FieldInfo(
            type_name=base_type_name,
            is_nested_object=is_nested,
            graphql_name=graphql_name,
        )


@dataclass
class FieldSelection:
    """Represents a selected field with its full materialized path and alias.

    Example for query: assignments { device: equipment { deviceName: name } }

    Creates two selections:
    1. FieldSelection(
         path=["equipment"],           # Database path
         alias="device",                # GraphQL alias
         type_name="Equipment",
         is_nested_object=True
       )
    2. FieldSelection(
         path=["equipment", "name"],   # Full path from root
         alias="deviceName",            # Alias for this field
         type_name="String",
         is_nested_object=False
       )

    Note: Design is extensible - future versions can add fields like:
    - directives: list[DirectiveInfo]  # For @skip, @include
    - required_permissions: list[str]   # For authorization
    - scalar_transform: Optional[str]   # For custom transformations
    """

    path: list[str]  # Materialized path: ["equipment", "name"]
    alias: str  # Final output key: "deviceName"
    type_name: str  # GraphQL type: "String"
    is_nested_object: bool  # False for scalars, True for objects


def build_selection_tree(
    field_paths: list[Any],  # list[FieldPath]
    schema_registry: Any,  # SchemaRegistry
    parent_type: str,
) -> list[FieldSelection]:
    """Build flat list of field selections with materialized paths.

    Each FieldSelection contains the complete path from root to field,
    making it easy to serialize and process in Rust.

    Args:
        field_paths: List of FieldPath objects from AST parser
        schema_registry: Schema registry for type lookups
        parent_type: The GraphQL type name for the root object

    Returns:
        List of FieldSelection objects with materialized paths

    Example:
        >>> field_paths = [
        ...     FieldPath(alias="device", path=["equipment"]),
        ...     FieldPath(alias="deviceName", path=["equipment", "name"]),
        ... ]
        >>> selections = build_selection_tree(field_paths, registry, "Assignment")
        >>> len(selections)
        2
        >>> selections[0].path
        ['equipment']
        >>> selections[0].alias
        'device'
        >>> selections[1].path
        ['equipment', 'name']
    """
    selections = []

    for fp in field_paths:
        # Walk the path to resolve types at each level
        current_type = parent_type
        cumulative_path: list[str] = []

        for i, field_name in enumerate(fp.path):
            cumulative_path.append(field_name)

            # Look up field type in schema
            field_info = schema_registry.get_field_type(current_type, field_name)

            # Determine type information
            if field_info:
                field_type_name = field_info.type_name
                is_nested = field_info.is_nested_object
            else:
                # Field not found in schema - use unknown type
                field_type_name = "Unknown"
                is_nested = False

            # Determine alias for this level
            if i == len(fp.path) - 1:
                # Leaf field: use the alias from the AST
                alias = fp.alias
            else:
                # Intermediate field: its name in the schema. "smtp_server" is
                # "smtpServer", unless the schema keeps snake_case names
                # (auto_camel_case=False). camelCase when the schema doesn't say.
                graphql_name = getattr(field_info, "graphql_name", None)
                alias = graphql_name if isinstance(graphql_name, str) else to_camel_case(field_name)

            selections.append(
                FieldSelection(
                    path=cumulative_path.copy(),
                    alias=alias,
                    type_name=field_type_name,
                    is_nested_object=is_nested,
                )
            )

            # Move to next type in path
            if field_info:
                current_type = field_info.type_name

    # Deduplicate selections by path (keep first occurrence)
    unique_selections: dict[tuple[str, ...], FieldSelection] = {}
    for sel in selections:
        path_key = tuple(sel.path)
        if path_key not in unique_selections:
            unique_selections[path_key] = sel

    return list(unique_selections.values())


def named_object_type(graphql_type: Any) -> str | None:
    """The name of the object type a field returns (through lists and non-null), else None.

    ``[Note!]!`` gives ``"Note"``; a scalar, an interface or a union gives None.
    """
    while is_non_null_type(graphql_type) or is_list_type(graphql_type):
        graphql_type = graphql_type.of_type
    return graphql_type.name if is_object_type(graphql_type) else None


def rust_field_selections(
    field_paths: list[Any],  # list[FieldPath]
    schema: GraphQLSchema,
    parent_type: str,
) -> list[dict[str, Any]]:
    """The selection the Rust pipeline projects each row on, as it reads it.

    One dict per selected field, parents included: its JSON path
    (``materialized_path``, dot-separated), the key it answers under (``alias``), its
    type, and whether it is an object. Rust writes only these fields.
    """
    return [
        {
            "materialized_path": ".".join(sel.path),
            "alias": sel.alias,
            "type_name": sel.type_name,
            "is_nested_object": sel.is_nested_object,
        }
        for sel in build_selection_tree(
            field_paths, GraphQLSchemaWrapper(schema), parent_type=parent_type
        )
    ]

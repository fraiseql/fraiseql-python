"""WHERE clause normalization logic.

This module handles conversion of dict and WhereInput formats to the canonical
WhereClause representation.
"""

from __future__ import annotations

import logging
from typing import Any

from fraiseql.where_clause import ALL_OPERATORS, VECTOR_OPERATORS, FieldCondition, WhereClause

logger = logging.getLogger(__name__)


def _normalize_operator(op: str) -> str:
    """Convert operator name intelligently.

    Converts camelCase operators to snake_case ONLY if:
    1. The operator doesn't already have underscores
    2. The operator is not already registered in ALL_OPERATORS
    3. The converted snake_case version IS registered in ALL_OPERATORS

    This preserves camelCase operators like 'inSubnet' that are registered as-is,
    while converting hierarchy operators like 'descendantOfId' to 'descendant_of_id'.

    Args:
        op: Operator name from GraphQL input (may be camelCase)

    Returns:
        Normalized operator name ready for FieldCondition validation
    """
    from fraiseql.utils.casing import to_snake_case

    # If operator already has underscores or is already registered, use as-is
    if "_" in op or op in ALL_OPERATORS:
        return op

    # Try converting to snake_case
    snake_op = to_snake_case(op)

    # Use snake_case version if it's registered, otherwise fall back to original
    return snake_op if snake_op in ALL_OPERATORS else op


def normalize_dict_where(
    where_dict: dict[str, Any],
    view_name: str,
    table_columns: set[str] | None = None,
    jsonb_column: str = "data",
) -> WhereClause:
    """Normalize dict WHERE clause to canonical WhereClause.

    Args:
        where_dict: Dict-based WHERE clause
        view_name: Table/view name for metadata lookup
        table_columns: Set of actual table column names
        jsonb_column: JSONB column name (default: "data")

    Returns:
        Canonical WhereClause representation

    Examples:
        # Simple filter
        normalize_dict_where(
            {"status": {"eq": "active"}},
            "tv_allocation",
            {"status"}
        )
        # Returns: WhereClause with one FieldCondition using sql_column

        # Nested FK filter
        normalize_dict_where(
            {"machine": {"id": {"eq": "123"}}},
            "tv_allocation",
            {"machine_id", "data"}
        )
        # Returns: WhereClause with one FieldCondition using fk_column

        # Nested JSONB filter
        normalize_dict_where(
            {"device": {"name": {"eq": "Printer"}}},
            "tv_allocation",
            {"id", "data"}
        )
        # Returns: WhereClause with one FieldCondition using jsonb_path
    """
    # Handle empty dict
    if not where_dict:
        raise ValueError("WHERE clause cannot be empty dict")

    # Get metadata if not provided
    # CRITICAL FIX for Issue #124: Always retrieve table_columns if available from metadata
    from fraiseql.db import _table_metadata

    if table_columns is None and view_name in _table_metadata:
        metadata = _table_metadata[view_name]
        # Use metadata columns if available, otherwise use empty set
        # Empty set signals that metadata exists but no columns were registered
        if "columns" in metadata:
            table_columns = set(metadata["columns"]) if metadata["columns"] else set()
        else:
            table_columns = set()

    conditions = []
    nested_clauses = []
    not_clause = None
    logical_op = "AND"

    # Import field name converter
    from fraiseql.utils.casing import to_snake_case

    for original_field_name, field_value in where_dict.items():
        # Handle logical operators first (before conversion)
        if original_field_name == "OR":
            # OR is a list of WHERE clauses
            if isinstance(field_value, list):
                or_clauses = []
                for or_dict in field_value:
                    or_clause = normalize_dict_where(
                        or_dict, view_name, table_columns, jsonb_column
                    )
                    # CRITICAL FIX: Preserve the entire WhereClause structure
                    # Don't flatten to just conditions - this loses AND grouping
                    or_clauses.append(or_clause)

                # Create nested OR clause by combining the clauses
                if or_clauses:
                    nested_clauses.append(WhereClause(nested_clauses=or_clauses, logical_op="OR"))
            continue

        if original_field_name == "AND":
            # AND is a list of WHERE clauses
            if isinstance(field_value, list):
                for and_dict in field_value:
                    and_clause = normalize_dict_where(
                        and_dict, view_name, table_columns, jsonb_column
                    )
                    # CRITICAL FIX: Preserve nested clauses (like OR inside AND)
                    # If the clause has nested structures, preserve it as a nested clause
                    if and_clause.nested_clauses or and_clause.not_clause:
                        # Has complex structure - preserve as nested clause
                        nested_clauses.append(and_clause)
                    else:
                        # Simple conditions - can be flattened into parent AND
                        conditions.extend(and_clause.conditions)
            continue

        if original_field_name == "NOT":
            # NOT is a single WHERE clause
            if isinstance(field_value, dict):
                not_clause = normalize_dict_where(
                    field_value, view_name, table_columns, jsonb_column
                )
            continue

        # Convert camelCase field names to snake_case for database lookups
        # This allows GraphQL camelCase convention while using snake_case in DB
        field_name = original_field_name
        if "_" not in field_name:
            field_name = to_snake_case(field_name)

        # Regular field filter
        if not isinstance(field_value, dict):
            # Scalar value, wrap in eq operator
            field_value = {"eq": field_value}  # noqa: PLW2901

        # Check if this is a nested object filter
        is_nested, use_fk = _is_nested_object_filter(
            field_name, field_value, table_columns, view_name
        )

        if is_nested and use_fk:
            # FK-based nested filter: machine.id → machine_id
            fk_column = f"{field_name}_id"

            # Extract nested filters
            for original_nested_field, nested_value in field_value.items():
                # Convert nested field names too
                nested_field = original_nested_field
                if "_" not in nested_field:
                    nested_field = to_snake_case(nested_field)

                if nested_field == "id" and isinstance(nested_value, dict):
                    # This is the FK lookup
                    for op, val in nested_value.items():
                        if val is None:
                            continue

                        # Convert operator name from camelCase to snake_case
                        # (e.g., descendantOfId → descendant_of_id)
                        operator = _normalize_operator(op)

                        condition = FieldCondition(
                            field_path=[field_name, "id"],
                            operator=operator,
                            value=val,
                            lookup_strategy="fk_column",
                            target_column=fk_column,
                        )
                        conditions.append(condition)

                        logger.debug(
                            f"Dict WHERE: FK nested filter {field_name}.id → {fk_column}",
                            extra={"condition": condition},
                        )
                # Other nested fields use JSONB
                elif isinstance(nested_value, dict):
                    for op, val in nested_value.items():
                        if val is None:
                            continue

                        # Convert operator name from camelCase to snake_case
                        # (e.g., descendantOfId → descendant_of_id)
                        operator = _normalize_operator(op)

                        condition = FieldCondition(
                            field_path=[field_name, nested_field],
                            operator=operator,
                            value=val,
                            lookup_strategy="jsonb_path",
                            target_column=jsonb_column,
                            jsonb_path=[field_name, nested_field],
                        )
                        conditions.append(condition)

        elif is_nested and not use_fk:
            # JSONB-based nested filter: handle arbitrarily deep nesting
            for original_nested_field, nested_value in field_value.items():
                # Convert nested field names too
                nested_field = original_nested_field
                if "_" not in nested_field:
                    nested_field = to_snake_case(nested_field)

                if isinstance(nested_value, dict):
                    # Check if this nested value itself contains nested operators
                    # If so, recursively normalize it
                    has_nested_ops = any(
                        isinstance(v, dict) and not any(k in ("OR", "AND", "NOT") for k in v)
                        for v in nested_value.values()
                    )

                    if has_nested_ops:
                        # This is a deeply nested object - recursively normalize
                        # Create a nested WHERE clause with the parent path prepended
                        nested_where = {nested_field: nested_value}
                        nested_clause = normalize_dict_where(
                            nested_where, view_name, table_columns, jsonb_column
                        )
                        # The nested clause will have conditions with field_path
                        # like [parent, child, ...]
                        # We need to prepend our current field_name to make it
                        # [field_name, parent, child, ...]
                        for condition in nested_clause.conditions:
                            # Prepend field_name to field_path and jsonb_path
                            condition.field_path.insert(0, field_name)
                            if condition.jsonb_path:
                                condition.jsonb_path.insert(0, field_name)
                        conditions.extend(nested_clause.conditions)

                        # Handle nested clauses too
                        for nested_clause_item in nested_clause.nested_clauses:
                            # Recursively prepend field_name to all conditions in nested clauses
                            for condition in nested_clause_item.conditions:
                                condition.field_path.insert(0, field_name)
                                if condition.jsonb_path:
                                    condition.jsonb_path.insert(0, field_name)
                            nested_clauses.append(nested_clause_item)

                        if nested_clause.not_clause:
                            # Handle not_clause recursively
                            for condition in nested_clause.not_clause.conditions:
                                condition.field_path.insert(0, field_name)
                                if condition.jsonb_path:
                                    condition.jsonb_path.insert(0, field_name)
                            not_clause = nested_clause.not_clause
                    else:
                        # This is a direct nested field with operators
                        for op, val in nested_value.items():
                            if val is None:
                                continue

                            # Convert operator name from camelCase to snake_case
                            # (e.g., descendantOfId → descendant_of_id)
                            operator = _normalize_operator(op)

                            condition = FieldCondition(
                                field_path=[field_name, nested_field],
                                operator=operator,
                                value=val,
                                lookup_strategy="jsonb_path",
                                target_column=jsonb_column,
                                jsonb_path=[field_name, nested_field],
                            )
                            conditions.append(condition)

                            logger.debug(
                                f"Dict WHERE: JSONB nested filter {field_name}.{nested_field}",
                                extra={"condition": condition},
                            )

        else:
            # Direct column filter: status = 'active'
            # Determine lookup strategy based on table structure
            lookup_strategy = "sql_column"
            target_column = field_name

            # Check if we know table columns
            if table_columns is not None:
                # We have table column information - use it to decide
                if field_name not in table_columns:
                    # Column doesn't exist in table, must be in JSONB
                    lookup_strategy = "jsonb_path"
                    target_column = jsonb_column
            else:
                # We don't know table columns - check if table uses JSONB for data
                from fraiseql.db import _table_metadata

                if view_name in _table_metadata:
                    metadata = _table_metadata[view_name]
                    # Table uses JSONB data column - default to JSONB paths
                    # (unless field is 'id' which is often a top-level column)
                    if metadata.get("has_jsonb_data", False) and field_name != "id":
                        lookup_strategy = "jsonb_path"
                        target_column = jsonb_column

            for op, val in field_value.items():
                if val is None:
                    continue

                # Convert operator name from camelCase to snake_case
                # (e.g., descendantOfId → descendant_of_id)
                operator = _normalize_operator(op)

                if lookup_strategy == "jsonb_path":
                    condition = FieldCondition(
                        field_path=[field_name],
                        operator=operator,
                        value=val,
                        lookup_strategy="jsonb_path",
                        target_column=jsonb_column,
                        jsonb_path=[field_name],
                    )
                else:
                    condition = FieldCondition(
                        field_path=[field_name],
                        operator=operator,
                        value=val,
                        lookup_strategy="sql_column",
                        target_column=target_column,
                    )

                conditions.append(condition)

    return WhereClause(
        conditions=conditions,
        logical_op=logical_op,
        nested_clauses=nested_clauses,
        not_clause=not_clause,
    )


def _is_nested_object_filter(
    field_name: str,
    field_filter: dict,
    table_columns: set[str] | None,
    view_name: str,
) -> tuple[bool, bool]:
    """Detect if this is a nested object filter and how to handle it.

    Returns:
        Tuple of (is_nested, use_fk):
        - is_nested: True if this is a nested object filter
        - use_fk: True if should use FK column, False if should use JSONB path
    """
    # Check if any keys are vector operators - these should not be treated as nested
    # Example: {"cosine_distance": {"vector": [...], "threshold": 0.5}}
    if any(k in VECTOR_OPERATORS for k in field_filter):
        return False, False

    # Check if field_filter has nested operators
    # {"id": {"eq": value}} → nested
    # {"eq": value} → not nested
    has_nested_operator_values = any(
        isinstance(v, dict) and not any(k in ("OR", "AND", "NOT") for k in v)
        for v in field_filter.values()
    )

    if not has_nested_operator_values:
        return False, False

    # Check for explicit FK metadata first
    from fraiseql.db import _table_metadata

    if view_name in _table_metadata:
        metadata = _table_metadata[view_name]
        fk_relationships = metadata.get("fk_relationships", {})
        validate_strict = metadata.get("validate_fk_strict", True)

        # Explicit FK declared?
        if field_name in fk_relationships:
            fk_column = fk_relationships[field_name]

            # Verify FK column exists
            # CRITICAL FIX for Issue #124: Check if table_columns is not None (not just truthy)
            # Empty set is falsy but valid, so use explicit None check
            if table_columns is not None and fk_column in table_columns:
                logger.debug(f"Using explicit FK relationship: {field_name} → {fk_column}")
                return True, True
            error_msg = (
                f"FK relationship declared ({field_name} → {fk_column}) "
                f"but column '{fk_column}' not in table_columns. "
            )

            if validate_strict:
                # Strict mode: this should have been caught at registration
                # If we get here, it's a bug
                raise RuntimeError(error_msg + "This should have been caught during registration.")
            # Lenient mode: warn and fallback to JSONB
            logger.warning("%s Using JSONB fallback.", error_msg)

    # Fallback to convention-based detection
    # Check if this looks like a FK-based nested filter
    # Pattern: {"id": {"eq": value}}
    if "id" in field_filter and isinstance(field_filter["id"], dict):
        # Check if FK column exists
        potential_fk_column = f"{field_name}_id"

        # CRITICAL FIX for Issue #124: Check if table_columns is not None (not just truthy)
        # Empty set is falsy but valid, so use explicit None check
        if table_columns is not None and potential_fk_column in table_columns:
            # FK column exists, use it
            logger.debug(
                f"Dict WHERE: Detected FK nested object filter for {field_name} "
                f"(FK column {potential_fk_column} exists)"
            )
            return True, True

    # Default to JSONB path for nested filters
    logger.debug(f"Dict WHERE: Detected JSONB nested filter for {field_name}")
    return True, False


def normalize_whereinput(
    where_input: Any,
    view_name: str,
    table_columns: set[str] | None = None,
    jsonb_column: str = "data",
) -> WhereClause:
    """Normalize WhereInput object to canonical WhereClause.

    Args:
        where_input: WhereInput object with _to_whereinput_dict() method
        view_name: Table/view name for metadata lookup
        table_columns: Set of actual table column names
        jsonb_column: JSONB column name (default: "data")

    Returns:
        Canonical WhereClause representation

    Raises:
        TypeError: If where_input doesn't have _to_whereinput_dict() method
    """
    if not hasattr(where_input, "_to_whereinput_dict"):
        raise TypeError(
            f"WhereInput object must have _to_whereinput_dict() method. Got: {type(where_input)}"
        )

    # Convert to dict
    where_dict = where_input._to_whereinput_dict()

    logger.debug(
        "WhereInput normalization: converted to dict",
        extra={
            "input_type": type(where_input).__name__,
            "dict_keys": list(where_dict.keys()),
        },
    )

    # Use dict normalization logic
    return normalize_dict_where(where_dict, view_name, table_columns, jsonb_column)

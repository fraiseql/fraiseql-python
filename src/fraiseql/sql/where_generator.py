"""Dynamic WHERE clause generator with SQL translation for dataclasses.

This module provides utilities to dynamically generate filter types for
dataclasses that translate into SQL WHERE clauses. It uses parameterized
SQL with placeholders to prevent SQL injection. The module supports a set
of filter operators mapped to SQL expressions and dynamic creation of
filter dataclasses with a `to_sql()` method.

This enables flexible and type-safe construction of SQL WHERE conditions
from Python data structures, useful in GraphQL-to-SQL translation layers
and similar query builders.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from typing import (
    Any,
    Protocol,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    runtime_checkable,
)

from psycopg.sql import SQL, Composed, Literal

from .where.core.field_detection import FieldType, detect_field_type
from .where.operators import get_operator_function

# Define a type variable for the generic value to coerce
TValue = TypeVar("TValue", bound=object)


@runtime_checkable
class DynamicType(Protocol):
    """Protocol for dynamic filter types convertible to SQL WHERE clause strings."""

    def to_sql(self, parent_path: str | None = None) -> Composed | None:
        """Return a properly parameterized SQL snippet representing this filter.

        Args:
            parent_path: Optional JSONB path from parent for nested objects.

        Returns:
            A psycopg Composed object with parameterized SQL, or None if no condition.
        """


def build_operator_composed(
    path_sql: SQL | Composed,
    op: str,
    val: object,
    field_type: type | None = None,
    detected_field_type: FieldType | None = None,
) -> Composed:
    """Build parameterized SQL for a specific operator using psycopg Composed.

    This function uses the new function-based operator mapping system.

    Args:
        path_sql: The SQL object representing the JSONB path expression.
        op: The operator name.
        val: The value to compare against.
        field_type: Optional type hint for proper casting.
        detected_field_type: Optional pre-detected field type (overrides detection).

    Returns:
        A psycopg Composed object with properly parameterized SQL.
    """
    # Use pre-detected field type if provided, otherwise detect it
    if detected_field_type is None:
        detected_field_type = detect_field_type("", val, field_type)

    vector_distance_operators = {
        "cosine_distance",
        "l2_distance",
        "l1_distance",
        "inner_product",
        "hamming_distance",
        "jaccard_distance",
    }

    # Vector distance filters carry both the query vector and its threshold.
    # The operator builders render the distance expression, so add the boolean
    # comparison here before the expression is used as a WHERE condition.
    if (
        detected_field_type in (FieldType.VECTOR, FieldType.SPARSE_VECTOR)
        and op in vector_distance_operators
    ):
        if isinstance(val, dict):
            vector = val.get("vector")
            threshold = val.get("threshold", 0.5)
            comparison = val.get("comparison", "lt")
        elif isinstance(val, (list, tuple)) and len(val) == 2:
            vector, threshold = val
            comparison = "lt"
        else:
            raise ValueError(
                f"Vector operator requires dict or (vector, threshold) tuple, got {val!r}"
            )

        comparison_operator = {
            "lt": "<",
            "lte": "<=",
            "gt": ">",
            "gte": ">=",
            "eq": "=",
            "neq": "<>",
        }.get(comparison)
        if comparison_operator is None:
            raise ValueError(f"Unsupported vector comparison '{comparison}'")

        operator_func = get_operator_function(detected_field_type, op)
        distance_sql = operator_func(path_sql, vector)
        return Composed(
            [SQL("("), distance_sql, SQL(f") {comparison_operator} "), Literal(threshold)]
        )

    # Get the operator function
    operator_func = get_operator_function(detected_field_type, op)

    # Call the operator function
    return operator_func(path_sql, val)


def _build_nested_path(parent_path: str | None, field_name: str) -> str:
    """Build a JSONB path for nested object fields.

    Args:
        parent_path: The parent JSONB path (e.g., "data -> 'parent'")
        field_name: The field name to append to the path

    Returns:
        A JSONB path string for the nested field
    """
    if parent_path:
        return f"{parent_path} -> '{field_name}'"
    return f"data -> '{field_name}'"


def _make_filter_field_composed(
    name: str,
    valdict: dict[str, object],
    json_path: str,
    field_type: type | None = None,
) -> Composed | None:
    """Generate a parameterized SQL expression for a single field filter.

    Args:
        name: Field name to filter.
        valdict: Dict mapping operator strings to filter values.
        json_path: SQL JSON path expression string accessing the field.
        field_type: Optional type hint for the field.

    Returns:
        Composed SQL WHERE clause for the field, or None if no valid operators found.
    """
    conditions = []

    for op, val in valdict.items():
        if val is None:
            continue
        try:
            # Build the JSONB path expression
            # For arrays, use -> to get JSON array, for others use ->> to get text
            from .where.core.field_detection import detect_field_type

            detected_field_type = detect_field_type(name, val, field_type)

            if detected_field_type == FieldType.FULLTEXT:
                # For full-text search, use the direct column (tsvector)
                path_sql = SQL(name)  # type: ignore[arg-type]
            elif detected_field_type == FieldType.ARRAY and op not in ("in", "in_", "notin", "nin"):
                # For arrays, get the JSON array value
                # BUT: if using IN/NOTIN operators, we're checking membership of scalar values,
                # so we still need text extraction (->>)
                path_sql = Composed(
                    [SQL("("), SQL(json_path), SQL(" -> "), Literal(name), SQL(")")]
                )
            elif detected_field_type == FieldType.JSONB:
                # For JSONB, get the JSON value (preserve JSONB type)
                path_sql = Composed(
                    [SQL("("), SQL(json_path), SQL(" -> "), Literal(name), SQL(")")]
                )
            else:
                # For other types, get the text value
                # This includes IN/NOTIN operators with list values - the field is text, not array
                path_sql = Composed(
                    [SQL("("), SQL(json_path), SQL(" ->> "), Literal(name), SQL(")")]
                )

            condition = build_operator_composed(path_sql, op, val, field_type, detected_field_type)
            conditions.append(condition)
        except ValueError:
            # Skip unsupported operators
            continue

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    # Combine multiple conditions with AND
    result_parts = []
    for i, cond in enumerate(conditions):
        if i > 0:
            result_parts.append(SQL(" AND "))
        result_parts.append(cond)
    return Composed(result_parts)


def _build_where_to_sql(
    fields: list[str],
    type_hints: dict[str, type] | None = None,
    graphql_info: Any | None = None,
) -> Callable[[object, str | None], Composed | None]:
    """Build a `to_sql` method for a dynamic filter dataclass.

    Args:
        fields: List of filter field names.
        type_hints: Optional mapping of field names to their types.
        graphql_info: Optional GraphQL resolve info context for field type extraction.

    Returns:
        A function suitable as a `to_sql(self, parent_path)` method returning Composed SQL.
    """

    def to_sql(self: object, parent_path: str | None = None) -> Composed | None:
        # Enhance type hints with GraphQL context if available
        enhanced_type_hints = type_hints
        if graphql_info:
            try:
                from fraiseql.graphql.field_type_extraction import (
                    enhance_type_hints_with_graphql_context,
                )

                enhanced_type_hints = enhance_type_hints_with_graphql_context(
                    type_hints, graphql_info, fields
                )
            except ImportError:
                # Fallback gracefully if GraphQL extraction is not available
                pass

        conditions: list[Composed] = []
        logical_or: list[Composed] = []
        logical_and: list[Composed] = []
        logical_not: Composed | None = None

        for name in fields:
            val = getattr(self, name, None)
            if val is None:
                continue

            # Handle logical operators specially
            if name == "OR":
                if isinstance(val, list):
                    for item in val:
                        if hasattr(item, "to_sql"):
                            item_sql = item.to_sql(parent_path)
                            if item_sql:
                                logical_or.append(item_sql)
                        elif isinstance(item, dict):
                            # Handle plain dict items in OR clause
                            # Each dict represents a complete where condition
                            dict_conditions: list[Composed] = []
                            for field_name, field_val in item.items():
                                if isinstance(field_val, dict):
                                    field_type = (
                                        enhanced_type_hints.get(field_name)
                                        if enhanced_type_hints
                                        else None
                                    )
                                    json_path = parent_path or "data"
                                    cond = _make_filter_field_composed(
                                        field_name,
                                        cast("dict[str, object]", field_val),
                                        json_path,
                                        field_type,
                                    )
                                    if cond:
                                        dict_conditions.append(cond)
                            if dict_conditions:
                                if len(dict_conditions) == 1:
                                    logical_or.append(dict_conditions[0])
                                else:
                                    # Multiple conditions in this dict, combine with AND
                                    and_parts: list[SQL | Composed] = []
                                    for i, cond in enumerate(dict_conditions):
                                        if i > 0:
                                            and_parts.append(SQL(" AND "))
                                        and_parts.append(cond)
                                    logical_or.append(Composed(and_parts))
            elif name == "AND":
                if isinstance(val, list):
                    for item in val:
                        if hasattr(item, "to_sql"):
                            item_sql = item.to_sql(parent_path)
                            if item_sql:
                                logical_and.append(item_sql)
                        elif isinstance(item, dict):
                            # Handle plain dict items in AND clause
                            dict_conditions: list[Composed] = []
                            for field_name, field_val in item.items():
                                if isinstance(field_val, dict):
                                    field_type = (
                                        enhanced_type_hints.get(field_name)
                                        if enhanced_type_hints
                                        else None
                                    )
                                    json_path = parent_path or "data"
                                    cond = _make_filter_field_composed(
                                        field_name,
                                        cast("dict[str, object]", field_val),
                                        json_path,
                                        field_type,
                                    )
                                    if cond:
                                        dict_conditions.append(cond)
                            if dict_conditions:
                                if len(dict_conditions) == 1:
                                    logical_and.append(dict_conditions[0])
                                else:
                                    # Multiple conditions in this dict, combine with AND
                                    and_parts_inner: list[SQL | Composed] = []
                                    for i, cond in enumerate(dict_conditions):
                                        if i > 0:
                                            and_parts_inner.append(SQL(" AND "))
                                        and_parts_inner.append(cond)
                                    logical_and.append(Composed(and_parts_inner))
            elif name == "NOT":
                if hasattr(val, "to_sql"):
                    not_sql = val.to_sql(parent_path)
                    if not_sql:
                        logical_not = Composed([SQL("NOT ("), not_sql, SQL(")")])
            # Handle regular fields
            elif hasattr(val, "to_sql"):
                # For nested objects, build the JSONB path by appending the field name
                nested_path = _build_nested_path(parent_path, name)
                sql = val.to_sql(nested_path)
                if sql:
                    conditions.append(sql)
            elif isinstance(val, dict):
                field_type = enhanced_type_hints.get(name) if enhanced_type_hints else None
                # Use parent_path if provided, otherwise default to "data"
                json_path = parent_path or "data"
                cond = _make_filter_field_composed(
                    name,
                    cast("dict[str, object]", val),
                    json_path,
                    field_type,
                )
                if cond:
                    conditions.append(cond)

        # Collect all condition parts
        all_conditions: list[Composed] = []

        # Add regular field conditions (combine with implicit AND)
        if conditions:
            if len(conditions) == 1:
                all_conditions.append(conditions[0])
            else:
                # Combine multiple conditions with AND
                and_parts: list[SQL | Composed] = []
                for i, cond in enumerate(conditions):
                    if i > 0:
                        and_parts.append(SQL(" AND "))
                    and_parts.append(cond)
                all_conditions.append(Composed(and_parts))

        # Add explicit AND conditions
        if logical_and:
            all_conditions.extend(logical_and)

        # Add OR conditions (group them together)
        if logical_or:
            if len(logical_or) == 1:
                all_conditions.append(logical_or[0])
            else:
                # Combine multiple OR conditions
                or_parts: list[SQL | Composed] = []
                for i, or_cond in enumerate(logical_or):
                    if i > 0:
                        or_parts.append(SQL(" OR "))
                    or_parts.append(Composed([SQL("("), or_cond, SQL(")")]))
                all_conditions.append(Composed([SQL("("), Composed(or_parts), SQL(")")]))

        # Add NOT condition
        if logical_not:
            all_conditions.append(logical_not)

        if not all_conditions:
            return None

        # Combine all conditions with AND
        if len(all_conditions) == 1:
            return all_conditions[0]

        result_parts: list[SQL | Composed] = []
        for i, cond in enumerate(all_conditions):
            if i > 0:
                result_parts.append(SQL(" AND "))
            result_parts.append(cond)

        return Composed(result_parts)

    return to_sql


def unwrap_type(typ: type[Any]) -> type[Any]:
    """Unwrap Optional[T] to T, or return type as is.

    Args:
        typ: A type annotation to unwrap.

    Returns:
        The inner type if `typ` is Optional[T], else `typ` unchanged.
    """
    if get_origin(typ) is Union:
        args = [arg for arg in get_args(typ) if arg is not type(None)]
        if len(args) == 1:
            return args[0]
    return typ


@cache
def safe_create_where_type(cls: type[object]) -> type[DynamicType] | object:
    """Create a dataclass-based WHERE filter type dynamically for a given class.

    Args:
        cls: The base dataclass to generate filter type for.

    Returns:
        A new dataclass type implementing DynamicType with dict[str, base_type] | None
        fields and a to_sql method for SQL generation with parameterized queries.
    """
    type_hints = get_type_hints(cls)
    annotations: dict[str, object] = {}
    attrs: dict[str, object] = {}

    for name, typ in type_hints.items():
        unwrap_type(typ)
        annotations[name] = dict[str, object] | None  # Use object for the dict value type
        attrs[name] = field(default_factory=dict)

    # Add logical operators fields
    annotations["OR"] = list | None
    annotations["AND"] = list | None
    annotations["NOT"] = object | None
    attrs["OR"] = None
    attrs["AND"] = None
    attrs["NOT"] = None

    field_names = [*type_hints.keys(), "OR", "AND", "NOT"]
    attrs["__annotations__"] = annotations
    attrs["to_sql"] = _build_where_to_sql(field_names, type_hints)

    where_name = f"{cls.__name__}Where"
    return dataclass(type(where_name, (), attrs))


def create_where_type_with_graphql_context(
    cls: type[object], graphql_info: Any | None = None
) -> type[DynamicType] | object:
    """Create a dataclass-based WHERE filter type with GraphQL context support.

    This function is similar to safe_create_where_type but supports GraphQL context
    for enhanced field type extraction, enabling proper network operator handling.

    Args:
        cls: The base dataclass to generate filter type for.
        graphql_info: Optional GraphQL resolve info context for field type extraction.

    Returns:
        A new dataclass type implementing DynamicType with enhanced field type support.
    """
    type_hints = get_type_hints(cls)
    annotations: dict[str, object] = {}
    attrs: dict[str, object] = {}

    for name, typ in type_hints.items():
        unwrap_type(typ)
        annotations[name] = dict[str, object] | None  # Use object for the dict value type
        attrs[name] = field(default_factory=dict)

    # Add logical operators fields
    annotations["OR"] = list | None
    annotations["AND"] = list | None
    annotations["NOT"] = object | None
    attrs["OR"] = None
    attrs["AND"] = None
    attrs["NOT"] = None

    field_names = [*type_hints.keys(), "OR", "AND", "NOT"]
    attrs["__annotations__"] = annotations
    attrs["to_sql"] = _build_where_to_sql(field_names, type_hints, graphql_info)

    where_name = f"{cls.__name__}WhereWithContext"
    return dataclass(type(where_name, (), attrs))

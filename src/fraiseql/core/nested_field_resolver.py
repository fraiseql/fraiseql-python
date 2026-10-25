"""Smart field resolver for nested objects with sql_source.

This module provides a field resolver that handles nested objects based on their
resolve_nested setting:

- resolve_nested=False (default): Assumes data is embedded in parent's JSONB
- resolve_nested=True: Makes separate queries to the nested type's sql_source

The default behavior prioritizes performance by avoiding N+1 queries and works
well with PostgreSQL views that pre-join related data into JSONB columns.
"""

import logging
from collections.abc import Mapping
from enum import Enum
from typing import Any, Callable, get_args, get_origin

from graphql import GraphQLResolveInfo

from fraiseql.utils.casing import to_snake_case

logger = logging.getLogger(__name__)


def create_smart_nested_field_resolver(field_name: str, field_type: Any) -> Callable:
    """Create a field resolver that handles nested objects based on resolve_nested setting.

    This resolver is only used when resolve_nested=True is set on the field type.
    It provides intelligent resolution by:

    1. First checking if the field data is already present in the parent object (embedded)
    2. If data is present, returns it directly without any database query
    3. If data is missing, attempts to query the nested type's sql_source
    4. Falls back to None if neither approach works

    The resolver tries to be smart about parameters:
    - Looks for foreign key fields (e.g., field_name + "_id")
    - Passes tenant_id from context if available
    - Handles errors gracefully if required parameters are missing

    Args:
        field_name: The name of the field being resolved (e.g., "department")
        field_type: The type of the field (must have resolve_nested=True and sql_source)

    Returns:
        An async resolver function for GraphQL that handles the nested object resolution

    Note:
        This function is only called when resolve_nested=True. For the default behavior
        (resolve_nested=False), FraiseQL uses the standard field resolver that assumes
        data is embedded in the parent's JSONB column.
    """

    async def resolve_nested_field(
        parent: dict[str, Any], info: GraphQLResolveInfo, **kwargs: Any
    ) -> Any:
        """Resolve a nested field, preferring embedded data over separate queries."""
        # First, check if the data is already present in the parent object
        value = getattr(parent, field_name, None)

        if value is not None:
            # Data is embedded - return it directly
            logger.debug(
                f"Field '{field_name}' has embedded data, "
                f"returning directly without querying sql_source"
            )

            # If it's a dict and the field type is a FraiseQL type, convert it
            if isinstance(value, dict):
                # Extract actual type from Optional if needed
                actual_field_type = field_type
                import types
                from typing import Union, get_args, get_origin

                origin = get_origin(field_type)
                if origin is Union or origin is types.UnionType:
                    args = get_args(field_type)
                    non_none_types = [t for t in args if t is not type(None)]
                    if non_none_types:
                        actual_field_type = non_none_types[0]

                # Check if the field type is a FraiseQL type
                if hasattr(actual_field_type, "__fraiseql_definition__"):
                    if hasattr(actual_field_type, "from_dict"):
                        return actual_field_type.from_dict(value)
                    # Try direct instantiation
                    try:
                        return actual_field_type(**value)
                    except Exception as e:
                        logger.debug(f"Could not convert dict to {actual_field_type.__name__}: {e}")

            return value

        # Data is not embedded - check if we should query sql_source
        actual_field_type = field_type
        import types
        from typing import Union, get_args, get_origin

        origin = get_origin(field_type)
        if origin is Union or origin is types.UnionType:
            args = get_args(field_type)
            non_none_types = [t for t in args if t is not type(None)]
            if non_none_types:
                actual_field_type = non_none_types[0]

        # Check if the field type has sql_source and we have the necessary context
        if (
            hasattr(actual_field_type, "__gql_table__")
            and actual_field_type.__gql_table__
            and "db" in info.context
        ):
            # Check if we have the required parameters for querying
            # This is where the tenant_id issue occurs - we need to handle it gracefully

            # Try to get foreign key from parent for relationship
            fk_field = f"{field_name}_id"  # Common pattern: organization -> organization_id
            fk_value = getattr(parent, fk_field, None)

            if fk_value:
                # Attempt to query the related entity
                db = info.context["db"]
                table = actual_field_type.__gql_table__
                try:
                    # Build query parameters based on what's available in context
                    query_params = {"id": fk_value}

                    # Add tenant_id if available and the table requires it
                    if "tenant_id" in info.context:
                        query_params["tenant_id"] = info.context["tenant_id"]

                    logger.debug(
                        f"Attempting to query {table} for field '{field_name}' "
                        f"with params: {query_params}"
                    )

                    # Use find_one if available
                    if hasattr(db, "find_one"):
                        result = await db.find_one(table, **query_params)
                        if result:
                            if hasattr(actual_field_type, "from_dict"):
                                return actual_field_type.from_dict(result)
                            return actual_field_type(**result)

                except Exception as e:
                    logger.warning(
                        f"Failed to query {table} for field '{field_name}': {e}. "  # type: ignore[possibly-unbound]
                        f"This may be expected if the data should be embedded."
                    )

        # No data found - return None
        return None

    return resolve_nested_field


def should_use_nested_resolver(field_type: type) -> bool:
    """Check if a field type should use a nested resolver.

    This now checks the resolve_nested flag. By default (False),
    we assume data is embedded and don't create a separate resolver.

    Args:
        field_type: The type to check

    Returns:
        True only if the type explicitly requests nested resolution
    """
    import types
    from typing import Union, get_origin

    # Extract actual type from Optional if needed
    actual_type = field_type
    origin = get_origin(field_type)
    if origin is Union or origin is types.UnionType:
        args = get_args(field_type)
        non_none_types = [t for t in args if t is not type(None)]
        if non_none_types:
            actual_type = non_none_types[0]

    # Check if it's a type with sql_source AND resolve_nested=True
    if hasattr(actual_type, "__fraiseql_definition__"):
        definition = actual_type.__fraiseql_definition__
        # Only use nested resolver if explicitly requested
        return getattr(definition, "resolve_nested", False)

    return False


def create_nested_array_field_resolver_with_where(
    field_name: str, field_type: type, field_metadata: Any = None
) -> Callable:
    """Create a field resolver for nested arrays with comprehensive logical operator filtering.

    This resolver provides complete AND/OR/NOT logical operator support for filtering
    nested array elements. It handles:

    1. Complete logical operators (AND/OR/NOT with unlimited nesting depth)
    2. All standard field operators (equals, contains, gte, isnull, etc.)
    3. Embedded data filtering (when data is already present in parent)
    4. Database-level filtering (for sql_source queries)
    5. Automatic WhereInput type generation and application
    6. Client-side filtering with efficient evaluation

    Logical Operators Supported:
    - AND: All conditions must be true (implicit for multiple fields)
    - OR: Any condition can be true
    - NOT: Inverts condition result
    - Complex nesting: Unlimited depth combinations

    Field Operators Supported:
    - String: equals, not, contains, startsWith, endsWith, in, notIn, isnull
    - Numeric: equals, not, gt, gte, lt, lte, in, notIn, isnull
    - Boolean: equals, not, isnull

    Example GraphQL Query:
        printServers(where: {
          AND: [
            { operatingSystem: { in: ["Linux", "Windows"] } }
            { OR: [
                { nTotalAllocations: { gte: 100 } }
                { hostname: { contains: "critical" } }
              ]
            }
            { NOT: { ipAddress: { isnull: true } } }
          ]
        })

    Args:
        field_name: The name of the field being resolved
        field_type: The type of the field (typically list[SomeType])
        field_metadata: FraiseQLField metadata with where configuration

    Returns:
        An async resolver function that handles comprehensive where parameter filtering
        with complete logical operator support
    """

    async def resolve_nested_array_with_where(
        parent: Any, info: GraphQLResolveInfo, where: Any = None, **kwargs: Any
    ) -> Any:
        """Resolve nested array field with optional where filtering."""
        # First, get the raw data using existing logic
        value = getattr(parent, field_name, None)

        if value is None:
            # Try to resolve using the standard nested resolver first
            standard_resolver = create_smart_nested_field_resolver(field_name, field_type)
            value = await standard_resolver(parent, info, **kwargs)

        # If we still don't have data, return None or empty list
        if value is None:
            # Check if this is a list type - return empty list
            origin = get_origin(field_type)
            if origin is list:
                return []
            return None

        # If no where filtering requested, return the data as-is
        if where is None:
            return value

        # Apply where filtering to the data
        if isinstance(value, list):
            return await _apply_where_filter_to_array(value, where, field_type)
        # Single item filtering
        if await _item_matches_where_criteria(value, where):
            return value
        return None

    return resolve_nested_array_with_where


async def _apply_where_filter_to_array(items: list, where_filter: Any, field_type: Any) -> list:
    """Apply where filtering to an array of items."""
    if not items or not where_filter:
        return items

    filtered_items = []
    for item in items:
        if await _item_matches_where_criteria(item, where_filter):
            filtered_items.append(item)

    return filtered_items


def _item_value(item: Any, field_name: str) -> Any:
    """The value of an element's field: an attribute, or a key of a dict element.

    ``field_name`` is the Python name or the GraphQL (camelCase) name.
    """
    snake = to_snake_case(field_name)
    if isinstance(item, Mapping):
        return item[snake] if snake in item else item.get(field_name)
    value = getattr(item, snake, None)
    return getattr(item, field_name, None) if value is None and snake != field_name else value


async def _item_matches_where_dict(item: Any, where: Mapping[str, Any]) -> bool:
    """Whether an element matches a ``where`` as graphql-core passes it: a dict."""
    for key, condition in where.items():
        if condition is None:
            continue
        if key == "AND":
            for sub in condition:
                if not await _item_matches_where_criteria(item, sub):
                    return False
        elif key == "OR":
            if not condition:
                return False
            matched = False
            for sub in condition:
                if await _item_matches_where_criteria(item, sub):
                    matched = True
                    break
            if not matched:
                return False
        elif key == "NOT":
            if await _item_matches_where_criteria(item, condition):
                return False
        elif not _apply_field_filter_operators(_item_value(item, key), condition):
            return False
    return True


async def _item_matches_where_criteria(item: Any, where_filter: Any) -> bool:
    """Check if an item matches the where filter criteria."""
    if not where_filter:
        return True

    # graphql-core passes an input object argument as a dict (GraphQL names)
    if isinstance(where_filter, Mapping):
        return await _item_matches_where_dict(item, where_filter)

    # Convert where filter to SQL where type if it has the conversion method
    if hasattr(where_filter, "_to_sql_where"):
        sql_where = where_filter._to_sql_where()
        return await _evaluate_sql_where_on_item(item, sql_where)

    # Check if this has logical operators and process them exclusively
    if hasattr(where_filter, "__dict__"):
        filter_dict = where_filter.__dict__

        # Handle AND operator
        if "AND" in filter_dict and filter_dict["AND"] is not None:
            and_conditions = filter_dict["AND"]
            if isinstance(and_conditions, list):
                if not and_conditions:  # Empty AND array = all match
                    return True
                logger.debug(
                    f"Processing AND conditions for item: {getattr(item, 'hostname', 'unknown')}"
                )
                for i, condition in enumerate(and_conditions):
                    result = await _item_matches_where_criteria(item, condition)
                    logger.debug(f"  AND condition {i}: {result}")
                    if not result:
                        logger.debug(f"  AND failed on condition {i}")
                        return False
                logger.debug("  All AND conditions passed")
                return True

        # Handle OR operator
        if "OR" in filter_dict and filter_dict["OR"] is not None:
            or_conditions = filter_dict["OR"]
            if isinstance(or_conditions, list):
                if not or_conditions:  # Empty OR array = none match
                    return False
                for condition in or_conditions:
                    if await _item_matches_where_criteria(item, condition):
                        return True
                return False

        # Handle NOT operator
        if "NOT" in filter_dict and filter_dict["NOT"] is not None:
            not_condition = filter_dict["NOT"]
            return not await _item_matches_where_criteria(item, not_condition)

    # Handle direct field filtering
    if hasattr(where_filter, "__gql_fields__"):
        for field_name in where_filter.__gql_fields__:
            # Skip logical operators in field iteration
            if field_name in ("AND", "OR", "NOT"):
                continue

            field_filter = getattr(where_filter, field_name, None)
            if field_filter is None:
                continue

            item_value = _item_value(item, field_name)
            if not _apply_field_filter_operators(item_value, field_filter):
                return False
        return True

    # Fallback - try to use the filter as a dict
    if hasattr(where_filter, "__dict__"):
        for field_name, field_filter in where_filter.__dict__.items():
            # Skip logical operators in dict iteration
            if field_name in ("AND", "OR", "NOT") or field_filter is None:
                continue

            item_value = _item_value(item, field_name)
            if not _apply_field_filter_operators(item_value, field_filter):
                return False
        return True

    return True


async def _evaluate_sql_where_on_item(item: Any, sql_where: Any) -> bool:
    """Evaluate SQL where conditions on a Python object."""
    if not sql_where or not hasattr(sql_where, "__dict__"):
        return True

    # Handle logical operators first
    where_dict = sql_where.__dict__

    # Handle AND operator
    if "AND" in where_dict and where_dict["AND"] is not None:
        and_conditions = where_dict["AND"]
        if isinstance(and_conditions, list):
            if not and_conditions:  # Empty AND array = all match
                return True
            for condition in and_conditions:
                if not await _evaluate_sql_where_on_item(item, condition):
                    return False
            return True

    # Handle OR operator
    if "OR" in where_dict and where_dict["OR"] is not None:
        or_conditions = where_dict["OR"]
        if isinstance(or_conditions, list):
            if not or_conditions:  # Empty OR array = none match
                return False
            for condition in or_conditions:
                if await _evaluate_sql_where_on_item(item, condition):
                    return True
            return False

    # Handle NOT operator
    if "NOT" in where_dict and where_dict["NOT"] is not None:
        not_condition = where_dict["NOT"]
        return not await _evaluate_sql_where_on_item(item, not_condition)

    # Handle field conditions (implicit AND for multiple fields)
    for field_name, field_conditions in where_dict.items():
        # Skip logical operators in field iteration
        if field_name in ("AND", "OR", "NOT") or field_conditions is None:
            continue

        item_value = _item_value(item, field_name)
        if not _apply_field_filter_operators(item_value, field_conditions):
            return False

    return True


def _apply_field_filter_operators(item_value: Any, filter_conditions: Any) -> bool:
    """Apply filter operators to a field value."""
    if not filter_conditions:
        return True

    # Handle dict-based filter conditions
    if isinstance(filter_conditions, Mapping):
        for operator, filter_value in filter_conditions.items():
            if filter_value is None:
                continue  # an operator the query sets to null filters nothing
            if not _apply_single_operator(item_value, operator, filter_value):
                return False
        return True

    # Handle object-based filter conditions
    if hasattr(filter_conditions, "__dict__"):
        for operator, filter_value in filter_conditions.__dict__.items():
            if filter_value is None:
                continue
            if not _apply_single_operator(item_value, operator, filter_value):
                return False
        return True

    return True


def _apply_single_operator(item_value: Any, operator: str, filter_value: Any) -> bool:
    """Apply a single filter operator to a value."""
    # An enum field's filter takes the enum's values (a StringFilter)
    if isinstance(item_value, Enum) and not isinstance(filter_value, Enum):
        item_value = item_value.value
    # Handle both GraphQL standard names and internal names
    if operator in ("eq", "equals"):
        return item_value == filter_value
    if operator in ("neq", "not"):
        return item_value != filter_value
    if operator == "gt":
        return item_value is not None and item_value > filter_value
    if operator == "gte":
        return item_value is not None and item_value >= filter_value
    if operator == "lt":
        return item_value is not None and item_value < filter_value
    if operator == "lte":
        return item_value is not None and item_value <= filter_value
    if operator == "contains":
        return item_value is not None and str(filter_value) in str(item_value)
    if operator in ("startswith", "startsWith"):
        return item_value is not None and str(item_value).startswith(str(filter_value))
    if operator in ("endswith", "endsWith"):
        return item_value is not None and str(item_value).endswith(str(filter_value))
    if operator in {"in", "in_"}:
        return item_value in filter_value if filter_value else False
    if operator in ("nin", "notIn"):
        return item_value not in filter_value if filter_value else True
    if operator == "isnull":
        if filter_value:
            return item_value is None
        return item_value is not None
    # Matching every element would ignore the filter without a word
    supported = ", ".join(sorted(_OPERATORS))
    msg = (
        f"Operator {operator!r} is not supported in a nested array where "
        f"(it is filtered in Python); supported operators: {supported}"
    )
    raise ValueError(msg)


_OPERATORS = frozenset(
    {
        "eq",
        "equals",
        "neq",
        "not",
        "gt",
        "gte",
        "lt",
        "lte",
        "contains",
        "startswith",
        "startsWith",
        "endswith",
        "endsWith",
        "in",
        "in_",
        "nin",
        "notIn",
        "isnull",
    }
)

"""SQL generator for building SELECT queries with GraphQL-aware JSONB projection.

Supports JSONB path extraction and camelCase aliasing for GraphQL field names.
Integrates deeply with FraiseQL's AST selection and schema mappings to construct
optimized PostgreSQL queries using `jsonb_build_object` for minimal post-processing.
"""

from collections.abc import Sequence
from typing import Any

from psycopg import sql
from psycopg.sql import SQL, Composed, Identifier

from fraiseql.core.ast_parser import FieldPath
from fraiseql.sql.identifiers import qualified_identifier


def _get_graphql_field_type(typename: str | None, field_alias: str) -> type | None:
    """Get the actual Python type for a GraphQL field from the registered schema.

    Args:
        typename: The GraphQL type name (e.g., "User", "Order")
        field_alias: The field alias from the GraphQL query

    Returns:
        The Python type (str, int, float, bool) or None if not found
    """
    if not typename:
        return None

    try:
        from fraiseql.core.registry import get_registry

        registry = get_registry()
        registered_types = registry.get_types()

        if typename not in registered_types:
            return None

        type_def = registered_types[typename]

        # Access the __gql_fields__ to get field type information
        if hasattr(type_def, "__gql_fields__"):
            gql_fields = type_def.__gql_fields__

            # Look up by field alias (GraphQL field name)
            if field_alias in gql_fields:
                field = gql_fields[field_alias]
                return field.field_type

            # Also try snake_case version of the alias
            from fraiseql.utils.casing import to_snake_case

            snake_case_alias = to_snake_case(field_alias)
            if snake_case_alias in gql_fields:
                field = gql_fields[snake_case_alias]
                return field.field_type

    except (ImportError, AttributeError, KeyError):
        # Gracefully handle any issues with schema lookup
        pass

    return None


def _determine_jsonb_operator(alias: str, field_name: str, typename: str | None = None) -> str:
    """Determine the correct JSONB operator (-> or ->>) based on actual GraphQL field types.

    This function implements type-aware operator selection to fix the JSONB numeric
    coercion bug while maintaining compatibility with string fields.

    Args:
        alias: The GraphQL field alias
        field_name: The database field name
        typename: The GraphQL type name to look up field types

    Returns:
        The appropriate JSONB operator:
        - "->" for fields that should preserve types (numeric, boolean)
        - "->>" for fields that should be extracted as text (strings, UUIDs, etc.)
    """
    # First, try to get the actual type from the GraphQL schema
    field_type = _get_graphql_field_type(typename, alias)

    if field_type is not None:
        # Use actual type information from schema
        if field_type in (int, float, bool):
            return "->"  # Preserve numeric/boolean types
        if field_type is str:
            return "->>"  # Extract strings as text
        if hasattr(field_type, "__origin__"):
            # Handle generic types like list[str], Optional[int], etc.
            origin = getattr(field_type, "__origin__", None)
            args = getattr(field_type, "__args__", ())

            if origin is list and args:
                # For lists, we typically want to preserve the structure
                return "->"
            if (
                origin is type(None)
                or (
                    hasattr(__builtins__, "UnionType")
                    and isinstance(field_type, type(__builtins__.UnionType))
                )
            ) and args:
                # Get the non-None type
                non_none_type = next((arg for arg in args if arg is not type(None)), None)
                if non_none_type in (int, float, bool):
                    return "->"
                return "->>"

    # Fallback to heuristic-based type detection for common field patterns

    # Boolean field patterns - use -> for type preservation
    # Include both snake_case and camelCase variants
    boolean_patterns = {
        # Base boolean terms
        "active",
        "enabled",
        "disabled",
        "visible",
        "hidden",
        "public",
        "private",
        "verified",
        "confirmed",
        "approved",
        "published",
        "deleted",
        "archived",
        "locked",
        "banned",
        "blocked",
        "featured",
        "pinned",
        "starred",
        "favorite",
        "required",
        "optional",
        "mandatory",
        "valid",
        "invalid",
        "available",
        # snake_case variants
        "use_tls",
        "use_ssl",
        "is_active",
        "is_enabled",
        "is_deleted",
        "is_admin",
        "has_children",
        "can_edit",
        "can_delete",
        "can_view",
        "allow_comments",
        # camelCase variants
        "isActive",
        "isEnabled",
        "isDisabled",
        "isVisible",
        "isHidden",
        "isPublic",
        "isPrivate",
        "isVerified",
        "isConfirmed",
        "isApproved",
        "isPublished",
        "isDeleted",
        "isArchived",
        "isLocked",
        "isBanned",
        "isBlocked",
        "isFeatured",
        "isPinned",
        "isStarred",
        "isFavorite",
        "isRequired",
        "isOptional",
        "isMandatory",
        "isValid",
        "isInvalid",
        "isAvailable",
        "isAdmin",
        "useTls",
        "useSsl",
        "hasChildren",
        "canEdit",
        "canDelete",
        "canView",
        "allowComments",
    }

    # Numeric field patterns - use -> for type preservation
    numeric_patterns = {
        "count",
        "total",
        "sum",
        "amount",
        "price",
        "cost",
        "value",
        "rate",
        "score",
        "rating",
        "level",
        "rank",
        "position",
        "index",
        "order",
        "priority",
        "weight",
        "size",
        "length",
        "width",
        "height",
        "depth",
        "quantity",
        "stock",
        "inventory",
        "capacity",
        "limit",
        "max",
        "min",
        "port",
        "timeout",
        "retry",
        "interval",
        "duration",
        "delay",
        "percentage",
        "ratio",
        "factor",
        "multiplier",
        "version",
        "revision",
        "age",
        "year",
        "month",
        "day",
        "hour",
        "minute",
        "second",  # Time/age related
        "n_total_allocations",
        "unit_price",
        "quantity_ordered",
        "total_amount",
    }

    # Check field name patterns (case-insensitive)
    field_lower = field_name.lower()
    alias_lower = alias.lower()

    # Check exact matches first (both original case and lowercase)
    if (
        field_name in boolean_patterns
        or alias in boolean_patterns
        or field_lower in boolean_patterns
        or alias_lower in boolean_patterns
    ):
        return "->"

    if (
        field_name in numeric_patterns
        or alias in numeric_patterns
        or field_lower in numeric_patterns
        or alias_lower in numeric_patterns
    ):
        return "->"

    # Check field name suffixes for pattern matching
    numeric_suffixes = (
        "_count",
        "_total",
        "_sum",
        "_amount",
        "_price",
        "_cost",
        "_rate",
        "_score",
        "_level",
        "_rank",
        "_size",
        "_quantity",
        "_port",
        "_timeout",
        "_version",
        "_id_numeric",
    )

    boolean_suffixes = (
        "_active",
        "_enabled",
        "_disabled",
        "_visible",
        "_hidden",
        "_verified",
        "_confirmed",
        "_approved",
        "_deleted",
        "_archived",
        "_required",
        "_valid",
        "_available",
        "_allowed",
    )

    # Exception patterns - fields that contain numeric words but are actually strings
    string_exception_patterns = {
        "phone_number",
        "phonenumber",
        "telephone_number",
        "mobile_number",
        "fax_number",
        "account_number",
        "reference_number",
        "tracking_number",
        "order_number",
        "invoice_number",
        "serial_number",
        "part_number",
        "model_number",
        "sku_number",
        "registration_number",
        "license_number",
    }

    # Check for string exceptions first (these override numeric patterns)
    if field_lower in string_exception_patterns or alias_lower in string_exception_patterns:
        return "->>"

    if any(field_lower.endswith(suffix) for suffix in numeric_suffixes):
        return "->"

    if any(field_lower.endswith(suffix) for suffix in boolean_suffixes):
        return "->"

    # String/ID field patterns - use ->> for text extraction
    # These are fields that should always be strings in JSON
    string_patterns = {
        "id",
        "uuid",
        "identifier",
        "name",
        "title",
        "description",
        "summary",
        "email",
        "phone",
        "address",
        "street",
        "city",
        "state",
        "country",
        "postal_code",
        "zip_code",
        "url",
        "slug",
        "path",
        "filename",
        "extension",
        "mime_type",
        "hash",
        "token",
        "key",
        "secret",
        "username",
        "password",
        "first_name",
        "last_name",
        "full_name",
        "display_name",
        "nick_name",
        "status",
        "type",
        "category",
        "tag",
        "created_at",
        "updated_at",
        "deleted_at",
        "published_at",
        "user_id",
        "customer_id",
        "order_id",
        "contract_id",
        "item_id",
        "pk_entity",
        "pk_organization",
        "pk_user",
        "pk_contract",
    }

    # Check for string patterns
    if field_lower in string_patterns or alias_lower in string_patterns:
        return "->>"

    # Check string suffixes
    string_suffixes = (
        "_id",
        "_uuid",
        "_name",
        "_title",
        "_description",
        "_email",
        "_phone",
        "_address",
        "_url",
        "_path",
        "_filename",
        "_hash",
        "_token",
        "_key",
        "_username",
        "_status",
        "_type",
        "_category",
        "_at",
        "_date",
        "_time",
        "_timestamp",
    )

    if any(field_lower.endswith(suffix) for suffix in string_suffixes):
        return "->>"

    # Default fallback: Use ->> for unknown fields to maintain backward compatibility
    # This ensures existing string fields continue to work as expected
    # NOTE: Schema integration is now implemented above for registered types
    return "->>"


def _convert_order_by_to_tuples(order_by: Any) -> list[tuple[str, str]] | None:
    """Convert any OrderBy format to list of tuples.

    Args:
        order_by: OrderBy in any format (GraphQL dicts, tuples, OrderBySet)

    Returns:
        List of (field, direction) tuples or None
    """
    if not order_by:
        return None

    # Already a list of tuples
    if isinstance(order_by, list) and order_by and isinstance(order_by[0], tuple):
        return order_by

    # GraphQL format - convert using FraiseQL
    if isinstance(order_by, (list, dict)):
        try:
            from fraiseql.sql.graphql_order_by_generator import _convert_order_by_input_to_sql

            order_by_set = _convert_order_by_input_to_sql(order_by)
            if order_by_set:
                return [
                    (
                        instr.field,
                        instr.direction.value
                        if hasattr(instr.direction, "value")
                        else str(instr.direction),
                    )
                    for instr in order_by_set.instructions
                ]
        except (ImportError, AttributeError):
            pass

    # OrderBySet object
    if hasattr(order_by, "instructions"):
        return [
            (
                instr.field,
                instr.direction.value
                if hasattr(instr.direction, "value")
                else str(instr.direction),
            )
            for instr in order_by.instructions
        ]

    return None


def build_sql_query(
    table: str,
    field_paths: Sequence[FieldPath],
    where_clause: SQL | None = None,
    *,
    json_output: bool = False,
    typename: str | None = None,
    order_by: Sequence[tuple[str, str]] | None = None,
    group_by: Sequence[str] | None = None,
    auto_camel_case: bool = False,
    raw_json_output: bool = False,
    field_limit_threshold: int | None = None,
) -> Composed:
    """Build a SELECT SQL query using jsonb path extraction and optional WHERE/ORDER BY/GROUP BY.

    If `json_output` is True, wraps the result in jsonb_build_object(...)
    and aliases it as `result`. Adds '__typename' if `typename` is provided.

    v0.11.0: All camelCase transformation is handled by Rust after retrieval.
    PostgreSQL CamelForge function dependency has been removed for architectural simplicity.

    Args:
        table: Table name to query
        field_paths: Sequence of field paths to extract
        where_clause: Optional WHERE clause
        json_output: Whether to wrap output in jsonb_build_object
        typename: Optional GraphQL typename to include
        order_by: Optional list of (field_path, direction) tuples for ORDER BY
        group_by: Optional list of field paths for GROUP BY
        auto_camel_case: Whether to preserve camelCase field paths (True) or convert to snake_case
        raw_json_output: Whether to cast output to text for raw JSON passthrough
        field_limit_threshold: If set and field count exceeds this, return full data column
    """
    # Check if we should use full data column to avoid parameter limit
    if field_limit_threshold is not None and len(field_paths) > field_limit_threshold:
        # Simply select the full data column
        if raw_json_output:
            select_clause = SQL("data::text AS result")
        elif json_output:
            select_clause = SQL("data AS result")
        else:
            select_clause = SQL("data")

        base = SQL("SELECT {} FROM {}").format(select_clause, qualified_identifier(table))

        # Build query with clauses in correct SQL order
        query_parts = [base]

        if where_clause:
            query_parts.append(SQL(" WHERE "))
            query_parts.append(where_clause)

        # Note: GROUP BY and ORDER BY are skipped when using full data column
        # This is a current limitation that could be addressed in future versions

        return sql.SQL("").join(query_parts)

    # Original implementation for when threshold is not exceeded
    object_pairs: list[sql.Composable] = []

    for field in field_paths:
        json_path_parts = [sql.Literal(part) for part in field.path[:-1]]
        last_part = field.path[-1]

        expr = sql.SQL("data")
        for key in json_path_parts:
            expr = sql.SQL("{}->{}").format(expr, key)

        # CRITICAL FIX: Type-aware operator selection for JSONB field extraction
        # - Use -> operator for JSON-native types that need type preservation (int, float, bool)
        # - Use ->> operator for string fields and PostgreSQL-specific types
        #
        # This fixes the v0.4.1 numeric coercion bug while maintaining string field compatibility
        operator = _determine_jsonb_operator(field.alias, last_part, typename)
        expr = sql.SQL("{}{}{}").format(expr, sql.SQL(operator), sql.Literal(last_part))
        object_pairs.append(sql.Literal(field.alias))
        object_pairs.append(expr)

    if typename is not None:
        object_pairs.append(sql.Literal("__typename"))
        object_pairs.append(sql.Literal(typename))

    if json_output:
        # Build the jsonb_build_object expression
        # v0.11.0: Rust handles all camelCase transformation after retrieval
        jsonb_expr = SQL("jsonb_build_object({})").format(SQL(", ").join(object_pairs))

        if raw_json_output:
            select_clause = SQL("{}::text AS result").format(jsonb_expr)
        else:
            select_clause = SQL("{} AS result").format(jsonb_expr)
    else:
        select_items = [
            SQL("{} AS {}{}").format(expr, Identifier(field.alias), SQL(""))
            for field, expr in zip(field_paths, object_pairs[1::2], strict=False)
        ]
        select_clause = SQL(", ").join(select_items)

    base = SQL("SELECT {} FROM {}").format(select_clause, qualified_identifier(table))

    # Build query with clauses in correct SQL order
    query_parts = [base]

    if where_clause:
        query_parts.append(SQL(" WHERE "))
        query_parts.append(where_clause)

    if group_by:
        group_by_parts = []
        for field_path in group_by:
            # Convert field path (e.g., "profile.age") to JSONB expression
            path_parts = field_path.split(".")

            # Apply snake_case transformation if auto_camel_case is disabled
            if not auto_camel_case:
                from fraiseql.utils.casing import to_snake_case

                path_parts = [to_snake_case(part) for part in path_parts]

            if len(path_parts) == 1:
                # Top-level field
                expr = SQL("data->>{}").format(sql.Literal(path_parts[0]))
            else:
                # Nested field
                json_path = [sql.Literal(part) for part in path_parts[:-1]]
                expr = SQL("data")
                for part in json_path:
                    expr = SQL("{}->{}").format(expr, part)
                expr = SQL("{}->>{}").format(expr, sql.Literal(path_parts[-1]))
            group_by_parts.append(expr)

        query_parts.append(SQL(" GROUP BY "))
        query_parts.append(SQL(", ").join(group_by_parts))

    if order_by:
        order_by_parts = []
        # Safety net: convert OrderBy to tuples if needed
        order_by_tuples = _convert_order_by_to_tuples(order_by)
        if not order_by_tuples:
            # If conversion failed, assume it's already in correct format
            order_by_tuples = order_by

        for field_path, direction in order_by_tuples:
            # Convert field path to JSONB expression
            path_parts = field_path.split(".")

            # Apply snake_case transformation if auto_camel_case is disabled
            if not auto_camel_case:
                from fraiseql.utils.casing import to_snake_case

                path_parts = [to_snake_case(part) for part in path_parts]

            if len(path_parts) == 1:
                # Top-level field
                expr = SQL("data->>{}").format(sql.Literal(path_parts[0]))
            else:
                # Nested field
                json_path = [sql.Literal(part) for part in path_parts[:-1]]
                expr = SQL("data")
                for part in json_path:
                    expr = SQL("{}->{}").format(expr, part)
                expr = SQL("{}->>{}").format(expr, sql.Literal(path_parts[-1]))

            # Add direction (ASC/DESC) - handle both strings and OrderDirection enums
            if hasattr(direction, "value"):
                direction_str = direction.value.upper()
            else:
                direction_str = str(direction).upper()
            order_expr = expr + SQL(" ") + SQL(direction_str)
            order_by_parts.append(order_expr)

        query_parts.append(SQL(" ORDER BY "))
        query_parts.append(SQL(", ").join(order_by_parts))

    return sql.Composed(query_parts)

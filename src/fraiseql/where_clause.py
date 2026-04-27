"""Canonical representation for WHERE clauses.

This module defines the internal representation used by FraiseQL for all WHERE
clause processing, regardless of input format (dict or WhereInput).

Architecture:
    User Input (dict/WhereInput)
        → Normalize to WhereClause
        → Generate SQL
        → PostgreSQL

Known Limitations:
    JSON/Dict-valued scalar types (e.g., JSONScalar) cannot use standard WHERE
    operators (eq, ne, in, etc.) because the parser interprets dict keys as
    filter operators. For example:

        # This fails:
        where: {jsonField: {eq: {"key": "value"}}}

        # Parser sees "key" and thinks it's an operator like "eq", "contains"
        # Error: "Invalid operator 'key'"

    For JSON filtering, use specialized JSONB operators (contains, path, etc.)
    or filter on specific JSON paths rather than the whole object.

    Atomic-value custom scalars (strings, numbers) work correctly:
        where: {emailField: {eq: "user@test.com"}}  # ✅ Works
        where: {cidrField: {eq: "192.168.1.0/24"}}  # ✅ Works
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from psycopg.sql import SQL, Composed, Identifier
from psycopg.sql import Literal as SQLLiteral

from fraiseql.sql.operators import get_default_registry

# Supported operators
COMPARISON_OPERATORS = {
    "eq": "=",
    "neq": "!=",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
}

CONTAINMENT_OPERATORS = {
    "in": "IN",
    "nin": "NOT IN",
}

STRING_OPERATORS = {
    "contains": "LIKE",
    "icontains": "ILIKE",
    "startswith": "LIKE",
    "istartswith": "ILIKE",
    "endswith": "LIKE",
    "iendswith": "ILIKE",
    "like": "LIKE",  # NEW: explicit LIKE
    "ilike": "ILIKE",  # NEW: explicit ILIKE
}

NULL_OPERATORS = {
    "isnull": "IS NULL",
}

VECTOR_OPERATORS = {
    "cosine_distance": "<=>",
    "l2_distance": "<->",
    "l1_distance": "<+>",
    "hamming_distance": "<~>",
    "jaccard_distance": "<%>",
}

# Binary vector operators (use bit type, not vector type)
BINARY_VECTOR_OPERATORS = {"hamming_distance", "jaccard_distance"}

FULLTEXT_OPERATORS = {
    "matches": "@@",
    "plain_query": "@@",
    "phrase_query": "@@",
    "websearch_query": "@@",
    "rank_gt": ">",
    "rank_lt": "<",
    "rank_cd_gt": ">",
    "rank_cd_lt": "<",
}

ARRAY_OPERATORS = {
    "array_eq": "=",
    "array_neq": "!=",
    "array_contains": "@>",
    "contains": "@>",  # Alias for array_contains (for arrays, not strings)
    "array_contained_by": "<@",
    "contained_by": "<@",  # Alias for array_contained_by
    "array_overlaps": "&&",
    "overlaps": "&&",  # Alias for array_overlaps
    "array_length_eq": "=",
    "len_eq": "=",  # Alias for array_length_eq
    "array_length_gt": ">",
    "len_gt": ">",  # Alias for array_length_gt
    "array_length_lt": "<",
    "len_lt": "<",  # Alias for array_length_lt
    "array_length_gte": ">=",
    "len_gte": ">=",  # Alias for array_length_gte
    "array_any_eq": "= ANY",
    "any_eq": "= ANY",  # Alias for array_any_eq
    "array_all_eq": "= ALL",
    "all_eq": "= ALL",  # Alias for array_all_eq
}

# Exclude 'contains' from ALL_OPERATORS since it's ambiguous (string LIKE vs array @>)
# It's handled specially based on value type
_ARRAY_OPERATORS_FOR_ALL = {k: v for k, v in ARRAY_OPERATORS.items() if k != "contains"}

# Network operators for INET/CIDR types
# NOTE: These template strings are for documentation/validation only.
# Actual SQL generation is delegated to NetworkOperatorStrategy via operator registry.
NETWORK_OPERATORS = {
    "isIPv4": "family({}) = 4",
    "isIPv6": "family({}) = 6",
    "isPrivate": "CIDR_RANGE_CHECK",  # Uses CIDR containment checks, not inet_public()
    "isPublic": "NOT_CIDR_RANGE_CHECK",  # Uses NOT (CIDR containment checks)
    "inSubnet": "{} <<= {}",
    "inRange": "{} <<= {}",
    "overlaps": "{} && {}",
    "strictleft": "{} << {}",
    "strictright": "{} >> {}",
    # CamelCase aliases for compatibility
    "isprivate": "CIDR_RANGE_CHECK",  # Uses CIDR containment checks, not inet_public()
    "ispublic": "NOT_CIDR_RANGE_CHECK",  # Uses NOT (CIDR containment checks)
    "insubnet": "{} <<= {}",
    "inrange": "{} <<= {}",
    "isipv4": "family({}) = 4",
    "isipv6": "family({}) = 6",
}

# MAC Address operators
MACADDR_OPERATORS = {
    "notin": "NOT IN",  # Handled by MacAddressOperatorStrategy
}

# DateRange operators
DATERANGE_OPERATORS = {
    "contains_date": "@>",
    "adjacent": "-|-",
    "strictly_left": "<<",
    "strictly_right": ">>",
    "not_left": "&>",
    "not_right": "&<",
    "notin": "NOT IN",  # Note: 'notin' appears in multiple strategies
}

# LTree (hierarchical path) operators
LTREE_OPERATORS = {
    "ancestor_of": "@>",
    "descendant_of": "<@",
    "descendant_of_id": "<@",  # descendant_of with UUID resolution
    "ancestor_of_id": "@>",  # ancestor_of with UUID resolution
    "matches_lquery": "~",
    "matches_ltxtquery": "@",
    "matches_any_lquery": "?",
    "in_array": "<@",
    "concat": "||",
    "lca": "lca",
    "nlevel": "nlevel({})",
    "nlevel_eq": "nlevel({}) =",
    "nlevel_gt": "nlevel({}) >",
    "nlevel_gte": "nlevel({}) >=",
    "nlevel_lt": "nlevel({}) <",
    "nlevel_lte": "nlevel({}) <=",
    "nlevel_neq": "nlevel({}) !=",
    # Depth aliases for nlevel
    "depth_eq": "nlevel({}) =",
    "depth_gt": "nlevel({}) >",
    "depth_gte": "nlevel({}) >=",
    "depth_lt": "nlevel({}) <",
    "depth_lte": "nlevel({}) <=",
    "depth_neq": "nlevel({}) !=",
    "subpath": "subpath",
    "index": "index",
    "index_eq": "index =",
    "index_gte": "index >=",
    "notin": "NOT IN",
}

# JSONB operators
JSONB_OPERATORS = {
    "strictly_contains": "@>",  # Strictly contains (not just overlaps)
}

# Coordinate/spatial operators
COORDINATE_OPERATORS = {
    "distance_within": "distance_within",
    "notin": "NOT IN",
}

# Pattern matching operators
PATTERN_OPERATORS = {
    "imatches": "~*",  # Case-insensitive regex match
    "not_matches": "!~",  # Negated regex match
}

# Additional array operators (missing from ARRAY_OPERATORS)
ARRAY_OPERATORS_EXTRA = {
    "len_lte": "<=",
    "len_neq": "!=",
}

# Path operators (for hierarchical paths)
PATH_OPERATORS = {
    "depth_eq": "depth =",
    "depth_gt": "depth >",
    "depth_lt": "depth <",
    "isdescendant": "isdescendant",
}

# List operators (fallback)
LIST_OPERATORS = {
    "notin": "NOT IN",
}

ALL_OPERATORS = {
    **COMPARISON_OPERATORS,
    **CONTAINMENT_OPERATORS,
    **STRING_OPERATORS,  # contains -> LIKE
    **NULL_OPERATORS,
    **VECTOR_OPERATORS,
    **FULLTEXT_OPERATORS,
    **_ARRAY_OPERATORS_FOR_ALL,  # All array operators except 'contains'
    **NETWORK_OPERATORS,  # Network operators for INET/CIDR types
    **MACADDR_OPERATORS,  # MAC address operators
    **DATERANGE_OPERATORS,  # Date range operators
    **LTREE_OPERATORS,  # LTree hierarchical path operators
    **JSONB_OPERATORS,  # JSONB operators
    **COORDINATE_OPERATORS,  # Coordinate/spatial operators
    **PATTERN_OPERATORS,  # Pattern matching operators
    **ARRAY_OPERATORS_EXTRA,  # Additional array operators
    **PATH_OPERATORS,  # Path operators
    **LIST_OPERATORS,  # List operators (fallback)
}


@dataclass
class FieldCondition:
    """Single filter condition on a field.

    Represents a single comparison like: machine_id = '123' or data->'device'->>'name' = 'Printer'

    Attributes:
        field_path: Path to the field, e.g., ["machine", "id"] for nested filter
        operator: Filter operator like "eq", "neq", "in", "contains"
        value: The value to compare against
        lookup_strategy: How to access this field in SQL
            - "fk_column": Use FK column (e.g., machine_id)
            - "jsonb_path": Use JSONB path (e.g., data->'machine'->>'id')
            - "sql_column": Use direct column (e.g., status)
        target_column: The actual SQL column name
            - For FK: "machine_id"
            - For JSONB: "data" (with jsonb_path set)
            - For SQL: "status"
        jsonb_path: For JSONB lookups, the path within the data column
            - e.g., ["machine", "id"] → data->'machine'->>'id'

    Examples:
        # FK lookup: machine.id = '123'
        FieldCondition(
            field_path=["machine", "id"],
            operator="eq",
            value=UUID("123"),
            lookup_strategy="fk_column",
            target_column="machine_id",
            jsonb_path=None
        )

        # JSONB lookup: device.name = 'Printer'
        FieldCondition(
            field_path=["device", "name"],
            operator="eq",
            value="Printer",
            lookup_strategy="jsonb_path",
            target_column="data",
            jsonb_path=["device", "name"]
        )

        # Direct column: status = 'active'
        FieldCondition(
            field_path=["status"],
            operator="eq",
            value="active",
            lookup_strategy="sql_column",
            target_column="status",
            jsonb_path=None
        )
    """

    field_path: list[str]
    operator: str
    value: Any
    lookup_strategy: Literal["fk_column", "jsonb_path", "sql_column"]
    target_column: str
    jsonb_path: list[str] | None = None

    def __post_init__(self):
        """Validate the condition after initialization."""
        # Validate operator
        if self.operator not in ALL_OPERATORS:
            raise ValueError(
                f"Invalid operator '{self.operator}'. "
                f"Supported operators: {', '.join(sorted(ALL_OPERATORS.keys()))}"
            )

        # Validate lookup_strategy
        valid_strategies = {"fk_column", "jsonb_path", "sql_column"}
        if self.lookup_strategy not in valid_strategies:
            raise ValueError(
                f"Invalid lookup_strategy '{self.lookup_strategy}'. "
                f"Must be one of: {', '.join(sorted(valid_strategies))}"
            )

        # Validate JSONB path consistency
        if self.lookup_strategy == "jsonb_path" and not self.jsonb_path:
            raise ValueError("lookup_strategy='jsonb_path' requires jsonb_path to be set")

        # Validate field_path
        if not self.field_path:
            raise ValueError("field_path cannot be empty")

    def to_sql(self) -> tuple[Composed, list[Any]]:
        """Generate SQL for this condition.

        Returns:
            Tuple of (SQL Composed object, list of parameters)

        Examples:
            # FK column: machine_id = %s
            SQL: Identifier("machine_id") + SQL(" = ") + SQL("%s")
            Params: [UUID("123")]

            # JSONB path: data->'device'->>'name' = %s
            SQL: SQL("data->'device'->>'name' = %s")
            Params: ["Printer"]
        """
        params = []

        if self.lookup_strategy == "fk_column":
            # FK column lookup: machine_id = %s
            sql_op = ALL_OPERATORS[self.operator]

            if self.operator in CONTAINMENT_OPERATORS:
                # IN/NOT IN: machine_id IN (%s, %s, ...)
                # psycopg3 requires individual placeholders, not a single %s with tuple
                values_list = self.value if isinstance(self.value, list) else [self.value]
                placeholders = ", ".join(["%s"] * len(values_list))
                sql = Composed([Identifier(self.target_column), SQL(f" {sql_op} ({placeholders})")])
                params.extend(values_list)
            elif self.operator == "isnull":
                # IS NULL / IS NOT NULL
                null_op = "IS NULL" if self.value else "IS NOT NULL"
                sql = Composed([Identifier(self.target_column), SQL(f" {null_op}")])
            else:
                # Standard comparison: machine_id = %s
                sql = Composed([Identifier(self.target_column), SQL(f" {sql_op} "), SQL("%s")])
                params.append(self.value)

        elif self.lookup_strategy == "jsonb_path":
            # JSONB path lookup: data->'device'->>'name' = %s
            sql_op = ALL_OPERATORS[self.operator]

            # Build JSONB path: data->'device'->>'name'
            if not self.jsonb_path:
                raise ValueError("jsonb_path required for jsonb_path lookup")

            # Build the JSONB path as a Composed expression with proper escaping
            path_parts = [Identifier(self.target_column)]

            # Add intermediate keys with ->
            for key in self.jsonb_path[:-1]:
                path_parts.extend([SQL(" -> "), SQLLiteral(str(key))])

            # Add final key with ->> (text extraction)
            path_parts.extend([SQL(" ->> "), SQLLiteral(str(self.jsonb_path[-1]))])

            jsonb_expr = Composed(path_parts)

            # ID-based ltree hierarchy operators — generate nested IN subquery
            if self.operator in ("descendant_of_id", "ancestor_of_id"):
                from fraiseql.gql.builders.registry import SchemaRegistry
                from fraiseql.sql.where.core.sql_builder import (
                    _build_hierarchy_subquery,
                    _resolve_entity_name,
                )

                registry_instance = SchemaRegistry.get_instance()
                entity_schema = (
                    registry_instance.config.default_entity_schema
                    if registry_instance.config
                    else None
                )
                if entity_schema is None:
                    raise ValueError(
                        f"Operator '{self.operator}' requires FraiseQLConfig.default_entity_schema "
                        f"to be set (e.g., 'tenant')."
                    )
                db_field_name = self.jsonb_path[-1]
                entity_name = _resolve_entity_name(db_field_name)
                ltree_op = "<@" if self.operator == "descendant_of_id" else "@>"
                sql = _build_hierarchy_subquery(
                    entity_schema, entity_name, str(self.value), ltree_op, jsonb_expr
                )
                return sql, params

            if self.operator in CONTAINMENT_OPERATORS:
                # IN/NOT IN: psycopg3 requires individual placeholders
                values_list = self.value if isinstance(self.value, list) else [self.value]
                placeholders = ", ".join(["%s"] * len(values_list))
                sql = Composed([jsonb_expr, SQL(f" {sql_op} ({placeholders})")])
                params.extend(values_list)
            elif self.operator == "isnull":
                null_op = "IS NULL" if self.value else "IS NOT NULL"
                sql = Composed([jsonb_expr, SQL(f" {null_op}")])
            elif self.operator in STRING_OPERATORS:
                # LIKE/ILIKE with pattern
                pattern = self._build_like_pattern()
                sql = Composed([jsonb_expr, SQL(f" {sql_op} "), SQL("%s")])
                params.append(pattern)
            elif self.operator in NETWORK_OPERATORS:
                # Delegate to NetworkOperatorStrategy via operator registry
                registry = get_default_registry()
                sql = registry.build_sql(
                    operator=self.operator,
                    value=self.value,
                    path_sql=jsonb_expr,
                    field_type=None,  # Will be inferred by NetworkOperatorStrategy
                    jsonb_column="data",
                )
                if sql is None:
                    raise ValueError(
                        f"Network operator '{self.operator}' not supported by registry"
                    )
            else:
                # JSONB text comparison - need to handle boolean conversion
                sql = Composed([jsonb_expr, SQL(f" {sql_op} "), SQL("%s")])
                # Convert Python boolean to lowercase string for JSONB comparison
                if isinstance(self.value, bool):
                    params.append(str(self.value).lower())  # True -> "true", False -> "false"
                else:
                    params.append(str(self.value))

        elif self.lookup_strategy == "sql_column":
            # Direct SQL column: status = %s

            # ID-based ltree hierarchy operators — native UUID column variant
            if self.operator in ("descendant_of_id", "ancestor_of_id"):
                from fraiseql.gql.builders.registry import SchemaRegistry
                from fraiseql.sql.where.core.sql_builder import (
                    _build_hierarchy_subquery,
                    _resolve_entity_name,
                )

                registry_instance = SchemaRegistry.get_instance()
                entity_schema = (
                    registry_instance.config.default_entity_schema
                    if registry_instance.config
                    else None
                )
                if entity_schema is None:
                    raise ValueError(
                        f"Operator '{self.operator}' requires "
                        "FraiseQLConfig.default_entity_schema to be set (e.g. 'tenant')."
                    )
                entity_name = _resolve_entity_name(self.target_column)
                ltree_op = "<@" if self.operator == "descendant_of_id" else "@>"
                sql = _build_hierarchy_subquery(
                    entity_schema,
                    entity_name,
                    str(self.value),
                    ltree_op,
                    Identifier(self.target_column),
                )
                return sql, params

            sql_op = ALL_OPERATORS[self.operator]

            # Special case: 'contains' can be both string LIKE or array @>
            # Disambiguate based on value type
            if self.operator == "contains" and isinstance(self.value, list):
                # Array contains operator
                op = ARRAY_OPERATORS["contains"]
                sql = Composed([Identifier(self.target_column), SQL(f" {op} "), SQL("%s")])
                params.append(self.value)
            elif self.operator in CONTAINMENT_OPERATORS:
                # IN/NOT IN: psycopg3 requires individual placeholders
                values_list = self.value if isinstance(self.value, list) else [self.value]
                placeholders = ", ".join(["%s"] * len(values_list))
                sql = Composed([Identifier(self.target_column), SQL(f" {sql_op} ({placeholders})")])
                params.extend(values_list)
            elif self.operator == "isnull":
                null_op = "IS NULL" if self.value else "IS NOT NULL"
                sql = Composed([Identifier(self.target_column), SQL(f" {null_op}")])
            elif self.operator in STRING_OPERATORS:
                # String operators (LIKE/ILIKE)
                pattern = self._build_like_pattern()
                sql = Composed([Identifier(self.target_column), SQL(f" {sql_op} "), SQL("%s")])
                params.append(pattern)
            elif self.operator in VECTOR_OPERATORS:
                # Vector distance comparison
                # Value format: {"vector": [...], "threshold": 0.5, "comparison": "lt"}
                if isinstance(self.value, dict):
                    vector = self.value.get("vector")
                    threshold = self.value.get("threshold", 0.5)
                    comparison = self.value.get("comparison", "lt")
                elif isinstance(self.value, (list, tuple)) and len(self.value) == 2:
                    vector, threshold = self.value
                    comparison = "lt"
                else:
                    raise ValueError(
                        f"Vector operator requires dict or (vector, threshold) "
                        f"tuple, got {self.value!r}"
                    )

                comp_op = "<" if comparison == "lt" else "<=" if comparison == "lte" else ">"
                vector_op = VECTOR_OPERATORS[self.operator]
                # Escape % in operators to avoid psycopg placeholder interpretation
                vector_op_escaped = vector_op.replace("%", "%%")

                # Binary vectors (bit type) need different casting than regular vectors
                if self.operator in BINARY_VECTOR_OPERATORS:
                    # For bit type columns, no type cast needed (or use ::bit if needed)
                    sql = Composed(
                        [
                            SQL("("),
                            Identifier(self.target_column),
                            SQL(f" {vector_op_escaped} "),
                            SQL("%s"),
                            SQL(f") {comp_op} "),
                            SQL("%s"),
                        ]
                    )
                else:
                    # Regular vector type columns
                    sql = Composed(
                        [
                            SQL("("),
                            Identifier(self.target_column),
                            SQL("::vector"),
                            SQL(f" {vector_op_escaped} "),
                            SQL("%s::vector"),
                            SQL(f") {comp_op} "),
                            SQL("%s"),
                        ]
                    )
                params.extend([vector, threshold])
            elif self.operator in FULLTEXT_OPERATORS:
                # Fulltext search operators
                if self.operator == "matches":
                    # Basic fulltext: column @@ to_tsquery(%s)
                    sql = Composed(
                        [
                            Identifier(self.target_column),
                            SQL(" @@ to_tsquery("),
                            SQL("%s"),
                            SQL(")"),
                        ]
                    )
                    params.append(self.value)
                elif self.operator == "plain_query":
                    # Plain query: column @@ plainto_tsquery(%s)
                    sql = Composed(
                        [
                            Identifier(self.target_column),
                            SQL(" @@ plainto_tsquery("),
                            SQL("%s"),
                            SQL(")"),
                        ]
                    )
                    params.append(self.value)
                elif self.operator == "phrase_query":
                    # Phrase query: column @@ phraseto_tsquery(%s)
                    sql = Composed(
                        [
                            Identifier(self.target_column),
                            SQL(" @@ phraseto_tsquery("),
                            SQL("%s"),
                            SQL(")"),
                        ]
                    )
                    params.append(self.value)
                elif self.operator == "websearch_query":
                    # Websearch query: column @@ websearch_to_tsquery(%s)
                    sql = Composed(
                        [
                            Identifier(self.target_column),
                            SQL(" @@ websearch_to_tsquery("),
                            SQL("%s"),
                            SQL(")"),
                        ]
                    )
                    params.append(self.value)
                elif self.operator in ("rank_gt", "rank_lt"):
                    # Rank comparison: ts_rank(column, to_tsquery(%s)) > %s
                    # Value format: "query:threshold" or {"query": "search", "threshold": 0.5}
                    if isinstance(self.value, dict):
                        query = self.value.get("query")
                        threshold = self.value.get("threshold")
                    elif isinstance(self.value, str) and ":" in self.value:
                        query, threshold_str = self.value.split(":", 1)
                        threshold = float(threshold_str)
                    else:
                        raise ValueError(
                            f"rank_* operators require 'query:threshold' string or "
                            f"dict with query and threshold, got {self.value!r}"
                        )

                    comp = ">" if self.operator == "rank_gt" else "<"
                    sql = Composed(
                        [
                            SQL("ts_rank("),
                            Identifier(self.target_column),
                            SQL(", to_tsquery("),
                            SQL("%s"),
                            SQL(f")) {comp} "),
                            SQL("%s"),
                        ]
                    )
                    params.extend([query, threshold])
                elif self.operator in ("rank_cd_gt", "rank_cd_lt"):
                    # Cover density rank: ts_rank_cd(...)
                    # Value format: "query:threshold" or {"query": "search", "threshold": 0.5}
                    if isinstance(self.value, dict):
                        query = self.value.get("query")
                        threshold = self.value.get("threshold")
                    elif isinstance(self.value, str) and ":" in self.value:
                        query, threshold_str = self.value.split(":", 1)
                        threshold = float(threshold_str)
                    else:
                        raise ValueError(
                            f"rank_cd_* operators require 'query:threshold' string or "
                            f"dict with query and threshold, got {self.value!r}"
                        )

                    comp = ">" if self.operator == "rank_cd_gt" else "<"
                    sql = Composed(
                        [
                            SQL("ts_rank_cd("),
                            Identifier(self.target_column),
                            SQL(", to_tsquery("),
                            SQL("%s"),
                            SQL(f")) {comp} "),
                            SQL("%s"),
                        ]
                    )
                    params.extend([query, threshold])
            elif self.operator in ARRAY_OPERATORS:
                # Array operators
                if self.operator in ("array_eq", "array_neq"):
                    # Array equality: column = ARRAY[...]
                    op = "=" if self.operator == "array_eq" else "!="
                    sql = Composed([Identifier(self.target_column), SQL(f" {op} "), SQL("%s")])
                    params.append(self.value)
                elif self.operator in (
                    "array_contains",
                    "array_contained_by",
                    "contained_by",
                    "array_overlaps",
                    "overlaps",
                ):
                    # Array containment: column @> ARRAY[...]
                    # Note: 'contains' with list value is handled at the top of this function
                    # This should never be reached with 'contains', but check anyway
                    if self.operator == "contains":
                        raise ValueError(
                            f"Operator 'contains' reached ARRAY_OPERATORS section unexpectedly. "
                            f"Value type: {type(self.value).__name__}, value: {self.value!r}"
                        )
                    op = ARRAY_OPERATORS[self.operator]
                    sql = Composed([Identifier(self.target_column), SQL(f" {op} "), SQL("%s")])
                    params.append(self.value)
                elif self.operator in (
                    "array_length_eq",
                    "len_eq",
                    "array_length_gt",
                    "len_gt",
                    "array_length_lt",
                    "len_lt",
                    "array_length_gte",
                    "len_gte",
                ):
                    # Array length: array_length(column, 1) > %s
                    op = ARRAY_OPERATORS[self.operator]
                    sql = Composed(
                        [
                            SQL("array_length("),
                            Identifier(self.target_column),
                            SQL(", 1) "),
                            SQL(f"{op} "),
                            SQL("%s"),
                        ]
                    )
                    params.append(self.value)
                elif self.operator in ("array_any_eq", "any_eq", "array_all_eq", "all_eq"):
                    # ANY/ALL: %s = ANY(column)
                    op = "ANY" if self.operator in ("array_any_eq", "any_eq") else "ALL"
                    sql = Composed(
                        [SQL("%s = "), SQL(f"{op}("), Identifier(self.target_column), SQL(")")]
                    )
                    params.append(self.value)
            elif self.operator in NETWORK_OPERATORS:
                # Delegate to NetworkOperatorStrategy via operator registry
                registry = get_default_registry()
                column_sql = Identifier(self.target_column)
                sql = registry.build_sql(
                    operator=self.operator,
                    value=self.value,
                    path_sql=column_sql,
                    field_type=None,  # Will be inferred by NetworkOperatorStrategy
                    jsonb_column=None,
                )
                if sql is None:
                    raise ValueError(
                        f"Network operator '{self.operator}' not supported by registry"
                    )
            else:
                sql = Composed([Identifier(self.target_column), SQL(f" {sql_op} "), SQL("%s")])
                params.append(self.value)

        else:
            raise ValueError(f"Unknown lookup_strategy: {self.lookup_strategy}")

        return sql, params

    def _build_like_pattern(self) -> str:
        """Build LIKE pattern from operator and value."""
        if self.operator in ("contains", "icontains"):
            return f"%{self.value}%"
        if self.operator in ("startswith", "istartswith"):
            return f"{self.value}%"
        if self.operator in ("endswith", "iendswith"):
            return f"%{self.value}"
        if self.operator in ("like", "ilike"):
            # Explicit LIKE/ILIKE - user provides pattern with wildcards
            return str(self.value)
        return str(self.value)

    def __repr__(self) -> str:
        """Human-readable representation for debugging."""
        path_str = ".".join(self.field_path)

        if self.lookup_strategy == "fk_column":
            target = f"FK:{self.target_column}"
        elif self.lookup_strategy == "jsonb_path":
            jsonb_path_str = ".".join(self.jsonb_path or [])
            target = f"JSONB:{self.target_column}[{jsonb_path_str}]"
        else:
            target = f"COL:{self.target_column}"

        return f"FieldCondition({path_str} {self.operator} {self.value!r} → {target})"


@dataclass
class WhereClause:
    """Canonical representation of a WHERE clause.

    Represents the complete WHERE clause including multiple conditions,
    logical operators (AND/OR/NOT), and nested sub-clauses.

    Attributes:
        conditions: List of field conditions (combined with logical_op)
        logical_op: How to combine conditions ("AND" or "OR")
        nested_clauses: Sub-clauses for complex queries
        not_clause: Optional NOT clause

    Examples:
        # Simple: status = 'active'
        WhereClause(
            conditions=[
                FieldCondition(field_path=["status"], operator="eq", value="active", ...)
            ]
        )

        # Multiple conditions: status = 'active' AND machine_id = '123'
        WhereClause(
            conditions=[
                FieldCondition(field_path=["status"], ...),
                FieldCondition(field_path=["machine", "id"], ...)
            ],
            logical_op="AND"
        )

        # Nested: (status = 'active' OR status = 'pending') AND machine_id = '123'
        WhereClause(
            conditions=[
                FieldCondition(field_path=["machine", "id"], ...)
            ],
            nested_clauses=[
                WhereClause(
                    conditions=[
                        FieldCondition(field_path=["status"], operator="eq", value="active", ...),
                        FieldCondition(field_path=["status"], operator="eq", value="pending", ...)
                    ],
                    logical_op="OR"
                )
            ]
        )
    """

    conditions: list[FieldCondition] = field(default_factory=list)
    logical_op: Literal["AND", "OR"] = "AND"
    nested_clauses: list[WhereClause] = field(default_factory=list)
    not_clause: WhereClause | None = None

    def __post_init__(self):
        """Validate the WHERE clause."""
        if self.logical_op not in ("AND", "OR"):
            raise ValueError(f"Invalid logical_op '{self.logical_op}'. Must be 'AND' or 'OR'")

        # Must have at least one condition or nested clause
        if not self.conditions and not self.nested_clauses and not self.not_clause:
            raise ValueError(
                "WhereClause must have at least one condition, nested clause, or NOT clause"
            )

    def to_sql(self) -> tuple[Composed | None, list[Any]]:
        """Generate SQL for this WHERE clause.

        Returns:
            Tuple of (SQL Composed object or None, list of parameters)

        Examples:
            # Simple: status = %s
            SQL: Identifier("status") + SQL(" = ") + SQL("%s")
            Params: ["active"]

            # Multiple: status = %s AND machine_id = %s
            SQL: Identifier("status") + ... + SQL(" AND ") + Identifier("machine_id") + ...
            Params: ["active", UUID("123")]
        """
        all_parts = []
        all_params = []

        # Generate SQL for each condition
        for condition in self.conditions:
            sql, params = condition.to_sql()
            all_parts.append(sql)
            all_params.extend(params)

        # Generate SQL for nested clauses
        for nested in self.nested_clauses:
            nested_sql, nested_params = nested.to_sql()
            if nested_sql:
                # Wrap in parentheses
                wrapped = Composed([SQL("("), nested_sql, SQL(")")])
                all_parts.append(wrapped)
                all_params.extend(nested_params)

        # Generate SQL for NOT clause
        if self.not_clause:
            not_sql, not_params = self.not_clause.to_sql()
            if not_sql:
                wrapped = Composed([SQL("NOT ("), not_sql, SQL(")")])
                all_parts.append(wrapped)
                all_params.extend(not_params)

        # Combine with logical operator
        if not all_parts:
            return None, []

        if len(all_parts) == 1:
            return all_parts[0], all_params

        # Join with AND/OR
        separator = SQL(f" {self.logical_op} ")
        combined_sql = separator.join(all_parts)

        return combined_sql, all_params

    def __repr__(self) -> str:
        """Human-readable representation for debugging."""
        parts = []

        if self.conditions:
            cond_strs = [str(c) for c in self.conditions]
            parts.append(f" {self.logical_op} ".join(cond_strs))

        if self.nested_clauses:
            for nested in self.nested_clauses:
                parts.append(f"({nested!r})")

        if self.not_clause:
            parts.append(f"NOT ({self.not_clause!r})")

        return f"WhereClause({' AND '.join(parts)})"

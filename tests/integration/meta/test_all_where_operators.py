"""Meta-test for ALL WHERE operators E2E integration.

This test validates that every WHERE operator in FraiseQL works through the
complete GraphQL pipeline: query parsing → validation → SQL generation → execution.

It auto-discovers all operators and tests each one in real GraphQL queries.
"""

import json

import pytest
from graphql import graphql

# Import schema_builder to ensure SchemaRegistry is patched
import fraiseql.gql.schema_builder  # noqa: F401
from fraiseql import fraise_type, query
from fraiseql.gql.builders import SchemaRegistry
from fraiseql.types import CIDR, ID, DateRange, IpAddress, LTree
from fraiseql.where_clause import ALL_OPERATORS


async def ensure_extensions(conn, column_type: str):
    """Ensure required PostgreSQL extensions are available for column type.

    Note: Extensions are already created globally in test fixtures, but this
    provides explicit documentation of requirements.
    """
    extension_map = {
        "VECTOR(3)": "vector",  # pgvector
        "LTREE": "ltree",  # ltree for hierarchical paths
    }

    required_ext = extension_map.get(column_type)
    if required_ext:
        await conn.execute(f"CREATE EXTENSION IF NOT EXISTS {required_ext}")


def format_insert_value(value, column_type: str) -> str:
    """Format value for INSERT statement based on PostgreSQL column type."""
    if column_type.endswith("[]"):  # Array types
        if isinstance(value, list):
            items = ",".join(f'"{v}"' for v in value)  # Use double quotes for array literals
            return f"{{{items}}}"  # PostgreSQL array literal syntax: {item1,item2}

    # Special types requiring casting
    if column_type == "TSVECTOR":
        return f"to_tsvector('english', '{value}')"
    if column_type == "LTREE":
        return f"'{value}'::ltree"
    if column_type == "INET":
        return f"'{value}'::inet"
    if column_type == "CIDR":
        return f"'{value}'::cidr"
    if column_type == "DATERANGE":
        return f"'{value}'::daterange"
    if column_type.startswith("VECTOR"):
        # Convert GraphQL vector format {"dense": [0.1,0.2,0.3]} to PostgreSQL format
        if isinstance(value, dict) and "dense" in value:
            vector_str = ",".join(str(x) for x in value["dense"])
            return f"'[{vector_str}]'"
        return f"'{value}'"

    # Default: quote strings, pass numbers as-is
    return f"'{value}'" if isinstance(value, str) else str(value)


def get_test_insert_value(operator: str):
    """Get the appropriate insert value for database testing of an operator.

    Uses the same test values from get_test_params_for_operator() for consistency.
    """
    test_value, _, _, _ = get_db_test_params_for_operator(operator)
    return test_value


def snake_to_camel(name: str) -> str:
    """Convert snake_case to camelCase.

    Args:
        name: Snake case string (e.g., "cosine_distance")

    Returns:
        camelCase string (e.g., "cosineDistance")
    """
    components = name.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


def format_graphql_value(value):
    """Format Python value as GraphQL-compatible string.

    GraphQL requires specific formatting for different value types:
    - Strings: double quotes (not single quotes)
    - Booleans: lowercase true/false (not True/False)
    - Numbers: no quotes
    - Arrays: [item1, item2, ...]
    - null: lowercase null

    Args:
        value: Python value to format

    Returns:
        str: GraphQL-formatted value string

    Examples:
        >>> format_graphql_value("test")
        '"test"'
        >>> format_graphql_value(True)
        'true'
        >>> format_graphql_value(42)
        '42'
        >>> format_graphql_value(["a", "b"])
        '["a", "b"]'
    """
    if isinstance(value, str):
        # Use json.dumps to get double-quoted strings
        return json.dumps(value)
    if isinstance(value, bool):
        # GraphQL uses lowercase true/false
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        # Numbers don't need quotes
        return str(value)
    if isinstance(value, list):
        # Arrays: [item1, item2, ...]
        items = ", ".join(format_graphql_value(item) for item in value)
        return f"[{items}]"
    if isinstance(value, dict):
        # Objects: {key: value, ...}
        pairs = ", ".join(f"{k}: {format_graphql_value(v)}" for k, v in value.items())
        return f"{{{pairs}}}"
    if value is None:
        return "null"
    # Fallback: convert to string (may not always work)
    return str(value)


def get_all_operators():
    """Auto-enumerate all WHERE operators from ALL_OPERATORS."""
    operators = []
    for operator_name in ALL_OPERATORS.keys():
        # Skip internal/private operators
        if operator_name.startswith("_"):
            continue
        operators.append(operator_name)
    return operators


@pytest.fixture(scope="class")
def operator_test_schema(meta_test_schema):
    """Schema registry prepared with operator test types for all filter categories."""
    # Clear any existing registrations
    meta_test_schema.clear()

    # ==========================================
    # Test types for each filter category
    # ==========================================

    # StringFilter test type - for string operators
    @fraise_type(sql_source="test_strings")
    class StringTestType:
        id: int
        name: str
        description: str

    # IntFilter/FloatFilter test type - for numeric operators
    @fraise_type(sql_source="test_numbers")
    class NumberTestType:
        id: int
        value: int
        score: float

    # ArrayFilter test type - for array operators
    @fraise_type(sql_source="test_arrays")
    class ArrayTestType:
        id: int
        tags: list[str]
        numbers: list[int]

    # NetworkAddressFilter test type - for network operators
    # Uses IpAddress and CIDR scalar types
    @fraise_type(sql_source="test_networks")
    class NetworkTestType:
        id: int
        ip_address: IpAddress  # Maps to NetworkAddressFilter
        network: CIDR  # Maps to NetworkAddressFilter

    # LTreeFilter test type - for ltree/path operators
    @fraise_type(sql_source="test_ltrees")
    class LTreeTestType:
        id: int
        path: LTree  # Maps to LTreeFilter

    # DateRangeFilter test type - for range operators
    @fraise_type(sql_source="test_ranges")
    class DateRangeTestType:
        id: int
        date_range: DateRange  # Maps to DateRangeFilter

    # VectorFilter test type - for vector/embedding operators
    # Uses field naming convention to trigger VectorFilter
    @fraise_type(sql_source="test_vectors")
    class VectorTestType:
        id: int
        embedding: list[float]  # 'embedding' in name -> VectorFilter

    # FullTextFilter test type - for fulltext search operators
    # Uses field naming convention to trigger FullTextFilter
    @fraise_type(sql_source="test_fulltext")
    class FullTextTestType:
        id: int
        search_vector: str  # 'search_vector' in name -> FullTextFilter

    # JSONBFilter test type - for JSONB operators
    @fraise_type(sql_source="test_jsonb")
    class JSONBTestType:
        id: int
        data: dict  # Maps to JSONBFilter

    # IDFilter test type - for ID/UUID operators (descendant_of_id, ancestor_of_id)
    @fraise_type(sql_source="test_ids")
    class IDTestType:
        id: int
        entity_id: ID  # Maps to IDFilter

    # ==========================================
    # Register queries for each type
    # ==========================================

    @query
    async def get_strings(info) -> list[StringTestType]:
        return []

    @query
    async def get_numbers(info) -> list[NumberTestType]:
        return []

    @query
    async def get_arrays(info) -> list[ArrayTestType]:
        return []

    @query
    async def get_networks(info) -> list[NetworkTestType]:
        return []

    @query
    async def get_ltrees(info) -> list[LTreeTestType]:
        return []

    @query
    async def get_ranges(info) -> list[DateRangeTestType]:
        return []

    @query
    async def get_vectors(info) -> list[VectorTestType]:
        return []

    @query
    async def get_fulltext(info) -> list[FullTextTestType]:
        return []

    @query
    async def get_jsonb(info) -> list[JSONBTestType]:
        return []

    @query
    async def get_ids(info) -> list[IDTestType]:
        return []

    # Register all types and queries
    meta_test_schema.register_type(StringTestType)
    meta_test_schema.register_type(NumberTestType)
    meta_test_schema.register_type(ArrayTestType)
    meta_test_schema.register_type(NetworkTestType)
    meta_test_schema.register_type(LTreeTestType)
    meta_test_schema.register_type(DateRangeTestType)
    meta_test_schema.register_type(VectorTestType)
    meta_test_schema.register_type(FullTextTestType)
    meta_test_schema.register_type(JSONBTestType)
    meta_test_schema.register_type(IDTestType)

    meta_test_schema.register_query(get_strings)
    meta_test_schema.register_query(get_numbers)
    meta_test_schema.register_query(get_arrays)
    meta_test_schema.register_query(get_networks)
    meta_test_schema.register_query(get_ltrees)
    meta_test_schema.register_query(get_ranges)
    meta_test_schema.register_query(get_vectors)
    meta_test_schema.register_query(get_fulltext)
    meta_test_schema.register_query(get_jsonb)
    meta_test_schema.register_query(get_ids)

    return meta_test_schema


@pytest.mark.parametrize("operator", get_all_operators())
async def test_operator_in_graphql_query_validation(operator, operator_test_schema):
    """Every operator should pass GraphQL query validation without errors."""
    # Get appropriate test value and field for this operator
    test_value, field_name, query_name = get_test_params_for_operator(operator)

    # Convert operator name to camelCase for GraphQL
    # (FraiseQL converts snake_case Python field names to camelCase in GraphQL)
    graphql_operator = snake_to_camel(operator)

    # Build GraphQL query using the operator
    # Use format_graphql_value() to ensure proper GraphQL formatting (double quotes, etc.)
    query_str = f"""
    query {{
        {query_name}(where: {{{field_name}: {{{graphql_operator}: {format_graphql_value(test_value)}}}}}) {{
            id
        }}
    }}
    """

    schema = operator_test_schema.build_schema()

    # Execute query - should NOT raise validation error
    result = await graphql(schema, query_str)

    # Should not have validation errors
    assert not result.errors, (
        f"Operator '{operator}' (graphql: {graphql_operator}) failed GraphQL validation: {result.errors}"
    )


@pytest.mark.parametrize("operator", get_all_operators())
async def test_operator_in_where_clause_with_database(operator, meta_test_pool):
    """Every operator should work in WHERE clauses with real database operations."""
    # Convert operator name to camelCase for GraphQL
    graphql_operator = snake_to_camel(operator)

    # Get test parameters
    test_value, field_name, table_name, column_type = get_db_test_params_for_operator(operator)

    # Get the correct GraphQL test value (may differ from database insertion value)
    graphql_test_value, _, _ = get_test_params_for_operator(operator)

    # Create test table
    async with meta_test_pool.connection() as conn:
        from psycopg import sql

        # Ensure required extensions
        await ensure_extensions(conn, column_type)

        await conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table_name)))
        await conn.execute(
            sql.SQL("CREATE TABLE {} (id SERIAL PRIMARY KEY, {} {})").format(
                sql.Identifier(table_name), sql.Identifier(field_name), sql.SQL(column_type)
            )
        )

        # Insert test data with proper formatting
        test_value = get_test_insert_value(operator)

        # Use parameterized queries for all types - psycopg handles type conversion
        await conn.execute(
            sql.SQL("INSERT INTO {} ({}) VALUES (%s)").format(
                sql.Identifier(table_name), sql.Identifier(field_name)
            ),
            [test_value],
        )

        await conn.commit()

    try:
        # Create schema with test type
        registry = SchemaRegistry.get_instance()
        registry.clear()

        # Determine Python type based on column type
        if column_type == "INTEGER":
            field_type = int
        elif column_type == "FLOAT" or column_type == "DOUBLE PRECISION":
            field_type = float
        elif column_type == "TEXT[]":
            field_type = list[str]
        elif column_type.startswith("VECTOR") or column_type.startswith("BIT("):
            # VECTOR and BIT types both use list[float] to trigger VectorFilter
            # BIT is used for hamming/jaccard distance operators
            field_type = list[float]
        elif column_type == "LTREE":
            field_type = LTree  # Use LTree scalar type
        elif column_type == "INET":
            field_type = IpAddress  # Use IpAddress scalar type
        elif column_type == "CIDR":
            field_type = CIDR  # Use CIDR scalar type
        elif column_type == "DATERANGE":
            field_type = DateRange  # Use DateRange scalar type
        elif column_type == "UUID":
            field_type = ID  # Use ID scalar type for IDFilter
        else:
            field_type = str

        # Create dynamic type for this operator using @fraise_type
        # Use type() to create the class with the correct attributes
        attrs = {
            "id": int,
            field_name: field_type,
            "__annotations__": {"id": int, field_name: field_type},
            "__module__": __name__,
        }
        TestType = type(f"TestType_{operator}", (), attrs)

        # Apply the decorator
        TestType = fraise_type(sql_source=table_name, jsonb_column=None)(TestType)

        @query
        async def get_test_data(info) -> list[TestType]:
            return []

        registry.register_type(TestType)
        registry.register_query(get_test_data)

        # Convert field name to camelCase for GraphQL (FraiseQL converts snake_case to camelCase)
        graphql_field_name = snake_to_camel(field_name)

        # Use format_graphql_value for proper GraphQL formatting
        # graphql_test_value comes from get_test_params_for_operator which has the correct
        # GraphQL-format values (e.g., integer for nlevel, not the ltree path)
        formatted_value = format_graphql_value(graphql_test_value)

        query_str = f"""
        query {{
            getTestData(where: {{{graphql_field_name}: {{{graphql_operator}: {formatted_value}}}}}) {{
                id
                {graphql_field_name}
            }}
        }}
        """

        schema = registry.build_schema()

        # Execute query - should work without errors
        result = await graphql(schema, query_str)

        assert not result.errors, f"Operator '{operator}' failed in WHERE clause: {result.errors}"

    finally:
        # Cleanup
        async with meta_test_pool.connection() as conn:
            from psycopg import sql

            await conn.execute(
                sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table_name))
            )
            await conn.commit()


# Only test string operators that work with StringFilter in AND/OR combinations
STRING_OPERATORS_FOR_COMBINATION = ["eq", "neq", "contains", "in"]


@pytest.mark.parametrize("operator", STRING_OPERATORS_FOR_COMBINATION)
async def test_operator_combinations_with_and_or(operator, operator_test_schema):
    """Operators should work in AND/OR combinations."""
    # Use simple string operators for combination testing (all on StringFilter)
    test_value1, test_value2 = get_test_values_for_combination(operator)

    # Test AND combination - both conditions on string fields
    query_str = f"""
    query {{
        getStrings(where: {{
            AND: [
                {{name: {{eq: {format_graphql_value(test_value1)}}}}},
                {{description: {{{operator}: {format_graphql_value(test_value2)}}}}}
            ]
        }}) {{
            id
            name
            description
        }}
    }}
    """

    schema = operator_test_schema.build_schema()

    # Execute query - should work without errors
    result = await graphql(schema, query_str)

    assert not result.errors, f"Operator '{operator}' failed in AND combination: {result.errors}"

    # Test OR combination
    query_str_or = f"""
    query {{
        getStrings(where: {{
            OR: [
                {{name: {{eq: {format_graphql_value(test_value1)}}}}},
                {{description: {{{operator}: {format_graphql_value(test_value2)}}}}}
            ]
        }}) {{
            id
            name
            description
        }}
    }}
    """

    result_or = await graphql(schema, query_str_or)

    assert not result_or.errors, (
        f"Operator '{operator}' failed in OR combination: {result_or.errors}"
    )


def get_test_params_for_operator(operator):
    """Get test parameters appropriate for the given operator.

    Returns (test_value, field_name, query_name) tuple where:
    - test_value: A valid test value for the operator
    - field_name: The field name to use in the query
    - query_name: The GraphQL query name to use

    Maps operators to the correct filter types:
    - String operators -> StringFilter (name field on getStrings)
    - Numeric operators -> IntFilter/FloatFilter (value/score on getNumbers)
    - Array operators -> ArrayFilter (tags on getArrays)
    - Network operators -> NetworkAddressFilter (ipAddress/network on getNetworks)
    - LTree operators -> LTreeFilter (path on getLtrees)
    - Range operators -> DateRangeFilter (dateRange on getRanges)
    - Vector operators -> VectorFilter (embedding on getVectors)
    - FullText operators -> FullTextFilter (searchVector on getFulltext)
    """
    test_configs = {
        # ==========================================
        # StringFilter operators (getStrings)
        # ==========================================
        "eq": ("test_value", "name", "getStrings"),
        "neq": ("test_value", "name", "getStrings"),
        "in": (["value1", "value2"], "name", "getStrings"),
        "nin": (["value1", "value2"], "name", "getStrings"),
        "notin": (["value1", "value2"], "name", "getStrings"),
        "isnull": (True, "name", "getStrings"),
        "contains": ("test", "name", "getStrings"),
        "icontains": ("TEST", "name", "getStrings"),
        "startswith": ("test", "name", "getStrings"),
        "istartswith": ("TEST", "name", "getStrings"),
        "endswith": ("value", "name", "getStrings"),
        "iendswith": ("VALUE", "name", "getStrings"),
        "like": ("test%", "name", "getStrings"),
        "ilike": ("TEST%", "name", "getStrings"),
        "matches": ("search", "name", "getStrings"),
        "imatches": ("SEARCH", "name", "getStrings"),
        "not_matches": ("exclude", "name", "getStrings"),
        # ==========================================
        # IntFilter/FloatFilter operators (getNumbers)
        # ==========================================
        "gt": (5, "value", "getNumbers"),
        "gte": (5, "value", "getNumbers"),
        "lt": (10, "value", "getNumbers"),
        "lte": (10, "value", "getNumbers"),
        # ==========================================
        # ArrayFilter operators (getArrays)
        # ==========================================
        "array_eq": (["tag1", "tag2"], "tags", "getArrays"),
        "array_neq": (["tag1", "tag2"], "tags", "getArrays"),
        "array_contains": (["tag1"], "tags", "getArrays"),
        "array_contained_by": (["tag1", "tag2", "tag3"], "tags", "getArrays"),
        "contained_by": (["tag1", "tag2", "tag3"], "tags", "getArrays"),
        "array_overlaps": (["tag1", "tag3"], "tags", "getArrays"),
        "overlaps": (["tag1", "tag3"], "tags", "getArrays"),
        "strictly_contains": (["tag1"], "tags", "getArrays"),
        "array_any_eq": ("tag1", "tags", "getArrays"),
        "any_eq": ("tag1", "tags", "getArrays"),
        "array_all_eq": ("tag1", "tags", "getArrays"),
        "all_eq": ("tag1", "tags", "getArrays"),
        "in_array": ("tag1", "tags", "getArrays"),
        "array_length_eq": (2, "tags", "getArrays"),
        "array_length_gt": (1, "tags", "getArrays"),
        "array_length_gte": (2, "tags", "getArrays"),
        "array_length_lt": (5, "tags", "getArrays"),
        "len_eq": (2, "tags", "getArrays"),
        "len_gt": (1, "tags", "getArrays"),
        "len_gte": (2, "tags", "getArrays"),
        "len_lt": (5, "tags", "getArrays"),
        "len_lte": (5, "tags", "getArrays"),
        "len_neq": (0, "tags", "getArrays"),
        # ==========================================
        # NetworkAddressFilter operators (getNetworks)
        # ==========================================
        "isIPv4": (True, "ipAddress", "getNetworks"),
        "isIPv6": (True, "ipAddress", "getNetworks"),
        "isPrivate": (True, "ipAddress", "getNetworks"),
        "isPublic": (True, "ipAddress", "getNetworks"),
        "inSubnet": ("192.168.1.0/24", "ipAddress", "getNetworks"),
        "inRange": ({"from": "192.168.0.1", "to": "192.168.0.255"}, "ipAddress", "getNetworks"),
        "strictleft": ("10.0.0.0/8", "network", "getNetworks"),
        "strictright": ("10.0.0.0/8", "network", "getNetworks"),
        # Advanced network operators (CamelCase)
        "isLoopback": (True, "ipAddress", "getNetworks"),
        "isMulticast": (True, "ipAddress", "getNetworks"),
        "isBroadcast": (True, "ipAddress", "getNetworks"),
        "isLinkLocal": (True, "ipAddress", "getNetworks"),
        "isDocumentation": (True, "ipAddress", "getNetworks"),
        "isReserved": (True, "ipAddress", "getNetworks"),
        "isCarrierGrade": (True, "ipAddress", "getNetworks"),
        "isSiteLocal": (True, "ipAddress", "getNetworks"),
        "isUniqueLocal": (True, "ipAddress", "getNetworks"),
        "isGlobalUnicast": (True, "ipAddress", "getNetworks"),
        # Lowercase variants
        "isipv4": (True, "ipAddress", "getNetworks"),
        "isipv6": (True, "ipAddress", "getNetworks"),
        "isprivate": (True, "ipAddress", "getNetworks"),
        "ispublic": (True, "ipAddress", "getNetworks"),
        "insubnet": ("192.168.1.0/24", "ipAddress", "getNetworks"),
        "inrange": ({"from": "192.168.0.1", "to": "192.168.0.255"}, "ipAddress", "getNetworks"),
        # Advanced network operators (lowercase)
        "isloopback": (True, "ipAddress", "getNetworks"),
        "ismulticast": (True, "ipAddress", "getNetworks"),
        "isbroadcast": (True, "ipAddress", "getNetworks"),
        "islinklocal": (True, "ipAddress", "getNetworks"),
        "isdocumentation": (True, "ipAddress", "getNetworks"),
        "isreserved": (True, "ipAddress", "getNetworks"),
        "iscarriergrade": (True, "ipAddress", "getNetworks"),
        "issitelocal": (True, "ipAddress", "getNetworks"),
        "isuniquelocal": (True, "ipAddress", "getNetworks"),
        "isglobalunicast": (True, "ipAddress", "getNetworks"),
        # ==========================================
        # IDFilter operators (getIds)
        # ==========================================
        "descendant_of_id": ("some-id", "entityId", "getIds"),
        "ancestor_of_id": ("some-id", "entityId", "getIds"),
        # ==========================================
        # LTreeFilter operators (getLtrees)
        # ==========================================
        "ancestor_of": ("path.to.node", "path", "getLtrees"),
        "descendant_of": ("path.to.node", "path", "getLtrees"),
        "isdescendant": ("path.to.node", "path", "getLtrees"),
        "matches_lquery": ("*.node.*", "path", "getLtrees"),
        "matches_ltxtquery": ("node", "path", "getLtrees"),
        "matches_any_lquery": (["*.a.*", "*.b.*"], "path", "getLtrees"),
        "subpath": ("path.to", "path", "getLtrees"),
        "index": (1, "path", "getLtrees"),
        "index_eq": (1, "path", "getLtrees"),
        "index_gte": (0, "path", "getLtrees"),
        "lca": (["a.b.c", "a.b.d"], "path", "getLtrees"),
        "concat": ("additional.path", "path", "getLtrees"),
        # LTree level operators
        "nlevel": (3, "path", "getLtrees"),
        "nlevel_eq": (3, "path", "getLtrees"),
        "nlevel_gt": (2, "path", "getLtrees"),
        "nlevel_gte": (2, "path", "getLtrees"),
        "nlevel_lt": (5, "path", "getLtrees"),
        "nlevel_lte": (5, "path", "getLtrees"),
        "nlevel_neq": (0, "path", "getLtrees"),
        "depth_eq": (3, "path", "getLtrees"),
        "depth_gt": (2, "path", "getLtrees"),
        "depth_gte": (2, "path", "getLtrees"),
        "depth_lt": (5, "path", "getLtrees"),
        "depth_lte": (5, "path", "getLtrees"),
        "depth_neq": (0, "path", "getLtrees"),
        # ==========================================
        # DateRangeFilter operators (getRanges)
        # ==========================================
        "adjacent": ("2024-01-01", "dateRange", "getRanges"),
        "strictly_left": ("2024-01-01", "dateRange", "getRanges"),
        "strictly_right": ("2024-01-01", "dateRange", "getRanges"),
        "not_left": ("2024-01-01", "dateRange", "getRanges"),
        "not_right": ("2024-01-01", "dateRange", "getRanges"),
        "contains_date": ("2024-01-01", "dateRange", "getRanges"),
        # ==========================================
        # VectorFilter operators (getVectors)
        # Uses VectorDistanceInput with 'dense' field for array vectors
        # ==========================================
        "cosine_distance": ({"dense": [0.1, 0.2, 0.3]}, "embedding", "getVectors"),
        "l1_distance": ({"dense": [0.1, 0.2, 0.3]}, "embedding", "getVectors"),
        "l2_distance": ({"dense": [0.1, 0.2, 0.3]}, "embedding", "getVectors"),
        "inner_product": ({"dense": [0.1, 0.2, 0.3]}, "embedding", "getVectors"),
        "hamming_distance": ("101010", "embedding", "getVectors"),
        "jaccard_distance": ("111000", "embedding", "getVectors"),
        "distance_within": (1.0, "embedding", "getVectors"),
        # ==========================================
        # FullTextFilter operators (getFulltext)
        # ==========================================
        "plain_query": ("search term", "searchVector", "getFulltext"),
        "phrase_query": ("exact phrase", "searchVector", "getFulltext"),
        "websearch_query": ("web search", "searchVector", "getFulltext"),
        "rank_gt": ("search:0.5", "searchVector", "getFulltext"),
        "rank_lt": ("search:0.9", "searchVector", "getFulltext"),
        "rank_gte": ("search:0.5", "searchVector", "getFulltext"),
        "rank_lte": ("search:0.9", "searchVector", "getFulltext"),
        "rank_cd_gt": ("search:0.5", "searchVector", "getFulltext"),
        "rank_cd_lt": ("search:0.9", "searchVector", "getFulltext"),
        "rank_cd_gte": ("search:0.5", "searchVector", "getFulltext"),
        "rank_cd_lte": ("search:0.9", "searchVector", "getFulltext"),
    }

    # Return default for unknown operators
    return test_configs.get(operator, ("test_value", "name", "getStrings"))


def get_db_test_params_for_operator(operator):
    """Get database test parameters for the given operator.

    Returns (test_value, field_name, table_name, column_type) tuple.
    Now supports all 89+ operators with appropriate PostgreSQL column types.
    """
    db_configs = {
        # ==========================================
        # Existing basic operators (already working)
        # ==========================================
        "eq": ("test_value", "name", "test_eq_table", "TEXT"),
        "neq": ("test_value", "name", "test_neq_table", "TEXT"),
        "gt": (5, "value", "test_gt_table", "INTEGER"),
        "gte": (5, "value", "test_gte_table", "INTEGER"),
        "lt": (10, "value", "test_lt_table", "INTEGER"),
        "lte": (10, "value", "test_lte_table", "INTEGER"),
        "contains": ("test_string", "name", "test_contains_table", "TEXT"),
        "icontains": ("TEST_STRING", "name", "test_icontains_table", "TEXT"),
        "startswith": ("test", "name", "test_startswith_table", "TEXT"),
        "istartswith": ("TEST", "name", "test_istartswith_table", "TEXT"),
        "endswith": ("string", "name", "test_endswith_table", "TEXT"),
        "iendswith": ("STRING", "name", "test_iendswith_table", "TEXT"),
        "like": ("test%", "name", "test_like_table", "TEXT"),
        "ilike": ("TEST%", "name", "test_ilike_table", "TEXT"),
        "in": ("value1", "name", "test_in_table", "TEXT"),
        "nin": ("value1", "name", "test_nin_table", "TEXT"),
        "isnull": (True, "name", "test_isnull_table", "TEXT"),
        # ==========================================
        # Vector operators (7 operators)
        # Note: Vector insert value is a string like "[0.1,0.2,0.3]" for psycopg
        # ==========================================
        "cosine_distance": (
            "[0.1,0.2,0.3]",
            "embedding",
            "test_cosine_distance_table",
            "VECTOR(3)",
        ),
        "l2_distance": (
            "[0.1,0.2,0.3]",
            "embedding",
            "test_l2_distance_table",
            "VECTOR(3)",
        ),
        "l1_distance": (
            "[0.1,0.2,0.3]",
            "embedding",
            "test_l1_distance_table",
            "VECTOR(3)",
        ),
        "inner_product": (
            "[0.1,0.2,0.3]",
            "embedding",
            "test_inner_product_table",
            "VECTOR(3)",
        ),
        "hamming_distance": ("101010", "embedding", "test_hamming_distance_table", "BIT(6)"),
        "jaccard_distance": ("111000", "embedding", "test_jaccard_distance_table", "BIT(6)"),
        "distance_within": (
            "[0.1,0.2,0.3]",
            "embedding",
            "test_distance_within_table",
            "VECTOR(3)",
        ),
        # ==========================================
        # FullText operators (11 operators)
        # ==========================================
        "matches": ("search term", "search_vector", "test_matches_table", "TSVECTOR"),
        "plain_query": ("search term", "search_vector", "test_plain_query_table", "TSVECTOR"),
        "phrase_query": ("exact phrase", "search_vector", "test_phrase_query_table", "TSVECTOR"),
        "websearch_query": (
            "web search",
            "search_vector",
            "test_websearch_query_table",
            "TSVECTOR",
        ),
        "rank_gt": ("search term", "search_vector", "test_rank_gt_table", "TSVECTOR"),
        "rank_lt": ("search term", "search_vector", "test_rank_lt_table", "TSVECTOR"),
        "rank_gte": ("search term", "search_vector", "test_rank_gte_table", "TSVECTOR"),
        "rank_lte": ("search term", "search_vector", "test_rank_lte_table", "TSVECTOR"),
        "rank_cd_gt": ("search term", "search_vector", "test_rank_cd_gt_table", "TSVECTOR"),
        "rank_cd_lt": ("search term", "search_vector", "test_rank_cd_lt_table", "TSVECTOR"),
        "rank_cd_gte": ("search term", "search_vector", "test_rank_cd_gte_table", "TSVECTOR"),
        "rank_cd_lte": ("search term", "search_vector", "test_rank_cd_lte_table", "TSVECTOR"),
        # ==========================================
        # Array operators (20 operators)
        # ==========================================
        "array_eq": (["tag1", "tag2"], "tags", "test_array_eq_table", "TEXT[]"),
        "array_neq": (["tag1", "tag2"], "tags", "test_array_neq_table", "TEXT[]"),
        "array_contains": (["tag1"], "tags", "test_array_contains_table", "TEXT[]"),
        "array_contained_by": (
            ["tag1", "tag2", "tag3"],
            "tags",
            "test_array_contained_by_table",
            "TEXT[]",
        ),
        "array_overlaps": (["tag1", "tag3"], "tags", "test_array_overlaps_table", "TEXT[]"),
        "array_length_eq": (["tag1", "tag2"], "tags", "test_array_length_eq_table", "TEXT[]"),
        "array_length_gt": (["tag1"], "tags", "test_array_length_gt_table", "TEXT[]"),
        "array_length_gte": (["tag1", "tag2"], "tags", "test_array_length_gte_table", "TEXT[]"),
        "array_length_lt": (
            ["tag1", "tag2", "tag3", "tag4", "tag5"],
            "tags",
            "test_array_length_lt_table",
            "TEXT[]",
        ),
        "array_any_eq": (["tag1", "tag2"], "tags", "test_array_any_eq_table", "TEXT[]"),
        "any_eq": (["tag1", "tag2"], "tags", "test_any_eq_table", "TEXT[]"),
        "array_all_eq": (["tag1", "tag2"], "tags", "test_array_all_eq_table", "TEXT[]"),
        "all_eq": (["tag1", "tag2"], "tags", "test_all_eq_table", "TEXT[]"),
        # len_* operators: insert array, GraphQL query uses integer (from get_test_params)
        "len_eq": (["tag1", "tag2"], "tags", "test_len_eq_table", "TEXT[]"),
        "len_gt": (["tag1", "tag2"], "tags", "test_len_gt_table", "TEXT[]"),
        "len_gte": (["tag1", "tag2"], "tags", "test_len_gte_table", "TEXT[]"),
        "len_lt": (["tag1", "tag2", "tag3"], "tags", "test_len_lt_table", "TEXT[]"),
        "len_lte": (["tag1", "tag2", "tag3"], "tags", "test_len_lte_table", "TEXT[]"),
        "len_neq": (["tag1", "tag2"], "tags", "test_len_neq_table", "TEXT[]"),
        "strictly_contains": (["tag1"], "tags", "test_strictly_contains_table", "TEXT[]"),
        "in_array": (["tag1", "tag2"], "tags", "test_in_array_table", "TEXT[]"),
        # contained_by and overlaps are ArrayFilter operators (aliases)
        "contained_by": (["tag1", "tag2"], "tags", "test_contained_by_table", "TEXT[]"),
        "overlaps": (["tag1", "tag2"], "tags", "test_overlaps_table", "TEXT[]"),
        # ==========================================
        # Network operators (14 operators)
        # ==========================================
        "isIPv4": ("192.168.1.100", "ip_address", "test_isipv4_table", "INET"),
        "isIPv6": ("2001:db8::1", "ip_address", "test_isipv6_table", "INET"),
        "isPrivate": ("192.168.1.100", "ip_address", "test_isprivate_table", "INET"),
        "isPublic": ("8.8.8.8", "ip_address", "test_ispublic_table", "INET"),
        "inSubnet": ("192.168.1.100", "ip_address", "test_insubnet_table", "INET"),
        "inRange": ("192.168.1.100", "ip_address", "test_inrange_table", "INET"),
        "strictleft": ("192.168.0.0/16", "network", "test_strictleft_table", "CIDR"),
        "strictright": ("10.0.0.0/8", "network", "test_strictright_table", "CIDR"),
        "isipv4": ("192.168.1.100", "ip_address", "test_isipv4_lower_table", "INET"),
        "isipv6": ("2001:db8::1", "ip_address", "test_isipv6_lower_table", "INET"),
        "isprivate": ("192.168.1.100", "ip_address", "test_isprivate_lower_table", "INET"),
        "ispublic": ("8.8.8.8", "ip_address", "test_ispublic_lower_table", "INET"),
        "insubnet": ("192.168.1.100", "ip_address", "test_insubnet_lower_table", "INET"),
        "inrange": ("192.168.1.100", "ip_address", "test_inrange_lower_table", "INET"),
        # Advanced network operators (CamelCase)
        "isLoopback": ("127.0.0.1", "ip_address", "test_isloopback_table", "INET"),
        "isMulticast": ("224.0.0.1", "ip_address", "test_ismulticast_table", "INET"),
        "isBroadcast": ("255.255.255.255", "ip_address", "test_isbroadcast_table", "INET"),
        "isLinkLocal": ("169.254.0.1", "ip_address", "test_islinklocal_table", "INET"),
        "isDocumentation": ("192.0.2.1", "ip_address", "test_isdocumentation_table", "INET"),
        "isReserved": ("240.0.0.1", "ip_address", "test_isreserved_table", "INET"),
        "isCarrierGrade": ("100.64.0.1", "ip_address", "test_iscarriergrade_table", "INET"),
        "isSiteLocal": ("10.0.0.1", "ip_address", "test_issitelocal_table", "INET"),
        "isUniqueLocal": ("fc00::1", "ip_address", "test_isuniquelocal_table", "INET"),
        "isGlobalUnicast": ("8.8.8.8", "ip_address", "test_isglobalunicast_table", "INET"),
        # Advanced network operators (lowercase)
        "isloopback": ("127.0.0.1", "ip_address", "test_isloopback_lower_table", "INET"),
        "ismulticast": ("224.0.0.1", "ip_address", "test_ismulticast_lower_table", "INET"),
        "isbroadcast": ("255.255.255.255", "ip_address", "test_isbroadcast_lower_table", "INET"),
        "islinklocal": ("169.254.0.1", "ip_address", "test_islinklocal_lower_table", "INET"),
        "isdocumentation": ("192.0.2.1", "ip_address", "test_isdocumentation_lower_table", "INET"),
        "isreserved": ("240.0.0.1", "ip_address", "test_isreserved_lower_table", "INET"),
        "iscarriergrade": ("100.64.0.1", "ip_address", "test_iscarriergrade_lower_table", "INET"),
        "issitelocal": ("10.0.0.1", "ip_address", "test_issitelocal_lower_table", "INET"),
        "isuniquelocal": ("fc00::1", "ip_address", "test_isuniquelocal_lower_table", "INET"),
        "isglobalunicast": ("8.8.8.8", "ip_address", "test_isglobalunicast_lower_table", "INET"),
        # ID/UUID operators
        "descendant_of_id": (
            "11111111-1111-1111-1111-111111111111",
            "entity_id",
            "test_descendant_of_id_table",
            "UUID",
        ),
        "ancestor_of_id": (
            "11111111-1111-1111-1111-111111111111",
            "entity_id",
            "test_ancestor_of_id_table",
            "UUID",
        ),
        # ==========================================
        # LTree operators (21 operators)
        # ==========================================
        "ancestor_of": ("path.to.node", "path", "test_ancestor_of_table", "LTREE"),
        "descendant_of": ("path.to.node", "path", "test_descendant_of_table", "LTREE"),
        "isdescendant": ("path.to.node", "path", "test_isdescendant_table", "LTREE"),
        "matches_lquery": ("path.to.node", "path", "test_matches_lquery_table", "LTREE"),
        "matches_ltxtquery": ("path.to.node", "path", "test_matches_ltxtquery_table", "LTREE"),
        "matches_any_lquery": ("path.to.node", "path", "test_matches_any_lquery_table", "LTREE"),
        "subpath": ("path.to.node", "path", "test_subpath_table", "LTREE"),
        "index": ("path.to.node", "path", "test_index_table", "LTREE"),
        "index_eq": ("path.to.node", "path", "test_index_eq_table", "LTREE"),
        "index_gte": ("path.to.node", "path", "test_index_gte_table", "LTREE"),
        "lca": ("path.to.node", "path", "test_lca_table", "LTREE"),
        "concat": ("path.to.node", "path", "test_concat_table", "LTREE"),
        "nlevel": ("path.to.node", "path", "test_nlevel_table", "LTREE"),
        "nlevel_eq": ("path.to.node", "path", "test_nlevel_eq_table", "LTREE"),
        "nlevel_gt": ("path.to.node", "path", "test_nlevel_gt_table", "LTREE"),
        "nlevel_gte": ("path.to.node", "path", "test_nlevel_gte_table", "LTREE"),
        "nlevel_lt": ("path.to.node", "path", "test_nlevel_lt_table", "LTREE"),
        "nlevel_lte": ("path.to.node", "path", "test_nlevel_lte_table", "LTREE"),
        "nlevel_neq": ("path.to.node", "path", "test_nlevel_neq_table", "LTREE"),
        "depth_eq": ("path.to.node", "path", "test_depth_eq_table", "LTREE"),
        "depth_gt": ("path.to.node", "path", "test_depth_gt_table", "LTREE"),
        "depth_gte": ("path.to.node", "path", "test_depth_gte_table", "LTREE"),
        "depth_lt": ("path.to.node", "path", "test_depth_lt_table", "LTREE"),
        "depth_lte": ("path.to.node", "path", "test_depth_lte_table", "LTREE"),
        "depth_neq": ("path.to.node", "path", "test_depth_neq_table", "LTREE"),
        # ==========================================
        # DateRange operators (6 operators)
        # ==========================================
        "contains_date": (
            "[2024-01-01,2024-01-31]",
            "date_range",
            "test_contains_date_table",
            "DATERANGE",
        ),
        "adjacent": ("[2024-02-01,2024-02-28]", "date_range", "test_adjacent_table", "DATERANGE"),
        "strictly_left": (
            "[2024-03-01,2024-03-31]",
            "date_range",
            "test_strictly_left_table",
            "DATERANGE",
        ),
        "strictly_right": (
            "[2023-01-01,2023-12-31]",
            "date_range",
            "test_strictly_right_table",
            "DATERANGE",
        ),
        "not_left": ("[2024-01-01,2024-12-31]", "date_range", "test_not_left_table", "DATERANGE"),
        "not_right": ("[2024-01-01,2024-12-31]", "date_range", "test_not_right_table", "DATERANGE"),
        # ==========================================
        # String pattern operators (3 operators)
        # ==========================================
        "imatches": ("SEARCH", "name", "test_imatches_table", "TEXT"),
        "not_matches": ("exclude", "name", "test_not_matches_table", "TEXT"),
        "notin": (["value1", "value2"], "name", "test_notin_table", "TEXT"),
    }

    # Return default for unknown operators
    return db_configs.get(operator, ("test_value", "name", "test_default_table", "TEXT"))


def get_test_values_for_combination(operator):
    """Get test values for operator combination testing (string operators only)."""
    combination_values = {
        "eq": ("test_name", "test_description"),
        "neq": ("test_name", "other_description"),
        "contains": ("test_name", "desc"),
        "in": ("test_name", ["desc1", "desc2"]),
    }

    return combination_values.get(operator, ("value1", "value2"))

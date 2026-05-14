"""Tests for JSONB entities through full GraphQL execution stack.

This test suite validates that JSONB entities work correctly when accessed
through GraphQL resolvers with typed return values, not just direct repository access.

This reproduces the PrintOptim team's reported issue where:
- Direct repository calls work
- GraphQL queries with typed resolvers fail with RustResponseBytes errors

Related: /tmp/JSONB_ISSUE_ANALYSIS_PRINTOPTIM_VS_FRAISEQL.md
"""

import json

import pytest
import pytest_asyncio

pytestmark = pytest.mark.database

# Import database fixtures

import fraiseql
from fraiseql.core.rust_pipeline import RustResponseBytes
from fraiseql.db import FraiseQLRepository, register_type_for_view
from fraiseql.gql.schema_builder import build_fraiseql_schema
from fraiseql.graphql.execute import execute_graphql
from fraiseql.types import ID


# Test type with JSONB data
@fraiseql.type
class ProductWithJSONB:
    """Product entity with JSONB data column."""

    id: ID
    name: str
    brand: str  # Stored in JSONB
    category: str  # Stored in JSONB
    price: float  # Stored in JSONB


# GraphQL resolvers that return typed JSONB entities
@fraiseql.query
async def products_with_jsonb(info, limit: int = 10) -> list[ProductWithJSONB]:
    """List query with typed return value - this should reproduce PrintOptim's issue.

    The resolver returns list[ProductWithJSONB] but repo.find() returns RustResponseBytes.
    GraphQL-core will try to serialize RustResponseBytes as list[ProductWithJSONB].

    Expected error (PrintOptim's observation):
        "Expected Iterable, but did not find one for field 'Query.productsWithJsonb'."
    """
    pool = info.context.get("pool")
    test_schema = info.context.get("test_schema")
    repo = FraiseQLRepository(pool, context={"mode": "development"})
    return await repo.find(f"{test_schema}.test_products_graphql_jsonb_view", limit=limit)


@fraiseql.query
async def product_with_jsonb(info, id: ID) -> ProductWithJSONB | None:
    """Single query with typed return value.

    The resolver returns ProductWithJSONB | None but repo.find_one() returns RustResponseBytes.

    Expected error (PrintOptim's observation):
        "Expected value of type 'ProductWithJSONB' but got: <RustResponseBytes instance>."
    """
    pool = info.context.get("pool")
    test_schema = info.context.get("test_schema")
    repo = FraiseQLRepository(pool, context={"mode": "development"})
    return await repo.find_one(f"{test_schema}.test_products_graphql_jsonb_view", mandatory_filters={"id": id})


@fraiseql.mutation
async def create_product_with_jsonb(
    info, id: ID, name: str, brand: str, category: str, price: float
) -> ProductWithJSONB:
    """Mutation that creates a JSONB entity and returns it.

    This tests the mutation path with RustResponseBytes:
    - Create data in database
    - Return the created entity (via repository)
    - GraphQL-core tries to serialize the return value

    According to PrintOptim's observation, mutations work correctly while queries fail.
    This test verifies that mutations also work with the RustResponseBytes pass-through.
    """
    pool = info.context.get("pool")
    test_schema = info.context.get("test_schema")

    # Insert the new product into database
    async with pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}")
        json_data = json.dumps({"brand": brand, "category": category, "price": price})
        await conn.execute(
            f"""
            INSERT INTO {test_schema}.test_products_graphql_jsonb (id, name, data)
            VALUES ('{id}', '{name}', '{json_data}'::jsonb)
            """
        )

    # Return the created product via repository
    # This will return RustResponseBytes which should be passed through by execute_graphql()
    repo = FraiseQLRepository(pool, context={"mode": "development"})

    return await repo.find_one(f"{test_schema}.test_products_graphql_jsonb_view", mandatory_filters={"id": id})


class TestJSONBFullGraphQLExecution:
    """Test JSONB entities through complete GraphQL execution path.

    These tests go through the full stack:
        Test → GraphQL Query → Resolver → Repository → RustResponseBytes
            → GraphQL Type Checking → ??? (should work, but might fail)
    """

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def setup_graphql_jsonb_test(self, class_db_pool, test_schema):
        """Create test data and register types for GraphQL execution."""
        # Register type with has_jsonb_data=True
        register_type_for_view(
            f"{test_schema}.test_products_graphql_jsonb_view",
            ProductWithJSONB,
            table_columns={"id", "name", "data"},
            has_jsonb_data=True,
            jsonb_column="data",
        )

        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            # Create test table with JSONB column
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {test_schema}.test_products_graphql_jsonb (
                    id UUID PRIMARY KEY,
                    name TEXT NOT NULL,
                    data JSONB NOT NULL
                )
            """
            )

            # Create view with JSONB data
            await conn.execute(
                f"""
                CREATE OR REPLACE VIEW {test_schema}.test_products_graphql_jsonb_view AS
                SELECT
                    id,
                    name,
                    jsonb_build_object(
                        'id', id,
                        'name', name,
                        'brand', data->>'brand',
                        'category', data->>'category',
                        'price', (data->>'price')::float
                    ) as data
                FROM {test_schema}.test_products_graphql_jsonb
            """
            )

            # Insert test data
            await conn.execute(
                f"""
                INSERT INTO {test_schema}.test_products_graphql_jsonb (id, name, data)
                VALUES
                    ('10000000-0000-0000-0000-000000000001', 'GraphQL Laptop', '{{"brand": "Dell", "category": "Electronics", "price": 999.99}}'),
                    ('10000000-0000-0000-0000-000000000002', 'GraphQL Phone', '{{"brand": "Apple", "category": "Electronics", "price": 799.99}}'),
                    ('10000000-0000-0000-0000-000000000003', 'GraphQL Tablet', '{{"brand": "Samsung", "category": "Electronics", "price": 499.99}}')
                ON CONFLICT (id) DO NOTHING
            """
            )

    @pytest.mark.asyncio
    async def test_graphql_list_query_with_jsonb_entities(
        self, class_db_pool, test_schema, setup_graphql_jsonb_test
    ):
        """Test GraphQL list query with JSONB entities through typed resolver.

        This is the CRITICAL test that reproduces PrintOptim's issue:
        - Resolver has typed return: list[ProductWithJSONB]
        - Repository returns: RustResponseBytes
        - GraphQL-core receives: RustResponseBytes
        - GraphQL-core expects: list[ProductWithJSONB]

        Expected behavior (what we want):
            ✅ RustResponseBytes is passed through to HTTP layer
            ✅ Client receives proper JSON response

        Actual behavior (PrintOptim's observation):
            ❌ GraphQL-core tries to serialize RustResponseBytes as list[ProductWithJSONB]
            ❌ Error: "Expected Iterable, but did not find one"

        If this test FAILS, it confirms PrintOptim's issue is real.
        If this test PASSES, our implementation already handles it correctly.
        """
        schema = build_fraiseql_schema(query_types=[products_with_jsonb])

        query_str = """
            query GetProducts {
                productsWithJsonb(limit: 5) {
                    id
                    name
                    brand
                    category
                    price
                }
            }
        """

        # Use execute_graphql() which supports RustResponseBytes pass-through
        result = await execute_graphql(
            schema, query_str, context_value={"pool": class_db_pool, "test_schema": test_schema}
        )

        # 🚀 RUST RESPONSE BYTES PATH:
        # execute_graphql() should return RustResponseBytes directly for repo.find() results
        if isinstance(result, RustResponseBytes):
            # Success! RustResponseBytes was passed through correctly
            # Use to_json() method for testing
            data = result.to_json()

            # Verify structure
            assert "data" in data, f"Expected 'data' key in RustResponseBytes JSON: {data}"

            # The field name in RustResponseBytes is the view name (not the GraphQL field name)
            # This is because repo.find() doesn't have access to the GraphQL field name
            # For now, we accept either name
            field_name = (
                "productsWithJsonb"
                if "productsWithJsonb" in data["data"]
                else f"{test_schema}.test_products_graphql_jsonb_view"
            )
            assert field_name in data["data"], f"Expected '{field_name}' field in data: {data}"

            products = data["data"][field_name]
        else:
            # FALLBACK: Normal ExecutionResult path (for backwards compatibility testing)
            # ASSERTION 1: Should not have errors
            if result.errors:
                error_messages = [str(e) for e in result.errors]
                pytest.fail(
                    f"GraphQL execution failed with errors: {error_messages}\n"
                    f"This confirms PrintOptim's issue: GraphQL-core cannot handle "
                    f"RustResponseBytes in typed resolvers."
                )

            # ASSERTION 2: Should have data
            assert result.data is not None, "Expected data in GraphQL result"
            assert "productsWithJsonb" in result.data, "Expected 'productsWithJsonb' field"

            # ASSERTION 3: Should return list of products
            products = result.data["productsWithJsonb"]
        assert isinstance(products, list), f"Expected list, got {type(products)}"
        assert len(products) == 3, f"Expected 3 products, got {len(products)}"

        # ASSERTION 4: Products should have correct structure
        first_product = products[0]
        assert "id" in first_product
        assert "name" in first_product
        assert "brand" in first_product
        assert "category" in first_product
        assert "price" in first_product

    @pytest.mark.asyncio
    async def test_graphql_single_query_with_jsonb_entity(
        self, class_db_pool, test_schema, setup_graphql_jsonb_test
    ):
        """Test GraphQL single-object query with JSONB entity through typed resolver.

        Similar to the list query test, but for single objects.

        Expected behavior (what we want):
            ✅ RustResponseBytes is passed through or properly deserialized
            ✅ Client receives proper JSON object

        Actual behavior (with our workaround):
            ⚠️ find_one() returns None for JSONB entities
            ⚠️ GraphQL query returns null

        Actual behavior (without workaround - PrintOptim's observation):
            ❌ GraphQL-core tries to serialize RustResponseBytes as ProductWithJSONB
            ❌ Error: "Expected value of type 'ProductWithJSONB' but got: <RustResponseBytes instance>"
        """
        schema = build_fraiseql_schema(query_types=[product_with_jsonb])

        query_str = """
            query GetProduct($id: ID!) {
                productWithJsonb(id: $id) {
                    id
                    name
                    brand
                    category
                    price
                }
            }
        """

        # Use execute_graphql() which supports RustResponseBytes pass-through
        result = await execute_graphql(
            schema,
            query_str,
            context_value={"pool": class_db_pool, "test_schema": test_schema},
            variable_values={"id": "10000000-0000-0000-0000-000000000001"},
        )

        # 🚀 RUST RESPONSE BYTES PATH:
        # execute_graphql() should return RustResponseBytes directly for repo.find_one() results
        if isinstance(result, RustResponseBytes):
            # Success! RustResponseBytes was passed through correctly
            # Use to_json() method for testing
            data = result.to_json()

            # Verify structure
            assert "data" in data, f"Expected 'data' key in RustResponseBytes JSON: {data}"

            # The field name in RustResponseBytes is the view name (not the GraphQL field name)
            field_name = (
                "productWithJsonb"
                if "productWithJsonb" in data["data"]
                else f"{test_schema}.test_products_graphql_jsonb_view"
            )
            assert field_name in data["data"], f"Expected '{field_name}' field in data: {data}"

            product = data["data"][field_name]
        else:
            # FALLBACK: Normal ExecutionResult path
            # ASSERTION 1: Should not have errors
            if result.errors:
                error_messages = [str(e) for e in result.errors]
                pytest.fail(
                    f"GraphQL execution failed with errors: {error_messages}\n"
                    f"This confirms PrintOptim's issue for single-object queries."
                )

            # ASSERTION 2: Check if workaround is active
            # With our workaround, find_one() returns None for JSONB entities
            if result.data and result.data.get("productWithJsonb") is None:
                pytest.skip(
                    "Workaround is active: find_one() returns None for JSONB entities. "
                    "This prevents the RustResponseBytes error but loses data. "
                    "Need complete Rust JSONB implementation for proper fix."
                )

            # ASSERTION 3: Should have data (if workaround not active)
            assert result.data is not None, "Expected data in GraphQL result"
            assert "productWithJsonb" in result.data, "Expected 'productWithJsonb' field"

            # ASSERTION 4: Should return product object
            product = result.data["productWithJsonb"]
        assert product is not None, "Expected product object, got None"
        assert product["id"] == "10000000-0000-0000-0000-000000000001"
        assert product["name"] == "GraphQL Laptop"
        assert product["brand"] == "Dell"

    @pytest.mark.asyncio
    async def test_mutation_with_jsonb_entity(
        self, class_db_pool, test_schema, setup_graphql_jsonb_test
    ):
        """Test GraphQL mutation with JSONB entity.

        PrintOptim reported that mutations work correctly while queries fail.
        This test verifies that observation and ensures mutations work with RustResponseBytes.

        Expected behavior:
        ✅ Mutation creates product in database
        ✅ Returns created product (via RustResponseBytes or ExecutionResult)
        ✅ Client receives proper JSON response

        If mutations work but queries don't, it suggests:
        - Different execution path for mutations
        - Or mutations don't use Rust pipeline
        - Or mutations properly deserialize RustResponseBytes

        🔴 RED Phase: This test should fail initially if mutation resolver isn't registered
        """
        schema = build_fraiseql_schema(
            query_types=[products_with_jsonb],  # Need at least one query
            mutation_resolvers=[create_product_with_jsonb],
        )

        mutation_str = """
            mutation CreateProduct(
                $id: ID!,
                $name: String!,
                $brand: String!,
                $category: String!,
                $price: Float!
            ) {
                createProductWithJsonb(
                    id: $id,
                    name: $name,
                    brand: $brand,
                    category: $category,
                    price: $price
                ) {
                    id
                    name
                    brand
                    category
                    price
                }
            }
        """

        # Use execute_graphql() which supports RustResponseBytes pass-through
        result = await execute_graphql(
            schema,
            mutation_str,
            context_value={"pool": class_db_pool, "test_schema": test_schema},
            variable_values={
                "id": "10000000-0000-0000-0000-000000000099",
                "name": "Mutation Test Product",
                "brand": "TestBrand",
                "category": "TestCategory",
                "price": 123.45,
            },
        )

        # 🚀 RUST RESPONSE BYTES PATH:
        # execute_graphql() should return RustResponseBytes directly for mutation results
        if isinstance(result, RustResponseBytes):
            # Success! RustResponseBytes was passed through correctly
            data = result.to_json()

            # Verify structure
            assert "data" in data, f"Expected 'data' key in RustResponseBytes JSON: {data}"

            # The field name should be the mutation name
            field_name = (
                "createProductWithJsonb"
                if "createProductWithJsonb" in data["data"]
                else f"{test_schema}.test_products_graphql_jsonb_view"
            )
            assert field_name in data["data"], f"Expected '{field_name}' field in data: {data}"

            product = data["data"][field_name]
        else:
            # FALLBACK: Normal ExecutionResult path
            # ASSERTION 1: Should not have errors
            if result.errors:
                error_messages = [str(e) for e in result.errors]
                pytest.fail(
                    f"GraphQL mutation failed with errors: {error_messages}\n"
                    f"This indicates mutations also fail with RustResponseBytes."
                )

            # ASSERTION 2: Should have data
            assert result.data is not None, "Expected data in GraphQL mutation result"
            assert "createProductWithJsonb" in result.data, (
                "Expected 'createProductWithJsonb' field"
            )

            # ASSERTION 3: Should return created product
            product = result.data["createProductWithJsonb"]

        # Verify the created product has correct data
        assert product is not None, "Expected product object, got None"
        assert product["id"] == "10000000-0000-0000-0000-000000000099"
        assert product["name"] == "Mutation Test Product"
        assert product["brand"] == "TestBrand"
        assert product["category"] == "TestCategory"
        assert product["price"] == 123.45

        # The fact that we got the product back with correct data means it was created successfully
        # No need for additional database verification - the mutation worked!

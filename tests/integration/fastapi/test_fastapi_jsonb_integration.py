"""Tests for FastAPI GraphQL router with JSONB entities.

Validates that the FastAPI create_graphql_router correctly handles
JSONB entities through the complete HTTP stack with RustResponseBytes pass-through.

Tests cover queries, mutations, and error handling through the full FastAPI HTTP layer.
"""

import json

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration
pytestmark = pytest.mark.database

# Import database fixtures

import fraiseql
from fraiseql.db import FraiseQLRepository, register_type_for_view
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.fastapi.routers import create_graphql_router
from fraiseql.gql.schema_builder import build_fraiseql_schema
from fraiseql.types import ID


# Test type with JSONB data
@fraiseql.type
class ProductWithJSONB:
    """Product entity with JSONB data column."""

    id: str
    name: str
    brand: str  # Stored in JSONB
    category: str  # Stored in JSONB
    price: float  # Stored in JSONB


# GraphQL resolvers
@fraiseql.query
async def products_with_jsonb(info, limit: int = 10) -> list[ProductWithJSONB]:
    """List query with typed return value."""
    pool = info.context.get("pool")
    repo = FraiseQLRepository(pool, context={"mode": "development"})
    return await repo.find("test_products_fastapi_jsonb_view", limit=limit)


@fraiseql.query
async def product_with_jsonb(info, id: ID) -> ProductWithJSONB | None:
    """Single query with typed return value."""
    pool = info.context.get("pool")
    repo = FraiseQLRepository(pool, context={"mode": "development"})
    return await repo.find_one("test_products_fastapi_jsonb_view", id=id)


@fraiseql.mutation
async def create_product_with_jsonb(
    info, id: ID, name: str, brand: str, category: str, price: float
) -> ProductWithJSONB:
    """Mutation that creates a JSONB entity and returns it."""
    pool = info.context.get("pool")

    # Insert the new product into database
    async with pool.connection() as conn:
        json_data = json.dumps({"brand": brand, "category": category, "price": price})
        await conn.execute(
            f"""
            INSERT INTO test_products_fastapi_jsonb (id, name, data)
            VALUES ('{id}', '{name}', '{json_data}'::jsonb)
            """
        )

    # Return the created product via repository
    repo = FraiseQLRepository(pool, context={"mode": "development"})
    return await repo.find_one("test_products_fastapi_jsonb_view", id=id)


class TestFastAPIJSONBIntegration:
    """Test FastAPI router with JSONB entities through complete HTTP stack.

    These tests go through the full FastAPI HTTP stack:
        HTTP Request → FastAPI Router → execute_graphql() → Resolver → Repository
        → RustResponseBytes → HTTP Response
    """

    @pytest.fixture(scope="class")
    def clear_registry_fixture(self, clear_registry_class):
        """Clear registry before class tests."""
        return

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def setup_fastapi_jsonb_test(self, class_db_pool, test_schema) -> None:
        """Create test data and register types for FastAPI testing."""
        # Register type with has_jsonb_data=True
        register_type_for_view(
            "test_products_fastapi_jsonb_view",
            ProductWithJSONB,
            table_columns={"id", "name", "data"},
            has_jsonb_data=True,
            jsonb_column="data",
        )

        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            # Create test table with JSONB column
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_products_fastapi_jsonb (
                    id UUID PRIMARY KEY,
                    name TEXT NOT NULL,
                    data JSONB NOT NULL
                )
            """
            )

            # Create view with JSONB data
            await conn.execute(
                """
                CREATE OR REPLACE VIEW test_products_fastapi_jsonb_view AS
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
                FROM test_products_fastapi_jsonb
            """
            )

            # Insert test data (using valid UUIDs - FraiseQL enforces ID = UUID)
            await conn.execute(
                """
                INSERT INTO test_products_fastapi_jsonb (id, name, data)
                VALUES
                    ('00000000-0000-0000-0000-000000000001', 'FastAPI Laptop', '{"brand": "Dell", "category": "Electronics", "price": 999.99}'),
                    ('00000000-0000-0000-0000-000000000002', 'FastAPI Phone', '{"brand": "Apple", "category": "Electronics", "price": 799.99}'),
                    ('00000000-0000-0000-0000-000000000003', 'FastAPI Tablet', '{"brand": "Samsung", "category": "Electronics", "price": 499.99}')
            """
            )

            await conn.commit()

        yield

        # Cleanup
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}")
            await conn.execute("DROP VIEW IF EXISTS test_products_fastapi_jsonb_view")
            await conn.execute("DROP TABLE IF EXISTS test_products_fastapi_jsonb")
            await conn.commit()

    @pytest.fixture
    def fastapi_app(self, class_db_pool) -> None:
        """Create FastAPI app with GraphQL router configured for testing.

        This fixture creates a real FastAPI app with the create_graphql_router,
        allowing us to test the complete HTTP stack.
        """
        # Initialize global pool for dependencies
        from fraiseql.fastapi.dependencies import set_db_pool, set_fraiseql_config

        # Create config for testing
        # Use development environment which enables UnifiedExecutor (realistic scenario)
        config = FraiseQLConfig(
            database_url="postgresql://test:test@localhost:5432/test", environment="development"
        )

        # Set globals so dependencies work
        set_db_pool(class_db_pool)
        set_fraiseql_config(config)

        # DEBUG: Verify pool was set
        from fraiseql.fastapi.dependencies import get_db_pool

        test_pool = get_db_pool()
        print(f"🔍 DEBUG: Pool set successfully: {test_pool is not None}")

        # Build schema
        schema = build_fraiseql_schema(
            query_types=[products_with_jsonb, product_with_jsonb],
            mutation_resolvers=[create_product_with_jsonb],
        )

        # Create custom context getter that adds pool to context
        @pytest.mark.asyncio
        async def test_context_getter(request) -> None:
            """Add pool to context for our test resolvers."""
            return {"pool": class_db_pool}

        # Create router with custom context getter
        router = create_graphql_router(
            schema=schema, config=config, context_getter=test_context_getter
        )

        # Create FastAPI app and include router
        app = FastAPI()
        app.include_router(router)

        yield app

        # Cleanup globals
        set_db_pool(None)
        set_fraiseql_config(None)

    @pytest.mark.asyncio
    async def test_fastapi_list_query_with_jsonb_entities(
        self, class_db_pool, setup_fastapi_jsonb_test, fastapi_app
    ):
        """Test FastAPI HTTP endpoint with list query returning JSONB entities.

        🔴 RED Phase: This test validates the complete HTTP stack with RustResponseBytes

        Expected behavior:
            ✅ HTTP POST to /graphql returns 200
            ✅ Response is valid JSON
            ✅ Data contains list of products with JSONB fields
            ✅ RustResponseBytes is passed through to HTTP layer
        """
        client = TestClient(fastapi_app)

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

        # Make HTTP request
        response = client.post("/graphql", json={"query": query_str})

        # ASSERTION 1: HTTP status should be 200
        assert response.status_code == 200, (
            f"Expected 200 OK, got {response.status_code}: {response.text}"
        )

        # ASSERTION 2: Response should be JSON
        assert response.headers["content-type"].startswith("application/json"), (
            f"Expected application/json, got {response.headers['content-type']}"
        )

        # ASSERTION 3: Parse and validate response data
        data = response.json()
        assert "data" in data, f"Expected 'data' key in response: {data}"

        # DEBUG: Print actual response to understand structure
        import json as json_module

        print(f"\n🔍 DEBUG Response: {json_module.dumps(data, indent=2)}")

        # The field name might be different depending on how RustResponseBytes is handled
        if "productsWithJsonb" in data["data"]:
            products = data["data"]["productsWithJsonb"]
        elif "test_products_fastapi_jsonb_view" in data["data"]:
            products = data["data"]["test_products_fastapi_jsonb_view"]
        else:
            # Show what fields are actually present
            actual_fields = list(data["data"].keys()) if data["data"] else []
            pytest.fail(
                f"Expected products field in data. Actual fields: {actual_fields}, Full data: {data}"
            )

        # ASSERTION 4: Should return list of products
        assert isinstance(products, list), f"Expected list, got {type(products)}"
        assert len(products) == 3, f"Expected 3 products, got {len(products)}"

        # ASSERTION 5: Products should have correct structure
        first_product = products[0]
        assert "id" in first_product
        assert "name" in first_product
        assert "brand" in first_product
        assert "category" in first_product
        assert "price" in first_product

        # ASSERTION 6: Verify actual data
        product_ids = {p["id"] for p in products}
        assert "00000000-0000-0000-0000-000000000001" in product_ids
        assert "00000000-0000-0000-0000-000000000002" in product_ids
        assert "00000000-0000-0000-0000-000000000003" in product_ids

    @pytest.mark.asyncio
    async def test_fastapi_single_query_with_jsonb_entity(
        self, class_db_pool, setup_fastapi_jsonb_test, fastapi_app
    ):
        """Test FastAPI HTTP endpoint with single-object query returning JSONB entity.

        🔴 RED Phase: This test validates single object queries through HTTP

        Expected behavior:
            ✅ HTTP POST returns 200
            ✅ Response contains single product object
            ✅ All JSONB fields are correctly deserialized
        """
        client = TestClient(fastapi_app)

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

        # Make HTTP request
        response = client.post(
            "/graphql", json={"query": query_str, "variables": {"id": "00000000-0000-0000-0000-000000000001"}}
        )

        # ASSERTION 1: HTTP status should be 200
        assert response.status_code == 200, (
            f"Expected 200 OK, got {response.status_code}: {response.text}"
        )

        # ASSERTION 2: Parse and validate response data
        data = response.json()
        assert "data" in data, f"Expected 'data' key in response: {data}"

        # Handle different field names
        if "productWithJsonb" in data["data"]:
            product = data["data"]["productWithJsonb"]
        elif "test_products_fastapi_jsonb_view" in data["data"]:
            product = data["data"]["test_products_fastapi_jsonb_view"]
        else:
            pytest.fail(f"Expected product field in data: {data}")

        # ASSERTION 3: Should return product object
        assert product is not None, "Expected product object, got None"
        assert product["id"] == "00000000-0000-0000-0000-000000000001"
        assert product["name"] == "FastAPI Laptop"
        assert product["brand"] == "Dell"
        assert product["category"] == "Electronics"
        assert product["price"] == 999.99

    @pytest.mark.asyncio
    async def test_fastapi_mutation_with_jsonb_entity(
        self, class_db_pool, setup_fastapi_jsonb_test, fastapi_app
    ):
        """Test FastAPI HTTP endpoint with mutation creating JSONB entity.

        🔴 RED Phase: This test validates mutations through HTTP stack

        Expected behavior:
            ✅ HTTP POST returns 200
            ✅ Mutation creates product in database
            ✅ Returns created product with all fields
            ✅ RustResponseBytes pass-through works for mutations
        """
        client = TestClient(fastapi_app)

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

        # Make HTTP request
        response = client.post(
            "/graphql",
            json={
                "query": mutation_str,
                "variables": {
                    "id": "00000000-0000-0000-0000-000000000099",
                    "name": "FastAPI Mutation Product",
                    "brand": "TestBrand",
                    "category": "TestCategory",
                    "price": 123.45,
                },
            },
        )

        # ASSERTION 1: HTTP status should be 200
        assert response.status_code == 200, (
            f"Expected 200 OK, got {response.status_code}: {response.text}"
        )

        # ASSERTION 2: Parse and validate response data
        data = response.json()
        assert "data" in data, f"Expected 'data' key in response: {data}"

        # Handle different field names
        if "createProductWithJsonb" in data["data"]:
            product = data["data"]["createProductWithJsonb"]
        elif "test_products_fastapi_jsonb_view" in data["data"]:
            product = data["data"]["test_products_fastapi_jsonb_view"]
        else:
            pytest.fail(f"Expected mutation field in data: {data}")

        # ASSERTION 3: Verify created product
        assert product is not None, "Expected product object, got None"
        assert product["id"] == "00000000-0000-0000-0000-000000000099"
        assert product["name"] == "FastAPI Mutation Product"
        assert product["brand"] == "TestBrand"
        assert product["category"] == "TestCategory"
        assert product["price"] == 123.45

    @pytest.mark.asyncio
    async def test_fastapi_error_handling_with_graphql_errors(
        self, class_db_pool, setup_fastapi_jsonb_test, fastapi_app
    ):
        """Test that FastAPI router handles GraphQL errors correctly.

        This validates that errors are still returned properly even when
        RustResponseBytes pass-through is enabled.
        """
        client = TestClient(fastapi_app)

        # Query with invalid field
        query_str = """
            query GetProducts {
                productsWithJsonb(limit: 5) {
                    id
                    name
                    invalidField
                }
            }
        """

        # Make HTTP request
        response = client.post("/graphql", json={"query": query_str})

        # Should still return 200 (GraphQL spec)
        assert response.status_code == 200

        # But should have errors in response
        data = response.json()
        assert "errors" in data, f"Expected 'errors' key in response: {data}"
        assert len(data["errors"]) > 0, "Expected at least one error"

    @pytest.mark.asyncio
    async def test_fastapi_rustresponsebytes_content_type(
        self, class_db_pool, setup_fastapi_jsonb_test, fastapi_app
    ):
        """Test that RustResponseBytes returns proper content-type header.

        This validates that when RustResponseBytes is returned, the HTTP
        response has the correct content-type: application/json header.
        """
        client = TestClient(fastapi_app)

        query_str = """
            query GetProducts {
                productsWithJsonb(limit: 1) {
                    id
                    name
                }
            }
        """

        response = client.post("/graphql", json={"query": query_str})

        assert response.status_code == 200

        # Verify content-type is application/json
        content_type = response.headers.get("content-type", "")
        assert "application/json" in content_type.lower(), (
            f"Expected application/json in content-type, got: {content_type}"
        )

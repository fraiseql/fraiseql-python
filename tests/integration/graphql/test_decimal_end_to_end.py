"""``Decimal`` through the HTTP stack and Postgres keeps every digit (issue #575).

A ``price`` of ``12.345678901234567890123`` has more significant digits than a
float holds. These tests check what a client receives for it from a query, that
where filters compare it as a number, and what a mutation's SQL function gets
for a ``Decimal`` input field.

In HTTP mode the Rust pipeline builds the response. It parses each JSONB row with
``serde_json`` and its ``arbitrary_precision`` feature, so a JSONB number reaches
the client with the digits Postgres wrote, as a number. A view that emits the
value as text (``price::text``) gets it as a string.
"""

import json
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.sql import create_graphql_where_input

pytestmark = pytest.mark.integration

_EXACT = "12.345678901234567890123"
# Wider than an f64 (a Python int), and beyond its range: -1e400.
_BIG = "123456789012345678901234567890"
_HUGE = "-1" + "0" * 400


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def decimal_tables(class_db_pool, test_schema) -> None:
    async with class_db_pool.connection() as conn:
        await conn.execute(
            f"""
            CREATE TYPE {test_schema}.mutation_response AS (
                status text, message text, entity_id text, entity_type text,
                entity jsonb, updated_fields text[], cascade jsonb, metadata jsonb
            );
            CREATE TABLE {test_schema}.tb_product (id int PRIMARY KEY, price numeric NOT NULL);
            CREATE VIEW {test_schema}.v_product AS
                SELECT id, jsonb_build_object('id', id, 'price', price) AS data
                FROM {test_schema}.tb_product;
            CREATE VIEW {test_schema}.v_product_text AS
                SELECT id, jsonb_build_object('id', id, 'price', price::text) AS data
                FROM {test_schema}.tb_product;
            INSERT INTO {test_schema}.tb_product VALUES (1, {_EXACT}), (2, 9.99), (3, 100);

            CREATE TABLE {test_schema}.tb_reading (id int PRIMARY KEY, value numeric NOT NULL);
            CREATE VIEW {test_schema}.v_reading AS
                SELECT id, jsonb_build_object('id', id, 'value', value) AS data
                FROM {test_schema}.tb_reading;
            INSERT INTO {test_schema}.tb_reading VALUES (1, {_BIG}), (2, -1e400), (3, 7), (4, 0.5);

            CREATE FUNCTION {test_schema}.set_price(input jsonb)
            RETURNS {test_schema}.mutation_response AS $$
                UPDATE {test_schema}.tb_product SET price = (input->>'price')::numeric
                WHERE id = (input->>'id')::int;
                SELECT ROW('updated', 'ok', input->>'id', 'Product',
                    (SELECT data FROM {test_schema}.v_product WHERE id = (input->>'id')::int),
                    NULL, NULL, jsonb_build_object('input', input))::{test_schema}.mutation_response;
            $$ LANGUAGE sql;
            """
        )
        await conn.commit()


@pytest.fixture
def client(class_db_pool, test_schema, decimal_tables, clear_registry) -> TestClient:
    from fraiseql.db import FraiseQLRepository
    from fraiseql.fastapi.dependencies import set_db_pool

    @fraiseql.type(sql_source=f"{test_schema}.v_product", jsonb_column="data")
    class Product:
        id: int
        price: Decimal

    @fraiseql.type(sql_source=f"{test_schema}.v_product_text", jsonb_column="data")
    class ProductAsText:
        id: int
        price: Decimal

    @fraiseql.type(sql_source=f"{test_schema}.v_reading", jsonb_column="data")
    class Reading:
        id: int
        value: Decimal

    product_where = create_graphql_where_input(Product)
    product_as_text_where = create_graphql_where_input(ProductAsText)

    @fraiseql.query
    async def products(info, where: product_where | None = None) -> list[Product]:
        db = info.context["db"]
        return await db.find(f"{test_schema}.v_product", "products", info, where=where)

    @fraiseql.query
    async def products_as_text(
        info, where: product_as_text_where | None = None
    ) -> list[ProductAsText]:
        db = info.context["db"]
        return await db.find(f"{test_schema}.v_product_text", "productsAsText", info, where=where)

    @fraiseql.query
    async def readings(info) -> list[Reading]:
        db = info.context["db"]
        return await db.find(f"{test_schema}.v_reading", "readings", info)

    @fraiseql.input
    class SetPriceInput:
        id: int
        price: Decimal

    @fraiseql.success
    class SetPriceSuccess:
        product: Product

    @fraiseql.error
    class SetPriceError:
        message: str

    @fraiseql.mutation(schema=test_schema)
    class SetPrice:
        input: SetPriceInput
        success: SetPriceSuccess
        error: SetPriceError

    set_db_pool(class_db_pool)

    async def context_getter(request, user=None):
        return {"db": FraiseQLRepository(class_db_pool), "user": user}

    app = create_fraiseql_app(
        database_url="postgresql://test/test",
        types=[Product, ProductAsText, Reading],
        queries=[products, products_as_text, readings],
        mutations=[SetPrice],
        production=False,
        context_getter=context_getter,
    )
    return TestClient(app)


def _post(client: TestClient, query: str) -> dict:
    response = client.post("/graphql", json={"query": query})
    assert response.status_code == 200, response.text
    body = json.loads(response.text, parse_float=Decimal)  # response.json() makes floats
    assert "errors" not in body, body["errors"]
    return body["data"]


@pytest.mark.usefixtures("test_schema")
class TestDecimalEndToEnd:
    def test_text_in_the_view_reaches_the_client_exactly(self, client: TestClient) -> None:
        data = _post(client, "{ productsAsText { id price } }")

        prices = {row["id"]: row["price"] for row in data["productsAsText"]}
        assert prices[1] == _EXACT

    def test_number_in_the_view_reaches_the_client_exactly(self, client: TestClient) -> None:
        data = _post(client, "{ products { id price } }")

        prices = {row["id"]: row["price"] for row in data["products"]}
        assert prices[1] == Decimal(_EXACT)

    def test_numbers_outside_a_float_reach_the_client_exactly(self, client: TestClient) -> None:
        data = _post(client, "{ readings { id value } }")

        values = {row["id"]: row["value"] for row in data["readings"]}
        assert values == {1: int(_BIG), 2: int(_HUGE), 3: 7, 4: Decimal("0.5")}

    @pytest.mark.parametrize("field", ["products", "productsAsText"])
    def test_where_compares_as_numbers(self, client: TestClient, field: str) -> None:
        # As text, "9.99" > "10"; as numbers, it isn't.
        data = _post(client, f'{{ {field}(where: {{price: {{gt: "10"}}}}) {{ id }} }}')

        assert sorted(row["id"] for row in data[field]) == [1, 3]

    @pytest.mark.parametrize("field", ["products", "productsAsText"])
    def test_where_eq_matches_the_exact_value(self, client: TestClient, field: str) -> None:
        data = _post(client, f'{{ {field}(where: {{price: {{eq: "{_EXACT}"}}}}) {{ id }} }}')

        assert [row["id"] for row in data[field]] == [1]

    def test_mutation_input_reaches_sql_with_every_digit(self, client: TestClient) -> None:
        exact = "1.000000000000000000001"
        _post(
            client,
            f'mutation {{ setPrice(input: {{id: 2, price: "{exact}"}}) {{'
            " ... on SetPriceSuccess { product { id } } } }",
        )

        stored = _post(client, "{ productsAsText { id price } }")
        assert {row["id"]: row["price"] for row in stored["productsAsText"]}[2] == exact

    def test_mutation_entity_reaches_the_client_exactly(self, client: TestClient) -> None:
        exact = "1.000000000000000000002"
        data = _post(
            client,
            f'mutation {{ setPrice(input: {{id: 3, price: "{exact}"}}) {{'
            " ... on SetPriceSuccess { product { id price } } } }",
        )

        assert data["setPrice"]["product"]["price"] == Decimal(exact)

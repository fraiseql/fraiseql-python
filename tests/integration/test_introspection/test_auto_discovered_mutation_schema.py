"""A schema builds from auto-discovered mutations.

AutoDiscovery generates each mutation's input class from the database. The
generated class has to be a FraiseQL input type, or the schema build rejects it.
"""

from typing import Any

import pytest
import pytest_asyncio
from graphql import GraphQLInputObjectType, get_named_type

import fraiseql
from fraiseql.gql.schema_builder import build_fraiseql_schema
from fraiseql.introspection import AutoDiscovery

pytestmark = [pytest.mark.integration, pytest.mark.database]


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def discovered_mutations(class_db_pool, test_schema) -> None:
    """Two functions, one per way an input class is generated.

    fn_create_item: plain p_ parameters (legacy). fn_update_item: an
    input_payload JSONB parameter described by a composite type (SpecQL).
    """
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute("""
            CREATE VIEW v_create_item_success AS
            SELECT '{"id": "00000000-0000-0000-0000-000000000000", "message": "ok"}'::jsonb
                AS data;
            COMMENT ON VIEW v_create_item_success IS '@fraiseql:type';

            CREATE VIEW v_create_item_error AS
            SELECT '{"code": "CREATE_ERROR", "message": "failed"}'::jsonb AS data;
            COMMENT ON VIEW v_create_item_error IS '@fraiseql:type';

            CREATE FUNCTION fn_create_item(p_name TEXT, p_email TEXT) RETURNS JSONB AS $$
                SELECT jsonb_build_object('name', p_name, 'email', p_email);
            $$ LANGUAGE sql;
            COMMENT ON FUNCTION fn_create_item(TEXT, TEXT) IS
            '@fraiseql:mutation
            name: createItem
            success_type: CreateItemSuccess
            error_type: CreateItemError';

            CREATE TYPE type_fn_update_item_input AS (name TEXT, email TEXT);
            COMMENT ON COLUMN type_fn_update_item_input.name IS 'The item name';
            CREATE FUNCTION fn_update_item(input_payload JSONB) RETURNS JSONB AS $$
                SELECT input_payload;
            $$ LANGUAGE sql;
            COMMENT ON FUNCTION fn_update_item(JSONB) IS
            '@fraiseql:mutation
            name: updateItem
            success_type: CreateItemSuccess
            error_type: CreateItemError';
        """)
        await conn.commit()


async def _build_input(class_db_pool: Any, test_schema: str, function: str) -> Any:
    """Discover one function, build the schema, and return its mutation's input type."""
    result = await AutoDiscovery(class_db_pool).discover_all(
        function_pattern=function, schemas=[test_schema]
    )
    mutation = function.removeprefix("fn_").title().replace("_", "")
    mutations = [m for m in result["mutations"] if m.__name__ == mutation]
    assert mutations, f"{mutation} was not discovered: {result['mutations']}"

    @fraiseql.query
    async def ping(info: Any) -> str:
        return "ok"

    schema = build_fraiseql_schema(
        query_types=[*result["types"], ping], mutation_resolvers=mutations
    )

    assert schema.mutation_type is not None
    field = schema.mutation_type.fields[f"fn{mutation}"]
    return get_named_type(field.args["input"].type)


@pytest.mark.usefixtures("clear_registry", "discovered_mutations")
class TestAutoDiscoveredMutationSchema:
    @pytest.mark.asyncio
    async def test_parameter_based_input(self, class_db_pool, test_schema) -> None:
        input_type = await _build_input(class_db_pool, test_schema, "fn_create_item")

        assert isinstance(input_type, GraphQLInputObjectType)
        assert set(input_type.fields) == {"name", "email"}

    @pytest.mark.asyncio
    async def test_composite_type_input(self, class_db_pool, test_schema) -> None:
        input_type = await _build_input(class_db_pool, test_schema, "fn_update_item")

        assert isinstance(input_type, GraphQLInputObjectType)
        assert set(input_type.fields) == {"name", "email"}
        assert input_type.fields["name"].description == "The item name"

"""execute_function returns what the function returns.

``SELECT * FROM fn(...)`` puts a function returning ``jsonb`` in one column named
after the function, so the row used to be ``{"fn_name": {...}}``. A JSON object
returned that way is now the result itself. Composite results (OUT parameters,
``RETURNS TABLE``, ``mutation_response``) are rows of their own columns, as before.
"""

import uuid
import warnings

import pytest
import pytest_asyncio

from fraiseql.db import FraiseQLRepository

pytestmark = [pytest.mark.integration, pytest.mark.database]


@pytest_asyncio.fixture(loop_scope="class", scope="class")
async def schema(class_db_pool):
    name = f"fn_result_{uuid.uuid4().hex[:8]}"
    async with class_db_pool.connection() as conn:
        await conn.execute(f"CREATE SCHEMA {name}")
        await conn.execute(f"""
            CREATE FUNCTION {name}.fn_create_note(input jsonb) RETURNS jsonb AS $$
                SELECT jsonb_build_object('success', true, 'title', input->>'title')
            $$ LANGUAGE sql;
            CREATE FUNCTION {name}.fn_list(input jsonb) RETURNS jsonb AS $$
                SELECT '[1, 2]'::jsonb
            $$ LANGUAGE sql;
            CREATE FUNCTION {name}.fn_out(input jsonb, OUT success boolean, OUT id int) AS $$
                SELECT true, 7
            $$ LANGUAGE sql;
            CREATE FUNCTION {name}.fn_with_user(p_user text, input jsonb) RETURNS jsonb AS $$
                SELECT input || jsonb_build_object('user', p_user)
            $$ LANGUAGE sql;
        """)
        await conn.commit()
    yield name
    async with class_db_pool.connection() as conn:
        await conn.execute(f"DROP SCHEMA {name} CASCADE")
        await conn.commit()


@pytest.mark.asyncio(loop_scope="class")
class TestExecuteFunctionResult:
    async def test_a_jsonb_object_is_the_result(self, class_db_pool, schema) -> None:
        repo = FraiseQLRepository(class_db_pool)

        result = await repo.execute_function(f"{schema}.fn_create_note", {"title": "Hi"})

        assert result == {"success": True, "title": "Hi"}
        assert result["success"] is True

    async def test_the_function_name_key_still_answers(self, class_db_pool, schema) -> None:
        repo = FraiseQLRepository(class_db_pool)
        result = await repo.execute_function(f"{schema}.fn_create_note", {"title": "Hi"})

        with pytest.warns(DeprecationWarning, match="fn_create_note"):
            assert result["fn_create_note"]["title"] == "Hi"

    async def test_other_keys_still_raise(self, class_db_pool, schema) -> None:
        repo = FraiseQLRepository(class_db_pool)
        result = await repo.execute_function(f"{schema}.fn_create_note", {"title": "Hi"})

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with pytest.raises(KeyError):
                result["missing"]

    async def test_a_jsonb_array_stays_in_its_column(self, class_db_pool, schema) -> None:
        repo = FraiseQLRepository(class_db_pool)

        assert await repo.execute_function(f"{schema}.fn_list", {}) == {"fn_list": [1, 2]}

    async def test_out_parameters_are_the_row(self, class_db_pool, schema) -> None:
        repo = FraiseQLRepository(class_db_pool)

        assert await repo.execute_function(f"{schema}.fn_out", {}) == {"success": True, "id": 7}

    async def test_with_context(self, class_db_pool, schema) -> None:
        repo = FraiseQLRepository(class_db_pool)

        result = await repo.execute_function_with_context(
            f"{schema}.fn_with_user", ["alice"], {"title": "Hi"}
        )

        assert result == {"title": "Hi", "user": "alice"}

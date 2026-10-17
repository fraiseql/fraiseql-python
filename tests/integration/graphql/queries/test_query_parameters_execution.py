"""Execution tests for auto-wired query parameters.

These tests verify that orderBy, limit, offset parameters actually work
at runtime with real database queries.

DATABASE REQUIRED - tests execute real GraphQL queries.
"""

from dataclasses import dataclass
from typing import Any

import pytest

from fraiseql import query
from fraiseql import type as fraiseql_type
from fraiseql.gql.schema_builder import build_fraiseql_schema
from fraiseql.graphql.execute import execute_graphql

pytestmark = pytest.mark.integration


def parse_graphql_result(result: Any) -> tuple[dict | None, list | None]:
    """Parse GraphQL result, handling both RustResponseBytes and ExecutionResult.

    Returns:
        (data, errors) tuple
    """
    from fraiseql.core.rust_pipeline import RustResponseBytes

    if isinstance(result, RustResponseBytes):
        json_result = result.to_json()
        return json_result.get("data"), json_result.get("errors")
    return result.data, result.errors


class TestOrderByExecution:
    """Test orderBy parameter works at runtime."""

    @pytest.mark.asyncio
    async def test_order_by_ascending(
        self,
        clear_registry,
        db_connection,
        gql_context,
        setup_graphql_table,
        seed_graphql_data,
    ):
        """OrderBy with ASC should sort ascending."""
        await setup_graphql_table("order_asc_users")
        await seed_graphql_data(
            "tb_order_asc_users",
            [
                {"name": "Charlie", "age": 35},
                {"name": "Alice", "age": 30},
                {"name": "Bob", "age": 25},
            ],
        )

        @fraiseql_type(sql_source="v_order_asc_users", jsonb_column="data")
        @dataclass
        class OrderAscUser:
            id: str
            name: str
            age: int

        @query
        async def order_asc_users(info, order_by=None) -> list[OrderAscUser]:
            db = info.context["db"]
            return await db.find("v_order_asc_users", info=info, order_by=order_by)

        schema = build_fraiseql_schema(query_types=[OrderAscUser, order_asc_users])
        result = await execute_graphql(
            schema,
            "{ orderAscUsers(orderBy: [{age: ASC}]) { name age } }",
            context_value=gql_context,
        )

        data, errors = parse_graphql_result(result)
        assert errors is None
        users = data["orderAscUsers"]
        ages = [u["age"] for u in users]
        assert ages == sorted(ages), f"Should be ascending: {ages}"

    @pytest.mark.asyncio
    async def test_order_by_descending(
        self,
        clear_registry,
        db_connection,
        gql_context,
        setup_graphql_table,
        seed_graphql_data,
    ):
        """OrderBy with DESC should sort descending."""
        await setup_graphql_table("order_desc_users")
        await seed_graphql_data(
            "tb_order_desc_users",
            [
                {"name": "Alice", "age": 30},
                {"name": "Bob", "age": 25},
                {"name": "Charlie", "age": 35},
            ],
        )

        @fraiseql_type(sql_source="v_order_desc_users", jsonb_column="data")
        @dataclass
        class OrderDescUser:
            id: str
            name: str
            age: int

        @query
        async def order_desc_users(info, order_by=None) -> list[OrderDescUser]:
            db = info.context["db"]
            return await db.find("v_order_desc_users", info=info, order_by=order_by)

        schema = build_fraiseql_schema(query_types=[OrderDescUser, order_desc_users])
        result = await execute_graphql(
            schema,
            "{ orderDescUsers(orderBy: [{age: DESC}]) { name age } }",
            context_value=gql_context,
        )

        data, errors = parse_graphql_result(result)
        assert errors is None
        users = data["orderDescUsers"]
        ages = [u["age"] for u in users]
        assert ages == sorted(ages, reverse=True), f"Should be descending: {ages}"

    @pytest.mark.asyncio
    async def test_order_by_string_field(
        self,
        clear_registry,
        db_connection,
        gql_context,
        setup_graphql_table,
        seed_graphql_data,
    ):
        """OrderBy should work on string fields."""
        await setup_graphql_table("order_str_users")
        await seed_graphql_data(
            "tb_order_str_users",
            [
                {"name": "Charlie"},
                {"name": "Alice"},
                {"name": "Bob"},
            ],
        )

        @fraiseql_type(sql_source="v_order_str_users", jsonb_column="data")
        @dataclass
        class OrderStrUser:
            id: str
            name: str

        @query
        async def order_str_users(info, order_by=None) -> list[OrderStrUser]:
            db = info.context["db"]
            return await db.find("v_order_str_users", info=info, order_by=order_by)

        schema = build_fraiseql_schema(query_types=[OrderStrUser, order_str_users])
        result = await execute_graphql(
            schema,
            "{ orderStrUsers(orderBy: [{name: ASC}]) { name } }",
            context_value=gql_context,
        )

        data, errors = parse_graphql_result(result)
        assert errors is None
        names = [u["name"] for u in data["orderStrUsers"]]
        assert names == sorted(names)

    @pytest.mark.asyncio
    async def test_order_by_with_where(
        self,
        clear_registry,
        db_connection,
        gql_context,
        setup_graphql_table,
        seed_graphql_data,
    ):
        """OrderBy should work with where clause."""
        await setup_graphql_table("order_where_users")
        await seed_graphql_data(
            "tb_order_where_users",
            [
                {"name": "Alice", "age": 30},
                {"name": "Bob", "age": 25},
                {"name": "Charlie", "age": 35},
                {"name": "Diana", "age": 20},
            ],
        )

        @fraiseql_type(sql_source="v_order_where_users", jsonb_column="data")
        @dataclass
        class OrderWhereUser:
            id: str
            name: str
            age: int

        @query
        async def order_where_users(info, where=None, order_by=None) -> list[OrderWhereUser]:
            db = info.context["db"]
            return await db.find("v_order_where_users", info=info, where=where, order_by=order_by)

        schema = build_fraiseql_schema(query_types=[OrderWhereUser, order_where_users])
        result = await execute_graphql(
            schema,
            """{ orderWhereUsers(where: {age: {gte: 25}}, orderBy: [{age: DESC}]) { name age } }""",
            context_value=gql_context,
        )

        data, errors = parse_graphql_result(result)
        assert errors is None
        users = data["orderWhereUsers"]
        ages = [u["age"] for u in users]

        assert all(age >= 25 for age in ages)
        assert ages == sorted(ages, reverse=True)


class TestPaginationExecution:
    """Test limit/offset parameters work at runtime."""

    @pytest.mark.asyncio
    async def test_limit_restricts_results(
        self,
        clear_registry,
        db_connection,
        gql_context,
        setup_graphql_table,
        seed_graphql_data,
    ):
        """Limit should restrict number of results."""
        await setup_graphql_table("limit_exec_items")
        await seed_graphql_data(
            "tb_limit_exec_items",
            [{"name": f"Item {i}", "seq": i} for i in range(20)],
        )

        @fraiseql_type(sql_source="v_limit_exec_items", jsonb_column="data")
        @dataclass
        class LimitExecItem:
            id: str
            name: str

        @query
        async def limit_exec_items(info, limit=None) -> list[LimitExecItem]:
            db = info.context["db"]
            return await db.find("v_limit_exec_items", info=info, limit=limit)

        schema = build_fraiseql_schema(query_types=[LimitExecItem, limit_exec_items])
        result = await execute_graphql(
            schema,
            "{ limitExecItems(limit: 5) { name } }",
            context_value=gql_context,
        )

        data, errors = parse_graphql_result(result)
        assert errors is None
        assert len(data["limitExecItems"]) == 5

    @pytest.mark.asyncio
    async def test_offset_skips_results(
        self,
        clear_registry,
        db_connection,
        gql_context,
        setup_graphql_table,
        seed_graphql_data,
    ):
        """Offset should skip initial results."""
        await setup_graphql_table("offset_exec_items")
        await seed_graphql_data(
            "tb_offset_exec_items",
            [{"name": f"Item {i}", "seq": i} for i in range(20)],
        )

        @fraiseql_type(sql_source="v_offset_exec_items", jsonb_column="data")
        @dataclass
        class OffsetExecItem:
            id: str
            seq: int

        @query
        async def offset_exec_items(info, order_by=None, offset=None) -> list[OffsetExecItem]:
            db = info.context["db"]
            return await db.find("v_offset_exec_items", info=info, order_by=order_by, offset=offset)

        schema = build_fraiseql_schema(query_types=[OffsetExecItem, offset_exec_items])

        # Get all ordered
        all_result = await execute_graphql(
            schema,
            "{ offsetExecItems(orderBy: [{seq: ASC}]) { seq } }",
            context_value=gql_context,
        )

        # Get with offset
        offset_result = await execute_graphql(
            schema,
            "{ offsetExecItems(orderBy: [{seq: ASC}], offset: 5) { seq } }",
            context_value=gql_context,
        )

        all_data, _all_errors = parse_graphql_result(all_result)
        offset_data, offset_errors = parse_graphql_result(offset_result)

        assert offset_errors is None
        all_items = all_data["offsetExecItems"]
        offset_items = offset_data["offsetExecItems"]
        assert offset_items[0]["seq"] == all_items[5]["seq"]

    @pytest.mark.asyncio
    async def test_limit_and_offset_together(
        self,
        clear_registry,
        db_connection,
        gql_context,
        setup_graphql_table,
        seed_graphql_data,
    ):
        """Limit and offset should work together."""
        await setup_graphql_table("page_exec_items")
        await seed_graphql_data(
            "tb_page_exec_items",
            [{"seq": i} for i in range(20)],
        )

        @fraiseql_type(sql_source="v_page_exec_items", jsonb_column="data")
        @dataclass
        class PageExecItem:
            id: str
            seq: int

        @query
        async def page_exec_items(
            info, order_by=None, limit=None, offset=None
        ) -> list[PageExecItem]:
            db = info.context["db"]
            return await db.find(
                "v_page_exec_items",
                info=info,
                order_by=order_by,
                limit=limit,
                offset=offset,
            )

        schema = build_fraiseql_schema(query_types=[PageExecItem, page_exec_items])
        result = await execute_graphql(
            schema,
            "{ pageExecItems(orderBy: [{seq: ASC}], limit: 5, offset: 10) { seq } }",
            context_value=gql_context,
        )

        data, errors = parse_graphql_result(result)
        assert errors is None
        items = data["pageExecItems"]
        assert len(items) == 5
        assert items[0]["seq"] == 10

    @pytest.mark.asyncio
    async def test_negative_limit_returns_error(
        self, clear_registry, db_connection, gql_context, setup_graphql_table
    ):
        """Negative limit should return error."""
        await setup_graphql_table("neg_limit_items")

        @fraiseql_type(sql_source="v_neg_limit_items", jsonb_column="data")
        @dataclass
        class NegLimitItem:
            id: str

        @query
        async def neg_limit_items(info, limit=None) -> list[NegLimitItem]:
            db = info.context["db"]
            return await db.find("v_neg_limit_items", info=info, limit=limit)

        schema = build_fraiseql_schema(query_types=[NegLimitItem, neg_limit_items])
        result = await execute_graphql(
            schema,
            "{ negLimitItems(limit: -1) { id } }",
            context_value=gql_context,
        )

        _data, errors = parse_graphql_result(result)
        assert errors is not None

    @pytest.mark.asyncio
    async def test_negative_offset_returns_error(
        self, clear_registry, db_connection, gql_context, setup_graphql_table
    ):
        """Negative offset should return error."""
        await setup_graphql_table("neg_offset_items")

        @fraiseql_type(sql_source="v_neg_offset_items", jsonb_column="data")
        @dataclass
        class NegOffsetItem:
            id: str

        @query
        async def neg_offset_items(info, offset=None) -> list[NegOffsetItem]:
            db = info.context["db"]
            return await db.find("v_neg_offset_items", info=info, offset=offset)

        schema = build_fraiseql_schema(query_types=[NegOffsetItem, neg_offset_items])
        result = await execute_graphql(
            schema,
            "{ negOffsetItems(offset: -1) { id } }",
            context_value=gql_context,
        )

        _data, errors = parse_graphql_result(result)
        assert errors is not None


class TestAllParametersCombined:
    """Test all parameters work together."""

    @pytest.mark.asyncio
    async def test_where_order_by_limit_offset_combined(
        self,
        clear_registry,
        db_connection,
        gql_context,
        setup_graphql_table,
        seed_graphql_data,
    ):
        """All parameters should work together."""
        await setup_graphql_table("combined_items")
        await seed_graphql_data(
            "tb_combined_items",
            [
                {
                    "name": f"Item {i}",
                    "category": "A" if i % 2 == 0 else "B",
                    "seq": i,
                }
                for i in range(30)
            ],
        )

        @fraiseql_type(sql_source="v_combined_items", jsonb_column="data")
        @dataclass
        class CombinedItem:
            id: str
            name: str
            category: str
            seq: int

        @query
        async def combined_items(
            info, where=None, order_by=None, limit=None, offset=None
        ) -> list[CombinedItem]:
            db = info.context["db"]
            return await db.find(
                "v_combined_items",
                info=info,
                where=where,
                order_by=order_by,
                limit=limit,
                offset=offset,
            )

        schema = build_fraiseql_schema(query_types=[CombinedItem, combined_items])
        result = await execute_graphql(
            schema,
            """{ combinedItems(
                where: {category: {eq: "A"}},
                orderBy: [{seq: DESC}],
                limit: 5,
                offset: 2
            ) { category seq } }""",
            context_value=gql_context,
        )

        data, errors = parse_graphql_result(result)
        assert errors is None
        items = data["combinedItems"]

        assert all(item["category"] == "A" for item in items)
        assert len(items) == 5
        seqs = [item["seq"] for item in items]
        assert seqs == sorted(seqs, reverse=True)

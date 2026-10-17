"""Schema generation tests for auto-wired query parameters.

These tests verify that the GraphQL schema correctly includes auto-wired
parameters (orderBy, limit, offset) for queries returning list[FraiseType].

NO DATABASE REQUIRED - these tests only check schema generation.
"""

from dataclasses import dataclass
from uuid import UUID

import pytest
from graphql import GraphQLEnumType, GraphQLInputObjectType, GraphQLInt, GraphQLList

from fraiseql import query
from fraiseql import type as fraiseql_type
from fraiseql.gql.schema_builder import build_fraiseql_schema

pytestmark = pytest.mark.integration


class TestOrderBySchemaGeneration:
    """Test that orderBy parameter is auto-added to schema."""

    @pytest.fixture(autouse=True)
    def auto_clear(self, clear_registry):
        """Use standard clear_registry fixture."""
        return

    def test_list_query_has_order_by_parameter(self):
        """Queries returning list[FraiseType] should have orderBy parameter."""

        @fraiseql_type(sql_source="v_order_by_users")
        @dataclass
        class OrderByUser:
            id: UUID
            name: str
            age: int

        @query
        async def order_by_users(info) -> list[OrderByUser]:
            return []

        schema = build_fraiseql_schema()
        field = schema.query_type.fields.get("orderByUsers")

        assert field is not None, "Query field should exist"
        assert "orderBy" in field.args, "orderBy parameter should be auto-added"

    def test_order_by_parameter_is_list_type(self):
        """OrderBy should be a list to support multiple sort criteria."""

        @fraiseql_type(sql_source="v_order_list_users")
        @dataclass
        class OrderListUser:
            id: UUID
            name: str

        @query
        async def order_list_users(info) -> list[OrderListUser]:
            return []

        schema = build_fraiseql_schema()
        field = schema.query_type.fields.get("orderListUsers")
        order_by_arg = field.args["orderBy"]

        assert isinstance(order_by_arg.type, GraphQLList)

    def test_order_by_input_has_type_fields(self):
        """OrderByInput should have fields matching the return type."""

        @fraiseql_type(sql_source="v_order_fields_users")
        @dataclass
        class OrderFieldsUser:
            id: UUID
            name: str
            age: int
            email: str

        @query
        async def order_fields_users(info) -> list[OrderFieldsUser]:
            return []

        schema = build_fraiseql_schema()
        field = schema.query_type.fields.get("orderFieldsUsers")
        inner_type = field.args["orderBy"].type.of_type

        assert isinstance(inner_type, GraphQLInputObjectType)
        assert "name" in inner_type.fields
        assert "age" in inner_type.fields
        assert "email" in inner_type.fields

    def test_order_by_field_is_enum_type(self):
        """Each field in OrderByInput should be OrderDirection enum."""

        @fraiseql_type(sql_source="v_order_enum_users")
        @dataclass
        class OrderEnumUser:
            id: UUID
            name: str

        @query
        async def order_enum_users(info) -> list[OrderEnumUser]:
            return []

        schema = build_fraiseql_schema()
        field = schema.query_type.fields.get("orderEnumUsers")
        inner_type = field.args["orderBy"].type.of_type
        name_field = inner_type.fields["name"]

        field_type = name_field.type
        if hasattr(field_type, "of_type"):
            field_type = field_type.of_type

        assert isinstance(field_type, GraphQLEnumType)

    def test_manual_order_by_not_duplicated(self):
        """If resolver already has orderBy, don't add another."""

        @fraiseql_type(sql_source="v_manual_order_users")
        @dataclass
        class ManualOrderUser:
            id: UUID
            name: str

        OrderByInput = ManualOrderUser.OrderBy

        @query
        async def manual_order_users(
            info, order_by: OrderByInput | None = None
        ) -> list[ManualOrderUser]:
            return []

        schema = build_fraiseql_schema()
        field = schema.query_type.fields.get("manualOrderUsers")

        order_params = [k for k in field.args if "order" in k.lower()]
        assert len(order_params) == 1, f"Should not duplicate: {order_params}"

    def test_single_return_type_no_order_by(self):
        """Single FraiseType return should NOT have orderBy."""

        @fraiseql_type(sql_source="v_single_user")
        @dataclass
        class SingleUser:
            id: UUID
            name: str

        @query
        async def single_user(info, id: UUID) -> SingleUser | None:
            return None

        schema = build_fraiseql_schema()
        field = schema.query_type.fields.get("singleUser")

        assert "orderBy" not in field.args


class TestPaginationSchemaGeneration:
    """Test that limit/offset parameters are auto-added to schema."""

    @pytest.fixture(autouse=True)
    def auto_clear(self, clear_registry):
        return

    def test_list_query_has_limit_parameter(self):
        """Queries returning list[FraiseType] should have limit parameter."""

        @fraiseql_type(sql_source="v_limit_items")
        @dataclass
        class LimitItem:
            id: UUID
            name: str

        @query
        async def limit_items(info) -> list[LimitItem]:
            return []

        schema = build_fraiseql_schema()
        field = schema.query_type.fields.get("limitItems")

        assert "limit" in field.args

    def test_list_query_has_offset_parameter(self):
        """Queries returning list[FraiseType] should have offset parameter."""

        @fraiseql_type(sql_source="v_offset_items")
        @dataclass
        class OffsetItem:
            id: UUID
            name: str

        @query
        async def offset_items(info) -> list[OffsetItem]:
            return []

        schema = build_fraiseql_schema()
        field = schema.query_type.fields.get("offsetItems")

        assert "offset" in field.args

    def test_limit_and_offset_are_int_type(self):
        """Limit and offset should be Int type."""

        @fraiseql_type(sql_source="v_int_type_items")
        @dataclass
        class IntTypeItem:
            id: UUID

        @query
        async def int_type_items(info) -> list[IntTypeItem]:
            return []

        schema = build_fraiseql_schema()
        field = schema.query_type.fields.get("intTypeItems")

        assert field.args["limit"].type == GraphQLInt
        assert field.args["offset"].type == GraphQLInt

    def test_manual_limit_not_duplicated(self):
        """If resolver already has limit, don't add another."""

        @fraiseql_type(sql_source="v_manual_limit_items")
        @dataclass
        class ManualLimitItem:
            id: UUID

        @query
        async def manual_limit_items(info, limit: int | None = None) -> list[ManualLimitItem]:
            return []

        schema = build_fraiseql_schema()
        field = schema.query_type.fields.get("manualLimitItems")

        limit_params = [k for k in field.args if k == "limit"]
        assert len(limit_params) == 1

"""Relay pagination tests for auto-wired Connection query parameters.

These tests verify that queries returning Connection[FraiseType] automatically
get first/after/last/before parameters.
"""

from dataclasses import dataclass
from uuid import UUID

import pytest
from graphql import GraphQLInt, GraphQLString

from fraiseql import query
from fraiseql import type as fraiseql_type
from fraiseql.gql.schema_builder import build_fraiseql_schema

pytestmark = pytest.mark.integration


# Check if Connection type exists
try:
    from fraiseql.types.generic import Connection  # noqa: F401 - availability check

    HAS_CONNECTION = True
except ImportError:
    HAS_CONNECTION = False


@pytest.mark.skipif(not HAS_CONNECTION, reason="Connection type not available")
class TestRelaySchemaGeneration:
    """Test that Relay parameters are auto-added to schema."""

    @pytest.fixture(autouse=True)
    def auto_clear(self, clear_registry):
        return

    def test_connection_query_has_first_parameter(self):
        """Connection queries should have 'first' parameter."""
        from fraiseql.types.generic import Connection

        @fraiseql_type(sql_source="v_relay_posts")
        @dataclass
        class RelayPost:
            id: UUID
            title: str

        @query
        async def relay_posts(info) -> Connection[RelayPost]:
            return None

        schema = build_fraiseql_schema()
        field = schema.query_type.fields.get("relayPosts")

        assert field is not None
        assert "first" in field.args

    def test_connection_query_has_after_parameter(self):
        """Connection queries should have 'after' parameter."""
        from fraiseql.types.generic import Connection

        @fraiseql_type(sql_source="v_relay_after_posts")
        @dataclass
        class RelayAfterPost:
            id: UUID

        @query
        async def relay_after_posts(info) -> Connection[RelayAfterPost]:
            return None

        schema = build_fraiseql_schema()
        field = schema.query_type.fields.get("relayAfterPosts")

        assert "after" in field.args

    def test_connection_query_has_last_and_before(self):
        """Connection queries should have 'last' and 'before' parameters."""
        from fraiseql.types.generic import Connection

        @fraiseql_type(sql_source="v_relay_back_posts")
        @dataclass
        class RelayBackPost:
            id: UUID

        @query
        async def relay_back_posts(info) -> Connection[RelayBackPost]:
            return None

        schema = build_fraiseql_schema()
        field = schema.query_type.fields.get("relayBackPosts")

        assert "last" in field.args
        assert "before" in field.args

    def test_first_is_int_after_is_string(self):
        """First should be Int, after should be String."""
        from fraiseql.types.generic import Connection

        @fraiseql_type(sql_source="v_relay_types")
        @dataclass
        class RelayTypesPost:
            id: UUID

        @query
        async def relay_types(info) -> Connection[RelayTypesPost]:
            return None

        schema = build_fraiseql_schema()
        field = schema.query_type.fields.get("relayTypes")

        assert field.args["first"].type == GraphQLInt
        assert field.args["after"].type == GraphQLString

    def test_connection_also_has_where_and_order_by(self):
        """Connection queries should have where and orderBy."""
        from fraiseql.types.generic import Connection

        @fraiseql_type(sql_source="v_relay_full_posts")
        @dataclass
        class RelayFullPost:
            id: UUID
            title: str

        @query
        async def relay_full_posts(info) -> Connection[RelayFullPost]:
            return None

        schema = build_fraiseql_schema()
        field = schema.query_type.fields.get("relayFullPosts")

        assert "where" in field.args
        assert "orderBy" in field.args

    def test_list_query_no_relay_params(self):
        """Regular list queries should NOT get Relay parameters."""

        @fraiseql_type(sql_source="v_list_no_relay")
        @dataclass
        class ListNoRelay:
            id: UUID

        @query
        async def list_no_relay(info) -> list[ListNoRelay]:
            return []

        schema = build_fraiseql_schema()
        field = schema.query_type.fields.get("listNoRelay")

        assert "first" not in field.args
        assert "after" not in field.args
        assert "last" not in field.args
        assert "before" not in field.args


@pytest.mark.skipif(not HAS_CONNECTION, reason="Connection type not available")
class TestRelayValidation:
    """Test validation for Relay parameters."""

    @pytest.mark.asyncio
    async def test_negative_first_returns_error(
        self, clear_registry, db_connection, gql_context, setup_graphql_table
    ):
        """Negative first should return error."""
        from fraiseql.graphql.execute import execute_graphql
        from fraiseql.types.generic import Connection

        await setup_graphql_table("neg_first_posts")

        @fraiseql_type(sql_source="v_neg_first_posts", jsonb_column="data")
        @dataclass
        class NegFirstPost:
            id: str

        @query
        async def neg_first_posts(info, first=None) -> Connection[NegFirstPost]:
            return {"edges": [], "pageInfo": {}, "totalCount": 0}

        schema = build_fraiseql_schema(query_types=[NegFirstPost, neg_first_posts])
        result = await execute_graphql(
            schema,
            "{ negFirstPosts(first: -1) { edges { cursor } } }",
            context_value=gql_context,
        )

        assert result.errors is not None

    @pytest.mark.asyncio
    async def test_negative_last_returns_error(
        self, clear_registry, db_connection, gql_context, setup_graphql_table
    ):
        """Negative last should return error."""
        from fraiseql.graphql.execute import execute_graphql
        from fraiseql.types.generic import Connection

        await setup_graphql_table("neg_last_posts")

        @fraiseql_type(sql_source="v_neg_last_posts", jsonb_column="data")
        @dataclass
        class NegLastPost:
            id: str

        @query
        async def neg_last_posts(info, last=None) -> Connection[NegLastPost]:
            return {"edges": [], "pageInfo": {}, "totalCount": 0}

        schema = build_fraiseql_schema(query_types=[NegLastPost, neg_last_posts])
        result = await execute_graphql(
            schema,
            "{ negLastPosts(last: -1) { edges { cursor } } }",
            context_value=gql_context,
        )

        assert result.errors is not None

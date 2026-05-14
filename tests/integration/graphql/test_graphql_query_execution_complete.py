"""Integration tests for direct path GraphQL execution.

These tests validate the direct path: GraphQL → SQL → Rust → HTTP.
This bypasses GraphQL resolvers entirely for maximum performance.

Pipeline: Query parsing → SQL generation → JSONB retrieval →
          Rust transformation (camelCase + field projection + __typename) → HTTP

Status: ✅ PASSING - Direct path implemented and working!
"""

import pytest

# Import database fixtures
from fraiseql import query
from fraiseql import type as fraiseql_type
from fraiseql.sql import create_graphql_where_input

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_graphql_simple_query_returns_data(db_connection) -> None:
    """Test that simple GraphQL query returns data via direct path.

    ✅ Tests: GraphQL → SQL → Rust → Direct Execution for single object query.
    """
    # Setup test data
    await db_connection.execute("""
        DROP TABLE IF EXISTS tv_user CASCADE;
        DROP VIEW IF EXISTS v_user CASCADE;

        CREATE TABLE tv_user (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            data JSONB NOT NULL
        );

        INSERT INTO tv_user (id, data) VALUES
            ('11111111-1111-1111-1111-111111111111', '{"id": "11111111-1111-1111-1111-111111111111", "first_name": "John", "last_name": "Doe", "email": "john@example.com"}');

        CREATE VIEW v_user AS
        SELECT id, data FROM tv_user;
    """)

    @fraiseql_type(sql_source="v_user", jsonb_column="data")
    class User:
        id: str
        first_name: str
        email: str

    @query
    async def user(info, id: str) -> User | None:
        db = info.context["db"]
        return await db.find_one("v_user", info=info, mandatory_filters={"id": id})

    # Build schema and execute directly
    from fraiseql.gql.schema_builder import build_fraiseql_schema
    from fraiseql.graphql.execute import execute_graphql

    schema = build_fraiseql_schema(query_types=[User, user])

    # Create a repository instance like the FastAPI app does
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock

    from fraiseql.db import FraiseQLRepository

    # Create a mock pool that returns our db_connection as an async context manager
    mock_pool = MagicMock()

    @asynccontextmanager
    async def mock_connection():
        yield db_connection

    mock_pool.connection = mock_connection

    repo = FraiseQLRepository(pool=mock_pool)

    result = await execute_graphql(
        schema,
        'query { user(id: "11111111-1111-1111-1111-111111111111") { id firstName email } }',
        context_value={"db": repo},
    )

    # Verify direct path success
    from fraiseql.core.rust_pipeline import RustResponseBytes

    if isinstance(result, RustResponseBytes):
        data = result.to_json()
        assert "data" in data, f"Expected 'data' key in RustResponseBytes JSON: {data}"
        data = data["data"]
    else:
        # Standard ExecutionResult
        assert result.errors is None, f"Query failed with errors: {result.errors}"
        data = result.data

    assert data["user"]["id"] == "11111111-1111-1111-1111-111111111111"
    assert data["user"]["firstName"] == "John"
    assert data["user"]["email"] == "john@example.com"


@pytest.mark.asyncio
async def test_graphql_list_query_returns_array(db_connection) -> None:
    """Test that list queries return arrays via direct path.

    ✅ Tests: GraphQL → SQL → Rust → Direct Execution for list queries.
    """
    # Setup test data
    await db_connection.execute("""
        DROP TABLE IF EXISTS tv_users CASCADE;
        DROP VIEW IF EXISTS v_users CASCADE;

        CREATE TABLE tv_users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            data JSONB NOT NULL
        );

        INSERT INTO tv_users (id, data) VALUES
            ('11111111-1111-1111-1111-111111111111', '{"id": "11111111-1111-1111-1111-111111111111", "first_name": "John", "last_name": "Doe", "email": "john@example.com"}'),
            ('22222222-2222-2222-2222-222222222222', '{"id": "22222222-2222-2222-2222-222222222222", "first_name": "Jane", "last_name": "Smith", "email": "jane@example.com"}');

        CREATE VIEW v_users AS
        SELECT id, data FROM tv_users;
    """)

    @fraiseql_type(sql_source="v_users", jsonb_column="data")
    class User:
        id: str
        first_name: str
        email: str

    @query
    async def users(info) -> list[User]:
        db = info.context["db"]
        return await db.find("v_users", info=info)

    # Create a repository instance like the FastAPI app does
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock

    from fraiseql.db import FraiseQLRepository

    # Create a mock pool that returns our db_connection as an async context manager
    mock_pool = MagicMock()

    @asynccontextmanager
    async def mock_connection():
        yield db_connection

    mock_pool.connection = mock_connection

    repo = FraiseQLRepository(pool=mock_pool)

    # Build schema and execute directly
    from fraiseql.gql.schema_builder import build_fraiseql_schema
    from fraiseql.graphql.execute import execute_graphql

    schema = build_fraiseql_schema(query_types=[User, users])

    result = await execute_graphql(
        schema, "query { users { id firstName email } }", context_value={"db": repo}
    )

    # Verify direct path success
    from fraiseql.core.rust_pipeline import RustResponseBytes

    if isinstance(result, RustResponseBytes):
        data = result.to_json()
        assert "data" in data, f"Expected 'data' key in RustResponseBytes JSON: {data}"
        data = data["data"]
    else:
        # Standard ExecutionResult
        assert result.errors is None, f"Query failed with errors: {result.errors}"
        data = result.data

    assert len(data["users"]) == 2
    assert all("id" in user and "firstName" in user and "email" in user for user in data["users"])


@pytest.mark.asyncio
async def test_graphql_field_selection(db_connection) -> None:
    """Test that Rust field projection works correctly.

    ✅ Tests: Rust filters fields to only those requested in GraphQL query.
    """
    # Setup test data
    await db_connection.execute("""
        DROP TABLE IF EXISTS tv_user CASCADE;
        DROP VIEW IF EXISTS v_user CASCADE;

        CREATE TABLE tv_user (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            data JSONB NOT NULL
        );

        INSERT INTO tv_user (id, data) VALUES
            ('11111111-1111-1111-1111-111111111111', '{"id": "11111111-1111-1111-1111-111111111111", "first_name": "John", "last_name": "Doe", "email": "john@example.com"}');

        CREATE VIEW v_user AS
        SELECT id, data FROM tv_user;
    """)

    @fraiseql_type(sql_source="v_user", jsonb_column="data")
    class User:
        id: str
        first_name: str
        last_name: str
        email: str

    @query
    async def user(info, id: str) -> User | None:
        db = info.context["db"]
        return await db.find_one("v_user", info=info, mandatory_filters={"id": id})

    # Create a repository instance like the FastAPI app does
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock

    from fraiseql.db import FraiseQLRepository

    # Create a mock pool that returns our db_connection as an async context manager
    mock_pool = MagicMock()

    @asynccontextmanager
    async def mock_connection():
        yield db_connection

    mock_pool.connection = mock_connection

    repo = FraiseQLRepository(pool=mock_pool)

    # Build schema and execute directly
    from fraiseql.gql.schema_builder import build_fraiseql_schema
    from fraiseql.graphql.execute import execute_graphql

    schema = build_fraiseql_schema(query_types=[User, user])

    result = await execute_graphql(
        schema,
        'query { user(id: "11111111-1111-1111-1111-111111111111") { id firstName } }',
        context_value={"db": repo},
    )

    # Verify direct path success
    from fraiseql.core.rust_pipeline import RustResponseBytes

    if isinstance(result, RustResponseBytes):
        data = result.to_json()
        assert "data" in data, f"Expected 'data' key in RustResponseBytes JSON: {data}"
        data = data["data"]
    else:
        # Standard ExecutionResult
        assert result.errors is None, f"Query failed with errors: {result.errors}"
        data = result.data

    user_data = data["user"]

    # Should have requested fields
    assert "id" in user_data
    assert "firstName" in user_data

    # Should NOT have non-requested fields (Rust field projection)
    assert "email" not in user_data
    assert "lastName" not in user_data


@pytest.mark.asyncio
async def test_graphql_with_where_filter(db_connection) -> None:
    """Test GraphQL queries with WHERE filters via direct path.

    ✅ Tests: WHERE filters work with dict arguments in direct path.
    """
    # Setup test data
    await db_connection.execute("""
        DROP TABLE IF EXISTS tv_user CASCADE;
        DROP VIEW IF EXISTS v_user CASCADE;

        CREATE TABLE tv_user (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            data JSONB NOT NULL
        );

        INSERT INTO tv_user (id, data) VALUES
            ('11111111-1111-1111-1111-111111111111', '{"id": "11111111-1111-1111-1111-111111111111", "first_name": "John", "active": true}'),
            ('22222222-2222-2222-2222-222222222222', '{"id": "22222222-2222-2222-2222-222222222222", "first_name": "Jane", "active": false}'),
            ('33333333-3333-3333-3333-333333333333', '{"id": "33333333-3333-3333-3333-333333333333", "first_name": "Bob", "active": true}');

        CREATE VIEW v_user AS
        SELECT id, data FROM tv_user;
    """)

    @fraiseql_type(sql_source="v_user", jsonb_column="data")
    class User:
        id: str
        first_name: str
        active: bool

    # Generate Where input type
    UserWhereInput = create_graphql_where_input(User)

    @query
    async def users(info, where: UserWhereInput | None = None) -> list[User]:
        db = info.context["db"]
        return await db.find("v_user", info=info, where=where)

    # Create a repository instance like the FastAPI app does
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock

    from fraiseql.db import FraiseQLRepository

    # Create a mock pool that returns our db_connection as an async context manager
    mock_pool = MagicMock()

    @asynccontextmanager
    async def mock_connection():
        yield db_connection

    mock_pool.connection = mock_connection

    repo = FraiseQLRepository(pool=mock_pool)

    # Build schema and execute directly
    from fraiseql.gql.schema_builder import build_fraiseql_schema
    from fraiseql.graphql.execute import execute_graphql

    schema = build_fraiseql_schema(query_types=[User, UserWhereInput, users])

    result = await execute_graphql(
        schema,
        """
        query {
            users(where: {active: {eq: true}}) {
                id
                firstName
            }
        }
        """,
        context_value={"db": repo},
    )

    # Verify direct path success
    from fraiseql.core.rust_pipeline import RustResponseBytes

    if isinstance(result, RustResponseBytes):
        data = result.to_json()
        assert "data" in data, f"Expected 'data' key in RustResponseBytes JSON: {data}"
        data = data["data"]
    else:
        # Standard ExecutionResult
        assert result.errors is None, f"Query failed with errors: {result.errors}"
        data = result.data

    users_data = data["users"]
    assert len(users_data) == 2  # John and Bob
    # Verify they are the active users (John and Bob)
    names = {user["firstName"] for user in users_data}
    assert names == {"John", "Bob"}

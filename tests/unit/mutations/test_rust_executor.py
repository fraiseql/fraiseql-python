"""Test Rust mutation executor."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_execute_mutation_no_result():
    """Test mutation execution when no result is returned."""
    from fraiseql.core.rust_pipeline import RustResponseBytes
    from fraiseql.mutations.rust_executor import execute_mutation_rust

    # Mock connection - no result returned
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = None

    # Mock async context manager for cursor
    mock_cursor_ctx = AsyncMock()
    mock_cursor_ctx.__aenter__.return_value = mock_cursor
    mock_cursor_ctx.__aexit__.return_value = None

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor_ctx

    result = await execute_mutation_rust(
        conn=mock_conn,
        function_name="app.create_user",
        input_data={"name": "Test"},
        field_name="createUser",
        success_type="CreateUserSuccess",
        error_type="CreateUserError",
        entity_field_name="user",
        entity_type="User",  # For simple format, but Rust uses entity_type from JSON
    )

    assert isinstance(result, RustResponseBytes)

    # Verify the response structure
    import json

    response = json.loads(bytes(result))
    assert response["data"]["createUser"]["__typename"] == "CreateUserError"


@pytest.mark.asyncio
async def test_execute_mutation_simple_format():
    """Test mutation execution with simple format (just entity JSONB)."""
    from fraiseql.core.rust_pipeline import RustResponseBytes
    from fraiseql.mutations.rust_executor import execute_mutation_rust

    # Mock connection - simple format: just entity data, no status wrapper
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = (
        {"id": "123", "name": "Test", "email": "test@example.com"},
    )

    # Mock async context manager for cursor
    mock_cursor_ctx = AsyncMock()
    mock_cursor_ctx.__aenter__.return_value = mock_cursor
    mock_cursor_ctx.__aexit__.return_value = None

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor_ctx

    result = await execute_mutation_rust(
        conn=mock_conn,
        function_name="app.create_user",
        input_data={"name": "Test"},
        field_name="createUser",
        success_type="CreateUserSuccess",
        error_type="CreateUserError",
        entity_field_name="user",
        entity_type="User",  # REQUIRED for simple format
    )

    assert isinstance(result, RustResponseBytes)

    # Verify the response structure
    import json

    response = json.loads(bytes(result))
    assert response["data"]["createUser"]["__typename"] == "CreateUserSuccess"
    assert response["data"]["createUser"]["user"]["__typename"] == "User"
    assert response["data"]["createUser"]["user"]["name"] == "Test"


@pytest.mark.asyncio
async def test_execute_mutation_with_context_args():
    """Test mutation execution with context arguments."""
    from fraiseql.core.rust_pipeline import RustResponseBytes
    from fraiseql.mutations.rust_executor import execute_mutation_rust

    # Mock connection - simple format
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = ({"id": "123", "name": "Test"},)

    # Mock async context manager for cursor
    mock_cursor_ctx = AsyncMock()
    mock_cursor_ctx.__aenter__.return_value = mock_cursor
    mock_cursor_ctx.__aexit__.return_value = None

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor_ctx

    result = await execute_mutation_rust(
        conn=mock_conn,
        function_name="app.create_user",
        input_data={"email": "test@example.com"},
        field_name="createUser",
        success_type="CreateUserSuccess",
        error_type="CreateUserError",
        entity_field_name="user",
        entity_type="User",
    )

    assert isinstance(result, RustResponseBytes)

    # Verify the response structure
    import json

    response = json.loads(bytes(result))
    assert response["data"]["createUser"]["__typename"] == "CreateUserSuccess"
    assert response["data"]["createUser"]["user"]["__typename"] == "User"
    assert response["data"]["createUser"]["user"]["name"] == "Test"


@pytest.mark.asyncio
async def test_execute_mutation_v2_format():
    """Test mutation execution with v2 format (has status field)."""
    from fraiseql.core.rust_pipeline import RustResponseBytes
    from fraiseql.mutations.rust_executor import execute_mutation_rust

    # Mock connection - v2 format with status field
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = (
        {
            "status": "created",
            "message": "User created",
            "entity_id": "123",
            "entity_type": "User",
            "entity": {"id": "123", "name": "Test"},
            "updated_fields": None,
            "cascade": None,
            "metadata": None,
        },
    )

    # Mock async context manager for cursor
    mock_cursor_ctx = AsyncMock()
    mock_cursor_ctx.__aenter__.return_value = mock_cursor
    mock_cursor_ctx.__aexit__.return_value = None

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor_ctx

    result = await execute_mutation_rust(
        conn=mock_conn,
        function_name="app.create_user",
        input_data={"name": "Test"},
        field_name="createUser",
        success_type="CreateUserSuccess",
        error_type="CreateUserError",
        entity_field_name="user",
        entity_type="User",
    )

    assert isinstance(result, RustResponseBytes)

    # Should return a success response
    import json

    response = json.loads(bytes(result))
    assert response["data"]["createUser"]["__typename"] == "CreateUserSuccess"
    assert response["data"]["createUser"]["user"]["__typename"] == "User"
    assert response["data"]["createUser"]["user"]["name"] == "Test"


@pytest.mark.asyncio
async def test_execute_mutation_error_format():
    """Test mutation execution with error format."""
    from fraiseql.core.rust_pipeline import RustResponseBytes
    from fraiseql.mutations.rust_executor import execute_mutation_rust

    # Mock connection - error format
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = (
        {
            "status": "failed:validation",
            "message": "Email already exists",
            "entity_id": None,
            "entity_type": None,
            "entity": None,
            "updated_fields": None,
            "cascade": None,
            "metadata": None,
        },
    )

    # Mock async context manager for cursor
    mock_cursor_ctx = AsyncMock()
    mock_cursor_ctx.__aenter__.return_value = mock_cursor
    mock_cursor_ctx.__aexit__.return_value = None

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor_ctx

    result = await execute_mutation_rust(
        conn=mock_conn,
        function_name="app.create_user",
        input_data={"name": "Test"},
        field_name="createUser",
        success_type="CreateUserSuccess",
        error_type="CreateUserError",
        entity_field_name="user",
        entity_type="User",
        context_args=["user-456", "org-123"],  # Additional context args
    )

    assert isinstance(result, RustResponseBytes)

    # Verify SQL was called with correct parameters
    mock_cursor.execute.assert_called_once()
    args, _kwargs = mock_cursor.execute.call_args
    args[0]
    params = args[1]

    # Should have context args + input JSON
    assert len(params) == 3  # 2 context args + 1 JSON input
    assert params[0] == "user-456"
    assert params[1] == "org-123"
    assert '"name":"Test"' in params[2]  # JSON input

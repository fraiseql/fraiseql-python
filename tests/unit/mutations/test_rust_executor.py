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


def _conn_returning(row: dict) -> MagicMock:
    """A connection whose cursor returns one row holding the mutation result."""
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = (row,)
    mock_cursor_ctx = AsyncMock()
    mock_cursor_ctx.__aenter__.return_value = mock_cursor
    mock_cursor_ctx.__aexit__.return_value = None
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor_ctx
    return mock_conn


_UNTYPED_RESULT = {
    "status": "updated",
    "message": "ok",
    "entity_id": "l1",
    "entity_type": None,
    "entity": {"id": "l1", "name": "HQ"},
    "updated_fields": None,
    "cascade": None,
    "metadata": None,
}


async def _run_untyped(function_name: str, entity_type: str | None, row: dict) -> None:
    from fraiseql.mutations.rust_executor import execute_mutation_rust

    await execute_mutation_rust(
        conn=_conn_returning(row),
        function_name=function_name,
        input_data={"id": "l1"},
        field_name="updateLocation",
        success_type="UpdateLocationSuccess",
        error_type="UpdateLocationError",
        entity_field_name="location",
        entity_type=entity_type,
    )


@pytest.mark.asyncio
async def test_untyped_entity_warns_once_per_function(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    """A success entity with no type from SQL, the data or the schema logs one warning."""
    from fraiseql.mutations import rust_executor

    monkeypatch.setattr(rust_executor, "_warned_untyped_entity", set())
    with caplog.at_level("WARNING", logger="fraiseql.mutations.rust_executor"):
        await _run_untyped("app.update_location_untyped", None, _UNTYPED_RESULT)
        await _run_untyped("app.update_location_untyped", None, _UNTYPED_RESULT)

    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert warnings == [
        "SQL function app.update_location_untyped returned an entity without entity_type; "
        "__typename left out"
    ]


@pytest.mark.asyncio
async def test_typed_entity_does_not_warn(caplog: pytest.LogCaptureFixture):
    typed_in_data = {**_UNTYPED_RESULT, "entity": {"__typename": "Location", "id": "l1"}}
    failed = {**_UNTYPED_RESULT, "status": "failed:validation"}
    with caplog.at_level("WARNING", logger="fraiseql.mutations.rust_executor"):
        await _run_untyped("app.typed_by_schema", "Location", _UNTYPED_RESULT)
        await _run_untyped("app.typed_by_sql", None, {**_UNTYPED_RESULT, "entity_type": "Location"})
        await _run_untyped("app.typed_by_data", None, typed_in_data)
        await _run_untyped("app.failed", None, failed)

    assert [r for r in caplog.records if r.levelname == "WARNING"] == []

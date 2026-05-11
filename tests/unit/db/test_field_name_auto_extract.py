"""Unit test for auto-extraction of info from repository context.

This tests the fix for the field name bug where db.find() and db.find_one()
would use view_name as the field name when info parameter was not passed.

The fix: Auto-extract info from self.context["graphql_info"] if not provided.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from fraiseql.core.rust_pipeline import RustResponseBytes
from fraiseql.db import FraiseQLRepository


@pytest.mark.asyncio
async def test_find_auto_extracts_info_from_context() -> None:
    """Test that find() auto-extracts info from context when not explicitly passed."""
    # Create a mock pool with async context manager
    mock_conn = AsyncMock()
    mock_pool = Mock()
    mock_pool.connection.return_value = AsyncMock()
    mock_pool.connection.return_value.__aenter__.return_value = mock_conn
    mock_pool.connection.return_value.__aexit__.return_value = AsyncMock()

    # Create a mock GraphQL info object with proper structure
    mock_info = Mock()
    mock_info.field_name = "locations"  # This is the correct field name
    mock_info.context = {}
    mock_info.field_nodes = []  # Empty list to avoid extraction logic

    # Create repository with context containing graphql_info
    context = {"graphql_info": mock_info}
    repo = FraiseQLRepository(mock_pool, context=context)

    # Mock the execute_via_rust_pipeline function
    mock_response = b'{"data":{"locations":[]}}'

    with patch("fraiseql.db.execute_via_rust_pipeline") as mock_execute:
        mock_execute.return_value = RustResponseBytes(mock_response)

        # Call find WITHOUT passing info parameter
        # The fix should auto-extract it from context
        result = await repo.find("tv_location", limit=10)

        # Verify execute_via_rust_pipeline was called
        assert mock_execute.called

        # CRITICAL ASSERTION: Verify field_name parameter is "locations" (from info.field_name)
        # NOT "tv_location" (from view_name)
        call_args = mock_execute.call_args
        field_name_arg = call_args[0][3]  # 4th positional arg is field_name

        assert field_name_arg == "locations", (
            f"Expected field_name='locations' (from info.field_name in context), "
            f"but got field_name='{field_name_arg}'. "
            f"This means the auto-extract from context failed."
        )


@pytest.mark.asyncio
async def test_find_uses_explicit_info_over_context() -> None:
    """Test that explicitly passed info takes precedence over context."""
    # Create a mock pool with async context manager
    mock_conn = AsyncMock()
    mock_pool = Mock()
    mock_pool.connection.return_value = AsyncMock()
    mock_pool.connection.return_value.__aenter__.return_value = mock_conn
    mock_pool.connection.return_value.__aexit__.return_value = AsyncMock()

    # Create TWO mock info objects
    context_info = Mock()
    context_info.field_name = "wrong_field"
    context_info.context = {}
    context_info.field_nodes = []

    explicit_info = Mock()
    explicit_info.field_name = "correct_field"
    explicit_info.context = {}
    explicit_info.field_nodes = []

    # Repository has one info in context
    context = {"graphql_info": context_info}
    repo = FraiseQLRepository(mock_pool, context=context)

    # Mock response
    mock_response = b'{"data":{"correct_field":[]}}'

    with patch("fraiseql.db.execute_via_rust_pipeline") as mock_execute:
        mock_execute.return_value = RustResponseBytes(mock_response)

        # Call find WITH explicit info parameter
        # Should use explicit_info, not context_info
        result = await repo.find("tv_location", info=explicit_info, limit=10)

        # Verify field_name is from explicit_info
        call_args = mock_execute.call_args
        field_name_arg = call_args[0][3]

        assert field_name_arg == "correct_field", (
            f"Expected field_name='correct_field' (from explicit info), "
            f"but got field_name='{field_name_arg}'. "
            f"Explicit info should take precedence over context."
        )


@pytest.mark.asyncio
async def test_find_one_auto_extracts_info_from_context() -> None:
    """Test that find_one() also auto-extracts info from context."""
    # Create a mock pool with async context manager
    mock_conn = AsyncMock()
    mock_pool = Mock()
    mock_pool.connection.return_value = AsyncMock()
    mock_pool.connection.return_value.__aenter__.return_value = mock_conn
    mock_pool.connection.return_value.__aexit__.return_value = AsyncMock()

    # Create a mock GraphQL info object with proper structure
    mock_info = Mock()
    mock_info.field_name = "location"  # Singular for find_one
    mock_info.context = {}
    mock_info.field_nodes = []

    # Create repository with context
    context = {"graphql_info": mock_info}
    repo = FraiseQLRepository(mock_pool, context=context)

    # Mock response for single object
    mock_response = b'{"data":{"location":{"id":"123"}}}'

    with patch("fraiseql.db.execute_via_rust_pipeline") as mock_execute:
        mock_execute.return_value = RustResponseBytes(mock_response)

        # Call find_one WITHOUT passing info
        result = await repo.find_one("tv_location", mandatory_filters={"id": "123"})

        # Verify field_name is "location" from context, not "tv_location" from view_name
        call_args = mock_execute.call_args
        field_name_arg = call_args[0][3]

        assert field_name_arg == "location", (
            f"Expected field_name='location' (from info.field_name in context), "
            f"but got field_name='{field_name_arg}'. "
            f"find_one() should also auto-extract info from context."
        )


@pytest.mark.asyncio
async def test_find_falls_back_to_view_name_when_no_info_available() -> None:
    """Test that view_name is used as fallback when no info is available."""
    # Create a mock pool with async context manager
    mock_conn = AsyncMock()
    mock_pool = Mock()
    mock_pool.connection.return_value = AsyncMock()
    mock_pool.connection.return_value.__aenter__.return_value = mock_conn
    mock_pool.connection.return_value.__aexit__.return_value = AsyncMock()

    # Create repository WITHOUT graphql_info in context
    context = {}  # Empty context, no graphql_info
    repo = FraiseQLRepository(mock_pool, context=context)

    # Mock response
    mock_response = b'{"data":{"tv_location":[]}}'

    with patch("fraiseql.db.execute_via_rust_pipeline") as mock_execute:
        mock_execute.return_value = RustResponseBytes(mock_response)

        # Call find WITHOUT info and without info in context
        result = await repo.find("tv_location", limit=10)

        # In this case, field_name should fall back to view_name
        call_args = mock_execute.call_args
        field_name_arg = call_args[0][3]

        assert field_name_arg == "tv_location", (
            f"Expected field_name='tv_location' (fallback to view_name), "
            f"but got field_name='{field_name_arg}'. "
            f"When no info is available, view_name should be used as fallback."
        )

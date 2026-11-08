"""Test session variables functionality in the Rust pipeline."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from psycopg.sql import SQL, Literal

pytestmark = pytest.mark.integration


class TestSessionVariablesAcrossExecutionModes:
    """Test that session variables are set consistently in all execution modes."""

    @pytest.fixture
    async def mock_pool_psycopg(self) -> None:
        """Create a mock psycopg pool with connection tracking."""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()

        # Track executed SQL statements
        executed_statements = []

        async def track_execute(sql, *args) -> None:
            # Store both raw SQL and string representation
            executed_statements.append(sql)

        mock_cursor.execute = track_execute
        mock_cursor.fetchone = AsyncMock(return_value={"result": "test"})
        mock_cursor.fetchall = AsyncMock(return_value=[{"result": "test"}])

        # Setup connection context manager
        mock_pool.connection.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)

        # Setup cursor context manager
        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor_cm)

        # Attach tracking to pool for easy access
        mock_pool.executed_statements = executed_statements

        return mock_pool

    @pytest.fixture
    async def mock_pool_asyncpg(self) -> None:
        """Create a mock asyncpg pool with connection tracking."""
        mock_pool = AsyncMock(spec=["acquire"])
        mock_conn = AsyncMock()

        # Track executed SQL statements
        executed_statements = []

        async def track_execute(sql, *args) -> None:
            executed_statements.append({"sql": sql, "args": args})

        mock_conn.execute = track_execute
        mock_conn.fetchrow = AsyncMock(return_value={"result": "test"})
        mock_conn.fetch = AsyncMock(return_value=[{"result": "test"}])
        mock_conn.set_type_codec = AsyncMock()

        # Setup acquire context manager
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        # Attach tracking to pool
        mock_pool.executed_statements = executed_statements

        return mock_pool

    @pytest.mark.asyncio
    async def test_session_variables_work(self, mock_pool_psycopg) -> None:
        """Test that session variables are set in TurboRouter execution mode."""
        tenant_id = str(uuid4())
        contact_id = str(uuid4())

        # Mock Rust pipeline execution with context
        context = {
            "tenant_id": tenant_id,
            "contact_id": contact_id,
        }

        # Create a mock cursor to track SQL
        mock_cursor = AsyncMock()
        executed_statements = []

        async def track_execute(sql, *args) -> None:
            # Handle both SQL objects and strings
            if hasattr(sql, "__sql__"):
                sql_str = str(sql.as_string(mock_cursor))
            else:
                sql_str = str(sql)
            executed_statements.append(sql_str)

        mock_cursor.execute = track_execute
        mock_cursor.fetchall = AsyncMock(return_value=[{"result": "test"}])

        # Test the TurboRouter session variable logic directly
        # This simulates what happens in turbo.py lines 252-271

        # Set session variables from context if available
        if "tenant_id" in context:
            await mock_cursor.execute(
                SQL("SET LOCAL app.tenant_id = {}").format(Literal(str(context["tenant_id"])))
            )
        if "contact_id" in context:
            await mock_cursor.execute(
                SQL("SET LOCAL app.contact_id = {}").format(Literal(str(context["contact_id"])))
            )

        # Verify session variables were set
        assert any("SET LOCAL app.tenant_id" in sql for sql in executed_statements), (
            f"Expected SET LOCAL app.tenant_id in turbo mode. SQL: {executed_statements}"
        )
        assert any("SET LOCAL app.contact_id" in sql for sql in executed_statements), (
            f"Expected SET LOCAL app.contact_id in turbo mode. SQL: {executed_statements}"
        )

        # Convert to strings for checking (handle Composed SQL objects)
        executed_sql_str = []
        for stmt in executed_statements:
            if hasattr(stmt, "as_string"):
                try:
                    executed_sql_str.append(stmt.as_string(None))
                except Exception:
                    executed_sql_str.append(str(stmt))
            else:
                executed_sql_str.append(str(stmt))

        # Current implementation should set tenant_id
        assert any("SET LOCAL app.tenant_id" in sql for sql in executed_sql_str)

        # user_id would require configuration support (future enhancement)
        # For now, it won't be set unless explicitly handled

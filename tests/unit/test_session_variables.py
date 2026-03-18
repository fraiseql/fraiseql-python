"""Unit tests for FraiseQLRepository._set_session_variables.

Verifies that session variables including fraiseql.started_at are injected
via set_config() before each query/mutation execution.
"""

from typing import Any
from unittest.mock import AsyncMock, Mock, call, patch

import pytest

import fraiseql
from fraiseql.db import FraiseQLRepository
from fraiseql.mutations.decorators import error, success
from fraiseql.mutations.mutation_decorator import mutation
from fraiseql.types.fraise_input import fraise_input
from tests.mocks import MockDatabase, MockRustResponseBytes

pytestmark = pytest.mark.unit

STARTED_AT_QUERY = "SELECT set_config('fraiseql.started_at', clock_timestamp()::text, true)"


def _make_repo(context: dict | None = None) -> FraiseQLRepository:
    """Create a FraiseQLRepository with a mock pool and optional context."""
    pool = AsyncMock()
    return FraiseQLRepository(pool=pool, context=context or {})


class TestStartedAtSessionVariable:
    """Tests for fraiseql.started_at injection in _set_session_variables."""

    @pytest.mark.asyncio
    async def test_started_at_injected_with_psycopg_cursor(self) -> None:
        """fraiseql.started_at is set via set_config() through a psycopg cursor."""
        repo = _make_repo()
        cursor = AsyncMock()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock()

        await repo._set_session_variables(cursor)

        cursor.execute.assert_called_with(STARTED_AT_QUERY)

    @pytest.mark.asyncio
    async def test_started_at_injected_with_asyncpg_connection(self) -> None:
        """fraiseql.started_at is set via set_config() through an asyncpg connection."""
        repo = _make_repo()
        conn = AsyncMock()
        conn.execute = AsyncMock()
        if hasattr(conn, "fetchone"):
            del conn.fetchone

        await repo._set_session_variables(conn)

        conn.execute.assert_called_with(STARTED_AT_QUERY)

    @pytest.mark.asyncio
    async def test_started_at_is_last_set_local(self) -> None:
        """Ensure started_at is the last session variable set.

        This guarantees the timestamp is captured closest to actual query execution.
        """
        repo = _make_repo({"tenant_id": "t1", "user_id": "u1"})
        cursor = AsyncMock()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock()

        await repo._set_session_variables(cursor)

        last_call = cursor.execute.call_args_list[-1]
        assert last_call == call(STARTED_AT_QUERY)

    @pytest.mark.asyncio
    async def test_started_at_injected_even_without_context(self) -> None:
        """fraiseql.started_at is always injected, regardless of context contents."""
        repo = _make_repo({})
        cursor = AsyncMock()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock()

        await repo._set_session_variables(cursor)

        assert cursor.execute.call_count == 1
        cursor.execute.assert_called_once_with(STARTED_AT_QUERY)


# --- Types for mutation resolver tests ---


@fraise_input
class _TestInput:
    name: str


@fraiseql.type
class _TestUser:
    id: str
    name: str


@success
class _TestSuccess:
    message: str
    user: _TestUser


@error
class _TestError:
    message: str
    code: str = "ERROR"


class TestSessionVariablesInMutationPath:
    """Verify that session variables are set before Rust mutation execution.

    Issue #309: the Rust executor path bypassed _set_session_variables(),
    causing fraiseql.started_at and all app.* session variables to be NULL.
    """

    @pytest.mark.asyncio
    async def test_set_session_variables_called_before_rust_mutation(self) -> None:
        """_set_session_variables() must be called before execute_mutation_rust()."""

        @mutation
        class CreateItem:
            input: _TestInput
            success: _TestSuccess
            error: _TestError

        resolver = CreateItem.__fraiseql_resolver__

        mock_db = MockDatabase()
        # Spy on _set_session_variables to track call order
        call_order: list[str] = []
        original_set_vars = mock_db._set_session_variables

        async def tracked_set_vars(cursor_or_conn):
            call_order.append("set_session_variables")
            await original_set_vars(cursor_or_conn)

        mock_db._set_session_variables = tracked_set_vars

        info = Mock()
        info.context = {"db": mock_db}
        info.field_nodes = []

        input_obj = Mock()
        input_obj.name = "test"
        input_obj.to_dict = lambda: {"name": "test"}

        mock_response = MockRustResponseBytes(
            {"data": {"createItem": {"status": "success", "message": "ok"}}}
        )

        async def tracked_execute(**kwargs: Any):
            call_order.append("execute_mutation_rust")
            return mock_response

        with patch(
            "fraiseql.mutations.rust_executor.execute_mutation_rust",
            side_effect=tracked_execute,
        ):
            await resolver(info, input_obj)

        assert "set_session_variables" in call_order
        assert "execute_mutation_rust" in call_order
        assert call_order.index("set_session_variables") < call_order.index(
            "execute_mutation_rust"
        ), "Session variables must be set BEFORE mutation execution"


class TestCustomSessionVariables:
    """Tests for configurable session variable forwarding (issue #310)."""

    @pytest.mark.asyncio
    async def test_custom_session_variable_forwarded(self) -> None:
        """Custom session variables from config are SET LOCAL on the cursor."""
        from psycopg.sql import SQL, Literal

        config = Mock()
        config.session_variables = {"locale": "app.locale"}

        repo = _make_repo({"config": config, "locale": "fr-FR"})
        cursor = AsyncMock()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock()

        await repo._set_session_variables(cursor)

        # Find the SET LOCAL call for app.locale
        set_locale_call = call(SQL("SET LOCAL {} = {}").format(SQL("app.locale"), Literal("fr-FR")))
        assert set_locale_call in cursor.execute.call_args_list

    @pytest.mark.asyncio
    async def test_custom_variable_before_started_at(self) -> None:
        """Custom session variables are set before fraiseql.started_at."""
        config = Mock()
        config.session_variables = {"locale": "app.locale"}

        repo = _make_repo({"config": config, "locale": "fr-FR"})
        cursor = AsyncMock()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock()

        await repo._set_session_variables(cursor)

        # started_at must be the last call
        last_call = cursor.execute.call_args_list[-1]
        assert last_call == call(STARTED_AT_QUERY)

    @pytest.mark.asyncio
    async def test_custom_variable_skipped_if_not_in_context(self) -> None:
        """Custom session variables are skipped if the context key is absent."""
        config = Mock()
        config.session_variables = {"locale": "app.locale"}

        repo = _make_repo({"config": config})  # no "locale" in context
        cursor = AsyncMock()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock()

        await repo._set_session_variables(cursor)

        # Only started_at should be called
        assert cursor.execute.call_count == 1
        cursor.execute.assert_called_once_with(STARTED_AT_QUERY)

    @pytest.mark.asyncio
    async def test_no_custom_variables_when_config_has_empty_dict(self) -> None:
        """Empty session_variables config does not add any extra SET LOCAL calls."""
        config = Mock()
        config.session_variables = {}

        repo = _make_repo({"config": config})
        cursor = AsyncMock()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock()

        await repo._set_session_variables(cursor)

        assert cursor.execute.call_count == 1
        cursor.execute.assert_called_once_with(STARTED_AT_QUERY)

    @pytest.mark.asyncio
    async def test_multiple_custom_variables(self) -> None:
        """Multiple custom session variables are all forwarded."""
        config = Mock()
        config.session_variables = {
            "locale": "app.locale",
            "timezone": "app.timezone",
        }

        repo = _make_repo(
            {
                "config": config,
                "locale": "fr-FR",
                "timezone": "Europe/Paris",
            }
        )
        cursor = AsyncMock()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock()

        await repo._set_session_variables(cursor)

        # 2 custom variables + 1 started_at = 3 calls
        assert cursor.execute.call_count == 3

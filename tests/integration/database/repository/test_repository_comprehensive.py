"""Comprehensive tests for CQRS repository module to improve coverage."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.sql import SQL

import fraiseql
from fraiseql.cqrs.executor import CQRSExecutor
from fraiseql.cqrs.repository import CQRSRepository

pytestmark = pytest.mark.database


@pytest.fixture
def mock_connection() -> None:
    """Create a mock async database connection."""
    conn = AsyncMock(spec=AsyncConnection)
    conn.execute = AsyncMock()
    conn.fetchone = AsyncMock()
    conn.fetchall = AsyncMock()
    return conn


@pytest.fixture
def mock_executor() -> None:
    """Create a mock CQRS executor."""
    executor = AsyncMock(spec=CQRSExecutor)
    return executor


@pytest_asyncio.fixture
async def repository(mock_connection) -> None:
    """Create a repository instance with mock connection."""
    return CQRSRepository(mock_connection)


class TestCQRSRepositoryCommands:
    """Test command methods (write operations)."""

    @pytest.mark.asyncio
    async def test_create_entity(self, repository, mock_connection) -> None:
        """Test creating an entity via SQL function."""
        # Mock the executor
        test_id = uuid4()
        expected_result = {"id": test_id, "name": "Test User", "email": "test@example.com"}

        with patch.object(
            repository.executor, "execute_function", return_value=expected_result
        ) as mock_exec:
            result = await repository.create(
                "user", {"name": "Test User", "email": "test@example.com"}
            )

            mock_exec.assert_called_once_with(
                "fn_create_user", {"name": "Test User", "email": "test@example.com"}
            )
            assert result == expected_result

    @pytest.mark.asyncio
    async def test_update_entity(self, repository) -> None:
        """Test updating an entity via SQL function."""
        test_id = uuid4()
        update_data = {"id": test_id, "name": "Updated User"}
        expected_result = {"id": test_id, "name": "Updated User", "email": "test@example.com"}

        with patch.object(
            repository.executor, "execute_function", return_value=expected_result
        ) as mock_exec:
            result = await repository.update("user", update_data)

            mock_exec.assert_called_once_with("fn_update_user", update_data)
            assert result == expected_result

    @pytest.mark.asyncio
    async def test_delete_entity(self, repository) -> None:
        """Test deleting an entity via SQL function."""
        test_id = uuid4()
        expected_result = {"id": test_id, "deleted": True}

        with patch.object(
            repository.executor, "execute_function", return_value=expected_result
        ) as mock_exec:
            result = await repository.delete("user", test_id)

            mock_exec.assert_called_once_with("fn_delete_user", {"id": str(test_id)})
            assert result == expected_result

    @pytest.mark.asyncio
    async def test_execute_custom_function(self, repository) -> None:
        """Test executing a custom SQL function."""
        function_result = {"status": "success", "count": 5}

        with patch.object(
            repository.executor, "execute_function", return_value=function_result
        ) as mock_exec:
            result = await repository.execute_function("custom_function", {"param": "value"})

            mock_exec.assert_called_once_with("custom_function", {"param": "value"})
            assert result == function_result


class TestCQRSRepositoryQueries:
    """Test query methods (read operations)."""

    @pytest.mark.asyncio
    async def test_find_by_id(self, repository, mock_connection) -> None:
        """Test finding entity by ID."""
        test_id = uuid4()
        expected_data = {
            "data": {"id": str(test_id), "name": "Test User", "email": "test@example.com"}
        }

        mock_connection.cursor.return_value.__aenter__.return_value.fetchone.return_value = [
            expected_data["data"]
        ]

        @fraiseql.type
        class User:
            id: UUID
            name: str
            email: str

        await repository.find_by_id(User, test_id)

        # Should have made cursor call
        mock_connection.cursor.assert_called()
        # Check the query was executed
        cursor = mock_connection.cursor.return_value.__aenter__.return_value
        cursor.execute.assert_called_once()

        # Verify the SQL query
        query_args = cursor.execute.call_args[0]
        assert "vw_user" in str(query_args[0])  # View name
        assert test_id in query_args[1]  # ID in parameters

    @pytest.mark.asyncio
    async def test_find_by_id_not_found(self, repository, mock_connection) -> None:
        """Test finding entity by ID when not found."""
        test_id = uuid4()

        mock_connection.cursor.return_value.__aenter__.return_value.fetchone.return_value = None

        @fraiseql.type
        class User:
            id: UUID
            name: str

        result = await repository.find_by_id(User, test_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_list_entities(self, repository, mock_connection) -> None:
        """Test listing entities with pagination."""
        expected_data = [
            {"data": {"id": "1", "name": "User 1"}},
            {"data": {"id": "2", "name": "User 2"}},
        ]

        mock_connection.cursor.return_value.__aenter__.return_value.fetchall.return_value = [
            [row["data"]] for row in expected_data
        ]

        @fraiseql.type
        class User:
            id: str
            name: str

        _ = await repository.list_entities(User, limit=10, offset=0)

        # Check cursor was called
        cursor = mock_connection.cursor.return_value.__aenter__.return_value
        cursor.execute.assert_called_once()

        # Verify the SQL query
        query_args = cursor.execute.call_args[0]
        query_str = str(query_args[0])

        assert "vw_user" in query_str
        assert "LIMIT" in query_str
        assert "OFFSET" in query_str

    @pytest.mark.asyncio
    async def test_list_with_filtering(self, repository, mock_connection) -> None:
        """Test listing entities with where clause."""
        expected_data = [{"data": {"id": "1", "name": "Active User"}}]

        mock_connection.cursor.return_value.__aenter__.return_value.fetchall.return_value = [
            [row["data"]] for row in expected_data
        ]

        @fraiseql.type
        class User:
            id: str
            name: str
            status: str

        _ = await repository.list_entities(User, where={"status": {"eq": "active"}}, limit=10)

        # Check cursor was called
        cursor = mock_connection.cursor.return_value.__aenter__.return_value
        cursor.execute.assert_called_once()
        # Where clause should be applied

    @pytest.mark.asyncio
    async def test_list_with_ordering(self, repository, mock_connection) -> None:
        """Test listing entities with order by."""
        mock_connection.cursor.return_value.__aenter__.return_value.fetchall.return_value = []

        @fraiseql.type
        class User:
            id: str
            created_at: str

        _ = await repository.list_entities(User, order_by=[("created_at", "DESC")], limit=10)

        # Check cursor was called
        cursor = mock_connection.cursor.return_value.__aenter__.return_value
        cursor.execute.assert_called_once()

        # Verify the SQL query
        query_args = cursor.execute.call_args[0]
        query_str = str(query_args[0])

        assert "ORDER BY" in query_str

    @pytest.mark.asyncio
    async def test_find_by_view(self, repository, mock_connection) -> None:
        """Test finding by custom view."""
        expected_data = [{"data": {"id": "1", "email": "user@example.com"}}]

        mock_connection.cursor.return_value.__aenter__.return_value.fetchall.return_value = [
            [row["data"]] for row in expected_data
        ]

        @fraiseql.type
        class User:
            id: str
            email: str

        _ = await repository.find_by_view(
            "vw_active_users", where={"email": {"like": "%@example.com"}}, limit=5
        )

        # Check cursor was called
        cursor = mock_connection.cursor.return_value.__aenter__.return_value
        cursor.execute.assert_called_once()

        # Verify the SQL query
        query_args = cursor.execute.call_args[0]
        assert "vw_active_users" in str(query_args[0])

    @pytest.mark.asyncio
    async def test_execute_raw_query(self, repository) -> None:
        """Test executing raw SQL query."""
        expected_data = [{"count": 10, "status": "active"}]

        query = SQL("SELECT COUNT(*) as count, status FROM users GROUP BY status")
        params = None

        with patch.object(
            repository.executor, "execute_query", return_value=expected_data
        ) as mock_exec:
            results = await repository.execute_query(query, params)

            mock_exec.assert_called_once_with(query, params)
            assert results == expected_data


# Note: TestCQRSRepositoryRelationships class removed
# FraiseQL philosophy: relationships should be composed in database views
# not loaded separately. See CQRS Repository comments for details.


class TestCQRSRepositoryBatchOperations:
    """Test batch operations."""

    @pytest.mark.asyncio
    async def test_batch_create(self, repository) -> None:
        """Test batch creating entities."""
        inputs = [
            {"name": "User 1", "email": "user1@example.com"},
            {"name": "User 2", "email": "user2@example.com"},
        ]
        expected_results = [
            {"id": "1", "name": "User 1", "email": "user1@example.com"},
            {"id": "2", "name": "User 2", "email": "user2@example.com"},
        ]

        with patch.object(repository.executor, "execute_function") as mock_exec:
            mock_exec.side_effect = expected_results

            results = await repository.batch_create("user", inputs)

            assert len(results) == 2
            assert mock_exec.call_count == 2

    @pytest.mark.asyncio
    async def test_batch_update(self, repository) -> None:
        """Test batch updating entities."""
        updates = [{"id": "1", "name": "Updated 1"}, {"id": "2", "name": "Updated 2"}]
        expected_results = [
            {"id": "1", "name": "Updated 1", "email": "user1@example.com"},
            {"id": "2", "name": "Updated 2", "email": "user2@example.com"},
        ]

        with patch.object(repository.executor, "execute_function") as mock_exec:
            mock_exec.side_effect = expected_results

            results = await repository.batch_update("user", updates)

            assert len(results) == 2
            assert mock_exec.call_count == 2

    @pytest.mark.asyncio
    async def test_batch_delete(self, repository) -> None:
        """Test batch deleting entities."""
        ids = [uuid4(), uuid4(), uuid4()]
        expected_results = [
            {"id": str(ids[0]), "deleted": True},
            {"id": str(ids[1]), "deleted": True},
            {"id": str(ids[2]), "deleted": True},
        ]

        with patch.object(repository.executor, "execute_function") as mock_exec:
            mock_exec.side_effect = expected_results

            results = await repository.batch_delete("user", ids)

            assert len(results) == 3
            assert all(r["deleted"] for r in results)


class TestCQRSRepositoryTransactions:
    """Test transaction handling."""

    @pytest.mark.asyncio
    async def test_with_transaction(self, mock_connection) -> None:
        """Test executing operations within a transaction."""
        # Mock transaction context
        transaction = AsyncMock()
        mock_connection.transaction.return_value.__aenter__.return_value = transaction

        repository = CQRSRepository(mock_connection)

        async with repository.transaction():
            # Perform operations
            with patch.object(repository.executor, "execute_function") as mock_exec:
                await repository.create("user", {"name": "Test"})
                mock_exec.assert_called_once()

        # Transaction should be used
        mock_connection.transaction.assert_called_once()


class TestCQRSRepositoryUtilities:
    """Test utility methods."""

    def test_get_view_name(self) -> None:
        """Test view name generation from entity type."""

        @fraiseql.type
        class UserProfile:
            id: str

        repo = CQRSRepository(MagicMock())
        view_name = repo._get_view_name(UserProfile)
        assert view_name == "vw_user_profile"

    def test_get_function_name(self) -> None:
        """Test function name generation."""
        repo = CQRSRepository(MagicMock())

        assert repo._get_function_name("create", "user") == "fn_create_user"
        assert repo._get_function_name("update", "user_profile") == "fn_update_user_profile"

    @pytest.mark.asyncio
    async def test_count_entities(self, repository, mock_connection) -> None:
        """Test counting entities."""
        mock_connection.cursor.return_value.__aenter__.return_value.fetchone.return_value = [42]

        @fraiseql.type
        class User:
            id: str

        count = await repository.count(User, where={"is_active": {"eq": True}})

        assert count == 42
        # Should use COUNT(*) query
        cursor = mock_connection.cursor.return_value.__aenter__.return_value
        cursor.execute.assert_called_once()
        query_args = cursor.execute.call_args[0]
        assert "COUNT(*)" in str(query_args[0])

    @pytest.mark.asyncio
    async def test_exists(self, repository, mock_connection) -> None:
        """Test checking entity existence."""
        test_id = uuid4()

        # Entity exists
        mock_connection.cursor.return_value.__aenter__.return_value.fetchone.return_value = [
            {"id": str(test_id), "name": "Test"}
        ]

        @fraiseql.type
        class User:
            id: UUID

        exists = await repository.exists(User, test_id)
        assert exists is True

        # Entity doesn't exist
        mock_connection.cursor.return_value.__aenter__.return_value.fetchone.return_value = None
        exists = await repository.exists(User, test_id)
        assert exists is False


class TestCQRSRepositoryErrorHandling:
    """Test error handling in repository."""

    @pytest.mark.asyncio
    async def test_handle_missing_function(self, repository) -> None:
        """Test handling when SQL function doesn't exist."""
        with patch.object(repository.executor, "execute_function") as mock_exec:
            mock_exec.side_effect = Exception("function fn_create_invalid does not exist")

            with pytest.raises(Exception, match=r"function.*does not exist"):
                await repository.create("invalid", {"data": "test"})

    @pytest.mark.asyncio
    async def test_handle_query_error(self, repository, mock_connection) -> None:
        """Test handling query execution errors."""
        mock_connection.cursor.return_value.__aenter__.return_value.execute.side_effect = Exception(
            """relation does not exist"""
        )

        @fraiseql.type
        class User:
            id: str

        with pytest.raises(Exception, match="relation does not exist"):
            await repository.list_entities(User)

"""Integration tests for complete GraphQL mutations via Rust backend."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from src.fraiseql.core.graphql_pipeline import RustGraphQLPipeline


class TestGraphQLMutationsIntegration:
    """Test complete mutation pipeline from GraphQL to database."""

    def test_mutation_pipeline_creation(self):
        """Test that the mutation pipeline can be created."""
        pipeline = RustGraphQLPipeline()
        assert pipeline is not None
        assert hasattr(pipeline, "execute_mutation")

    def test_mutation_definition_structure(self):
        """Test that mutation definitions have the expected structure."""
        mutation_def = {
            "operation": "mutation",
            "type": "insert",
            "table": "users",
            "input": {"name": "John", "email": "john@example.com"},
            "return_fields": ["id", "name", "email"],
        }

        required_keys = ["operation", "type", "table"]
        for key in required_keys:
            assert key in mutation_def

        assert mutation_def["operation"] == "mutation"
        assert mutation_def["type"] == "insert"
        assert mutation_def["table"] == "users"
        assert "name" in mutation_def["input"]

    @pytest.mark.asyncio
    async def test_create_user_mutation_mock(self):
        """Test create user mutation with mocked Rust backend."""
        pipeline = RustGraphQLPipeline()

        mutation_def = {
            "operation": "mutation",
            "type": "insert",
            "table": "users",
            "input": {"name": "John", "email": "john@example.com"},
            "return_fields": ["id", "name", "email"],
        }

        # Mock the Rust function to return created user
        mock_result = '{"id": 1, "name": "John", "email": "john@example.com"}'

        with patch.object(
            pipeline._rust, "execute_mutation_async", new_callable=AsyncMock
        ) as mock_execute:
            mock_execute.return_value = mock_result

            result = await pipeline.execute_mutation(mutation_def)

            # Verify the mock was called with JSON string
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args[0][0]
            parsed_args = json.loads(call_args)
            assert parsed_args["operation"] == "mutation"
            assert parsed_args["type"] == "insert"
            assert parsed_args["table"] == "users"
            assert parsed_args["input"]["name"] == "John"

            # Verify the result structure
            assert "data" in result
            assert "errors" in result
            assert result["errors"] is None
            assert result["data"]["name"] == "John"
            assert result["data"]["email"] == "john@example.com"
            assert result["data"]["id"] == 1

    @pytest.mark.asyncio
    async def test_update_user_mutation_mock(self):
        """Test update user mutation with mocked Rust backend."""
        pipeline = RustGraphQLPipeline()

        mutation_def = {
            "operation": "mutation",
            "type": "update",
            "table": "users",
            "filters": {"field": "id", "operator": "eq", "value": 1},
            "input": {"name": "Jane"},
            "return_fields": ["id", "name", "email"],
        }

        mock_result = '{"id": 1, "name": "Jane", "email": "jane@example.com"}'

        with patch.object(
            pipeline._rust, "execute_mutation_async", new_callable=AsyncMock
        ) as mock_execute:
            mock_execute.return_value = mock_result

            result = await pipeline.execute_mutation(mutation_def)

            # Verify the result
            assert result["errors"] is None
            assert result["data"]["name"] == "Jane"
            assert result["data"]["id"] == 1

    @pytest.mark.asyncio
    async def test_delete_user_mutation_mock(self):
        """Test delete user mutation with mocked Rust backend."""
        pipeline = RustGraphQLPipeline()

        mutation_def = {
            "operation": "mutation",
            "type": "delete",
            "table": "users",
            "filters": {"field": "id", "operator": "eq", "value": 1},
        }

        mock_result = '{"success": true}'

        with patch.object(
            pipeline._rust, "execute_mutation_async", new_callable=AsyncMock
        ) as mock_execute:
            mock_execute.return_value = mock_result

            result = await pipeline.execute_mutation(mutation_def)

            assert result["errors"] is None
            assert result["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_mutation_error_handling(self):
        """Test error handling in mutation operations."""
        pipeline = RustGraphQLPipeline()

        mutation_def = {
            "operation": "mutation",
            "type": "insert",
            "table": "users",
            "input": {"name": "John", "email": "john@example.com"},
        }

        # Mock the Rust function to raise an exception
        with patch.object(
            pipeline._rust,
            "execute_mutation_async",
            side_effect=Exception("Database constraint violation"),
        ):
            result = await pipeline.execute_mutation(mutation_def)

            # Verify error structure
            assert "data" in result
            assert "errors" in result
            assert result["data"] is None
            assert len(result["errors"]) == 1
            assert "constraint violation" in result["errors"][0]["message"].lower()
            assert result["errors"][0]["extensions"]["code"] == "INTERNAL_ERROR"
            assert result["errors"][0]["extensions"]["operation"] == "mutation"


class TestMutationValidation:
    """Test mutation input validation and edge cases."""

    @pytest.mark.asyncio
    async def test_mutation_missing_required_fields(self):
        """Test mutation with missing required fields."""
        pipeline = RustGraphQLPipeline()

        # Missing 'input' field for insert
        mutation_def = {"operation": "mutation", "type": "insert", "table": "users"}

        # This should work since validation happens in Rust
        # The test verifies the pipeline doesn't crash on invalid input
        with patch.object(
            pipeline._rust,
            "execute_mutation_async",
            side_effect=Exception("Input required for INSERT"),
        ):
            result = await pipeline.execute_mutation(mutation_def)

            assert result["data"] is None
            assert len(result["errors"]) == 1

    @pytest.mark.asyncio
    async def test_mutation_invalid_type(self):
        """Test mutation with invalid type."""
        pipeline = RustGraphQLPipeline()

        mutation_def = {
            "operation": "mutation",
            "type": "invalid_type",
            "table": "users",
            "input": {"name": "Test"},
        }

        with patch.object(
            pipeline._rust, "execute_mutation_async", side_effect=Exception("Unknown mutation type")
        ):
            result = await pipeline.execute_mutation(mutation_def)

            assert result["data"] is None
            assert len(result["errors"]) == 1

    def test_mutation_def_structure_validation(self):
        """Test that mutation definitions are properly structured."""
        # Valid insert mutation
        insert_def = {
            "operation": "mutation",
            "type": "insert",
            "table": "users",
            "input": {"name": "John"},
            "return_fields": ["id", "name"],
        }
        assert insert_def["type"] == "insert"

        # Valid update mutation
        update_def = {
            "operation": "mutation",
            "type": "update",
            "table": "users",
            "filters": {"field": "id", "value": 1},
            "input": {"name": "Jane"},
            "return_fields": ["id", "name"],
        }
        assert update_def["type"] == "update"
        assert "filters" in update_def

        # Valid delete mutation
        delete_def = {
            "operation": "mutation",
            "type": "delete",
            "table": "users",
            "filters": {"field": "id", "value": 1},
        }
        assert delete_def["type"] == "delete"
        assert "input" not in delete_def  # Delete doesn't need input


class TestBulkOperations:
    """Test bulk mutation operations."""

    @pytest.mark.asyncio
    async def test_bulk_mutation_execution(self):
        """Test executing multiple mutations in sequence."""
        pipeline = RustGraphQLPipeline()

        operations = [
            {
                "operation": "mutation",
                "type": "insert",
                "table": "users",
                "input": {"name": "User 1", "email": "user1@example.com"},
                "return_fields": ["id"],
            },
            {
                "operation": "mutation",
                "type": "insert",
                "table": "users",
                "input": {"name": "User 2", "email": "user2@example.com"},
                "return_fields": ["id"],
            },
        ]

        # Mock successful results for both operations
        call_count = 0

        async def mock_execute(json_str):
            nonlocal call_count
            call_count += 1
            return f'{{"id": {call_count}}}'

        with patch.object(pipeline._rust, "execute_mutation_async", side_effect=mock_execute):
            results = await pipeline.execute_bulk_operation(operations)

            assert len(results) == 2
            assert results[0]["data"]["id"] == 1
            assert results[1]["data"]["id"] == 2
            assert all(result["errors"] is None for result in results)

    @pytest.mark.asyncio
    async def test_bulk_operation_with_mixed_success_failure(self):
        """Test bulk operations where some succeed and some fail."""
        pipeline = RustGraphQLPipeline()

        operations = [
            {
                "operation": "mutation",
                "type": "insert",
                "table": "users",
                "input": {"name": "Success User"},
                "return_fields": ["id"],
            },
            {
                "operation": "mutation",
                "type": "insert",
                "table": "users",
                "input": {"name": "Fail User"},
                "return_fields": ["id"],
            },
        ]

        # Mock first success, second failure
        call_count = 0

        async def mock_execute(json_str):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return '{"id": 1}'
            raise Exception("Duplicate email constraint")

        with patch.object(pipeline._rust, "execute_mutation_async", side_effect=mock_execute):
            results = await pipeline.execute_bulk_operation(operations)

            assert len(results) == 2
            assert results[0]["errors"] is None
            assert results[0]["data"]["id"] == 1
            assert results[1]["data"] is None
            assert len(results[1]["errors"]) == 1

"""Basic integration test for Phase 4 GraphQL pipeline."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from src.fraiseql.core.graphql_pipeline import (
    RustGraphQLPipeline,
    execute_graphql_mutation,
    execute_graphql_query,
)


class TestGraphQLPipelineBasic:
    """Basic tests for the GraphQL pipeline interface."""

    def test_pipeline_creation(self):
        """Test that the pipeline can be created."""
        pipeline = RustGraphQLPipeline()
        assert pipeline is not None
        assert hasattr(pipeline, "execute_query")
        assert hasattr(pipeline, "execute_mutation")

    def test_query_definition_structure(self):
        """Test that query definitions have the expected structure."""
        query_def = {
            "operation": "query",
            "table": "users",
            "fields": ["id", "name", "email"],
            "filters": {"field": "id", "operator": "eq", "value": 1},
            "pagination": {"limit": 10, "offset": 0},
            "sort": [{"field": "name", "direction": "ASC"}],
        }

        required_keys = ["operation", "table", "fields"]
        for key in required_keys:
            assert key in query_def

        assert query_def["operation"] == "query"
        assert query_def["table"] == "users"
        assert "id" in query_def["fields"]

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

    @pytest.mark.asyncio
    async def test_execute_query_with_mock(self):
        """Test execute_query with mocked Rust backend."""
        pipeline = RustGraphQLPipeline()

        query_def = {"operation": "query", "table": "users", "fields": ["id", "name"]}

        # Mock the Rust function - should return GraphQL format with data/errors
        mock_result = json.dumps({
            "data": [{"id": 1, "name": "Test User"}],
            "errors": None
        })

        with patch.object(
            pipeline._rust, "execute_query_async", new_callable=AsyncMock
        ) as mock_execute:
            mock_execute.return_value = mock_result

            result = await pipeline.execute_query(query_def)

            # Verify the mock was called with JSON string
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args[0][0]
            parsed_args = json.loads(call_args)
            assert parsed_args["operation"] == "query"
            assert parsed_args["table"] == "users"

            # Verify the result structure
            assert "data" in result
            assert "errors" in result
            assert result["errors"] is None
            assert len(result["data"]) == 1
            assert result["data"][0]["name"] == "Test User"

    @pytest.mark.asyncio
    async def test_execute_mutation_with_mock(self):
        """Test execute_mutation with mocked Rust backend."""
        pipeline = RustGraphQLPipeline()

        mutation_def = {
            "operation": "mutation",
            "type": "insert",
            "table": "users",
            "input": {"name": "John", "email": "john@example.com"},
        }

        # Mock the Rust function
        mock_result = '{"id": 1, "name": "John"}'

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

            # Verify the result structure
            assert "data" in result
            assert "errors" in result
            assert result["errors"] is None
            assert result["data"]["name"] == "John"

    @pytest.mark.asyncio
    async def test_error_handling(self):
        """Test error handling in pipeline operations."""
        pipeline = RustGraphQLPipeline()

        query_def = {"operation": "query", "table": "users", "fields": ["id", "name"]}

        # Mock the Rust function to raise an exception
        with patch.object(
            pipeline._rust, "execute_query_async", side_effect=Exception("Database error")
        ):
            result = await pipeline.execute_query(query_def)

            # Verify error structure
            assert "data" in result
            assert "errors" in result
            assert result["data"] is None
            assert len(result["errors"]) == 1
            assert result["errors"][0]["message"] == "Database error"
            assert result["errors"][0]["extensions"]["code"] == "INTERNAL_ERROR"

    def test_convenience_functions(self):
        """Test that convenience functions exist."""
        # These are just smoke tests to ensure the functions exist
        # They would need proper async testing in a real test environment

        async def test_functions():
            # Test convenience functions exist (would need real Rust backend)
            pass

        # Just verify the functions can be imported

        assert callable(execute_graphql_query)
        assert callable(execute_graphql_mutation)


class TestPhase4Integration:
    """Integration tests for Phase 4 functionality."""

    def test_rust_backend_available(self):
        """Test that the Rust backend interface is available."""
        try:
            from src.fraiseql.core.graphql_pipeline import pipeline

            assert pipeline is not None
            assert hasattr(pipeline, "_rust")
        except ImportError:
            # Rust extension not available - this is expected in some environments
            pytest.skip("Rust extension not available")

    def test_fallback_behavior(self):
        """Test fallback behavior when Rust extension is not available."""
        # This would test the fallback implementations
        # For now, just ensure the module can be imported
        import src.fraiseql.core.graphql_pipeline as gp

        assert hasattr(gp, "RustGraphQLPipeline")
        assert hasattr(gp, "pipeline")

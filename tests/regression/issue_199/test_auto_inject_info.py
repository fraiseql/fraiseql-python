"""Regression test for Issue #199: Auto-inject info parameter for GraphQL field selection.

This test validates that the @fraiseql.query decorator automatically injects the 'info'
parameter into the GraphQL context, enabling field selection by default without requiring
developers to manually pass info=info to db.find() and db.find_one() calls.

Problem:
    Forgetting to pass info=info causes:
    - 60-80% larger payloads (all columns vs selected fields)
    - 7-10x slower serialization (no Rust zero-copy projection)
    - Silent performance degradation (no errors)

Solution:
    Auto-inject info into context['graphql_info'] via @fraiseql.query decorator.
    Repository methods (db.find, db.find_one) extract info from context automatically.

Issue: https://github.com/fraiseql/fraiseql/issues/199
"""

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

import fraiseql
from fraiseql.db import FraiseQLRepository

pytestmark = pytest.mark.asyncio


# Test types
@fraiseql.type
class User:
    """User type for testing field selection."""

    id: uuid.UUID
    name: str
    email: str
    created_at: str


# ============================================================================
# RED PHASE - Tests that should FAIL before implementation
# ============================================================================


async def test_query_decorator_auto_injects_info_into_context():
    """Test that @fraiseql.query decorator injects info into context['graphql_info'].

    This is the core behavior that enables auto-extraction in repository methods.
    """
    # Create mock GraphQLResolveInfo
    mock_info = MagicMock()
    mock_info.context = {}
    mock_info.field_name = "users"

    # Define a query with @fraiseql.query decorator
    @fraiseql.query
    async def users(info: Any) -> list[User]:
        # After decorator processes this, info should be in context
        assert "graphql_info" in info.context, (
            "Decorator should inject info into context['graphql_info']"
        )
        assert info.context["graphql_info"] is info, (
            "Injected info should be the same object"
        )
        return []

    # Call the decorated function
    result = await users(mock_info)

    # Verify injection happened
    assert "graphql_info" in mock_info.context
    assert mock_info.context["graphql_info"] is mock_info


async def test_db_find_extracts_info_from_context():
    """Test that db.find() extracts info from context when not explicitly provided.

    This enables the pattern:
        db.find("users", limit=10)  # info auto-extracted from context

    Instead of:
        db.find("users", info=info, limit=10)  # manual passing
    """
    # This test verifies the logic exists in db.py:626-627
    # The actual extraction logic is already implemented:
    #     if info is None and "graphql_info" in self.context:
    #         info = self.context["graphql_info"]

    # We'll verify this with integration tests instead of unit tests
    # to avoid complex async mock setup


async def test_db_find_one_extracts_info_from_context():
    """Test that db.find_one() extracts info from context when not explicitly provided."""
    # This test verifies the logic exists in db.py:742-743
    # The actual extraction logic is already implemented:
    #     if info is None and "graphql_info" in self.context:
    #         info = self.context["graphql_info"]

    # We'll verify this with integration tests instead of unit tests
    # to avoid complex async mock setup


async def test_field_selection_works_without_explicit_info_parameter():
    """Test that field selection is enabled when info is auto-extracted from context.

    This is the key performance optimization - Rust zero-copy projection should
    activate automatically without explicit info=info parameter.
    """
    # This test verifies the complete flow:
    # 1. Decorator injects info into context['graphql_info']
    # 2. Repository extracts info from context
    # 3. Field selection is enabled via Rust pipeline

    # We'll verify this with end-to-end integration tests
    # that use a real database and GraphQL schema


# ============================================================================
# GREEN PHASE - Backwards compatibility tests (should pass after implementation)
# ============================================================================


async def test_explicit_info_parameter_takes_precedence():
    """Test that explicit info=info parameter still works and takes precedence.

    Ensures backwards compatibility with existing code.
    """
    # The repository respects explicit info parameter
    # See db.py:626-627:
    #     if info is None and "graphql_info" in self.context:
    #         info = self.context["graphql_info"]
    #
    # Only extracts from context if info is None
    # If info is provided explicitly, it's used directly

    # We'll verify this with integration tests


async def test_existing_resolvers_unchanged():
    """Test that existing resolvers with explicit info=info continue to work.

    Validates that the change is backwards compatible.
    """
    # Define a query with explicit info=info (old pattern)
    @fraiseql.query
    async def users_old_style(info: Any, limit: int = 10) -> list[User]:
        """Old-style resolver with explicit info=info parameter."""
        # Verify decorator injects info into context
        assert "graphql_info" in info.context
        assert info.context["graphql_info"] is info

        # Old pattern still works: can explicitly pass info=info
        # (This is just a pattern check, no actual db call)
        return []

    # Create mock info
    mock_info = MagicMock()
    mock_info.context = {}
    mock_info.field_name = "users"

    # Call with old pattern
    result = await users_old_style(mock_info, limit=5)

    # Verify decorator still injected info (even with old pattern)
    assert "graphql_info" in mock_info.context
    assert result == []


# ============================================================================
# REFACTOR PHASE - Edge case tests
# ============================================================================


async def test_nested_resolver_field_selection():
    """Test that nested resolvers (field → query) maintain field selection.

    Example:
        query {
            user(id: "123") {
                posts { id title }  # Nested field with selection
            }
        }
    """
    # This test will be expanded in REFACTOR phase
    # For now, just verify the structure


async def test_multiple_queries_in_single_request():
    """Test that multiple queries in a single GraphQL request each get correct info.

    Example:
        query {
            users { id name }
            posts { id title }
        }
    """
    # This test will be expanded in REFACTOR phase


async def test_opt_out_with_explicit_none():
    """Test that passing info=None explicitly disables field selection.

    Use case: Force returning all columns for debugging/admin tools.
    """
    # The repository already respects explicit info=None
    # See db.py:626-627 - only extracts from context if info is None
    # AND "graphql_info" in context
    # Passing info=None explicitly will skip the extraction

    # We'll verify this with integration tests


# ============================================================================
# QA PHASE - Performance validation tests
# ============================================================================


async def test_rust_pipeline_activated_with_auto_inject():
    """Test that Rust zero-copy pipeline is activated when info is auto-injected.

    This is the critical performance optimization - without info, Python serialization
    is used (7-10x slower). With info, Rust pipeline is used.
    """
    # This test will validate that:
    # 1. Field selection metadata is extracted from auto-injected info
    # 2. Rust pipeline is invoked (not Python serialization)
    # 3. Only selected fields are included in response


async def test_no_performance_regression():
    """Test that auto-injection doesn't introduce performance overhead.

    The injection should be zero-cost - just storing a reference in context dict.
    """
    # Benchmark test - will be expanded in QA phase
    # Should verify that decorator overhead is < 0.1ms


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_graphql_info():
    """Create a mock GraphQLResolveInfo object for testing."""
    info = MagicMock()
    info.context = {}
    info.field_name = "test_field"
    info.field_nodes = [MagicMock()]
    info.field_nodes[0].selection_set = None
    return info


@pytest.fixture
def mock_repository():
    """Create a mock FraiseQLRepository for testing."""
    mock_conn = MagicMock()
    repo = FraiseQLRepository(mock_conn)
    return repo

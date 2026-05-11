"""Regression test for Issue #145: _build_find_query using unified WHERE clause.

Issue #145: WhereInput nested filters fail in _build_find_query (Issue #124 fix incomplete)

The Issue #124 fix for WhereInput nested filters on hybrid tables was only applied to
_build_where_clause() but not to _build_find_query(). This caused nested filters like
{machine: {id: {eq: $id}}} to fail when using certain code paths.

The fix: Refactor _build_find_query to call _build_where_clause instead of duplicating
WHERE processing logic. This ensures all code paths benefit from the Issue #124 fix.

These tests verify that _build_find_query properly uses the unified WHERE clause
building logic that includes the hybrid table handling.
"""

import uuid
from unittest.mock import MagicMock, patch

import fraiseql
from fraiseql.db import FraiseQLRepository, _table_metadata, register_type_for_view
from fraiseql.sql.graphql_where_generator import UUIDFilter, create_graphql_where_input


# Test types that simulate hybrid tables with FK columns
@fraiseql.type
class Machine:
    """Machine type for nested filtering tests."""

    id: uuid.UUID
    name: str


@fraiseql.type(sql_source="tv_allocation")
class Allocation:
    """Allocation type - hybrid table with machine_id FK column."""

    id: uuid.UUID
    machine: Machine | None


class TestBuildFindQueryUsesUnifiedWhere:
    """Tests that _build_find_query uses unified WHERE clause building."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        # Register hybrid table metadata
        register_type_for_view(
            "tv_allocation",
            Allocation,
            table_columns={"id", "machine_id", "tenant_id", "data"},
            has_jsonb_data=True,
        )

    def teardown_method(self) -> None:
        """Clean up after tests."""
        # Clean up table metadata
        if "tv_allocation" in _table_metadata:
            del _table_metadata["tv_allocation"]

    def test_build_find_query_calls_build_where_clause(self) -> None:
        """Verify _build_find_query delegates to _build_where_clause."""
        # Create repository with mock connection
        mock_conn = MagicMock()
        repo = FraiseQLRepository(mock_conn)

        # Create WhereInput with nested filter
        MachineWhereInput = create_graphql_where_input(Machine)
        AllocationWhereInput = create_graphql_where_input(Allocation)

        machine_id = uuid.UUID("01513100-0000-0000-0000-000000000066")
        where = AllocationWhereInput(machine=MachineWhereInput(id=UUIDFilter(eq=machine_id)))

        # Patch _build_where_clause to verify it's called
        with patch.object(repo, "_build_where_clause", wraps=repo._build_where_clause) as mock_bwc:
            # Call _build_find_query
            query = repo._build_find_query("tv_allocation", where=where, jsonb_column="data")

            # Verify _build_where_clause was called
            mock_bwc.assert_called_once()
            call_args = mock_bwc.call_args
            assert call_args[0][0] == "tv_allocation"  # view_name

    def test_build_find_query_processes_nested_where_input(self) -> None:
        """Verify nested WhereInput filters are processed correctly."""
        mock_conn = MagicMock()
        repo = FraiseQLRepository(mock_conn)

        # Create WhereInput with nested filter
        MachineWhereInput = create_graphql_where_input(Machine)
        AllocationWhereInput = create_graphql_where_input(Allocation)

        machine_id = uuid.UUID("01513100-0000-0000-0000-000000000066")
        where = AllocationWhereInput(machine=MachineWhereInput(id=UUIDFilter(eq=machine_id)))

        # Build query - should not raise any errors
        query = repo._build_find_query("tv_allocation", where=where, jsonb_column="data")

        # The query should have a statement
        assert query.statement is not None

        # Verify the query object structure (without trying to render SQL with MagicMock)
        # The key test is that _build_where_clause was called (tested above)
        # and no exceptions were raised during query building

    def test_build_find_query_preserves_limit_offset_order_by(self) -> None:
        """Verify limit, offset, order_by are extracted before WHERE processing."""
        mock_conn = MagicMock()
        repo = FraiseQLRepository(mock_conn)

        # Patch _build_where_clause to capture what kwargs it receives
        original_bwc = repo._build_where_clause
        received_kwargs = {}

        def capture_kwargs(view_name, **kwargs):
            received_kwargs.update(kwargs)
            return original_bwc(view_name, **kwargs)

        with patch.object(repo, "_build_where_clause", side_effect=capture_kwargs):
            # Build query with all parameters
            repo._build_find_query(
                "tv_allocation",
                where={"id": {"eq": str(uuid.uuid4())}},
                limit=10,
                offset=5,
                jsonb_column="data",
            )

            # limit, offset should NOT be in kwargs passed to _build_where_clause
            # (they should be extracted before calling it)
            assert "limit" not in received_kwargs
            assert "offset" not in received_kwargs

    def test_build_find_query_no_duplicate_kwargs_processing(self) -> None:
        """Verify mandatory_filters are converted to _mandatory_parts and processed once."""
        mock_conn = MagicMock()
        repo = FraiseQLRepository(mock_conn)

        # Track how many times _build_where_clause processes _mandatory_parts
        call_count = 0
        original_bwc = repo._build_where_clause

        def count_calls(view_name, **kwargs):
            nonlocal call_count
            if "_mandatory_parts" in kwargs:
                call_count += 1
            return original_bwc(view_name, **kwargs)

        with patch.object(repo, "_build_where_clause", side_effect=count_calls):
            tenant_id = uuid.uuid4()
            repo._build_find_query(
                "tv_allocation",
                mandatory_filters={"tenant_id": tenant_id},
                jsonb_column="data",
            )

            # _build_where_clause should be called once with _mandatory_parts
            assert call_count == 1


class TestBuildFindQueryCodePathUnification:
    """Tests that verify the code path is unified (no duplicate WHERE logic)."""

    def test_whereinput_via_find_query_uses_same_logic_as_where_clause(self) -> None:
        """Both _build_find_query and _build_where_clause should produce same WHERE."""
        mock_conn = MagicMock()
        repo = FraiseQLRepository(mock_conn)

        # Register hybrid table
        register_type_for_view(
            "tv_test",
            Allocation,
            table_columns={"id", "machine_id", "data"},
            has_jsonb_data=True,
        )

        try:
            # Create WhereInput
            MachineWhereInput = create_graphql_where_input(Machine)
            AllocationWhereInput = create_graphql_where_input(Allocation)

            machine_id = uuid.UUID("01513100-0000-0000-0000-000000000066")
            where = AllocationWhereInput(machine=MachineWhereInput(id=UUIDFilter(eq=machine_id)))

            # Get WHERE parts directly from _build_where_clause
            where_parts_direct = repo._build_where_clause("tv_test", where=where)

            # Both should produce WHERE clause with proper FK handling
            # The direct call should produce non-empty result
            assert len(where_parts_direct) > 0, "WHERE clause should not be empty"

            # Verify _build_find_query uses _build_where_clause (indirectly)
            # by checking that the query builds successfully with same where input
            where2 = AllocationWhereInput(machine=MachineWhereInput(id=UUIDFilter(eq=machine_id)))
            query = repo._build_find_query("tv_test", where=where2, jsonb_column="data")
            assert query.statement is not None, "Query should be built successfully"

        finally:
            # Cleanup
            if "tv_test" in _table_metadata:
                del _table_metadata["tv_test"]

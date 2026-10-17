"""Tests for WHERE clause normalization.

These tests define the expected behavior for converting dict and WhereInput
to canonical WhereClause representation. They will fail initially (RED phase)
and pass once normalization is implemented (GREEN phase).
"""

import uuid

from fraiseql.db import FraiseQLRepository
from fraiseql.where_clause import WhereClause


class TestDictNormalization:
    """Test dict WHERE normalization.

    These tests will FAIL until Phase 2 implements _normalize_dict_where().
    """

    def test_normalize_simple_dict(self):
        """Test normalizing simple dict WHERE clause."""
        where = {"status": {"eq": "active"}}

        # This will fail until we implement normalization
        repo = FraiseQLRepository(None)  # type: ignore
        clause = repo._normalize_where(  # type: ignore
            where, view_name="tv_allocation", table_columns={"status"}
        )

        assert isinstance(clause, WhereClause)
        assert len(clause.conditions) == 1
        assert clause.conditions[0].field_path == ["status"]
        assert clause.conditions[0].operator == "eq"
        assert clause.conditions[0].value == "active"
        assert clause.conditions[0].lookup_strategy == "sql_column"

    def test_normalize_nested_jsonb_dict(self):
        """Test normalizing nested JSONB filter."""
        where = {"device": {"name": {"eq": "Printer"}}}

        repo = FraiseQLRepository(None)  # type: ignore
        clause = repo._normalize_where(  # type: ignore
            where, view_name="tv_allocation", table_columns={"machine_id", "data"}
        )

        assert isinstance(clause, WhereClause)
        assert len(clause.conditions) == 1
        assert clause.conditions[0].field_path == ["device", "name"]
        assert clause.conditions[0].lookup_strategy == "jsonb_path"
        assert clause.conditions[0].jsonb_path == ["device", "name"]

    def test_normalize_multiple_conditions(self):
        """Test normalizing multiple conditions."""
        where = {
            "status": {"eq": "active"},
            "machine": {"id": {"eq": uuid.UUID("12345678-1234-1234-1234-123456789abc")}},
        }

        repo = FraiseQLRepository(None)  # type: ignore
        clause = repo._normalize_where(  # type: ignore
            where, view_name="tv_allocation", table_columns={"status", "machine_id", "data"}
        )

        assert len(clause.conditions) == 2
        # Should have both status and machine.id conditions

    def test_normalize_in_operator(self):
        """Test normalizing IN operator."""
        where = {"status": {"in": ["active", "pending"]}}

        repo = FraiseQLRepository(None)  # type: ignore
        clause = repo._normalize_where(  # type: ignore
            where, view_name="tv_allocation", table_columns={"status"}
        )

        assert len(clause.conditions) == 1
        assert clause.conditions[0].operator == "in"
        assert clause.conditions[0].value == ["active", "pending"]

    def test_normalize_or_clause(self):
        """Test normalizing OR logical operator."""
        where = {"OR": [{"status": {"eq": "active"}}, {"status": {"eq": "pending"}}]}

        repo = FraiseQLRepository(None)  # type: ignore
        clause = repo._normalize_where(  # type: ignore
            where, view_name="tv_allocation", table_columns={"status"}
        )

        # Should have nested OR clause
        assert len(clause.nested_clauses) == 1
        assert clause.nested_clauses[0].logical_op == "OR"
        # UPDATED: With the fix for Issue #124 complex filters, OR now preserves
        # nested WhereClause structures instead of flattening to conditions
        assert len(clause.nested_clauses[0].nested_clauses) == 2
        # Verify each nested clause has the expected condition
        for nested in clause.nested_clauses[0].nested_clauses:
            assert len(nested.conditions) == 1
            assert nested.conditions[0].operator == "eq"
            assert nested.conditions[0].value in ("active", "pending")

    def test_normalize_not_clause(self):
        """Test normalizing NOT logical operator."""
        where = {"status": {"eq": "active"}, "NOT": {"machine_id": {"isnull": True}}}

        repo = FraiseQLRepository(None)  # type: ignore
        clause = repo._normalize_where(  # type: ignore
            where, view_name="tv_allocation", table_columns={"status", "machine_id"}
        )

        assert len(clause.conditions) == 1
        assert clause.not_clause is not None
        assert len(clause.not_clause.conditions) == 1

    def test_normalize_mixed_fk_and_jsonb(self):
        """Test normalizing mixed FK and JSONB filters on same object."""
        where = {
            "machine": {
                "id": {"eq": uuid.UUID("12345678-1234-1234-1234-123456789abc")},
                "name": {"contains": "Printer"},
            }
        }

        repo = FraiseQLRepository(None)  # type: ignore
        clause = repo._normalize_where(  # type: ignore
            where, view_name="tv_allocation", table_columns={"machine_id", "data"}
        )

        assert len(clause.conditions) == 2
        # First condition should use FK
        fk_cond = next(c for c in clause.conditions if c.field_path == ["machine", "id"])
        assert fk_cond.lookup_strategy == "fk_column"
        assert fk_cond.target_column == "machine_id"

        # Second condition should use JSONB
        jsonb_cond = next(c for c in clause.conditions if c.field_path == ["machine", "name"])
        assert jsonb_cond.lookup_strategy == "jsonb_path"
        assert jsonb_cond.jsonb_path == ["machine", "name"]

    def test_normalize_contains_operator(self):
        """Test normalizing string contains operator."""
        where = {"name": {"contains": "test"}}

        repo = FraiseQLRepository(None)  # type: ignore
        clause = repo._normalize_where(  # type: ignore
            where, view_name="tv_allocation", table_columns={"name"}
        )

        assert len(clause.conditions) == 1
        assert clause.conditions[0].operator == "contains"

    def test_normalize_isnull_operator(self):
        """Test normalizing IS NULL operator."""
        where = {"machine_id": {"isnull": True}}

        repo = FraiseQLRepository(None)  # type: ignore
        clause = repo._normalize_where(  # type: ignore
            where, view_name="tv_allocation", table_columns={"machine_id"}
        )

        assert len(clause.conditions) == 1
        assert clause.conditions[0].operator == "isnull"
        assert clause.conditions[0].value is True

    def test_normalize_scalar_value_wraps_in_eq(self):
        """Test scalar value gets wrapped in eq operator."""
        where = {"status": "active"}

        repo = FraiseQLRepository(None)  # type: ignore
        clause = repo._normalize_where(  # type: ignore
            where, view_name="tv_allocation", table_columns={"status"}
        )

        assert len(clause.conditions) == 1
        assert clause.conditions[0].operator == "eq"
        assert clause.conditions[0].value == "active"

    def test_normalize_whereinput_with_string_filter(self):
        """Test normalizing WhereInput with StringFilter."""
        from fraiseql.sql import StringFilter, create_graphql_where_input
        from tests.regression.test_nested_filter_id_field import Allocation

        AllocationWhereInput = create_graphql_where_input(Allocation)

        where_input = AllocationWhereInput(status=StringFilter(eq="active"))

        repo = FraiseQLRepository(None)  # type: ignore
        clause = repo._normalize_where(  # type: ignore
            where_input, view_name="tv_allocation", table_columns={"status", "data"}
        )

        assert len(clause.conditions) == 1
        assert clause.conditions[0].operator == "eq"
        assert clause.conditions[0].value == "active"

    def test_normalize_whereinput_with_multiple_filters(self):
        """Test normalizing WhereInput with multiple fields."""
        from fraiseql.sql import StringFilter, UUIDFilter, create_graphql_where_input
        from tests.regression.test_nested_filter_id_field import Allocation, Machine

        MachineWhereInput = create_graphql_where_input(Machine)
        AllocationWhereInput = create_graphql_where_input(Allocation)

        machine_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        where_input = AllocationWhereInput(
            status=StringFilter(eq="active"),
            machine=MachineWhereInput(id=UUIDFilter(eq=machine_id)),
        )

        repo = FraiseQLRepository(None)  # type: ignore
        clause = repo._normalize_where(  # type: ignore
            where_input, view_name="tv_allocation", table_columns={"status", "machine_id", "data"}
        )

        assert len(clause.conditions) == 2

    def test_normalize_whereinput_with_or_operator(self):
        """Test normalizing WhereInput with OR operator."""
        from fraiseql.sql import StringFilter, create_graphql_where_input
        from tests.regression.test_nested_filter_id_field import Allocation

        AllocationWhereInput = create_graphql_where_input(Allocation)

        where_input = AllocationWhereInput(
            OR=[
                AllocationWhereInput(status=StringFilter(eq="active")),
                AllocationWhereInput(status=StringFilter(eq="pending")),
            ]
        )

        repo = FraiseQLRepository(None)  # type: ignore
        clause = repo._normalize_where(  # type: ignore
            where_input, view_name="tv_allocation", table_columns={"status"}
        )

        assert len(clause.nested_clauses) == 1
        assert clause.nested_clauses[0].logical_op == "OR"
        # UPDATED: With the fix for Issue #124 complex filters, OR now preserves
        # nested WhereClause structures instead of flattening to conditions
        assert len(clause.nested_clauses[0].nested_clauses) == 2
        # Verify each nested clause has the expected condition
        for nested in clause.nested_clauses[0].nested_clauses:
            assert len(nested.conditions) == 1
            assert nested.conditions[0].operator == "eq"
            assert nested.conditions[0].value in ("active", "pending")


class TestNormalizationEquivalence:
    """Test dict and WhereInput produce identical WhereClause.

    These tests will FAIL until both Phase 2 and Phase 3 are complete.
    """

    def test_dict_and_whereinput_produce_identical_whereclause(self):
        """Test dict and WhereInput normalize to identical WhereClause."""
        from fraiseql.sql import UUIDFilter, create_graphql_where_input
        from tests.regression.test_nested_filter_id_field import Allocation, Machine

        MachineWhereInput = create_graphql_where_input(Machine)
        AllocationWhereInput = create_graphql_where_input(Allocation)

        machine_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")

        # Dict version
        where_dict = {"machine": {"id": {"eq": machine_id}}}

        # WhereInput version
        where_input = AllocationWhereInput(machine=MachineWhereInput(id=UUIDFilter(eq=machine_id)))

        repo = FraiseQLRepository(None)  # type: ignore

        clause_dict = repo._normalize_where(  # type: ignore
            where_dict, view_name="tv_allocation", table_columns={"machine_id", "data"}
        )

        clause_input = repo._normalize_where(  # type: ignore
            where_input, view_name="tv_allocation", table_columns={"machine_id", "data"}
        )

        # Should be identical
        assert len(clause_dict.conditions) == len(clause_input.conditions)
        assert clause_dict.conditions[0].field_path == clause_input.conditions[0].field_path
        assert clause_dict.conditions[0].operator == clause_input.conditions[0].operator
        assert clause_dict.conditions[0].value == clause_input.conditions[0].value
        assert (
            clause_dict.conditions[0].lookup_strategy == clause_input.conditions[0].lookup_strategy
        )

"""Unit tests for WhereClause canonical representation.

These tests verify the dataclass validation, SQL generation, and edge cases
for the canonical WHERE representation.
"""

import uuid
from typing import cast

import pytest
from psycopg.sql import Composed

from fraiseql.where_clause import (
    FieldCondition,
    WhereClause,
)


class TestFieldCondition:
    """Test FieldCondition dataclass."""

    def test_create_fk_condition(self):
        """Test creating FK column condition."""
        condition = FieldCondition(
            field_path=["machine", "id"],
            operator="eq",
            value=uuid.UUID("12345678-1234-1234-1234-123456789abc"),
            lookup_strategy="fk_column",
            target_column="machine_id",
        )

        assert condition.field_path == ["machine", "id"]
        assert condition.operator == "eq"
        assert condition.lookup_strategy == "fk_column"
        assert condition.target_column == "machine_id"
        assert condition.jsonb_path is None

    def test_create_jsonb_condition(self):
        """Test creating JSONB path condition."""
        condition = FieldCondition(
            field_path=["device", "name"],
            operator="eq",
            value="Printer",
            lookup_strategy="jsonb_path",
            target_column="data",
            jsonb_path=["device", "name"],
        )

        assert condition.field_path == ["device", "name"]
        assert condition.lookup_strategy == "jsonb_path"
        assert condition.jsonb_path == ["device", "name"]

    def test_create_sql_column_condition(self):
        """Test creating direct SQL column condition."""
        condition = FieldCondition(
            field_path=["status"],
            operator="eq",
            value="active",
            lookup_strategy="sql_column",
            target_column="status",
        )

        assert condition.field_path == ["status"]
        assert condition.lookup_strategy == "sql_column"
        assert condition.target_column == "status"

    def test_invalid_operator_raises_error(self):
        """Test invalid operator raises ValueError."""
        with pytest.raises(ValueError, match="Invalid operator 'invalid'"):
            FieldCondition(
                field_path=["status"],
                operator="invalid",
                value="active",
                lookup_strategy="sql_column",
                target_column="status",
            )

    def test_invalid_lookup_strategy_raises_error(self):
        """Test invalid lookup_strategy raises ValueError."""
        with pytest.raises(ValueError, match="Invalid lookup_strategy"):
            FieldCondition(
                field_path=["status"],
                operator="eq",
                value="active",
                lookup_strategy="invalid",  # type: ignore
                target_column="status",
            )

    def test_jsonb_without_path_raises_error(self):
        """Test JSONB lookup without jsonb_path raises ValueError."""
        with pytest.raises(ValueError, match="requires jsonb_path"):
            FieldCondition(
                field_path=["device", "name"],
                operator="eq",
                value="Printer",
                lookup_strategy="jsonb_path",
                target_column="data",
                jsonb_path=None,  # Missing!
            )

    def test_empty_field_path_raises_error(self):
        """Test empty field_path raises ValueError."""
        with pytest.raises(ValueError, match="field_path cannot be empty"):
            FieldCondition(
                field_path=[],
                operator="eq",
                value="active",
                lookup_strategy="sql_column",
                target_column="status",
            )

    def test_fk_condition_to_sql(self):
        """Test FK condition generates correct SQL."""
        condition = FieldCondition(
            field_path=["machine", "id"],
            operator="eq",
            value=uuid.UUID("12345678-1234-1234-1234-123456789abc"),
            lookup_strategy="fk_column",
            target_column="machine_id",
        )

        sql, params = condition.to_sql()

        assert sql is not None
        assert isinstance(sql, Composed)
        sql_obj = cast(Composed, sql)
        sql_str = sql_obj.as_string(None)
        assert "machine_id" in sql_str
        assert "=" in sql_str
        assert len(params) == 1
        assert params[0] == uuid.UUID("12345678-1234-1234-1234-123456789abc")

    def test_jsonb_condition_to_sql(self):
        """Test JSONB condition generates correct SQL."""
        condition = FieldCondition(
            field_path=["device", "name"],
            operator="eq",
            value="Printer",
            lookup_strategy="jsonb_path",
            target_column="data",
            jsonb_path=["device", "name"],
        )

        sql, params = condition.to_sql()

        assert isinstance(sql, Composed)
        sql_str = sql.as_string(None)
        assert "data" in sql_str
        assert "'device'" in sql_str
        assert "'name'" in sql_str
        assert "->" in sql_str
        assert "->>" in sql_str
        assert len(params) == 1
        assert params[0] == "Printer"

    def test_sql_column_condition_to_sql(self):
        """Test SQL column condition generates correct SQL."""
        condition = FieldCondition(
            field_path=["status"],
            operator="eq",
            value="active",
            lookup_strategy="sql_column",
            target_column="status",
        )

        sql, params = condition.to_sql()

        assert isinstance(sql, Composed)
        assert "status" in sql.as_string(None)
        assert "=" in sql.as_string(None)
        assert len(params) == 1
        assert params[0] == "active"

    def test_in_operator_to_sql(self):
        """Test IN operator generates correct SQL."""
        condition = FieldCondition(
            field_path=["status"],
            operator="in",
            value=["active", "pending"],
            lookup_strategy="sql_column",
            target_column="status",
        )

        sql, params = condition.to_sql()

        sql_str = sql.as_string(None)
        assert "status" in sql_str
        assert "IN" in sql_str
        assert len(params) == 2  # psycopg3 uses individual placeholders
        assert params == ["active", "pending"]

    def test_isnull_operator_to_sql(self):
        """Test IS NULL operator generates correct SQL."""
        condition = FieldCondition(
            field_path=["machine_id"],
            operator="isnull",
            value=True,
            lookup_strategy="sql_column",
            target_column="machine_id",
        )

        sql, params = condition.to_sql()

        sql_str = sql.as_string(None)
        assert "machine_id" in sql_str
        assert "IS NULL" in sql_str
        assert len(params) == 0  # IS NULL has no parameters

    def test_contains_operator_to_sql(self):
        """Test LIKE operator for contains generates correct SQL."""
        condition = FieldCondition(
            field_path=["name"],
            operator="contains",
            value="test",
            lookup_strategy="sql_column",
            target_column="name",
        )

        sql, params = condition.to_sql()

        sql_str = sql.as_string(None)
        assert "name" in sql_str
        assert "LIKE" in sql_str
        assert len(params) == 1
        assert params[0] == "%test%"

    def test_startswith_operator_to_sql(self):
        """Test LIKE operator for startswith generates correct SQL."""
        condition = FieldCondition(
            field_path=["name"],
            operator="startswith",
            value="test",
            lookup_strategy="sql_column",
            target_column="name",
        )

        sql, params = condition.to_sql()

        assert sql is not None
        sql_obj = cast(Composed, sql)
        sql_str = sql_obj.as_string(None)
        assert "name" in sql_str
        assert "LIKE" in sql_str
        assert len(params) == 1
        assert params[0] == "test%"

    def test_endswith_operator_to_sql(self):
        """Test LIKE operator for endswith generates correct SQL."""
        condition = FieldCondition(
            field_path=["name"],
            operator="endswith",
            value="test",
            lookup_strategy="sql_column",
            target_column="name",
        )

        sql, params = condition.to_sql()

        assert sql is not None
        sql_obj = cast(Composed, sql)
        sql_str = sql_obj.as_string(None)
        assert "name" in sql_str
        assert "LIKE" in sql_str
        assert len(params) == 1
        assert params[0] == "%test"

    def test_icontains_operator_to_sql(self):
        """Test ILIKE operator for icontains generates correct SQL."""
        condition = FieldCondition(
            field_path=["name"],
            operator="icontains",
            value="test",
            lookup_strategy="sql_column",
            target_column="name",
        )

        sql, params = condition.to_sql()

        assert sql is not None
        sql_obj = cast(Composed, sql)
        sql_str = sql_obj.as_string(None)
        assert "name" in sql_str
        assert "ILIKE" in sql_str
        assert len(params) == 1
        assert params[0] == "%test%"

    def test_isnull_false_operator_to_sql(self):
        """Test IS NOT NULL operator generates correct SQL."""
        condition = FieldCondition(
            field_path=["machine_id"],
            operator="isnull",
            value=False,
            lookup_strategy="sql_column",
            target_column="machine_id",
        )

        sql, params = condition.to_sql()

        assert sql is not None
        sql_obj = cast(Composed, sql)
        sql_str = sql_obj.as_string(None)
        assert "machine_id" in sql_str
        assert "IS NOT NULL" in sql_str
        assert len(params) == 0  # IS NOT NULL has no parameters

    def test_repr(self):
        """Test FieldCondition repr is readable."""
        condition = FieldCondition(
            field_path=["machine", "id"],
            operator="eq",
            value="test-value",
            lookup_strategy="fk_column",
            target_column="machine_id",
        )

        repr_str = repr(condition)
        assert "machine.id" in repr_str
        assert "eq" in repr_str
        assert "test-value" in repr_str
        assert "FK:machine_id" in repr_str


class TestWhereClause:
    """Test WhereClause dataclass."""

    def test_create_simple_where_clause(self):
        """Test creating simple WHERE clause with one condition."""
        clause = WhereClause(
            conditions=[
                FieldCondition(
                    field_path=["status"],
                    operator="eq",
                    value="active",
                    lookup_strategy="sql_column",
                    target_column="status",
                )
            ]
        )

        assert len(clause.conditions) == 1
        assert clause.logical_op == "AND"
        assert len(clause.nested_clauses) == 0

    def test_create_multi_condition_where_clause(self):
        """Test creating WHERE clause with multiple conditions."""
        clause = WhereClause(
            conditions=[
                FieldCondition(
                    field_path=["status"],
                    operator="eq",
                    value="active",
                    lookup_strategy="sql_column",
                    target_column="status",
                ),
                FieldCondition(
                    field_path=["machine", "id"],
                    operator="eq",
                    value=uuid.UUID("12345678-1234-1234-1234-123456789abc"),
                    lookup_strategy="fk_column",
                    target_column="machine_id",
                ),
            ],
            logical_op="AND",
        )

        assert len(clause.conditions) == 2
        assert clause.logical_op == "AND"

    def test_create_or_where_clause(self):
        """Test creating WHERE clause with OR logic."""
        clause = WhereClause(
            conditions=[
                FieldCondition(
                    field_path=["status"],
                    operator="eq",
                    value="active",
                    lookup_strategy="sql_column",
                    target_column="status",
                ),
                FieldCondition(
                    field_path=["status"],
                    operator="eq",
                    value="pending",
                    lookup_strategy="sql_column",
                    target_column="status",
                ),
            ],
            logical_op="OR",
        )

        assert clause.logical_op == "OR"

    def test_empty_where_clause_raises_error(self):
        """Test empty WHERE clause raises ValueError."""
        with pytest.raises(ValueError, match="must have at least one condition"):
            WhereClause(conditions=[], nested_clauses=[], not_clause=None)

    def test_invalid_logical_op_raises_error(self):
        """Test invalid logical_op raises ValueError."""
        with pytest.raises(ValueError, match="Invalid logical_op"):
            WhereClause(
                conditions=[
                    FieldCondition(
                        field_path=["status"],
                        operator="eq",
                        value="active",
                        lookup_strategy="sql_column",
                        target_column="status",
                    )
                ],
                logical_op="XOR",  # type: ignore # Invalid
            )

    def test_simple_where_clause_to_sql(self):
        """Test simple WHERE clause generates correct SQL."""
        clause = WhereClause(
            conditions=[
                FieldCondition(
                    field_path=["status"],
                    operator="eq",
                    value="active",
                    lookup_strategy="sql_column",
                    target_column="status",
                )
            ]
        )

        sql, params = clause.to_sql()

        assert sql is not None
        sql_str = sql.as_string(None)
        assert "status" in sql_str
        assert "=" in sql_str
        assert len(params) == 1
        assert params[0] == "active"

    def test_multi_condition_where_clause_to_sql(self):
        """Test multi-condition WHERE clause generates correct SQL."""
        clause = WhereClause(
            conditions=[
                FieldCondition(
                    field_path=["status"],
                    operator="eq",
                    value="active",
                    lookup_strategy="sql_column",
                    target_column="status",
                ),
                FieldCondition(
                    field_path=["machine", "id"],
                    operator="eq",
                    value=uuid.UUID("12345678-1234-1234-1234-123456789abc"),
                    lookup_strategy="fk_column",
                    target_column="machine_id",
                ),
            ],
            logical_op="AND",
        )

        sql, params = clause.to_sql()

        assert sql is not None
        sql_str = sql.as_string(None)
        assert "status" in sql_str
        assert "machine_id" in sql_str
        assert "AND" in sql_str
        assert len(params) == 2

    def test_or_where_clause_to_sql(self):
        """Test OR WHERE clause generates correct SQL."""
        clause = WhereClause(
            conditions=[
                FieldCondition(
                    field_path=["status"],
                    operator="eq",
                    value="active",
                    lookup_strategy="sql_column",
                    target_column="status",
                ),
                FieldCondition(
                    field_path=["status"],
                    operator="eq",
                    value="pending",
                    lookup_strategy="sql_column",
                    target_column="status",
                ),
            ],
            logical_op="OR",
        )

        sql, _params = clause.to_sql()

        sql_str = sql.as_string(None)
        assert "OR" in sql_str

    def test_nested_where_clause_to_sql(self):
        """Test nested WHERE clause generates correct SQL with parentheses."""
        clause = WhereClause(
            conditions=[
                FieldCondition(
                    field_path=["machine", "id"],
                    operator="eq",
                    value=uuid.UUID("12345678-1234-1234-1234-123456789abc"),
                    lookup_strategy="fk_column",
                    target_column="machine_id",
                ),
            ],
            nested_clauses=[
                WhereClause(
                    conditions=[
                        FieldCondition(
                            field_path=["status"],
                            operator="eq",
                            value="active",
                            lookup_strategy="sql_column",
                            target_column="status",
                        ),
                        FieldCondition(
                            field_path=["status"],
                            operator="eq",
                            value="pending",
                            lookup_strategy="sql_column",
                            target_column="status",
                        ),
                    ],
                    logical_op="OR",
                )
            ],
        )

        sql, _params = clause.to_sql()

        sql_str = sql.as_string(None)
        assert "machine_id" in sql_str
        assert "status" in sql_str
        assert "OR" in sql_str
        assert "(" in sql_str  # Nested clause should be wrapped
        assert ")" in sql_str

    def test_not_clause_to_sql(self):
        """Test NOT clause generates correct SQL."""
        clause = WhereClause(
            conditions=[
                FieldCondition(
                    field_path=["status"],
                    operator="eq",
                    value="active",
                    lookup_strategy="sql_column",
                    target_column="status",
                ),
            ],
            not_clause=WhereClause(
                conditions=[
                    FieldCondition(
                        field_path=["machine_id"],
                        operator="isnull",
                        value=True,
                        lookup_strategy="sql_column",
                        target_column="machine_id",
                    ),
                ]
            ),
        )

        sql, _params = clause.to_sql()

        sql_str = sql.as_string(None)
        assert "NOT" in sql_str
        assert "(" in sql_str
        assert "machine_id" in sql_str

    def test_repr(self):
        """Test WhereClause repr is readable."""
        clause = WhereClause(
            conditions=[
                FieldCondition(
                    field_path=["status"],
                    operator="eq",
                    value="active",
                    lookup_strategy="sql_column",
                    target_column="status",
                ),
            ]
        )

        repr_str = repr(clause)
        assert "WhereClause" in repr_str
        assert "status" in repr_str

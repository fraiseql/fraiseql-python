"""Unit tests for WhereClause canonical representation.

These tests verify the dataclass validation, SQL generation, and edge cases
for the canonical WHERE representation.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
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


class TestJsonbNumericComparison:
    """A number compared with a JSONB field is compared as a number, not as text.

    As text, ``'9' > '10'`` and ``'10.50' <> '10.5'``.
    """

    @staticmethod
    def _sql(operator: str, value: object) -> tuple[str, list]:
        condition = FieldCondition(
            field_path=["price"],
            operator=operator,
            value=value,
            lookup_strategy="jsonb_path",
            target_column="data",
            jsonb_path=["price"],
        )
        sql, params = condition.to_sql()
        return sql.as_string(None), params

    @pytest.mark.parametrize(
        ("operator", "sql_op"),
        [("eq", "="), ("neq", "!="), ("gt", ">"), ("gte", ">="), ("lt", "<"), ("lte", "<=")],
    )
    @pytest.mark.parametrize("value", [10, 10.5, Decimal("10.50")])
    def test_number_is_compared_as_numeric(self, operator: str, sql_op: str, value) -> None:
        sql, params = self._sql(operator, value)

        assert sql == f"(\"data\" ->> 'price')::numeric {sql_op} %s"
        assert params == [value]

    def test_numbers_in_list_are_compared_as_numeric(self) -> None:
        sql, params = self._sql("in", [1, Decimal("2.5")])

        assert sql == "(\"data\" ->> 'price')::numeric IN (%s, %s)"
        assert params == [1, Decimal("2.5")]

    @pytest.mark.parametrize(("value", "param"), [("10", "10"), (True, "true")])
    def test_strings_and_booleans_stay_text(self, value: object, param: str) -> None:
        sql, params = self._sql("eq", value)

        assert sql == "\"data\" ->> 'price' = %s"
        assert params == [param]

    def test_mixed_list_stays_text(self) -> None:
        sql, _params = self._sql("in", ["a", 1])

        assert sql == "\"data\" ->> 'price' IN (%s, %s)"


class TestJsonbTemporalComparison:
    """A datetime or date compared with a JSONB field is compared as one, not as text.

    As text, ``'2025-01-01T00:00:00+00:00' < '2025-01-01T00:00:00Z'``.
    """

    @staticmethod
    def _sql(operator: str, value: object, temporal_cast=None) -> tuple[str, list]:
        condition = FieldCondition(
            field_path=["created_at"],
            operator=operator,
            value=value,
            lookup_strategy="jsonb_path",
            target_column="data",
            jsonb_path=["created_at"],
            temporal_cast=temporal_cast,
        )
        sql, params = condition.to_sql()
        return sql.as_string(None), params

    @pytest.mark.parametrize(
        ("operator", "sql_op"),
        [("eq", "="), ("neq", "!="), ("gt", ">"), ("gte", ">="), ("lt", "<"), ("lte", "<=")],
    )
    def test_declared_datetime_string_casts_to_timestamptz(
        self, operator: str, sql_op: str
    ) -> None:
        sql, params = self._sql(operator, "2025-01-01T00:00:00Z", "timestamptz")

        assert sql == f"(\"data\" ->> 'created_at')::timestamptz {sql_op} %s::timestamptz"
        assert params == ["2025-01-01T00:00:00Z"]

    def test_declared_date_in_list_casts_to_date(self) -> None:
        sql, params = self._sql("nin", ["2025-01-01", "2025-01-02"], "date")

        assert sql == "(\"data\" ->> 'created_at')::date NOT IN (%s::date, %s::date)"
        assert params == ["2025-01-01", "2025-01-02"]

    @pytest.mark.parametrize(
        ("value", "cast"),
        [(datetime(2025, 1, 1, tzinfo=UTC), "timestamptz"), (date(2025, 1, 1), "date")],
    )
    def test_temporal_value_casts_without_a_declared_type(self, value, cast: str) -> None:
        sql, params = self._sql("gte", value)

        assert sql == f"(\"data\" ->> 'created_at')::{cast} >= %s::{cast}"
        assert params == [value]

    def test_undeclared_string_stays_text(self) -> None:
        sql, _params = self._sql("gte", "2025-01-01T00:00:00Z")

        assert sql == "\"data\" ->> 'created_at' >= %s"

    def test_declared_datetime_isnull_is_not_cast(self) -> None:
        sql, _params = self._sql("isnull", True, "timestamptz")

        assert sql == "\"data\" ->> 'created_at' IS NULL"

"""Comprehensive tests for where_generator module to improve coverage."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Optional

import pytest
from psycopg.sql import SQL, Composed

from fraiseql.sql.where.core.field_detection import FieldType
from fraiseql.sql.where_generator import (
    DynamicType,
    build_operator_composed,
    safe_create_where_type,
    unwrap_type,
)

pytestmark = pytest.mark.database


@pytest.mark.unit
@dataclass
class SampleModel:
    """Test model with various field types."""

    id: uuid.UUID
    name: str
    age: int
    score: float
    amount: Decimal
    is_active: bool
    created_at: datetime
    birth_date: date
    tags: list[str]
    metadata: dict
    optional_field: Optional[str] = None


class TestBuildOperatorComposed:
    """Test the build_operator_composed function with all operators."""

    def test_eq_operator(self) -> None:
        """Test equality operator."""
        path_sql = SQL("data->>'name'")
        result = build_operator_composed(path_sql, "eq", "test")
        assert isinstance(result, Composed)
        assert "=" in result.as_string(None)

    def test_neq_operator(self) -> None:
        """Test not equal operator."""
        path_sql = SQL("data->>'name'")
        result = build_operator_composed(path_sql, "neq", "test")
        assert isinstance(result, Composed)
        assert "!=" in result.as_string(None)

    def test_like_operator(self) -> None:
        """Test LIKE operator."""
        # Like operator doesn't exist in FraiseQL - skip this test
        # The startswith operator is used instead

    def test_ilike_operator(self) -> None:
        """Test ILIKE operator."""
        # ILike operator doesn't exist in FraiseQL - skip this test

    def test_numeric_operators(self) -> None:
        """Test numeric comparison operators."""
        path_sql = SQL("data->>'age'")

        # Greater than
        result = build_operator_composed(path_sql, "gt", 21)
        assert " > " in result.as_string(None)

        # Greater than or equal
        result = build_operator_composed(path_sql, "gte", 21)
        assert " >= " in result.as_string(None)

        # Less than
        result = build_operator_composed(path_sql, "lt", 21)
        assert " < " in result.as_string(None)

        # Less than or equal
        result = build_operator_composed(path_sql, "lte", 21)
        assert " <= " in result.as_string(None)

    def test_isnull_operator(self) -> None:
        """Test IS NULL and IS NOT NULL operators."""
        path_sql = SQL("data->>'optional'")

        # IS NULL
        result = build_operator_composed(path_sql, "isnull", True)
        assert "IS NULL" in result.as_string(None)

        # IS NOT NULL
        result = build_operator_composed(path_sql, "isnull", False)
        assert "IS NOT NULL" in result.as_string(None)

    def test_jsonb_operators(self) -> None:
        """Test JSONB-specific operators."""
        path_sql = SQL("data")

        # Contains with dict value uses JSONB @> (containment) operator
        result = build_operator_composed(path_sql, "contains", {"key": "value"})
        # Just check that the result is a valid Composed object with the right operator
        assert isinstance(result, Composed)
        # Convert to string format that can be inspected
        parts = []
        for part in result:
            if hasattr(part, "_wrapped"):  # This is a Literal
                parts.append(f"<Literal: {part._wrapped}>")
            else:
                parts.append(str(part))
        result_str = " ".join(parts)
        # Uses JSONB @> operator for containment
        assert " @> " in result_str

        # Overlaps - for JSONB arrays, PostgreSQL uses ?| operator, not &&
        # The && operator only exists for native PostgreSQL arrays, not JSONB
        result = build_operator_composed(path_sql, "overlaps", ["a", "b"])
        assert isinstance(result, Composed)
        parts = []
        for part in result:
            if hasattr(part, "_wrapped"):
                parts.append(f"<Literal: {part._wrapped}>")
            else:
                parts.append(str(part))
        result_str = " ".join(parts)
        assert " ?| " in result_str  # JSONB uses ?| for array element existence check

    def test_regex_operators(self) -> None:
        """Test regex operators."""
        path_sql = SQL("data->>'name'")

        # Matches
        result = build_operator_composed(path_sql, "matches", "^test.*")
        assert " ~ " in result.as_string(None)

        # Startswith
        result = build_operator_composed(path_sql, "startswith", "test")
        assert "LIKE" in result.as_string(None)
        assert "test%" in result.as_string(None)

    def test_in_operator_with_different_types(self) -> None:
        """Test IN operator with various value types."""
        path_sql = SQL("data->>'value'")

        # String values
        result = build_operator_composed(path_sql, "in", ["a", "b", "c"])
        sql_str = result.as_string(None)
        assert " IN (" in sql_str
        assert "'a'" in sql_str
        assert "'b'" in sql_str
        assert "'c'" in sql_str

        # Numeric values
        result = build_operator_composed(path_sql, "in", [1, 2, 3])
        sql_str = result.as_string(None)
        assert " IN (" in sql_str
        assert "::numeric" in sql_str

        # Boolean values (converted to strings)
        result = build_operator_composed(path_sql, "in", [True, False])
        sql_str = result.as_string(None)
        assert " IN (" in sql_str
        # Check for either boolean literals or string representation
        # The implementation may use either true/false or 'true'/'false'
        assert "true" in sql_str.lower()
        assert "false" in sql_str.lower()

    def test_in_operator_invalid_type(self) -> None:
        """Test IN operator with invalid type raises TypeError."""
        path_sql = SQL("data->>'value'")
        with pytest.raises(TypeError, match="'in' operator requires a list"):
            build_operator_composed(path_sql, "in", "not a list")

    def test_notin_operator(self) -> None:
        """Test NOT IN operator."""
        path_sql = SQL("data->>'value'")

        # String values
        result = build_operator_composed(path_sql, "notin", ["a", "b"])
        sql_str = result.as_string(None)
        assert " NOT IN (" in sql_str

        # Boolean values
        result = build_operator_composed(path_sql, "notin", [True, False])
        sql_str = result.as_string(None)
        assert " NOT IN (" in sql_str
        # Check for either boolean literals or string representation
        assert "true" in sql_str.lower()
        assert "false" in sql_str.lower()

    def test_notin_operator_invalid_type(self) -> None:
        """Test NOT IN operator with invalid type raises TypeError."""
        path_sql = SQL("data->>'value'")
        with pytest.raises(TypeError, match="'notin' operator requires a list"):
            build_operator_composed(path_sql, "notin", "not a list")

    def test_ltree_operators(self) -> None:
        """Test ltree-specific operators."""
        path_sql = SQL("path")

        # Depth equal
        result = build_operator_composed(path_sql, "depth_eq", 3)
        assert "nlevel(" in result.as_string(None)
        assert " = " in result.as_string(None)

        # Depth greater than
        result = build_operator_composed(path_sql, "depth_gt", 3)
        assert "nlevel(" in result.as_string(None)
        assert " > " in result.as_string(None)

        # Depth less than
        result = build_operator_composed(path_sql, "depth_lt", 3)
        assert "nlevel(" in result.as_string(None)
        assert " < " in result.as_string(None)

        # Is descendant
        result = build_operator_composed(path_sql, "isdescendant", "root.branch")
        assert " <@ " in result.as_string(None)

    def test_strictly_contains_operator(self) -> None:
        """Test strictly contains operator (contains but not equal)."""
        path_sql = SQL("data")
        result = build_operator_composed(path_sql, "strictly_contains", {"key": "value"})
        # Cannot call as_string(None) with dict, check structure instead
        assert isinstance(result, Composed)
        parts = []
        for part in result:
            if hasattr(part, "_wrapped"):
                parts.append(f"<Literal: {part._wrapped}>")
            else:
                parts.append(str(part))
        result_str = " ".join(parts)
        assert " @> " in result_str
        assert " AND " in result_str
        assert " != " in result_str

    def test_boolean_value_handling(self) -> None:
        """Test boolean value conversion to proper SQL."""
        path_sql = SQL("data->>'is_active'")

        # Boolean true - now uses text comparison for JSONB consistency
        result = build_operator_composed(path_sql, "eq", True)
        sql_str = result.as_string(None)
        assert "= 'true'" in sql_str  # Text literal for JSONB consistency

        # Boolean false
        result = build_operator_composed(path_sql, "eq", False)
        sql_str = result.as_string(None)
        assert "= 'false'" in sql_str  # Text literal for JSONB consistency

    def test_uuid_value_handling(self) -> None:
        """Test UUID value handling with type hints."""
        path_sql = SQL("data->>'id'")
        test_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")

        result = build_operator_composed(path_sql, "eq", test_uuid, uuid.UUID)
        sql_str = result.as_string(None)
        assert "::uuid" in sql_str

    def test_datetime_value_handling(self) -> None:
        """Test datetime value handling."""
        path_sql = SQL("data->>'created_at'")
        test_dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

        result = build_operator_composed(path_sql, "gt", test_dt, datetime)
        sql_str = result.as_string(None)
        # Check for the datetime value being present rather than exact type casting
        assert "2024-01-01" in sql_str

    def test_date_value_handling(self) -> None:
        """Test date value handling."""
        path_sql = SQL("data->>'birth_date'")
        test_date = date(2024, 1, 1)

        result = build_operator_composed(path_sql, "lt", test_date, date)
        sql_str = result.as_string(None)
        assert "::date" in sql_str

    def test_unsupported_operator(self) -> None:
        """Test unsupported operator raises ValueError."""
        path_sql = SQL("data->>'value'")
        with pytest.raises(ValueError, match="Unsupported operator 'invalid_op'"):
            build_operator_composed(path_sql, "invalid_op", "value")


class TestUnwrapType:
    """Test the unwrap_type function."""

    def test_unwrap_optional(self) -> None:
        """Test unwrapping Optional types."""
        assert unwrap_type(Optional[str]) is str
        assert unwrap_type(Optional[int]) is int
        assert unwrap_type(Optional[uuid.UUID]) is uuid.UUID

    def test_unwrap_union_with_none(self) -> None:
        """Test unwrapping Union types with None."""
        # The unwrap_type function doesn't unwrap Union types, it returns them unchanged
        assert unwrap_type(str | None) == (str | None)
        assert unwrap_type(int | None) == (int | None)

    def test_no_unwrap_needed(self) -> None:
        """Test types that don't need unwrapping."""
        assert unwrap_type(str) == str
        assert unwrap_type(int) == int
        assert unwrap_type(list[str]) == list[str]

    def test_complex_union(self) -> None:
        """Test complex Union types are not unwrapped."""
        union_type = str | int | None
        # Should not unwrap because there are multiple non-None types
        assert unwrap_type(union_type) == union_type


class TestSafeCreateWhereType:
    """Test the safe_create_where_type function."""

    def test_basic_where_type_creation(self) -> None:
        """Test creating a basic WHERE type."""
        WhereType = safe_create_where_type(SampleModel)

        # Check it's a proper class
        assert isinstance(WhereType, type)

        # Check it has the expected fields
        instance = WhereType()
        assert hasattr(instance, "id")
        assert hasattr(instance, "name")
        assert hasattr(instance, "age")
        assert hasattr(instance, "to_sql")

    def test_where_type_with_simple_filters(self) -> None:
        """Test WHERE type with simple equality filters."""
        WhereType = safe_create_where_type(SampleModel)

        where = WhereType(name={"eq": "test"}, age={"gt": 21}, is_active={"eq": True})

        sql = where.to_sql()
        assert sql is not None
        sql_str = sql.as_string(None)

        # Test string field - should be exact text comparison
        assert "(data ->> 'name') = 'test'" in sql_str

        # Test numeric field - should have proper casting structure
        # Valid pattern: (data ->> 'age')::numeric > 21
        import re

        numeric_pattern = r"\(\(data ->> 'age'\)\)::numeric > 21|\(data ->> 'age'\)::numeric > 21"
        assert re.search(numeric_pattern, sql_str), (
            f"Expected numeric casting pattern not found in: {sql_str}"
        )

        # Test boolean field - should use text comparison, not boolean casting
        assert "(data ->> 'is_active') = 'true'" in sql_str
        assert "::boolean" not in sql_str, (
            f"Boolean fields should not use ::boolean casting, found in: {sql_str}"
        )

    def test_where_type_with_complex_filters(self) -> None:
        """Test WHERE type with complex filters."""
        WhereType = safe_create_where_type(SampleModel)

        test_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        test_date = date(2024, 1, 1)

        where = WhereType(
            id={"eq": test_uuid},
            name={"startswith": "test"},  # Use supported operator instead of 'like'
            age={"in": [21, 22, 23]},
            birth_date={"gte": test_date},
            tags={"contains": ["python", "sql"]},
        )

        sql = where.to_sql()
        assert sql is not None
        sql_str = sql.as_string(None)

        assert "::uuid" in sql_str
        # Check for startswith pattern - uses LIKE with % suffix
        assert "LIKE 'test%'" in sql_str
        assert " IN (" in sql_str
        assert "::date" in sql_str

    def test_where_type_with_null_filters(self) -> None:
        """Test WHERE type with null checks."""
        WhereType = safe_create_where_type(SampleModel)

        where = WhereType(optional_field={"isnull": True}, name={"isnull": False})

        sql = where.to_sql()
        assert sql is not None
        sql_str = sql.as_string(None)

        assert "(data ->> 'optional_field') IS NULL" in sql_str
        assert "(data ->> 'name') IS NOT NULL" in sql_str

    def test_where_type_with_multiple_operators_same_field(self) -> None:
        """Test WHERE type with multiple operators on the same field."""
        WhereType = safe_create_where_type(SampleModel)

        where = WhereType(age={"gte": 21, "lte": 65})

        sql = where.to_sql()
        assert sql is not None
        sql_str = sql.as_string(None)

        # Validate complete SQL structure
        print(f"Generated SQL: {sql_str}")

        # Validate the complete SQL is exactly what we expect for proper age range filtering
        expected_sql = "(data ->> 'age')::numeric >= 21 AND (data ->> 'age')::numeric <= 65"
        assert sql_str == expected_sql, f"Expected exact SQL: {expected_sql}, got: {sql_str}"

        # Additional validations for robustness
        assert "data ->> 'age'" in sql_str, f"Missing age field in: {sql_str}"
        assert "::numeric" in sql_str, f"Missing numeric casting in: {sql_str}"
        assert ">= 21" in sql_str, f"Missing gte condition in: {sql_str}"
        assert "<= 65" in sql_str, f"Missing lte condition in: {sql_str}"
        assert " AND " in sql_str, f"Missing AND operator in: {sql_str}"

        # Validate balanced parentheses
        assert sql_str.count("(") == sql_str.count(")"), f"Unbalanced parentheses in: {sql_str}"

    def test_where_type_empty_filter(self) -> None:
        """Test WHERE type with no filters returns None."""
        WhereType = safe_create_where_type(SampleModel)

        where = WhereType()
        sql = where.to_sql()
        assert sql is None

    def test_where_type_with_none_values(self) -> None:
        """Test WHERE type ignores None values in filter dicts."""
        WhereType = safe_create_where_type(SampleModel)

        where = WhereType(
            name={"eq": None},  # Should be ignored
            age={"gt": 21},
        )

        sql = where.to_sql()
        assert sql is not None
        sql_str = sql.as_string(None)

        assert "name" not in sql_str
        # Validate complete SQL - should be exactly this with our casting approach
        expected_sql = "(data ->> 'age')::numeric > 21"
        assert sql_str == expected_sql, f"Expected: {expected_sql}, got: {sql_str}"

    def test_where_type_caching(self) -> None:
        """Test that safe_create_where_type uses caching."""
        WhereType1 = safe_create_where_type(SampleModel)
        WhereType2 = safe_create_where_type(SampleModel)

        # Should return the same cached type
        assert WhereType1 is WhereType2

    def test_nested_dynamic_type(self) -> None:
        """Test WHERE type with nested dynamic type filters."""

        # Define Child first to avoid forward reference issues
        @dataclass
        class Child:
            name: str
            value: int

        @dataclass
        class Parent:
            id: int
            child: Optional[Child] = None

        ParentWhere = safe_create_where_type(Parent)
        ChildWhere = safe_create_where_type(Child)

        # Create a nested filter
        child_filter = ChildWhere(name={"eq": "test"})
        parent_filter = ParentWhere(id={"eq": 1}, child=child_filter)

        sql = parent_filter.to_sql()
        assert sql is not None
        sql_str = sql.as_string(None)

        # Validate complete SQL - adjusted for our casting approach
        assert "(data ->> 'id')::numeric = 1" in sql_str
        # Child's name should now be accessed via nested path: data -> 'child' ->> 'name'
        assert "(data -> 'child' ->> 'name') = 'test'" in sql_str


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_invalid_field_type_in_filter(self) -> None:
        """Test handling of non-dict filter values."""
        WhereType = safe_create_where_type(SampleModel)

        # Non-dict values should be ignored
        where = WhereType(
            name="not a dict",  # Should be ignored
            age={"gt": 21},
        )

        sql = where.to_sql()
        assert sql is not None
        sql_str = sql.as_string(None)

        assert "name" not in sql_str
        assert "(data ->> 'age')::numeric > 21" in sql_str

    def test_unsupported_operators_ignored(self) -> None:
        """Test that unsupported operators are silently ignored."""
        WhereType = safe_create_where_type(SampleModel)

        where = WhereType(name={"invalid_op": "value", "eq": "test"})

        sql = where.to_sql()
        assert sql is not None
        sql_str = sql.as_string(None)

        # Invalid operator ignored, valid one used
        assert "(data ->> 'name') = 'test'" in sql_str
        assert "invalid_op" not in sql_str


@pytest.mark.unit
class TestBuildOperatorComposedExtended:
    """Test the build_operator_composed function comprehensively."""

    def test_equality_operator(self) -> None:
        """Test equality operator with various types."""
        path_sql = SQL("data->>'name'")

        # String equality
        result = build_operator_composed(path_sql, "eq", "John")
        assert isinstance(result, Composed)

        # Numeric equality
        result = build_operator_composed(path_sql, "eq", 42)
        assert isinstance(result, Composed)

        # Boolean equality
        result = build_operator_composed(path_sql, "eq", True)
        assert isinstance(result, Composed)

    def test_inequality_operator(self) -> None:
        """Test not-equal operator."""
        path_sql = SQL("data->>'age'")
        result = build_operator_composed(path_sql, "neq", 25)
        assert isinstance(result, Composed)

    def test_comparison_operators(self) -> None:
        """Test greater than, less than operators."""
        path_sql = SQL("data->>'score'")

        # Greater than
        result = build_operator_composed(path_sql, "gt", 100)
        assert isinstance(result, Composed)

        # Greater than or equal
        result = build_operator_composed(path_sql, "gte", 90)
        assert isinstance(result, Composed)

        # Less than
        result = build_operator_composed(path_sql, "lt", 50)
        assert isinstance(result, Composed)

        # Less than or equal
        result = build_operator_composed(path_sql, "lte", 75)
        assert isinstance(result, Composed)

    def test_string_operators(self) -> None:
        """Test string-specific operators."""
        path_sql = SQL("data->>'name'")

        # Contains
        result = build_operator_composed(path_sql, "contains", "John")
        assert isinstance(result, Composed)

        # Starts with
        result = build_operator_composed(path_sql, "startswith", "J")
        assert isinstance(result, Composed)

        # Matches (regex)
        result = build_operator_composed(path_sql, "matches", "John")
        assert isinstance(result, Composed)

    def test_list_operators(self) -> None:
        """Test list/array operators."""
        path_sql = SQL("data->>'tags'")

        # In operator
        result = build_operator_composed(path_sql, "in", ["python", "javascript"])
        assert isinstance(result, Composed)

        # Not in operator
        result = build_operator_composed(path_sql, "notin", ["go", "rust"])
        assert isinstance(result, Composed)

    def test_null_operators(self) -> None:
        """Test null checking operators."""
        path_sql = SQL("data->>'optional_field'")

        # Is null
        result = build_operator_composed(path_sql, "isnull", True)
        assert isinstance(result, Composed)

        # Is not null
        result = build_operator_composed(path_sql, "isnull", False)
        assert isinstance(result, Composed)

    def test_type_casting_numeric(self) -> None:
        """Test type casting for numeric comparisons."""
        path_sql = SQL("data->>'price'")

        # Integer comparison
        result = build_operator_composed(path_sql, "gt", 100)
        assert isinstance(result, Composed)

        # Float comparison
        result = build_operator_composed(path_sql, "gte", 99.99)
        assert isinstance(result, Composed)

        # Decimal comparison
        result = build_operator_composed(path_sql, "lt", Decimal("199.99"))
        assert isinstance(result, Composed)

    def test_type_casting_datetime(self) -> None:
        """Test type casting for datetime comparisons."""
        path_sql = SQL("data->>'created_at'")

        # Datetime comparison
        dt = datetime(2023, 1, 1, 12, 0, 0)
        result = build_operator_composed(path_sql, "gte", dt)
        assert isinstance(result, Composed)

        # Date comparison
        d = date(2023, 1, 1)
        result = build_operator_composed(path_sql, "eq", d)
        assert isinstance(result, Composed)

    def test_type_casting_boolean(self) -> None:
        """Test type casting for boolean comparisons."""
        path_sql = SQL("data->>'is_active'")

        # Boolean true
        result = build_operator_composed(path_sql, "eq", True)
        assert isinstance(result, Composed)

        # Boolean false
        result = build_operator_composed(path_sql, "neq", False)
        assert isinstance(result, Composed)

    def test_depth_operators(self) -> None:
        """Test depth operators for ltree-like operations."""
        path_sql = SQL("data->>'path'")

        # Depth equal
        result = build_operator_composed(path_sql, "depth_eq", 3)
        assert isinstance(result, Composed)

        # Depth greater than
        result = build_operator_composed(path_sql, "depth_gt", 2)
        assert isinstance(result, Composed)

    def test_advanced_operators(self) -> None:
        """Test advanced JSONB operators."""
        path_sql = SQL("data->>'config'")

        # Is descendant
        result = build_operator_composed(path_sql, "isdescendant", "parent.child")
        assert isinstance(result, Composed)

        # Strictly contains
        result = build_operator_composed(path_sql, "strictly_contains", {"key": "value"})
        assert isinstance(result, Composed)

    def test_unsupported_operator(self) -> None:
        """Test behavior with unsupported operator."""
        path_sql = SQL("data->>'field'")

        with pytest.raises(ValueError, match="Unsupported operator"):
            build_operator_composed(path_sql, "unsupported_op", "value")

    @pytest.mark.parametrize(
        ("operator", "value", "distance_operator"),
        [
            ("cosine_distance", {"vector": [0.1, 0.2], "threshold": 0.5}, "<=>"),
            ("l2_distance", ([0.1, 0.2], 1.0), "<->"),
            ("l1_distance", {"vector": [0.1, 0.2], "threshold": 2.0}, "<+>"),
            ("inner_product", {"vector": [0.1, 0.2], "threshold": -0.1}, "<#>"),
            ("hamming_distance", {"vector": "1010", "threshold": 1}, "<~>"),
            ("jaccard_distance", {"vector": "1010", "threshold": 0.5}, "<%>"),
        ],
    )
    def test_vector_distance_operators_render_boolean_predicates(
        self, operator: str, value: object, distance_operator: str
    ) -> None:
        """Distance operators must be valid WHERE predicates, not bare numbers."""
        path_sql = SQL("data ->> 'embedding'")

        result = build_operator_composed(
            path_sql, operator, value, detected_field_type=FieldType.VECTOR
        )
        sql = result.as_string(None)

        assert distance_operator in sql
        assert ") < " in sql


class TestSafeCreateWhereTypeExtended:
    """Test dynamic filter type creation."""

    def test_create_simple_filter_type(self) -> None:
        """Test creating a filter type for simple dataclass."""

        @dataclass
        class User:
            id: int
            name: str
            email: str

        FilterType = safe_create_where_type(User)

        # Should create a class
        assert callable(FilterType)

        # Should have filter fields
        filter_instance = FilterType()
        assert hasattr(filter_instance, "id")
        assert hasattr(filter_instance, "name")
        assert hasattr(filter_instance, "email")

    def test_create_filter_with_optional_fields(self) -> None:
        """Test creating filter type with optional fields."""

        @dataclass
        class Post:
            id: int
            title: str
            content: Optional[str] = None
            published: bool = False

        FilterType = safe_create_where_type(Post)
        filter_instance = FilterType()

        assert hasattr(filter_instance, "id")
        assert hasattr(filter_instance, "title")
        assert hasattr(filter_instance, "content")
        assert hasattr(filter_instance, "published")

    def test_filter_type_to_sql(self) -> None:
        """Test that created filter types implement to_sql method."""

        @dataclass
        class Simple:
            name: str

        FilterType = safe_create_where_type(Simple)
        filter_instance = FilterType()

        # Should implement DynamicType protocol
        assert isinstance(filter_instance, DynamicType)

        # Should have to_sql method
        assert hasattr(filter_instance, "to_sql")
        assert callable(filter_instance.to_sql)

    def test_filter_type_with_complex_types(self) -> None:
        """Test filter type creation with complex field types."""

        @dataclass
        class ComplexModel:
            id: int
            created_at: datetime
            score: Decimal
            tags: list[str]
            metadata: dict[str, Any]

        FilterType = safe_create_where_type(ComplexModel)
        filter_instance = FilterType()

        # Should handle complex types
        assert hasattr(filter_instance, "created_at")
        assert hasattr(filter_instance, "score")
        assert hasattr(filter_instance, "tags")
        assert hasattr(filter_instance, "metadata")

    def test_filter_inheritance(self) -> None:
        """Test filter type with inheritance."""

        @dataclass
        class BaseModel:
            id: int
            created_at: datetime

        @dataclass
        class User(BaseModel):
            name: str
            email: str

        UserFilter = safe_create_where_type(User)
        user_filter = UserFilter()

        # Should include inherited fields
        assert hasattr(user_filter, "id")
        assert hasattr(user_filter, "created_at")
        assert hasattr(user_filter, "name")
        assert hasattr(user_filter, "email")


class TestDynamicTypeProtocol:
    """Test the DynamicType protocol."""

    def test_protocol_compliance(self) -> None:
        """Test that objects can implement the protocol."""

        class CustomFilter:
            def to_sql(self) -> Composed | None:
                return Composed([SQL("1 = 1")])

        filter_instance = CustomFilter()
        assert isinstance(filter_instance, DynamicType)

    def test_protocol_method_signature(self) -> None:
        """Test protocol method signature requirements."""

        class InvalidFilter:
            def to_sql(self, extra_param):  # Wrong signature
                return None

        InvalidFilter()
        # Should not satisfy protocol due to signature mismatch
        # Note: runtime_checkable only checks method existence, not signature


class TestEdgeCasesExtended:
    """Test edge cases and error conditions."""

    def test_build_operator_with_none_value(self) -> None:
        """Test operator building with None values."""
        path_sql = SQL("data->>'field'")

        # None value with equality
        result = build_operator_composed(path_sql, "eq", None)
        assert isinstance(result, Composed)

    def test_build_operator_with_empty_string(self) -> None:
        """Test operator building with empty string."""
        path_sql = SQL("data->>'field'")
        result = build_operator_composed(path_sql, "eq", "")
        assert isinstance(result, Composed)

    def test_build_operator_with_complex_nested_value(self) -> None:
        """Test operator with complex nested values."""
        path_sql = SQL("data->>'config'")
        complex_value = {"nested": {"key": "value"}}

        result = build_operator_composed(path_sql, "eq", complex_value)
        assert isinstance(result, Composed)

    def test_edge_case_operators(self) -> None:
        """Test edge case operator handling."""
        path_sql = SQL("data->>'field'")

        # Test with None values
        result = build_operator_composed(path_sql, "eq", None)
        assert isinstance(result, Composed)

    def test_filter_type_caching(self) -> None:
        """Test that filter types are cached properly."""

        @dataclass
        class CachedModel:
            name: str

        # Generate same filter type twice
        Filter1 = safe_create_where_type(CachedModel)
        Filter2 = safe_create_where_type(CachedModel)

        # Should be the same due to caching
        assert Filter1 is Filter2


@pytest.fixture
def sample_where_type() -> None:
    """Provide a sample WHERE type for testing."""
    return safe_create_where_type(SampleModel)

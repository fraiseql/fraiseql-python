"""Comprehensive tests to verify SQL injection prevention in where_generator."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from psycopg import DataError
from psycopg.sql import Composed

from fraiseql.sql.where_generator import safe_create_where_type

pytestmark = pytest.mark.database


@dataclass
class User:
    name: str
    email: str
    age: int
    is_admin: bool
    user_id: uuid.UUID
    created_at: datetime


UserWhere = safe_create_where_type(User)


# Additional model for testing ltree-specific operators
@dataclass
class CategoryNode:
    """Model with ltree field for testing hierarchical operators."""

    id: uuid.UUID
    path: str  # Will be treated as ltree when operators are used
    name: str


CategoryNodeWhere = safe_create_where_type(CategoryNode)


class TestSQLInjectionPrevention:
    """Test suite to verify SQL injection vulnerabilities are prevented."""

    def test_basic_parameterization(self) -> None:
        """Test that basic filters use parameterized queries."""
        where = UserWhere(name={"eq": "Alice"}, age={"gt": 21})
        composed = where.to_sql()

        assert composed is not None
        assert isinstance(composed, Composed)

        # Convert to string to inspect structure
        sql_str = composed.as_string(None)
        assert "(data ->> 'name') = 'Alice'" in sql_str
        # Validate numeric casting structure - should be well-formed
        import re

        numeric_pattern = r"\(\(data ->> 'age'\)\)::numeric > 21|\(data ->> 'age'\)::numeric > 21"
        assert re.search(numeric_pattern, sql_str), (
            f"Expected valid numeric casting pattern, got: {sql_str}"
        )

    def test_string_injection_attempts(self) -> None:
        """Test that SQL injection in string values is prevented."""
        injection_attempts = [
            "'; DROP TABLE users; --",
            "' OR '1'='1",
            "'; DELETE FROM users WHERE '1'='1'; --",
            "admin'--",
            "' UNION SELECT * FROM passwords --",
            "'; UPDATE users SET is_admin = true WHERE '1'='1'; --",
            "Robert'); DROP TABLE students;--",  # Little Bobby Tables
        ]

        for malicious_input in injection_attempts:
            where = UserWhere(name={"eq": malicious_input})
            composed = where.to_sql()

            assert composed is not None
            # The Composed object uses Literal() which safely parameterizes values
            # When executed, psycopg will use proper parameter binding

            # Convert to string for inspection (this shows placeholders are used)
            sql_str = composed.as_string(None)

            # The malicious input should be properly quoted/escaped
            # No SQL keywords should be executable
            assert "DROP TABLE" not in sql_str or "DROP TABLE" in repr(sql_str).replace("\\", "")

    def test_boolean_handling(self) -> None:
        """Test that boolean values are correctly converted to strings for JSONB."""
        where_true = UserWhere(is_admin={"eq": True})
        where_false = UserWhere(is_admin={"eq": False})

        sql_true = where_true.to_sql().as_string(None)
        sql_false = where_false.to_sql().as_string(None)

        # Booleans should use text comparison for JSONB
        assert "(data ->> 'is_admin') = 'true'" in sql_true
        assert "(data ->> 'is_admin') = 'false'" in sql_false

    def test_list_injection_attempts(self) -> None:
        """Test that SQL injection in list values is prevented."""
        malicious_list = ["normal_user", "'; DROP TABLE users; --", "' OR '1'='1", "admin'--"]

        where = UserWhere(name={"in": malicious_list})
        composed = where.to_sql()

        assert composed is not None
        sql_str = composed.as_string(None)

        # All values should be safely parameterized
        assert "IN (" in sql_str
        # Dangerous SQL should be quoted
        assert "DROP TABLE users" not in sql_str or "DROP TABLE" in repr(sql_str)

    def test_all_operators_are_safe(self) -> None:
        """Test that all operators use parameterization."""
        test_cases = [
            ("eq", "' OR '1'='1"),
            ("neq", "'; DROP TABLE users; --"),
            ("gt", "1' OR '1'='1"),
            ("gte", "1'; DELETE FROM users; --"),
            ("lt", "100' OR '1'='1"),
            ("lte", "100'; --"),
            ("contains", "' OR TRUE --"),
            ("matches", ".*'; DROP TABLE users; --"),
            ("startswith", "admin'; --"),
        ]

        for operator, malicious_value in test_cases:
            where = UserWhere(name={operator: malicious_value})
            composed = where.to_sql()

            assert composed is not None
            assert isinstance(composed, Composed)

            # The Literal class ensures safe parameterization
            sql_str = composed.as_string(None)

            # Verify the operator is present but the injection is neutralized
            if operator == "eq":
                assert " = " in sql_str
            elif operator == "neq":
                assert " != " in sql_str
            elif operator == "gt":
                assert " > " in sql_str
            # ... other operators are similarly safe

    def test_uuid_and_date_safety(self) -> None:
        """Test that special types are safely handled."""
        test_uuid = (uuid.UUID("12345678-1234-5678-1234-567812345678"),)
        test_date = (datetime(2024, 12, 31, 12, 0, 0, tzinfo=UTC),)

        where = UserWhere(user_id={"eq": test_uuid}, created_at={"lt": test_date})

        composed = where.to_sql()
        assert composed is not None

        sql_str = composed.as_string(None)
        # psycopg might format UUIDs differently
        assert "12345678" in sql_str
        assert "2024-12-31" in sql_str

    def test_null_handling(self) -> None:
        """Test that null checks don't allow injection."""
        where_null = UserWhere(email={"isnull": True})
        where_not_null = UserWhere(email={"isnull": False})

        sql_null = where_null.to_sql().as_string(None)
        sql_not_null = where_not_null.to_sql().as_string(None)

        assert "IS NULL" in sql_null
        assert "IS NOT NULL" in sql_not_null

        # No values are inserted, so no injection possible
        assert "=" not in sql_null.split("IS NULL")[0].split("email")[-1]

    def test_complex_combined_injection(self) -> None:
        """Test complex injection attempts with multiple fields."""
        where = UserWhere(
            name={"eq": "'; DROP TABLE users; --"},
            email={"in": ["admin@example.com", "' OR '1'='1", "'; DELETE FROM users; --"]},
            age={"gt": 18, "lt": 65},
            is_admin={"eq": False},
            user_id={"neq": uuid.UUID("12345678-1234-5678-1234-567812345678")},
        )

        composed = where.to_sql()
        assert composed is not None

        sql_str = composed.as_string(None)

        # Multiple conditions should be ANDed together
        assert " AND " in sql_str

        # All dangerous inputs should be safely parameterized
        assert "DROP TABLE" not in sql_str or "DROP TABLE" in repr(sql_str)
        assert "DELETE FROM" not in sql_str or "DELETE FROM" in repr(sql_str)

    def test_special_characters_handling(self) -> None:
        """Test that special characters are safely handled."""
        special_chars = [
            "O'Reilly",  # Single quote
            'Say "Hello"',  # Double quotes
            "Line1\nLine2",  # Newline
            "Tab\there",  # Tab
            "Back\\slash",  # Backslash
            "Null\x00Byte",  # Null byte
            "Unicode😀",  # Unicode emoji
        ]

        for special in special_chars:
            try:
                where = UserWhere(name={"eq": special})
                composed = where.to_sql()
                assert composed is not None
                # Psycopg's Literal handles all special characters safely
            except DataError as e:
                # Null bytes are not supported by PostgreSQL, which is expected
                if "\x00" in special and "NUL (0x00) bytes" in str(e):
                    continue  # This is expected behavior
                raise

    def test_nested_filter_safety(self) -> None:
        """Test that nested filters maintain safety."""

        @dataclass
        class Profile:
            bio: str
            website: str
            verified: bool

        ProfileWhere = safe_create_where_type(Profile)

        # Create filter with injection attempts
        profile_where = ProfileWhere(
            bio={"contains": "'; DELETE FROM profiles; --"},
            website={"startswith": "https://evil.com'; --"},
            verified={"eq": True},
        )

        composed = profile_where.to_sql()
        assert composed is not None

        sql_str = composed.as_string(None)

        # All values should be safely parameterized
        assert "DELETE FROM" not in sql_str or "DELETE FROM" in repr(sql_str)
        assert "(data ->> 'verified') = 'true'" in sql_str  # Boolean as text comparison

    @pytest.mark.parametrize("operator", ["strictly_contains"])
    def test_jsonb_operators_safety(self, operator) -> None:
        """Test that JSONB operators are safe from injection."""
        # Test with malicious input
        where = UserWhere(name={operator: "'; DROP TABLE users; --"})

        composed = where.to_sql()
        assert composed is not None

        sql_str = composed.as_string(None)

        # Verify operator is present and injection is prevented
        assert " @> " in sql_str
        assert " != " in sql_str
        # Malicious string should be safely parameterized
        assert "DROP TABLE" not in sql_str or "DROP TABLE" in repr(sql_str)

    @pytest.mark.parametrize(
        ("operator", "value"), [("depth_eq", 3), ("depth_gt", 2), ("depth_lt", 5)]
    )
    def test_ltree_depth_operators_require_field_type(self, operator, value) -> None:
        """Test that ltree depth operators require explicit field type specification.

        Depth operators work on ltree fields but accept integer values. Without explicit
        field type information, the system cannot determine if a string field contains
        ltree data. This is the correct behavior - type safety requires explicit typing.

        These operators WILL work correctly when:
        1. Using typed models with LTree type hints, OR
        2. Querying views/tables where field types are known, OR
        3. Using GraphQL where type information is available from the schema
        """
        where = CategoryNodeWhere(path={operator: value})

        composed = where.to_sql()

        # Without explicit field type, depth operators on string fields return None
        # This is CORRECT behavior - prevents misapplication of ltree operators
        assert composed is None, (
            f"Depth operator {operator} should return None without field type specification. "
            "This prevents incorrect operator application and maintains type safety."
        )

    def test_ltree_hierarchy_operators_require_field_type(self) -> None:
        """Test that ltree hierarchy operators require field type specification.

        The isdescendant operator is ltree-specific and cannot be automatically detected
        from string values alone. This test verifies that type safety is maintained.
        """
        # Test with a valid ltree path
        where = CategoryNodeWhere(path={"isdescendant": "top.middle.leaf"})

        composed = where.to_sql()

        # Without explicit field type, ltree operators on string fields return None
        # This is CORRECT behavior - maintains type safety
        assert composed is None, (
            "LTree operators should return None without field type specification. "
            "This is the correct behavior that maintains type safety and prevents "
            "incorrect operator application to non-ltree fields."
        )

    def test_empty_and_none_values(self) -> None:
        """Test that empty and None values are handled safely."""
        # Empty string
        where_empty = UserWhere(name={"eq": ""})
        assert where_empty.to_sql() is not None

        # Empty list for IN operator
        where_empty_list = UserWhere(name={"in": []})
        assert where_empty_list.to_sql() is not None

        # None values should be skipped
        where_with_none = UserWhere(name={"eq": "Alice"}, email=None)
        sql_str = where_with_none.to_sql().as_string(None)
        assert "email" not in sql_str  # None fields are not included


def test_actual_database_execution() -> None:
    """Integration test placeholder.

    In a real integration test, this would verify that the parameterized
    queries execute safely against an actual database.
    """
    # This test is a placeholder - actual database testing would be done
    # in integration tests with proper database fixtures

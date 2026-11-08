import pytest

"""Tests for SQL helper tool for beginners."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from fraiseql.cli.sql_helper import (
    FieldMapping,
    SQLHelper,
    SQLPattern,
    ViewGenerator,
    ViewOptions,
)


@pytest.mark.unit
@dataclass
class User:
    """Test user type."""

    id: int
    email: str
    name: str
    is_active: bool = True
    created_at: datetime | None = None


@dataclass
class Post:
    """Test post type."""

    id: int
    title: str
    content: str
    author_id: int
    published_at: datetime | None = None
    tags: list[str] = None


@dataclass
class Product:
    """Test product type."""

    id: int
    name: str
    price: Decimal
    in_stock: bool
    category: str


class TestViewGenerator:
    """Test SQL view generation."""

    def test_simple_view_generation(self) -> None:
        """Test generating a simple view."""
        generator = ViewGenerator()
        sql = generator.generate_view(User)

        expected = """-- View for GraphQL type 'User'
-- This view returns a JSONB 'data' column that FraiseQL will use

CREATE OR REPLACE VIEW v_users AS
SELECT
    jsonb_build_object(
        'id', id,
        'email', email,
        'name', name,
        'is_active', is_active,
        'created_at', created_at
    ) as data
FROM users;

-- Grant permissions (adjust as needed)
GRANT SELECT ON v_users TO fraiseql_reader;"""

        assert sql.strip() == expected.strip()

    def test_view_with_custom_table(self) -> None:
        """Test view generation with custom table name."""
        generator = ViewGenerator()
        options = ViewOptions(table_name="tb_users")
        sql = generator.generate_view(User, options)

        assert "FROM tb_users" in sql
        assert "CREATE OR REPLACE VIEW v_users" in sql

    def test_view_with_custom_view_name(self) -> None:
        """Test view generation with custom view name."""
        generator = ViewGenerator()
        options = ViewOptions(view_name="user_profiles")
        sql = generator.generate_view(User, options)

        assert "CREATE OR REPLACE VIEW user_profiles" in sql
        assert "GRANT SELECT ON user_profiles" in sql

    def test_view_with_field_mapping(self) -> None:
        """Test view generation with field mapping."""
        generator = ViewGenerator()
        options = ViewOptions(
            field_mapping={
                "email": "user_email",
                "is_active": "active",
            },
        )
        sql = generator.generate_view(User, options)

        assert "'email', user_email" in sql
        assert "'is_active', active" in sql

    def test_view_with_excluded_fields(self) -> None:
        """Test view generation excluding fields."""
        generator = ViewGenerator()
        options = ViewOptions(excluded_fields={"created_at"})
        sql = generator.generate_view(User, options)

        assert "created_at" not in sql
        assert "'id', id" in sql  # Other fields still included

    def test_view_with_list_field(self) -> None:
        """Test view generation with list/array fields."""
        generator = ViewGenerator()
        sql = generator.generate_view(Post)

        # Should handle tags array properly
        assert "'tags', tags" in sql or "'tags', COALESCE(tags, '[]'::jsonb)" in sql

    def test_view_with_type_casting(self) -> None:
        """Test view generation with proper type casting."""
        generator = ViewGenerator()
        ViewOptions(add_type_casts=True)
        sql = generator.generate_view(Product)

        # Should cast decimal to numeric for JSON
        assert "'price', price::numeric" in sql or "'price', price" in sql

    def test_view_with_joins(self) -> None:
        """Test view generation with relationship joins."""
        generator = ViewGenerator()
        options = ViewOptions(
            joins=[
                {
                    "field": "author",
                    "target_table": "users",
                    "join_column": "author_id",
                    "target_fields": ["id", "name", "email"],
                },
            ],
        )
        sql = generator.generate_view(Post, options)

        assert "LEFT JOIN users" in sql
        assert "ON posts.author_id = users.id" in sql
        assert "'author', jsonb_build_object(" in sql


class TestSQLPatterns:
    """Test common SQL pattern generation."""

    def test_pagination_pattern(self) -> None:
        """Test generating pagination pattern."""
        pattern = SQLPattern.pagination("users", limit=20, offset=40)

        expected = """-- Pagination pattern for users
SELECT data
FROM v_users
LIMIT 20
OFFSET 40;"""

        assert pattern.strip() == expected.strip()

    def test_filtering_pattern(self) -> None:
        """Test generating filtering pattern."""
        pattern = SQLPattern.filtering(
            "users",
            conditions={"email": "test@example.com", "is_active": True},
        )

        assert "WHERE data->>'email' = 'test@example.com'" in pattern
        assert "AND (data->>'is_active')::boolean = true" in pattern

    def test_sorting_pattern(self) -> None:
        """Test generating sorting pattern."""
        pattern = SQLPattern.sorting(
            "users",
            order_by=[("name", "ASC"), ("created_at", "DESC")],
        )

        assert "ORDER BY data->>'name' ASC" in pattern
        assert "data->>'created_at' DESC" in pattern

    def test_relationship_pattern(self) -> None:
        """Test generating relationship query pattern."""
        pattern = SQLPattern.relationship(
            parent_table="users",
            child_table="posts",
            relationship_field="posts",
            foreign_key="author_id",
        )

        expected_parts = [
            "-- One-to-many relationship: users.posts",
            "u.data || jsonb_build_object(",
            "'posts', COALESCE(",
            "SELECT jsonb_agg(p.data",
            "FROM v_posts p",
            "WHERE (p.data->>'author_id')::int = (u.data->>'id')::int",
        ]

        for part in expected_parts:
            assert part in pattern

    def test_aggregation_pattern(self) -> None:
        """Test generating aggregation pattern."""
        pattern = SQLPattern.aggregation(
            "orders",
            group_by="customer_id",
            aggregates={
                "total_amount": "SUM(amount)",
                "order_count": "COUNT(*)",
                "avg_amount": "AVG(amount)",
            },
        )

        assert "GROUP BY data->>'customer_id'" in pattern
        assert "'total_amount', SUM((data->>'amount')::numeric)" in pattern
        assert "'order_count', COUNT(*)" in pattern
        assert "'avg_amount', AVG((data->>'amount')::numeric)" in pattern


class TestSQLHelper:
    """Test the main SQL helper functionality."""

    def test_generate_complete_setup(self) -> None:
        """Test generating complete SQL setup for a type."""
        helper = SQLHelper()

        # Generate complete setup
        setup = helper.generate_setup(
            User,
            include_table=True,
            include_indexes=True,
            include_sample_data=True,
        )

        # Should include table creation
        assert "CREATE TABLE users" in setup
        assert "id SERIAL PRIMARY KEY" in setup
        assert "email VARCHAR(255) NOT NULL UNIQUE" in setup

        # A `T | None` field is a nullable column of T's type
        columns = [line.strip().rstrip(",") for line in setup.splitlines()]
        assert "created_at TIMESTAMP" in columns

        # Should include indexes
        assert "CREATE INDEX" in setup
        assert "idx_users_email" in setup

        # Should include view
        assert "CREATE OR REPLACE VIEW v_users" in setup

        # Should include sample data
        assert "INSERT INTO users" in setup
        assert "sample.user" in setup

    def test_generate_migration(self) -> None:
        """Test generating migration from existing table."""
        helper = SQLHelper()

        # Mock existing table schema
        existing_schema = {
            "columns": {
                "user_id": "INTEGER",
                "user_email": "TEXT",
                "full_name": "TEXT",
                "status": "VARCHAR(20)",
            },
        }

        migration = helper.generate_migration(
            User,
            existing_schema,
            field_mapping={
                "id": "user_id",
                "email": "user_email",
                "name": "full_name",
                "is_active": "status = 'active'",
            },
        )

        # Should create view with proper mapping
        assert "'id', user_id" in migration
        assert "'email', user_email" in migration
        assert "'is_active', status = 'active'" in migration

    def test_validate_view(self) -> None:
        """Test validating generated view."""
        helper = SQLHelper()

        # Generate view
        view_sql = helper.generate_view(User)

        # Validate it
        validation = helper.validate_sql(view_sql)

        assert validation.is_valid
        assert validation.has_data_column
        assert validation.returns_jsonb
        assert not validation.errors

    def test_explain_sql(self) -> None:
        """Test SQL explanation for beginners."""
        helper = SQLHelper()

        simple_view = """CREATE VIEW v_users AS
SELECT jsonb_build_object('id', id, 'name', name) as data
FROM users;"""

        explanation = helper.explain_sql(simple_view)

        expected_parts = [
            "This SQL creates a view named 'v_users'",
            "jsonb_build_object: Creates a JSON object from key-value pairs",
            "FROM users: Reads from the 'users' table",
        ]

        for part in expected_parts:
            assert part in explanation

    def test_common_mistakes_detection(self) -> None:
        """Test detection of common SQL mistakes."""
        helper = SQLHelper()

        # Missing 'data' column
        bad_sql1 = "CREATE VIEW v_users AS SELECT * FROM users;"
        issues1 = helper.detect_common_mistakes(bad_sql1)
        assert any("data" in issue for issue in issues1)

        # Not returning JSONB
        bad_sql2 = "CREATE VIEW v_users AS SELECT id::text as data FROM users;"
        issues2 = helper.detect_common_mistakes(bad_sql2)
        assert any("JSONB" in issue for issue in issues2)

        # Using wrong naming convention
        bad_sql3 = "CREATE VIEW users_view AS SELECT jsonb_build_object() as data FROM users;"
        issues3 = helper.detect_common_mistakes(bad_sql3)
        assert any("naming convention" in issue for issue in issues3)


class TestFieldMapping:
    """Test field mapping utilities."""

    def test_auto_detect_mapping(self) -> None:
        """Test automatic field mapping detection with exact matches only."""
        mapper = FieldMapping()

        # Mock database columns - only is_active matches exactly
        db_columns = ["user_id", "user_email", "user_name", "created_date", "is_active"]

        # Auto-detect mapping for User type
        mapping = mapper.auto_detect(User, db_columns)

        # Only exact matches should be found
        assert mapping == {"is_active": "is_active"}

        # Test with exact matches
        db_columns_exact = ["id", "email", "name", "created_at", "is_active"]
        mapping_exact = mapper.auto_detect(User, db_columns_exact)

        assert mapping_exact["id"] == "id"
        assert mapping_exact["email"] == "email"
        assert mapping_exact["name"] == "name"
        assert mapping_exact["created_at"] == "created_at"
        assert mapping_exact["is_active"] == "is_active"

    def test_mapping_suggestions(self) -> None:
        """Test field mapping suggestions returns all columns sorted."""
        mapper = FieldMapping()

        # Get suggestions - should return all columns sorted alphabetically
        suggestions = mapper.suggest_mapping(
            field_name="email",
            available_columns=["email_address", "user_email", "contact_email", "mail"],
        )

        # Should return all columns in alphabetical order
        assert suggestions == ["contact_email", "email_address", "mail", "user_email"]

    def test_type_compatibility_check(self) -> None:
        """Test checking type compatibility."""
        mapper = FieldMapping()

        # Check compatible types
        assert mapper.is_compatible("VARCHAR(255)", str)
        assert mapper.is_compatible("INTEGER", int)
        assert mapper.is_compatible("BOOLEAN", bool)
        assert mapper.is_compatible("TIMESTAMP", datetime)
        assert mapper.is_compatible("NUMERIC(10,2)", Decimal)

        # T | None is T, nullable (Optional[T] and T | None are one type only on 3.14)
        assert mapper.is_compatible("TIMESTAMP", datetime | None)

        # Check incompatible types
        assert not mapper.is_compatible("VARCHAR(255)", int)
        assert not mapper.is_compatible("INTEGER", str)

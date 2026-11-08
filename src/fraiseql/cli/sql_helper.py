"""SQL helper tool for beginners.

This module provides utilities to help users generate SQL views and understand
how FraiseQL maps GraphQL types to PostgreSQL views.
"""

import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date, datetime
from decimal import Decimal
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from fraiseql.utils.naming import to_snake_case


@dataclass
class ViewOptions:
    """Options for view generation."""

    table_name: str | None = None
    view_name: str | None = None
    field_mapping: dict[str, str] = dataclass_field(default_factory=dict)
    excluded_fields: set[str] = dataclass_field(default_factory=set)
    add_type_casts: bool = False
    include_comments: bool = True
    joins: list[dict[str, Any]] = dataclass_field(default_factory=list)


@dataclass
class ValidationResult:
    """Result of SQL validation."""

    is_valid: bool
    has_data_column: bool
    returns_jsonb: bool
    errors: list[str] = dataclass_field(default_factory=list)
    warnings: list[str] = dataclass_field(default_factory=list)


class ViewGenerator:
    """Generates SQL views for FraiseQL types."""

    def generate_view(self, cls: type, options: ViewOptions | None = None) -> str:
        """Generate a SQL view for a FraiseQL type.

        Args:
            cls: The dataclass type to generate a view for
            options: Optional view generation options

        Returns:
            SQL view creation statement
        """
        options = options or ViewOptions()

        # Get type information
        type_name = cls.__name__
        type_hints = get_type_hints(cls)

        # Determine names
        table_name = options.table_name or to_snake_case(type_name) + "s"
        view_name = options.view_name or f"v_{to_snake_case(type_name)}s"

        # Build field list
        fields = []
        for field_name, field_type in type_hints.items():
            if field_name in options.excluded_fields:
                continue

            # Get column name
            column_name = options.field_mapping.get(field_name, field_name)

            # Handle type casting if needed
            if options.add_type_casts and field_type == Decimal:
                column_expr = f"{column_name}::numeric"
            else:
                column_expr = column_name

            fields.append(f"        '{field_name}', {column_expr}")

        # Handle joins
        join_sql = ""
        join_fields = []
        if options.joins:
            for join in options.joins:
                join_sql += (
                    f"\n    LEFT JOIN {join['target_table']} "
                    f"ON {table_name}.{join['join_column']} = {join['target_table']}.id"
                )

                # Build nested object for join
                join_obj_fields = [
                    f"            '{field}', {join['target_table']}.{field}"
                    for field in join["target_fields"]
                ]

                join_obj_str = ",\n".join(join_obj_fields)
                join_fields.append(
                    f"        '{join['field']}', jsonb_build_object(\n{join_obj_str}\n        )",
                )

        # Combine all fields
        all_fields = fields + join_fields
        fields_sql = ",\n".join(all_fields)

        # Build SQL
        sql_parts = []

        if options.include_comments:
            sql_parts.append(f"-- View for GraphQL type '{type_name}'")
            sql_parts.append("-- This view returns a JSONB 'data' column that FraiseQL will use")
            sql_parts.append("")

        sql_parts.append(f"CREATE OR REPLACE VIEW {view_name} AS")
        sql_parts.append("SELECT")
        sql_parts.append("    jsonb_build_object(")
        sql_parts.append(fields_sql)
        sql_parts.append("    ) as data")
        sql_parts.append(f"FROM {table_name}{join_sql};")
        sql_parts.append("")
        sql_parts.append("-- Grant permissions (adjust as needed)")
        sql_parts.append(f"GRANT SELECT ON {view_name} TO fraiseql_reader;")

        return "\n".join(sql_parts)


class SQLPattern:
    """Common SQL patterns for FraiseQL."""

    @staticmethod
    def pagination(table: str, limit: int = 20, offset: int = 0) -> str:
        """Generate pagination pattern."""
        return f"""-- Pagination pattern for {table}
SELECT data
FROM v_{table}
LIMIT {limit}
OFFSET {offset};"""

    @staticmethod
    def filtering(table: str, conditions: dict[str, Any]) -> str:
        """Generate filtering pattern."""
        where_parts = []

        for field, value in conditions.items():
            if isinstance(value, str):
                where_parts.append(f"data->>'{field}' = '{value}'")
            elif isinstance(value, bool):
                where_parts.append(f"(data->>'{field}')::boolean = {str(value).lower()}")
            elif isinstance(value, int | float):
                where_parts.append(f"(data->>'{field}')::numeric = {value}")
            else:
                where_parts.append(f"data->>'{field}' = '{value}'")

        where_clause = " AND ".join(where_parts)

        return f"""-- Filtering pattern for {table}
SELECT data
FROM v_{table}
WHERE {where_clause};"""

    @staticmethod
    def sorting(table: str, order_by: list[tuple[str, str]]) -> str:
        """Generate sorting pattern."""
        order_parts = []

        for field, direction in order_by:
            order_parts.append(f"data->>'{field}' {direction}")

        order_clause = ", ".join(order_parts)

        return f"""-- Sorting pattern for {table}
SELECT data
FROM v_{table}
ORDER BY {order_clause};"""

    @staticmethod
    def relationship(
        parent_table: str,
        child_table: str,
        relationship_field: str,
        foreign_key: str,
    ) -> str:
        """Generate relationship query pattern."""
        return f"""-- One-to-many relationship: {parent_table}.{relationship_field}
SELECT
    u.data || jsonb_build_object(
        '{relationship_field}', COALESCE(
            (
                SELECT jsonb_agg(p.data ORDER BY p.data->>'created_at' DESC)
                FROM v_{child_table} p
                WHERE (p.data->>'{foreign_key}')::int = (u.data->>'id')::int
            ),
            '[]'::jsonb
        )
    ) as data
FROM v_{parent_table} u;"""

    @staticmethod
    def aggregation(table: str, group_by: str, aggregates: dict[str, str]) -> str:
        """Generate aggregation pattern."""
        agg_parts = []

        for alias, expression in aggregates.items():
            # Parse the expression to add proper casting
            if "SUM" in expression or "AVG" in expression:
                # Extract field name
                match = re.search(r"\((.*?)\)", expression)
                if match:
                    field = match.group(1)
                    func = expression.split("(")[0]
                    agg_parts.append(f"        '{alias}', {func}((data->>'{field}')::numeric)")
            else:
                agg_parts.append(f"        '{alias}', {expression}")

        agg_sql = ",\n".join(agg_parts)

        return f"""-- Aggregation pattern for {table}
SELECT
    jsonb_build_object(
        '{group_by}', data->>'{group_by}',
{agg_sql}
    ) as data
FROM v_{table}
GROUP BY data->>'{group_by}';"""


class FieldMapping:
    """Utilities for mapping fields between GraphQL and database."""

    def auto_detect(self, cls: type, db_columns: list[str]) -> dict[str, str]:
        """Auto-detect field mapping based on exact column name matches.

        Args:
            cls: The dataclass type
            db_columns: List of database column names

        Returns:
            Mapping of class field names to database columns (only exact matches)
        """
        type_hints = get_type_hints(cls)
        return {field_name: field_name for field_name in type_hints if field_name in db_columns}

    def suggest_mapping(self, field_name: str, available_columns: list[str]) -> list[str]:
        """Return all available columns for manual mapping selection.

        Args:
            field_name: The field name to map
            available_columns: List of available database columns

        Returns:
            List of all available columns (sorted alphabetically)
        """
        return sorted(available_columns)

    def is_compatible(self, db_type: str, python_type: type) -> bool:
        """Check if database type is compatible with Python type.

        Args:
            db_type: Database column type
            python_type: Python type

        Returns:
            True if types are compatible
        """
        db_type_upper = db_type.upper()

        # Handle Optional types
        origin = get_origin(python_type)
        if origin in (Union, UnionType):
            args = get_args(python_type)
            if len(args) == 2 and type(None) in args:
                python_type = args[0] if args[1] is type(None) else args[1]

        # Type compatibility mapping
        compatibility = {
            str: ["VARCHAR", "TEXT", "CHAR", "CHARACTER"],
            int: ["INTEGER", "INT", "SERIAL", "BIGINT", "SMALLINT"],
            float: ["REAL", "DOUBLE", "FLOAT", "NUMERIC", "DECIMAL"],
            Decimal: ["NUMERIC", "DECIMAL", "MONEY"],
            bool: ["BOOLEAN", "BOOL"],
            datetime: ["TIMESTAMP", "DATETIME"],
            date: ["DATE"],
        }

        if python_type in compatibility:
            return any(compat in db_type_upper for compat in compatibility[python_type])

        return False


class SQLHelper:
    """Main SQL helper for beginners."""

    def __init__(self) -> None:
        """Initialize SQL helper."""
        self.generator = ViewGenerator()
        self.mapper = FieldMapping()

    def generate_view(self, cls: type, options: ViewOptions | None = None) -> str:
        """Generate a view for a FraiseQL type."""
        return self.generator.generate_view(cls, options)

    def generate_setup(
        self,
        cls: type,
        include_table: bool = False,
        include_indexes: bool = False,
        include_sample_data: bool = False,
    ) -> str:
        """Generate complete SQL setup for a type.

        Args:
            cls: The dataclass type
            include_table: Whether to include table creation
            include_indexes: Whether to include index creation
            include_sample_data: Whether to include sample data

        Returns:
            Complete SQL setup script
        """
        parts = []
        type_name = cls.__name__
        table_name = to_snake_case(type_name) + "s"
        type_hints = get_type_hints(cls)

        # Table creation
        if include_table:
            parts.append(f"-- Create table for {type_name}")
            parts.append(f"CREATE TABLE {table_name} (")

            columns = []
            for field_name, field_type in type_hints.items():
                sql_type = self._python_to_sql_type(field_type)

                if field_name == "id":
                    columns.append("    id SERIAL PRIMARY KEY")
                elif field_name == "email":
                    columns.append("    email VARCHAR(255) NOT NULL UNIQUE")
                else:
                    # Handle nullability
                    origin = get_origin(field_type)
                    if origin in (Union, UnionType):
                        columns.append(f"    {field_name} {sql_type}")
                    else:
                        columns.append(f"    {field_name} {sql_type} NOT NULL")

            parts.append(",\n".join(columns))
            parts.append(");")
            parts.append("")

        # Indexes
        if include_indexes:
            parts.append("-- Create indexes for better performance")

            parts.extend(
                f"CREATE INDEX idx_{table_name}_{field_name} ON {table_name}({field_name});"
                for field_name in type_hints
                if field_name in ("email", "name", "created_at")
            )

            parts.append("")

        # View
        parts.append("-- Create view for GraphQL access")
        parts.append(self.generator.generate_view(cls))
        parts.append("")

        # Sample data
        if include_sample_data:
            parts.append("-- Insert sample data")
            parts.append(f"INSERT INTO {table_name} (")

            fields = [f for f in type_hints if f != "id"]
            parts.append(f"    {', '.join(fields)}")
            parts.append(") VALUES")

            # Generate 3 sample records
            for i in range(3):
                values = []
                for field_name, field_type in type_hints.items():
                    if field_name == "id":
                        continue

                    if field_type is str:
                        if field_name == "email":
                            values.append(f"'sample.user{i + 1}@example.com'")
                        else:
                            values.append(f"'Sample {field_name.title()} {i + 1}'")
                    elif field_type is bool:
                        values.append("true")
                    elif field_type in (int, float):
                        values.append(str(i + 1))
                    elif field_type is Decimal:
                        values.append(f"{(i + 1) * 10.99}")
                    else:
                        values.append("NULL")

                parts.append(f"    ({', '.join(values)}){';' if i == 2 else ','}")

        return "\n".join(parts)

    def generate_migration(
        self,
        cls: type,
        existing_schema: dict,
        field_mapping: dict[str, str],
    ) -> str:
        """Generate migration SQL from existing table to FraiseQL view.

        Args:
            cls: The target dataclass type
            existing_schema: Existing database schema info
            field_mapping: Mapping of class fields to database expressions

        Returns:
            Migration SQL script
        """
        type_name = cls.__name__
        view_name = f"v_{to_snake_case(type_name)}s"

        parts = []
        parts.append(f"-- Migration script to create FraiseQL view for {type_name}")
        parts.append("-- From existing table with custom field mapping")
        parts.append("")

        # Build view with mapping
        parts.append(f"CREATE OR REPLACE VIEW {view_name} AS")
        parts.append("SELECT")
        parts.append("    jsonb_build_object(")

        fields = []
        for field_name, db_expr in field_mapping.items():
            fields.append(f"        '{field_name}', {db_expr}")

        parts.append(",\n".join(fields))
        parts.append("    ) as data")
        parts.append("FROM your_existing_table;")

        return "\n".join(parts)

    def validate_sql(self, sql: str) -> ValidationResult:
        """Validate SQL for FraiseQL compatibility.

        Args:
            sql: SQL to validate

        Returns:
            Validation result
        """
        result = ValidationResult(
            is_valid=True,
            has_data_column=False,
            returns_jsonb=False,
        )

        # Check for 'data' column
        if " as data" in sql.lower() or " data " in sql.lower():
            result.has_data_column = True
        else:
            result.is_valid = False
            result.errors.append("View must return a column named 'data'")

        # Check for JSONB
        if "jsonb_build_object" in sql.lower():
            result.returns_jsonb = True
        else:
            result.is_valid = False
            result.errors.append("View must return JSONB data using jsonb_build_object")

        # Check view naming convention
        if "create view" in sql.lower() and not re.search(
            r"create\s+(or\s+replace\s+)?view\s+v_\w+",
            sql.lower(),
        ):
            result.warnings.append("View name should follow convention: v_tablename")

        return result

    def explain_sql(self, sql: str) -> str:
        """Explain SQL in beginner-friendly terms.

        Args:
            sql: SQL to explain

        Returns:
            Human-readable explanation
        """
        explanations = []

        lines = sql.strip().split("\n")
        for line in lines:
            line_stripped = line.strip()

            if line_stripped.startswith("--"):
                continue

            if "CREATE VIEW" in line_stripped.upper():
                view_match = re.search(
                    r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(\w+)",
                    line_stripped,
                    re.IGNORECASE,
                )
                if view_match:
                    explanations.append(f"This SQL creates a view named '{view_match.group(1)}'")
                    explanations.append("A view is like a saved query that acts as a virtual table")

            elif "jsonb_build_object" in line_stripped.lower():
                explanations.append(
                    "jsonb_build_object: Creates a JSON object from key-value pairs",
                )

            elif re.match(r"^\s*'(\w+)',\s*(\w+)", line_stripped):
                match = re.match(r"^\s*'(\w+)',\s*(\w+)", line_stripped)
                explanations.append(
                    f"'{match.group(1)}', {match.group(2)}: "
                    f"Maps the '{match.group(2)}' column to JSON field '{match.group(1)}'",
                )

            elif "as data" in line_stripped.lower():
                explanations.append("as data: Names the JSON column 'data' (required by FraiseQL)")

            elif re.match(r"FROM\s+(\w+)", line_stripped, re.IGNORECASE):
                match = re.match(r"FROM\s+(\w+)", line_stripped, re.IGNORECASE)
                explanations.append(
                    f"FROM {match.group(1)}: Reads from the '{match.group(1)}' table",
                )

            elif "LEFT JOIN" in line_stripped.upper():
                explanations.append(
                    "LEFT JOIN: Includes related data (keeps all rows from left table)",
                )

            elif "GRANT SELECT" in line_stripped.upper():
                explanations.append("GRANT SELECT: Gives read permission to a database user/role")

        return "\n".join(explanations)

    def detect_common_mistakes(self, sql: str) -> list[str]:
        """Detect common SQL mistakes for FraiseQL views.

        Args:
            sql: SQL to check

        Returns:
            List of detected issues
        """
        issues = []

        sql_lower = sql.lower()

        # Check for missing 'data' column
        if "as data" not in sql_lower:
            issues.append("Missing 'as data' - the view must return a column named 'data'")

        # Check for JSONB usage
        if "jsonb_build_object" not in sql_lower:
            issues.append("Not using jsonb_build_object - FraiseQL requires JSONB output")

        # Check naming convention
        if "create view" in sql_lower and not re.search(r"v_\w+", sql):
            issues.append("View naming convention - consider using 'v_tablename' format")

        # Check for SELECT *
        if "select *" in sql_lower:
            issues.append("Using SELECT * - explicitly build JSONB object instead")

        # Check for missing permissions
        if "grant" not in sql_lower:
            issues.append("Missing GRANT statement - remember to grant SELECT permission")

        return issues

    def _python_to_sql_type(self, python_type: type) -> str:
        """Convert Python type to SQL type.

        Args:
            python_type: Python type

        Returns:
            SQL type string
        """
        # Handle Optional types
        origin = get_origin(python_type)
        if origin in (Union, UnionType):
            args = get_args(python_type)
            if len(args) == 2 and type(None) in args:
                python_type = args[0] if args[1] is type(None) else args[1]

        type_map = {
            str: "VARCHAR(255)",
            int: "INTEGER",
            float: "REAL",
            Decimal: "NUMERIC(10,2)",
            bool: "BOOLEAN",
            datetime: "TIMESTAMP",
            date: "DATE",
            list: "JSONB",
            dict: "JSONB",
        }

        return type_map.get(python_type, "TEXT")

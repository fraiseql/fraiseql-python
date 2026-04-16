"""Module for generating SQL ORDER BY clauses with proper JSONB handling.

This module defines the `OrderBySet` dataclass, which aggregates multiple
ORDER BY instructions and compiles them into a PostgreSQL-safe SQL fragment
using the `psycopg` library's SQL composition utilities.

IMPORTANT: This module uses JSONB extraction (data -> 'field') rather than
text extraction (data ->> 'field') to preserve proper numeric ordering.
This prevents lexicographic sorting bugs where "125.0" > "1234.53" because
"2" > "1" in string comparison.

Key Features:
- Uses `data -> 'field'` for type-preserving JSONB extraction
- Maintains PostgreSQL's native type comparison behavior
- Supports nested field paths like `data -> 'profile' -> 'age'`
- Prevents numeric ordering bugs in financial and statistical data

The generated SQL is intended for use in query building where sorting by
multiple columns or expressions is required, supporting seamless integration
with dynamic query generators.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from psycopg import sql

from fraiseql import fraise_enum


@fraise_enum
class OrderDirection(Enum):
    """Order direction for sorting."""

    ASC = "asc"
    DESC = "desc"


@dataclass(frozen=True)
class OrderBy:
    """Single ORDER BY clause with JSONB type preservation and collation support.

    Generates PostgreSQL ORDER BY clauses using JSONB extraction (data -> 'field')
    to maintain proper type-based sorting. This ensures numeric fields are sorted
    numerically rather than lexicographically.

    For vector distance operations, supports pgvector operators:
    - cosine_distance: Cosine distance (0.0 = identical, 2.0 = opposite)
    - l2_distance: L2/Euclidean distance (0.0 = identical, ∞ = different)
    - inner_product: Negative inner product (more negative = more similar)

    For text collation, supports PostgreSQL COLLATE clause:
    - en_US.utf8: US English locale-aware sorting
    - fr_FR.utf8: French locale-aware sorting (accents, case)
    - C: Byte-order sorting (fastest)

    Attributes:
        field: The field name or nested path (e.g., 'amount' or 'profile.age')
               For vector distance: 'embedding.cosine_distance'
        direction: Sort direction ('asc' or 'desc')
        value: Optional value for vector distance operations (list[float])
        collation: Optional PostgreSQL collation for text sorting (str)

    Examples:
        OrderBy('amount') -> "data -> 'amount' ASC"
        OrderBy('name', collation='fr_FR.utf8') -> "data -> 'name' COLLATE "fr_FR.utf8" ASC"
        OrderBy('profile.age', 'desc') -> "data -> 'profile' -> 'age' DESC"
        OrderBy('embedding.cosine_distance', 'asc', [0.1, 0.2, 0.3]) ->
            "(data -> 'embedding') <=> '[0.1,0.2,0.3]'::vector ASC"
    """

    field: str
    direction: OrderDirection = OrderDirection.ASC
    value: list[float] | None = None
    collation: str | None = None

    def to_sql(
        self,
        table_ref: str = "t",
        native_columns: set[str] | None = None,
    ) -> sql.Composed:
        """Generate ORDER BY clause using JSONB numeric extraction or vector distance.

        Args:
            table_ref: Table alias or column name to use for JSONB access (default: "t")
            native_columns: Set of column names that are native SQL columns on the
                view (not inside JSONB). These use ``t."col"`` instead of JSONB
                extraction for correct index usage (#337).

        Uses data -> 'field' instead of data ->> 'field' to preserve proper
        numeric ordering. JSONB extraction (data->'field') maintains the
        original data type for comparison, while text extraction (data->>'field')
        converts everything to text causing lexicographic sorting.

        For nested fields like 'profile.age', uses:
        {table_ref} -> 'profile' -> 'age' (all JSONB extraction)

        For vector distance operations like 'embedding.cosine_distance', uses:
        ({table_ref} -> 'embedding') <=> '[0.1,0.2,...]'::vector
        """
        # Native column short-circuit: use t."col" instead of JSONB extraction (#337)
        if native_columns and self.field in native_columns:
            direction_str = (
                self.direction.value.upper()
                if isinstance(self.direction, OrderDirection)
                else str(self.direction).upper()
            )
            col_expr = sql.SQL("{}.{}").format(sql.Identifier("t"), sql.Identifier(self.field))
            return col_expr + sql.SQL(" ") + sql.SQL(direction_str)

        # Check if this is a vector distance operation
        if "." in self.field and self.value is not None:
            parts = self.field.split(".")
            if len(parts) == 2:  # field.operator format
                field_name, operator = parts
                if operator in ("cosine_distance", "l2_distance", "inner_product"):
                    return self._build_vector_distance_sql(
                        field_name, operator, self.value, table_ref
                    )

        # Standard JSONB extraction for regular fields
        path = self.field.split(".")
        json_path = sql.SQL(" -> ").join(sql.Literal(p) for p in path[:-1])
        last_key = sql.Literal(path[-1])
        if path[:-1]:
            # For nested fields: {table_ref} -> 'profile' -> 'age' (all JSONB)
            data_expr = sql.SQL(table_ref + " -> ") + json_path + sql.SQL(" -> ") + last_key
        else:
            # For simple fields: {table_ref} -> 'field' (JSONB)
            data_expr = sql.SQL(table_ref + " -> ") + last_key

        # Apply COLLATE clause if specified
        # IMPORTANT: Use sql.Identifier() for collation name (NOT sql.Literal())
        # PostgreSQL syntax: COLLATE "name" (identifier), not COLLATE 'name' (string)
        if self.collation is not None:
            collation_clause = sql.SQL(" COLLATE ") + sql.Identifier(self.collation)
            data_expr = data_expr + collation_clause

        # Handle both OrderDirection enum and string directions
        if isinstance(self.direction, OrderDirection):
            direction_str = self.direction.value.upper()
        else:
            direction_str = str(self.direction).upper()
        direction_sql = sql.SQL(direction_str)
        return data_expr + sql.SQL(" ") + direction_sql

    def _build_vector_distance_sql(
        self,
        field_name: str,
        operator: str,
        value: list[float] | dict[str, Any],
        table_ref: str = "t",
    ) -> sql.Composed:
        """Build SQL for vector distance ordering.

        Generates: ({table_ref}."field") <operator> '[0.1,0.2,...]'::vector

        Args:
            field_name: The vector field name (e.g., 'embedding')
            operator: The distance operator ('cosine_distance', 'l2_distance', 'inner_product')
            value: The vector to compare against
            table_ref: Table alias or column name to use for field access

        Returns:
            SQL fragment for vector distance ordering
        """
        # Map operator names to PostgreSQL operators and data types
        if isinstance(value, dict):
            # Sparse vector handling
            indices = value["indices"]
            vals = value["values"]
            dimension = max(indices) + 1 if indices else 0
            elements = ",".join(f"{idx}:{val}" for idx, val in zip(indices, vals, strict=True))
            literal_value = f"{{{elements}}}/{dimension}"
            type_cast = sql.SQL("::sparsevec")

            if operator == "cosine_distance":
                pg_operator_sql = sql.SQL("<=>")
            elif operator == "l2_distance":
                pg_operator_sql = sql.SQL("<->")
            elif operator == "inner_product":
                pg_operator_sql = sql.SQL("<#>")
            else:
                raise ValueError(f"Unsupported sparse vector operator: {operator}")
        else:
            # Dense vector handling
            literal_value = "[" + ",".join(str(v) for v in value) + "]"
            if operator == "cosine_distance":
                pg_operator_sql = sql.SQL("<=>")
                type_cast = sql.SQL("::vector")
            elif operator == "l2_distance":
                pg_operator_sql = sql.SQL("<->")
                type_cast = sql.SQL("::vector")
            elif operator == "l1_distance":
                pg_operator_sql = sql.SQL("<+>")
                type_cast = sql.SQL("::vector")
            elif operator == "inner_product":
                pg_operator_sql = sql.SQL("<#>")
                type_cast = sql.SQL("::vector")
            elif operator == "hamming_distance":
                pg_operator_sql = sql.SQL("<~>")
                type_cast = sql.SQL("::bit")
                literal_value = str(value)  # value is already a string for binary operators
            elif operator == "jaccard_distance":
                pg_operator_sql = sql.SQL("<%>")
                type_cast = sql.SQL("::bit")
                literal_value = str(value)  # value is already a string for binary operators
            else:
                raise ValueError(f"Unknown vector distance operator: {operator}")

        # Build SQL: ({table_ref}."field") <operator> 'literal'::type ASC

        # Handle both OrderDirection enum and string directions
        if isinstance(self.direction, OrderDirection):
            direction_str = "ASC" if self.direction == OrderDirection.ASC else "DESC"
        else:
            direction_str = str(self.direction).upper()
        direction_sql = sql.SQL(direction_str)
        return sql.Composed(
            [
                sql.SQL("("),
                sql.SQL(table_ref + "."),
                sql.Identifier(field_name),
                sql.SQL(")"),
                sql.SQL(" "),
                pg_operator_sql,
                sql.SQL(" "),
                sql.Literal(literal_value),
                type_cast,
                sql.SQL(" "),
                direction_sql,
            ]
        )


@dataclass(frozen=True)
class OrderBySet:
    """Represents a set of ORDER BY instructions for SQL query construction.

    Attributes:
        instructions: A sequence of `OrderBy` instances representing individual
            ORDER BY clauses to be combined.
    """

    instructions: Sequence[OrderBy]

    def to_sql(
        self,
        table_ref: str = "t",
        native_columns: set[str] | None = None,
    ) -> sql.Composed:
        """Compile the ORDER BY instructions into a psycopg SQL Composed object.

        Args:
            table_ref: Table alias or column name to use for field access (default: "t")
            native_columns: Set of native SQL column names to use column refs
                instead of JSONB extraction (#337).

        Returns:
            A `psycopg.sql.Composed` instance representing the full ORDER BY
            clause. Returns an empty SQL fragment if no instructions exist.
        """
        if not self.instructions:
            return sql.Composed([])  # Return empty Composed to satisfy Pyright
        clauses = sql.SQL(", ").join(
            instr.to_sql(table_ref, native_columns=native_columns) for instr in self.instructions
        )
        return sql.SQL("ORDER BY ") + clauses

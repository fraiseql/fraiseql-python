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

# The distance operators :meth:`OrderBy._build_vector_distance_sql` can render,
# in the order ``VectorOrderBy`` declares them so that the first operand set on
# one wins identically on every ``order_by`` shape. Both shapes read this tuple:
# they emitted different subsets of it until #483, and the three the gate below
# did not route -- ``l1_distance``, ``hamming_distance``, ``jaccard_distance`` --
# degraded into a JSONB path sort against a vector column.
VECTOR_DISTANCE_OPERATORS = (
    "cosine_distance",
    "l2_distance",
    "l1_distance",
    "inner_product",
    "hamming_distance",
    "jaccard_distance",
)


def _bit_cast(bit_string: str) -> sql.Composed:
    """Cast a bit-string literal to a bit type of its own width.

    A bare ``::bit`` is ``bit(1)``, so ``'1010...'::bit`` keeps the first bit and
    pgvector's bit operators then reject the comparison with *different bit
    lengths 64 and 1*. The width has to come from the literal (#483). A caller
    whose string does not match the column width still gets the server's
    length mismatch, which is the right error to surface.
    """
    return sql.SQL("::bit({})").format(sql.Literal(len(bit_string)))


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

    A collation is honoured on every path: a flat column collates directly, and
    a JSONB field is extracted as text (``->>``) so the collation has something
    to apply to. Requesting one therefore selects a *text* ordering -- which is
    what a collation means -- so do not set one on a numeric field. It also
    makes an explicit JSON ``null`` sort with an absent key (both become SQL
    NULL) rather than ahead of every string, as ``->`` does.

    Attributes:
        field: The field name or nested path (e.g., 'amount' or 'profile.age')
               For vector distance: 'embedding.cosine_distance'
        direction: Sort direction ('asc' or 'desc')
        value: Optional value for vector distance operations (list[float])
        collation: Optional PostgreSQL collation for text sorting (str)

    Examples:
        OrderBy('amount') -> "data -> 'amount' ASC"
        OrderBy('name', collation='fr_FR.utf8') -> "(data ->> 'name') COLLATE "fr_FR.utf8" ASC"
        OrderBy('profile.age', 'desc') -> "data -> 'profile' -> 'age' DESC"
        OrderBy('embedding.cosine_distance', 'asc', [0.1, 0.2, 0.3]) ->
            "(data -> 'embedding') <=> '[0.1,0.2,0.3]'::vector ASC"
    """

    field: str
    direction: OrderDirection = OrderDirection.ASC
    value: list[float] | None = None
    collation: str | None = None

    def _collated(self, expr: sql.Composed | sql.SQL) -> sql.Composed | sql.SQL:
        """Append ``COLLATE "name"`` to *expr*, or return it untouched.

        The collation name is rendered with :class:`~psycopg.sql.Identifier`, not
        :class:`~psycopg.sql.Literal`: PostgreSQL's syntax is ``COLLATE "name"``,
        and the name reaches here from configuration.

        Every branch of :meth:`to_sql` that can carry a collation routes through
        this, because the two flat-column branches used to return before the
        collation was applied at all (#476).
        """
        if self.collation is None:
            return expr
        return expr + sql.SQL(" COLLATE ") + sql.Identifier(self.collation)

    def _direction_sql(self) -> sql.SQL:
        """Render the sort direction, accepting either the enum or a bare string."""
        direction_str = (
            self.direction.value.upper()
            if isinstance(self.direction, OrderDirection)
            else str(self.direction).upper()
        )
        return sql.SQL(direction_str)

    def _flat_column(
        self,
        native_columns: set[str] | None,
        column_mapping: dict[str, str] | None,
    ) -> str | None:
        """Return the flat column this instruction sorts on, or None for JSONB.

        Shares :func:`resolve_native_column` with the GROUP BY builders, because
        the two must agree: PostgreSQL requires a sort key to be grouped or
        functionally determined by the grouping, and two different expressions
        for one logical field is how that constraint gets violated.

        ``native_measures`` is deliberately not passed. A measure is aggregated
        in the SELECT list, so resolving a sort key to its raw column would
        produce an ungrouped reference.
        """
        from fraiseql.sql.native_columns import resolve_native_column

        return resolve_native_column(
            self.field, native_columns=native_columns, column_mapping=column_mapping
        )

    def to_sql(
        self,
        table_ref: str = "t",
        native_columns: set[str] | None = None,
        column_mapping: dict[str, str] | None = None,
    ) -> sql.Composed:
        """Generate ORDER BY clause using JSONB numeric extraction or vector distance.

        Args:
            table_ref: Table alias or column name to use for JSONB access (default: "t")
            native_columns: Set of column names that are native SQL columns on the
                view (not inside JSONB). These use ``t."col"`` instead of JSONB
                extraction for correct index usage (#337).
            column_mapping: Map of dotted field path → flat SQL column name, as
                declared by ``column_mapping=`` / ``native_dimension_mapping``.
                Reaches deep paths ``native_columns`` cannot express (#467).

        Uses data -> 'field' instead of data ->> 'field' to preserve proper
        numeric ordering. JSONB extraction (data->'field') maintains the
        original data type for comparison, while text extraction (data->>'field')
        converts everything to text causing lexicographic sorting.

        For nested fields like 'profile.age', uses:
        {table_ref} -> 'profile' -> 'age' (all JSONB extraction)

        For vector distance operations like 'embedding.cosine_distance', uses:
        ({table_ref} -> 'embedding') <=> '[0.1,0.2,...]'::vector
        """
        # Flat column short-circuit: use t."col" instead of JSONB extraction.
        # A collation applies here exactly as it would to any text column.
        flat_column = self._flat_column(native_columns, column_mapping)
        if flat_column is not None:
            col_expr = sql.SQL("{}.{}").format(sql.Identifier("t"), sql.Identifier(flat_column))
            return self._collated(col_expr) + sql.SQL(" ") + self._direction_sql()

        # Check if this is a vector distance operation
        if "." in self.field and self.value is not None:
            parts = self.field.split(".")
            if len(parts) == 2:  # field.operator format
                field_name, operator = parts
                if operator in VECTOR_DISTANCE_OPERATORS:
                    return self._build_vector_distance_sql(
                        field_name, operator, self.value, table_ref
                    )

        # Standard JSONB extraction for regular fields.
        #
        # The leaf is extracted with -> (jsonb) so numbers sort numerically
        # rather than lexicographically -- except when a collation is asked
        # for. jsonb has no collation, so the leaf must come out as text for
        # the request to mean anything, and the whole extraction has to be
        # parenthesised: COLLATE binds tighter than ->, so the unparenthesised
        # `data -> 'name' COLLATE "x"` parses as `data -> ('name' COLLATE "x")`,
        # attaching the collation to the *key literal*. PostgreSQL accepts that
        # and silently ignores it, which is how it went unnoticed (#476).
        #
        # Asking for a collation is asking for a text ordering, so -> is only
        # traded for ->> on the branch that requested one; an uncollated sort
        # keeps its previous SQL byte for byte.
        path = self.field.split(".")
        json_path = sql.SQL(" -> ").join(sql.Literal(p) for p in path[:-1])
        last_key = sql.Literal(path[-1])
        leaf_op = sql.SQL(" ->> ") if self.collation is not None else sql.SQL(" -> ")
        if path[:-1]:
            # For nested fields: {table_ref} -> 'profile' -> 'age'
            data_expr = sql.SQL(table_ref + " -> ") + json_path + leaf_op + last_key
        else:
            # For simple fields: {table_ref} -> 'field'
            data_expr = sql.SQL(table_ref) + leaf_op + last_key

        if self.collation is not None:
            data_expr = sql.SQL("({})").format(data_expr)

        return self._collated(data_expr) + sql.SQL(" ") + self._direction_sql()

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
            operator: One of :data:`VECTOR_DISTANCE_OPERATORS`
            value: The vector to compare against
            table_ref: Table alias or column name to use for field access

        Returns:
            SQL fragment for vector distance ordering
        """
        # Map operator names to PostgreSQL operators and data types
        # Set to a function name by any operator that must render as a call rather
        # than an infix operator; pg_operator_sql is None in exactly those cases.
        pg_function_sql = None

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
            elif operator == "l1_distance":
                pg_operator_sql = sql.SQL("<+>")
            elif operator == "inner_product":
                pg_operator_sql = sql.SQL("<#>")
            else:
                # hamming_distance and jaccard_distance are bit-string operators;
                # pgvector has no sparsevec form of either.
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
                literal_value = str(value)  # value is already a string for binary operators
                type_cast = _bit_cast(literal_value)
            elif operator == "jaccard_distance":
                # Rendered as jaccard_distance(col, lit), not as the <%> operator.
                # psycopg scans a statement for placeholders whenever parameters
                # accompany it, and rejects `%>` as one; escaping to `<%%>` only
                # moves the failure to the no-parameter statements, which are sent
                # verbatim and then have no such operator. The function form is the
                # one spelling correct under both, at the cost of the
                # bit_jaccard_ops index, which cannot match a function call (#495).
                pg_operator_sql = None
                pg_function_sql = sql.SQL("jaccard_distance")
                literal_value = str(value)  # value is already a string for binary operators
                type_cast = _bit_cast(literal_value)
            else:
                raise ValueError(f"Unknown vector distance operator: {operator}")

        # Build SQL: ({table_ref}."field") <operator> 'literal'::type ASC
        # or, where pg_operator_sql is None: func({table_ref}."field", 'literal'::type) ASC

        # Handle both OrderDirection enum and string directions
        if isinstance(self.direction, OrderDirection):
            direction_str = "ASC" if self.direction == OrderDirection.ASC else "DESC"
        else:
            direction_str = str(self.direction).upper()
        direction_sql = sql.SQL(direction_str)
        column_sql = sql.Composed(
            [sql.SQL(table_ref + "."), sql.Identifier(field_name)],
        )
        if pg_operator_sql is None:
            return sql.Composed(
                [
                    pg_function_sql,
                    sql.SQL("("),
                    column_sql,
                    sql.SQL(", "),
                    sql.Literal(literal_value),
                    type_cast,
                    sql.SQL(") "),
                    direction_sql,
                ]
            )
        return sql.Composed(
            [
                sql.SQL("("),
                column_sql,
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
        column_mapping: dict[str, str] | None = None,
    ) -> sql.Composed:
        """Compile the ORDER BY instructions into a psycopg SQL Composed object.

        Args:
            table_ref: Table alias or column name to use for field access (default: "t")
            native_columns: Set of native SQL column names to use column refs
                instead of JSONB extraction (#337).
            column_mapping: Map of dotted field path → flat SQL column name, for
                deep paths ``native_columns`` cannot express (#467).

        Returns:
            A `psycopg.sql.Composed` instance representing the full ORDER BY
            clause. Returns an empty SQL fragment if no instructions exist.
        """
        if not self.instructions:
            return sql.Composed([])  # Return empty Composed to satisfy Pyright
        clauses = sql.SQL(", ").join(
            instr.to_sql(table_ref, native_columns=native_columns, column_mapping=column_mapping)
            for instr in self.instructions
        )
        return sql.SQL("ORDER BY ") + clauses

    def uses_flat_columns(
        self,
        native_columns: set[str] | None = None,
        column_mapping: dict[str, str] | None = None,
    ) -> bool:
        """True when any instruction sorts on a flat column rather than JSONB.

        A flat column renders as ``t."col"``, so the caller must make sure the
        FROM clause actually carries the ``t`` alias. Aggregated queries always
        do; a plain ``SELECT data::text FROM view`` does not until a mapping
        makes one of its sort keys native.
        """
        return any(
            instr._flat_column(native_columns, column_mapping) is not None
            for instr in self.instructions
        )

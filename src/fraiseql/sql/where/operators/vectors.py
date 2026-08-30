"""Vector/embedding specific operators for PostgreSQL pgvector.

This module exposes PostgreSQL's native pgvector distance operators:
- <=> : cosine distance (0.0 = identical, 2.0 = opposite)
- <-> : L2/Euclidean distance (0.0 = identical, ∞ = very different)
- <#> : negative inner product (more negative = more similar)

FraiseQL exposes these operators transparently without abstraction.
Distance values are returned raw from PostgreSQL (no conversion to similarity).
"""

from typing import Any

from psycopg.sql import SQL, Composed, Literal


def _bit_cast(bit_string: str) -> Composed:
    """Cast a bit-string operand to a bit type of its own width.

    A bare ``::bit`` is ``bit(1)``, so ``'1010...'::bit`` keeps only the first
    bit. Applied to *both* operands -- as it was here until #494 -- the lengths
    still agree, no error is raised, and the distance is computed over a single
    bit: every row reports 0 and a threshold filter matches everything.

    The width has to come from the literal. The column side needs the cast too,
    because this path renders a JSONB extraction (``data ->> 'field'``) that
    arrives as text, not as a ``bit(n)`` column. Mirrors ``_bit_cast`` in
    :mod:`fraiseql.sql.order_by_generator`, which fixed the ORDER BY half (#483).
    """
    return SQL("::bit({})").format(Literal(len(bit_string)))


def build_cosine_distance_sql(path_sql: SQL, value: list[float]) -> Composed:
    """Build SQL for cosine distance using PostgreSQL <=> operator.

    Generates: column <=> '[0.1,0.2,...]'::vector
    Returns distance: 0.0 (identical) to 2.0 (opposite)
    """
    vector_literal = "[" + ",".join(str(v) for v in value) + "]"
    return Composed(
        [SQL("("), path_sql, SQL(")::vector <=> "), Literal(vector_literal), SQL("::vector")]
    )


def build_l2_distance_sql(path_sql: SQL, value: list[float]) -> Composed:
    """Build SQL for L2/Euclidean distance using PostgreSQL <-> operator.

    Generates: column <-> '[0.1,0.2,...]'::vector
    Returns distance: 0.0 (identical) to ∞ (very different)
    """
    vector_literal = "[" + ",".join(str(v) for v in value) + "]"
    return Composed(
        [SQL("("), path_sql, SQL(")::vector <-> "), Literal(vector_literal), SQL("::vector")]
    )


def build_inner_product_sql(path_sql: SQL, value: list[float]) -> Composed:
    """Build SQL for inner product using PostgreSQL <#> operator.

    Generates: column <#> '[0.1,0.2,...]'::vector
    Returns negative inner product: more negative = more similar
    """
    vector_literal = "[" + ",".join(str(v) for v in value) + "]"
    return Composed(
        [SQL("("), path_sql, SQL(")::vector <#> "), Literal(vector_literal), SQL("::vector")]
    )


def build_l1_distance_sql(path_sql: SQL, value: list[float]) -> Composed:
    """Build SQL for L1/Manhattan distance using PostgreSQL <+> operator.

    Generates: column <+> '[0.1,0.2,...]'::vector
    Returns distance: sum of absolute differences
    """
    vector_literal = "[" + ",".join(str(v) for v in value) + "]"
    return Composed(
        [SQL("("), path_sql, SQL(")::vector <+> "), Literal(vector_literal), SQL("::vector")]
    )


def build_hamming_distance_sql(path_sql: SQL, value: str) -> Composed:
    """Build SQL for Hamming distance using PostgreSQL <~> operator.

    Generates: (column)::bit(6) <~> '101010'::bit(6)
    Returns distance: number of differing bits

    Note: Hamming distance works on bit type vectors, not float vectors.
    Use for categorical features, fingerprints, or binary similarity.
    """
    bit_cast = _bit_cast(value)
    return Composed(
        [SQL("("), path_sql, SQL(")"), bit_cast, SQL(" <~> "), Literal(value), bit_cast]
    )


def build_jaccard_distance_sql(path_sql: SQL, value: str) -> Composed:
    """Build SQL for Jaccard distance using PostgreSQL <%> operator.

    Generates: (column)::bit(6) <%> '111000'::bit(6)
    Returns distance: 1 - (intersection / union) for bit sets

    Note: Jaccard distance works on bit type vectors for set similarity.
    Useful for recommendation systems, tag similarity, feature matching.
    """
    bit_cast = _bit_cast(value)
    return Composed(
        [SQL("("), path_sql, SQL(")"), bit_cast, SQL(" <%> "), Literal(value), bit_cast]
    )


def build_sparse_cosine_distance_sql(path_sql: SQL, value: dict[str, Any]) -> Composed:
    """Build SQL for sparse vector cosine distance using PostgreSQL <=> operator.

    Generates: column <=> '{1:0.1,3:0.2,5:0.3}/dimension'::sparsevec
    Returns distance: 0.0 (identical) to 2.0 (opposite)
    """
    # Convert sparse vector dict to pgvector format
    indices = value["indices"]
    values = value["values"]
    # Assume dimension is the maximum index + 1 (this should be configurable)
    dimension = max(indices) + 1 if indices else 0

    # Create sparse vector literal in pgvector format: {index1:value1,index2:value2,...}/dimension
    elements = ",".join(f"{idx}:{val}" for idx, val in zip(indices, values, strict=True))
    sparse_literal = f"{{{elements}}}/{dimension}"

    return Composed(
        [SQL("("), path_sql, SQL(")::sparsevec <=> "), Literal(sparse_literal), SQL("::sparsevec")]
    )


def build_sparse_l2_distance_sql(path_sql: SQL, value: dict[str, Any]) -> Composed:
    """Build SQL for sparse vector L2 distance using PostgreSQL <-> operator.

    Args:
        path_sql: SQL fragment for the vector column path
        value: Sparse vector value with 'indices' and 'values' keys

    Returns:
        Composed SQL fragment for the distance calculation
    """
    # Convert sparse vector dict to pgvector format
    indices = value["indices"]
    values = value["values"]
    dimension = max(indices) + 1 if indices else 0

    elements = ",".join(f"{idx}:{val}" for idx, val in zip(indices, values, strict=True))
    sparse_literal = f"{{{elements}}}/{dimension}"

    return Composed(
        [SQL("("), path_sql, SQL(")::sparsevec <-> "), Literal(sparse_literal), SQL("::sparsevec")]
    )


def build_sparse_inner_product_sql(path_sql: SQL, value: dict[str, Any]) -> Composed:
    """Build SQL for sparse vector inner product using PostgreSQL <#> operator.

    Args:
        path_sql: SQL fragment for the vector column path
        value: Sparse vector value with 'indices' and 'values' keys

    Returns:
        Composed SQL fragment for the inner product calculation

    Generates: column <#> '{1:0.1,3:0.2,5:0.3}/dimension'::sparsevec
    Returns negative inner product: more negative = more similar
    """
    # Convert sparse vector dict to pgvector format
    indices = value["indices"]
    values = value["values"]
    dimension = max(indices) + 1 if indices else 0

    elements = ",".join(f"{idx}:{val}" for idx, val in zip(indices, values, strict=True))
    sparse_literal = f"{{{elements}}}/{dimension}"

    return Composed(
        [SQL("("), path_sql, SQL(")::sparsevec <#> "), Literal(sparse_literal), SQL("::sparsevec")]
    )


# Vector aggregation functions for use with aggregate() method
def build_vector_sum_aggregation(path_sql: SQL) -> Composed:
    """Build SQL for vector SUM aggregation.

    Generates: SUM(column)::vector
    Returns sum of all vectors in the group
    """
    return Composed([SQL("SUM("), path_sql, SQL(")::vector")])


def build_vector_avg_aggregation(path_sql: SQL) -> Composed:
    """Build SQL for vector AVG aggregation.

    Generates: AVG(column)::vector
    Returns average of all vectors in the group
    """
    return Composed([SQL("AVG("), path_sql, SQL(")::vector")])


def build_sparse_vector_sum_aggregation(path_sql: SQL) -> Composed:
    """Build SQL for sparse vector SUM aggregation.

    Generates: SUM(column)::sparsevec
    Returns sum of all sparse vectors in the group
    """
    return Composed([SQL("SUM("), path_sql, SQL(")::sparsevec")])


def build_sparse_vector_avg_aggregation(path_sql: SQL) -> Composed:
    """Build SQL for sparse vector AVG aggregation.

    Generates: AVG(column)::sparsevec
    Returns average of all sparse vectors in the group
    """
    return Composed([SQL("AVG("), path_sql, SQL(")::sparsevec")])


def build_half_vector_sum_aggregation(path_sql: SQL) -> Composed:
    """Build SQL for half-vector SUM aggregation.

    Generates: SUM(column)::halfvec
    Returns sum of all half-vectors in the group
    """
    return Composed([SQL("SUM("), path_sql, SQL(")::halfvec")])


def build_half_vector_avg_aggregation(path_sql: SQL) -> Composed:
    """Build SQL for half-vector AVG aggregation.

    Generates: AVG(column)::halfvec
    Returns average of all half-vectors in the group
    """
    return Composed([SQL("AVG("), path_sql, SQL(")::halfvec")])


def build_custom_distance_sql(path_sql: SQL, value: dict[str, Any]) -> Composed:
    """Build SQL for custom distance function.

    Allows calling user-defined distance functions with custom parameters.

    Args:
        path_sql: SQL for the vector column path
        value: Dict with 'function' key and optional 'parameters' key

    Generates: custom_distance_function(column, param1, param2, ...)
    """
    if not isinstance(value, dict) or "function" not in value:
        raise ValueError("Custom distance requires 'function' key")

    function_name = value["function"]
    parameters = value.get("parameters", [])

    # Build function call: function_name(column, param1, param2, ...)
    sql_parts = [SQL(function_name), SQL("("), path_sql]

    for param in parameters:
        sql_parts.extend([SQL(", "), SQL(str(param))])

    sql_parts.append(SQL(")"))

    return Composed(sql_parts)


def build_vector_norm_sql(path_sql: SQL, value: Any) -> Composed:
    """Build SQL for vector norm calculation.

    Generates: vector_norm(column, 'p_norm') or similar
    Useful for L1, L2, etc. norms
    """
    # For now, implement as a simple wrapper around vector_norm function
    # This could be extended to support different norm types
    return Composed([SQL("vector_norm("), path_sql, SQL(", 'l2')")])


def build_quantized_distance_sql(path_sql: SQL, value: dict[str, Any]) -> Composed:
    """Build SQL for quantized vector distance calculation.

    This requires reconstructing the vector from the quantized representation
    and then performing distance calculation.

    Args:
        path_sql: SQL for the quantized vector column path
        value: Dict with quantization parameters and target vector

    Generates: custom function call for quantized distance
    """
    if not isinstance(value, dict) or "target_vector" not in value:
        raise ValueError("Quantized distance requires 'target_vector' key")

    target_vector = value["target_vector"]
    distance_type = value.get("distance_type", "cosine")

    # This would require custom PostgreSQL functions for quantization
    # For now, implement as a placeholder that calls a custom function
    function_name = f"quantized_{distance_type}_distance"

    if isinstance(target_vector, list):
        # Dense target vector
        vector_literal = "[" + ",".join(str(v) for v in target_vector) + "]"
        return Composed(
            [
                SQL(function_name),
                SQL("("),
                path_sql,
                SQL(", "),
                SQL(vector_literal),
                SQL("::vector)"),
            ]
        )
    # Could support sparse target vectors too
    raise ValueError("Quantized distance currently only supports dense target vectors")


def build_quantization_reconstruct_sql(path_sql: SQL, value: Any) -> Composed:
    """Build SQL for reconstructing a vector from quantized representation.

    Generates: reconstruct_quantized_vector(column)
    Returns the reconstructed full vector
    """
    return Composed([SQL("reconstruct_quantized_vector("), path_sql, SQL(")")])

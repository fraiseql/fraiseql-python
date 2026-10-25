"""Vector/embedding specific operators for PostgreSQL pgvector.

This module exposes PostgreSQL's native pgvector distance operators:
- <=> : cosine distance (0.0 = identical, 2.0 = opposite)
- <-> : L2/Euclidean distance (0.0 = identical, ∞ = very different)
- <#> : negative inner product (more negative = more similar)

FraiseQL exposes these operators transparently without abstraction.
Distance values are returned raw from PostgreSQL (no conversion to similarity).
"""

import warnings
from typing import Any, NoReturn

from psycopg.sql import SQL, Composed, Literal

from fraiseql.errors.exceptions import WhereClauseError

#: Distance operators whose expression is a number and therefore needs an
#: explicit comparison before it can serve as a WHERE predicate (#505).
VECTOR_DISTANCE_OPERATORS = frozenset(
    {
        "cosine_distance",
        "l2_distance",
        "l1_distance",
        "inner_product",
        "hamming_distance",
        "jaccard_distance",
    }
)

#: Vector operators that render an expression rather than a boolean and can
#: therefore never serve as a WHERE predicate (#510), mapped to the two halves
#: of the error each one raises: what it used to render, and what to do instead.
#:
#: These stay registered in ``OPERATOR_MAP`` deliberately. Deleting the entries
#: would make ``get_operator_function`` raise ``ValueError``, which
#: ``_make_filter_field_composed`` swallows with ``except ValueError: continue``
#: -- the filter would vanish while its sibling scoping filters survived, and
#: the query would succeed against a wider set of rows than was asked for.
#: A registered builder that raises ``WhereClauseError`` fails loudly instead.
NON_PREDICATE_OPERATORS: dict[str, tuple[str, str]] = {
    "custom_distance": (
        "a call to a caller-supplied function",
        "FraiseQL cannot validate an arbitrary function name or its parameters. "
        "Expose the distance as a column in your view and filter on that column, "
        "or use one of the supported distance operators.",
    ),
    "vector_norm": (
        "a bare norm expression",
        "A norm is a number. Expose it as a column in your view and filter on that column.",
    ),
}

#: Comparison keyword -> SQL operator, mirroring ``where_clause.py``.
VECTOR_COMPARISON_SQL = {
    "lt": "<",
    "lte": "<=",
    "gt": ">",
    "gte": ">=",
    "eq": "=",
    "neq": "<>",
}

#: Applied when a filter names no threshold at all, as ``where_clause.py`` does.
#: Deprecated: :func:`warn_missing_threshold` says so, and the default will go.
DEFAULT_DISTANCE_THRESHOLD = 0.5


def warn_missing_threshold(field_name: str | None, operator: str, *, stacklevel: int) -> None:
    """Warn that a distance filter fell back to :data:`DEFAULT_DISTANCE_THRESHOLD`.

    The GraphQL ``VectorFilter`` refuses a distance operator without
    ``distanceWithin``. The Python ``where`` dict still accepts one without a
    ``"threshold"`` and filters at ``< 0.5``, a distance nobody asked for.
    """
    field = f"{field_name!r} " if field_name else ""
    warnings.warn(
        f'where: {field}{operator} without a "threshold" filters at a distance '
        f"< {DEFAULT_DISTANCE_THRESHOLD}; this default is deprecated and will be removed, "
        'pass {"vector": ..., "threshold": ...}',
        DeprecationWarning,
        stacklevel=stacklevel + 1,
    )


def _reject(message: str, operator: str, value: object) -> WhereClauseError:
    """Build the error raised for an unusable vector filter payload.

    Deliberately *not* a :class:`ValueError`. ``_make_filter_field_composed``
    wraps operator construction in ``except ValueError: continue``, so a
    ``ValueError`` here would drop the predicate from the WHERE clause while
    every sibling filter survived -- the query would then succeed and return
    rows the similarity threshold was meant to exclude.
    """
    return WhereClauseError(
        f"{message} (operator {operator!r}, got {value!r})",
        operator=operator,
        supported_operators=sorted(VECTOR_DISTANCE_OPERATORS),
    )


def _reject_non_predicate(operator: str) -> WhereClauseError:
    """Build the error raised for a vector operator that is not a predicate.

    Like :func:`_reject`, deliberately not a :class:`ValueError`: the caller
    swallows those and drops the filter rather than failing the query.
    """
    renders, remedy = NON_PREDICATE_OPERATORS[operator]
    return WhereClauseError(
        f"{operator!r} is not a WHERE predicate: it renders {renders}, not a boolean. {remedy}",
        operator=operator,
        supported_operators=sorted(VECTOR_DISTANCE_OPERATORS),
    )


def unpack_distance_filter(
    value: object,
    *,
    operator: str,
    distance_within: float | None = None,
    field_name: str | None = None,
) -> tuple[Any, float, str]:
    """Normalise a vector distance filter into ``(query_vector, threshold, comparison)``.

    Two input shapes reach this code and both are supported:

    * the normalised form used by :mod:`fraiseql.where_clause` --
      ``{"vector": ..., "threshold": 0.5, "comparison": "lt"}``;
    * the GraphQL form declared by ``VectorFilter`` -- ``{"dense": [...]}``,
      with the threshold supplied by the sibling ``distance_within`` field.

    A sparse operand (``{"sparse": ...}`` or ``{"indices", "values"}``) is
    refused: there is no sparse builder, and its literal needs the column's
    dimension.

    A bare list or tuple is always the query vector itself; a bare string is a
    bit vector for the Hamming and Jaccard operators. There is deliberately no
    ``(vector, threshold)`` 2-tuple form: it cannot be told apart from a
    two-dimensional query vector, so ``[0.1, 0.2]`` would silently filter on a
    0.1-dimensional vector with a 0.2 threshold.

    With no threshold at all, :data:`DEFAULT_DISTANCE_THRESHOLD` applies and a
    ``DeprecationWarning`` naming ``field_name`` and ``operator`` is emitted.

    Raises:
        WhereClauseError: If the payload, threshold or comparison is unusable.
    """
    threshold: object | None = None
    comparison: object | None = None

    if isinstance(value, dict):
        query_vector = None
        for key in ("vector", "dense"):
            if key in value:
                query_vector = value[key]
                break
        if query_vector is None and (
            value.get("sparse") is not None or ("indices" in value and "values" in value)
        ):
            raise _reject(
                "A sparse query vector can't be filtered on (its literal needs the "
                "column's dimension); pass a dense vector",
                operator,
                value,
            )
        if not any(key in value for key in ("vector", "dense")):
            raise _reject("Vector filter needs 'vector' or 'dense'", operator, value)
        threshold = value.get("threshold")
        comparison = value.get("comparison")
    elif isinstance(value, (list, tuple)):
        query_vector = list(value)
    elif isinstance(value, str):
        query_vector = value
    else:
        raise _reject("Vector filter must be a mapping, sequence or bit string", operator, value)

    if query_vector is None:
        raise _reject("Vector filter carries no query vector", operator, value)

    if threshold is None and distance_within is not None:
        threshold = distance_within
        if comparison is None:
            # 'distance_within' reads as "maximum distance to include".
            comparison = "lte"
    if threshold is None:
        warn_missing_threshold(field_name, operator, stacklevel=2)
        threshold = DEFAULT_DISTANCE_THRESHOLD
    if comparison is None:
        comparison = "lt"

    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise _reject("Vector distance threshold must be a number", operator, threshold)
    if comparison not in VECTOR_COMPARISON_SQL:
        raise _reject(
            f"Unsupported vector comparison; expected one of {sorted(VECTOR_COMPARISON_SQL)}",
            operator,
            comparison,
        )

    return query_vector, float(threshold), comparison


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
    """Build SQL for Jaccard distance using pgvector's jaccard_distance function.

    Generates: jaccard_distance((column)::bit(6), '111000'::bit(6))
    Returns distance: 1 - (intersection / union) for bit sets

    Rendered as a function call rather than with the ``<%>`` operator. psycopg
    scans a statement for placeholders whenever parameters accompany it and
    rejects ``%>`` as one, so an ``<%>`` term fails as soon as anything else in
    the statement parameterises. Escaping to ``<%%>`` only moves the failure:
    a statement sent without parameters is passed verbatim and PostgreSQL then
    has no such operator. The function form is the one spelling correct under
    both, at the cost of the bit_jaccard_ops index, which cannot match a
    function call (#495).

    Note: Jaccard distance works on bit type vectors for set similarity.
    Useful for recommendation systems, tag similarity, feature matching.
    """
    bit_cast = _bit_cast(value)
    return Composed(
        [
            SQL("jaccard_distance(("),
            path_sql,
            SQL(")"),
            bit_cast,
            SQL(", "),
            Literal(value),
            bit_cast,
            SQL(")"),
        ]
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


def build_custom_distance_sql(path_sql: SQL, value: dict[str, Any]) -> NoReturn:
    """Reject ``custom_distance`` in a WHERE clause (#510).

    The operator rendered ``<function>(<column>, <param>, ...)`` -- a bare
    function call whose type is whatever the function returns, never a boolean.

    It also concatenated two caller-supplied strings straight into the
    statement. ``psycopg.sql.SQL()`` is the raw-fragment constructor and
    performs no escaping, so both the ``function`` name and every entry of
    ``parameters`` were interpolated verbatim::

        {"function": "true OR 1=1 --"}                    -> WHERE true OR 1=1 --(...)
        {"function": "strpos", "parameters": ["'x') > -1 OR true --"]}

    Both forms parse and return every row. FraiseQL has no registry of
    user-defined distance functions to validate a name against, so there is
    nothing to allow-list and no safe way to build the call from a filter dict.
    """
    raise _reject_non_predicate("custom_distance")


def build_vector_norm_sql(path_sql: SQL, value: Any) -> NoReturn:
    """Reject ``vector_norm`` in a WHERE clause (#510).

    The operator rendered ``vector_norm(<column>, 'l2')``, ignoring ``value``
    entirely. pgvector declares ``vector_norm(vector)`` -- one argument -- so
    that call does not exist at any arity and PostgreSQL rejected it with
    ``function vector_norm(text, unknown) does not exist`` on every execution.
    The column side was never cast to ``vector`` either.

    A norm is a number, so even spelled correctly it is not a predicate.
    """
    raise _reject_non_predicate("vector_norm")

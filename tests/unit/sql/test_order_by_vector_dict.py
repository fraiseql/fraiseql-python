"""A dict ``order_by`` can sort by vector distance, like ``VectorOrderBy``.

``{"embedding": {"cosine_distance": [...]}}`` was dropped with "cannot read a
sort direction from list", and a ``hamming_distance`` bit string was read as a
direction (DESC) on a field named ``hamming_distance``.
"""

import warnings

import pytest

from fraiseql.sql.graphql_order_by_generator import _convert_order_by_input_to_sql
from fraiseql.sql.order_by_generator import OrderDirection

_BITS = "0000000000100010100000100111001111100101001010111011101110100100"


def _instructions(order_by):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = _convert_order_by_input_to_sql(order_by)
    return [(i.field, i.direction, i.value) for i in result.instructions]


@pytest.mark.parametrize(
    ("order_by", "field", "value"),
    [
        ({"embedding": {"cosine_distance": [0.1, 0.2]}}, "embedding.cosine_distance", [0.1, 0.2]),
        ({"embedding": {"cosineDistance": [0.1, 0.2]}}, "embedding.cosine_distance", [0.1, 0.2]),
        ([{"embedding": {"l2_distance": [0.1, 0.2]}}], "embedding.l2_distance", [0.1, 0.2]),
        ({"embedding": {"inner_product": (0.1, 0.2)}}, "embedding.inner_product", (0.1, 0.2)),
        ({"fingerprint": {"hamming_distance": _BITS}}, "fingerprint.hamming_distance", _BITS),
        ({"fingerprint": {"jaccardDistance": _BITS}}, "fingerprint.jaccard_distance", _BITS),
    ],
)
def test_distance(order_by, field, value) -> None:
    assert _instructions(order_by) == [(field, OrderDirection.ASC, value)]


def test_a_field_named_like_an_operator_still_takes_a_direction() -> None:
    assert _instructions({"stats": {"cosine_distance": "desc"}}) == [
        ("stats.cosine_distance", OrderDirection.DESC, None)
    ]


def test_distance_next_to_other_keys() -> None:
    assert _instructions([{"embedding": {"cosine_distance": [1.0]}}, {"title": "asc"}]) == [
        ("embedding.cosine_distance", OrderDirection.ASC, [1.0]),
        ("title", OrderDirection.ASC, None),
    ]


# GraphQL sends the operand as a VectorDistanceInput, the same input `where` takes
_COSINE_SQL = "(t.\"embedding\") <=> '[0.1,0.2]'::vector ASC"


@pytest.mark.parametrize(
    "order_by",
    [
        {"embedding": {"cosineDistance": {"dense": [0.1, 0.2]}}},
        [{"embedding": {"cosine_distance": {"dense": [0.1, 0.2]}}}],
        {"embedding": {"cosineDistance": {"dense": [0.1, 0.2], "sparse": None}}},
    ],
)
def test_dense_operand_renders_the_vector(order_by) -> None:
    [instruction] = _convert_order_by_input_to_sql(order_by).instructions
    assert instruction.to_sql().as_string(None) == _COSINE_SQL


def test_vector_order_by_takes_a_distance_input() -> None:
    from fraiseql.sql.graphql_order_by_generator import VectorOrderBy
    from fraiseql.sql.graphql_where_generator import VectorDistanceInput

    order_by = {"embedding": VectorOrderBy(cosine_distance=VectorDistanceInput(dense=[0.1, 0.2]))}
    [instruction] = _convert_order_by_input_to_sql(order_by).instructions
    assert instruction.to_sql().as_string(None) == _COSINE_SQL


@pytest.mark.parametrize(
    "operand",
    [
        {"sparse": {"indices": [1, 3], "values": [0.1, 0.2]}},
        {"indices": [1, 3], "values": [0.1, 0.2]},
    ],
)
def test_sparse_operand_is_refused(operand) -> None:
    [instruction] = _convert_order_by_input_to_sql(
        {"embedding": {"cosine_distance": operand}}
    ).instructions
    with pytest.raises(ValueError, match=r"'embedding\.cosine_distance' needs a dense vector"):
        instruction.to_sql()

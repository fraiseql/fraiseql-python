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

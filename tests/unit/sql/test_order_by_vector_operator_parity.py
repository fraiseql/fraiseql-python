"""Issue #483: every ``VectorOrderBy`` operator must render, on both order_by shapes.

``VectorOrderBy`` accepts six distance operators. ``OrderBy.to_sql`` gated its
vector branch on three of them, and the two ``order_by`` shapes disagreed about
which ones to emit at all:

* the dict shape emitted only the three the gate accepted, so ``l1_distance``,
  ``hamming_distance`` and ``jaccard_distance`` produced **no instruction** —
  the query ran with no ``ORDER BY`` and returned rows in whatever order the
  scan produced;
* the ``__gql_fields__`` shape emitted all six, so those same three fell past
  the gate into plain JSONB extraction — ``t -> 'fingerprint' -> 'jaccard_distance'``
  against a ``bit`` column, which the server rejects outright.

The ``__gql_fields__`` shape had a second defect on top: a ``VectorOrderBy`` was
handled and then *also* recursed into as if it were a nested order-by input, so
the two bit-string operators emitted a **second** instruction. Their operand is
a ``str``, and ``_normalize_order_direction`` reads any string that is not
``"ASC"`` as ``DESC``, so ``jaccard_distance="111000"`` appended a contradictory
``... DESC`` term after the real one.

Both shapes now read one operator tuple and append through one helper, so a
seventh operator cannot reach one shape and not the other.
"""

from uuid import UUID

import pytest

from fraiseql.sql.graphql_order_by_generator import (
    VectorOrderBy,
    _convert_order_by_input_to_sql,
    create_graphql_order_by_input,
)
from fraiseql.types import fraise_type

pytestmark = pytest.mark.unit

DENSE = [0.1, 0.2, 0.3]
BITS = "111000"

# operator -> (operand, rendered SQL fragment)
OPERATORS = {
    "cosine_distance": (DENSE, "(t.\"embedding\") <=> '[0.1,0.2,0.3]'::vector ASC"),
    "l2_distance": (DENSE, "(t.\"embedding\") <-> '[0.1,0.2,0.3]'::vector ASC"),
    "l1_distance": (DENSE, "(t.\"embedding\") <+> '[0.1,0.2,0.3]'::vector ASC"),
    "inner_product": (DENSE, "(t.\"embedding\") <#> '[0.1,0.2,0.3]'::vector ASC"),
    # ``::bit`` alone is ``bit(1)``: the literal has to carry its own width or
    # pgvector rejects the comparison with "different bit lengths 64 and 1".
    "hamming_distance": (BITS, "(t.\"embedding\") <~> '111000'::bit(6) ASC"),
    "jaccard_distance": (BITS, "(t.\"embedding\") <%> '111000'::bit(6) ASC"),
}


@fraise_type
class _Document:
    """The vector field is detected by name, so ``embedding`` gets a VectorOrderBy."""

    id: UUID
    title: str
    embedding: list[float]


def _dict_shape(operator: str, operand: object) -> dict:
    return {"embedding": VectorOrderBy(**{operator: operand})}


def _gql_fields_shape(operator: str, operand: object):
    order_by_input = create_graphql_order_by_input(_Document)
    return order_by_input(embedding=VectorOrderBy(**{operator: operand}))


@pytest.mark.parametrize("operator", list(OPERATORS))
@pytest.mark.parametrize("shape", [_dict_shape, _gql_fields_shape], ids=["dict", "gql_fields"])
def test_operator_renders_its_distance_expression(shape, operator: str) -> None:
    """Every operator ``VectorOrderBy`` accepts reaches the vector branch of to_sql."""
    operand, expected = OPERATORS[operator]

    order_by_set = _convert_order_by_input_to_sql(shape(operator, operand))

    assert order_by_set is not None, f"{operator} emitted no instruction"
    assert order_by_set.to_sql().as_string(None) == f"ORDER BY {expected}"


@pytest.mark.parametrize("operator", list(OPERATORS))
@pytest.mark.parametrize("shape", [_dict_shape, _gql_fields_shape], ids=["dict", "gql_fields"])
def test_operator_emits_exactly_one_instruction(shape, operator: str) -> None:
    """A bit-string operand must not also be read as a sort direction."""
    operand, _expected = OPERATORS[operator]

    order_by_set = _convert_order_by_input_to_sql(shape(operator, operand))

    assert order_by_set is not None
    assert [instruction.field for instruction in order_by_set.instructions] == [
        f"embedding.{operator}"
    ]


@pytest.mark.parametrize("operator", list(OPERATORS))
def test_both_shapes_render_identically(operator: str) -> None:
    """The two shapes are the same request written two ways."""
    operand, _expected = OPERATORS[operator]

    from_dict = _convert_order_by_input_to_sql(_dict_shape(operator, operand))
    from_gql_fields = _convert_order_by_input_to_sql(_gql_fields_shape(operator, operand))

    assert from_dict is not None
    assert from_gql_fields is not None
    assert from_dict.to_sql().as_string(None) == from_gql_fields.to_sql().as_string(None)

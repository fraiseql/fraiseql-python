"""``FraiseQLJSONEncoder`` writes a ``Decimal`` as a string, as the ``Decimal`` scalar does.

It wrote ``float(obj)``, so a ``Decimal`` inside a JSON scalar (or a
``CQRSExecutor`` mutation input) lost every digit past about 17.
"""

import json
from decimal import Decimal

import pytest

from fraiseql.fastapi.json_encoder import FraiseQLJSONEncoder, FraiseQLJSONResponse
from fraiseql.types.scalars.decimal import serialize_decimal

pytestmark = pytest.mark.unit

_DIGITS = "12.345678901234567890123"


def test_encoder_keeps_every_digit() -> None:
    assert json.loads(FraiseQLJSONEncoder().encode({"price": Decimal(_DIGITS)})) == {
        "price": _DIGITS
    }


@pytest.mark.parametrize("value", [_DIGITS, "1E+400", "-0.00", "100"])
def test_encoder_matches_the_decimal_scalar(value) -> None:
    assert FraiseQLJSONEncoder().default(Decimal(value)) == serialize_decimal(Decimal(value))


def test_response_keeps_every_digit() -> None:
    body = FraiseQLJSONResponse({"data": {"metadata": {"price": Decimal(_DIGITS)}}}).body
    assert json.loads(body) == {"data": {"metadata": {"price": _DIGITS}}}

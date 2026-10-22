"""from_dict builds an output type from a dict that doesn't match its fields exactly.

Mutation entities reach it filtered to the client's selection, and a view's JSONB
may carry keys the type doesn't declare. ``cls(**data)`` failed on both:
``missing a required argument`` / ``unexpected keyword argument``.
"""

import fraiseql


@fraiseql.type
class Address:
    city: str
    zip_code: str | None = None


@fraiseql.type
class Place:
    id: int
    name: str
    address: Address | None = None
    rating: int = 3


def test_missing_fields_are_none_and_defaults_stay() -> None:
    place = Place.from_dict({"id": 1})

    assert place.id == 1
    assert place.name is None
    assert place.address is None
    assert place.rating == 3


def test_unknown_keys_are_ignored() -> None:
    place = Place.from_dict({"id": 1, "name": "Home", "secret": "x", "__typename": "Place"})

    assert (place.id, place.name) == (1, "Home")
    assert not hasattr(place, "secret")


def test_nested_partial_dict() -> None:
    place = Place.from_dict({"id": 1, "address": {"zipCode": "75001", "country": "FR"}})

    assert place.address.zip_code == "75001"
    assert place.address.city is None

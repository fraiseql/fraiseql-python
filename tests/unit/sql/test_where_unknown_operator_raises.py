"""A generated where type raises on an operator it can't render.

``_make_filter_field_composed`` caught ``ValueError`` around each operator and
moved on, so ``{"age": {"bogus": 3}}`` dropped the age filter while its
siblings survived: the query matched more rows than were asked for. That
included ``quantized_distance``, whose vector type is gone.
"""

import pytest

import fraiseql
from fraiseql.sql.where_generator import safe_create_where_type


@fraiseql.type
class _Person:
    age: int
    name: str


class _Doc:
    __annotations__ = {}


PersonWhere = safe_create_where_type(_Person)
DocWhere = safe_create_where_type(_Doc)


class TestUnknownOperatorRaises:
    def test_unknown_operator_on_a_field(self) -> None:
        where = PersonWhere(age={"bogus": 3}, name={"eq": "x"})
        with pytest.raises(ValueError, match=r"'age'.*'bogus'"):
            where.to_sql()

    def test_unknown_operator_next_to_a_known_one(self) -> None:
        with pytest.raises(ValueError, match="'bogus'"):
            PersonWhere(age={"gte": 1, "bogus": 3}).to_sql()

    def test_quantized_distance_inside_or(self) -> None:
        where = DocWhere()
        where.OR = [{"age": {"eq": 1}}, {"embedding": {"quantized_distance": [1.0, 2.0]}}]
        with pytest.raises(ValueError, match="'quantized_distance'"):
            where.to_sql()

    def test_known_operators_still_render(self) -> None:
        sql = PersonWhere(age={"gte": 1}, name={"eq": "x"}).to_sql()
        assert sql is not None
        assert " >= " in sql.as_string(None)

"""A vector distance filter with no threshold is deprecated, not silently 0.5.

The GraphQL ``VectorFilter`` already refuses a distance operator without
``distanceWithin``. The Python ``where`` dict still accepts
``{"vector": [...]}`` alone, and used to filter at ``< 0.5`` without saying so.
It keeps working for now, with a ``DeprecationWarning`` naming the field and
operator; the default will be removed.
"""

import warnings

import pytest

from fraiseql.db import FraiseQLRepository
from fraiseql.sql.where_generator import safe_create_where_type

_MISSING_THRESHOLD = r"'embedding'.*cosine_distance.*\"threshold\""


def _find_sql(where: dict) -> tuple[object, list]:
    """Render a ``db.find`` style dict filter."""
    repo = FraiseQLRepository(None)  # type: ignore[arg-type]
    clause = repo._normalize_where(  # type: ignore[attr-defined]
        where, view_name="tv_vector_doc", table_columns={"id", "embedding"}
    )
    return clause.to_sql()


class _Doc:
    __annotations__ = {}


WhereType = safe_create_where_type(_Doc)


def _where_type_sql(filters: dict) -> object:
    """Render a filter through the generated where type (JSONB path)."""
    where = WhereType()
    where.OR = [{"embedding": filters}]
    return where.to_sql()


class TestFindDictPath:
    def test_missing_threshold_warns_and_keeps_the_default(self) -> None:
        where = {"embedding": {"cosine_distance": {"vector": [1.0, 0.0]}}}
        with pytest.warns(DeprecationWarning, match=_MISSING_THRESHOLD):
            _, params = _find_sql(where)
        assert params == [[1.0, 0.0], 0.5]

    def test_explicit_threshold_does_not_warn(self) -> None:
        where = {"embedding": {"cosine_distance": {"vector": [1.0, 0.0], "threshold": 0.3}}}
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _, params = _find_sql(where)
        assert params == [[1.0, 0.0], 0.3]


class TestWhereTypePath:
    def test_missing_threshold_warns_and_keeps_the_default(self) -> None:
        with pytest.warns(DeprecationWarning, match=_MISSING_THRESHOLD):
            sql = _where_type_sql({"cosine_distance": {"vector": [1.0, 0.0]}})
        assert sql is not None
        assert "0.5" in sql.as_string(None)

    def test_explicit_threshold_does_not_warn(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            sql = _where_type_sql({"cosine_distance": {"vector": [1.0, 0.0], "threshold": 0.3}})
        assert sql is not None

    def test_distance_within_does_not_warn(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            sql = _where_type_sql({"cosine_distance": [1.0, 0.0], "distance_within": 0.3})
        assert sql is not None

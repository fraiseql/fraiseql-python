"""Repository merge of authorization filters from context (issue #362, phase 5)."""

from __future__ import annotations

from typing import Any

import pytest
from graphql import GraphQLError

from fraiseql.db import FraiseQLRepository, _make_mandatory_conditions


def _repo(context: dict[str, Any]) -> FraiseQLRepository:
    # _consume_mandatory_filters never touches the pool, so None is fine here.
    return FraiseQLRepository(pool=None, context=context)  # type: ignore[arg-type]


def test_auth_filter_from_context_without_explicit() -> None:
    repo = _repo(
        {
            "_fraiseql_auth_filters": {"users": {"tenant_id": "t1"}},
            "graphql_field_name": "users",
        }
    )
    merged = repo._consume_mandatory_filters({})
    assert merged == {"tenant_id": "t1"}

    parts, params = _make_mandatory_conditions(merged)
    assert params == ["t1"]
    assert "tenant_id" in str(parts[0])


def test_merge_explicit_and_auth_filters() -> None:
    repo = _repo(
        {
            "_fraiseql_auth_filters": {"users": {"tenant_id": "t1"}},
            "graphql_field_name": "users",
        }
    )
    merged = repo._consume_mandatory_filters({"mandatory_filters": {"status": "active"}})
    assert merged == {"status": "active", "tenant_id": "t1"}


def test_consume_pops_kwarg() -> None:
    repo = _repo({})
    kwargs = {"mandatory_filters": {"a": 1}, "other": 2}
    repo._consume_mandatory_filters(kwargs)
    assert "mandatory_filters" not in kwargs
    assert kwargs == {"other": 2}


def test_no_filters_returns_none() -> None:
    repo = _repo({})
    assert repo._consume_mandatory_filters({}) is None


def test_overlapping_columns_rejected() -> None:
    repo = _repo(
        {
            "_fraiseql_auth_filters": {"users": {"tenant_id": "t1"}},
            "graphql_field_name": "users",
        }
    )
    with pytest.raises(GraphQLError):
        repo._consume_mandatory_filters({"mandatory_filters": {"tenant_id": "t2"}})


def test_field_name_keying_isolates_scopes() -> None:
    # Field A is scoped to tenant t1; field B is unscoped. Each reads its own bucket.
    repo = _repo(
        {
            "_fraiseql_auth_filters": {"a": {"tenant_id": "t1"}},
            "graphql_field_name": "a",
        }
    )
    assert repo._consume_mandatory_filters({}) == {"tenant_id": "t1"}

    repo.context["graphql_field_name"] = "b"
    assert repo._consume_mandatory_filters({}) is None


def test_unsafe_column_rejected_by_validator() -> None:
    repo = _repo(
        {
            "_fraiseql_auth_filters": {"users": {"tenant_id; DROP TABLE": 1}},
            "graphql_field_name": "users",
        }
    )
    merged = repo._consume_mandatory_filters({})
    with pytest.raises(ValueError):
        _make_mandatory_conditions(merged)

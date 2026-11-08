"""Which ``FraiseQLConfig`` settings turn the query limits on."""

import pytest

from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.gql.query_limits import QueryLimits

_URL = "postgresql://localhost/test"


def test_a_depth_limit_of_15_by_default() -> None:
    config = FraiseQLConfig(database_url=_URL)
    assert config.complexity_enabled is False
    assert QueryLimits.from_config(config) == QueryLimits(max_depth=15)


def test_none_turns_the_depth_limit_off() -> None:
    config = FraiseQLConfig(database_url=_URL, max_query_depth=None)
    assert QueryLimits.from_config(config) is None


def test_the_depth_limit_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("FRAISEQL_MAX_QUERY_DEPTH", "25")
    assert FraiseQLConfig(database_url=_URL).max_query_depth == 25


def test_max_query_depth_alone() -> None:
    limits = QueryLimits.from_config(FraiseQLConfig(database_url=_URL, max_query_depth=7))
    assert limits == QueryLimits(max_depth=7)


@pytest.mark.parametrize(
    ("kwargs", "max_depth", "max_complexity"),
    [
        ({"complexity_enabled": True}, 10, 1000),
        ({"complexity_max_score": 50}, 10, 50),
        ({"complexity_max_depth": 4}, 4, 1000),
        ({"complexity_max_depth": 4, "max_query_depth": 3}, 3, 1000),
    ],
)
def test_complexity_limits(kwargs, max_depth, max_complexity) -> None:
    config = FraiseQLConfig(database_url=_URL, **kwargs)
    assert config.complexity_enabled is True
    limits = QueryLimits.from_config(config)
    assert limits is not None
    assert (limits.max_depth, limits.max_complexity) == (max_depth, max_complexity)


def test_a_limit_from_the_environment_turns_complexity_on(monkeypatch) -> None:
    monkeypatch.setenv("FRAISEQL_COMPLEXITY_MAX_SCORE", "200")
    config = FraiseQLConfig(database_url=_URL)
    assert config.complexity_enabled is True
    assert config.complexity_max_score == 200


def test_complexity_enabled_false_wins_over_a_limit() -> None:
    config = FraiseQLConfig(
        database_url=_URL, complexity_enabled=False, complexity_max_score=5, max_query_depth=None
    )
    assert QueryLimits.from_config(config) is None


def test_list_size_and_multipliers_are_passed_on() -> None:
    config = FraiseQLConfig(
        database_url=_URL,
        complexity_enabled=True,
        complexity_default_list_size=3,
        complexity_field_multipliers={"search": 20},
    )
    limits = QueryLimits.from_config(config)
    assert limits is not None
    assert limits.default_list_size == 3
    assert limits.field_multipliers == {"search": 20}


@pytest.mark.parametrize(
    "kwargs",
    [{"max_query_depth": 0}, {"complexity_max_score": 0}, {"complexity_max_depth": 0}],
)
def test_a_limit_below_one_is_refused(kwargs) -> None:
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        FraiseQLConfig(database_url=_URL, **kwargs)

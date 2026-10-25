"""Settings nothing reads warn when set: ``database_echo``,
``complexity_include_in_response``, ``execution_timeout_ms`` and ``default_query_schema``.

``FraiseQLConfig`` documented them (SQL echo, complexity in the response, an
execution timeout, the schema of queries), but no code reads them, so setting
them changed nothing.
"""

import warnings

import pytest

from fraiseql.fastapi.config import FraiseQLConfig

_URL = "postgresql://localhost/test"

_SET = [
    ("database_echo", True, "FRAISEQL_DATABASE_ECHO", "true"),
    ("complexity_include_in_response", True, "FRAISEQL_COMPLEXITY_INCLUDE_IN_RESPONSE", "1"),
    ("execution_timeout_ms", 5000, "FRAISEQL_EXECUTION_TIMEOUT_MS", "5000"),
    ("default_query_schema", "app", "FRAISEQL_DEFAULT_QUERY_SCHEMA", "app"),
]


@pytest.mark.parametrize(("name", "value", "env", "env_value"), _SET)
def test_setting_it_warns(name, value, env, env_value) -> None:
    with pytest.warns(DeprecationWarning, match=f"{name} has no effect"):
        config = FraiseQLConfig(database_url=_URL, **{name: value})
    assert getattr(config, name) == value


@pytest.mark.parametrize(("name", "value", "env", "env_value"), _SET)
def test_setting_it_from_the_environment_warns(monkeypatch, name, value, env, env_value) -> None:
    monkeypatch.setenv(env, env_value)
    with pytest.warns(DeprecationWarning, match=f"{name} has no effect"):
        config = FraiseQLConfig(database_url=_URL)
    assert getattr(config, name) == value


def test_execution_timeout_ms_points_to_query_timeout() -> None:
    with pytest.warns(DeprecationWarning, match="use query_timeout"):
        FraiseQLConfig(database_url=_URL, execution_timeout_ms=1)


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {
            "database_echo": False,
            "complexity_include_in_response": False,
            "execution_timeout_ms": 30000,
            "default_query_schema": "public",
        },
    ],
)
def test_the_defaults_do_not_warn(kwargs) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        FraiseQLConfig(database_url=_URL, **kwargs)

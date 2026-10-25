"""``cache_ttl`` is deprecated: nothing reads it.

``FraiseQLConfig`` documented it as the query cache TTL, but no code reads
``config.cache_ttl``, so setting it changed nothing.
"""

import warnings

import pytest

from fraiseql.fastapi.config import FraiseQLConfig

_URL = "postgresql://localhost/test"


def test_setting_it_warns() -> None:
    with pytest.warns(DeprecationWarning, match="cache_ttl has no effect"):
        config = FraiseQLConfig(database_url=_URL, cache_ttl=60)
    assert config.cache_ttl == 60


def test_setting_it_from_the_environment_warns(monkeypatch) -> None:
    monkeypatch.setenv("FRAISEQL_CACHE_TTL", "600")
    with pytest.warns(DeprecationWarning, match="cache_ttl has no effect"):
        config = FraiseQLConfig(database_url=_URL)
    assert config.cache_ttl == 600


@pytest.mark.parametrize("kwargs", [{}, {"cache_ttl": 300}])
def test_the_default_does_not_warn(kwargs) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        config = FraiseQLConfig(database_url=_URL, **kwargs)
    assert config.cache_ttl == 300

"""``entity_routing`` is deprecated: nothing on the request path reads it.

``FraiseQLConfig`` validated and stored it, but no code builds a
``QueryRouter`` from it, and ``ModeSelector.select_mode`` is never called, so
setting it changed nothing.
"""

import warnings

import pytest

from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.routing.config import EntityRoutingConfig

_URL = "postgresql://localhost/test"


@pytest.mark.parametrize(
    "entity_routing",
    [
        {"turbo_entities": ["allocation"], "normal_entities": ["dns_server"]},
        EntityRoutingConfig(turbo_entities=["allocation"], normal_entities=[]),
    ],
)
def test_setting_it_warns(entity_routing) -> None:
    with pytest.warns(DeprecationWarning, match="entity_routing has no effect"):
        config = FraiseQLConfig(database_url=_URL, entity_routing=entity_routing)
    assert isinstance(config.entity_routing, EntityRoutingConfig)


def test_leaving_it_unset_does_not_warn() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        config = FraiseQLConfig(database_url=_URL)
    assert config.entity_routing is None

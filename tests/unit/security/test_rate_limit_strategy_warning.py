"""RateLimit.strategy and burst are not implemented: setting them logs a warning."""

import logging

import pytest

from fraiseql.security.rate_limiting import RateLimit, RateLimitStrategy

pytestmark = pytest.mark.unit

LOGGER = "fraiseql.security.rate_limiting"


@pytest.mark.parametrize(
    "kwargs",
    [{"strategy": RateLimitStrategy.SLIDING_WINDOW}, {"strategy": "token_bucket"}, {"burst": 5}],
)
def test_unimplemented_options_warn(caplog: pytest.LogCaptureFixture, kwargs: dict) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        RateLimit(requests=5, window=60, **kwargs)
    assert "fixed window" in caplog.text


def test_fixed_window_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        RateLimit(requests=5, window=60, strategy=RateLimitStrategy.FIXED_WINDOW)
    assert caplog.text == ""

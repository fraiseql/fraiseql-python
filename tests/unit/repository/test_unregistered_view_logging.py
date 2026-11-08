"""A view without a registered type is normal: find() looks it up on every call."""

import logging
from unittest.mock import MagicMock

import pytest

from fraiseql.db import FraiseQLRepository


def test_unregistered_view_logs_no_error(caplog: pytest.LogCaptureFixture, clear_registry) -> None:
    repo = FraiseQLRepository(MagicMock())

    with caplog.at_level(logging.DEBUG, logger="fraiseql.db"):
        assert repo._float_list_columns("v_unregistered") == []
        with pytest.raises(NotImplementedError):
            repo._get_type_for_view("v_unregistered")

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

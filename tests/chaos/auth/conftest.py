# Conftest for tests/chaos/auth
import os
import sys

import pytest

tests_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if tests_dir not in sys.path:
    sys.path.insert(0, tests_dir)


@pytest.fixture(autouse=True)
def inject_chaos_config(request, chaos_config):
    """
    Auto-inject chaos_config into unittest-style test classes.

    This fixture runs automatically for all tests in this directory and
    makes chaos_config available as self.chaos_config in test methods.
    """
    if hasattr(request, "instance") and request.instance is not None:
        request.instance.chaos_config = chaos_config

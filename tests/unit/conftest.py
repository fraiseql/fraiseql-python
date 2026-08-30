"""Unit-test isolation from the ambient environment (issue #470).

A unit test must not be able to reach a database. ``fraiseql query-stats``
declares ``envvar="DATABASE_URL"`` on its ``--database-url`` option, so with that
variable set in the process environment the CLI does not stop at the missing
argument — it connects to whatever server the URL names and fails further in.

That is not hypothetical: the variable was leaking out of the example app
fixtures, which set it with a bare ``os.environ[...] = ...`` and never restored
it, so every later test in a full run inherited it. Those fixtures now use
``monkeypatch.setenv``; this clears the variable for the whole unit suite as
well, so a future writer anywhere cannot quietly give a unit test a live
database again.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_ambient_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset ``DATABASE_URL`` for every unit test, however it got set."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

"""The example database manager connects where ``TEST_DATABASE_URL`` points.

It used ``fraiseql:fraiseql@localhost:5432`` whatever the environment said, so
against any other server (the documented ``TEST_DATABASE_URL`` one, say) it
couldn't create the blog_simple template and its 16 tests skipped.
"""

import pytest

from tests.fixtures.examples.database_manager import DatabaseConfig

pytestmark = pytest.mark.unit


def test_reads_test_database_url(monkeypatch) -> None:
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://postgres:pg@db.local:55440/postgres")
    config = DatabaseConfig.from_env()
    assert (config.host, config.port, config.user, config.password, config.admin_db) == (
        "db.local",
        55440,
        "postgres",
        "pg",
        "postgres",
    )


def test_missing_parts_keep_the_defaults(monkeypatch) -> None:
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://db.local/")
    config = DatabaseConfig.from_env()
    assert (config.host, config.port, config.user, config.password, config.admin_db) == (
        "db.local",
        5432,
        "fraiseql",
        "fraiseql",
        "postgres",
    )


def test_without_the_variable(monkeypatch) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    assert DatabaseConfig.from_env() == DatabaseConfig()

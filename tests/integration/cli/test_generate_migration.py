"""The view `fraiseql generate migration` writes serves a type's ``id`` through ``find``.

``find`` reads a type from the view's ``data`` column. The generated view
selected the table's ``data`` as is, which has no ``id``, so a type's
``id: ID`` read as null. The view now puts ``id`` (and the timestamps) in
``data``.
"""

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.cli.main import cli
from fraiseql.db import FraiseQLRepository
from fraiseql.types import ID

pytestmark = [pytest.mark.integration, pytest.mark.database]


@pytest.fixture
def migration_sql(tmp_path) -> str:
    cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        result = CliRunner().invoke(cli, ["generate", "migration", "Note"])
        assert result.exit_code == 0, result.output
    finally:
        os.chdir(cwd)
    (migration,) = (tmp_path / "migrations").glob("*_create_notes.sql")
    return migration.read_text()


async def test_find_reads_the_id(clear_registry, class_db_pool, test_schema, migration_sql):
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute(migration_sql)
        cursor = await conn.execute(
            """INSERT INTO notes (data) VALUES ('{"title": "first"}') RETURNING id, created_at"""
        )
        note_id, created_at = await cursor.fetchone()
        await conn.commit()
        await conn.execute("SET search_path TO DEFAULT")
        await conn.commit()

    @fraiseql.type(sql_source=f"{test_schema}.v_notes")
    class Note:
        id: ID
        title: str
        created_at: str

    repo = FraiseQLRepository(class_db_pool)
    response = await repo.find_one(f"{test_schema}.v_notes", "note")

    note = json.loads(bytes(response))["data"]["note"]
    assert note["id"] == str(note_id)
    assert note["title"] == "first"
    assert note["createdAt"].startswith(created_at.date().isoformat())

"""`fraiseql generate crud` writes mutations that build and run against PostgreSQL.

The template called ``repository.update(table, id, input)`` on a
``CQRSRepository`` parameter nothing passes, and decorated a result class with
``@fraiseql.result``, which takes the success and error classes: the generated
module didn't import. It now writes class mutations and the PostgreSQL
functions they call, for the table ``fraiseql generate migration`` creates.
"""

import importlib
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from click.testing import CliRunner
from fastapi.testclient import TestClient

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.cli.main import cli

pytestmark = [pytest.mark.integration, pytest.mark.database]

TYPES_MODULE = """
import fraiseql
from fraiseql.types import ID


@fraiseql.type(sql_source="v_blogposts")
class BlogPost:
    id: ID
    name: str
"""


def _forget_project_modules() -> None:
    for name in [n for n in sys.modules if n == "src" or n.startswith("src.")]:
        del sys.modules[name]


@pytest.fixture(scope="class")
def project(tmp_path_factory) -> Path:
    """A project with a BlogPost type, its migration and its CRUD, as the CLI writes them."""
    path = tmp_path_factory.mktemp("crud_project")
    (path / "src" / "types").mkdir(parents=True)
    (path / "src" / "__init__.py").write_text("")
    (path / "src" / "types" / "__init__.py").write_text(TYPES_MODULE)

    cwd = Path.cwd()
    os.chdir(path)
    try:
        runner = CliRunner()
        for command in (["generate", "migration", "BlogPost"], ["generate", "crud", "BlogPost"]):
            result = runner.invoke(cli, command)
            assert result.exit_code == 0, result.output
    finally:
        os.chdir(cwd)
    return path


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def crud_database(class_db_pool, test_schema, project):
    table_sql, functions_sql = sorted((project / "migrations").glob("*.sql"))
    assert functions_sql.name.endswith("_create_blogposts_mutations.sql")
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute(table_sql.read_text())
        await conn.execute(functions_sql.read_text())
        await conn.commit()
    yield


@pytest.mark.usefixtures("clear_registry_class")
class TestGeneratedCrud:
    @pytest.fixture(scope="class")
    def client(self, class_db_pool, test_schema, project, crud_database):
        from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app
        from fraiseql.fastapi.dependencies import set_db_pool

        _forget_project_modules()
        sys.path.insert(0, str(project))
        try:
            importlib.import_module("src.mutations.blog_post_mutations")
            types = importlib.import_module("src.types")
        finally:
            sys.path.remove(str(project))
            _forget_project_modules()

        @fraiseql.query
        async def blog_posts(info) -> list[types.BlogPost]:
            return []

        set_db_pool(class_db_pool)
        config = FraiseQLConfig(
            database_url="postgresql://test/test",  # the pool above is used
            default_mutation_schema=test_schema,
        )
        app = create_fraiseql_app(
            config=config,
            types=[types.BlogPost],
            # No mutations=: the generated module registered them on import
            production=False,
        )
        return TestClient(app)

    def _post(self, client: TestClient, query: str) -> dict:
        body = client.post("/graphql", json={"query": query}).json()
        assert "errors" not in body, body
        return body["data"]

    _SELECTION = """
        __typename
        ... on BlogPostSuccess { blogPost { id name } }
        ... on BlogPostError { status message code }
    """

    def _mutate(self, client: TestClient, field: str, input_: str) -> dict:
        return self._post(
            client, f"mutation {{ {field}(input: {input_}) {{ {self._SELECTION} }} }}"
        )[field]

    def test_create_update_delete(self, client) -> None:
        created = self._mutate(client, "createBlogPost", '{name: "first"}')
        assert created["__typename"] == "BlogPostSuccess", created
        post_id = created["blogPost"]["id"]
        assert created["blogPost"]["name"] == "first"

        updated = self._mutate(client, "updateBlogPost", f'{{id: "{post_id}", name: "second"}}')
        assert (updated["blogPost"]["id"], updated["blogPost"]["name"]) == (post_id, "second")

        deleted = self._mutate(client, "deleteBlogPost", f'{{id: "{post_id}"}}')
        assert (deleted["blogPost"]["id"], deleted["blogPost"]["name"]) == (post_id, "second")

        again = self._mutate(client, "deleteBlogPost", f'{{id: "{post_id}"}}')
        assert again["__typename"] == "BlogPostError"
        assert again["code"] == 404

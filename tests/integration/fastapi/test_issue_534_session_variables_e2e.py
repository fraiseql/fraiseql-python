"""End-to-end regression for issue #534 against a real PostgreSQL.

``session_variables={"locale": "app.locale"}`` plus a ``context_getter`` returning
``{"locale": ...}`` must make ``current_setting('app.locale', true)`` return that locale
inside the views FraiseQL reads — on ``find()``, ``find_one()`` and ``count()``, and
through the FastAPI router.

The view below defaults to ``en-US``. Every assertion that matters uses ``fr-FR``: a test
that only checks the default locale passes whether or not the variable is set.

Requires a real PostgreSQL (markers: integration + database). The unit-level tests live
in ``tests/regression/test_issue_534_session_variables.py``.
"""

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.sql import SQL
from psycopg_pool import AsyncConnectionPool

import fraiseql
from fraiseql.db import DatabaseQuery, FraiseQLRepository, register_type_for_view
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.fastapi.dependencies import set_db_pool, set_fraiseql_config
from fraiseql.fastapi.routers import create_graphql_router
from fraiseql.gql.schema_builder import build_fraiseql_schema

pytestmark = [pytest.mark.integration, pytest.mark.database]

_LABELS = "v_localized_label"
_PROBE = "v_session_settings_probe"

_HELLO = "00000000-0000-0000-0000-000000000001"
_WORLD = "00000000-0000-0000-0000-000000000002"
_ONLY_FR = "00000000-0000-0000-0000-000000000003"
_TENANT = "11111111-1111-1111-1111-111111111111"
_CONTACT = "41111111-1111-1111-1111-111111111111"

_FRENCH = {"Bonjour", "Monde", "Seulement"}
_ENGLISH = {"Hello", "World"}


@fraiseql.type
class LocalizedLabel:
    """A label translated per ``app.locale``."""

    id: str
    name: str
    locale: str


@fraiseql.type
class SessionSettings:
    """The ``app.*`` settings as the database sees them."""

    id: int
    locale: str | None
    tenant_id: str | None
    contact_id: str | None
    user_id: str | None
    is_super_admin: str | None


@fraiseql.query
async def localized_labels(info) -> list[LocalizedLabel]:
    return await info.context["db"].find(_LABELS, info=info)


@fraiseql.query
async def localized_labels_count(info) -> int:
    return await info.context["db"].count(_LABELS)


@fraiseql.query
async def session_settings(info) -> SessionSettings | None:
    return await info.context["db"].find_one(_PROBE, info=info)


def _config() -> FraiseQLConfig:
    return FraiseQLConfig(
        database_url="postgresql://test:test@localhost:5432/test",
        environment="development",
        session_variables={"locale": "app.locale"},
    )


def _rows(result: Any) -> Any:
    """Unwrap the ``{"data": {<field>: ...}}`` bytes a repository read returns."""
    (value,) = json.loads(bytes(result))["data"].values()
    return value


class TestIssue534SessionVariables:
    """``app.*`` settings reach the views on every read path."""

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def pool(self, postgres_url, test_schema) -> AsyncIterator[AsyncConnectionPool]:
        """One connection with the test schema on its search_path.

        A single connection makes consecutive reads share it, so a setting that outlived
        its transaction would show up in the next read.
        """
        pool = AsyncConnectionPool(
            postgres_url,
            min_size=1,
            max_size=1,
            open=False,
            kwargs={"options": f"-c search_path={test_schema},public"},
        )
        await pool.open()
        await pool.wait()

        for view, columns in ((_LABELS, {"id", "locale", "data"}), (_PROBE, {"id", "data"})):
            register_type_for_view(
                view,
                LocalizedLabel if view == _LABELS else SessionSettings,
                table_columns=columns,
                has_jsonb_data=True,
                jsonb_column="data",
            )

        async with pool.connection() as conn:
            await conn.execute("CREATE TABLE tb_localized_label (id UUID, locale TEXT, name TEXT)")
            await conn.execute(
                f"""
                INSERT INTO tb_localized_label (id, locale, name) VALUES
                    ('{_HELLO}', 'en-US', 'Hello'), ('{_HELLO}', 'fr-FR', 'Bonjour'),
                    ('{_WORLD}', 'en-US', 'World'), ('{_WORLD}', 'fr-FR', 'Monde'),
                    ('{_ONLY_FR}', 'fr-FR', 'Seulement')
                """
            )
            await conn.execute(
                f"""
                CREATE VIEW {_LABELS} AS
                SELECT id, locale,
                       jsonb_build_object('id', id, 'name', name, 'locale', locale) AS data
                FROM tb_localized_label
                WHERE locale = COALESCE(NULLIF(current_setting('app.locale', true), ''), 'en-US')
                """
            )
            await conn.execute(
                f"""
                CREATE VIEW {_PROBE} AS
                SELECT 1 AS id, jsonb_build_object(
                    'id', 1,
                    'locale', current_setting('app.locale', true),
                    'tenant_id', current_setting('app.tenant_id', true),
                    'contact_id', current_setting('app.contact_id', true),
                    'user_id', current_setting('app.user_id', true),
                    'is_super_admin', current_setting('app.is_super_admin', true)
                ) AS data
                """
            )

        yield pool

        await pool.close()

    # -- repository ---------------------------------------------------------

    @pytest.mark.asyncio(loop_scope="class")
    async def test_find_returns_the_context_locale(self, pool) -> None:
        repo = FraiseQLRepository(pool, context={"config": _config(), "locale": "fr-FR"})

        labels = _rows(await repo.find(_LABELS))

        assert {label["name"] for label in labels} == _FRENCH

    @pytest.mark.asyncio(loop_scope="class")
    async def test_find_one_returns_the_context_locale(self, pool) -> None:
        repo = FraiseQLRepository(pool, context={"config": _config(), "locale": "fr-FR"})

        label = _rows(await repo.find_one(_LABELS, where={"id": {"eq": _HELLO}}))

        assert label["name"] == "Bonjour"

    @pytest.mark.asyncio(loop_scope="class")
    async def test_count_uses_the_context_locale(self, pool) -> None:
        repo = FraiseQLRepository(pool, context={"config": _config(), "locale": "fr-FR"})

        assert await repo.count(_LABELS) == len(_FRENCH)

    @pytest.mark.asyncio(loop_scope="class")
    async def test_setting_does_not_outlive_its_transaction(self, pool) -> None:
        """The next read on the same connection, with no locale, sees the view default."""
        french = FraiseQLRepository(pool, context={"config": _config(), "locale": "fr-FR"})
        default = FraiseQLRepository(pool, context={"config": _config()})

        assert await french.count(_LABELS) == len(_FRENCH)
        assert await default.count(_LABELS) == len(_ENGLISH)

    @pytest.mark.asyncio(loop_scope="class")
    async def test_user_id_without_roles_does_not_abort_the_transaction(self, pool) -> None:
        """The removed ``is_super_admin`` lookup was a syntax error in PostgreSQL."""
        repo = FraiseQLRepository(pool, context={"user_id": _CONTACT})

        rows = await repo.run(
            DatabaseQuery(
                statement=SQL("SELECT current_setting('app.is_super_admin', true) AS value"),
                params={},
                fetch_result=True,
            )
        )

        assert rows == [{"value": "false"}]

    # -- FastAPI router -----------------------------------------------------

    @pytest.fixture
    def client(self, pool) -> Iterator[TestClient]:
        """The reporter's setup: a ``context_getter`` returning the locale (and ids)."""
        config = _config()
        set_db_pool(pool)
        set_fraiseql_config(config)

        async def context_getter(request) -> dict[str, Any]:
            return {
                "tenant_id": _TENANT,
                "user_id": _CONTACT,
                "contact_id": _CONTACT,
                "locale": "fr-FR",
            }

        schema = build_fraiseql_schema(
            query_types=[localized_labels, localized_labels_count, session_settings]
        )
        app = FastAPI()
        app.include_router(
            create_graphql_router(schema=schema, config=config, context_getter=context_getter)
        )
        yield TestClient(app)
        set_db_pool(None)
        set_fraiseql_config(None)

    @staticmethod
    def _data(client: TestClient, query: str) -> dict[str, Any]:
        response = client.post("/graphql", json={"query": query})
        assert response.status_code == 200, response.text
        body = response.json()
        assert "errors" not in body, body
        return body["data"]

    @pytest.mark.asyncio(loop_scope="class")
    async def test_router_list_query(self, client) -> None:
        data = self._data(client, "{ localizedLabels { name } }")

        assert {label["name"] for label in data["localizedLabels"]} == _FRENCH

    @pytest.mark.asyncio(loop_scope="class")
    async def test_router_multi_field_query(self, client) -> None:
        data = self._data(client, "{ localizedLabels { name } localizedLabelsCount }")

        assert {label["name"] for label in data["localizedLabels"]} == _FRENCH
        assert data["localizedLabelsCount"] == len(_FRENCH)

    @pytest.mark.asyncio(loop_scope="class")
    async def test_router_forwards_every_session_setting(self, client) -> None:
        data = self._data(
            client, "{ sessionSettings { locale tenantId contactId userId isSuperAdmin } }"
        )

        settings = {k: v for k, v in data["sessionSettings"].items() if k != "__typename"}
        assert settings == {
            "locale": "fr-FR",
            "tenantId": _TENANT,
            "contactId": _CONTACT,
            "userId": _CONTACT,
            "isSuperAdmin": "false",
        }

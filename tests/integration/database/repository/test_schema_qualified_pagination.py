"""Issue #486: schema-qualified view names in cursor pagination, resolved by a real PostgreSQL.

The same defect as #472, in a different module. ``CursorPaginator.paginate`` and
``CursorPaginator._get_total_count`` handed the whole view name to a
single-argument ``Identifier``, so ``"myschema.v_posts"`` rendered as
``"myschema.v_posts"`` — one quoted relation name that happens to contain a dot,
which PostgreSQL cannot resolve — instead of ``"myschema"."v_posts"``.

The two renderings differ by a single quote character and both read as plausible
in a diff, so a text assertion cannot tell them apart; only the server can. The
schema built here is therefore deliberately kept *off* the search path, so a
mis-quoted or unqualified name has nothing to resolve against.

Reachable in production from any ``@connection`` query, which resolves a view
name and hands it to ``CQRSRepository.paginate`` → ``paginate_query`` →
``CursorPaginator``.
"""

import json
import uuid
from collections.abc import AsyncIterator

import psycopg
import pytest

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

from fraiseql.cqrs.pagination import CursorPaginator, PaginationParams

pytestmark = [pytest.mark.integration, pytest.mark.database]

VIEW = "v_486_posts"

# (title, author) — ordered by title, so the cursor field is unique and stable.
ROWS = [
    ("post-a", "alice"),
    ("post-b", "bob"),
    ("post-c", "alice"),
]

ROW_IDS = [uuid.UUID(int=i) for i in range(1, len(ROWS) + 1)]


@pytest.fixture
async def qualified_view(class_db_pool, test_schema) -> AsyncIterator[None]:
    """Build the table inside ``test_schema`` and leave it off the search path."""
    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {test_schema}.{VIEW} (
                id UUID PRIMARY KEY,
                data JSONB NOT NULL
            )
        """)
        for row_id, (title, author) in zip(ROW_IDS, ROWS, strict=True):
            await cursor.execute(
                f"INSERT INTO {test_schema}.{VIEW} (id, data) VALUES (%s, %s::jsonb)",
                (row_id, json.dumps({"id": str(row_id), "title": title, "author": author})),
            )
        await conn.commit()

    yield

    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"DROP TABLE IF EXISTS {test_schema}.{VIEW} CASCADE")
        await conn.commit()


class TestSchemaQualifiedPagination:
    """``paginate`` renders one view name; ``include_total`` renders the second."""

    async def test_the_unqualified_name_does_not_resolve(
        self, class_db_pool, test_schema, qualified_view
    ) -> None:
        """Without this, every test below could pass for the wrong reason."""
        async with class_db_pool.connection() as conn:
            paginator = CursorPaginator(conn)

            with pytest.raises(psycopg.errors.UndefinedTable):
                await paginator.paginate(VIEW, PaginationParams(first=2, order_by="title"))

    async def test_paginate_resolves_the_qualified_view(
        self, class_db_pool, test_schema, qualified_view
    ) -> None:
        """Both the page query and the ``include_total`` count query name the view."""
        async with class_db_pool.connection() as conn:
            paginator = CursorPaginator(conn)

            result = await paginator.paginate(
                f"{test_schema}.{VIEW}", PaginationParams(first=2, order_by="title")
            )

        assert [edge["node"]["title"] for edge in result["edges"]] == ["post-a", "post-b"]
        assert result["page_info"]["has_next_page"] is True
        # _get_total_count is the second Identifier site, and counts past the page.
        assert result["total_count"] == len(ROWS)

    async def test_get_total_count_resolves_the_qualified_view_with_filters(
        self, class_db_pool, test_schema, qualified_view
    ) -> None:
        """The filtered count path renders the same name."""
        async with class_db_pool.connection() as conn:
            paginator = CursorPaginator(conn)

            total = await paginator._get_total_count(
                f"{test_schema}.{VIEW}", filters={"author": "alice"}
            )

        assert total == 2

    async def test_unqualified_name_still_resolves_on_the_search_path(
        self, class_db_pool, test_schema, qualified_view
    ) -> None:
        """The bare-name form must keep working — the helper must not split what has no dot."""
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            paginator = CursorPaginator(conn)

            result = await paginator.paginate(VIEW, PaginationParams(first=2, order_by="title"))

        assert result["total_count"] == len(ROWS)

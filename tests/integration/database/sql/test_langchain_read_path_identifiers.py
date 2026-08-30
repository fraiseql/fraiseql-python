"""Issue #490: the langchain read path interpolates its five identifiers raw.

``FraiseQLVectorStore``'s two write paths (``aadd_texts``, ``adelete``) render
their names through ``psycopg.sql``, so they are quoted. ``asimilarity_search``
built its statement as an f-string, dropping five constructor-supplied names —
the table and the id, content, metadata and embedding columns — into the text
unquoted.

The inversion versus #488 is the point. Raw interpolation means
``FROM myschema.documents`` is valid SQL, so the read path has always resolved
both the bare and the schema-qualified spelling; ``UndefinedTable`` cannot prove
anything here. What raw interpolation *cannot* survive is a name that needs
quoting, so each case below gives exactly one of the five identifiers a
mixed-case spelling and leaves the other four alone. PostgreSQL folds an
unquoted ``"DocId"`` to ``docid`` and the statement fails on that one name, which
is what makes the parametrisation fail once per site rather than once overall.

The write paths were already quoted, so ``aadd_texts`` populating these tables is
itself the control: it accepts the mixed-case names the read path rejected.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from fraiseql.integrations.langchain import FraiseQLVectorStore

pytestmark = [pytest.mark.integration, pytest.mark.database]

# Each site names the one identifier spelled in mixed case; the rest stay plain.
# (site, table, id_column, content_column, metadata_column, embedding_column)
SITES = [
    ("table", "Tb490Documents", "id", "content", "metadata", "embedding"),
    ("id_column", "tb490_id", "DocId", "content", "metadata", "embedding"),
    ("content_column", "tb490_content", "id", "DocContent", "metadata", "embedding"),
    ("metadata_column", "tb490_metadata", "id", "content", "DocMetadata", "embedding"),
    ("embedding_column", "tb490_embedding", "id", "content", "metadata", "DocEmbedding"),
]

PLAIN = ("tb490_plain", "id", "content", "metadata", "embedding")

DIMENSION = 3


class _StubEmbeddings:
    """Deterministic stand-in — the vector maths is irrelevant to identifier rendering."""

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text)), 0.0, 1.0]

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


def _store(pool: Any, table_name: str, columns: tuple[str, str, str, str]) -> FraiseQLVectorStore:
    id_column, content_column, metadata_column, embedding_column = columns
    return FraiseQLVectorStore(
        db_pool=pool,
        table_name=table_name,
        embedding_function=_StubEmbeddings(),
        id_column=id_column,
        content_column=content_column,
        metadata_column=metadata_column,
        embedding_column=embedding_column,
    )


@pytest.fixture
async def documents_tables(class_db_pool, test_schema, pgvector_available) -> AsyncIterator[None]:
    """One table per site, plus an all-plain table, inside ``test_schema``."""
    if not pgvector_available:
        pytest.skip("pgvector extension not available")

    tables = [row[1:] for row in SITES] + [PLAIN]

    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        for table, id_column, content_column, metadata_column, embedding_column in tables:
            await cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {test_schema}."{table}" (
                    "{id_column}" TEXT PRIMARY KEY,
                    "{content_column}" TEXT NOT NULL,
                    "{metadata_column}" JSONB,
                    "{embedding_column}" vector({DIMENSION})
                )
            """)
        await conn.commit()

    yield

    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        for table, *_ in tables:
            await cursor.execute(f'DROP TABLE IF EXISTS {test_schema}."{table}" CASCADE')
        await conn.commit()


class TestLangchainReadPathIdentifiers:
    """``asimilarity_search`` renders every name it interpolates."""

    @pytest.mark.parametrize(
        ("site", "table", "id_column", "content_column", "metadata_column", "embedding_column"),
        SITES,
        ids=[row[0] for row in SITES],
    )
    async def test_mixed_case_identifier_resolves(
        self,
        class_db_pool,
        test_schema,
        documents_tables,
        site: str,
        table: str,
        id_column: str,
        content_column: str,
        metadata_column: str,
        embedding_column: str,
    ) -> None:
        """One mixed-case name per case, so a raw-interpolated site fails on its own."""
        columns = (id_column, content_column, metadata_column, embedding_column)
        store = _store(class_db_pool, f"{test_schema}.{table}", columns)
        await store.aadd_texts(["hello"], [{"kind": "greeting"}])

        results = await store.asimilarity_search("hello", k=1)

        assert [document.page_content for document in results] == ["hello"]
        assert results[0].metadata == {"kind": "greeting"}

    async def test_mixed_case_metadata_column_resolves_in_the_filter(
        self, class_db_pool, test_schema, documents_tables
    ) -> None:
        """``_build_metadata_where_clause`` interpolates the same name a second time."""
        _site, table, *columns = next(row for row in SITES if row[0] == "metadata_column")
        store = _store(class_db_pool, f"{test_schema}.{table}", tuple(columns))
        await store.aadd_texts(["hello", "world"], [{"kind": "greeting"}, {"kind": "noun"}])

        results = await store.asimilarity_search("hello", k=5, filter={"kind": "greeting"})

        assert [document.page_content for document in results] == ["hello"]

    async def test_plain_names_still_resolve(
        self, class_db_pool, test_schema, documents_tables
    ) -> None:
        """The regression guard: quoting must not break the names that already worked."""
        table, *columns = PLAIN
        store = _store(class_db_pool, f"{test_schema}.{table}", tuple(columns))
        await store.aadd_texts(["hello"], [{"kind": "greeting"}])

        results = await store.asimilarity_search("hello", k=1, filter={"kind": "greeting"})

        assert [document.page_content for document in results] == ["hello"]

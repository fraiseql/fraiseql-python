"""Vector search over GraphQL: ``orderBy`` by distance, ``where`` within a distance.

``docs/features/pgvector.md`` shows clients sending
``documents(where: ..., orderBy: {embedding: {cosineDistance: [...]}}, limit: 10)``.
A list query over a type with a vector field had no ``orderBy`` argument at all
(the query builder skipped it, as ``VectorOrderBy`` couldn't become a GraphQL
type), and a vector ``where`` failed in ``db.find`` with ``Invalid operator
'dense'``.

The rows, against the query vector ``[1, 0]`` (and the bit string ``1100``):

    id  embedding   cosine  l2     l1   <#>   binary  hamming  jaccard
    1   [1, 0]      0       0      0    -1    1100    0        0
    2   [0, 1]      1       1.414  2    0     0011    4        1
    3   [0.6, 0.8]  0.4     0.894  1.2  -0.6  1110    1        0.333
    4   [2, 2]      0.293   2.236  3    -2    0111    3        0.75
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# Import database fixtures for this database test
from tests.fixtures.database.database_conftest import *  # noqa: F403

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.sql.graphql_order_by_generator import create_graphql_order_by_input

pytestmark = [pytest.mark.integration, pytest.mark.database]

_VIEW = "v_vector_graphql_doc"
_TYPED_VIEW = "v_vector_graphql_typed_doc"


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def vector_docs(class_db_pool, test_schema, pgvector_available):
    if not pgvector_available:
        pytest.skip("pgvector extension not available")
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.execute(
            "CREATE TABLE tb_vector_graphql_doc (id INT PRIMARY KEY, category TEXT, "
            "embedding vector(2), binary_embedding bit(4), half_embedding halfvec(2))"
        )
        await conn.execute(
            "INSERT INTO tb_vector_graphql_doc VALUES "
            "(1, 'a', '[1,0]', '1100', '[1,0]'), (2, 'a', '[0,1]', '0011', '[0,1]'), "
            "(3, 'b', '[0.6,0.8]', '1110', '[0.6,0.8]'), (4, 'a', '[2,2]', '0111', '[2,2]')"
        )
        await conn.execute(f"CREATE VIEW {_VIEW} AS SELECT * FROM tb_vector_graphql_doc")
        await conn.execute(
            f"CREATE VIEW {_TYPED_VIEW} AS SELECT id, embedding AS vec, half_embedding AS half, "
            "embedding AS nullable_embedding FROM tb_vector_graphql_doc"
        )
        await conn.commit()
    yield


def _ids(client: TestClient, query: str, variables: dict | None = None) -> list[int]:
    body = client.post("/graphql", json={"query": query, "variables": variables or {}}).json()
    assert "errors" not in body, body
    return [row["id"] for row in next(iter(body["data"].values()))]


@pytest.mark.usefixtures("clear_registry_class")
class TestVectorSearchOverGraphQL:
    @pytest.fixture(scope="class")
    def client(self, class_db_pool, vector_docs):
        from fraiseql.fastapi.dependencies import set_db_pool

        # A flat view: pgvector columns, no JSONB data column
        @fraiseql.type(sql_source=_VIEW, jsonb_column=None)
        class VectorDoc:
            id: int
            category: str
            embedding: list[float]
            binary_embedding: list[float]

        doc_order_by = create_graphql_order_by_input(VectorDoc)

        @fraiseql.query
        async def documents(info) -> list[VectorDoc]:
            # Declares none of the list arguments: they are auto-wired
            return await info.context["db"].find(_VIEW, "documents", info)

        @fraiseql.query
        async def documents_declared(
            info, order_by: doc_order_by | None = None, limit: int | None = None
        ) -> list[VectorDoc]:
            return await info.context["db"].find(
                _VIEW, "documentsDeclared", info, order_by=order_by, limit=limit
            )

        set_db_pool(class_db_pool)
        app = create_fraiseql_app(
            database_url="postgresql://test/test",  # the pool above is used
            types=[VectorDoc],
            queries=[documents, documents_declared],
            production=False,
        )
        return TestClient(app)

    @pytest.mark.parametrize(
        ("operator", "operand", "expected"),
        [
            ("cosineDistance", "{dense: [1, 0]}", [1, 4, 3, 2]),
            ("l2Distance", "{dense: [1, 0]}", [1, 3, 2, 4]),
            ("l1Distance", "{dense: [1, 0]}", [1, 3, 2, 4]),
            ("innerProduct", "{dense: [1, 0]}", [4, 1, 3, 2]),
        ],
    )
    def test_order_by_distance(self, client, operator, operand, expected) -> None:
        query = f"{{ documents(orderBy: {{embedding: {{{operator}: {operand}}}}}) {{ id }} }}"
        assert _ids(client, query) == expected

    @pytest.mark.parametrize("operator", ["hammingDistance", "jaccardDistance"])
    def test_order_by_bit_distance(self, client, operator) -> None:
        query = f'{{ documents(orderBy: {{binaryEmbedding: {{{operator}: "1100"}}}}) {{ id }} }}'
        assert _ids(client, query) == [1, 3, 4, 2]

    def test_declared_order_by_argument(self, client) -> None:
        query = (
            "{ documentsDeclared(orderBy: {embedding: {innerProduct: {dense: [1, 0]}}}, limit: 2) "
            "{ id } }"
        )
        assert _ids(client, query) == [4, 1]

    def test_vectors_come_back_as_lists(self, client) -> None:
        body = client.post(
            "/graphql",
            json={
                "query": "{ documents(where: {embedding: {cosineDistance: {dense: [1, 0]}, "
                "distanceWithin: 0.35}}, orderBy: {embedding: {cosineDistance: {dense: [1, 0]}}}) "
                "{ id embedding } }"
            },
        ).json()
        assert "errors" not in body, body
        rows = [
            {"id": row["id"], "embedding": row["embedding"]} for row in body["data"]["documents"]
        ]
        assert rows == [
            {"id": 1, "embedding": [1.0, 0.0]},
            {"id": 4, "embedding": [2.0, 2.0]},
        ]

    def test_a_bare_list_is_not_an_order_by_operand(self, client) -> None:
        # orderBy takes the operand where takes, so a client learns one shape
        body = client.post(
            "/graphql",
            json={"query": "{ documents(orderBy: {embedding: {cosineDistance: [1, 0]}}) { id } }"},
        ).json()
        assert "VectorDistanceInput" in body["errors"][0]["message"], body

    def test_sparse_order_by_is_refused(self, client) -> None:
        body = client.post(
            "/graphql",
            json={
                "query": "{ documents(orderBy: {embedding: {cosineDistance: "
                "{sparse: {indices: [1], values: [1.0]}}}}) { id } }"
            },
        ).json()
        assert "needs a dense vector" in body["errors"][0]["message"], body

    @pytest.mark.parametrize(
        ("field", "operator"),
        [
            ("embedding", "cosineDistance: {dense: [1, 0]}"),
            ("binaryEmbedding", 'hammingDistance: "1100"'),
        ],
    )
    def test_where_needs_distance_within(self, client, field, operator) -> None:
        # It used to filter at < 0.5 without saying so
        body = client.post(
            "/graphql",
            json={"query": f"{{ documents(where: {{{field}: {{{operator}}}}}) {{ id }} }}"},
        ).json()
        message = body["errors"][0]["message"]
        assert f"'{field}'" in message, body
        assert "distanceWithin" in message, body

    def test_plain_where(self, client) -> None:
        assert _ids(client, '{ documents(where: {category: {eq: "b"}}) { id } }') == [3]

    def test_where_within_a_distance(self, client) -> None:
        query = (
            "{ documents(where: {embedding: {cosineDistance: {dense: [1, 0]}, "
            "distanceWithin: 0.5}}, orderBy: {id: DESC}) { id } }"
        )
        assert _ids(client, query) == [4, 3, 1]

    @pytest.mark.parametrize(
        ("operator", "threshold", "expected"),
        [
            ("l2Distance", 1.0, [1, 3]),
            ("l1Distance", 1.5, [1, 3]),
            ("innerProduct", -0.8, [1, 4]),
        ],
    )
    def test_where_other_distances(self, client, operator, threshold, expected) -> None:
        query = (
            f"{{ documents(where: {{embedding: {{{operator}: {{dense: [1, 0]}}, "
            f"distanceWithin: {threshold}}}}}, orderBy: {{id: ASC}}) {{ id }} }}"
        )
        assert _ids(client, query) == expected

    def test_where_bit_distance(self, client) -> None:
        query = (
            '{ documents(where: {binaryEmbedding: {hammingDistance: "1100", distanceWithin: 1}}, '
            "orderBy: {id: ASC}) { id } }"
        )
        assert _ids(client, query) == [1, 3]

    def test_where_order_by_and_limit_as_documented(self, client) -> None:
        # docs/features/pgvector.md, "GraphQL Client Queries"
        query = """
            query SearchDocuments($embedding: [Float!]!, $category: String, $limit: Int) {
              documents(
                where: {
                  embedding: { cosineDistance: { dense: $embedding }, distanceWithin: 0.5 }
                  category: { eq: $category }
                }
                orderBy: { embedding: { cosineDistance: { dense: $embedding } } }
                limit: $limit
              ) { id }
            }
        """
        variables = {"embedding": [1, 0], "category": "a", "limit": 2}
        assert _ids(client, query, variables) == [1, 4]
        assert _ids(client, query, {**variables, "category": "b"}) == [3]


@pytest.mark.usefixtures("clear_registry_class")
class TestVectorFieldTypes:
    """``VectorField`` and ``HalfVectorField`` behave like ``list[float]``.

    Both failed the schema build (``Unsupported output type: VectorField``), and
    a ``where`` gave them a ``StringFilter``. The field names here match none of
    the name patterns that make a ``list[float]`` a vector, so the type alone has
    to. A nullable ``list[float]`` with a vector name got an ``OrderDirection``.
    """

    @pytest.fixture(scope="class")
    def client(self, class_db_pool, vector_docs):
        from fraiseql.fastapi.dependencies import set_db_pool
        from fraiseql.types.scalars.vector import HalfVectorField, VectorField

        @fraiseql.type(sql_source=_TYPED_VIEW, jsonb_column=None)
        class TypedDoc:
            id: int
            vec: VectorField
            half: HalfVectorField | None
            nullable_embedding: list[float] | None

        @fraiseql.query
        async def typed_documents(info) -> list[TypedDoc]:
            return await info.context["db"].find(_TYPED_VIEW, "typedDocuments", info)

        set_db_pool(class_db_pool)
        app = create_fraiseql_app(
            database_url="postgresql://test/test",  # the pool above is used
            types=[TypedDoc],
            queries=[typed_documents],
            production=False,
        )
        return TestClient(app)

    def test_values_come_back_as_lists(self, client) -> None:
        body = client.post(
            "/graphql", json={"query": "{ typedDocuments(orderBy: {id: ASC}) { id vec half } }"}
        ).json()
        assert "errors" not in body, body
        [row, *_] = body["data"]["typedDocuments"]
        assert (row["id"], row["vec"], row["half"]) == (1, [1.0, 0.0], [1.0, 0.0])

    @pytest.mark.parametrize("field", ["vec", "half", "nullableEmbedding"])
    def test_where_and_order_by_distance(self, client, field) -> None:
        query = (
            f"{{ typedDocuments(where: {{{field}: {{cosineDistance: {{dense: [1, 0]}}, "
            f"distanceWithin: 0.5}}}}, orderBy: {{{field}: {{cosineDistance: {{dense: [1, 0]}}}}}}) "
            "{ id } }"
        )
        assert _ids(client, query) == [1, 4, 3]


_HYBRID_VIEW = "v_vector_graphql_hybrid_doc"


@pytest.mark.usefixtures("clear_registry_class")
class TestVectorColumnNextToData:
    """A view with a JSONB ``data`` column and the vector as a column beside it.

    The vector can't be sorted inside JSONB, so the view exposes it as a column.
    ``orderBy`` read it as ``data."embedding"`` (``missing FROM-clause entry for
    table "data"``) while ``where`` used the column.
    """

    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def hybrid_view(self, class_db_pool, test_schema, vector_docs):
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            await conn.execute(
                f"CREATE VIEW {_HYBRID_VIEW} AS SELECT id, embedding, "
                "jsonb_build_object('id', id, 'category', category) AS data "
                "FROM tb_vector_graphql_doc"
            )
            await conn.commit()
        yield

    @pytest.fixture(scope="class")
    def hybrid_type(self):
        @fraiseql.type(sql_source=_HYBRID_VIEW)
        class HybridDoc:
            id: int
            category: str
            embedding: list[float]

        return HybridDoc

    @pytest.fixture(scope="class")
    def client(self, class_db_pool, hybrid_view, hybrid_type):
        from fraiseql.fastapi.dependencies import set_db_pool

        @fraiseql.query
        async def hybrid_documents(info) -> list[hybrid_type]:
            return await info.context["db"].find(_HYBRID_VIEW, "hybridDocuments", info)

        set_db_pool(class_db_pool)
        app = create_fraiseql_app(
            database_url="postgresql://test/test",  # the pool above is used
            types=[hybrid_type],
            queries=[hybrid_documents],
            production=False,
        )
        return TestClient(app)

    @pytest.mark.parametrize(
        ("operator", "expected"),
        [("cosineDistance", [1, 4, 3, 2]), ("l2Distance", [1, 3, 2, 4])],
    )
    def test_order_by_distance_over_graphql(self, client, operator, expected) -> None:
        query = (
            f"{{ hybridDocuments(orderBy: {{embedding: {{{operator}: {{dense: [1, 0]}}}}}}) "
            "{ id category } }"
        )
        assert _ids(client, query) == expected

    def test_where_and_order_by_over_graphql(self, client) -> None:
        query = (
            "{ hybridDocuments(where: {embedding: {cosineDistance: {dense: [1, 0]}, "
            "distanceWithin: 0.5}}, orderBy: {embedding: {cosineDistance: {dense: [1, 0]}}}) "
            "{ id } }"
        )
        assert _ids(client, query) == [1, 4, 3]

    @pytest.mark.asyncio
    async def test_order_by_distance_in_db_find(self, class_db_pool, client) -> None:
        from tests.unit.utils.test_response_utils import extract_graphql_data

        from fraiseql.db import FraiseQLRepository

        repo = FraiseQLRepository(class_db_pool, context={"mode": "development"})
        result = await repo.find(
            _HYBRID_VIEW, order_by={"embedding": {"cosine_distance": [1.0, 0.0]}}
        )
        assert [row["id"] for row in extract_graphql_data(result, _HYBRID_VIEW)] == [1, 4, 3, 2]

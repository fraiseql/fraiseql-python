"""End-to-end tests that vector distance filters render executable WHERE predicates.

Every test here EXECUTES the rendered fragment against PostgreSQL. The six
distance operators previously rendered a bare distance expression, which is a
``double precision`` and not a predicate, so PostgreSQL rejected the statement
with ``argument of WHERE must be type boolean``. String-matching the generated
SQL cannot catch that -- only running it can (#505).

The filters are built through the real operator-registry path
(:func:`safe_create_where_type`), which reaches ``FieldType.VECTOR`` only for a
vector-ish field name with no resolved type hint.
"""

import pytest
import pytest_asyncio
from psycopg.sql import SQL, Composed

from fraiseql.errors.exceptions import WhereClauseError
from fraiseql.sql.where_generator import safe_create_where_type

pytestmark = pytest.mark.integration


class _Doc:
    """Bare marker class; filter fields arrive through the OR plain-dict path."""

    __annotations__ = {}


WhereType = safe_create_where_type(_Doc)


def render(field: str, op: str, value: object, **extra: object) -> Composed | None:
    """Render one filter through the registry path, as a GraphQL where would."""
    where = WhereType()
    where.OR = [{field: {op: value, **extra}}]
    return where.to_sql()


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def vector_docs(class_db_pool, test_schema, pgvector_available) -> None:
    """Create a JSONB-backed table matching the registry's ``data ->> 'field'`` path."""
    if not pgvector_available:
        pytest.skip("pgvector extension not available")

    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute("CREATE TABLE vec_docs (id int PRIMARY KEY, data jsonb NOT NULL)")
        await conn.execute(
            """INSERT INTO vec_docs (id, data) VALUES
                (1, '{"embedding": "[1,0]", "binary_embedding": "1010"}'),
                (2, '{"embedding": "[0,1]", "binary_embedding": "0101"}')"""
        )
        await conn.commit()


@pytest.mark.usefixtures("vector_docs")
class TestVectorDistancePredicatesExecute:
    """The rendered fragment must be a boolean predicate PostgreSQL accepts."""

    @staticmethod
    async def run(pool, schema, condition: Composed, params: tuple = ()) -> list[int]:
        """Execute ``SELECT ... WHERE <condition>`` and return the matching ids."""
        stmt = Composed([SQL("SELECT id FROM vec_docs WHERE "), condition, SQL(" ORDER BY id")])
        async with pool.connection() as conn:
            await conn.execute(f"SET search_path TO {schema}, public")
            cur = await conn.execute(stmt, params) if params else await conn.execute(stmt)
            return [row[0] async for row in cur]

    @pytest.mark.parametrize(
        ("field", "operator", "query_vector", "threshold"),
        [
            ("embedding", "cosine_distance", [1.0, 0.0], 0.75),
            ("embedding", "l2_distance", [1.0, 0.0], 0.75),
            ("embedding", "l1_distance", [1.0, 0.0], 0.75),
            # <#> is the *negative* inner product, so row 1 scores -1 and row 2 scores 0.
            ("embedding", "inner_product", [1.0, 0.0], -0.5),
            ("binary_embedding", "hamming_distance", "1010", 0.75),
            ("binary_embedding", "jaccard_distance", "1010", 0.75),
        ],
    )
    async def test_distance_operator_is_a_usable_where_predicate(
        self, class_db_pool, test_schema, field, operator, query_vector, threshold
    ) -> None:
        """All six operators must execute as WHERE predicates, not bare numbers.

        The threshold discriminates between the two rows, so a predicate that
        executed but ignored the distance would fail this assertion too.
        """
        condition = render(field, operator, {"vector": query_vector, "threshold": threshold})
        assert condition is not None

        assert await self.run(class_db_pool, test_schema, condition) == [1]

    async def test_predicate_still_executes_alongside_placeholders(
        self, class_db_pool, test_schema
    ) -> None:
        """A statement carrying parameters must not break the rendered fragment (#507)."""
        condition = render("binary_embedding", "jaccard_distance", {"vector": "1010"})
        assert condition is not None

        stmt = Composed(
            [SQL("SELECT id FROM vec_docs WHERE "), condition, SQL(" AND id = %s ORDER BY id")]
        )
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            cur = await conn.execute(stmt, (1,))
            assert [row[0] async for row in cur] == [1]


@pytest.mark.usefixtures("vector_docs")
class TestVectorFilterInputShapes:
    """Both the normalised and the GraphQL-declared input shapes must work."""

    @pytest.mark.parametrize(
        ("value", "extra"),
        [
            ({"vector": [1.0, 0.0], "threshold": 0.75}, {}),
            ({"dense": [1.0, 0.0]}, {"distance_within": 0.75}),
            ([1.0, 0.0], {"distance_within": 0.75}),
            ({"vector": [1.0, 0.0], "threshold": 0.75, "comparison": "lt"}, {}),
        ],
    )
    async def test_accepted_shapes_render_and_execute(
        self, class_db_pool, test_schema, value, extra
    ) -> None:
        """Each documented input shape must produce an executable predicate."""
        condition = render("embedding", "cosine_distance", value, **extra)
        assert condition is not None

        stmt = Composed([SQL("SELECT id FROM vec_docs WHERE "), condition, SQL(" ORDER BY id")])
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")
            cur = await conn.execute(stmt)
            assert [row[0] async for row in cur] == [1]

    async def test_sparse_vector_shape_renders(self) -> None:
        """A sparse ``{indices, values}`` payload must not be mistaken for a dense filter."""
        from dataclasses import dataclass

        from fraiseql.types.scalars.vector import SparseVectorField

        @dataclass
        class SparseDoc:
            sparse_emb: SparseVectorField

        where = safe_create_where_type(SparseDoc)()
        where.sparse_emb = {"cosine_distance": {"indices": [1, 3], "values": [0.1, 0.2]}}

        rendered = where.to_sql()
        assert rendered is not None
        assert "sparsevec" in rendered.as_string(None)


class TestVectorFilterRejectsBadInput:
    """A malformed vector filter must fail loudly, never vanish from the WHERE clause."""

    def test_unusable_shape_raises_instead_of_dropping_the_predicate(self) -> None:
        """A silently dropped predicate would widen the result set (#505)."""
        with pytest.raises(WhereClauseError):
            render("embedding", "cosine_distance", {"nonsense": 1})

    def test_unknown_comparison_raises(self) -> None:
        """An unsupported comparison must not fall back to a default operator."""
        with pytest.raises(WhereClauseError):
            render("embedding", "cosine_distance", {"vector": [1.0, 0.0], "comparison": "between"})

    def test_sibling_filters_do_not_mask_a_bad_vector_filter(self) -> None:
        """The scoping filter surviving alone is exactly the dangerous outcome."""
        with pytest.raises(WhereClauseError):
            where = WhereType()
            where.OR = [
                {"tenant": {"eq": "acme"}, "embedding": {"cosine_distance": {"bad": 1}}},
            ]
            where.to_sql()


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def scoped_docs(class_db_pool, test_schema, pgvector_available) -> None:
    """Rows carrying a scoping key, to show what a dropped vector filter leaves."""
    if not pgvector_available:
        pytest.skip("pgvector extension not available")

    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute("CREATE TABLE vec_docs (id int PRIMARY KEY, data jsonb NOT NULL)")
        await conn.execute(
            """INSERT INTO vec_docs (id, data) VALUES
                (1, '{"kind": "doc", "embedding": "[1,0]"}'),
                (2, '{"kind": "doc", "embedding": "[0,1]"}')"""
        )
        await conn.commit()


@pytest.mark.usefixtures("scoped_docs")
class TestNonPredicateOperatorsNeverReachTheDatabase:
    """Four registry entries rendered an expression, not a predicate (#510).

    ``custom_distance``, ``vector_norm``, ``quantized_distance`` and
    ``reconstruct`` are refused in a WHERE clause. Each test here first
    *executes* the outcome being prevented, so the assertion that the fix
    raises is anchored to a demonstrated result set rather than to a string.
    """

    @staticmethod
    async def run_sql(pool, schema, statement: str) -> list[int]:
        """Execute a raw statement and return the matching ids, sorted."""
        async with pool.connection() as conn:
            await conn.execute(f"SET search_path TO {schema}, public")
            cur = await conn.execute(statement)
            return sorted([row[0] async for row in cur])

    @staticmethod
    async def run(pool, schema, condition: Composed) -> list[int]:
        """Execute a rendered condition and return the matching ids."""
        stmt = Composed([SQL("SELECT id FROM vec_docs WHERE "), condition, SQL(" ORDER BY id")])
        async with pool.connection() as conn:
            await conn.execute(f"SET search_path TO {schema}, public")
            cur = await conn.execute(stmt)
            return [row[0] async for row in cur]

    async def test_injected_function_name_executes_and_returns_every_row(
        self, class_db_pool, test_schema
    ) -> None:
        """The statement ``{"function": "true OR 1=1 --"}`` used to build, run.

        ``build_custom_distance_sql`` concatenated the function name with
        ``psycopg.sql.SQL()``, the raw-fragment constructor, so this parsed as
        written. Establishes that the channel was live before asserting it is
        closed.
        """
        injected = "SELECT id FROM vec_docs WHERE true OR 1=1 --((data ->> 'embedding'))"
        assert await self.run_sql(class_db_pool, test_schema, injected) == [1, 2]

        with pytest.raises(WhereClauseError):
            render("embedding", "custom_distance", {"function": "true OR 1=1 --"})

    async def test_injected_parameter_executes_and_returns_every_row(
        self, class_db_pool, test_schema
    ) -> None:
        """``parameters`` was a second raw channel: ``SQL(str(param))`` per entry."""
        injected = (
            "SELECT id FROM vec_docs WHERE strpos((data ->> 'embedding'), 'x') > -1 OR true --)"
        )
        assert await self.run_sql(class_db_pool, test_schema, injected) == [1, 2]

        with pytest.raises(WhereClauseError):
            render(
                "embedding",
                "custom_distance",
                {"function": "strpos", "parameters": ["'x') > -1 OR true --"]},
            )

    async def test_vector_norm_rendering_never_existed_in_pgvector(
        self, class_db_pool, test_schema
    ) -> None:
        """``vector_norm(col, 'l2')`` is not a function at any arity.

        pgvector declares ``vector_norm(vector)``. The two-argument form the
        operator emitted -- against an uncast ``text`` column, and registered
        for sparse fields where pgvector names the function ``l2_norm`` --
        failed on every execution, so no caller can be relying on it.
        """
        import psycopg

        with pytest.raises(psycopg.errors.UndefinedFunction):
            await self.run_sql(
                class_db_pool,
                test_schema,
                "SELECT id FROM vec_docs WHERE vector_norm((data ->> 'embedding'), 'l2')",
            )

        with pytest.raises(WhereClauseError):
            render("embedding", "vector_norm", "l2")

    async def test_a_dropped_vector_filter_would_widen_the_result_set(
        self, class_db_pool, test_schema
    ) -> None:
        """Unregistering the operators instead is the worse fix.

        ``get_operator_function`` raises ``ValueError`` for an unknown
        operator and ``_make_filter_field_composed`` swallows it, so the scope
        filter would render and execute alone -- the query succeeding over
        every row rather than the similar ones. The first half of this test is
        that surviving filter, rendered by the real renderer and executed.
        """
        scope_only = render("kind", "eq", "doc")
        assert scope_only is not None
        assert await self.run(class_db_pool, test_schema, scope_only) == [1, 2]

        where = WhereType()
        where.OR = [
            {"kind": {"eq": "doc"}, "embedding": {"custom_distance": {"function": "my_dist"}}}
        ]
        with pytest.raises(WhereClauseError):
            where.to_sql()

    async def test_supported_operators_are_unaffected(self, class_db_pool, test_schema) -> None:
        """The six real distance operators must still narrow the result set."""
        value = {"vector": [1.0, 0.0], "threshold": 0.75}
        condition = render("embedding", "cosine_distance", value)
        assert condition is not None
        assert await self.run(class_db_pool, test_schema, condition) == [1]

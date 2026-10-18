"""Mutation field names come from the mutation, not its SQL function.

A class mutation is named after its class (``CreateThing`` -> ``createThing``),
``name=`` overrides it, and ``function=`` only picks the SQL function. Until the
next major release, a mutation that works today keeps its old name and the schema
build emits one ``FutureWarning`` listing every field that will be renamed.
"""

import json
import warnings
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, Self

import pytest
from fastapi.testclient import TestClient
from graphql import GraphQLSchema, GraphQLUnionType, get_named_type

import fraiseql
from fraiseql import mutation
from fraiseql.gql.schema_builder import build_fraiseql_schema

pytestmark = pytest.mark.usefixtures("clear_registry_class", "clear_registry")


def _types() -> SimpleNamespace:
    @fraiseql.input
    class CreateThingInput:
        name: str

    @fraiseql.type
    class Thing:
        id: str
        name: str

    @fraiseql.type
    class CreateThingSuccess:
        thing: Thing
        message: str

    @fraiseql.type
    class CreateThingEnrichedSuccess:
        thing: Thing
        message: str
        enriched: bool

    @fraiseql.type
    class CreateThingError:
        code: int
        message: str

    return SimpleNamespace(
        In=CreateThingInput,
        Thing=Thing,
        S=CreateThingSuccess,
        S2=CreateThingEnrichedSuccess,
        E=CreateThingError,
    )


def _build(mutations: list[Any], **kwargs: Any) -> tuple[GraphQLSchema, list[str]]:
    """Build a schema; return it with the text of every FutureWarning raised."""

    @fraiseql.query
    async def ping(info: Any) -> str:
        return "ok"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema = build_fraiseql_schema(query_types=[ping], mutation_resolvers=mutations, **kwargs)
    return schema, [str(w.message) for w in caught if issubclass(w.category, FutureWarning)]


def _fields(schema: GraphQLSchema) -> list[str]:
    assert schema.mutation_type is not None
    return sorted(schema.mutation_type.fields)


def _field_union(schema: GraphQLSchema, field: str) -> tuple[str, list[str]]:
    assert schema.mutation_type is not None
    union = get_named_type(schema.mutation_type.fields[field].type)
    assert isinstance(union, GraphQLUnionType)
    return union.name, [member.name for member in union.types]


class TestSharedFunction:
    """(a) Two ``@mutation`` classes with the same ``function=``."""

    def test_both_fields_exist_with_their_own_results(self) -> None:
        t = _types()

        @mutation(function="create_thing")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        @mutation(function="create_thing")
        class CreateThingEnriched:
            input: t.In
            success: t.S2
            error: t.E

        schema, future = _build([CreateThing, CreateThingEnriched])

        assert _fields(schema) == ["createThing", "createThingEnriched"]
        assert _field_union(schema, "createThing") == (
            "CreateThingResult",
            ["CreateThingSuccess", "CreateThingError"],
        )
        assert _field_union(schema, "createThingEnriched") == (
            "CreateThingEnrichedResult",
            ["CreateThingEnrichedSuccess", "CreateThingError"],
        )
        assert future == []

    def test_both_call_the_shared_function(self) -> None:
        t = _types()

        @mutation(function="create_thing")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        @mutation(function="create_thing")
        class CreateThingEnriched:
            input: t.In
            success: t.S2
            error: t.E

        assert CreateThing.__fraiseql_mutation__.function_name == "create_thing"
        assert CreateThingEnriched.__fraiseql_mutation__.function_name == "create_thing"

    def test_old_name_of_a_working_mutation_clashes_with_a_new_name(self) -> None:
        """The duplicate check runs on the final names, after the old/new choice."""
        t = _types()

        @fraiseql.type
        class CreateThingV3Success:
            thing: t.Thing
            message: str

        @mutation(function="create_thing_v2")
        class MakeThing:
            input: t.In
            success: t.S
            error: t.E

        @mutation(function="x")
        class CreateThingV2:
            input: t.In
            success: t.S2
            error: t.E

        @mutation(function="x")
        class CreateThingV3:
            input: t.In
            success: CreateThingV3Success
            error: t.E

        with pytest.raises(ValueError, match="createThingV2") as exc:
            _build([MakeThing, CreateThingV2, CreateThingV3])

        assert "MakeThing" in str(exc.value)
        assert "CreateThingV2" in str(exc.value)
        assert "name=" in str(exc.value)


class TestRegistry:
    def test_classes_sharing_a_function_are_both_registered(self) -> None:
        from fraiseql.gql.builders.registry import SchemaRegistry

        t = _types()

        @mutation(function="create_thing")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        @mutation(function="create_thing")
        class CreateThingEnriched:
            input: t.In
            success: t.S2
            error: t.E

        registered = SchemaRegistry.get_instance().mutations.values()
        assert CreateThing.__fraiseql_resolver__ in registered
        assert CreateThingEnriched.__fraiseql_resolver__ in registered

    def test_redefined_class_replaces_the_old_one(self) -> None:
        from fraiseql.gql.builders.registry import SchemaRegistry

        t = _types()

        @mutation(function="create_thing")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        first = CreateThing

        @mutation(function="create_thing")
        class CreateThing:  # type: ignore[no-redef]
            input: t.In
            success: t.S2
            error: t.E

        registered = list(SchemaRegistry.get_instance().mutations.values())
        assert CreateThing.__fraiseql_resolver__ in registered
        assert first.__fraiseql_resolver__ not in registered


class TestNameOverride:
    def test_name_sets_the_field_name(self) -> None:
        t = _types()

        @mutation(function="fn_create_thing", name="makeThing")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        schema, future = _build([CreateThing])

        assert _fields(schema) == ["makeThing"]
        assert future == []

    def test_name_is_used_as_given_without_camel_case(self) -> None:
        t = _types()

        @mutation(name="make_thing")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        schema, _ = _build([CreateThing])

        assert _fields(schema) == ["make_thing"]

    def test_name_on_a_function_mutation(self) -> None:
        t = _types()

        @mutation(name="makeThing")
        async def create_thing(info: Any, input: t.In) -> t.S | t.E:  # type: ignore[valid-type]
            raise NotImplementedError

        schema, future = _build([create_thing])

        assert _fields(schema) == ["makeThing"]
        assert future == []

    def test_same_name_twice_raises(self) -> None:
        t = _types()

        @mutation(name="makeThing")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        @mutation(name="makeThing")
        class CreateThingEnriched:
            input: t.In
            success: t.S2
            error: t.E

        with pytest.raises(ValueError, match="makeThing") as exc:
            _build([CreateThing, CreateThingEnriched])

        assert "CreateThing " in str(exc.value) or "CreateThing," in str(exc.value)
        assert "CreateThingEnriched" in str(exc.value)


class TestDeprecatedFunctionName:
    """A working mutation whose ``function=`` differs from its class keeps its name."""

    def test_keeps_the_function_name_and_warns_once(self) -> None:
        t = _types()

        @mutation(function="fn_create_thing")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        schema, future = _build([CreateThing])

        assert _fields(schema) == ["fnCreateThing"]
        assert len(future) == 1
        assert "'fnCreateThing' -> 'createThing'" in future[0]
        assert "name=" in future[0]
        assert "2.0.0" in future[0]
        assert "FraiseQL 2.0" not in future[0]
        assert "FraiseQL v2" not in future[0]

    def test_one_warning_lists_every_rename(self) -> None:
        t = _types()

        @fraiseql.type
        class DeleteThingSuccess:
            thing: t.Thing
            message: str

        @mutation(function="fn_create_thing")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        @mutation(function="fn_update_thing")
        class UpdateThing:
            input: t.In
            success: t.S2
            error: t.E

        @mutation(function="fn_delete_thing")
        class DeleteThing:
            input: t.In
            success: DeleteThingSuccess
            error: t.E

        schema, future = _build([CreateThing, UpdateThing, DeleteThing])

        assert _fields(schema) == ["fnCreateThing", "fnDeleteThing", "fnUpdateThing"]
        assert len(future) == 1
        for old, new in [
            ("fnCreateThing", "createThing"),
            ("fnUpdateThing", "updateThing"),
            ("fnDeleteThing", "deleteThing"),
        ]:
            assert f"'{old}' -> '{new}'" in future[0]

    def test_function_matching_the_class_does_not_warn(self) -> None:
        t = _types()

        @mutation(function="create_thing")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        schema, future = _build([CreateThing])

        assert _fields(schema) == ["createThing"]
        assert future == []

    def test_snake_case_schema(self) -> None:
        t = _types()

        @mutation(function="fn_create_thing")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        schema, future = _build([CreateThing], camel_case_fields=False)

        assert _fields(schema) == ["fn_create_thing"]
        assert len(future) == 1
        assert "'fn_create_thing' -> 'create_thing'" in future[0]


class TestFunctionResolvers:
    def test_decorated_function_keeps_its_name(self) -> None:
        t = _types()

        @mutation
        async def fn_create_thing(info: Any, input: t.In) -> t.S | t.E:  # type: ignore[valid-type]
            raise NotImplementedError

        schema, future = _build([fn_create_thing])

        assert _fields(schema) == ["fnCreateThing"]
        assert future == []

    def test_plain_resolver_keeps_its_name(self) -> None:
        t = _types()

        async def fn_create_thing(info: Any, input: t.In) -> t.S | t.E:  # type: ignore[valid-type]
            raise NotImplementedError

        schema, future = _build([fn_create_thing])

        assert _fields(schema) == ["fnCreateThing"]
        assert future == []


class TestAutoDiscoveredMutations:
    """The ``name:`` in a ``@fraiseql:mutation`` comment is the 2.0.0 field name."""

    @staticmethod
    async def _generate(comment_name: str) -> Any:
        from fraiseql.introspection.input_generator import InputGenerator
        from fraiseql.introspection.metadata_parser import MutationAnnotation
        from fraiseql.introspection.mutation_generator import MutationGenerator
        from fraiseql.introspection.postgres_introspector import FunctionMetadata, ParameterInfo
        from fraiseql.introspection.type_mapper import TypeMapper

        class NoCompositeTypes:
            async def discover_composite_type(self, *args: Any, **kwargs: Any) -> None:
                return None

        t = _types()

        class InputFromTypes(InputGenerator):
            async def generate_input_type(self, *args: Any, **kwargs: Any) -> type:
                return t.In

        generator = MutationGenerator(InputFromTypes(TypeMapper()))
        generated = await generator.generate_mutation_for_function(
            FunctionMetadata(
                schema_name="public",
                function_name="fn_create_thing",
                parameters=[
                    ParameterInfo(name="p_name", pg_type="text", mode="IN", default_value=None)
                ],
                return_type="jsonb",
                comment=None,
                language="plpgsql",
            ),
            MutationAnnotation(
                name=comment_name, success_type="CreateThingSuccess", error_type="CreateThingError"
            ),
            {"CreateThingSuccess": t.S, "CreateThingError": t.E},
            NoCompositeTypes(),
        )
        assert generated is not None
        return generated

    @pytest.mark.asyncio
    async def test_keeps_the_function_name_and_points_to_the_comment(self) -> None:
        generated = await self._generate("makeThing")

        schema, future = _build([generated])

        assert _fields(schema) == ["fnCreateThing"]
        assert len(future) == 1
        assert "'fnCreateThing' -> 'makeThing'" in future[0]
        assert "@fraiseql:mutation comment" in future[0]

    @pytest.mark.asyncio
    async def test_comment_name_matching_today_does_not_warn(self) -> None:
        generated = await self._generate("fnCreateThing")

        schema, future = _build([generated])

        assert _fields(schema) == ["fnCreateThing"]
        assert future == []


class _FakeCursor:
    def __init__(self, conn: "_FakeConnection") -> None:
        self._conn = conn
        self._row: tuple[Any, ...] | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        if "row_to_json" in query:
            self._conn.calls.append(query)
            self._row = (self._conn.result,)

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self._row


class _FakeConnection:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[str] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)


class _FakeDb:
    """The parts of FraiseQLRepository a class mutation's resolver uses."""

    def __init__(self, result: dict[str, Any]) -> None:
        self.conn = _FakeConnection(result)

    def get_pool(self) -> "_FakeDb":
        return self

    @asynccontextmanager
    async def connection(self) -> Any:
        yield self.conn

    async def _set_session_variables(self, cursor: Any) -> None:
        return None


class TestSharedFunctionThroughTheApp:
    """(a) end to end: both fields execute through the FastAPI app."""

    def test_each_field_returns_its_own_success_shape(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import MagicMock

        from fraiseql.fastapi import create_fraiseql_app

        monkeypatch.setattr("fraiseql.fastapi.dependencies.get_db_pool", MagicMock)

        t = _types()

        @mutation(function="create_thing")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        @mutation(function="create_thing")
        class CreateThingEnriched:
            input: t.In
            success: t.S2
            error: t.E

        @fraiseql.query
        async def ping(info: Any) -> str:
            return "ok"

        db = _FakeDb(
            {
                "status": "created",
                "message": "Thing created",
                "entity_id": "t1",
                "entity_type": "Thing",
                "entity": {"id": "t1", "name": "lamp"},
                "updated_fields": None,
                "cascade": None,
                "metadata": {"enriched": True},
            }
        )

        async def context(request: Any) -> dict[str, Any]:
            return {"db": db}

        app = create_fraiseql_app(
            database_url="postgresql://test/test",
            types=[t.Thing, t.S, t.S2, t.E],
            queries=[ping],
            mutations=[CreateThing, CreateThingEnriched],
            context_getter=context,
        )
        client = TestClient(app)

        plain = client.post(
            "/graphql",
            json={
                "query": 'mutation { createThing(input: {name: "lamp"}) {'
                " __typename ... on CreateThingSuccess { message thing { id name } } } }"
            },
        ).json()
        enriched = client.post(
            "/graphql",
            json={
                "query": 'mutation { createThingEnriched(input: {name: "lamp"}) {'
                " __typename ... on CreateThingEnrichedSuccess { message thing { id } } } }"
            },
        ).json()

        assert "errors" not in plain, json.dumps(plain)
        assert "errors" not in enriched, json.dumps(enriched)
        # The Rust pipeline also adds __typename to the nested entity; not checked here.
        plain_result = plain["data"]["createThing"]
        enriched_result = enriched["data"]["createThingEnriched"]
        assert plain_result["__typename"] == "CreateThingSuccess"
        assert plain_result["message"] == "Thing created"
        assert {k: plain_result["thing"][k] for k in ("id", "name")} == {"id": "t1", "name": "lamp"}
        assert enriched_result["__typename"] == "CreateThingEnrichedSuccess"
        assert enriched_result["thing"]["id"] == "t1"
        assert len(db.conn.calls) == 2
        assert all("public.create_thing(" in call for call in db.conn.calls)

"""Each mutation gets its own result union, named after its field.

The union is ``<FieldName>Result`` (``createThing`` -> ``CreateThingResult``),
``result_name=`` overrides it, and two mutations may share success and error
types. Until the next major release, a mutation that works today keeps its old
union name (``<success type without "Success">Result``), and the schema build
emits one ``FutureWarning`` listing every union that will be renamed.
"""

import warnings
from types import SimpleNamespace
from typing import Any, get_args

import pytest
from graphql import GraphQLObjectType, GraphQLSchema, GraphQLUnionType, get_named_type

import fraiseql
from fraiseql import mutation
from fraiseql.gql.schema_builder import build_fraiseql_schema

pytestmark = pytest.mark.usefixtures("clear_registry_class", "clear_registry")

_RESULT_DEPRECATED = r"fraiseql\.result\(\) is deprecated"


def _types() -> SimpleNamespace:
    @fraiseql.input
    class CreateThingInput:
        name: str

    @fraiseql.type
    class Thing:
        id: str

    @fraiseql.type
    class CreateThingSuccess:
        thing: Thing
        message: str

    @fraiseql.type
    class CreateThingError:
        code: int
        message: str

    @fraiseql.type
    class OtherError:
        code: int
        message: str

    return SimpleNamespace(
        In=CreateThingInput, Thing=Thing, S=CreateThingSuccess, E=CreateThingError, E2=OtherError
    )


def _build(mutations: list[Any]) -> tuple[GraphQLSchema, list[str]]:
    """Build a schema; return it with the text of every FutureWarning raised."""

    @fraiseql.query
    async def ping(info: Any) -> str:
        return "ok"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema = build_fraiseql_schema(query_types=[ping], mutation_resolvers=mutations)
    return schema, [str(w.message) for w in caught if issubclass(w.category, FutureWarning)]


def _field_union(schema: GraphQLSchema, field: str) -> tuple[str, list[str]]:
    assert schema.mutation_type is not None
    union = get_named_type(schema.mutation_type.fields[field].type)
    assert isinstance(union, GraphQLUnionType)
    return union.name, [member.name for member in union.types]


class TestSharedSuccessType:
    """(b) Two mutations whose results share a success type."""

    def test_same_pair_gets_one_union_per_mutation(self) -> None:
        t = _types()

        @mutation(function="create_thing")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        @mutation(function="create_thing_again")
        class CreateThingAgain:
            input: t.In
            success: t.S
            error: t.E

        schema, future = _build([CreateThing, CreateThingAgain])

        members = ["CreateThingSuccess", "CreateThingError"]
        assert _field_union(schema, "createThing") == ("CreateThingResult", members)
        assert _field_union(schema, "createThingAgain") == ("CreateThingAgainResult", members)
        assert future == []

    def test_different_error_types(self) -> None:
        t = _types()

        @mutation(function="create_thing")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        @mutation(function="create_thing_other")
        class CreateThingOther:
            input: t.In
            success: t.S
            error: t.E2

        schema, future = _build([CreateThing, CreateThingOther])

        assert _field_union(schema, "createThing") == (
            "CreateThingResult",
            ["CreateThingSuccess", "CreateThingError"],
        )
        assert _field_union(schema, "createThingOther") == (
            "CreateThingOtherResult",
            ["CreateThingSuccess", "OtherError"],
        )
        assert future == []

    def test_result_helper_and_mutation_on_the_same_pair(self) -> None:
        t = _types()
        with pytest.warns(DeprecationWarning, match=_RESULT_DEPRECATED):
            union = fraiseql.result(t.S, t.E)

        async def create_thing_fn(info: Any, input: t.In) -> union:  # type: ignore[valid-type]
            raise NotImplementedError

        @mutation(function="create_thing")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        schema, _ = _build([create_thing_fn, CreateThing])

        assert _field_union(schema, "createThing")[0] == "CreateThingResult"
        assert _field_union(schema, "createThingFn")[0] == "CreateThingFnResult"

    def test_cascade_on_a_shared_success_type_reaches_both(self) -> None:
        """Pinned: cascade is added to the success type itself, so a mutation sharing
        that type without cascade also shows the field (it resolves to null).
        """
        t = _types()

        @mutation(function="create_thing", enable_cascade=True)
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        @mutation(function="create_thing_quietly")
        class CreateThingQuietly:
            input: t.In
            success: t.S
            error: t.E

        schema, _ = _build([CreateThing, CreateThingQuietly])

        assert schema.mutation_type is not None
        for field in ("createThing", "createThingQuietly"):
            union = get_named_type(schema.mutation_type.fields[field].type)
            assert isinstance(union, GraphQLUnionType)
            success = next(m for m in union.types if m.name == "CreateThingSuccess")
            assert isinstance(success, GraphQLObjectType)
            assert "cascade" in success.fields


class TestResultHelper:
    def test_returns_a_union_of_the_pair_it_was_given(self) -> None:
        t = _types()
        with pytest.warns(DeprecationWarning, match=_RESULT_DEPRECATED):
            fraiseql.result(t.S, t.E)

        with pytest.warns(DeprecationWarning, match=r"Success \| Error"):
            union = fraiseql.result(t.S, t.E2)

        assert set(get_args(get_args(union)[0])) == {t.S, t.E2}


class TestResultName:
    def test_result_name_is_used(self) -> None:
        t = _types()

        @mutation(function="fn_create_thing", name="createThing", result_name="ThingOutcome")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        schema, future = _build([CreateThing])

        assert _field_union(schema, "createThing")[0] == "ThingOutcome"
        assert future == []

    def test_result_name_on_a_function_mutation(self) -> None:
        t = _types()

        @mutation(result_name="ThingOutcome")
        async def create_thing(info: Any, input: t.In) -> t.S | t.E:  # type: ignore[valid-type]
            raise NotImplementedError

        schema, future = _build([create_thing])

        assert _field_union(schema, "createThing")[0] == "ThingOutcome"
        assert future == []

    def test_same_result_name_twice_raises(self) -> None:
        t = _types()

        @mutation(result_name="ThingOutcome")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        @mutation(result_name="ThingOutcome")
        class CreateThingAgain:
            input: t.In
            success: t.S
            error: t.E

        with pytest.raises(ValueError, match="ThingOutcome") as exc:
            _build([CreateThing, CreateThingAgain])

        assert "CreateThingAgain" in str(exc.value)
        assert "result_name=" in str(exc.value)


class TestDeprecatedUnionName:
    """A working mutation whose old union name differs keeps it, with a warning."""

    def test_keeps_the_success_type_name_and_warns_once(self) -> None:
        t = _types()

        @fraiseql.type
        class PostSuccess:
            thing: t.Thing
            message: str

        @mutation(function="update_post_title")
        class UpdatePostTitle:
            input: t.In
            success: PostSuccess
            error: t.E

        schema, future = _build([UpdatePostTitle])

        assert _field_union(schema, "updatePostTitle")[0] == "PostResult"
        assert len(future) == 1
        assert "result union 'PostResult' -> 'UpdatePostTitleResult'" in future[0]
        assert "result_name=" in future[0]

    def test_field_and_union_renames_share_one_warning(self) -> None:
        t = _types()

        @fraiseql.type
        class PostSuccess:
            thing: t.Thing
            message: str

        @mutation(function="fn_update_post_title")
        class UpdatePostTitle:
            input: t.In
            success: PostSuccess
            error: t.E

        schema, future = _build([UpdatePostTitle])

        assert _field_union(schema, "fnUpdatePostTitle")[0] == "PostResult"
        assert len(future) == 1
        assert "field 'fnUpdatePostTitle' -> 'updatePostTitle'" in future[0]
        assert "result union 'PostResult' -> 'UpdatePostTitleResult'" in future[0]

    def test_warning_points_at_the_caller(self) -> None:
        """The warning is attributed to the code that builds the schema, not to fraiseql."""
        t = _types()

        @fraiseql.type
        class PostSuccess:
            thing: t.Thing
            message: str

        @mutation(function="update_post_title")
        class UpdatePostTitle:
            input: t.In
            success: PostSuccess
            error: t.E

        @fraiseql.query
        async def ping(info: Any) -> str:
            return "ok"

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            build_fraiseql_schema(query_types=[ping], mutation_resolvers=[UpdatePostTitle])

        future = [w for w in caught if issubclass(w.category, FutureWarning)]
        assert len(future) == 1
        assert future[0].filename == __file__

    def test_kept_union_name_clashing_with_a_new_one_raises(self) -> None:
        """The duplicate check runs on the final union names."""
        t = _types()

        @fraiseql.type
        class CreateThingAgainSuccess:
            thing: t.Thing
            message: str

        @mutation(function="make_thing")
        class MakeThing:  # keeps CreateThingAgainResult, from its success type
            input: t.In
            success: CreateThingAgainSuccess
            error: t.E

        @mutation(function="create_thing")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        @mutation(function="create_thing_again")
        class CreateThingAgain:  # shares CreateThingSuccess: new name CreateThingAgainResult
            input: t.In
            success: t.S
            error: t.E

        with pytest.raises(ValueError, match="CreateThingAgainResult") as exc:
            _build([MakeThing, CreateThing, CreateThingAgain])

        assert "MakeThing" in str(exc.value)
        assert "CreateThingAgain" in str(exc.value)


class TestClashMessage:
    def test_classes_with_the_same_name_are_told_apart(self) -> None:
        t = _types()

        def define(function: str) -> type:
            @mutation(function=function)
            class CreateThing:
                input: t.In
                success: t.S
                error: t.E

            return CreateThing

        define("create_thing")
        define("custom_create_thing")

        with pytest.raises(ValueError, match="CreateThingResult") as exc:
            _build([])

        assert str(exc.value).count("define.<locals>.CreateThing") == 2


class TestNamePerPath:
    """The union name each way of declaring a mutation puts in the schema."""

    def test_mutation_class(self) -> None:
        t = _types()

        @mutation(function="create_thing")
        class CreateThing:
            input: t.In
            success: t.S
            error: t.E

        schema, future = _build([CreateThing])

        assert _field_union(schema, "createThing")[0] == "CreateThingResult"
        assert future == []

    def test_result_helper(self) -> None:
        t = _types()
        with pytest.warns(DeprecationWarning, match=_RESULT_DEPRECATED):
            union = fraiseql.result(t.S, t.E)

        async def create_thing(info: Any, input: t.In) -> union:  # type: ignore[valid-type]
            raise NotImplementedError

        schema, future = _build([create_thing])

        assert _field_union(schema, "createThing")[0] == "CreateThingResult"
        assert future == []

    def test_plain_union_annotation(self) -> None:
        t = _types()

        async def create_thing(info: Any, input: t.In) -> t.S | t.E:  # type: ignore[valid-type]
            raise NotImplementedError

        schema, future = _build([create_thing])

        assert _field_union(schema, "createThing")[0] == "CreateThingResult"
        assert future == []

    def test_success_error_convention(self) -> None:
        t = _types()

        @fraiseql.success
        class MakeWidgetSuccess:
            thing: t.Thing

        @fraiseql.error
        class MakeWidgetError:
            code: int

        @mutation(function="make_widget")
        class MakeWidget:
            input: t.In
            success: MakeWidgetSuccess
            error: MakeWidgetError

        schema, _ = _build([MakeWidget])

        assert _field_union(schema, "makeWidget")[0] == "MakeWidgetResult"
        assert "MakeWidgetSuccessResult" not in schema.type_map

    def test_generate_mutation_schema_name_is_kept(self) -> None:
        from fraiseql.schema import generate_mutation_schema

        t = _types()

        @fraiseql.type
        class GenSuccess:
            gizmo: t.Thing
            status: str
            message: str

        @fraiseql.type
        class GenError:
            code: int
            status: str
            message: str

        union = generate_mutation_schema("CreateGizmo", GenSuccess, GenError).union_type

        async def make_gizmo(info: Any, input: t.In) -> union:  # type: ignore[valid-type]
            raise NotImplementedError

        schema, future = _build([make_gizmo])

        assert _field_union(schema, "makeGizmo")[0] == "CreateGizmoResult"
        assert future == []

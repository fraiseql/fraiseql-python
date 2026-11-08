"""A class mutation's members are checked when the schema is built (issues #576, #587).

A class mutation reads only ``input``, ``success``, ``error`` and ``prepare_input``.
Anything else (``failure:``, ``noop:``, ``errors:``, ``resolve()``, a typo) used to be
ignored without a word, and a missing ``input:`` failed with an error that named
neither the mutation nor the annotation.
"""

import pytest

import fraiseql
from fraiseql.gql.schema_builder import build_fraiseql_schema

pytestmark = pytest.mark.usefixtures("clear_registry")


@fraiseql.type
class Thing:
    id: int


@fraiseql.input
class ThingInput:
    name: str


@fraiseql.success
class ThingSuccess:
    thing: Thing


@fraiseql.error
class ThingError:
    message: str


async def thing(info) -> Thing:
    return Thing(id=1)


def _build() -> None:
    fraiseql.query(thing)
    build_fraiseql_schema()


def test_missing_input_names_the_mutation() -> None:
    @fraiseql.mutation
    class ClearCart:
        success: ThingSuccess
        error: ThingError

    with pytest.raises(TypeError, match=r"Mutation ClearCart has no `input:` annotation"):
        _build()


def test_no_result_type_names_the_mutation() -> None:
    @fraiseql.mutation
    class CreateThing:
        input: ThingInput

    with pytest.raises(TypeError, match=r"CreateThing has neither `success:` nor `error:`"):
        _build()


@pytest.mark.parametrize("member", ["failure", "noop", "errors"])
def test_error_type_under_another_name_points_at_error(member: str) -> None:
    namespace = {"__annotations__": {"input": ThingInput, "success": ThingSuccess}}
    namespace["__annotations__"][member] = ThingError
    fraiseql.mutation(type("CreateThing", (), namespace))

    with pytest.raises(TypeError) as excinfo:
        _build()

    message = str(excinfo.value)
    assert f"CreateThing has `{member}`, which fraiseql doesn't read" in message
    assert "use `error:`" in message


def test_resolve_method_is_reported() -> None:
    @fraiseql.mutation
    class CreateThing:
        input: ThingInput
        success: ThingSuccess
        error: ThingError

        async def resolve(self, info):
            return None

    with pytest.raises(TypeError) as excinfo:
        _build()

    message = str(excinfo.value)
    assert "CreateThing has `resolve`, which fraiseql doesn't read" in message
    assert "`error:`" in message
    assert "function mutation" in message


def test_unknown_member_is_reported() -> None:
    @fraiseql.mutation
    class CreateThing:
        input: ThingInput
        success: ThingSuccess
        error: ThingError
        sucess_message = "typo"

    with pytest.raises(TypeError, match=r"CreateThing has `sucess_message`"):
        _build()


def test_every_bad_mutation_is_listed_once() -> None:
    @fraiseql.mutation
    class ClearCart:
        success: ThingSuccess

    @fraiseql.mutation
    class CreateThing:
        input: ThingInput
        success: ThingSuccess
        failure: ThingError

    with pytest.raises(TypeError) as excinfo:
        _build()

    message = str(excinfo.value)
    assert "ClearCart has no `input:`" in message
    assert "CreateThing has `failure`" in message


def test_inherited_members_and_private_helpers_build() -> None:
    class ThingMutationBase:
        input: ThingInput
        error: ThingError

    class NormalizeMixin:
        @staticmethod
        def prepare_input(input_data: dict) -> dict:
            return NormalizeMixin._strip(input_data)

        @staticmethod
        def _strip(input_data: dict) -> dict:
            return {key: value.strip() for key, value in input_data.items()}

    @fraiseql.mutation
    class CreateThing(NormalizeMixin, ThingMutationBase):
        """Create a thing."""

        success: ThingSuccess

    _build()


def test_success_only_and_error_only_still_build() -> None:
    @fraiseql.mutation
    class CreateThing:
        input: ThingInput
        success: ThingSuccess

    @fraiseql.mutation
    class DeleteThing:
        input: ThingInput
        error: ThingError

    _build()


@fraiseql.error
class OtherError:
    message: str


def test_union_error_type_is_reported_at_build() -> None:
    # Decorating it raised AttributeError: 'types.UnionType' object has no attribute '__name__'
    @fraiseql.mutation
    class SaveThing:
        input: ThingInput
        success: ThingSuccess
        error: ThingError | OtherError

    with pytest.raises(
        TypeError, match=r"Mutation SaveThing has `error: ThingError \| OtherError`"
    ):
        _build()


def test_union_success_type_is_reported_at_build() -> None:
    @fraiseql.mutation
    class SaveThing:
        input: ThingInput
        success: ThingSuccess | ThingError
        error: ThingError

    with pytest.raises(TypeError, match=r"Mutation SaveThing has `success: "):
        _build()

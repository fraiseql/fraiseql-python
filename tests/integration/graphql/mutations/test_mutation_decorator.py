"""Tests for the @mutation decorator."""

from unittest.mock import Mock

import pytest

import fraiseql
from fraiseql.mutations.decorators import error, success
from fraiseql.mutations.mutation_decorator import MutationDefinition, mutation
from fraiseql.types.fraise_input import fraise_input

pytestmark = pytest.mark.integration


@fraise_input
class SampleInput:
    name: str
    email: str


@fraiseql.type
class User:
    id: str
    name: str
    email: str


@success
class SampleSuccess:
    message: str
    user: User


@error
class SampleError:
    message: str
    code: str = "ERROR"


class TestMutationDefinition:
    """Test MutationDefinition class."""

    def test_create_definition_with_all_types(self) -> None:
        """Test creating a mutation definition with all required types."""

        @mutation
        class CreateUser:
            input: SampleInput
            success: SampleSuccess
            error: SampleError

        definition = CreateUser.__fraiseql_mutation__

        assert isinstance(definition, MutationDefinition)
        assert definition.name == "CreateUser"
        assert definition.function_name == "create_user"
        assert definition.schema == "public"
        assert definition.input_type == SampleInput
        assert definition.success_type == SampleSuccess
        assert definition.error_type == SampleError

    def test_custom_function_name(self) -> None:
        """Test mutation with custom function name."""

        @mutation(function="custom_create_user")
        class CreateUser:
            input: SampleInput
            success: SampleSuccess
            error: SampleError

        definition = CreateUser.__fraiseql_mutation__
        assert definition.function_name == "custom_create_user"

    def test_custom_schema(self) -> None:
        """Test mutation with custom schema."""

        @mutation(schema="mutations")
        class CreateUser:
            input: SampleInput
            success: SampleSuccess
            error: SampleError

        definition = CreateUser.__fraiseql_mutation__
        assert definition.schema == "mutations"

    def test_missing_input_type_stores_none(self) -> None:
        """Test that missing input type stores None (no validation at decoration time)."""

        @mutation
        class BadMutation:
            success: SampleSuccess
            error: SampleError

        definition = BadMutation.__fraiseql_mutation__
        assert definition.input_type is None

    def test_missing_success_type_stores_none(self) -> None:
        """Test that missing success type stores None (no validation at decoration time)."""

        @mutation
        class BadMutation:
            input: SampleInput
            error: SampleError

        definition = BadMutation.__fraiseql_mutation__
        assert definition.success_type is None

    def test_missing_error_type_stores_none(self) -> None:
        """Test that missing error type stores None (no validation at decoration time)."""

        @mutation
        class BadMutation:
            input: SampleInput
            success: SampleSuccess

        definition = BadMutation.__fraiseql_mutation__
        assert definition.error_type is None

    def test_camel_to_snake_conversion(self) -> None:
        """Test CamelCase to snake_case conversion."""
        test_cases = [
            ("CreateUser", "create_user"),
            ("UpdateUserProfile", "update_user_profile"),
            ("DeletePost", "delete_post"),
            ("BulkUpdateOrders", "bulk_update_orders"),
            ("APIKeyGeneration", "api_key_generation"),
        ]

        for camel, expected_snake in test_cases:

            @mutation
            class TestMutation:
                input: SampleInput
                success: SampleSuccess
                error: SampleError

            # Temporarily change the name
            TestMutation.__name__ = camel
            definition = MutationDefinition(TestMutation)
            assert definition.function_name == expected_snake


class TestInputConversion:
    """Test input object to dict conversion."""

    def test_convert_object_with_to_dict(self) -> None:
        """Test converting object with to_dict method."""
        from fraiseql.mutations.mutation_decorator import _to_dict

        obj = Mock()
        obj.to_dict.return_value = {"name": "test", "value": 42}

        result = _to_dict(obj)
        assert result == {"name": "test", "value": 42}

    def test_convert_object_with_dict_attr(self) -> None:
        """Test converting object with __dict__ attribute."""
        from fraiseql.mutations.mutation_decorator import _to_dict

        class TestObj:
            def __init__(self) -> None:
                self.name = "test"
                self.value = 42
                self._private = "hidden"

        result = _to_dict(TestObj())
        assert result == {"name": "test", "value": 42}
        assert "_private" not in result

    def test_convert_dict_object(self) -> None:
        """Test converting dict object."""
        from fraiseql.mutations.mutation_decorator import _to_dict

        data = {"name": "test", "value": 42}
        result = _to_dict(data)
        assert result == data

    def test_convert_unsupported_type_raises_error(self) -> None:
        """Test that unsupported types raise TypeError."""
        from fraiseql.mutations.mutation_decorator import _to_dict

        with pytest.raises(TypeError, match=r"Cannot convert.*to dictionary"):
            _to_dict("string")

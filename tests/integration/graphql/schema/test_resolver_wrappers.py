from typing import Any
from unittest.mock import MagicMock

import pytest
from graphql import GraphQLArgument, GraphQLField, GraphQLResolveInfo

import fraiseql
from fraiseql.gql.resolver_wrappers import wrap_resolver

pytestmark = pytest.mark.integration


class TestWrapResolver:
    """Test suite for wrap_resolver function."""

    @pytest.fixture
    def clear_registry(self) -> None:
        """Clear the schema registry before each test."""
        from fraiseql.gql.schema_builder import SchemaRegistry

        registry = SchemaRegistry.get_instance()
        registry.clear()
        yield
        registry.clear()

    @pytest.fixture
    def sample_input_type(self, clear_registry) -> None:
        """Create a sample input type."""

        @fraiseql.input
        class CreateUserInput:
            name: str
            age: int | None = None

        return CreateUserInput

    @pytest.fixture
    def sample_output_type(self, clear_registry) -> None:
        """Create a sample output type."""

        @fraiseql.type
        class User:
            id: str
            name: str
            age: int | None = None

        return User

    def test_wrap_simple_resolver(self, sample_input_type, sample_output_type) -> None:
        """Test wrapping a simple async resolver."""

        async def create_user(
            info: GraphQLResolveInfo, input: sample_input_type
        ) -> sample_output_type:
            return sample_output_type(id="123", name=input.name, age=input.age)

        # Wrap the resolver
        field = wrap_resolver(create_user)

        # Check that it returns a GraphQLField
        assert isinstance(field, GraphQLField)

        # Check arguments
        assert "input" in field.args
        assert isinstance(field.args["input"], GraphQLArgument)

        # Check that the resolver is wrapped
        assert field.resolve is not None
        assert field.resolve != create_user  # It should be wrapped

    @pytest.mark.asyncio
    async def test_wrapped_resolver_execution(self, sample_input_type, sample_output_type) -> None:
        """Test executing a wrapped resolver."""

        async def create_user(
            info: GraphQLResolveInfo, input: sample_input_type
        ) -> sample_output_type:
            return sample_output_type(id="123", name=input.name, age=input.age or 0)

        field = wrap_resolver(create_user)

        # Mock GraphQLResolveInfo
        mock_info = MagicMock(spec=GraphQLResolveInfo)

        # Execute the wrapped resolver
        result = await field.resolve(None, mock_info, input={"name": "John", "age": 30})  # root

        # Check result
        assert result.id == "123"
        assert result.name == "John"
        assert result.age == 30

    @pytest.mark.asyncio
    async def test_wrapped_resolver_with_missing_optional_field(
        self, sample_input_type, sample_output_type
    ) -> None:
        """Test wrapped resolver with missing optional fields."""

        async def create_user(
            info: GraphQLResolveInfo, input: sample_input_type
        ) -> sample_output_type:
            return sample_output_type(id="456", name=input.name, age=input.age)

        field = wrap_resolver(create_user)

        mock_info = MagicMock(spec=GraphQLResolveInfo)

        # Execute without optional age field
        result = await field.resolve(None, mock_info, input={"name": "Jane"})

        assert result.id == "456"
        assert result.name == "Jane"
        assert result.age is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("spelling", ["pipe", "optional"])
    async def test_optional_input_argument_is_coerced(
        self, sample_input_type, sample_output_type, spelling: str
    ) -> None:
        """``Input | None`` and ``Optional[Input]`` coerce a dict alike (3.13 and 3.14)."""
        from typing import Optional

        annotation = sample_input_type | None if spelling == "pipe" else Optional[sample_input_type]
        received: list[Any] = []

        async def create_user(info: GraphQLResolveInfo, input: annotation) -> sample_output_type:  # type: ignore[valid-type]
            received.append(input)
            return sample_output_type(id="1", name=input.name, age=input.age)

        field = wrap_resolver(create_user)
        await field.resolve(None, MagicMock(spec=GraphQLResolveInfo), input={"name": "Ann"})

        assert isinstance(received[0], sample_input_type)

    def test_wrap_resolver_with_no_arguments(self) -> None:
        """Test wrapping a resolver with no arguments except info."""

        @fraiseql.type
        class Status:
            online: bool
            message: str

        async def get_status(info: GraphQLResolveInfo) -> Status:
            return Status(online=True, message="All systems operational")

        field = wrap_resolver(get_status)

        # Check no arguments except info
        assert len(field.args) == 0

    def test_wrap_resolver_with_multiple_arguments(self, clear_registry) -> None:
        """Test wrapping a resolver with multiple arguments."""

        @fraiseql.input
        class FilterInput:
            category: str

        @fraiseql.type
        class Product:
            id: str
            name: str

        async def search_products(
            info: GraphQLResolveInfo, query: str, filter: FilterInput, limit: int | None = None
        ) -> list[Product]:
            return []

        field = wrap_resolver(search_products)

        # Check all arguments are present
        assert "query" in field.args
        assert "filter" in field.args
        assert "limit" in field.args
        assert len(field.args) == 3

    @pytest.mark.asyncio
    async def test_wrapped_resolver_error_handling(self, sample_input_type) -> None:
        """Test error handling in wrapped resolver."""

        async def failing_resolver(info: GraphQLResolveInfo, input: sample_input_type) -> Any:
            msg = "Something went wrong"
            raise ValueError(msg)

        field = wrap_resolver(failing_resolver)

        mock_info = MagicMock(spec=GraphQLResolveInfo)

        # The wrapped resolver should propagate the error
        with pytest.raises(ValueError, match="Something went wrong"):
            await field.resolve(None, mock_info, input={"name": "Test"})

    @pytest.mark.asyncio
    async def test_input_coercion(self, sample_input_type, sample_output_type) -> None:
        """Test that input is properly coerced to the input type."""
        received_input = None

        async def create_user(
            info: GraphQLResolveInfo, input: sample_input_type
        ) -> sample_output_type:
            nonlocal received_input
            received_input = input
            return sample_output_type(id="1", name=input.name)

        field = wrap_resolver(create_user)

        mock_info = MagicMock(spec=GraphQLResolveInfo)

        await field.resolve(None, mock_info, input={"name": "Test User", "age": 25})

        # Check that input was coerced to the correct type
        assert isinstance(received_input, sample_input_type)
        assert received_input.name == "Test User"
        assert received_input.age == 25

    def test_wrap_resolver_with_union_return_type(self, clear_registry) -> None:
        """Test wrapping a resolver that returns a union type."""

        @fraiseql.success
        class CreateSuccess:
            id: str
            message: str

        @fraiseql.error
        class CreateError:
            message: str
            code: int

        # Use the result decorator to create a proper union
        CreateResult = fraiseql.result(CreateSuccess, CreateError)

        async def create_something(info: GraphQLResolveInfo, name: str) -> CreateResult:
            if name == "error":
                return CreateError(message="Failed", code=400)
            return CreateSuccess(id="123", message="Created")

        field = wrap_resolver(create_something)

        # Check the field was created
        assert isinstance(field, GraphQLField)
        assert "name" in field.args

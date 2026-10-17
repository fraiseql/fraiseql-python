"""Integration tests for empty string validation in FraiseQL input scenarios.

This module tests that the empty string validation works correctly when FraiseQL
input types are used in realistic scenarios, including complex nested types
and real-world use cases.
"""

import pytest

from fraiseql.types.fraise_input import fraise_input

pytestmark = pytest.mark.integration


@fraise_input
class CreateUserInput:
    name: str
    email: str
    bio: str | None = None


@pytest.mark.integration
def test_nested_input_validation() -> None:
    """Test that validation works in nested input scenarios."""

    @fraise_input
    class AddressInput:
        street_name: str
        city: str
        postal_code: str | None = None

    @fraise_input
    class CreateCustomerInput:
        name: str
        email: str
        address: AddressInput

    # Test validation on nested input
    with pytest.raises(ValueError, match="Field 'street_name' cannot be empty"):
        address = AddressInput(street_name="", city="Valid City")

    # Test that valid nested input works
    address = AddressInput(street_name="123 Main St", city="Valid City")
    customer = CreateCustomerInput(name="John Doe", email="john@example.com", address=address)
    assert customer.address.street_name == "123 Main St"


@pytest.mark.integration
def test_list_of_inputs_validation() -> None:
    """Test validation works when using lists of input objects."""

    @fraise_input
    class TagInput:
        name: str
        description: str | None = None

    @fraise_input
    class CreatePostInput:
        title: str
        content: str
        tags: list[TagInput]

    # Individual tag validation should work
    with pytest.raises(ValueError, match="Field 'name' cannot be empty"):
        TagInput(name="")

    # Valid tags should work in lists
    tags = [
        TagInput(name="python", description="Python programming"),
        TagInput(name="graphql", description="GraphQL API"),
    ]

    post = CreatePostInput(title="My Post", content="Post content", tags=tags)
    assert len(post.tags) == 2
    assert post.tags[0].name == "python"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_async_context_validation() -> None:
    """Test that validation works in async contexts."""

    async def create_user_async(input_data: dict) -> CreateUserInput:
        # This simulates how GraphQL resolvers might construct input objects
        return CreateUserInput(**input_data)

    # Empty string should fail even in async context
    with pytest.raises(ValueError, match="Field 'name' cannot be empty"):
        await create_user_async({"name": "", "email": "valid@example.com"})

    # Valid data should work in async context
    user_input = await create_user_async({"name": "Valid Name", "email": "valid@example.com"})
    assert user_input.name == "Valid Name"


@pytest.mark.integration
def test_empty_string_validation_matches_issue_requirements() -> None:
    """Test that validation matches the exact requirements from the GitHub issue."""

    @fraise_input
    class CreateOrganizationalUnitInput:
        name: str
        organizational_unit_level_id: str  # Using str for simplicity in test

    # Test case from the issue: empty string should be rejected
    with pytest.raises(ValueError, match="Field 'name' cannot be empty"):
        CreateOrganizationalUnitInput(
            name="", organizational_unit_level_id="bbd74f0c-911f-48a9-94f6-af46f8ae75de"
        )

    # Test case: whitespace should be rejected
    with pytest.raises(ValueError, match="Field 'name' cannot be empty"):
        CreateOrganizationalUnitInput(
            name="   ", organizational_unit_level_id="bbd74f0c-911f-48a9-94f6-af46f8ae75de"
        )

    # Test case: valid string should work
    instance = CreateOrganizationalUnitInput(
        name="valid", organizational_unit_level_id="bbd74f0c-911f-48a9-94f6-af46f8ae75de"
    )
    assert instance.name == "valid"


@pytest.mark.integration
def test_validation_error_format_matches_graphql_standards() -> None:
    """Test that error messages follow GraphQL error formatting expectations."""

    @fraise_input
    class TestInput:
        first_name: str
        last_name: str

    try:
        TestInput(first_name="", last_name="valid")
        pytest.fail("Expected ValueError to be raised")
    except ValueError as e:
        error_message = str(e)

        # Error should clearly identify the field
        assert "first_name" in error_message
        assert "cannot be empty" in error_message

        # Error message should be suitable for GraphQL error response
        assert len(error_message) < 100  # Keep it concise
        assert not error_message.startswith("Error:")  # Clean message

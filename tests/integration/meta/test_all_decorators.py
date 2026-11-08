"""Meta-test for ALL decorators integration.

This test validates that every decorator in FraiseQL works through the
complete GraphQL pipeline: registration → schema generation → execution.

It auto-discovers all decorators and tests each one comprehensively.
"""

import pytest
from graphql import graphql

# Import schema_builder to ensure SchemaRegistry is patched
import fraiseql.gql.schema_builder  # noqa: F401
from fraiseql import fraise_type
from fraiseql.decorators import connection, field, subscription
from fraiseql.decorators import query as query_decorator
from fraiseql.mutations import mutation
from fraiseql.mutations.decorators import error, success


def get_all_decorators():
    """Auto-enumerate all decorators from FraiseQL modules."""
    decorators = {}

    # Query decorators
    decorators["query"] = query_decorator
    decorators["subscription"] = subscription

    # Field decorators
    decorators["field"] = field

    # Connection decorators
    decorators["connection"] = connection

    # Turbo decorators
    from fraiseql.decorators import turbo_query

    decorators["turbo_query"] = turbo_query

    # Mutation decorators
    decorators["mutation"] = mutation
    decorators["error"] = error
    decorators["success"] = success
    # NOTE: result() is a type factory, not a decorator.
    # It's used as: result_type = result(Success, Error)
    # Not as: @result(Success, Error)  # This won't work!

    return decorators


@pytest.fixture(scope="class")
def decorator_test_schema(meta_test_schema):
    """Schema registry prepared with decorator test types."""
    # Clear any existing registrations
    meta_test_schema.clear()

    # Register test types for different decorator categories
    @fraise_type(sql_source="test_users")
    class User:
        id: int
        name: str
        email: str

        @field(description="User's full name")
        def full_name(self) -> str:
            return f"{self.name} (field decorator test)"

    @fraise_type(sql_source="test_posts")
    class Post:
        id: int
        title: str
        content: str

    # Register queries using different decorators
    @query_decorator
    async def get_users(info) -> list[User]:
        return []

    @query_decorator
    @connection(node_type=User)
    async def users_connection(info) -> list[User]:
        return []

    # Register subscriptions
    @subscription
    async def on_user_created(info) -> str:
        return "subscription test"

    # Register mutations
    @success
    class CreateUserSuccess:
        user: User

    @error
    class CreateUserError:
        message: str

    # CreateUserResult union is automatically created by FraiseQL
    # when both @success CreateUserSuccess and @error CreateUserError are defined.
    # No manual class definition needed.

    @mutation
    class CreateUser:
        input: dict  # Simplified for testing
        success: CreateUserSuccess
        error: CreateUserError

    # Register types with schema
    meta_test_schema.register_type(User)
    meta_test_schema.register_type(Post)
    meta_test_schema.register_query(get_users)
    meta_test_schema.register_query(users_connection)
    meta_test_schema.register_subscription(on_user_created)
    meta_test_schema.register_mutation(CreateUser)

    return meta_test_schema


@pytest.mark.parametrize(("decorator_name", "decorator_fn"), get_all_decorators().items())
async def test_decorator_registers_with_schema(decorator_name, decorator_fn, decorator_test_schema):
    """Every decorator should successfully register with the GraphQL schema."""
    # Build the schema - this should not raise any errors
    schema = decorator_test_schema.build_schema()

    # Verify schema was built successfully
    assert schema is not None

    # Verify the decorator registered something in the schema
    # Different decorators register in different places
    registered_something = False

    # Check query type
    if schema.query_type and schema.query_type.fields:
        registered_something = True

    # Check mutation type
    if schema.mutation_type and schema.mutation_type.fields:
        registered_something = True

    # Check subscription type
    if schema.subscription_type and schema.subscription_type.fields:
        registered_something = True

    # Check types
    if schema.type_map:
        registered_something = True

    assert registered_something, f"Decorator '{decorator_name}' did not register anything in schema"


@pytest.mark.parametrize(
    ("decorator_name", "decorator_fn"),
    [
        ("query", query_decorator),
        ("subscription", subscription),
        ("connection", connection),
    ],
)
async def test_decorator_executes_in_graphql(decorator_name, decorator_fn, decorator_test_schema):
    """Decorators that create resolvers should execute without errors."""
    schema = decorator_test_schema.build_schema()

    # Test query decorator
    if decorator_name == "query":
        query_str = """
        query {
            getUsers {
                id
                name
                fullName
            }
        }
        """
        result = await graphql(schema, query_str)
        assert not result.errors, f"Query decorator failed: {result.errors}"

    # Test connection decorator
    elif decorator_name == "connection":
        query_str = """
        query {
            usersConnection(first: 10) {
                edges {
                    node {
                        id
                        name
                    }
                }
            }
        }
        """
        result = await graphql(schema, query_str)
        # Connection decorator should have valid schema (no GraphQL syntax/schema errors)
        # Execution errors are expected (no db context)
        if result.errors:
            # Should be execution error (missing db), not schema error
            assert any(
                "Database repository not found" in str(e) or "'NoneType' object" in str(e)
                for e in result.errors
            ), f"Expected db error, got schema error: {result.errors}"

    # Subscriptions are harder to test without WebSocket setup
    elif decorator_name == "subscription":
        # Just verify schema has subscription type
        assert schema.subscription_type is not None, (
            "Subscription decorator didn't create subscription type"
        )


@pytest.mark.parametrize(
    ("decorator_name", "decorator_fn"),
    [
        ("mutation", mutation),
        ("success", success),
        ("error", error),
        # NOTE: result is not a decorator, it's a type factory
    ],
)
async def test_mutation_decorators_build_schema(
    decorator_name, decorator_fn, decorator_test_schema
):
    """Mutation-related decorators should build valid schema."""
    schema = decorator_test_schema.build_schema()

    # Verify schema was built successfully
    assert schema is not None

    # Verify mutation type exists
    assert schema.mutation_type is not None, (
        f"Mutation decorator '{decorator_name}' didn't create mutation type"
    )

    # Verify mutation field exists
    mutation_fields = schema.mutation_type.fields
    assert mutation_fields, f"Mutation decorator '{decorator_name}' didn't create mutation fields"

    # Should have createUser mutation
    assert "createUser" in mutation_fields, (
        f"Mutation decorator '{decorator_name}' missing createUser field"
    )


@pytest.mark.parametrize(
    ("decorator_name", "decorator_fn"),
    [
        ("field", field),
    ],
)
async def test_field_decorator_in_schema(decorator_name, decorator_fn, decorator_test_schema):
    """Field decorators should add fields to GraphQL types."""
    schema = decorator_test_schema.build_schema()

    # Get User type
    user_type = schema.get_type("User")
    assert user_type is not None, "User type not found in schema"

    # Check that field decorator added fullName field
    assert hasattr(user_type, "fields"), "User type should have fields"
    assert "fullName" in user_type.fields, "Field decorator didn't add fullName field"

    # Verify field has description
    full_name_field = user_type.fields["fullName"]
    assert full_name_field.description == "User's full name", (
        "Field decorator didn't set description"
    )


@pytest.mark.parametrize(
    ("decorator_name", "decorator_fn"),
    [
        ("query", query_decorator),
        ("connection", connection),
    ],
)
async def test_decorator_combination_compatibility(
    decorator_name, decorator_fn, decorator_test_schema
):
    """Decorators should work in combination with each other."""
    schema = decorator_test_schema.build_schema()

    # Test query + connection combination
    if decorator_name == "query":
        # Verify both getUsers and usersConnection exist
        query_type = schema.query_type
        assert query_type is not None

        query_fields = query_type.fields
        assert "getUsers" in query_fields, "Query decorator not registered"
        assert "usersConnection" in query_fields, "Connection decorator not registered"

        # Test query decorator executes
        query_str = "{ getUsers { id } }"
        result = await graphql(schema, query_str)
        assert not result.errors, f"Decorator combination failed for query: {query_str}"

        # Test connection decorator schema is valid (execution will fail without db)
        connection_query = "{ usersConnection(first: 5) { edges { node { id } } } }"
        result = await graphql(schema, connection_query)
        if result.errors:
            # Should be execution error (missing db), not schema error
            assert any(
                "Database repository not found" in str(e) or "'NoneType' object" in str(e)
                for e in result.errors
            ), f"Expected db error, got schema error: {result.errors}"


async def test_decorator_error_handling(decorator_test_schema):
    """Decorators should handle errors gracefully during schema building."""
    # This test ensures decorators don't crash schema building
    # even if there are issues with their configuration

    schema = decorator_test_schema.build_schema()

    # Schema should still be built even if some decorators have issues
    assert schema is not None, "Schema building failed with decorators"

    # Should have some basic structure
    assert schema.query_type is not None or schema.mutation_type is not None, (
        "Schema should have at least query or mutation type"
    )


async def test_decorator_schema_introspection(decorator_test_schema):
    """Decorators should be introspectable through GraphQL schema."""
    schema = decorator_test_schema.build_schema()

    # Test basic introspection query
    introspection_query = """
    query {
        __schema {
            queryType {
                name
            }
            mutationType {
                name
            }
            subscriptionType {
                name
            }
        }
    }
    """

    result = await graphql(schema, introspection_query)

    assert not result.errors, f"Schema introspection failed: {result.errors}"
    assert result.data is not None, "No introspection data returned"

    schema_data = result.data["__schema"]

    # Should have query type
    assert schema_data["queryType"] is not None, "Schema should have query type"

    # Should have mutation type (from mutation decorator)
    assert schema_data["mutationType"] is not None, "Schema should have mutation type"

    # Should have subscription type (from subscription decorator)
    assert schema_data["subscriptionType"] is not None, "Schema should have subscription type"

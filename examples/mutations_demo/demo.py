"""Working demo of PostgreSQL function-based mutations in FraiseQL.

Before running:
1. Start PostgreSQL: docker-compose up -d
2. Install dependencies: pip install psycopg[async]
3. Run: python examples/mutations_demo/demo.py
"""

import asyncio
from uuid import UUID

import psycopg

import fraiseql
from fraiseql.types import ID
from fraiseql import CQRSRepository

# Database connection settings
DB_CONFIG = {
    "host": "localhost",
    "port": 5434,  # Using 5434 to avoid conflict
    "dbname": "fraiseql_demo",
    "user": "fraiseql",
    "password": "fraiseql",
}


# Define input types
@fraiseql.input
class CreateUserInput:
    name: str
    email: str
    role: str = "user"


@fraiseql.input
class UpdateUserInput:
    id: ID
    name: str | None = None
    email: str | None = None
    role: str | None = None


@fraiseql.input
class DeleteUserInput:
    id: ID


# Define the User type
@fraiseql.type
class User:
    id: ID
    name: str
    email: str
    role: str
    created_at: str


# Define Success/Error types for mutations
@fraiseql.success
class CreateUserSuccess:
    message: str
    user: User


@fraiseql.error
class CreateUserError:
    message: str
    conflict_user: User | None = None
    suggested_email: str | None = None


@fraiseql.success
class UpdateUserSuccess:
    message: str
    user: User
    updated_fields: list[str] | None = None  # Make it optional


@fraiseql.error
class UpdateUserError:
    message: str
    not_found: bool = False
    validation_errors: dict[str, str] | None = None


@fraiseql.success
class DeleteUserSuccess:
    message: str
    user: User  # The deleted user data


@fraiseql.error
class DeleteUserError:
    message: str
    not_found: bool = False


# Define mutations using the @mutation decorator
@fraiseql.mutation(schema="graphql")
class CreateUser:
    """Create a new user account."""

    input: CreateUserInput
    success: CreateUserSuccess
    error: CreateUserError


# A custom SQL function name. name= names the GraphQL field after the class
# (without it, fraiseql 1.x keeps the field named after the function,
# updateUserAccount, and warns).
@fraiseql.mutation(function="update_user_account", schema="graphql", name="updateUser")
class UpdateUser:
    """Update an existing user account."""

    input: UpdateUserInput
    success: UpdateUserSuccess
    error: UpdateUserError


@fraiseql.mutation(schema="graphql")
class DeleteUser:
    """Delete a user account."""

    input: DeleteUserInput
    success: DeleteUserSuccess
    error: DeleteUserError


# Define a query root for completeness
@fraiseql.type
class QueryRoot:
    hello: str = fraiseql.fraise_field(default="Hello from FraiseQL!", purpose="output")


async def demo():
    """Run the mutation demo."""
    # Connect to database
    async with await psycopg.AsyncConnection.connect(**DB_CONFIG) as conn:
        db = CQRSRepository(conn)

        # Mock GraphQL context
        class MockInfo:
            def __init__(self, db):
                self.context = {"db": db}

        info = MockInfo(db)

        # 1. Create a new user
        create_input = CreateUserInput(
            name="John Doe",
            email="john@example.com",
            role="admin",
        )

        result = await CreateUser.__fraiseql_resolver__(info, create_input)

        if isinstance(result, CreateUserSuccess):
            user_id = result.user.id
        else:
            if result.conflict_user:
                pass
            return

        # 2. Try to create the same user again (should fail)
        result2 = await CreateUser.__fraiseql_resolver__(info, create_input)

        if isinstance(result2, CreateUserError) and result2.conflict_user:
            pass

        # 3. Update the user
        update_input = UpdateUserInput(id=user_id, name="Jane Doe", role="superadmin")

        update_result = await UpdateUser.__fraiseql_resolver__(info, update_input)

        if isinstance(update_result, UpdateUserSuccess):
            if update_result.updated_fields:
                pass
        else:
            pass

        # 4. Try to update non-existent user
        fake_id = UUID("00000000-0000-0000-0000-000000000000")
        bad_update = UpdateUserInput(id=fake_id, name="Ghost")

        bad_result = await UpdateUser.__fraiseql_resolver__(info, bad_update)

        if isinstance(bad_result, UpdateUserError):
            pass

        # 5. Delete the user
        delete_input = DeleteUserInput(id=user_id)

        delete_result = await DeleteUser.__fraiseql_resolver__(info, delete_input)

        if isinstance(delete_result, DeleteUserSuccess):
            pass
        else:
            pass

        # 6. Build and show GraphQL schema
        schema = fraiseql.build_fraiseql_schema(
            query_types=[QueryRoot],
            mutation_resolvers=[CreateUser, UpdateUser, DeleteUser],
        )

        # Show mutation details
        schema.mutation_type.fields["createUser"]


if __name__ == "__main__":
    asyncio.run(demo())

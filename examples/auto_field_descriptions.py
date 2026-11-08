"""Demonstration of automatic field description extraction in FraiseQL.

This example showcases the new automatic field description feature that extracts
descriptions from multiple sources to enhance GraphQL schema documentation.
"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import fraiseql
from fraiseql.types import ID


# Example 1: Docstring-based field descriptions
@fraiseql.fraise_type
@dataclass
class User:
    """User account with authentication capabilities.

    Fields:
        id: Unique user identifier
        username: Username for authentication
        email: User's email address for communication
        full_name: Complete display name
        is_active: Whether the account is currently active
    """
    id: ID
    username: str
    email: str
    full_name: str
    is_active: bool = True


# Example 2: Mixed sources (docstring + explicit descriptions)
@fraiseql.fraise_type
@dataclass
class Product:
    """Product catalog item.

    Fields:
        id: Product identifier
        name: Product display name
        price: Price in USD
    """
    id: ID
    name: str
    price: float
    description: str = fraiseql.fraise_field(description="Detailed product description")
    stock_count: int = fraiseql.fraise_field(description="Current inventory count")


# Example 3: Annotated type hints (when supported)
@fraiseql.fraise_type
@dataclass
class Order:
    """Customer order information."""
    id: Annotated[UUID, "Order identifier"]
    customer_id: Annotated[UUID, "Customer who placed the order"]
    total_amount: Annotated[float, "Total order value in USD"]
    status: str = "pending"


# Example 4: Input types with automatic descriptions
@fraiseql.fraise_input
@dataclass
class CreateUserInput:
    """Input for creating a new user account.

    Args:
        username: Desired username (must be unique)
        email: User's email address
        full_name: User's display name
        password: Account password (will be hashed)
    """
    username: str
    email: str
    full_name: str
    password: str


# Example 5: Complex nested types
@fraiseql.fraise_type
@dataclass
class Address:
    """Physical address information.

    Fields:
        street: Street address
        city: City name
        state: State or province
        postal_code: ZIP or postal code
        country: Country name
    """
    street: str
    city: str
    state: str
    postal_code: str
    country: str


@fraiseql.fraise_type
@dataclass
class Customer:
    """Customer profile with contact information.

    Fields:
        id: Customer identifier
        personal_info: Basic customer information
        shipping_address: Primary shipping address
        billing_address: Billing address (if different from shipping)
    """
    id: ID
    personal_info: User
    shipping_address: Address
    billing_address: Address | None = None


# GraphQL queries using the types with auto-generated descriptions
@fraiseql.query
async def get_user(info, id: ID) -> User | None:
    """Retrieve a user by their unique identifier."""
    # In a real app, this would query your database
    return User(
        id=id,
        username="john_doe",
        email="john@example.com",
        full_name="John Doe",
        is_active=True
    )


@fraiseql.query
async def list_products(info) -> list[Product]:
    """Get all available products in the catalog."""
    # In a real app, this would query your database
    return [
        Product(
            id=UUID("123e4567-e89b-12d3-a456-426614174000"),
            name="Sample Product",
            price=29.99,
            description="A great sample product",
            stock_count=100
        )
    ]


@fraiseql.mutation
async def create_user(info, input: CreateUserInput) -> User:
    """Create a new user account with the provided information."""
    # In a real app, this would validate and save to database
    return User(
        id=UUID("123e4567-e89b-12d3-a456-426614174001"),
        username=input.username,
        email=input.email,
        full_name=input.full_name,
        is_active=True
    )


if __name__ == "__main__":
    # Build the GraphQL schema; the descriptions are part of it
    schema = fraiseql.build_fraiseql_schema(
        query_types=[get_user, list_products],
        mutation_resolvers=[create_user],
    )

    # The GraphQL schema now includes automatic descriptions for all fields:
    # - Type descriptions from class docstrings
    # - Field descriptions from docstring Fields: sections
    # - Explicit field descriptions from fraise_field() calls
    print("User:", schema.type_map["User"].description.splitlines()[0])
    print("User.email:", schema.type_map["User"].fields["email"].description)
    print("Product.description:", schema.type_map["Product"].fields["description"].description)

    # To serve it, build the app with the same types and resolvers:
    #   from fraiseql.fastapi import create_fraiseql_app
    #   app = create_fraiseql_app(
    #       database_url="postgresql://localhost/mydb",
    #       queries=[get_user, list_products],
    #       mutations=[create_user],
    #   )
    # and run it with uvicorn; the descriptions show in GraphiQL and Apollo Studio.

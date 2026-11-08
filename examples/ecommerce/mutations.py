"""E-commerce mutations for FraiseQL example."""

import fraiseql
from fraiseql.types import ID

from .models import (
    AddressError,
    AddressSuccess,
    AddToCartInput,
    AuthError,
    # Success/Error types
    AuthSuccess,
    CartError,
    CartSuccess,
    CheckoutInput,
    CreateAddressInput,
    CreateReviewInput,
    CreateReviewSuccess,
    LoginInput,
    OrderError,
    OrderSuccess,
    # Inputs
    RegisterInput,
    ReviewError,
    UpdateCartItemInput,
)

# Inputs used only by these mutations


@fraiseql.input
class ClearCartInput:
    """Clear cart input."""

    cart_id: ID


@fraiseql.input
class CancelOrderInput:
    """Cancel order input."""

    order_id: ID
    reason: str | None = None


@fraiseql.input
class UpdateAddressInput:
    """Update address input."""

    address_id: ID
    label: str | None = None
    street1: str | None = None
    street2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    is_default: bool | None = None


@fraiseql.input
class DeleteAddressInput:
    """Delete address input."""

    address_id: ID


# Authentication mutations


@fraiseql.mutation
class Register:
    """Register a new user account."""

    input: RegisterInput
    success: AuthSuccess
    error: AuthError


@fraiseql.mutation
class Login:
    """Login to existing account."""

    input: LoginInput
    success: AuthSuccess
    error: AuthError


# Cart mutations


@fraiseql.mutation
class AddToCart:
    """Add product to shopping cart."""

    input: AddToCartInput
    success: CartSuccess
    error: CartError


@fraiseql.mutation
class UpdateCartItem:
    """Update quantity of cart item."""

    input: UpdateCartItemInput
    success: CartSuccess
    error: CartError


@fraiseql.mutation
class RemoveFromCart:
    """Remove item from cart."""

    input: UpdateCartItemInput  # Only need cart_item_id
    success: CartSuccess
    error: CartError


@fraiseql.mutation
class ClearCart:
    """Clear all items from cart."""

    input: ClearCartInput
    success: CartSuccess
    error: CartError


# Order mutations


@fraiseql.mutation
class Checkout:
    """Complete checkout and create order."""

    input: CheckoutInput
    success: OrderSuccess
    error: OrderError


@fraiseql.mutation
class CancelOrder:
    """Cancel an order."""

    input: CancelOrderInput
    success: OrderSuccess
    error: OrderError


# Address mutations


@fraiseql.mutation
class CreateAddress:
    """Create a new address."""

    input: CreateAddressInput
    success: AddressSuccess
    error: AddressError


@fraiseql.mutation
class UpdateAddress:
    """Update existing address."""

    input: UpdateAddressInput
    success: AddressSuccess
    error: AddressError


@fraiseql.mutation
class DeleteAddress:
    """Delete an address."""

    input: DeleteAddressInput
    success: AddressSuccess
    error: AddressError


# Review mutations


@fraiseql.mutation
class CreateReview:
    """Create a product review."""

    input: CreateReviewInput
    success: CreateReviewSuccess
    error: ReviewError

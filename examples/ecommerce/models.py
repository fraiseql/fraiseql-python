"""E-commerce data models for FraiseQL example."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

import fraiseql
from fraiseql.types import ID
from fraiseql import fraise_field


@fraiseql.enum
class OrderStatus(Enum):
    """Order status enumeration."""

    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


@fraiseql.enum
class PaymentStatus(Enum):
    """Payment status enumeration."""

    PENDING = "pending"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"
    REFUNDED = "refunded"


@fraiseql.enum
class ProductCategory(Enum):
    """Product categories."""

    ELECTRONICS = "electronics"
    CLOTHING = "clothing"
    BOOKS = "books"
    HOME = "home"
    SPORTS = "sports"
    TOYS = "toys"
    FOOD = "food"
    OTHER = "other"


@fraiseql.type
class User:
    """E-commerce user account."""

    id: ID
    email: str = fraise_field(description="User's email address")
    name: str = fraise_field(description="Full name")
    phone: str | None = fraise_field(description="Phone number")
    is_active: bool = fraise_field(default=True, description="Account active status")
    is_verified: bool = fraise_field(default=False, description="Email verified")
    created_at: datetime = fraise_field(description="Account creation timestamp")
    updated_at: datetime = fraise_field(description="Last update timestamp")


@fraiseql.type
class Address:
    """Shipping/billing address."""

    id: ID
    user_id: ID = fraise_field(description="User who owns this address")
    label: str = fraise_field(description="Address label (Home, Work, etc)")
    street1: str = fraise_field(description="Street address line 1")
    street2: str | None = fraise_field(description="Street address line 2")
    city: str = fraise_field(description="City")
    state: str = fraise_field(description="State/Province")
    postal_code: str = fraise_field(description="ZIP/Postal code")
    country: str = fraise_field(default="US", description="Country code")
    is_default: bool = fraise_field(default=False, description="Default address")
    created_at: datetime


@fraiseql.type
class Product:
    """Product in the catalog."""

    id: ID
    sku: str = fraise_field(description="Stock keeping unit")
    name: str = fraise_field(description="Product name")
    description: str = fraise_field(description="Product description")
    category: ProductCategory = fraise_field(description="Product category")
    price: Decimal = fraise_field(description="Current price")
    compare_at_price: Decimal | None = fraise_field(description="Original price")
    cost: Decimal | None = fraise_field(description="Cost to business")
    inventory_count: int = fraise_field(default=0, description="Available inventory")
    is_active: bool = fraise_field(default=True, description="Available for purchase")
    weight_grams: int | None = fraise_field(description="Weight in grams")
    images: list[str] = fraise_field(default_factory=list, description="Product image URLs")
    tags: list[str] = fraise_field(default_factory=list, description="Product tags")
    created_at: datetime
    updated_at: datetime


@fraiseql.type
class Cart:
    """Shopping cart."""

    id: ID
    user_id: ID | None = fraise_field(description="User ID if logged in")
    session_id: str | None = fraise_field(description="Session ID for guests")
    items_count: int = fraise_field(default=0, description="Number of items")
    subtotal: Decimal = fraise_field(description="Subtotal before tax/shipping")
    expires_at: datetime = fraise_field(description="Cart expiration time")
    created_at: datetime
    updated_at: datetime


@fraiseql.type
class CartItem:
    """Item in shopping cart."""

    id: ID
    cart_id: ID = fraise_field(description="Cart this item belongs to")
    product_id: ID = fraise_field(description="Product being purchased")
    quantity: int = fraise_field(description="Quantity to purchase")
    price: Decimal = fraise_field(description="Price at time of adding")
    created_at: datetime
    updated_at: datetime


@fraiseql.type
class Order:
    """Customer order."""

    id: ID
    order_number: str = fraise_field(description="Human-readable order number")
    user_id: ID = fraise_field(description="Customer who placed order")
    status: OrderStatus = fraise_field(description="Current order status")
    payment_status: PaymentStatus = fraise_field(description="Payment status")

    # Addresses
    shipping_address_id: ID = fraise_field(description="Shipping address")
    billing_address_id: ID = fraise_field(description="Billing address")

    # Amounts
    subtotal: Decimal = fraise_field(description="Subtotal before tax/shipping")
    tax_amount: Decimal = fraise_field(description="Tax amount")
    shipping_amount: Decimal = fraise_field(description="Shipping cost")
    discount_amount: Decimal = fraise_field(default=Decimal(0), description="Discount applied")
    total: Decimal = fraise_field(description="Total amount")

    # Tracking
    tracking_number: str | None = fraise_field(description="Shipping tracking number")
    notes: str | None = fraise_field(description="Order notes")

    # Timestamps
    placed_at: datetime = fraise_field(description="When order was placed")
    shipped_at: datetime | None = fraise_field(description="When order shipped")
    delivered_at: datetime | None = fraise_field(description="When order delivered")
    cancelled_at: datetime | None = fraise_field(description="When order cancelled")


@fraiseql.type
class OrderItem:
    """Item in an order."""

    id: ID
    order_id: ID = fraise_field(description="Order this item belongs to")
    product_id: ID = fraise_field(description="Product ordered")
    quantity: int = fraise_field(description="Quantity ordered")
    price: Decimal = fraise_field(description="Price per unit at order time")
    total: Decimal = fraise_field(description="Line total (price * quantity)")
    created_at: datetime


@fraiseql.type
class Review:
    """Product review."""

    id: ID
    product_id: ID = fraise_field(description="Product being reviewed")
    user_id: ID = fraise_field(description="User who wrote review")
    order_id: ID | None = fraise_field(description="Associated order")
    rating: int = fraise_field(description="Rating 1-5")
    title: str = fraise_field(description="Review title")
    comment: str = fraise_field(description="Review text")
    is_verified: bool = fraise_field(default=False, description="Verified purchase")
    helpful_count: int = fraise_field(default=0, description="Number of helpful votes")
    created_at: datetime
    updated_at: datetime


@fraiseql.type
class Coupon:
    """Discount coupon."""

    id: ID
    code: str = fraise_field(description="Coupon code")
    description: str = fraise_field(description="Coupon description")
    discount_type: str = fraise_field(description="percentage or fixed")
    discount_value: Decimal = fraise_field(description="Discount amount or percentage")
    minimum_amount: Decimal | None = fraise_field(description="Minimum order amount")
    usage_limit: int | None = fraise_field(description="Total usage limit")
    usage_count: int = fraise_field(default=0, description="Times used")
    is_active: bool = fraise_field(default=True, description="Currently active")
    valid_from: datetime = fraise_field(description="Valid from date")
    valid_until: datetime | None = fraise_field(description="Expiration date")
    created_at: datetime


@fraiseql.type
class WishlistItem:
    """User's wishlist item."""

    id: ID
    user_id: ID = fraise_field(description="User who added item")
    product_id: ID = fraise_field(description="Product in wishlist")
    added_at: datetime = fraise_field(description="When added to wishlist")


# Input types for mutations


@fraiseql.input
class RegisterInput:
    """User registration input."""

    email: str
    password: str
    name: str
    phone: str | None = None


@fraiseql.input
class LoginInput:
    """User login input."""

    email: str
    password: str


@fraiseql.input
class AddToCartInput:
    """Add item to cart input."""

    product_id: ID
    quantity: int = 1


@fraiseql.input
class UpdateCartItemInput:
    """Update cart item input."""

    cart_item_id: ID
    quantity: int


@fraiseql.input
class CheckoutInput:
    """Checkout input."""

    shipping_address_id: ID
    billing_address_id: ID | None = None  # Use shipping if not provided
    coupon_code: str | None = None
    notes: str | None = None


@fraiseql.input
class CreateAddressInput:
    """Create address input."""

    label: str
    street1: str
    street2: str | None = None
    city: str
    state: str
    postal_code: str
    country: str = "US"
    is_default: bool = False


@fraiseql.input
class CreateReviewInput:
    """Create review input."""

    product_id: ID
    rating: int  # 1-5
    title: str
    comment: str


@fraiseql.input
class ProductFilterInput:
    """Product search filters."""

    category: ProductCategory | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    in_stock: bool | None = None
    search_term: str | None = None
    tags: list[str | None] = None


# Success/Error types for mutations


@fraiseql.success
class AuthSuccess:
    """Successful authentication."""

    user: User
    token: str
    message: str = "Authentication successful"


@fraiseql.error
class AuthError:
    """Authentication error."""

    message: str
    code: str = "AUTH_ERROR"


@fraiseql.success
class CartSuccess:
    """Successful cart operation."""

    cart: Cart
    message: str


@fraiseql.error
class CartError:
    """Cart operation error."""

    message: str
    code: str = "CART_ERROR"


@fraiseql.success
class OrderSuccess:
    """Successful order operation."""

    order: Order
    message: str


@fraiseql.error
class OrderError:
    """Order operation error."""

    message: str
    code: str = "ORDER_ERROR"


@fraiseql.success
class AddressSuccess:
    """Successful address operation."""

    address: Address
    message: str


@fraiseql.error
class AddressError:
    """Address operation error."""

    message: str
    code: str = "ADDRESS_ERROR"


@fraiseql.success
class CreateReviewSuccess:
    """Successful review creation."""

    review: Review
    message: str


@fraiseql.error
class ReviewError:
    """Review operation error."""

    message: str
    code: str = "REVIEW_ERROR"

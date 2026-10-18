"""E-commerce mutations demonstrating complex validation patterns.

This example showcases enterprise-grade patterns:
- Cross-entity validation (inventory, pricing, customer eligibility)
- Multi-layer validation (GraphQL, app, core, business rules)
- NOOP handling for business rule violations
- Comprehensive audit trails for financial data
- Transaction patterns with rollback handling

For simpler patterns, see ../blog_api/
For complete enterprise example, see ../enterprise_patterns/
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

# Import enterprise pattern types (would be defined in models.py)
import fraiseql
from fraiseql.types import ID

from .models import (
    AddressMutationResult,
    CartMutationResult,
    CustomerMutationResult,
    OrderMutationResult,
    ReviewMutationResult,
)


# Cart Mutations
@fraiseql.mutation(
    name="addToCart",
    function="add_to_cart",
    description="Add a product variant to the shopping cart",
)
async def add_to_cart(
    variant_id: ID,
    quantity: int,
    cart_id: ID | None = None,
    customer_id: ID | None = None,
    session_id: str | None = None,
) -> CartMutationResult:
    """Add item to cart with inventory checking"""


@fraiseql.mutation(
    name="updateCartItem",
    function="update_cart_item",
    description="Update quantity of an item in the cart",
)
async def update_cart_item(
    cart_item_id: ID,
    quantity: int,
    customer_id: ID | None = None,
    session_id: str | None = None,
) -> CartMutationResult:
    """Update cart item quantity or remove if quantity is 0"""


@fraiseql.mutation(
    name="clearCart",
    function="clear_cart",
    description="Remove all items from the cart",
)
async def clear_cart(
    cart_id: ID,
    customer_id: ID | None = None,
    session_id: str | None = None,
) -> CartMutationResult:
    """Clear all items from cart"""


@fraiseql.mutation(
    name="applyCouponToCart",
    function="apply_coupon_to_cart",
    description="Apply a discount coupon to the cart",
)
async def apply_coupon_to_cart(
    cart_id: ID,
    coupon_code: str,
    customer_id: ID | None = None,
    session_id: str | None = None,
) -> CartMutationResult:
    """Apply coupon code to cart"""


# Order Mutations
@fraiseql.mutation(
    name="createOrder",
    function="create_order_from_cart",
    description="Create an order from the current cart",
)
async def create_order(
    cart_id: ID,
    customer_id: ID,
    shipping_address_id: ID,
    billing_address_id: ID | None = None,
    payment_method: dict | None = None,
    notes: str | None = None,
) -> OrderMutationResult:
    """Convert cart to order with inventory reservation"""


@fraiseql.mutation(
    name="updateOrderStatus",
    function="update_order_status",
    description="Update the status of an order",
)
async def update_order_status(
    order_id: ID,
    status: str,
    notes: str | None = None,
) -> OrderMutationResult:
    """Update order status with validation"""


@fraiseql.mutation(
    name="processOrderPayment",
    function="process_order_payment",
    description="Process payment for an order",
)
async def process_order_payment(
    order_id: ID,
    payment_details: dict,
) -> OrderMutationResult:
    """Process payment and update order status"""


@fraiseql.mutation(name="cancelOrder", function="cancel_order", description="Cancel an order")
async def cancel_order(
    order_id: ID,
    customer_id: ID,
    reason: str,
) -> OrderMutationResult:
    """Cancel order and release inventory"""


# Customer Mutations
@fraiseql.mutation(
    name="registerCustomer",
    function="register_customer",
    description="Register a new customer account",
)
async def register_customer(
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    phone: str | None = None,
) -> CustomerMutationResult:
    """Register new customer with email validation"""


@fraiseql.mutation(
    name="updateCustomerProfile",
    function="update_customer_profile",
    description="Update customer profile information",
)
async def update_customer_profile(
    customer_id: ID,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
    metadata: dict | None = None,
) -> CustomerMutationResult:
    """Update customer profile fields"""


@fraiseql.mutation(
    name="addCustomerAddress",
    function="add_customer_address",
    description="Add a new address to customer profile",
)
async def add_customer_address(
    customer_id: ID,
    type: str,  # billing, shipping, both
    first_name: str,
    last_name: str,
    address_line1: str,
    city: str,
    country_code: str,
    company: str | None = None,
    address_line2: str | None = None,
    state_province: str | None = None,
    postal_code: str | None = None,
    phone: str | None = None,
    is_default: bool = False,
) -> AddressMutationResult:
    """Add new address to customer account"""


# Wishlist Mutations
@fraiseql.mutation(
    name="addToWishlist",
    function="add_to_wishlist",
    description="Add a product to customer's wishlist",
)
async def add_to_wishlist(
    customer_id: ID,
    product_id: ID,
    variant_id: ID | None = None,
    wishlist_id: ID | None = None,
    priority: int = 0,
    notes: str | None = None,
) -> dict:
    """Add product to wishlist"""


# Review Mutations
@fraiseql.mutation(
    name="submitReview",
    function="submit_review",
    description="Submit a product review",
)
async def submit_review(
    customer_id: ID,
    product_id: ID,
    rating: int,
    title: str | None = None,
    comment: str | None = None,
    order_id: ID | None = None,
) -> ReviewMutationResult:
    """Submit product review with optional order verification"""


@fraiseql.mutation(
    name="markReviewHelpful",
    function="mark_review_helpful",
    description="Mark a review as helpful or not helpful",
)
async def mark_review_helpful(
    review_id: ID,
    is_helpful: bool,
    customer_id: ID | None = None,
    session_id: str | None = None,
) -> dict:
    """Mark review helpfulness"""


# Enterprise Pattern Examples
# These demonstrate complex validation and cross-entity patterns


@fraiseql.mutation(name="processOrder", function="process_order", schema="app")
class ProcessOrderEnterprise:
    """Process order with comprehensive validation.

    Enterprise features demonstrated:
    - Cross-entity validation (inventory, customer credit, pricing)
    - Multi-step transaction with rollback handling
    - NOOP for business rule violations (insufficient inventory, credit limits)
    - Financial audit trails with precise change tracking
    - Real-time inventory reservation and payment processing
    """

    input: ProcessOrderInput
    success: ProcessOrderSuccess
    error: ProcessOrderError
    noop: ProcessOrderNoop  # For inventory/business rule issues


@fraiseql.mutation(name="updateInventory", function="update_inventory", schema="app")
class UpdateInventoryEnterprise:
    """Update inventory with business rules.

    Validation layers:
    1. GraphQL: Type validation, required fields
    2. App layer: Basic bounds checking, format validation
    3. Core layer: Business rules, cross-entity consistency
    4. Database: Constraint validation, transaction integrity

    NOOP scenarios:
    - No actual quantity changes detected
    - Inventory levels would violate business rules
    - Concurrent modification conflicts (optimistic locking)
    """

    input: UpdateInventoryInput
    success: UpdateInventorySuccess
    error: UpdateInventoryError
    noop: UpdateInventoryNoop  # For no-change scenarios


@fraiseql.mutation(name="applyDiscount", function="apply_discount", schema="app")
class ApplyDiscountEnterprise:
    """Apply discount with eligibility validation.

    Complex validation example:
    - Customer eligibility (membership tier, purchase history)
    - Product eligibility (category restrictions, brand exclusions)
    - Temporal validation (valid date ranges, usage limits)
    - Quantity validation (minimum purchase requirements)
    - Cross-promotion conflicts (stackable vs exclusive discounts)
    """

    input: ApplyDiscountInput
    success: ApplyDiscountSuccess
    error: ApplyDiscountError
    noop: ApplyDiscountNoop  # For ineligible customers/products


# Legacy Pattern Examples (for comparison)
# Note: These show the old way. Use Enterprise classes above for new code.


async def process_order_legacy(
    info, cart_id: ID, customer_id: ID, payment_details: dict
) -> OrderMutationResult:
    """Legacy pattern - for comparison only.

    This shows the old resolver-based approach without:
    - Structured NOOP handling
    - Multi-layer validation
    - Comprehensive audit trails
    - Cross-entity validation patterns

    Compare with ProcessOrderEnterprise above to see the difference.
    """
    # Implementation would be similar to create_order function above


# Enterprise Pattern Type Definitions
# These would typically be in models.py but shown here for demonstration


@fraiseql.input
class ProcessOrderInput:
    """Order processing with comprehensive validation."""

    cart_id: ID
    customer_id: ID
    shipping_address_id: ID
    billing_address_id: ID | None = None
    payment_details: dict[str, Any]
    coupon_codes: list[str] | None = None
    special_instructions: str | None = None

    # Enterprise validation metadata
    _expected_total: Decimal | None = None  # For price validation
    _inventory_reserved_until: datetime | None = None  # For inventory checks


@fraiseql.success
class ProcessOrderSuccess:
    """Order processed successfully."""

    order_id: ID
    order_number: str
    total_amount: Decimal
    payment_status: str
    estimated_delivery: datetime | None = None

    # Enterprise audit information
    inventory_adjustments: list[dict[str, Any]]
    payment_transaction_id: str
    applied_discounts: list[dict[str, Any]]
    audit_trail: dict[str, Any]


@fraiseql.success
class ProcessOrderNoop:
    """Order processing was a no-op."""

    reason: str
    order_id: ID | None = None
    blocking_issues: list[dict[str, Any]]

    # Context for NOOP scenarios
    inventory_shortfalls: list[dict[str, Any | None]] = None
    credit_limit_exceeded: dict[str, Any] | None = None
    pricing_discrepancies: list[dict[str, Any | None]] = None


@fraiseql.error
class ProcessOrderError:
    """Order processing failed."""

    message: str
    error_code: str
    field_errors: dict[str, str] | None = None

    # Enterprise error context
    validation_failures: list[dict[str, Any]]
    transaction_rollback_info: dict[str, Any]
    affected_entities: list[dict[str, Any]]


@fraiseql.input
class UpdateInventoryInput:
    """Inventory update with business rules."""

    product_variant_id: ID
    quantity_change: int  # Can be negative
    reason_code: str  # 'restock', 'sale', 'damage', 'adjustment'
    reference_id: UUID | None = None  # Order ID, return ID, etc.
    notes: str | None = None

    # Enterprise validation
    _expected_current_quantity: int | None = None  # For optimistic locking
    _force_negative: bool = False  # Allow negative inventory


@fraiseql.success
class UpdateInventorySuccess:
    """Inventory updated successfully."""

    product_variant_id: ID
    previous_quantity: int
    new_quantity: int
    quantity_change: int

    # Business context
    reorder_point_triggered: bool = False
    low_stock_alert_sent: bool = False
    audit_trail: dict[str, Any]


@fraiseql.success
class UpdateInventoryNoop:
    """Inventory update was a no-op."""

    reason: str
    product_variant_id: ID
    current_quantity: int
    attempted_change: int

    # NOOP context
    business_rule_violation: str | None = None
    concurrent_modification: dict[str, Any] | None = None


@fraiseql.error
class UpdateInventoryError:
    """Inventory update failed."""

    message: str
    error_code: str
    product_variant_id: ID

    # Detailed error context
    validation_failures: list[str]
    business_rule_violations: list[str]
    system_constraints: list[str]


@fraiseql.input
class ApplyDiscountInput:
    """Discount application with eligibility rules."""

    cart_id: ID
    discount_code: str | None = None
    discount_id: ID | None = None
    customer_id: ID

    # Validation context
    _cart_total_for_validation: Decimal | None = None
    _customer_tier: str | None = None


@fraiseql.success
class ApplyDiscountSuccess:
    """Discount applied successfully."""

    discount_id: ID
    discount_amount: Decimal
    discount_percentage: Decimal | None = None
    cart_total_before: Decimal
    cart_total_after: Decimal

    # Discount details
    discount_rules_applied: list[dict[str, Any]]
    expiry_info: dict[str, Any]


@fraiseql.success
class ApplyDiscountNoop:
    """Discount application was a no-op."""

    reason: str
    discount_code: str | None = None
    customer_id: ID

    # Eligibility context
    customer_ineligible_reasons: list[str]
    product_restrictions: list[dict[str, Any]]
    temporal_restrictions: dict[str, Any] | None = None


@fraiseql.error
class ApplyDiscountError:
    """Discount application failed."""

    message: str
    error_code: str
    discount_code: str | None = None

    # Error details
    eligibility_failures: list[str]
    system_errors: list[str]
    validation_context: dict[str, Any]

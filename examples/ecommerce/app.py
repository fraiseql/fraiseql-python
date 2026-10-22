"""E-commerce API using FraiseQL.

This is a complete example of building an e-commerce GraphQL API with FraiseQL,
demonstrating best practices for production applications.
"""

import os

from fraiseql import create_fraiseql_app
from fraiseql.auth import Auth0Config
from fraiseql.monitoring import MetricsConfig, setup_metrics
from fraiseql.tracing import TracingConfig, setup_tracing
from fraiseql.types import ID

# Import models and operations
from .models import (
    Address,
    Cart,
    CartItem,
    Coupon,
    Order,
    OrderItem,
    # Enums
    Product,
    Review,
    User,
    WishlistItem,
)
from .mutations import (
    # Cart mutations
    AddToCart,
    CancelOrder,
    # Additional input types
    Checkout,
    ClearCart,
    # Address mutations
    CreateAddress,
    # Review mutations
    CreateReview,
    DeleteAddress,
    Login,
    # Auth mutations
    Register,
    RemoveFromCart,
    UpdateAddress,
    UpdateCartItem,
)
from .queries import (
    # Aggregated types
    CartWithItems,
    DashboardStats,
    OrderConnection,
    OrderWithDetails,
    # Connection types
    ProductConnection,
    ProductWithReviews,
    ReviewConnection,
)

# Load environment variables
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/ecommerce")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")
AUTH0_API_IDENTIFIER = os.getenv("AUTH0_API_IDENTIFIER")

# Configure based on environment
is_production = ENVIRONMENT == "production"

# Create the FraiseQL app
app = create_fraiseql_app(
    # Database configuration
    database_url=DATABASE_URL,
    # GraphQL types
    types=[
        # Core types
        User,
        Address,
        Product,
        Cart,
        CartItem,
        Order,
        OrderItem,
        Review,
        Coupon,
        WishlistItem,
        # Query types
        ProductConnection,
        OrderConnection,
        ReviewConnection,
        CartWithItems,
        OrderWithDetails,
        ProductWithReviews,
        DashboardStats,
    ],
    # Mutations
    mutations=[
        # Auth
        Register,
        Login,
        # Cart
        AddToCart,
        UpdateCartItem,
        RemoveFromCart,
        ClearCart,
        # Orders
        Checkout,
        CancelOrder,
        # Addresses
        CreateAddress,
        UpdateAddress,
        DeleteAddress,
        # Reviews
        CreateReview,
    ],
    # App configuration
    title="E-commerce API",
    version="1.0.0",
    description="Complete e-commerce GraphQL API built with FraiseQL",
    # Environment
    production=is_production,
    # Authentication
    auth=(
        Auth0Config(
            domain=AUTH0_DOMAIN,
            api_identifier=AUTH0_API_IDENTIFIER,
        )
        if AUTH0_DOMAIN
        else None
    ),
    # Development auth (if not using Auth0)
    dev_auth_username="admin" if not is_production else None,
    dev_auth_password="admin123" if not is_production else None,
)

# Setup monitoring
if is_production:
    metrics_config = MetricsConfig(
        namespace="ecommerce",
        labels={
            "service": "api",
            "environment": ENVIRONMENT,
        },
    )
    metrics = setup_metrics(app, metrics_config)

# Setup tracing
if is_production:
    tracing_config = TracingConfig(
        service_name="ecommerce-api",
        service_version="1.0.0",
        deployment_environment=ENVIRONMENT,
        sample_rate=0.1,  # 10% sampling
        export_endpoint=os.getenv("TRACING_ENDPOINT"),
        export_format=os.getenv("TRACING_FORMAT", "otlp"),
    )
    tracer = setup_tracing(app, tracing_config)

# Add CORS for frontend
from starlette.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# Health check endpoints
@app.get("/health")
async def health():
    """Basic health check."""
    return {"status": "healthy", "service": "ecommerce-api"}


@app.get("/ready")
async def ready():
    """Readiness check including database."""
    # Check database connection
    try:
        # You would check database here
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        return {"status": "not ready", "error": str(e)}, 503


# Startup event
@app.on_event("startup")
async def startup():
    """Initialize application on startup."""
    if not is_production:
        pass


# Example queries for documentation
EXAMPLE_QUERIES = """
# Featured products for homepage
query GetFeaturedProducts {
    featuredProducts(limit: 8) {
        id
        name
        price
        images
        category
    }
}

# Product search with filters
query SearchProducts($filters: ProductFilterInput!) {
    products(filters: $filters, limit: 20) {
        items {
            id
            name
            description
            price
            compareAtPrice
            inventoryCount
            images
        }
        totalCount
        hasNextPage
    }
}

# Get product with reviews
query GetProductDetails($id: ID!) {
    productWithReviews(id: $id) {
        product {
            id
            name
            description
            price
            inventoryCount
            images
            tags
        }
        averageRating
        reviewCount
        reviews(limit: 5) {
            items {
                id
                rating
                title
                comment
                isVerified
                user {
                    name
                }
                createdAt
            }
            totalCount
        }
        relatedProducts {
            id
            name
            price
            images
        }
    }
}

# User registration
mutation RegisterUser($input: RegisterInput!) {
    register(input: $input) {
        ... on AuthSuccess {
            user {
                id
                email
                name
            }
            token
            message
        }
        ... on AuthError {
            message
            code
        }
    }
}

# Add to cart
mutation AddProductToCart($input: AddToCartInput!) {
    addToCart(input: $input) {
        ... on CartSuccess {
            cart {
                id
                itemsCount
                subtotal
            }
            message
        }
        ... on CartError {
            message
            code
        }
    }
}

# Checkout
mutation CompleteCheckout($input: CheckoutInput!) {
    checkout(input: $input) {
        ... on OrderSuccess {
            order {
                id
                orderNumber
                total
                status
            }
            message
        }
        ... on OrderError {
            message
            code
        }
    }
}
"""

# Development data seeding (if needed)
if not is_production:

    @app.on_event("startup")
    async def seed_data():
        """Seed development data."""
        # This would be implemented to add sample products, users, etc.


if __name__ == "__main__":
    import uvicorn

    # Run the application
    uvicorn.run(
        "app:app",
        host="0.0.0.0",  # noqa: S104
        port=8000,
        reload=not is_production,
        log_level="info" if is_production else "debug",
    )

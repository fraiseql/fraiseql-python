"""FraiseQL Security Module.

This module provides comprehensive security features for FraiseQL applications:

- Rate limiting for API endpoints and GraphQL operations
- CSRF protection for mutations and forms
- Security headers middleware for defense in depth
- Input validation and sanitization
- Authentication and authorization helpers

Example usage:

    from fraiseql.security import setup_security

    # Quick setup with sensible defaults
    setup_security(app, secret_key="your-secret-key")

    # Or configure individual components
    from fraiseql.security import (
        setup_rate_limiting, setup_csrf_protection, setup_security_headers
    )

    setup_rate_limiting(app)
    setup_csrf_protection(app, "your-secret-key")
    setup_security_headers(app, environment="production")
"""

import logging
from typing import Any

from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Operation-level authorization (issue #362)
from .authorization import (
    AuthorizationDecision,
    Authorizer,
    normalize_decision,
)

# CSRF protection
from .csrf_protection import (
    CSRFConfig,
    CSRFProtectionMiddleware,
    CSRFTokenEndpoint,
    CSRFTokenGenerator,
    CSRFTokenStorage,
    GraphQLCSRFValidator,
    create_development_csrf_config,
    create_production_csrf_config,
    setup_csrf_protection,
)

# Field-level authorization
from .field_auth import (
    FieldAuthorizationError,
    any_permission,
    authorize_field,
    combine_permissions,
)

# Rate limiting
from .rate_limiting import (
    GraphQLRateLimiter,
    RateLimit,
    RateLimitMiddleware,
    RateLimitRule,
    RateLimitStore,
    RateLimitStrategy,
    RedisRateLimitStore,
    create_default_rate_limit_rules,
    setup_rate_limiting,
)

# Security headers
from .security_headers import (
    ContentSecurityPolicy,
    CSPDirective,
    FrameOptions,
    ReferrerPolicy,
    SecurityHeadersConfig,
    SecurityHeadersMiddleware,
    create_api_csp,
    create_development_csp,
    create_development_security_config,
    create_graphql_security_config,
    create_production_security_config,
    create_strict_csp,
    setup_security_headers,
)

# Input validation (existing)
from .validators import (
    InputValidator,
    ValidationResult,
)

__all__ = [
    # Operation-level authorization (issue #362)
    "AuthorizationDecision",
    "Authorizer",
    "CSPDirective",
    # CSRF protection
    "CSRFConfig",
    "CSRFProtectionMiddleware",
    "CSRFTokenEndpoint",
    "CSRFTokenGenerator",
    "CSRFTokenStorage",
    "ContentSecurityPolicy",
    # Field-level authorization
    "FieldAuthorizationError",
    "FrameOptions",
    "GraphQLCSRFValidator",
    "GraphQLRateLimiter",
    # Input validation
    "InputValidator",
    # Rate limiting
    "RateLimit",
    "RateLimitMiddleware",
    "RateLimitRule",
    "RateLimitStore",
    "RateLimitStrategy",
    "RedisRateLimitStore",
    "ReferrerPolicy",
    # Security headers
    "SecurityHeadersConfig",
    "SecurityHeadersMiddleware",
    "ValidationResult",
    "any_permission",
    "authorize_field",
    "combine_permissions",
    "create_api_csp",
    "create_default_rate_limit_rules",
    "create_development_csp",
    "create_development_csrf_config",
    "create_development_security_config",
    "create_graphql_security_config",
    "create_production_csrf_config",
    "create_production_security_config",
    "create_strict_csp",
    "normalize_decision",
    "setup_csrf_protection",
    "setup_rate_limiting",
    # Main setup function
    "setup_security",
    "setup_security_headers",
]


class SecurityConfig:
    """Comprehensive security configuration."""

    def __init__(
        self,
        secret_key: str,
        environment: str = "production",
        domain: str | None = None,
        trusted_origins: set[str] | None = None,
        api_only: bool = False,
        enable_rate_limiting: bool = True,
        enable_csrf_protection: bool = True,
        enable_security_headers: bool = True,
        enable_input_validation: bool = True,
        redis_client: Any | None = None,
        custom_rate_limits: list[RateLimitRule] | None = None,
        custom_csrf_config: CSRFConfig | None = None,
        custom_security_headers: SecurityHeadersConfig | None = None,
    ) -> None:
        self.secret_key = secret_key
        self.environment = environment
        self.domain = domain or "localhost"
        self.trusted_origins = trusted_origins or set()
        self.api_only = api_only
        self.enable_rate_limiting = enable_rate_limiting
        self.enable_csrf_protection = enable_csrf_protection
        self.enable_security_headers = enable_security_headers
        self.enable_input_validation = enable_input_validation
        self.redis_client = redis_client
        self.custom_rate_limits = custom_rate_limits
        self.custom_csrf_config = custom_csrf_config
        self.custom_security_headers = custom_security_headers

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment.lower() == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment.lower() == "development"


def setup_security(
    app: FastAPI,
    secret_key: str,
    environment: str = "production",
    domain: str | None = None,
    trusted_origins: set[str] | None = None,
    api_only: bool = False,
    redis_client: Any | None = None,
    custom_config: SecurityConfig | None = None,
) -> dict[str, Any]:
    """Set up comprehensive security for FraiseQL applications.

    This function configures rate limiting, CSRF protection, security headers,
    and input validation with sensible defaults for the specified environment.

    Args:
        app: FastAPI application instance
        secret_key: Secret key for CSRF token generation
        environment: Environment ("production", "development", "testing")
        domain: Application domain for security headers
        trusted_origins: Set of trusted origins for CORS/CSP
        api_only: Whether this is an API-only application
        redis_client: Redis client for distributed rate limiting
        custom_config: Custom security configuration

    Returns:
        Dictionary of configured middleware instances

    Example:
        ```python
        from fastapi import FastAPI
        from fraiseql.security import setup_security

        app = FastAPI()

        # Production setup
        security = setup_security(
            app=app,
            secret_key="your-secret-key",
            environment="production",
            domain="api.example.com",
            trusted_origins={"https://app.example.com"},
            api_only=True
        )

        # Development setup
        security = setup_security(
            app=app,
            secret_key="dev-secret-key",
            environment="development"
        )
        ```
    """
    if custom_config:
        config = custom_config
    else:
        config = SecurityConfig(
            secret_key=secret_key,
            environment=environment,
            domain=domain,
            trusted_origins=trusted_origins or set(),
            api_only=api_only,
            redis_client=redis_client,
        )

    middleware_instances = {}

    # 1. Set up rate limiting
    if config.enable_rate_limiting:
        try:
            rate_limiting_middleware = setup_rate_limiting(
                app=app,
                redis_client=config.redis_client,
                custom_rules=config.custom_rate_limits,
            )
            middleware_instances["rate_limiting"] = rate_limiting_middleware
        except Exception as e:
            logger.warning("Failed to set up rate limiting: %s", e)

    # 2. Set up CSRF protection
    if config.enable_csrf_protection:
        try:
            csrf_config = config.custom_csrf_config
            if not csrf_config:
                if config.is_production:
                    csrf_config = create_production_csrf_config(
                        secret_key=config.secret_key,
                        trusted_origins=config.trusted_origins,
                    )
                else:
                    csrf_config = create_development_csrf_config(
                        secret_key=config.secret_key,
                    )

            csrf_middleware = setup_csrf_protection(
                app=app,
                secret_key=config.secret_key,
                config=csrf_config,
            )
            middleware_instances["csrf"] = csrf_middleware
        except Exception as e:
            logger.warning("Failed to set up CSRF protection: %s", e)

    # 3. Set up security headers
    if config.enable_security_headers:
        try:
            headers_config = config.custom_security_headers
            if not headers_config:
                if config.is_production:
                    headers_config = create_production_security_config(
                        domain=config.domain,
                        api_only=config.api_only,
                    )
                elif config.api_only:
                    headers_config = create_graphql_security_config(
                        trusted_origins=list(config.trusted_origins),
                        enable_introspection=config.is_development,
                    )
                else:
                    headers_config = create_development_security_config()

            headers_middleware = setup_security_headers(
                app=app,
                config=headers_config,
            )
            middleware_instances["security_headers"] = headers_middleware
        except Exception as e:
            logger.warning("Failed to set up security headers: %s", e)

    # 4. Set up input validation (if available)
    if config.enable_input_validation:
        try:
            # Input validation is typically set up in the GraphQL schema layer
            # This would be integrated with the FraiseQL query processing
            pass
        except Exception as e:
            logger.warning("Failed to set up input validation: %s", e)

    return middleware_instances


def create_security_config_for_graphql(
    secret_key: str,
    environment: str = "production",
    trusted_origins: list[str] | None = None,
    enable_introspection: bool = False,
    redis_client: Any | None = None,
) -> SecurityConfig:
    """Create security configuration optimized for GraphQL APIs.

    Args:
        secret_key: Secret key for CSRF tokens
        environment: Environment ("production", "development")
        trusted_origins: List of trusted origins for CORS/CSP
        enable_introspection: Whether to enable GraphQL introspection
        redis_client: Redis client for distributed rate limiting

    Returns:
        SecurityConfig instance optimized for GraphQL
    """
    trusted_origins_set = set(trusted_origins) if trusted_origins else set()

    # Custom rate limits for GraphQL
    graphql_rate_limits = [
        RateLimitRule(
            path_pattern="/graphql",
            rate_limit=RateLimit(requests=60, window=60),
            message="GraphQL rate limit exceeded",
        ),
        RateLimitRule(
            path_pattern="/graphql/introspection",
            rate_limit=RateLimit(requests=10, window=60),
            message="Introspection rate limit exceeded",
        ),
    ]

    # Custom CSRF config for GraphQL
    csrf_config = None
    if environment == "production":
        csrf_config = create_production_csrf_config(
            secret_key=secret_key,
            trusted_origins=trusted_origins_set,
        )
    else:
        csrf_config = create_development_csrf_config(secret_key=secret_key)

    # Enable mutations protection but not subscriptions by default
    csrf_config.require_for_mutations = True
    csrf_config.require_for_subscriptions = False

    # Custom security headers for GraphQL
    headers_config = create_graphql_security_config(
        trusted_origins=list(trusted_origins_set),
        enable_introspection=enable_introspection,
    )

    return SecurityConfig(
        secret_key=secret_key,
        environment=environment,
        trusted_origins=trusted_origins_set,
        api_only=True,
        redis_client=redis_client,
        custom_rate_limits=graphql_rate_limits,
        custom_csrf_config=csrf_config,
        custom_security_headers=headers_config,
    )


def create_security_config_for_api(
    secret_key: str,
    environment: str = "production",
    domain: str = "api.example.com",
    redis_client: Any | None = None,
) -> SecurityConfig:
    """Create security configuration optimized for REST APIs.

    Args:
        secret_key: Secret key for CSRF tokens
        environment: Environment ("production", "development")
        domain: API domain for security headers
        redis_client: Redis client for distributed rate limiting

    Returns:
        SecurityConfig instance optimized for REST APIs
    """
    # API-focused rate limits
    api_rate_limits = [
        RateLimitRule(
            path_pattern="/api/v1/*",
            rate_limit=RateLimit(requests=100, window=60),
            message="API rate limit exceeded",
        ),
        RateLimitRule(
            path_pattern="/auth/*",
            rate_limit=RateLimit(requests=5, window=300),
            message="Authentication rate limit exceeded",
        ),
    ]

    return SecurityConfig(
        secret_key=secret_key,
        environment=environment,
        domain=domain,
        api_only=True,
        redis_client=redis_client,
        custom_rate_limits=api_rate_limits,
    )


# Export convenience functions
def setup_production_security(
    app: FastAPI,
    secret_key: str,
    domain: str,
    trusted_origins: set[str],
    redis_client: Any | None = None,
) -> dict[str, Any]:
    """Set up production security with strict settings."""
    return setup_security(
        app=app,
        secret_key=secret_key,
        environment="production",
        domain=domain,
        trusted_origins=trusted_origins,
        redis_client=redis_client,
    )


def setup_development_security(
    app: FastAPI,
    secret_key: str = "dev-secret-key-change-in-production",
) -> dict[str, Any]:
    """Set up development security with permissive settings."""
    return setup_security(
        app=app,
        secret_key=secret_key,
        environment="development",
    )

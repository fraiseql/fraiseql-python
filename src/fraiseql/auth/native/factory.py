"""Factory functions for setting up native authentication."""

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, FastAPI
from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from fraiseql.auth.native.provider import NativeAuthProvider
from fraiseql.auth.native.tokens import TokenManager


async def create_native_auth_provider(
    db_pool: AsyncConnectionPool,
    schema: str = "public",
    secret_key: Optional[str] = None,
    access_token_ttl_minutes: int = 15,
    refresh_token_ttl_days: int = 30,
) -> NativeAuthProvider:
    """Create a configured NativeAuthProvider instance.

    Args:
        db_pool: PostgreSQL connection pool
        schema: Database schema name (for multi-tenant support)
        secret_key: JWT signing secret (falls back to env var JWT_SECRET_KEY)
        access_token_ttl_minutes: Access token lifetime in minutes
        refresh_token_ttl_days: Refresh token lifetime in days

    Returns:
        Configured NativeAuthProvider instance
    """
    # Get secret key from parameter or environment
    if not secret_key:
        secret_key = os.environ.get("JWT_SECRET_KEY")
        if not secret_key:
            raise ValueError(
                "JWT secret key required. Set JWT_SECRET_KEY environment variable "
                "or pass secret_key parameter."
            )

    # Create token manager with configured TTLs
    from datetime import timedelta

    token_manager = TokenManager(
        secret_key=secret_key,
        access_token_ttl=timedelta(minutes=access_token_ttl_minutes),
        refresh_token_ttl=timedelta(days=refresh_token_ttl_days),
    )

    # Create and return provider
    return NativeAuthProvider(
        token_manager=token_manager,
        db_pool=db_pool,
        schema=schema,
    )


async def apply_native_auth_schema(
    db_pool: AsyncConnectionPool,
    schema: str = "public",
) -> None:
    """Apply the native auth database schema to the given schema.

    This function reads and executes ``migrations/001_native_auth_schema.sql``
    (shipped in this package) to create the tables native authentication uses:
    ``tb_user``, ``tb_session``, ``tb_used_refresh_token`` and ``tb_password_reset``.
    It is idempotent.

    Args:
        db_pool: PostgreSQL connection pool
        schema: Database schema name to apply migration to
    """
    # Read migration file
    migration_path = Path(__file__).parent / "migrations" / "001_native_auth_schema.sql"

    if not migration_path.exists():
        raise FileNotFoundError(f"Migration file not found: {migration_path}")

    migration_sql = migration_path.read_text()

    # Apply migration in one transaction. SET LOCAL keeps the search_path change to
    # that transaction, so the pooled connection goes back with its own.
    async with db_pool.connection() as conn, conn.transaction():
        await conn.execute(
            sql.SQL("SET LOCAL search_path TO {}, public").format(sql.Identifier(schema))
        )
        await conn.execute(migration_sql)


def get_native_auth_router() -> APIRouter:
    """Get the FastAPI router for native auth endpoints.

    This is a convenience function that returns the pre-configured
    router with all the auth endpoints (register, login, refresh, etc.).

    Returns:
        FastAPI APIRouter with native auth endpoints
    """
    from fraiseql.auth.native.router import auth_router

    return auth_router


def add_security_middleware(
    app: FastAPI,
    secret_key: str,
    enable_rate_limiting: bool = True,
    enable_security_headers: bool = True,
    enable_csrf_protection: bool = False,  # Disabled by default for API-first apps
    rate_limit_requests_per_minute: int = 60,
    rate_limit_auth_requests_per_minute: int = 5,
    csp_policy: Optional[str] = None,
) -> None:
    """Add security middleware to a FastAPI application.

    Args:
        app: FastAPI application instance
        secret_key: Secret key for CSRF protection
        enable_rate_limiting: Whether to enable rate limiting
        enable_security_headers: Whether to add security headers
        enable_csrf_protection: Whether to enable CSRF protection
        rate_limit_requests_per_minute: General rate limit per IP
        rate_limit_auth_requests_per_minute: Auth endpoint rate limit per IP
        csp_policy: Custom Content Security Policy
    """
    if enable_rate_limiting:
        from fraiseql.auth.native.middleware import RateLimitMiddleware

        app.add_middleware(
            RateLimitMiddleware,
            requests_per_minute=rate_limit_requests_per_minute,
            auth_requests_per_minute=rate_limit_auth_requests_per_minute,
        )

    if enable_security_headers:
        from fraiseql.auth.native.middleware import SecurityHeadersMiddleware

        app.add_middleware(
            SecurityHeadersMiddleware,
            csp_policy=csp_policy,
        )

    if enable_csrf_protection:
        from fraiseql.auth.native.middleware import CSRFProtectionMiddleware

        app.add_middleware(
            CSRFProtectionMiddleware,
            secret_key=secret_key,
        )

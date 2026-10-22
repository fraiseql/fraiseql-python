"""Example of using token revocation with FraiseQL.

This example demonstrates how to implement token revocation functionality
to invalidate JWT tokens before they expire.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, HTTPException, Request
from redis.asyncio import Redis

from fraiseql import fraise_type
from fraiseql.auth import Auth0ProviderWithRevocation
from fraiseql.auth.decorators import requires_auth, requires_role
from fraiseql.auth.token_revocation import (
    InMemoryRevocationStore,
    RedisRevocationStore,
    RevocationConfig,
    TokenRevocationService,
)
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app
from fraiseql.fastapi.dependencies import get_current_user


# Define types
@fraise_type
class User:
    id: str
    email: str
    name: str


@fraise_type
class LogoutResult:
    success: bool
    message: str


# Global revocation service
revocation_service: TokenRevocationService | None = None


@asynccontextmanager
async def lifespan(app):
    """Application lifespan manager."""
    global revocation_service

    # Initialize revocation service
    if app.state.config.redis_url:
        # Use Redis in production
        redis = Redis.from_url(app.state.config.redis_url)
        store = RedisRevocationStore(redis)
    else:
        # Use in-memory store for development
        store = InMemoryRevocationStore()

    revocation_service = TokenRevocationService(
        store=store,
        config=RevocationConfig(
            enabled=True,
            check_revocation=True,
            ttl=86400,  # 24 hours
            cleanup_interval=3600,  # Clean every hour
        ),
    )

    # Start the service
    await revocation_service.start()

    # Create auth provider with revocation
    auth_provider = Auth0ProviderWithRevocation(
        domain=app.state.config.auth0_domain,
        api_identifier=app.state.config.auth0_api_identifier,
        revocation_service=revocation_service,
    )

    # Store in app state
    app.state.auth_provider = auth_provider

    yield

    # Cleanup
    await revocation_service.stop()
    if isinstance(store, RedisRevocationStore):
        await redis.close()


# Query functions
@requires_auth
async def me(info) -> User:
    """Get current user information."""
    user = info.context["user"]
    return User(
        id=user.user_id,
        email=user.email or "",
        name=user.name or "Unknown",
    )


@requires_auth
async def check_token_status(info) -> dict:
    """Check if the current token is still valid."""
    token_payload = info.context.get("token_payload", {})

    if revocation_service:
        is_revoked = await revocation_service.is_token_revoked(token_payload)
        return {
            "valid": not is_revoked,
            "token_id": token_payload.get("jti", "unknown"),
        }

    return {"valid": True, "token_id": "unknown"}


# Mutation functions
@requires_auth
async def logout(info) -> LogoutResult:
    """Logout current session by revoking the token."""
    user = info.context["user"]
    token_payload = info.context.get("token_payload")

    if not token_payload:
        raise HTTPException(status_code=400, detail="No token found")

    # Ensure token has JTI (JWT ID) for revocation
    if "jti" not in token_payload:
        return LogoutResult(
            success=False,
            message="Token does not support revocation (missing JTI)",
        )

    # Revoke the token
    auth_provider = info.context["request"].app.state.auth_provider
    await auth_provider.logout(token_payload)

    return LogoutResult(
        success=True,
        message=f"Successfully logged out user {user.email}",
    )


@requires_auth
async def logout_all_sessions(info) -> LogoutResult:
    """Logout all sessions for the current user."""
    user = info.context["user"]

    # Revoke all tokens for this user
    auth_provider = info.context["request"].app.state.auth_provider
    await auth_provider.logout_all_sessions(user.user_id)

    return LogoutResult(
        success=True,
        message=f"Successfully logged out all sessions for {user.email}",
    )


# Admin mutation (requires admin role)
@requires_role("admin")
async def revoke_user_tokens(info, user_id: str) -> LogoutResult:
    """Admin function to revoke all tokens for a specific user."""
    if not revocation_service:
        raise HTTPException(status_code=500, detail="Revocation service not available")

    await revocation_service.revoke_all_user_tokens(user_id)

    return LogoutResult(
        success=True,
        message=f"Successfully revoked all tokens for user {user_id}",
    )


@requires_role("admin")
async def revocation_stats(info) -> dict:
    """Get token revocation statistics."""
    if not revocation_service:
        return {"error": "Revocation service not available"}

    return await revocation_service.get_stats()


# Custom context getter that includes token payload
async def custom_context_getter(request: Request) -> dict[str, Any]:
    """Get context with token payload for revocation checks."""
    # Get default context
    from fraiseql.fastapi.dependencies import get_db_pool

    context = {
        "request": request,
        "db": get_db_pool(),
    }

    # Try to get current user and token
    try:
        # Extract token from header
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

            # Get auth provider
            auth_provider = request.app.state.auth_provider

            # Validate and get payload
            token_payload = await auth_provider.validate_token(token)
            context["token_payload"] = token_payload

            # Get user context
            user = await auth_provider.get_user_from_token(token)
            context["user"] = user
    except Exception:
        # Not authenticated, that's OK for public queries
        pass

    return context


# Create the application
def create_app(config: FraiseQLConfig | None = None) -> Any:
    """Create FraiseQL app with token revocation support."""
    if not config:
        config = FraiseQLConfig(
            database_url="postgresql://localhost/myapp",
            auth_provider="auth0",
            auth0_domain="myapp.auth0.com",
            auth0_api_identifier="https://api.myapp.com",
            redis_url="redis://localhost:6379",  # For production
        )

    app = create_fraiseql_app(
        types=[User, LogoutResult],
        queries=[
            me,
            check_token_status,
            revocation_stats,
        ],
        mutations=[
            logout,
            logout_all_sessions,
            revoke_user_tokens,
        ],
        config=config,
        context_getter=custom_context_getter,
        lifespan=lifespan,
    )

    # Add custom logout endpoint
    @app.post("/logout")
    async def logout_endpoint(request: Request, user=Depends(get_current_user)):
        """REST endpoint for logout."""
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="No token found")

        token = auth_header[7:]
        auth_provider = request.app.state.auth_provider

        # Get token payload
        token_payload = await auth_provider.validate_token(token)

        # Revoke it
        await auth_provider.logout(token_payload)

        return {"message": "Successfully logged out"}

    return app


if __name__ == "__main__":
    import uvicorn

    # Create and run the app
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)

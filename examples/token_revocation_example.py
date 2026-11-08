"""Example of using token revocation with FraiseQL.

This example demonstrates how to implement token revocation functionality
to invalidate JWT tokens before they expire: logging out one session, all of
a user's sessions, or (for an admin) all of another user's sessions.

Revoked token ids are kept in memory, or in PostgreSQL (table
tb_token_revocation, created on first use) when REVOCATION_STORE=postgresql,
which every worker shares. Tokens need a ``jti`` (JWT ID) claim to be revocable.

Usage:
    AUTH0_DOMAIN=myapp.auth0.com AUTH0_API_IDENTIFIER=https://api.myapp.com \
        DATABASE_URL=postgresql://localhost/myapp python token_revocation_example.py
"""

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from graphql import GraphQLResolveInfo

import fraiseql
from fraiseql.auth import Auth0ProviderWithRevocation
from fraiseql.auth.decorators import requires_auth, requires_role
from fraiseql.auth.token_revocation import (
    InMemoryRevocationStore,
    PostgreSQLRevocationStore,
    RevocationConfig,
    TokenRevocationService,
)
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.dependencies import get_db_pool

AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN", "myapp.auth0.com")
AUTH0_API_IDENTIFIER = os.getenv("AUTH0_API_IDENTIFIER", "https://api.myapp.com")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/myapp")
REVOCATION_STORE = os.getenv("REVOCATION_STORE", "memory")  # or "postgresql"


# Define types
@fraiseql.type
class User:
    id: str
    email: str
    name: str


@fraiseql.type
class TokenStatus:
    valid: bool
    token_id: str


@fraiseql.type
class LogoutResult:
    success: bool
    message: str


# The in-memory store is per process; lifespan swaps in PostgreSQL if asked
revocation_service = TokenRevocationService(
    store=InMemoryRevocationStore(),
    config=RevocationConfig(
        enabled=True,
        check_revocation=True,
        ttl=86400,  # 24 hours
        cleanup_interval=3600,  # Clean every hour
    ),
)

# Validates tokens with Auth0, then rejects revoked ones
auth_provider = Auth0ProviderWithRevocation(
    domain=AUTH0_DOMAIN,
    api_identifier=AUTH0_API_IDENTIFIER,
    revocation_service=revocation_service,
)


# Queries
@fraiseql.query
@requires_auth
async def me(info: GraphQLResolveInfo) -> User:
    """Get current user information."""
    user = info.context["user"]
    return User(id=user.user_id, email=user.email or "", name=user.name or "Unknown")


@fraiseql.query
@requires_auth
async def token_status(info: GraphQLResolveInfo) -> TokenStatus:
    """Check whether the current token is still valid."""
    token_payload = info.context["token_payload"]
    is_revoked = await revocation_service.is_token_revoked(token_payload)
    return TokenStatus(valid=not is_revoked, token_id=token_payload.get("jti", "unknown"))


@fraiseql.query
@requires_role("admin")
async def revocation_stats(info: GraphQLResolveInfo) -> dict[str, Any]:
    """Get token revocation statistics (admin only)."""
    return await revocation_service.get_stats()


# Mutations
@fraiseql.mutation
@requires_auth
async def logout(info: GraphQLResolveInfo) -> LogoutResult:
    """Logout the current session by revoking its token."""
    token_payload = info.context["token_payload"]

    # A token without a JTI (JWT ID) can't be revoked on its own
    if "jti" not in token_payload:
        return LogoutResult(
            success=False, message="Token does not support revocation (missing JTI)"
        )

    await auth_provider.logout(token_payload)
    return LogoutResult(success=True, message="Logged out")


@fraiseql.mutation
@requires_auth
async def logout_all_sessions(info: GraphQLResolveInfo) -> LogoutResult:
    """Logout all sessions of the current user."""
    user = info.context["user"]
    await auth_provider.logout_all_sessions(user.user_id)
    return LogoutResult(success=True, message="Logged out of all sessions")


@fraiseql.mutation
@requires_role("admin")
async def revoke_user_tokens(info: GraphQLResolveInfo, user_id: str) -> LogoutResult:
    """Revoke all tokens of a user (admin only)."""
    await revocation_service.revoke_all_user_tokens(user_id)
    return LogoutResult(success=True, message=f"Revoked all tokens for user {user_id}")


# Context: fraiseql adds the user (from auth_provider); add the token's claims
async def get_context(request: Request) -> dict[str, Any]:
    """Add the validated token payload, which logout needs, to the context."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return {}
    try:
        return {"token_payload": await auth_provider.validate_token(auth_header[7:])}
    except Exception:
        # Invalid or revoked: fraiseql leaves the user out, and @requires_auth refuses
        return {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run the revocation service's cleanup task while the app runs."""
    if REVOCATION_STORE == "postgresql":
        # fraiseql opens its pool before this lifespan runs
        revocation_service.store = PostgreSQLRevocationStore(get_db_pool())
    await revocation_service.start()
    yield
    await revocation_service.stop()


# Create the application
def create_app() -> FastAPI:
    """Create FraiseQL app with token revocation support."""
    app = create_fraiseql_app(
        database_url=DATABASE_URL,
        types=[User, TokenStatus, LogoutResult],
        queries=[me, token_status, revocation_stats],
        mutations=[logout, logout_all_sessions, revoke_user_tokens],
        auth=auth_provider,
        context_getter=get_context,
        lifespan=lifespan,
    )

    # The same logout as a REST endpoint
    @app.post("/logout")
    async def logout_endpoint(request: Request) -> dict[str, str]:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="No token found")
        try:
            token_payload = await auth_provider.validate_token(auth_header[7:])
        except Exception as e:
            raise HTTPException(status_code=401, detail="Invalid token") from e

        await auth_provider.logout(token_payload)
        return {"message": "Successfully logged out"}

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=8000)  # noqa: S104

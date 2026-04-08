"""FastAPI dependencies for FraiseQL."""

from typing import Annotated, Any, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg_pool import AsyncConnectionPool

from fraiseql.auth.base import AuthenticationError, AuthProvider, UserContext
from fraiseql.db import FraiseQLRepository
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.optimization.registry import LoaderRegistry

# Global instances (will be set by create_app)
_db_pool = None
_auth_provider: AuthProvider | None = None
_fraiseql_config = None


def get_db_pool() -> Any:
    """Get the database connection pool."""
    if _db_pool is None:
        msg = "Database pool not initialized. Call create_fraiseql_app first."
        raise RuntimeError(msg)
    return _db_pool


def set_db_pool(pool: AsyncConnectionPool) -> None:
    """Set the database connection pool (called by create_app)."""
    global _db_pool
    _db_pool = pool


def get_auth_provider() -> AuthProvider | None:
    """Get the configured auth provider."""
    return _auth_provider


def set_auth_provider(provider: AuthProvider | None) -> None:
    """Set the auth provider (called by create_app)."""
    global _auth_provider
    _auth_provider = provider


def get_fraiseql_config() -> Any:
    """Get the FraiseQL configuration."""
    return _fraiseql_config


def set_fraiseql_config(config: FraiseQLConfig) -> None:
    """Set the FraiseQL configuration (called by create_app)."""
    global _fraiseql_config
    _fraiseql_config = config

    # Also set config in the schema registry for decorators to use
    from fraiseql.gql.builders.registry import SchemaRegistry

    registry = SchemaRegistry.get_instance()
    registry.config = config


# FastAPI dependencies
security = HTTPBearer(auto_error=False)


async def get_db() -> FraiseQLRepository:
    """Get database repository instance."""
    pool = get_db_pool()
    config = get_fraiseql_config()

    # Create repository with timeout from config
    context = {}
    if config:
        context["config"] = config

        if hasattr(config, "query_timeout"):
            context["query_timeout"] = config.query_timeout
        if hasattr(config, "jsonb_field_limit_threshold"):
            context["jsonb_field_limit_threshold"] = config.jsonb_field_limit_threshold

    return FraiseQLRepository(pool=pool, context=context)


async def get_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),  # noqa: B008
) -> str | None:
    """Extract bearer token from request."""
    if credentials is None:
        return None
    return credentials.credentials


async def get_current_user_optional(
    token: Annotated[str | None, Depends(get_token)],
) -> UserContext | None:
    """Get current user context, returning None if not authenticated."""
    if token is None:
        return None

    auth_provider = get_auth_provider()
    if auth_provider is None:
        return None

    try:
        return await auth_provider.get_user_from_token(token)
    except AuthenticationError:
        return None


async def get_current_user(
    user: Annotated[UserContext | None, Depends(get_current_user_optional)],
) -> UserContext:
    """Get current user context, raising 401 if not authenticated."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_permission(permission: str) -> Callable:
    """Dependency to require a specific permission."""

    async def check_permission(
        user: Annotated[UserContext, Depends(get_current_user)],
    ) -> UserContext:
        if not user.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' required",
            )
        return user

    return check_permission


def require_role(role: str) -> Callable:
    """Dependency to require a specific role."""

    async def check_role(
        user: Annotated[UserContext, Depends(get_current_user)],
    ) -> UserContext:
        if not user.has_role(role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' required",
            )
        return user

    return check_role


# Context builders for GraphQL
async def build_graphql_context(
    db: Annotated[FraiseQLRepository, Depends(get_db)],
    user: Annotated[UserContext | None, Depends(get_current_user_optional)],
) -> dict[str, Any]:
    """Build GraphQL context with database and user info."""
    # Create a new LoaderRegistry for this request
    loader_registry = LoaderRegistry(db=db)

    # Set as current registry for this request context
    LoaderRegistry.set_current(loader_registry)

    config = get_fraiseql_config()

    context = {
        "db": db,
        "user": user,
        "authenticated": user is not None,
        "loader_registry": loader_registry,
        "config": config,  # Add config for introspection policy access
        "_http_mode": True,  # Enable Rust-first path for mutations
    }

    # Add query timeout to context if configured
    if config and hasattr(config, "query_timeout"):
        context["query_timeout"] = config.query_timeout

    return context

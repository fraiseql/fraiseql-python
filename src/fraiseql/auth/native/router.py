"""Native authentication REST API router."""

import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, AsyncGenerator, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, EmailStr, Field, field_validator

from fraiseql.auth.native.models import User
from fraiseql.auth.native.tokens import (
    InvalidTokenError,
    SecurityError,
    TokenExpiredError,
    TokenManager,
)


# Pydantic models for request/response
class RegisterRequest(BaseModel):
    """Request model for user registration."""

    email: EmailStr
    password: str = Field(..., min_length=8)
    name: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate password meets security requirements."""
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in v):
            raise ValueError("Password must contain at least one special character")
        return v


class LoginRequest(BaseModel):
    """Request model for user login."""

    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """Request model for token refresh."""

    refresh_token: str


class LogoutRequest(BaseModel):
    """Request model for user logout."""

    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    """Request model for password reset initiation."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Request model for password reset completion."""

    token: str
    new_password: str = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate new password meets security requirements."""
        # Same validation as RegisterRequest
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in v):
            raise ValueError("Password must contain at least one special character")
        return v


class UserResponse(BaseModel):
    """Response model for user data."""

    id: UUID
    email: str
    name: str
    roles: list[str]
    permissions: list[str]
    is_active: bool
    email_verified: bool
    created_at: datetime
    updated_at: datetime


class AuthResponse(BaseModel):
    """Response model for authentication operations."""

    user: UserResponse
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenResponse(BaseModel):
    """Response model for token operations."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class MessageResponse(BaseModel):
    """Response model for simple message responses."""

    message: str


class SessionResponse(BaseModel):
    """Response model for session data."""

    id: UUID
    user_agent: Optional[str]
    ip_address: Optional[str]
    created_at: datetime
    last_used_at: datetime
    is_current: bool = False


# Security
security = HTTPBearer(auto_error=False)


# Router
auth_router = APIRouter(tags=["auth"])


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NativeAuthSettings:
    """What the router's endpoints sign tokens with and read users from.

    ``get_native_auth_router`` builds one from a ``NativeAuthProvider`` (its token
    manager, pool and schema), so the router and the provider guarding ``/graphql``
    share one secret.
    """

    token_manager: TokenManager
    db_pool: AsyncConnectionPool | None = None
    schema: str = "public"


_SETTINGS_STATE_ATTR = "fraiseql_native_auth"


def _settings_from_provider(provider: object) -> NativeAuthSettings | None:
    from fraiseql.auth.native.provider import NativeAuthProvider

    if not isinstance(provider, NativeAuthProvider):
        return None
    return NativeAuthSettings(
        token_manager=provider.token_manager,
        db_pool=provider.db_pool,
        schema=provider.schema,
    )


def _app_provider_settings() -> NativeAuthSettings | None:
    """Settings of the NativeAuthProvider given to ``create_fraiseql_app``, if any."""
    from fraiseql.fastapi.dependencies import get_auth_provider

    return _settings_from_provider(get_auth_provider())


def _settings(request: Request) -> NativeAuthSettings | None:
    """The settings bound to the router serving the request, or the app's provider's."""
    bound = getattr(request.state, _SETTINGS_STATE_ATTR, None)
    if bound is not None:
        return bound
    return _app_provider_settings()


def _request_pool(request: Request) -> AsyncConnectionPool | None:
    """The psycopg pool the endpoints take their connection from.

    The provider's pool, else ``app.state.db_pool`` when the app sets one, else the
    pool ``create_fraiseql_app`` opened.
    """
    settings = _settings(request)
    if settings is not None and settings.db_pool is not None:
        return settings.db_pool
    pool = getattr(request.app.state, "db_pool", None)
    if pool is not None:
        return pool
    from fraiseql.fastapi.dependencies import get_db_pool

    try:
        return get_db_pool()
    except RuntimeError:
        return None


# Dependency to get database connection
async def get_db(request: Request) -> AsyncGenerator[AsyncConnection]:
    """Get a database connection for the request.

    A connection a middleware put in ``request.state.db_connection`` is used as is;
    otherwise one is borrowed from the pool (see ``_request_pool``) for the request.
    """
    injected = getattr(request.state, "db_connection", None)
    if injected is not None:
        yield injected
        return

    pool = _request_pool(request)
    if pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool not initialized",
        )
    async with pool.connection() as conn:
        yield conn


# Dependency to get schema (for multi-tenant support)
async def get_schema(request: Request) -> str:
    """Get the database schema holding the auth tables (the provider's schema)."""
    settings = _settings(request)
    return settings.schema if settings is not None else "public"


# Dependency to get token manager
def get_token_manager(request: Request) -> TokenManager:
    """Get the token manager that signs and verifies this router's tokens.

    It is the one of the ``NativeAuthProvider`` the router is bound to (or the one
    given to ``create_fraiseql_app``), else one keyed by ``JWT_SECRET_KEY``. With
    neither, the request fails: there is no default key.
    """
    settings = _settings(request)
    if settings is not None:
        return settings.token_manager

    secret_key = os.environ.get("JWT_SECRET_KEY")
    if secret_key:
        return TokenManager(secret_key=secret_key)

    logger.error(
        "Native auth router has no signing key: build it with "
        "get_native_auth_router(auth_provider) or set JWT_SECRET_KEY"
    )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Native authentication is not configured",
    )


def build_native_auth_router(auth_provider: object | None = None) -> APIRouter:
    """Return the auth endpoints bound to a NativeAuthProvider.

    Args:
        auth_provider: The ``NativeAuthProvider`` whose token manager, pool and schema
            the endpoints use. Without it, the provider given to
            ``create_fraiseql_app`` is used if it is a ``NativeAuthProvider``, else a
            token manager keyed by ``JWT_SECRET_KEY``.

    Raises:
        TypeError: If ``auth_provider`` is not a ``NativeAuthProvider``.
        ValueError: If there is no provider and ``JWT_SECRET_KEY`` is unset or empty.
    """
    if auth_provider is not None:
        settings = _settings_from_provider(auth_provider)
        if settings is None:
            msg = (
                "get_native_auth_router() takes a NativeAuthProvider, got "
                f"{type(auth_provider).__name__}"
            )
            raise TypeError(msg)
    else:
        settings = _app_provider_settings()
        if settings is None:
            secret_key = os.environ.get("JWT_SECRET_KEY")
            if not secret_key:
                msg = (
                    "The native auth router needs a signing key: pass the "
                    "NativeAuthProvider (get_native_auth_router(auth_provider)), give it "
                    "to create_fraiseql_app(auth=...) first, or set JWT_SECRET_KEY."
                )
                raise ValueError(msg)
            settings = NativeAuthSettings(token_manager=TokenManager(secret_key=secret_key))

    async def bind_settings(request: Request) -> None:
        setattr(request.state, _SETTINGS_STATE_ATTR, settings)

    # Path-level dependencies run before the endpoint's own, so every dependency
    # above sees the bound settings.
    router = APIRouter()
    router.include_router(auth_router, dependencies=[Depends(bind_settings)])
    return router


# Dependency to get current user
async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncConnection, Depends(get_db)],
    schema: Annotated[str, Depends(get_schema)],
    token_manager: Annotated[TokenManager, Depends(get_token_manager)],
) -> User:
    """Get current authenticated user."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = token_manager.verify_access_token(credentials.credentials)

        async with db.cursor() as cursor:
            user = await User.get_by_id(cursor, schema, UUID(payload["sub"]))
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

        # Store session_id for later use
        user._session_id = payload.get("session_id")
        return user

    except (TokenExpiredError, InvalidTokenError, SecurityError) as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


@auth_router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    db: Annotated[AsyncConnection, Depends(get_db)],
    schema: Annotated[str, Depends(get_schema)],
    token_manager: Annotated[TokenManager, Depends(get_token_manager)],
) -> AuthResponse:
    """Register a new user."""
    # Check if email already exists
    async with db.cursor() as cursor:
        existing_user = await User.get_by_email(cursor, schema, request.email)
    if existing_user:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    # Create new user
    user = User(
        email=request.email,
        password=request.password,
        name=request.name,
        roles=["user"],
        is_active=True,
        email_verified=False,  # Email verification can be added later
    )
    async with db.cursor() as cursor:
        await user.save(cursor, schema)
        await db.commit()  # Ensure user is committed

    # Generate initial tokens to get family_id
    initial_tokens = token_manager.generate_tokens(str(user.id))

    # Store session info
    async with db.cursor() as cursor:
        await cursor.execute(
            f"""
            INSERT INTO {schema}.tb_session (fk_user, token_family, user_agent, ip_address)
            VALUES (%s, %s, %s, %s)
            RETURNING pk_session
            """,
            (user.id, initial_tokens["family_id"], None, None),
        )
        session_result = await cursor.fetchone()
        session_id = str(session_result[0]) if session_result else None
        await db.commit()  # Ensure session is committed

    # Generate final tokens with session_id
    user_claims = {"session_id": session_id} if session_id else {}
    tokens = token_manager.generate_tokens(
        str(user.id), family_id=initial_tokens["family_id"], user_claims=user_claims
    )
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    return AuthResponse(
        user=UserResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            roles=user.roles,
            permissions=user.permissions,
            is_active=user.is_active,
            email_verified=user.email_verified,
            created_at=user.created_at,
            updated_at=user.updated_at,
        ),
        access_token=access_token,
        refresh_token=refresh_token,
    )


@auth_router.post("/login")
async def login(
    request: LoginRequest,
    db: Annotated[AsyncConnection, Depends(get_db)],
    schema: Annotated[str, Depends(get_schema)],
    token_manager: Annotated[TokenManager, Depends(get_token_manager)],
) -> AuthResponse:
    """Login with email and password."""
    # Get user by email
    async with db.cursor() as cursor:
        user = await User.get_by_email(cursor, schema, request.email)
    if not user or not user.verify_password(request.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    # Generate initial tokens to get family_id
    initial_tokens = token_manager.generate_tokens(str(user.id))

    # Store session info
    async with db.cursor() as cursor:
        await cursor.execute(
            f"""
            INSERT INTO {schema}.tb_session (fk_user, token_family, user_agent, ip_address)
            VALUES (%s, %s, %s, %s)
            RETURNING pk_session
            """,
            (user.id, initial_tokens["family_id"], None, None),
        )
        session_result = await cursor.fetchone()
        session_id = str(session_result[0]) if session_result else None
        await db.commit()  # Ensure session is committed

    # Generate final tokens with session_id
    user_claims = {"session_id": session_id} if session_id else {}
    tokens = token_manager.generate_tokens(
        str(user.id), family_id=initial_tokens["family_id"], user_claims=user_claims
    )
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    return AuthResponse(
        user=UserResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            roles=user.roles,
            permissions=user.permissions,
            is_active=user.is_active,
            email_verified=user.email_verified,
            created_at=user.created_at,
            updated_at=user.updated_at,
        ),
        access_token=access_token,
        refresh_token=refresh_token,
    )


@auth_router.post("/refresh")
async def refresh_token(
    request: RefreshRequest,
    db: Annotated[AsyncConnection, Depends(get_db)],
    schema: Annotated[str, Depends(get_schema)],
    token_manager: Annotated[TokenManager, Depends(get_token_manager)],
) -> TokenResponse:
    """Refresh access token using refresh token."""
    try:
        # Verify the refresh token
        payload = token_manager.verify_refresh_token(request.refresh_token)

        # Check if token has been used before (token theft detection)
        async with db.cursor() as cursor:
            # Get the JTI from the token
            jti = payload.get("jti")

            await cursor.execute(
                f"""
                SELECT 1 FROM {schema}.tb_used_refresh_token
                WHERE token_jti = %s
                """,
                (jti,),
            )
            if await cursor.fetchone():
                # Token reuse detected - invalidate entire family
                await cursor.execute(
                    f"""
                    UPDATE {schema}.tb_session
                    SET revoked_at = NOW()
                    WHERE token_family = %s
                    """,
                    (payload["family"],),
                )
                await db.commit()  # Ensure revocation is committed
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token theft detected - all sessions revoked",
                )

            # Mark token as used
            await cursor.execute(
                f"""
                INSERT INTO {schema}.tb_used_refresh_token (token_jti, family_id)
                VALUES (%s, %s)
                """,
                (jti, payload["family"]),
            )
            await db.commit()  # Ensure the token usage is committed

            # Generate new tokens
            new_tokens = token_manager.generate_tokens(
                user_id=payload["sub"], family_id=payload["family"]
            )

            return TokenResponse(
                access_token=new_tokens["access_token"], refresh_token=new_tokens["refresh_token"]
            )

    except (TokenExpiredError, InvalidTokenError, SecurityError) as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


@auth_router.get("/me")
async def get_current_user_info(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    """Get current user information."""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        roles=current_user.roles,
        permissions=current_user.permissions,
        is_active=current_user.is_active,
        email_verified=current_user.email_verified,
        created_at=current_user.created_at,
        updated_at=current_user.updated_at,
    )


@auth_router.post("/logout")
async def logout(
    request: LogoutRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncConnection, Depends(get_db)],
    schema: Annotated[str, Depends(get_schema)],
    token_manager: Annotated[TokenManager, Depends(get_token_manager)],
) -> MessageResponse:
    """Logout and invalidate refresh token."""
    # Invalidate the refresh token family
    try:
        payload = token_manager.verify_refresh_token(request.refresh_token)

        async with db.cursor() as cursor:
            await cursor.execute(
                f"""
                UPDATE {schema}.tb_session
                SET revoked_at = NOW()
                WHERE token_family = %s
                """,
                (payload["family"],),
            )
            await db.commit()  # Ensure logout is committed

        return MessageResponse(message="Successfully logged out")

    except (TokenExpiredError, InvalidTokenError, SecurityError):
        # Even if token is invalid, return success
        return MessageResponse(message="Successfully logged out")


@auth_router.post("/forgot-password")
async def forgot_password(
    request: ForgotPasswordRequest,
    db: Annotated[AsyncConnection, Depends(get_db)],
    schema: Annotated[str, Depends(get_schema)],
) -> MessageResponse:
    """Request password reset email."""
    # Always return success to prevent email enumeration
    async with db.cursor() as cursor:
        user = await User.get_by_email(cursor, schema, request.email)

        if user and user.is_active:
            # Create reset token
            reset_token = str(uuid4())
            expires_at = datetime.now(UTC) + timedelta(hours=1)

            # Hash the reset token before storing (security best practice)
            token_hash = hashlib.sha256(reset_token.encode()).hexdigest()

            await cursor.execute(
                f"""
                INSERT INTO {schema}.tb_password_reset (fk_user, token_hash, expires_at)
                VALUES (%s, %s, %s)
                """,
                (user.id, token_hash, expires_at),
            )

        # In a real app, send email here
        # await send_password_reset_email(user.email, reset_token)

    return MessageResponse(message="If the email exists, a reset link has been sent")


@auth_router.post("/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    db: Annotated[AsyncConnection, Depends(get_db)],
    schema: Annotated[str, Depends(get_schema)],
) -> MessageResponse:
    """Reset password using reset token."""
    # Hash the incoming token to compare with stored hash
    token_hash = hashlib.sha256(request.token.encode()).hexdigest()

    # Verify reset token
    async with db.cursor() as cursor:
        await cursor.execute(
            f"""
            SELECT pr.*, u.pk_user as user_id
            FROM {schema}.tb_password_reset pr
            JOIN {schema}.tb_user u ON pr.fk_user = u.pk_user
            WHERE pr.token_hash = %s
            AND pr.expires_at > NOW()
            AND pr.used_at IS NULL
            AND u.is_active = TRUE
            """,
            (token_hash,),
        )
        result = await cursor.fetchone()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token"
            )

        # Update password
        user = await User.get_by_id(cursor, schema, result[6])  # user_id is last column
        user.set_password(request.new_password)
        await user.update(cursor, schema)

        # Mark token as used
        await cursor.execute(
            f"""
            UPDATE {schema}.tb_password_reset
            SET used_at = NOW()
            WHERE token_hash = %s
            """,
            (token_hash,),
        )

        # Invalidate all sessions for security
        await cursor.execute(
            f"""
            UPDATE {schema}.tb_session
            SET revoked_at = NOW()
            WHERE fk_user = %s
            """,
            (user.id,),
        )
        await db.commit()  # Ensure all changes are committed

    return MessageResponse(message="Password reset successfully")


@auth_router.get("/sessions")
async def list_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncConnection, Depends(get_db)],
    schema: Annotated[str, Depends(get_schema)],
) -> list[SessionResponse]:
    """List all active sessions for current user."""
    async with db.cursor() as cursor:
        await cursor.execute(
            f"""
            SELECT pk_session, user_agent, ip_address, created_at, last_active
            FROM {schema}.tb_session
            WHERE fk_user = %s
            AND revoked_at IS NULL
            ORDER BY last_active DESC
            """,
            (current_user.id,),
        )
        sessions = await cursor.fetchall()

    # Get current session ID from token
    current_session_id = getattr(current_user, "_session_id", None)

    return [
        SessionResponse(
            id=session[0],  # pk_session
            user_agent=session[1],  # user_agent
            ip_address=session[2],  # ip_address
            created_at=session[3],  # created_at
            last_used_at=session[4],  # last_active
            is_current=str(session[0]) == current_session_id,
        )
        for session in sessions
    ]


@auth_router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncConnection, Depends(get_db)],
    schema: Annotated[str, Depends(get_schema)],
) -> MessageResponse:
    """Revoke a specific session."""
    # Verify session belongs to user
    async with db.cursor() as cursor:
        await cursor.execute(
            f"""
            SELECT token_family
            FROM {schema}.tb_session
            WHERE pk_session = %s AND fk_user = %s
            """,
            (session_id, current_user.id),
        )
        result = await cursor.fetchone()

        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

        # Invalidate the session's token family
        await cursor.execute(
            f"""
            UPDATE {schema}.tb_session
            SET revoked_at = NOW()
            WHERE token_family = %s
            """,
            (result[0],),  # token_family is first column
        )
        await db.commit()  # Ensure revocation is committed

    return MessageResponse(message="Session revoked successfully")

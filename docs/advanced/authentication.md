---
title: Authentication & Authorization
description: Enterprise-grade authentication with JWT, Auth0, role-based access control, and field-level permissions
tags:
  - authentication
  - authorization
  - JWT
  - Auth0
  - RBAC
  - security
  - permissions
  - roles
---

# Authentication & Authorization

Complete guide to implementing enterprise-grade authentication and authorization in FraiseQL applications.

## Quick Start - JWT Authentication Example

```python
"""
Complete example: JWT authentication with FraiseQL.

Prerequisites:
- pip install "fraiseql<2" pyjwt cryptography
- Generate a secret key: python -c "import secrets; print(secrets.token_hex(32))"
"""

import asyncio
from datetime import datetime, timedelta
from uuid import UUID, uuid4
import jwt
import fraiseql
from fraiseql.auth import AuthProvider, UserContext, requires_auth, requires_role

# 1. Create custom JWT auth provider
class SimpleJWTProvider(AuthProvider):
    """Simple JWT authentication provider."""

    def __init__(self, secret_key: str):
        self.secret_key = secret_key
        self.algorithm = "HS256"

    async def validate_token(self, token: str) -> dict:
        """Validate and decode JWT token."""
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm]
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise ValueError("Token has expired")
        except jwt.InvalidTokenError:
            raise ValueError("Invalid token")

    async def get_user_from_token(self, token: str) -> UserContext:
        """Extract user context from token."""
        payload = await self.validate_token(token)

        return UserContext(
            user_id=UUID(payload["user_id"]),
            email=payload.get("email"),
            name=payload.get("name"),
            roles=payload.get("roles", []),
            permissions=payload.get("permissions", [])
        )

# 2. Define types with authorization
@fraiseql.type(sql_source="v_user")
class User:
    id: UUID
    name: str
    email: str

# 3. Protected queries and mutations
@fraiseql.query
@requires_auth  # ← Requires authentication
async def current_user(info) -> User:
    """Get current authenticated user."""
    user_context = info.context["user"]  # UserContext available here
    db = info.context["db"]

    return await db.fetch_one(
        "SELECT * FROM v_user WHERE data->>'id' = $1",
        str(user_context.user_id)
    )

@fraiseql.query
@requires_role("admin")  # ← Requires admin role
async def all_users(info) -> list[User]:
    """Admin-only: Get all users."""
    db = info.context["db"]
    return await db.fetch("SELECT * FROM v_user")

# 4. Set up schema with auth
async def main():
    # Create auth provider
    auth_provider = SimpleJWTProvider(secret_key="your-secret-key-here")

    # Create schema with auth
    schema = fraiseql.Schema(
        database_url="postgresql://localhost/mydb",
        auth_provider=auth_provider
    )

    # Generate test token
    token = jwt.encode(
        {
            "user_id": str(uuid4()),
            "email": "alice@example.com",
            "name": "Alice",
            "roles": ["admin"],
            "exp": datetime.utcnow() + timedelta(hours=1)
        },
        "your-secret-key-here",
        algorithm="HS256"
    )

    # Execute authenticated query
    query = """
    {
      currentUser {
        id
        name
        email
      }
    }
    """

    result = await schema.execute(
        query,
        context={
            "authorization": f"Bearer {token}"  # ← Pass token in context
        }
    )

    if result.errors:
        print(f"❌ Errors: {result.errors}")
    else:
        user = result.data['currentUser']
        print(f"✅ Authenticated as: {user['name']} ({user['email']})")

if __name__ == "__main__":
    asyncio.run(main())
```

**Expected Output:**

```
✅ Authenticated as: Alice (alice@example.com)
```

**Without Token (Unauthorized):**

```
❌ Errors: [{'message': 'Authentication required', 'locations': [...]}]
```

---

## Overview

FraiseQL provides a flexible authentication system supporting multiple providers (Auth0, custom JWT, native sessions) with fine-grained authorization through decorators and field-level permissions.

**Core Components:**

- AuthProvider interface for pluggable authentication
- UserContext structure propagated to all resolvers
- Decorators: @requires_auth, @requires_permission, @requires_role
- Token validation with JWKS
- Token revocation (in-memory and Redis)
- Session management
- Field-level authorization

## Authentication Providers

### AuthProvider Interface

All authentication providers implement the `AuthProvider` abstract base class:

```python
from abc import ABC, abstractmethod
from typing import Any

class AuthProvider(ABC):
    """Abstract base for authentication providers."""

    @abstractmethod
    async def validate_token(self, token: str) -> dict[str, Any]:
        """Validate token and return decoded payload.

        Raises:
            TokenExpiredError: If token has expired
            InvalidTokenError: If token is invalid
        """
        pass

    @abstractmethod
    async def get_user_from_token(self, token: str) -> UserContext:
        """Extract UserContext from validated token."""
        pass

    async def refresh_token(self, refresh_token: str) -> tuple[str, str]:
        """Optional: Refresh access token.

        Returns:
            Tuple of (new_access_token, new_refresh_token)
        """
        raise NotImplementedError("Token refresh not supported")

    async def revoke_token(self, token: str) -> None:
        """Optional: Revoke a token."""
        raise NotImplementedError("Token revocation not supported")
```

**Implementation Requirements:**

- Must validate token signature and expiration
- Must extract user information into UserContext
- Should log authentication events for audit
- Should handle edge cases (expired, malformed, missing claims)

## UserContext Structure

UserContext is the standardized user representation passed to all resolvers:

```python
from dataclasses import dataclass, field
from typing import Any
from fraiseql.types import ID

@dataclass
class UserContext:
    """User context available in all GraphQL resolvers."""

    user_id: ID
    email: str | None = None
    name: str | None = None
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def has_role(self, role: str) -> bool:
        """Check if user has specific role."""
        return role in self.roles

    def has_permission(self, permission: str) -> bool:
        """Check if user has specific permission."""
        return permission in self.permissions

    def has_any_role(self, roles: list[str]) -> bool:
        """Check if user has any of the specified roles."""
        return any(role in self.roles for role in roles)

    def has_any_permission(self, permissions: list[str]) -> bool:
        """Check if user has any of the specified permissions."""
        return any(perm in self.permissions for perm in permissions)

    def has_all_roles(self, roles: list[str]) -> bool:
        """Check if user has all specified roles."""
        return all(role in self.roles for role in roles)

    def has_all_permissions(self, permissions: list[str]) -> bool:
        """Check if user has all specified permissions."""
        return all(perm in self.permissions for perm in permissions)
```

**Access in Resolvers:**

```python
import fraiseql
from graphql import GraphQLResolveInfo

@fraiseql.query
async def get_my_profile(info: GraphQLResolveInfo) -> User:
    """Get current user's profile."""
    # Extract context early (standard pattern)
    user = info.context["user"]
    db = info.context["db"]
    tenant_id = info.context["tenant_id"]

    if not user:
        raise AuthenticationError("Not authenticated")

    # Use repository to fetch user data
    return await db.find_one("v_user", id=user.user_id)
```

## Auth0 Provider

### Configuration

Complete Auth0 integration with JWT validation and JWKS caching:

```python
from fraiseql.auth import Auth0Provider, Auth0Config
from fraiseql.fastapi import create_fraiseql_app

# Method 1: Direct provider instantiation
auth_provider = Auth0Provider(
    domain="your-tenant.auth0.com",
    api_identifier="https://api.yourapp.com",
    algorithms=["RS256"],
    cache_jwks=True  # Cache JWKS keys for 1 hour
)

# Method 2: Using config object
auth_config = Auth0Config(
    domain="your-tenant.auth0.com",
    api_identifier="https://api.yourapp.com",
    client_id="your_client_id",  # Optional: for Management API
    client_secret="your_client_secret",  # Optional: for Management API
    algorithms=["RS256"]
)

auth_provider = auth_config.create_provider()

# Create app with authentication
app = create_fraiseql_app(
    types=[User, Post, Order],
    auth_provider=auth_provider
)
```

### Environment Variables

```bash
# .env file
FRAISEQL_AUTH_ENABLED=true
FRAISEQL_AUTH_PROVIDER=auth0
FRAISEQL_AUTH0_DOMAIN=your-tenant.auth0.com
FRAISEQL_AUTH0_API_IDENTIFIER=https://api.yourapp.com
FRAISEQL_AUTH0_ALGORITHMS=["RS256"]
```

### Token Structure

Auth0 JWT tokens must contain:

```json
{
  "sub": "auth0|507f1f77bcf86cd799439011",
  "email": "user@example.com",
  "name": "John Doe",
  "permissions": ["users:read", "users:write", "posts:create"],
  "https://api.yourapp.com/roles": ["user", "editor"],
  "aud": "https://api.yourapp.com",
  "iss": "https://your-tenant.auth0.com/",
  "iat": 1516239022,
  "exp": 1516325422
}
```

**Custom Claims:**

- Roles: `https://{api_identifier}/roles` (namespaced)
- Permissions: `permissions` or `scope` (standard OAuth2)
- Metadata: Any additional claims

### Token Validation

Auth0Provider automatically validates:

```python
# Automatic validation process:
# 1. Fetch JWKS from https://your-tenant.auth0.com/.well-known/jwks.json
# 2. Verify signature using RS256 algorithm
# 3. Check audience matches api_identifier
# 4. Check issuer matches https://your-tenant.auth0.com/
# 5. Check token not expired (exp claim)
# 6. Extract user information into UserContext

async def validate_token(self, token: str) -> dict[str, Any]:
    """Validate Auth0 JWT token."""
    try:
        # Get signing key from JWKS (cached)
        signing_key = self.jwks_client.get_signing_key_from_jwt(token)

        # Decode and verify
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=self.algorithms,
            audience=self.api_identifier,
            issuer=self.issuer,
        )

        return payload

    except jwt.ExpiredSignatureError:
        raise TokenExpiredError("Token has expired")
    except jwt.InvalidTokenError as e:
        raise InvalidTokenError(f"Invalid token: {e}")
```

### Management API Integration

Access Auth0 Management API for user profile, roles, permissions:

```python
# Fetch full user profile
user_profile = await auth_provider.get_user_profile(
    user_id="auth0|507f1f77bcf86cd799439011",
    access_token=management_api_token
)
# Returns: {"user_id": "...", "email": "...", "name": "...", ...}

# Fetch user roles
roles = await auth_provider.get_user_roles(
    user_id="auth0|507f1f77bcf86cd799439011",
    access_token=management_api_token
)
# Returns: [{"id": "rol_...", "name": "admin", "description": "..."}]

# Fetch user permissions
permissions = await auth_provider.get_user_permissions(
    user_id="auth0|507f1f77bcf86cd799439011",
    access_token=management_api_token
)
# Returns: [{"permission_name": "users:write", "resource_server_identifier": "..."}]
```

**Management API Token:**

```python
import httpx

async def get_management_api_token(domain: str, client_id: str, client_secret: str) -> str:
    """Get Management API access token."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://{domain}/oauth/token",
            json={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "audience": f"https://{domain}/api/v2/"
            }
        )
        return response.json()["access_token"]
```

## Custom JWT Provider

Implement custom JWT authentication for non-Auth0 providers:

```python
from fraiseql.auth import AuthProvider, UserContext, InvalidTokenError, TokenExpiredError
import jwt
from typing import Any

class CustomJWTProvider(AuthProvider):
    """Custom JWT authentication provider."""

    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        issuer: str | None = None,
        audience: str | None = None
    ):
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.issuer = issuer
        self.audience = audience

    async def validate_token(self, token: str) -> dict[str, Any]:
        """Validate JWT token with secret key."""
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                audience=self.audience,
                issuer=self.issuer,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_aud": self.audience is not None,
                    "verify_iss": self.issuer is not None
                }
            )
            return payload

        except jwt.ExpiredSignatureError:
            raise TokenExpiredError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise InvalidTokenError(f"Invalid token: {e}")

    async def get_user_from_token(self, token: str) -> UserContext:
        """Extract UserContext from token payload."""
        payload = await self.validate_token(token)

        return UserContext(
            user_id=UUID(payload.get("sub", payload.get("user_id"))),
            email=payload.get("email"),
            name=payload.get("name"),
            roles=payload.get("roles", []),
            permissions=payload.get("permissions", []),
            metadata={
                k: v for k, v in payload.items()
                if k not in ["sub", "user_id", "email", "name", "roles", "permissions", "exp", "iat", "iss", "aud"]
            }
        )
```

**Usage:**

```python
from fraiseql.fastapi import create_fraiseql_app

# Create provider
auth_provider = CustomJWTProvider(
    secret_key="your-secret-key-keep-secure",
    algorithm="HS256",
    issuer="https://yourapp.com",
    audience="https://api.yourapp.com"
)

# Create app
app = create_fraiseql_app(
    types=[User, Post],
    auth_provider=auth_provider
)
```

## Native Authentication

FraiseQL includes native username/password authentication with session management:

```python
from fraiseql.auth.native import (
    NativeAuthProvider,
    NativeAuthFactory,
    UserRepository,
    create_auth_router
)
from fraiseql.types import ID

# 1. Implement user repository
class PostgresUserRepository(UserRepository):
    """User repository backed by PostgreSQL."""

    async def get_user_by_username(self, username: str) -> User | None:
        return await db.find_one("v_user", "user", None, username=username)

    async def get_user_by_id(self, user_id: str) -> User | None:
        return await db.find_one("v_user", "user", None, id=user_id)

    async def create_user(self, username: str, password_hash: str, email: str) -> User:
        result = await db.execute_function("fn_create_user", {
            "username": username,
            "password_hash": password_hash,
            "email": email
        })
        return await db.find_one("v_user", "user", None, id=result["id"])

# 2. Create provider
user_repo = PostgresUserRepository()

auth_provider = NativeAuthFactory.create_provider(
    user_repository=user_repo,
    secret_key="your-secret-key",
    access_token_ttl=3600,  # 1 hour
    refresh_token_ttl=2592000  # 30 days
)

# 3. Mount authentication routes
auth_router = create_auth_router(auth_provider)
app.include_router(auth_router, prefix="/auth")
```

**Authentication Endpoints:**

```bash
# Register
POST /auth/register
{
  "username": "john",
  "password": "secure_password",
  "email": "john@example.com"
}

# Login
POST /auth/login
{
  "username": "john",
  "password": "secure_password"
}
# Returns: {"access_token": "...", "refresh_token": "...", "token_type": "bearer"}

# Refresh token
POST /auth/refresh
{
  "refresh_token": "..."
}
# Returns: {"access_token": "...", "refresh_token": "..."}

# Logout
POST /auth/logout
Authorization: Bearer <access_token>
```

## Authorization Decorators

### @requires_auth

Require authentication for any resolver:

```python
import fraiseql, mutation
from fraiseql.auth import requires_auth

@fraiseql.query
@requires_auth
async def get_my_orders(info) -> list[Order]:
    """Get current user's orders - requires authentication."""
    user = info.context["user"]  # Guaranteed to exist
    return await fetch_user_orders(user.user_id)

@fraiseql.mutation
@requires_auth
async def update_profile(info, name: str, email: str) -> User:
    """Update user profile - requires authentication."""
    user = info.context["user"]
    return await update_user_profile(user.user_id, name, email)
```

**Behavior:**

- Checks `info.context["user"]` exists and is UserContext instance
- Raises GraphQLError with code "UNAUTHENTICATED" if not authenticated
- Resolver only executes if user is authenticated

### @requires_permission

Require specific permission:

```python
import fraiseql
from fraiseql.auth import requires_permission

@fraiseql.mutation
@requires_permission("orders:create")
async def create_order(info, product_id: str, quantity: int) -> Order:
    """Create order - requires orders:create permission."""
    user = info.context["user"]
    return await create_order_for_user(user.user_id, product_id, quantity)

@fraiseql.mutation
@requires_permission("users:delete")
async def delete_user(info, user_id: str) -> bool:
    """Delete user - requires users:delete permission."""
    await delete_user_by_id(user_id)
    return True
```

**Permission Format:**

- Convention: `resource:action` (e.g., "orders:read", "users:write")
- Flexible: Any string format works
- Case-sensitive: "Orders:Read" != "orders:read"

### @requires_role

Require specific role:

```python
import fraiseql, mutation
from fraiseql.auth import requires_role

@fraiseql.query
@requires_role("admin")
async def get_all_users(info) -> list[User]:
    """Get all users - admin only."""
    return await fetch_all_users()

@fraiseql.mutation
@requires_role("moderator")
async def ban_user(info, user_id: str, reason: str) -> bool:
    """Ban user - moderator only."""
    await ban_user_by_id(user_id, reason)
    return True
```

### @requires_any_permission

Require any of multiple permissions:

```python
import fraiseql
from fraiseql.auth import requires_any_permission

@fraiseql.mutation
@requires_any_permission("orders:write", "admin:all")
async def update_order(info, order_id: str, status: str) -> Order:
    """Update order - requires orders:write OR admin:all permission."""
    return await update_order_status(order_id, status)
```

### @requires_any_role

Require any of multiple roles:

```python
import fraiseql
from fraiseql.auth import requires_any_role

@fraiseql.mutation
@requires_any_role("admin", "moderator")
async def moderate_content(info, content_id: str, action: str) -> bool:
    """Moderate content - admin or moderator."""
    await moderate_content_by_id(content_id, action)
    return True
```

### Combining Decorators

Stack decorators for complex authorization:

```python
import fraiseql
from fraiseql.auth import requires_auth, requires_permission

@fraiseql.mutation
@requires_auth
@requires_permission("orders:refund")
async def refund_order(info, order_id: str, reason: str) -> Order:
    """Refund order - requires authentication and orders:refund permission."""
    user = info.context["user"]

    # Additional custom checks
    order = await fetch_order(order_id)
    if order.user_id != user.user_id and not user.has_role("admin"):
        raise GraphQLError("Can only refund your own orders")

    return await process_refund(order_id, reason)
```

**Decorator Order:**

- Outermost decorator executes first
- Recommended: @fraiseql.mutation/@fraiseql.query first, then auth decorators
- Auth checks happen before resolver logic

## Token Revocation

Support logout and session invalidation with token revocation:

### In-Memory Store (Development)

```python
from fraiseql.auth import (
    InMemoryRevocationStore,
    TokenRevocationService,
    RevocationConfig
)

# Create revocation store
revocation_store = InMemoryRevocationStore()

# Create revocation service
revocation_service = TokenRevocationService(
    store=revocation_store,
    config=RevocationConfig(
        enabled=True,
        check_revocation=True,
        ttl=86400,  # 24 hours
        cleanup_interval=3600  # Clean expired every hour
    )
)

# Start cleanup task in application lifecycle
@app.on_event("startup")
async def startup():
    await revocation_service.start()

@app.on_event("shutdown")
async def shutdown():
    await revocation_service.stop()
```

### Redis Store (Production)

```python
from fraiseql.auth import RedisRevocationStore, TokenRevocationService
import redis.asyncio as redis

# Create Redis client
redis_client = redis.from_url("redis://localhost:6379/0")

# Create revocation store
revocation_store = RedisRevocationStore(
    redis_client=redis_client,
    ttl=86400  # 24 hours
)

# Create revocation service
revocation_service = TokenRevocationService(
    store=revocation_store,
    config=RevocationConfig(
        enabled=True,
        check_revocation=True,
        ttl=86400
    )
)
```

### Integration with Auth Provider

```python
from fraiseql.auth import Auth0ProviderWithRevocation

# Auth0 with revocation support
auth_provider = Auth0ProviderWithRevocation(
    domain="your-tenant.auth0.com",
    api_identifier="https://api.yourapp.com",
    revocation_service=revocation_service
)

# Usage in resolver or endpoint:
async def logout_user(token_payload, user_id: str):
    # Revoke specific token
    await auth_provider.logout(token_payload)

    # Or revoke all user tokens (logout all sessions)
    await auth_provider.logout_all_sessions(user_id)
```

### Logout Endpoint

```python
from fastapi import APIRouter, Header, HTTPException
from fraiseql.auth import AuthenticationError

router = APIRouter()

@router.post("/logout")
async def logout(authorization: str = Header(...)):
    """Logout current session."""
    try:
        # Extract token
        token = authorization.replace("Bearer ", "")

        # Validate and decode
        payload = await auth_provider.validate_token(token)

        # Revoke token
        await auth_provider.logout(payload)

        return {"message": "Logged out successfully"}

    except AuthenticationError:
        raise HTTPException(status_code=401, detail="Invalid token")

@router.post("/logout-all")
async def logout_all_sessions(authorization: str = Header(...)):
    """Logout all sessions for current user."""
    try:
        token = authorization.replace("Bearer ", "")
        payload = await auth_provider.validate_token(token)
        user_id = payload["sub"]

        # Revoke all user tokens
        await auth_provider.logout_all_sessions(user_id)

        return {"message": "All sessions logged out"}

    except AuthenticationError:
        raise HTTPException(status_code=401, detail="Invalid token")
```

**Token Requirements:**

- Tokens must include `jti` (JWT ID) claim for revocation tracking
- Tokens must include `sub` (subject) claim for user identification

## Session Management

### Session Variables

Store user-specific state in session:

```python
import fraiseql

@fraiseql.query
async def get_cart(info) -> Cart:
    """Get user's shopping cart from session."""
    user = info.context["user"]
    session = info.context.get("session", {})

    cart_id = session.get(f"cart:{user.user_id}")
    if not cart_id:
        # Create new cart
        cart = await create_cart(user.user_id)
        session[f"cart:{user.user_id}"] = cart.id
    else:
        cart = await fetch_cart(cart_id)

    return cart
```

### Session Middleware

```python
from starlette.middleware.sessions import SessionMiddleware

app.add_middleware(
    SessionMiddleware,
    secret_key="your-session-secret-key",
    session_cookie="fraiseql_session",
    max_age=86400,  # 24 hours
    same_site="lax",
    https_only=True  # Production only
)
```

## Field-Level Authorization

Restrict access to specific fields based on roles/permissions:

```python
import fraiseql
import fraiseql_
from fraiseql.security import authorize_field, any_permission
from fraiseql.types import ID

@type_
class User:
    id: ID
    name: str
    email: str

    # Only admins or user themselves can see email
    @authorize_field(lambda user, info: (
        info.context["user"].user_id == user.id or
        info.context["user"].has_role("admin")
    ))
    async def email(self) -> str:
        return self._email

    # Only admins can see internal notes
    @authorize_field(any_permission("admin:all"))
    async def internal_notes(self) -> str | None:
        return self._internal_notes
```

**Authorization Patterns:**

```python
# Permission-based
@authorize_field(lambda obj, info: info.context["user"].has_permission("users:read_pii"))
async def ssn(self) -> str:
    return self._ssn

# Role-based
@authorize_field(lambda obj, info: info.context["user"].has_role("admin"))
async def audit_log(self) -> list[AuditEvent]:
    return self._audit_log

# Owner-based
@authorize_field(lambda order, info: order.user_id == info.context["user"].user_id)
async def payment_details(self) -> PaymentDetails:
    return self._payment_details

# Combined
@authorize_field(lambda obj, info: (
    info.context["user"].has_permission("orders:read_all") or
    obj.user_id == info.context["user"].user_id
))
async def internal_status(self) -> str:
    return self._internal_status
```

## Multi-Provider Setup

Support multiple authentication methods simultaneously:

```python
from fraiseql.auth import Auth0Provider, CustomJWTProvider
from fraiseql.fastapi import create_fraiseql_app

class MultiAuthProvider:
    """Support multiple authentication providers."""

    def __init__(self):
        self.providers = {
            "auth0": Auth0Provider(
                domain="tenant.auth0.com",
                api_identifier="https://api.app.com"
            ),
            "api_key": CustomJWTProvider(
                secret_key="api-key-secret",
                algorithm="HS256"
            )
        }

    async def validate_token(self, token: str) -> dict:
        """Try each provider until one succeeds."""
        errors = []

        for name, provider in self.providers.items():
            try:
                return await provider.validate_token(token)
            except Exception as e:
                errors.append(f"{name}: {e}")

        raise InvalidTokenError(f"All providers failed: {errors}")

    async def get_user_from_token(self, token: str) -> UserContext:
        """Extract user from first successful provider."""
        payload = await self.validate_token(token)

        # Determine provider from token and extract user
        if "iss" in payload and "auth0.com" in payload["iss"]:
            return await self.providers["auth0"].get_user_from_token(token)
        else:
            return await self.providers["api_key"].get_user_from_token(token)
```

## Security Best Practices

### Token Security

**DO:**

- Use RS256 for Auth0 (asymmetric keys)
- Use HS256 for internal services (symmetric keys)
- Rotate secret keys periodically
- Set appropriate token expiration (1 hour for access, 30 days for refresh)
- Include `jti` claim for revocation tracking
- Validate `aud` and `iss` claims

**DON'T:**

- Store tokens in localStorage (use httpOnly cookies or memory)
- Use weak secret keys (minimum 32 bytes)
- Set excessive expiration times
- Skip signature verification
- Log tokens in error messages

### Permission Design

**Hierarchical Permissions:**

```python
# Resource-based
"orders:read"       # Read orders
"orders:write"      # Create/update orders
"orders:delete"     # Delete orders
"orders:*"          # All order permissions

# Scope-based
"users:read:self"   # Read own user
"users:read:team"   # Read team users
"users:read:all"    # Read all users

# Admin override
"admin:all"         # All permissions
```

### Role-Based Access Control (RBAC)

```python
import fraiseql

# Define roles with associated permissions
ROLES = {
    "user": [
        "orders:read:self",
        "orders:write:self",
        "profile:read:self",
        "profile:write:self"
    ],
    "manager": [
        "orders:read:team",
        "orders:write:team",
        "users:read:team",
        "reports:read:team"
    ],
    "admin": [
        "admin:all"
    ]
}

# Check in resolver
@fraiseql.mutation
async def delete_order(info, order_id: str) -> bool:
    user = info.context["user"]

    if not user.has_any_permission(["orders:delete", "admin:all"]):
        raise GraphQLError("Insufficient permissions")

    order = await fetch_order(order_id)

    # Owners can delete own orders
    if order.user_id != user.user_id and not user.has_permission("admin:all"):
        raise GraphQLError("Can only delete your own orders")

    await delete_order_by_id(order_id)
    return True
```

### Audit Logging

Log all authentication and authorization events:

```python
from fraiseql.audit import get_security_logger, SecurityEventType

security_logger = get_security_logger()

# Log successful authentication
security_logger.log_auth_success(
    user_id=user.user_id,
    user_email=user.email,
    metadata={"provider": "auth0", "roles": user.roles}
)

# Log failed authentication
security_logger.log_auth_failure(
    reason="Invalid token",
    metadata={"token_type": "bearer", "error": str(error)}
)

# Log authorization failure
security_logger.log_event(
    SecurityEvent(
        event_type=SecurityEventType.AUTH_PERMISSION_DENIED,
        severity=SecurityEventSeverity.WARNING,
        user_id=user.user_id,
        metadata={"required_permission": "orders:delete", "resource": order_id}
    )
)
```

## Next Steps

- [Security Example](../../examples/security/) - Complete authentication implementation
- [Multi-Tenancy](multi-tenancy.md) - Tenant isolation and context propagation
- [Field-Level Authorization](../core/queries-and-mutations.md) - Advanced authorization patterns
- [Security Best Practices](../production/security.md) - Production security hardening
- [Monitoring](../production/monitoring.md) - Authentication metrics and alerts

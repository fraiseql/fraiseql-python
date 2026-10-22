"""Authentication module for FraiseQL."""

from fraiseql.auth.auth0 import Auth0Config, Auth0Provider
from fraiseql.auth.auth0_with_revocation import Auth0ProviderWithRevocation
from fraiseql.auth.base import AuthProvider, UserContext
from fraiseql.auth.decorators import (
    requires_any_permission,
    requires_any_role,
    requires_auth,
    requires_permission,
    requires_role,
)
from fraiseql.auth.token_revocation import (
    InMemoryRevocationStore,
    PostgreSQLRevocationStore,
    RevocationConfig,
    TokenRevocationMixin,
    TokenRevocationService,
)

__all__ = [
    "Auth0Config",
    "Auth0Provider",
    "Auth0ProviderWithRevocation",
    "AuthProvider",
    "InMemoryRevocationStore",
    "PostgreSQLRevocationStore",
    "RevocationConfig",
    "TokenRevocationMixin",
    "TokenRevocationService",
    "UserContext",
    "requires_any_permission",
    "requires_any_role",
    "requires_auth",
    "requires_permission",
    "requires_role",
]

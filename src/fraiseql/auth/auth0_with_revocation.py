"""Auth0 provider with token revocation support."""

from typing import Any, Optional

from .auth0 import Auth0Provider
from .token_revocation import TokenRevocationMixin, TokenRevocationService


class Auth0ProviderWithRevocation(TokenRevocationMixin, Auth0Provider):
    """Auth0 provider enhanced with token revocation capabilities.

    This provider extends the standard Auth0Provider to add token revocation
    support, allowing tokens to be invalidated before they expire.

    Example:
        ```python
        from fraiseql.auth import Auth0ProviderWithRevocation
        from fraiseql.auth.token_revocation import (
            InMemoryRevocationStore,
            PostgreSQLRevocationStore,
            TokenRevocationService,
            RevocationConfig
        )

        # Create revocation store (in-memory for dev, PostgreSQL for production)
        if production:
            store = PostgreSQLRevocationStore(pool)  # a psycopg AsyncConnectionPool
        else:
            store = InMemoryRevocationStore()

        # Create revocation service
        revocation_service = TokenRevocationService(
            store=store,
            config=RevocationConfig(enabled=True)
        )

        # Create Auth0 provider with revocation
        auth_provider = Auth0ProviderWithRevocation(
            domain="myapp.auth0.com",
            api_identifier="https://api.myapp.com",
            revocation_service=revocation_service
        )

        # Start the service (enables cleanup tasks)
        await revocation_service.start()
        ```
    """

    def __init__(
        self,
        domain: str,
        api_identifier: str,
        algorithms: list[str] | None = None,
        *,
        cache_jwks: bool = True,
        revocation_service: Optional[TokenRevocationService] = None,
    ) -> None:
        """Initialize Auth0 provider with revocation support.

        Args:
            domain: Auth0 domain (e.g., "myapp.auth0.com")
            api_identifier: API identifier/audience
            algorithms: Allowed algorithms (defaults to ["RS256"])
            cache_jwks: Whether to cache JWKS keys
            revocation_service: Token revocation service instance
        """
        super().__init__(
            domain=domain,
            api_identifier=api_identifier,
            algorithms=algorithms,
            cache_jwks=cache_jwks,
        )
        self.revocation_service = revocation_service

    async def validate_token(self, token: str) -> dict[str, Any]:
        """Validate token with revocation check.

        This overrides the mixin's validate_token to use the proper
        Auth0Provider validation method.

        Args:
            token: JWT token to validate

        Returns:
            Decoded token payload

        Raises:
            TokenExpiredError: If token has expired
            InvalidTokenError: If token is invalid or revoked
        """
        # The mixin checks revocation around _original_validate_token (below)
        return await TokenRevocationMixin.validate_token(self, token)

    async def _original_validate_token(self, token: str) -> dict[str, Any]:
        """Auth0's own validation, which the mixin's revocation check wraps.

        Named explicitly: super().validate_token here is the mixin's, which would
        call back into this method forever.
        """
        return await Auth0Provider.validate_token(self, token)

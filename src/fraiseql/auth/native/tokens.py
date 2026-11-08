"""JWT token management for native authentication."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import jwt
from psycopg import AsyncCursor


class TokenExpiredError(Exception):
    """Raised when a token has expired."""


class InvalidTokenError(Exception):
    """Raised when a token is invalid."""


class SecurityError(Exception):
    """Raised when a security violation is detected."""


class TokenManager:
    """Manages JWT tokens for authentication."""

    def __init__(
        self,
        secret_key: str,
        access_token_ttl: timedelta = timedelta(minutes=15),
        refresh_token_ttl: timedelta = timedelta(days=30),
        algorithm: str = "HS256",
    ) -> None:
        """Initialize TokenManager.

        Args:
            secret_key: Secret key for signing tokens
            access_token_ttl: Access token time-to-live
            refresh_token_ttl: Refresh token time-to-live
            algorithm: JWT signing algorithm
        """
        if not secret_key:
            raise ValueError("TokenManager needs a non-empty secret_key")
        self.secret_key = secret_key
        self.access_token_ttl = access_token_ttl
        self.refresh_token_ttl = refresh_token_ttl
        self.algorithm = algorithm

    def create_token_family(self, user_id: str) -> str:
        """Create a new token family for tracking token lineage.

        Args:
            user_id: User ID (unused but kept for API compatibility)

        Returns:
            UUID string for the token family
        """
        return str(uuid.uuid4())

    def generate_tokens(
        self,
        user_id: str,
        family_id: Optional[str] = None,
        user_claims: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Generate access and refresh tokens.

        Args:
            user_id: User ID to encode in token
            family_id: Token family ID for refresh token tracking
            user_claims: Additional claims to include in access token

        Returns:
            Dictionary with access_token, refresh_token, family_id, and expires_at
        """
        if not family_id:
            family_id = self.create_token_family(user_id)

        now = datetime.now(UTC)

        # Access token with user data
        access_payload = {
            "sub": user_id,
            "type": "access",
            "exp": now + self.access_token_ttl,
            "iat": now,
            "jti": str(uuid.uuid4()),
        }

        # Add user claims to access token
        if user_claims:
            access_payload.update(user_claims)

        # Refresh token with family tracking
        refresh_payload = {
            "sub": user_id,
            "type": "refresh",
            "family": family_id,
            "exp": now + self.refresh_token_ttl,
            "iat": now,
            "jti": str(uuid.uuid4()),
        }

        access_token = jwt.encode(access_payload, self.secret_key, algorithm=self.algorithm)
        refresh_token = jwt.encode(refresh_payload, self.secret_key, algorithm=self.algorithm)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "family_id": family_id,
            "expires_at": access_payload["exp"],
        }

    def verify_access_token(self, token: str) -> dict[str, Any]:
        """Verify and decode an access token.

        Args:
            token: JWT access token

        Returns:
            Decoded token payload

        Raises:
            TokenExpiredError: If token is expired
            InvalidTokenError: If token is invalid
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])

            # Verify it's an access token
            if payload.get("type") != "access":
                raise InvalidTokenError("Invalid token type")

            return payload

        except jwt.ExpiredSignatureError:
            raise TokenExpiredError("Access token has expired")
        except (jwt.InvalidTokenError, KeyError) as e:
            raise InvalidTokenError(f"Invalid access token: {e!s}")

    def verify_refresh_token(self, token: str) -> dict[str, Any]:
        """Verify and decode a refresh token.

        Args:
            token: JWT refresh token

        Returns:
            Decoded token payload

        Raises:
            TokenExpiredError: If token is expired
            InvalidTokenError: If token is invalid
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])

            # Verify it's a refresh token
            if payload.get("type") != "refresh":
                raise InvalidTokenError("Invalid token type")

            return payload

        except jwt.ExpiredSignatureError:
            raise TokenExpiredError("Refresh token has expired")
        except (jwt.InvalidTokenError, KeyError) as e:
            raise InvalidTokenError(f"Invalid refresh token: {e!s}")

    async def rotate_refresh_token(
        self, old_token: str, cursor: AsyncCursor, schema: str
    ) -> dict[str, Any]:
        """Rotate refresh token and detect token theft.

        Args:
            old_token: Current refresh token
            cursor: Database cursor
            schema: Database schema

        Returns:
            New token set

        Raises:
            SecurityError: If token reuse is detected
            TokenExpiredError: If token is expired
            InvalidTokenError: If token is invalid
        """
        # Verify the old token
        payload = self.verify_refresh_token(old_token)

        # Check if token was already used
        await cursor.execute(
            f"""
            SELECT token_jti FROM {schema}.tb_used_refresh_token
            WHERE token_jti = %s
        """,
            (payload["jti"],),
        )

        used_token = await cursor.fetchone()

        if used_token:
            # Token theft detected! Invalidate entire family
            await self.invalidate_token_family(payload["family"], cursor, schema)
            raise SecurityError("Token reuse detected - possible theft")

        # Mark token as used
        await cursor.execute(
            f"""
            INSERT INTO {schema}.tb_used_refresh_token (token_jti, family_id)
            VALUES (%s, %s)
        """,
            (payload["jti"], payload["family"]),
        )

        # Generate new tokens with same family
        return self.generate_tokens(payload["sub"], payload["family"])

    async def invalidate_token_family(
        self, family_id: str, cursor: AsyncCursor, schema: str
    ) -> None:
        """Invalidate all tokens in a family.

        Args:
            family_id: Token family ID
            cursor: Database cursor
            schema: Database schema
        """
        # Revoke all sessions in this family
        await cursor.execute(
            f"""
            UPDATE {schema}.tb_session
            SET revoked_at = CURRENT_TIMESTAMP
            WHERE token_family = %s AND revoked_at IS NULL
        """,
            (family_id,),
        )

    def extract_user_id(self, token: str) -> Optional[str]:
        """Extract user ID from token without full verification.

        This is useful for logging or non-security-critical operations.

        Args:
            token: JWT token

        Returns:
            User ID or None if extraction fails
        """
        try:
            # Decode without verification (for expired tokens)
            payload = jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
            return payload.get("sub")
        except Exception:
            return None

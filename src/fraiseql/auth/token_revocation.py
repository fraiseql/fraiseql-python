"""Token revocation mechanism for FraiseQL.

This module provides functionality to revoke JWT tokens before they expire,
with both PostgreSQL and in-memory storage backends.
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Protocol

from fraiseql.audit import get_security_logger
from fraiseql.audit.security_logger import SecurityEvent, SecurityEventSeverity, SecurityEventType

from .base import InvalidTokenError

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

try:
    from psycopg_pool import AsyncConnectionPool  # noqa: TC002

    PSYCOPG_AVAILABLE = True
except ImportError:
    PSYCOPG_AVAILABLE = False

logger = logging.getLogger(__name__)


class RevocationStore(Protocol):
    """Protocol for token revocation stores."""

    async def revoke_token(self, token_id: str, user_id: str) -> None:
        """Revoke a specific token."""
        ...

    async def is_revoked(self, token_id: str) -> bool:
        """Check if a token is revoked."""
        ...

    async def revoke_all_user_tokens(self, user_id: str) -> None:
        """Revoke all tokens for a user."""
        ...

    async def revoked_before(self, user_id: str) -> float | None:
        """Return when all of a user's tokens were last revoked (a Unix timestamp).

        Tokens of that user issued before it are revoked. None when no such
        revocation is active. Optional: without it, only token ids are checked.
        """
        ...

    async def cleanup_expired(self) -> int:
        """Clean up expired revocations. Returns number cleaned."""
        ...

    async def get_revoked_count(self) -> int:
        """Get count of revoked tokens."""
        ...


class InMemoryRevocationStore:
    """In-memory token revocation store for development/testing."""

    def __init__(self) -> None:
        """Initialize in-memory store."""
        # Map token_id to expiry timestamp
        self._revoked_tokens: dict[str, float] = {}
        # Map user_id to set of token_ids
        self._user_tokens: dict[str, set[str]] = defaultdict(set)
        # Map user_id to (revoked_before, expiry) from revoke_all_user_tokens
        self._user_cutoffs: dict[str, tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    async def revoke_token(self, token_id: str, user_id: str) -> None:
        """Revoke a specific token."""
        async with self._lock:
            # Store with expiry time (could be from token exp claim)
            # For now, use a default TTL of 24 hours
            expiry_time = time.time() + 86400
            self._revoked_tokens[token_id] = expiry_time
            self._user_tokens[user_id].add(token_id)

            logger.info("Revoked token %s for user %s", token_id, user_id)

    async def is_revoked(self, token_id: str) -> bool:
        """Check if a token is revoked."""
        async with self._lock:
            if token_id not in self._revoked_tokens:
                return False

            # Check if still valid
            expiry = self._revoked_tokens[token_id]
            if time.time() > expiry:
                # Expired, remove it
                del self._revoked_tokens[token_id]
                return False

            return True

    async def revoke_all_user_tokens(self, user_id: str) -> None:
        """Revoke all tokens for a user: every token issued before now."""
        async with self._lock:
            now = time.time()
            expiry_time = now + 86400
            self._user_cutoffs[user_id] = (now, expiry_time)

            # Tokens revoked one by one stay revoked as long as the cutoff
            user_tokens = self._user_tokens.get(user_id, set())
            for token_id in user_tokens:
                self._revoked_tokens[token_id] = expiry_time

            logger.info("Revoked all tokens for user %s", user_id)

    async def revoked_before(self, user_id: str) -> float | None:
        """Return when all of a user's tokens were last revoked, if still active."""
        async with self._lock:
            cutoff = self._user_cutoffs.get(user_id)
            if cutoff is None:
                return None

            revoked_before, expiry = cutoff
            if time.time() > expiry:
                del self._user_cutoffs[user_id]
                return None

            return revoked_before

    async def cleanup_expired(self) -> int:
        """Clean up expired revocations."""
        async with self._lock:
            current_time = time.time()
            expired = [
                token_id
                for token_id, expiry in self._revoked_tokens.items()
                if current_time > expiry
            ]

            for token_id in expired:
                del self._revoked_tokens[token_id]
                # Clean from user mappings
                for user_tokens in self._user_tokens.values():
                    user_tokens.discard(token_id)

            # Clean empty user entries
            empty_users = [user_id for user_id, tokens in self._user_tokens.items() if not tokens]
            for user_id in empty_users:
                del self._user_tokens[user_id]

            expired_cutoffs = [
                user_id
                for user_id, (_, expiry) in self._user_cutoffs.items()
                if current_time > expiry
            ]
            for user_id in expired_cutoffs:
                del self._user_cutoffs[user_id]

            return len(expired) + len(expired_cutoffs)

    async def get_revoked_count(self) -> int:
        """Get count of revoked tokens."""
        async with self._lock:
            return len(self._revoked_tokens)


class PostgreSQLRevocationStore:
    """PostgreSQL-based token revocation store for production."""

    def __init__(
        self,
        pool: "AsyncConnectionPool",
        table_name: str = "tb_token_revocation",
    ) -> None:
        """Initialize PostgreSQL revocation store.

        Args:
            pool: AsyncConnectionPool instance
            table_name: Name of revocation table
        """
        if not PSYCOPG_AVAILABLE:
            msg = "psycopg and psycopg_pool required for PostgreSQL revocation store"
            raise ImportError(msg)

        self.pool = pool
        self.table_name = table_name
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """Ensure revocation table exists."""
        if self._initialized:
            return

        async with self.pool.connection() as conn, conn.cursor() as cur:
            # Create revocation table
            await cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    token_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    revoked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL
                )
            """
            )

            # Create index on user_id for batch revocations
            await cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {self.table_name}_user_idx
                ON {self.table_name} (user_id)
            """
            )

            # Create index on expires_at for efficient cleanup
            await cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {self.table_name}_expires_idx
                ON {self.table_name} (expires_at)
            """
            )

            await conn.commit()
            self._initialized = True
            logger.info("Initialized PostgreSQL revocation table: %s", self.table_name)

    async def revoke_token(self, token_id: str, user_id: str) -> None:
        """Revoke a specific token."""
        await self._ensure_initialized()

        # Default expiry: 24 hours from now
        expiry_time = time.time() + 86400

        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                f"""
                INSERT INTO {self.table_name} (token_id, user_id, expires_at)
                VALUES (%s, %s, TO_TIMESTAMP(%s))
                ON CONFLICT (token_id) DO NOTHING
                """,
                (token_id, user_id, expiry_time),
            )
            await conn.commit()
            logger.info("Revoked token %s for user %s", token_id, user_id)

    async def is_revoked(self, token_id: str) -> bool:
        """Check if a token is revoked."""
        await self._ensure_initialized()

        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT 1 FROM {self.table_name}
                WHERE token_id = %s AND expires_at > NOW()
                """,
                (token_id,),
            )
            result = await cur.fetchone()
            return result is not None

    @staticmethod
    def _cutoff_token_id(user_id: str) -> str:
        """Row id of a user's "revoke all" cutoff; its revoked_at is the cutoff."""
        return f"__all__{user_id}"

    async def revoke_all_user_tokens(self, user_id: str) -> None:
        """Revoke all tokens for a user: every token issued before now."""
        await self._ensure_initialized()

        now = time.time()
        # Default expiry: 24 hours from now
        expiry_time = now + 86400

        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                f"""
                INSERT INTO {self.table_name} (token_id, user_id, revoked_at, expires_at)
                VALUES (%s, %s, TO_TIMESTAMP(%s), TO_TIMESTAMP(%s))
                ON CONFLICT (token_id) DO UPDATE
                SET revoked_at = EXCLUDED.revoked_at, expires_at = EXCLUDED.expires_at
                """,
                (self._cutoff_token_id(user_id), user_id, now, expiry_time),
            )
            await conn.commit()
            logger.info("Revoked all tokens for user %s", user_id)

    async def revoked_before(self, user_id: str) -> float | None:
        """Return when all of a user's tokens were last revoked, if still active."""
        await self._ensure_initialized()

        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT EXTRACT(EPOCH FROM revoked_at)::float8 FROM {self.table_name}
                WHERE token_id = %s AND expires_at > NOW()
                """,
                (self._cutoff_token_id(user_id),),
            )
            result = await cur.fetchone()
            return result[0] if result else None

    async def cleanup_expired(self) -> int:
        """Clean up expired revocations."""
        await self._ensure_initialized()

        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                f"""
                DELETE FROM {self.table_name}
                WHERE expires_at <= NOW()
                """,
            )
            deleted = cur.rowcount
            await conn.commit()

            if deleted > 0:
                logger.debug("Cleaned up %s expired token revocations", deleted)

            return deleted

    async def get_revoked_count(self) -> int:
        """Get count of revoked tokens."""
        await self._ensure_initialized()

        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT COUNT(*) FROM {self.table_name}
                WHERE expires_at > NOW()
                """,
            )
            result = await cur.fetchone()
            return result[0] if result else 0


@dataclass
class RevocationConfig:
    """Configuration for token revocation."""

    enabled: bool = True
    check_revocation: bool = True
    ttl: int = 86400  # 24 hours
    cleanup_interval: int = 3600  # 1 hour


class TokenRevocationService:
    """Main service for handling token revocation."""

    def __init__(
        self,
        store: RevocationStore,
        config: Optional[RevocationConfig] = None,
    ) -> None:
        """Initialize revocation service.

        Args:
            store: Revocation store backend
            config: Revocation configuration
        """
        self.store = store
        self.config = config or RevocationConfig()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the revocation service."""
        if self.config.enabled and self.config.cleanup_interval > 0:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("Token revocation service started")

    async def stop(self) -> None:
        """Stop the revocation service."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            logger.info("Token revocation service stopped")

    async def revoke_token(self, token_payload: dict[str, Any]) -> None:
        """Revoke a token.

        Args:
            token_payload: Decoded JWT payload (must contain 'jti' and 'sub')
        """
        if not self.config.enabled:
            return

        token_id = token_payload.get("jti")
        user_id = token_payload.get("sub")

        if not token_id:
            raise ValueError("Token missing JTI (JWT ID) claim")
        if not user_id:
            raise ValueError("Token missing sub (subject) claim")

        await self.store.revoke_token(token_id, user_id)

        # Log security event
        security_logger = get_security_logger()
        security_logger.log_event(
            SecurityEvent(
                event_type=SecurityEventType.AUTH_LOGOUT,
                severity=SecurityEventSeverity.INFO,
                user_id=user_id,
                metadata={"token_id": token_id},
            ),
        )

    async def is_token_revoked(self, token_payload: dict[str, Any]) -> bool:
        """Check if a token is revoked.

        A token is revoked when its ``jti`` was revoked, or when its user's tokens
        were all revoked (``revoke_all_user_tokens``) after it was issued. Once a
        user's tokens were all revoked, a token of that user without a numeric
        ``iat`` claim is revoked too: its age can't be told.

        Args:
            token_payload: Decoded JWT payload ('jti', 'sub' and 'iat' are read)

        Returns:
            True if token is revoked
        """
        if not self.config.enabled or not self.config.check_revocation:
            return False

        token_id = token_payload.get("jti")
        if token_id and await self.store.is_revoked(token_id):
            return True

        user_id = token_payload.get("sub")
        revoked_before = getattr(self.store, "revoked_before", None)
        if not user_id or revoked_before is None:
            return False

        cutoff = await revoked_before(str(user_id))
        if cutoff is None:
            return False

        issued_at = token_payload.get("iat")
        if isinstance(issued_at, bool) or not isinstance(issued_at, (int, float)):
            return True
        # iat has whole seconds: a token from the cutoff's own second is revoked
        return issued_at < cutoff

    async def revoke_all_user_tokens(self, user_id: str) -> None:
        """Revoke all tokens for a user: every token issued before now.

        Tokens are matched by their ``sub`` claim and dated by ``iat``. The
        revocation lasts 24 hours, like a single token's.

        Args:
            user_id: User identifier (the tokens' ``sub`` claim)
        """
        if not self.config.enabled:
            return

        await self.store.revoke_all_user_tokens(user_id)

        # Log security event
        security_logger = get_security_logger()
        security_logger.log_event(
            SecurityEvent(
                event_type=SecurityEventType.AUTH_LOGOUT,
                severity=SecurityEventSeverity.INFO,
                user_id=user_id,
                metadata={"action": "logout_all_sessions"},
            ),
        )

    async def get_stats(self) -> dict[str, Any]:
        """Get revocation statistics."""
        return {
            "enabled": self.config.enabled,
            "check_revocation": self.config.check_revocation,
            "revoked_tokens": await self.store.get_revoked_count(),
        }

    async def _cleanup_loop(self) -> None:
        """Periodic cleanup of expired revocations."""
        while True:
            try:
                await asyncio.sleep(self.config.cleanup_interval)
                await self._run_cleanup_once()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in revocation cleanup")

    async def _run_cleanup_once(self) -> None:
        """Run cleanup once."""
        cleaned = await self.store.cleanup_expired()
        if cleaned > 0:
            logger.info("Cleaned %s expired token revocations", cleaned)


class TokenRevocationMixin:
    """Mixin for auth providers to add revocation support."""

    revocation_service: Optional[TokenRevocationService] = None

    async def validate_token(self, token: str) -> dict[str, Any]:
        """Validate token with revocation check.

        This wraps the original validate_token method to add revocation checking.
        """
        # First, validate the token normally
        payload = await self._original_validate_token(token)

        # Then check if it's revoked
        if self.revocation_service and await self.revocation_service.is_token_revoked(payload):
            raise InvalidTokenError("Token has been revoked")

        return payload

    async def _original_validate_token(self, token: str) -> dict[str, Any]:
        """Original token validation (to be overridden by auth provider)."""
        raise NotImplementedError

    async def logout(self, token_payload: dict[str, Any]) -> None:
        """Logout by revoking the token."""
        if self.revocation_service:
            await self.revocation_service.revoke_token(token_payload)

    async def logout_all_sessions(self, user_id: str) -> None:
        """Logout all sessions by revoking all user tokens."""
        if self.revocation_service:
            await self.revocation_service.revoke_all_user_tokens(user_id)

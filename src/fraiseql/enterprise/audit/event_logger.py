"""Audit event logging with cryptographic chain integrity.

Philosophy: "In PostgreSQL Everything"
- Crypto operations (hashing, signing) are done in PostgreSQL via triggers
- Python layer focuses on event capture and batching
- PostgreSQL ensures chain integrity at the database level
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

import psycopg
import psycopg.types.json
from psycopg import AsyncConnection

from fraiseql.db import DatabaseQuery, FraiseQLRepository


class AuditLogger:
    """Logs audit events with cryptographic chain and batching support.

    Cryptographic operations (hashing, signing, chain linking) are handled
    by PostgreSQL triggers. This Python layer only captures and batches events.
    """

    def __init__(self, repo: FraiseQLRepository, batch_size: int = 100) -> None:
        self.repo = repo
        self.batch_size = batch_size
        self._batch: list[dict] = []

    async def log_event(
        self,
        event_type: str,
        event_data: dict[str, Any],
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        immediate: bool = True,
    ) -> UUID:
        """Log audit event (batched or immediate).

        Args:
            event_type: Type of event
            event_data: Event data
            user_id: User ID
            tenant_id: Tenant ID
            ip_address: Source IP
            immediate: If True, write immediately; if False, batch

        Returns:
            UUID of event
        """
        event = self._prepare_event(event_type, event_data, user_id, tenant_id, ip_address)

        if immediate:
            return await self._write_event(event)
        self._batch.append(event)
        if len(self._batch) >= self.batch_size:
            await self.flush_batch()
        return event["id"]

    async def flush_batch(self) -> None:
        """Write all batched events to database."""
        if not self._batch:
            return

        # Write events in transaction
        async def write_batch(conn: AsyncConnection) -> None:
            for event in self._batch:
                await self._write_event(event, conn)

        try:
            await self.repo.run_in_transaction(write_batch)
            self._batch.clear()
        except Exception as e:
            # Log error but don't re-raise - batch failures shouldn't break the app
            # In production, you might want to retry or send to dead letter queue
            print(f"Failed to flush audit batch: {e}")
            # Keep batch for retry on next flush
            raise

    def _prepare_event(
        self,
        event_type: str,
        event_data: dict[str, Any],
        user_id: Optional[str],
        tenant_id: Optional[str],
        ip_address: Optional[str],
    ) -> dict[str, Any]:
        """Prepare event data for logging.

        Note: Crypto fields (event_hash, signature, previous_hash) are NOT
        set here - they are auto-populated by PostgreSQL trigger.
        """
        event_id = uuid4()
        timestamp = datetime.utcnow()

        return {
            "id": event_id,
            "event_type": event_type,
            "event_data": event_data,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "timestamp": timestamp,
            "timestamp_str": timestamp.isoformat(),
            "ip_address": ip_address,
        }

    async def _write_event(
        self, event: dict[str, Any], conn: AsyncConnection | None = None
    ) -> UUID:
        """Write a single event to database.

        PostgreSQL trigger (populate_crypto_trigger) automatically:
        - Gets previous_hash from the chain
        - Generates event_hash
        - Generates signature

        This method only provides the event data.
        """
        # Use provided connection or create new query
        query = DatabaseQuery(
            statement="""
            INSERT INTO audit_events (
                id, event_type, event_data, user_id, tenant_id,
                timestamp, ip_address
            ) VALUES (%(id)s, %(event_type)s, %(event_data)s, %(user_id)s, %(tenant_id)s, %(timestamp)s, %(ip_address)s)
        """,
            params={
                "id": str(event["id"]),
                "event_type": event["event_type"],
                "event_data": psycopg.types.json.Jsonb(event["event_data"]),
                "user_id": event["user_id"],
                "tenant_id": event["tenant_id"],
                "timestamp": event["timestamp_str"],
                "ip_address": event["ip_address"],
            },
            fetch_result=False,
        )

        if conn:
            # Use provided connection (for transactions)
            async with conn.cursor() as cursor:
                await cursor.execute(query.statement, query.params)
        else:
            # Use repository
            await self.repo.run(query)

        return event["id"]

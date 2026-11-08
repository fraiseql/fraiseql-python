"""PostgreSQL-native error tracking - Sentry replacement.

This module provides comprehensive error tracking using PostgreSQL as the backend,
eliminating the need for external services like Sentry. Features include:

- Automatic error grouping via fingerprinting
- Full stack trace capture
- Request/user context preservation
- OpenTelemetry trace correlation
- Issue management (resolve, ignore, assign)
- Custom notification triggers
"""

import asyncio
import hashlib
import json
import logging
import traceback
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import psycopg
from psycopg_pool import AsyncConnectionPool

if TYPE_CHECKING:
    from fraiseql.monitoring.notifications import NotificationManager

logger = logging.getLogger(__name__)


class PostgreSQLErrorTracker:
    """PostgreSQL-native error tracking with Sentry-like features."""

    def __init__(
        self,
        db_pool: AsyncConnectionPool,
        environment: str = "production",
        release_version: str | None = None,
        enable_notifications: bool = True,
        notification_manager: "NotificationManager | None" = None,
    ) -> None:
        """Initialize PostgreSQL error tracker.

        Args:
            db_pool: psycopg connection pool
            environment: Environment name (production, staging, development)
            release_version: Application release version
            enable_notifications: Whether to trigger notifications on errors
            notification_manager: The manager that sends them, with your custom
                channels registered (default: a NotificationManager on db_pool,
                created on the first error)
        """
        self.db = db_pool
        self.environment = environment
        self.release_version = release_version
        self.enable_notifications = enable_notifications
        self.notification_manager = notification_manager
        # Notification tasks in flight: the event loop keeps only weak references
        self._notification_tasks: set[asyncio.Task[None]] = set()

    async def capture_exception(
        self,
        error: Exception,
        context: dict[str, Any] | None = None,
        severity: str = "error",
        tags: list[str] | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> str:
        """Capture an exception with full context.

        Args:
            error: The exception to capture
            context: Additional context (request, user, application)
            severity: Error severity (debug, info, warning, error, critical)
            tags: List of tags for categorization
            trace_id: OpenTelemetry trace ID
            span_id: OpenTelemetry span ID

        Returns:
            error_id: UUID of the created/updated error
        """
        context = context or {}

        # Create error fingerprint for grouping
        fingerprint = self._create_fingerprint(error, context)

        # Extract stack trace
        stack_trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))

        # Build contexts
        request_context = context.get("request", {})
        user_context = context.get("user", {})
        application_context = context.get("application", {})

        # Add default application context
        application_context.setdefault("environment", self.environment)
        if self.release_version:
            application_context.setdefault("release", self.release_version)

        try:
            async with self.db.connection() as conn, conn.cursor() as cur:
                # Upsert error (increment occurrence count if exists)
                await cur.execute(
                    """
                        INSERT INTO tb_error_log (
                            error_id,
                            error_fingerprint,
                            error_type,
                            error_message,
                            stack_trace,
                            request_context,
                            application_context,
                            user_context,
                            trace_id,
                            span_id,
                            severity,
                            tags,
                            environment,
                            release_version,
                            first_seen,
                            last_seen,
                            occurrence_count
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1
                        )
                        ON CONFLICT (error_fingerprint) DO UPDATE SET
                            last_seen = EXCLUDED.last_seen,
                            occurrence_count = tb_error_log.occurrence_count + 1,
                            stack_trace = EXCLUDED.stack_trace,
                            request_context = EXCLUDED.request_context,
                            user_context = EXCLUDED.user_context,
                            application_context = EXCLUDED.application_context,
                            trace_id = COALESCE(EXCLUDED.trace_id, tb_error_log.trace_id),
                            span_id = COALESCE(EXCLUDED.span_id, tb_error_log.span_id),
                            tags = EXCLUDED.tags,
                            -- Re-open if it was resolved
                            status = CASE
                                WHEN tb_error_log.status = 'resolved' THEN 'unresolved'
                                ELSE tb_error_log.status
                            END
                        RETURNING error_id, (xmax = 0) as is_new
                        """,
                    (
                        str(uuid4()),
                        fingerprint,
                        type(error).__name__,
                        str(error),
                        stack_trace,
                        json.dumps(request_context),
                        json.dumps(application_context),
                        json.dumps(user_context),
                        trace_id,
                        span_id,
                        severity,
                        json.dumps(tags or []),
                        self.environment,
                        self.release_version,
                        datetime.now(UTC),
                        datetime.now(UTC),
                    ),
                )

                result = await cur.fetchone()
                error_id = str(result[0]) if result and result[0] else ""
                is_new = bool(result[1]) if result else False

                # Log individual occurrence for detailed analysis
                await cur.execute(
                    """
                        INSERT INTO tb_error_occurrence (
                            occurrence_id,
                            error_id,
                            occurred_at,
                            request_context,
                            user_context,
                            stack_trace,
                            trace_id,
                            span_id,
                            breadcrumbs
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                    (
                        str(uuid4()),
                        error_id,
                        datetime.now(UTC),
                        json.dumps(request_context),
                        json.dumps(user_context),
                        stack_trace,
                        trace_id,
                        span_id,
                        json.dumps(context.get("breadcrumbs", [])),
                    ),
                )

                await conn.commit()

                # Trigger notifications if enabled
                if self.enable_notifications:
                    # This will be handled by the notification system
                    await self._trigger_notifications(error_id, is_new)

                logger.info(
                    "Captured error: %s (fingerprint=%s, error_id=%s, is_new=%s)",
                    type(error).__name__,
                    fingerprint[:8],
                    error_id,
                    is_new,
                )

                return error_id or ""

        except psycopg.Error:
            logger.exception("Failed to capture error in PostgreSQL")
            # Don't raise - we don't want error tracking to break the application
            return ""

    async def capture_message(
        self,
        message: str,
        level: str = "info",
        context: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Capture a message (for logging important events).

        Args:
            message: The message to capture
            level: Message level (debug, info, warning, error, critical)
            context: Additional context
            tags: List of tags

        Returns:
            error_id: UUID of the created entry
        """

        # Create a simple exception-like object for consistent handling
        class MessageException(Exception):
            pass

        try:
            raise MessageException(message)
        except MessageException as e:
            return await self.capture_exception(
                e,
                context=context,
                severity=level,
                tags=tags,
            )

    def _create_fingerprint(
        self,
        error: Exception,
        context: dict[str, Any],
    ) -> str:
        """Create error fingerprint for grouping.

        This creates a hash based on error type, file, and line number,
        similar to how Sentry groups errors.

        Args:
            error: The exception
            context: Error context

        Returns:
            Fingerprint string (16-char hex)
        """
        tb = error.__traceback__
        if tb:
            # Get the most relevant frame (last frame before framework code)
            while tb.tb_next:
                next_frame = tb.tb_next
                # Stop if we're entering framework code
                filename = next_frame.tb_frame.f_code.co_filename
                if "fraiseql" in filename or "site-packages" in filename:
                    break
                tb = next_frame

            filename = tb.tb_frame.f_code.co_filename
            lineno = tb.tb_lineno
            function = tb.tb_frame.f_code.co_name
        else:
            filename = "unknown"
            lineno = 0
            function = "unknown"

        # Allow custom fingerprinting via context
        if "fingerprint" in context:
            fingerprint_str = context["fingerprint"]
        else:
            # Standard fingerprinting: type + file + line
            fingerprint_str = f"{type(error).__name__}:{filename}:{lineno}:{function}"

        return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]

    async def get_error(self, error_id: str) -> dict[str, Any] | None:
        """Get error details by ID.

        Args:
            error_id: Error UUID

        Returns:
            Error details or None if not found
        """
        try:
            async with self.db.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    """
                        SELECT
                            error_id,
                            error_fingerprint,
                            error_type,
                            error_message,
                            stack_trace,
                            request_context,
                            application_context,
                            user_context,
                            to_json(first_seen) #>> '{}',
                            to_json(last_seen) #>> '{}',
                            occurrence_count,
                            status,
                            assigned_to,
                            to_json(resolved_at) #>> '{}',
                            resolved_by,
                            resolution_notes,
                            trace_id,
                            span_id,
                            severity,
                            tags,
                            environment,
                            release_version
                        FROM tb_error_log
                        WHERE error_id = %s
                        """,
                    (error_id,),
                )

                row = await cur.fetchone()
                if not row:
                    return None

                return {
                    "error_id": str(row[0]),
                    "error_fingerprint": row[1],
                    "error_type": row[2],
                    "error_message": row[3],
                    "stack_trace": row[4],
                    "request_context": row[5],
                    "application_context": row[6],
                    "user_context": row[7],
                    "first_seen": row[8],
                    "last_seen": row[9],
                    "occurrence_count": row[10],
                    "status": row[11],
                    "assigned_to": row[12],
                    "resolved_at": row[13],
                    "resolved_by": row[14],
                    "resolution_notes": row[15],
                    "trace_id": row[16],
                    "span_id": row[17],
                    "severity": row[18],
                    "tags": row[19],
                    "environment": row[20],
                    "release_version": row[21],
                }

        except psycopg.Error:
            logger.exception("Failed to get error from PostgreSQL")
            return None

    async def get_unresolved_errors(
        self,
        limit: int = 100,
        offset: int = 0,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get list of unresolved errors.

        Args:
            limit: Maximum number of errors to return
            offset: Offset for pagination
            severity: Filter by severity level

        Returns:
            List of error dictionaries
        """
        try:
            async with self.db.connection() as conn, conn.cursor() as cur:
                query = """
                        SELECT
                            error_id,
                            error_type,
                            error_message,
                            severity,
                            occurrence_count,
                            to_json(first_seen) #>> '{}',
                            to_json(last_seen) #>> '{}',
                            environment,
                            release_version,
                            tags
                        FROM tb_error_log
                        WHERE status = 'unresolved'
                    """

                params: list[Any] = []

                if severity:
                    query += " AND severity = %s"
                    params.append(severity)

                query += " ORDER BY last_seen DESC LIMIT %s OFFSET %s"
                params.extend([limit, offset])

                await cur.execute(query, tuple(params))

                rows = await cur.fetchall()
                return [
                    {
                        "error_id": str(row[0]),
                        "error_type": row[1],
                        "error_message": row[2],
                        "severity": row[3],
                        "occurrence_count": row[4],
                        "first_seen": row[5],
                        "last_seen": row[6],
                        "environment": row[7],
                        "release_version": row[8],
                        "tags": row[9],
                    }
                    for row in rows
                ]

        except psycopg.Error:
            logger.exception("Failed to get unresolved errors")
            return []

    async def resolve_error(
        self,
        error_id: str,
        resolved_by: str,
        resolution_notes: str | None = None,
    ) -> bool:
        """Mark an error as resolved.

        Args:
            error_id: Error UUID
            resolved_by: User who resolved the error
            resolution_notes: Optional notes about the resolution

        Returns:
            True if successful
        """
        try:
            async with self.db.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    """
                        UPDATE tb_error_log
                        SET status = 'resolved',
                            resolved_at = %s,
                            resolved_by = %s,
                            resolution_notes = %s
                        WHERE error_id = %s
                        """,
                    (datetime.now(UTC), resolved_by, resolution_notes, error_id),
                )

                await conn.commit()
                return cur.rowcount > 0

        except psycopg.Error:
            logger.exception("Failed to resolve error")
            return False

    async def get_error_stats(self, hours: int = 24) -> dict[str, Any]:
        """Get error statistics for the specified time period.

        Args:
            hours: Number of hours to look back

        Returns:
            Dictionary with error statistics
        """
        try:
            async with self.db.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT
                        COUNT(*)::INT as total_errors,
                        COUNT(*) FILTER (
                            WHERE status = 'unresolved'
                        )::INT as unresolved_errors,
                        COUNT(DISTINCT error_type)::INT as unique_error_types,
                        AVG(
                            EXTRACT(EPOCH FROM (resolved_at - first_seen)) / 3600
                        )::NUMERIC as avg_resolution_time_hours
                    FROM tb_error_log
                    WHERE first_seen > NOW() - (%s || ' hours')::INTERVAL
                    """,
                    (hours,),
                )

                row = await cur.fetchone()
                if row:
                    return {
                        "total_errors": row[0],
                        "unresolved_errors": row[1],
                        "unique_error_types": row[2],
                        "avg_resolution_time_hours": float(row[3]) if row[3] else None,
                    }
                return {
                    "total_errors": 0,
                    "unresolved_errors": 0,
                    "unique_error_types": 0,
                    "avg_resolution_time_hours": None,
                }

        except psycopg.Error:
            logger.exception("Failed to get error stats")
            return {
                "total_errors": 0,
                "unresolved_errors": 0,
                "unique_error_types": 0,
                "avg_resolution_time_hours": None,
            }

    async def _trigger_notifications(self, error_id: str, is_new: bool) -> None:
        """Trigger notifications for an error (internal use).

        This method is called automatically when an error is captured.
        The notification system will process this asynchronously.

        Args:
            error_id: Error UUID
            is_new: Whether this is a new error (first occurrence)
        """
        # Import NotificationManager lazily to avoid circular imports
        try:
            if self.notification_manager is None:
                from fraiseql.monitoring.notifications import NotificationManager

                self.notification_manager = NotificationManager(self.db)
            # Send notifications asynchronously without blocking error capture,
            # keeping a reference so the task isn't garbage-collected mid-way
            task = asyncio.create_task(self.notification_manager.send_notifications(error_id))
            self._notification_tasks.add(task)
            task.add_done_callback(self._notification_tasks.discard)

            logger.debug(
                "Error notification triggered: error_id=%s, is_new=%s",
                error_id,
                is_new,
            )
        except Exception:
            # Don't let notification failures break error tracking
            logger.exception("Failed to trigger notifications for error %s", error_id)


# Global tracker instance
_tracker_instance: PostgreSQLErrorTracker | None = None


def get_error_tracker() -> PostgreSQLErrorTracker | None:
    """Get the global error tracker instance."""
    return _tracker_instance


def init_error_tracker(
    db_pool: AsyncConnectionPool,
    environment: str = "production",
    release_version: str | None = None,
    enable_notifications: bool = True,
    notification_manager: "NotificationManager | None" = None,
) -> PostgreSQLErrorTracker:
    """Initialize the global error tracker.

    Args:
        db_pool: psycopg connection pool
        environment: Environment name
        release_version: Application release version
        enable_notifications: Whether to enable notifications
        notification_manager: The manager that sends them (see PostgreSQLErrorTracker)

    Returns:
        Initialized error tracker
    """
    global _tracker_instance
    _tracker_instance = PostgreSQLErrorTracker(
        db_pool,
        environment=environment,
        release_version=release_version,
        enable_notifications=enable_notifications,
        notification_manager=notification_manager,
    )
    logger.info("Initialized PostgreSQL error tracker for environment: %s", environment)
    return _tracker_instance

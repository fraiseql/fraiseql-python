"""Security event logging for FraiseQL.

This module provides centralized security event logging with structured
events, configurable outputs, and integration with monitoring systems.
"""

import json
import logging
import os
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer

logger = logging.getLogger("fraiseql.security")


class SecurityEventType(StrEnum):
    """Types of security events."""

    # Authentication events
    AUTH_SUCCESS = "auth.success"
    AUTH_FAILURE = "auth.failure"
    AUTH_TOKEN_EXPIRED = "auth.token_expired"
    AUTH_TOKEN_INVALID = "auth.token_invalid"
    AUTH_LOGOUT = "auth.logout"

    # Authorization events
    AUTHZ_DENIED = "authz.denied"
    AUTHZ_FIELD_DENIED = "authz.field_denied"
    AUTHZ_PERMISSION_DENIED = "authz.permission_denied"
    AUTHZ_ROLE_DENIED = "authz.role_denied"

    # Rate limiting
    RATE_LIMIT_EXCEEDED = "rate_limit.exceeded"
    RATE_LIMIT_WARNING = "rate_limit.warning"

    # CSRF protection
    CSRF_TOKEN_INVALID = "csrf.token_invalid"
    CSRF_TOKEN_MISSING = "csrf.token_missing"

    # Query security
    QUERY_COMPLEXITY_EXCEEDED = "query.complexity_exceeded"
    QUERY_DEPTH_EXCEEDED = "query.depth_exceeded"
    QUERY_TIMEOUT = "query.timeout"
    QUERY_MALICIOUS_PATTERN = "query.malicious_pattern"

    # Data access
    DATA_ACCESS_DENIED = "data.access_denied"
    DATA_EXPORT_LARGE = "data.export_large"

    # Configuration
    CONFIG_CHANGED = "config.changed"
    CONFIG_ACCESS_DENIED = "config.access_denied"

    # System security
    SYSTEM_INTRUSION_ATTEMPT = "system.intrusion_attempt"
    SYSTEM_VULNERABILITY_SCAN = "system.vulnerability_scan"


class SecurityEventSeverity(StrEnum):
    """Severity levels for security events."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class SecurityEvent(BaseModel):
    """Structured security event."""

    model_config = ConfigDict()

    event_type: SecurityEventType
    severity: SecurityEventSeverity
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    request_id: Optional[str] = None
    resource: Optional[str] = None
    action: Optional[str] = None
    result: Optional[str] = None
    reason: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_serializer("timestamp")
    def serialize_timestamp(self, timestamp: datetime) -> str:
        """Serialize datetime to ISO format."""
        return timestamp.isoformat()


class SecurityLogger:
    """Centralized security event logger."""

    def __init__(
        self,
        *,
        log_to_file: bool = True,
        log_to_stdout: bool = True,
        log_file_path: Optional[str] = None,
    ) -> None:
        """Initialize security logger.

        Args:
            log_to_file: Whether to log events to a file
            log_to_stdout: Whether to log events to stdout
            log_file_path: Custom path for security log file
        """
        self.log_to_file = log_to_file
        self.log_to_stdout = log_to_stdout

        # Configure file handler if needed
        if self.log_to_file:
            file_path = log_file_path or os.environ.get(
                "FRAISEQL_SECURITY_LOG_PATH", "security_events.log"
            )
            try:
                file_handler = logging.FileHandler(file_path)
                file_handler.setFormatter(
                    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
                )
                logger.addHandler(file_handler)
            except (PermissionError, OSError) as e:
                logger.warning(
                    "Cannot write security log to %s: %s. Using stderr only.",
                    file_path,
                    e,
                )

        # Configure stdout handler if needed
        if self.log_to_stdout:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(
                logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
            )
            logger.addHandler(console_handler)

        logger.setLevel(logging.INFO)

    def log_event(self, event: SecurityEvent) -> None:
        """Log a security event.

        Args:
            event: The security event to log
        """
        # Convert event to log message
        log_data = event.model_dump(mode="json")
        log_message = json.dumps(log_data)

        # Log based on severity
        if event.severity == SecurityEventSeverity.CRITICAL:
            logger.critical(log_message, extra={"security_event": log_data})
        elif event.severity == SecurityEventSeverity.ERROR:
            logger.error(log_message, extra={"security_event": log_data})
        elif event.severity == SecurityEventSeverity.WARNING:
            logger.warning(log_message, extra={"security_event": log_data})
        else:
            logger.info(log_message, extra={"security_event": log_data})

        # Hook for additional processing (metrics, alerts, etc.)
        self._process_event(event)

    def _process_event(self, event: SecurityEvent) -> None:
        """Process event for metrics, alerts, etc.

        Override this method to add custom processing.

        Args:
            event: The security event to process
        """
        # This is a hook for subclasses to implement
        # Examples: send to metrics system, trigger alerts, etc.

    # Convenience methods for common events

    def log_auth_success(
        self,
        user_id: str,
        user_email: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log successful authentication."""
        event = SecurityEvent(
            event_type=SecurityEventType.AUTH_SUCCESS,
            severity=SecurityEventSeverity.INFO,
            user_id=user_id,
            user_email=user_email,
            ip_address=ip_address,
            user_agent=user_agent,
            result="success",
            metadata=metadata or {},
        )
        self.log_event(event)

    def log_auth_failure(
        self,
        reason: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        attempted_username: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log failed authentication attempt."""
        event = SecurityEvent(
            event_type=SecurityEventType.AUTH_FAILURE,
            severity=SecurityEventSeverity.WARNING,
            ip_address=ip_address,
            user_agent=user_agent,
            result="failure",
            reason=reason,
            metadata={
                "attempted_username": attempted_username,
                **(metadata or {}),
            },
        )
        self.log_event(event)

    def log_authorization_denied(
        self,
        user_id: str,
        resource: str,
        action: str,
        reason: str,
        user_email: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log authorization denial."""
        event = SecurityEvent(
            event_type=SecurityEventType.AUTHZ_DENIED,
            severity=SecurityEventSeverity.WARNING,
            user_id=user_id,
            user_email=user_email,
            resource=resource,
            action=action,
            result="denied",
            reason=reason,
            metadata=metadata or {},
        )
        self.log_event(event)

    def log_rate_limit_exceeded(
        self,
        ip_address: str,
        endpoint: str,
        limit: int,
        window: str,
        user_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log rate limit violation."""
        event = SecurityEvent(
            event_type=SecurityEventType.RATE_LIMIT_EXCEEDED,
            severity=SecurityEventSeverity.WARNING,
            user_id=user_id,
            ip_address=ip_address,
            resource=endpoint,
            result="blocked",
            reason=f"Rate limit exceeded: {limit} requests per {window}",
            metadata={
                "limit": limit,
                "window": window,
                **(metadata or {}),
            },
        )
        self.log_event(event)

    def log_query_timeout(
        self,
        user_id: Optional[str] = None,
        query_hash: Optional[str] = None,
        execution_time: Optional[float] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log query timeout event."""
        event = SecurityEvent(
            event_type=SecurityEventType.QUERY_TIMEOUT,
            severity=SecurityEventSeverity.ERROR,
            user_id=user_id,
            result="timeout",
            reason="Query execution timeout",
            metadata={
                "query_hash": query_hash,
                "execution_time": execution_time,
                **(metadata or {}),
            },
        )
        self.log_event(event)


# Global security logger instance
_security_logger: Optional[SecurityLogger] = None


def get_security_logger() -> SecurityLogger:
    """Get the global security logger instance."""
    global _security_logger
    if _security_logger is None:
        _security_logger = SecurityLogger()
    return _security_logger


def set_security_logger(logger: SecurityLogger) -> None:
    """Set the global security logger instance."""
    global _security_logger
    _security_logger = logger

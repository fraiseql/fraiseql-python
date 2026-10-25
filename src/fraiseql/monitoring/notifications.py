"""Extensible notification system for error alerts.

Supports multiple notification channels:
- Email (via SMTP)
- Slack (via webhook)
- Webhook (generic HTTP POST)
- SMS (extensible via custom channels)

Features:
- Rate limiting per error type
- Template-based messages
- Async delivery
- Retry logic
- Delivery tracking
"""

import asyncio
import inspect
import json
import logging
import smtplib
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Protocol

import httpx
import psycopg
from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


# ============================================================================
# Notification Channel Protocol
# ============================================================================


class NotificationChannel(Protocol):
    """Protocol for notification channels."""

    async def send(
        self,
        error: dict[str, Any],
        config: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Send notification.

        Args:
            error: Error details from tb_error_log
            config: Channel-specific configuration

        Returns:
            (success, error_message)
        """
        ...

    def format_message(
        self,
        error: dict[str, Any],
        template: str | None = None,
    ) -> str:
        """Format error message for this channel.

        Args:
            error: Error details
            template: Optional custom template

        Returns:
            Formatted message
        """
        ...


# ============================================================================
# Email Channel
# ============================================================================


class EmailChannel:
    """Email notification channel using SMTP."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int = 587,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        use_tls: bool = True,
        from_address: str = "noreply@fraiseql.app",
    ) -> None:
        """Initialize email channel.

        Args:
            smtp_host: SMTP server hostname
            smtp_port: SMTP server port
            smtp_user: SMTP username (optional)
            smtp_password: SMTP password (optional)
            use_tls: Whether to use TLS
            from_address: From email address
        """
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.use_tls = use_tls
        self.from_address = from_address

    async def send(
        self,
        error: dict[str, Any],
        config: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Send email notification.

        Config format:
        {
            "to": ["user@example.com", "team@example.com"],
            "subject": "Error Alert: {error_type}",
            "template": "custom template..." (optional)
        }

        Args:
            error: Error details
            config: Email configuration

        Returns:
            (success, error_message)
        """
        try:
            to_addresses = config.get("to", [])
            if not to_addresses:
                return False, "No recipient addresses specified"

            subject = config.get("subject", "Error Alert: {error_type}").format(
                error_type=error.get("error_type", "Unknown"),
                environment=error.get("environment", "unknown"),
            )

            body = self.format_message(error, config.get("template"))

            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.from_address
            msg["To"] = ", ".join(to_addresses)

            # Add plain text and HTML parts
            text_part = MIMEText(body, "plain")
            html_part = MIMEText(self._format_html(error), "html")

            msg.attach(text_part)
            msg.attach(html_part)

            # Send email (in thread pool to avoid blocking)
            await asyncio.to_thread(self._send_smtp, msg, to_addresses)

            logger.info("Sent error notification email to %s", to_addresses)
            return True, None

        except Exception as e:
            logger.exception("Failed to send email notification")
            return False, str(e)

    def _send_smtp(self, msg: MIMEMultipart, to_addresses: list[str]) -> None:
        """Send email via SMTP (blocking, runs in thread)."""
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            if self.use_tls:
                server.starttls()
            if self.smtp_user and self.smtp_password:
                server.login(self.smtp_user, self.smtp_password)
            server.sendmail(self.from_address, to_addresses, msg.as_string())

    def format_message(
        self,
        error: dict[str, Any],
        template: str | None = None,
    ) -> str:
        """Format error message for email.

        Args:
            error: Error details
            template: Optional custom template

        Returns:
            Formatted message
        """
        if template:
            return template.format(**error)

        # Default template
        return f"""
Error Alert from FraiseQL

Error Type: {error.get("error_type", "Unknown")}
Message: {error.get("error_message", "No message")}
Severity: {error.get("severity", "unknown")}
Environment: {error.get("environment", "unknown")}

Occurrences: {error.get("occurrence_count", 1)}
First Seen: {error.get("first_seen", "unknown")}
Last Seen: {error.get("last_seen", "unknown")}

Stack Trace:
{error.get("stack_trace", "Not available")[:500]}...

---
Error ID: {error.get("error_id", "unknown")}
Fingerprint: {error.get("error_fingerprint", "unknown")}
        """.strip()

    def _format_html(self, error: dict[str, Any]) -> str:
        """Format error as HTML email."""
        severity_colors = {
            "critical": "#ff0000",
            "error": "#ff6b6b",
            "warning": "#ffa500",
            "info": "#4dabf7",
            "debug": "#868e96",
        }

        severity = error.get("severity", "error")
        color = severity_colors.get(severity, "#ff6b6b")

        return f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: {color}; color: white; padding: 20px;
                   border-radius: 5px 5px 0 0; }}
        .content {{ background-color: #f9f9f9; padding: 20px;
                    border-radius: 0 0 5px 5px; }}
        .info-row {{ margin: 10px 0; }}
        .label {{ font-weight: bold; color: #555; }}
        .stack-trace {{ background-color: #2d2d2d; color: #f8f8f2;
                        padding: 15px; border-radius: 5px; overflow-x: auto;
                        font-family: 'Courier New', monospace; font-size: 12px; }}
        .footer {{ margin-top: 20px; padding-top: 20px;
                   border-top: 1px solid #ddd; font-size: 12px; color: #999; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>🚨 Error Alert from FraiseQL</h2>
        </div>
        <div class="content">
            <div class="info-row">
                <span class="label">Error Type:</span> {error.get("error_type", "Unknown")}
            </div>
            <div class="info-row">
                <span class="label">Message:</span> {error.get("error_message", "No message")}
            </div>
            <div class="info-row">
                <span class="label">Severity:</span>
                <strong style="color: {color};">{severity.upper()}</strong>
            </div>
            <div class="info-row">
                <span class="label">Environment:</span> {error.get("environment", "unknown")}
            </div>
            <div class="info-row">
                <span class="label">Occurrences:</span> {error.get("occurrence_count", 1)}
            </div>
            <div class="info-row">
                <span class="label">First Seen:</span> {error.get("first_seen", "unknown")}
            </div>
            <div class="info-row">
                <span class="label">Last Seen:</span> {error.get("last_seen", "unknown")}
            </div>

            <h3>Stack Trace:</h3>
            <pre class="stack-trace">{error.get("stack_trace", "Not available")[:1000]}</pre>

            <div class="footer">
                Error ID: {error.get("error_id", "unknown")}<br>
                Fingerprint: {error.get("error_fingerprint", "unknown")}
            </div>
        </div>
    </div>
</body>
</html>
        """.strip()


# ============================================================================
# Slack Channel
# ============================================================================


class SlackChannel:
    """Slack notification channel using incoming webhooks."""

    async def send(
        self,
        error: dict[str, Any],
        config: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Send Slack notification.

        Config format:
        {
            "webhook_url": "https://hooks.slack.com/services/...",
            "channel": "#alerts" (optional),
            "username": "FraiseQL Error Bot" (optional),
            "template": "custom template..." (optional)
        }

        Args:
            error: Error details
            config: Slack configuration

        Returns:
            (success, error_message)
        """
        try:
            webhook_url = config.get("webhook_url")
            if not webhook_url:
                return False, "No webhook URL specified"

            # Format Slack message
            message = self._format_slack_message(error, config)

            # Send via webhook
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    webhook_url,
                    json=message,
                    timeout=10.0,
                )

                if response.status_code == 200:
                    logger.info("Sent error notification to Slack")
                    return True, None
                return False, f"Slack API returned {response.status_code}"

        except Exception as e:
            logger.exception("Failed to send Slack notification")
            return False, str(e)

    def _format_slack_message(
        self,
        error: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Format error as Slack message with blocks."""
        severity_emoji = {
            "critical": "🔴",
            "error": "🔴",
            "warning": "🟡",
            "info": "🔵",
            "debug": "⚪",
        }

        severity = error.get("severity", "error")
        emoji = severity_emoji.get(severity, "🔴")

        return {
            "username": config.get("username", "FraiseQL Error Bot"),
            "channel": config.get("channel"),
            "icon_emoji": ":warning:",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{emoji} {error.get('error_type', 'Unknown Error')}",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Message:*\n{error.get('error_message', 'No message')}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Environment:*\n{error.get('environment', 'unknown')}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Occurrences:*\n{error.get('occurrence_count', 1)}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Last Seen:*\n{error.get('last_seen', 'unknown')}",
                        },
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"```{error.get('stack_trace', 'Not available')[:500]}...```",
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": (
                                f"Error ID: `{error.get('error_id', 'unknown')}` | "
                                f"Fingerprint: `{error.get('error_fingerprint', 'unknown')}`"
                            ),
                        },
                    ],
                },
            ],
        }

    def format_message(
        self,
        error: dict[str, Any],
        template: str | None = None,
    ) -> str:
        """Format error message for Slack (simple text fallback)."""
        return f"{error.get('error_type')}: {error.get('error_message')}"


# ============================================================================
# Webhook Channel
# ============================================================================


class WebhookChannel:
    """Generic webhook notification channel."""

    async def send(
        self,
        error: dict[str, Any],
        config: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Send webhook notification.

        Config format:
        {
            "url": "https://api.example.com/errors",
            "method": "POST" (optional, default: POST),
            "headers": {"Authorization": "Bearer token"} (optional),
            "payload_template": {...} (optional)
        }

        Args:
            error: Error details
            config: Webhook configuration

        Returns:
            (success, error_message)
        """
        try:
            url = config.get("url")
            if not url:
                return False, "No webhook URL specified"

            method = config.get("method", "POST").upper()
            headers = config.get("headers", {})

            # Format payload
            if "payload_template" in config:
                payload = config["payload_template"].format(**error)
            else:
                payload = error

            # Send webhook
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method,
                    url,
                    json=payload,
                    headers=headers,
                    timeout=10.0,
                )

                if 200 <= response.status_code < 300:
                    logger.info("Sent error notification to webhook: %s", url)
                    return True, None
                return False, f"Webhook returned {response.status_code}"

        except Exception as e:
            logger.exception("Failed to send webhook notification")
            return False, str(e)

    def format_message(
        self,
        error: dict[str, Any],
        template: str | None = None,
    ) -> str:
        """Format error message for webhook."""
        return json.dumps(error)


# ============================================================================
# Notification Manager
# ============================================================================


class NotificationManager:
    """Manages error notifications with rate limiting and delivery tracking."""

    def __init__(self, db_pool: AsyncConnectionPool) -> None:
        """Initialize notification manager.

        Args:
            db_pool: psycopg connection pool
        """
        self.db = db_pool
        self.channels = {
            "email": EmailChannel,
            "slack": SlackChannel,
            "webhook": WebhookChannel,
        }

    def register_channel(self, name: str, channel_class: type | NotificationChannel) -> None:
        """Register a custom notification channel.

        Args:
            name: Channel name (the ``channel_type`` of its configs)
            channel_class: Channel class implementing NotificationChannel protocol,
                or an instance of one, used as is for every notification
        """
        self.channels[name] = channel_class
        logger.info("Registered notification channel: %s", name)

    @staticmethod
    def _build_channel(
        channel_class: type | NotificationChannel, channel_config: dict[str, Any]
    ) -> NotificationChannel:
        """The channel to send with: a registered instance, or a new one of the class.

        A class gets the keys of ``channel_config`` its constructor takes (all of
        them if it takes ``**kwargs``): ``EmailChannel`` its ``smtp_*`` settings,
        ``SlackChannel`` and ``WebhookChannel`` none. Every key is still passed to
        ``send``.
        """
        if not isinstance(channel_class, type):
            return channel_class
        parameters = inspect.signature(channel_class).parameters.values()
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters):
            return channel_class(**channel_config)
        accepted = {
            p.name
            for p in parameters
            if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        }
        return channel_class(**{k: v for k, v in channel_config.items() if k in accepted})

    async def send_notifications(self, error_id: str) -> None:
        """Send notifications for an error based on configured rules.

        Args:
            error_id: Error UUID
        """
        try:
            # Get error details
            error = await self._get_error(error_id)
            if not error:
                logger.warning("Cannot send notifications: error not found: %s", error_id)
                return

            # Get matching notification configs
            configs = await self._get_matching_configs(error)

            # Send notifications for each config
            for config in configs:
                await self._send_notification(error, config)

        except Exception:
            logger.exception("Failed to send notifications for error %s", error_id)

    async def _get_error(self, error_id: str) -> dict[str, Any] | None:
        """Get error details from database."""
        async with self.db.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    SELECT
                        error_id, error_fingerprint, error_type, error_message,
                        severity, occurrence_count, first_seen, last_seen,
                        environment, release_version, stack_trace
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
                "severity": row[4],
                "occurrence_count": row[5],
                "first_seen": row[6].isoformat() if row[6] else None,
                "last_seen": row[7].isoformat() if row[7] else None,
                "environment": row[8],
                "release_version": row[9],
                "stack_trace": row[10],
            }

    async def _get_matching_configs(self, error: dict[str, Any]) -> list[dict[str, Any]]:
        """Get notification configs that match this error."""
        async with self.db.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    SELECT
                        config_id, channel_type, channel_config,
                        rate_limit_minutes, message_template
                    FROM tb_error_notification_config
                    WHERE enabled = true
                        AND (error_fingerprint IS NULL OR error_fingerprint = %s)
                        AND (error_type IS NULL OR error_type = %s)
                        AND (severity IS NULL OR %s = ANY(severity))
                        AND (environment IS NULL OR %s = ANY(environment))
                        AND %s >= min_occurrence_count
                    """,
                (
                    error["error_fingerprint"],
                    error["error_type"],
                    error["severity"],
                    error["environment"],
                    error["occurrence_count"],
                ),
            )

            rows = await cur.fetchall()
            return [
                {
                    "config_id": str(row[0]),
                    "channel_type": row[1],
                    "channel_config": row[2],
                    "rate_limit_minutes": row[3],
                    "message_template": row[4],
                }
                for row in rows
            ]

    async def _send_notification(
        self,
        error: dict[str, Any],
        config: dict[str, Any],
    ) -> None:
        """Send a notification for a specific config."""
        # Check rate limiting
        rate_limited = not await self._check_rate_limit(
            error["error_id"], config["config_id"], config["rate_limit_minutes"]
        )
        if rate_limited:
            logger.debug(
                "Skipping notification due to rate limit: error_id=%s, config_id=%s",
                error["error_id"],
                config["config_id"],
            )
            return

        # Get channel
        channel_type = config["channel_type"]
        if channel_type not in self.channels:
            logger.warning("Unknown channel type: %s", channel_type)
            return

        # Create channel instance
        try:
            channel = self._build_channel(self.channels[channel_type], config["channel_config"])
        except Exception as e:
            logger.exception("Failed to create channel %s", channel_type)
            await self._log_notification(
                error["error_id"],
                config["config_id"],
                channel_type,
                "N/A",
                "failed",
                f"Channel creation failed: {e}",
            )
            return

        # Send notification
        success, error_message = await channel.send(error, config["channel_config"])

        # Log delivery
        await self._log_notification(
            error["error_id"],
            config["config_id"],
            channel_type,
            config["channel_config"].get("to") or config["channel_config"].get("channel") or "N/A",
            "sent" if success else "failed",
            error_message,
        )

    async def _check_rate_limit(
        self,
        error_id: str,
        config_id: str,
        rate_limit_minutes: int,
    ) -> bool:
        """Check if notification is rate-limited."""
        if rate_limit_minutes <= 0:
            return True  # No rate limiting

        cutoff_time = datetime.now(UTC) - timedelta(minutes=rate_limit_minutes)

        async with self.db.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    SELECT COUNT(*)
                    FROM tb_error_notification_log
                    WHERE error_id = %s
                        AND config_id = %s
                        AND sent_at > %s
                        AND status = 'sent'
                    """,
                (error_id, config_id, cutoff_time),
            )

            result = await cur.fetchone()
            return result[0] == 0 if result else False

    async def _log_notification(
        self,
        error_id: str,
        config_id: str,
        channel_type: str,
        recipient: str,
        status: str,
        error_message: str | None,
    ) -> None:
        """Log notification delivery."""
        try:
            async with self.db.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    """
                        INSERT INTO tb_error_notification_log (
                            notification_id, config_id, error_id,
                            sent_at, channel_type, recipient, status, error_message
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                    (
                        str(uuid4()),
                        config_id,
                        error_id,
                        datetime.now(UTC),
                        channel_type,
                        str(recipient),
                        status,
                        error_message,
                    ),
                )

                await conn.commit()

        except psycopg.Error:
            logger.exception("Failed to log notification")


# ============================================================================
# Helper Functions
# ============================================================================


def uuid4() -> str:
    """Generate UUID4 string."""
    from uuid import uuid4 as _uuid4

    return str(_uuid4())

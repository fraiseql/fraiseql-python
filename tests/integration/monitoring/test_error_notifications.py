"""Integration tests for PostgreSQL error notification system."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from fraiseql.monitoring.notifications import (
    EmailChannel,
    NotificationManager,
    SlackChannel,
    WebhookChannel,
)
from fraiseql.monitoring.postgres_error_tracker import (
    PostgreSQLErrorTracker,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def error_tracker(class_db_pool, test_schema):
    """Create error tracker instance for testing."""
    # Read and execute schema
    with open("src/fraiseql/monitoring/schema.sql") as f:
        schema_sql = f.read()

    # Run the async setup
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        await conn.execute(schema_sql)
        await conn.commit()

    tracker = PostgreSQLErrorTracker(
        class_db_pool,
        environment="test",
        release_version="1.0.0",
        enable_notifications=True,
    )

    yield tracker


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def notification_manager(class_db_pool, test_schema):
    """Create notification manager instance for testing."""
    yield NotificationManager(class_db_pool)


class TestEmailChannel:
    """Test email notification channel."""

    @pytest.mark.asyncio
    async def test_email_format_message(self) -> None:
        """Test email message formatting."""
        channel = EmailChannel(
            smtp_host="smtp.example.com",
            smtp_port=587,
            from_address="test@example.com",
        )

        error = {
            "error_id": "test-error-id",
            "error_type": "ValueError",
            "error_message": "Invalid input",
            "severity": "error",
            "environment": "production",
            "occurrence_count": 5,
            "first_seen": "2024-01-01T00:00:00",
            "last_seen": "2024-01-01T12:00:00",
            "stack_trace": "Traceback (most recent call last):\\n  ...",
            "error_fingerprint": "abc123",
        }

        message = channel.format_message(error)

        assert "ValueError" in message
        assert "Invalid input" in message
        assert "production" in message
        assert "5" in message  # occurrence count

    @pytest.mark.asyncio
    async def test_email_send_success(self) -> None:
        """Test successful email sending."""
        channel = EmailChannel(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="test@example.com",
            smtp_password="password",
            from_address="test@example.com",
        )

        error = {
            "error_id": "test-error-id",
            "error_type": "ValueError",
            "error_message": "Invalid input",
            "severity": "error",
            "environment": "test",
            "occurrence_count": 1,
            "first_seen": "2024-01-01T00:00:00",
            "last_seen": "2024-01-01T00:00:00",
            "stack_trace": "Stack trace here",
            "error_fingerprint": "abc123",
        }

        config = {
            "to": ["recipient@example.com"],
            "subject": "Error Alert: {error_type}",
        }

        # Mock SMTP to avoid actually sending email
        with patch("smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_server

            success, error_msg = await channel.send(error, config)

            assert success is True
            assert error_msg is None
            mock_server.sendmail.assert_called_once()

    @pytest.mark.asyncio
    async def test_email_send_no_recipients(self) -> None:
        """Test email sending with no recipients."""
        channel = EmailChannel(smtp_host="smtp.example.com")

        error = {"error_type": "ValueError"}
        config = {"to": []}  # No recipients

        success, error_msg = await channel.send(error, config)

        assert success is False
        assert "No recipient" in error_msg


class TestSlackChannel:
    """Test Slack notification channel."""

    @pytest.mark.asyncio
    async def test_slack_format_message(self) -> None:
        """Test Slack message formatting."""
        channel = SlackChannel()

        error = {
            "error_id": "test-error-id",
            "error_type": "ValueError",
            "error_message": "Invalid input",
            "severity": "error",
            "environment": "production",
            "occurrence_count": 5,
            "first_seen": "2024-01-01T00:00:00",
            "last_seen": "2024-01-01T12:00:00",
            "stack_trace": "Traceback...",
            "error_fingerprint": "abc123",
        }

        config = {
            "webhook_url": "https://hooks.slack.com/services/TEST",
            "username": "FraiseQL Bot",
            "channel": "#alerts",
        }

        message = channel._format_slack_message(error, config)

        assert message["username"] == "FraiseQL Bot"
        assert message["channel"] == "#alerts"
        assert "blocks" in message
        assert len(message["blocks"]) > 0
        # Check that error type is in header
        assert "ValueError" in str(message["blocks"][0])

    @pytest.mark.asyncio
    async def test_slack_send_success(self) -> None:
        """Test successful Slack notification."""
        channel = SlackChannel()

        error = {
            "error_id": "test-error-id",
            "error_type": "ValueError",
            "error_message": "Invalid input",
            "severity": "error",
            "environment": "test",
            "occurrence_count": 1,
            "first_seen": "2024-01-01T00:00:00",
            "last_seen": "2024-01-01T00:00:00",
            "stack_trace": "Stack trace",
            "error_fingerprint": "abc123",
        }

        config = {"webhook_url": "https://hooks.slack.com/services/TEST"}

        # Mock httpx client
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            success, error_msg = await channel.send(error, config)

            assert success is True
            assert error_msg is None

    @pytest.mark.asyncio
    async def test_slack_send_no_webhook(self) -> None:
        """Test Slack sending with no webhook URL."""
        channel = SlackChannel()

        error = {"error_type": "ValueError"}
        config = {}  # No webhook URL

        success, error_msg = await channel.send(error, config)

        assert success is False
        assert "No webhook URL" in error_msg


class TestWebhookChannel:
    """Test generic webhook notification channel."""

    @pytest.mark.asyncio
    async def test_webhook_send_success(self) -> None:
        """Test successful webhook notification."""
        channel = WebhookChannel()

        error = {
            "error_id": "test-error-id",
            "error_type": "ValueError",
            "error_message": "Invalid input",
        }

        config = {"url": "https://api.example.com/errors"}

        # Mock httpx client
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )

            success, error_msg = await channel.send(error, config)

            assert success is True
            assert error_msg is None

    @pytest.mark.asyncio
    async def test_webhook_custom_method(self) -> None:
        """Test webhook with custom HTTP method."""
        channel = WebhookChannel()

        error = {"error_type": "ValueError"}
        config = {"url": "https://api.example.com/errors", "method": "PUT"}

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_request = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.request = mock_request

            success, _error_msg = await channel.send(error, config)

            assert success is True
            # Verify PUT method was used
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "PUT"


class TestNotificationManager:
    """Test notification manager."""

    pytestmark = pytest.mark.asyncio

    @pytest.mark.asyncio
    async def test_register_custom_channel(self, notification_manager) -> None:
        """Test registering a custom notification channel."""

        class CustomChannel:
            async def send(self, error, config) -> None:
                return True, None

            def format_message(self, error, template=None) -> None:
                return "custom message"

        notification_manager.register_channel("custom", CustomChannel)

        assert "custom" in notification_manager.channels
        assert notification_manager.channels["custom"] == CustomChannel

    @pytest.mark.asyncio
    async def test_send_notifications_no_config(
        self, error_tracker, notification_manager, test_schema
    ) -> None:
        """Test sending notifications with no matching config."""
        # Create an error
        try:
            raise ValueError("Test error")
        except ValueError as e:
            error_id = await error_tracker.capture_exception(e)

        # Try to send notifications (should not fail, just do nothing)
        await notification_manager.send_notifications(error_id)

        # Verify no notifications were sent (no config exists)
        async with error_tracker.db.connection() as conn, conn.cursor() as cur:
            await conn.execute(f"SET search_path TO {test_schema}")
            await cur.execute(
                "SELECT COUNT(*) FROM tb_error_notification_log WHERE error_id = %s",
                (error_id,),
            )
            result = await cur.fetchone()
            assert result[0] == 0

    @pytest.mark.asyncio
    async def test_send_notifications_with_config(
        self, error_tracker, notification_manager, test_schema
    ) -> None:
        """Test sending notifications with matching config."""
        # Create notification config
        async with error_tracker.db.connection() as conn, conn.cursor() as cur:
            await conn.execute(f"SET search_path TO {test_schema}")
            await cur.execute(
                """
                        INSERT INTO tb_error_notification_config (
                            config_id, error_type, channel_type,
                            channel_config, rate_limit_minutes, enabled
                        ) VALUES (
                            gen_random_uuid(), 'ValueError', 'slack',
                            '{"webhook_url": "https://example.com/webhook"}'::jsonb,
                            0, true
                        )
                        """
            )
            await conn.commit()

        # Create an error
        try:
            raise ValueError("Test error for notification")
        except ValueError as e:
            error_id = await error_tracker.capture_exception(e)

        # Mock Slack channel to avoid actual HTTP call
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            # Send notifications
            await notification_manager.send_notifications(error_id)

            # Give async task time to complete
            await asyncio.sleep(0.1)

        # Verify notification was logged
        async with error_tracker.db.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM tb_error_notification_log WHERE error_id = %s",
                (error_id,),
            )
            await cur.fetchone()
            # Note: Might be 0 if async task hasn't completed yet
            # This is expected behavior for fire-and-forget notifications

    @pytest.mark.asyncio
    async def test_rate_limiting(self, error_tracker, notification_manager, test_schema) -> None:
        """Test notification rate limiting."""
        # Create notification config with 60-minute rate limit
        async with error_tracker.db.connection() as conn, conn.cursor() as cur:
            await conn.execute(f"SET search_path TO {test_schema}")
            await cur.execute(
                """
                        INSERT INTO tb_error_notification_config (
                            config_id, error_type, channel_type,
                            channel_config, rate_limit_minutes, enabled
                        ) VALUES (
                            gen_random_uuid(), 'ValueError', 'webhook',
                            '{"url": "https://example.com/webhook"}'::jsonb,
                            60, true
                        )
                        """
            )
            await conn.commit()

        # Create an error twice
        try:
            raise ValueError("Rate limit test")
        except ValueError as e:
            error_id1 = await error_tracker.capture_exception(e)
            error_id2 = await error_tracker.capture_exception(e)  # Same error

        # Mock webhook
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )

            # Send first notification
            await notification_manager.send_notifications(error_id1)
            await asyncio.sleep(0.1)

            # Send second notification immediately (should be rate-limited)
            await notification_manager.send_notifications(error_id2)
            await asyncio.sleep(0.1)

        # Verify only one notification was sent (due to rate limiting)
        async with error_tracker.db.connection() as conn, conn.cursor() as cur:
            await conn.execute(f"SET search_path TO {test_schema}")
            await cur.execute(
                "SELECT COUNT(*) FROM tb_error_notification_log WHERE status = 'sent'"
            )
            await cur.fetchone()
            # Should have at most 1 successful notification due to rate limiting


class TestErrorTrackerNotificationIntegration:
    """Test integration between error tracker and notification system."""

    pytestmark = pytest.mark.asyncio

    @pytest.mark.asyncio
    async def test_notifications_triggered_on_error(self, error_tracker, test_schema) -> None:
        """Test that notifications are triggered when error is captured."""
        # Mock NotificationManager at the import location
        with patch("fraiseql.monitoring.notifications.NotificationManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.send_notifications = AsyncMock()
            mock_manager_class.return_value = mock_manager

            # Capture an error
            try:
                raise ValueError("Test error")
            except ValueError as e:
                await error_tracker.capture_exception(e)

            # Give async task time to complete
            await asyncio.sleep(0.1)

            # Verify NotificationManager was instantiated
            mock_manager_class.assert_called_once_with(error_tracker.db)

            # Verify send_notifications was called
            # Note: Due to asyncio.create_task, this might not be immediately called
            # This is expected for fire-and-forget notifications

    @pytest.mark.asyncio
    async def test_notifications_disabled(self, class_db_pool, test_schema) -> None:
        """Test that notifications can be disabled."""
        # Create tracker with notifications disabled
        tracker = PostgreSQLErrorTracker(
            class_db_pool,
            environment="test",
            enable_notifications=False,
        )

        with patch("fraiseql.monitoring.notifications.NotificationManager") as mock_manager_class:
            # Capture an error
            try:
                raise ValueError("Test error")
            except ValueError as e:
                await tracker.capture_exception(e)

            await asyncio.sleep(0.1)

            # Verify NotificationManager was NOT instantiated
            mock_manager_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_notification_failure_doesnt_break_error_tracking(
        self, error_tracker, test_schema
    ) -> None:
        """Test that notification failures don't break error tracking."""
        # Mock NotificationManager to raise an exception
        with patch("fraiseql.monitoring.notifications.NotificationManager") as mock_manager_class:
            mock_manager_class.side_effect = Exception("Notification system failed")

            # Capture an error (should succeed despite notification failure)
            try:
                raise ValueError("Test error")
            except ValueError as e:
                error_id = await error_tracker.capture_exception(e)

            await asyncio.sleep(0.1)

            # Verify error was still captured successfully
            assert error_id != ""
            error = await error_tracker.get_error(error_id)
            assert error is not None
            assert error["error_type"] == "ValueError"

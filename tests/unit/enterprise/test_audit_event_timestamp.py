"""The audit logger sends an event's time as an instant, not a local wall time."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from fraiseql.enterprise.audit.event_logger import AuditLogger


def test_event_timestamp_carries_its_utc_offset() -> None:
    """A naive ISO string is read in the session's time zone, which moves the event.

    The timestamp must say it is UTC so PostgreSQL stores the same instant whatever
    the connection's ``TimeZone`` is.
    """
    event = AuditLogger(MagicMock())._prepare_event(
        event_type="user.created",
        event_data={},
        user_id=None,
        tenant_id=None,
        ip_address=None,
    )

    assert event["timestamp"].tzinfo is not None
    assert event["timestamp"].utcoffset() == timedelta(0)
    sent = datetime.fromisoformat(event["timestamp_str"])
    assert sent.utcoffset() == timedelta(0)
    assert abs(sent - datetime.now(UTC)) < timedelta(minutes=1)

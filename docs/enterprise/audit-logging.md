<!-- Skip to main content -->
---

title: Enterprise Audit Logging Documentation
description: FraiseQL's Enterprise Audit Logging system provides:
keywords: []
tags: ["documentation", "reference"]
---

# Enterprise Audit Logging Documentation

**Status:** ✅ Production Ready
**Topic**: Audit Event Logging & Chain Verification
**Performance**: ~1ms per event (Rust FFI), ~5-10ms (Python fallback)

---

## Overview

FraiseQL's Enterprise Audit Logging system provides:

- **Debezium-Compatible Events**: Industry-standard CDC (Change Data Capture) format
- **Cryptographic Chain Verification**: SHA-256 hash chains + HMAC-SHA256 signatures
- **Per-Tenant Audit Chains**: Separate chains per tenant for multi-tenancy
- **Query/Performance Tracking**: Complexity, depth, duration, result size
- **Rust FFI Mode**: Optimized direct database operations (1ms/event)
- **Comprehensive Event Types**: 40+ event types covering all operations
- **Chain Verification**: Detect tampering via cryptographic verification

---

## Quick Start

### Basic Setup

```python
from fraiseql.enterprise.audit import AuditEventLogger

# Initialize at application startup
audit_logger = AuditEventLogger(
    repo=fraiseql_repo,
    connection_string="postgresql://user:pass@host/db",
    use_rust=True  # Prefer Rust FFI (faster)
)
```

### Logging Events

```python
# Log a mutation completion
event_id = await audit_logger.log_event(
    tenant_id="tenant-123",
    user_id="user-456",
    event_type="mutation.completed",
    op="u",  # u=update, c=create, d=delete, r=read
    before_data={"name": "Old Name"},
    after_data={"name": "New Name"},
    duration_ms=45.3
)

# Log an authentication event
event_id = await audit_logger.log_event(
    tenant_id="tenant-123",
    user_id="user-456",
    event_type="auth.login",
    ip_address="203.0.113.1"
)
```

### Querying Audit Events

```python
from fraiseql.enterprise.audit import AuditEventFilter

# Get recent events
events, total = await audit_logger.get_events(
    tenant_id="tenant-123",
    filter_=AuditEventFilter(
        event_type="mutation.completed",
        start_time=datetime.now() - timedelta(hours=1),
        limit=100
    )
)

for event in events:
    print(f"{event.created_at} {event.event_type}: {event.user_id}")
```

### Verifying Chain Integrity

```python
# Verify cryptographic chain
result = await audit_logger.verify_chain(
    tenant_id="tenant-123"
)

if result.is_valid:
    print(f"Chain valid: {result.verified_events}/{result.total_events}")
else:
    print(f"Chain broken at event {result.broken_at_index}")
    print(f"Error: {result.error_message}")
```

---

## Architecture

### Event Structure

Each audit event captures comprehensive change information:

```python
@strawberry.type
class AuditEvent:
    # Identity
    id: UUID                    # Unique event ID
    event_type: str            # e.g., "mutation.completed"

    # Change Information
    change_status: str         # "ok", "error", "partial"
    op: str                    # c=create, r=read, u=update, d=delete
    before_data: dict | None   # Previous state (Debezium format)
    after_data: dict | None    # Current state (Debezium format)
    source: dict | None        # Metadata (table, schema, database)

    # Cryptographic Chain
    event_hash: str            # SHA-256 of event
    previous_event_hash: str   # Link to prior event
    signature: str             # HMAC-SHA256 signature

    # Context
    tenant_id: UUID           # Multi-tenant scoping
    user_id: UUID | None      # Who triggered (optional)
    ip_address: str | None    # Source IP

    # Query/Performance
    query_hash: str | None    # Hash of executed query
    query_depth: int | None   # GraphQL nesting depth
    query_complexity: int | None  # Complexity score
    query_fields_count: int | None  # Fields requested

    # Performance
    duration_ms: float | None # Operation duration
    result_size_bytes: int | None  # Payload size

    # Metadata
    created_at: datetime      # Immutable timestamp
```

### Debezium-Compatible Format

FraiseQL audit events follow Debezium CDC format:

```python
@strawberry.type
class DebeziumEvent:
    """
    Debezium Change Data Capture format for compatibility with
    stream processing systems (Kafka, Pulsar, etc.)
    """

    before: dict | None    # State before change
    after: dict | None     # State after change
    source: dict           # Source metadata
    op: str                # Operation: c/r/u/d
    ts_ms: int             # Timestamp in milliseconds
```

**Example**:

```json
{
  "before": {
    "id": "user-123",
    "name": "John Doe",
    "status": "active"
  },
  "after": {
    "id": "user-123",
    "name": "Jane Doe",
    "status": "active"
  },
  "source": {
    "table": "users",
    "schema": "public",
    "database": "FraiseQL",
    "ts_ms": 1705000000000
  },
  "op": "u",
  "ts_ms": 1705000000000
}
```

### Cryptographic Chain

FraiseQL maintains an immutable cryptographic chain:

```text
Event 1
├─ event_hash: SHA256(event_data)
├─ previous_hash: NULL (first event)
└─ signature: HMAC(event_hash, secret_key)
        ↓
Event 2
├─ event_hash: SHA256(event_data)
├─ previous_hash: Event1.event_hash
└─ signature: HMAC(event_hash, secret_key)
        ↓
Event 3
├─ event_hash: SHA256(event_data)
├─ previous_hash: Event2.event_hash
└─ signature: HMAC(event_hash, secret_key)
```

**Chain Verification**:

1. Compute hash of each event's data
2. Verify hash matches stored `event_hash`
3. Verify each event's `previous_hash` matches prior event
4. Verify HMAC signature with shared secret
5. Report first break in chain (if any)

---

## Event Types

FraiseQL supports 40+ event types across all operations:

### Query Events

| Event Type | Description | Fields |
|-----------|---|---|
| `query.executed` | Query started | query_hash, query_depth, complexity |
| `query.completed` | Query finished | duration_ms, result_size_bytes, cache_hit |
| `query.failed` | Query errored | error_info, duration_ms |

### Mutation Events

| Event Type | Description | Fields |
|-----------|---|---|
| `mutation.started` | Mutation began | query_hash, user_id |
| `mutation.completed` | Mutation finished | before_data, after_data, duration_ms |
| `mutation.failed` | Mutation errored | error_info, duration_ms |

### Authentication Events

| Event Type | Description | Fields |
|-----------|---|---|
| `auth.login` | User logged in | user_id, ip_address |
| `auth.logout` | User logged out | user_id |
| `auth.token_refresh` | Token refreshed | user_id |
| `auth.failed` | Auth failed | reason, ip_address |
| `auth.permission_denied` | Unauthorized action | resource, action, user_id |

### Configuration Events

| Event Type | Description | Fields |
|-----------|---|---|
| `config.changed` | Config updated | before_data, after_data |
| `schema.updated` | Schema changed | before_data, after_data |
| `security.policy_changed` | Policy updated | policy_type, before_data, after_data |

### Security Events

| Event Type | Description | Fields |
|-----------|---|---|
| `security.violation` | Security violation | violation_type, severity |
| `security.rate_limit_exceeded` | Rate limit hit | limit, window, current_count |
| `security.introspection_blocked` | Introspection rejected | ip_address, user_id |
| `security.tls_violation` | TLS issue | tls_version, cert_present |

### Data Access Events

| Event Type | Description | Fields |
|-----------|---|---|
| `data.accessed` | Data read | table_name, row_count |
| `data.modified` | Data changed | table_name, op, row_count |
| `data.exported` | Data exported | table_name, export_format, row_count |
| `data.deleted` | Data deleted | table_name, row_count |

---

## Logging API

### Log Events

```python
# Basic event
event_id = await audit_logger.log_event(
    tenant_id="tenant-123",
    event_type="mutation.completed",
    op="u"
)

# Complete event with all context
event_id = await audit_logger.log_event(
    tenant_id="tenant-123",
    user_id="user-456",
    event_type="mutation.completed",
    change_status="ok",
    op="u",
    before_data={"status": "draft"},
    after_data={"status": "published"},
    source={
        "table": "posts",
        "schema": "public",
        "database": "FraiseQL"
    },
    extra_metadata={"tags": ["blog", "featured"]},
    ip_address="203.0.113.1",
    query_hash="a1b2c3d4e5f6g7h8",
    query_depth=3,
    query_complexity=45,
    query_fields_count=12,
    duration_ms=78.5,
    result_size_bytes=2048
)
```

### Query Events

```python
# Get recent events for a tenant
events, total = await audit_logger.get_events(
    tenant_id="tenant-123"
)

# Filter by event type
events, total = await audit_logger.get_events(
    tenant_id="tenant-123",
    filter_=AuditEventFilter(
        event_type="mutation.completed"
    )
)

# Filter by user and time range
events, total = await audit_logger.get_events(
    tenant_id="tenant-123",
    filter_=AuditEventFilter(
        user_id="user-456",
        start_time=datetime(2025, 1, 1),
        end_time=datetime(2025, 1, 31),
        limit=500
    )
)

# Filter by IP address (security audits)
events, total = await audit_logger.get_events(
    tenant_id="tenant-123",
    filter_=AuditEventFilter(
        ip_address="203.0.113.1",
        start_time=datetime.now() - timedelta(days=7)
    )
)
```

### Verify Chain Integrity

```python
# Verify cryptographic chain
result = await audit_logger.verify_chain(
    tenant_id="tenant-123"
)

print(f"Chain valid: {result.is_valid}")
print(f"Total events: {result.total_events}")
print(f"Verified events: {result.verified_events}")

if not result.is_valid:
    print(f"Break at event {result.broken_at_index}")
    print(f"Error: {result.error_message}")
```

---

## Event Data Structures

### QueryEventData

```python
@strawberry.input
class QueryEventData:
    query_hash: str
    query_string: str | None  # Optional for privacy
    variables: dict | None
    query_depth: int
    query_complexity: int
    query_fields_count: int
```

### MutationEventData

```python
@strawberry.input
class MutationEventData:
    mutation_hash: str
    mutation_name: str | None
    variables: dict | None
    changes_count: int
    affected_tables: list[str]
```

### QueryCompletionEventData

```python
@strawberry.input
class QueryCompletionEventData:
    query_hash: str
    duration_ms: float
    field_count: int
    cache_hit: bool
    result_size_bytes: int
```

### AuthenticationEventData

```python
@strawberry.input
class AuthenticationEventData:
    auth_method: str  # "oauth", "jwt", "session", "mfa"
    username: str | None
    ip_address: str
    user_agent: str | None
    success: bool
    failure_reason: str | None
```

### SecurityViolationEventData

```python
@strawberry.input
class SecurityViolationEventData:
    violation_type: str  # "injection", "xss", "csrfblocked"
    severity: str  # "low", "medium", "high", "critical"
    ip_address: str
    user_id: str | None
    details: dict
```

---

## Integration with GraphQL

### Automatic Event Logging Middleware

```python
from fraiseql.enterprise.audit.middleware import create_audit_middleware

# Add audit logging middleware
schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[create_audit_middleware(audit_logger=audit_logger)]
)
```

**Automatically logs**:

- All mutations (create, update, delete)
- Failed queries with error details
- Authentication events
- Permission denials
- Performance metrics

### Manual Event Logging

```python
from fraiseql.strawberry_compat import strawberry

@strawberry.mutation
async def publish_post(
    info: strawberry.types.Info,
    post_id: str,
    audit_logger: AuditEventLogger
) -> Post:
    post = await update_post_status(post_id, "published")

    # Manually log the event
    await audit_logger.log_event(
        tenant_id=info.context["tenant_id"],
        user_id=info.context["user_id"],
        event_type="mutation.completed",
        op="u",
        before_data={"status": "draft"},
        after_data={"status": "published"},
        duration_ms=45.3
    )

    return post
```

---

## Compliance & Governance

### Immutability Guarantees

Audit events are **immutable**:

- `created_at` timestamp set once
- All fields are read-only in database
- No UPDATE or DELETE operations allowed
- Only append-only INSERT

**Database enforcement**:

```sql
-- Audit table is append-only
CREATE TABLE audit_events (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- All other fields...
);

-- Trigger prevents modifications
CREATE TRIGGER audit_immutable
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW
RAISE EXCEPTION 'Audit events are immutable';
```

### Retention Policies

```python
# Configure retention
config = AuditConfig(
    retention_days=90,           # Keep 90 days of events
    archive_destination=None,    # Optional: archive old events
    enable_chain_verification=True
)

# Archive old events (optional)
archived = await audit_logger.archive_events(
    tenant_id="tenant-123",
    before_date=datetime.now() - timedelta(days=90),
    destination="s3://archive-bucket/audit/"
)
```

### Compliance Reporting

```python
# Generate compliance report
report = await audit_logger.generate_compliance_report(
    tenant_id="tenant-123",
    start_date=datetime(2025, 1, 1),
    end_date=datetime(2025, 1, 31),
    event_types=["mutation.completed", "auth.login", "auth.failed"]
)

print(f"Total events: {report.total_events}")
print(f"Mutations: {report.mutation_count}")
print(f"Auth events: {report.auth_count}")
print(f"Security violations: {report.violation_count}")
print(f"Chain valid: {report.chain_verification.is_valid}")
```

---

## Query/Performance Tracking

### Capturing Performance Data

Log query and mutation performance:

```python
event_id = await audit_logger.log_event(
    tenant_id="tenant-123",
    user_id="user-456",
    event_type="query.completed",
    query_hash="abc123def456",
    query_depth=3,
    query_complexity=75,
    query_fields_count=12,
    duration_ms=45.3,
    result_size_bytes=4096
)
```

### Performance Analytics

```python
# Get slow queries
from fraiseql.enterprise.audit import AuditEventFilter

slow_queries = await audit_logger.get_events(
    tenant_id="tenant-123",
    filter_=AuditEventFilter(
        event_type="query.completed",
        # Custom filter for duration > 1000ms
        extra_filters={"duration_ms": {">": 1000}}
    )
)

for event in slow_queries:
    print(f"Query: {event.query_hash}")
    print(f"Duration: {event.duration_ms}ms")
    print(f"Complexity: {event.query_complexity}")
```

### Query Complexity Distribution

```python
# Analyze query complexity
report = await audit_logger.get_complexity_report(
    tenant_id="tenant-123",
    days=7
)

print(f"Avg complexity: {report.avg_complexity}")
print(f"Max complexity: {report.max_complexity}")
print(f"Queries > 100: {report.high_complexity_count}")
```

---

## Security Audit Use Cases

### User Activity Audit

```python
# Get all activities for a specific user
events, total = await audit_logger.get_events(
    tenant_id="tenant-123",
    filter_=AuditEventFilter(
        user_id="user-456",
        start_time=datetime.now() - timedelta(days=30)
    )
)

for event in events:
    print(f"{event.created_at} {event.event_type}")
```

### Failed Authentication Detection

```python
# Find suspicious failed login patterns
failed_logins = await audit_logger.get_events(
    tenant_id="tenant-123",
    filter_=AuditEventFilter(
        event_type="auth.failed",
        start_time=datetime.now() - timedelta(hours=1)
    )
)

from collections import Counter
ips = Counter(e.ip_address for e in failed_logins)

for ip, count in ips.most_common(10):
    if count > 5:
        print(f"Alert: {count} failed logins from {ip}")
```

### Data Access Audit

```python
# Track who accessed sensitive data
sensitive_queries = await audit_logger.get_events(
    tenant_id="tenant-123",
    filter_=AuditEventFilter(
        event_type="query.completed",
        extra_filters={"query_hash": ["pii_query_hash1", "pii_query_hash2"]}
    )
)

for event in sensitive_queries:
    print(f"User {event.user_id} accessed sensitive data at {event.created_at}")
    print(f"From IP: {event.ip_address}")
```

### Configuration Change Tracking

```python
# Find all configuration changes
config_changes = await audit_logger.get_events(
    tenant_id="tenant-123",
    filter_=AuditEventFilter(
        event_type="config.changed",
        start_time=datetime.now() - timedelta(days=7)
    )
)

for event in config_changes:
    print(f"Changed by: {event.user_id}")
    print(f"Before: {event.before_data}")
    print(f"After: {event.after_data}")
```

---

## Chain Verification Workflow

### Regular Verification

Run chain verification periodically (e.g., daily):

```python
# Daily verification task
async def verify_audit_chain_daily():
    tenants = await get_all_tenants()

    for tenant in tenants:
        result = await audit_logger.verify_chain(tenant_id=tenant.id)

        if not result.is_valid:
            # Alert: Chain broken
            await send_alert(
                f"Audit chain broken for {tenant.id} "
                f"at event {result.broken_at_index}"
            )
        else:
            # Log successful verification
            await log_verification(
                tenant_id=tenant.id,
                verified_count=result.verified_events,
                total_count=result.total_events
            )
```

### Chain Repair

If tampering is detected:

1. **Isolate**: Stop accepting new audit events
2. **Investigate**: Review events around break point
3. **Rebuild**: Restore from backup and replay
4. **Verify**: Run chain verification again

---

## Performance Characteristics

### Event Logging

| Operation | Latency | Backend |
|-----------|---------|---------|
| Log event (Rust FFI) | ~1ms | Direct database |
| Log event (Python fallback) | ~5-10ms | Via FraiseQLRepository |
| Batch log (10 events) | ~10-20ms | Single transaction |

### Querying Events

| Operation | Query Time | Notes |
|-----------|-----------|-------|
| Get 100 recent events | ~10-50ms | Indexed by tenant_id, created_at |
| Get events by user | ~20-100ms | Scans user_id index |
| Get events by type | ~20-100ms | Scans event_type index |
| Get events by time range | ~50-200ms | Range scan on created_at |

### Chain Verification

| Operation | Time (per 10K events) | Notes |
|-----------|-----|-------|
| Verify chain | ~500-1000ms | Linear hash verification |
| Verify signature | ~100-200ms | HMAC check per event |

---

## Best Practices

### 1. Log Comprehensive Context

Always include full context:

```python
# GOOD - Full context
await audit_logger.log_event(
    tenant_id=tenant_id,
    user_id=user_id,
    event_type="mutation.completed",
    ip_address=request.client.host,
    query_complexity=complexity_score,
    duration_ms=elapsed_ms,
    before_data=old_state,
    after_data=new_state
)

# BAD - Minimal context
await audit_logger.log_event(
    tenant_id=tenant_id,
    event_type="mutation.completed"
)
```

### 2. Use Rust FFI Mode

Prefer Rust FFI for better performance:

```python
# GOOD
audit_logger = AuditEventLogger(
    repo=repo,
    connection_string=db_url,
    use_rust=True  # Prefer Rust FFI
)

# Falls back to Python if Rust unavailable
```

### 3. Run Regular Verification

Set up periodic chain verification:

```python
# Daily verification
scheduler.add_job(
    verify_audit_chain_daily,
    trigger="cron",
    hour=2  # 2 AM daily
)
```

### 4. Archive Old Events

Archive events older than retention period:

```python
# Monthly archive task
scheduler.add_job(
    archive_old_events,
    trigger="cron",
    day=1,  # First day of month
    hour=3
)
```

### 5. Monitor Chain Health

Alert on chain breaks:

```python
# Set up alert
if not verification_result.is_valid:
    send_critical_alert(
        f"Audit chain integrity violation detected "
        f"at event {verification_result.broken_at_index}"
    )
```

---

## Troubleshooting

### Chain Verification Fails

1. Check event counts:

   ```sql
   SELECT COUNT(*) FROM audit_events WHERE tenant_id = ?;
   ```

2. Inspect event at break point:

   ```sql
   SELECT id, event_hash, previous_hash FROM audit_events
   WHERE tenant_id = ? AND created_at > ?
   ORDER BY created_at LIMIT 10;
   ```

3. Verify signatures:

   ```sql
   SELECT id, signature FROM audit_events WHERE tenant_id = ?
   ORDER BY created_at DESC LIMIT 100;
   ```

### High Event Logging Latency

1. Check database:

   ```sql
   EXPLAIN ANALYZE INSERT INTO audit_events (...);
   ```

2. Monitor Rust FFI:
   - Check if Rust library is loaded: `audit_logger.use_rust`
   - Check fallback to Python if slow

3. Consider batching:

   ```python
   # Batch multiple events
   events = [...]
   await audit_logger.batch_log_events(events)
   ```

---

## Summary

FraiseQL Audit Logging provides:

✅ **Debezium-compatible** events for CDC integration
✅ **Cryptographic chains** for tamper detection
✅ **Per-tenant isolation** for multi-tenancy
✅ **Query/performance tracking** for analytics
✅ **40+ event types** covering all operations
✅ **Immutable append-only** logs
✅ **Chain verification** for integrity assurance
✅ **Compliance reporting** for audits

Perfect for SOC 2, ISO 27001, and regulatory compliance requirements.

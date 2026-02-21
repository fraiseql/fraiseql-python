//! Async audit logging for security events.

use chrono::{DateTime, Utc};
use deadpool_postgres::Pool;
use serde::{Deserialize, Serialize};
use tokio::sync::mpsc;
use uuid::Uuid;

use super::errors::Result;

/// Audit event types
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AuditEventType {
    // Authentication
    LoginSuccess,
    LoginFailure,
    Logout,
    TokenRefresh,
    TokenRevoke,

    // Authorization
    PermissionGranted,
    PermissionDenied,
    RoleAssigned,
    RoleRevoked,

    // Data access
    DataRead,
    DataWrite,
    DataDelete,

    // Security
    RateLimitExceeded,
    InvalidToken,
    SuspiciousActivity,
    SecurityViolation,
}

impl AuditEventType {
    pub fn severity(&self) -> AuditSeverity {
        match self {
            AuditEventType::LoginFailure
            | AuditEventType::PermissionDenied
            | AuditEventType::InvalidToken
            | AuditEventType::SecurityViolation => AuditSeverity::High,

            AuditEventType::RateLimitExceeded | AuditEventType::SuspiciousActivity => {
                AuditSeverity::Medium
            },

            _ => AuditSeverity::Low,
        }
    }

    pub fn category(&self) -> &'static str {
        match self {
            AuditEventType::LoginSuccess
            | AuditEventType::LoginFailure
            | AuditEventType::Logout
            | AuditEventType::TokenRefresh
            | AuditEventType::TokenRevoke => "authentication",

            AuditEventType::PermissionGranted
            | AuditEventType::PermissionDenied
            | AuditEventType::RoleAssigned
            | AuditEventType::RoleRevoked => "authorization",

            AuditEventType::DataRead | AuditEventType::DataWrite | AuditEventType::DataDelete => {
                "data_access"
            },

            AuditEventType::RateLimitExceeded
            | AuditEventType::InvalidToken
            | AuditEventType::SuspiciousActivity
            | AuditEventType::SecurityViolation => "security",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum AuditSeverity {
    Low,
    Medium,
    High,
    Critical,
}

/// Audit event
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuditEvent {
    pub id:         Uuid,
    pub event_type: AuditEventType,
    pub user_id:    Option<Uuid>,
    pub tenant_id:  Option<Uuid>,
    pub resource:   Option<String>,
    pub action:     Option<String>,
    pub status:     String, // "success" or "failure"
    pub ip_address: Option<String>,
    pub user_agent: Option<String>,
    pub metadata:   Option<serde_json::Value>,
    pub timestamp:  DateTime<Utc>,
    pub severity:   AuditSeverity,
}

impl AuditEvent {
    pub fn new(event_type: AuditEventType) -> Self {
        Self {
            id:         Uuid::new_v4(),
            event_type: event_type.clone(),
            user_id:    None,
            tenant_id:  None,
            resource:   None,
            action:     None,
            status:     "success".to_string(),
            ip_address: None,
            user_agent: None,
            metadata:   None,
            timestamp:  Utc::now(),
            severity:   event_type.severity(),
        }
    }

    pub fn with_user(mut self, user_id: Uuid) -> Self {
        self.user_id = Some(user_id);
        self
    }

    pub fn with_tenant(mut self, tenant_id: Uuid) -> Self {
        self.tenant_id = Some(tenant_id);
        self
    }

    pub fn with_resource(mut self, resource: String, action: String) -> Self {
        self.resource = Some(resource);
        self.action = Some(action);
        self
    }

    pub fn with_status(mut self, status: String) -> Self {
        self.status = status;
        self
    }

    pub fn with_metadata(mut self, metadata: serde_json::Value) -> Self {
        self.metadata = Some(metadata);
        self
    }

    pub fn with_ip(mut self, ip_address: String) -> Self {
        self.ip_address = Some(ip_address);
        self
    }

    pub fn with_user_agent(mut self, user_agent: String) -> Self {
        self.user_agent = Some(user_agent);
        self
    }

    pub fn with_severity(mut self, severity: AuditSeverity) -> Self {
        self.severity = severity;
        self
    }
}

/// Async audit logger with buffered writes
pub struct AuditLogger {
    tx: mpsc::UnboundedSender<AuditEvent>,
}

impl AuditLogger {
    /// Create audit logger with async worker
    pub fn new(pool: Pool) -> Self {
        let (tx, rx) = mpsc::unbounded_channel();

        // Spawn async worker to write audit logs
        tokio::spawn(async move {
            Self::audit_worker(pool, rx).await;
        });

        Self { tx }
    }

    /// Log audit event (non-blocking)
    pub fn log(&self, event: AuditEvent) {
        // Fire and forget - if channel is closed, event is lost
        // Production would use reliable queue (Kafka, RabbitMQ)
        let _ = self.tx.send(event);
    }

    /// Async worker to write audit logs to database
    async fn audit_worker(pool: Pool, mut rx: mpsc::UnboundedReceiver<AuditEvent>) {
        let mut consecutive_errors = 0;
        const MAX_CONSECUTIVE_ERRORS: u32 = 10;

        while let Some(event) = rx.recv().await {
            match Self::write_event(&pool, &event).await {
                Ok(_) => {
                    consecutive_errors = 0; // Reset error counter on success
                },
                Err(e) => {
                    consecutive_errors += 1;
                    eprintln!("Failed to write audit log (attempt {}): {}", consecutive_errors, e);

                    // If too many consecutive errors, log to stderr and continue
                    // In production, this might trigger alerts or fallback logging
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS {
                        eprintln!(
                            "WARNING: {} consecutive audit log failures. Check database connectivity.",
                            consecutive_errors
                        );
                        // Could implement circuit breaker pattern here
                    }

                    // For critical events, retry with backoff
                    if Self::should_retry(&event, consecutive_errors) {
                        consecutive_errors =
                            Self::retry_critical_event(&pool, &event, consecutive_errors).await;
                    }
                },
            }
        }
    }

    /// Check if we should retry writing this event
    fn should_retry(event: &AuditEvent, consecutive_errors: u32) -> bool {
        Self::is_critical_event(event) && consecutive_errors < 3
    }

    /// Retry writing a critical event with exponential backoff
    async fn retry_critical_event(
        pool: &deadpool_postgres::Pool,
        event: &AuditEvent,
        consecutive_errors: u32,
    ) -> u32 {
        // Exponential backoff
        tokio::time::sleep(tokio::time::Duration::from_millis(100 * consecutive_errors as u64))
            .await;

        // Retry write
        if (Self::write_event(pool, event).await).is_ok() {
            0 // Reset error counter on success
        } else {
            consecutive_errors // Keep current count on failure
        }
    }

    /// Check if event is critical and should be retried
    fn is_critical_event(event: &AuditEvent) -> bool {
        matches!(
            event.event_type,
            AuditEventType::LoginFailure
                | AuditEventType::PermissionDenied
                | AuditEventType::InvalidToken
                | AuditEventType::SecurityViolation
                | AuditEventType::SuspiciousActivity
        )
    }

    /// Write single event to database
    async fn write_event(pool: &Pool, event: &AuditEvent) -> Result<()> {
        let client = pool.get().await?;

        let sql = r#"
            INSERT INTO audit_logs (
                id, event_type, user_id, tenant_id, resource, action,
                status, ip_address, user_agent, metadata, timestamp, severity
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        "#;

        let event_type_json = serde_json::to_string(&event.event_type).map_err(|e| {
            super::errors::SecurityError::AuditLogFailure(format!(
                "Failed to serialize event type: {}",
                e
            ))
        })?;
        let severity_json = serde_json::to_string(&event.severity).map_err(|e| {
            super::errors::SecurityError::AuditLogFailure(format!(
                "Failed to serialize severity: {}",
                e
            ))
        })?;

        client
            .execute(
                sql,
                &[
                    &event.id.to_string(),
                    &event_type_json,
                    &event.user_id.map(|u| u.to_string()),
                    &event.tenant_id.map(|t| t.to_string()),
                    &event.resource,
                    &event.action,
                    &event.status,
                    &event.ip_address,
                    &event.user_agent,
                    &event.metadata.as_ref().map(|m| serde_json::to_string(m).unwrap_or_default()),
                    &event.timestamp.to_rfc3339(),
                    &severity_json,
                ],
            )
            .await?;

        Ok(())
    }

    /// Get audit statistics
    pub async fn stats(&self, pool: &Pool) -> Result<AuditStats> {
        let client = pool.get().await?;

        let sql = "SELECT COUNT(*) as total_events FROM audit_logs";
        let total_events: i64 = client.query_one(sql, &[]).await?.get(0);

        let sql = "SELECT COUNT(*) as recent_events FROM audit_logs WHERE timestamp > NOW() - INTERVAL '1 hour'";
        let recent_events: i64 = client.query_one(sql, &[]).await?.get(0);

        Ok(AuditStats {
            total_events:  total_events as usize,
            recent_events: recent_events as usize,
        })
    }
}

impl Clone for AuditLogger {
    fn clone(&self) -> Self {
        Self {
            tx: self.tx.clone(),
        }
    }
}

#[derive(Debug)]
pub struct AuditStats {
    pub total_events:  usize,
    pub recent_events: usize,
}

//! Database pool configuration.

use crate::db::errors::{DatabaseError, DatabaseResult};
use std::time::Duration;

/// SSL/TLS mode for `PostgreSQL` connections.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum SslMode {
    /// No SSL/TLS (insecure, development only)
    Disable,
    /// Prefer SSL/TLS but allow plaintext fallback
    #[default]
    Prefer,
    /// Require SSL/TLS (fail if unavailable)
    Require,
}

impl SslMode {
    /// Parse SSL mode from string.
    ///
    /// # Errors
    ///
    /// Returns `DatabaseError::Configuration` if the string is not a valid SSL mode.
    /// Valid values are: "disable", "prefer", "require" (case-insensitive).
    pub fn parse_mode(s: &str) -> DatabaseResult<Self> {
        match s.to_lowercase().as_str() {
            "disable" => Ok(Self::Disable),
            "prefer" => Ok(Self::Prefer),
            "require" => Ok(Self::Require),
            _ => Err(DatabaseError::Configuration(format!(
                "Invalid ssl_mode: '{s}'. Must be 'disable', 'prefer', or 'require'"
            ))),
        }
    }
}

impl std::str::FromStr for SslMode {
    type Err = DatabaseError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Self::parse_mode(s)
    }
}

/// Complete database pool configuration.
#[derive(Debug, Clone)]
pub struct DatabaseConfig {
    /// Database host (default: "localhost")
    pub host: String,
    /// Database port (default: 5432)
    pub port: u16,
    /// Database name
    pub database: String,
    /// Username
    pub username: String,
    /// Password (optional)
    pub password: Option<String>,

    // Pool settings
    /// Maximum pool size (default: 10)
    pub max_size: usize,
    /// Minimum idle connections (default: 1)
    pub min_idle: Option<usize>,

    // Timeouts
    /// Connection timeout (default: 30s)
    pub connect_timeout: Duration,
    /// Idle timeout before recycling connection (default: 10 minutes)
    pub idle_timeout: Option<Duration>,
    /// Max connection lifetime before forced recycling (default: 30 minutes)
    pub max_lifetime: Option<Duration>,
    /// Wait timeout for getting connection from pool (default: 30s)
    pub wait_timeout: Option<Duration>,

    // SSL/TLS
    /// SSL mode (default: Prefer)
    pub ssl_mode: SslMode,

    // Application
    /// Application name for `PostgreSQL` logging (default: "fraiseql")
    pub application_name: String,
}

impl Default for DatabaseConfig {
    fn default() -> Self {
        Self {
            host: "localhost".to_string(),
            port: 5432,
            database: "postgres".to_string(),
            username: "postgres".to_string(),
            password: None,

            max_size: 10,
            min_idle: Some(1),

            connect_timeout: Duration::from_secs(30),
            idle_timeout: Some(Duration::from_secs(600)), // 10 minutes
            max_lifetime: Some(Duration::from_secs(1800)), // 30 minutes
            wait_timeout: Some(Duration::from_secs(30)),

            ssl_mode: SslMode::Prefer,

            application_name: "fraiseql".to_string(),
        }
    }
}

impl DatabaseConfig {
    /// Create a new configuration with required fields.
    #[must_use]
    pub fn new(database: impl Into<String>) -> Self {
        Self {
            database: database.into(),
            ..Default::default()
        }
    }

    /// Parse from `DATABASE_URL` environment variable format.
    ///
    /// Format: `postgresql://user:password@host:port/database`
    ///
    /// # Errors
    ///
    /// Returns `DatabaseError::Configuration` if URL is invalid.
    ///
    /// # Panics
    ///
    /// This function uses `expect()` on values that have been pre-validated:
    /// - URL prefix is validated before `strip_prefix()`
    /// - Colon presence is checked before `split_once(':')`
    ///
    /// These panics indicate bugs in the parsing logic and should never occur
    /// in production with well-formed input validated by the initial checks.
    ///
    /// # Example
    ///
    /// ```rust
    /// use fraiseql_rs::db::pool_config::DatabaseConfig;
    ///
    /// let config = DatabaseConfig::from_url(
    ///     "postgresql://myuser:secret@db.example.com:5432/mydb"
    /// )?;
    /// assert_eq!(config.database, "mydb");
    /// assert_eq!(config.host, "db.example.com");
    /// # Ok::<(), fraiseql_rs::db::errors::DatabaseError>(())
    /// ```
    pub fn from_url(url: &str) -> DatabaseResult<Self> {
        // Basic parsing (production should use url crate)
        if !url.starts_with("postgresql://") && !url.starts_with("postgres://") {
            return Err(DatabaseError::Configuration(
                "URL must start with postgresql:// or postgres://".to_string(),
            ));
        }

        // Safe unwrap: we just checked starts_with above
        // SAFETY: This expect is safe because we just validated that the URL starts with
        // either "postgresql://" or "postgres://" in the preceding lines.
        #[allow(clippy::expect_used)]
        let url = url
            .strip_prefix("postgresql://")
            .or_else(|| url.strip_prefix("postgres://"))
            .expect("URL prefix was just validated");

        // Split user:pass@host:port/database
        let (credentials, rest) = url
            .split_once('@')
            .ok_or_else(|| DatabaseError::Configuration("Missing @ in URL".to_string()))?;

        let (host_port, database) = rest
            .split_once('/')
            .ok_or_else(|| DatabaseError::Configuration("Missing / in URL".to_string()))?;

        // Parse credentials
        let (username, password) = if credentials.contains(':') {
            // SAFETY: This expect is safe because we just checked that credentials contains ':' above.
            #[allow(clippy::expect_used)]
            let (u, p) = {
                credentials
                    .split_once(':')
                    .expect("':' was just checked to exist")
            };
            (u.to_string(), Some(p.to_string()))
        } else {
            (credentials.to_string(), None)
        };

        // Parse host:port
        let (host, port) = if host_port.contains(':') {
            // SAFETY: This expect is safe because we just checked that host_port contains ':' above.
            #[allow(clippy::expect_used)]
            let (h, p) = {
                host_port
                    .split_once(':')
                    .expect("':' was just checked to exist")
            };
            let port = p
                .parse::<u16>()
                .map_err(|e| DatabaseError::Configuration(format!("Invalid port: {e}")))?;
            (h.to_string(), port)
        } else {
            (host_port.to_string(), 5432)
        };

        Ok(Self {
            host,
            port,
            database: database.to_string(),
            username,
            password,
            ..Default::default()
        })
    }

    /// Set the host.
    #[must_use]
    pub fn with_host(mut self, host: impl Into<String>) -> Self {
        self.host = host.into();
        self
    }

    /// Set the port.
    #[must_use]
    pub const fn with_port(mut self, port: u16) -> Self {
        self.port = port;
        self
    }

    /// Set the username.
    #[must_use]
    pub fn with_username(mut self, username: impl Into<String>) -> Self {
        self.username = username.into();
        self
    }

    /// Set the password.
    #[must_use]
    pub fn with_password(mut self, password: impl Into<String>) -> Self {
        self.password = Some(password.into());
        self
    }

    /// Set the max pool size.
    #[must_use]
    pub const fn with_max_size(mut self, max_size: usize) -> Self {
        self.max_size = max_size;
        self
    }

    /// Set the SSL mode.
    #[must_use]
    pub const fn with_ssl_mode(mut self, ssl_mode: SslMode) -> Self {
        self.ssl_mode = ssl_mode;
        self
    }

    /// Set the connection timeout.
    #[must_use]
    pub const fn with_connect_timeout(mut self, timeout: Duration) -> Self {
        self.connect_timeout = timeout;
        self
    }

    /// Set the max connection lifetime.
    #[must_use]
    pub const fn with_max_lifetime(mut self, lifetime: Duration) -> Self {
        self.max_lifetime = Some(lifetime);
        self
    }

    /// Build a connection string for logging (password redacted).
    #[must_use]
    pub fn connection_string_safe(&self) -> String {
        let password = if self.password.is_some() {
            "[REDACTED]"
        } else {
            "[NONE]"
        };

        format!(
            "postgresql://{}:{}@{}:{}/{}",
            self.username, password, self.host, self.port, self.database
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::str::FromStr;

    #[test]
    fn test_default_config() {
        let config = DatabaseConfig::default();
        assert_eq!(config.host, "localhost");
        assert_eq!(config.port, 5432);
        assert_eq!(config.max_size, 10);
    }

    #[test]
    fn test_builder_pattern() {
        let config = DatabaseConfig::new("mydb")
            .with_host("db.example.com")
            .with_port(5433)
            .with_username("myuser")
            .with_password("secret")
            .with_max_size(20)
            .with_ssl_mode(SslMode::Require);

        assert_eq!(config.database, "mydb");
        assert_eq!(config.host, "db.example.com");
        assert_eq!(config.port, 5433);
        assert_eq!(config.username, "myuser");
        assert_eq!(config.password, Some("secret".to_string()));
        assert_eq!(config.max_size, 20);
        assert_eq!(config.ssl_mode, SslMode::Require);
    }

    #[test]
    fn test_connection_string_safe() {
        let config = DatabaseConfig::new("test").with_password("secret123");

        let conn_str = config.connection_string_safe();
        assert!(conn_str.contains("[REDACTED]"));
        assert!(!conn_str.contains("secret123"));
    }

    #[test]
    fn test_from_url() {
        let config =
            DatabaseConfig::from_url("postgresql://user:pass@localhost:5432/testdb").unwrap();

        assert_eq!(config.username, "user");
        assert_eq!(config.password, Some("pass".to_string()));
        assert_eq!(config.host, "localhost");
        assert_eq!(config.port, 5432);
        assert_eq!(config.database, "testdb");
    }

    #[test]
    fn test_from_url_no_password() {
        let config = DatabaseConfig::from_url("postgresql://user@localhost/testdb").unwrap();

        assert_eq!(config.username, "user");
        assert_eq!(config.password, None);
        assert_eq!(config.port, 5432); // default
    }

    #[test]
    fn test_from_url_custom_port() {
        let config = DatabaseConfig::from_url("postgresql://user@localhost:5433/testdb").unwrap();
        assert_eq!(config.port, 5433);
    }

    #[test]
    fn test_from_url_invalid() {
        let result = DatabaseConfig::from_url("http://invalid");
        assert!(result.is_err());
    }

    #[test]
    fn test_ssl_mode_parsing() {
        assert_eq!(
            SslMode::from_str("disable").expect("disable should parse"),
            SslMode::Disable
        );
        assert_eq!(
            SslMode::from_str("prefer").expect("prefer should parse"),
            SslMode::Prefer
        );
        assert_eq!(
            SslMode::from_str("require").expect("require should parse"),
            SslMode::Require
        );
        assert_eq!(
            SslMode::from_str("DISABLE").expect("DISABLE should parse"),
            SslMode::Disable
        );
        assert!(SslMode::from_str("invalid").is_err());
    }
}

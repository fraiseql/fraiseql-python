//! Configuration management.
//!
//! This module provides:
//! - Server configuration
//! - Database configuration
//! - Feature flags
//! - Environment loading

use crate::error::{FraiseQLError, Result};
use serde::{Deserialize, Serialize};

/// Main configuration structure.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FraiseQLConfig {
    /// Database connection URL.
    pub database_url: String,

    /// Server host.
    pub host: String,

    /// Server port.
    pub port: u16,

    /// Maximum connections in pool.
    pub max_connections: u32,

    /// Query timeout in seconds.
    pub query_timeout_secs: u64,
}

impl Default for FraiseQLConfig {
    fn default() -> Self {
        Self {
            database_url: String::new(),
            host: "0.0.0.0".to_string(),
            port: 8000,
            max_connections: 10,
            query_timeout_secs: 30,
        }
    }
}

impl FraiseQLConfig {
    /// Create a new configuration builder.
    #[must_use]
    pub fn builder() -> ConfigBuilder {
        ConfigBuilder::default()
    }

    /// Load configuration from environment variables.
    ///
    /// # Errors
    ///
    /// Returns error if required environment variables are missing.
    pub fn from_env() -> Result<Self> {
        let database_url = std::env::var("DATABASE_URL")
            .map_err(|_| FraiseQLError::Configuration("DATABASE_URL not set".to_string()))?;

        let host = std::env::var("FRAISEQL_HOST").unwrap_or_else(|_| "0.0.0.0".to_string());

        let port = std::env::var("FRAISEQL_PORT")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(8000);

        Ok(Self {
            database_url,
            host,
            port,
            ..Default::default()
        })
    }

    /// Create a test configuration.
    #[must_use]
    pub fn test() -> Self {
        Self {
            database_url: "postgresql://postgres:postgres@localhost:5432/fraiseql_test".to_string(),
            host: "127.0.0.1".to_string(),
            port: 0, // Random port
            max_connections: 2,
            query_timeout_secs: 5,
        }
    }
}

/// Configuration builder.
#[derive(Debug, Default)]
pub struct ConfigBuilder {
    config: FraiseQLConfig,
}

impl ConfigBuilder {
    /// Set the database URL.
    #[must_use]
    pub fn database_url(mut self, url: &str) -> Self {
        self.config.database_url = url.to_string();
        self
    }

    /// Set the server host.
    #[must_use]
    pub fn host(mut self, host: &str) -> Self {
        self.config.host = host.to_string();
        self
    }

    /// Set the server port.
    #[must_use]
    pub const fn port(mut self, port: u16) -> Self {
        self.config.port = port;
        self
    }

    /// Build the configuration.
    ///
    /// # Errors
    ///
    /// Returns error if configuration is invalid.
    pub fn build(self) -> Result<FraiseQLConfig> {
        if self.config.database_url.is_empty() {
            return Err(FraiseQLError::Configuration(
                "database_url is required".to_string(),
            ));
        }
        Ok(self.config)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = FraiseQLConfig::default();
        assert_eq!(config.port, 8000);
        assert_eq!(config.host, "0.0.0.0");
    }

    #[test]
    fn test_builder() {
        let config = FraiseQLConfig::builder()
            .database_url("postgresql://localhost/test")
            .port(9000)
            .build()
            .unwrap();

        assert_eq!(config.port, 9000);
        assert!(!config.database_url.is_empty());
    }

    #[test]
    fn test_builder_requires_database_url() {
        let result = FraiseQLConfig::builder().build();
        assert!(result.is_err());
    }
}

//! Security configuration management.

use std::env;

use super::{
    audit::AuditLogger,
    cors::{CORSConfig, CORSHandler},
    csrf::CSRFManager,
    headers::SecurityHeaders,
    rate_limit::{RateLimit, RateLimitStrategy, RateLimiter},
    validators::{QueryLimits, QueryValidator},
};

/// Master security configuration
#[derive(Debug)]
pub struct SecurityConfig {
    pub rate_limiting:    RateLimitingConfig,
    pub headers:          SecurityHeadersConfig,
    pub audit:            AuditConfig,
    pub query_validation: QueryValidationConfig,
    pub csrf:             CSRFConfig,
    pub cors:             CORSConfig,
}

#[derive(Debug)]
pub struct RateLimitingConfig {
    pub enabled:         bool,
    pub default_limit:   RateLimit,
    pub endpoint_limits: Vec<(String, RateLimit)>,
}

#[derive(Debug)]
pub struct SecurityHeadersConfig {
    pub enabled:     bool,
    pub environment: String, // "development" | "production"
}

#[derive(Debug)]
pub struct AuditConfig {
    pub enabled:      bool,
    pub database_url: Option<String>,
}

#[derive(Debug)]
pub struct QueryValidationConfig {
    pub enabled: bool,
    pub limits:  QueryLimits,
}

#[derive(Debug)]
pub struct CSRFConfig {
    pub enabled: bool,
    pub secret:  Option<String>,
}

impl Default for SecurityConfig {
    fn default() -> Self {
        Self {
            rate_limiting:    RateLimitingConfig {
                enabled:         true,
                default_limit:   RateLimit {
                    requests:    100,
                    window_secs: 60,
                    burst:       Some(20),
                    strategy:    RateLimitStrategy::TokenBucket,
                },
                endpoint_limits: vec![(
                    "/graphql".to_string(),
                    RateLimit {
                        requests:    1000,
                        window_secs: 60,
                        burst:       Some(100),
                        strategy:    RateLimitStrategy::TokenBucket,
                    },
                )],
            },
            headers:          SecurityHeadersConfig {
                enabled:     true,
                environment: "development".to_string(),
            },
            audit:            AuditConfig {
                enabled:      true,
                database_url: None,
            },
            query_validation: QueryValidationConfig {
                enabled: true,
                limits:  QueryLimits::default(),
            },
            csrf:             CSRFConfig {
                enabled: false, // Disabled by default for API-first apps
                secret:  None,
            },
            cors:             CORSConfig::default(),
        }
    }
}

impl SecurityConfig {
    /// Load configuration from environment variables
    pub fn from_env() -> Result<Self, Box<dyn std::error::Error>> {
        let mut config = Self::default();

        // Rate limiting
        if let Ok(enabled) = env::var("SECURITY_RATE_LIMITING_ENABLED") {
            config.rate_limiting.enabled = enabled.parse().unwrap_or(true);
        }

        if let Ok(requests) = env::var("SECURITY_RATE_LIMIT_REQUESTS") {
            config.rate_limiting.default_limit.requests = requests.parse().unwrap_or(100);
        }

        if let Ok(window) = env::var("SECURITY_RATE_LIMIT_WINDOW") {
            config.rate_limiting.default_limit.window_secs = window.parse().unwrap_or(60);
        }

        // Security headers
        if let Ok(env) = env::var("SECURITY_HEADERS_ENV") {
            config.headers.environment = env;
        }

        // Audit logging
        if let Ok(enabled) = env::var("SECURITY_AUDIT_ENABLED") {
            config.audit.enabled = enabled.parse().unwrap_or(true);
        }

        // Query validation
        if let Ok(max_depth) = env::var("SECURITY_QUERY_MAX_DEPTH") {
            config.query_validation.limits.max_depth = max_depth.parse().unwrap_or(10);
        }

        if let Ok(max_complexity) = env::var("SECURITY_QUERY_MAX_COMPLEXITY") {
            config.query_validation.limits.max_complexity = max_complexity.parse().unwrap_or(1000);
        }

        // CSRF
        if let Ok(enabled) = env::var("SECURITY_CSRF_ENABLED") {
            config.csrf.enabled = enabled.parse().unwrap_or(false);
        }

        if let Ok(secret) = env::var("SECURITY_CSRF_SECRET") {
            config.csrf.secret = Some(secret);
        }

        // CORS
        if let Ok(origins) = env::var("SECURITY_CORS_ORIGINS") {
            config.cors.allowed_origins =
                origins.split(',').map(|s| s.trim().to_string()).collect();
        }

        config.validate()?;
        Ok(config)
    }

    /// Create production configuration
    pub fn production() -> Self {
        let mut config = Self::default();

        config.rate_limiting.default_limit.requests = 50; // Stricter limits
        config.headers.environment = "production".to_string();
        config.query_validation.limits = QueryLimits::production();
        config.cors = CORSConfig::production();

        config
    }

    /// Create strict configuration for high-security environments
    pub fn strict() -> Self {
        let mut config = Self::production();

        config.rate_limiting.default_limit.requests = 10;
        config.query_validation.limits = QueryLimits::strict();
        config.csrf.enabled = true;

        config
    }

    /// Validate configuration
    pub fn validate(&self) -> Result<(), Box<dyn std::error::Error>> {
        // Validate CSRF secret if enabled
        if self.csrf.enabled && self.csrf.secret.is_none() {
            return Err("CSRF secret must be provided when CSRF is enabled".into());
        }

        // Validate audit database URL if enabled
        if self.audit.enabled && self.audit.database_url.is_none() {
            return Err("Database URL must be provided when audit logging is enabled".into());
        }

        // Validate rate limits
        if self.rate_limiting.default_limit.requests == 0 {
            return Err("Rate limit requests must be greater than 0".into());
        }

        Ok(())
    }
}

/// Security components builder
pub struct SecurityComponents {
    pub rate_limiter:     Option<RateLimiter>,
    pub security_headers: SecurityHeaders,
    pub audit_logger:     Option<AuditLogger>,
    pub query_validator:  QueryValidator,
    pub csrf_manager:     Option<CSRFManager>,
    pub cors_handler:     CORSHandler,
}

impl SecurityComponents {
    /// Build security components from configuration
    pub async fn from_config(
        config: &SecurityConfig,
        pool: Option<deadpool_postgres::Pool>,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        // Rate limiter
        let rate_limiter = if config.rate_limiting.enabled {
            let mut limiter = RateLimiter::new();

            // Add default limit
            limiter.add_rule("*".to_string(), config.rate_limiting.default_limit.clone());

            // Add endpoint-specific limits
            for (endpoint, limit) in &config.rate_limiting.endpoint_limits {
                limiter.add_rule(endpoint.clone(), limit.clone());
            }

            Some(limiter)
        } else {
            None
        };

        // Security headers
        let security_headers = if config.headers.environment == "production" {
            SecurityHeaders::production()
        } else if config.headers.environment == "development" {
            SecurityHeaders::development()
        } else {
            SecurityHeaders::default()
        };

        // Audit logger
        let audit_logger = if config.audit.enabled {
            pool.map(AuditLogger::new)
        } else {
            None
        };

        // Query validator
        let query_validator = if config.query_validation.enabled {
            QueryValidator::new(config.query_validation.limits.clone())
        } else {
            QueryValidator::new(QueryLimits::default())
        };

        // CSRF manager
        let csrf_manager = if config.csrf.enabled {
            config.csrf.secret.as_ref().map(|secret| CSRFManager::new(secret.clone()))
        } else {
            None
        };

        // CORS handler
        let cors_handler = CORSHandler::new(config.cors.clone());

        Ok(Self {
            rate_limiter,
            security_headers,
            audit_logger,
            query_validator,
            csrf_manager,
            cors_handler,
        })
    }

    /// Get security statistics
    pub async fn stats(&self) -> SecurityStats {
        let rate_limit_stats = if let Some(ref limiter) = self.rate_limiter {
            limiter.stats().await
        } else {
            super::rate_limit::RateLimitStats {
                rules_count:    0,
                buckets_count:  0,
                windows_count:  0,
                requests_count: 0,
            }
        };

        let audit_stats = if let (Some(ref _logger), Some(_pool)) =
            (&self.audit_logger, None::<&deadpool_postgres::Pool>)
        {
            // Note: We can't get audit stats without a pool reference
            // This would need to be passed in or stored
            super::audit::AuditStats {
                total_events:  0,
                recent_events: 0,
            }
        } else {
            super::audit::AuditStats {
                total_events:  0,
                recent_events: 0,
            }
        };

        SecurityStats {
            rate_limiting: rate_limit_stats,
            audit:         audit_stats,
        }
    }
}

#[derive(Debug)]
pub struct SecurityStats {
    pub rate_limiting: super::rate_limit::RateLimitStats,
    pub audit:         super::audit::AuditStats,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_security_config_default() {
        let config = SecurityConfig::default();
        assert!(config.rate_limiting.enabled);
        assert!(config.headers.enabled);
        assert!(config.audit.enabled);
        assert!(config.query_validation.enabled);
        assert!(!config.csrf.enabled);
    }

    #[test]
    fn test_security_config_production() {
        let config = SecurityConfig::production();
        assert_eq!(config.headers.environment, "production");
        assert_eq!(config.rate_limiting.default_limit.requests, 50);
        assert_eq!(config.query_validation.limits.max_depth, 7);
    }

    #[test]
    fn test_security_config_strict() {
        let config = SecurityConfig::strict();
        assert!(config.csrf.enabled);
        assert_eq!(config.rate_limiting.default_limit.requests, 10);
        assert_eq!(config.query_validation.limits.max_depth, 5);
    }

    #[tokio::test]
    async fn test_security_components_from_config() {
        let config = SecurityConfig::default();
        let components = SecurityComponents::from_config(&config, None).await.unwrap();

        assert!(components.rate_limiter.is_some());
        assert!(components.audit_logger.is_none()); // No pool provided
        assert!(components.csrf_manager.is_none()); // Disabled by default
    }
}

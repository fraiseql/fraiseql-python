//! CORS (Cross-Origin Resource Sharing) policy enforcement.

use std::collections::HashSet;

use super::errors::{Result, SecurityError};

/// CORS configuration
#[derive(Debug, Clone)]
pub struct CORSConfig {
    /// Allowed origins (exact matches or patterns)
    pub allowed_origins:   HashSet<String>,
    /// Allowed HTTP methods
    pub allowed_methods:   HashSet<String>,
    /// Allowed headers
    pub allowed_headers:   HashSet<String>,
    /// Headers exposed to browser
    pub exposed_headers:   HashSet<String>,
    /// Whether credentials are allowed
    pub allow_credentials: bool,
    /// Max age for preflight cache (seconds)
    pub max_age:           u32,
}

impl Default for CORSConfig {
    fn default() -> Self {
        let mut allowed_origins = HashSet::new();
        allowed_origins.insert("http://localhost:3000".to_string());
        allowed_origins.insert("http://localhost:3001".to_string());

        let mut allowed_methods = HashSet::new();
        allowed_methods.insert("GET".to_string());
        allowed_methods.insert("POST".to_string());
        allowed_methods.insert("OPTIONS".to_string());

        let mut allowed_headers = HashSet::new();
        allowed_headers.insert("Content-Type".to_string());
        allowed_headers.insert("Authorization".to_string());
        allowed_headers.insert("X-Requested-With".to_string());

        let mut exposed_headers = HashSet::new();
        exposed_headers.insert("X-Total-Count".to_string());
        exposed_headers.insert("X-Rate-Limit-Remaining".to_string());

        Self {
            allowed_origins,
            allowed_methods,
            allowed_headers,
            exposed_headers,
            allow_credentials: false,
            max_age: 86400, // 24 hours
        }
    }
}

impl CORSConfig {
    /// Create production CORS config
    pub fn production() -> Self {
        let mut config = Self::default();
        config.allowed_origins.clear(); // Must be explicitly configured
        config.allow_credentials = true;
        config
    }

    /// Add allowed origin
    pub fn add_origin(&mut self, origin: String) {
        self.allowed_origins.insert(origin);
    }

    /// Add allowed method
    pub fn add_method(&mut self, method: String) {
        self.allowed_methods.insert(method);
    }

    /// Add allowed header
    pub fn add_header(&mut self, header: String) {
        self.allowed_headers.insert(header);
    }

    /// Check if origin is allowed
    pub fn is_origin_allowed(&self, origin: &str) -> bool {
        self.allowed_origins.contains(origin) || self.allowed_origins.contains("*")
    }

    /// Check if method is allowed
    pub fn is_method_allowed(&self, method: &str) -> bool {
        self.allowed_methods.contains(method) || self.allowed_methods.contains("*")
    }

    /// Check if header is allowed
    pub fn is_header_allowed(&self, header: &str) -> bool {
        self.allowed_headers.contains(header) || self.allowed_headers.contains("*")
    }
}

/// CORS policy enforcer
pub struct CORSHandler {
    config: CORSConfig,
}

impl CORSHandler {
    pub fn new(config: CORSConfig) -> Self {
        Self { config }
    }

    /// Handle CORS preflight request
    pub fn handle_preflight(
        &self,
        origin: Option<&str>,
        method: Option<&str>,
        headers: Option<&str>,
    ) -> Result<Vec<(String, String)>> {
        let mut response_headers = Vec::new();

        // Validate origin
        if let Some(origin) = origin {
            if !self.config.is_origin_allowed(origin) {
                return Err(SecurityError::OriginNotAllowed(origin.to_string()));
            }
            response_headers.push(("Access-Control-Allow-Origin".to_string(), origin.to_string()));
        }

        // Validate method
        if let Some(method) = method {
            if !self.config.is_method_allowed(method) {
                return Err(SecurityError::MethodNotAllowed(method.to_string()));
            }
            response_headers.push((
                "Access-Control-Allow-Methods".to_string(),
                self.config.allowed_methods.iter().cloned().collect::<Vec<_>>().join(", "),
            ));
        }

        // Validate headers
        if let Some(request_headers) = headers {
            let requested_headers: Vec<&str> =
                request_headers.split(',').map(|s| s.trim()).collect();
            for header in &requested_headers {
                if !self.config.is_header_allowed(header) {
                    return Err(SecurityError::HeaderNotAllowed((*header).to_string()));
                }
            }
            response_headers
                .push(("Access-Control-Allow-Headers".to_string(), request_headers.to_string()));
        }

        // Add other CORS headers
        if self.config.allow_credentials {
            response_headers
                .push(("Access-Control-Allow-Credentials".to_string(), "true".to_string()));
        }

        response_headers
            .push(("Access-Control-Max-Age".to_string(), self.config.max_age.to_string()));

        Ok(response_headers)
    }

    /// Add CORS headers to response
    pub fn add_cors_headers(
        &self,
        origin: Option<&str>,
        mut headers: Vec<(String, String)>,
    ) -> Vec<(String, String)> {
        if let Some(origin) = origin {
            if self.config.is_origin_allowed(origin) {
                headers.push(("Access-Control-Allow-Origin".to_string(), origin.to_string()));

                if self.config.allow_credentials {
                    headers
                        .push(("Access-Control-Allow-Credentials".to_string(), "true".to_string()));
                }

                if !self.config.exposed_headers.is_empty() {
                    headers.push((
                        "Access-Control-Expose-Headers".to_string(),
                        self.config.exposed_headers.iter().cloned().collect::<Vec<_>>().join(", "),
                    ));
                }
            }
        }

        headers
    }

    /// Check if request is a CORS preflight
    pub fn is_preflight_request(method: &str, headers: &http::HeaderMap) -> bool {
        method == "OPTIONS"
            && headers.contains_key("origin")
            && (headers.contains_key("access-control-request-method")
                || headers.contains_key("access-control-request-headers"))
    }

    /// Get the configuration
    pub fn config(&self) -> &CORSConfig {
        &self.config
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cors_config_default() {
        let config = CORSConfig::default();
        assert!(config.is_origin_allowed("http://localhost:3000"));
        assert!(config.is_method_allowed("GET"));
        assert!(config.is_header_allowed("Content-Type"));
        assert!(!config.allow_credentials);
    }

    #[test]
    fn test_cors_config_production() {
        let config = CORSConfig::production();
        assert!(!config.is_origin_allowed("http://localhost:3000")); // Cleared in production
        assert!(config.allow_credentials);
    }

    #[test]
    fn test_cors_handler_preflight() {
        let handler = CORSHandler::new(CORSConfig::default());

        let headers = handler
            .handle_preflight(
                Some("http://localhost:3000"),
                Some("POST"),
                Some("Content-Type, Authorization"),
            )
            .unwrap();

        assert!(
            headers
                .iter()
                .any(|(k, v)| k == "Access-Control-Allow-Origin" && v == "http://localhost:3000")
        );
        assert!(headers.iter().any(|(k, _)| k == "Access-Control-Allow-Methods"));
        assert!(headers.iter().any(|(k, _)| k == "Access-Control-Allow-Headers"));
    }

    #[test]
    fn test_cors_handler_preflight_invalid_origin() {
        let handler = CORSHandler::new(CORSConfig::default());

        let result = handler.handle_preflight(Some("http://evil.com"), Some("POST"), None);

        assert!(matches!(result, Err(SecurityError::OriginNotAllowed(_))));
    }

    #[test]
    fn test_cors_add_headers() {
        let handler = CORSHandler::new(CORSConfig::default());
        let mut headers = vec![("Content-Type".to_string(), "application/json".to_string())];

        let new_headers = handler.add_cors_headers(Some("http://localhost:3000"), headers);

        assert!(
            new_headers
                .iter()
                .any(|(k, v)| k == "Access-Control-Allow-Origin" && v == "http://localhost:3000")
        );
    }
}

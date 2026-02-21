//! CSRF token validation.

use rand::Rng;
use sha2::{Digest, Sha256};

use super::errors::{Result, SecurityError};

/// CSRF token manager
pub struct CSRFManager {
    secret: String,
}

impl CSRFManager {
    pub fn new(secret: String) -> Self {
        Self { secret }
    }

    /// Generate CSRF token for session
    pub fn generate_token(&self, session_id: &str) -> String {
        let nonce: [u8; 32] = rand::thread_rng().gen();
        let payload = format!("{}:{}", session_id, hex::encode(nonce));

        let mut hasher = Sha256::new();
        hasher.update(payload.as_bytes());
        hasher.update(self.secret.as_bytes());

        format!("{}:{}", payload, hex::encode(hasher.finalize()))
    }

    /// Validate CSRF token
    pub fn validate_token(&self, session_id: &str, token: &str) -> Result<()> {
        let parts: Vec<&str> = token.split(':').collect();
        if parts.len() != 3 {
            return Err(SecurityError::InvalidCSRFToken("Invalid token format".to_string()));
        }

        let provided_session = parts[0];
        let nonce = parts[1];
        let provided_hash = parts[2];

        // Verify session matches
        if provided_session != session_id {
            return Err(SecurityError::CSRFSessionMismatch);
        }

        // Verify hash
        let payload = format!("{}:{}", provided_session, nonce);
        let mut hasher = Sha256::new();
        hasher.update(payload.as_bytes());
        hasher.update(self.secret.as_bytes());
        let expected_hash = hex::encode(hasher.finalize());

        if expected_hash != provided_hash {
            return Err(SecurityError::InvalidCSRFToken("Hash verification failed".to_string()));
        }

        Ok(())
    }

    /// Check if token format is valid (without full validation)
    pub fn is_valid_format(&self, token: &str) -> bool {
        let parts: Vec<&str> = token.split(':').collect();
        parts.len() == 3 && !parts.iter().any(|part| part.is_empty())
    }

    /// Get token expiry time (CSRF tokens don't expire but this could be extended)
    pub fn token_lifetime_seconds(&self) -> u64 {
        // CSRF tokens are typically valid for the session
        // This could be made configurable for per-token expiry
        3600 * 24 // 24 hours
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_csrf_token_generation_and_validation() {
        let manager = CSRFManager::new("test-secret".to_string());
        let session_id = "session123";

        let token = manager.generate_token(session_id);
        assert!(manager.is_valid_format(&token));

        // Should validate successfully
        assert!(manager.validate_token(session_id, &token).is_ok());
    }

    #[test]
    fn test_csrf_token_wrong_session() {
        let manager = CSRFManager::new("test-secret".to_string());
        let token = manager.generate_token("session123");

        // Should fail with wrong session
        assert!(matches!(
            manager.validate_token("wrong-session", &token),
            Err(SecurityError::CSRFSessionMismatch)
        ));
    }

    #[test]
    fn test_csrf_token_invalid_format() {
        let manager = CSRFManager::new("test-secret".to_string());

        assert!(!manager.is_valid_format(""));
        assert!(!manager.is_valid_format("invalid"));
        assert!(!manager.is_valid_format("session:nounce"));
        assert!(!manager.is_valid_format("session::hash"));
        assert!(!manager.is_valid_format(":nonce:hash"));
    }

    #[test]
    fn test_csrf_token_tampered() {
        let manager = CSRFManager::new("test-secret".to_string());
        let token = manager.generate_token("session123");

        // Tamper with the token
        let tampered_token = token.replace("session123", "evil-session");

        // Should fail validation
        assert!(matches!(
            manager.validate_token("session123", &tampered_token),
            Err(SecurityError::InvalidCSRFToken(_))
        ));
    }
}

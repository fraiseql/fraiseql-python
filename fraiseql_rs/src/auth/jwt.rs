//! JWT token validation with JWKS caching.

use std::{
    collections::HashMap,
    num::NonZeroUsize,
    sync::{Arc, Mutex},
    time::{Duration, SystemTime},
};

use jsonwebtoken::{
    Algorithm, DecodingKey, Validation, decode, decode_header,
    jwk::{Jwk, JwkSet},
};
use lru::LruCache;
use serde::{Deserialize, Serialize};

use crate::auth::errors::AuthError;

type Result<T> = std::result::Result<T, AuthError>;

/// JWT claims structure.
#[derive(Debug, Serialize, Deserialize)]
pub struct Claims {
    pub sub:    String,      // Subject (user ID)
    pub iss:    String,      // Issuer
    pub aud:    Vec<String>, // Audience
    pub exp:    u64,         // Expiration time
    pub iat:    u64,         // Issued at
    #[serde(flatten)]
    pub custom: HashMap<String, serde_json::Value>, // Custom claims
}

/// JWT validator with JWKS caching.
#[derive(Debug)]
pub struct JWTValidator {
    issuer:      String,
    audience:    Vec<String>,
    jwks_url:    String,
    jwks_cache:  JWKSCache,
    http_client: reqwest::Client,
}

impl JWTValidator {
    /// Create a new JWT validator.
    pub fn new(issuer: String, audience: Vec<String>, jwks_url: String) -> Result<Self> {
        // Validate HTTPS for JWKS URL
        if !jwks_url.starts_with("https://") {
            return Err(AuthError::InvalidToken(format!("JWKS URL must use HTTPS: {}", jwks_url)));
        }

        // Create HTTP client with timeout
        let http_client = reqwest::Client::builder()
            .timeout(Duration::from_secs(5))
            .build()
            .map_err(|e| AuthError::HttpError(e.to_string()))?;

        Ok(Self {
            issuer,
            audience,
            jwks_url,
            jwks_cache: JWKSCache::new(),
            http_client,
        })
    }

    /// Validate a JWT token.
    pub async fn validate(&self, token: &str) -> Result<Claims> {
        // Decode header to get key ID
        let header = decode_header(token)
            .map_err(|e| AuthError::InvalidToken(format!("Invalid header: {}", e)))?;

        let kid = header
            .kid
            .ok_or_else(|| AuthError::InvalidToken("Missing kid in token header".to_string()))?;

        // Get JWK from cache or fetch
        let jwk = self.jwks_cache.get_jwk(&kid, &self.jwks_url, &self.http_client).await?;

        // Use built-in JWK to DecodingKey conversion
        let decoding_key = DecodingKey::from_jwk(&jwk)
            .map_err(|e| AuthError::InvalidToken(format!("Invalid JWK: {}", e)))?;

        // Set up validation
        let mut validation = Validation::new(Algorithm::RS256);
        validation.set_issuer(&[&self.issuer]);
        validation.set_audience(&self.audience);

        // Decode and validate token
        let token_data = decode::<Claims>(token, &decoding_key, &validation)?;

        Ok(token_data.claims)
    }
}

/// JWKS cache with LRU eviction and TTL.
#[derive(Debug)]
struct JWKSCache {
    cache: Arc<Mutex<LruCache<String, (Jwk, SystemTime)>>>,
    ttl:   Duration,
}

impl JWKSCache {
    fn new() -> Self {
        Self {
            cache: Arc::new(Mutex::new(LruCache::new(NonZeroUsize::new(100).unwrap()))),
            ttl:   Duration::from_secs(3600), // 1 hour
        }
    }

    /// Get a JWK by key ID, from cache or by fetching.
    async fn get_jwk(&self, kid: &str, jwks_url: &str, client: &reqwest::Client) -> Result<Jwk> {
        // Check cache with TTL validation
        {
            let mut cache = self.cache.lock().unwrap();
            if let Some((jwk, cached_at)) = cache.get(kid) {
                let elapsed = SystemTime::now()
                    .duration_since(*cached_at)
                    .unwrap_or(Duration::from_secs(u64::MAX));

                if elapsed < self.ttl {
                    return Ok(jwk.clone());
                }

                // Expired - remove from cache
                cache.pop(kid);
            }
        }

        // Fetch from JWKS endpoint
        let jwks = self.fetch_jwks(jwks_url, client).await?;

        // Find the specific key
        let jwk = jwks
            .keys
            .iter()
            .find(|k| k.common.key_id.as_ref() == Some(&kid.to_string()))
            .ok_or_else(|| AuthError::KeyNotFound(kid.to_string()))?
            .clone();

        // Store in cache
        {
            let mut cache = self.cache.lock().unwrap();
            cache.put(kid.to_string(), (jwk.clone(), SystemTime::now()));
        }

        Ok(jwk)
    }

    /// Fetch JWKS from URL.
    async fn fetch_jwks(&self, url: &str, client: &reqwest::Client) -> Result<JwkSet> {
        let response = client.get(url).send().await?;

        if !response.status().is_success() {
            return Err(AuthError::JwksFetchFailed(format!(
                "HTTP {}: {}",
                response.status(),
                response.text().await.unwrap_or_default()
            )));
        }

        let jwks: JwkSet = response.json().await?;

        Ok(jwks)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_https_validation() {
        let result = JWTValidator::new(
            "https://example.com/".to_string(),
            vec!["api".to_string()],
            "http://example.com/.well-known/jwks.json".to_string(),
        );

        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("HTTPS"));
    }
}

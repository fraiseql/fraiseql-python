//! Authentication provider trait and implementations.

use async_trait::async_trait;

use crate::{
    auth::{errors::AuthError, jwt::JWTValidator},
    pipeline::unified::UserContext,
};

type Result<T> = std::result::Result<T, AuthError>;

/// Authentication provider trait.
#[async_trait]
pub trait AuthProvider: Send + Sync {
    /// Validate a token and return user context.
    async fn validate_token(&self, token: &str) -> Result<UserContext>;
}

/// Auth0 authentication provider.
pub struct Auth0Provider {
    validator: JWTValidator,
}

impl Auth0Provider {
    /// Create a new Auth0 provider.
    pub fn new(domain: &str, audience: Vec<String>) -> Result<Self> {
        let issuer = format!("https://{}/", domain);
        let jwks_url = format!("https://{}/.well-known/jwks.json", domain);

        Ok(Self {
            validator: JWTValidator::new(issuer, audience, jwks_url)?,
        })
    }
}

#[async_trait]
impl AuthProvider for Auth0Provider {
    async fn validate_token(&self, token: &str) -> Result<UserContext> {
        let claims = self.validator.validate(token).await?;

        // Extract roles from Auth0 custom claims
        let roles = claims
            .custom
            .get("https://fraiseql.com/roles")
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_str().map(String::from)).collect())
            .unwrap_or_default();

        // Extract permissions from Auth0 custom claims
        let permissions = claims
            .custom
            .get("https://fraiseql.com/permissions")
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_str().map(String::from)).collect())
            .unwrap_or_default();

        Ok(UserContext {
            user_id: Some(claims.sub),
            permissions,
            roles,
            exp: claims.exp,
        })
    }
}

/// Custom JWT authentication provider.
pub struct CustomJWTProvider {
    validator:         JWTValidator,
    roles_claim:       String,
    permissions_claim: String,
}

impl CustomJWTProvider {
    /// Create a new custom JWT provider.
    pub fn new(
        issuer: String,
        audience: Vec<String>,
        jwks_url: String,
        roles_claim: String,
        permissions_claim: String,
    ) -> Result<Self> {
        Ok(Self {
            validator: JWTValidator::new(issuer, audience, jwks_url)?,
            roles_claim,
            permissions_claim,
        })
    }
}

#[async_trait]
impl AuthProvider for CustomJWTProvider {
    async fn validate_token(&self, token: &str) -> Result<UserContext> {
        let claims = self.validator.validate(token).await?;

        // Extract roles from custom claim
        let roles = claims
            .custom
            .get(&self.roles_claim)
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_str().map(String::from)).collect())
            .unwrap_or_default();

        // Extract permissions from custom claim
        let permissions = claims
            .custom
            .get(&self.permissions_claim)
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_str().map(String::from)).collect())
            .unwrap_or_default();

        Ok(UserContext {
            user_id: Some(claims.sub),
            permissions,
            roles,
            exp: claims.exp,
        })
    }
}

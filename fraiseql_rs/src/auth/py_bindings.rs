//! PyO3 bindings for authentication module (Phase 10).

use std::sync::Arc;

use pyo3::prelude::*;

use crate::{
    auth::provider::{Auth0Provider, AuthProvider, CustomJWTProvider},
    pipeline::unified::UserContext,
};

/// Python wrapper for UserContext (exposed from Rust to Python)
#[pyclass]
#[derive(Clone)]
pub struct PyUserContext {
    #[pyo3(get)]
    pub user_id:     Option<String>,
    #[pyo3(get)]
    pub roles:       Vec<String>,
    #[pyo3(get)]
    pub permissions: Vec<String>,
    #[pyo3(get)]
    pub exp:         u64,
}

impl From<UserContext> for PyUserContext {
    fn from(ctx: UserContext) -> Self {
        Self {
            user_id:     ctx.user_id,
            roles:       ctx.roles,
            permissions: ctx.permissions,
            exp:         ctx.exp,
        }
    }
}

/// Python wrapper for authentication providers
///
/// Provides token validation with Auth0 and custom JWT support.
#[pyclass]
#[allow(dead_code)]
pub struct PyAuthProvider {
    // The actual auth provider (Auth0 or CustomJWT)
    provider:         Arc<dyn AuthProvider>,
    // Store for debugging/introspection
    provider_type:    String,
    domain_or_issuer: String, // Stored for potential debug features
    audience:         Vec<String>,
}

#[pymethods]
impl PyAuthProvider {
    /// Create an Auth0 provider.
    ///
    /// Args:
    ///     domain: Auth0 domain (e.g., "example.auth0.com")
    ///     audience: List of allowed audiences
    ///
    /// Returns:
    ///     PyAuthProvider instance
    ///
    /// Raises:
    ///     ValueError: If domain or audience is invalid
    #[staticmethod]
    pub fn auth0(domain: String, audience: Vec<String>) -> PyResult<Self> {
        let provider = Auth0Provider::new(&domain, audience.clone()).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                "Failed to create Auth0 provider: {}",
                e
            ))
        })?;

        Ok(Self {
            provider: Arc::new(provider),
            provider_type: "auth0".to_string(),
            domain_or_issuer: domain,
            audience,
        })
    }

    /// Create a custom JWT provider.
    ///
    /// Args:
    ///     issuer: JWT issuer URL (must be HTTPS)
    ///     audience: List of allowed audiences
    ///     jwks_url: URL to fetch JWK set (must be HTTPS)
    ///     roles_claim: Custom claim name for roles (default: "roles")
    ///     permissions_claim: Custom claim name for permissions (default: "permissions")
    ///
    /// Returns:
    ///     PyAuthProvider instance
    ///
    /// Raises:
    ///     ValueError: If URLs are invalid or other parameters are malformed
    #[staticmethod]
    #[pyo3(signature = (issuer, audience, jwks_url, roles_claim="roles", permissions_claim="permissions"))]
    pub fn jwt(
        issuer: String,
        audience: Vec<String>,
        jwks_url: String,
        roles_claim: &str,
        permissions_claim: &str,
    ) -> PyResult<Self> {
        let provider = CustomJWTProvider::new(
            issuer.clone(),
            audience.clone(),
            jwks_url,
            roles_claim.to_string(),
            permissions_claim.to_string(),
        )
        .map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                "Failed to create custom JWT provider: {}",
                e
            ))
        })?;

        Ok(Self {
            provider: Arc::new(provider),
            provider_type: "jwt".to_string(),
            domain_or_issuer: issuer,
            audience,
        })
    }

    /// Validate a JWT token and return user context.
    ///
    /// This is an async method - call it with await from Python.
    ///
    /// Args:
    ///     token: JWT token string to validate
    ///
    /// Returns:
    ///     PyUserContext with user_id, roles, permissions, and exp
    ///
    /// Raises:
    ///     RuntimeError: If token validation fails (expired, invalid signature, etc.)
    ///
    /// Example:
    ///     ```python
    ///     import asyncio
    ///     from fraiseql._fraiseql_rs import PyAuthProvider
    ///
    ///     async def main():
    ///         auth = PyAuthProvider.auth0("example.auth0.com", ["https://api.example.com"])
    ///         try:
    ///             user = await auth.validate_token(token)
    ///             print(f"User {user.user_id} with roles {user.roles}")
    ///         except RuntimeError as e:
    ///             print(f"Token validation failed: {e}")
    ///
    ///     asyncio.run(main())
    ///     ```
    /// Validate a JWT token (blocks until validation completes).
    ///
    /// For best compatibility with Python async code, call this from
    /// an executor like asyncio.to_thread.run_in_executor() or
    /// concurrent.futures.ThreadPoolExecutor.
    ///
    /// Example:
    ///     ```python
    ///     import asyncio
    ///     auth = PyAuthProvider.auth0("example.auth0.com", ["https://api.example.com"])
    ///
    ///     async def validate(token):
    ///         loop = asyncio.get_event_loop()
    ///         user = await loop.run_in_executor(None, auth.validate_token_blocking, token)
    ///         return user
    ///     ```
    pub fn validate_token_blocking(&self, token: String) -> PyResult<PyUserContext> {
        let provider = self.provider.clone();

        // Run the async validation on the current tokio runtime
        // Using block_on, which requires a tokio runtime to be available
        let rt = tokio::runtime::Handle::try_current()
            .map_err(|_| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                "No tokio runtime available. Call from async context or use asyncio.to_thread.run_in_executor()"
            ))?;

        let context = rt.block_on(provider.validate_token(&token)).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                "Token validation failed: {}",
                e
            ))
        })?;

        Ok(PyUserContext::from(context))
    }

    /// Get provider type (for debugging)
    pub fn provider_type(&self) -> String {
        self.provider_type.clone()
    }

    /// Get configured audience list
    pub fn audience(&self) -> Vec<String> {
        self.audience.clone()
    }
}

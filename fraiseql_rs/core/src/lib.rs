//! `FraiseQL` Core - Pure Rust GraphQL Engine
//!
//! This crate contains the core GraphQL engine with ZERO FFI dependencies.
//! It can be used directly from Rust or wrapped by language-specific bindings.
//!
//! # Architecture
//!
//! ```text
//! ┌─────────────────────────────────────────────────────────┐
//! │                    fraiseql_core                         │
//! ├─────────────────────────────────────────────────────────┤
//! │  config   │  db     │  graphql  │  http    │  security  │
//! │  ────────────────────────────────────────────────────── │
//! │                     pipeline                             │
//! │  ────────────────────────────────────────────────────── │
//! │           query        │       cache                     │
//! └─────────────────────────────────────────────────────────┘
//! ```
//!
//! # Usage
//!
//! ```ignore
//! use fraiseql_core::{FraiseQLConfig, GraphQLPipeline};
//!
//! // Create configuration
//! let config = FraiseQLConfig::builder()
//!     .database_url("postgresql://localhost/mydb")
//!     .build()?;
//!
//! // Create pipeline
//! let pipeline = GraphQLPipeline::from_config(config).await?;
//!
//! // Execute query
//! let result = pipeline.execute("{ users { id name } }").await?;
//! ```

#![warn(missing_docs)]
#![warn(clippy::all)]
#![warn(clippy::pedantic)]
#![allow(clippy::module_name_repetitions)]

// ============================================================================
// Module declarations
// ============================================================================

/// Error types for the core library.
pub mod error;

/// Configuration management.
pub mod config;

/// Core utility modules (Phase 5.1)
pub mod core;

/// Query caching layer (Phase 5.2)
pub mod cache;

/// Automatic Persisted Queries infrastructure (Phase 5.4)
pub mod apq;

/// Database connectivity.
pub mod db;

/// GraphQL parsing and validation.
pub mod graphql;

/// HTTP server implementation.
pub mod http;

/// Unified execution pipeline.
pub mod pipeline;

/// SQL query building.
pub mod query;

/// Security and authorization.
pub mod security;

/// Input validation.
pub mod validation;

// ============================================================================
// Re-exports for convenient access
// ============================================================================

pub use config::FraiseQLConfig;
pub use error::{FraiseQLError, Result};

// These will be enabled as modules are migrated:
// pub use db::DatabasePool;
// pub use graphql::ParsedQuery;
// pub use http::Server;
// pub use pipeline::GraphQLPipeline;
// pub use security::RbacEngine;

/// Library version.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

// ============================================================================
// Unit tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_version() {
        // VERSION is set at compile time from Cargo.toml
        assert!(!VERSION.contains("UNSET"));
    }

    #[test]
    fn test_config_creation() {
        let config = FraiseQLConfig::builder()
            .database_url("postgresql://localhost/test")
            .port(9000)
            .build()
            .unwrap();

        assert_eq!(config.port, 9000);
    }
}

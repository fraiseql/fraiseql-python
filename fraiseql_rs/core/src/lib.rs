//! `FraiseQL` Core - Pure Rust GraphQL Engine
//!
//! This crate contains the core GraphQL engine with ZERO FFI dependencies.
//! It can be used directly from Rust or wrapped by language-specific bindings.

#![warn(missing_docs)]
#![warn(clippy::all)]
#![warn(clippy::pedantic)]

/// Error types for the core library.
pub mod error;

// These will be populated as we migrate modules:
// pub mod cache;
// pub mod config;
// pub mod db;
// pub mod graphql;
// pub mod http;
// pub mod pipeline;
// pub mod query;
// pub mod security;

/// Library version.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

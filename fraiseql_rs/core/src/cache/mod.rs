//! Query caching module with memory-safe bounds (Phase 5.2).
//!
//! Contains cache infrastructure for GraphQL queries with:
//! - Query result caching with entity tracking
//! - Cache coherency validation
//! - Cache executor for integrated query execution
//!
//! # Phase 5.2 Status
//!
//! Modules migrated:
//! - coherency_validator: Cache coherency checks
//! - executor: Cache executor (deferred - has dependencies)
//! - query_result: Query result caching
//! - signature: Signature generation
//!
//! Modules deferred:
//! - cache_key.rs: Depends on crate::apq (Phase 5.4)
//!
//! # Cache Bounds
//!
//! All caches are configured with entry count limits to prevent unbounded memory growth:
//!
//! - **QueryPlanCache**: 5,000 entries max (~2.5 MB)
//! - **QueryResultCache**: 10,000 entries max (~10-100 MB with TTL)
//! - **PermissionCache**: 10,000 entries max (~10 MB with LRU)
//!
//! # Memory Safety
//!
//! - All caches use LRU eviction when entry count is exceeded
//! - TTL expiry as secondary safety mechanism
//! - Configured for servers with 512MB+ available for caching

pub mod coherency_validator;
pub mod query_result;
pub mod signature;
// executor.rs deferred - depends on crate::cascade
// cache_key.rs deferred - depends on crate::apq

// Re-export key types for convenience
pub use coherency_validator::{CoherencyValidationResult, CoherencyValidator};
pub use query_result::{CacheMetrics, QueryResultCache, QueryResultCacheConfig};
pub use signature::{generate_signature, is_cacheable};

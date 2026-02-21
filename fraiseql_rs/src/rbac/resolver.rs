//! Permission resolver with multi-layer caching and role hierarchy support.
//!
//! This module provides the core permission resolution logic. It orchestrates:
//! 1. Cache lookup (hit: <0.1ms)
//! 2. User role queries
//! 3. Role hierarchy traversal (includes inherited parent roles)
//! 4. Permission collection and matching
//! 5. Result caching with TTL
//!
//! ## Performance Path
//!
//! ```
//! has_permission(user_id, "document", "read", tenant_id)
//!   ├─ Check cache (Instant::now() < expires_at) → HIT: return in <0.1ms
//!   ├─ Query user_roles (includes expiration check)
//!   ├─ Traverse role hierarchy via recursive CTE
//!   ├─ Collect permissions from all roles
//!   ├─ Match resource:action pattern
//!   ├─ Cache result with 5m TTL
//!   └─ Return result in <1ms (cache miss)
//! ```
//!
//! ## Expiration Handling
//!
//! The resolver respects role assignment expiration:
//! - User-role assignments can have optional `expires_at` timestamp
//! - Query automatically filters expired assignments
//! - No cleanup job needed - expired roles naturally stop being used
//! - Separate from cache TTL: even non-expired cached entries will be stale
//!
//! ## Query Patterns
//!
//! All queries use parameterized statements (safe from SQL injection):
//! - User roles: filters by user_id and expiration
//! - Hierarchy: recursive CTE with tenant scoping
//! - Permissions: DISTINCT join on role_permissions + permissions
//!
//! ## Thread Safety
//!
//! The resolver is thread-safe and can be shared via `Arc<PermissionResolver>`:
//! - All methods take `&self` (immutable borrow)
//! - Database pool handles concurrent connections
//! - Cache uses Mutex for atomic updates

use std::sync::Arc;

use deadpool_postgres::Pool;
use uuid::Uuid;

use super::{
    cache::PermissionCache,
    errors::Result,
    hierarchy::RoleHierarchy,
    models::{Permission, UserRole},
};

/// Permission resolver with caching and hierarchy support.
///
/// The main API for permission checking in FraiseQL. Combines efficient
/// database queries with multi-layer caching for sub-millisecond performance.
///
/// # Example
///
/// ```ignore
/// use fraiseql_rs::rbac::PermissionResolver;
///
/// let resolver = PermissionResolver::new(pool, 10_000);
///
/// // Check if user can read documents
/// if resolver.has_permission(user_id, "document", "read", Some(tenant_id)).await? {
///     // Grant access
/// } else {
///     // Deny access
/// }
///
/// // On role changes, invalidate cache
/// resolver.invalidate_user(user_id);
/// ```
pub struct PermissionResolver {
    pool:      Pool,
    hierarchy: RoleHierarchy,
    cache:     Arc<PermissionCache>,
}

impl PermissionResolver {
    pub fn new(pool: Pool, cache_capacity: usize) -> Self {
        let hierarchy = RoleHierarchy::new(pool.clone());
        let cache = Arc::new(PermissionCache::new(cache_capacity));

        Self {
            pool,
            hierarchy,
            cache,
        }
    }

    /// Get all effective permissions for a user
    pub async fn get_user_permissions(
        &self,
        user_id: Uuid,
        tenant_id: Option<Uuid>,
    ) -> Result<Vec<Permission>> {
        // Try cache first
        if let Some(cached) = self.cache.get(user_id, tenant_id) {
            return Ok(cached);
        }

        // Cache miss - compute from database
        let permissions = self.compute_permissions(user_id, tenant_id).await?;

        // Cache result
        self.cache.set(user_id, tenant_id, permissions.clone());

        Ok(permissions)
    }

    /// Check if user has specific permission
    pub async fn has_permission(
        &self,
        user_id: Uuid,
        resource: &str,
        action: &str,
        tenant_id: Option<Uuid>,
    ) -> Result<bool> {
        let permissions = self.get_user_permissions(user_id, tenant_id).await?;

        Ok(permissions.iter().any(|p| p.matches(resource, action)))
    }

    /// Compute permissions from database
    async fn compute_permissions(
        &self,
        user_id: Uuid,
        tenant_id: Option<Uuid>,
    ) -> Result<Vec<Permission>> {
        // 1. Get user's roles (including expired check)
        let user_roles = self.get_user_roles(user_id, tenant_id).await?;
        let role_ids: Vec<Uuid> = user_roles.iter().map(|ur| ur.role_id).collect();

        if role_ids.is_empty() {
            return Ok(vec![]);
        }

        // 2. Get all roles in hierarchy
        let all_roles = self.hierarchy.get_all_roles(&role_ids, tenant_id).await?;
        let all_role_ids: Vec<Uuid> = all_roles.iter().map(|r| r.id).collect();

        // 3. Get permissions for all roles
        let sql = r#"
            SELECT DISTINCT p.id, p.resource, p.action, p.description, p.constraints, p.created_at
            FROM permissions p
            INNER JOIN role_permissions rp ON p.id = rp.permission_id
            WHERE rp.role_id::text = ANY($1)
            ORDER BY p.resource, p.action
        "#;

        let client = self.pool.get().await?;
        let role_id_strings: Vec<String> = all_role_ids.iter().map(|id| id.to_string()).collect();
        let rows = client.query(sql, &[&role_id_strings]).await?;
        let permissions: Vec<Permission> = rows.into_iter().map(Permission::from_row).collect();

        Ok(permissions)
    }

    /// Get user's direct role assignments
    async fn get_user_roles(
        &self,
        user_id: Uuid,
        tenant_id: Option<Uuid>,
    ) -> Result<Vec<UserRole>> {
        let sql = r#"
            SELECT id, user_id, role_id, tenant_id, granted_by, granted_at, expires_at
            FROM user_roles
            WHERE user_id::text = $1
              AND ($2::text IS NULL OR tenant_id::text = $2)
              AND (expires_at IS NULL OR expires_at > NOW())
        "#;

        let client = self.pool.get().await?;
        let user_id_string = user_id.to_string();
        let tenant_id_string = tenant_id.map(|id| id.to_string());
        let rows = client.query(sql, &[&user_id_string, &tenant_id_string]).await?;
        let user_roles: Vec<UserRole> = rows.into_iter().map(UserRole::from_row).collect();

        Ok(user_roles)
    }

    /// Clear cache for specific user
    pub fn invalidate_user(&self, user_id: Uuid) {
        self.cache.invalidate_user(user_id);
    }

    /// Clear entire cache
    pub fn clear_cache(&self) {
        self.cache.clear();
    }

    /// Get cache statistics
    pub fn cache_stats(&self) -> super::cache::CacheStats {
        self.cache.stats()
    }
}

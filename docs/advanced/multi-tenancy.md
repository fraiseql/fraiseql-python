---
title: Multi-Tenancy
description: Tenant isolation patterns with PostgreSQL RLS and data partitioning
tags:
  - multi-tenancy
  - isolation
  - RLS
  - PostgreSQL
  - security
---

# Multi-Tenancy

Comprehensive guide to implementing multi-tenant architectures in FraiseQL with complete data isolation, tenant context propagation, and scalable database patterns.

## Overview

Multi-tenancy allows a single application instance to serve multiple organizations (tenants) with complete data isolation and customizable behavior per tenant.

**Prerequisites**: Before implementing multi-tenancy, ensure you understand:

- [CQRS Pattern](../core/concepts-glossary.md#cqrs-command-query-responsibility-segregation) - Foundation for tenant isolation
- [Security Basics](../production/security.md) - RLS and access control fundamentals
- [Context Propagation](../advanced/where-input-types.md) - Dynamic filtering patterns

**Key Strategies:**

- Row-level security (RLS) with tenant_id filtering
- Database per tenant
- Schema per tenant
- Shared database with tenant isolation
- Hybrid approaches

## How RLS Works (Common Misconception)

> **FAQ: Do I need one PostgreSQL user per application user?**
>
> **No.** This is a common misconception. FraiseQL uses **session variables** with a shared connection pool - you only need one database role for your application.

### Session Variables vs. Database Roles

There are two approaches to RLS in PostgreSQL:

| Approach | How It Works | Use Case |
|----------|--------------|----------|
| **Database Role per User** | Each app user = PostgreSQL role. RLS uses `current_user`. | Rarely practical for web apps with thousands of users |
| **Session Variables** ✅ | All users share one DB role. App sets `SET LOCAL app.tenant_id = 'X'` before each query. RLS uses `current_setting()`. | **Standard for web applications. FraiseQL uses this.** |

### How FraiseQL Implements This

```
┌─────────────────┐     ┌──────────────────────────┐     ┌─────────────────┐
│  App User A     │────▶│  Shared Connection Pool  │────▶│   PostgreSQL    │
│  (tenant: X)    │     │   (1 DB role: app_user)  │     │                 │
├─────────────────┤     │                          │     │  RLS policies   │
│  App User B     │────▶│  SET LOCAL app.tenant_id │────▶│  check session  │
│  (tenant: Y)    │     │  SET LOCAL app.user_id   │     │  variables      │
└─────────────────┘     └──────────────────────────┘     └─────────────────┘
```

When you create a `FraiseQLRepository` with context, it automatically sets session variables before every query:

```python
from fraiseql.db import FraiseQLRepository

# Pass tenant/user context when creating the repository
repo = FraiseQLRepository(db_pool, context={
    "tenant_id": "abc-123",      # → SET LOCAL app.tenant_id = 'abc-123'
    "user_id": "user-456",       # → SET LOCAL app.user_id = 'user-456'
    "contact_id": "contact-789", # → SET LOCAL app.contact_id = 'contact-789'
    "roles": [{"name": "admin"}] # → Computes app.is_super_admin
})

# Every query now automatically:
# 1. Gets a connection from the shared pool
# 2. Runs SET LOCAL for all context variables (transaction-scoped)
# 3. Executes your query (RLS policies filter based on session vars)
# 4. Returns connection to pool (SET LOCAL vars are auto-cleared)
```

Your RLS policies then reference these session variables:

```sql
-- This policy uses the session variable set by FraiseQL. NULLIF: on a pooled
-- connection that already served a tenant, an unset variable reads as '', not NULL.
CREATE POLICY tenant_isolation ON orders
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
```

### Why This Is Secure

- **`SET LOCAL`** is transaction-scoped - variables are automatically cleared when the transaction ends
- Each request gets a fresh connection with fresh session state
- No risk of one user seeing another user's data due to connection reuse
- RLS is enforced at the database level - even bugs in app code can't bypass it

### Available Session Variables

FraiseQL automatically sets these based on your context:

| Context Key | Session Variable | Used For |
|-------------|------------------|----------|
| `tenant_id` | `app.tenant_id` | Multi-tenant isolation |
| `user_id` | `app.user_id` | User-level row filtering |
| `contact_id` | `app.contact_id` | Alternative user identifier |
| `roles` | `app.is_super_admin` | `true` when the roles (names or `{"name": ...}` dicts) include `super_admin`; `false` when they don't, or when `user_id` is set without `roles` |

A key whose value is `None` is not forwarded.

## Tenant Isolation Architecture

### Multi-Tenant Data Flow

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Client    │───▶│  Auth       │───▶│ Repository  │───▶│ PostgreSQL  │
│  Request    │    │ Middleware  │    │  Layer      │    │  Database   │
│             │    │             │    │             │    │             │
│ JWT Token   │    │ Extract     │    │ Tenant      │    │ RLS Policy  │
│ X-Tenant-ID │    │ Tenant ID   │    │ Context     │    │ Filtering   │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                                                          │
                                                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    TENANT DATA ONLY                         │
│  • tenant_a.users can only see tenant_a data               │
│  • tenant_b.users can only see tenant_b data               │
│  • Complete isolation at database level                    │
└─────────────────────────────────────────────────────────────┘
```

**Isolation Layers:**

1. **Network**: API Gateway routes by subdomain/header
2. **Application**: Middleware sets tenant context
3. **Database**: RLS policies enforce row-level filtering
4. **Caching**: Tenant-scoped cache invalidation

## Architecture Patterns

### Pattern 1: Row-Level Security (Most Common)

Single database, tenant_id column in all tables:

```sql
-- Example schema
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    subdomain TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE tb_user (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES organizations(id),
    email TEXT NOT NULL,
    name TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, email)
);

CREATE TABLE tb_order (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES organizations(id),
    user_id UUID NOT NULL REFERENCES tb_user(id),
    total DECIMAL(10, 2) NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for tenant filtering
CREATE INDEX idx_users_tenant_id ON users(tenant_id);
CREATE INDEX idx_orders_tenant_id ON orders(tenant_id);

-- RLS policies
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_users ON users
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

CREATE POLICY tenant_isolation_orders ON orders
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);
```

**Pros:**

- Simple to implement
- Cost-effective (single database)
- Easy cross-tenant analytics (for admins)
- Straightforward backups

**Cons:**

- Shared database (noisy neighbor risk)
- RLS overhead on queries
- Must maintain tenant_id discipline

### Pattern 2: Database Per Tenant

Separate database for each tenant:

```python
from fraiseql.db import DatabasePool

class TenantDatabaseManager:
    """Manage separate database per tenant."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.pools: dict[str, DatabasePool] = {}

    async def get_pool(self, tenant_id: str) -> DatabasePool:
        """Get database pool for specific tenant."""
        if tenant_id not in self.pools:
            # Create tenant-specific connection
            db_url = f"{self.base_url.rsplit('/', 1)[0]}/tenant_{tenant_id}"
            self.pools[tenant_id] = DatabasePool(db_url)

        return self.pools[tenant_id]

    async def close_all(self):
        """Close all tenant database pools."""
        for pool in self.pools.values():
            await pool.close()
```

**Pros:**

- Complete isolation
- Per-tenant scaling
- Easy to backup/restore individual tenants
- No RLS overhead

**Cons:**

- Higher infrastructure cost
- Connection pool per database
- Complex cross-tenant queries
- Schema migration overhead

### Pattern 3: Schema Per Tenant

Separate PostgreSQL schema per tenant in single database:

```sql
-- Create tenant schema
CREATE SCHEMA tenant_acme;
CREATE SCHEMA tenant_globex;

-- Each tenant has isolated tables
CREATE TABLE tenant_acme.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    name TEXT
);

CREATE TABLE tenant_globex.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    name TEXT
);
```

```python
from fraiseql.db import DatabasePool

class SchemaPerTenantManager:
    """Manage schema-per-tenant pattern."""

    def __init__(self, db_pool: DatabasePool):
        self.db_pool = db_pool

    async def set_search_path(self, tenant_id: str):
        """Set PostgreSQL search_path to tenant schema."""
        async with self.db_pool.connection() as conn:
            await conn.execute(
                f"SET search_path TO tenant_{tenant_id}, public"
            )
```

**Pros:**

- Good isolation
- Single database connection pool
- Per-tenant schema versioning
- Lower cost than database-per-tenant

**Cons:**

- Search path management complexity
- Schema migration overhead
- PostgreSQL schema limits

## Row-Level Security

### Tenant Context Propagation

Set tenant context in PostgreSQL session:

```python
from fraiseql.db import get_db_pool
from graphql import GraphQLResolveInfo

async def set_tenant_context(tenant_id: str):
    """Set tenant_id in PostgreSQL session variable."""
    pool = get_db_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "SET LOCAL app.current_tenant_id = $1",
            tenant_id
        )

# Middleware to set tenant context
from starlette.middleware.base import BaseHTTPMiddleware

class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Extract tenant from request (subdomain, header, JWT)
        tenant_id = await resolve_tenant_id(request)

        # Store in request state
        request.state.tenant_id = tenant_id

        # Set in database session
        await set_tenant_context(tenant_id)

        response = await call_next(request)
        return response
```

### Automatic Tenant Filtering

FraiseQL automatically adds tenant_id filters when context is set:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type_
class Order:
    id: ID
    tenant_id: ID  # Automatically filtered
    user_id: ID
    total: float
    status: str

@fraiseql.query
async def get_orders(info: GraphQLResolveInfo) -> list[Order]:
    """Get orders for current tenant."""
    tenant_id = info.context["tenant_id"]

    # Explicit tenant filtering (recommended for clarity)
    async with db.connection() as conn:
        result = await conn.execute(
            "SELECT * FROM orders WHERE tenant_id = $1",
            tenant_id
        )
        return [Order(**row) for row in await result.fetchall()]

@fraiseql.query
async def get_order(info: GraphQLResolveInfo, order_id: ID) -> Order | None:
    """Get specific order - tenant isolation enforced."""
    tenant_id = info.context["tenant_id"]

    async with db.connection() as conn:
        result = await conn.execute(
            "SELECT * FROM orders WHERE id = $1 AND tenant_id = $2",
            order_id, tenant_id
        )
        row = await result.fetchone()
        return Order(**row) if row else None
```

### RLS Policy Examples

```sql
-- Basic tenant isolation
CREATE POLICY tenant_isolation ON orders
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

-- Allow tenant admins to see all data
CREATE POLICY tenant_admin_all ON orders
    USING (
        tenant_id = current_setting('app.current_tenant_id')::UUID
        OR current_setting('app.user_role', TRUE) = 'admin'
    );

-- User can only see own orders
CREATE POLICY user_own_orders ON orders
    USING (
        tenant_id = current_setting('app.current_tenant_id')::UUID
        AND user_id = current_setting('app.current_user_id')::UUID
    );

-- Separate policies for SELECT vs INSERT/UPDATE/DELETE
CREATE POLICY tenant_select ON orders
    FOR SELECT
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

CREATE POLICY tenant_insert ON orders
    FOR INSERT
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::UUID);

CREATE POLICY tenant_update ON orders
    FOR UPDATE
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::UUID);

CREATE POLICY tenant_delete ON orders
    FOR DELETE
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);
```

## Tenant Context

### Tenant Resolution Strategies

#### 1. Subdomain-Based

```python
from urllib.parse import urlparse

def extract_tenant_from_subdomain(request) -> str:
    """Extract tenant from subdomain (e.g., acme.yourapp.com)."""
    host = request.headers.get("host", "")
    subdomain = host.split(".")[0]

    # Validate subdomain
    if subdomain in ["www", "api", "admin"]:
        raise ValueError("Invalid tenant subdomain")

    return subdomain

# Look up tenant ID from subdomain
async def resolve_tenant_id(subdomain: str) -> str:
    async with db.connection() as conn:
        result = await conn.execute(
            "SELECT id FROM organizations WHERE subdomain = $1",
            subdomain
        )
        row = await result.fetchone()
        if not row:
            raise ValueError(f"Unknown tenant: {subdomain}")
        return row["id"]
```

#### 2. Header-Based

```python
def extract_tenant_from_header(request) -> str:
    """Extract tenant from X-Tenant-ID header."""
    tenant_id = request.headers.get("X-Tenant-ID")
    if not tenant_id:
        raise ValueError("Missing X-Tenant-ID header")
    return tenant_id
```

#### 3. JWT-Based

```python
def extract_tenant_from_jwt(request) -> str:
    """Extract tenant from JWT token."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    payload = jwt.decode(token, verify=False)  # Already verified by auth middleware
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise ValueError("Token missing tenant_id claim")
    return tenant_id
```

### Complete Tenant Context Setup

```python
from fastapi import FastAPI, Request, HTTPException
from fraiseql.fastapi import create_fraiseql_app

app = FastAPI()

@app.middleware("http")
async def tenant_context_middleware(request: Request, call_next):
    """Set tenant context for all requests."""
    try:
        # 1. Resolve tenant (try multiple strategies)
        tenant_id = None

        # Try JWT first
        if "Authorization" in request.headers:
            try:
                tenant_id = extract_tenant_from_jwt(request)
            except:
                pass

        # Try subdomain
        if not tenant_id:
            try:
                subdomain = extract_tenant_from_subdomain(request)
                tenant_id = await resolve_tenant_id(subdomain)
            except:
                pass

        # Try header
        if not tenant_id:
            try:
                tenant_id = extract_tenant_from_header(request)
            except:
                pass

        if not tenant_id:
            raise HTTPException(status_code=400, detail="Tenant not identified")

        # 2. Store in request state
        request.state.tenant_id = tenant_id

        # 3. Set in database session
        await set_tenant_context(tenant_id)

        # 4. Continue request
        response = await call_next(request)
        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tenant resolution failed: {e}")
```

### GraphQL Context Integration

```python
from fraiseql.fastapi import create_fraiseql_app

def get_graphql_context(request: Request) -> dict:
    """Build GraphQL context with tenant."""
    return {
        "request": request,
        "tenant_id": request.state.tenant_id,
        "user": request.state.user,  # From auth middleware
    }

app = create_fraiseql_app(
    types=[User, Order, Product],
    context_getter=get_graphql_context
)
```

## Database Pool Strategies

### Strategy 1: Shared Pool with RLS

Single connection pool, tenant isolation via RLS:

```python
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.db import DatabasePool

config = FraiseQLConfig(
    database_url="postgresql://user:pass@localhost/app",
    database_pool_size=20,
    database_max_overflow=10
)

# Single pool shared by all tenants
pool = DatabasePool(
    config.database_url,
    min_size=config.database_pool_size,
    max_size=config.database_pool_size + config.database_max_overflow
)

# Use set_tenant_context before queries
async with pool.connection() as conn:
    await conn.execute("SET LOCAL app.current_tenant_id = $1", tenant_id)
    # All queries now filtered by tenant_id via RLS
```

**Characteristics:**

- Cost-effective (single pool)
- Must set session variable for each connection
- RLS provides safety net

### Strategy 2: Pool Per Tenant

Dedicated connection pool per tenant:

```python
class TenantPoolManager:
    """Manage connection pool per tenant."""

    def __init__(self, base_db_url: str, pool_size: int = 5):
        self.base_db_url = base_db_url
        self.pool_size = pool_size
        self.pools: dict[str, DatabasePool] = {}

    async def get_pool(self, tenant_id: str) -> DatabasePool:
        """Get or create pool for tenant."""
        if tenant_id not in self.pools:
            # Option 1: Different database per tenant
            db_url = f"{self.base_db_url.rsplit('/', 1)[0]}/tenant_{tenant_id}"

            # Option 2: Same database, different schema
            # db_url = self.base_db_url
            # Set search_path after connection

            self.pools[tenant_id] = DatabasePool(
                db_url,
                min_size=self.pool_size,
                max_size=self.pool_size * 2
            )

        return self.pools[tenant_id]

    async def close_pool(self, tenant_id: str):
        """Close pool for inactive tenant."""
        if tenant_id in self.pools:
            await self.pools[tenant_id].close()
            del self.pools[tenant_id]

    async def close_all(self):
        """Close all tenant pools."""
        for pool in self.pools.values():
            await pool.close()
        self.pools.clear()

# Usage
pool_manager = TenantPoolManager("postgresql://user:pass@localhost/app")

@app.middleware("http")
async def tenant_pool_middleware(request: Request, call_next):
    tenant_id = await resolve_tenant_id(request)
    request.state.db_pool = await pool_manager.get_pool(tenant_id)
    response = await call_next(request)
    return response
```

**Characteristics:**

- Better isolation
- Higher memory usage (N pools)
- Good for large tenants with high traffic
- Can scale pools independently

### Strategy 3: Hybrid (Shared + Dedicated)

Small tenants share pool, large tenants get dedicated pools:

```python
class HybridPoolManager:
    """Hybrid pool management based on tenant size."""

    def __init__(self, shared_db_url: str):
        self.shared_pool = DatabasePool(shared_db_url, min_size=20, max_size=50)
        self.dedicated_pools: dict[str, DatabasePool] = {}
        self.large_tenants = set()  # Tenants with dedicated pools

    async def get_pool(self, tenant_id: str) -> DatabasePool:
        """Get pool for tenant based on size."""
        if tenant_id in self.large_tenants:
            return self.dedicated_pools[tenant_id]
        return self.shared_pool

    async def promote_to_dedicated(self, tenant_id: str):
        """Promote tenant to dedicated pool."""
        if tenant_id not in self.large_tenants:
            db_url = f"postgresql://user:pass@localhost/tenant_{tenant_id}"
            self.dedicated_pools[tenant_id] = DatabasePool(db_url, min_size=10, max_size=20)
            self.large_tenants.add(tenant_id)
```

## Cross-Tenant Queries

### Admin Cross-Tenant Access

Allow admins to query across tenants:

```python
import fraiseql

@fraiseql.query
@requires_role("super_admin")
async def get_all_tenants_orders(
    info,
    tenant_id: str | None = None,
    limit: int = 100
) -> list[Order]:
    """Admin query: Get orders across tenants."""
    # Bypass RLS by using superuser connection or disabling RLS
    async with db.connection() as conn:
        # Disable RLS for this query (requires appropriate permissions)
        await conn.execute("SET LOCAL row_security = off")

        if tenant_id:
            result = await conn.execute(
                "SELECT * FROM orders WHERE tenant_id = $1 LIMIT $2",
                tenant_id, limit
            )
        else:
            result = await conn.execute(
                "SELECT * FROM orders LIMIT $1",
                limit
            )

        return [Order(**row) for row in await result.fetchall()]
```

### Aggregated Analytics

```python
import fraiseql

@fraiseql.query
@requires_role("super_admin")
async def get_tenant_statistics(info) -> list[TenantStats]:
    """Get statistics across all tenants."""
    async with db.connection() as conn:
        await conn.execute("SET LOCAL row_security = off")

        result = await conn.execute("""
            SELECT
                t.id as tenant_id,
                t.name as tenant_name,
                COUNT(DISTINCT u.id) as user_count,
                COUNT(DISTINCT o.id) as order_count,
                COALESCE(SUM(o.total), 0) as total_revenue
            FROM organizations t
            LEFT JOIN users u ON u.tenant_id = t.id
            LEFT JOIN orders o ON o.tenant_id = t.id
            GROUP BY t.id, t.name
            ORDER BY total_revenue DESC
        """)

        return [TenantStats(**row) for row in await result.fetchall()]
```

## Tenant-Aware Caching

Cache data per tenant to avoid leakage:

```python
import fraiseql

from fraiseql.caching import Cache

class TenantCache:
    """Tenant-aware caching wrapper."""

    def __init__(self, cache: Cache):
        self.cache = cache

    def _tenant_key(self, tenant_id: str, key: str) -> str:
        """Generate tenant-scoped cache key."""
        return f"tenant:{tenant_id}:{key}"

    async def get(self, tenant_id: str, key: str):
        """Get cached value for tenant."""
        return await self.cache.get(self._tenant_key(tenant_id, key))

    async def set(self, tenant_id: str, key: str, value, ttl: int = 300):
        """Set cached value for tenant."""
        return await self.cache.set(
            self._tenant_key(tenant_id, key),
            value,
            ttl=ttl
        )

    async def delete(self, tenant_id: str, key: str):
        """Delete cached value for tenant."""
        return await self.cache.delete(self._tenant_key(tenant_id, key))

    async def clear_tenant(self, tenant_id: str):
        """Clear all cache for tenant."""
        pattern = f"tenant:{tenant_id}:*"
        await self.cache.delete_pattern(pattern)

# Usage
tenant_cache = TenantCache(cache)

@fraiseql.query
async def get_products(info) -> list[Product]:
    """Get products with tenant-aware caching."""
    tenant_id = info.context["tenant_id"]

    # Check cache
    cached = await tenant_cache.get(tenant_id, "products")
    if cached:
        return cached

    # Fetch from database
    async with db.connection() as conn:
        result = await conn.execute(
            "SELECT * FROM products WHERE tenant_id = $1",
            tenant_id
        )
        products = [Product(**row) for row in await result.fetchall()]

    # Cache result
    await tenant_cache.set(tenant_id, "products", products, ttl=600)
    return products
```

## Data Export & Import

### Tenant Data Export

```python
import fraiseql

import json
from datetime import datetime

@fraiseql.mutation
@requires_permission("tenant:export")
async def export_tenant_data(info) -> str:
    """Export all tenant data as JSON."""
    tenant_id = info.context["tenant_id"]

    export_data = {
        "tenant_id": tenant_id,
        "exported_at": datetime.utcnow().isoformat(),
        "users": [],
        "orders": [],
        "products": []
    }

    async with db.connection() as conn:
        # Export users
        result = await conn.execute(
            "SELECT * FROM users WHERE tenant_id = $1",
            tenant_id
        )
        export_data["users"] = [dict(row) for row in await result.fetchall()]

        # Export orders
        result = await conn.execute(
            "SELECT * FROM orders WHERE tenant_id = $1",
            tenant_id
        )
        export_data["orders"] = [dict(row) for row in await result.fetchall()]

        # Export products
        result = await conn.execute(
            "SELECT * FROM products WHERE tenant_id = $1",
            tenant_id
        )
        export_data["products"] = [dict(row) for row in await result.fetchall()]

    # Save to file or return JSON
    export_json = json.dumps(export_data, default=str)
    return export_json
```

### Tenant Data Import

```python
import fraiseql

@fraiseql.mutation
@requires_permission("tenant:import")
async def import_tenant_data(info, data: str) -> bool:
    """Import tenant data from JSON."""
    tenant_id = info.context["tenant_id"]
    import_data = json.loads(data)

    async with db.connection() as conn:
        async with conn.transaction():
            # Import users
            for user_data in import_data.get("users", []):
                user_data["tenant_id"] = tenant_id  # Force current tenant
                await conn.execute("""
                    INSERT INTO users (id, tenant_id, email, name, created_at)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (id) DO UPDATE SET
                        email = EXCLUDED.email,
                        name = EXCLUDED.name
                """, user_data["id"], user_data["tenant_id"],
                     user_data["email"], user_data["name"], user_data["created_at"])

            # Import orders
            for order_data in import_data.get("orders", []):
                order_data["tenant_id"] = tenant_id
                await conn.execute("""
                    INSERT INTO orders (id, tenant_id, user_id, total, status, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (id) DO UPDATE SET
                        total = EXCLUDED.total,
                        status = EXCLUDED.status
                """, order_data["id"], order_data["tenant_id"], order_data["user_id"],
                     order_data["total"], order_data["status"], order_data["created_at"])

    return True
```

## Tenant Provisioning

### New Tenant Workflow

```python
import fraiseql

from uuid import uuid4

@fraiseql.mutation
@requires_role("super_admin")
async def provision_tenant(
    info,
    name: str,
    subdomain: str,
    admin_email: str,
    plan: str = "basic"
) -> Organization:
    """Provision new tenant with admin user."""
    tenant_id = str(uuid4())

    async with db.connection() as conn:
        async with conn.transaction():
            # 1. Create organization
            result = await conn.execute("""
                INSERT INTO organizations (id, name, subdomain, plan, created_at)
                VALUES ($1, $2, $3, $4, NOW())
                RETURNING *
            """, tenant_id, name, subdomain, plan)

            org = await result.fetchone()

            # 2. Create admin user
            admin_id = str(uuid4())
            await conn.execute("""
                INSERT INTO users (id, tenant_id, email, name, roles, created_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
            """, admin_id, tenant_id, admin_email, "Admin User", ["admin"])

            # 3. Create default data (optional)
            await conn.execute("""
                INSERT INTO settings (tenant_id, key, value)
                VALUES
                    ($1, 'theme', 'default'),
                    ($1, 'timezone', 'UTC'),
                    ($1, 'locale', 'en-US')
            """, tenant_id)

            # 4. Initialize schema (if using schema-per-tenant)
            # await conn.execute(f"CREATE SCHEMA IF NOT EXISTS tenant_{tenant_id}")
            # Run migrations for tenant schema

    # 5. Send welcome email
    await send_welcome_email(admin_email, subdomain)

    return Organization(**org)
```

## Performance Optimization

### Index Strategy

```sql
-- Ensure tenant_id is first column in composite indexes
CREATE INDEX idx_orders_tenant_user ON orders(tenant_id, user_id);
CREATE INDEX idx_orders_tenant_status ON orders(tenant_id, status);
CREATE INDEX idx_orders_tenant_created ON orders(tenant_id, created_at DESC);

-- Partial indexes for active tenants
CREATE INDEX idx_active_tenant_orders ON orders(tenant_id, created_at)
WHERE status IN ('pending', 'processing');
```

### Query Optimization

```python
# GOOD: tenant_id first in WHERE clause
SELECT * FROM orders
WHERE tenant_id = 'uuid' AND status = 'completed'
ORDER BY created_at DESC
LIMIT 10;

# BAD: Missing tenant_id filter
SELECT * FROM orders
WHERE user_id = 'uuid'
ORDER BY created_at DESC;

# GOOD: Explicit tenant_id
SELECT * FROM orders
WHERE tenant_id = 'uuid' AND user_id = 'uuid'
ORDER BY created_at DESC;
```

### Connection Pool Tuning

```python
# Small tenants: Shared pool
config = FraiseQLConfig(
    database_pool_size=20,
    database_max_overflow=10
)

# Large tenant: Dedicated pool
large_tenant_pool = DatabasePool(
    "postgresql://user:pass@localhost/tenant_large",
    min_size=10,
    max_size=30
)
```

## Next Steps

- [Authentication](authentication.md) - Tenant-scoped authentication
- [Bounded Contexts](bounded-contexts.md) - Multi-tenant DDD patterns
- [Performance](../performance/index.md) - Query optimization per tenant
- [Security](../production/security.md) - Tenant isolation security

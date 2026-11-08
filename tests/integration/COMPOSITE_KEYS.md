# Composite Key & Multi-Tenant Integration Tests

This document describes composite key federation and multi-tenant integration tests for Apollo Federation v2 with FraiseQL.

## Overview

Composite keys are federation keys composed of multiple fields, commonly used in multi-tenant systems:

### Single Field Key (Standard)

```graphql
@key(fields: ["id"])
type User {
    id: ID!
}
```

Query: `user(id: "...")`

### Composite Key (Multi-Field)

```graphql
@key(fields: ["tenantId", "userId"])
type TenantUser {
    tenantId: String!
    userId: String!
}
```

Query: `tenantUser(tenantId: "...", userId: "...")`

## Multi-Tenant Architecture

### Data Isolation Pattern

```
┌─────────────────────────────────────────────────┐
│         Apollo Router Gateway                   │
└────────────────┬────────────────────────────────┘
                 │
         ┌───────┴──────────┐
         │                  │
    ┌────▼────────┐    ┌───▼──────────┐
    │ Tenant A    │    │ Tenant B     │
    │ Subgraph    │    │ Subgraph     │
    └────┬────────┘    └───┬──────────┘
         │                  │
    ┌────▼────────┐    ┌───▼──────────┐
    │PostgreSQL   │    │PostgreSQL    │
    │Tenant A DB  │    │Tenant B DB   │
    └─────────────┘    └──────────────┘

Single Database with Isolation:
    ┌─────────────────────────────────┐
    │     PostgreSQL (Shared)         │
    ├─────────────────────────────────┤
    │ tb_user (tenant_id, user_id)    │
    │ tb_order (tenant_id, order_id)  │
    │ ...                             │
    └─────────────────────────────────┘
```

### Composite Key Structure

In multi-tenant systems, composite keys typically include:

```
Entity Key = TenantId + EntityId

Examples:

- User: (tenant_id: "acme-corp", user_id: "550e8400-...")
- Order: (tenant_id: "acme-corp", order_id: "650e8400-...")
- Product: (tenant_id: "acme-corp", product_id: "750e8400-...")
```

## Test Scenarios

### 1. Setup Validation

**Test**: `test_composite_key_setup_validation`

Validates that the environment supports composite key operations:

- Database schema has composite key structure
- Services can query entities
- Data exists for testing

**Expected Outcome**: System ready for composite key testing

---

### 2. Single Field Key (Baseline)

**Test**: `test_composite_key_single_field_federation`

Tests single-field keys as baseline (current implementation):

- User entity with single UUID key
- Resolution from extended subgraph
- Validates infrastructure foundation

**Example**:

```graphql
query {
    user(id: "550e8400-e29b-41d4-a716-446655440001") {
        id
        identifier
    }
}
```

**Expected Outcome**: Single field resolution works correctly

---

### 3. Multi-Field Key Resolution

**Test**: `test_composite_key_multi_field_resolution`

Tests multi-field composite key infrastructure:

- Multiple fields available for key composition
- Resolution with combined fields
- Infrastructure readiness for true composite keys

**Example** (future):

```graphql
query {
    user(tenantId: "acme", userId: "550e8400...") {
        id
        identifier
    }
}
```

**Validates**: System can resolve entities with multiple key fields

---

### 4. Tenant Isolation

**Test**: `test_tenant_isolation_with_composite_keys`

Tests multi-tenant data isolation patterns:

- Users from different tenants are isolated
- Composite key includes tenant identifier
- Cross-tenant queries fail or return null

**Pattern**:

```
Query Tenant A data with Tenant B credentials → Denied/Null
Query Tenant A data with Tenant A credentials → Success
```

**Expected Outcome**: Data isolation is enforced

---

### 5. Batch Entity Resolution

**Test**: `test_composite_key_entity_batch_resolution`

Tests resolving multiple entities with composite keys:

- Query 5+ users simultaneously
- Each with composite key structure
- All resolved consistently

**Example**:

```graphql
query {
    users(limit: 5) {
        id           # Part of composite key
        identifier
    }
}
```

**Validates**: Batch operations work with composite keys

---

### 6. Mutation with Isolation

**Test**: `test_composite_key_mutation_with_isolation`

Tests mutations preserve tenant isolation:

- Create entity within tenant context
- Entity tagged with tenant_id in composite key
- Mutation respects isolation boundaries

**Example**:

```graphql
mutation {
    createUser(
        tenantId: "acme"
        identifier: "test@acme.com"
        name: "Test User"
    ) {
        id            # Composite: (tenantId, userId)
        identifier
    }
}
```

**Validates**: Mutations respect composite key and isolation

---

### 7. Cross-Subgraph Federation

**Test**: `test_composite_key_federation_across_boundaries`

Tests composite key federation across subgraph boundaries:

- Orders subgraph references User via composite key
- User resolution includes all composite key fields
- Isolation maintained across federation

**Example**:

```graphql
mutation {
    createOrder(
        tenantId: "acme"
        userId: "550e8400..."
        status: "pending"
    ) {
        id
        user {
            id           # Composite key maintained
            identifier
        }
    }
}
```

**Validates**: Composite keys work across federation boundaries

---

### 8. Gateway Resolution

**Test**: `test_composite_key_gateway_resolution`

Tests gateway-level composite key handling:

- Gateway routes queries with composite keys
- Multi-level resolution maintains isolation
- Consistency across resolution layers

**Example**:

```graphql
query {
    users(tenantId: "acme") {
        id
        identifier
        orders {
            id
            user {
                id          # Composite key verified at each level
                identifier
            }
        }
    }
}
```

**Validates**: Gateway maintains composite key consistency

---

### 9. Performance at Scale

**Test**: `test_composite_key_performance`

Tests composite key performance:

- Resolve 20 users with composite keys
- Each user has multiple orders
- Measure total latency

**Target**: < 5 seconds for 20 users + orders

**Validates**: Performance scales with composite keys

---

## Running Composite Key Tests

### Quick Start

```bash
cd tests/integration
docker-compose up -d
sleep 30
cargo test test_composite_key_ --ignored --nocapture
docker-compose down -v
```

### Automated

```bash
./run_composite_key_tests.sh
```

### Individual Test

```bash
cargo test test_composite_key_multi_field_resolution --ignored --nocapture
```

## Composite Key Patterns

### Pattern 1: Tenant + Entity

```sql
CREATE TABLE tb_user (
    tenant_id TEXT NOT NULL,
    user_id UUID NOT NULL,
    identifier TEXT NOT NULL,
    name TEXT NOT NULL,

    PRIMARY KEY (tenant_id, user_id),
    UNIQUE (tenant_id, identifier)
);

-- Federation key: (tenant_id, user_id)
-- @key(fields: ["tenantId", "userId"])
```

### Pattern 2: Organization + Account

```sql
CREATE TABLE tb_account (
    org_id TEXT NOT NULL,
    account_id UUID NOT NULL,
    name TEXT NOT NULL,
    status TEXT,

    PRIMARY KEY (org_id, account_id)
);

-- Federation key: (org_id, account_id)
-- @key(fields: ["orgId", "accountId"])
```

### Pattern 3: Workspace + Resource

```sql
CREATE TABLE tb_resource (
    workspace_id TEXT NOT NULL,
    resource_id UUID NOT NULL,
    type TEXT NOT NULL,
    data JSONB,

    PRIMARY KEY (workspace_id, resource_id)
);

-- Federation key: (workspace_id, resource_id)
-- @key(fields: ["workspaceId", "resourceId"])
```

## Multi-Tenant Schema Example

### Users Subgraph

```python
@type
@key(fields=["id"])  # MVP: single field
class User:
    id: ID
    tenantId: String  # Added for multi-tenant
    identifier: str
    email: str
    name: str


@type
class Query:
    def user(self, id: ID) -> Optional[User]:
        """Get user by ID (within tenant context)"""
        pass

    def users(self, tenantId: String) -> List[User]:
        """Get users for tenant"""
        pass
```

### Orders Subgraph

```python
@extends
@key(fields=["id"])  # MVP: extends with single field
@type
class User:
    id: ID = external()
    tenantId: String = external()
    orders: List["Order"]


@type
@key(fields=["id"])
class Order:
    id: ID
    tenantId: String  # Part of composite key
    userId: ID
    status: str
    total: float


@type
class Query:
    def order(self, id: ID, tenantId: String) -> Optional[Order]:
        """Get order by composite key"""
        pass

    def orders(self, tenantId: String) -> List[Order]:
        """Get orders for tenant"""
        pass
```

## Tenant Isolation Enforcement

### Query-Level Isolation

```

1. Client request arrives with tenant context
2. Gateway validates tenant_id in request
3. Query executed with tenant_id filter
4. Result includes only client's tenant data
```

### Mutation-Level Isolation

```

1. Mutation includes tenant_id
2. System validates mutation is for client's tenant
3. Entity created with tenant_id in composite key
4. Result scoped to client's tenant
```

### Federation-Level Isolation

```

1. Entity extension includes tenant_id
2. Cross-subgraph query includes tenant_id
3. Each subgraph filters by tenant_id
4. Isolation maintained across boundaries
```

## Performance Characteristics

### Composite Key Indexing

```sql
-- Composite key index (efficient)
CREATE INDEX idx_user_composite ON tb_user(tenant_id, user_id);
✓ Fast lookup by (tenant_id, user_id)
✓ Fast tenant-only queries with tenant_id prefix

-- Separate indexes
CREATE INDEX idx_tenant ON tb_user(tenant_id);
CREATE INDEX idx_user_id ON tb_user(user_id);
⚠ May cause extra lookups
⚠ Less efficient than composite index
```

### Query Performance

| Query Type | Latency Target | Notes |
|-----------|-----------------|-------|
| Single user (composite key) | <10ms | Indexed lookup |
| Tenant users (20 total) | <20ms | Partial composite index |
| User with orders (federated) | <50ms | Cross-subgraph |
| Batch 20 users + orders | <1s | Multiple queries |

## Implementation Status

### ✅ Implemented (MVP)

- Single field keys with UUID (current infrastructure)
- Entity resolution within subgraphs
- Federation across subgraphs
- Batch queries

### 🚧 In Progress / Future

- Multi-field composite keys (infrastructure ready)
- Multi-tenant isolation enforcement
- Tenant context propagation
- Row-level security

### 📋 Future Enhancements

- Automatic tenant_id injection in queries
- Tenant-scoped caching
- Cross-tenant analytics (secure)
- Tenant-specific rate limiting

## Debugging Composite Keys

### View Composite Key Queries

```bash
docker-compose logs -f orders-subgraph | grep -i "composite\|key\|tenant"
```

### Check Database Schema

```sql
-- Verify composite key structure
\d tb_user
\d tb_order

-- Check indexes
\di *

-- Sample data
SELECT tenant_id, user_id, identifier FROM tb_user LIMIT 5;
SELECT tenant_id, order_id, user_id FROM tb_order LIMIT 5;
```

### Manual Composite Key Query

```bash
curl -X POST http://localhost:4001/graphql \
  -H "Content-Type: application/json" \
  -d '{
    "query": "{ users(limit: 3) { id identifier } }"
  }'
```

## Testing Checklist

### MVP (Single Field Keys)

- [ ] Single field resolution works
- [ ] Entity queries succeed
- [ ] Cross-subgraph resolution works
- [ ] Batch queries complete quickly
- [ ] Mutations preserve entity references

### Multi-Tenant Ready (Infrastructure)

- [ ] Multiple fields available in key
- [ ] Tenant_id included in schema
- [ ] Composite key indexing efficient
- [ ] Query filters by tenant_id
- [ ] Isolation model documented

### Production Ready (Future)

- [ ] Multi-field composite keys implemented
- [ ] Tenant isolation enforced at query level
- [ ] Tenant context auto-injected
- [ ] Row-level security working
- [ ] Performance meets SLA

## Troubleshooting

### "Composite key query returns wrong data"

Possible causes:

1. Tenant context not passed in query
2. Database missing tenant_id column
3. Index not using composite key prefix
4. Query filter missing tenant_id

### "Cross-tenant data visible"

Critical issue! Check:

1. Isolation not enforced at gateway level
2. Subgraph queries missing tenant_id filter
3. Extended types not including tenant_id
4. Database not filtering by tenant_id

### "Composite key performance slow"

Check:

1. Composite index missing or incorrect
2. Query not using index (EXPLAIN plan)
3. Too many subgraph calls (batching needed)
4. Network latency between subgraphs

## Query Examples

### Get User with Composite Key

```graphql
query GetUserWithCompositeKey {
    user(id: "550e8400-e29b-41d4-a716-446655440001") {
        id
        identifier
        email
    }
}
```

### Get Tenant Users

```graphql
query GetTenantUsers {
    users(tenantId: "acme-corp") {
        id
        identifier
        email
        createdAt
    }
}
```

### Get User with Orders (Composite Federation)

```graphql
query GetUserWithOrders {
    user(id: "550e8400-e29b-41d4-a716-446655440001") {
        id
        identifier
        orders {
            id
            status
            total
        }
    }
}
```

### Federated Query Through Gateway

```graphql
query FederatedCompositeKeyQuery {
    users(tenantId: "acme-corp") {
        id
        identifier
        orders {
            id
            status
            total
            user {
                id
                identifier
            }
        }
    }
}
```

## Next Steps

After composite key tests pass:

1. **Task #5**: 3+ subgraph federation tests
   - Products subgraph with composite keys
   - 3-hop federated queries

2. **Task #6**: Apollo Router verification
   - Gateway handles composite keys
   - Query planning with composite keys

3. **Task #8**: Performance benchmarking
   - Composite key latency analysis
   - Tenant isolation overhead

## References

- [Apollo Federation @key Directive](https://www.apollographql.com/docs/apollo-server/federation/entities/#defining-an-entity)
- [Multi-Tenant SaaS Architecture](https://martinfowler.com/articles/multi-tenant.html)
- [PostgreSQL Composite Indexes](https://www.postgresql.org/docs/current/indexes-multicolumn.html)

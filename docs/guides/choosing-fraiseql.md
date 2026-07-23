---
title: "Choosing FraiseQL: Is It Right for Your Project?"
description: FraiseQL is a Python runtime GraphQL framework for PostgreSQL. It's optimized for a specific set of problems. This guide helps you decide if it's a good fit.
keywords: ["debugging", "implementation", "best-practices", "deployment", "tutorial"]
tags: ["documentation", "reference"]
---

# Choosing FraiseQL: Is It Right for Your Project?

FraiseQL is a **Python runtime GraphQL framework for PostgreSQL**. It builds your GraphQL schema in memory at app startup and serves it over FastAPI, reading from PostgreSQL views and writing through PostgreSQL functions (CQRS). It is **not a general-purpose, any-database GraphQL engine** — it's optimized for a specific set of problems. This guide helps you decide if it's a good fit.

---

## Prerequisites

### Required Knowledge

- GraphQL concepts and use cases
- Database architecture and query patterns
- ACID vs eventual consistency trade-offs
- API design and performance requirements
- Your project's data model and access patterns
- Alternative GraphQL engines and ORMs
- Latency and throughput requirements
- Data consistency requirements

### Required Software

- None (this is a decision-making guide, not hands-on implementation)
- Optional: Documentation from your existing system/architecture

### Required Infrastructure

- None (decision guide only)

#### Optional but Recommended

- Performance baseline data from current system (if migrating)
- Team technical expertise assessment
- Architecture documentation

**Time Estimate:** 15-30 minutes for initial evaluation, 1-2 hours for comprehensive comparison with alternatives

## Quick Checklist

Answer these questions honestly:

- [ ] Is **PostgreSQL** your database (or can it be)?
- [ ] Do you need **strong consistency** (no stale data)?
- [ ] Is your database the **source of truth** (not external APIs)?
- [ ] Do you have **relational data** (not primarily document-oriented)?
- [ ] Do you need **ACID compliance** or regulated-industry support?

**Diagram:** System architecture visualization

```d2
direction: down

Count: "Count your YES answers" {
  shape: box
  style.fill: "#fff9c4"
}

Four: "✅ 4-5 YES" {
  shape: box
  style.fill: "#c8e6c9"
}
FourResult: "FraiseQL is likely\na good fit!" {
  shape: box
  style.fill: "#a5d6a7"
}

Two: "⚠️ 2-3 YES" {
  shape: box
  style.fill: "#ffe0b2"
}
TwoResult: "Evaluate carefully\nwith alternatives" {
  shape: box
  style.fill: "#ffcc80"
}

Zero: "❌ 0-1 YES" {
  shape: box
  style.fill: "#ffccbc"
}
ZeroResult: "Probably choose\nsomething else" {
  shape: box
  style.fill: "#ff8a65"
}

Count -> Four
Count -> Two
Count -> Zero
Four -> FourResult
Two -> TwoResult
Zero -> ZeroResult
```

---

## Feature Comparison Matrix

### Consistency & Reliability

| Requirement | FraiseQL | DynamoDB | Cassandra | Firebase | GraphQL-core |
|---|---|---|---|---|---|
| Strong consistency | ✅ | ⚠️ eventual | ⚠️ eventual | ⚠️ eventual | ✅ |
| ACID transactions | ✅ (PostgreSQL) | ⚠️ limited | ❌ | ❌ | ✅ |
| Multi-tenant isolation | ✅ (PostgreSQL RLS) | ✅ | ✅ | ✅ | ⚠️ |
| Audit trail | ✅ (in PostgreSQL) | ⚠️ | ⚠️ | ✅ | ❌ |

### Performance

| Requirement | FraiseQL | DynamoDB | Cassandra | Firebase | GraphQL-core |
|---|---|---|---|---|---|
| Mutation latency | 100-500ms | <10ms | <10ms | <100ms | 50-200ms |
| Query throughput | High | Very high | Very high | Medium | Medium |
| N+1 prevention | ✅ (dataloaders) | ✅ | ✅ | ✅ | ❌ |
| Result caching | ✅ (PostgreSQL-backed) | ❌ | ❌ | ✅ | ⚠️ |

### Operational

| Requirement | FraiseQL | DynamoDB | Cassandra | Firebase | GraphQL-core |
|---|---|---|---|---|---|
| Managed service | ❌ | ✅ | ⚠️ | ✅ | ❌ |
| Infrastructure needed | PostgreSQL | AWS | Cassandra | Google Cloud | Any DB |
| Scaling complexity | Low | Automatic | Medium-High | Automatic | High |
| Cost | Database-dependent | Per request | Self-hosted | Per request | Self-hosted |

### Developer Experience

| Requirement | FraiseQL | DynamoDB | Cassandra | Firebase | GraphQL-core |
|---|---|---|---|---|---|
| Schema authoring | Python decorators | AWS SDKs | CQL | Firebase SDKs | Python |
| Schema build | ✅ At app startup (in memory) | ⚠️ Runtime | ⚠️ Runtime | ⚠️ Runtime | ⚠️ Runtime |
| Authorization rules | ✅ Built-in (authorizers/RBAC) | ⚠️ Custom | ⚠️ Custom | ⚠️ Custom | ⚠️ Custom |
| API generation | ✅ Automatic | ⚠️ Manual | ❌ | ⚠️ Manual | ⚠️ Manual |
| Query optimization | ✅ At runtime (field selection) | ⚠️ At query | ⚠️ At query | ⚠️ At query | ❌ |

---

## Use Case Analysis

### ✅ Excellent Fit

#### 1. Financial Services & Banking

**Why FraiseQL**:

- Requires absolute consistency (no double-charging)
- Needs an audit trail (regulatory compliance)
- Mutations are infrequent, must be correct
- Multi-step writes happen inside a single PostgreSQL function

**Example**: "Transfer $1000 from account A to account B"

```graphql
mutation Transfer($fromId: ID!, $toId: ID!, $amount: Money!) {
  transferMoney(fromId: $fromId, toId: $toId, amount: $amount) {
    fromBalance
    toBalance
    transactionId
  }
}
```

The `transferMoney` mutation calls a PostgreSQL `fn_transfer_money` function: either both
accounts are updated within one transaction, or neither is. No partial transfers.

---

#### 2. Healthcare & Medical Records

**Why FraiseQL**:

- Patient safety depends on data accuracy
- Regulatory compliance (HIPAA, etc.)
- Audit trail required
- Data corruption is unacceptable

**Example**: "Update patient medication with lab-result verification"

```graphql
mutation PrescribeMedication($patientId: ID!, $medication: String!) {
  prescribeMedication(patientId: $patientId, medication: $medication) {
    patient { id, allergies }
    prescription { id, medication }
  }
}
```

The mutation's PostgreSQL function runs the allergy check and the write in one transaction:
a prescription is never issued if the allergy check fails.

---

#### 3. Inventory Management

**Why FraiseQL**:

- Overselling causes financial loss
- Multiple warehouses need coordination
- Order processing is transactional
- Consistency prevents double-booking

**Example**: "Move inventory between warehouses"

```graphql
mutation MoveInventory(
  $sku: String!
  $from: ID!
  $to: ID!
  $quantity: Int!
) {
  moveInventory(sku: $sku, from: $from, to: $to, quantity: $quantity) {
    fromWarehouse { available }
    toWarehouse { available }
  }
}
```

The PostgreSQL function backing `moveInventory` runs both updates in one transaction:
inventory either moves completely or not at all.

---

#### 4. Enterprise SaaS (Multi-tenant)

**Why FraiseQL**:

- Data isolation is critical
- Customers expect consistency
- ACID compliance expected
- Audit logging required

**Example**: "Multi-tenant user management with role hierarchy"

```graphql
query GetTenantUsers($tenantId: ID!) {
  users(tenantId: $tenantId) {
    id, email, role
  }
}

mutation AddUser($tenantId: ID!, $email: String!, $role: String!) {
  addUserToTenant(tenantId: $tenantId, email: $email, role: $role) {
    id, email, role
  }
}
```

Isolation is enforced with PostgreSQL Row-Level Security: FraiseQL sets the tenant context
as a session GUC per request, so RLS policies prevent cross-tenant data leaks and mutations
stay atomic per tenant.

---

### ⚠️ Possible Fit (With Caveats)

#### 1. E-commerce (Without Real-time Features)

**Pros**:

- Order processing needs consistency
- Inventory accuracy critical
- Payment processing needs ACID

**Cons**:

- Users expect <100ms response times (FraiseQL does 100-500ms)
- Real-time stock updates nice-to-have (not required)
- Shopping cart updates don't need strict consistency

**Verdict**: Use FraiseQL for:

- ✅ Order checkout & payment
- ✅ Inventory management
- ❌ Real-time cart updates (use cache)
- ❌ Live stock counts (use Redis)

---

#### 2. CMS & Content Management

**Pros**:

- Data consistency important
- Publishing workflows fit transactional mutations
- Audit trail required

**Cons**:

- Read-heavy (FraiseQL doesn't optimize for this)
- Mutation latency acceptable
- Caching is effective

**Verdict**: FraiseQL works but might be overkill.

- Better choice: WordPress, Strapi, or simpler CMS

---

### ❌ Poor Fit

#### 1. Real-time Analytics

**Why NOT FraiseQL**:

- Needs high throughput (500k+ rows/sec)
- Eventual consistency is fine
- Mutations rare, queries frequent
- Stale data acceptable

**Better choice**: DynamoDB, Cassandra, ClickHouse

**Example anti-pattern**:

```graphql
query RealTimeMetrics {
  metrics(last: 10000) {
    timestamp, value
  }
}
```

FraiseQL would be slow. Use a columnar/analytics store instead.

---

#### 2. Social Media

**Why NOT FraiseQL**:

- Availability > Consistency (AP, not CP)
- Like counts can be approximated
- Comment ordering eventual ok
- High throughput required (1000+ req/sec per user)

**Better choice**: DynamoDB, Cassandra, Firebase

**Example anti-pattern**:

```graphql
mutation LikePost($postId: ID!) {
  likePost(postId: $postId) {
    likes  # Doesn't need exact count
  }
}
```

DynamoDB's eventual consistency is perfect here.

---

#### 3. IoT & Time Series

**Why NOT FraiseQL**:

- Millions of writes/sec
- Some data loss acceptable
- Queries are time-range based
- Relational structure minimal

**Better choice**: InfluxDB, TimescaleDB, Prometheus

**Example anti-pattern**:

```graphql
mutation LogSensorReading($sensorId: ID!, $value: Float!) {
  logReading(sensorId: $sensorId, value: $value) {
    sensorId, value, timestamp
  }
}
```

Use a time-series DB directly.

---

#### 4. Real-time Chat / Presence

**Why NOT FraiseQL**:

- Needs low latency (<50ms ideal)
- Eventually consistent is fine
- Message ordering eventual ok
- High concurrent connections

**Better choice**: Firebase, Socket.io + Redis, Websockets

**Example anti-pattern**:

```graphql
mutation SendMessage($chatId: ID!, $text: String!) {
  sendMessage(chatId: $chatId, text: $text) {
    id, text, createdAt
  }
}
```

Use a message broker + cache instead.

---

## Decision Flowchart

```text
START
  │
  ├─ Is PostgreSQL your database (or can it be)?
  │  ├─ NO → Don't use FraiseQL (PostgreSQL only)
  │  └─ YES
  │     │
  │     ├─ Do you need STRONG CONSISTENCY?
  │     │  ├─ NO → Consider DynamoDB/Cassandra for AP workloads
  │     │  └─ YES
  │     │     │
  │     │     ├─ Can mutations wait 100-500ms?
  │     │     │  ├─ NO → Use a low-latency eventual-consistency system
  │     │     │  └─ YES
  │     │     │     │
  │     │     │     ├─ Is your data RELATIONAL (tables, joins)?
  │     │     │     │  ├─ NO → Use a document DB
  │     │     │     │  └─ YES
  │     │     │     │     │
  │     │     │     │     ├─ Do you need enterprise features?
  │     │     │     │     │  ├─ YES (audit, RBAC, multi-tenant)
  │     │     │     │     │  │  └─ FraiseQL is ideal
  │     │     │     │     │  └─ NO
  │     │     │     │     │     └─ FraiseQL works, but simpler systems might too
  │
  └─ END
```

---

## Migration Paths

### From Other GraphQL Engines

**From Apollo Server**:

- Apollo wires up hand-written resolvers; FraiseQL generates resolvers from your PostgreSQL views
- No direct migration, but the schema-first patterns are similar
- Most boilerplate resolvers disappear (reads come from `v_`/`tv_` views)
- Time: 2-4 weeks for a small API

**From Hasura**:

- Hasura auto-generates an API from your schema; FraiseQL maps a Python-decorated schema to PostgreSQL views and functions at startup
- Hasura supports more databases; FraiseQL is PostgreSQL only
- FraiseQL puts write logic in PostgreSQL functions, giving you full transactional control
- Time: 2-3 weeks for migration

**From Prisma**:

- Prisma is ORM-based; FraiseQL is SQL/view-based (CQRS)
- Both eliminate N+1 problems (FraiseQL via dataloaders)
- FraiseQL leans on PostgreSQL features (JSONB, RLS, functions) rather than an ORM layer
- Time: 1-2 weeks (small API)

### To Other Systems

**If you choose wrong and need to migrate OUT**:

**FraiseQL → DynamoDB**:

- Time: 3-4 weeks
- Loss: Strong consistency guarantees
- Gain: Higher throughput, better availability

**FraiseQL → Firebase**:

- Time: 2-3 weeks
- Loss: Transaction support, schema flexibility
- Gain: Managed service, less ops work

**FraiseQL → Cassandra**:

- Time: 4-6 weeks
- Loss: Transaction support, schema validation
- Gain: Extreme scale, availability

---

## Red Flags: Don't Use FraiseQL If

🚫 **You need mutation latency < 50ms**

- FraiseQL's mutations run through PostgreSQL functions and typically take 100-500ms

🚫 **You need Availability in distributed scenarios**

- FraiseQL chooses Consistency, refuses AP

🚫 **Your data is primarily document-based**

- FraiseQL assumes relational schema

🚫 **You need infinite scaling without cost increase**

- FraiseQL's cost scales with database performance

🚫 **You want a managed service (hands-off)**

- FraiseQL requires you to run PostgreSQL and the FastAPI app

🚫 **Your database isn't (and can't be) PostgreSQL**

- FraiseQL targets PostgreSQL only — its CQRS model relies on PostgreSQL views, functions, JSONB, and RLS

🚫 **You're building real-time analytics**

- Use ClickHouse, InfluxDB, or similar

🚫 **You want "eventual consistency" design**

- FraiseQL refuses this philosophy

---

## Green Flags: Do Use FraiseQL If

✅ **You need strong consistency**

- Backed by PostgreSQL ACID transactions

✅ **You have complex multi-step writes**

- Encapsulate them in a single PostgreSQL function (`fn_`), called atomically by a mutation

✅ **You're in a regulated industry** (finance, healthcare)

- Audit logging and compliance enforced in PostgreSQL

✅ **You need multi-tenant data isolation**

- Field-level authorization plus PostgreSQL Row-Level Security

✅ **You want PostgreSQL as the single source of truth**

- Reads from views, writes through functions — one well-understood database

✅ **You're tired of N+1 query problems**

- Dataloaders and view-based reads keep queries flat

✅ **You want schema as code** (not API comments)

- Define types, queries, and mutations with Python decorators

---

## Recommendation: Talk to the Team

Before choosing FraiseQL, answer these questions:

1. **Database**: Is PostgreSQL your database, or can it be?
2. **Consistency**: Is strong consistency worth 100-500ms mutation latency?
3. **Scope**: Do you have relational data and transactional writes?
4. **Compliance**: Do you need regulated-industry features (audit, RBAC)?
5. **Scale**: Does PostgreSQL scale to your throughput needs?

If the answers are yes, FraiseQL is the right choice.

If the answers are mixed, discuss trade-offs with your team. Every architecture choice involves trade-offs.

**There is no universally "best" system.** Only the right choice for your specific problem.

---

## Troubleshooting Decision Process

### "I'm unsure if FraiseQL is right for us"

#### Decision Framework

1. **What's your primary concern?**
   - Data consistency → FraiseQL ✅
   - High availability → Other options ❌
   - Real-time performance (<50ms) → Other options ❌
   - Schema safety → FraiseQL ✅

2. **What's your data model?**
   - Highly relational (10+ tables, joins) → FraiseQL ✅
   - Mostly document-oriented (JSON data) → Firebase/Datastore ✅
   - Time-series focused → ClickHouse/Prometheus ✅
   - Mixed relational + documents → FraiseQL can handle ✅

3. **Do you have this requirement?**
   - Field-level RBAC enforcement → FraiseQL ✅
   - Audit logging compliance → FraiseQL ✅
   - Multi-tenant isolation → FraiseQL ✅
   - Low-latency real-time (<10ms p95) → Other options

4. **What's your team's expertise?**
   - GraphQL comfortable → FraiseQL ✅
   - SQL comfortable → FraiseQL ✅
   - REST API comfortable → No GraphQL learning ❌
   - Needs ORM (no schema code) → Other options ✅

### If 3+ checks passed: Strong FraiseQL fit
### If 1-2 checks passed: Evaluate carefully
### If 0 checks passed: Probably wrong tool

### "Our team is skeptical about consistency trade-offs"

#### Address Concerns

| Concern | Counter-Point | Evidence |
|---------|---------------|----------|
| "100-500ms latency is too slow" | Most business logic already has this latency | Compare: API Gateway (20ms) + DB (50ms) + Network (30ms) = 100ms baseline |
| "We need real-time updates" | FraiseQL supports WebSocket subscriptions | See [Real-time subscriptions](../architecture/realtime/subscriptions.md) |
| "We'll need eventual consistency anyway" | Implement it at the application layer if truly needed | Add caching/queues outside FraiseQL where appropriate |
| "Consistency not important for us" | Then FraiseQL isn't the right choice | Consider alternatives |

### "We're between FraiseQL and [Alternative]"

#### Quick Comparison

| Need | FraiseQL | Firebase | DynamoDB | GraphQL-Core |
|------|----------|----------|----------|--------------|
| Strong consistency | ✅ | ❌ | ❌ | ✅ |
| PostgreSQL-native (views, functions, JSONB, RLS) | ✅ | ❌ | ❌ | ⚠️ |
| Schema as code | ✅ | ❌ | ❌ | ❌ |
| Built-in RBAC | ✅ | ❌ | ❌ | ❌ |
| Low-latency real-time | ❌ | ✅ | ✅ | ❌ |
| Serverless | ❌ | ✅ | ✅ | ❌ |
| Learning curve | Medium | Low | Low | High |

### Recommendation

- If you need consistency + schema safety → FraiseQL
- If you need serverless + real-time → Firebase/DynamoDB
- If you need maximum flexibility → GraphQL-core

### "How do we pilot FraiseQL to prove it works?"

#### Phased Approach

#### Phase 1 (Week 1): POC on single feature

- Pick one GraphQL query reading from a view over 2-3 tables
- Define the type and query with Python decorators
- Run the FastAPI app locally and hit the playground
- Time: 2-4 hours
- Success metric: Query executes and returns data

### Phase 2 (Week 2): Expand to one service

- Migrate one real service to FraiseQL
- Run side-by-side with existing API for comparison
- Load test: Compare performance profiles
- Time: 2-3 days
- Success metric: FraiseQL performance acceptable

### Phase 3 (Weeks 3-4): Production trial

- Deploy to staging
- Shadow traffic (duplicate requests to both)
- Monitor error rates, latency, consistency
- Time: 1-2 weeks
- Success metric: All metrics within acceptable range

### Phase 4 (Week 5+): Full migration

- Gradual cutover: 10% → 25% → 50% → 100%
- Rollback plan ready
- Time: 2-4 weeks depending on traffic
- Success metric: Running in production with no issues

---

## See Also

- [Consistency Model Deep Dive](./consistency-model.md)
- [Production Deployment](./production-deployment.md)
- [Comparisons with Other Engines](../foundation/05-comparisons.md)
- [Core Concepts](../foundation/02-core-concepts.md)

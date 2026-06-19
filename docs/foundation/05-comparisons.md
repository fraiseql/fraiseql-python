---
title: "1.5: FraiseQL Compared to Other Approaches"
description: FraiseQL is one of several approaches to building GraphQL APIs. This topic compares FraiseQL with popular alternatives to help you understand where each approach excels and where it makes tradeoffs.
keywords: ["graphql", "comparison", "architecture", "postgresql", "runtime-framework"]
tags: ["documentation", "reference"]
---

# 1.5: FraiseQL Compared to Other Approaches

**Audience:** Technical decision-makers, architects evaluating GraphQL solutions
**Prerequisite:** Topics 1.1 (What is FraiseQL?), 1.2 (Core Concepts), 1.4 (Design Principles)
**Reading Time:** 20-25 minutes

---

## Overview

FraiseQL is one of several approaches to building GraphQL APIs. This topic compares FraiseQL with popular alternatives to help you understand where each approach excels and where it makes tradeoffs.

FraiseQL is a **Python runtime GraphQL framework for PostgreSQL**. You define types, queries, and mutations with decorators; at application startup the GraphQL schema is built in memory and served over FastAPI. Reads come from PostgreSQL views that return a `data` JSONB column, and writes are delegated to PostgreSQL functions. An optional Rust extension (`fraiseql_rs`) accelerates JSON transformation and field selection on the hot path.

**Key Question:** Which approach is right for your project?

The answer depends on:

- Your data source (a single PostgreSQL database vs. mixed sources)
- Your team's expertise (database, backend, frontend)
- Your performance requirements (predictability vs. flexibility)
- Your development speed priorities (time-to-market vs. long-term maintainability)

---

## Comparison Matrix: At a Glance

| Aspect | FraiseQL | Apollo Server | Hasura | WunderGraph | Custom REST |
|--------|----------|---------------|--------|-------------|-------------|
| **Primary Data Source** | PostgreSQL | Multiple sources | PostgreSQL (and others) | Multiple sources | Anything |
| **Schema Definition** | Python decorators | GraphQL schema language | PostgreSQL schema | Multiple languages | Not applicable |
| **Execution Model** | Runtime (Python over FastAPI), schema built at startup | Runtime | Runtime | Runtime | N/A |
| **Resolver Code** | Automatic (views + functions) | Manual custom code | Automatic rules | Automatic + manual | Manual code |
| **Type Safety** | Database + GraphQL | GraphQL only | PostgreSQL only | GraphQL + custom validation | Code-level only |
| **Performance** | Fast (JSONB + optional Rust pipeline, no N+1) | Variable (resolver dependent) | Variable (rule based) | Moderate (middleware overhead) | Variable |
| **Flexibility** | Limited to DB schema | Very high | Limited to DB + rules | High | Complete |
| **Time to API** | Fast (decorators → views) | Slow (code resolvers) | Fast (introspection) | Moderate | Slow |
| **Learning Curve** | Medium (GraphQL + SQL) | High (GraphQL + resolver patterns) | Low (just SQL) | Moderate | N/A |
| **Best For** | PostgreSQL-backed OLTP APIs | Complex multi-source APIs | Quick PostgreSQL APIs | Flexible API gateway | Simple services |

---

## Detailed Comparisons

### FraiseQL vs. Apollo Server

**Apollo Server** is the most popular GraphQL framework. It's flexible, well-documented, and the industry standard.

#### What Apollo Server Excels At

**Flexibility**

```graphql
type Query {
  user(id: Int!): User
  trendingUsers: [User!]!
  searchUsers(query: String!): [User!]!
  recommendations(userId: Int!): [Recommendation!]!
}
```

Each field can resolve from a different source:

- Database query
- REST API call
- Cache lookup
- Computed value
- File system

**Multi-Source Integration**

```typescript
// Apollo: Combine data from multiple sources
const resolvers = {
  Query: {
    user: async (_, { id }, context) => {
      const user = await context.db.query('SELECT * FROM users WHERE id = ?', [id]);
      const profile = await context.externalAPI.getProfile(id);
      const recommendations = await context.ml.getRecommendations(id);
      return { ...user, profile, recommendations };
    }
  }
};
```

**Ecosystem & Plugins**

- Apollo Server extensions (authentication, logging, monitoring)
- DataLoader (N+1 prevention)
- Apollo Federation (schema stitching)
- Hundreds of community plugins

#### Where Apollo Server Struggles

**Resolver Complexity**

```typescript
// Apollo: Every field needs a resolver
const resolvers = {
  Query: {
    user: (_, { id }, context) => context.db.findUser(id),
  },
  User: {
    id: (user) => user.id,
    email: (user) => user.email,
    orders: (user, _, context) => context.db.findOrders(user.id),  // N+1 problem?
  },
  Order: {
    id: (order) => order.id,
    total: (order) => order.total,
    items: (order, _, context) => context.db.findItems(order.id),  // Another N+1?
  }
};
```

**Manual Optimization**

```typescript
// Apollo: You must implement optimization patterns
const dataLoaders = {
  userLoader: new DataLoader(async (userIds) => {
    return context.db.query('SELECT * FROM users WHERE id = ANY(?)', [userIds]);
  }),
};
```

**Performance Unpredictability**

- Query performance depends on resolver implementation
- N+1 problems can hide until production
- No structural visibility into query costs
- Hard to debug performance issues

**Synchronizing Schemas**

```text
TypeScript type definitions
       ↕ (must match)
GraphQL schema
       ↕ (must match)
Database schema
```

If you change the database, you must update two more places. With FraiseQL the read view's `data` JSONB and your `@fraiseql.type` are the single source of truth.

#### FraiseQL vs. Apollo: Decision

| Your Priority | Better Choice | Why |
|---------------|---------------|-----|
| **Single PostgreSQL-backed API** | FraiseQL | Simpler, faster, fewer N+1 surprises |
| **Multi-source data aggregation** | Apollo Server | FraiseQL targets a single PostgreSQL database |
| **Complex custom business logic in resolvers** | Apollo Server | FraiseQL pushes write logic into PostgreSQL functions |
| **Time-to-market wrapping existing REST APIs** | Apollo Server | Easier to wrap external services |
| **Performance predictability** | FraiseQL | View-driven reads, no per-field resolver fan-out |
| **Team has database expertise** | FraiseQL | Database knowledge directly applies |
| **Team has JavaScript expertise** | Apollo Server | Lower learning curve |

---

### FraiseQL vs. Hasura

**Hasura** automatically generates a GraphQL API by introspecting your PostgreSQL schema.

#### What Hasura Excels At

**Fast Time to API**

```bash
# Hasura: Point at database, get GraphQL API instantly
docker run hasura/graphql-engine:latest \
  --database-url postgresql://user:pass@db:5432/mydb
```

Result: a complete GraphQL API with CRUD operations, relationships, and filtering—without writing a line of code.

**Database-First Approach**

```sql
CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  email VARCHAR(255) NOT NULL UNIQUE,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE orders (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  total DECIMAL(10, 2)
);
```

Hasura immediately exposes:

```graphql
type User {
  id: Int!
  email: String!
  createdAt: DateTime!
  orders: [Order!]!
}

type Order {
  id: Int!
  user: User!
  total: Float!
}
```

**Permission Rules**

```yaml
# Hasura: Row-level security via rules
Users:
  select:
    columns:
      - id
      - email
    filter:
      id: { _eq: X-Hasura-User-Id }
```

**Simplicity for Standard CRUD**

```graphql
query {
  users {
    id
    email
    orders {
      id
      total
    }
  }
}
# Hasura handles the SQL automatically
```

#### Where Hasura Struggles

**Fixed Query Patterns**

```graphql
# Hasura: No custom computed fields without Actions
query {
  user(id: 1) {
    id
    email
    orders {
      id
      total
      items {        # ✅ Can do this
        name
      }
    }
    orderCount       # ❌ Requires custom Action (REST API call)
  }
}
```

With FraiseQL, a computed field is just another key built into the view's `data` JSONB, so it is available without an external Action.

**Action-Based Extensions**

```yaml
# Hasura: Must implement custom logic via Actions
actions:
  - name: searchUsers
    definition:
      kind: query
      arguments:
        query: string!
      output_type: SearchResult
      handler: https://api.example.com/search
```

This converts back to the multi-source problem (like Apollo).

**Runtime Permission Overhead**

- Permission checks evaluated per request
- Permission rules are not statically analyzed
- Complex permissions can cause N+1 queries

**Schema Coupling**

```text
PostgreSQL table/column names ←→ GraphQL schema (1:1 mapping)
```

Rename a table or column and the GraphQL API changes, which can break clients. FraiseQL decouples this: the GraphQL shape is defined by the view's `data` JSONB and your `@fraiseql.type`, independent of the underlying write tables.

#### FraiseQL vs. Hasura: Decision

| Your Priority | Better Choice | Why |
|---------------|---------------|-----|
| **Time to basic CRUD API** | Hasura | Introspection is instant |
| **Standard database queries** | Hasura | Zero code needed |
| **Custom computed fields** | FraiseQL | Built into the read view's JSONB |
| **Decoupling API shape from table layout** | FraiseQL | Views isolate the public schema from write tables |
| **Schema versioning/evolution** | FraiseQL | Explicit types let you version deliberately |
| **Team only knows SQL** | Hasura | No Python needed |
| **Write logic in the database** | FraiseQL | Mutations call PostgreSQL functions |
| **Rapid prototyping** | Hasura | Get an API in minutes |

---

### FraiseQL vs. WunderGraph

**WunderGraph** positions itself as a "serverless GraphQL federation platform." It supports multiple data sources and aims for developer productivity.

#### What WunderGraph Excels At

**Configuration-First Development**

```yaml
# WunderGraph: Configure data sources and relationships
dataSources:
  - name: database
    kind: postgresql
    database_url: ${DATABASE_URL}
  - name: external_api
    kind: graphql
    url: https://api.example.com/graphql
```

**Flexible Data Source Support**

- Relational databases (PostgreSQL, MySQL, MongoDB)
- GraphQL APIs
- REST APIs
- Custom operations

**Built-in Authentication**

```yaml
# WunderGraph: Auth integrated
authentication:
  providers:
    - github
    - auth0
    - custom_webhook
```

**Federation Support**

```typescript
// WunderGraph: Compose multiple GraphQL APIs
import { introspectAndCompose } from '@wundergraph/sdk';

export default {
  apis: [
    introspectAndCompose({
      apiNamespace: 'users',
      url: 'http://users-service/graphql',
    }),
    introspectAndCompose({
      apiNamespace: 'products',
      url: 'http://products-service/graphql',
    }),
  ],
};
```

#### Where WunderGraph Struggles

**Still Manual for Complex Queries**

```typescript
// WunderGraph: You write resolvers for complex operations
export default async function GetUserRecommendations(
  ctx: Context,
  input: GetUserRecommendationsInput,
) {
  const user = await ctx.user.findOne({ id: input.id });
  const recommendations = await ctx.ml.getRecommendations(user.id);
  // Still writing custom code
  return recommendations;
}
```

**Middle-Ground Positioning**

- Not as fast to stand up as Hasura (requires more code)
- More moving parts than FraiseQL's single PostgreSQL path
- Not as flexible as Apollo (no custom middleware)

**Optimization Still on You**

```typescript
// WunderGraph: You're still responsible for optimization
export default async function GetUserWithOrders(
  ctx: Context,
  input: GetUserWithOrdersInput,
) {
  const user = await ctx.db.users.findOne({ id: input.id }); // 1 query
  const orders = await ctx.db.orders.findMany({ userId: user.id }); // 1 query
  // What if orders has 10,000 items? Pagination? Filtering?
  // You have to handle this manually
  return { user, orders };
}
```

#### FraiseQL vs. WunderGraph: Decision

| Your Priority | Better Choice | Why |
|---------------|---------------|-----|
| **Single PostgreSQL database** | FraiseQL | Simpler, one data path |
| **Multiple data sources** | WunderGraph | Explicit multi-source support |
| **Quick API for a single service** | Hasura | Faster than both |
| **Complex business logic** | Apollo Server | More mature ecosystem |
| **No N+1 by construction** | FraiseQL | Nested data comes from view JSONB |
| **Team learning curve** | WunderGraph | Mid-point between options |

---

### FraiseQL vs. Custom REST APIs

Before GraphQL was popular, teams built custom REST APIs. This is still the baseline to compare against.

#### What Custom REST Excels At

**Simplicity for Simple Services**

```python
# REST: Simple to understand
@app.get("/users/{user_id}")
def get_user(user_id: int):
    return db.query("SELECT * FROM users WHERE id = ?", [user_id])
```

**Familiarity**

- Every developer knows REST
- No GraphQL learning curve
- Mature tooling and libraries

**Fine-Grained Control**

```python
# REST: You control exactly what goes into each endpoint
@app.get("/users/{user_id}/recommendations")
def get_recommendations(user_id: int, limit: int = 10):
    # Your logic: exactly what you need, nothing more
    return db.query(
        "SELECT * FROM recommendations WHERE user_id = ? LIMIT ?",
        [user_id, limit],
    )
```

#### Where Custom REST Struggles

**Versioning Chaos**

```text
/api/v1/users/{id}
/api/v2/users/{id}
/api/v3/users/{id}
```

Each API version requires separate endpoints and testing.

**Over-fetching & Under-fetching**

```text
REST API returns:
GET /api/users/1
{
  "id": 1,
  "email": "user@example.com",
  "name": "John",
  "phone": "123-456-7890",    // You don't need this
  "address": { ... }          // Or this
}

Returned 500 bytes, needed 200 bytes
```

Or:

```text
You need user + orders + order items
3 separate requests: GET /users/1, GET /users/1/orders, GET /orders/123/items
```

**No Standard Query Language**

```text
Custom filtering:
GET /api/users?filter=email:contains:@example.com&sort=-created_at&limit=10

Different service:
GET /api/products?q=coffee&sort=price&page=1&per_page=20

Inconsistent APIs everywhere
```

**Documentation Burden**

```text
Each endpoint needs separate documentation:

- GET /users/{id}
- GET /users/{id}/orders
- GET /users/{id}/recommendations
- POST /users
- PUT /users/{id}
- DELETE /users/{id}
- GET /users?search=...&limit=...&offset=...

And that's just for users. Multiply by 20 resources = 100s of endpoints
```

#### FraiseQL vs. REST: Decision

| Your Priority | Better Choice | Why |
|---------------|---------------|-----|
| **Simple CRUD service** | Custom REST | Less overhead |
| **Mobile API with bandwidth concerns** | FraiseQL | Query-specific fields only |
| **Multi-use API (web + mobile + partners)** | FraiseQL | Single flexible API |
| **Team knows REST already** | Custom REST | No GraphQL learning needed |
| **Long-term API evolution** | FraiseQL | Single versioning story |
| **Fast development** | REST or Hasura | Pre-built patterns |

---

## FraiseQL's Unique Position

### What FraiseQL Brings

**1. PostgreSQL as the Source of Truth**

Reads come from `v_`/`tv_` views that build a `data` JSONB column; writes go through `fn_` PostgreSQL functions. Your database team's work (indexes, views, function logic) directly improves API behavior, with no separate resolver layer to keep in sync.

**2. No N+1 by Construction**

Nested data is assembled inside the view's `data` JSONB, so a single GraphQL query maps to a single read. There are no per-field resolvers fanning out into extra queries.

**3. Fast JSON Path**

PostgreSQL JSONB feeds an optional Rust pipeline (`fraiseql_rs`) that handles field selection and JSON transformation efficiently. The framework runs in Python over FastAPI, with the schema assembled in memory at startup.

**4. Minimal Application Code**

Define types and operations with decorators (`@fraiseql.type`, `@fraiseql.query`, `@fraiseql.mutation`). No hand-written resolvers, no DataLoaders, no manual optimization patterns.

### What FraiseQL Trades Off

**Single Data Source**

FraiseQL targets one PostgreSQL database. It is not designed to aggregate data from multiple external APIs in a single query—best for database-centric services.

**Logic Lives in the Database**

Complex write logic happens in PostgreSQL functions, and computed read fields are built into views. Teams that prefer to keep all logic in application code may find this constraining.

**PostgreSQL Only**

FraiseQL v1 deliberately supports PostgreSQL and leans into its strengths (JSONB, functions, views, indexes). This is a focused choice, not a missing feature—if you need a different database, FraiseQL is not the right tool.

---

## Decision Framework: Choosing Your Approach

### If You Answer "YES" to Most of These → Use FraiseQL

- [ ] Your primary data is in a PostgreSQL database
- [ ] You want fast, predictable query performance without N+1 surprises
- [ ] Your team has database expertise
- [ ] You are comfortable putting write logic in PostgreSQL functions
- [ ] Your data relationships are well-defined (not highly dynamic)
- [ ] You want minimal application code (no custom resolvers)
- [ ] You want the public API shape decoupled from your write tables

### If You Answer "YES" to Most of These → Use Hasura

- [ ] You want to launch a GraphQL API as quickly as possible
- [ ] Your database schema is already well-designed
- [ ] Standard CRUD operations cover 80% of your use cases
- [ ] You're using PostgreSQL
- [ ] Simple permission rules are sufficient

### If You Answer "YES" to Most of These → Use Apollo Server

- [ ] You need to aggregate data from multiple sources
- [ ] You need complex custom resolver logic
- [ ] Your team has strong JavaScript/TypeScript expertise
- [ ] Flexibility is more important than performance predictability
- [ ] You're building an API gateway or federation platform

### If You Answer "YES" to Most of These → Use Custom REST

- [ ] This is a simple, single-purpose service
- [ ] You don't need a flexible query language
- [ ] Your team prefers REST familiarity
- [ ] Simplicity matters more than advanced features

---

## Real-World Examples

### Example 1: E-Commerce Platform

**Requirements:**

- Product catalog with search, filtering, recommendations
- Orders with items and order history
- User profiles and permissions
- Shopping cart state

**Best Choice: FraiseQL**

Why:

- Well-defined schema (products, orders, users, cart)
- Fast, predictable reads from view JSONB (catalog, recommendations)
- Performance is critical (search must be fast)
- Clear data relationships
- Database team can optimize indexes and views independently

**API would include:**

```python
import fraiseql
from fraiseql.types import ID


@fraiseql.type(sql_source="v_product", jsonb_column="data")
class Product:
    id: ID
    name: str
    price: float
    rating: float


@fraiseql.query
async def product_search(info, query: str, limit: int = 10) -> list[Product]:
    db = info.context["db"]
    return await db.find("v_product")


@fraiseql.query
async def user_recommendations(info, user_id: ID) -> list[Product]:
    db = info.context["db"]
    return await db.find("v_product")
```

### Example 2: Multi-Tenant SaaS Dashboard

**Requirements:**

- Multiple data sources (main DB, analytics DB, external services)
- Complex permission rules (tenant isolation, role-based)
- Custom computed fields (user's total spend, team metrics)
- Real-time updates via WebSocket

**Best Choice: Apollo Server**

Why:

- Multiple data sources (can't consolidate into one DB)
- Custom business logic needed (computations, complex auth)
- Flexibility more important than performance predictability
- Mature ecosystem for SaaS patterns

### Example 3: Rapid Internal Tool

**Requirements:**

- Quick GraphQL API over an existing PostgreSQL database
- Standard CRUD operations
- Simple permission rules
- Time to launch: 1 week

**Best Choice: Hasura**

Why:

- Time to launch is critical
- Schema is already defined (existing database)
- Standard operations are sufficient
- Zero code = faster development

### Example 4: Mobile App Backend

**Requirements:**

- Minimize bandwidth (mobile networks)
- Fetch exactly the fields needed
- Consistent schema across multiple client versions
- Performance matters (cellular networks)

**Best Choice: FraiseQL or Apollo Server**

Why:

- GraphQL eliminates over-fetching (good for mobile)
- FraiseQL for predictable PostgreSQL-backed performance
- Apollo Server for complex aggregation (if needed)

---

## Summary

| Situation | Best Choice | Runner-Up |
|-----------|-------------|-----------|
| **Single PostgreSQL DB, performance critical** | FraiseQL | Hasura |
| **Multiple data sources, complex logic** | Apollo Server | WunderGraph |
| **Rapid API for existing PostgreSQL** | Hasura | FraiseQL |
| **Flexible federation of services** | WunderGraph | Apollo Server |
| **Simple CRUD service** | Custom REST | Hasura |
| **Mobile app backend** | FraiseQL | Apollo Server |
| **Write logic in the database** | FraiseQL | Hasura |
| **Complex business logic, multi-source** | Apollo Server | WunderGraph |

---

## Related Topics

- **[Core Concepts](02-core-concepts.md):** the building blocks of a FraiseQL API
- **[Database-Centric Architecture](03-database-centric-architecture.md):** how reads and writes map to views and functions
- **[Design Principles](04-design-principles.md):** why FraiseQL makes these tradeoffs
- **[Performance Characteristics](12-performance-characteristics.md):** how FraiseQL stays fast
- **[Choosing FraiseQL](../guides/choosing-fraiseql.md):** a deeper fit-for-purpose guide
- **[Quickstart](../getting-started/quickstart.md):** build your first FraiseQL API

---

## Conclusion

FraiseQL is not the right tool for every job. It excels when:

1. **Your data is in PostgreSQL** (the single source of truth)
2. **You want fast, predictable reads** (view JSONB, no N+1)
3. **Your team values database expertise** (views and functions carry the logic)
4. **You prefer simplicity over flexibility** (minimal application code)

If your use case matches these criteria, FraiseQL gives you a fast, predictable GraphQL API with minimal code. If you need multi-source aggregation or extreme flexibility, other tools (Apollo Server, WunderGraph) may be better choices.

The key insight: **Different tools for different jobs. Choose based on your actual constraints, not hype.**

---
title: Understanding FraiseQL
description: Conceptual overview and mental models for FraiseQL
tags:
  - concepts
  - overview
  - mental-models
  - understanding
  - tutorial
---

# Understanding FraiseQL in 10 Minutes

## The Big Idea

FraiseQL is **database-first GraphQL**. Instead of starting with GraphQL types and then figuring out how to fetch data, you start with your database schema and let it drive your API design.

**Why this matters:** Most GraphQL APIs suffer from N+1 query problems, ORM overhead, and complex caching. FraiseQL eliminates these by composing data in PostgreSQL read tables/views, then serving it directly as JSONB.

## How It Works: The Request Journey

Every GraphQL request follows this path:

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   GraphQL   │───▶│   FastAPI   │───▶│ PostgreSQL  │───▶│    Rust     │
│   Query     │    │  Resolver   │    │   View      │    │ Transform   │
│             │    │             │    │             │    │             │
│ { users {   │    │ @query      │    │ SELECT      │    │ jsonb →     │
│   name      │    │ def users:  │    │ jsonb_build_│    │ GraphQL     │
│ } }         │    │   return db │    │ object(...) │    │ Response    │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

1. **GraphQL Query** arrives at your FastAPI server
2. **Python Resolver** calls a PostgreSQL view or function
3. **Database View** returns pre-composed JSONB data
4. **Rust Pipeline** transforms JSONB to GraphQL response

## Core Pattern: JSONB Views

The heart of FraiseQL is the **JSONB read pattern** with **trinity identifiers**:

```
┌─────────────┐      ┌─────────────────────────────┐      ┌─────────────────────────┐
│  tb_user    │  →   │   v_user                    │  →   │  GraphQL Response       │
│ (table)     │      │  (view)                     │      │                         │
│             │      │                             │      │                         │
│ pk_user: 1  │      │ SELECT jsonb_build_object(  │      │ {                       │
│ id: uuid    │      │  'id', id,                  │      │   "__typename": "user", │
│ name: Alice │      │  'name', name,              │      │   "id": "uuid",         │
│ email: a@b  │      │  'email', email             │      │   "name": "Alice",      │
│             │      │ )                           │      │   "email": "a@b"        │
│             │      │                             │      │  }                      │
└─────────────┘      └─────────────────────────────┘      └─────────────────────────┘
```

**Trinity Identifiers:** Every entity uses `pk_*` (int) for fast internal joins and `id` (uuid) for public API access. Your database tables store normalized data, but your read tables/views compose it into ready-to-serve JSONB objects.

### Why JSONB Views?

**The Problem:** Traditional GraphQL APIs have performance issues:

- N+1 queries when resolving nested relationships
- ORM overhead converting database rows to objects
- Complex caching strategies needed

**The Solution:** Pre-compose data in the database:

- Single query returns complete object graphs
- No ORM - direct JSONB output
- Database handles joins, aggregations, filtering
- Views are always fresh (no stale cache issues)

## Naming Conventions Explained

FraiseQL uses consistent naming to make patterns clear:

```
Database Objects:
├── tb_*    - Write Tables (normalized storage)
├── v_*     - Read Views (JSONB composition)
├── tv_*    - Projection Tables (denormalized JSONB cache)
└── fn_*    - Business Logic Functions (writes/updates)
```

### tb_* - Write Tables

Store your normalized data. These are regular PostgreSQL tables following the trinity identifier pattern.

**Example:** `tb_user`

See the [User table schema](../examples/canonical-examples.md#user-table) for a complete example with Trinity identifiers.

**When to use:** All data storage, relationships, constraints.

### v_* - Read Views

Compose data into JSONB objects for GraphQL queries. Views must return two columns: an `id` column for filtering and a `data` column containing the JSONB object.

**Example:** `v_user`

```sql
CREATE VIEW v_user AS
SELECT
    id,                          -- Required: enables WHERE id = $1 filtering
    jsonb_build_object(
        'id', id,                -- Required: every JSONB object must have id
        'name', name,
        'email', email,
        'created_at', created_at
    ) as data                    -- Required: contains the GraphQL response
FROM tb_user;
```

**Why two columns?**

- The `id` column enables efficient filtering: `SELECT data FROM v_user WHERE id = $1`
- The `data` column contains the complete JSONB object returned to GraphQL
- This pattern allows PostgreSQL to use indexes on the `id` column for fast lookups

**When to use:** Simple queries, real-time data, no heavy aggregations.

### tv_* - Table Views

Denormalized projection tables for complex data that can be efficiently updated and queried. Table views store JSONB in a `data` column but may include additional columns for efficient filtering. The `id` column (UUID) is exposed to GraphQL for filtering.

**Example:** `tv_user_stats`

```sql
CREATE TABLE tv_user_stats (
    id UUID PRIMARY KEY,                -- Required: GraphQL filtering uses UUID
    total_posts INT,                    -- For efficient filtering/sorting
    last_post_date TIMESTAMPTZ,         -- For efficient filtering/sorting
    data JSONB GENERATED ALWAYS AS (
        jsonb_build_object(
            'id', id,                   -- Required: every table view must have id
            'total_posts', total_posts,
            'last_post_date', last_post_date
        )
    ) STORED
);
```

**When to use:** Complex nested data, performance-critical reads, analytics with embedded relations.

### fn_* - Business Logic Functions

Handle writes, updates, and complex business logic.

**Example:** See [canonical fn_create_user()](../examples/canonical-examples.md#create-user-function) for a complete implementation.

**When to use:** All write operations, validation, business rules.

## Trinity Identifiers

FraiseQL uses **three types of identifiers** per entity for different purposes:

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│    pk_*     │  │     id      │  │ identifier  │
│ (internal)  │  │  (public)   │  │   (human)   │
├─────────────┤  ┌─────────────┤  ┌─────────────┤
│ Fast joins  │  │ API access  │  │ SEO/URLs    │
│ Never shown │  │ UUID        │  │ Readable    │
│ Auto-inc    │  │ External    │  │ Nullable    │
└─────────────┘  └─────────────┘  └─────────────┘
```

- **pk_***: Internal primary keys for fast database joins (never exposed in API)
- **id**: Public UUID identifiers for GraphQL queries and external references
- **identifier**: Human-readable slugs for URLs and user interfaces (nullable)

## The CQRS Pattern

FraiseQL implements **Command Query Responsibility Segregation**:

```
┌─────────────────────────────────────┐
│         GraphQL API                 │
├──────────────────┬──────────────────┤
│   QUERIES        │   MUTATIONS      │
│   (Reads)        │   (Writes)       │
├──────────────────┼──────────────────┤
│  v_* views       │  fn_* functions  │
│  tv_* tables     │  tb_* tables     │
└──────────────────┴──────────────────┘
```

**Queries** (reads) use read-optimized tables/views for fast, fresh data.
**Mutations** (writes) use functions for business logic and data integrity.

## Development Workflow

Here's how you build with FraiseQL:

```
1. Design Domain          2. Create Tables          3. Create Read Tables/Views
   What data?             (tb_* tables)             (tv_* tables or v_* views)
   What relationships?                              JSONB composition

4. Define Types           5. Write Resolvers        6. Test API
   Python classes         @query/@mutation          GraphQL queries
   Match view structure   Call views/functions      Verify responses
```

### Step-by-Step Example

**Goal:** Build a user management API

1. **Design:** Users have name, email, posts
2. **Tables:** `tb_user`, `tb_post` with foreign keys
3. **Views:** `v_user` (single user), `v_users` (list with post counts)
4. **Types:** `User` class matching `v_user` JSONB structure
5. **Resolvers:** `@query def user(id): return db.v_user(id)`
6. **Test:** Query `{ user(id: "123") { name email } }`

## Performance Patterns

Different query patterns optimized for different use cases:

**Performance Decision Tree:**

```
Need fast response?
├── Yes → Use tv_* projection table (0.05ms)
└── No  → Need fresh data?
    ├── Yes → Use v_* view (real-time)
    └── No  → Use tv_* projection table (denormalized)
```

**Response Time Comparison:**

```
Query Type      | Response Time | Use Case
───────────────────|──────────────|─────────────────────
tv_* projection    | 0.05-0.5ms   | Dashboard, analytics
v_* view           | 1-5ms        | Real-time data
Complex JOIN    | 50-200ms     | Traditional ORM
```

## When to Use What

Decision tree for choosing patterns:

```
Need to read data?
├── Simple query, real-time data → v_* view
├── Complex nested data → tv_* projection table
└── Performance-critical analytics → tv_* projection table
```

## Next Steps

Now that you understand the patterns:

- **[5-Minute Quickstart](../getting-started/quickstart.md)** - Get a working API immediately
- **[First Hour Guide](../getting-started/first-hour.md)** - Progressive tutorial from zero to production
- **[Core Concepts](../core/concepts-glossary.md)** - Deep dive into each pattern
- **[Quick Reference](../reference/quick-reference.md)** - Complete cheatsheet and examples

**Ready to code?** Start with the [quickstart](../getting-started/quickstart.md) to see it in action.

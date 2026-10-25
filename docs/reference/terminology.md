# FraiseQL Terminology Guide

**Last Updated:** 2025-12-30

This guide defines canonical terminology used throughout FraiseQL documentation to ensure consistency and clarity.

---

## Quick Reference

| Term | Use When | Example | Avoid |
|------|----------|---------|-------|
| **PostgreSQL function** | Technical docs, API references | `fn_create_user()` | "database function", "DB function" |
| **SQL function** | Code comments, casual mentions | `-- SQL function for user creation` | In formal docs |
| **JSONB view** | FraiseQL-specific views | `v_user`, `v_post` | Generic "view" |
| **PostgreSQL view** | Generic database views | Any `CREATE VIEW` | When discussing JSONB pattern specifically |
| **Projection table** | Performance optimization tables | `tv_user_cached` | "table view", "materialized projection" |
| **Rust pipeline** | Architecture explanations | PostgreSQL → Rust → HTTP | "Rust extension" (in user docs) |
| **fraiseql_rs** | Code/technical references | `from fraiseql import fraiseql_rs` | In user-facing docs |
| **Trinity pattern** | Architectural pattern | Three-identifier design | "three-tier ID system" |
| **Trinity identifiers** | The three ID fields | pk_*, id, identifier | "Trinity IDs" |
| **CQRS** | After first definition | Read/write separation | Spell out repeatedly |

---

## Database Terminology

### PostgreSQL Functions

**Primary term:** "PostgreSQL function"

**When to use:**

- Formal documentation
- API references
- Technical explanations
- Mutation descriptions

**Acceptable alternatives:**

- "SQL function" (in code comments, casual use)
- "Database function" (only when PostgreSQL is clear from context)

**Avoid:**

- "DB function" (too informal)
- "Function" alone (ambiguous - Python vs SQL)

**Examples:**

✅ **CORRECT:**

```markdown
Mutations call PostgreSQL functions for business logic:

CREATE OR REPLACE FUNCTION fn_create_user(...) RETURNS JSONB AS $$
```

⚠️ **ACCEPTABLE (casual context):**

```python
# Call SQL function to create user
result = await db.execute_function("fn_create_user", {...})
```

❌ **AVOID:**

```markdown
Create a database function to handle the mutation.
```

**Why:** "PostgreSQL function" is precise and differentiates from Python functions, AWS Lambda functions, etc.

---

### Views and Tables

#### JSONB View

**Primary term:** "JSONB view"

**When to use:**

- Describing FraiseQL's view pattern
- Views that return JSONB in `data` column
- Most GraphQL type mappings

**Pattern:**

```sql
CREATE VIEW v_user AS
SELECT
    id,
    jsonb_build_object(
        'id', id,
        'name', name
    ) as data
FROM tb_user;
```

**Why JSONB view:**

- Distinguishes FraiseQL's specific pattern
- Differentiates from generic PostgreSQL views
- Highlights that JSONB is pre-composed for GraphQL

#### PostgreSQL View

**Primary term:** "PostgreSQL view"

**When to use:**

- Generic database view discussions
- When not using JSONB pattern
- Comparing with other databases

**Example:**

```markdown
FraiseQL uses PostgreSQL views for read optimization, but specifically
uses the JSONB view pattern for GraphQL types.
```

#### Projection Table

**Primary term:** "Projection table" (with `tv_*` notation)

**When to use:**

- Regular tables storing cached JSONB
- Performance optimization discussions
- Comparing with views

**Avoid:**

- "Table view" (confusing - is it a table or view?)
- "Materialized projection" (too verbose)
- "Cached table" (doesn't convey JSONB nature)

**Pattern:**

```sql
CREATE TABLE tv_user (
    id UUID PRIMARY KEY,
    data JSONB NOT NULL,  -- Cached from v_user
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Key distinction:**

| Type | What It Is | Storage | Performance |
|------|-----------|---------|-------------|
| **JSONB view (`v_*`)** | Virtual view | None | 5-10ms |
| **Projection table (`tv_*`)** | Physical table with cached JSONB | 1.5-2x data | 0.05-0.5ms |
| **Materialized view** | PostgreSQL MATERIALIZED VIEW | 1x data | 0.1-1ms |

#### Materialized View

**Primary term:** "Materialized view" (PostgreSQL's `CREATE MATERIALIZED VIEW`)

**When to use:**

- Pre-computed aggregations
- PostgreSQL-native materialized views
- Rarely used in FraiseQL (projection tables preferred)

**Why rare in FraiseQL:**

- Projection tables (`tv_*`) offer more control
- Explicit sync functions vs `REFRESH MATERIALIZED VIEW`
- Better integration with mutation pipeline

---

## Architecture Terminology

### Rust Pipeline

**Primary term:** "Rust pipeline"

**When to use:**

- Architecture explanations
- User-facing documentation
- Performance discussions
- "How FraiseQL works" sections

**Example:**

```markdown
FraiseQL's Rust pipeline transforms PostgreSQL JSONB to HTTP responses
7-10x faster than Python serialization.
```

**Avoid in user docs:**

- "Rust extension" (too technical)
- "fraiseql_rs module" (implementation detail)
- "Rust layer" (vague)

**Use in technical docs:**

- "fraiseql_rs" (when discussing code/implementation)

#### fraiseql_rs

**Primary term:** "fraiseql_rs"

**When to use:**

- Code examples with imports
- Technical/developer documentation
- Contributing guides
- Source code references

The extension ships inside the `fraiseql` package; there is no top-level `fraiseql_rs`
module to import.

**Example:**

```python
from fraiseql import fraiseql_rs

fraiseql_rs.transform_json('{"user_name": "John"}')  # '{"userName":"John"}'
```

**Avoid in user docs:**

- Don't expose internal module structure
- Use "Rust pipeline" instead

---

### Trinity Pattern and Identifiers

#### Trinity Pattern

**Primary term:** "Trinity pattern"

**When to use:**

- Describing the architectural pattern
- High-level explanations
- Design discussions

**Definition:**
The architectural pattern of using three identifier types per entity:

1. `pk_*` (integer primary key - internal)
2. `id` (UUID - public API)
3. `identifier` (text slug - human-readable)

**Example:**

```markdown
FraiseQL uses the Trinity pattern to optimize both performance
and security.
```

#### Trinity Identifiers

**Primary term:** "Trinity identifiers"

**When to use:**

- Referring to the three specific ID fields
- SQL schema examples
- Field-level discussions

**Example:**

```sql
CREATE TABLE tb_user (
    pk_user INT PRIMARY KEY,      -- Trinity identifiers:
    id UUID UNIQUE NOT NULL,       -- 1. Internal (pk_*)
    identifier TEXT UNIQUE,        -- 2. Public (id)
                                   -- 3. Human-readable (identifier)
    name TEXT
);
```

**Avoid:**

- "Trinity IDs" (too casual)
- "Three-tier ID system" (confusing with application tiers)
- "Triple identifier pattern" (not established term)

**Summary table:**

| Identifier | Type | Purpose | Exposed in GraphQL? | Use Case |
|-----------|------|---------|---------------------|----------|
| `pk_*` | Integer | PostgreSQL JOINs | ❌ Never | Database performance |
| `id` | UUID | Public API identifier | ✅ Always | GraphQL queries, external APIs |
| `identifier` | Text | Human-readable slug | ✅ Optional | SEO-friendly URLs |

---

### CQRS

**Primary term:** "CQRS"

**First mention:** "CQRS (Command Query Responsibility Segregation)"

**Subsequent mentions:** "CQRS" (acronym only)

**When to use:**

- Architecture discussions
- After defining on first use in document
- Well-established pattern (no need to spell out repeatedly)

**Example:**

✅ **CORRECT:**

```markdown
FraiseQL follows CQRS (Command Query Responsibility Segregation)
principles, separating read paths (queries) from write paths (mutations).

The CQRS architecture allows independent optimization of reads and writes.
```

❌ **AVOID (too verbose):**

```markdown
FraiseQL follows Command Query Responsibility Segregation (CQRS).
The Command Query Responsibility Segregation pattern allows...
```

**Always link to definition:**

```markdown
FraiseQL follows [CQRS](../core/concepts-glossary.md#cqrs) principles...
```

---

## GraphQL Terminology

### Type

**Primary term:** "GraphQL type"

**When to use:**

- Distinguishing from Python types, database types
- GraphQL schema discussions

**Avoid:**

- "Type" alone (ambiguous - Python, SQL, or GraphQL?)

**Example:**

```markdown
The @fraiseql.type decorator maps a Python class to a GraphQL type.
```

### Field

**Primary term:** "GraphQL field" (when context needs clarification)

**Acceptable:** "field" (when GraphQL context is clear)

**Avoid confusing with:**

- "Column" (database term)
- "Attribute" (Python term)
- "Property" (Python term)

### Resolver

**Primary term:** "resolver"

**Use when:**

- Discussing GraphQL field resolution
- Query/mutation execution
- Custom field logic

**Example:**

```markdown
The resolver fetches data from the database and returns it to GraphQL.
```

### Mutation

**Primary term:** "mutation" or "GraphQL mutation"

**Use "GraphQL mutation" when:**

- Distinguishing from database mutations (INSERT/UPDATE/DELETE)
- Clarifying context

**Example:**

```markdown
GraphQL mutations call PostgreSQL functions for business logic.

The mutation validates input and calls fn_create_user().
```

---

## Feature-Specific Terminology

### Auto-Inference

**Primary term:** "auto-inference"

**What it means:**
Automatic detection/generation by FraiseQL:

- Field names: `created_at` → `createdAt`
- View names: `User` type → `v_user` view
- Success fields: Automatic `success`, `message`, `data`, `timestamp`

**Always link to:**

```markdown
FraiseQL's [auto-inference](../core/auto-inference.md) reduces boilerplate...
```

### Cascade

**Primary term:** "Cascade" or "GraphQL Cascade"

**What it means:**
FraiseQL's automatic cache invalidation based on data relationships.

**Avoid:**

- "CASCADE" (all caps - confuses with SQL CASCADE DELETE)
- "Cascade feature" (redundant)

**Example:**

```markdown
Enable Cascade for automatic cache invalidation:

mutation {
  createPost(input: {...}) {
    success {
      post { id }
      _cascade { invalidations }  # Cascade metadata
    }
  }
}
```

---

## Comparison Tables

### View Types Quick Reference

| Type | Definition | Performance | Use Case | Storage Overhead |
|------|-----------|-------------|----------|------------------|
| **JSONB view (`v_*`)** | `CREATE VIEW` with JSONB | 5-10ms | Standard queries | None (virtual) |
| **Projection table (`tv_*`)** | `CREATE TABLE` with cached JSONB | 0.05-0.5ms | Ultra-high read:write | 1.5-2x |
| **Materialized view** | `CREATE MATERIALIZED VIEW` | 0.1-1ms | Aggregations | 1x |
| **Standard table (`tb_*`)** | `CREATE TABLE` (normalized) | N/A | Write targets | 1x |

### Identifier Types Quick Reference

| Identifier | PostgreSQL Type | GraphQL Type | Exposed? | Purpose |
|-----------|----------------|--------------|----------|---------|
| `pk_*` | `INT` | Not exposed | ❌ Never | Database JOINs (fast) |
| `id` | `UUID` | `UUID!` | ✅ Always | Public API (stable) |
| `identifier` | `TEXT` | `String` | ✅ Optional | Human-readable (SEO) |

### Function Types Quick Reference

| Term | What It Is | Example |
|------|-----------|---------|
| **PostgreSQL function** | SQL function in database | `fn_create_user()` |
| **Python function** | Python function/method | `async def create_user()` |
| **Resolver** | GraphQL field resolver | Field execution function |
| **Mutation resolver** | GraphQL mutation handler | Mutation execution function |

---

## When to Define Terms

### Always Define on First Use

For less common terms:

- Projection tables
- Trinity pattern
- APQ (Automatic Persisted Queries)
- Dataloader

**Example:**

```markdown
FraiseQL supports projection tables (regular tables storing cached JSONB
for ultra-fast reads) for high-performance use cases.
```

### No Need to Define (Well-Established)

For common terms:

- CQRS (define once per doc)
- GraphQL (assume knowledge)
- PostgreSQL (assume knowledge)
- UUID (standard term)

---

## Common Mistakes

### ❌ Inconsistent Term Usage

**WRONG:**

```markdown
Create a database function...
Later: The PostgreSQL function should return JSONB...
Later: The SQL function validates input...
```

**CORRECT:**

```markdown
Create a PostgreSQL function...
The PostgreSQL function should return JSONB...
The function validates input... (or "SQL function" if casual)
```

### ❌ Ambiguous "View" Usage

**WRONG:**

```markdown
Create a view for the User type...
(Is it JSONB view? Materialized view? Regular view?)
```

**CORRECT:**

```markdown
Create a JSONB view for the User type:

CREATE VIEW v_user AS
SELECT id, jsonb_build_object(...) as data FROM tb_user;
```

### ❌ Using Technical Terms in User Docs

**WRONG (in getting-started docs):**

```markdown
The fraiseql_rs module transforms JSONB...
```

**CORRECT:**

```markdown
FraiseQL's Rust pipeline transforms JSONB 7-10x faster than Python...
```

---

## Style Guidelines

### Capitalization

| Term | Capitalization | Example |
|------|---------------|---------|
| FraiseQL | Always capital F, QL | FraiseQL is a framework... |
| PostgreSQL | Always capital P, SQL | PostgreSQL function |
| GraphQL | Always capital G, QL | GraphQL mutation |
| CQRS | Always uppercase | CQRS architecture |
| UUID | Always uppercase | UUID identifier |
| JSONB | Always uppercase | JSONB view |
| Rust | Capital R | Rust pipeline |
| Python | Capital P | Python types |

### Code Formatting

**Function names:** Use code formatting

```markdown
Call the `fn_create_user()` function...
```

**View names:** Use code formatting

```markdown
Query the `v_user` view...
```

**Column names:** Use code formatting

```markdown
The `data` column contains JSONB...
```

---

## Cross-Reference Links

When mentioning these concepts, always link to canonical definitions:

| Concept | Link To |
|---------|---------|
| CQRS | `[CQRS](../core/concepts-glossary.md#cqrs)` |
| Trinity Pattern | `[Trinity pattern](../core/concepts-glossary.md#trinity-identifiers)` |
| JSONB View Pattern | `[JSONB view](../core/concepts-glossary.md#jsonb-view-pattern)` |
| Projection Tables | `[Projection tables](../core/concepts-glossary.md#projection-tables-tv_)` |
| Auto-Inference | `[Auto-inference](../core/auto-inference.md)` |
| Rust Pipeline | `[Rust pipeline](../performance/rust-pipeline-optimization.md)` |
| Cascade | `[Cascade](../features/graphql-cascade.md)` |

---

## See Also

- [Core Concepts & Glossary](../core/concepts-glossary.md) - Detailed concept explanations
- [Quick Reference](quick-reference.md) - Common code patterns
- [API Reference](database.md) - Complete API documentation

---

**Maintained by:** FraiseQL documentation team
**Questions?** Open an issue or discussion on GitHub

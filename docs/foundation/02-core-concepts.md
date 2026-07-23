---
title: Core Concepts & Terminology
description: The vocabulary and mental models that underpin FraiseQL. This topic defines the core concepts that appear throughout the documentation and helps you build the right mental model for how the framework works at runtime.
keywords: ["graphql", "postgresql", "runtime-schema", "database-centric", "architecture"]
tags: ["documentation", "reference"]
---

# Core Concepts & Terminology

**Audience:** All users (developers, architects, operations)
**Reading Time:** 15-20 minutes

---

## Overview

Before diving into FraiseQL's architecture and capabilities, you need to understand the vocabulary and mental models that underpin the system. This topic defines core concepts that appear throughout FraiseQL documentation and helps you develop the right mental model for how FraiseQL works.

**Key insight:** FraiseQL uses database-native vocabulary, not application code vocabulary. This is intentional and reflects its philosophy: databases are the source of truth, not an afterthought.

FraiseQL is a **runtime GraphQL framework for PostgreSQL**. You author types, queries, and mutations as decorated Python; the GraphQL schema is assembled in memory at application startup and served over FastAPI. There is no build step and no compiled artifact.

---

## Part 1: Core Terminology

### Schema

**Definition:** A complete specification of your API's structure, including all types, fields, relationships, and validation rules.

In FraiseQL, a schema is authored once in Python and defines:

- What types exist (User, Order, Product, etc.)
- What fields each type has (name, email, created_at, etc.)
- What relationships exist (User has many Orders)
- How queries and mutations work (what data can be read/written)
- Authorization rules (who can access what)

```python
import fraiseql
from fraiseql.types import ID

# Schema definition (Python)
@fraiseql.type(sql_source="v_user")
class User:
    """User in the system"""
    id: ID                    # Field: public UUID identifier
    name: str                 # Field: text name
    email: str                # Field: email address
    orders: list[Order]       # Relationship: one user has many orders
    is_active: bool           # Field: boolean flag
    created_at: str           # Field: timestamp
```

**Mental model:** Schema is a *contract* between your client and server. It says "these are the exact types, fields, and relationships available to query."

---

### Type

**Definition:** A definition of a data object with named fields of specific data types.

FraiseQL has several type categories:

**1. Object Types** - Represent entities in your domain

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    name: str
    email: str

@fraiseql.type(sql_source="v_order")
class Order:
    id: ID
    total: float
    created_at: str
```

**2. Scalar Types** - Basic values (strings, numbers, dates, etc.)

```text
String        → text (name, email, description)
Int           → whole numbers (quantity)
Float         → decimal numbers (price, rating)
Boolean       → true/false (is_active, has_shipped)
DateTime      → timestamps (created_at, updated_at)
Date          → just dates (birthday, due_date)
ID            → public UUID identifiers
JSON          → arbitrary data (metadata, config)
EmailAddress  → validated email strings
```

FraiseQL ships these scalars from `fraiseql.types`: `ID`, `Date`, `DateTime`, `EmailAddress`, `JSON`, `LTree`, plus many domain-specific scalars.

**3. Enum Types** - Limited set of named values

```python
import fraiseql

@fraiseql.enum
class OrderStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
```

**4. Interface Types** - Shared fields across multiple types (advanced)

**5. Union Types** - "One of these types" (advanced)

**Mental model:** Types are *blueprints*. Just like a database view defines the columns and their types, a GraphQL type defines the fields and their types.

---

### Field

**Definition:** A named value within a type, with a specific data type and optional validation rules.

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_product")
class Product:
    id: ID                   # Field name: id, type: ID
    name: str                # Field name: name, type: String
    price: float             # Field name: price, type: Float
    in_stock: bool           # Field name: in_stock, type: Boolean
    created_at: str          # Field name: created_at, type: DateTime
```

**Field modifiers:**

```python
# Required (must always have a value)
name: str                    # Required - cannot be null

# Optional (can be null/absent)
middle_name: str | None      # Optional - can be null
```

**Mental model:** Fields are *columns in a database view*. Each field has a name, type, and nullability.

---

### Query

**Definition:** A read operation that retrieves data from the system without modifying it.

```graphql
# A query is a request for data
query GetUser {
  user(id: "00000000-0000-0000-0000-000000000001") {
    id
    name
    email
  }
}
```

**How it works in FraiseQL:**

1. The query arrives at the FastAPI GraphQL endpoint.
2. The query resolver — registered with `@fraiseql.query` — runs.
3. It reads from a `v_`/`tv_` view through the repository, e.g. `await db.find_one("v_user", id=id)`.
4. PostgreSQL returns the view's `data` JSONB.
5. FraiseQL shapes the result to exactly the GraphQL fields the client requested.

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.query
async def user(info, id: ID) -> User | None:
    db = info.context["db"]
    return await db.find_one("v_user", id=id)

@fraiseql.query
async def users(info) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user")
```

**Mental model:** A query is a *SELECT statement*. It specifies what data you want and returns results without modifying the database.

---

### Mutation

**Definition:** A write operation that modifies data (creates, updates, or deletes).

```graphql
# A mutation modifies data
mutation CreateUser {
  createUser(input: {
    name: "Ada"
    email: "ada@example.com"
  }) {
    ... on CreateUserSuccess {
      user { id name email }
    }
    ... on CreateUserError {
      message
      code
    }
  }
}
```

**How it works in FraiseQL:**

1. The mutation arrives at the FastAPI GraphQL endpoint.
2. Authorization is checked (can this user perform this write?).
3. Input arguments are validated and coerced against the GraphQL types.
4. The mutation resolver calls a PostgreSQL `fn_` function through the repository, e.g. `await db.execute_function("fn_create_user", {...})`.
5. The function performs validation plus the write inside the database and returns JSONB indicating success or failure.
6. FraiseQL returns the success or error payload to the client.

```python
import fraiseql

@fraiseql.mutation
async def create_user(info, input: CreateUserInput) -> CreateUserSuccess | CreateUserError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_create_user",
        {"name": input.name, "email": input.email},
    )
    if not result.get("success"):
        return CreateUserError(message=result.get("message", "failed"))
    return CreateUserSuccess(user=User(**result["user"]))
```

**Mental model:** A mutation is an *INSERT, UPDATE, or DELETE* — but in FraiseQL the DML lives inside a PostgreSQL function. The function modifies the database and returns the result.

---

### Resolver

**Definition:** Logic that determines what data to return for a field or operation.

In traditional GraphQL servers, resolvers are *custom code* you write by hand for every field:

```python
# Traditional GraphQL - hand-written resolver
async def user_resolver(parent, info, id):
    return await db.fetchrow("SELECT * FROM users WHERE id = $1", id)
```

In FraiseQL, you write resolvers for **operations** (`@fraiseql.query` / `@fraiseql.mutation`), and FraiseQL generates the per-field resolvers automatically at runtime when the schema is built. Field resolvers read straight from the view's `data` JSONB, so you do not write glue code per field:

```python
import fraiseql
from fraiseql.types import ID

# Field resolvers are generated when the schema is built at startup
@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    name: str
    email: str
    # FraiseQL reads each field from the `data` JSONB of v_user
```

**Mental model:** A resolver is the *glue between GraphQL and the database*. In FraiseQL, the field-level glue is generated at startup from your decorated types — you only hand-write the query and mutation entry points.

---

### Relationship

**Definition:** A connection between two types, representing how data relates.

**One-to-Many** (User has many Orders):

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    name: str
    orders: list[Order]  # One user → many orders

@fraiseql.type(sql_source="v_order")
class Order:
    id: ID
    total: float
```

**Many-to-One** (Order belongs to User):

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_order")
class Order:
    id: ID
    total: float
    user: User           # Many orders → one user
```

**Many-to-Many** (Students enroll in Courses):

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_student")
class Student:
    id: ID
    name: str
    courses: list[Course]  # Many students → many courses

@fraiseql.type(sql_source="v_course")
class Course:
    id: ID
    name: str
    students: list[Student]  # Many courses → many students
```

**Self-Relationships** (Employee has manager):

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_employee")
class Employee:
    id: ID
    name: str
    manager: Employee | None  # Self-relationship
    reports: list[Employee]   # Reverse relationship
```

**Mental model:** Relationships are *foreign keys in databases*. They connect tables and define how data relates. The read views compose related data into the `data` JSONB so nested fields are served without N+1 round-trips.

---

## Part 2: Mental Models

### Mental Model 1: "Schemas Describe Your API Contract"

A schema is a contract between client and server:

**The contract says:**

- These types exist (User, Order, Product)
- These fields are available (name, email, created_at)
- These relationships exist (User has Orders)
- These queries are available (getUser, searchProducts)
- These mutations are available (createOrder, updateUser)
- These authorization rules apply (only admins can delete users)

**The client can trust:**

- Fields won't disappear (backward compatibility)
- Fields won't change type (type safety)
- Authorization will be enforced (security)

**The server guarantees:**

- Query results match the schema (type safety)
- No N+1 queries (performance)
- Consistent performance (deterministic)

**Mental model:** Think of schema as *REST API documentation on steroids*. It's not just documentation; it's enforced by the system.

---

### Mental Model 2: "Types Map to Database Tables"

In FraiseQL, types correspond to database structures — you read from a view and write through tables and functions:

```python
import fraiseql
from fraiseql.types import ID

# GraphQL Type, backed by a read view
@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    name: str
    email: str

# Backed by a write table + read view
# CREATE TABLE tb_user (
#     pk_user BIGINT PRIMARY KEY,   -- internal, never exposed
#     id      UUID NOT NULL,        -- public id
#     name    VARCHAR(255),
#     email   VARCHAR(255)
# );
#
# CREATE VIEW v_user AS
# SELECT id, jsonb_build_object('id', id, 'name', name, 'email', email) AS data
# FROM tb_user WHERE deleted_at IS NULL;
```

**Why this matters:**

| Aspect | Implication |
|--------|-------------|
| **Write tables** | Prefix with `tb_` (normalized, source of truth) |
| **Read views** | Prefix with `v_` (expose a `data` JSONB column) |
| **Column names** | Use snake_case (SQL convention) |
| **Internal keys** | `pk_*` / `fk_*` BIGINT keys — never exposed |
| **Public id** | `id` UUID column becomes the GraphQL `id` |
| **Relationships** | Composed into the view's `data` JSONB |

**Mental model:** Your Python schema is *metadata about your database*. The database is the source of truth; the schema describes it.

---

### Mental Model 3: "Queries Map to SELECT Statements"

Every GraphQL query reads from a PostgreSQL view via a SELECT statement:

```graphql
# GraphQL Query
query GetUser {
  user(id: "00000000-0000-0000-0000-000000000001") {
    id
    name
    orders {
      id
      total
    }
  }
}
```

Reads from the `v_user` view, whose `data` JSONB already composes the nested orders:

```sql
-- Read path (simplified)
SELECT data
FROM v_user
WHERE id = $1;
```

**Why this matters:**

- You can predict query performance (look at the view's SQL)
- Complex shapes are composed in the database (JSONB, JOINs, indexes)
- No application-level N+1 queries (the view does the composition)
- You understand the data flow (no hidden per-field round-trips)

**Mental model:** Think of GraphQL queries as *SELECT statements against read views*. The database composes the result; FraiseQL shapes it to the requested fields.

---

### Mental Model 4: "Mutations Map to DML Statements"

GraphQL mutations perform INSERT, UPDATE, or DELETE — encapsulated in a PostgreSQL function:

```graphql
# GraphQL Mutation
mutation CreateOrder {
  createOrder(input: {
    userId: "00000000-0000-0000-0000-000000000001"
    total: 99.99
  }) {
    ... on CreateOrderSuccess {
      order { id status createdAt }
    }
    ... on CreateOrderError {
      message
    }
  }
}
```

Calls a `fn_` function that does the DML and returns a result:

```sql
-- Inside fn_create_order (simplified)
INSERT INTO tb_order (fk_user, id, total, created_at)
VALUES ($1, gen_random_uuid(), $2, CURRENT_TIMESTAMP)
RETURNING id, status, created_at;
```

**Why this matters:**

- Mutations are database transactions (ACID guarantees)
- Validation happens inside the function (prevent bad data)
- Authorization is checked before the function runs (security)
- Results are consistent (the function returns the actual values)

**Mental model:** Mutations are *transactional database operations* implemented as PostgreSQL functions, not application logic.

---

### Mental Model 5: "The Schema Is Built Once at Startup, Then Served"

FraiseQL is a runtime framework — there is no compile step and no build artifact. Instead it separates **schema construction** (at app startup) from **request handling** (per request):

**At app startup:**

```text
Decorated Python (@fraiseql.type / @query / @mutation)
                        ↓
        build_fraiseql_schema / create_fraiseql_app
                        ↓
        GraphQL schema assembled in memory (graphql-core)
```

When the schema is built:

- ✅ Types and fields are validated for structural correctness
- ✅ Relationships are wired into the type system
- ✅ Field resolvers are generated
- ✅ The schema is held in memory — no file is written

**Per request (runtime):**

```text
GraphQL Query → resolver → db.find / execute_function → PostgreSQL → results
```

Per request:

- ✅ The query is validated against the in-memory schema
- ✅ Authorization is verified
- ✅ Arguments are validated and coerced
- ✅ A read view is queried, or a write function is called
- ✅ Results are shaped to the requested fields

**Why this matters:**

- Structural errors surface when the schema builds at startup
- Authorization, validation, and constraints run per request
- No artifact to manage or keep in sync — the running process is the schema

**Mental model:** *Building the schema is for structural correctness; each request is for authorization, validation, and execution.* The optional `fraiseql_rs` Rust extension only accelerates JSON shaping on the read path — it is not a separate stage.

---

## Part 3: Database-Centric Design

### Core Principle: The Database is the Source of Truth

Traditional application architecture:

```text
Client → Application Code → ORM → Database
                    ↑
         (custom resolvers, business logic, caching)
```

FraiseQL architecture:

```text
Client → FraiseQL resolvers → v_ views (read) / fn_ functions (write) → PostgreSQL
         (thin runtime; logic lives in the database)
```

**Why this matters:**

| Aspect | Traditional | FraiseQL |
|--------|-------------|----------|
| **Where logic lives** | Application code | Database (views + functions) |
| **Consistency** | Depends on code quality | Database enforces rules |
| **Debugging** | "Why is resolver slow?" | Look at the SQL query plan |
| **Performance** | Application bottleneck | Database determines speed |
| **Data integrity** | Application validation | Database constraints |

---

### View vs Table vs Relationship

FraiseQL relies on a clear split between write tables and read views:

**Write Tables** (`tb_*` prefix):

```sql
CREATE TABLE tb_user (
    pk_user BIGINT PRIMARY KEY,   -- internal, never exposed
    id      UUID NOT NULL,        -- public id
    name    VARCHAR(255),
    email   VARCHAR(255),
    created_at TIMESTAMP
);
```

→ Normalized, DBA-owned, source of truth. Never exposed directly to GraphQL.

**Read Views** (`v_*` prefix):

```sql
CREATE VIEW v_user AS
SELECT
    id,
    jsonb_build_object(
        'id', id,
        'name', name,
        'email', email,
        'createdAt', created_at
    ) AS data
FROM tb_user
WHERE deleted_at IS NULL;  -- Soft deletes
```

→ Curated for GraphQL. Each read view carries an `id` column (for `WHERE id = $1`) plus a `data` JSONB column built with `jsonb_build_object(...)`. Never put `pk_*` inside `data`.

**Table-Backed Projection Views** (`tv_*` prefix):

```sql
-- A real table holding pre-composed JSONB, refreshed by functions/triggers.
-- Used for heavy nested reads where computing the JSONB on the fly is too costly.
CREATE TABLE tv_user (
    id   UUID PRIMARY KEY,
    data JSONB NOT NULL
);
```

→ A read projection — queried exactly like a `v_` view, but materialized for performance. It is **not** a write path; mutations still go through `fn_` functions.

**Mental model:** Views are *application-facing read interfaces* to database tables. Tables are DBA-owned and normalized; views (`v_` logical, `tv_` materialized) are curated for read access; functions (`fn_`) own all writes.

---

## Part 4: Schema Construction vs Request Handling

### Schema Construction (App Startup)

**What happens:**

```text
Decorated Python types, queries, mutations
    ↓
build_fraiseql_schema / create_fraiseql_app
    ↓
Type registry assembled (types mapped to their sql_source views)
    ↓
Field resolvers generated
    ↓
graphql-core schema held in memory
```

**What is validated when the schema builds:**

- Field types resolve to known GraphQL types
- Relationships reference existing types
- Query/mutation signatures are well-formed
- Result/success/error unions are consistent

**Example - surfaced at startup:**

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    profile: MissingType   # Building the schema fails: MissingType is not a registered type
```

---

### Request Handling (Runtime)

**What happens:**

```text
GraphQL Query / Mutation
    ↓
Validate against the in-memory schema
    ↓
Authorize (check permissions)
    ↓
Validate & coerce arguments
    ↓
Read: db.find on a v_ view    |    Write: db.execute_function on a fn_ function
    ↓
Shape results to requested fields
    ↓
Response (send to client)
```

**What is checked per request:**

- ✅ Authorization (does the user have permission?)
- ✅ Argument validation (is the id a valid UUID?)
- ✅ Constraint checks (unique violation, foreign key, etc., raised by PostgreSQL)
- ✅ Business logic (implemented inside the `fn_` functions)

**Example - checked per request:**

```graphql
# Runtime check: does the user have permission?
query GetUser {
  user(id: "00000000-0000-0000-0000-000000000123") {
    name
  }
}

# Error (if unauthorized): "Not authorized to view this user"
```

---

### Comparison: Startup vs Request

| Check | When | What | Who Decides |
|-------|------|------|-------------|
| **Type check** | Startup | Does the field exist? | Schema |
| **Type match** | Startup | Is the type known? | Schema |
| **Relationship** | Startup | Is the related type registered? | Schema |
| **Authorization** | Request | Can the user access this? | Application |
| **Validation** | Request | Is the value valid? | Application + PostgreSQL |
| **Constraint** | Request | Does the database allow it? | PostgreSQL |

**Mental model:** *Schema construction catches structural errors; request handling enforces authorization, validation, and constraints.*

---

## Summary: The FraiseQL Mental Model

```text
┌─────────────────────────────────────────────────────┐
│ Your Business Domain                                │
│ (E-commerce, SaaS, Data Platform, etc.)             │
└────────────────┬────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────┐
│ PostgreSQL Database (Source of Truth)               │
│ - tb_* tables (normalized, write)                   │
│ - v_* / tv_* views (curated, read; data JSONB)      │
│ - fn_* functions (write business logic)             │
└────────────────┬────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────┐
│ FraiseQL Decorators (Python)                        │
│ @fraiseql.type / @fraiseql.query / @fraiseql.mutation│
│ - Types map to read views (sql_source="v_x")        │
│ - Queries read from v_/tv_ views                    │
│ - Mutations call fn_ functions                      │
└────────────────┬────────────────────────────────────┘
                 │
      (SCHEMA BUILT AT STARTUP — in memory)
   build_fraiseql_schema / create_fraiseql_app
                 │
┌────────────────▼────────────────────────────────────┐
│ FastAPI GraphQL Server (Runtime Execution)          │
│ - Validates queries against the in-memory schema    │
│ - Checks authorization                              │
│ - Reads views / calls functions                     │
│ - Shapes and returns results                        │
└────────────────┬────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────┐
│ Client Application                                  │
│ - Sends GraphQL queries                             │
│ - Receives typed results                            │
│ - Type safe (guaranteed by schema)                  │
└─────────────────────────────────────────────────────┘
```

---

## Key Concepts Map

**Terminology:**

- **Schema** = Full specification of your API
- **Type** = Data object definition (maps to a read view)
- **Field** = Named value in a type (maps to a column in the view's `data`)
- **Query** = Read operation (SELECT against a `v_`/`tv_` view)
- **Mutation** = Write operation (calls a `fn_` function)
- **Resolver** = Logic connecting GraphQL to the database (field resolvers generated at startup)
- **Relationship** = Connection between types (composed into the view's `data` JSONB)

**Mental Models:**

- Schemas are *API contracts*
- Types map to *read views*
- Queries map to *SELECT statements*
- Mutations map to *PostgreSQL functions*
- The schema is *built once at startup*, then served per request

**Database Concepts:**

- Write tables (`tb_*`) = normalized source of truth
- Read views (`v_*`) = curated reads with a `data` JSONB column
- Projection views (`tv_*`) = materialized reads for heavy nested data
- Functions (`fn_*`) = write business logic
- The database is the *source of truth*

---

## Next Steps

Now that you understand the terminology and mental models:

1. **Understand the design** → [Database-Centric Architecture](./03-database-centric-architecture.md)
   - Why FraiseQL puts the database at the center

2. **Build your first app** → [Quickstart](../getting-started/quickstart.md)
   - Stand up a FraiseQL GraphQL API

3. **Learn the type system** → [Type System](./09-type-system.md)
   - Scalars, objects, enums, inputs, and results

---

## Related Topics

- [Database-Centric Architecture](./03-database-centric-architecture.md) — Why the database is central
- [Design Principles](./04-design-principles.md) — The thinking behind FraiseQL
- [Comparisons](./05-comparisons.md) — How FraiseQL relates to other approaches
- [Error Handling & Validation](./10-error-handling-validation.md) — Success/error result patterns
- [Performance Characteristics](./12-performance-characteristics.md) — What to expect at runtime
- [Concepts Glossary](../core/concepts-glossary.md) — Quick definitions
- [Scalars Reference](../reference/scalars.md) — Built-in scalar types

---

## Quick Reference: FraiseQL Vocabulary

| Term | Means | Example |
|------|-------|---------|
| **Schema** | Full API specification | `@fraiseql.type(sql_source="v_user")` |
| **Type** | Data object definition | `class User:` |
| **Field** | Value in a type | `name: str` |
| **Query** | Read operation | `query GetUser { ... }` |
| **Mutation** | Write operation | `mutation CreateUser { ... }` |
| **Resolver** | GraphQL ↔ DB logic | Field resolvers generated at startup |
| **Relationship** | Connection between types | `orders: list[Order]` |
| **Write table** | Normalized source of truth | `tb_user` |
| **Read view** | Curated read with `data` JSONB | `v_user` |
| **Function** | Write business logic | `fn_create_user` |

---

**Key Takeaway:** FraiseQL uses *database-native terminology* because the PostgreSQL database is the source of truth. Understand the database concepts — write tables, read views, and functions — and FraiseQL becomes intuitive.

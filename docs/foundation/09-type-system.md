---
title: "2.4: Type System"
description: FraiseQL's type system is the bridge between your Python type hints and your GraphQL API. Python types you declare on @fraiseql.type classes map to GraphQL types when the schema is built at app startup.
keywords: ["type-system", "graphql", "scalars", "postgresql", "runtime"]
tags: ["documentation", "reference"]
---

# 2.4: Type System

**Audience:** Schema designers, backend developers, API architects
**Prerequisite:** [2.2 Core Concepts](02-core-concepts.md), [2.3 Database-Centric Architecture](03-database-centric-architecture.md)
**Reading Time:** 15-20 minutes

---

## Overview

FraiseQL's type system is the bridge between your Python type hints and your GraphQL API. You declare types with `@fraiseql.type` and annotate fields with ordinary Python type hints; FraiseQL reads those hints when the schema is built and maps each one to a GraphQL type.

**Key Insight:** Your GraphQL schema is generated from your Python type definitions at **app startup**. There is no separate compile or codegen step — the schema is assembled in memory when the application boots and is served over FastAPI.

FraiseQL is **PostgreSQL-only**. Object types are backed by read views (`v_`/`tv_`) that expose a `data` JSONB column, and the shape of that JSONB matches the GraphQL type. See [Database-Centric Architecture](03-database-centric-architecture.md) for how views and the `data` column work.

---

## Type System Flow

```text
Python type hints
(@fraiseql.type field annotations: int, str, bool, datetime, UUID, ...)
         ↓
Schema build at app startup
(FraiseQL reads the annotations in memory)
         ↓
GraphQL types
(Int, String, Boolean, DateTime, ID, ...)
         ↓
API contract
(served over FastAPI / graphql-core)
```

Backing the runtime: a PostgreSQL read view returns a `data` JSONB document whose keys correspond to the GraphQL fields. FraiseQL shapes that JSONB to the fields the client requested.

---

## Built-In Scalar Types

### The Mapping

FraiseQL maps common Python types to GraphQL scalars, and provides domain scalars you can use explicitly. Import the scalars you need:

```python
from fraiseql.types import ID, Date, DateTime, Time, EmailAddress, JSON, LTree
```

| Python type | GraphQL type | PostgreSQL (`data` JSONB value) | Example |
|-------------|--------------|---------------------------------|---------|
| `int` | `Int` | JSON number | `123` |
| `float` | `Float` | JSON number | `3.14` |
| `str` | `String` | JSON string | `"hello"` |
| `bool` | `Boolean` | JSON boolean | `true` |
| `ID` | `ID` | JSON string (UUID) | `"550e8400-e29b-41d4-a716-446655440000"` |
| `UUID` | `UUID` | JSON string | `"550e8400-..."` |
| `Date` | `Date` | ISO date string | `"2026-01-29"` |
| `DateTime` | `DateTime` | ISO timestamp string | `"2026-01-29T14:30:00Z"` |
| `Time` | `Time` | ISO time string | `"14:30:00"` |
| `EmailAddress` | `EmailAddress` | JSON string | `"a@example.com"` |
| `JSON` | `JSON` | nested JSON | `{"key": "value"}` |
| `LTree` | `LTree` | JSON string (label path) | `"top.science.maths"` |

> FraiseQL ships many more domain scalars (currency codes, IP addresses, vectors, and more). See the full list in [Custom Scalar Types](../reference/scalars.md) — only use scalars documented there.

### Defining a Type

A `@fraiseql.type` class declares the GraphQL object type and the read view that backs it. `jsonb_column` defaults to `"data"`.

```python
import fraiseql
from fraiseql.types import ID, DateTime, EmailAddress

@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    email: EmailAddress
    first_name: str | None      # nullable field
    last_name: str | None       # nullable field
    is_active: bool
    created_at: DateTime
    metadata: dict | None       # nullable JSON object
```

**Generated GraphQL type:**

```graphql
type User {
  id: ID!
  email: EmailAddress!
  firstName: String
  lastName: String
  isActive: Boolean!
  createdAt: DateTime!
  metadata: JSON
}
```

The `id` field is the public `UUID` exposed as `ID`. Internal keys (`pk_*`, `fk_*`) are never part of the `data` JSONB and never appear in GraphQL. See [Database-Centric Architecture](03-database-centric-architecture.md) for the trinity identifier pattern (`pk_` internal, `id` public UUID, optional `identifier` slug).

---

## Nullable vs Non-Nullable Types

Nullability comes directly from your Python type hints.

**Rule: `X | None` → nullable; bare `X` → non-nullable.**

```python
@fraiseql.type(sql_source="v_order")
class Order:
    id: ID                  # → ID!     (non-nullable)
    total: float            # → Float!  (non-nullable)
    note: str | None        # → String  (nullable)
    status: str             # → String! (non-nullable)
```

**Result in GraphQL:**

```graphql
type Order {
  id: ID!
  total: Float!
  note: String
  status: String!
}
```

A non-nullable field must always be present in the response; a nullable field may be `null`.

```graphql
query {
  user {
    email    # always present (non-null in schema)
    phone    # included if set, null if not
  }
}
```

Make sure your read view's `data` JSONB always provides a value for non-nullable fields, otherwise resolution will fail at runtime.

---

## Composite Types: Objects and Relationships

### Object Types

An object type is a composite type with multiple fields:

```python
import fraiseql
from fraiseql.types import ID, DateTime

@fraiseql.type(sql_source="v_order")
class Order:
    id: ID
    total: float
    status: str
    created_at: DateTime
```

The backing read view builds the `data` JSONB:

```sql
CREATE VIEW v_order AS
SELECT
    o.id,                                       -- public UUID, exposed as ID
    jsonb_build_object(
        'id', o.id,
        'total', o.total,
        'status', o.status,
        'created_at', o.created_at
    ) AS data
FROM tb_order o;
```

### Relationships: One-to-Many

Relationships are expressed as nested types in Python, and the backing read view composes the nested objects into the `data` JSONB.

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_order")
class Order:
    id: ID
    total: float

@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    email: str
    orders: list[Order]       # one-to-many: a user has many orders
```

**Generated GraphQL types:**

```graphql
type User {
  id: ID!
  email: String!
  orders: [Order!]!
}

type Order {
  id: ID!
  total: Float!
}
```

The `v_user` view builds the nested orders inside the user's `data` JSONB (for example with `jsonb_agg(...)` over the related rows), so the relationship is pre-composed in PostgreSQL:

```sql
CREATE VIEW v_user AS
SELECT
    u.id,
    jsonb_build_object(
        'id', u.id,
        'email', u.email,
        'orders', COALESCE(
            (SELECT jsonb_agg(jsonb_build_object('id', o.id, 'total', o.total))
             FROM tb_order o
             WHERE o.fk_user = u.pk_user),
            '[]'::jsonb
        )
    ) AS data
FROM tb_user u;
```

**Query example:**

```graphql
query GetUserWithOrders($id: ID!) {
  user(id: $id) {
    id
    email
    orders {
      id
      total
    }
  }
}
```

### Relationships: Many-to-Many

A junction table (`tb_student_courses`) links the two sides; each side's read view composes the related objects into its `data` JSONB.

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_course")
class Course:
    id: ID
    title: str

@fraiseql.type(sql_source="v_student")
class Student:
    id: ID
    name: str
    courses: list[Course]      # many-to-many via junction table
```

**Generated GraphQL types:**

```graphql
type Student {
  id: ID!
  name: String!
  courses: [Course!]!
}

type Course {
  id: ID!
  title: String!
}
```

---

## List Types

Lists come from Python `list[...]` annotations. Optionality of the list itself follows the same `X | None` rule.

```python
@fraiseql.type(sql_source="v_user")
class User:
    tags: list[str]            # → [String!]!  (list and items non-null)
    notes: list[str] | None    # → [String!]   (list nullable, items non-null)
```

**GraphQL list modifiers:**

```graphql
[String]        # list can be null, items can be null
[String!]       # list can be null, items non-null
[String]!       # list non-null, items can be null
[String!]!      # list non-null, items non-null
```

A non-empty, non-null list:

```graphql
type User {
  tags: [String!]!
}

# Valid:
{ "tags": ["vip", "premium"] }

# Invalid:
{ "tags": null }            # list is non-null
{ "tags": ["vip", null] }   # items must be non-null
```

One-to-many relationships are expressed as `list[RelatedType]` and become `[RelatedType!]!`, as shown above.

---

## Input Types

Use `@fraiseql.input` for arguments to mutations and queries. Inputs follow the same Python-type-hint mapping.

```python
import fraiseql

@fraiseql.input
class CreateUserInput:
    name: str
    email: str
    age: int | None = None      # optional input field with default
```

**Generated GraphQL input:**

```graphql
input CreateUserInput {
  name: String!
  email: String!
  age: Int
}
```

A mutation consumes the input and delegates the write to a PostgreSQL function:

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

See [Error Handling & Validation](10-error-handling-validation.md) for the success/error result pattern.

---

## Enum Types

Use `@fraiseql.enum` on a Python `enum.Enum` to expose a GraphQL enum.

```python
import fraiseql
from enum import Enum

@fraiseql.enum
class OrderStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"

@fraiseql.type(sql_source="v_order")
class Order:
    id: ID
    status: OrderStatus
```

**Generated GraphQL:**

```graphql
enum OrderStatus {
  PENDING
  CONFIRMED
  SHIPPED
  DELIVERED
}

type Order {
  id: ID!
  status: OrderStatus!
}
```

Enums are a good fit for constrained values stored as text (or a PostgreSQL `ENUM`) in your tables.

---

## Interface Types

Use `@fraiseql.interface` to declare a shared field contract that multiple object types implement.

```python
import fraiseql
from fraiseql.types import ID, DateTime

@fraiseql.interface
class Node:
    id: ID
    created_at: DateTime

@fraiseql.type(sql_source="v_user")
class User(Node):
    email: str

@fraiseql.type(sql_source="v_order")
class Order(Node):
    total: float
```

**Generated GraphQL:**

```graphql
interface Node {
  id: ID!
  createdAt: DateTime!
}

type User implements Node {
  id: ID!
  createdAt: DateTime!
  email: String!
}

type Order implements Node {
  id: ID!
  createdAt: DateTime!
  total: Float!
}
```

---

## Union Types

A union is expressed with the `A | B` syntax — most commonly as a mutation return type combining a success and an error type.

```python
import fraiseql

@fraiseql.success
class CreateUserSuccess:
    user: User

@fraiseql.error
class CreateUserError:
    message: str
    code: str = "VALIDATION_ERROR"

@fraiseql.mutation
async def create_user(info, input: CreateUserInput) -> CreateUserSuccess | CreateUserError:
    ...
```

**Generated GraphQL:**

```graphql
union CreateUserResult = CreateUserSuccess | CreateUserError
```

Clients use inline fragments to read the result:

```graphql
mutation {
  createUser(input: { name: "Bob", email: "bob@example.com" }) {
    ... on CreateUserSuccess { user { id email } }
    ... on CreateUserError { message code }
  }
}
```

---

## Type Safety in Action

### At Schema Build (App Startup)

When the application boots, FraiseQL reads your Python type hints and assembles the GraphQL schema in memory. This is where field-to-type mapping and nullability are resolved.

```python
@fraiseql.type(sql_source="v_user")
class User:
    id: ID          # → ID!     (non-nullable)
    email: str      # → String! (non-nullable)
    phone: str | None  # → String (nullable)
```

```text
✅ id: annotated ID → GraphQL ID! (non-null)
✅ email: annotated str → GraphQL String! (non-null)
✅ phone: annotated str | None → GraphQL String (nullable)
✅ schema assembled in memory, served over FastAPI
```

### At Runtime (Query Execution)

graphql-core validates incoming variables and arguments against the schema, and FraiseQL shapes the read view's `data` JSONB to the requested fields.

```graphql
query GetUser($id: ID!) {
  user(id: $id) {
    id
    email
  }
}

# Variables: { "id": 123 }   # wrong type
```

```text
❌ Variable $id: expected ID, got Int
Error: "Variable '$id' got invalid value 123; ID cannot represent a non-string value"
```

---

## Worked Example: User with Orders

**Python types:**

```python
import fraiseql
from fraiseql.types import ID, DateTime

@fraiseql.type(sql_source="v_order")
class Order:
    id: ID
    total: float
    created_at: DateTime

@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    email: str
    first_name: str | None
    last_name: str | None
    created_at: DateTime
    orders: list[Order]
```

**Generated GraphQL types:**

```graphql
type User {
  id: ID!
  email: String!
  firstName: String
  lastName: String
  createdAt: DateTime!
  orders: [Order!]!
}

type Order {
  id: ID!
  total: Float!
  createdAt: DateTime!
}
```

The `v_user` read view builds the user's `data` JSONB (including the nested `orders` array), and the `v_order` view builds each order's `data`. No foreign keys are exposed; the relationship is composed in the view.

---

## Type System Best Practices

### 1. Be explicit about nullability

```python
# Be explicit with the | None hint
@fraiseql.type(sql_source="v_user")
class User:
    email: str          # → String! (always present)
    phone: str | None   # → String  (may be null)
```

### 2. Model relationships, not foreign keys

Expose related objects (`user: User`, `orders: list[Order]`) rather than raw `fk_*` columns. The trinity pattern keeps `pk_`/`fk_` internal and out of the `data` JSONB.

### 3. Use enums for constrained values

```python
@fraiseql.enum
class OrderStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
```

### 4. Prefer domain scalars where they add validation

Use `EmailAddress` over a bare `str` for emails, `Date`/`DateTime` over strings for dates, and so on. See [Custom Scalar Types](../reference/scalars.md).

---

## Related Topics

- [2.2 Core Concepts](02-core-concepts.md) — understanding types and terminology
- [2.3 Database-Centric Architecture](03-database-centric-architecture.md) — read views, `data` JSONB, the trinity identifier pattern
- [2.5 Error Handling & Validation](10-error-handling-validation.md) — success/error result types and validation
- [Custom Scalar Types](../reference/scalars.md) — the full scalar catalogue
- [Where Operators](../reference/where-operators.md) — filtering query results
- [Concepts Glossary](../core/concepts-glossary.md) — terminology reference
- [Quickstart](../getting-started/quickstart.md) — define your first types end-to-end

---

## Summary

FraiseQL's type system maps your Python type hints to GraphQL at **app startup**:

**Built-in scalar mappings:**

- Numbers: `int` → `Int`, `float` → `Float`
- Text: `str` → `String`
- Booleans: `bool` → `Boolean`
- Identifiers / dates: `ID`, `UUID`, `Date`, `DateTime`, `Time`
- Domain scalars: `EmailAddress`, `JSON`, `LTree`, and more (see [the scalar reference](../reference/scalars.md))

**Key principles:**

1. **Python type hints drive the schema** — types are read in memory when the app boots; there is no compile step.
2. **`X | None` drives nullability** — bare `X` is non-null, `X | None` is nullable.
3. **Relationships are nested types** — `list[Related]` becomes `[Related!]!`, composed in the backing read view.
4. **PostgreSQL-backed** — object types map to `v_`/`tv_` views exposing a `data` JSONB; `pk_`/`fk_` stay internal.
5. **Self-documenting** — the schema clearly shows what is required vs optional.

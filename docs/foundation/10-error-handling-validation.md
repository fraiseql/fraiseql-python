---
title: Error Handling & Validation
description: FraiseQL's error handling and validation strategy ensures predictable, safe query execution. Validation happens at runtime — in Python resolvers and in PostgreSQL functions — producing structured, classified errors.
keywords: ["error-handling", "validation", "graphql", "postgresql", "mutations"]
tags: ["documentation", "reference"]
---

# Error Handling & Validation

## Overview

FraiseQL's error handling and validation strategy ensures predictable, safe query execution. FraiseQL is a **runtime** GraphQL framework: the schema is assembled in memory at application startup, and validation happens while requests are served — in Python resolvers and in the PostgreSQL functions that back mutations. There is no separate compile step.

This topic explains:

- **Error classification**: How errors are grouped (client vs server, retryable vs permanent)
- **Validation layers**: Where errors are caught (type definitions, schema assembly, request parameters, authorization, execution)
- **Mutation result pattern**: The `success | error` union returned by mutations
- **Error handling patterns**: How to handle errors in client applications, HTTP responses, and recovery strategies
- **Validation best practices**: Input validation, authorization enforcement, conflict detection

### Error Handling Architecture

```text
Authoring Layer          Startup Layer            Runtime Layer
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Python decorators│    │ Schema assembly  │    │ FastAPI app      │
│ schema.py        │    │ (in memory)      │    │ GraphQL API      │
│                  │    │                  │    │                  │
│ VALIDATION PHASE │    │ VALIDATION PHASE │    │ VALIDATION PHASE │
│ - Type syntax    │    │ - Schema refs    │    │ - Auth rules     │
│ - Field names    │    │ - Relationships  │    │ - Parameter type │
│ - Decorators     │    │ - SQL sources    │    │ - PostgreSQL fn  │
└────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘
         │                       │                       │
         └──────→ Errors         └──────→ Errors        └──────→ Errors
            (raised)                (raised)               (raised)
```

---

## Error Classification

FraiseQL errors are classified by:

1. **Source**: Where the error originated (GraphQL, Database, Authorization, etc.)
2. **Severity**: Client error (4xx) vs Server error (5xx)
3. **Retryability**: Whether the operation can be safely retried

### Common Error Types

| Error Type | Category | HTTP Status | Retryable | Cause |
|------------|----------|-------------|-----------|-------|
| **Parse** | GraphQL Client | 400 | ❌ | Invalid GraphQL syntax (malformed query/mutation) |
| **Validation** | GraphQL Client | 400 | ❌ | Query valid but semantically wrong (wrong field/type) |
| **UnknownField** | GraphQL Client | 400 | ❌ | Field doesn't exist on type |
| **UnknownType** | GraphQL Client | 400 | ❌ | Type doesn't exist in schema |
| **Database** | Server | 500 | ❌ | Database operation failed (constraint violation, etc.) |
| **ConnectionPool** | Server | 500 | ✅ | No available connections in pool |
| **Timeout** | Server | 408 | ✅ | Query exceeded execution timeout |
| **Cancelled** | Server | 408 | ✅ | Query cancelled (client disconnect or explicit) |
| **Authorization** | Client | 403 | ❌ | User lacks permission for operation/resource |
| **Authentication** | Client | 401 | ❌ | Invalid/missing/expired credentials |
| **NotFound** | Client | 404 | ❌ | Requested resource doesn't exist |
| **Conflict** | Client | 409 | ❌ | Operation conflicts with existing data |
| **Configuration** | Server | 500 | ❌ | Invalid application configuration |
| **Internal** | Server | 500 | ❌ | Unexpected internal error (rare) |

### Error Categories

**Client Errors (4xx):**

```text
Parse, Validation, UnknownField, UnknownType,
Authentication, Authorization, NotFound, Conflict
```

The caller made a mistake. The same request will fail repeatedly. Example:

```graphql
# Query has unknown field 'usernam' instead of 'username'
query {
  user(id: 1) {
    usernam  # ← Validation error (4xx)
  }
}
```

**Server Errors (5xx):**

```text
Database, ConnectionPool, Timeout, Cancelled,
Configuration, Internal
```

System failure outside the caller's control. May succeed if retried. Example:

```text
"Database error: connection refused"  # ← 5xx error
# May succeed if database recovers and request is retried
```

**Retryable Errors (can be safely retried):**

```text
ConnectionPool, Timeout, Cancelled
```

Safe to retry with exponential backoff. Examples:

- Connection pool exhausted → retry when connections available
- Query timeout → retry with possibly reduced complexity
- Client cancellation → external event, caller can retry manually

---

## Validation Layers

### Layer 1: Authoring-Time Validation

Errors caught while writing Python type definitions:

```python
import fraiseql
from fraiseql.types import ID

# ✅ VALID: Proper type annotation
@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    name: str

# ❌ INVALID: Unknown field type (caught by your Python type checker)
@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    name: BadType  # ← Python type error before the app even starts
```

**Tools:** Python type checking (`ty`, your editor / IDE).

### Layer 2: Schema-Assembly Validation

When the app starts, FraiseQL assembles the GraphQL schema in memory and validates references between types:

**Schema Reference Validation:**

```python
@fraiseql.type(sql_source="v_post")
class Post:
    id: ID
    author: User  # ← Must reference a registered @fraiseql.type

# ❌ FAILS AT STARTUP: author references a type that was never registered
@fraiseql.type(sql_source="v_post")
class Post:
    id: ID
    author: NonExistentUser

# Error: schema build fails — "Unknown type 'NonExistentUser' referenced in Post.author"
```

**Read-Source Validation:**

```python
@fraiseql.type(sql_source="v_post")
class Post:
    id: ID
    title: str
    # At startup FraiseQL records that this type reads from the v_post view.
    # The view's `data` JSONB column must contain the fields you expose.
    # If the view is missing at query time, the database raises an error.
```

The underlying PostgreSQL objects follow FraiseQL's naming conventions. Writes go to a normalized `tb_` table; reads come from a `v_` view (or a `tv_` projection view) that exposes a public `id UUID` plus a `data` JSONB column built with `jsonb_build_object(...)`:

```sql
-- Write table (source of truth, never exposed directly)
CREATE TABLE tb_post (
    pk_post   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- internal, hidden
    id        UUID NOT NULL DEFAULT gen_random_uuid(),          -- public GraphQL id
    fk_author BIGINT NOT NULL REFERENCES tb_user(pk_user),      -- internal FK, hidden
    title     TEXT NOT NULL
);

-- Read view exposed to GraphQL
CREATE VIEW v_post AS
SELECT
    p.id,
    jsonb_build_object(
        'id', p.id,
        'title', p.title,
        'author', jsonb_build_object('id', u.id, 'name', u.name)
    ) AS data
FROM tb_post p
JOIN tb_user u ON u.pk_user = p.fk_author;
```

### Layer 3: Request-Time Validation

Errors caught before query execution (parameter binding, authorization):

**Parameter Type Validation:**

```graphql
# Schema defines: user(id: ID!)
query {
  user(id: 123) {  # ← Number where an ID is expected
    name
  }
}

# Error: "Expected value of type 'ID' for argument 'id'"
```

**Parameter Range Validation:**

```graphql
# Schema defines: users(limit: Int = 20, offset: Int = 0)
# A resolver can enforce: limit [1, 10000], offset [0, ∞)
query {
  users(limit: 100000) {  # ← Exceeds maximum
    name
  }
}

# Error: "Parameter 'limit' must be ≤ 10000, got 100000"
```

**Authorization Validation:**

Authorization in FraiseQL v1 is implemented in Python. The `info.context` carries the authenticated principal, and resolvers (or a shared authorization helper) decide whether the operation is allowed before any SQL is executed:

```python
@fraiseql.mutation
async def update_post(info, input: UpdatePostInput) -> UpdatePostSuccess | UpdatePostError:
    user = info.context.get("user")
    if user is None:
        return UpdatePostError(message="authentication required", code="UNAUTHENTICATED")
    if not user.can_write("Post", input.id):
        # Deny before touching the database
        return UpdatePostError(message="insufficient permissions", code="FORBIDDEN")

    db = info.context["db"]
    result = await db.execute_function("fn_update_post", {"id": str(input.id), "title": input.title})
    if not result.get("success"):
        return UpdatePostError(message=result.get("message", "failed"), code=result.get("code", "ERROR"))
    return UpdatePostSuccess(post=Post(**result["post"]))
```

For the full authorization model and decision API, see [Authorization](../security/authorization.md). Describe access rules in Python; do not assume a separate server enforces them.

### Layer 4: Execution-Time Validation

Errors caught during or after SQL execution. For mutations, business validation lives inside the `fn_` PostgreSQL function, which returns a JSONB result indicating success or failure.

**Conflict Detection (inside the PostgreSQL function):**

```sql
-- fn_create_user: validates and writes, returns JSONB
CREATE FUNCTION fn_create_user(input JSONB)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    new_id UUID;
BEGIN
    IF EXISTS (SELECT 1 FROM tb_user WHERE username = input->>'username') THEN
        RETURN jsonb_build_object(
            'success', false,
            'code', 'CONFLICT',
            'message', format('username %s is already taken', input->>'username')
        );
    END IF;

    INSERT INTO tb_user (username, email)
    VALUES (input->>'username', input->>'email')
    RETURNING id INTO new_id;

    RETURN jsonb_build_object(
        'success', true,
        'message', 'user created',
        'user', jsonb_build_object('id', new_id, 'name', input->>'username')
    );
END;
$$;
```

If a database constraint is violated despite the checks (a race condition, for example), PostgreSQL raises an error the framework surfaces as a `Database` error:

```text
Database {
  message: "duplicate key value violates unique constraint \"uc_user_username\"",
  sql_state: "23505"   -- PostgreSQL unique violation code
}
```

**Post-Fetch Authorization (field filtering):**

Because reads return a `data` JSONB document shaped to the requested GraphQL fields, a resolver can strip fields the caller is not allowed to see before returning the object:

```python
@fraiseql.query
async def post(info, id: ID) -> Post | None:
    db = info.context["db"]
    row = await db.find_one("v_post", id=id)
    if row is None:
        return None
    user = info.context.get("user")
    if user is None or not user.can_read("Post.secret", id):
        row.secret = None  # silently drop the unauthorized field
    return row
```

**Timeout Detection:**

A query that exceeds the configured statement timeout is surfaced as a retryable `Timeout` error rather than hanging the request.

---

## GraphQL Error Response Format

FraiseQL follows the GraphQL specification for error responses. Errors are returned as JSON with error codes, locations, and path information.

### Single Error Response

```json
{
  "errors": [
    {
      "message": "Unknown field 'usernam' on type 'User'",
      "extensions": {
        "code": "UNKNOWN_FIELD",
        "status": 400
      },
      "locations": [
        { "line": 3, "column": 5 }
      ],
      "path": ["user", "usernam"]
    }
  ]
}
```

### Multiple Errors Response

```json
{
  "errors": [
    {
      "message": "Unknown field 'usernam' on type 'User'",
      "extensions": { "code": "UNKNOWN_FIELD" },
      "path": ["user", "usernam"],
      "locations": [{ "line": 3, "column": 5 }]
    },
    {
      "message": "Expected type 'ID' for argument 'id'",
      "extensions": { "code": "GRAPHQL_VALIDATION_FAILED" },
      "path": ["user"],
      "locations": [{ "line": 2, "column": 8 }]
    }
  ]
}
```

### Database Error Response

```json
{
  "errors": [
    {
      "message": "Database error: duplicate key value violates unique constraint",
      "extensions": {
        "code": "DATABASE_ERROR",
        "status": 500,
        "sql_state": "23505",
        "retryable": false
      }
    }
  ]
}
```

### Authorization Error Response

```json
{
  "errors": [
    {
      "message": "Authorization error: insufficient permissions",
      "extensions": {
        "code": "FORBIDDEN",
        "status": 403,
        "action": "read",
        "resource": "Post:456",
        "reason": "user_role is 'viewer', requires 'editor' or above"
      }
    }
  ]
}
```

---

## The Mutation Result Pattern

FraiseQL mutations return a **union** of a success type and an error type. This makes both outcomes part of the typed GraphQL schema, so clients can branch on the concrete type instead of parsing a top-level `errors` array.

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.input
class CreateUserInput:
    name: str
    email: str

@fraiseql.success
class CreateUserSuccess:
    user: User                # @success auto-injects status/message/updated_fields/id

@fraiseql.error               # @fraiseql.failure is an accepted alias
class CreateUserError:
    message: str
    code: str = "VALIDATION_ERROR"

@fraiseql.mutation
async def create_user(info, input: CreateUserInput) -> CreateUserSuccess | CreateUserError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_create_user",
        {"name": input.name, "email": input.email},
    )
    if not result.get("success"):
        return CreateUserError(
            message=result.get("message", "failed"),
            code=result.get("code", "VALIDATION_ERROR"),
        )
    return CreateUserSuccess(user=User(**result["user"]))
```

The PostgreSQL `fn_create_user` function performs the validation and the write, returning a JSONB document of the shape `{success, message, code, ...}`. The resolver translates that document into the success or error branch of the union.

Clients select on the concrete type:

```graphql
mutation {
  createUser(input: { name: "Alice", email: "alice@example.com" }) {
    __typename
    ... on CreateUserSuccess {
      user { id name }
    }
    ... on CreateUserError {
      message
      code
    }
  }
}
```

---

## Error Handling Strategies

### Strategy 1: Fail Fast (Default)

Return the first error immediately, stop processing:

```text
# Schema: query { posts { id, title, author { name } } }
# Execution order:
# 1. Validate GraphQL syntax       → ✅ Pass
# 2. Validate query structure      → ✅ Pass
# 3. Check authorization           → ❌ FAIL → Return 403 immediately
# 4. Execute SQL                   → (skipped)
# 5. Format response               → (skipped)

# Response:
# { "errors": [{ "message": "...", "extensions": { "code": "FORBIDDEN" } }] }
```

**When to use:** Default for all queries. Safe and predictable.

### Strategy 2: Partial Execution with Field-Level Errors

Return available data with errors for failed fields:

```graphql
query {
  posts {
    id           # ✅ Succeeds
    title        # ✅ Succeeds
    author {
      name       # ❌ Authorization denied on this field
      email      # (not fetched due to error above)
    }
  }
}
```

**Response:**

```json
{
  "data": {
    "posts": [
      {
        "id": 1,
        "title": "GraphQL Guide",
        "author": null
      }
    ]
  },
  "errors": [
    {
      "message": "Authorization error: cannot read author.name",
      "extensions": { "code": "FORBIDDEN" },
      "path": ["posts", 0, "author", "name"]
    }
  ]
}
```

**When to use:** When some fields are public and others require permission. Provides better UX.

### Strategy 3: Retry with Exponential Backoff

For retryable errors (ConnectionPool, Timeout, Cancelled):

```python
import asyncio
import random

async def execute_with_retry(client, query, max_attempts: int = 3):
    for attempt in range(1, max_attempts + 1):
        try:
            return await client.execute(query)
        except RetryableError as e:
            if attempt >= max_attempts:
                raise

            # Exponential backoff with jitter
            backoff = 2 ** (attempt - 1)  # 1s, 2s, 4s
            jitter = random.uniform(0, backoff * 0.1)
            wait_time = backoff + jitter
            await asyncio.sleep(wait_time)

# Usage
result = await execute_with_retry(client, query)
```

**Error types to retry:**

- `ConnectionPool`: Wait for an available connection
- `Timeout`: May succeed with a longer timeout or simpler query
- `Cancelled`: Query was interrupted, caller can retry

**Error types NOT to retry:**

- `Parse`, `Validation`: The same query will fail identically
- `Database` (constraint violation): Data hasn't changed
- `Authorization`: Permissions are unchanged

### Strategy 4: Graceful Degradation

Provide fallback behavior when queries fail:

```python
ANALYTICS_QUERY = """
  query {
    sales { date revenue costs margin }
  }
"""

FALLBACK_QUERY = """
  query {
    sales { date revenue }
  }
"""

async def get_analytics(client):
    try:
        return await client.execute(ANALYTICS_QUERY)
    except FraiseQLError as error:
        if error.code in {"TIMEOUT", "CONNECTION_POOL_ERROR"}:
            # Fall back to a simpler, faster query
            return await client.execute(FALLBACK_QUERY)
        raise
```

---

## Input Validation Best Practices

### Practice 1: Validate at Entry Points

Validate user input before executing SQL. Type and shape validation come from the `@fraiseql.input` type; business rules live in the resolver and the PostgreSQL function:

```python
import fraiseql
from fraiseql.types import ID, EmailAddress

@fraiseql.input
class CreateUserInput:
    username: str
    email: EmailAddress
    age: int

@fraiseql.mutation
async def create_user(info, input: CreateUserInput) -> CreateUserSuccess | CreateUserError:
    # Resolver-level business validation
    if not (1 <= len(input.username) <= 50):
        return CreateUserError(message="username must be 1-50 characters", code="VALIDATION_ERROR")
    if not (13 <= input.age <= 150):
        return CreateUserError(message="age must be between 13 and 150", code="VALIDATION_ERROR")

    db = info.context["db"]
    result = await db.execute_function("fn_create_user", {
        "username": input.username,
        "email": str(input.email),
        "age": input.age,
    })
    if not result.get("success"):
        return CreateUserError(message=result.get("message", "failed"), code=result.get("code", "ERROR"))
    return CreateUserSuccess(user=User(**result["user"]))
```

**Defense in depth — enforce the same rules with database constraints:**

```sql
-- PostgreSQL constraints (enforced by the database, even under race conditions)
CREATE TABLE tb_user (
    pk_user  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id       UUID NOT NULL DEFAULT gen_random_uuid(),
    username VARCHAR(50) NOT NULL,
    email    VARCHAR(255) NOT NULL,
    age      INT NOT NULL CHECK (age >= 13 AND age <= 150),
    CONSTRAINT uc_user_username UNIQUE (username),
    CONSTRAINT uc_user_email UNIQUE (email)
);

-- A CHECK violation surfaces with SQLSTATE 23514 (check_violation)
```

### Practice 2: List-Size Limits

Prevent queries from returning excessive data. Enforce limits in the query resolver:

```python
@fraiseql.query
async def users(info, limit: int = 20, offset: int = 0) -> list[User]:
    if not (1 <= limit <= 10000):
        raise ValueError(f"limit must be 1-10000, got {limit}")
    if offset < 0:
        raise ValueError("offset must be ≥ 0")

    db = info.context["db"]
    return await db.find("v_user", limit=limit, offset=offset)
```

```graphql
# ✅ Valid request
query {
  users(limit: 100, offset: 200) { id name }
}

# ❌ Invalid request: limit too high
query {
  users(limit: 100000, offset: 0) { id name }
}
# Error: "limit must be 1-10000"
```

### Practice 3: String Safety (Implicit via Parameterization)

FraiseQL prevents SQL injection by never interpolating user input into SQL strings. Values are always passed as bound parameters:

```python
# ❌ UNSAFE (never do this):
query = f"SELECT * FROM tb_user WHERE name = '{user_input}'"
# If user_input = "' OR '1'='1", this becomes a SQL injection.

# ✅ SAFE (what FraiseQL does internally — parameterized):
await db.fetchval("SELECT * FROM tb_user WHERE name = $1", user_input)
# user_input is treated as pure data, never as SQL
```

Mutation arguments reach PostgreSQL the same way — `db.execute_function("fn_x", {...})` binds the payload as a JSONB parameter, so a hostile string is data, not executable SQL.

### Practice 4: Enumeration over Free Text

Use enums to restrict input to valid values:

```python
import fraiseql
from enum import Enum
from fraiseql.types import ID

@fraiseql.enum
class UserRole(str, Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"

@fraiseql.input
class UpdateUserInput:
    id: ID
    role: UserRole  # ← Restricted to three valid values
```

```graphql
# Valid request
mutation {
  updateUser(input: { id: "…", role: ADMIN }) { __typename }
}

# Invalid request
mutation {
  updateUser(input: { id: "…", role: "superuser" }) { __typename }
  # Error: "Expected one of [ADMIN, EDITOR, VIEWER]"
}
```

---

## Authorization Patterns

Authorization in FraiseQL v1 is implemented in Python. The authenticated principal is carried in `info.context`, and resolvers (often through a shared authorization helper) decide whether to allow an operation or filter a field. The patterns below describe how to structure those decisions; for the supported decision API see [Authorization](../security/authorization.md).

### Pattern 1: Role-Based Access Control (RBAC)

Control access based on user role. Check the role in the resolver before fetching or returning sensitive fields:

```python
@fraiseql.query
async def post(info, id: ID) -> Post | None:
    db = info.context["db"]
    row = await db.find_one("v_post", id=id)
    if row is None:
        return None

    user = info.context.get("user")
    # Only editors and admins may see the `secret` field
    if user is None or user.role not in {"editor", "admin"}:
        row.secret = None
    return row
```

### Pattern 2: Ownership-Based Access Control

Control access based on data ownership. The cleanest place to enforce ownership is in the read view itself, which can mask fields the caller does not own:

```sql
-- v_post exposes `content` only to the owner or when the post is published.
CREATE VIEW v_post AS
SELECT
    p.id,
    jsonb_build_object(
        'id', p.id,
        'title', p.title,
        'content',
            CASE
                WHEN p.fk_owner = current_setting('app.current_user_pk', true)::BIGINT
                     OR p.is_published
                THEN p.content
                ELSE NULL
            END
    ) AS data
FROM tb_post p;
```

The resolver sets `app.current_user_pk` for the session from the authenticated principal before reading, so the view applies the ownership rule per request.

### Pattern 3: Attribute-Based Access Control (ABAC)

Control access based on user attributes, resource attributes, and context. Express the combined rule in a Python authorization helper invoked by the resolver:

```python
def can_read_document(user, doc) -> bool:
    return (
        user.department == doc.department
        and (doc.classification < user.clearance or doc.owner_id == user.id)
    )

@fraiseql.query
async def document(info, id: ID) -> Document | None:
    db = info.context["db"]
    doc = await db.find_one("v_document", id=id)
    user = info.context.get("user")
    if doc is None or user is None or not can_read_document(user, doc):
        return None
    return doc
```

---

## Common Error Scenarios and Recovery

### Scenario 1: User Tries to Access an Unauthorized Field

```graphql
# User 'alice' with role 'viewer' requests:
query {
  post(id: 123) {
    title       # ✅ Allowed for viewers
    secret      # ❌ Denied for viewers
  }
}
```

**Response:**

```json
{
  "data": {
    "post": {
      "title": "Public Post",
      "secret": null
    }
  },
  "errors": [
    {
      "message": "Authorization error: viewers cannot read post.secret",
      "extensions": { "code": "FORBIDDEN" },
      "path": ["post", "secret"]
    }
  ]
}
```

**Client recovery:**

```python
result = await client.execute(query)

if result.errors:
    auth_errors = [e for e in result.errors if e["extensions"]["code"] == "FORBIDDEN"]
    other_errors = [e for e in result.errors if e["extensions"]["code"] != "FORBIDDEN"]

    if auth_errors and result.data:
        # Partially available — show what we have
        show_data(result.data)
        notify(f"Some fields unavailable ({len(auth_errors)} access denied)")
    elif other_errors:
        raise RuntimeError(other_errors[0]["message"])
else:
    show_data(result.data)
```

### Scenario 2: Database Connection Lost

```text
Database operation fails with ConnectionPool error
↓
Retryable: Yes (connections will eventually become available)
↓
Client strategy: Retry with exponential backoff
```

```python
async def execute_with_connection_retry(client, query, max_retries: int = 3):
    attempt = 0
    while True:
        try:
            return await client.execute(query)
        except ConnectionPoolError:
            attempt += 1
            if attempt >= max_retries:
                raise
            # Exponential backoff: 100ms, 200ms, 400ms, ...
            await asyncio.sleep(0.1 * 2 ** (attempt - 1))
```

### Scenario 3: Query Exceeds Timeout

```text
Query execution exceeds the statement timeout
↓
Error: "Query exceeded the 30000ms statement timeout"
↓
Retryable: Possibly (with a simpler query or a raised timeout)
↓
Client strategy: Retry with reduced complexity
```

```python
FULL_REPORT = """
  query { sales(year: 2024) { id date revenue costs margin region } }
"""

QUICK_REPORT = """
  query { sales(year: 2024) { date revenue costs } }
"""

async def get_report(client):
    try:
        return await client.execute(FULL_REPORT)
    except FraiseQLError as error:
        if error.code == "TIMEOUT":
            return await client.execute(QUICK_REPORT)
        raise
```

### Scenario 4: Data Constraint Violation

```text
User tries to create a duplicate username
↓
INSERT violates a UNIQUE constraint
↓
Error: SQLSTATE 23505 (unique_violation)
↓
Retryable: No (constraint violation, not transient)
↓
Client strategy: Show error, ask for a different username
```

Most commonly this is caught inside `fn_create_user` (Layer 4 above) and returned as a typed `CreateUserError` with `code = "CONFLICT"`. If a race slips past the check, the raw `Database` error is surfaced:

```python
async def create_user(client, username: str, email: str):
    result = await client.execute(CREATE_USER_MUTATION, {"username": username, "email": email})
    payload = result.data["createUser"]
    if payload["__typename"] == "CreateUserError" and payload["code"] == "CONFLICT":
        raise UserFriendlyError("This username is already taken. Please try another.")
    return payload
```

---

## Validation in Different Scenarios

### Scenario A: Simple Read Query

```graphql
query {
  user(id: "…") {
    name
  }
}
```

**Validation order:**

1. ✅ Parse GraphQL syntax
2. ✅ Validate that the `user` query exists
3. ✅ Validate that `id` is an `ID`
4. ✅ Validate that `name` exists on the `User` type
5. ✅ Check authorization (caller may read `User.name`)
6. ✅ Execute SQL: `SELECT data FROM v_user WHERE id = $1`
7. ✅ Apply field-level authorization (if any)
8. ✅ Format JSON response
9. ✅ Return result

### Scenario B: Mutation with Input Validation

```graphql
mutation {
  createPost(input: {
    title: "New Post"
    content: "Content here"
    tags: ["postgres", "graphql"]
  }) {
    __typename
    ... on CreatePostSuccess { post { id title } }
    ... on CreatePostError { message code }
  }
}
```

**Validation order:**

1. ✅ Parse GraphQL syntax
2. ✅ Validate that the `createPost` mutation exists
3. ✅ Validate that `input` matches the `CreatePostInput` shape
4. ✅ Resolver business validation (lengths, item counts)
5. ✅ Check authorization (caller may write posts)
6. ✅ Call `fn_create_post` — it validates and inserts into `tb_post`
7. ✅ The function returns `{success, message, code, ...}` JSONB
8. ✅ Resolver maps the result to `CreatePostSuccess` or `CreatePostError`
9. ✅ Return the union result

### Scenario C: Nested Read Query

```graphql
query {
  salesByRegion(limit: 100, year: 2024) {
    region
    total
    items {
      id
      date
      revenue
    }
  }
}
```

**Validation order:**

1. ✅ Parse GraphQL syntax
2. ✅ Validate that `salesByRegion` exists
3. ✅ Validate parameters: `limit` (1–10000), `year` (1900–2100)
4. ✅ Check authorization (caller may read this data)
5. ✅ Apply field-level authorization on sensitive fields
6. ✅ Execute the read against the `tv_` projection view (pre-composed JSONB)
7. ✅ If the statement times out: return a retryable `Timeout` error
8. ✅ If the pool is exhausted: return a retryable `ConnectionPool` error
9. ✅ Format the JSON response (Rust accelerates field selection on the hot path)
10. ✅ Return result

---

## Validation Best Practices Checklist

- [ ] **Validate input shapes**: Use `@fraiseql.input` types so parameters match expected types before SQL runs
- [ ] **Enforce range limits**: Set min/max for numeric inputs and length for strings in the resolver
- [ ] **Use enums**: Restrict categorical input to a fixed set of valid values
- [ ] **Check authorization first**: Deny access before executing expensive queries
- [ ] **Push business rules into PostgreSQL**: Let `fn_` functions and constraints be the final authority
- [ ] **Classify errors**: Distinguish client errors (4xx) from server errors (5xx)
- [ ] **Retry responsibly**: Only retry retryable errors (ConnectionPool, Timeout, Cancelled)
- [ ] **Expose error codes**: Let clients distinguish error types by `code`, not message text
- [ ] **Log errors consistently**: Include error code, user ID, resource, timestamp
- [ ] **Don't leak internals**: Client-facing messages should not expose DB schema or system details
- [ ] **Track error rates**: Monitor error types and rates to detect issues early

---

## Real-World Error Handling Example

### E-Commerce: Order Creation with Full Validation

```graphql
mutation {
  createOrder(input: {
    userId: "…"
    items: [
      { productId: "…", quantity: 2 }
      { productId: "…", quantity: 1 }
    ]
    shippingAddress: "123 Main St"
  }) {
    __typename
    ... on CreateOrderSuccess { orderId status total }
    ... on CreateOrderError { message code }
  }
}
```

**Resolver: thin authorization + delegation to PostgreSQL:**

```python
@fraiseql.mutation
async def create_order(info, input: CreateOrderInput) -> CreateOrderSuccess | CreateOrderError:
    # LAYER 1 — input validation
    if not input.items:
        return CreateOrderError(message="order must contain at least one item", code="VALIDATION_ERROR")

    # LAYER 2 — authorization (Python, before touching the database)
    user = info.context.get("user")
    if user is None:
        return CreateOrderError(message="authentication required", code="UNAUTHENTICATED")
    if not user.is_active:
        return CreateOrderError(message="user is not active", code="FORBIDDEN")

    # LAYER 3 & 4 — stock check, totals, and the write happen atomically in fn_create_order
    db = info.context["db"]
    result = await db.execute_function("fn_create_order", {
        "user_id": str(input.user_id),
        "items": [{"product_id": str(i.product_id), "quantity": i.quantity} for i in input.items],
        "shipping_address": input.shipping_address,
    })

    if not result.get("success"):
        return CreateOrderError(
            message=result.get("message", "failed"),
            code=result.get("code", "ERROR"),
        )
    return CreateOrderSuccess(
        order_id=result["order_id"],
        status=result["status"],
        total=result["total"],
    )
```

**PostgreSQL function: stock validation, totals, and the write in one transaction:**

```sql
CREATE FUNCTION fn_create_order(input JSONB)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    item        JSONB;
    stock       INT;
    total       NUMERIC := 0;
    new_id      UUID;
BEGIN
    -- Validate stock for every item
    FOR item IN SELECT * FROM jsonb_array_elements(input->'items')
    LOOP
        SELECT stock_count INTO stock
        FROM tb_product
        WHERE id = (item->>'product_id')::UUID;

        IF stock IS NULL THEN
            RETURN jsonb_build_object('success', false, 'code', 'NOT_FOUND',
                'message', format('product %s not found', item->>'product_id'));
        END IF;

        IF stock < (item->>'quantity')::INT THEN
            RETURN jsonb_build_object('success', false, 'code', 'CONFLICT',
                'message', format('only %s units available', stock));
        END IF;
    END LOOP;

    -- ... compute total, insert the order and line items, decrement stock ...
    INSERT INTO tb_order (fk_user, shipping_address, total_amount)
    VALUES (
        (SELECT pk_user FROM tb_user WHERE id = (input->>'user_id')::UUID),
        input->>'shipping_address',
        total
    )
    RETURNING id INTO new_id;

    RETURN jsonb_build_object(
        'success', true,
        'message', 'order created',
        'order_id', new_id,
        'status', 'pending',
        'total', total
    );
END;
$$;
```

**GraphQL response scenarios:**

Success:

```json
{
  "data": {
    "createOrder": {
      "__typename": "CreateOrderSuccess",
      "orderId": "ord_12345",
      "status": "pending",
      "total": 99.99
    }
  }
}
```

Validation error:

```json
{
  "data": {
    "createOrder": {
      "__typename": "CreateOrderError",
      "message": "order must contain at least one item",
      "code": "VALIDATION_ERROR"
    }
  }
}
```

Authorization error:

```json
{
  "data": {
    "createOrder": {
      "__typename": "CreateOrderError",
      "message": "user is not active",
      "code": "FORBIDDEN"
    }
  }
}
```

Conflict error (insufficient stock, raised by the PostgreSQL function):

```json
{
  "data": {
    "createOrder": {
      "__typename": "CreateOrderError",
      "message": "only 5 units available",
      "code": "CONFLICT"
    }
  }
}
```

Transient database error (surfaced as a top-level GraphQL error, should retry):

```json
{
  "errors": [{
    "message": "Query timeout",
    "extensions": {
      "code": "TIMEOUT",
      "retryable": true
    }
  }]
}
```

---

## Related Topics

- [Core Concepts](02-core-concepts.md) — How FraiseQL assembles a schema at startup
- [Database-Centric Architecture](03-database-centric-architecture.md) — Why business logic lives in PostgreSQL functions
- [Design Principles](04-design-principles.md) — The principles behind the success/error pattern
- [Type System](09-type-system.md) — Type validation and inference
- [Performance Characteristics](12-performance-characteristics.md) — Impact of validation on performance
- [Authorization](../security/authorization.md) — FraiseQL's Python authorization model
- [Concepts Glossary](../core/concepts-glossary.md) — Definitions of terms used here

---

## Summary

FraiseQL's error handling strategy is **multi-layered** and entirely **runtime**:

1. **Authoring time**: Python type checking prevents annotation mistakes
2. **Schema assembly (startup)**: FraiseQL validates type references and read sources in memory
3. **Request time**: Parameter types, ranges, and authorization are checked in Python before SQL runs
4. **Execution time**: PostgreSQL `fn_` functions and constraints enforce business rules and surface conflicts

Errors are **classified** (client vs server, retryable vs permanent), **exposed** as structured JSON with error codes, and **recoverable** through intelligent retry logic. Mutations return a typed `success | error` union so clients branch on the concrete result type.

Validation follows best practices: **validate at boundaries** (input types), **use strong types** (enums over strings), **check authorization first** (before expensive operations), and **push business rules into PostgreSQL** (functions and constraints as the final authority).

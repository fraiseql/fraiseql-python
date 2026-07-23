---
title: Error Handling Model
description: FraiseQL's error handling model is deterministic, predictable, and classifiable. Unlike traditional GraphQL servers where error handling varies by resolver, FraiseQL has a unified, classifiable error model.
keywords: ["design", "errors", "reliability", "patterns", "security"]
tags: ["documentation", "reference"]
---

# Error Handling Model

**Version:** 1.0
**Status:** Complete
**Audience:** All developers, integrators, operations engineers, architecture reviewers

---

## 1. Overview

FraiseQL's error handling model is **deterministic, predictable, and classifiable**. Unlike traditional GraphQL servers where error handling varies by resolver implementation, FraiseQL has a unified, classifiable error model.

FraiseQL v1 is a Python runtime framework: you define types, queries, and mutations with decorators, and the GraphQL schema is **built in memory at application startup** and served over FastAPI. There is no compile step and no build artifact. Errors fall into two broad phases:

**Core principle:** All errors are either **preventable** (caught when the schema is validated at app startup) or **recoverable** (clearly classified at runtime).

### 1.1 Design Philosophy

**No surprises.** Clients should never encounter unexpected error types or inconsistent error formats.

**Classifiable.** Every error falls into a well-defined category with clear semantics.

**Remediable.** Every error either tells you exactly how to fix it (schema-validation errors) or how to recover from it (runtime errors).

**Auditable.** Error context includes enough information for debugging without leaking sensitive data.

---

## 2. Error Categories

### 2.1 Schema-Validation Errors (App Startup)

**When:** While the schema is being assembled and validated at application startup
**Who sees them:** Schema authors, operators starting the app
**Recovery:** Fix the Python type/query/mutation definitions or the database, then restart
**Visibility:** Never reaches clients — the app fails to start

FraiseQL validates the in-memory schema as `build_fraiseql_schema(...)` / `create_fraiseql_app(...)` runs. If a type is missing, a view does not exist, or a column does not match, startup fails with a clear message. No partially valid schema is ever served.

#### 2.1.1 Schema Validation Errors

```text
Category: SCHEMA_INVALID
Code: E_SCHEMA_<subtype>_<number>

Examples:
  E_SCHEMA_TYPE_NOT_DEFINED_001
  E_SCHEMA_FIELD_NOT_FOUND_002
  E_SCHEMA_SOURCE_MISSING_003
  E_SCHEMA_OPERATOR_UNSUPPORTED_004
  E_SCHEMA_AUTHORIZATION_INVALID_005
```

**Causes:**

- Type referenced but not declared with `@fraiseql.type`
- Field referenced but not present in the backing database view
- Query/mutation without an `sql_source`
- WHERE operator not supported by PostgreSQL
- Authorization rule references a non-existent auth context field

**Example:**

```text
Error: Schema validation failed at startup
  Type: Type closure violation
  Code: E_SCHEMA_TYPE_NOT_DEFINED_001
  Query 'users' returns 'list[User]'
  Type 'User' is not defined
  Suggestion: Add @fraiseql.type class User or check spelling
  File: schema.py, line 42
```

#### 2.1.2 Database Binding Errors

```text
Category: BINDING_INVALID
Code: E_BINDING_<subtype>_<number>

Examples:
  E_BINDING_VIEW_NOT_FOUND_010
  E_BINDING_COLUMN_NOT_FOUND_011
  E_BINDING_TYPE_MISMATCH_012
  E_BINDING_FUNCTION_SIGNATURE_MISMATCH_013
```

**Causes:**

- A type's `sql_source` references a view (`v_`/`tv_`) that does not exist in the database
- Field maps to a column that does not exist in the view's `data` JSONB
- Field type does not match the database column type
- A mutation calls a PostgreSQL `fn_` function whose signature does not match the input

**Example:**

```text
Error: Database binding failed at startup
  Type: View not found
  Code: E_BINDING_VIEW_NOT_FOUND_010
  Query 'users' bound to view 'v_user_missing'
  Database: postgresql (localhost:5432/mydb)
  Suggestion: Create view v_user or fix sql_source to an existing view
  Available views: v_user, v_user_archived, v_user_deleted
```

#### 2.1.3 Capability Errors

```text
Category: DATABASE_CAPABILITY_UNSUPPORTED
Code: E_CAPABILITY_<operator>_<number>

Examples:
  E_CAPABILITY_VECTOR_DISTANCE_001
  E_CAPABILITY_TRIGRAM_SIMILARITY_002
  E_CAPABILITY_GEOSPATIAL_CONTAINS_003
```

**Causes:**

- Schema uses an operator that requires a PostgreSQL extension that is not installed
- Database lacks a required extension (`pgvector`, `pg_trgm`, PostGIS)

**Example:**

```text
Error: Operator requires a missing PostgreSQL extension
  Type: Database capability mismatch
  Code: E_CAPABILITY_VECTOR_DISTANCE_001
  Operator: _cosine_distance (vector similarity)
  Field: Document.embedding
  Suggestion: Install the pgvector extension (CREATE EXTENSION vector), or use a supported operator
```

#### 2.1.4 Authorization Configuration Errors

```text
Category: AUTHORIZATION_INVALID
Code: E_AUTH_<subtype>_<number>

Examples:
  E_AUTH_CONTEXT_FIELD_NOT_FOUND_020
  E_AUTH_ROLE_UNDEFINED_021
  E_AUTH_RULE_CIRCULAR_DEPENDENCY_022
```

**Causes:**

- Authorization rule references a non-existent auth context field
- Authorization rule references an undefined role
- Authorization rules have circular dependencies

See [`../../foundation/10-error-handling-validation.md`](../../foundation/10-error-handling-validation.md) for how validation and authorization are wired into the schema, and [`../../specs/schema-conventions.md`](../../specs/schema-conventions.md) for the database naming conventions (`tb_`, `v_`, `tv_`, `fn_`) referenced above.

---

### 2.2 Runtime Errors (Query/Mutation/Subscription Execution)

**When:** During runtime query execution
**Who sees them:** Client applications
**Recovery:** Application-specific (retry, notify user, log, etc.)
**Visibility:** Always returned in the GraphQL error list

#### 2.2.1 Validation Errors

```text
GraphQL error
Category: VALIDATION_FAILED
Code: E_VALIDATION_<subtype>

Structure:
{
  "errors": [{
    "message": "Human-readable error message",
    "extensions": {
      "code": "E_VALIDATION_QUERY_MALFORMED_100",
      "category": "VALIDATION_FAILED",
      "remediable": true,
      "retryable": false,
      "user_actionable": true,
      "timestamp": "2026-01-11T15:35:00Z",
      "trace_id": "req_550e8400"
    }
  }]
}
```

**Error Types:**

| Subtype | Code | Cause | Retryable | Example |
|---------|------|-------|-----------|---------|
| QUERY_MALFORMED | E_VALIDATION_QUERY_MALFORMED_100 | Syntax error in GraphQL query | No | `{ users { invalid_field } }` |
| VARIABLE_TYPE_MISMATCH | E_VALIDATION_VARIABLE_TYPE_MISMATCH_101 | Variable has wrong type | No | Query expects `$id: ID!`, got string |
| ARGUMENT_MISSING | E_VALIDATION_ARGUMENT_MISSING_102 | Required argument omitted | No | `users(first: 10)` missing `after` |
| ARGUMENT_TYPE_MISMATCH | E_VALIDATION_ARGUMENT_TYPE_MISMATCH_103 | Argument has wrong type | No | Query expects `first: Int!`, got string |
| ARGUMENT_INVALID_VALUE | E_VALIDATION_ARGUMENT_INVALID_VALUE_104 | Argument value out of range or invalid | No | `first: -1` (must be >= 0) |
| DEPRECATED_FIELD | E_VALIDATION_DEPRECATED_FIELD_105 | Query uses deprecated field | No | Field marked `@deprecated(reason: "...")` |
| DIRECTIVE_INVALID | E_VALIDATION_DIRECTIVE_INVALID_106 | Unknown or invalid directive | No | `@unknown_directive` |

**Example:**

```json
{
  "errors": [{
    "message": "Field 'invalid_field' not found on type 'User'",
    "locations": [{"line": 2, "column": 5}],
    "extensions": {
      "code": "E_VALIDATION_QUERY_MALFORMED_100",
      "category": "VALIDATION_FAILED",
      "remediable": true,
      "retryable": false,
      "user_actionable": true,
      "available_fields": ["id", "name", "email", "posts"],
      "suggestion": "Did you mean 'name'?"
    }
  }]
}
```

#### 2.2.2 Authorization Errors

```text
GraphQL error
Category: AUTHORIZATION_DENIED
Code: E_AUTH_<subtype>

Structure: Same as validation errors above
```

**Error Types:**

| Subtype | Code | Cause | Retryable | Example |
|---------|------|-------|-----------|---------|
| NOT_AUTHENTICATED | E_AUTH_NOT_AUTHENTICATED_200 | No auth token provided or invalid | No | Request lacks Authorization header |
| INVALID_TOKEN | E_AUTH_INVALID_TOKEN_201 | Auth token malformed or expired | No | Token signature invalid |
| INSUFFICIENT_PERMISSIONS | E_AUTH_INSUFFICIENT_PERMISSIONS_202 | User lacks required role | No | Role is "user", requires "admin" |
| INSUFFICIENT_CLAIMS | E_AUTH_INSUFFICIENT_CLAIMS_203 | Auth token lacks required claims | No | Token lacks "org_id" claim |
| ROW_LEVEL_SECURITY_DENIED | E_AUTH_ROW_LEVEL_SECURITY_DENIED_204 | RLS policy prevents access | No | User cannot access this organization's data |
| FIELD_MASKING_APPLIED | E_AUTH_FIELD_MASKED_205 | Field returned as null due to auth rule | No | Field redacted for security |
| TENANT_ISOLATION_VIOLATION | E_AUTH_TENANT_VIOLATION_206 | Query crosses tenant boundary | No | Cannot query another tenant's data |

**Example:**

```json
{
  "errors": [{
    "message": "Insufficient permissions to query 'adminUsers'",
    "extensions": {
      "code": "E_AUTH_INSUFFICIENT_PERMISSIONS_202",
      "category": "AUTHORIZATION_DENIED",
      "remediable": false,
      "retryable": false,
      "user_actionable": false,
      "required_role": "admin",
      "user_role": "user"
    }
  }]
}
```

#### 2.2.3 Database Execution Errors

```text
GraphQL error
Category: DATABASE_ERROR
Code: E_DB_<error_class>_<number>

Structure: Same as others
```

These surface when a query reads a `v_`/`tv_` view, or when a mutation calls a PostgreSQL `fn_` function. PostgreSQL reports failures via SQLSTATE codes; FraiseQL maps them onto the codes below and includes the underlying `SQLSTATE <code>` note in the extensions when available.

**Error Types:**

| Subtype | Code | SQLSTATE | Cause | Retryable | Example |
|---------|------|----------|-------|-----------|---------|
| CONNECTION_FAILED | E_DB_CONNECTION_FAILED_300 | 08006 | Cannot connect to database | **Yes** | Connection timeout, network down |
| CONNECTION_POOL_EXHAUSTED | E_DB_POOL_EXHAUSTED_301 | — | No available connections | **Yes** | All connections in use, retry later |
| QUERY_TIMEOUT | E_DB_QUERY_TIMEOUT_302 | 57014 | Statement exceeded `statement_timeout` | **Yes** | Long-running query, retry or optimize |
| DEADLOCK | E_DB_DEADLOCK_303 | 40P01 | Transaction deadlock detected | **Yes** | Concurrent transaction conflict |
| CONSTRAINT_VIOLATION | E_DB_CONSTRAINT_VIOLATION_304 | 23505 / 23503 | Unique/foreign key constraint violated | No | Duplicate key, referential integrity |
| SERIALIZATION_FAILURE | E_DB_SERIALIZATION_FAILURE_305 | 40001 | Could not serialize concurrent transactions | **Yes** | Retry the transaction |
| PERMISSION_DENIED | E_DB_PERMISSION_DENIED_306 | 42501 | Database role lacks permission | No | Misconfigured database credentials |
| OUT_OF_MEMORY | E_DB_OUT_OF_MEMORY_307 | 53200 | Database ran out of memory | **Yes** | Query too large, reduce batch size |
| DISK_FULL | E_DB_DISK_FULL_308 | 53100 | Database disk full | **Yes** | Free up disk space |
| UNKNOWN | E_DB_UNKNOWN_ERROR_309 | — | Unclassified database error | **Yes** | See error details |

**Example (Retryable):**

```json
{
  "errors": [{
    "message": "Database connection timeout after 5s",
    "extensions": {
      "code": "E_DB_CONNECTION_FAILED_300",
      "category": "DATABASE_ERROR",
      "remediable": false,
      "retryable": true,
      "retry_after_ms": 1000,
      "database": "postgresql",
      "sqlstate": "08006",
      "host": "db.example.com",
      "port": 5432,
      "attempt": 1,
      "max_attempts": 3
    }
  }]
}
```

**Example (Non-Retryable):**

```json
{
  "errors": [{
    "message": "Unique constraint violation on users.email",
    "extensions": {
      "code": "E_DB_CONSTRAINT_VIOLATION_304",
      "category": "DATABASE_ERROR",
      "remediable": true,
      "retryable": false,
      "user_actionable": true,
      "sqlstate": "23505",
      "constraint": "unique_email",
      "table": "users",
      "field": "email",
      "value": "user@example.com",
      "suggestion": "Email already exists. Use a different email or recover account."
    }
  }]
}
```

A mutation's `fn_` function can also signal a domain failure in its returned JSONB (for example, `{"success": false, "message": "...", "code": "VALIDATION_ERROR"}`). The resolver translates that into a typed `@fraiseql.error` result, which is then surfaced in the GraphQL response. This is distinct from a raw PostgreSQL execution error: a domain failure is an expected, recoverable outcome, while a SQLSTATE error indicates the statement itself could not run.

#### 2.2.4 Execution Logic Errors

```text
GraphQL error
Category: EXECUTION_ERROR
Code: E_EXEC_<subtype>

Structure: Same as others
```

**Error Types:**

| Subtype | Code | Cause | Retryable | Example |
|---------|------|-------|-----------|---------|
| FIELD_NOT_FOUND | E_EXEC_FIELD_NOT_FOUND_400 | Field absent from the view's `data` JSONB | No | View out of sync with schema |
| PROJECTION_FAILED | E_EXEC_PROJECTION_FAILED_401 | Cannot project field from data | No | Type mismatch |
| AGGREGATION_FAILED | E_EXEC_AGGREGATION_FAILED_402 | Cannot aggregate result | No | Type mismatch in aggregation |
| PAGINATION_INVALID | E_EXEC_PAGINATION_INVALID_403 | Invalid pagination parameters | No | Invalid cursor or offset |
| CURSOR_INVALID | E_EXEC_CURSOR_INVALID_404 | Pagination cursor invalid | No | Cursor expired or tampered |
| LIMIT_EXCEEDED | E_EXEC_LIMIT_EXCEEDED_405 | Query result exceeds size limit | No | Reduce page size or filter |

**Example:**

```json
{
  "errors": [{
    "message": "Query result would exceed maximum size of 100MB",
    "extensions": {
      "code": "E_EXEC_LIMIT_EXCEEDED_405",
      "category": "EXECUTION_ERROR",
      "remediable": true,
      "retryable": false,
      "user_actionable": true,
      "limit_bytes": 104857600,
      "estimated_size_bytes": 250000000,
      "suggestion": "Use pagination with smaller batch size or add more filters"
    }
  }]
}
```

#### 2.2.5 Subscription/Event Errors

```text
GraphQL error
Category: SUBSCRIPTION_ERROR
Code: E_SUB_<subtype>

Structure: Same as others (sent to client over WebSocket)
```

**Error Types:**

| Subtype | Code | Cause | Retryable | Example |
|---------|------|-------|-----------|---------|
| SUBSCRIPTION_NOT_FOUND | E_SUB_NOT_FOUND_600 | Subscription doesn't exist | No | Typo in subscription name |
| SUBSCRIPTION_FILTERS_INVALID | E_SUB_FILTERS_INVALID_601 | WHERE filters are invalid | No | Invalid filter expression |
| SUBSCRIPTION_AUTHORIZATION_DENIED | E_SUB_AUTH_DENIED_602 | Insufficient permissions | No | Role doesn't allow subscription |
| EVENT_BUFFER_OVERFLOW | E_SUB_BUFFER_OVERFLOW_603 | Event buffer full | **Yes** | Too many pending events |
| CONNECTION_CLOSED | E_SUB_CONNECTION_CLOSED_604 | WebSocket connection lost | **Yes** | Network issue, reconnect |
| EVENT_DELIVERY_FAILED | E_SUB_DELIVERY_FAILED_605 | Cannot deliver event | **Yes** | Transport issue |

**Example:**

```json
{
  "type": "error",
  "id": "1",
  "payload": {
    "errors": [{
      "message": "WebSocket connection closed unexpectedly",
      "extensions": {
        "code": "E_SUB_CONNECTION_CLOSED_604",
        "category": "SUBSCRIPTION_ERROR",
        "remediable": false,
        "retryable": true,
        "close_code": 1006,
        "reason": "connection lost",
        "reconnect_after_ms": 1000
      }
    }]
  }
}
```

#### 2.2.6 Internal Errors

```text
GraphQL error
Category: INTERNAL_ERROR
Code: E_INTERNAL_<subtype>

Structure: Same as others
```

**Error Types:**

| Subtype | Code | Cause | Retryable | Example |
|---------|------|-------|-----------|---------|
| RESOLVER_FAILED | E_INTERNAL_RESOLVER_FAILED_700 | A resolver raised an unexpected exception | No | Bug in resolver code |
| CACHE_CORRUPTED | E_INTERNAL_CACHE_CORRUPTED_701 | Cache backend returned invalid data | **Yes** | Cache corruption, retry |
| UNKNOWN_ERROR | E_INTERNAL_UNKNOWN_ERROR_702 | Unclassified internal error | **Yes** | Unknown issue, retry |

**Example:**

```json
{
  "errors": [{
    "message": "Internal server error",
    "extensions": {
      "code": "E_INTERNAL_RESOLVER_FAILED_700",
      "category": "INTERNAL_ERROR",
      "remediable": false,
      "retryable": false,
      "timestamp": "2026-01-11T15:35:00Z",
      "trace_id": "req_550e8400",
      "stack_trace": "Available only in debug mode",
      "support_link": "https://github.com/fraiseql/fraiseql/issues"
    }
  }]
}
```

---

## 3. Error Response Format

### 3.1 Standard GraphQL Error Response

All runtime errors follow the GraphQL spec with FraiseQL extensions:

```json
{
  "errors": [
    {
      "message": "Human-readable error message",
      "locations": [
        {"line": 1, "column": 1}
      ],
      "path": ["users", 0, "name"],
      "extensions": {
        "code": "E_VALIDATION_QUERY_MALFORMED_100",
        "category": "VALIDATION_FAILED",
        "remediable": true,
        "retryable": false,
        "user_actionable": true,
        "timestamp": "2026-01-11T15:35:00Z",
        "trace_id": "req_550e8400",
        "suggestion": "Did you mean field 'email'?",
        "available_options": ["id", "name", "email"],
        "retry_after_ms": null,
        "attempt": 1,
        "max_attempts": 3
      }
    }
  ],
  "data": null
}
```

The fields under `extensions` after `trace_id` are context-specific and optional; they appear only when relevant to the error.

### 3.2 Error Context Fields

**Always included:**

- `code` — Unique error identifier (E_XXX_NNN)
- `category` — Error classification (VALIDATION_FAILED, DATABASE_ERROR, etc.)
- `message` — Human-readable message
- `timestamp` — ISO 8601 timestamp
- `trace_id` — Request trace ID for logging

**Conditional fields:**

- `remediable` — Can the client fix this? (schema/query fixes)
- `retryable` — Should the client retry? (transient errors)
- `user_actionable` — Should the client show this to a user? (not security details)
- `suggestion` — How to fix it
- `retry_after_ms` — Milliseconds to wait before retry

**Context-specific:**

- `sqlstate` — The PostgreSQL SQLSTATE code (`E_DB_*` errors)
- `constraint` — Which constraint was violated (database errors)
- `field` — Which field caused the error
- `available_options` — Valid choices for this field

### 3.3 Sensitive Data Redaction

**Never expose:**

- SQL queries (even if the query is client-safe)
- Internal file paths
- Stack traces (unless debug mode)
- Database credentials
- Auth tokens or claims
- Unencrypted user data

**Safe to expose:**

- Field names (part of the schema)
- Constraint names (helps debugging)
- Error codes (for client classification)
- SQLSTATE codes (standard PostgreSQL classification)
- Operation type (query, mutation, subscription)

---

## 4. Error Classification Rules

### 4.1 Remediable vs Non-Remediable

**Remediable:** The error indicates client code or schema is wrong. The client can fix it.

Examples:

- Invalid query syntax
- Missing required field
- Constraint violation
- Deprecated field usage

**Non-Remediable:** The error indicates a system state issue. The client cannot fix it.

Examples:

- Database connection failure
- Authorization denial
- Authentication failure
- Internal server error

### 4.2 Retryable vs Non-Retryable

**Retryable:** The error is transient. Retrying may succeed.

Examples:

- Database connection timeout
- Connection pool exhausted
- Query timeout (retry with a better query)
- Serialization failure (SQLSTATE 40001)
- Event buffer overflow

**Non-Retryable:** The error is deterministic. Retrying will fail identically.

Examples:

- Schema validation error
- Authorization denial
- Constraint violation
- Invalid query syntax

### 4.3 User-Actionable vs Hidden

**User-Actionable:** The error message is safe to show end users.

Examples:

- "Email already exists"
- "You don't have permission to access this"
- "Invalid input format"

**Hidden:** The error message is for developers only, not end users.

Examples:

- "Database connection lost" (not the user's problem)
- "Query timeout after 30s" (implementation detail)
- "Insufficient permissions" (does not explain why)

---

## 5. Error Propagation

### 5.1 Query Execution Error Propagation

When an error occurs during query execution, FraiseQL follows this strategy:

```text
Query: { user { id name } posts { id title } }

Execution:
  1. Fetch user (succeeds)
  2. Fetch posts (fails with DATABASE_ERROR)

Result:
{
  "errors": [{
    "message": "Database connection lost",
    "path": ["user", "posts"],
    "extensions": { ... }
  }],
  "data": {
    "user": {
      "id": "123",
      "name": "Alice",
      "posts": null
    }
  }
}
```

**Rule:** The field with the error is set to `null` in the partial response. Parent queries continue executing. This allows clients to use partial data.

### 5.2 Mutation Error Propagation

Mutations are **atomic**: if any part fails, the entire mutation fails with no partial data. Each mutation runs inside a PostgreSQL transaction in its `fn_` function, so a failure rolls back every write.

```text
Mutation: mutation {
  createUser(input: {name: "Bob", email: "bob@example.com"}) { ... on CreateUserSuccess { user { id } } }
  createPost(input: {title: "Hello", userId: "123"}) { ... on CreatePostSuccess { post { id } } }
}

Execution:
  1. Create user (succeeds)
  2. Create post (fails with CONSTRAINT_VIOLATION - userId invalid)

Result:
{
  "errors": [{
    "message": "Foreign key constraint violated: userId not found",
    "path": ["createPost"],
    "extensions": { "code": "E_DB_CONSTRAINT_VIOLATION_304", "sqlstate": "23503", ... }
  }],
  "data": null
}
```

**Rule:** Mutations provide all-or-nothing semantics. If any part fails, all changes roll back via the database transaction.

### 5.3 Subscription Error Propagation

Subscription errors are **per-event**. One event's error does not stop the subscription.

```text
Subscription: subscription {
  orderCreated { id amount }
}

Event 1: Success
{
  "type": "next",
  "id": "1",
  "payload": {
    "data": {
      "orderCreated": {"id": "ord_1", "amount": 100}
    }
  }
}

Event 2: Authorization error
{
  "type": "error",
  "id": "2",
  "payload": {
    "errors": [{
      "message": "Insufficient permissions for this order",
      "extensions": { "code": "E_AUTH_ROW_LEVEL_SECURITY_DENIED_204", ... }
    }]
  }
}

Event 3: Success (continues after error)
{
  "type": "next",
  "id": "3",
  "payload": {
    "data": {
      "orderCreated": {"id": "ord_3", "amount": 250}
    }
  }
}
```

**Rule:** A subscription continues after an error. One error event does not close the subscription (unless `close_code` indicates a connection close).

For how these semantics interact with transactional guarantees, see [`./consistency-model.md`](./consistency-model.md). For recovery procedures when database or transport errors occur, see [`./failure-modes-and-recovery.md`](./failure-modes-and-recovery.md).

---

## 6. Error Handling for Clients

### 6.1 Recommended Client Error Handling

**Step 1: Check for errors in the response**

```python
response = await client.execute(query)
if response.get("errors"):
    # Handle errors
    ...
```

**Step 2: Classify errors by category**

```python
for error in response["errors"]:
    code = error["extensions"]["code"]
    category = error["extensions"]["category"]

    if category == "VALIDATION_FAILED":
        # Fix query and retry immediately
        ...
    elif category == "AUTHORIZATION_DENIED":
        # Request authentication, then retry
        ...
    elif category == "DATABASE_ERROR" and error["extensions"]["retryable"]:
        # Exponential backoff retry
        ...
    elif category == "INTERNAL_ERROR":
        # Log and notify support
        ...
```

**Step 3: Implement retry logic**

```python
import asyncio


async def retry_query(query: str, max_attempts: int = 3, backoff_base: int = 1000) -> dict:
    response: dict = {}
    for attempt in range(1, max_attempts + 1):
        response = await client.execute(query)

        if not response.get("errors"):
            return response  # Success

        retryable_errors = [
            e for e in response["errors"]
            if e["extensions"].get("retryable")
        ]

        if not retryable_errors:
            return response  # Non-retryable, give up

        if attempt < max_attempts:
            wait_ms = response["errors"][0]["extensions"].get(
                "retry_after_ms",
                backoff_base * (2 ** (attempt - 1)),
            )
            await asyncio.sleep(wait_ms / 1000)
    return response  # Max attempts reached
```

### 6.2 Error Display to End-Users

**Show these errors to users:**

- Validation errors with suggestions (query/input fixes)
- Constraint violations ("Email already exists")
- Authorization denials (general message, not details)
- Timeouts (with a retry option)

**Hide these errors from users:**

- Database connection details
- Internal stack traces
- SQL queries
- Auth token issues
- Internal server errors (show a support contact instead)

---

## 7. Debugging & Troubleshooting

### 7.1 Using Trace IDs

Every error includes a `trace_id` for correlation:

```text
Client sees:
{
  "errors": [{
    "message": "Database connection failed",
    "extensions": {
      "trace_id": "req_550e8400"
    }
  }]
}

Server logs:
[2026-01-11 15:35:00] TRACE req_550e8400: query { users { id } }
[2026-01-11 15:35:01] ERROR req_550e8400: connection timeout after 5s
```

**Use trace_id to:**

- Correlate client-side errors with server logs
- Track an error through the system
- Debug transient errors that are hard to reproduce

### 7.2 Debug Mode

FraiseQL can run with debug mode enabled to include additional error context. Set `production=False` in `create_fraiseql_app(...)` or the `FRAISEQL_DEBUG` environment variable in development environments only:

```text
# Enable debug mode (dev environments only)
FRAISEQL_DEBUG=true

Response with debug mode:
{
  "errors": [{
    "message": "Query timeout",
    "extensions": {
      "code": "E_DB_QUERY_TIMEOUT_302",
      "sqlstate": "57014",
      "traceback": [
        "fraiseql/db.py:312 in find",
        "psycopg/cursor_async.py:128 in execute"
      ],
      "query": "SELECT data FROM v_user WHERE id = $1",
      "bindings": ["12345"],
      "duration_ms": 30001
    }
  }]
}
```

### 7.3 Error Context Logging

Enable structured logging to capture error context:

```json
{
  "timestamp": "2026-01-11T15:35:00Z",
  "level": "ERROR",
  "trace_id": "req_550e8400",
  "category": "DATABASE_ERROR",
  "code": "E_DB_DEADLOCK_303",
  "sqlstate": "40P01",
  "operation": "mutation",
  "query_hash": "5f5a3c2b1e0d9f8c",
  "database": "postgresql",
  "user_id": "user_123",
  "tenant_id": "org_456",
  "attempt": 2,
  "duration_ms": 5234,
  "retryable": true
}
```

---

## 8. Error Codes Reference

### 8.1 Complete Error Code Catalog

| Range | Category | Count |
|-------|----------|-------|
| E_SCHEMA_* (001-009) | Schema validation | 9 |
| E_BINDING_* (010-019) | Database binding | 10 |
| E_CAPABILITY_* (020-099) | Database capability | 80 |
| E_AUTH_* (200-209) | Authorization | 10 |
| E_VALIDATION_* (100-109) | Query validation | 10 |
| E_DB_* (300-309) | Database execution | 10 |
| E_EXEC_* (400-405) | Execution logic | 6 |
| E_SUB_* (600-605) | Subscriptions | 6 |
| E_INTERNAL_* (700-702) | Internal errors | 3 |

---

## 9. Error Evolution & Stability

### 9.1 Error Code Stability Guarantee

**Error codes are stable:** Once assigned, an error code will never change meaning.

**Adding errors:** New error codes may be added in minor releases (X.Y.Z → X.Y+1.Z).

**Removing errors:** Error codes are never removed, only deprecated.

**Example:** If `E_DB_CONNECTION_FAILED_300` is used today, it will have the same meaning in 1.10, 1.11, and later releases.

See [`./versioning-strategy.md`](./versioning-strategy.md) for the full compatibility and deprecation policy.

### 9.2 Deprecation of Error Types

When an error becomes obsolete, it is marked deprecated:

```json
{
  "errors": [{
    "message": "...",
    "extensions": {
      "code": "E_OLD_ERROR_123",
      "deprecated": true,
      "deprecated_since": "1.5.0",
      "use_instead": "E_NEW_ERROR_456",
      "removal_date": "2027-01-11"
    }
  }]
}
```

---

## 10. Non-Goals

**Error handling explicitly does NOT:**

- Attempt automatic recovery (clients must handle retries)
- Hide all error details (debugging requires transparency)
- Support custom error codes (standard codes only)
- Provide error translation per locale (use standard codes)
- Guarantee error message format stability (messages evolve)

---

## Summary

FraiseQL's error handling is **deterministic and classifiable**:

- All errors fall into well-defined categories
- Each error code is stable and never changes meaning
- Errors include actionable context (retry, remediable, user-actionable)
- Partial results are possible for queries; mutations are atomic
- Clients can implement robust error handling
- Operations can debug using trace IDs and structured logs

**Golden rule:** If the error code is the same, the error is the same. Clients can build deterministic error handling logic.

---

*End of Error Handling Model*

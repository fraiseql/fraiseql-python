---
title: Mutation SQL Requirements
description: Complete guide to writing PostgreSQL functions for FraiseQL mutations with mutation_response type and error handling
tags:
  - mutations
  - postgresql
  - plpgsql
  - mutation_response
  - error handling
  - SQL functions
---

# Mutation SQL Requirements - Complete Guide

This guide provides the authoritative reference for writing PostgreSQL functions that work with FraiseQL mutations. It covers everything from basic function structure to advanced error handling patterns.

## Complete Runnable Example

```python
"""
End-to-end example: Creating a user with FraiseQL mutations.

Prerequisites:
- PostgreSQL database
- FraiseQL installed: pip install "fraiseql<2"
- Run the SQL setup below first
"""

import asyncio
from uuid import UUID
import fraiseql

# SQL Setup (run this first in your database):
SQL_SETUP = """
-- 1. Create mutation_response type (if not exists)
CREATE TYPE mutation_response AS (
    status text,
    message text,
    entity_id text,
    entity_type text,
    entity jsonb,
    updated_fields jsonb,
    cascade jsonb,
    metadata jsonb
);

-- 2. Create users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Create mutation function
CREATE OR REPLACE FUNCTION create_user(input_payload jsonb)
RETURNS mutation_response AS $$
DECLARE
    result mutation_response;
    new_user users;
BEGIN
    -- Validate input
    IF input_payload->>'name' IS NULL THEN
        result.status := 'validation:invalid_name';
        result.message := 'Name is required';
        RETURN result;
    END IF;

    -- Insert user
    INSERT INTO users (name, email)
    VALUES (
        input_payload->>'name',
        input_payload->>'email'
    )
    RETURNING * INTO new_user;

    -- Return success
    result.status := 'created';
    result.message := 'User created successfully';
    result.entity_id := new_user.id::text;
    result.entity_type := 'User';
    result.entity := row_to_json(new_user);

    RETURN result;
END;
$$ LANGUAGE plpgsql;
"""

# Python Integration:

@fraiseql.type(sql_source="users")
class User:
    id: UUID
    name: str
    email: str

@fraiseql.mutation
async def create_user(info, name: str, email: str) -> fraiseql.MutationResponse[User]:
    """Create a new user."""
    db = info.context["db"]

    # Call PostgreSQL function
    result = await db.execute(
        "SELECT * FROM create_user($1::jsonb)",
        fraiseql.json.dumps({"name": name, "email": email})
    )

    return fraiseql.MutationResponse.from_db(result[0])

async def main():
    schema = fraiseql.Schema("postgresql://localhost/mydb")

    # Execute mutation
    mutation = """
    mutation {
      createUser(name: "Alice Johnson", email: "alice@example.com") {
        status
        message
        entity {
          id
          name
          email
        }
        errors {
          code
          identifier
          message
        }
      }
    }
    """

    result = await schema.execute(mutation)

    if result.errors:
        print(f"❌ GraphQL Errors: {result.errors}")
    else:
        response = result.data['createUser']
        if response['status'] == 'created':
            print(f"✅ {response['message']}")
            print(f"   User ID: {response['entity']['id']}")
        else:
            print(f"⚠️  {response['message']}")
            for error in response.get('errors', []):
                print(f"   - {error['identifier']}: {error['message']}")

if __name__ == "__main__":
    asyncio.run(main())
```

**Expected Output (Success):**

```
✅ User created successfully
   User ID: 123e4567-e89b-12d3-a456-426614174000
```

**Expected Output (Validation Error):**

```
⚠️  Name is required
   - invalid_name: Name is required
```

---

## Quick Start (90% Use Case)

For most mutations, you only need a PostgreSQL function that returns a `mutation_response` with status strings:

```sql
CREATE OR REPLACE FUNCTION create_user(input_payload jsonb)
RETURNS mutation_response AS $$
DECLARE
    result mutation_response;
BEGIN
    -- Your business logic here
    -- ...

    -- Return success
    result.status := 'created';
    result.message := 'User created successfully';
    result.entity_id := NEW.id::text;
    result.entity_type := 'User';
    result.entity := row_to_json(NEW);
    result.updated_fields := NULL;
    result.cascade := NULL;
    result.metadata := NULL;

    RETURN result;
END;
$$ LANGUAGE plpgsql;
```

This automatically gives you structured errors in GraphQL responses without any special base classes.

## How SQL Becomes GraphQL (The Pipeline)

Understanding how FraiseQL transforms PostgreSQL responses into GraphQL helps you write effective mutations.

### The Transformation Flow

```
PostgreSQL Function Returns mutation_response (8 fields)
         ↓
Rust Pipeline Parses and Transforms
         ↓
GraphQL Error Response (root fields + errors array)
```

### Field Mapping: SQL → GraphQL

**What You Write in SQL:**

```sql
result.status := 'validation:';   -- Field 1
result.message := 'Name is required';   -- Field 2
result.metadata := NULL;                -- Field 8 (or explicit errors)
```

**What GraphQL Client Receives:**

```json
{
  "code": 422,                    // ← GENERATED by Rust from status
  "status": "validation:",  // ← SQL field 1 (passed through)
  "message": "Name is required",  // ← SQL field 2 (passed through)
  "errors": [{                    // ← GENERATED by Rust (or from metadata)
    "code": 422,                  // ← Same as root
    "identifier": "validation",   // ← EXTRACTED from "validation:"
    "message": "Name is required",// ← Copied from SQL field 2
    "details": null
  }]
}
```

### Key Insights

**You DON'T set in SQL:**

- ❌ `code` - Rust generates this from status string prefix
- ❌ `identifier` - Rust extracts this from status string after `:`
- ❌ Root-level `errors` array - Rust builds this automatically

**You DO set in SQL:**

- ✅ `status` - Use format `prefix:identifier` (e.g., `"validation:"`)
- ✅ `message` - Human-readable summary
- ✅ `metadata.errors` - (Optional) For Pattern 2 explicit errors

### Pattern 1: Auto-Generation (Simple)

**SQL:**

```sql
result.status := 'validation:';
result.message := 'Name is required';
result.metadata := NULL;  -- ← No explicit errors
```

**Rust Logic:**

1. Sees `metadata` is NULL
2. Extracts `"validation"` from `"validation:"`
3. Auto-generates `errors` array with single error

### Pattern 2: Explicit Errors (Advanced)

**SQL:**

```sql
result.status := 'validation:';
result.message := 'Multiple validation errors';
result.metadata := jsonb_build_object(
    'errors', jsonb_build_array(  -- ← Explicit errors here!
        jsonb_build_object(
            'code', 422,
            'identifier', 'invalid_email',
            'message', 'Email format invalid',
            'details', jsonb_build_object('field', 'email')
        )
    )
);
```

**Rust Logic:**

1. Sees `metadata.errors` exists
2. Uses it directly (no auto-generation)
3. Passes through to GraphQL response

**Priority:** `metadata.errors` **overrides** auto-generation.

---

## Error Handling (The FraiseQL Way™)

### Native Error Arrays

**All error responses get `errors: list[Error]` automatically.** This is populated from status strings by the Rust pipeline.

```graphql
mutation {
  createUser(input: {name: ""}) {
    __typename
    message
    code
    status
    errors {  # ← Auto-populated!
      code
      identifier
      message
      details
    }
  }
}
```

Response:

```json
{
  "data": {
    "createUser": {
      "__typename": "CreateUserError",
      "message": "Name is required",
      "code": 422,
      "status": "validation:",
      "errors": [{
        "code": 422,
        "identifier": "validation",
        "message": "Name is required",
        "details": null
      }]
    }
  }
}
```

**Note:** Error responses have both root-level fields (`code`, `message`, `status`) and an `errors` array by design. Root fields provide quick access for simple cases, while the array enables structured processing for multiple errors. See [Error Handling Patterns](./error-handling-patterns.md#response-structure-design) for detailed explanation.

### Pattern 1: Auto-Generated Errors (Recommended)

Use status strings like `"validation:"` or `"not_found:user"`. FraiseQL extracts the identifier and creates structured errors automatically.

**PostgreSQL Function:**

```sql
CREATE OR REPLACE FUNCTION create_user(input_payload jsonb)
RETURNS mutation_response AS $$
DECLARE
    result mutation_response;
    user_name text;
BEGIN
    user_name := input_payload->>'name';

    -- Validation
    IF user_name IS NULL OR length(trim(user_name)) = 0 THEN
        result.status := 'validation:';
        result.message := 'Name is required';
        RETURN result;
    END IF;

    -- Your creation logic here
    -- ...

    result.status := 'created';
    result.message := 'User created successfully';
    -- ... other fields

    RETURN result;
END;
$$ LANGUAGE plpgsql;
```

**GraphQL Response:** Errors array auto-populated from `"validation:"` → `{"identifier": "validation"}`.

### Pattern 2: Explicit Validation Errors (Advanced)

For complex validation with multiple field-level errors, use `metadata.errors`:

**PostgreSQL Function:**

```sql
CREATE OR REPLACE FUNCTION create_user(input_payload jsonb)
RETURNS mutation_response AS $$
DECLARE
    result mutation_response;
    validation_errors jsonb := '[]'::jsonb;
BEGIN
    -- Collect multiple validation errors
    IF input_payload->>'email' IS NULL THEN
        validation_errors := validation_errors || jsonb_build_object(
            'code', 422,
            'identifier', 'email_required',
            'message', 'Email is required',
            'details', '{"field": "email"}'
        );
    END IF;

    IF input_payload->>'name' IS NULL THEN
        validation_errors := validation_errors || jsonb_build_object(
            'code', 422,
            'identifier', 'name_required',
            'message', 'Name is required',
            'details', '{"field": "name"}'
        );
    END IF;

    -- If errors, return them
    IF jsonb_array_length(validation_errors) > 0 THEN
        result.status := 'validation:';
        result.message := 'Validation failed';
        result.metadata := jsonb_build_object('errors', validation_errors);
        RETURN result;
    END IF;

    -- Success case...
END;
$$ LANGUAGE plpgsql;
```

**GraphQL Response:** Uses explicit errors from `metadata.errors` instead of auto-generation.

### ~~Pattern 3: Legacy Format~~ (Deprecated)

The old format with `success`/`data`/`error` JSONB fields is deprecated. Use `mutation_response` type instead.

## PostgreSQL Requirements

### Required: mutation_response Type

All mutation functions must return this composite type:

```sql
CREATE TYPE mutation_response AS (
    status text,           -- Required: Status string (success/error/noop)
    message text,          -- Required: Human-readable message
    entity_id text,        -- Optional: ID of affected entity
    entity_type text,      -- Optional: GraphQL type name
    entity jsonb,          -- Optional: Full entity data
    updated_fields text[], -- Optional: Fields that were updated
    cascade jsonb,         -- Optional: CASCADE data for cache invalidation
    metadata jsonb         -- Optional: Extra context (explicit errors go here)
);
```

### Required: Helper Functions

Use these helper functions for consistent status handling:

```sql
-- Success states
SELECT mutation_success('User created');           -- → status: 'success'
SELECT mutation_created('User created');           -- → status: 'created'
SELECT mutation_updated('User updated');           -- → status: 'updated'
SELECT mutation_deleted('User deleted');           -- → status: 'deleted'

-- Error states
SELECT mutation_validation_error('Invalid input'); -- → status: 'validation:'
SELECT mutation_not_found('User not found');       -- → status: 'not_found:user'
SELECT mutation_error('failed:custom', 'Custom error'); -- → status: 'failed:custom'
```

### Input Handling

**Parameter:** Functions receive `jsonb` input payload:

```sql
CREATE OR REPLACE FUNCTION create_user(input_payload jsonb)
RETURNS mutation_response AS $$
BEGIN
    -- Extract fields
    DECLARE
        user_name text := input_payload->>'name';
        user_email text := input_payload->>'email';
    BEGIN
        -- Use extracted values...
    END;
END;
$$ LANGUAGE plpgsql;
```

**Type Casting:** Handle type conversion safely:

```sql
-- Safe integer conversion
user_age integer := (input_payload->>'age')::integer;

-- Safe boolean with default
is_active boolean := COALESCE((input_payload->>'is_active')::boolean, true);

-- Safe array handling
tags text[] := ARRAY(SELECT jsonb_array_elements_text(input_payload->'tags'));
```

### Output Structure

**entity field:** The created/updated entity data. Use `row_to_json()` for full rows:

```sql
result.entity := row_to_json(NEW);  -- From INSERT/UPDATE
```

**entity_type field:** GraphQL `__typename` mapping:

```sql
result.entity_type := 'User';  -- Matches your @fraiseql.type
```

**entity_id field:** String representation of the primary key:

```sql
result.entity_id := NEW.id::text;
```

**updated_fields array:** For updates, list changed fields:

```sql
result.updated_fields := ARRAY['name', 'email'];
```

**cascade field:** Cache invalidation data (advanced):

```sql
result.cascade := jsonb_build_object(
    'updated', jsonb_build_array(
        jsonb_build_object('__typename', 'User', 'id', NEW.id)
    ),
    'invalidations', jsonb_build_array('User:stats')
);
```

**metadata field:** Extra context, including explicit errors:

```sql
result.metadata := jsonb_build_object(
    'errors', validation_errors,  -- For Pattern 2
    'extra_context', 'value'      -- Any additional data
);
```

## Status Strings Reference

| Status Pattern | HTTP Code | Use Case | Example |
|----------------|-----------|----------|---------|
| `success` | 200 | Generic success | Basic operations |
| `created` | 201 | Resource creation | INSERT operations |
| `updated` | 200 | Resource update | UPDATE operations |
| `deleted` | 200 | Resource deletion | DELETE operations |
| `validation:` | 422 | Input validation | Required fields missing |
| `failed:conflict` | 409 | Business conflicts | Duplicate emails |
| `failed:forbidden` | 403 | Permission denied | Access control |
| `failed:unauthorized` | 401 | Auth required | Missing credentials |
| `not_found:{type}` | 404 | Resource missing | User not found |
| `timeout:{operation}` | 408 | Operation timeout | Database timeout |
| `noop:{reason}` | 422 | No changes made | Already exists |

## log_and_return_mutation Pattern

For complex functions, use this standardized error logging pattern:

```sql
CREATE OR REPLACE FUNCTION create_user(input_payload jsonb)
RETURNS mutation_response AS $$
DECLARE
    result mutation_response;
BEGIN
    -- Start transaction if needed
    BEGIN
        -- Your business logic here
        -- ...

        -- Success
        RETURN mutation_created('User created successfully');

    EXCEPTION
        WHEN unique_violation THEN
            -- Log and return structured error
            RETURN log_and_return_mutation(
                mutation_error('failed:conflict', 'User already exists'),
                'User creation failed due to unique constraint'
            );

        WHEN OTHERS THEN
            -- Log unexpected errors
            RETURN log_and_return_mutation(
                mutation_error('failed:internal', 'Internal error'),
                SQLERRM
            );
    END;
END;
$$ LANGUAGE plpgsql;
```

**Performance Note:** `log_and_return_mutation` adds logging overhead. Use only for unexpected errors.

## Complete Working Examples

### Example 1: Simple Create

**PostgreSQL Function:**

```sql
CREATE OR REPLACE FUNCTION create_user(input_payload jsonb)
RETURNS mutation_response AS $$
DECLARE
    new_user users;
BEGIN
    -- Insert user
    INSERT INTO users (name, email, created_at)
    VALUES (
        input_payload->>'name',
        input_payload->>'email',
        now()
    )
    RETURNING * INTO new_user;

    -- Return success
    RETURN mutation_created('User created successfully')
        WITH entity_id = new_user.id::text,
             entity_type = 'User',
             entity = row_to_json(new_user);

END;
$$ LANGUAGE plpgsql;
```

**GraphQL Schema:**

```python
@fraiseql.input
class CreateUserInput:
    name: str
    email: str

@fraiseql.success
class CreateUserSuccess:
    user: User
    message: str

@fraiseql.failure
class CreateUserError:
    message: str
    # errors array auto-populated

@fraiseql.mutation
class CreateUser:
    input: CreateUserInput
    success: CreateUserSuccess
    failure: CreateUserError
```

### Example 2: Update with Validation

**PostgreSQL Function:**

```sql
CREATE OR REPLACE FUNCTION update_user(user_id text, input_payload jsonb)
RETURNS mutation_response AS $$
DECLARE
    updated_user users;
    changed_fields text[] := ARRAY[]::text[];
BEGIN
    -- Check if user exists
    IF NOT EXISTS (SELECT 1 FROM users WHERE id = user_id::uuid) THEN
        RETURN mutation_not_found('User not found');
    END IF;

    -- Build update query dynamically
    UPDATE users SET
        updated_at = now()
        -- Add other fields conditionally
        name = CASE WHEN input_payload ? 'name'
                   THEN input_payload->>'name' ELSE name END,
        email = CASE WHEN input_payload ? 'email'
                    THEN input_payload->>'email' ELSE email END
    WHERE id = user_id::uuid
    RETURNING * INTO updated_user;

    -- Track changed fields
    IF input_payload ? 'name' THEN
        changed_fields := changed_fields || 'name';
    END IF;
    IF input_payload ? 'email' THEN
        changed_fields := changed_fields || 'email';
    END IF;

    RETURN mutation_updated('User updated successfully')
        WITH entity_id = updated_user.id::text,
             entity_type = 'User',
             entity = row_to_json(updated_user),
             updated_fields = changed_fields;

END;
$$ LANGUAGE plpgsql;
```

### Example 3: Delete with CASCADE

**PostgreSQL Function:**

```sql
CREATE OR REPLACE FUNCTION delete_user(user_id text)
RETURNS mutation_response AS $$
DECLARE
    deleted_user users;
    cascade_data jsonb;
BEGIN
    -- Check if user exists
    SELECT * INTO deleted_user FROM users WHERE id = user_id::uuid;
    IF NOT FOUND THEN
        RETURN mutation_not_found('User not found');
    END IF;

    -- Delete user (CASCADE will handle related records)
    DELETE FROM users WHERE id = user_id::uuid;

    -- Build cascade data for cache invalidation
    cascade_data := jsonb_build_object(
        'deleted', jsonb_build_array(
            jsonb_build_object(
                '__typename', 'User',
                'id', deleted_user.id
            )
        ),
        'invalidations', jsonb_build_array(
            'User:list',  -- Invalidate user lists
            'Post:author:' || deleted_user.id  -- Invalidate user's posts
        )
    );

    RETURN mutation_deleted('User deleted successfully')
        WITH cascade = cascade_data;

END;
$$ LANGUAGE plpgsql;
```

## Troubleshooting

### Common Issues

**Errors not appearing:** Check status string format. Must be `"failed:{reason}"` or `"not_found:{type}"`.

**Wrong HTTP code:** Status strings map to specific codes. See reference table above.

**CASCADE not working:** Verify `enable_cascade=True` in your mutation decorator.

**Entity not showing:** Check `entity_type` matches your GraphQL type name exactly.

### Debug Queries

Check what your function returns:

```sql
-- Test your function
SELECT * FROM create_user('{"name": "Test", "email": "test@example.com"}');

-- Should return:
-- status: "created"
-- message: "User created successfully"
-- entity_id: "uuid-here"
-- entity_type: "User"
-- entity: {...}
```

## Migration Guide

### From ad-hoc field_errors

**Before:**

```python
@fraiseql.failure
class CreateUserError(MutationResultBase):
    field_errors: dict[str, str] = None
```

**After:**

```python
@fraiseql.failure
class CreateUserError:
    message: str
    # errors array auto-populated from status strings
```

### From MutationResultBase requirement

**Before:**

```python
@fraiseql.success
class CreateUserSuccess(MutationResultBase):
    user: User

@fraiseql.failure
class CreateUserError(MutationResultBase):
    pass
```

**After:**

```python
@fraiseql.success
class CreateUserSuccess:
    user: User
    message: str

@fraiseql.failure
class CreateUserError:
    message: str
    # errors auto-populated
```

### From legacy format

**Before:**

```sql
-- Legacy format (deprecated)
RETURN jsonb_build_object(
    'success', false,
    'data', null,
    'error', 'Validation failed'
);
```

**After:**

```sql
-- New format
RETURN mutation_validation_error('Validation failed');
```

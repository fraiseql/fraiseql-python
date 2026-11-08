# Mutation Result Reference

**⚠️ This document has been consolidated into the new comprehensive guide.**

**📖 Please see: [Mutation SQL Requirements](../guides/mutation-sql-requirements.md)**

This new guide provides:

- Complete PostgreSQL function requirements
- Error handling patterns (including native error arrays)
- Working examples for all mutation types
- Migration guides from legacy formats
- Troubleshooting and best practices

---

**Legacy Content Below** (for reference during migration)

## Format Overview

FraiseQL's mutation pipeline accepts two return formats from PostgreSQL functions:

### Supported Formats

| Format | Detection | Use Case | Complexity |
|--------|-----------|----------|------------|
| **Simple** | No `status` field | Quick mutations, existing functions | Low |
| **V2** | Has valid `status` field | Full-featured mutations with errors, cascade, metadata | High |

### Auto-Detection Logic

The Rust transformation layer automatically detects format by checking for a valid mutation `status` field:

```rust
// Simple format: treated as success
{"id": "123", "name": "John"}  // No status field

// V2 format: parsed fully
{"status": "success", "entity": {...}}  // Has status field
```

**Valid status values**: `success`, `new`, `updated`, `deleted`, `completed`, `ok`, `noop:*`, `failed:*`

## Simple Format

The simple format treats any JSONB without a valid `status` field as entity data and assumes success.

### Definition

Any JSONB that doesn't contain a valid mutation status field is treated as simple format.

### Use Cases

- Quick prototyping
- Existing functions returning entity data
- Simple create/update operations
- Array responses for bulk operations

### PostgreSQL Function Example

```sql
CREATE OR REPLACE FUNCTION graphql.create_user(input jsonb)
RETURNS jsonb AS $$
DECLARE
    user_id uuid := gen_random_uuid();
BEGIN
    INSERT INTO users (id, name, email, created_at)
    VALUES (user_id, input->>'name', input->>'email', now());

    -- Return simple entity data (no status field)
    RETURN jsonb_build_object(
        'id', user_id,
        'name', input->>'name',
        'email', input->>'email',
        'created_at', now()
    );
END;
$$ LANGUAGE plpgsql;
```

### GraphQL Response

```json
{
  "data": {
    "createUser": {
      "__typename": "CreateUserSuccess",
      "message": "Success",
      "user": {
        "__typename": "User",
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "firstName": "John",
        "lastName": "Doe",
        "email": "john@example.com",
        "createdAt": "2025-01-25T10:30:00Z"
      }
    }
  }
}
```

### Array Support

Simple format supports arrays for bulk operations:

```sql
-- Bulk create returns array
RETURN jsonb_build_array(
    jsonb_build_object('id', '1', 'name', 'Alice'),
    jsonb_build_object('id', '2', 'name', 'Bob')
);
```

## Full V2 Format (mutation_response)

The v2 format uses a structured composite type for complete mutation responses.

### Composite Type Definition

```sql
CREATE TYPE mutation_response AS (
    status          text,                    -- Status string
    message         text,                    -- Human-readable message
    entity_id       text,                    -- Optional entity ID
    entity_type     text,                    -- Entity type for __typename
    entity          jsonb,                   -- Entity data
    updated_fields  text[],                  -- Changed fields
    cascade         jsonb,                   -- Side effects
    metadata        jsonb                    -- Additional data
);
```

### Status Values

FraiseQL uses a comprehensive status taxonomy parsed by the Rust layer. See [Status String Conventions](../archive/mutations/status-strings.md) for complete details.

#### Success States

- `success` - Generic success
- `new` / `created` - Entity created
- `updated` - Entity modified
- `deleted` - Entity removed
- `completed` - Operation finished
- `ok` - Alternative success

#### Noop States

- `noop:<reason>` - No changes made (e.g., `noop:unchanged`, `noop:duplicate`)

#### Error States

FraiseQL recognizes specific error prefixes that map to HTTP status codes:

- `failed:<type>` - Generic failure (500) - e.g., `failed:database_error`; `failed:validation`, `failed:not_found` etc. get the code of their reason
- `validation:<type>` - Invalid input (422) - e.g., `validation:email`
- `unauthorized:<type>` - Authentication required (401) - e.g., `unauthorized:token_expired`
- `forbidden:<type>` - Insufficient permissions (403) - e.g., `forbidden:admin_only`
- `not_found:<type>` - Resource doesn't exist (404) - e.g., `not_found:user_missing`
- `conflict:<type>` - Resource conflict (409) - e.g., `conflict:duplicate_email`
- `timeout:<type>` - Operation timeout (408/504) - e.g., `timeout:external_api`

**Note**: All status matching is case-insensitive (`FAILED:validation` = `validation:`).

### SQL Helper Functions

Use these helper functions to construct v2 responses:

#### Success Helpers

```sql
-- Generic success
SELECT mutation_success('Operation completed', entity_data, 'EntityType');

-- Entity created
SELECT mutation_created('Entity created', entity_data, 'EntityType');

-- Entity updated with specific fields
SELECT mutation_updated('Entity updated', entity_data, updated_fields, 'EntityType');

-- Entity deleted
SELECT mutation_deleted('Entity deleted', entity_id, 'EntityType');
```

#### Error Helpers

```sql
-- Validation error
SELECT mutation_validation_error('Invalid input', 'field_name');

-- Not found error
SELECT mutation_not_found('User', user_id);

-- Conflict error
SELECT mutation_conflict('Email already exists', 'duplicate');

-- Generic error
SELECT mutation_error('custom_error', 'Something went wrong');
```

#### Noop Helper

```sql
-- No changes made
SELECT mutation_noop('unchanged', 'No fields were modified');
```

### PostgreSQL Function Example

```sql
CREATE OR REPLACE FUNCTION graphql.update_user(user_id uuid, input jsonb)
RETURNS mutation_response AS $$
DECLARE
    updated_fields text[] := ARRAY[]::text[];
    user_data jsonb;
    current_user record;
BEGIN
    -- Check if user exists
    SELECT * INTO current_user FROM users WHERE id = user_id;
    IF NOT FOUND THEN
        RETURN mutation_not_found('User', user_id::text);
    END IF;

    -- Update email if provided
    IF input ? 'email' AND input->>'email' != current_user.email THEN
        -- Check uniqueness
        IF EXISTS (SELECT 1 FROM users WHERE email = input->>'email' AND id != user_id) THEN
            RETURN mutation_validation_error('Email already exists', 'email');
        END IF;
        UPDATE users SET email = input->>'email' WHERE id = user_id;
        updated_fields := array_append(updated_fields, 'email');
    END IF;

    -- Check if anything changed
    IF array_length(updated_fields, 1) = 0 THEN
        RETURN mutation_noop('unchanged', 'No fields were updated');
    END IF;

    -- Return updated data
    SELECT jsonb_build_object(
        'id', id,
        'name', name,
        'email', email,
        'updated_at', to_jsonb(updated_at)
    ) INTO user_data FROM users WHERE id = user_id;

    RETURN mutation_updated(
        'User updated successfully',
        user_data,
        updated_fields,
        'User'
    );
END;
$$ LANGUAGE plpgsql;
```

### GraphQL Response

```json
{
  "data": {
    "updateUser": {
      "__typename": "UpdateUserSuccess",
      "message": "User updated successfully",
      "user": {
        "__typename": "User",
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "firstName": "John",
        "lastName": "Smith",
        "email": "john.smith@example.com",
        "updatedAt": "2025-01-25T11:00:00Z"
      },
      "updatedFields": ["firstName", "email"]
    }
  }
}
```

## HTTP Status Code Semantics

**All GraphQL responses return HTTP 200**. This follows the GraphQL specification where errors are communicated in the response body, not via HTTP status codes.

### The `code` Field

For REST-like semantics, error responses include a `code` field with equivalent HTTP status codes:

```json
{
  "data": {
    "createUser": {
      "__typename": "CreateUserError",
      "status": "validation:",
      "code": 422,
      "message": "Email already exists",
      "errors": [
        {
          "field": "email",
          "code": "duplicate",
          "message": "Email already exists"
        }
      ]
    }
  }
}
```

### Status to Code Mapping

FraiseQL's Rust layer automatically maps status prefixes to HTTP status codes. See [Status String Conventions](../archive/mutations/status-strings.md) for complete reference.

| Status Pattern | Code | Description | Use Case |
|----------------|------|-------------|----------|
| `success`, `created`, `updated`, `deleted`, `completed`, `ok` | 200 | Success | All successful operations |
| `noop:*` | 422 | No changes (returns the error type) | Idempotent operations, no fields changed |
| `unauthorized:*`, `failed:unauthorized` | 401 | Unauthorized | Authentication required or token expired |
| `forbidden:*`, `failed:forbidden` | 403 | Forbidden | Authenticated but insufficient permissions |
| `not_found:*`, `failed:not_found` | 404 | Not Found | Resource doesn't exist |
| `timeout:*`, `failed:timeout` | 408 | Request Timeout | Operation timed out |
| `conflict:*`, `failed:conflict`, `failed:duplicate` | 409 | Conflict | Duplicate key, version conflict |
| `validation:*`, `failed:validation` | 422 | Unprocessable Entity | Invalid input data |
| `failed:*` (other) | 500 | Internal Server Error | Generic server error |

**Note**: The Rust layer performs case-insensitive matching on status prefixes.
`failed:<reason>` is read like `<reason>:`, so the trinity helpers
`mutation_validation_error`, `mutation_not_found` and `mutation_conflict`
(`failed:validation`, `failed:not_found`, `failed:duplicate`) get 422, 404 and
409. `mutation_conflict` with another `conflict_type` gives `failed:<type>`,
which is 500 unless the type is one of these words.

### Frontend Handling Example

```typescript
interface MutationResponse<T> {
  __typename: string;
  message: string;
  code?: number;  // Only present on errors
  status?: string;  // Only present on errors
  errors?: Array<{
    field?: string;
    code: string;
    message: string;
  }>;
}

// Type guard for error responses
function isErrorResponse<T>(response: MutationResponse<T>): response is MutationResponse<T> & { code: number } {
  return 'code' in response && typeof response.code === 'number';
}

// Usage
const result = await createUser({ name: "John", email: "john@example.com" });

if (isErrorResponse(result)) {
  // Handle error with REST-like status codes
  switch (result.code) {
    case 404:
      showNotFoundError(result.message);
      break;
    case 422:
      showValidationError(result.errors || []);
      break;
    case 409:
      showConflictError(result.message);
      break;
    default:
      showGenericError(result.message);
  }
} else {
  // Handle success
  showSuccess(result.message);
  updateUI(result.user);
}
```

## Error Response Shape

Error responses use the error union type and include structured error information.

### Standard Error Object Structure

```json
{
  "__typename": "MutationErrorType",
  "message": "Human-readable error message",
  "status": "failed:error_type",
  "code": 422,
  "errors": [
    {
      "field": "field_name",
      "code": "error_code",
      "message": "Field-specific error message"
    }
  ]
}
```

### The `errors` Array

The `errors` array contains detailed validation or field-specific errors:

- **`field`**: Optional field name that caused the error
- **`code`**: Machine-readable error code (e.g., "duplicate", "required", "invalid_format")
- **`message`**: Human-readable error message for this specific field/issue

### Auto-generated vs Explicit Errors

#### Auto-generated Errors

When no explicit errors are provided in `metadata.errors`, the system generates an error from the status and message:

```json
{
  "errors": [
    {
      "field": null,
      "code": "validation",  // Derived from status "validation:"
      "message": "Email already exists"
    }
  ]
}
```

#### Explicit Errors

Use `metadata.errors` for detailed field-level validation:

```sql
-- In PostgreSQL function
RETURN mutation_validation_error(
    'Validation failed',
    NULL,  -- No specific field
    jsonb_build_object(
        'errors', jsonb_build_array(
            jsonb_build_object('field', 'email', 'code', 'duplicate', 'message', 'Email already exists'),
            jsonb_build_object('field', 'password', 'code', 'too_weak', 'message', 'Password must be 8+ characters')
        )
    )
);
```

## Cascade Data

Cascade data represents side effects and related entity changes from mutations.

### Overview

Cascade data is stored in the `cascade` field and describes operations that occurred on related entities. See the [GraphQL Cascade documentation](graphql-cascade.md) for complete details.

### Integration with Mutation Formats

Both simple and v2 formats support cascade data:

```sql
-- V2 format with cascade
RETURN mutation_created(
    'User created',
    user_data,
    'User',
    cascade_entity_created('User', user_id, user_data)  -- Cascade data
);

-- Simple format with cascade (not recommended - use v2 for cascade)
-- Cascade data would be ignored in simple format
```

### SQL Helper Functions

Use these functions to construct cascade data:

```sql
-- Entity created
SELECT cascade_entity_created('User', user_id, user_data);

-- Entity updated
SELECT cascade_entity_update('User', user_id, user_data);

-- Count field updated
SELECT cascade_count_update('Organization', org_id, 'user_count', 5, 6);

-- Entity deleted
SELECT cascade_entity_deleted('User', user_id);

-- Cache invalidation
SELECT cascade_invalidate_cache(ARRAY['users', 'user_profile']);

-- Merge multiple cascades
SELECT cascade_merge(cascade1, cascade2);
```

### Example with Cascade

```sql
CREATE OR REPLACE FUNCTION graphql.create_user(input jsonb)
RETURNS mutation_response AS $$
DECLARE
    user_data jsonb;
    user_id uuid;
    cascade_data jsonb;
BEGIN
    -- Create user
    user_id := gen_random_uuid();
    INSERT INTO users (id, name, email, created_at)
    VALUES (user_id, input->>'name', input->>'email', now());

    -- Build entity data
    user_data := jsonb_build_object(
        'id', user_id,
        'name', input->>'name',
        'email', input->>'email'
    );

    -- Build cascade: update organization user count
    cascade_data := cascade_count_update(
        'Organization',
        input->>'organization_id',
        'user_count',
        5,  -- previous count
        6   -- new count
    );

    RETURN mutation_created(
        'User created successfully',
        user_data,
        'User',
        cascade_data
    );
END;
$$ LANGUAGE plpgsql;
```

---

**Related Documentation**:

- [Mutation SQL Requirements](../guides/mutation-sql-requirements.md) - Comprehensive PostgreSQL function guide
- [GraphQL Cascade](graphql-cascade.md) - Complete cascade specification
- [Migration: Add mutation_response](../../migrations/trinity/005_add_mutation_response.sql) - SQL type definition and helpers

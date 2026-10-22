---
title: Error Handling Patterns
description: Production-ready error handling strategies and patterns
tags:
  - errors
  - handling
  - patterns
  - exceptions
  - production
---

# Error Handling Patterns - Deep Dive

This guide dives deep into FraiseQL's error handling philosophy, patterns, and advanced usage. It explains why we have one opinionated way and how to use it effectively.

## Philosophy: Why One Pattern?

FraiseQL takes an opinionated stance on error handling to provide consistency and developer experience:

### Problems with Multiple Patterns

**Before (v1.7.x):**

- `field_errors: dict[str, str]` in blog_simple
- `validation_errors: list[dict]` in enterprise
- `MutationResultBase` required for errors
- Ad-hoc patterns everywhere
- Inconsistent API responses

**Result:** Confusion, scattered documentation, poor DX

### The FraiseQL Way™

**After (v1.8.1+):**

- `errors: list[Error]` on ALL error responses
- Auto-populated from status strings
- No special base classes needed
- One pattern, everywhere

**Benefits:**

- ✅ Predictable API responses
- ✅ Consistent error structure
- ✅ Better TypeScript/frontend integration
- ✅ Single source of truth
- ✅ Zero boilerplate for simple cases

## Response Structure Design

Error responses have a **two-level structure** by intentional design. Understanding this helps you use the API effectively.

### Root Level Fields (Quick Access)

```json
{
  "code": 422,                     // HTTP-like status for quick checks
  "status": "validation:",   // Domain-specific status string
  "message": "Name is required",   // Human-readable summary
  "errors": [...]                  // Detailed structured errors (see below)
}
```

**Use root fields when:**

- Quick error checks: `if (response.code === 422) { ... }`
- Display single error message: `toast.error(response.message)`
- Legacy client compatibility
- You need the overall status: `response.status === "validation:"`

### Errors Array (Structured Details)

```json
{
  "errors": [
    {
      "code": 422,                  // Same as root for consistency
      "identifier": "validation",   // Extracted from status string
      "message": "Name is required",// Field-specific or same as root
      "details": {"field": "name"}  // Optional structured context
    }
  ]
}
```

**Use errors array when:**

- Multiple validation errors to display
- Mapping errors to specific form fields
- Structured error processing: `errors.forEach(err => ...)`
- You need the machine-readable identifier
- You need error-specific details

### Why Both Root and Array?

This design supports both simple and complex use cases:

**Simple case (single error):**

```json
{
  "message": "Name is required",    // ← Quick access
  "errors": [{
    "message": "Name is required",  // ← Same value, structured format
    "identifier": "validation"
  }]
}
```

Root and errors[0] intentionally match for convenience.

**Complex case (multiple errors):**

```json
{
  "message": "Multiple validation errors",  // ← Summary
  "errors": [
    {"identifier": "invalid_email", "message": "Email format invalid"},
    {"identifier": "password_weak", "message": "Password too short"}
  ]
}
```

Root provides summary, array provides per-field details.

### Quick Reference

| Need | Use |
|------|-----|
| Check if error | `response.code >= 400` |
| Show toast notification | `response.message` |
| Get error category | `response.status` prefix |
| Loop through errors | `response.errors.forEach(...)` |
| Map to form field | `response.errors.find(e => e.details.field === 'email')` |
| Machine-readable ID | `response.errors[0].identifier` |

---

## Auto-Generated Errors (Default)

The simplest and most common pattern: status strings automatically become structured errors.

### How It Works

1. **PostgreSQL returns status string:** `"validation:"`
2. **Rust pipeline extracts identifier:** `"validation"`
3. **GraphQL response includes:** `errors: [{code: 422, identifier: "validation", ...}]`

### Status String Format

```
{prefix}:{identifier}
```

**Prefixes:**

- `failed:` - General errors (422)
- `not_found:` - Missing resources (404)
- `conflict:` - Business conflicts (409)
- `unauthorized:` - Auth issues (401)
- `forbidden:` - Permission issues (403)
- `timeout:` - Timeouts (408)
- `noop:` - No changes (422)

**Examples:**

```sql
-- Input validation
status := 'validation:'

-- User not found
status := 'not_found:user'

-- Email conflict
status := 'conflict:duplicate_email'

-- Permission denied
status := 'forbidden:insufficient_role'
```

### Auto-Generated Error Structure

```json
{
  "code": 422,
  "identifier": "validation",
  "message": "Email format invalid",
  "details": null
}
```

**Code mapping:**

- `failed:*` → 422 (Unprocessable Entity)
- `not_found:*` → 404 (Not Found)
- `conflict:*` → 409 (Conflict)
- `unauthorized:*` → 401 (Unauthorized)
- `forbidden:*` → 403 (Forbidden)
- `timeout:*` → 408 (Request Timeout)
- `noop:*` → 422 (Unprocessable Entity)

## Explicit Errors (Advanced)

For complex validation with multiple field-level errors, use `metadata.errors`.

### When to Use

- Multiple validation errors per field
- Field-level error details
- Custom error codes per error
- Complex validation logic

### PostgreSQL Implementation

```sql
CREATE OR REPLACE FUNCTION create_user(input_payload jsonb)
RETURNS mutation_response AS $$
DECLARE
    result mutation_response;
    validation_errors jsonb := '[]'::jsonb;
BEGIN
    -- Collect validation errors
    IF input_payload->>'email' IS NULL THEN
        validation_errors := validation_errors || jsonb_build_object(
            'code', 422,
            'identifier', 'email_required',
            'message', 'Email address is required',
            'details', jsonb_build_object(
                'field', 'email',
                'constraint', 'required',
                'severity', 'error'
            )
        );
    END IF;

    IF input_payload->>'name' IS NULL THEN
        validation_errors := validation_errors || jsonb_build_object(
            'code', 422,
            'identifier', 'name_required',
            'message', 'Full name is required',
            'details', jsonb_build_object(
                'field', 'name',
                'constraint', 'required'
            )
        );
    END IF;

    -- Email format validation
    IF input_payload->>'email' NOT LIKE '%@%' THEN
        validation_errors := validation_errors || jsonb_build_object(
            'code', 422,
            'identifier', 'email_invalid_format',
            'message', 'Email must contain @ symbol',
            'details', jsonb_build_object(
                'field', 'email',
                'constraint', 'format',
                'provided_value', input_payload->>'email'
            )
        );
    END IF;

    -- Return errors if any
    IF jsonb_array_length(validation_errors) > 0 THEN
        result.status := 'validation:';
        result.message := format('Validation failed with %s errors',
                               jsonb_array_length(validation_errors));
        result.metadata := jsonb_build_object('errors', validation_errors);
        RETURN result;
    END IF;

    -- Success case...
END;
$$ LANGUAGE plpgsql;
```

### Explicit Error Structure

```json
{
  "errors": [
    {
      "code": 422,
      "identifier": "email_required",
      "message": "Email address is required",
      "details": {
        "field": "email",
        "constraint": "required",
        "severity": "error"
      }
    },
    {
      "code": 422,
      "identifier": "email_invalid_format",
      "message": "Email must contain @ symbol",
      "details": {
        "field": "email",
        "constraint": "format",
        "provided_value": "invalid-email"
      }
    }
  ]
}
```

## Error Type Definition

All errors conform to this structure:

```python
@fraise_type
class Error:
    code: int           # HTTP-like status code
    identifier: str     # Machine-readable error ID
    message: str        # Human-readable message
    details: Any | None # Optional structured details
```

### Field Meanings

**code:** HTTP-inspired status codes for categorization:

- 400-499: Client errors (validation, not found, etc.)
- 500-599: Server errors

**identifier:** Machine-readable identifier for:

- Frontend error handling logic
- Translation keys
- Analytics tracking
- Debugging

**message:** Human-readable description for:

- User display
- Logs
- API documentation

**details:** Structured additional context:

- Field names for validation errors
- Constraint information
- Debug data
- Recovery suggestions

## HTTP Code Mapping

Status strings automatically map to HTTP codes:

| Status Pattern | HTTP Code | GraphQL Code | Use Case |
|----------------|-----------|--------------|----------|
| `success` | 200 | 200 | Success |
| `created` | 201 | 201 | Resource created |
| `updated` | 200 | 200 | Resource updated |
| `deleted` | 200 | 200 | Resource deleted |
| `failed:*` | 200 | 422 | Validation/general errors |
| `not_found:*` | 200 | 404 | Resource not found |
| `conflict:*` | 200 | 409 | Business conflicts |
| `unauthorized:*` | 200 | 401 | Authentication required |
| `forbidden:*` | 200 | 403 | Permission denied |
| `timeout:*` | 200 | 408 | Operation timeout |
| `noop:*` | 200 | 422 | No changes made |

**Note:** GraphQL always returns HTTP 200. The `code` field provides application-level semantics.

## Frontend Integration Examples

### TypeScript Error Handling

```typescript
interface GraphQLError {
  code: number;
  identifier: string;
  message: string;
  details?: any;
}

interface MutationResponse {
  __typename: string;
  message: string;
  code: number;
  status: string;
  errors: GraphQLError[];
}

// Handle mutation response
function handleMutationResponse<T>(response: MutationResponse & T) {
  if (response.__typename.endsWith('Error')) {
    // Handle errors
    for (const error of response.errors) {
      switch (error.identifier) {
        case 'validation':
          showValidationError(error);
          break;
        case 'not_found':
          showNotFoundError(error);
          break;
        case 'conflict':
          showConflictError(error);
          break;
        default:
          showGenericError(error);
      }
    }
  } else {
    // Handle success
    showSuccess(response.message);
  }
}
```

### React Hook Example

```typescript
function useMutationWithErrors() {
  const [mutate, { loading, error }] = useMutation(CREATE_USER);

  const handleSubmit = async (input: CreateUserInput) => {
    try {
      const result = await mutate({ variables: { input } });

      if (result.data?.createUser.__typename === 'CreateUserError') {
        const errors = result.data.createUser.errors;

        // Group by field for form validation
        const fieldErrors: Record<string, string[]> = {};
        for (const error of errors) {
          if (error.details?.field) {
            fieldErrors[error.details.field] = fieldErrors[error.details.field] || [];
            fieldErrors[error.details.field].push(error.message);
          }
        }

        setFormErrors(fieldErrors);
      } else {
        // Success
        navigate('/users');
      }
    } catch (err) {
      // GraphQL/network errors
      console.error('Mutation failed:', err);
    }
  };

  return { handleSubmit, loading };
}
```

### Vue.js Composition API

```typescript
import { ref, computed } from 'vue';
import { useMutation } from '@vue/apollo-composable';

export function useCreateUser() {
  const formErrors = ref<Record<string, string[]>>({});

  const { mutate, loading, error } = useMutation(CREATE_USER, {
    errorPolicy: 'all'
  });

  const submitForm = async (input: CreateUserInput) => {
    formErrors.value = {};

    const result = await mutate({ input });

    if (result?.data?.createUser.__typename === 'CreateUserError') {
      // Group errors by field
      const errors = result.data.createUser.errors;
      for (const error of errors) {
        const field = error.details?.field;
        if (field) {
          formErrors.value[field] = formErrors.value[field] || [];
          formErrors.value[field].push(error.message);
        }
      }
    }
  };

  const hasErrors = computed(() => Object.keys(formErrors.value).length > 0);

  return {
    submitForm,
    formErrors: readonly(formErrors),
    hasErrors,
    loading
  };
}
```

## Common Patterns

### Validation Errors

**Use case:** Form validation with multiple field errors.

```sql
-- PostgreSQL
IF name_is_invalid THEN
    errors := errors || jsonb_build_object(
        'code', 422,
        'identifier', 'name_invalid',
        'message', 'Name must be 2-50 characters',
        'details', jsonb_build_object(
            'field', 'name',
            'min_length', 2,
            'max_length', 50,
            'provided_length', length(name)
        )
    );
END IF;
```

### Authorization Errors

**Use case:** Permission checks.

```sql
-- PostgreSQL
IF NOT user_has_permission(user_id, 'create_post') THEN
    RETURN mutation_error('forbidden:insufficient_permissions',
                         'You do not have permission to create posts')
        WITH metadata = jsonb_build_object(
            'required_permission', 'create_post',
            'user_id', user_id
        );
END IF;
```

### Business Rule Violations

**Use case:** Domain logic constraints.

```sql
-- PostgreSQL
IF user_post_count_today(user_id) >= 10 THEN
    RETURN mutation_error('failed:daily_limit_exceeded',
                         'Daily post limit exceeded')
        WITH metadata = jsonb_build_object(
            'limit', 10,
            'current_count', user_post_count_today(user_id),
            'reset_time', 'midnight UTC'
        );
END IF;
```

### Not Found Errors

**Use case:** Resource lookup failures.

```sql
-- PostgreSQL
SELECT * INTO target_user FROM users WHERE id = user_id::uuid;
IF NOT FOUND THEN
    RETURN mutation_not_found('User not found');
END IF;
```

### Concurrency Conflicts

**Use case:** Optimistic locking failures.

```sql
-- PostgreSQL
UPDATE posts SET content = new_content, version = version + 1
WHERE id = post_id::uuid AND version = expected_version;

IF NOT FOUND THEN
    RETURN mutation_error('conflict:concurrent_modification',
                         'Post was modified by another user')
        WITH metadata = jsonb_build_object(
            'conflict_type', 'concurrent_modification',
            'entity_type', 'Post',
            'entity_id', post_id
        );
END IF;
```

## Migration from Legacy Patterns

### From field_errors Dictionaries

**Before:**

```python
@fraiseql.error
class CreateUserError(MutationResultBase):
    field_errors: dict[str, str] = None
```

**After:**

```python
@fraiseql.error
class CreateUserError:
    message: str
    # errors array auto-populated
```

**Migration logic:**

```sql
-- Before: Set field_errors in Python resolver
-- After: Use metadata.errors in PostgreSQL function

result.metadata := jsonb_build_object('errors', jsonb_build_array(
    jsonb_build_object(
        'code', 422,
        'identifier', 'email_required',
        'message', 'Email is required',
        'details', jsonb_build_object('field', 'email')
    )
));
```

### From ValidationError Lists

**Before:**

```python
@fraiseql.error
class ValidationError:
    validation_errors: list[dict[str, str]] = None
```

**After:**

```python
@fraiseql.error
class ValidationError:
    message: str
    # errors auto-populated from metadata.errors
```

### From MutationResultBase Dependency

**Before:**

```python
@fraiseql.error
class MyError(MutationResultBase):
    custom_field: str
```

**After:**

```python
@fraiseql.error
class MyError:
    message: str
    custom_field: str
    # errors still auto-populated
```

## Best Practices

### Error Identifier Naming

- Use `snake_case` for identifiers
- Be specific but not verbose: `email_required`, not `email_field_is_required`
- Group related errors: `validation_*`, `permission_*`, `conflict_*`
- Include context when helpful: `post_not_found`, `user_not_found`

### Error Message Guidelines

- User-friendly but informative
- Actionable when possible
- Consistent tone and style
- Include relevant values: `"Name must be 2-50 characters (got 100)"`

### Details Structure

- Use consistent field names: `field`, `constraint`, `value`, `expected`
- Include debugging info for developers
- Keep it structured for frontend consumption
- Avoid sensitive data in details

### Testing Error Scenarios

```python
def test_validation_errors():
    # Test with invalid input
    result = execute_mutation(create_user, {name: "", email: "invalid"})

    assert result.errors[0].identifier == "validation"
    assert len(result.errors) > 1  # Multiple validation errors
    assert result.errors[0].details.field == "name"
```

### Logging and Monitoring

```sql
-- Log errors for monitoring
CREATE OR REPLACE FUNCTION log_and_return_mutation(
    result mutation_response,
    log_message text
) RETURNS mutation_response AS $$
BEGIN
    -- Log to your monitoring system
    PERFORM log_error(log_message, result);

    RETURN result;
END;
$$ LANGUAGE plpgsql;
```

## Performance Considerations

### Error Generation Overhead

- Auto-generated errors: Minimal (string parsing only)
- Explicit errors: JSON construction cost
- Only occurs on error paths (not success)

### Database Function Design

- Keep validation logic close to data
- Use constraints for simple validations
- Reserve complex logic for business rules
- Consider performance impact of error aggregation

### Frontend Error Handling

- Batch error processing when possible
- Cache error messages/translations
- Use error boundaries for graceful degradation
- Provide fallbacks for unknown error types

## Troubleshooting

### Errors Not Appearing

**Check:**

- Status string format: Must be `prefix:identifier`
- Function returns `mutation_response` type
- No explicit errors in `metadata.errors` (would override)

### Wrong Error Codes

**Check:**

- Status prefix mapping (see table above)
- Explicit error codes in `metadata.errors`

### Details Not Showing

**Check:**

- `details` field is valid JSONB
- Frontend expects the structure you provide
- No null/undefined values breaking serialization

### Performance Issues

**Check:**

- Error generation only on failure paths
- JSONB construction not in hot paths
- Logging not enabled for all errors

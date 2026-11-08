# Troubleshooting Mutations

Common problems when writing FraiseQL mutations and how to solve them.

---

## Quick Diagnosis

| Symptom | Likely Cause | Section |
|---------|--------------|---------|
| No errors in response | metadata.errors malformed | [Errors Not Showing](#errors-not-showing) |
| Wrong HTTP code | Invalid status prefix | [Wrong Error Code](#wrong-error-code) |
| GraphQL validation error | Missing required fields | [Schema Mismatch](#schema-mismatch) |
| Function not found | Schema search path issue | [Function Not Found](#function-not-found) |
| CASCADE not appearing | Selection not requested | [CASCADE Missing](#cascade-missing) |
| Null entity on success | entity field not set | [Null Entity](#null-entity) |

---

## Errors Not Showing

**Problem:** GraphQL response has `code`, `status`, `message`, but `errors` array is empty or missing.

### Diagnosis

```bash
# Test function directly
SELECT * FROM your_function('{"test": "data"}'::jsonb);

# Check metadata field
SELECT metadata FROM your_function('{"test": "data"}'::jsonb);
```

### Common Causes

#### 1. Malformed metadata.errors JSONB

**Symptom:** `errors` array is empty

**Cause:** `metadata.errors` is not a valid JSONB array

```sql
-- ❌ WRONG: String instead of JSONB array
result.metadata := '{"errors": "[...]"}';

-- ❌ WRONG: Not an array
result.metadata := jsonb_build_object('errors', jsonb_build_object(...));

-- ✅ CORRECT: JSONB array
result.metadata := jsonb_build_object(
    'errors', jsonb_build_array(
        jsonb_build_object('code', 422, 'identifier', 'validation', ...)
    )
);
```

#### 2. Missing Required Error Fields

**Symptom:** Rust pipeline error in logs

**Cause:** `metadata.errors` objects missing required fields

```sql
-- ❌ WRONG: Missing 'message' field
jsonb_build_object('code', 422, 'identifier', 'validation')

-- ✅ CORRECT: All required fields
jsonb_build_object(
    'code', 422,
    'identifier', 'validation',
    'message', 'Validation failed',
    'details', null
)
```

#### 3. Pattern 1 Status String Format Invalid

**Symptom:** Auto-generated error has `identifier: "general_error"`

**Cause:** Status string doesn't follow `prefix:identifier` format

```sql
-- ❌ WRONG: No colon separator
result.status := 'failed_validation';  -- → identifier: "general_error"

-- ✅ CORRECT: Use colon
result.status := 'validation:';  -- → identifier: "validation"
```

### Solution

**Validate your status string:**

```sql
-- Add assertion in your function
ASSERT result.status ~ '^(created|updated|deleted|failed|not_found|conflict|noop)(:.+)?$',
    format('Invalid status format: %s', result.status);
```

---

## Wrong Error Code

**Problem:** Getting `422` when you expect `404`, or vice versa.

### Diagnosis

```bash
# Check what code your status generates
SELECT status,
    CASE
        WHEN status LIKE 'failed:%' THEN 422
        WHEN status LIKE 'not_found:%' THEN 404
        WHEN status LIKE 'conflict:%' THEN 409
        -- ... etc
    END as expected_code
FROM your_function(...);
```

### Common Causes

#### Wrong Status Prefix

```sql
-- ❌ WRONG: Using 'failed:' for not found
result.status := 'failed:user_not_found';  -- → 422

-- ✅ CORRECT: Use 'not_found:' prefix
result.status := 'not_found:user';  -- → 404
```

### Status Prefix to Code Mapping

| Prefix | Code | Use For |
|--------|------|---------|
| `failed:` | 422 | Validation, business logic errors |
| `not_found:` | 404 | Resource doesn't exist |
| `conflict:` | 409 | Duplicates, constraint violations |
| `unauthorized:` | 401 | Missing authentication |
| `forbidden:` | 403 | Permission denied |
| `timeout:` | 408 | Operation timeout |
| `noop:` | 422 | No changes made |

---

## Schema Mismatch

**Problem:** GraphQL validation error: "Field 'X' not found in type 'CreateUserError'"

### Diagnosis

Check your Python type definitions match SQL output:

```python
@fraiseql.error
class CreateUserError:
    status: str
    message: str
    code: int
    errors: list[Error]  # ← Make sure this is present!
```

### Common Causes

#### 1. Missing `errors` Field in Error Type

```python
# ❌ WRONG: No errors field
@fraiseql.error
class CreateUserError:
    status: str
    message: str
    code: int
    # Missing: errors: list[Error]

# ✅ CORRECT: Include errors
@fraiseql.error
class CreateUserError:
    status: str
    message: str
    code: int
    errors: list[Error]  # Auto-populated by Rust
```

#### 2. Wrong Field Names

GraphQL is case-sensitive and follows camelCase (if `auto_camel_case=True`).

```python
# Python definition (snake_case)
class CreateUserError:
    error_code: int  # ← Will become "errorCode" in GraphQL

# GraphQL query must match
mutation {
  createUser {
    errorCode  # ← Must use camelCase
  }
}
```

---

## Function Not Found

**Problem:** `ERROR: function app.create_user(jsonb) does not exist`

### Diagnosis

```sql
-- Check function exists
SELECT proname, pronamespace::regnamespace
FROM pg_proc
WHERE proname = 'create_user';

-- Check search path
SHOW search_path;
```

### Common Causes

#### 1. Wrong Schema

```sql
-- Function created in different schema
CREATE FUNCTION public.create_user(...) -- ← Created in 'public'

-- But app expects 'app' schema
-- FraiseQL looks in: app schema first, then search_path
```

**Solution:**

```sql
-- Option 1: Create in 'app' schema
CREATE FUNCTION app.create_user(...)

-- Option 2: Set search path
ALTER DATABASE your_db SET search_path TO app, public;
```

#### 2. Wrong Signature

```sql
-- Function defined with different parameter
CREATE FUNCTION create_user(data json) -- ← json not jsonb

-- But called with jsonb
SELECT create_user('{"test": 1}'::jsonb);  -- ← Fails
```

**Solution:** Use `jsonb` consistently:

```sql
CREATE FUNCTION create_user(input_payload jsonb)
```

---

## CASCADE Missing

**Problem:** `cascade` field is null in response even though function returns CASCADE data.

### Diagnosis

```sql
-- Check function returns cascade
SELECT cascade FROM your_function(...)::mutation_response;
```

### Common Cause

**GraphQL query doesn't select cascade field:**

```graphql
# ❌ WRONG: Not requesting cascade
mutation {
  createUser(input: {...}) {
    user { id }
    # Missing: cascade { ... }
  }
}

# ✅ CORRECT: Request cascade
mutation {
  createUser(input: {...}) {
    user { id }
    cascade {  # ← Must explicitly request
      updated { ... }
      deleted { ... }
    }
  }
}
```

**Why:** FraiseQL only includes CASCADE if selected (GraphQL spec compliance).

---

## Null Entity

**Problem:** Success response has `user: null` instead of entity data.

### Diagnosis

```sql
-- Check entity field
SELECT entity FROM your_function(...)::mutation_response;
```

### Common Causes

#### 1. Forgot to Set entity Field

```sql
-- ❌ WRONG: entity not set
result.status := 'created';
result.message := 'User created';
RETURN result;  -- entity is NULL

-- ✅ CORRECT: Set entity
result.status := 'created';
result.message := 'User created';
result.entity := row_to_json(NEW);  -- ← Set entity!
RETURN result;
```

#### 2. Using OLD Instead of NEW

```sql
-- ❌ WRONG: OLD is the pre-UPDATE state
UPDATE users SET name = new_name WHERE id = user_id
RETURNING * INTO user_record;

result.entity := row_to_json(OLD);  -- ← OLD data!

-- ✅ CORRECT: Use NEW or RETURNING
UPDATE users SET name = new_name WHERE id = user_id
RETURNING * INTO user_record;

result.entity := row_to_json(user_record);  -- ← Updated data
```

#### 3. Entity Not Found (DELETE)

```sql
-- DELETE operations: entity should be null (deleted)
result.status := 'deleted';
result.message := 'User deleted';
result.entity := NULL;  -- ← Correct for DELETE
result.entity_id := old_user_id::text;  -- ← Use entity_id instead
```

---

## Performance Issues

**Problem:** Mutation is slow.

### Diagnosis

```sql
EXPLAIN ANALYZE SELECT * FROM your_function(...);
```

### Common Causes

#### 1. Missing Index

```sql
-- Slow: No index on email
SELECT * FROM users WHERE email = user_email;

-- Fix: Add index
CREATE INDEX idx_users_email ON users(email);
```

#### 2. N+1 Queries in CASCADE

```sql
-- ❌ SLOW: Loop with individual queries
FOR record IN SELECT * FROM related_table LOOP
    -- Multiple queries
END LOOP;

-- ✅ FAST: Single batch query
SELECT jsonb_agg(row_to_json(r))
FROM related_table r
WHERE r.parent_id = entity_id;
```

---

## Performance Issues

**Problem:** Mutation is slow.

### Diagnosis

```sql
EXPLAIN ANALYZE SELECT * FROM your_function(...);
```

### Common Causes

#### 1. Missing Index

```sql
-- Slow: No index on email
SELECT * FROM users WHERE email = user_email;

-- Fix: Add index
CREATE INDEX idx_users_email ON users(email);
```

#### 2. N+1 Queries in CASCADE

```sql
-- ❌ SLOW: Loop with individual queries
FOR record IN SELECT * FROM related_table LOOP
    -- Multiple queries
END LOOP;

-- ✅ FAST: Single batch query
SELECT jsonb_agg(row_to_json(r))
FROM related_table r
WHERE r.parent_id = entity_id;
```

#### 3. Large JSONB Objects

```sql
-- ❌ SLOW: Building huge nested objects
result.metadata := jsonb_build_object(
    'all_related_data', (SELECT jsonb_agg(*) FROM massive_table)
);

-- ✅ FAST: Only include necessary data
result.metadata := jsonb_build_object(
    'related_count', (SELECT COUNT(*) FROM massive_table WHERE ...)
);
```

#### 4. Missing WHERE Clause

```sql
-- ❌ SLOW: Full table scan
UPDATE users SET last_seen = now();

-- ✅ FAST: Specific rows
UPDATE users SET last_seen = now() WHERE id = user_id;
```

#### 5. Redundant row_to_json Calls

```sql
-- ❌ SLOW: Converting same data multiple times
result.entity := row_to_json(user_record);
result.metadata := jsonb_build_object('user', row_to_json(user_record));

-- ✅ FAST: Convert once, reuse
DECLARE entity_json jsonb := row_to_json(user_record);
result.entity := entity_json;
result.metadata := jsonb_build_object('user', entity_json);
```

### Performance Tips

1. **Use EXPLAIN ANALYZE** - Always measure, don't guess
2. **Add indexes** - On foreign keys, frequently queried columns
3. **Batch operations** - Use jsonb_agg instead of loops
4. **Limit CASCADE data** - Only return what's needed
5. **Use FOR UPDATE SKIP LOCKED** - For queue-based patterns
6. **Avoid SELECT *** - Select only needed columns

---

## Debug Checklist

When mutation isn't working, follow this systematic checklist:

### 1. Test SQL Directly (Isolate the Issue)

```sql
-- Test function in psql
SELECT * FROM your_function('{"test": "data"}'::jsonb);

-- Check raw JSON output
SELECT row_to_json(your_function('{"test": "data"}'::jsonb));
```

**What to look for:**

- Does function return a result?
- Is the result structure correct?
- Any PostgreSQL errors?

### 2. Validate Response Structure

```sql
-- Check status format
SELECT status ~ '^(created|updated|deleted|failed|not_found|conflict|unauthorized|forbidden|timeout|noop)(:.+)?$' as valid_status
FROM your_function(...);

-- Validate metadata.errors if present
SELECT jsonb_typeof(metadata->'errors') = 'array' as is_array,
       jsonb_array_length(metadata->'errors') as error_count
FROM your_function(...);

-- Use validation helpers
SELECT validate_mutation_response(your_function(...)::mutation_response);
```

### 3. Check Python Type Definitions

**Error types must have:**

```python
@fraiseql.error
class YourError:
    status: str
    message: str
    code: int
    errors: list[Error]  # ← Required!
```

**Success types must have:**

```python
@fraiseql.success
class YourSuccess:
    entity: YourEntity  # ← Your entity type
    # Optional: cascade, metadata, etc.
```

### 4. Verify GraphQL Query

```graphql
# ❌ WRONG: Not requesting errors array
mutation {
  yourMutation(input: {...}) {
    ... on YourError {
      status
      message
      # Missing: errors { ... }
    }
  }
}

# ✅ CORRECT: Request all fields
mutation {
  yourMutation(input: {...}) {
    ... on YourError {
      status
      message
      code
      errors {
        code
        identifier
        message
        details
      }
    }
  }
}
```

### 5. Check Field Naming (camelCase vs snake_case)

```python
# If auto_camel_case=True in schema
class YourType:
    entity_id: str  # ← Becomes "entityId" in GraphQL

# GraphQL query must match:
{
  yourMutation {
    entityId  # ← camelCase
  }
}
```

### 6. Review Error Logs

```bash
# Application logs
tail -f /var/log/your-app/app.log

# PostgreSQL logs (if slow queries)
tail -f /var/log/postgresql/postgresql-14-main.log

# FraiseQL/Rust pipeline logs (if available)
tail -f /var/log/fraiseql/mutations.log
```

### 7. Common Quick Fixes

```sql
-- Missing message field
result.message := 'Your message here';  -- Always required!

-- Forgot to set entity
result.entity := row_to_json(NEW);  -- For success responses

-- Wrong status prefix
result.status := 'not_found:user';  -- NOT 'failed:user_not_found'

-- Malformed errors array
result.metadata := jsonb_build_object(
    'errors', jsonb_build_array(  -- Must be array!
        build_error_object(422, 'id', 'msg', null)
    )
);
```

### 8. Debug Tips

- **Start simple:** Test with minimal valid input first
- **Add logging:** Use `RAISE NOTICE 'value: %', variable;` to debug
- **Check permissions:** Ensure database user has necessary privileges
- **Verify schema:** `\df your_function` in psql shows function signature
- **Test in transaction:** `BEGIN; SELECT your_function(...); ROLLBACK;`

---

## Getting Help

Still stuck?

1. **Check Examples:** `examples/mutation-patterns/` has real-world cases
2. **Read Full Guide:** [Mutation SQL Requirements](./mutation-sql-requirements.md)
3. **GitHub Issues:** Search existing issues or create new one
4. **Discussions:** Ask in GitHub Discussions for community help

**Include in bug reports:**

- SQL function code
- GraphQL query
- Expected vs actual response
- PostgreSQL version
- FraiseQL version

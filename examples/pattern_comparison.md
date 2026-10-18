# Pattern Comparison Guide

## Basic vs Enterprise Patterns

### Mutation Responses

**Basic Pattern (todo_quickstart.py):**

```python
async def create_user(info, input: CreateUserInput) -> User:
    # Simple success/error handling
    user_id = await db.call_function("create_user", ...)
    return User.from_dict(result)
```

**Enterprise Pattern (blog_api/):**

```python
@fraiseql.mutation(function="create_user", schema="app")
class CreateUser:
    input: CreateUserInput
    success: CreateUserSuccess  # With metadata
    error: CreateUserError      # With context; a "noop:" status also returns it
```

### Function Architecture

**Basic Pattern:**

```sql
-- Single function with mixed concerns
CREATE FUNCTION create_user(input_data JSONB) RETURNS JSONB;
```

**Enterprise Pattern:**

```sql
-- App layer: Input handling
CREATE FUNCTION app.create_user(...) RETURNS app.mutation_result;

-- Core layer: Business logic
CREATE FUNCTION core.create_user(...) RETURNS app.mutation_result;
```

## When to Use Each Pattern

| Feature | Basic | Enterprise | Use When |
|---------|-------|-----------|----------|
| Simple CRUD | ✅ | ✅ | Learning, prototypes |
| Audit trails | ❌ | ✅ | Compliance required |
| NOOP handling | ❌ | ✅ | Idempotency needed |
| Complex validation | ❌ | ✅ | Business rules complex |
| Change tracking | ❌ | ✅ | Data governance required |

## Migration Path

1. Start with basic patterns for prototyping
2. Add mutation result pattern for better error handling
3. Implement audit fields for compliance
4. Add NOOP handling for reliability
5. Split functions for complex business logic

## Example Comparison Matrix

| Example | Complexity | Patterns Used | Best For |
|---------|------------|---------------|----------|
| `todo_quickstart.py` | Basic | Simple mutations | Learning FraiseQL |
| `blog_api/` | Intermediate | Mutation results, basic audit | Content management |
| `enterprise_patterns/` | Full | All patterns | Production systems |

## Pattern Evolution

### Stage 1: Basic CRUD

```python
# Simple, direct approach
@fraiseql.query
async def users(info) -> list[User]:
    return await info.context["db"].find("users")

@fraiseql.mutation
async def create_user(info, input: CreateUserInput) -> User:
    result = await info.context["db"].call_function("create_user", input.dict())
    return User.from_dict(result)
```

### Stage 2: Structured Responses

```python
# Add success/error structure
@fraiseql.mutation
class CreateUser:
    input: CreateUserInput
    success: CreateUserSuccess  # @fraiseql.success
    error: CreateUserError      # @fraiseql.error
```

### Stage 3: Business Logic Handling

```python
# Add NOOP for business rules: the SQL function returns a "noop:..." status,
# which comes back as CreateUserError
@fraiseql.mutation
class CreateUser:
    input: CreateUserInput
    success: CreateUserSuccess  # @fraiseql.success
    error: CreateUserError      # @fraiseql.error
```

### Stage 4: Full Enterprise

```python
# Complete audit, validation, and error handling
@fraiseql.mutation(function="create_user", schema="app")  # app/core split
class CreateUser:
    input: CreateUserInput            # With validation
    success: CreateUserSuccess        # With audit trail
    error: CreateUserError            # With field errors and "noop:" business context
```

## Code Comparison Examples

### Error Handling Evolution

**Basic:**

```python
try:
    user = await create_user(input)
    return user
except Exception as e:
    raise GraphQLError(str(e))
```

**Enterprise:**

```python
# Structured error with native error arrays
class CreateUserError:
    """Error response with clean patterns."""
    message: str
    errors: list[FraiseQLError] = []  # Native error arrays
    field_errors: dict[str, str] | None = None
    validation_context: dict[str, Any] | None = None
```

### Validation Evolution

**Basic:**

```python
@fraiseql.input
class CreateUserInput:
    email: str
    name: str
```

**Enterprise:**

```python
@fraiseql.input
class CreateUserInput:
    email: Annotated[str, Field(regex=r"^[^@]+@[^@]+\.[^@]+$")]
    name: Annotated[str, Field(min_length=2, max_length=100)]
    _change_reason: str | None = None
    _expected_version: int | None = None
```

### Database Function Evolution

**Basic:**

```sql
CREATE FUNCTION create_user(input_data JSONB) RETURNS JSONB AS $$
BEGIN
    INSERT INTO users (email, name, data)
    VALUES (
        input_data->>'email',
        input_data->>'name',
        input_data
    );
    -- Return whatever
END;
$$ LANGUAGE plpgsql;
```

**Enterprise:**

```sql
-- App layer: Input sanitization
CREATE FUNCTION app.create_user(
    input_pk_organization UUID,
    input_created_by UUID,
    input_payload JSONB
) RETURNS app.mutation_result AS $$
DECLARE
    v_input app.type_user_input;
BEGIN
    v_input := jsonb_populate_record(NULL::app.type_user_input, input_payload);
    RETURN core.create_user(input_pk_organization, input_created_by, v_input, input_payload);
END;
$$ LANGUAGE plpgsql;

-- Core layer: Business logic
CREATE FUNCTION core.create_user(
    input_pk_organization UUID,
    input_created_by UUID,
    input_data app.type_user_input,
    input_payload JSONB
) RETURNS app.mutation_result AS $$
BEGIN
    -- Check for duplicate email (NOOP case)
    IF EXISTS (SELECT 1 FROM tenant.tb_user WHERE data->>'email' = input_data.email) THEN
        RETURN core.log_and_return_mutation(
            input_pk_organization, input_created_by, 'user', NULL,
            'NOOP', 'noop:email_exists', ARRAY[]::TEXT[],
            'User with this email already exists',
            NULL, NULL,
            jsonb_build_object('attempted_email', input_data.email)
        );
    END IF;

    -- Create user with audit trail
    -- Full business logic here...

    RETURN core.log_and_return_mutation(...);
END;
$$ LANGUAGE plpgsql;
```

## Decision Tree

Use this tree to choose the right pattern:

```
Is this a learning/prototype project?
├─ Yes → Use Basic patterns (todo_quickstart.py)
└─ No → Do you need audit trails?
    ├─ No → Use Intermediate patterns (blog_api basic)
    └─ Yes → Do you need NOOP handling?
        ├─ No → Use Advanced patterns (blog_api enterprise)
        └─ Yes → Do you have complex business rules?
            ├─ No → Use blog_api with NOOP
            └─ Yes → Use Full Enterprise patterns
```

## Performance Implications

| Pattern | Query Complexity | Function Calls | Memory Usage | Best For |
|---------|------------------|----------------|--------------|----------|
| Basic | Low | 1 per mutation | Minimal | < 1000 users |
| Intermediate | Medium | 1-2 per mutation | Low | < 10k users |
| Advanced | Medium-High | 2-3 per mutation | Medium | < 100k users |
| Enterprise | High | 3-5 per mutation | Higher | Production scale |

Choose based on your scale and complexity requirements.

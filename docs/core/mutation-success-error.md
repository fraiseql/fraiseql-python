# Mutation Success and Error Types

FraiseQL provides `@success` and `@error` decorators for defining mutation response types with automatic field injection.

## Overview

Mutations in FraiseQL return **union types** with success and error cases:

```python
@fraiseql.mutation(result_name="CreateUserResult")
class CreateUser:
    input: CreateUserInput
    success: UserCreated      # Success case
    failure: ValidationError  # Error case (uses @error decorated class)
```

**GraphQL Result**:

```graphql
union CreateUserResult = UserCreated | ValidationError

type Mutation {
  createUser(input: CreateUserInput!): CreateUserResult!
}
```

---

## @success Decorator

### Auto-Injected Fields

The `@success` decorator automatically adds standard fields to your success type:

```python
from fraiseql.types import ID

@fraiseql.success
class UserCreated:
    user: User  # Your custom field

    # ✅ Auto-injected (don't add these manually):
    # status: str = "success"
    # message: str | None = None
    # updated_fields: list[str] | None = None
    # id: ID | None = None
```

### Generated GraphQL Type

```graphql
type UserCreated {
  # Your fields:
  user: User!

  # Auto-injected fields:
  status: String!            # Always "success"
  message: String            # Optional success message
  updatedFields: [String!]   # List of fields that were updated
  id: ID                   # ID of created/updated resource
}
```

### Example Response

```json
{
  "data": {
    "createUser": {
      "status": "success",
      "message": null,
      "user": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "name": "John Doe",
        "email": "john@example.com"
      },
      "updatedFields": null,
      "id": "550e8400-e29b-41d4-a716-446655440000"
    }
  }
}
```

---

## @error Decorator

### Basic Usage

Define error types with custom fields:

```python
@fraiseql.error
class ValidationError:
    message: str
    code: str = "VALIDATION_ERROR"
    field: str | None = None
```

**Note**: `@error` does NOT auto-inject fields like `@success` does. You define all fields explicitly.

### Generated GraphQL Type

```graphql
type ValidationError {
  message: String!
  code: String!
  field: String
}
```

### Example Response

```json
{
  "data": {
    "createUser": {
      "message": "Email is already taken",
      "code": "VALIDATION_ERROR",
      "field": "email"
    }
  }
}
```

---

## Complete Mutation Example

```python
import fraiseql
from fraiseql.types import ID

# Input type
@fraiseql.input
class CreateUserInput:
    name: str
    email: str
    password: str

# Success type (auto-injected fields)
@fraiseql.success
class UserCreated:
    user: User
    message: str = "User created successfully"  # Custom default

# Error type (explicit fields only)
@fraiseql.error
class ValidationError:
    message: str
    code: str = "VALIDATION_ERROR"
    field: str | None = None

# Mutation definition
@fraiseql.mutation(result_name="CreateUserResult")
class CreateUser:
    input: CreateUserInput
    success: UserCreated
    failure: ValidationError  # Note: 'failure' field, NOT '@failure' decorator

    async def resolve(self, info) -> UserCreated | ValidationError:
        db = info.context["db"]

        # Validate input
        if not self.input.email:
            return ValidationError(
                message="Email is required",
                field="email"
            )

        # Call PostgreSQL function
        try:
            result = await db.execute_function("fn_create_user", {
                "name": self.input.name,
                "email": self.input.email,
                "password": self.input.password
            })

            if not result.get("success"):
                return ValidationError(
                    message=result.get("error", "Unknown error")
                )

            # Fetch created user
            user = await db.find_one("v_user", id=result["id"])

            # Return success (auto-injected fields included)
            return UserCreated(user=user)

        except Exception as e:
            return ValidationError(
                message=f"Failed to create user: {e!s}"
            )
```

---

## Auto-Injected Fields Deep Dive

### status

**Type**: `str`
**Default**: `"success"`
**Purpose**: Indicates successful mutation execution

```python
@fraiseql.success
class UserCreated:
    user: User
    # status is auto-set to "success"
```

**GraphQL**:

```graphql
{
  createUser {
    status  # Returns "success"
  }
}
```

### message

**Type**: `str | None`
**Default**: `None`
**Purpose**: Optional human-readable success message

```python
@fraiseql.success
class UserCreated:
    user: User
    message: str = "User created successfully"  # Override default
```

**GraphQL**:

```graphql
{
  createUser {
    message  # Returns "User created successfully"
  }
}
```

### updated_fields

**Type**: `list[str] | None`
**Default**: `None`
**Purpose**: List of fields that were modified (useful for updates)

```python
@fraiseql.success
class UserUpdated:
    user: User
    # updated_fields can be set manually if needed

# In resolver:
return UserUpdated(
    user=updated_user,
    updated_fields=["name", "email"]  # Explicitly set
)
```

**GraphQL**:

```graphql
{
  updateUser {
    updatedFields  # Returns ["name", "email"]
  }
}
```

### id

**Type**: `UUID | None`
**Default**: `None`
**Purpose**: ID of the created or updated resource

```python
@fraiseql.success
class UserCreated:
    user: User
    # id can be set manually

# In resolver:
return UserCreated(
    user=new_user,
    id=new_user.id  # Explicitly set
)
```

**GraphQL**:

```graphql
{
  createUser {
    id    # Returns UUID of created user
    user {
      id  # Same UUID
    }
  }
}
```

---

## Customizing Auto-Injected Fields

### Override Defaults

```python
@fraiseql.success
class UserCreated:
    user: User
    message: str = "User created successfully"  # Custom default message
    # status, updated_fields, id still auto-injected with defaults
```

### Disable Auto-Injection (Advanced)

If you need full control and don't want auto-injection:

```python
from fraiseql.types import ID

# Option 1: Use a regular class (not @success)
class UserCreatedManual:
    user: User
    custom_field: str

# Option 2: Override all auto-injected fields
@fraiseql.success
class UserCreatedCustom:
    user: User
    status: str = "created"  # Override "success" default
    message: str = "User created"
    updated_fields: list[str] = []
    id: ID | None = None
```

---

## Common Patterns

### Simple Success Response

```python
@fraiseql.success
class UserCreated:
    user: User
    # That's it! Auto-injected fields handle the rest
```

### Success with Custom Message

```python
@fraiseql.success
class UserCreated:
    user: User
    message: str = "User created and welcome email sent"
```

### Update Success with Updated Fields

```python
@fraiseql.success
class UserUpdated:
    user: User

# In resolver:
return UserUpdated(
    user=updated_user,
    updated_fields=["name", "email"],  # Explicitly list changed fields
    message=f"Updated {len(updated_fields)} fields"
)
```

### Multiple Error Types

```python
@fraiseql.error
class ValidationError:
    message: str
    code: str = "VALIDATION_ERROR"
    field: str | None = None

@fraiseql.error
class AuthorizationError:
    message: str
    code: str = "UNAUTHORIZED"

@fraiseql.mutation(result_name="UpdateUserResult")
class UpdateUser:
    input: UpdateUserInput
    success: UserUpdated
    failure: ValidationError | AuthorizationError  # Union of error types
```

---

## Best Practices

### 1. Use Descriptive Error Codes

```python
@fraiseql.error
class ValidationError:
    message: str
    code: str = "VALIDATION_ERROR"  # Clear, uppercase, specific
    field: str | None = None
```

**Error codes should be:**

- UPPERCASE_SNAKE_CASE
- Descriptive (VALIDATION_ERROR, not ERR001)
- Unique across your application

### 2. Include Field Names in Validation Errors

```python
if not self.input.email:
    return ValidationError(
        message="Email is required",
        field="email",  # ✅ Helps client highlight the right field
        code="REQUIRED_FIELD"
    )
```

### 3. Leverage Auto-Injected message for User Feedback

```python
@fraiseql.success
class UserCreated:
    user: User
    message: str = "Welcome! Your account has been created."  # User-friendly message
```

### 4. Use updated_fields for Audit Trails

```python
@fraiseql.success
class UserUpdated:
    user: User

# In resolver:
changed_fields = []
if old_user.name != new_user.name:
    changed_fields.append("name")
if old_user.email != new_user.email:
    changed_fields.append("email")

return UserUpdated(
    user=new_user,
    updated_fields=changed_fields  # Audit trail
)
```

---

## Comparison with Other Frameworks

### Relay-Style Mutations (GraphQL Best Practice)

**Traditional Relay**:

```graphql
type CreateUserPayload {
  userEdge: UserEdge
  clientMutationId: String
}
```

**FraiseQL Equivalent**:

```python
@fraiseql.success
class UserCreated:
    user: User
    # Auto-injected fields (status, message, id) provide similar metadata
```

### Strawberry (Python)

**Strawberry**:

```python
@strawberry.type
class CreateUserSuccess:
    user: User
    message: str = "User created"
    # Must manually define all fields
```

**FraiseQL**:

```python
@fraiseql.success
class UserCreated:
    user: User
    # Auto-injected: status, message, updated_fields, id
    # 60% less boilerplate!
```

---

## GraphQL Queries

### Query Success Fields

```graphql
mutation {
  createUser(input: {name: "John", email: "john@example.com"}) {
    ... on UserCreated {
      status        # Auto-injected
      message       # Auto-injected
      id            # Auto-injected
      user {
        id
        name
        email
      }
    }
    ... on ValidationError {
      message
      code
      field
    }
  }
}
```

### Conditional Fragments

```graphql
mutation {
  createUser(input: {name: "John", email: "john@example.com"}) {
    __typename
    ... on UserCreated {
      status
      user {
        id
      }
    }
    ... on ValidationError {
      message
    }
  }
}
```

---

## See Also

- [Mutations Guide](../reference/mutations-api.md) - Complete mutation documentation
- [Auto-Inference](auto-inference.md) - Other auto-inference features
- [Quick Reference](../reference/quick-reference.md) - Mutation patterns cheatsheet

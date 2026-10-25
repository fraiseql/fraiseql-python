# Rust Mutation Pipeline Examples

These examples call `build_mutation_response`, the Rust function that turns a SQL
function's result into the GraphQL response of a mutation. Applications don't call it:
a class mutation (`@fraiseql.mutation`) does, with the selection of the request. Calling
it directly is useful to see what the pipeline does with a given result, or in tests.

The extension ships inside the `fraiseql` package (there is no separate `fraiseql_rs`
module to import):

```python
import json

from fraiseql import fraiseql_rs

build_mutation_response = fraiseql_rs.build_mutation_response

# The selection document: which fields of the success and error types the query
# selected. None for both means "unfiltered": every field the result has.
UNFILTERED = json.dumps({"format": 2, "success": None, "error": None})
```

`entity_selections` is required. Its `format` is `fraiseql_rs.MUTATION_SELECTION_FORMAT`
(2); see [Selecting Fields](#selecting-fields) for a filtered document.

## Basic Usage

### Simple Entity Creation

```python
# Simple format - just entity data
mutation_json = json.dumps({
    "id": "user-123",
    "name": "John Doe",
    "email": "john@example.com",
    "created_at": "2024-01-01T00:00:00Z"
})

result = build_mutation_response(
    mutation_json=mutation_json,
    field_name="createUser",
    success_type="CreateUserSuccess",
    error_type="CreateUserError",
    entity_field_name="user",
    entity_type="User",
    auto_camel_case=True,
    entity_selections=UNFILTERED,
)

# Result is bytes - parse to dict
response = json.loads(result)
print(json.dumps(response, indent=2))
```

**Output:**

```json
{
  "data": {
    "createUser": {
      "__typename": "CreateUserSuccess",
      "id": "user-123",
      "message": "Success",
      "status": "success",
      "user": {
        "__typename": "User",
        "createdAt": "2024-01-01T00:00:00Z",
        "email": "john@example.com",
        "id": "user-123",
        "name": "John Doe"
      }
    }
  }
}
```

### Full Format with Status

```python
# Full format with explicit status
mutation_json = json.dumps({
    "status": "created",
    "message": "User account created successfully",
    "entity_id": "user-123",
    "entity_type": "User",
    "entity": {
        "id": "user-123",
        "name": "John Doe",
        "email": "john@example.com"
    },
    "updated_fields": ["name", "email"],
    "metadata": {
        "operation_id": "op-456",
        "timestamp": "2024-01-01T00:00:00Z"
    }
})

result = build_mutation_response(
    mutation_json=mutation_json,
    field_name="createUser",
    success_type="CreateUserSuccess",
    error_type="CreateUserError",
    entity_field_name="user",
    entity_type=None,  # Will use entity_type from JSON
    auto_camel_case=True,
    entity_selections=UNFILTERED,
)

response = json.loads(result)
print(json.dumps(response, indent=2))
```

**Output:**

```json
{
  "data": {
    "createUser": {
      "__typename": "CreateUserSuccess",
      "id": "user-123",
      "message": "User account created successfully",
      "status": "created",
      "updatedFields": [
        "name",
        "email"
      ],
      "user": {
        "__typename": "User",
        "email": "john@example.com",
        "id": "user-123",
        "name": "John Doe"
      }
    }
  }
}
```

## Error Handling

### Validation Error

```python
mutation_json = json.dumps({
    "status": "validation:",
    "message": "Email address is already in use",
    "entity_id": None,
    "entity_type": None,
    "entity": None,
    "metadata": {
        "errors": [
            {
                "field": "email",
                "code": "duplicate",
                "message": "This email address is already registered"
            }
        ]
    }
})

result = build_mutation_response(
    mutation_json=mutation_json,
    field_name="createUser",
    success_type="CreateUserSuccess",
    error_type="CreateUserError",
    entity_field_name="user",
    entity_type="User",
    auto_camel_case=True,
    entity_selections=UNFILTERED,
)

response = json.loads(result)
print(json.dumps(response, indent=2))
```

**Output:**

```json
{
  "data": {
    "createUser": {
      "__typename": "CreateUserError",
      "code": 422,
      "errors": [
        {
          "code": "duplicate",
          "field": "email",
          "message": "This email address is already registered"
        }
      ],
      "message": "Email address is already in use",
      "status": "validation:"
    }
  }
}
```

### Different Error Types

The status prefix picks the error type and its `code`:

```python
for status in [
    "unauthorized:token_expired",
    "forbidden:insufficient_permissions",
    "not_found:user_missing",
    "conflict:duplicate_email",
    "failed:validation",
]:
    result = build_mutation_response(
        mutation_json=json.dumps({"status": status, "message": "..."}),
        field_name="createUser",
        success_type="CreateUserSuccess",
        error_type="CreateUserError",
        entity_field_name="user",
        entity_type="User",
        entity_selections=UNFILTERED,
    )
    body = json.loads(result)["data"]["createUser"]
    print(status, body["__typename"], body["code"])
```

**Output:**

```text
unauthorized:token_expired CreateUserError 401
forbidden:insufficient_permissions CreateUserError 403
not_found:user_missing CreateUserError 404
conflict:duplicate_email CreateUserError 409
failed:validation CreateUserError 422
```

## Cascade Data

### Update with Side Effects

```python
mutation_json = json.dumps({
    "status": "updated",
    "message": "User profile updated",
    "entity_id": "user-123",
    "entity_type": "User",
    "entity": {
        "id": "user-123",
        "name": "John Smith",
        "email": "johnsmith@example.com"
    },
    "updated_fields": ["name", "email"],
    "cascade": {
        "updated": [
            {
                "__typename": "Post",
                "id": "post-456",
                "operation": "UPDATED",
                "entity": {"id": "post-456", "author_name": "John Smith"}
            }
        ],
        "deleted": [],
        "invalidations": [{"query_name": "posts", "strategy": "INVALIDATE", "scope": "PREFIX"}],
        "metadata": {"timestamp": "2024-01-01T00:00:00Z", "affected_count": 1}
    }
})

# The cascade is written only when the query selects it: cascade_selections names
# the selected cascade fields (and the fields of each part)
cascade_selections = json.dumps({
    "fields": ["updated", "invalidations", "metadata"],
    "updated": {"fields": ["__typename", "id", "operation", "entity"]},
    "invalidations": {"fields": ["query_name", "strategy", "scope"]},
    "metadata": {"fields": ["affected_count"]},
})

result = build_mutation_response(
    mutation_json=mutation_json,
    field_name="updateUser",
    success_type="UpdateUserSuccess",
    error_type="UpdateUserError",
    entity_field_name="user",
    entity_type="User",
    cascade_selections=cascade_selections,
    auto_camel_case=True,
    entity_selections=UNFILTERED,
)

response = json.loads(result)
print(json.dumps(response, indent=2))
```

**Output:**

```json
{
  "data": {
    "updateUser": {
      "__typename": "UpdateUserSuccess",
      "cascade": {
        "invalidations": [
          {
            "query_name": "posts",
            "scope": "PREFIX",
            "strategy": "INVALIDATE"
          }
        ],
        "metadata": {
          "affected_count": 1
        },
        "updated": [
          {
            "__typename": "Post",
            "entity": {
              "author_name": "John Smith",
              "id": "post-456"
            },
            "id": "post-456",
            "operation": "UPDATED"
          }
        ]
      },
      "id": "user-123",
      "message": "User profile updated",
      "status": "updated",
      "updatedFields": [
        "name",
        "email"
      ],
      "user": {
        "__typename": "User",
        "email": "johnsmith@example.com",
        "id": "user-123",
        "name": "John Smith"
      }
    }
  }
}
```

Without `cascade_selections` (the query doesn't select `cascade`), the response has no
`cascade` key. See [GraphQL Cascade](../features/graphql-cascade.md) for the shape of
`cascade`.

## Array Entities

### Bulk Operations

```python
mutation_json = json.dumps([
    {
        "id": "user-1",
        "name": "Alice Johnson",
        "email": "alice@example.com"
    },
    {
        "id": "user-2",
        "name": "Bob Wilson",
        "email": "bob@example.com"
    }
])

result = build_mutation_response(
    mutation_json=mutation_json,
    field_name="createUsers",
    success_type="CreateUsersSuccess",
    error_type="CreateUsersError",
    entity_field_name="users",
    entity_type="User",
    auto_camel_case=True,
    entity_selections=UNFILTERED,
)

response = json.loads(result)
print(json.dumps(response, indent=2))
```

**Output:**

```json
{
  "data": {
    "createUsers": {
      "__typename": "CreateUsersSuccess",
      "message": "Success",
      "status": "success",
      "users": [
        {
          "__typename": "User",
          "email": "alice@example.com",
          "id": "user-1",
          "name": "Alice Johnson"
        },
        {
          "__typename": "User",
          "email": "bob@example.com",
          "id": "user-2",
          "name": "Bob Wilson"
        }
      ]
    }
  }
}
```

## Noop Operations

### Unchanged Data

A `noop:` status answers with the error type (code 422), the reason after the colon
as the error's `identifier`:

```python
mutation_json = json.dumps({
    "status": "noop:unchanged",
    "message": "No changes were needed",
    "entity_id": "user-123",
    "entity_type": "User",
    "entity": {
        "id": "user-123",
        "name": "John Doe",
        "email": "john@example.com"
    }
})

result = build_mutation_response(
    mutation_json=mutation_json,
    field_name="updateUser",
    success_type="UpdateUserSuccess",
    error_type="UpdateUserError",
    entity_field_name="user",
    entity_type="User",
    auto_camel_case=True,
    entity_selections=UNFILTERED,
)

response = json.loads(result)
print(json.dumps(response, indent=2))
```

**Output:**

```json
{
  "data": {
    "updateUser": {
      "__typename": "UpdateUserError",
      "code": 422,
      "email": "john@example.com",
      "errors": [
        {
          "code": 422,
          "details": null,
          "identifier": "unchanged",
          "message": "No changes were needed"
        }
      ],
      "id": "user-123",
      "message": "No changes were needed",
      "name": "John Doe",
      "status": "noop:unchanged"
    }
  }
}
```

## Advanced Features

### Selecting Fields

A class mutation sends the fields the query selected. A selection is
`{"__type": ..., "fields": [{"name": ..., "alias": ..., "selections": ...}]}`: the
response holds only those fields, each under its `alias` (the response key). With
`"typename": "selected"`, `__typename` is written only where it is selected, as in a
GraphQL response:

```python
# mutation { createUser(...) { ... on CreateUserSuccess { u: user { id name } } } }
selections = json.dumps({
    "format": 2,
    "typename": "selected",
    "success": {
        "__type": "CreateUserSuccess",
        "fields": [
            {"name": "user", "alias": "u", "selections": {
                "fields": [
                    {"name": "id", "alias": "id"},
                    {"name": "name", "alias": "name"},
                ]
            }},
        ],
    },
    "error": None,
})

result = build_mutation_response(
    mutation_json=json.dumps({"id": "user-123", "name": "John Doe", "email": "john@example.com"}),
    field_name="createUser",
    success_type="CreateUserSuccess",
    error_type="CreateUserError",
    entity_field_name="user",
    entity_type="User",
    entity_selections=selections,
)
print(json.loads(result))
```

**Output:**

```text
{'data': {'createUser': {'u': {'id': 'user-123', 'name': 'John Doe'}}}}
```

### Custom Field Names

```python
# Use custom field names
result = build_mutation_response(
    mutation_json=json.dumps({"id": "acc-1", "name": "Main"}),
    field_name="createAccount",  # Response key of the mutation field
    success_type="AccountCreationSuccess",
    error_type="AccountCreationError",
    entity_field_name="account",  # Custom entity field name
    entity_type="Account",
    auto_camel_case=True,
    entity_selections=UNFILTERED,
)
print(json.loads(result))
```

**Output:**

```text
{'data': {'createAccount': {'__typename': 'AccountCreationSuccess', 'account': {'__typename': 'Account', 'id': 'acc-1', 'name': 'Main'}, 'id': 'acc-1', 'message': 'Success', 'status': 'success'}}}
```

### Disable CamelCase Conversion

```python
# Keep original field names
result = build_mutation_response(
    mutation_json=json.dumps({"id": "user-123", "created_at": "2024-01-01T00:00:00Z"}),
    field_name="create_user",
    success_type="CreateUserSuccess",
    error_type="CreateUserError",
    entity_field_name="user",
    entity_type="User",
    auto_camel_case=False,  # Keep snake_case
    entity_selections=UNFILTERED,
)
print(json.loads(result))
```

**Output:**

```text
{'data': {'create_user': {'__typename': 'CreateUserSuccess', 'id': 'user-123', 'message': 'Success', 'status': 'success', 'user': {'__typename': 'User', 'created_at': '2024-01-01T00:00:00Z', 'id': 'user-123'}}}}
```

### Complex Nested Data

```python
mutation_json = json.dumps({
    "id": "user-123",
    "profile": {
        "personal": {
            "first_name": "John",
            "last_name": "Doe",
            "date_of_birth": "1990-01-01"
        },
        "contact": {
            "email": "john@example.com",
            "phone": "+1-555-0123"
        }
    },
    "preferences": {
        "notifications": {
            "email_enabled": True,
            "sms_enabled": False
        }
    }
})

result = build_mutation_response(
    mutation_json=mutation_json,
    field_name="createUser",
    success_type="CreateUserSuccess",
    error_type="CreateUserError",
    entity_field_name="user",
    entity_type="User",
    auto_camel_case=True,
    entity_selections=UNFILTERED,
)

response = json.loads(result)
print(json.dumps(response, indent=2))
```

**Output:**

```json
{
  "data": {
    "createUser": {
      "__typename": "CreateUserSuccess",
      "id": "user-123",
      "message": "Success",
      "status": "success",
      "user": {
        "__typename": "User",
        "id": "user-123",
        "preferences": {
          "notifications": {
            "emailEnabled": true,
            "smsEnabled": false
          }
        },
        "profile": {
          "contact": {
            "email": "john@example.com",
            "phone": "+1-555-0123"
          },
          "personal": {
            "dateOfBirth": "1990-01-01",
            "firstName": "John",
            "lastName": "Doe"
          }
        }
      }
    }
  }
}
```

## Integration with Web Frameworks

`create_fraiseql_app` serves class mutations through this pipeline already. If you
build the response yourself, return the bytes as they are:

```python
from fastapi import FastAPI
from fastapi.responses import Response

app = FastAPI()


@app.post("/create-user")
async def create_user() -> Response:
    # Simulate database mutation result
    db_result = {
        "status": "created",
        "message": "User created",
        "entity_id": "123",
        "entity_type": "User",
        "entity": {
            "id": "123",
            "name": "John Doe",
            "email": "john@example.com"
        }
    }

    # Build GraphQL response using Rust pipeline
    result_bytes = build_mutation_response(
        mutation_json=json.dumps(db_result),
        field_name="createUser",
        success_type="CreateUserSuccess",
        error_type="CreateUserError",
        entity_field_name="user",
        entity_type="User",
        entity_selections=UNFILTERED,
    )

    # The bytes are already the JSON response body
    return Response(content=result_bytes, media_type="application/json")
```

## Performance Comparison

```python
import time

# Test data
mutation_json = json.dumps({
    "status": "created",
    "entity_type": "User",
    "entity": {"id": "123", "name": "Test", "email": "test@example.com"}
})

# Benchmark Rust pipeline
start = time.perf_counter()
for _ in range(1000):
    result = build_mutation_response(
        mutation_json=mutation_json,
        field_name="createUser",
        success_type="CreateUserSuccess",
        error_type="CreateUserError",
        entity_field_name="user",
        entity_type="User",
        entity_selections=UNFILTERED,
    )
rust_time = time.perf_counter() - start

print(f"Rust pipeline: {rust_time:.4f}s for 1000 operations")
print(f"Average: {rust_time:.4f}ms per operation")
```

The time per call is in microseconds for small results; measure on your own data.

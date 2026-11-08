# Rust Mutation Pipeline Architecture

## Overview

The Rust mutation pipeline provides ultra-fast GraphQL mutation response building from PostgreSQL JSON data. It supports two JSON formats and handles complex GraphQL response construction including cascade data, `__typename`, aliases, field selection and camelCase conversion.

Applications don't call it: a class mutation (`@fraiseql.mutation`) runs the SQL function and hands its result to this pipeline with the request's selection. The Python API below is for tests and for seeing what the pipeline does with a given result.

## Architecture

### Core Components

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   PostgreSQL    │───▶│  MutationResult  │───▶│ ResponseBuilder │
│     JSON        │    │    Parser        │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                                       │
                                                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   GraphQL       │◀───│  Entity         │◀───│   Cascade       │
│   Response      │    │  Processor      │    │   Processor     │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

### Key Features

- **Zero-copy JSON parsing** where possible
- **SIMD-accelerated** string operations
- **Format auto-detection** between simple and full v2 formats
- **Cascade data handling** with proper placement
- **Type-safe status taxonomy** with HTTP code mapping
- **Comprehensive error handling** with detailed messages

## JSON Format Support

### Simple Format (Auto-detected)

```json
{"id": "123", "name": "John", "email": "john@example.com"}
```

- No `status` field or invalid status values
- Entire JSON becomes the entity
- Assumes success status
- Supports `_cascade` field extraction

### Full v2 Format

```json
{
  "status": "created",
  "message": "User created successfully",
  "entity_type": "User",
  "entity": {"id": "123", "name": "John"},
  "updated_fields": ["name", "email"],
  "cascade": {
    "updated": [{"id": "user-123", "post_count": 5}],
    "deleted": [],
    "invalidations": ["User:123"]
  },
  "metadata": {"errors": [...]}
}
```

- Complete mutation response structure
- Rich status taxonomy
- Cascade data support
- Error handling with metadata

## Status Taxonomy

The code is the error type's `code` field (and each `errors[].code`), not the HTTP
status of the response, which is 200.

### Success States

- `success`, `new`, `created`, `updated`, `deleted`, `completed`, `ok` → the success type

### Error States (with codes)

- `validation:*` → 422
- `unauthorized:*` → 401
- `forbidden:*` → 403
- `not_found:*` → 404
- `conflict:*` → 409
- `timeout:*` → 408
- `failed:<reason>` → read like `<reason>:` (`failed:validation` 422,
  `failed:not_found` 404, `failed:duplicate` 409, ...); any other `failed:*` → 500

### Noop States

- `noop:*` → the error type, code 422 (nothing changed)

## Cascade Data Handling

Cascade data represents side effects of mutations:

```json
{
  "updated": [{"id": "user-123", "post_count": 5}],
  "deleted": ["post-456"],
  "invalidations": ["User:123", "Post:456"],
  "metadata": {"operation": "create"}
}
```

**Important**: Cascade data is **never** placed inside entity objects. It always appears at the mutation response level, and only when the query selects `cascade`.

## Response Structure

### Success Response

```json
{
  "data": {
    "createUser": {
      "__typename": "CreateUserSuccess",
      "message": "User created successfully",
      "user": {
        "__typename": "User",
        "id": "123",
        "firstName": "John",
        "lastName": "Doe"
      },
      "cascade": {
        "updated": [...],
        "deleted": [...],
        "invalidations": [...]
      }
    }
  }
}
```

### Error Response

```json
{
  "data": {
    "createUser": {
      "__typename": "CreateUserError",
      "status": "validation:",
      "message": "Email already exists",
      "code": 422,
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

## Performance Characteristics

- **10-50x faster** than pure Python implementation
- **Zero-copy** JSON parsing for simple formats
- **SIMD acceleration** for string transformations
- **Arena-based memory management** for reduced allocations

## Integration Points

### Python API

```python
import json

from fraiseql import fraiseql_rs

result = fraiseql_rs.build_mutation_response(
    mutation_json='{"id": "123", "name": "John"}',
    field_name="createUser",
    success_type="CreateUserSuccess",
    error_type="CreateUserError",
    entity_field_name="user",
    entity_type="User",
    cascade_selections=None,  # the query doesn't select cascade
    auto_camel_case=True,
    # Required: what the query selected; None for both types is unfiltered
    entity_selections=json.dumps({"format": 2, "success": None, "error": None}),
)
print(json.loads(result))
# {'data': {'createUser': {'__typename': 'CreateUserSuccess', 'id': '123', 'message': 'Success',
#  'status': 'success', 'user': {'__typename': 'User', 'id': '123', 'name': 'John'}}}}
```

`result` is the response body as bytes. The selection document's `format` is
`fraiseql_rs.MUTATION_SELECTION_FORMAT`; a class mutation builds it from the query, with
`"typename": "selected"` so that `__typename` appears only where the query selects it.
See [Rust Mutation Pipeline Examples](./examples.md) for more.

### GraphQL Schema Integration

The pipeline integrates with GraphQL union types:

```graphql
union CreateUserResult = CreateUserSuccess | CreateUserError

type CreateUserSuccess {
  message: String!
  user: User!
  cascade: CascadeData
}

type CreateUserError {
  status: String!
  message: String!
  code: Int!
  errors: [ValidationError!]
}
```

## Testing Strategy

### Unit Tests

- Format detection edge cases
- Status taxonomy validation
- Cascade placement invariants
- Entity processing correctness
- Error handling scenarios

### Property-Based Tests

- Invariant verification (cascade never in entity)
- Deterministic format detection
- Type safety guarantees

### Integration Tests

- End-to-end response building
- Python interoperability
- Performance regression detection

### Benchmarks

- Simple format processing
- Full format with cascade
- Error response handling
- Array entity processing

## Migration from Python

See [Migration Guide](./migration-guide.md) for details on transitioning from the Python mutation pipeline to the Rust implementation.

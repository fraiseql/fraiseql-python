---
title: Migration Guide
description: Calling the Rust mutation response builder from code written for the old Python pipeline
tags:
  - migration
  - upgrade
  - guide
  - transition
---

# Migration Guide: Python to Rust Mutation Pipeline

## Overview

FraiseQL builds every mutation response in Rust: the Python mutation pipeline is gone,
and there is nothing to switch back to. A class mutation (`@fraiseql.mutation`) calls
the Rust builder itself, with the selection of the request, so an application that
only defines mutations has nothing to migrate.

This page is for code that called the response builder directly (tests, custom
endpoints). `fraiseql.mutations` has no `build_mutation_response`; the function lives
in the Rust extension, which ships inside the `fraiseql` package.

## Migration Steps

### 1. Update Imports

**Before:**

```text
from fraiseql.mutations import build_mutation_response   # no longer exists
from fraiseql_rs import build_mutation_response          # not a top-level module
```

**After:**

```python
from fraiseql import fraiseql_rs

build_mutation_response = fraiseql_rs.build_mutation_response
```

### 2. Pass the Selection Document

The call takes a selection document in `entity_selections` (format 2,
`fraiseql_rs.MUTATION_SELECTION_FORMAT`): what the query selected on the success and
error types, under its response keys. `null` for a type returns it unfiltered. It is
required: a call without it raises `ValueError`.

```python
import json

result = build_mutation_response(
    mutation_json='{"id": "123", "name": "John"}',
    field_name="createUser",
    success_type="CreateUserSuccess",
    error_type="CreateUserError",
    entity_field_name="user",
    entity_type="User",
    cascade_selections=None,
    auto_camel_case=True,
    entity_selections='{"format": 2, "success": null, "error": null}',
)
```

A class mutation builds this document from the resolver's `info`, with
`"typename": "selected"` so that `__typename` is written only where the query selects
it. See [Rust Mutation Pipeline Examples](./examples.md#selecting-fields) for a filtered
document.

### 3. Handle the Return Type

The function returns the response body as `bytes`, ready to send:

```python
assert isinstance(result, bytes)

# Parse to dict if needed
parsed = json.loads(result)
user = parsed["data"]["createUser"]["user"]
print(user)
# {'__typename': 'User', 'id': '123', 'name': 'John'}
```

## Format Support

### Simple Format (Auto-detected)

```json
{"id": "123", "name": "John", "email": "john@example.com"}
```

- No `status` field or invalid status values
- Entire JSON becomes the entity
- Assumes success status

### Full Format

```json
{
  "status": "created",
  "message": "User created successfully",
  "entity_type": "User",
  "entity": {"id": "123", "name": "John"},
  "cascade": {"updated": [], "deleted": []}
}
```

- Complete mutation response structure
- Rich status taxonomy
- Cascade data support (written only when the query selects `cascade`)

The status taxonomy and the codes of the error type are in
[Rust Mutation Pipeline Architecture](./rust-mutation-pipeline.md#status-taxonomy).

## Testing

```python
result = build_mutation_response(
    mutation_json='{"id": "123", "name": "John"}',
    field_name="createUser",
    success_type="CreateUserSuccess",
    error_type="CreateUserError",
    entity_field_name="user",
    entity_type="User",
    entity_selections='{"format": 2, "success": null, "error": null}',
)
parsed = json.loads(result)
assert parsed["data"]["createUser"]["__typename"] == "CreateUserSuccess"
```

## Error Handling

Malformed JSON, a missing or wrong selection document, or a failed transformation
raise `ValueError`:

```python
try:
    build_mutation_response(
        mutation_json="{not json",
        field_name="createUser",
        success_type="CreateUserSuccess",
        error_type="CreateUserError",
        entity_selections='{"format": 2, "success": null, "error": null}',
    )
except ValueError as e:
    print(f"Rust pipeline error: {e}")
```

## Troubleshooting

1. **`TypeError` / `AttributeError` on the result**: it is `bytes`; parse it with
   `json.loads(result)`.
2. **`ValueError: build_mutation_response needs a selection document of format 2`**:
   pass `entity_selections`. If you do and still get it, the `fraiseql` package and its
   Rust extension are from different versions: reinstall fraiseql (or, in a development
   checkout, rebuild the extension with `uv run maturin develop`).

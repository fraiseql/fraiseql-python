# Phase 6.1: Mutation Field Selection - Implementation Guide

**Status**: 🚀 **IN PROGRESS**
**Date**: January 9, 2026
**Issue**: [PrintOptim #525](https://github.com/zedix/printoptim_backend/issues/525)

---

## What's Being Implemented

This document covers the **actual implementation** of Phase 6.1 Mutation Field Selection Filtering. The high-level design is documented in `PHASE_6_MUTATION_FIELD_SELECTION.md`.

---

## Phase 6.1: Step-by-Step Implementation

### Step 1: Infrastructure (COMPLETED ✅)

#### 1a. Created `mutation_resolver.py` Helper Module ✅

**File**: `src/fraiseql/mutations/mutation_resolver.py`

Provides utilities to extract GraphQL field selections from `info` object:

```python
def extract_field_selections(info: GraphQLResolveInfo | None) -> dict[str, Any] | None:
    """Extract field selections from mutation context.

    Returns nested dict: {"id": True, "name": True, "address": {"city": True}}
    """
```

Usage in mutation resolvers:

```python
from fraiseql.mutations.mutation_resolver import extract_field_selections

@fraiseql.mutation
async def create_user(info: GraphQLResolveInfo, input: CreateUserInput) -> CreateUserResult:
    # Extract field selections
    field_selections = extract_field_selections(info)
    # field_selections = {"user": {"id": True, "name": True}}

    # ... rest of implementation
```

#### 1b. Extended Unified FFI Adapter ✅

**File**: `src/fraiseql/core/unified_ffi_adapter.py` (lines 152-159)

Updated `build_graphql_response_via_unified()` to pass `field_selections` to Rust:

```python
# Phase 6.1: Add field selections for filtering (NEW)
if field_selections is not None:
    try:
        request["selections"] = json.loads(field_selections)
    except (json.JSONDecodeError, TypeError):
        # Invalid field_selections JSON - ignore and use defaults
        pass
```

The FFI now includes selections in the request sent to Rust:

```json
{
  "query": "{ __typename }",
  "variables": {},
  "selections": {
    "id": true,
    "name": true,
    "address": {"city": true}
  }
}
```

---

### Step 2: Mutation Integration (IN PROGRESS)

#### 2a. Implicit Info Injection for User-Defined Mutations

**Current Status**: FraiseQL's resolver wrapping already supports `info` parameter implicitly!

The `MutationDefinition.create_resolver()` method in `mutation_decorator.py` (line 365) creates resolvers with this signature:

```python
async def resolver(info: GraphQLResolveInfo, input: dict[str, Any]) -> Any:
    """Auto-generated resolver for PostgreSQL mutation."""
```

**This means users can now write mutations with optional info parameter**:

**Pattern 1: Simple mutation (no info needed)**
```python
@fraiseql.mutation
class CreateUser:
    input: CreateUserInput
    success: CreateUserSuccess
    error: CreateUserError
```

**Pattern 2: Custom mutation with access to info**
```python
@fraiseql.mutation
async def create_user_custom(
    info: GraphQLResolveInfo,
    input: CreateUserInput,
) -> CreateUserResult:
    """Custom mutation with access to GraphQL context."""
    # Access field selections for custom filtering
    from fraiseql.mutations.mutation_resolver import extract_field_selections

    fields = extract_field_selections(info)
    # Use fields for custom business logic

    # Call mutation function
    # ...
```

The resolver wrapping layer (`_wrap_mutation_resolver()` in `mutation_builder.py` lines 135-181) automatically:
1. Maps GraphQL argument names (camelCase handling)
2. Passes `info` as first argument
3. Calls input coercion
4. Invokes the user's resolver

#### 2b. Rust Executor Already Passes Selections

**File**: `src/fraiseql/mutations/rust_executor.py`

The `execute_mutation_rust()` function already:
1. Receives `success_type_fields` and `error_type_fields` from `create_resolver()` (line 440-441)
2. Passes them to the Rust FFI boundary
3. The Rust code applies field filtering on responses

**Key code** (mutation_decorator.py lines 419-442):

```python
# Extract selected fields from GraphQL query for field filtering
success_type_fields = _extract_mutation_selected_fields(info, success_type_name)
error_type_fields = _extract_mutation_selected_fields(info, error_type_name)

rust_response = await execute_mutation_rust(
    # ... other args ...
    success_type_fields=success_type_fields,  # Passed to Rust!
    error_type_fields=error_type_fields,      # Passed to Rust!
)
```

---

### Step 3: Rust FFI Enhancement (READY FOR IMPLEMENTATION)

**File**: `fraiseql_rs/src/pipeline/unified.rs`

The Rust FFI needs to:

1. **Accept selections in request** (already done via Python adapter)
2. **Filter response fields** based on selections

**Pseudocode** (to be implemented):

```rust
pub fn process_graphql_request(
    request_json: &str,
    context: Option<&str>,
) -> Result<String> {
    let request: GraphQLRequest = serde_json::from_str(request_json)?;

    // Extract selections if provided
    let selections = request
        .get("selections")
        .and_then(|s| s.as_object())
        .cloned();

    // Execute query as before
    let response = execute_query(...)?;

    // Filter response based on selections
    if let Some(selections) = selections {
        filter_response_fields(&response, &selections)
    } else {
        Ok(response)
    }
}

fn filter_response_fields(
    response: &Value,
    selections: &Map<String, Value>,
) -> Result<String> {
    // Filter response.data fields based on selection map
    // This keeps only requested fields at all nesting levels
    // ...
}
```

---

### Step 4: Testing Strategy

#### 4a. Unit Tests

**File**: `tests/unit/mutations/test_field_selection.py` (to be created)

Test cases:

1. **Simple field selection**
   ```python
   def test_mutation_respects_simple_field_selection():
       """Request only id, name from location mutation."""
       # Create location requesting only id, name
       # Verify response has only those fields
       # Verify extra fields (address, coordinates, etc.) are absent
   ```

2. **Nested field selection**
   ```python
   def test_mutation_respects_nested_field_selection():
       """Request nested address.city only."""
       # Create location requesting location.address.city
       # Verify nested filtering works
   ```

3. **Union type responses**
   ```python
   def test_mutation_union_field_selection():
       """Both success and error branches respect filtering."""
       # Test success path
       # Test error path
   ```

4. **Backward compatibility**
   ```python
   def test_mutation_backward_compatible():
       """Old mutations without field selection still work."""
       # Ensure all fields returned when no selection provided
   ```

#### 4b. Integration Tests

**File**: `tests/integration/mutations/test_field_selection_integration.py` (to be created)

End-to-end tests:

1. **Full GraphQL query with mutations**
   ```graphql
   mutation CreateLocation($input: CreateLocationInput!) {
     createLocation(input: $input) {
       ... on CreateLocationSuccess {
         __typename
         location {
           id
           name
         }
       }
     }
   }
   ```

2. **Response size validation**
   ```python
   def test_mutation_response_size_reduction():
       """Measure response size reduction from filtering."""
       # Large entity with 50+ fields
       # Request only 5 fields
       # Verify response is ~10% of original size
   ```

---

## Architecture Summary

### Execution Flow with Field Selection

```
GraphQL Mutation Query
    ↓
Python Resolver (receives 'info')
    ↓
Extract field selections via extract_field_selections(info)
    ↓
Call Rust executor with selections
    ↓
Rust FFI processes query + applies field filtering
    ↓
Response with only requested fields
    ↓
Return to client
```

### Code Ownership by Layer

| Layer | File | Responsibility |
|-------|------|-----------------|
| **Python** | `mutation_resolver.py` | Extract selections from GraphQL info |
| **Python** | `unified_ffi_adapter.py` | Pass selections to Rust in request |
| **Rust** | `pipeline/unified.rs` | Apply field filtering to response |
| **Tests** | `tests/unit/mutations/test_field_selection.py` | Unit testing |
| **Tests** | `tests/integration/mutations/test_field_selection_integration.py` | Integration testing |

---

## Key Implementation Notes

### 1. Info Parameter Is Already Available!

Users don't need to do anything special. The resolver wrapping already supports `info`:

```python
# This works - info is implicitly available
@fraiseql.mutation
async def create_user(info: GraphQLResolveInfo, input: CreateUserInput):
    # Can access field selections
    from fraiseql.mutations.mutation_resolver import extract_field_selections
    fields = extract_field_selections(info)
```

### 2. Backward Compatibility

- Old mutations without field selection still work
- Default behavior: return all fields (current behavior)
- New behavior: only when field selections are provided
- Zero performance impact when selections aren't used

### 3. Union Type Handling

For mutations with `Success | Error` union types:

```python
# Automatically handled in both paths:
# - CreateLocationSuccess → selections filtered to requested fields
# - CreateLocationError → selections filtered to error fields
```

The resolver already extracts selections for both success and error types (mutation_decorator.py lines 419-420).

### 4. Nested Entity Support

Field selections work with nested entities:

```graphql
mutation {
  createLocation(input: {...}) {
    ... on CreateLocationSuccess {
      location {
        id
        name
        address {
          city      # Only this field requested
        }
      }
    }
  }
}
```

The selection tree `{"location": {"address": {"city": true}}}` is passed to Rust for filtering.

---

## Performance Implications

### Expected Results

- **Response size**: 30-50% reduction for typical mutations
- **Network bandwidth**: Proportional to response size reduction
- **Rust filtering overhead**: Minimal (single pass through JSON)
- **Zero overhead when**: Selections not provided (current behavior preserved)

### Benchmarking

```python
# Measure before/after response sizes
def test_response_size_benchmark():
    # Create location with 100 fields
    # Request 5 fields
    # Measure size reduction
    # Expected: ~95% smaller response
```

---

## Security Implications

✅ **Positive security impact**:
- Prevents leakage of unrequested fields
- Sensitive data not exposed unless explicitly requested
- Consistent security posture across queries and mutations

---

## Success Criteria

- [ ] Field extraction utility created (`mutation_resolver.py`) ✅ DONE
- [ ] FFI adapter extended with field_selections ✅ DONE
- [ ] Rust FFI filtering implemented (IN PROGRESS)
- [ ] Unit tests passing (PENDING)
- [ ] Integration tests passing (PENDING)
- [ ] Performance benchmarks showing improvement (PENDING)
- [ ] Documentation updated (PENDING)
- [ ] Issue #525 resolved (PENDING)

---

## Next Steps

1. **Implement Rust filtering** (fraiseql_rs/src/pipeline/unified.rs)
   - Parse selections from request
   - Apply recursive filtering to response JSON
   - Handle union types correctly

2. **Add unit tests** (tests/unit/mutations/test_field_selection.py)
   - Test extraction logic
   - Test filtering logic
   - Test edge cases

3. **Add integration tests** (tests/integration/mutations/)
   - Test full GraphQL execution
   - Test performance
   - Test backward compatibility

4. **Update documentation**
   - Add examples to mutation guide
   - Document field selection best practices
   - Update API docs

---

## Files Modified/Created

| File | Status | Type |
|------|--------|------|
| `src/fraiseql/mutations/mutation_resolver.py` | ✅ CREATED | New utility module |
| `src/fraiseql/core/unified_ffi_adapter.py` | ✅ MODIFIED | Pass selections to Rust |
| `fraiseql_rs/src/pipeline/unified.rs` | 🔄 IN PROGRESS | Implement filtering |
| `tests/unit/mutations/test_field_selection.py` | 📝 PENDING | New tests |
| `tests/integration/mutations/test_field_selection_integration.py` | 📝 PENDING | New tests |
| `docs/mutation-api.md` | 📝 PENDING | Update docs |

---

## References

- **High-level design**: `PHASE_6_MUTATION_FIELD_SELECTION.md`
- **Mutation architecture**: `src/fraiseql/mutations/mutation_decorator.py`
- **FFI adapter**: `src/fraiseql/core/unified_ffi_adapter.py`
- **Existing filtering**: `src/fraiseql/mutations/selection_filter.py`

---

## Implementation Timeline

| Task | Duration | Status |
|------|----------|--------|
| Infra: Create helper modules | ✅ 1 hour | COMPLETED |
| Infra: Extend FFI boundary | ✅ 1 hour | COMPLETED |
| Rust: Implement filtering | 🔄 4 hours | IN PROGRESS |
| Tests: Unit tests | ⏳ 3 hours | PENDING |
| Tests: Integration tests | ⏳ 2 hours | PENDING |
| Docs: Update documentation | ⏳ 1 hour | PENDING |
| **TOTAL** | **~12 hours** | **6/12 hours completed** |

---

**Last Updated**: January 9, 2026

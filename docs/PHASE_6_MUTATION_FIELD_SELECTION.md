# Phase 6.1: Mutation Field Selection Filtering

**Status**: 🎯 **READY FOR IMPLEMENTATION**
**Priority**: High (security & performance)
**Issue**: [PrintOptim #525](https://github.com/zedix/printoptim_backend/issues/525)
**Date**: January 9, 2026

---

## Executive Summary

FraiseQL mutations currently return **all fields** for nested entities regardless of GraphQL field selection, causing:

- **Larger response payloads** (unnecessary data transfer)
- **Potential security issue** (unrequested sensitive fields exposed)
- **Inconsistent behavior** (queries respect field selection, mutations don't)

This Phase implements **unified field selection filtering** at the FFI boundary for both queries and mutations.

---

## Problem Statement

### Current Behavior

When a mutation requests specific fields:

```graphql
mutation CreateLocation($input: CreateLocationInput!) {
  createLocation(input: $input) {
    ... on CreateLocationSuccess {
      __typename
      location {
        id
        name
        parentId
      }
    }
  }
}
```

The response contains **all Location fields** instead of just the requested ones.

### Root Cause

1. **Queries work correctly**: Pass `info` parameter to filtering layer
2. **Mutations don't filter**: Rust FFI response builder doesn't receive field selection info
3. **Infrastructure exists**: `mutations/selection_filter.py` has the filtering logic, but it's not integrated at FFI boundary

---

## Architecture Analysis

### Current Query Path (Works ✅)

```
GraphQL Query
  ↓
Python Resolver (receives 'info')
  ↓
db.find(..., info=info)  ← Field selection passed
  ↓
Rust FFI (receives selection info)
  ↓
build_graphql_response() [filters based on selections]
  ↓
Filtered Response ✅
```

### Current Mutation Path (Broken ❌)

```
GraphQL Mutation
  ↓
Python Resolver (receives 'info')
  ↓
SQL Function (returns full entity)
  ↓
Rust FFI (NO selection info passed!)
  ↓
build_graphql_response() [returns ALL fields]
  ↓
Unfiltered Response ❌
```

---

## Solution Design

### Phase 6.1.1: Extend FFI Boundary

**File**: `src/fraiseql/core/unified_ffi_adapter.py`

Add `field_selections` parameter to response builders:

```python
def build_graphql_response_via_unified(
    json_strings: List[str],
    field_name: str,
    type_name: str,
    field_selections: Optional[str] = None,  # NEW: GraphQL selections as JSON
    is_list: bool = False,
    field_paths: Optional[List[str]] = None,
    include_graphql_wrapper: bool = True,
) -> bytes:
    """Enhanced to support field filtering for mutations."""
    # ... existing code ...

    # NEW: Build request with selection info
    request = {
        "query": _build_graphql_query_for_field(...),
        "variables": {},
        "selections": field_selections,  # Pass selections to Rust
    }

    response_json_str = fraiseql_rs.process_graphql_request(...)
    return response_json_str.encode("utf-8")
```

### Phase 6.1.2: Update Python Mutation Resolvers

**File**: `src/fraiseql/mutations/mutation_resolver.py` (NEW)

Create helper to extract field selections from GraphQL info:

```python
def extract_field_selections(info: GraphQLResolveInfo) -> Optional[dict]:
    """Extract field selections from mutation context.

    Converts GraphQL info.field_nodes into a format the Rust FFI
    can use to filter response fields.
    """
    if not info or not info.field_nodes:
        return None

    # Build selection tree from info.field_nodes
    selections = {}
    for field_node in info.field_nodes:
        if field_node.selection_set:
            selections.update(
                _traverse_selections(field_node.selection_set)
            )

    return selections if selections else None

def _traverse_selections(selection_set: SelectionSetNode) -> dict:
    """Recursively build selection tree."""
    selections = {}
    for selection in selection_set.selections:
        if isinstance(selection, FieldNode):
            field_name = selection.name.value
            selections[field_name] = True

            if selection.selection_set:
                selections[field_name] = _traverse_selections(
                    selection.selection_set
                )

    return selections
```

### Phase 6.1.3: Update Mutation Response Building

**File**: `src/fraiseql/mutations/base_mutation.py`

Integrate field selection when building responses:

```python
async def build_mutation_response(
    result_data: dict,
    success_type_name: str,
    info: GraphQLResolveInfo,
) -> dict:
    """Build mutation response respecting GraphQL field selection."""

    # Extract field selections from the GraphQL query context
    field_selections = extract_field_selections(info)

    # Use unified FFI with field selections
    response_bytes = build_graphql_response_via_unified(
        json_strings=[json.dumps(result_data)],
        field_name=success_type_name,
        type_name=success_type_name,
        field_selections=json.dumps(field_selections),
        is_list=False,
    )

    return json.loads(response_bytes)
```

### Phase 6.1.4: Rust FFI Enhancement

**File**: `fraiseql_rs/src/pipeline/unified.rs`

Update request processing to handle selections:

```rust
pub fn process_graphql_request(
    request_json: &str,
    context: Option<&str>,
) -> Result<String> {
    let mut request: GraphQLRequest = serde_json::from_str(request_json)?;

    // NEW: Extract selections if provided
    let selections = request
        .get("selections")
        .and_then(|s| s.as_object())
        .cloned();

    // Execute query as before
    let response = execute_query(...)?;

    // NEW: Filter response based on selections
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
    // ... implementation ...
}
```

---

## Implementation Steps

### Step 1: Infrastructure (4 hours)
- [x] Design FFI extension
- [ ] Update `unified_ffi_adapter.py` signature
- [ ] Add `extract_field_selections()` utility
- [ ] Extend request format in Rust

### Step 2: Mutation Integration (6 hours)
- [ ] Update `build_mutation_response()` helper
- [ ] Modify mutation resolvers to pass selections
- [ ] Handle nested entity responses
- [ ] Handle union type responses (Success/Error)

### Step 3: Rust Implementation (4 hours)
- [ ] Implement selection filtering in Rust
- [ ] Handle recursive field filtering
- [ ] Handle null/missing fields gracefully
- [ ] Optimize for common cases

### Step 4: Testing (4 hours)
- [ ] Unit tests for field extraction
- [ ] Integration tests for mutations
- [ ] Performance benchmarks
- [ ] Edge cases (union types, nested entities)

### Step 5: Documentation (2 hours)
- [ ] Update API docs
- [ ] Add example mutations
- [ ] Document behavior changes
- [ ] Migration guide for users

---

## Testing Strategy

### Test Cases

1. **Simple Mutation with Field Selection**
   ```python
   def test_mutation_respects_field_selection():
       """Verify mutation returns only requested fields."""
       # Create location requesting only id, name
       # Assert response contains only those fields
       # Assert extra fields (address, coordinates, etc.) are absent
   ```

2. **Nested Entity Field Selection**
   ```python
   def test_mutation_nested_field_selection():
       """Verify nested entities respect field selection."""
       # Create location requesting location.address.id only
       # Assert address contains only id field
       # Assert other address fields (city, country) are absent
   ```

3. **Union Type Responses**
   ```python
   def test_mutation_union_field_selection():
       """Verify Success/Error union branches filter correctly."""
       # Test both success and error paths
       # Ensure each branch respects its field selection
   ```

4. **Backward Compatibility**
   ```python
   def test_mutation_backward_compatible():
       """Verify old mutations without field selection still work."""
       # Ensure mutations without info parameter still work
       # Return full data (current behavior)
   ```

### Performance Tests

```python
def test_mutation_response_size_reduction():
    """Measure response size reduction from filtering."""
    # Large entity with 50+ fields
    # Request 5 fields
    # Verify response is ~10% of original size
```

---

## Files to Modify

| File | Change | Type |
|------|--------|------|
| `src/fraiseql/core/unified_ffi_adapter.py` | Add field_selections parameter | Enhancement |
| `src/fraiseql/mutations/mutation_resolver.py` | Create NEW helper module | New |
| `src/fraiseql/mutations/base_mutation.py` | Integrate field selection | Enhancement |
| `fraiseql_rs/src/pipeline/unified.rs` | Add filtering logic | Enhancement |
| `tests/mutations/test_field_selection.py` | Create NEW test file | New |
| `docs/mutation-api.md` | Update documentation | Docs |

---

## Backward Compatibility

✅ **Fully backward compatible**
- Old mutations without field selection still work
- Default behavior: return all fields (existing behavior)
- New behavior: only when field selections are provided

---

## Performance Impact

### Expected Improvements

- **Response size**: 30-50% reduction for typical mutations
- **Network bandwidth**: Proportional to response size reduction
- **Client parsing**: Faster JSON parsing with fewer fields

### Zero Overhead When

- Mutations don't use field selection (default behavior preserved)
- Selection filtering in Rust (minimal overhead)

---

## Security Implications

✅ **Positive security impact**
- Prevents leakage of unrequested fields
- Sensitive data not exposed unless explicitly requested
- Consistent security posture across queries and mutations

---

## Migration Path

### For Users

1. **No action required**: Existing mutations continue to work
2. **Optional optimization**: Mutations automatically benefit from smaller responses
3. **Framework guarantee**: Field selection will be respected

### For Contributors

1. Update mutation response builders to pass `info` parameter
2. Use new `extract_field_selections()` utility
3. Tests will verify field filtering works correctly

---

## Success Criteria

- [x] Architecture designed
- [ ] FFI boundary extended
- [ ] Mutation resolvers updated
- [ ] Rust filtering implemented
- [ ] All tests passing (30+ tests)
- [ ] Performance benchmarks show improvement
- [ ] Documentation updated
- [ ] Issue #525 resolved

---

## Timeline

| Phase | Duration | Owner |
|-------|----------|-------|
| Step 1: Infrastructure | 4h | Architecture |
| Step 2: Mutation Integration | 6h | Framework |
| Step 3: Rust Implementation | 4h | Rust |
| Step 4: Testing | 4h | QA |
| Step 5: Documentation | 2h | Docs |
| **Total** | **20h** | - |

**Estimated Completion**: 2-3 days for full implementation

---

## Related Issues

- **PrintOptim #525**: Mutation field selection (reported issue)
- **FraiseQL Issue**: Field selection consistency

---

## Notes

This enhancement improves FraiseQL's compliance with GraphQL specification and resolves the inconsistency between queries and mutations. It's a foundational improvement for Phase 6 Enterprise Features.

The implementation leverages existing infrastructure (`selection_filter.py`, unified FFI) and extends it to cover all response types.

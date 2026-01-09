---
name: Phase 6 Enhancement
about: Enterprise feature enhancement for FraiseQL Phase 6
title: "[Phase 6] "
labels: enhancement, phase-6
assignees: ''

---

## Phase 6.1: Mutation Field Selection Filtering

**Related Issue**: [PrintOptim #525](https://github.com/zedix/printoptim_backend/issues/525)

### Problem Statement

FraiseQL mutations return **all fields** for nested entities regardless of GraphQL field selection, causing:

- Larger response payloads (unnecessary data transfer)
- Potential security issues (unrequested fields exposed)
- Inconsistent behavior between queries and mutations

### Expected Behavior

Mutations should respect GraphQL field selection at the FFI boundary, similar to how queries already do.

### Actual Behavior

```graphql
mutation CreateLocation {
  createLocation(input: {...}) {
    ... on CreateLocationSuccess {
      location {
        id
        name  # Only these fields requested
      }
    }
  }
}
```

Returns response with ALL location fields (100+ fields) instead of just `id` and `name`.

### Solution

Extend the unified FFI boundary to accept and apply GraphQL field selections for all response types (queries and mutations).

### Implementation Details

See: `docs/PHASE_6_MUTATION_FIELD_SELECTION.md`

**Duration**: ~20 hours
**Complexity**: Medium
**Risk**: Low (fully backward compatible)

### Checklist

- [ ] Design FFI extension
- [ ] Update Python FFI adapter
- [ ] Implement Rust filtering
- [ ] Add mutation integration
- [ ] Write comprehensive tests
- [ ] Update documentation
- [ ] Performance verification

### Success Criteria

- [x] Architecture designed
- [ ] FFI extended with field_selections parameter
- [ ] Mutation resolvers pass selections to FFI
- [ ] Rust implements field filtering
- [ ] 30+ tests pass (unit + integration)
- [ ] Response size reduced 30-50%
- [ ] Backward compatible (all existing mutations work)

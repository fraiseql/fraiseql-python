# Phase 4: Module Migration Strategy

**Status**: Started with Validation module ✅
**Milestone 1 Complete**: Validation module (id_policy.rs + input_processor.rs) successfully migrated
**Next**: Continue with modules in dependency order

---

## What's Done

### ✅ Module 1: Validation (COMPLETE)
- Files: `id_policy.rs`, `input_processor.rs`
- Location: `core/src/validation/`
- Status: Compiles, no PyO3, pure Rust
- Dependencies: serde, std::collections (internal only)

---

## Remaining Modules (Priority Order)

### Order Strategy: Leaves First (No Dependencies → Most Dependencies)

```
Level 1 (No internal dependencies):
├── graphql/types.rs (PyO3 removal ONLY)
└── security modules

Level 2 (Depends on Level 1):
├── query/ (depends on graphql)
├── db/pool (depends on config, error)
└── cache (depends on graphql, query, apq)

Level 3 (Orchestration):
├── pipeline/unified (depends on ALL above)
└── http/ (depends on pipeline)
```

---

## Module 2: GraphQL Types (NEXT)

**Files to migrate**:
- `src/graphql/types.rs` → `core/src/graphql/types.rs`

**Key transformation** (remove PyO3):

```rust
// BEFORE (in src/graphql/types.rs):
use pyo3::prelude::*;

#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParsedQuery {
    #[pyo3(get)]
    pub operation_type: OperationType,
    #[pyo3(get)]
    pub selections: Vec<FieldSelection>,
}

// AFTER (in core/src/graphql/types.rs):
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParsedQuery {
    pub operation_type: OperationType,
    pub selections: Vec<FieldSelection>,
}
```

**Process**:
1. `cp src/graphql/types.rs core/src/graphql/types.rs`
2. Remove all `use pyo3::*` lines
3. Remove all `#[pyclass]`, `#[pyo3(...)]` decorators
4. Update `core/src/graphql/mod.rs` to export types
5. `cargo check`

---

## Module 3: DB Pool

**File to migrate**:
- `src/db/pool.rs` → `core/src/db/pool.rs`

**PyO3 class to remove**:
```rust
#[pyclass(name = "DatabasePool")]
pub struct DatabasePool { ... }

#[pymethods]
impl DatabasePool { ... }
```

**Transformation pattern**:
```rust
// BEFORE
#[pyclass(name = "DatabasePool")]
pub struct DatabasePool {
    pool: Arc<tokio_postgres::Connection>,
}

#[pymethods]
impl DatabasePool {
    #[new]
    pub fn new(url: &str) -> PyResult<Self> {
        // ...
        Ok(Self { ... })
    }
}

// AFTER
pub struct DatabasePool {
    pool: Arc<tokio_postgres::Connection>,
}

impl DatabasePool {
    pub async fn new(url: &str) -> Result<Self> {
        // Keep async but remove PyResult
        Ok(Self { ... })
    }
}
```

---

## Module 4-10: Remaining Modules

### Query Module
**Files**: `src/query/*.rs` (9 files)
- Remove PyO3 from `mod.rs` entry points
- Keep pure Rust logic in `composer.rs`, `where_builder.rs`, etc.

### Cache Module
**Files**: `src/cache/*.rs` (11 files)
- Already pure Rust, copy as-is
- Fix imports once graphql/query migrated

### Security/RBAC
**Files**: `src/security/py_bindings.rs`, `src/rbac/py_bindings.rs`
- Move FFI to dedicated binding files
- Keep core logic in pure Rust files

### Pipeline Module
**Files**: `src/pipeline/unified.rs` (main PyO3 class)
- This is the **unified interface** (Phase 9)
- Remove PyO3, keep orchestration logic

### HTTP Module
**Files**: `src/http/axum_server.rs` (already pure Rust)
- Core HTTP server has no PyO3
- Copy most files as-is

---

## Common Patterns for Removal

### Pattern 1: PyFunction → Regular Function
```rust
// BEFORE
#[pyfunction]
pub fn parse_query(query: &str) -> PyResult<ParsedQuery> {
    Ok(ParsedQuery { ... })
}

// AFTER
pub fn parse_query(query: &str) -> Result<ParsedQuery> {
    Ok(ParsedQuery { ... })
}
```

### Pattern 2: PyClass with Async
```rust
// BEFORE
#[pyclass]
pub struct Pipeline {
    engine: Arc<Engine>,
}

#[pymethods]
impl Pipeline {
    pub fn execute<'py>(&self, py: Python<'py>, query: String) -> PyResult<Bound<'py, PyAny>> {
        let engine = self.engine.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            engine.execute(&query).await.map_err(|e| PyErr::new::<...>(e))
        })
    }
}

// AFTER
pub struct Pipeline {
    engine: Arc<Engine>,
}

impl Pipeline {
    pub async fn execute(&self, query: &str) -> Result<Vec<u8>> {
        self.engine.execute(query).await
    }
}
```

### Pattern 3: Error Conversion
```rust
// BEFORE
use pyo3::exceptions::PyValueError;
return Err(PyErr::new::<PyValueError, _>("Invalid query"));

// AFTER
use crate::error::FraiseQLError;
return Err(FraiseQLError::validation("Invalid query"));
```

---

## Testing After Each Module

After migrating each module:

```bash
# 1. Check compilation
cargo check -p fraiseql_core

# 2. Run tests
cargo test -p fraiseql_core

# 3. Verify no PyO3 in core
grep -r "pyo3" core/src/module_name/
# Should return nothing!
```

---

## Verification Checklist (Final)

Before committing Phase 4:

- [ ] All 8-10 modules migrated
- [ ] `cargo check` succeeds
- [ ] `cargo test` passes all tests
- [ ] `grep -r "pyo3" core/src/` returns NOTHING
- [ ] `cargo tree | grep pyo3` shows NO deps in core
- [ ] Python bindings still in `py/src/` (not removed)
- [ ] Old `src/` directory still exists (for reference)

---

## Commit Message Template

```
refactor(core): Migrate all modules from src/ to core/

Phase 4 of Rust-first architecture refactor:
- Migrate validation, graphql, db, query, cache modules
- Migrate security/rbac modules
- Migrate pipeline (unified interface)
- Migrate http module

All modules now use FraiseQLError instead of PyErr.
Core crate has ZERO PyO3 dependencies.
All tests pass.

Migrated modules:
✅ validation/ - id_policy, input_processor
✅ graphql/ - types (PyO3 removed), parser, directives
✅ db/ - pool, schema, transaction
✅ query/ - composer, builder, where_builder
✅ cache/ - query_result, executor, invalidator
✅ security/ - validators, rate_limit, profiles
✅ rbac/ - resolver, hierarchy, field_auth
✅ pipeline/ - unified (orchestrator)
✅ http/ - axum_server, middleware, websocket
```

---

## Next Steps After Phase 4

- **Phase 5**: Create Python bindings wrapper in `py/src/`
- **Phase 6**: Create CLI binary in `cli/src/`
- **Phase 7**: Testing strategy and integration
- **Phase 8**: Final integration and verification

---

## Tips for Success

1. **Migrate one module at a time** - Test after each
2. **Use search & replace** for pattern-based changes
3. **Keep old src/ directory** - Reference for imports
4. **Fix imports gradually** - Start with crate::error, crate::graphql, etc.
5. **Test frequently** - Don't migrate all modules then test

---

## Performance Note

After Phase 4 completes:
- ✅ Core can be tested without Python
- ✅ Core can be compiled as standalone binary
- ✅ Core can be used from TypeScript (future)
- ✅ Pure Rust benchmarking possible
- ✅ FFI overhead eliminated from core logic

# DB Module Migration Strategy (Phase 4)

**Status**: Planning
**Complexity**: HIGH
**Total Lines**: 4,411 across 15 files
**PyO3 Entrypoints**: 1 major struct (`DatabasePool`)
**Timeline**: 3-4 focused work sessions

---

## 🎯 Executive Summary

The db module is the largest component in Phase 4 migration. It contains:

- **Connection pooling** (deadpool-postgres wrapper)
- **Transaction management** (ACID transactions + savepoints)
- **Query execution** (JSONB result handling)
- **Health checks & metrics** (operational observability)
- **Error handling** (rich error context)
- **SSL/TLS support** (production security)

**Key Challenge**: The `DatabasePool` struct has extensive PyO3 wrappers for:
- Context manager support (`__aenter__`, `__aexit__`)
- Async method conversions (`future_into_py`)
- Python dictionary returns (`PyDict`)
- Parameter binding (`PyResult`, error conversion)

**Strategy**: Convert to pure Rust while preserving async/await semantics and error handling.

---

## 📊 File Dependency Graph

```
LEAF NODES (no internal dependencies):
├── errors.rs (131 lines)
│   └── Only depends: std
├── types.rs (189 lines)
│   └── Only depends: std, chrono, serde_json
├── health.rs (146 lines)
│   └── Only depends: std, serde
├── metrics.rs (216 lines)
│   └── Only depends: std, serde
├── mutex_recovery.rs (170 lines)
│   └── Only depends: std
└── runtime.rs (256 lines)
    └── Only depends: std, tokio

INTERMEDIATE NODES (depend on leaf nodes):
├── pool_config.rs (371 lines)
│   └── Depends: errors, types, std
├── pool/traits.rs (106 lines)
│   └── Depends: async_trait
├── parameter_binding.rs (376 lines)
│   └── Depends: types, serde_json
└── query.rs (401 lines)
    └── Depends: types, errors, serde_json

CORE NODES (depend on intermediates):
├── pool_production.rs (571 lines)
│   └── Depends: errors, metrics, parameter_binding, pool_config, types
├── transaction.rs (617 lines)
│   └── Depends: errors, types, parameter_binding
└── pool.rs (548 lines)
    └── Depends: pool_config, pool_production, pyo3 (PyO3 wrappers only)

TOP LEVEL:
└── mod.rs (39 lines)
    └── Re-exports all above

SPECIAL CASES:
├── prototype.rs (274 lines) - Phase 0 testing, can skip
└── pool/mutex_recovery.rs (170 lines) - Already pure Rust
```

---

## ✅ Migration Path (Leaves-First Strategy)

### Phase 4.1: Pure Rust Core Modules (No PyO3)

**Objective**: Migrate all pure Rust modules first to establish stable foundation.

#### Step 1: Error Types (errors.rs - 131 lines) ⭐ FIRST
- **PyO3 Conversion**: None needed - already pure Rust
- **Transformation**: Direct copy with Rust ergonomics
- **Action**:
  ```bash
  cp src/db/errors.rs core/src/db/errors.rs
  ```
- **Testing**: No tests in original, add doc examples
- **Verification**: `cargo check`, no warnings

#### Step 2: Type Definitions (types.rs - 189 lines)
- **PyO3 Conversion**: None needed - already pure Rust
- **Transformation**: Direct copy
- **Action**:
  ```bash
  cp src/db/types.rs core/src/db/types.rs
  ```
- **Testing**: Add tests for `QueryParam` enum variants
- **Verification**: `cargo check`

#### Step 3: Health Check Types (health.rs - 146 lines)
- **PyO3 Conversion**: None needed - already pure Rust
- **Transformation**: Direct copy
- **Action**:
  ```bash
  cp src/db/health.rs core/src/db/health.rs
  ```
- **Verification**: `cargo check`

#### Step 4: Metrics (metrics.rs - 216 lines)
- **PyO3 Conversion**: None needed - already pure Rust
- **Transformation**: Direct copy
- **Action**:
  ```bash
  cp src/db/metrics.rs core/src/db/metrics.rs
  ```
- **Verification**: `cargo check`

#### Step 5: Mutex Recovery (mutex_recovery.rs - 170 lines)
- **PyO3 Conversion**: None needed - already pure Rust
- **Transformation**: Direct copy
- **Action**:
  ```bash
  cp src/db/mutex_recovery.rs core/src/db/mutex_recovery.rs
  ```
- **Verification**: `cargo check`

#### Step 6: Tokio Runtime (runtime.rs - 256 lines)
- **PyO3 Conversion**: None needed - already pure Rust
- **Transformation**: Direct copy
- **Action**:
  ```bash
  cp src/db/runtime.rs core/src/db/runtime.rs
  ```
- **Verification**: `cargo check`

**Checkpoint 1**: After Step 1-6, verify:
```bash
cargo check -p fraiseql_core
cargo test -p fraiseql_core
```

Should have ~6-8 new passing tests.

---

### Phase 4.2: Intermediate Configuration Modules (No PyO3)

**Objective**: Migrate configuration builders that don't use PyO3.

#### Step 7: Pool Configuration (pool_config.rs - 371 lines)
- **PyO3 Conversion**:
  - Remove imports: `use pyo3::prelude::*`
  - Remove `#[pyclass(name="DatabaseConfig")]` decorator
  - Remove `#[pyo3(get)]` on struct fields
  - Remove `#[pymethods]` impl block
- **Transformation Pattern**:
  ```rust
  // BEFORE (with PyO3)
  #[pyclass(name = "DatabaseConfig")]
  pub struct DatabaseConfig {
      #[pyo3(get)]
      pub database: String,
  }

  #[pymethods]
  impl DatabaseConfig {
      #[new]
      pub fn py_new(database: &str) -> PyResult<Self> { ... }
  }

  // AFTER (pure Rust)
  pub struct DatabaseConfig {
      pub database: String,
  }

  impl DatabaseConfig {
      pub fn new(database: &str) -> Self { ... }
  }
  ```
- **Key Changes**:
  - `PyResult<T>` → `Result<T, DatabaseError>`
  - `PyValueError` → `DatabaseError::Configuration`
  - `#[pyo3(...)]` annotations → nothing
- **Action**: Copy file, remove all PyO3, update error handling
- **Testing**: Add tests for builder pattern
- **Verification**: `cargo check`

#### Step 8: Pool Traits (pool/traits.rs - 106 lines)
- **PyO3 Conversion**: None needed - already pure Rust
- **Transformation**: Direct copy
- **Action**:
  ```bash
  cp src/db/pool/traits.rs core/src/db/pool/traits.rs
  ```
- **Verification**: `cargo check`

#### Step 9: Parameter Binding (parameter_binding.rs - 376 lines)
- **PyO3 Conversion**: None needed - already pure Rust
- **Transformation**: Direct copy
- **Action**:
  ```bash
  cp src/db/parameter_binding.rs core/src/db/parameter_binding.rs
  ```
- **Testing**: Already has tests, verify they pass
- **Verification**: `cargo check`

#### Step 10: Query Execution Types (query.rs - 401 lines)
- **PyO3 Conversion**: None needed - already pure Rust
- **Transformation**: Direct copy
- **Action**:
  ```bash
  cp src/db/query.rs core/src/db/query.rs
  ```
- **Verification**: `cargo check`

**Checkpoint 2**: After Step 7-10:
```bash
cargo check -p fraiseql_core
cargo test -p fraiseql_core
```

Should have 20-25 passing tests.

---

### Phase 4.3: Core Pool Implementation (Complex - Handle with Care)

**Objective**: Migrate the actual pool implementation before the PyO3 wrapper.

#### Step 11: Production Pool (pool_production.rs - 571 lines)
- **PyO3 Conversion**: None needed - already pure Rust
- **Transformation**: Direct copy
- **Key Points**:
  - This is the CORE pool logic (deadpool-postgres wrapper)
  - All methods are already `async fn` (not PyO3-wrapped)
  - Returns `Result<T, DatabaseError>` (not `PyResult`)
- **Action**:
  ```bash
  cp src/db/pool_production.rs core/src/db/pool_production.rs
  ```
- **Testing**: Already has async tests, verify with `cargo test`
- **Verification**: `cargo check`

#### Step 12: Transaction Management (transaction.rs - 617 lines)
- **PyO3 Conversion**: None needed - already pure Rust
- **Transformation**: Direct copy
- **Key Points**:
  - Pure Rust transaction handling
  - No PyO3 dependencies
  - Async transaction methods
- **Action**:
  ```bash
  cp src/db/transaction.rs core/src/db/transaction.rs
  ```
- **Verification**: `cargo check`

#### Step 13: Database Pool Wrapper (pool.rs - 548 lines)
- **PyO3 Conversion**: This is the BIG ONE ⚠️
- **Transformation Pattern**:
  ```rust
  // BEFORE
  #[pyclass(name = "DatabasePool")]
  pub struct DatabasePool {
      inner: Arc<ProductionPool>,
  }

  #[pymethods]
  impl DatabasePool {
      #[new]
      #[pyo3(signature = (database=None, host="localhost", ...))]
      fn py_new(...) -> PyResult<Self> { ... }

      #[pyo3(name = "execute_query")]
      fn execute_query_py<'py>(&self, py: Python<'py>, sql: String)
          -> PyResult<Bound<'py, PyAny>> {
          future_into_py(py, async move { ... })
      }
  }

  // AFTER
  pub struct DatabasePool {
      inner: Arc<ProductionPool>,
  }

  impl DatabasePool {
      pub fn new(
          database: Option<&str>,
          host: &str,
          port: u16,
          username: &str,
          password: Option<&str>,
          max_size: usize,
          ssl_mode: &str,
          url: Option<&str>,
      ) -> Result<Self, DatabaseError> { ... }

      pub async fn execute_query(&self, sql: &str)
          -> Result<Vec<String>, DatabaseError> {
          self.inner.execute_query(sql).await
      }
  }
  ```

- **Detailed Changes**:
  1. **Remove PyO3 decorators**:
     - Remove `#[pyclass(name = "DatabasePool")]`
     - Remove `#[pymethods]` blocks
     - Remove `#[pyo3(name = "...")]` method renames
     - Remove `#[pyo3(signature = (...))]` parameter specs

  2. **Convert error types**:
     - `PyResult<T>` → `Result<T, DatabaseError>`
     - `pyo3::exceptions::PyValueError` → `DatabaseError::Configuration`
     - `pyo3::exceptions::PyRuntimeError` → `DatabaseError::QueryExecution`
     - `.map_err(|e| PyErr::new::<...>(e.to_string()))` → `.map_err(|e| DatabaseError::...)`

  3. **Convert async methods**:
     - Remove `<'py>(&self, py: Python<'py>)` signature
     - Change to `async fn execute_query(&self, sql: &str)`
     - Remove `future_into_py(py, async move { ... })` wrapper
     - Return raw `Result<T, DatabaseError>` (not wrapped)

  4. **Convert context manager**:
     - Remove `fn __aenter__<'py>` and `fn __aexit__<'py>`
     - Implement Rust traits: `AsyncContextManager` or similar
     - Or just provide explicit `connect()` and `close()` methods

  5. **Convert Python dict returns**:
     - Remove `PyDict::new(py)` calls
     - Return structured types instead: `struct PoolStats { ... }`
     - Let Python layer convert to dict via PyO3 (Phase 5)

- **Step-by-step Changes**:

  **Part A: Remove all PyO3 imports and decorators**
  ```rust
  // Remove these lines
  use pyo3::prelude::*;
  use pyo3::types::PyDict;
  use pyo3_async_runtimes::tokio::future_into_py;

  // Remove from struct
  #[pyclass(name = "DatabasePool")]

  // Remove from impl block
  #[pymethods]
  ```

  **Part B: Convert DatabasePool::new() method**
  ```rust
  // BEFORE
  #[new]
  #[pyo3(signature = (...))]
  fn py_new(...) -> PyResult<Self> {
      let config = if let Some(url_str) = url {
          DatabaseConfig::from_url(url_str)
              .map_err(|e| pyo3::exceptions::PyValueError::new_err(...))?
      } else { ... };

      let inner = ProductionPool::new(config)
          .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(...))?;
      Ok(Self { ... })
  }

  // AFTER
  pub fn new(
      database: Option<&str>,
      host: &str,
      port: u16,
      username: &str,
      password: Option<&str>,
      max_size: usize,
      ssl_mode: &str,
      url: Option<&str>,
  ) -> Result<Self, DatabaseError> {
      let config = if let Some(url_str) = url {
          DatabaseConfig::from_url(url_str)?
      } else {
          let database = database
              .ok_or(DatabaseError::Configuration("database required".into()))?;
          // ... build config
      };

      let inner = ProductionPool::new(config)?;
      Ok(Self { inner: Arc::new(inner) })
  }
  ```

  **Part C: Convert async methods**
  ```rust
  // BEFORE
  #[pyo3(name = "execute_query")]
  fn execute_query_py<'py>(&self, py: Python<'py>, sql: String)
      -> PyResult<Bound<'py, PyAny>> {
      let pool = Arc::clone(&self.inner);
      future_into_py(py, async move {
          let results = pool.execute_query(&sql).await
              .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(...))?;
          let json_strings: Result<Vec<String>, _> =
              results.iter().map(serde_json::to_string).collect();
          json_strings.map_err(|e| pyo3::exceptions::PyValueError::new_err(...))
      })
  }

  // AFTER
  pub async fn execute_query(&self, sql: &str)
      -> Result<Vec<String>, DatabaseError> {
      let results = self.inner.execute_query(sql).await?;
      results.iter()
          .map(serde_json::to_string)
          .collect::<Result<Vec<String>, _>>()
          .map_err(|e| DatabaseError::QueryExecution(e.to_string()))
  }
  ```

  **Part D: Convert dict-returning methods**
  ```rust
  // BEFORE
  fn stats(&self, py: Python) -> PyResult<Py<PyDict>> {
      let stats = self.inner.stats();
      let dict = PyDict::new(py);
      dict.set_item("size", stats.size)?;
      // ...
      Ok(dict.into())
  }

  // AFTER (option 1: return struct)
  pub fn stats(&self) -> PoolStats {
      let stats = self.inner.stats();
      PoolStats {
          size: stats.size,
          available: stats.available,
          max_size: stats.max_size,
          active: stats.size - stats.available,
      }
  }

  // Later in py/src/lib.rs, convert PoolStats to PyDict via PyO3
  ```

  **Part E: Remove context manager (or adapt)**
  ```rust
  // REMOVE these methods entirely
  fn __aenter__<'py>(&self, py: Python<'py>) -> ... { }
  fn __aexit__<'py>(&self, py: Python<'py>, ...) -> ... { }

  // KEEP simple methods
  pub fn close(&self) { self.inner.close(); }
  ```

- **Testing Strategy**:
  - Keep all existing async tests
  - Update test signatures: `fn py_new()` → `fn new()`
  - Remove `PyResult` error handling, use `Result<T, DatabaseError>`
  - Add tests for error cases

- **Verification**:
  ```bash
  cargo check -p fraiseql_core
  cargo test -p fraiseql_core --lib
  ```

**Checkpoint 3**: After Step 11-13:
- All db module files migrated
- No PyO3 in `core/src/db/`
- All tests passing
- Full compilation succeeds

---

### Phase 4.4: Module Integration & Finalization

#### Step 14: Update Module Declarations (mod.rs)
- **Action**: Create `core/src/db/mod.rs` with all re-exports
- **Template**:
  ```rust
  //! Database layer (pure Rust, no PyO3)

  pub mod errors;
  pub mod health;
  pub mod metrics;
  pub mod mutex_recovery;
  pub mod parameter_binding;
  pub mod pool;
  pub mod pool_config;
  pub mod pool_production;
  pub mod query;
  pub mod runtime;
  pub mod transaction;
  pub mod types;

  pub use errors::{DatabaseError, DatabaseResult};
  pub use health::HealthCheckResult;
  pub use metrics::PoolMetrics;
  pub use mutex_recovery::recover_from_poisoned;
  pub use pool::{DatabasePool, PoolBackend};
  pub use pool_config::DatabaseConfig;
  pub use pool_production::ProductionPool;
  pub use types::{PoolConfig, QueryParam};
  ```

- **Verification**: `cargo check`

#### Step 15: Verification & Testing
- **Comprehensive Checks**:
  ```bash
  # Check compilation
  cargo check -p fraiseql_core

  # Run all tests
  cargo test -p fraiseql_core

  # Verify NO PyO3 in core/src/db/
  grep -r "pyo3" core/src/db/ | wc -l
  # Should return: 0

  # Check full Cargo tree
  cargo tree -p fraiseql_core | grep pyo3
  # Should return: nothing
  ```

- **Test Results Expected**:
  - 70-80+ tests passing
  - 0 failures
  - 0 warnings

#### Step 16: Create Python Bindings Wrapper (Phase 5 planning)
- **Note**: Don't implement yet, just plan the structure
- **Location**: `py/src/lib.rs`
- **Purpose**: Wrap pure Rust types with PyO3 for Python compatibility
- **Examples**:
  ```rust
  // Phase 5: In py/src/lib.rs
  #[pyclass]
  pub struct DatabasePool {
      inner: fraiseql_core::db::DatabasePool,
  }

  #[pymethods]
  impl DatabasePool {
      #[new]
      pub fn new(...) -> PyResult<Self> { ... }

      fn execute_query_py<'py>(&self, py: Python<'py>, sql: String)
          -> PyResult<Bound<'py, PyAny>> {
          future_into_py(py, async move {
              self.inner.execute_query(&sql).await
          })
      }
  }
  ```

---

## 🔑 Key Design Decisions

### Decision 1: Error Handling Strategy
- **Choice**: Use `DatabaseError` enum (not `anyhow::Error`)
- **Rationale**:
  - Explicit error types for Rust layer
  - Python layer can convert to exceptions via PyO3
  - Better error handling in pure Rust code
- **Implementation**: All methods return `Result<T, DatabaseError>`

### Decision 2: Async/Await Without PyO3
- **Choice**: Use native Rust `async/await` (no `future_into_py`)
- **Rationale**:
  - Core logic is pure Rust async
  - Python integration happens in separate `py/` crate
  - Enables standalone Rust usage
- **Implementation**: Methods are `pub async fn(...) -> Result<T>`

### Decision 3: Python Integration Point
- **Choice**: Move all PyO3 wrappers to `py/src/lib.rs`
- **Rationale**:
  - Core is truly language-agnostic
  - Python bindings are thin wrapper layer
  - Enables future TypeScript/WASM bindings
- **Timing**: Phase 5

### Decision 4: Return Type Conversions
- **Choice**: Return pure Rust structs, convert to Python in `py/`
- **Examples**:
  - `stats()` returns `PoolStats` struct (not `PyDict`)
  - `execute_query()` returns `Vec<String>` (not Python list)
  - `health_check()` returns `HealthCheckResult` struct
- **Rationale**: Core layer doesn't know about Python

---

## ⚠️ Common Pitfalls & Mitigations

### Pitfall 1: Forgetting `Arc` Cloning
- **Problem**: Async closures in old code use `Arc::clone(&self.inner)`
- **Mitigation**: In pure Rust version, just use `self.inner` directly (Arc is already Clone)
- **Example**:
  ```rust
  // BEFORE (with future_into_py)
  let pool = Arc::clone(&self.inner);
  future_into_py(py, async move { pool.execute_query(...) })

  // AFTER (native async)
  pub async fn execute_query(&self, ...) {
      self.inner.execute_query(...)  // No cloning needed!
  }
  ```

### Pitfall 2: Error Type Conversions
- **Problem**: PyO3 errors don't map 1:1 to Rust error types
- **Mitigation**: Create explicit conversion in DatabaseError
- **Example**:
  ```rust
  // Use match/map_err consistently
  pool.execute_query(&sql).await
      .map_err(|e| DatabaseError::QueryExecution(e.to_string()))?
  ```

### Pitfall 3: Context Manager Loss
- **Problem**: `__aenter__` / `__aexit__` can't exist in pure Rust
- **Mitigation**: Implement Rust traits or use `scopeguard`
- **Alternative**: Python layer handles context manager wrapping

### Pitfall 4: Dictionary Returns
- **Problem**: `PyDict` doesn't exist in pure Rust
- **Mitigation**: Return structured types (structs) instead
- **Conversion**: Python layer wraps in PyDict via PyO3

### Pitfall 5: Module Organization
- **Problem**: Easy to forget creating `/pool/` subdirectory
- **Mitigation**: Create `core/src/db/pool/` directory and `mod.rs`
- **Checklist**:
  ```
  core/src/db/
  ├── mod.rs (main)
  ├── errors.rs
  ├── pool/
  │   ├── mod.rs
  │   └── traits.rs
  ├── pool_config.rs
  ├── pool_production.rs
  └── [... other files ...]
  ```

---

## 📋 Execution Checklist

- [ ] Phase 4.1: Pure Rust core modules (Steps 1-6)
  - [ ] errors.rs copied
  - [ ] types.rs copied
  - [ ] health.rs copied
  - [ ] metrics.rs copied
  - [ ] mutex_recovery.rs copied
  - [ ] runtime.rs copied
  - [ ] `cargo check` passes
  - [ ] Tests passing
  - [ ] No PyO3 in core/src/db/

- [ ] Phase 4.2: Configuration modules (Steps 7-10)
  - [ ] pool_config.rs migrated (remove PyO3)
  - [ ] pool/traits.rs copied
  - [ ] parameter_binding.rs copied
  - [ ] query.rs copied
  - [ ] `cargo check` passes
  - [ ] Tests passing

- [ ] Phase 4.3: Core pool & transactions (Steps 11-13)
  - [ ] pool_production.rs copied
  - [ ] transaction.rs copied
  - [ ] pool.rs migrated (remove all PyO3)
  - [ ] Async methods converted
  - [ ] Error handling updated
  - [ ] Dict returns refactored
  - [ ] Context managers handled
  - [ ] `cargo check` passes
  - [ ] All tests passing

- [ ] Phase 4.4: Integration (Steps 14-16)
  - [ ] mod.rs created with re-exports
  - [ ] Verification checks:
    - [ ] `grep -r "pyo3" core/src/db/` returns 0
    - [ ] `cargo test -p fraiseql_core` all pass
    - [ ] `cargo check -p fraiseql_core` no warnings
  - [ ] Git commit prepared
  - [ ] Phase 5 plan documented

---

## 🚀 Success Criteria

After completing db module migration:

1. **Zero PyO3 Dependencies** in `core/src/db/`
   ```bash
   grep -r "pyo3" core/src/db/ | wc -l  # Should be: 0
   ```

2. **All Tests Passing**
   ```bash
   cargo test -p fraiseql_core  # All green ✓
   ```

3. **Clean Compilation**
   ```bash
   cargo check -p fraiseql_core  # No warnings
   ```

4. **Async/Await Works**
   - Can call `await` on `execute_query()`
   - Can use `tokio::spawn()` with pool methods
   - Error handling chains work seamlessly

5. **Python Integration Ready**
   - `DatabasePool` struct is ready for `py/` wrapping
   - All methods have clear Python equivalents
   - Error types can convert to PyErr

6. **Documentation Updated**
   - Doc comments on all public methods
   - Examples showing pure Rust usage
   - Async/await patterns documented

---

## 📝 Commit Template

```
refactor(core): Phase 4 - Migrate database module (remove PyO3)

## Summary
Migrated complete db module from src/db/ to core/src/db/ with all PyO3
dependencies removed. Database pool, transactions, and query execution
now use pure Rust async/await without any FFI binding code.

## Changes
- Migrated 15 files totaling 4,411 lines
- Converted DatabasePool from PyClass to pure Rust struct
- Removed all PyO3 decorators and async conversion wrappers
- Updated error handling: PyResult → Result<T, DatabaseError>
- Refactored dict returns to structured types

## Migration Path
✅ Phase 4.1: Pure Rust core modules (errors, types, health, etc.)
✅ Phase 4.2: Configuration modules (pool_config, parameter_binding)
✅ Phase 4.3: Core pool & transactions (pool_production, pool.rs)
✅ Phase 4.4: Integration & verification

## Files Changed
- core/src/db/mod.rs (new)
- core/src/db/errors.rs (migrated)
- core/src/db/types.rs (migrated)
- core/src/db/health.rs (migrated)
- core/src/db/metrics.rs (migrated)
- core/src/db/mutex_recovery.rs (migrated)
- core/src/db/runtime.rs (migrated)
- core/src/db/pool_config.rs (migrated + PyO3 removed)
- core/src/db/pool/traits.rs (migrated)
- core/src/db/pool/mod.rs (new)
- core/src/db/parameter_binding.rs (migrated)
- core/src/db/query.rs (migrated)
- core/src/db/pool_production.rs (migrated)
- core/src/db/transaction.rs (migrated)
- core/src/db/pool.rs (migrated + major PyO3 refactor)

## Verification
✅ cargo check -p fraiseql_core: passes
✅ cargo test -p fraiseql_core: 80+ tests passing
✅ No PyO3 in core/src/db/ (grep verified)
✅ All async methods working (tested)
✅ Error handling updated (tested)
✅ Pre-commit hooks passing

## Next Steps
- Phase 5: Create Python bindings wrapper in py/src/
- Wrap core::db types with PyO3 for Python compatibility
```

---

## 🎓 Learning Resources

### Async Rust Pattern
- Remove `<'py>&self, py: Python<'py>` from method signatures
- Replace `future_into_py(py, async move { ... })` with `pub async fn`
- Return `Result<T, DatabaseError>` directly (not wrapped)

### Error Handling Pattern
- Replace all `PyErr::new::<SomeError, _>(msg)` with `DatabaseError::Variant(msg)`
- Chain errors with `?` operator instead of `.map_err(|e| PyErr::...)`
- Let Python layer convert `DatabaseError` to exceptions

### Type Conversion Pattern
- Instead of `PyDict::new(py)` → return `PoolStats` struct
- Instead of `dict.set_item(...)` → implement struct fields
- Python layer converts struct to dict via `#[pyo3]`

---

## 📊 Complexity Analysis

| Component | Lines | Complexity | PyO3 Removal | Effort |
|-----------|-------|-----------|--------------|--------|
| errors.rs | 131 | Low | None | Trivial |
| types.rs | 189 | Low | None | Trivial |
| health.rs | 146 | Low | None | Trivial |
| metrics.rs | 216 | Low | None | Trivial |
| mutex_recovery.rs | 170 | Low | None | Trivial |
| runtime.rs | 256 | Low | None | Trivial |
| pool_config.rs | 371 | Medium | Remove decorators | Low |
| pool/traits.rs | 106 | Low | None | Trivial |
| parameter_binding.rs | 376 | Medium | None | Trivial |
| query.rs | 401 | Medium | None | Trivial |
| pool_production.rs | 571 | High | None | Medium |
| transaction.rs | 617 | High | None | Medium |
| pool.rs | 548 | **VERY HIGH** | Remove PyMethods | **HIGH** |
| mod.rs | 39 | Low | None | Trivial |
| **TOTAL** | **4,411** | - | 2 files | **5-8 hours** |

---

**Status**: Ready for implementation
**Next Action**: Begin Phase 4.1 with errors.rs migration

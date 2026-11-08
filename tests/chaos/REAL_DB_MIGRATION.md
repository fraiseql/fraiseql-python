# Chaos Tests Real PostgreSQL Migration Guide

## Overview

This document describes the transformation of FraiseQL chaos engineering tests from mock-based to real PostgreSQL database backend. The transformation enables actual chaos testing with real network failures, database timeouts, and genuine error conditions.

**Status**: Transformation in progress
**Last Updated**: 2025-12-21

---

## Why Real Database Backend?

### Problems with Mock Client

The previous `MockFraiseQLClient` approach had fundamental limitations:

1. **No real network effects**: Toxiproxy chaos injection didn't affect the mock client
2. **Artificial error conditions**: Mock errors didn't reflect real database failures
3. **Unrealistic timing**: Simulated execution times weren't representative
4. **Pool exhaustion not real**: Couldn't test actual connection pool behavior
5. **Transaction behavior unrealistic**: Couldn't test real deadlocks, serialization failures

### Benefits of Real Database

With the real PostgreSQL backend:

✅ **Actual chaos effects**: Network delays genuinely affect query execution
✅ **Real error conditions**: Connection failures, timeouts, deadlocks are real
✅ **Accurate performance metrics**: Measure actual database response times
✅ **Pool behavior realistic**: Test real connection pool exhaustion
✅ **Transaction testing**: Real locks, deadlocks, isolation anomalies

---

## Architecture

### Component Overview

```
Test File
  ├─ pytest functions (async) - Not unittest.TestCase classes!
  ├─ Uses fixtures: chaos_db_client, chaos_test_schema, baseline_metrics
  └─ Each test handles chaos injection and measurement

chaos_db_client (RealFraiseQLClient)
  ├─ Executes queries against real PostgreSQL
  ├─ Simulates chaos: connection_disabled, latency_ms, packet_loss_rate
  ├─ Measures actual execution time
  └─ Returns results with _execution_time_ms metadata

chaos_test_schema (from database_conftest.py)
  ├─ Per-class database schema isolation
  ├─ Automatic transaction rollback per test
  ├─ PostgreSQL container with testcontainers
  └─ Fixtures: test_schema, class_db_pool, db_connection

Toxiproxy (Optional)
  ├─ Real network chaos injection
  ├─ Auto-detects if available (mock mode fallback)
  ├─ Affects actual database connections
  └─ Example: Toxiproxy.add_latency_toxic()
```

### Key Differences from Old Tests

| Aspect | Old (Mock) | New (Real DB) |
|--------|-----------|--------------|
| **Test Style** | `unittest.TestCase` class | `async def` pytest function |
| **Client** | `MockFraiseQLClient` | `RealFraiseQLClient` |
| **Database** | None (all simulated) | Real PostgreSQL container |
| **Fixtures** | Manual init in test | pytest fixtures |
| **Concurrency** | Simulated with sleep | Real with asyncio |
| **Errors** | Thrown when expected | Thrown when real |
| **Timing** | Hardcoded delays | Real execution times |

---

## Implementation Steps

### Step 1: Understand the Fixtures (✅ Done)

Located in `/home/lionel/code/fraiseql/tests/fixtures/database/database_conftest.py`:

- **`postgres_container`**: Docker PostgreSQL instance (session-scoped)
- **`postgres_url`**: Connection URL
- **`class_db_pool`**: AsyncConnectionPool (per test class)
- **`test_schema`**: Isolated schema per test class
- **`db_connection`**: Per-test connection with auto-rollback
- **`clear_registry`**: Clears FraiseQL global state

These are inherited automatically by any conftest that imports them.

### Step 2: Create Chaos-Specific Fixtures (✅ Done)

File: `/home/lionel/code/fraiseql/tests/chaos/database_fixtures.py`

Key components:

```python
class RealFraiseQLClient:
    """Real client executing against PostgreSQL."""

    async def execute_query(self, operation, timeout=30.0):
        """Execute operation against real database."""
        # 1. Check chaos conditions
        # 2. Apply latency
        # 3. Acquire connection from pool
        # 4. Execute query
        # 5. Measure execution time
        # 6. Return result with _execution_time_ms

    def inject_latency(self, latency_ms):
        """Simulate network latency."""

    def inject_connection_failure(self):
        """Simulate connection failure."""

    def reset_chaos(self):
        """Clear all chaos conditions."""


@pytest_asyncio.fixture
async def chaos_db_client(class_db_pool, test_schema):
    """Provide real client connected to test database."""


@pytest_asyncio.fixture
async def chaos_test_schema(test_schema, db_connection):
    """Prepare schema with test tables (users, posts, comments)."""


@pytest.fixture
def baseline_metrics():
    """Load baseline performance metrics for comparison."""
```

### Step 3: Transform Test Files (✅ Started, Partially Done)

Example transformation for network/test_db_connection_chaos.py:

**Before (Mock-based):**

```python
class TestDatabaseConnectionChaos(ChaosTestCase):
    def test_connection_refused_recovery(self):
        toxiproxy = ToxiproxyManager()
        client = MockFraiseQLClient()
        operation = FraiseQLTestScenarios.simple_user_query()

        # All simulated...
```

**After (Real DB):**

```python
@pytest.mark.chaos
@pytest.mark.chaos_database
@pytest.mark.chaos_real_db
@pytest.mark.asyncio
async def test_connection_refused_recovery(chaos_db_client, chaos_test_schema, baseline_metrics):
    """Test recovery from connection refused."""
    operation = FraiseQLTestScenarios.simple_user_query()

    # Baseline: Measure normal operations
    baseline_times = []
    for _ in range(5):
        result = await chaos_db_client.execute_query(operation)
        baseline_times.append(result.get("_execution_time_ms"))

    # Inject chaos
    chaos_db_client.inject_connection_failure()

    # Measure failures during chaos
    errors_during_chaos = 0
    for _ in range(5):
        try:
            await chaos_db_client.execute_query(operation)
        except ConnectionError:
            errors_during_chaos += 1

    # Reset and verify recovery
    chaos_db_client.reset_chaos()

    # Validate...
    assert errors_during_chaos > 0
```

### Step 4: Key Changes to Make

#### 4.1 Test Structure

- **Remove**: `class TestXxx(ChaosTestCase):`
- **Add**: `@pytest.mark.asyncio` decorator on async functions
- **Remove**: `self.metrics` (create local `ChaosMetrics()` instance)
- **Remove**: Manual `setup_method()`/`teardown_method()`

#### 4.2 Client Initialization

- **Remove**: `client = MockFraiseQLClient()`
- **Add**: Accept `chaos_db_client` as parameter
- **Remove**: Toxiproxy manual setup (use auto-detection)

#### 4.3 Async/Await

- **Add**: `async def` to test functions
- **Add**: `await` to all `execute_query()` calls
- **Add**: `asyncio.TimeoutError` handling for timeouts

#### 4.4 Imports

- **Add**: `import asyncio`
- **Add**: `from chaos.base import ChaosMetrics`
- **Remove**: `from chaos.base import ChaosTestCase` (unless other tests in file use it)

### Step 5: Migration Patterns

#### Pattern 1: Simple Query Test

```python
@pytest.mark.asyncio
async def test_simple_scenario(chaos_db_client, chaos_test_schema):
    """Test scenario with real database."""
    operation = FraiseQLTestScenarios.simple_user_query()

    # No baseline needed if not comparing to mock
    result = await chaos_db_client.execute_query(operation)
    assert result.get("data") is not None
```

#### Pattern 2: Chaos Injection Test

```python
@pytest.mark.asyncio
async def test_chaos_scenario(chaos_db_client):
    """Test with chaos injection."""
    operation = FraiseQLTestScenarios.simple_user_query()

    # Baseline
    baseline = await chaos_db_client.execute_query(operation)
    baseline_time = baseline.get("_execution_time_ms")

    # Inject chaos
    chaos_db_client.inject_latency(1000)  # 1 second latency

    # Measure with chaos
    chaotic = await chaos_db_client.execute_query(operation)
    chaotic_time = chaotic.get("_execution_time_ms")

    # Verify impact
    assert chaotic_time > baseline_time * 0.9  # At least ~90% of injected latency

    # Recovery
    chaos_db_client.reset_chaos()
    recovered = await chaos_db_client.execute_query(operation)
    recovered_time = recovered.get("_execution_time_ms")
    assert recovered_time < baseline_time * 1.2
```

#### Pattern 3: Concurrent Chaos

```python
@pytest.mark.asyncio
async def test_concurrent_chaos(chaos_db_client):
    """Test concurrent operations under chaos."""
    operation = FraiseQLTestScenarios.simple_user_query()

    chaos_db_client.inject_latency(100)  # 100ms latency

    # Run 5 concurrent queries
    results = await asyncio.gather(
        *[chaos_db_client.execute_query(operation) for _ in range(5)], return_exceptions=True
    )

    # Validate all completed
    errors = [r for r in results if isinstance(r, Exception)]
    assert len(errors) == 0  # No errors during chaos
```

---

## Files Changed/Created

### Created Files

1. **`tests/chaos/database_fixtures.py`** (✅ Created)
   - `RealFraiseQLClient` class
   - `chaos_db_client` fixture
   - `chaos_test_schema` fixture
   - `baseline_metrics` fixture

2. **`tests/chaos/network/test_db_connection_chaos_real.py`** (✅ Created)
   - 4 new async test functions
   - Real database connection testing
   - Pool exhaustion, latency, mid-query failures

### Modified Files

1. **`tests/chaos/conftest.py`** (✅ Modified)
   - Added: `pytest_plugins = ["chaos.database_fixtures"]`

### Files to Transform (Still TODO)

#### Network Chaos Tests

- `tests/chaos/network/test_db_connection_chaos.py` - Create `_real` variant
- `tests/chaos/network/test_network_latency_chaos.py` - Create `_real` variant
- `tests/chaos/network/test_packet_loss_corruption.py` - Create `_real` variant

#### Database Chaos Tests

- `tests/chaos/database/test_query_execution_chaos.py` - Create `_real` variant
- `tests/chaos/database/test_data_consistency_chaos.py` - Create `_real` variant

#### Cache, Auth, Resource, Concurrency

- `tests/chaos/cache/test_*_validation.py` - Multiple `_real` variants
- `tests/chaos/auth/test_*_validation.py` - Multiple `_real` variants
- `tests/chaos/resources/test_*_validation.py` - Multiple `_real` variants
- `tests/chaos/concurrency/test_*_validation.py` - Multiple `_real` variants

---

## Migration Checklist

For each test file transformation:

- [ ] Create new `test_*_real.py` file
- [ ] Change test from `class TestXxx(ChaosTestCase)` to `async def test_xxx`
- [ ] Add `@pytest.mark.asyncio` and `@pytest.mark.chaos_real_db` decorators
- [ ] Add fixtures to function signature: `chaos_db_client`, `chaos_test_schema`, `baseline_metrics`
- [ ] Replace `MockFraiseQLClient()` with fixture parameter
- [ ] Replace `self.metrics` with local `ChaosMetrics()` instance
- [ ] Add `await` to all `execute_query()` calls
- [ ] Handle `asyncio.TimeoutError` in addition to other exceptions
- [ ] Add `import asyncio` if needed
- [ ] Test collection passes: `pytest test_*_real.py --collect-only`
- [ ] Run single test with verbose output to debug fixture issues

---

## Running Tests

### Collect Tests

```bash
pytest tests/chaos/network/test_db_connection_chaos_real.py --collect-only
```

### Run Single Test

```bash
pytest tests/chaos/network/test_db_connection_chaos_real.py::test_connection_refused_recovery -xvs
```

### Run All Chaos Real Tests

```bash
pytest tests/chaos/ -m chaos_real_db -v
```

### Run with Database Debug

```bash
# If tests hang waiting for database:
pytest tests/chaos/ -m chaos_real_db -v --timeout=30
```

---

## Troubleshooting

### Issue: Test times out waiting for database

**Cause**: PostgreSQL container not starting or conftest fixtures failing

**Solution**:

```bash
# Check if Docker is available
docker ps

# Check testcontainers logs
pytest tests/chaos/network/test_db_connection_chaos_real.py -xvs --tb=short

# Run a simpler fixture test first
pytest tests/fixtures/database/ -v --tb=short
```

### Issue: "fixture 'chaos_db_client' not found"

**Cause**: pytest_plugins not loading or conftest import issue

**Solution**:

```python
# In conftest.py, ensure this exists:
pytest_plugins = ["chaos.database_fixtures"]

# And database_fixtures.py has:
import pytest
import pytest_asyncio

@pytest_asyncio.fixture
async def chaos_db_client(...):
    ...
```

### Issue: "TypeError: execute_query() missing positional argument"

**Cause**: Test function is an instance method instead of standalone function

**Solution**:

```python
# Wrong:
class TestXxx:
    def test_foo(self, chaos_db_client):
        result = await chaos_db_client.execute_query(...)


# Correct:
@pytest.mark.asyncio
async def test_foo(chaos_db_client):
    result = await chaos_db_client.execute_query(...)
```

### Issue: "module 'chaos.fraiseql_scenarios' has no attribute..."

**Cause**: Import path issue in new test file

**Solution**:

```python
# Tests in tests/chaos/network/ need:
from chaos.fraiseql_scenarios import GraphQLOperation, FraiseQLTestScenarios

# NOT:
from tests.chaos.fraiseql_scenarios import ...
```

---

## Performance Expectations

### Real Database Overhead

Compared to mock tests:

- **Test execution**: 2-5x slower (real database I/O)
- **Setup/teardown**: Same (pytest fixtures handle it)
- **Memory usage**: Higher (PostgreSQL container)
- **Reliability**: Much higher (real conditions tested)

### Estimated Test Suite Times

- **Network chaos (4 tests × 3 functions)**: ~2-3 minutes
- **Database chaos (5 tests)**: ~3-5 minutes
- **Cache/Auth/Resources/Concurrency**: ~10-15 minutes
- **Total chaos suite**: ~15-25 minutes

---

## Next Steps

1. **Complete network chaos transformation** (3 files)
2. **Transform database chaos tests** (2 files)
3. **Transform cache chaos tests** (4 files)
4. **Transform auth chaos tests** (3 files)
5. **Transform resource chaos tests** (2 files)
6. **Transform concurrency chaos tests** (2 files)
7. **Verify full test suite passes**
8. **Document real vs mock test differences in CI/CD**

---

## References

- **Database Fixtures**: `tests/fixtures/database/database_conftest.py`
- **Real Client**: `tests/chaos/database_fixtures.py`
- **Example Tests**: `tests/chaos/network/test_db_connection_chaos_real.py`
- **GraphQL Scenarios**: `tests/chaos/fraiseql_scenarios.py`
- **ChaosMetrics**: `tests/chaos/base.py`

---

## Summary

The migration from mock-based to real PostgreSQL chaos tests is underway with:

✅ **Created**: Real client (`RealFraiseQLClient`) and fixtures
✅ **Created**: First example test suite (`test_db_connection_chaos_real.py`)
✅ **Established**: pytest-based async test pattern
✅ **Documented**: Migration guide and troubleshooting

⏳ **Remaining**: Transform remaining ~20 test files using the documented patterns

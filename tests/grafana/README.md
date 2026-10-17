# Grafana Dashboard Tests

Comprehensive test suite for FraiseQL Grafana dashboards ensuring high quality standards.

## Test Coverage

### 1. Dashboard Structure Tests (`test_dashboard_structure.py`)

**17 tests** validating dashboard JSON structure and Grafana compatibility:

- **File validation**: All 5 dashboards exist and contain valid JSON
- **Schema validation**: Required Grafana fields present (title, tags, panels, etc.)
- **Panel structure**: IDs, titles, types, grid positions, and targets
- **Template variables**: Environment variable configuration
- **Time configuration**: Default time ranges and refresh rates
- **Dashboard-specific content**: Each dashboard has expected panels
- **Tagging**: Proper tags for organization

### 2. SQL Query Tests (`test_sql_queries.py`)

**17 tests** validating SQL queries for correctness, performance, and security:

#### SQL Syntax (4 tests)

- Queries are not empty
- All queries have SELECT statements
- All queries have FROM clauses
- Consistent semicolon usage

#### Table References (2 tests)

- Queries reference valid FraiseQL tables
- Monitoring schema usage for observability tables

#### Grafana Variables (3 tests)

- Time range variables usage (`$__timeFrom()`, `$__timeTo()`, or `NOW()`)
- Environment variable filtering
- Custom time range variable usage

#### Query Performance (3 tests)

- Indexed columns in WHERE clauses
- Reasonable LIMIT values (≤1000 rows)
- Avoid SELECT * (use specific columns)

#### SQL Injection Prevention (2 tests)

- Variables properly quoted in WHERE clauses
- No dynamic SQL construction

#### Query Correctness (3 tests)

- Aggregates with proper GROUP BY clauses
- Valid JSONB operators (->>, ->)
- Valid CTE (WITH ... AS) syntax

### 3. Import Script Tests (`test_import_script.py`)

**16 tests** validating the import automation script:

#### Script Structure (4 tests)

- Script exists and is executable
- Has proper shebang (#!/bin/bash)
- Has error handling (set -e)

#### Script Content (5 tests)

- Configuration variables defined
- Grafana connectivity check
- Import function defined
- All dashboard files listed
- Error and success messages

#### Script Safety (3 tests)

- Proper variable quoting
- Safe exit codes
- File path validation

#### Script Help (2 tests)

- Header comments present
- Usage information documented

#### Script Dependencies (2 tests)

- Uses standard Unix tools (curl)
- Uses jq for JSON manipulation

#### Script Linting (1 test, optional)

- Passes shellcheck (if installed)

## Running Tests

### Run All Tests

```bash
# From project root
uv run pytest tests/grafana/ -v

# Expected output:
# ======================== 50 passed, 1 skipped in 0.38s ========================
```

### Run Specific Test Suite

```bash
# Structure tests only
uv run pytest tests/grafana/test_dashboard_structure.py -v

# SQL query tests only
uv run pytest tests/grafana/test_sql_queries.py -v

# Import script tests only
uv run pytest tests/grafana/test_import_script.py -v
```

### Run with Coverage

```bash
uv run pytest tests/grafana/ --cov=grafana --cov-report=html
```

### Run in Watch Mode

```bash
uv run pytest tests/grafana/ -f
```

## Known Exceptions

Some queries intentionally don't follow strict rules for valid reasons. These are documented in `conftest.py`:

### No Environment Filter

**Query**: `error_monitoring.Errors by Environment`

**Reason**: This panel intentionally shows data from ALL environments to compare error rates across environments.

### No Time Filter

**Query**: `database_pool.Pool Utilization Rate`

**Reason**: Shows latest connection pool utilization using complex CTE with DISTINCT ON.

### No GROUP BY

**Queries**:

- `error_monitoring.Error Resolution Status`
- `cache_hit_rate.Overall Cache Hit Rate`

**Reason**: These are single-row aggregate queries using FILTER clauses or CTEs that don't require GROUP BY.

## Test Philosophy

### High Standards

FraiseQL maintains **very high quality standards**. These tests ensure:

1. **Correctness**: SQL queries are syntactically valid and logically sound
2. **Performance**: Queries use indexed columns and reasonable limits
3. **Security**: No SQL injection vulnerabilities
4. **Maintainability**: Consistent structure and clear organization
5. **Grafana compatibility**: Dashboards work correctly in Grafana 9.0+

### Continuous Quality

Tests run automatically on:

- Every commit (via pre-commit hooks)
- Pull requests (via CI/CD)
- Before releases

### Failed Tests = Blocked Merge

If any test fails, the merge is blocked until fixed. This ensures dashboards remain production-ready.

## Adding New Dashboards

When adding a new dashboard:

1. **Add to file list** in all test files:

   ```python
   DASHBOARD_FILES = [
       "error_monitoring.json",
       "performance_metrics.json",
       "cache_hit_rate.json",
       "database_pool.json",
       "apq_effectiveness.json",
       "your_new_dashboard.json",  # Add here
   ]
   ```

2. **Add expected panels** to `test_dashboard_structure.py`:

   ```python
   def test_your_new_dashboard(self, dashboards):
       dashboard = dashboards["your_new_dashboard"]
       panel_titles = [p["title"] for p in dashboard["dashboard"]["panels"]]

       expected_panels = [
           "Panel 1 Title",
           "Panel 2 Title",
       ]

       for expected in expected_panels:
           assert expected in panel_titles, f"Your dashboard missing panel: {expected}"
   ```

3. **Add expected tags** to tag validation:

   ```python
   expected_tags = {
       # ... existing dashboards ...
       "your_new_dashboard": ["fraiseql", "your", "tags"],
   }
   ```

4. **Run tests** to verify:

   ```bash
   uv run pytest tests/grafana/ -v
   ```

5. **Add exceptions** if needed in `conftest.py`

## Modifying Existing Dashboards

When modifying dashboards:

1. **Make changes** to dashboard JSON
2. **Run tests** to catch issues:

   ```bash
   uv run pytest tests/grafana/ -v
   ```

3. **Fix any failures**
4. **If test is too strict**, add documented exception in `conftest.py`
5. **Update tests** if dashboard structure changed intentionally

## Test Maintenance

### When to Update Tests

- **Dashboard structure changes**: Update panel validation
- **New SQL patterns**: Add to known exceptions if valid
- **Grafana version upgrade**: Update schemaVersion expectations
- **New Grafana features**: Add validation for new features

### Test Performance

Current test performance:

- **50 tests** run in **<0.4 seconds**
- **Fast feedback** for development
- **No external dependencies** (except optional shellcheck)

## Integration with CI/CD

### GitHub Actions

```yaml
name: Test Grafana Dashboards

on: [push, pull_request]

jobs:
  test-dashboards:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install uv
          uv sync
      - name: Run dashboard tests
        run: uv run pytest tests/grafana/ -v
```

### Pre-commit Hook

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: test-grafana-dashboards
      name: Test Grafana Dashboards
      entry: uv run pytest tests/grafana/ -v
      language: system
      pass_filenames: false
      files: ^grafana/.*\.json$
```

## Troubleshooting

### Test Fails: "Dashboard file not found"

**Fix**: Check filename in `DASHBOARD_FILES` list matches actual file

### Test Fails: "Unknown table 'xxx'"

**Fix**: Add table to `EXPECTED_TABLES` in `test_sql_queries.py` if it's a valid FraiseQL table

### Test Fails: "Query should filter by '$environment'"

**Options**:

1. Add environment filter to query (recommended)
2. Add to known exceptions if multi-environment query is intentional

### Test Fails: "Query with aggregates needs GROUP BY"

**Options**:

1. Add GROUP BY clause (recommended)
2. Simplify to aggregate-only query
3. Add to known exceptions if structure is correct

### Shellcheck Test Skipped

**Optional**: Install shellcheck for bash script linting

```bash
# macOS
brew install shellcheck

# Ubuntu/Debian
apt-get install shellcheck

# Arch Linux
pacman -S shellcheck
```

## Benefits of This Test Suite

### For Developers

- **Fast feedback** (<0.4s)
- **Clear error messages**
- **Prevents regressions**
- **Documents expected structure**

### For Production

- **Prevents broken dashboards**
- **Ensures SQL injection safety**
- **Validates performance best practices**
- **Maintains consistency**

### For Users

- **Reliable dashboards**
- **Fast loading times**
- **Accurate data**
- **Professional quality**

## Future Enhancements

Potential test additions:

1. **Query execution tests** (requires test database)
   - Queries actually run without errors
   - Results match expected format

2. **Grafana API integration tests**
   - Dashboards import successfully
   - Datasource connections work

3. **Visual regression tests**
   - Dashboard screenshots match expected

4. **Load testing**
   - Queries perform well under load

5. **Alert validation**
   - Alert rules are syntactically valid

## Contributing

When contributing dashboard changes:

1. Ensure all tests pass
2. Add tests for new functionality
3. Document any intentional exceptions
4. Update this README if test structure changes

---

**Test Coverage**: 50 tests (49 passed, 1 skipped)
**Execution Time**: <0.4 seconds
**Last Updated**: October 11, 2025

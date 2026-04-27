# Changelog

All notable changes to FraiseQL are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.16.1] - 2026-04-27

### Fixed

- **`descendant_of_id` / `ancestor_of_id` on native SQL columns** — when a UUID
  field is registered in `table_columns` (i.e. a real column, not inside the JSONB
  `data` blob), fraiseql uses the `sql_column` lookup strategy for WHERE clauses.
  The hierarchy-operator interception was only wired into the `jsonb_path` branch,
  so native-column fields silently fell through to the standard operator dispatch and
  raised `KeyError`. Fixed by adding the same interception in the `sql_column` branch,
  generating `"field_name"::uuid IN (SELECT id FROM ...)` instead of
  `(data->>'field_name')::uuid IN (SELECT id FROM ...)`.

## [1.16.0] - 2026-04-27

### Added

- **`descendant_of_id` and `ancestor_of_id` ltree hierarchy operators** — filter by
  hierarchy using a UUID instead of an ltree path string. The operator lives on the
  UUID/ID field (e.g. `categoryId`), so callers never need to know the underlying
  ltree path:

  ```graphql
  items(where: { categoryId: { descendantOfId: $categoryId } })
  ```

  FraiseQL resolves the UUID to its ltree path via a nested subquery and generates:

  ```sql
  (data->>'category_id')::uuid IN (
    SELECT id FROM "myschema"."tb_category"
    WHERE path <@ (
      SELECT path FROM "myschema"."tb_category" WHERE id = 'uuid'::uuid
    )::ltree
  )
  ```

  The JSONB value is cast to `::uuid` (not `id::text`) so PostgreSQL can use the UUID
  index on the `id` column.

  **Convention**: column `{entity}_id` resolves to `{schema}.tb_{entity}`. Configure
  the schema via `FraiseQLConfig.default_entity_schema = "myschema"`.

  Both `descendantOfId` (GraphQL camelCase) and `descendant_of_id` (snake_case) are
  accepted as operator names. `UUIDFilter` exposes both fields for GraphQL schema
  introspection.

## [1.15.0] - 2026-04-19

### Fixed

- **`native_dimensions` always injected into GROUP BY** — previously, native
  dimensions were only added to `GROUP BY` when the client explicitly selected
  them as top-level GraphQL fields. Queries that accessed the same column
  through a nested path (e.g. `dimensions.dateInfo.date`) received no `GROUP BY`
  entry for the native column, making `ORDER BY` on it a PostgreSQL error
  ("column must appear in the GROUP BY clause"). Native dimensions are now
  pre-seeded into `GROUP BY` unconditionally, so `ORDER BY {"date": "asc"}` is
  always safe regardless of selection shape.

## [1.14.0] - 2026-04-16

### Added

- **Native SQL column grouping in auto-aggregation** (#337):
  `register_type_for_view()` now accepts a `native_dimensions` key in the
  `aggregation` metadata. Listed columns are grouped via `t."col"` instead of
  JSONB extraction (`data->>'col'`), enabling btree index usage and fixing
  `ORDER BY` errors when the ordered field is a real SQL column on the view.

  ```python
  register_type_for_view(
      "v_orders_by_period", OrderPeriodType,
      has_jsonb_data=True,
      aggregation={
          "native_dimensions": ["period_date", "category_id"],
          "dimensions": "dimensions",
          "measures": {"measures.total": "SUM", "measures.count": "SUM"},
      },
  )
  ```

  Generated SQL changes from:

  ```sql
  -- Before (slow, no index, error-prone)
  SELECT ... FROM v_orders_by_period
  GROUP BY "data"->>'period_date'
  ORDER BY "data" -> 'period_date'  -- ERROR: data not in GROUP BY
  ```

  to:

  ```sql
  -- After (index-friendly, correct)
  SELECT ... FROM v_orders_by_period AS t
  GROUP BY t."period_date"
  ORDER BY t."period_date"
  ```

  Mixed grouping (native + JSONB dimensions in the same query) is fully
  supported. Backward compatible: existing metadata without `native_dimensions`
  behaves identically to before.

## [1.13.1] - 2026-04-08

### Fixed

- **auth: `get_current_user_optional` silently swallows non-auth exceptions** (#325):
  Narrowed the bare `except Exception` to `except AuthenticationError` so that
  non-auth errors (`PermissionError`, `ConnectionError`, `RuntimeError`, etc.)
  propagate instead of being silently treated as "unauthenticated".

- **audit: `SecurityLogger` crashes on `PermissionError`** (#326):
  Wrapped `FileHandler` creation in a `try/except` so the logger falls back to
  stderr-only logging when the log file is not writable. Added
  `FRAISEQL_SECURITY_LOG_PATH` environment variable support for configuring the
  log path without code changes.

### Changed

- **Version is now derived from package metadata at runtime** via
  `importlib.metadata.version()` instead of a hardcoded string in `__init__.py`.
  Removed orphaned `__version__.py` and standalone version management scripts
  (`version_manager.py`, `check_version_consistency.py`, `check_versions.py`).
  The only version check retained is pyproject.toml ↔ fraiseql_rs/Cargo.toml
  consistency (required by maturin), run as part of `make release-check`.

## [1.13.0] - 2026-03-31

### Added

- **Auto-aggregation from type metadata** (#322): `register_type_for_view()` now
  accepts an `aggregation` parameter that declares which fields are measures
  (with aggregation function) and which are dimensions. When `db.find()` detects
  that the GraphQL field selection contains only dimensions and measures (no
  identity fields like `id`), it auto-generates `group_by` and `aggregations` —
  no manual AST walking in resolvers needed.

  ```python
  register_type_for_view(
      "v_statistics_day", DataPoint,
      has_jsonb_data=True,
      aggregation={
          "measures": {"measures.cost": "SUM", "measures.volume": "SUM"},
          "dimensions": "dimensions",
      },
  )

  # Resolver stays clean — auto-aggregates when appropriate
  @fraiseql.query
  async def datapoints(info, where=None) -> list[DataPoint]:
      return await db.find("v_statistics_day", where=where, info=info)
  ```

### Fixed

- **Multi-platform wheel builds**: Release workflow now builds wheels for Linux
  (x86_64), macOS (x86_64 + ARM64), and Windows (x86_64). Previously only a
  Linux wheel was published, causing `uv sync` failures on cross-platform
  resolution.

---

## [1.12.0] - 2026-03-31

### Added

- **Nested `json_build_object` for `group_by` dot-separated paths** (#318): When `group_by`
  uses dot-separated field paths (e.g. `dimensions.date_info.date`), the SQL now generates
  nested `json_build_object()` calls matching the GraphQL type structure. Previously, flat
  keys like `"dimensions.date_info.date"` were produced, which the Rust pipeline couldn't
  project.

### Fixed

- **`is_type_of` rejects plain dicts from resolvers** (#317): Resolvers returning plain
  dicts (e.g. from `db.run()`) are now accepted by `is_type_of` and correctly resolved.
  Previously, `graphql-core` rejected them with "Expected value of type 'MyType' but got:
  dict". Both `is_type_of` (type gating) and `resolve_field` (field value access) now
  handle dicts alongside typed instances.

- **`group_by` results stripped by Rust field projection** (#319): When `db.find()` is
  called with `group_by`/`aggregations`, the Rust pipeline's field projection is now
  skipped. The SQL's `json_build_object()` already returns exactly the requested fields,
  so additional projection was incorrectly stripping all data.

- **Regression test ordering failures**: Added missing `clear_registry` fixtures to
  multiple regression tests that were failing when run as part of the full suite due
  to stale type registrations from prior tests.

---

## [1.11.0] - 2026-03-31

### Added

- **GROUP BY and aggregations in `db.find()`** (#315): `db.find()` now accepts `group_by`
  and `aggregations` parameters, enabling SQL-level aggregation before returning results.
  This avoids returning hundreds of MB of individual rows for high-cardinality views when
  only aggregated measures are needed.

  ```python
  results = await db.find(
      "v_my_view",
      where={"date": {"gte": "2026-01-01", "lte": "2026-03-31"}},
      group_by=["date"],
      aggregations={"total_cost": "SUM(cost)", "total_volume": "SUM(volume)"},
      info=info,
  )
  ```

  Supports nested JSONB field paths (`date_info.date`), multiple aggregation functions
  (`SUM`, `AVG`, `COUNT`, `MIN`, `MAX`, `ARRAY_AGG`, `JSON_AGG`, etc.), and both JSONB
  and non-JSONB tables. Aggregation expressions are validated against an allowlist to
  prevent SQL injection.

### Fixed

- **Rust mutation executor missing session variables** (#309): Session variables are now
  set before the Rust executor path, fixing `NULL` values for `fraiseql.started_at` and
  RLS policy variables on mutations.

- **CI: Container Security Scan SBOM generation** (#314): Replaced broken `aquasec/trivy`
  Docker Hub image (removed upstream) with `aquasecurity/trivy-action` for SBOM generation,
  fixing the Container Security Scan and Security Gate CI checks.

---

## [1.10.1] - 2026-03-18

### Added

- **Configurable session variable forwarding** (#310): New `session_variables` config field
  on `FraiseQLConfig` maps request context keys to PostgreSQL session variables via `SET LOCAL`.
  Enables locale-aware views (`current_setting('app.locale', true)`) and any custom per-request
  PostgreSQL session state without code changes. Variable names are validated against SQL injection.

  ```python
  config = FraiseQLConfig(
      session_variables={"locale": "app.locale", "timezone": "app.timezone"},
  )
  ```

### Fixed

- **Rust mutation executor missing session variables** (#309): The Rust-accelerated mutation
  path (`execute_mutation_rust`) bypassed `_set_session_variables()`, causing `fraiseql.started_at`,
  `app.tenant_id`, `app.user_id`, `app.contact_id`, and `app.is_super_admin` to all be `NULL`
  for mutations. This broke `duration_ms` computation in `core.tb_entity_change_log` and silently
  disabled Row-Level Security policies on the mutation path. Session variables are now injected
  on the connection before the Rust executor is invoked.

- **TurboRouter missing session variables**: TurboRouter queries reimplemented session variable
  injection inline and only set `tenant_id` and `contact_id`, missing `user_id`, `roles`,
  `is_super_admin`, `fraiseql.started_at`, and all custom variables. Now delegates to the
  canonical `_set_session_variables()` method.

- **`set_config()` for `fraiseql.started_at`**: Use `set_config()` via `SELECT` instead of
  `SET LOCAL` to avoid psycopg extended query protocol issues with function calls in SET
  statements.

### Changed

- **Repository cleanup**: Removed v2 artifacts from v1 repository.

---

## [1.10.0] - 2026-03-14

### Added

- **CLI: `validate-mutation-return` command** (#280): New CLI command and library function
  to validate mutation return values against GraphQL schema types at build time or in CI.
  Supports recursive type validation (objects, lists, unions, enums, scalars), NonNull vs
  nullable field handling, union type matching with `__typename` disambiguation, and three
  output formats: human-readable, JSON, and JUnit XML. Available as both
  `fraiseql validate-mutation-return` CLI command and `from fraiseql import validate_mutation_return`
  library function.

- **DB: `fraiseql.started_at` session variable** (#304): `_set_session_variables` now injects
  `SET LOCAL fraiseql.started_at = clock_timestamp()::text` before every query and mutation,
  enabling PostgreSQL functions to compute their own execution duration via
  `clock_timestamp() - current_setting('fraiseql.started_at', true)::timestamptz`. Uses
  `clock_timestamp()` (not `NOW()`) for accurate wall-clock timing including lock waits.

### Security

- **CVE-2025-14104 resolved** (#295, #299): Removed util-linux heap buffer overread exception
  from `.trivyignore` — now fixed in upstream `python:3.13-slim` base image. Updated review
  dates for remaining monitored CVEs (gnutls28, ncurses, shadow).

---

## [1.9.20] - 2026-02-25

### Fixed

- **Scalar fields on `@fraiseql.error` types silently resolve to `None`** (#294): When a
  SQL mutation function returned scalar values (e.g. `datetime`, `str`, `int`, `UUID`) in
  its metadata JSONB (via `jsonb_build_object(...)`), those values were never populated into
  the corresponding fields of an `@fraiseql.error`-decorated class — they always resolved to
  `None`. The root cause was that `build_error_response_with_code` in the Rust pipeline only
  extracted fields from `result.entity` (dict-backed entities like `conflict_machine:
  Machine`), and completely ignored scalar values stored directly in `result.metadata`. Fixed
  by iterating `result.metadata` after `result.entity` and promoting any non-reserved key
  (`errors`, `entity_type`, `entity`, `_cascade`) to the root error response object, applying
  camelCase conversion and field selection filtering consistently with the rest of the pipeline.

---

## [1.9.19] - 2026-02-21

### Fixed

- **Multi-field query with JSONB types returns empty nested fields** (#288): When a GraphQL
  query had 2+ root-level fields and at least one resolver used a JSONB type
  (`@fraiseql.type(jsonb_column=...)`), nested JSONB fields in the response were empty —
  only `__typename` was returned for each nested object. The root cause was that
  `execute_multi_field_query` only passed top-level field names (e.g. `"nested"`) to
  `build_multi_field_response`, causing Rust's `transform_with_selections` to filter out
  all sub-fields (e.g. `"nested.value"`) whose full paths were absent from `selected_paths`.
  Fixed by replacing the shallow field list with a complete recursive traversal via the new
  `_build_field_selections_recursive()` helper, which includes every dot-separated path at
  every nesting depth. Sub-field `@skip`/`@include` directives and aliases at any depth are
  also preserved correctly. Single-field queries are unaffected.

---

## [2.0.0-alpha.2] - 2026-02-06

### Added

**Audit Backend Test Coverage (Complete):**

- PostgreSQL audit backend comprehensive tests (27 tests, 804 lines):
  - Backend creation and schema validation
  - Event logging with optional fields
  - Query operations with filters and pagination
  - JSONB metadata and state snapshots
  - Multi-tenancy and tenant isolation
  - Bulk logging and concurrent operations
  - Schema idempotency verification
  - Complex multi-filter queries
  - Error handling and validation scenarios

- Syslog audit backend comprehensive tests (27 tests, 574 lines):
  - RFC 3164 format validation
  - Facility and severity mapping
  - Event logging and complex event handling
  - Query behavior (always returns empty)
  - Network operations and timeout handling
  - Concurrent logging with 20+ concurrent tasks
  - Builder pattern and trait compliance
  - E2E integration flows for all statuses

**Arrow Flight Enhancements:**

- Event storage capabilities
- Export functionality
- Subscription support
- Observer events integration tests
- Schema refresh tests with streaming updates

**Observer Infrastructure:**

- Storage layer implementation
- Event-driven observer patterns
- Automatic observer triggering

### Fixed

- Removed placeholder test stubs for deferred audit backends
- Enhanced test documentation with clear categories
- Improved error handling in audit operations

### Test Coverage

- Total comprehensive tests: 54+ (27 PostgreSQL, 27 Syslog)
- All tests passing with zero warnings
- Database tests marked for CI integration with proper isolation
- Syslog tests run without external dependencies

### Already Included (Clarification)

Note: The following features are already available in this release and not deferred:

- OpenTelemetry integration for distributed tracing
- Advanced analytics with Arrow views (va_*, tv_*, ta_*)
- Performance metrics collection and monitoring
- GraphQL subscriptions with streaming support
- Real-time analytics pipelines

---

## [2.0.0-alpha.1] - 2026-02-05

### Added

**Documentation (Phase 16-18 Complete):**

- Complete SDK reference documentation for all 16 languages
  - Python, TypeScript, Go, Java, Kotlin, Scala, Clojure, Groovy
  - Rust, C#, PHP, Ruby, Swift, Dart, Elixir, Node.js
- 4 full-stack example applications
- 6 production architecture patterns
- Complete production deployment guides
- Performance optimization guide
- Comprehensive troubleshooting guide

**Documentation Infrastructure:**

- ReadTheDocs configuration and integration
- Material Design theme with dark mode support
- Search functionality with 251 indexed pages
- Zero broken links (validated)
- 100% code example coverage

**Core Features:**

- GraphQL compilation and execution engine
- Multi-database support (PostgreSQL, MySQL, SQLite, SQL Server)
- Apache Arrow Flight data plane
- Apollo Federation v2 with SAGA transactions
- Query result caching with automatic invalidation

**Enterprise Security:**

- Audit logging with multiple backends
- Rate limiting and field-level authorization
- Field-level encryption-at-rest
- Credential rotation automation
- HashiCorp Vault integration

### Documentation Statistics

- **Total Files:** 251 markdown documents
- **Total Lines:** 70,000+ lines
- **Broken Links:** 0
- **Code Examples:** 100% coverage
- **Languages:** 16 SDK references

---

## Contributing

See [ARCHITECTURE_PRINCIPLES.md](.claude/ARCHITECTURE_PRINCIPLES.md) for contribution guidelines.

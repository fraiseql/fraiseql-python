# Changelog

All notable changes to FraiseQL are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

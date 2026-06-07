# Changelog

All notable changes to FraiseQL are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.23.7] - 2026-06-07

### Security

- **Upgraded dependencies to resolve known advisories** (all open Dependabot alerts + a
  pip-audit pass):
  - `pyjwt` 2.12.1 -> 2.13.0 — fixes PYSEC-2026-175/177/178/179 (the JWT auth library).
  - `starlette` 0.52.1 -> 1.2.1 (pulls `fastapi` 0.129.0 -> 0.136.3) — fixes GHSA-86qp-5c8j-p5mr.
  - `aiohttp` 3.13.5 -> 3.14.0 — fixes GHSA-hg6j-4rv6-33pg, GHSA-jg22-mg44-37j8 (dev).
  - `idna` 3.11 -> 3.18 — fixes GHSA-65pc-fj4g-8rjx.
  - `langchain-classic` 1.0.1 -> 1.0.7 — fixes GHSA-3644-q5cj-c5c7 (dev tooling).
  - `pymdown-extensions` 10.21 -> 10.21.3 (and `docs/requirements.txt` 10.5 -> 10.21.3) —
    fixes GHSA-62q4-447f-wv8h, GHSA-r6h4-mm7h-8pmq (docs).
  - All 3,462 unit + security/FastAPI integration tests pass on the upgraded stack
    (including the FastAPI 0.136 / Starlette 1.2 major bump).

- **Container compliance gate (government-grade) now passes.** The 2 CRITICAL and HIGH
  findings flagged by Trivy are all unpatchable base-image OS packages (`perl-base`,
  `ncurses`; `FixedVersion: none`) that are never invoked at runtime by the API server. They
  are documented as accepted, monitored risks in `.trivyignore` (CATEGORY 12) per the existing
  exception process, to be removed once Debian ships fixes.

### Notes

- One pip-audit finding remains with no upstream fix: `py` 1.11.0 (PYSEC-2022-42969), an EOL
  transitive of the dev-group `pytest-forked` (used for process-isolation tests). It is not
  installed by the CI dependency-audit extras and is not invoked at runtime.

## [1.23.6] - 2026-06-07

### Fixed

- **Field-level authorization is now enforced on the resolver-bypass paths (issue #366)** —
  closing a silent fail-open
  - `@fraise_type(authorize_fields=[...])` installs a per-field gate on
    `GraphQLField.resolve`. The Rust multi-field merge, JSON passthrough, TurboRouter, and
    `POST /graphql/rust` paths never invoke that resolver, so a gated field could be served
    **without consulting the authorizer**. Each bypass path now re-applies the gate against the
    query's selection set before serving data — fail-closed, decision-cache-aware, using the
    same `"TypeName.fieldName"` identity and the same evaluation core as the resolver path.
  - Because a bypass path has no resolved parent object, an `authorize_fields` policy must be a
    function of `context`, the field identity, and arguments only (the automatic gate already
    calls authorizers this way). A hand-rolled `@authorize_field` that inspects `root` remains
    enforced on the resolver path only. Detection is per-document: a gated field anywhere in the
    request is enforced (conservative over-enforcement for multi-operation documents, never a
    silent allow).
  - New API: `fraiseql.security.field_auth.enforce_selected_field_authorization` and
    `iter_gated_selections`. `TurboRouter`/`EnhancedTurboRouter` gained an optional `schema`
    argument (wired automatically inside `create_graphql_router`) enabling the field gate on
    that path.

- **TurboRouter authorization gate no longer mislabels persisted mutations as queries
  (issue #368)** — a security regression in the #362 turbo gate
  - `TurboRouter.execute` hardcoded `operation_type="query"`, so a **mutation** served via the
    TurboRouter was presented to the `Authorizer` as a *query*, silently defeating write-guards
    that gate on `operation_type`. The operation type and name are now derived from the document
    (via `_derive_operation_info`), exactly as the APQ and `/graphql/rust` gates already do.

## [1.23.5] - 2026-06-06

### Fixed

- **`@field` / `@authorize_field` compose in either decorator order** — a pre-existing
  field-resolver defect, surfaced during the #366 work
  - A field method gated with `@authorize_field` now runs its check and resolver with the
    correct arguments regardless of decorator order (`@authorize_field` outer / `@field`
    inner, or `@field` outer / `@authorize_field` inner) and for any method shape (`self`,
    `self, info`, sync or `async`). Previously the `@field`-outer order silently failed for
    `self`-only methods (the order the docs showed).
  - Auth wrappers no longer mis-report their signature: `@authorize_field` drops the
    `functools.wraps`-set `__wrapped__`, so an outer `@field` (and `inspect.signature`) reads
    the wrapper's real `(root, info, *args, **kwargs)` interface. **Note:** external tooling
    that followed `__wrapped__` on an auth wrapper now sees this real signature instead of the
    inner method's.
  - A sync field resolver gated by an async authorizer (e.g. `field_authorizer_adapter`) no
    longer emits a `RuntimeWarning` or risks an event-loop deadlock: the wrapper is async
    end-to-end whenever the resolver or the check is async, so graphql-core awaits it directly.
  - Internals: a single `invoke_resolver` convention
    (`fraiseql.core.resolver_invocation`) is now the source of truth for how `@field` and
    `@authorize_field` call what they wrap. Fail-closed behavior is unchanged on every deny.

## [1.23.4] - 2026-06-06

### Added

- **Automatic field-level authorization** (#366) — ergonomics follow-up to #362
  - `@fraise_type(authorize_fields=[...])` gates the listed fields with the configured
    operation `Authorizer` automatically, checked with `operation_type="field"` and
    `operation_name="TypeName.fieldName"` before each field resolver runs — no per-field
    `@authorize_field` needed. Narrow opt-in by design (no gate-everything switch)
  - Fail-closed: `field_authorizer_adapter` now normalizes a raising authorizer to a
    `FIELD_AUTHORIZATION_ERROR` deny (parity with the operation path). An explicit
    `@authorize_field` AND-combines with the automatic gate
  - With no authorizer configured the gate is a no-op (byte-for-byte unchanged). The gate
    consults the optional decision cache (#367), which collapses the per-object call volume
    on nested lists; the per-object cost is documented in `docs/security/authorization.md`

## [1.23.3] - 2026-06-06

### Added

- **Optional authorization decision caching** (#367) — performance follow-up to #362
  - `AuthorizationCacheConfig` + `DecisionCache` (exported from `fraiseql` and
    `fraiseql.security`): opt-in TTL+LRU memoization of authorization decisions, wired via
    `create_fraiseql_app(authorization_cache=...)` and installed on
    `SchemaRegistry.decision_cache`; survives schema hot-reload
  - Consulted on every gated path — the resolver wrap, subscriptions, and the three
    resolver-bypass gates (TurboRouter, `/graphql/rust`, APQ) — keyed on
    `(principal_key(context), operation_type, operation_name, stable_hash(arguments))`
  - **Off by default** (always-evaluate is the safe default). Fail-closed is never cached
    around: a raising authorizer is never cached; a `None` principal is never cached;
    non-JSON-serializable arguments fall through to evaluate
  - **Correctness contract:** enable only if the authorizer is a pure function of
    principal + operation + arguments — a non-pure authorizer is served a wrong decision on
    a hit (documented in `docs/security/authorization.md`). TTL-only invalidation (no active
    revoke hook in this version)

## [1.23.2] - 2026-06-06

### Changed

- **`POST /graphql/rust` is now opt-in** (#365) — defense-in-depth follow-up to #362
  - New `FraiseQLConfig.enable_rust_endpoint` flag (default `False`,
    `FRAISEQL_ENABLE_RUST_ENDPOINT`). The Rust passthrough bypasses Python resolvers
    entirely, so the route is mounted only when explicitly enabled; when disabled it is
    not registered (a request 404s). When mounted it is still authorization-gated (#362).
  - ⚠️ **Behavior change:** apps that were calling `/graphql/rust` must now set
    `enable_rust_endpoint=True`, or the endpoint returns 404.

## [1.23.1] - 2026-06-06

### Added

- **Subscription authorization** (#364) — follow-up to the operation PEP (#362)
  - The configured `Authorizer` now gates subscriptions, enforced **once at subscribe
    time** with `operation_type="subscription"`, before the event stream is created. A
    deny (or a raising authorizer) raises a `GraphQLError` during the awaited `subscribe`,
    so the inner generator is never built and the database is never queried. Covers both
    the schema path and the websocket transport (which routes through graphql-core's
    `subscribe`)
  - `@subscription(authorizer=...)` per-operation override, mirroring
    `@query` / `@mutation`; the global default still applies otherwise
  - A returned `decision.filters` is **logged, not silently dropped** on subscriptions
    (no row-scoping semantics on a stream), mirroring the mutation path
  - Per-event re-checking of live streams is explicitly a future opt-in, not this change
  - With no authorizer configured, subscriptions stream byte-for-byte as before

## [1.23.0] - 2026-06-06

### Added

- **First-class operation authorization extension point** (#362)
  - `Authorizer` protocol + `AuthorizationDecision` value type (`allow`/`deny`,
    optional `code`/`message`/`filters`), exported from `fraiseql` and
    `fraiseql.security`; a single decision contract aligned with v2 (#422)
  - `create_fraiseql_app(authorizer=...)` and `build_fraiseql_schema(authorizer=...)`
    install a global default authorizer on `SchemaRegistry.default_authorizer`;
    `@query(authorizer=...)` / `@mutation(authorizer=...)` add per-operation overrides
  - Enforcement around every root query and mutation (sync + async resolvers) with
    **fail-closed** semantics in one shared helper: an authorizer that raises denies,
    a deny becomes a `GraphQLError` with `extensions.code`, and the raw exception is
    never surfaced to the client
  - **Resolver-bypass paths gated**: TurboRouter / persisted queries,
    `POST /graphql/rust`, and APQ cached passthrough all enforce the same authorizer
    before reaching the database / Rust
  - **Row-scoping filter injection**: a query authorizer may return `filters` that are
    AND-merged into the repository's validated, parameterized `mandatory_filters` via
    the repository context (keyed per root field; overlapping columns rejected). On the
    bypass paths a returned filter is logged (rely on session variables + RLS); APQ
    skips the cache when filters are present
  - Authorizer survives schema hot-reload; the legacy `registry._mutations` rewrite
    keeps working during migration
  - Field-level `authorize_field` accepts `AuthorizationDecision | bool` on one contract;
    `field_authorizer_adapter` lets one policy object serve fields and operations
  - New guide `docs/security/authorization.md` and `examples/authorization/`

## [1.22.0] - 2026-05-14

### Added

- **pg_stat_statements integration** (#357)
  - `v_query_stats` SQL view and `get_query_stats()` function with cache hit
    ratio computation, utility statement filtering, and graceful degradation
  - `QueryStatsCollector` Python API with `get_stats()`, `is_available()`,
    `reset_stats()` and global singleton pattern (`init_query_stats()`)
  - `check_query_stats()` optional health check for monitoring endpoints
  - `fraiseql query-stats` CLI command with `--top-n`, `--order-by`, `--reset`
    flags and color-coded cache hit ratios
  - Prometheus integration via `postgres_exporter_queries.yml` custom queries
  - Test container configured with `shared_preload_libraries=pg_stat_statements`

## [1.21.0] - 2026-05-13

### Added

- **Time grain truncation: `semester` and `half_month`** (#1516, #1517)
  - Extend partial-period awareness to support 6-month and ~15-day granularities
  - Custom SQL expressions (`MAKE_DATE` for semester, `CASE` for half_month)
    for non-native PostgreSQL intervals
  - Unblocks `printoptim_backend` v_statistics_semester and v_statistics_half_month views

## [1.20.1] - 2026-05-12

### Security

- **Bump urllib3** to >=2.7.0 — fix headers forwarded across origins and
  decompression-bomb bypass (Dependabot alerts #77, #78)
- **Bump langchain-core** to >=1.3.3 — fix unsafe deserialization via overly
  broad `load()` allowlists (alert #76)
- **Add banks >=2.4.2 constraint** — fix critical RCE via Jinja2 SSTI in
  llama-index transitive dependency (alert #75)
- **Bump cryptography** to >=47.0.0
- **Update .trivyignore** with documented risk assessments for all 30 open
  Trivy container CVEs (GnuTLS, libssh2, krb5, curl — none used by FraiseQL)

### Changed

- **Bump GitHub Actions** — docker/login-action v4, docker/metadata-action v6,
  docker/build-push-action v7, actions/upload-artifact v7
- **Bump dev dependencies** — llama-index >=0.14.21, ruff >=0.15.12,
  opentelemetry-sdk >=1.41.1, aioboto3 >=15.5.0, mkdocs-material >=9.7.6
- **Improve Dependabot config** — group patch+minor updates, group Actions
  updates, reduce PR limits, ignore boto3 major bumps (aiobotocore coupling)

### Housekeeping

- Closed 9 stale automated CVE monitoring issues
- Closed 16 superseded Dependabot PRs
- Merged pre-commit hook updates (pre-commit-hooks v6.0.0, markdownlint v0.48.0)

## [1.20.0] - 2026-05-11

### Security

- **Fix tenant isolation in aggregated queries** (#344) — filters passed as bare
  keyword arguments to `db.find()` (e.g. `tenant_id=...`) were silently dropped
  when auto-aggregation triggered the UNION ALL code path, causing cross-tenant
  data exposure. Introduced `mandatory_filters` — an explicit, identifier-validated
  dict parameter applied in **all** query modes (normal, aggregated, union-all,
  find_one, count, exists, and all utility methods). Credit: @evoludigit.

### Breaking Changes

- `db.find()`, `db.find_one()`, `db.count()`, `db.exists()`, and all utility
  methods no longer accept arbitrary keyword arguments as equality filters.
  Passing unrecognised kwargs now raises `TypeError`. Migrate from:

  ```python
  db.find("v_foo", tenant_id=tid, ...)
  ```

  To:

  ```python
  db.find("v_foo", mandatory_filters={"tenant_id": tid}, ...)
  ```

## [1.19.1] - 2026-05-03

### Fixed

- **`_build_coarse_branch` missing `GROUP BY` clause** (#342) — when the
  UNION ALL partial-period path was triggered, the coarse-grain branch omitted
  `GROUP BY` for native dimension columns, causing PostgreSQL to raise:

  > column "t.date" must appear in the GROUP BY clause or be used in an aggregate function

  The fix tracks `group_by_exprs` separately in `_build_coarse_branch` and
  appends `GROUP BY` exactly as `_build_fine_grain_branch` does. Regression
  tests added in `tests/regression/issue_342/`.

- **Testcontainer Docker skip** — `postgres_container` and Vault container
  fixtures now catch Docker networking failures (veth bridge creation error)
  and call `pytest.skip()` instead of raising an unhandled exception, so the
  test suite reports skips rather than errors when Docker networking is
  unavailable.

## [1.19.0] - 2026-05-03

### Added

- **Partial-period awareness for pre-aggregated time-series views** (#341) — when a
  `date >=` filter falls in the middle of a coarse-grain period (e.g. a monthly aggregate
  view queried from Jan 15), FraiseQL now automatically generates a three-branch
  `UNION ALL` query that returns correct data instead of silently dropping the partial
  leading period:

  - **Branch 1** (partial first period): fine-grain rows from the lower bound to the end
    of its period — only emitted when the lower bound is not period-aligned.
  - **Branch 2** (complete periods): coarse-grain rows for all full periods between the
    partial period and the current one — fast, uses pre-aggregated data.
  - **Branch 3** (current in-progress period): always fine-grain rows for the current
    period up to today, so live data is never stale.

  Opt in by adding three new optional keys to the `aggregation` dict in
  `register_type_for_view`:

  ```python
  register_type_for_view(
      "v_events_month",
      EventDataPoint,
      has_jsonb_data=True,
      aggregation={
          "dimensions": "data",
          "measures": {"data.volume": "SUM"},
          "native_dimensions": ["date"],
          "fine_grain_view":   "v_events_day",   # NEW
          "time_grain_column": "date",            # NEW
          "time_grain_trunc":  "month",           # NEW
      },
  )
  ```

  Supported granularities: `"day"`, `"week"`, `"month"`, `"quarter"`, `"year"`.
  An invalid `time_grain_trunc` raises `ValueError` at registration time (fast fail).
  Omitting the three new keys leaves existing behaviour completely unchanged.

  The UNION path is only triggered when a `date >=` or `date >` filter is present;
  queries without a date lower bound continue to use the single-query path.

## [1.18.0] - 2026-05-03

### Added

- **`native_measures` and `native_dimension_mapping` in aggregation metadata** — two
  new optional keys in the `aggregation` dict passed to `register_type_for_view`, enabling
  fully native SQL aggregation on JSONB views that also expose flat columns:

  - **`native_measures`**: maps JSONB measure paths to flat column names, so
    `SUM` uses `SUM(t."volume")` instead of `SUM((data->'measures'->>'volume')::numeric)`.
    Eliminates JSONB extraction and the `::numeric` cast for aggregated metrics.

  - **`native_dimension_mapping`**: maps deep JSONB dimension paths to flat column names,
    so `GROUP BY` on a path like `dimensions.category.id` resolves to `GROUP BY t."category_id"`
    via a native btree index instead of JSONB extraction.

  Example:

  ```python
  register_type_for_view(
      "v_statistics_day",
      StatisticsDay,
      has_jsonb_data=True,
      aggregation={
          "native_dimensions": ["date"],
          "dimensions": "dimensions",
          "measures": {
              "measures.volume": "SUM",
              "measures.cost": "SUM",
          },
          "native_measures": {
              "measures.volume": "volume",
              "measures.cost": "cost",
          },
          "native_dimension_mapping": {
              "dimensions.category.id": "category_id",
          },
      },
  )
  ```

  Views without these keys are unaffected — fully backwards-compatible (#340).

## [1.16.2] - 2026-04-28

### Fixed

- **`descendantOfId` / `ancestorOfId` not available on `IDFilter`** — fields typed
  as GraphQL `ID` (rather than `UUID`) use `IDFilter`, which was missing the two
  hierarchy operators. Added `descendantOfId` and `ancestorOfId` to `IDFilter` so
  they work regardless of whether the field is declared as `ID` or `UUID`.

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

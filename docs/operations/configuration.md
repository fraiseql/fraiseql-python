---

title: Configuration Reference
description: Complete configuration reference for a FraiseQL application. Settings are managed through FraiseQLConfig (pydantic), FRAISEQL_-prefixed environment variables, and create_fraiseql_app(...) keyword arguments.
keywords: ["deployment", "scaling", "performance", "monitoring", "troubleshooting"]
tags: ["documentation", "reference"]
---

# Configuration Reference

## Overview

FraiseQL is a Python runtime GraphQL framework for PostgreSQL. A FraiseQL app is
configured at startup through a single pydantic settings object, `FraiseQLConfig`.
You can populate it from environment variables (prefixed `FRAISEQL_`), a `.env`
file, or directly in Python. There is no separate config file format, no CLI, and
no build step: the GraphQL schema is assembled in memory when the FastAPI app
starts.

This document is the complete reference for `FraiseQLConfig` (the main application
config) and `MetricsConfig` (the optional Prometheus metrics integration).

---

## Quick Start

### Minimal Configuration

The only required setting is the PostgreSQL connection URL. Set it via an
environment variable:

```bash
export FRAISEQL_DATABASE_URL=postgresql://user:pass@localhost/mydb
```

Then create the app:

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://user:pass@localhost/mydb",
    types=[User],
    queries=[users, user],
    mutations=[create_user],
)
```

Run it with uvicorn:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

That's it. Every other setting has a conservative default.

---

## Configuration Methods

`FraiseQLConfig` is a `pydantic_settings.BaseSettings` subclass, so values resolve
in this order of precedence:

1. **Explicit Python values** (highest priority) — passed to `FraiseQLConfig(...)`
   or directly as `create_fraiseql_app(...)` keyword arguments.
2. **Environment variables** — any field can be set with a `FRAISEQL_`-prefixed,
   case-insensitive env var (e.g. `FRAISEQL_DATABASE_URL`,
   `FRAISEQL_ENVIRONMENT`).
3. **`.env` file** — a `.env` file in the working directory is loaded
   automatically.
4. **Field defaults** (lowest priority).

### Building a config object

```python
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

# Production configuration
config = FraiseQLConfig(
    database_url="postgresql://user:pass@localhost/mydb",
    environment="production",
    auth_enabled=True,
    auth_provider="auth0",
    auth0_domain="myapp.auth0.com",
    auth0_api_identifier="https://api.myapp.com",
)

app = create_fraiseql_app(types=[User, Post], config=config)
```

### Letting environment variables drive everything

```bash
export FRAISEQL_DATABASE_URL=postgresql://user:pass@localhost/mydb
export FRAISEQL_ENVIRONMENT=production
export FRAISEQL_AUTH_ENABLED=true
export FRAISEQL_AUTH_PROVIDER=auth0
export FRAISEQL_AUTH0_DOMAIN=myapp.auth0.com
export FRAISEQL_AUTH0_API_IDENTIFIER=https://api.myapp.com
```

```python
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

# Reads all FRAISEQL_-prefixed env vars / .env automatically
config = FraiseQLConfig()
app = create_fraiseql_app(types=[User, Post], config=config)
```

### `create_fraiseql_app(...)` keyword arguments

Some settings can also be passed directly to `create_fraiseql_app`, which builds a
config for you. Verified keyword arguments:

```python
app = create_fraiseql_app(
    database_url="postgresql://user:pass@localhost/mydb",
    types=[User, Post],
    queries=[users, user],
    mutations=[create_user],
    auth=auth_provider,                # an AuthProvider instance
    context_getter=get_context,        # custom GraphQL context builder
    config=config,                     # a FraiseQLConfig instance
    title="My API",
    version="1.0.0",
    description="My GraphQL API",
    production=False,                  # False enables the GraphQL playground
    connection_pool_size=20,
    connection_max_overflow=10,
    connection_timeout=30,
    connection_recycle=3600,
)
```

There is **no `middleware=` keyword argument**. Add middleware with
`app.add_middleware(...)` on the returned app, or pass your own FastAPI app via
`create_fraiseql_app(app=...)`.

---

## Database Configuration

### `database_url`

**Type**: `str` (PostgreSQL DSN)
**Required**: yes
**Environment**: `FRAISEQL_DATABASE_URL`

PostgreSQL connection URL. Must start with `postgresql://` or `postgres://`.
Unix-domain socket URLs are also supported
(`postgresql://user@/var/run/postgresql:5432/mydb`).

```bash
export FRAISEQL_DATABASE_URL=postgresql://app:pass@localhost:5432/myapp
```

```python
config = FraiseQLConfig(database_url="postgresql://app:pass@localhost:5432/myapp")
```

### `database_pool_size`

**Type**: `int`
**Default**: `20`
**Environment**: `FRAISEQL_DATABASE_POOL_SIZE`

Number of persistent connections kept open in the pool.

| Traffic | Pool Size | Reasoning |
|---------|-----------|-----------|
| Low (< 100 rps) | 5–10 | Minimal connections needed |
| Medium (100–1000 rps) | 20 | Default works well |
| High (> 1000 rps) | 40+ | More concurrent connections |

### `database_max_overflow`

**Type**: `int`
**Default**: `10`
**Environment**: `FRAISEQL_DATABASE_MAX_OVERFLOW`

Extra connections the pool may open beyond `database_pool_size` under load.

### `database_pool_timeout`

**Type**: `int` (seconds)
**Default**: `30`
**Environment**: `FRAISEQL_DATABASE_POOL_TIMEOUT`

How long a request waits for a free connection before raising.

### `database_pool_recycle`

**Type**: `int` (seconds)
**Default**: `3600`
**Environment**: `FRAISEQL_DATABASE_POOL_RECYCLE`

Recycle a connection after this many seconds, even if idle. Prevents stale
connections behind proxies and load balancers.

### `database_echo`

**Type**: `bool`
**Default**: `false`
**Environment**: `FRAISEQL_DATABASE_ECHO`

Log generated SQL. Useful in development; keep off in production.

```python
config = FraiseQLConfig(
    database_url="postgresql://app:pass@localhost:5432/myapp",
    database_pool_size=20,
    database_max_overflow=10,
    database_pool_timeout=30,
    database_pool_recycle=3600,
)
```

---

## Application Settings

### `environment`

**Type**: `"development" | "production" | "testing"`
**Default**: `"development"`
**Environment**: `FRAISEQL_ENVIRONMENT`

Setting `environment="production"` tightens defaults automatically: introspection
is disabled (unless explicitly set) and the GraphQL playground is turned off.

### `app_name`

**Type**: `str`
**Default**: `"FraiseQL API"`
**Environment**: `FRAISEQL_APP_NAME`

### `app_version`

**Type**: `str`
**Default**: `"1.0.0"`
**Environment**: `FRAISEQL_APP_VERSION`

```python
config = FraiseQLConfig(
    database_url="postgresql://app:pass@localhost/myapp",
    environment="production",
    app_name="My GraphQL API",
    app_version="2.3.1",
)
```

---

## GraphQL Settings

### `introspection_policy`

**Type**: `IntrospectionPolicy` (`"public" | "disabled" | "authenticated"`)
**Default**: `"public"` (forced to `"disabled"` in production unless set)
**Environment**: `FRAISEQL_INTROSPECTION_POLICY`

Controls who may run GraphQL introspection queries.

```python
from fraiseql.fastapi import FraiseQLConfig
from fraiseql.fastapi.config import IntrospectionPolicy

config = FraiseQLConfig(
    database_url="postgresql://app:pass@localhost/myapp",
    introspection_policy=IntrospectionPolicy.AUTHENTICATED,
)
```

### `enable_playground`

**Type**: `bool`
**Default**: `true` (forced to `false` in production unless explicitly set)
**Environment**: `FRAISEQL_ENABLE_PLAYGROUND`

Mount the in-browser GraphQL IDE. The `production=False` flag on
`create_fraiseql_app(...)` is the convenient way to enable it during development.

### `playground_tool`

**Type**: `"graphiql" | "apollo-sandbox"`
**Default**: `"graphiql"`
**Environment**: `FRAISEQL_PLAYGROUND_TOOL`

Which GraphQL IDE to serve.

### `max_query_depth`

**Type**: `int | None`
**Default**: `None` (no depth limit)
**Environment**: `FRAISEQL_MAX_QUERY_DEPTH`

Maximum nesting depth allowed in a query.

### `auto_camel_case`

**Type**: `bool`
**Default**: `true`
**Environment**: `FRAISEQL_AUTO_CAMEL_CASE`

Auto-convert `snake_case` Python field names to `camelCase` in the GraphQL schema.

### `query_timeout`

**Type**: `int` (seconds)
**Default**: `30`
**Environment**: `FRAISEQL_QUERY_TIMEOUT`

```python
config = FraiseQLConfig(
    database_url="postgresql://app:pass@localhost/myapp",
    enable_playground=False,
    max_query_depth=12,
    query_timeout=30,
)
```

---

## Performance Settings

### `cache_ttl`

**Type**: `int` (seconds)
**Default**: `300`
**Environment**: `FRAISEQL_CACHE_TTL`

Default time-to-live for cached query results.

### `execution_timeout_ms`

**Type**: `int` (milliseconds)
**Default**: `30000`
**Environment**: `FRAISEQL_EXECUTION_TIMEOUT_MS`

Maximum time a query may execute before being cancelled.

### `include_execution_metadata`

**Type**: `bool`
**Default**: `false`
**Environment**: `FRAISEQL_INCLUDE_EXECUTION_METADATA`

Include timing/diagnostic metadata in GraphQL responses. Useful during
development and profiling.

### `jsonb_field_limit_threshold`

**Type**: `int`
**Default**: `20`
**Environment**: `FRAISEQL_JSONB_FIELD_LIMIT_THRESHOLD`

When a query selects more than this many fields, FraiseQL switches to returning
the full `data` JSONB column instead of projecting individual paths.

### `turbo_router_cache_size`

**Type**: `int`
**Default**: `1000`
**Environment**: `FRAISEQL_TURBO_ROUTER_CACHE_SIZE`

Maximum number of prepared queries to cache for the fast-path router.

```python
config = FraiseQLConfig(
    database_url="postgresql://app:pass@localhost/myapp",
    cache_ttl=300,
    execution_timeout_ms=30000,
    include_execution_metadata=False,
    jsonb_field_limit_threshold=20,
)
```

---

## Security Settings

### Query Complexity

| Field | Type | Default | Environment |
|-------|------|---------|-------------|
| `complexity_enabled` | bool | `true` | `FRAISEQL_COMPLEXITY_ENABLED` |
| `complexity_max_score` | int | `1000` | `FRAISEQL_COMPLEXITY_MAX_SCORE` |
| `complexity_max_depth` | int | `10` | `FRAISEQL_COMPLEXITY_MAX_DEPTH` |
| `complexity_default_list_size` | int | `10` | `FRAISEQL_COMPLEXITY_DEFAULT_LIST_SIZE` |
| `complexity_include_in_response` | bool | `false` | `FRAISEQL_COMPLEXITY_INCLUDE_IN_RESPONSE` |

```python
config = FraiseQLConfig(
    database_url="postgresql://app:pass@localhost/myapp",
    complexity_enabled=True,
    complexity_max_score=1000,
    complexity_max_depth=10,
)
```

### Rate Limiting

| Field | Type | Default | Environment |
|-------|------|---------|-------------|
| `rate_limit_enabled` | bool | `true` | `FRAISEQL_RATE_LIMIT_ENABLED` |
| `rate_limit_requests_per_minute` | int | `60` | `FRAISEQL_RATE_LIMIT_REQUESTS_PER_MINUTE` |
| `rate_limit_requests_per_hour` | int | `1000` | `FRAISEQL_RATE_LIMIT_REQUESTS_PER_HOUR` |
| `rate_limit_burst_size` | int | `10` | `FRAISEQL_RATE_LIMIT_BURST_SIZE` |
| `rate_limit_window_type` | str | `"sliding"` | `FRAISEQL_RATE_LIMIT_WINDOW_TYPE` |

```python
config = FraiseQLConfig(
    database_url="postgresql://app:pass@localhost/myapp",
    rate_limit_enabled=True,
    rate_limit_requests_per_minute=120,
    rate_limit_window_type="sliding",
)
```

### CORS

| Field | Type | Default | Environment |
|-------|------|---------|-------------|
| `cors_enabled` | bool | `false` | `FRAISEQL_CORS_ENABLED` |
| `cors_origins` | list[str] | `[]` | `FRAISEQL_CORS_ORIGINS` |
| `cors_methods` | list[str] | `["GET", "POST"]` | `FRAISEQL_CORS_METHODS` |
| `cors_headers` | list[str] | `["Content-Type", "Authorization"]` | `FRAISEQL_CORS_HEADERS` |

CORS is **disabled by default** — the recommended pattern is to handle CORS at the
reverse proxy. If you enable it, set explicit origins; a wildcard `*` origin in
production triggers a warning.

```python
config = FraiseQLConfig(
    database_url="postgresql://app:pass@localhost/myapp",
    cors_enabled=True,
    cors_origins=["https://app.example.com"],
)
```

---

## Authentication Settings

| Field | Type | Default | Environment |
|-------|------|---------|-------------|
| `auth_enabled` | bool | `true` | `FRAISEQL_AUTH_ENABLED` |
| `auth_provider` | `"auth0" \| "custom" \| "none"` | `"none"` | `FRAISEQL_AUTH_PROVIDER` |
| `auth0_domain` | str \| None | `None` | `FRAISEQL_AUTH0_DOMAIN` |
| `auth0_api_identifier` | str \| None | `None` | `FRAISEQL_AUTH0_API_IDENTIFIER` |
| `auth0_algorithms` | list[str] | `["RS256"]` | `FRAISEQL_AUTH0_ALGORITHMS` |
| `dev_auth_username` | str \| None | `"admin"` | `FRAISEQL_DEV_AUTH_USERNAME` |
| `dev_auth_password` | str \| None | `None` | `FRAISEQL_DEV_AUTH_PASSWORD` |

Three provider modes exist: `"auth0"`, `"custom"`, and `"none"`. For Auth0,
`auth0_domain` is required. For any other OIDC/JWT issuer, set
`auth_provider="custom"` and implement an `AuthProvider` subclass (or front the
issuer with Auth0). See the authentication guides for details.

```python
config = FraiseQLConfig(
    database_url="postgresql://app:pass@localhost/myapp",
    auth_enabled=True,
    auth_provider="auth0",
    auth0_domain="myapp.auth0.com",
    auth0_api_identifier="https://api.myapp.com",
)
```

---

## Token Revocation Settings

| Field | Type | Default | Environment |
|-------|------|---------|-------------|
| `revocation_enabled` | bool | `true` | `FRAISEQL_REVOCATION_ENABLED` |
| `revocation_check_enabled` | bool | `true` | `FRAISEQL_REVOCATION_CHECK_ENABLED` |
| `revocation_ttl` | int (seconds) | `86400` | `FRAISEQL_REVOCATION_TTL` |
| `revocation_cleanup_interval` | int (seconds) | `3600` | `FRAISEQL_REVOCATION_CLEANUP_INTERVAL` |
| `revocation_store_type` | str | `"memory"` | `FRAISEQL_REVOCATION_STORE_TYPE` |

`revocation_store_type` accepts `"memory"` or `"redis"`. A PostgreSQL-backed
revocation store is also available programmatically via
`fraiseql.auth.token_revocation.PostgreSQLRevocationStore`.

---

## Automatic Persisted Queries (APQ)

| Field | Type | Default | Environment |
|-------|------|---------|-------------|
| `apq_mode` | `"optional" \| "required" \| "disabled"` | `"optional"` | `FRAISEQL_APQ_MODE` |
| `apq_storage_backend` | `"memory" \| "postgresql" \| "custom"` | `"memory"` | `FRAISEQL_APQ_STORAGE_BACKEND` |
| `apq_cache_responses` | bool | `false` | `FRAISEQL_APQ_CACHE_RESPONSES` |
| `apq_response_cache_ttl` | int (seconds) | `600` | `FRAISEQL_APQ_RESPONSE_CACHE_TTL` |
| `apq_queries_dir` | str \| None | `None` | `FRAISEQL_APQ_QUERIES_DIR` |

In `apq_mode="required"`, only persisted query hashes are accepted; arbitrary
queries are rejected. Set `apq_queries_dir` to a directory of `.graphql`/`.gql`
files to auto-register them at startup — useful for security-hardened
deployments.

---

## Schema and Session Settings

### Default schemas

| Field | Type | Default | Environment |
|-------|------|---------|-------------|
| `default_query_schema` | str | `"public"` | `FRAISEQL_DEFAULT_QUERY_SCHEMA` |
| `default_mutation_schema` | str | `"public"` | `FRAISEQL_DEFAULT_MUTATION_SCHEMA` |
| `default_entity_schema` | str \| None | `None` | `FRAISEQL_DEFAULT_ENTITY_SCHEMA` |

PostgreSQL schemas to use for query views, mutation functions, and `tb_*` entity
tables when not specified on the decorator.

### `coordinate_distance_method`

**Type**: `"postgis" | "haversine" | "earthdistance"`
**Default**: `"haversine"`
**Environment**: `FRAISEQL_COORDINATE_DISTANCE_METHOD`

How coordinate-distance filters are computed. `"haversine"` works without
extensions; `"postgis"` is the most accurate but requires the PostGIS extension.

### `default_string_collation`

**Type**: `str | None`
**Default**: `None` (use the database default)
**Environment**: `FRAISEQL_DEFAULT_STRING_COLLATION`

PostgreSQL collation applied to text `ORDER BY` clauses, e.g. `"fr_FR.utf8"` or
`"C"`.

### `session_variables`

**Type**: `dict[str, str]`
**Default**: `{}`

Maps request-context keys to PostgreSQL session variable names that FraiseQL sets
via `SET LOCAL` before each query/mutation. This is how request context reaches
your views and Row-Level Security policies:

```python
config = FraiseQLConfig(
    database_url="postgresql://app:pass@localhost/myapp",
    session_variables={"locale": "app.locale", "timezone": "app.timezone"},
)
```

When `context["locale"] == "fr-FR"`, the connection executes
`SET LOCAL app.locale = 'fr-FR'`, so a view can read it:

```sql
WHERE code = COALESCE(current_setting('app.locale', true), 'fr-FR')
```

---

## Metrics and Observability

FraiseQL ships an optional Prometheus-based metrics integration in
`fraiseql.monitoring`. It is **separate** from `FraiseQLConfig`: you configure it
with a `MetricsConfig` dataclass and wire it into your FastAPI app with
`setup_metrics(app, config)`.

```python
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.monitoring import MetricsConfig, setup_metrics

app = create_fraiseql_app(
    database_url="postgresql://app:pass@localhost/myapp",
    types=[User],
    queries=[users],
)

metrics = setup_metrics(app, MetricsConfig(enabled=True))
```

`setup_metrics` installs request-timing middleware and mounts a Prometheus
scrape endpoint (default `GET /metrics`).

### `MetricsConfig` fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `true` | Enable metrics collection |
| `namespace` | str | `"fraiseql"` | Prefix for all metric names |
| `metrics_path` | str | `"/metrics"` | URL path for the metrics endpoint |
| `buckets` | list[float] | latency buckets `[0.005 … 10]` | Histogram bucket boundaries (seconds) |
| `exclude_paths` | set[str] | `{"/metrics", "/health", "/ready", "/startup"}` | Paths excluded from HTTP metrics |
| `labels` | dict[str, str] | `{}` | Extra labels applied to all metrics |

```python
from fraiseql.monitoring import MetricsConfig, setup_metrics

config = MetricsConfig(
    enabled=True,
    namespace="myapp",
    metrics_path="/metrics",
    labels={"service": "graphql-api", "region": "eu-west-1"},
)
metrics = setup_metrics(app, config)
```

Prometheus exposes the metrics in the standard text format on the configured
path:

```text
# HELP fraiseql_graphql_queries_total Total GraphQL queries
# TYPE fraiseql_graphql_queries_total counter
fraiseql_graphql_queries_total 1
# HELP fraiseql_graphql_query_duration_seconds Query duration
# TYPE fraiseql_graphql_query_duration_seconds histogram
fraiseql_graphql_query_duration_seconds_sum 0.01
fraiseql_graphql_query_duration_seconds_count 1
```

### Privacy

The metrics integration records query structure and timing only. It does **not**
record query arguments/variables, user identifiers, PII, or actual data values.

### Health checks

`fraiseql.monitoring` also provides health-check helpers you can mount in your
app:

```python
from fraiseql.monitoring import HealthCheck, check_database, check_pool_stats

health = HealthCheck()
health.add_check("database", check_database)
health.add_check("pool", check_pool_stats)

result = await health.run_checks()
```

---

## Production Configuration Examples

### Small Application (< 100 rps)

```python
from fraiseql.fastapi import FraiseQLConfig

config = FraiseQLConfig(
    database_url="postgresql://app:pass@localhost/myapp",
    environment="production",
    database_pool_size=5,
    database_max_overflow=5,
    cache_ttl=300,
    rate_limit_enabled=True,
    rate_limit_requests_per_minute=120,
)
```

### Medium Application (100–1000 rps)

```python
config = FraiseQLConfig(
    database_url="postgresql://app:pass@db-host:5432/myapp",
    environment="production",
    database_pool_size=20,
    database_max_overflow=10,
    cache_ttl=300,
    complexity_enabled=True,
    complexity_max_score=1000,
    rate_limit_enabled=True,
)
```

### Large Application (> 1000 rps)

```python
config = FraiseQLConfig(
    database_url="postgresql://app:pass@db-cluster:5432/myapp",
    environment="production",
    database_pool_size=40,
    database_max_overflow=20,
    database_pool_timeout=10,        # fail fast under load
    database_pool_recycle=1800,
    cache_ttl=600,
    execution_timeout_ms=15000,
    complexity_enabled=True,
    complexity_max_score=2000,
    rate_limit_enabled=True,
    rate_limit_requests_per_minute=600,
)
```

---

## Configuration Validation

`FraiseQLConfig` validates on construction (pydantic). For example, an invalid
database URL or a missing `auth0_domain` when `auth_provider="auth0"` raises a
`ValidationError` immediately at startup:

```python
from pydantic import ValidationError
from fraiseql.fastapi import FraiseQLConfig

try:
    config = FraiseQLConfig(database_url="mysql://nope")  # not PostgreSQL
except ValidationError as exc:
    print(exc)
    # Database URL must start with postgresql:// or postgres://
```

Notable validation behavior:

- `database_url` must start with `postgresql://` or `postgres://` (Unix sockets
  supported).
- In `environment="production"`, introspection and the playground are disabled
  unless explicitly re-enabled.
- A wildcard `*` CORS origin in production logs a security warning.
- `auth0_domain` is required when `auth_provider="auth0"`.
- Collation and session-variable names are validated against SQL-injection
  characters.

---

## Troubleshooting Configuration

### Settings not taking effect

1. Confirm the env var name is `FRAISEQL_`-prefixed and uppercase:

   ```bash
   echo $FRAISEQL_DATABASE_URL
   ```

2. Remember that explicit Python values passed to `FraiseQLConfig(...)` or
   `create_fraiseql_app(...)` override env vars.

3. If you use a `.env` file, make sure it sits in the process working directory.

### Database connection errors

1. Verify the URL works directly:

   ```bash
   psql "$FRAISEQL_DATABASE_URL" -c "SELECT 1"
   ```

2. Increase pool capacity if you see pool-timeout errors:

   ```python
   config = FraiseQLConfig(
       database_url="postgresql://app:pass@localhost/myapp",
       database_pool_size=40,
       database_max_overflow=20,
   )
   ```

### Inspecting generated SQL

Turn on SQL echo in development to see what FraiseQL sends to PostgreSQL:

```python
config = FraiseQLConfig(
    database_url="postgresql://app:pass@localhost/myapp",
    database_echo=True,
)
```

For application logs, use standard Python logging (e.g. `LOG_LEVEL` in your own
process configuration) and uvicorn's `--log-level` flag.

---

## Next Steps

- **[Observability Guide](./observability.md)** — metrics, health checks, and
  error tracking
- **[Authentication](../advanced/authentication.md)** — Auth0 and custom
  providers
- **[Deployment](../production/deployment.md)** — running the FastAPI app in production

---
title: Configuration API Reference
description: Complete API reference for FraiseQLConfig class with all configuration options
tags:
  - configuration
  - API
  - settings
  - FraiseQLConfig
  - environment
---

# FraiseQLConfig API Reference

Complete API reference for FraiseQLConfig class with all configuration options for v1.6.1.

## Overview

```python
from fraiseql import FraiseQLConfig

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    environment="production"
)
```

## Import

```python
from fraiseql import FraiseQLConfig
from fraiseql.fastapi.config import IntrospectionPolicy  # For introspection settings
```

## Configuration Sources

Configuration values can be set via:

1. **Direct instantiation** (highest priority)
2. **Environment variables** with `FRAISEQL_` prefix
3. **.env file** in project root
4. **Default values**

## Database Settings

### database_url

- **Type**: `PostgresUrl` (str with validation)
- **Required**: Yes
- **Default**: None
- **Description**: PostgreSQL connection URL with JSONB support required

**Formats**:

```python
# Standard PostgreSQL URL
"postgresql://user:password@host:port/database"

# Unix domain socket
"postgresql://user@/var/run/postgresql:5432/database"

# With password in socket connection
"postgresql://user:password@/var/run/postgresql:5432/database"
```

**Environment Variable**: `FRAISEQL_DATABASE_URL`

**Examples**:

```python
# Direct
config = FraiseQLConfig(database_url="postgresql://localhost/mydb")

# From environment
export FRAISEQL_DATABASE_URL="postgresql://localhost/mydb"
config = FraiseQLConfig()

# .env file
FRAISEQL_DATABASE_URL=postgresql://localhost/mydb
```

### database_pool_size

- **Type**: `int`
- **Default**: `20`
- **Description**: Maximum number of database connections in pool

### database_max_overflow

- **Type**: `int`
- **Default**: `10`
- **Description**: Extra connections allowed beyond pool_size

### database_pool_timeout

- **Type**: `int`
- **Default**: `30`
- **Description**: Connection timeout in seconds

### database_echo

- **Type**: `bool`
- **Default**: `False`
- **Description**: Enable SQL query logging (development only)

**Examples**:

```python
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    database_pool_size=50,
    database_max_overflow=20,
    database_pool_timeout=60,
    database_echo=True  # Development only
)
```

### default_string_collation

- **Type**: `str | None`
- **Default**: `None`
- **Description**: Default PostgreSQL collation for string ORDER BY clauses

Applied to all text fields in ORDER BY unless overridden per-field in queries.

!!! note "Text fields only"
    Each sort key is resolved against the type registered for the view, and the
    default is applied only to fields that resolve to a string. A field that
    resolves to anything else -- or that cannot be resolved at all, because the
    view is unregistered or the field is not declared on its type -- is left
    alone. Collating a numeric field would either sort it lexicographically
    (1, 10, 2) or fail with *collations are not supported by type integer*.

**Common Values**:

- `"C"` - Byte-order sorting (fastest, case-sensitive)
- `"POSIX"` - Equivalent to `"C"`
- `"en_US.utf8"` - US English locale-aware sorting
- `"fr_FR.utf8"` - French locale-aware sorting (handles accents)
- `"de_DE.utf8"` - German locale-aware sorting
- `None` - Use PostgreSQL database default collation

**Environment Variable**: `FRAISEQL_DEFAULT_STRING_COLLATION`

**Examples**:

```python
# Global default for French locale
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    default_string_collation="fr_FR.utf8"
)

# Per-query override in GraphQL
query {
  users(orderBy: [
    { field: "name", direction: ASC, collation: "en_US.utf8" }
  ]) {
    id
    name
  }
}
```

**Performance**: For best performance with collation, create matching indexes:

```sql
CREATE INDEX idx_users_name_fr
ON users ((data->>'name') COLLATE "fr_FR.utf8");
```

**See Also**: [ORDER BY Collation Support](../core/queries-and-mutations.md#collation-support)

## Application Settings

### app_name

- **Type**: `str`
- **Default**: `"FraiseQL API"`
- **Description**: Application name displayed in API documentation

### app_version

- **Type**: `str`
- **Default**: `"1.0.0"`
- **Description**: Application version string

### environment

- **Type**: `Literal["development", "production", "testing"]`
- **Default**: `"development"`
- **Description**: Current environment mode

**Impact**:

- `production`: Disables playground and introspection by default
- `development`: Enables debugging features
- `testing`: Used for test suites

**Examples**:

```python
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    app_name="My GraphQL API",
    app_version="2.1.0",
    environment="production"
)
```

## GraphQL Settings

### introspection_policy

- **Type**: `IntrospectionPolicy`
- **Default**: `IntrospectionPolicy.PUBLIC` (development), `IntrospectionPolicy.DISABLED` (production)
- **Description**: Schema introspection access control policy

**Values**:

| Value | Description |
|-------|-------------|
| `IntrospectionPolicy.DISABLED` | No introspection for anyone |
| `IntrospectionPolicy.PUBLIC` | Introspection allowed for everyone |
| `IntrospectionPolicy.AUTHENTICATED` | Introspection only for authenticated users |

**Examples**:

```python
from fraiseql.fastapi.config import IntrospectionPolicy

# Disable introspection in production
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    environment="production",
    introspection_policy=IntrospectionPolicy.DISABLED
)

# Require auth for introspection
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    introspection_policy=IntrospectionPolicy.AUTHENTICATED
)
```

### enable_playground

- **Type**: `bool`
- **Default**: `True` (development), `False` (production)
- **Description**: Enable GraphQL playground IDE

### playground_tool

- **Type**: `Literal["graphiql", "apollo-sandbox"]`
- **Default**: `"graphiql"`
- **Description**: Which GraphQL IDE to use

### max_query_depth

- **Type**: `int | None`
- **Default**: `None`
- **Description**: Maximum allowed query depth (None = unlimited)

### query_timeout

- **Type**: `int`
- **Default**: `30`
- **Description**: Maximum query execution time in seconds

### auto_camel_case

- **Type**: `bool`
- **Default**: `True`
- **Description**: Auto-convert snake_case fields to camelCase in GraphQL

**Examples**:

```python
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    introspection_policy=IntrospectionPolicy.DISABLED,
    enable_playground=False,
    max_query_depth=10,
    query_timeout=15,
    auto_camel_case=True
)
```

## Performance Settings

### enable_query_caching

- **Type**: `bool`
- **Default**: `True`
- **Description**: Enable query result caching

### cache_ttl

- **Type**: `int`
- **Default**: `300`
- **Description**: Cache time-to-live in seconds

### enable_turbo_router

- **Type**: `bool`
- **Default**: `True`
- **Description**: Enable TurboRouter for registered queries

### turbo_router_cache_size

- **Type**: `int`
- **Default**: `1000`
- **Description**: Maximum number of queries to cache

### turbo_router_auto_register

- **Type**: `bool`
- **Default**: `False`
- **Description**: Auto-register queries at startup

### turbo_max_complexity

- **Type**: `int`
- **Default**: `100`
- **Description**: Max complexity score for turbo caching

### turbo_max_total_weight

- **Type**: `float`
- **Default**: `2000.0`
- **Description**: Max total weight of cached queries

### turbo_enable_adaptive_caching

- **Type**: `bool`
- **Default**: `True`
- **Description**: Enable complexity-based admission

## JSON Passthrough Settings

### json_passthrough_enabled

- **Type**: `bool`
- **Default**: `True`
- **Description**: Enable JSON passthrough optimization

### json_passthrough_in_production

- **Type**: `bool`
- **Default**: `True`
- **Description**: Auto-enable in production mode

### json_passthrough_cache_nested

- **Type**: `bool`
- **Default**: `True`
- **Description**: Cache wrapped nested objects

### passthrough_complexity_limit

- **Type**: `int`
- **Default**: `50`
- **Description**: Max complexity for passthrough mode

### passthrough_max_depth

- **Type**: `int`
- **Default**: `3`
- **Description**: Max query depth for passthrough

### passthrough_auto_detect_views

- **Type**: `bool`
- **Default**: `True`
- **Description**: Auto-detect database views

### passthrough_cache_view_metadata

- **Type**: `bool`
- **Default**: `True`
- **Description**: Cache view metadata

### passthrough_view_metadata_ttl

- **Type**: `int`
- **Default**: `3600`
- **Description**: Metadata cache TTL in seconds

## JSONB Extraction Settings

### jsonb_extraction_enabled

- **Type**: `bool`
- **Default**: `True`
- **Description**: Enable automatic JSONB column extraction in production mode

### jsonb_default_columns

- **Type**: `list[str]`
- **Default**: `["data", "json_data", "jsonb_data"]`
- **Description**: Default JSONB column names to search for

### jsonb_auto_detect

- **Type**: `bool`
- **Default**: `True`
- **Description**: Auto-detect JSONB columns by analyzing content

### jsonb_field_limit_threshold

- **Type**: `int`
- **Default**: `20`
- **Description**: Field count threshold for full data column (default: 20)

**Examples**:

```python
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    jsonb_extraction_enabled=True,
    jsonb_default_columns=["data", "metadata", "json_data"],
    jsonb_auto_detect=True,
    jsonb_field_limit_threshold=30
)
```

## Rust Pipeline (v1.0.0+)

**v0.11.5 Architectural Change**: FraiseQL now uses an exclusive Rust pipeline for all query execution. No mode detection or conditional logic.

**Configuration Options**:

- `field_projection: bool = True` - Enable Rust-based field filtering
- `schema_registry: bool = True` - Enable schema-based transformation

**Benefits**:

- ✅ **Single execution path** - PostgreSQL → Rust → HTTP
- ✅ **7-10x faster JSON transformation** - Zero Python overhead
- ✅ **Always active** - No configuration needed
- ✅ **Automatic camelCase** - snake_case → camelCase conversion
- ✅ **Built-in __typename** - Automatic GraphQL type injection

**Migration from v0.11.4 and earlier**: Remove all execution mode configuration.

```python
# v0.11.4 and earlier (OLD - remove these)
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    execution_mode_priority=["turbo", "passthrough", "normal"],  # ❌ Remove
    enable_python_fallback=True,                                 # ❌ Remove
    passthrough_detection_enabled=True,                         # ❌ Remove
)

# v1.0.0+ - Exclusive Rust pipeline
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    # ✅ Rust pipeline always active, minimal config needed
)
```

## Authentication Settings

### auth_enabled

- **Type**: `bool`
- **Default**: `True`
- **Description**: Enable authentication system

### auth_provider

- **Type**: `Literal["auth0", "custom", "none"]`
- **Default**: `"none"`
- **Description**: Authentication provider to use

### auth0_domain

- **Type**: `str | None`
- **Default**: `None`
- **Description**: Auth0 tenant domain (required if using Auth0)

**Required when**: `auth_provider="auth0"`

### auth0_api_identifier

- **Type**: `str | None`
- **Default**: `None`
- **Description**: Auth0 API identifier (required if using Auth0)

**Required when**: `auth_provider="auth0"`

### auth0_algorithms

- **Type**: `list[str]`
- **Default**: `["RS256"]`
- **Description**: Auth0 JWT algorithms

### dev_auth_username

- **Type**: `str | None`
- **Default**: `"admin"`
- **Description**: Development mode username

### dev_auth_password

- **Type**: `str | None`
- **Default**: `None`
- **Description**: Development mode password

**Examples**:

```python
# Auth0 configuration
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    auth_enabled=True,
    auth_provider="auth0",
    auth0_domain="myapp.auth0.com",
    auth0_api_identifier="https://api.myapp.com",
    auth0_algorithms=["RS256"]
)

# Development auth
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    environment="development",
    auth_provider="custom",
    dev_auth_username="admin",
    dev_auth_password="secret"
)
```

## CORS Settings

### cors_enabled

- **Type**: `bool`
- **Default**: `False`
- **Description**: Enable CORS (disabled by default to avoid conflicts with reverse proxies)

### cors_origins

- **Type**: `list[str]`
- **Default**: `[]`
- **Description**: Allowed CORS origins (empty by default, must be explicitly configured)

**Warning**: Using `["*"]` in production is a security risk

### cors_methods

- **Type**: `list[str]`
- **Default**: `["GET", "POST"]`
- **Description**: Allowed HTTP methods for CORS

### cors_headers

- **Type**: `list[str]`
- **Default**: `["Content-Type", "Authorization"]`
- **Description**: Allowed headers for CORS requests

**Examples**:

```python
# Production CORS (specific origins)
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    cors_enabled=True,
    cors_origins=[
        "https://app.example.com",
        "https://admin.example.com"
    ],
    cors_methods=["GET", "POST", "OPTIONS"],
    cors_headers=["Content-Type", "Authorization", "X-Request-ID"]
)
```

## Rate Limiting Settings

### rate_limit_enabled

- **Type**: `bool`
- **Default**: `True`
- **Description**: Enable rate limiting

### rate_limit_requests_per_minute

- **Type**: `int`
- **Default**: `60`
- **Description**: Maximum requests per minute

### rate_limit_requests_per_hour

- **Type**: `int`
- **Default**: `1000`
- **Description**: Maximum requests per hour

### rate_limit_burst_size

- **Type**: `int`
- **Default**: `10`
- **Description**: Burst size for rate limiting

### rate_limit_window_type

- **Type**: `str`
- **Default**: `"sliding"`
- **Description**: Window type ("sliding" or "fixed")

### rate_limit_whitelist

- **Type**: `list[str]`
- **Default**: `[]`
- **Description**: IP addresses to whitelist

### rate_limit_blacklist

- **Type**: `list[str]`
- **Default**: `[]`
- **Description**: IP addresses to blacklist

**Examples**:

```python
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    rate_limit_enabled=True,
    rate_limit_requests_per_minute=30,
    rate_limit_requests_per_hour=500,
    rate_limit_burst_size=5,
    rate_limit_whitelist=["10.0.0.1", "10.0.0.2"]
)
```

## Complexity Settings

### complexity_enabled

- **Type**: `bool`
- **Default**: `True`
- **Description**: Enable query complexity analysis

### complexity_max_score

- **Type**: `int`
- **Default**: `1000`
- **Description**: Maximum allowed complexity score

### complexity_max_depth

- **Type**: `int`
- **Default**: `10`
- **Description**: Maximum query depth

### complexity_default_list_size

- **Type**: `int`
- **Default**: `10`
- **Description**: Default list size for complexity calculation

### complexity_include_in_response

- **Type**: `bool`
- **Default**: `False`
- **Description**: Include complexity score in response

### complexity_field_multipliers

- **Type**: `dict[str, int]`
- **Default**: `{}`
- **Description**: Custom field complexity multipliers

**Examples**:

```python
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    complexity_enabled=True,
    complexity_max_score=500,
    complexity_max_depth=8,
    complexity_field_multipliers={
        "users": 2,
        "posts": 1,
        "comments": 3
    }
)
```

## APQ Settings

### apq_mode

- **Type**: `Literal["optional", "required", "disabled"]`
- **Default**: `"optional"`
- **Description**: APQ mode for controlling query acceptance

| Mode | Behavior |
|------|----------|
| `"optional"` | Accept both persisted query hashes and full queries (default) |
| `"required"` | **Only** accept persisted query hashes, reject arbitrary queries |
| `"disabled"` | Ignore APQ extensions entirely, always require full query |

*New in FraiseQL v1.6.1*

### apq_storage_backend

- **Type**: `Literal["memory", "postgresql", "custom"]`
- **Default**: `"memory"`
- **Description**: Storage backend for APQ (Automatic Persisted Queries)

### apq_queries_dir

- **Type**: `str | None`
- **Default**: `None`
- **Description**: Directory containing `.graphql` files to auto-register at startup

When set, all `.graphql` and `.gql` files in this directory (recursively) will be loaded and registered as persisted queries at application startup. Useful with `apq_mode="required"` for security-hardened deployments.

*New in FraiseQL v1.6.1*

### apq_cache_responses

- **Type**: `bool`
- **Default**: `False`
- **Description**: Enable JSON response caching for APQ queries

### apq_response_cache_ttl

- **Type**: `int`
- **Default**: `600`
- **Description**: Cache TTL for APQ responses in seconds

### apq_backend_config

- **Type**: `dict[str, Any]`
- **Default**: `{}`
- **Description**: Backend-specific configuration options

**Examples**:

```python
# APQ with PostgreSQL backend
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    apq_storage_backend="postgresql",
    apq_cache_responses=True,
    apq_response_cache_ttl=900
)

# APQ with custom Redis backend (bring your own implementation)
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    apq_storage_backend="custom",
    apq_backend_config={
        "backend_class": "myapp.storage.RedisAPQBackend",
        "redis_url": "redis://localhost:6379/0",
        "key_prefix": "apq:"
    }
)

# Security-hardened: Only allow pre-registered queries (v1.6.0+)
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    apq_mode="required",                  # Reject arbitrary queries
    apq_queries_dir="./graphql/queries/", # Auto-register from directory
    apq_storage_backend="postgresql",     # Persist across restarts
)
```

## Token Revocation Settings

### revocation_enabled

- **Type**: `bool`
- **Default**: `True`
- **Description**: Enable token revocation

### revocation_check_enabled

- **Type**: `bool`
- **Default**: `True`
- **Description**: Check revocation status on requests

### revocation_ttl

- **Type**: `int`
- **Default**: `86400`
- **Description**: Token revocation TTL in seconds (24 hours)

### revocation_cleanup_interval

- **Type**: `int`
- **Default**: `3600`
- **Description**: Cleanup interval in seconds (1 hour)

### revocation_store_type

- **Type**: `str`
- **Default**: `"memory"`
- **Description**: Storage type ("memory" or "redis")

## Rust Pipeline Settings

### field_projection

- **Type**: `bool`
- **Default**: `True`
- **Description**: Enable Rust-based field filtering

### schema_registry

- **Type**: `bool`
- **Default**: `True`
- **Description**: Enable schema-based transformation

**Examples**:

```python
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    field_projection=True,  # Enable field filtering
    schema_registry=True    # Enable schema-based transformation
)
```

## Schema Settings

### default_mutation_schema

- **Type**: `str`
- **Default**: `"public"`
- **Description**: Default schema for mutations when not specified

### default_query_schema

- **Type**: `str`
- **Default**: `"public"`
- **Description**: Default schema for queries when not specified

**Examples**:

```python
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    default_mutation_schema="app",
    default_query_schema="api"
)
```

## Mutation Error Handling Settings

### default_error_config

- **Type**: `MutationErrorConfig | None`
- **Default**: `None`
- **Description**: Default error configuration for all mutations when not explicitly specified in the `@mutation` decorator

**Impact**:

- When set, all mutations without an explicit `error_config` parameter will use this global default
- Individual mutations can override the global default by specifying `error_config` in the decorator
- Only used in non-HTTP mode (direct GraphQL execution); HTTP mode uses [status string taxonomy](../archive/mutations/status-strings.md)

**Available Configurations**:

| Configuration | Description |
|---------------|-------------|
| `DEFAULT_ERROR_CONFIG` | Standard error handling with common error keywords and prefixes |
| `STRICT_STATUS_CONFIG` | Strict prefix-based error detection, fewer keywords |
| `ALWAYS_DATA_CONFIG` | Returns all statuses as data (never raises GraphQL errors) |
| Custom `MutationErrorConfig` | Define your own error detection rules |

**Examples**:

```python
from fraiseql import FraiseQLConfig, DEFAULT_ERROR_CONFIG, STRICT_STATUS_CONFIG

# Development: Use standard error handling globally
dev_config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    environment="development",
    default_error_config=DEFAULT_ERROR_CONFIG,
)

# Production: Use stricter error handling globally
prod_config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    environment="production",
    default_error_config=STRICT_STATUS_CONFIG,
)

# Custom error configuration
from fraiseql import MutationErrorConfig

custom_config = MutationErrorConfig(
    success_keywords={"success", "ok", "done"},
    error_prefixes={"error:", "failed:"},
    always_return_as_data=False,
)

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    default_error_config=custom_config,
)
```

**With Mutations**:

```python
from fraiseql import mutation, FraiseQLConfig, DEFAULT_ERROR_CONFIG, STRICT_STATUS_CONFIG

# Global config with default error handling
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    default_error_config=DEFAULT_ERROR_CONFIG,  # Applied to all mutations by default
)

# Mutation uses global default (no error_config specified)
@mutation(function="create_user")
class CreateUser:
    input: CreateUserInput
    success: CreateUserSuccess
    failure: CreateUserError
    # Uses DEFAULT_ERROR_CONFIG from config

# Mutation overrides global default
@mutation(
    function="delete_user",
    error_config=STRICT_STATUS_CONFIG,  # Override: Use stricter config for deletions
)
class DeleteUser:
    input: DeleteUserInput
    success: DeleteUserSuccess
    failure: DeleteUserError
    # Uses STRICT_STATUS_CONFIG (explicit override)
```

**Resolution Order**:

1. Explicit `error_config` in `@mutation` decorator (highest priority)
2. `default_error_config` from `FraiseQLConfig`
3. `None` (no error configuration, uses default behavior)

**Benefits**:

- **DRY Principle**: Set error handling once, apply everywhere
- **Environment-aware**: Different configs for dev/staging/prod
- **Maintainability**: Change error strategy in one place
- **Flexibility**: Override per-mutation when needed

**See Also**:

- [Mutation Decorator](./decorators.md#fraiseqlmutation) - Mutation decorator reference
- [Status Strings](../archive/mutations/status-strings.md) - Status string conventions (HTTP mode)

## Entity Routing Settings

### entity_routing

- **Type**: `EntityRoutingConfig | dict | None`
- **Default**: `None`
- **Description**: Configuration for entity-aware query routing (optional)

**Examples**:

```python
from fraiseql.routing.config import EntityRoutingConfig

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    entity_routing=EntityRoutingConfig(
        enabled=True,
        default_schema="public",
        entity_mapping={
            "User": "users_schema",
            "Post": "content_schema"
        }
    )
)

# Or using dict
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    entity_routing={
        "enabled": True,
        "default_schema": "public"
    }
)
```

## Properties

### enable_introspection

- **Type**: `bool` (read-only property)
- **Description**: Backward compatibility property for enable_introspection

Returns `True` if `introspection_policy != IntrospectionPolicy.DISABLED`

## Complete Example

```python
from fraiseql import FraiseQLConfig
from fraiseql.fastapi.config import IntrospectionPolicy

config = FraiseQLConfig(
    # Database
    database_url="postgresql://user:pass@db.example.com:5432/prod",
    database_pool_size=50,
    database_max_overflow=20,
    database_pool_timeout=60,

    # Application
    app_name="Production API",
    app_version="2.0.0",
    environment="production",

    # GraphQL
    introspection_policy=IntrospectionPolicy.DISABLED,
    enable_playground=False,
    max_query_depth=10,
    query_timeout=15,

    # Performance
    enable_query_caching=True,
    cache_ttl=600,
    enable_turbo_router=True,
    jsonb_extraction_enabled=True,

    # Auth
    auth_enabled=True,
    auth_provider="auth0",
    auth0_domain="myapp.auth0.com",
    auth0_api_identifier="https://api.myapp.com",

    # CORS
    cors_enabled=True,
    cors_origins=["https://app.example.com"],

    # Rate Limiting
    rate_limit_enabled=True,
    rate_limit_requests_per_minute=30,

    # Complexity
    complexity_enabled=True,
    complexity_max_score=500
)
```

## See Also

- [Configuration Guide](../core/configuration.md) - Configuration patterns and examples
- [Deployment](../production/deployment.md) - Production configuration

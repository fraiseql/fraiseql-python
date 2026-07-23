---
title: GraphQL Schema Introspection Specification
description: FraiseQL provides comprehensive control over GraphQL schema introspection through a three-tier policy system. Schema introspection allows clients to query schema information, which is essential for development tools but poses a security risk in production.
keywords: ["format", "compliance", "schema", "graphql", "protocol", "specification", "standard"]
tags: ["documentation", "reference"]
---

# GraphQL Schema Introspection Specification

**Status:** Stable
**Version**: 1.0
**Last Updated**: 2026-01-11

## Overview

FraiseQL provides comprehensive control over GraphQL schema introspection through a three-tier policy system. Schema introspection allows clients to query schema information (`__schema`, `__type`, `__typename`), which is essential for development tools but poses a security risk in production environments.

This specification defines introspection policies, configuration options, enforcement mechanisms, and best practices for different deployment environments.

### Key Concepts

- **Introspection Query**: Any query accessing `__schema`, `__type`, `__typename`, or `__directive` fields
- **IntrospectionPolicy**: Configuration determining who can execute introspection queries
- **Schema Reflection**: Automatic discovery of database schema for type generation
- **Auto-Discovery**: Generating GraphQL types from PostgreSQL database schema

---

## Introspection Policies

FraiseQL provides three introspection policies to balance developer experience with security. The policy is a real `FraiseQLConfig` field, `introspection_policy`, of type `IntrospectionPolicy`.

### DISABLED Policy (Production)

**Configuration**:

```python
from fraiseql.fastapi import FraiseQLConfig
from fraiseql.fastapi.config import IntrospectionPolicy

config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    introspection_policy=IntrospectionPolicy.DISABLED,
)
```

**Environment Variable**:

```bash
export FRAISEQL_INTROSPECTION_POLICY=disabled
```

**Behavior**:

- ❌ No introspection queries allowed
- ❌ Blocks `__schema` queries
- ❌ Blocks `__type` queries
- ❌ Blocks `__typename` fields
- ❌ Blocks `__directive` queries
- ✅ Authentication requirement: None (blocks regardless of auth status)
- ✅ Suitable for production/public APIs

**Client Request** (rejected):

```graphql
query {
  __schema {
    types {
      name
    }
  }
}
```

**Server Response**:

```json
{
  "errors": [{
    "message": "GraphQL introspection is disabled",
    "extensions": {
      "code": "INTROSPECTION_DISABLED"
    }
  }]
}
```

**Use Cases**:

- Production GraphQL APIs
- Public-facing APIs with untrusted clients
- Regulated industries (financial, healthcare)
- Security-sensitive systems
- APIs where schema should not be exposed

**Security Benefits**:

- Prevents schema reconnaissance by attackers
- Hides available mutations and their signatures
- Blocks query complexity analysis via introspection
- Prevents automated attack tool operation

### AUTHENTICATED Policy

**Configuration**:

```python
config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    introspection_policy=IntrospectionPolicy.AUTHENTICATED,
)
```

**Environment Variable**:

```bash
export FRAISEQL_INTROSPECTION_POLICY=authenticated
```

**Behavior**:

- ✅ Introspection allowed only for authenticated users
- ✅ Requires valid authentication (JWT, OAuth, etc.)
- ❌ Unauthenticated users blocked
- ✅ Internal development tools can introspect
- ✅ Production API consumed by internal/trusted clients

**Client Request** (unauthenticated):

```graphql
query {
  __type(name: "User") {
    name
    fields { name }
  }
}
```

**Server Response** (unauthenticated):

```json
{
  "errors": [{
    "message": "Authentication required for introspection",
    "extensions": {
      "code": "AUTHENTICATION_REQUIRED",
      "introspection_policy": "authenticated"
    }
  }]
}
```

**Client Request** (authenticated):

```graphql
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

query {
  __type(name: "User") {
    name
    fields {
      name
      type { kind name }
    }
  }
}
```

**Server Response** (authenticated - success):

```json
{
  "data": {
    "__type": {
      "name": "User",
      "fields": [
        {"name": "id", "type": {"kind": "SCALAR", "name": "ID"}},
        {"name": "name", "type": {"kind": "SCALAR", "name": "String"}},
        {"name": "email", "type": {"kind": "SCALAR", "name": "String"}}
      ]
    }
  }
}
```

**Use Cases**:

- Staging environments
- Internal company APIs
- APIs with trusted internal clients
- Development APIs requiring authentication
- GraphQL playgrounds for internal tools

**Security Characteristics**:

- Prevents external schema reconnaissance
- Allows internal development tools to function
- Requires credential possession (authentication)
- Suitable for internal APIs with known clients

### PUBLIC Policy (Development Only)

**Configuration**:

```python
config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    introspection_policy=IntrospectionPolicy.PUBLIC,
)
```

`PUBLIC` is the default value of `introspection_policy`, but it is automatically downgraded to `DISABLED` when `environment="production"` unless you set it explicitly.

**Environment Variable**:

```bash
export FRAISEQL_INTROSPECTION_POLICY=public
```

**Behavior**:

- ✅ Introspection allowed for all clients
- ✅ No authentication required
- ✅ Full schema disclosure
- ✅ Developer-friendly (supports IDE tooling, the GraphQL playground, etc.)

**Client Request**:

```graphql
query {
  __schema {
    queryType { name }
    types {
      name
      kind
      fields { name }
    }
  }
}
```

**Server Response** (success):

```json
{
  "data": {
    "__schema": {
      "queryType": {"name": "Query"},
      "types": [
        {
          "name": "String",
          "kind": "SCALAR",
          "fields": null
        },
        {
          "name": "Query",
          "kind": "OBJECT",
          "fields": [
            {"name": "user"},
            {"name": "users"},
            {"name": "posts"}
          ]
        }
      ]
    }
  }
}
```

**Use Cases**:

- Local development
- CI/CD test environments
- Public/open source APIs
- Learning and tutorial projects

⚠️ **Warning**: Never use PUBLIC policy in production environments!

---

## Environment-Based Auto-Configuration

FraiseQL adjusts the effective introspection policy based on the configured `environment`. The `FraiseQLConfig` field validators downgrade `introspection_policy` to `DISABLED` and disable `enable_playground` when `environment="production"` (unless you override them explicitly).

**Automatic Policy Selection**:

```python
from fraiseql.fastapi import FraiseQLConfig

# Development environment
config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    environment="development",  # introspection_policy stays PUBLIC (default)
)

# Production environment
config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    environment="production",   # introspection_policy auto-downgraded to DISABLED
)
```

The supported `environment` values are `"development"`, `"production"`, and `"testing"`.

**Environment Variables**:

```bash
# Automatic policy downgrade in production
export FRAISEQL_ENVIRONMENT=production  # auto-disables introspection + playground

# Manual override (takes precedence)
export FRAISEQL_INTROSPECTION_POLICY=disabled
```

**Default Behavior**:

- Development: PUBLIC (the default `introspection_policy`)
- Production: DISABLED (auto-downgraded unless set explicitly)
- Testing: PUBLIC (for test suites)

---

## Security Profiles and Introspection

FraiseQL ships pre-configured security profiles (`fraiseql.security.profiles.definitions`) that bundle an appropriate introspection policy together with other hardening defaults. Profiles are descriptive configuration metadata: read the desired `introspection_policy` from a profile and pass it to `FraiseQLConfig`.

### STANDARD Profile

- Introspection Policy: **AUTHENTICATED**
- TLS: Optional
- Audit: Standard
- Rationale: Internal APIs with authentication requirement
- Suitable for: Development, staging, trusted internal users

### REGULATED Profile

- Introspection Policy: **DISABLED**
- TLS: Required (1.2+)
- Audit: Enhanced with field tracking
- Rationale: Financial/healthcare services cannot expose schema
- Suitable for: Financial services, healthcare, PCI-DSS compliance

### RESTRICTED Profile

- Introspection Policy: **DISABLED**
- TLS: Required (1.3+)
- mTLS: Required
- Audit: Verbose
- Rationale: Maximum security, zero schema exposure
- Suitable for: Government systems, critical infrastructure, military

**Usage**:

```python
from fraiseql.fastapi import FraiseQLConfig
from fraiseql.fastapi.config import IntrospectionPolicy
from fraiseql.security.profiles.definitions import get_profile

# STANDARD: AUTHENTICATED introspection
profile = get_profile("standard")
config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    introspection_policy=IntrospectionPolicy.AUTHENTICATED,  # from the standard profile
)

# REGULATED / RESTRICTED: DISABLED introspection
profile = get_profile("regulated")
config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    introspection_policy=IntrospectionPolicy.DISABLED,  # from the regulated/restricted profile
)
```

The `SecurityProfileConfig` returned by `get_profile(...)` exposes `introspection_policy` (among other fields), so you can read it programmatically:

```python
from fraiseql.fastapi import FraiseQLConfig
from fraiseql.fastapi.config import IntrospectionPolicy
from fraiseql.security.profiles.definitions import get_profile

profile = get_profile("restricted")
config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    introspection_policy=IntrospectionPolicy(profile.introspection_policy.value),
)
```

---

## Introspection Query Detection

FraiseQL detects introspection queries using pattern matching on reserved GraphQL field names.

### Detected Introspection Patterns

FraiseQL blocks queries containing any of these patterns:

- **`__schema`** - Schema type

  ```graphql
  query {
    __schema { types { name } }
  }
  ```

- **`__type`** - Specific type inspection

  ```graphql
  query {
    __type(name: "User") { name fields { name } }
  }
  ```

- **`__typename`** - Type name of objects

  ```graphql
  query {
    users {
      __typename
      id
      name
    }
  }
  ```

- **`__directive`** - Directive inspection

  ```graphql
  query {
    __schema {
      directives { name args { name } }
    }
  }
  ```

### Detection Behavior

**Case Insensitive**: Detection is case-insensitive

```graphql
# All of these are detected and blocked:
query { __schema { ... } }
query { __SCHEMA { ... } }
query { __Schema { ... } }
```

**Mixed Queries**: Introspection combined with regular queries is blocked

```graphql
# Blocked (contains introspection)
query {
  users { id name }
  __type(name: "User") { name }
}
```

**Implementation Detail**: Pattern matching is performed with case-lowering before comparison, as a pragmatic security measure.

---

## Error Responses

When introspection is blocked, FraiseQL returns standardized error responses.

### DISABLED Policy Error

```json
{
  "errors": [{
    "message": "GraphQL introspection is disabled",
    "extensions": {
      "code": "INTROSPECTION_DISABLED",
      "policy": "disabled"
    }
  }]
}
```

### AUTHENTICATED Policy Error (Unauthenticated)

```json
{
  "errors": [{
    "message": "Authentication required to access schema information",
    "extensions": {
      "code": "AUTHENTICATION_REQUIRED",
      "policy": "authenticated"
    }
  }]
}
```

### AUTHENTICATED Policy Error (Invalid Token)

```json
{
  "errors": [{
    "message": "Invalid authentication token",
    "extensions": {
      "code": "INVALID_TOKEN",
      "policy": "authenticated"
    }
  }]
}
```

### Generic Responses in Production

In production environments, error messages are intentionally generic to avoid leaking configuration details:

```json
{
  "errors": [{
    "message": "Introspection is not available",
    "extensions": {
      "code": "INTROSPECTION_NOT_AVAILABLE"
    }
  }]
}
```

---

## Schema Reflection and Auto-Discovery

Beyond security policies, FraiseQL provides tools to reflect on schema information programmatically and to discover GraphQL types from your PostgreSQL database at runtime.

### PostgreSQL Introspection

**Auto-Discovery from Database**:

FraiseQL can discover GraphQL read views from a PostgreSQL database. `PostgresIntrospector` takes an async connection pool (a `psycopg_pool.AsyncConnectionPool`):

```python
import psycopg_pool
from fraiseql.introspection.postgres_introspector import PostgresIntrospector

pool = psycopg_pool.AsyncConnectionPool("postgresql://localhost/fraiseql_db")
introspector = PostgresIntrospector(connection_pool=pool)

# Discover all read views
views = await introspector.discover_views(pattern="v_%")  # Views starting with "v_"
# Returns: [ViewMetadata, ViewMetadata, ...]

# Get view details
for view in views:
    print(f"View: {view.name}")
    for column in view.columns:
        print(f"  {column.name}: {column.pg_type} (nullable: {column.nullable})")
```

**Pattern Matching**:

```python
# LIKE pattern (SQL wildcards)
views = await introspector.discover_views(pattern="v_%")      # "v_*" pattern

# Regular expression
views = await introspector.discover_views(
    pattern="^v_(user|post)s?$",
    use_regex=True,
)

# Schema filtering
views = await introspector.discover_views(
    pattern="%",
    schemas=["public", "staging"],  # Only these schemas
)
```

**Metadata Extraction**:

```python
view = views[0]

# View information
print(f"View Name: {view.name}")
print(f"OID: {view.oid}")
print(f"Owner: {view.owner}")
print(f"Comment: {view.comment}")  # From PostgreSQL comment

# Column information
for col in view.columns:
    print(f"  {col.name}")
    print(f"    Type: {col.pg_type}")
    print(f"    Nullable: {col.nullable}")
    print(f"    Default: {col.default_value}")
    print(f"    Comment: {col.comment}")
```

### Type Generation from Database

**Automatic Type Creation**:

`TypeGenerator` builds a `@fraiseql.type` class from a discovered view. It is constructed with an optional `TypeMapper`, and `generate_type_class(...)` is an async method:

```python
from fraiseql.introspection.type_generator import TypeGenerator

generator = TypeGenerator()

# Generate a GraphQL type class from a database view
User = await generator.generate_type_class(view)

# The generated class is decorated with @fraiseql.type and ready to use
@fraiseql.query
async def get_user(info, id: ID) -> User | None:
    db = info.context["db"]
    return await db.find_one("v_users", id=id)
```

### Type Introspection API

**Runtime Type Inspection**:

```python
import fraiseql
from fraiseql.utils.introspection import describe_type
from fraiseql.types import ID

@fraiseql.type
class User:
    id: ID
    name: str
    email: str | None = None

# Describe type at runtime
description = describe_type(User)
# Returns:
# {
#   "typename": "User",
#   "is_input": False,
#   "is_output": True,
#   "is_frozen": False,
#   "kw_only": False,
#   "fields": {
#     "id": {"type": "ID", "required": True, "description": None},
#     "name": {"type": "String", "required": True, "description": None},
#     "email": {"type": "String", "required": False, "description": None}
#   }
# }

# Access field information
for field_name, field_info in description["fields"].items():
    print(f"{field_name}: {field_info['type']} (required: {field_info['required']})")
```

---

## Production Best Practices

### Deployment Checklist

- [ ] **Introspection Policy**: Set `introspection_policy=IntrospectionPolicy.DISABLED` in production
- [ ] **Environment Variable**: `FRAISEQL_INTROSPECTION_POLICY=disabled`
- [ ] **Playground**: Disable the GraphQL playground (`enable_playground=False`, auto-disabled in production)
- [ ] **Alternative Documentation**: Provide API documentation via OpenAPI/Swagger or a documentation site
- [ ] **Monitoring**: Enable logging of introspection denial attempts
- [ ] **Rate Limiting**: Apply rate limits to prevent DoS attempts
- [ ] **Security Headers**: Include CSP and other headers
- [ ] **Client Preparation**: Ensure all clients have persisted queries (APQ) instead of relying on introspection
- [ ] **Testing**: Verify introspection is blocked before deploying

### Client Alternatives to Introspection

When introspection is disabled, clients need alternative ways to discover the schema:

**1. Automatic Persisted Queries (APQ)**

- Queries pre-registered with the server
- Client sends only a hash, not the full query
- No introspection needed
- See: [Persisted Queries Specification](persisted-queries.md)

**2. Hand-Maintained Schema Document**

- Keep a checked-in copy of the GraphQL SDL in your repository
- Update it as part of each release
- Distribute it to client teams for code generation

**3. API Documentation Site**

- Host schema documentation on a separate website
- Markdown, HTML, or an interactive explorer
- Updated with each release

**4. GraphQL Code Generation**

```bash
# Generate TypeScript types from a checked-in SDL document (during build)
graphql-codegen --config codegen.yml
```

### Monitoring Introspection Attempts

**Security Event Logging**:

Enable security logging to track introspection attempts using `SecurityLogger`:

```python
from fraiseql.audit.security_logger import SecurityLogger

logger = SecurityLogger(
    log_to_file=True,
    log_file_path="/var/log/fraiseql-security.log",
    log_to_stdout=True,
)
```

**Log Example**:

```json
{
  "timestamp": "2025-01-11T10:30:45Z",
  "event_type": "QUERY_REJECTED",
  "severity": "WARNING",
  "ip_address": "192.0.2.1",
  "reason": "GraphQL introspection is disabled",
  "request_id": "req-abc123",
  "metadata": {
    "query_contains": "__schema",
    "policy": "disabled"
  }
}
```

**WAF Integration** (CrowdSec):

```yaml
# Deploy WAF rule to block introspection attempts
type: trigger
name: fraiseql/graphql-introspection
description: "Detect GraphQL introspection queries"
filter: |
  evt.Meta.log_type == 'nginx' &&
  (evt.Parsed.request contains '__schema' ||
   evt.Parsed.request contains '__type')
blackhole: 1h
```

### Rate Limiting Introspection

If introspection is AUTHENTICATED, rate-limit it via `RateLimitConfig`:

```python
from fraiseql.middleware.rate_limiter import RateLimitConfig

rate_limit_config = RateLimitConfig(
    strategies={
        # Introspection queries allowed but heavily rate-limited
        "introspection": {
            "limit": 5,           # 5 introspection queries/minute
            "window": 60,
            "per": "user",        # Per authenticated user
        },
        "query": {
            "limit": 100,         # Regular queries higher limit
            "window": 60,
        },
    }
)
```

---

## Testing Introspection Policies

### Test Cases

**DISABLED Policy - All Requests Blocked**:

```python
import pytest
from fraiseql.fastapi import FraiseQLConfig
from fraiseql.fastapi.config import IntrospectionPolicy

@pytest.mark.asyncio
async def test_introspection_disabled_blocks_schema_query():
    config = FraiseQLConfig(
        database_url="postgresql://localhost/test_db",
        introspection_policy=IntrospectionPolicy.DISABLED,
    )

    query = "query { __schema { types { name } } }"
    result = await schema.execute(query, context_value={})

    assert result.errors
    assert any("introspection" in str(e).lower() for e in result.errors)
```

**AUTHENTICATED Policy - Auth Required**:

```python
@pytest.mark.asyncio
async def test_introspection_authenticated_requires_auth():
    config = FraiseQLConfig(
        database_url="postgresql://localhost/test_db",
        introspection_policy=IntrospectionPolicy.AUTHENTICATED,
    )

    # Unauthenticated request
    query = "query { __type(name: \"User\") { name } }"
    result = await schema.execute(query, context_value={})

    assert result.errors
    assert "authentication" in str(result.errors[0]).lower()

@pytest.mark.asyncio
async def test_introspection_authenticated_succeeds_with_auth():
    config = FraiseQLConfig(
        database_url="postgresql://localhost/test_db",
        introspection_policy=IntrospectionPolicy.AUTHENTICATED,
    )

    # Authenticated request
    query = "query { __type(name: \"User\") { name } }"
    context = {"user_id": "user-123"}
    result = await schema.execute(query, context_value=context)

    assert not result.errors
    assert result.data["__type"]["name"] == "User"
```

**PUBLIC Policy - All Allowed**:

```python
@pytest.mark.asyncio
async def test_introspection_public_allows_all():
    config = FraiseQLConfig(
        database_url="postgresql://localhost/test_db",
        introspection_policy=IntrospectionPolicy.PUBLIC,
    )

    query = "query { __schema { types { name } } }"
    result = await schema.execute(query, context_value={})

    assert not result.errors
    assert result.data["__schema"]["types"]
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_introspection_mixed_query_rejected():
    """Introspection combined with regular query should be rejected."""
    config = FraiseQLConfig(
        database_url="postgresql://localhost/test_db",
        introspection_policy=IntrospectionPolicy.DISABLED,
    )

    query = """
    query {
      users { id name }
      __type(name: "User") { name }
    }
    """
    result = await schema.execute(query)

    assert result.errors
    assert "introspection" in str(result.errors[0]).lower()
```

---

## Configuration Examples

### Development Environment

```python
# config/development.py
from fraiseql.fastapi import FraiseQLConfig
from fraiseql.fastapi.config import IntrospectionPolicy

config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_dev",
    environment="development",
    introspection_policy=IntrospectionPolicy.PUBLIC,  # Explicit is better
)
```

**Environment Variables**:

```bash
FRAISEQL_ENVIRONMENT=development
FRAISEQL_INTROSPECTION_POLICY=public
```

### Staging Environment

```python
# config/staging.py
from fraiseql.fastapi import FraiseQLConfig
from fraiseql.fastapi.config import IntrospectionPolicy

config = FraiseQLConfig(
    database_url="postgresql://pg-staging/fraiseql_db",
    environment="development",  # staging runs with development semantics
    introspection_policy=IntrospectionPolicy.AUTHENTICATED,
)
```

**Environment Variables**:

```bash
FRAISEQL_ENVIRONMENT=development
FRAISEQL_INTROSPECTION_POLICY=authenticated
```

### Production Environment

```python
# config/production.py
from fraiseql.fastapi import FraiseQLConfig
from fraiseql.fastapi.config import IntrospectionPolicy

config = FraiseQLConfig(
    database_url="postgresql://pg-prod/fraiseql_db",
    environment="production",
    introspection_policy=IntrospectionPolicy.DISABLED,
    enable_playground=False,
)
```

**Environment Variables**:

```bash
FRAISEQL_ENVIRONMENT=production
FRAISEQL_INTROSPECTION_POLICY=disabled
```

---

## API Documentation Without Introspection

When introspection is disabled, provide schema documentation through these alternatives:

### 1. Hand-Maintained SDL Document

Keep a checked-in copy of the GraphQL SDL in your repository and update it on each release. Client teams consume that document for code generation instead of live introspection.

### 2. OpenAPI/Swagger Documentation

```bash
# Convert a checked-in GraphQL SDL document to OpenAPI
graphql-to-openapi \
  --input schema.graphql \
  --output api-docs.json
```

### 3. GraphQL Playground (Development Only)

In development, FraiseQL serves a GraphQL IDE so you can explore the schema interactively:

```python
from fraiseql.fastapi import create_fraiseql_app, FraiseQLConfig
from fraiseql.fastapi.config import IntrospectionPolicy

config = FraiseQLConfig(
    database_url="postgresql://localhost/fraiseql_db",
    environment="development",
    introspection_policy=IntrospectionPolicy.PUBLIC,
    enable_playground=True,           # GraphQL IDE enabled in development
    playground_tool="graphiql",       # or "apollo-sandbox"
)

app = create_fraiseql_app(
    database_url="postgresql://localhost/fraiseql_db",
    config=config,
    types=[User],
    queries=[users],
)
```

The playground is automatically disabled in production.

### 4. Markdown Documentation

Maintain hand-written documentation:

```markdown
# GraphQL API

## Query: users

Returns a list of users.

**Arguments:**
- `limit: Int!` - Maximum number of users
- `offset: Int` - Skip first N users

**Return Type:** `[User!]!`

**Example:**

    query {
      users(limit: 10) {
        id
        name
        email
      }
    }
```

---

## Conclusion

FraiseQL's three-tier introspection policy system provides flexible security for different deployment environments. By using DISABLED introspection in production and AUTHENTICATED or PUBLIC in development, you achieve both security (preventing schema reconnaissance) and usability (allowing development tools to function).

**Key Takeaways**:

- ✅ Use DISABLED in production (prevents schema exposure)
- ✅ Use AUTHENTICATED for trusted internal access (requires authentication)
- ✅ Use PUBLIC in development (full schema access)
- ✅ Use security profiles to choose bundled introspection settings
- ✅ Provide alternative documentation (SDL document, OpenAPI)
- ✅ Monitor introspection denial attempts via security logging
- ✅ Rate-limit introspection queries to prevent abuse

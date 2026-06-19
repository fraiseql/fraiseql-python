---

title: Configuration Guide
description: Complete configuration reference for FraiseQL security, networking, and operational settings.
keywords: []
tags: ["documentation", "reference"]
---

# Configuration Guide

Complete configuration reference for FraiseQL security, networking, and operational settings.

FraiseQL v1 is a Python runtime framework. Configuration is plain Python and environment
variables — there is **no `fraiseql.toml`** and **no compile step**. Settings are resolved
at app startup by `FraiseQLConfig`, a `pydantic-settings` model, and applied when you call
`create_fraiseql_app(...)`.

## Quick Navigation

### Security Configuration

- **[TLS/SSL Configuration](tls-configuration.md)** — Configure HTTPS and mutual TLS
- **[Rate Limiting](rate-limiting.md)** — Brute-force protection and request throttling

### Database Configuration

- **[PostgreSQL Authentication](postgresql-authentication.md)** — PostgreSQL connection and authentication

## Configuration Sources

FraiseQL reads settings from three places:

1. **`create_fraiseql_app(...)` keyword arguments** — passed directly in Python.
2. **A `FraiseQLConfig` instance** — a `pydantic-settings` model you can build and pass
   via `create_fraiseql_app(config=...)`.
3. **`FRAISEQL_`-prefixed environment variables** (and a `.env` file) — read automatically
   by `FraiseQLConfig` (`env_prefix="FRAISEQL_"`, `env_file=".env"`).

```python
import fraiseql
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

config = FraiseQLConfig(
    database_url="postgresql://user:pass@localhost/mydb",
)

app = create_fraiseql_app(
    config=config,
    types=[...],
    queries=[...],
    production=True,
)
```

## Environment Variables

`FraiseQLConfig` reads any `FRAISEQL_`-prefixed environment variable (or matching key in a
local `.env` file):

```bash
# Database
FRAISEQL_DATABASE_URL=postgresql://user:pass@localhost/db
FRAISEQL_DATABASE_POOL_SIZE=20
FRAISEQL_DATABASE_POOL_TIMEOUT=30

# Security
FRAISEQL_ENABLE_TLS=true
FRAISEQL_TLS_CERT=/path/to/cert.pem
FRAISEQL_TLS_KEY=/path/to/key.pem

# Rate Limiting
FRAISEQL_RATE_LIMIT_ENABLED=true
FRAISEQL_RATE_LIMIT_REQUESTS_PER_MINUTE=100
```

## Configuration Priority

Later sources win, so explicit code overrides ambient configuration:

1. **Defaults** — built into `FraiseQLConfig`.
2. **`FRAISEQL_` environment variables / `.env`** — override defaults (handy for secrets).
3. **A `FraiseQLConfig` instance** — overrides env-derived values you set explicitly.
4. **`create_fraiseql_app(...)` keyword arguments** — override everything else.

## Common Scenarios

### Production Setup

1. Enable TLS: [TLS Configuration](tls-configuration.md)
2. Set rate limits: [Rate Limiting](rate-limiting.md)
3. Configure the database connection: [PostgreSQL Authentication](postgresql-authentication.md)
4. Pass `production=True` to `create_fraiseql_app(...)` to disable the GraphQL playground

### Development Setup

1. Disable TLS (use HTTP)
2. Increase rate limits for testing
3. Use minimal security hardening
4. Local database connection, with `production=False` to enable the playground

### Enterprise Deployment

1. mTLS for service-to-service communication
2. Strict rate limiting
3. Security audit logging enabled
4. PostgreSQL connection hardening (`sslmode`, `pg_hba.conf`)

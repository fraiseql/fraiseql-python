---
title: FraiseQL Enterprise Features
description: Enterprise-grade security, compliance, and audit capabilities for production deployments.
keywords: []
tags: ["documentation", "reference"]
---

# FraiseQL Enterprise Features

Enterprise-grade runtime security hardening for production PostgreSQL deployments, including error sanitization, rate limiting, token protection, and encrypted state management.

---

## Runtime Security Features

All runtime security is configured at application startup through
[`FraiseQLConfig`](https://github.com/fraiseql/fraiseql-python/blob/main/src/fraiseql/fastapi/config.py) — a Pydantic
`BaseSettings` class — and/or `create_fraiseql_app(...)` keyword arguments.
Every setting can be overridden by an environment variable prefixed with
`FRAISEQL_` (for example `FRAISEQL_RATE_LIMIT_ENABLED`). There is no
configuration file: settings live in code, in `.env`, or in the process
environment.

```python
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

config = FraiseQLConfig(
    database_url="postgresql://user:pass@localhost/mydb",
    environment="production",
    rate_limit_enabled=True,
    complexity_enabled=True,
    revocation_enabled=True,
)

app = create_fraiseql_app(types=[...], queries=[...], config=config)
```

### Error Sanitization

**Hide implementation details from client errors**, preventing information
leakage. Setting `environment="production"` (or
`FRAISEQL_ENVIRONMENT=production`) switches FraiseQL into hardened mode:

- Clients receive generic error messages instead of SQL, stack traces, or
  internal identifiers.
- Full error detail is still written to server logs for debugging.
- Schema introspection is disabled and the GraphQL playground is turned off
  automatically in production.

```python
config = FraiseQLConfig(
    database_url="postgresql://user:pass@localhost/mydb",
    environment="production",  # masks internal error detail from clients
)
```

```bash
FRAISEQL_ENVIRONMENT=production
```

### Constant-Time Token Comparison

**Prevent timing attacks** on token validation:

- Token and credential comparisons use a constant-time algorithm.
- Verification duration is independent of where a mismatch occurs.
- Defends against brute-force inference via timing analysis.
- Applied automatically to all authentication tokens — no configuration
  needed.

### Token Revocation

**Invalidate compromised or logged-out tokens** before their natural
expiry. Revocation is enabled by default and tunable through `FraiseQLConfig`:

```python
config = FraiseQLConfig(
    database_url="postgresql://user:pass@localhost/mydb",
    revocation_enabled=True,
    revocation_check_enabled=True,
    revocation_ttl=86400,          # how long a revocation is retained (seconds)
    revocation_store_type="redis", # "memory" (default) or "redis"
)
```

```bash
FRAISEQL_REVOCATION_ENABLED=true
FRAISEQL_REVOCATION_CHECK_ENABLED=true
FRAISEQL_REVOCATION_TTL=86400
```

### Rate Limiting

**Brute-force and abuse protection** on the GraphQL endpoint:

- Per-minute and per-hour request ceilings.
- Burst allowance for short traffic spikes.
- Sliding or fixed time windows.
- Whitelist/blacklist of client identifiers.

```python
config = FraiseQLConfig(
    database_url="postgresql://user:pass@localhost/mydb",
    rate_limit_enabled=True,
    rate_limit_requests_per_minute=60,
    rate_limit_requests_per_hour=1000,
    rate_limit_burst_size=10,
    rate_limit_window_type="sliding",  # "sliding" or "fixed"
)
```

```bash
FRAISEQL_RATE_LIMIT_ENABLED=true
FRAISEQL_RATE_LIMIT_REQUESTS_PER_MINUTE=30   # stricter in production
FRAISEQL_RATE_LIMIT_REQUESTS_PER_HOUR=500
```

### Query Complexity Limits

**Reject expensive or abusive queries** before they reach PostgreSQL:

- Per-query complexity scoring with a configurable maximum.
- Maximum nesting depth enforcement.
- Optional per-field complexity multipliers.

```python
config = FraiseQLConfig(
    database_url="postgresql://user:pass@localhost/mydb",
    complexity_enabled=True,
    complexity_max_score=1000,
    complexity_max_depth=10,
)
```

```bash
FRAISEQL_COMPLEXITY_ENABLED=true
FRAISEQL_COMPLEXITY_MAX_SCORE=1000
FRAISEQL_COMPLEXITY_MAX_DEPTH=10
```

### Encrypted State and Audit Logging

**Tamper-evident audit trails** with HMAC signatures track authentication
events and data mutations. Audit logging is implemented as a PostgreSQL
pattern (immutable log tables plus HMAC signature chains) and is documented in
detail in [audit-logging.md](./audit-logging.md). OAuth state and other
sensitive parameters are encrypted before transmission so they cannot be
inspected or tampered with in transit.

### Configuration Summary

| Concern | `FraiseQLConfig` field(s) | Environment variable |
|---------|---------------------------|----------------------|
| Error sanitization | `environment="production"` | `FRAISEQL_ENVIRONMENT` |
| Token revocation | `revocation_enabled`, `revocation_check_enabled`, `revocation_ttl`, `revocation_store_type` | `FRAISEQL_REVOCATION_*` |
| Rate limiting | `rate_limit_enabled`, `rate_limit_requests_per_minute`, `rate_limit_requests_per_hour`, `rate_limit_burst_size`, `rate_limit_window_type` | `FRAISEQL_RATE_LIMIT_*` |
| Query complexity | `complexity_enabled`, `complexity_max_score`, `complexity_max_depth` | `FRAISEQL_COMPLEXITY_*` |
| Introspection control | `introspection_policy` | `FRAISEQL_INTROSPECTION_POLICY` |
| CORS | `cors_enabled`, `cors_origins` | `FRAISEQL_CORS_*` |
| Authentication | `auth_enabled`, `auth_provider` | `FRAISEQL_AUTH_*` |

Constant-time token comparison applies automatically and has no configuration
flag. See the full field list and defaults in
[`src/fraiseql/fastapi/config.py`](https://github.com/fraiseql/fraiseql-python/blob/main/src/fraiseql/fastapi/config.py).

---

## Enterprise Features Overview

### Access Control

| Document | Description |
|----------|-------------|
| [rbac.md](./rbac.md) | Role-Based Access Control |

**Topics covered:**

- Hierarchical role system
- Field-level permissions
- PostgreSQL Row-Level Security (RLS)
- Authorization enforcement via `Authorizer` and `@fraiseql.query(authorizer=...)`
- JWT claims integration
- Dynamic role assignment

---

### Audit & Compliance

| Document | Description |
|----------|-------------|
| [audit-logging.md](./audit-logging.md) | Cryptographic audit trails |

**Topics covered:**

- Immutable audit log tables
- HMAC signature chains
- Tamper detection
- Audit columns (`created_at`, `updated_at`, `deleted_at`)
- Compliance with GDPR, SOC 2, NIS2
- Retention policies

---

### Data Protection

| Document | Description |
|----------|-------------|
| [kms.md](./kms.md) | Key Management Service integration |

**Topics covered:**

- Field-level encryption
- AWS KMS integration
- Azure Key Vault integration
- Google Cloud KMS integration
- Key rotation strategies
- Encryption at rest and in transit

---

## Quick Start

**For security engineers:**

1. Read [rbac.md](./rbac.md) for access control design.
2. Review [audit-logging.md](./audit-logging.md) for compliance requirements.
3. Configure [kms.md](./kms.md) for data encryption.

**For compliance teams:**

1. Start with [audit-logging.md](./audit-logging.md).
2. Review security profiles in [Specs: Security Compliance](../specs/security-compliance.md).
3. Understand RBAC enforcement in [rbac.md](./rbac.md).

---

## Related Documentation

- **[Security Model](../architecture/security/security-model.md)** — Security model and authentication.
- **[Specs: Security Compliance](../specs/security-compliance.md)** — Security profiles (STANDARD, REGULATED, RESTRICTED).
- **[Guides: Production Deployment](../guides/production-deployment.md)** — Security hardening checklist.

---

## Compliance Standards Supported

- **GDPR** — Data protection and privacy.
- **SOC 2** — Security, availability, confidentiality.
- **NIS2** — EU cybersecurity directive.
- **HIPAA** — Healthcare data protection (with proper configuration).
- **PCI DSS** — Payment card data security (with proper configuration).

---

**Back to:** [Documentation Home](../index.md)
</content>
</invoke>

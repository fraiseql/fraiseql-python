---
title: PostgreSQL Authentication Guide
description: How FraiseQL connects to PostgreSQL securely using SCRAM-based authentication. This guide covers PostgreSQL connection authentication methods, pg_hba.conf, and version requirements.
keywords: []
tags: ["documentation", "reference"]
---

# PostgreSQL Authentication Guide

FraiseQL connects to PostgreSQL through psycopg (the libpq-based driver). Authentication to the database is handled by PostgreSQL itself — FraiseQL does not implement its own wire-protocol authentication. This guide covers how to configure PostgreSQL for secure SCRAM-based authentication and how FraiseQL's connection string negotiates it.

When FraiseQL opens a connection, the psycopg/libpq client and the PostgreSQL server negotiate the authentication method dictated by `pg_hba.conf` (typically `scram-sha-256`). You configure the credentials and TLS settings in your `database_url`; everything else happens in PostgreSQL.

## Prerequisites

**Required Knowledge:**

- PostgreSQL user and role management
- SCRAM authentication protocol basics
- SSL/TLS certificate handling
- Connection string/URI syntax
- Database permissions and privilege models
- Linux/Unix command-line tools (psql, openssl)

**Required Software:**

- FraiseQL (current release)
- PostgreSQL 10+ (for SCRAM-SHA-256 support)
- psql command-line client (usually included with PostgreSQL)
- OpenSSL 1.1.1+ (for certificate generation)
- A text editor for configuration files

**Required Infrastructure:**

- PostgreSQL 10 or later instance (local or remote)
- PostgreSQL superuser or admin account for user creation
- The host running your FraiseQL FastAPI application
- Network connectivity between FraiseQL and PostgreSQL
- For TLS: PostgreSQL compiled with SSL support

**Optional but Recommended:**

- PostgreSQL HA solution (replication, failover)
- Connection pooling (pgBouncer, PgPool)
- Secrets management system (Vault, AWS Secrets Manager)
- Monitoring tools (pg_stat_statements, pg_stat_monitor)
- Audit logging for authentication events

**Time Estimate:** 20-40 minutes for basic setup, 1-2 hours for production TLS setup

## Overview

PostgreSQL connection authentication uses the SCRAM (Salted Challenge Response Authentication Mechanism) family of protocols. These are cryptographically secure alternatives to older MD5-based authentication.

FraiseQL itself does not choose the authentication method — the PostgreSQL server's `pg_hba.conf` does. The psycopg/libpq client transparently performs SCRAM-SHA-256 (or MD5, or channel binding) on FraiseQL's behalf based on the `database_url` you provide. Your job is to:

1. Configure PostgreSQL to require SCRAM (`password_encryption = scram-sha-256`).
2. Create a least-privilege role for FraiseQL.
3. Point FraiseQL at it with a connection URL (and TLS settings).

## Supported Authentication Methods

### SCRAM-SHA-256 (Recommended)

**Status**: Recommended for production

SCRAM-SHA-256 is a salted challenge-response authentication mechanism defined in RFC 5802. It provides:

- Cryptographic security (SHA-256)
- Protection against rainbow table attacks (salt-based)
- No plaintext password transmission
- Defense against MitM attacks

**Requirements**:

- PostgreSQL 10 or later
- User password must be stored using SCRAM-SHA-256
- `pg_hba.conf` entry using the `scram-sha-256` auth method

**Configuration**:

Pass the connection URL to FraiseQL via the `database_url` argument or the `FRAISEQL_DATABASE_URL` environment variable. psycopg/libpq negotiates SCRAM-SHA-256 automatically:

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://fraiseql_user:secure_password@localhost:5432/mydb",
    types=[...],
    queries=[...],
)
```

Or via environment variable:

```bash
export FRAISEQL_DATABASE_URL="postgresql://fraiseql_user:secure_password@localhost:5432/mydb"
```

### SCRAM-SHA-256-PLUS (Channel Binding)

**Status**: Best for highly sensitive deployments

SCRAM-SHA-256-PLUS adds channel binding to SCRAM-SHA-256, providing additional protection by binding the authentication to the TLS connection itself. With a TLS connection, libpq negotiates channel binding automatically when both client and server support it.

**Requirements**:

- PostgreSQL 11 or later
- TLS connection required
- Channel binding support in libpq (PostgreSQL 11+ client libraries)

**When to use**:

- Multi-tenant deployments
- Highly sensitive data
- High-security compliance requirements (SOC2, ISO 27001)

**Configuration**:

Require TLS by adding `sslmode=require` (or stronger) to the connection URL:

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://fraiseql_user:secure_password@localhost:5432/mydb?sslmode=require",
    types=[...],
    queries=[...],
)
```

## PostgreSQL Version Requirements

| Version | SCRAM-SHA-256 | SCRAM-SHA-256-PLUS | Notes |
|---------|---------------|--------------------|-------|
| < 10    | Not supported | Not supported | **Upgrade required** - MD5 only |
| 10-10.x | Supported | Not supported | Minimum version for SCRAM |
| 11+     | Supported | Supported | **Recommended** |
| 12+     | Supported | Supported | Current stable branch |
| 13+     | Supported | Supported | Current stable branch |
| 14+     | Supported | Supported | Current stable branch |
| 15+     | Supported | Supported | Current stable branch |
| 16+     | Supported | Supported | Current stable branch |
| 17+     | Supported | Supported | Current stable branch |

## Migration from MD5

If you're currently using older PostgreSQL versions with MD5 authentication, follow these migration steps:

### Step 1: Upgrade PostgreSQL

Upgrade to PostgreSQL 10 or later:

```bash
# Check current version
psql --version

# For Ubuntu/Debian
sudo apt-get update
sudo apt-get install postgresql-11  # or newer version

# For macOS with Homebrew
brew upgrade postgresql
```

### Step 2: Configure SCRAM Authentication

Update PostgreSQL configuration to enforce SCRAM.

**PostgreSQL Server Configuration** (`postgresql.conf`):

```ini
# Enforce SCRAM for all new password hashes
password_encryption = scram-sha-256
```

**Host-Based Authentication** (`pg_hba.conf`) — set the auth method to `scram-sha-256` for the FraiseQL connections:

```conf
# TYPE  DATABASE   USER            ADDRESS         METHOD
host    mydb       fraiseql_user   0.0.0.0/0       scram-sha-256
hostssl mydb       fraiseql_user   0.0.0.0/0       scram-sha-256
```

Reload PostgreSQL after editing `pg_hba.conf`:

```bash
sudo systemctl reload postgresql
# or, from psql:
# SELECT pg_reload_conf();
```

### Step 3: Reset User Passwords

PostgreSQL stores password hashes. Existing passwords hashed under MD5 are not automatically re-hashed — you must set the password again after enabling `scram-sha-256` so a new SCRAM hash is created:

```sql
-- Reset password for FraiseQL user (creates a SCRAM-SHA-256 hash)
ALTER USER fraiseql_user WITH PASSWORD 'new_secure_password';

-- For new users, this is automatic with password_encryption = scram-sha-256
CREATE USER fraiseql_user WITH PASSWORD 'secure_password';
```

### Step 4: Update the Connection URL

Point FraiseQL at the database with the new credentials. Set it via the `FRAISEQL_DATABASE_URL` environment variable or pass it to `create_fraiseql_app(database_url=...)`:

```bash
# Old (MD5 - deprecated)
# FRAISEQL_DATABASE_URL="postgresql://fraiseql_user:password@localhost:5432/mydb"

# New (SCRAM-SHA-256 negotiated automatically by psycopg/libpq)
export FRAISEQL_DATABASE_URL="postgresql://fraiseql_user:secure_password@localhost:5432/mydb"
```

No code change is required to switch from MD5 to SCRAM — the negotiation is handled by the client library based on `pg_hba.conf`.

## Verifying SCRAM Authentication

### Check PostgreSQL Server Configuration

```sql
-- Check password encryption method
SHOW password_encryption;
-- Should output: scram-sha-256

-- Check authentication method in pg_hba.conf
SELECT * FROM pg_hba_file_rules WHERE auth_method LIKE 'scram%';
```

### Check User Authentication Method

```sql
-- Check a specific user (only visible to superusers)
SELECT usename, usesuper FROM pg_user WHERE usename = 'fraiseql_user';

-- The password is stored as a SCRAM hash, not MD5
SELECT substring(rolpassword, 1, 13) AS hash_prefix
FROM pg_authid WHERE rolname = 'fraiseql_user';
-- Should start with "SCRAM-SHA-256" not "md5"
```

### Test the Connection

Use `psql` with the same credentials FraiseQL will use to confirm SCRAM negotiation succeeds before starting the app:

```bash
# Connect as the FraiseQL role
psql "postgresql://fraiseql_user:secure_password@localhost:5432/mydb"
# A successful connection means SCRAM-SHA-256 was negotiated per pg_hba.conf
```

You can also start the FraiseQL FastAPI app and confirm it connects:

```bash
# Run the FastAPI app (uvicorn). A successful startup means the pool
# authenticated to PostgreSQL via SCRAM-SHA-256.
uvicorn app:app --host 0.0.0.0 --port 8000
```

## Troubleshooting

### "FATAL: password authentication failed for user"

**Cause**: Password mismatch or authentication method incompatibility

**Solution**:

1. Verify the password in your `database_url` is correct
2. Check PostgreSQL server is using SCRAM: `SHOW password_encryption;`
3. Reset the password: `ALTER USER fraiseql_user WITH PASSWORD 'password';`
4. Verify the connection URL format

### "SCRAM authentication required but not available"

**Cause**: PostgreSQL version < 10, MD5-only configuration, or a stale MD5 password hash

**Solution**:

1. Upgrade PostgreSQL to 10+
2. Update `password_encryption` in `postgresql.conf`
3. Reload PostgreSQL: `sudo systemctl reload postgresql`
4. Re-set passwords so SCRAM hashes are generated for all roles

### "SCRAM-SHA-256-PLUS not supported"

**Cause**: PostgreSQL version < 11 or TLS not configured

**Solution**:

1. For SCRAM-SHA-256-PLUS, upgrade to PostgreSQL 11+
2. Enable TLS: add `sslmode=require` to the connection URL
3. Verify TLS certificates are valid
4. Check PostgreSQL was compiled with OpenSSL support: `SELECT setting FROM pg_settings WHERE name = 'ssl';`

## Best Practices

1. **Always use SCRAM**: Migrate away from MD5 authentication
2. **Use Strong Passwords**: Generate cryptographically random passwords (16+ characters)
3. **Enable TLS**: Always encrypt the connection wire (`sslmode=require` or stronger)
4. **Separate Credentials**: Use a dedicated, least-privilege PostgreSQL role for FraiseQL
5. **Rotate Passwords**: Rotate database passwords regularly (quarterly or as per policy)
6. **Monitor Authentication**: Monitor failed authentication attempts in PostgreSQL logs
7. **Use Secrets Management**: Store the `database_url` / password in a secrets manager, not in plaintext config

## Example: Complete Setup

```bash
#!/bin/bash
# Complete PostgreSQL SCRAM setup for FraiseQL

# 1. Connect as PostgreSQL superuser
sudo -u postgres psql
```

In `psql`:

```sql
-- Enable SCRAM for future password changes
ALTER SYSTEM SET password_encryption = 'scram-sha-256';

-- Create a dedicated, least-privilege FraiseQL role
CREATE USER fraiseql_user WITH PASSWORD 'your_secure_password_here';

-- Grant only the privileges FraiseQL needs.
-- Reads happen through v_/tv_ views; writes happen through fn_ functions.
GRANT CONNECT ON DATABASE mydb TO fraiseql_user;
GRANT USAGE ON SCHEMA public TO fraiseql_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO fraiseql_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO fraiseql_user;

-- Reload configuration
SELECT pg_reload_conf();
```

```bash
# Exit psql (\q), then restart PostgreSQL to apply ALTER SYSTEM
sudo systemctl restart postgresql

# 2. Verify SCRAM is enabled
sudo -u postgres psql -c "SHOW password_encryption;"
# Should output: scram-sha-256

# 3. Test the connection with the FraiseQL credentials
psql "postgresql://fraiseql_user:your_secure_password_here@localhost:5432/mydb"
# Should authenticate via SCRAM-SHA-256

# 4. Point FraiseQL at the database
export FRAISEQL_DATABASE_URL="postgresql://fraiseql_user:your_secure_password_here@localhost:5432/mydb"
```

## Security Implications

| Aspect | MD5 (Deprecated) | SCRAM-SHA-256 | SCRAM-SHA-256-PLUS |
|--------|------------------|---------------|--------------------|
| **Cryptographic Strength** | Weak (broken) | Strong | Strong |
| **Salt Protection** | None | Per-user | Per-user |
| **Rainbow Table Resistant** | No | Yes | Yes |
| **Channel Binding** | N/A | None | TLS-bound |
| **MitM Protection** | Low | Medium | High |
| **Recommended** | Never | Production | Sensitive |

## References

- [PostgreSQL Authentication Documentation](https://www.postgresql.org/docs/current/auth-methods.html)
- [PostgreSQL pg_hba.conf](https://www.postgresql.org/docs/current/auth-pg-hba-conf.html)
- [RFC 5802 - SCRAM](https://tools.ietf.org/html/rfc5802)
- [PostgreSQL password_encryption Parameter](https://www.postgresql.org/docs/current/runtime-config-connection.html#GUC-PASSWORD-ENCRYPTION)
- [psycopg Connection Strings](https://www.psycopg.org/psycopg3/docs/api/connections.html)

## Support Matrix

| Component | PostgreSQL 10 | PostgreSQL 11+ | Notes |
|-----------|---------------|----------------|-------|
| FraiseQL Core | Supported | Recommended | Min version for SCRAM |
| SCRAM-SHA-256 | Yes | Yes | Recommended auth |
| SCRAM-SHA-256-PLUS | No | Yes | Best security |
| Connection Pooling | Yes | Yes | Via pgBouncer |
| Replication | Yes | Yes | Streaming replication |

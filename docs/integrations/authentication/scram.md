---
title: PostgreSQL SCRAM Authentication
description: Secure the FraiseQL-to-PostgreSQL database connection with SCRAM-SHA-256, PostgreSQL's modern challenge-response password authentication.
keywords: ["database", "authentication", "postgresql", "scram", "security"]
tags: ["documentation", "reference"]
---

# PostgreSQL SCRAM Authentication

SCRAM-SHA-256 is PostgreSQL's modern, secure password authentication method. It
replaces the older, vulnerable MD5 scheme. FraiseQL connects to PostgreSQL with
[psycopg](https://www.psycopg.org/) (libpq), which negotiates SCRAM-SHA-256 with
the server automatically — there is no FraiseQL-specific code or configuration
involved.

> **Database auth, not application auth.** This page is about authenticating
> *FraiseQL's own connection to PostgreSQL*. It is unrelated to authenticating
> your API's end users (JWT / Auth0 / custom providers) — for that, see
> [Authentication overview](./README.md).

## Overview

SCRAM (Salted Challenge Response Authentication Mechanism) lets the psycopg
client prove it knows the database role's password without ever sending the
password in plaintext. Configuration is entirely on the **PostgreSQL side**
(`postgresql.conf`, `pg_hba.conf`, role passwords); FraiseQL only needs a valid
`database_url`.

| Method | RFC | PostgreSQL | Channel binding |
|--------|-----|-----------|-----------------|
| **SCRAM-SHA-256** | [RFC 5802](https://datatracker.ietf.org/doc/html/rfc5802) | 10+ | No |
| **SCRAM-SHA-256-PLUS** | [RFC 5802](https://datatracker.ietf.org/doc/html/rfc5802) | 11+ (with TLS) | Yes |

## PostgreSQL side

### 1. Enable SCRAM password encryption

Set `password_encryption` so PostgreSQL stores password hashes in SCRAM format:

```sql
-- Check the current setting
SHOW password_encryption;
-- Want: scram-sha-256  (md5 is deprecated)

-- Enable SCRAM-SHA-256 (postgresql.conf, or via ALTER SYSTEM)
ALTER SYSTEM SET password_encryption = 'scram-sha-256';
SELECT pg_reload_conf();
```

This only governs *newly set* passwords. Existing roles keep their old hashes
until their passwords are reset (see step 3).

### 2. Require SCRAM in `pg_hba.conf`

`pg_hba.conf` decides the authentication method per connection. Use
`scram-sha-256` for the host/database/role FraiseQL connects as:

```text
# TYPE  DATABASE   USER             ADDRESS         METHOD
host    mydb       fraiseql_user    10.0.0.0/24     scram-sha-256
hostssl mydb       fraiseql_user    0.0.0.0/0       scram-sha-256
```

Reload after editing:

```sql
SELECT pg_reload_conf();
```

Use `hostssl` to additionally require TLS for that connection (recommended — see
[Recommend TLS alongside SCRAM](#recommend-tls-alongside-scram)).

### 3. Create roles with SCRAM-hashed passwords

With `password_encryption = scram-sha-256` active, any password you set is stored
as a SCRAM verifier:

```sql
-- New role
CREATE ROLE fraiseql_user LOGIN PASSWORD 'a-long-random-password';

-- Re-hash an existing role's password (also use \password in psql, which
-- never echoes the password into history or logs)
ALTER ROLE fraiseql_user PASSWORD 'a-long-random-password';
```

In `psql`, prefer the `\password` meta-command — it prompts interactively and
rehashes using the server's current `password_encryption`:

```text
\password fraiseql_user
```

### 4. Verify the role uses SCRAM

```sql
-- The stored verifier should begin with SCRAM-SHA-256$
SELECT rolname, rolpassword
FROM pg_authid
WHERE rolname = 'fraiseql_user';
-- e.g. SCRAM-SHA-256$4096:...   (not md5...)
```

## FraiseQL / client side

FraiseQL connects through psycopg using a standard `database_url`. SCRAM is
negotiated by libpq automatically; you do not write or configure any
authentication code in FraiseQL.

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://fraiseql_user:password@db.internal:5432/mydb",
    types=[...],
    queries=[...],
)
```

If `psql` with the same URL connects successfully against a SCRAM-configured
server, FraiseQL will too — the negotiation is identical.

Keep credentials out of source control. Pass the URL via an environment variable
(FraiseQL also reads `FRAISEQL_DATABASE_URL`):

```bash
export FRAISEQL_DATABASE_URL="postgresql://fraiseql_user:$(vault kv get -field=password secret/fraiseql/db)@db.internal:5432/mydb"
```

## Recommend TLS alongside SCRAM

SCRAM protects the *password*, but on its own it does not encrypt query traffic
or authenticate the server. Add TLS for both:

```python
app = create_fraiseql_app(
    database_url=(
        "postgresql://fraiseql_user:password@db.internal:5432/mydb"
        "?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca.crt"
    ),
    types=[...],
    queries=[...],
)
```

- `sslmode=verify-full` encrypts the connection **and** verifies the server's
  certificate against `sslrootcert` (preventing MITM). Use this in production.
- On PostgreSQL 11+, a TLS connection enables **SCRAM-SHA-256-PLUS** channel
  binding, which ties authentication to the TLS session and defeats relay
  attacks. libpq selects it automatically when both ends support it.
- Pair `sslmode=verify-full` with `hostssl ... scram-sha-256` lines in
  `pg_hba.conf` so the server rejects any non-TLS or non-SCRAM attempt.

## Migrating from MD5

If existing roles still use MD5:

```sql
-- 1. Switch the default to SCRAM
ALTER SYSTEM SET password_encryption = 'scram-sha-256';
SELECT pg_reload_conf();

-- 2. Re-hash each role by resetting its password
ALTER ROLE fraiseql_user PASSWORD 'a-long-random-password';

-- 3. Confirm the verifier is now SCRAM
SELECT rolname, rolpassword FROM pg_authid WHERE rolname = 'fraiseql_user';
```

Then change the `pg_hba.conf` method from `md5` to `scram-sha-256` and
`SELECT pg_reload_conf();`. FraiseQL needs no changes unless the password itself
changed — in which case update the `database_url`.

## Troubleshooting

**"SCRAM authentication failed" / "password authentication failed"**
Test the exact URL with `psql` first — FraiseQL uses the same negotiation:

```bash
psql "postgresql://fraiseql_user:password@db.internal:5432/mydb"
```

If `psql` also fails, the cause is on the PostgreSQL side (wrong password, role
missing, role still on MD5, or a `pg_hba.conf` line that does not match). Check
that the role's verifier starts with `SCRAM-SHA-256$` (step 4) and that
`pg_hba.conf` uses `scram-sha-256` for that host/database/user.

**Server still negotiates MD5**
The role's password was set before `password_encryption` was switched. Re-run
`ALTER ROLE ... PASSWORD ...` to rehash it.

**"connection refused"**
PostgreSQL is not reachable — check that it is running, that it listens on the
expected interface (`listen_addresses`), and that no firewall blocks port 5432.
This is a connectivity issue, not an authentication one.

## Security best practices

1. Set `password_encryption = scram-sha-256` and use `scram-sha-256` lines in
   `pg_hba.conf` for every FraiseQL connection; remove any `md5`/`trust` lines.
2. Require TLS with `sslmode=verify-full` so SCRAM-SHA-256-PLUS channel binding
   is used and traffic is encrypted.
3. Give FraiseQL a dedicated, least-privileged database role.
4. Use a long, unique, randomly generated password and rotate it periodically.
5. Keep the `database_url` in an environment variable or secrets manager, never
   in source control.
6. Monitor PostgreSQL logs for repeated authentication failures.

## References

- [PostgreSQL: Password Authentication (SCRAM)](https://www.postgresql.org/docs/current/auth-password.html)
- [PostgreSQL: The pg_hba.conf File](https://www.postgresql.org/docs/current/auth-pg-hba-conf.html)
- [PostgreSQL: SSL Support (libpq sslmode)](https://www.postgresql.org/docs/current/libpq-ssl.html)
- [RFC 5802: SCRAM](https://datatracker.ietf.org/doc/html/rfc5802)
- [Authentication overview (application/user auth)](./README.md)

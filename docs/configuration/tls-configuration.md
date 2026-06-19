---

title: TLS/SSL Configuration Guide
description: - SSL/TLS fundamentals (certificates, keys, handshakes)
keywords: []
tags: ["documentation", "reference"]
---

# TLS/SSL Configuration Guide

FraiseQL v1 is a Python runtime GraphQL framework that runs as a **FastAPI/ASGI
application** in front of **PostgreSQL**. It does not ship its own HTTPS server,
and there is no `[tls]` configuration block to set. Instead, TLS is handled at
two distinct, independent surfaces:

1. **App ↔ client TLS (inbound HTTPS).** Your FraiseQL app is served by an ASGI
   server such as `uvicorn` or `gunicorn`. In production, inbound TLS is normally
   terminated by a **reverse proxy** (nginx, Caddy, Traefik, or a cloud load
   balancer) in front of the app. For local/simple deployments, `uvicorn` can
   terminate TLS directly via `--ssl-certfile` / `--ssl-keyfile`.

2. **App ↔ PostgreSQL TLS.** The application's connection to PostgreSQL is
   encrypted through the `database_url` connection string (or
   `FRAISEQL_DATABASE_URL`) using libpq/psycopg `sslmode` parameters such as
   `?sslmode=verify-full&sslrootcert=...`. No FraiseQL code is involved — the
   PostgreSQL driver negotiates TLS.

This guide covers both surfaces, plus certificate management that applies to either.

## Prerequisites

**Required Knowledge:**

- SSL/TLS fundamentals (certificates, keys, handshakes)
- X.509 certificate structure and standards
- Public Key Infrastructure (PKI) concepts
- OpenSSL command-line tools
- DNS and certificate CN/SAN matching
- Basic Linux/Unix system administration

**Required Software:**

- A FraiseQL v1 application (FastAPI app built with `create_fraiseql_app`)
- An ASGI server: `uvicorn` (or `gunicorn` with `uvicorn` workers)
- A reverse proxy for production TLS termination (nginx, Caddy, Traefik) — optional for local
- OpenSSL 1.1.1+ (for certificate generation and verification)
- curl or OpenSSL CLI (for testing HTTPS endpoints)
- A code editor for configuration files
- Bash or similar shell for scripting

**Required Infrastructure:**

- A running FraiseQL app instance (local or deployed)
- TLS certificate and private key (self-signed or from a CA) for inbound HTTPS
- PostgreSQL 12+ with TLS (SSL) enabled, for encrypted database connections

**Optional but Recommended:**

- Certificate Authority (CA) certificate for client validation (mTLS)
- Let's Encrypt or other automated certificate provisioning
- HSM (Hardware Security Module) for key storage
- Certificate management tools (cert-manager for Kubernetes)
- nginx, Caddy, or Traefik reverse proxy with SSL termination

**Time Estimate:** 30-60 minutes for basic setup, 2-3 hours for mTLS in production

## Overview

There are two TLS surfaces to secure, and FraiseQL configures neither with a
custom config block:

1. **Inbound HTTPS (app ↔ client)** — terminated by a reverse proxy or by
   `uvicorn`'s built-in SSL flags. Optionally enforce **mutual TLS (mTLS)** at the
   proxy by requiring client certificates.
2. **PostgreSQL connection TLS (app ↔ database)** — driven entirely by the
   `sslmode` / `sslrootcert` parameters in your `database_url`.

The sections below show real options for each.

## Quick Start: Production Setup

### 1. Generate a TLS Certificate and Key (inbound HTTPS)

For production, prefer a certificate from a trusted CA (e.g. Let's Encrypt). For
local testing, you can self-sign with OpenSSL:

```bash
# Generate private key
openssl genrsa -out /etc/fraiseql/key.pem 2048

# Generate self-signed certificate (or use your CA)
openssl req -new -x509 -key /etc/fraiseql/key.pem -out /etc/fraiseql/cert.pem \
  -subj "/CN=api.example.com/O=YourOrg/C=US"

# Set proper permissions
chmod 600 /etc/fraiseql/key.pem
chmod 644 /etc/fraiseql/cert.pem
```

### 2. Terminate TLS in front of the FraiseQL app

You have two common choices. Pick one.

**Option A — Reverse proxy terminates TLS (recommended for production).** Run the
FraiseQL app on plain HTTP behind nginx/Caddy/Traefik or a cloud load balancer,
which holds the certificate and terminates TLS:

```bash
# Run the FraiseQL FastAPI app on localhost (HTTP); the proxy faces the internet
uvicorn app:app --host 127.0.0.1 --port 8000
```

Example nginx server block doing TLS termination and proxying to the app:

```text
server {
    listen 443 ssl;
    http2 on;
    server_name api.example.com;

    ssl_certificate     /etc/fraiseql/cert.pem;
    ssl_certificate_key /etc/fraiseql/key.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

**Option B — uvicorn terminates TLS directly (simple deployments).** Pass the
certificate and key to `uvicorn`; no proxy required:

```bash
uvicorn app:app \
  --host 0.0.0.0 --port 8443 \
  --ssl-certfile /etc/fraiseql/cert.pem \
  --ssl-keyfile /etc/fraiseql/key.pem
```

`gunicorn` with `uvicorn` workers accepts the equivalent `--certfile` /
`--keyfile` options if you run that stack.

### 3. Encrypt the PostgreSQL connection (app ↔ database)

Add the `sslmode` parameter to the `database_url` you pass to
`create_fraiseql_app(...)` (or set `FRAISEQL_DATABASE_URL`). libpq/psycopg
negotiates TLS — there is nothing to configure inside FraiseQL:

```python
import fraiseql
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url=(
        "postgresql://user:pass@db.example.com/mydb"
        "?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca.pem"
    ),
    types=[User],
    queries=[users, user],
    mutations=[create_user],
    production=True,
)
```

Or via environment variable (read by `FraiseQLConfig`):

```bash
export FRAISEQL_DATABASE_URL="postgresql://user:pass@db.example.com/mydb?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca.pem"
uvicorn app:app --host 127.0.0.1 --port 8000
```

## Configuration Options

### Inbound HTTPS (app ↔ client)

FraiseQL has **no built-in HTTPS server config** — these options belong to your
ASGI server or reverse proxy, not to FraiseQL.

| Where | Option | Description |
|-------|--------|-------------|
| uvicorn | `--ssl-certfile` | Path to the PEM certificate file |
| uvicorn | `--ssl-keyfile` | Path to the PEM private key file |
| uvicorn | `--ssl-keyfile-password` | Password for an encrypted key file (if any) |
| gunicorn | `--certfile` / `--keyfile` | Equivalent options for the gunicorn server |
| nginx | `ssl_certificate` / `ssl_certificate_key` | Certificate and key at the proxy |
| nginx | `ssl_protocols` | Minimum/allowed TLS versions, e.g. `TLSv1.2 TLSv1.3` |
| nginx | `ssl_client_certificate` + `ssl_verify_client on` | Require client certs (mTLS) |
| Caddy | automatic HTTPS | Caddy provisions and renews certs automatically |

When TLS is terminated by a proxy, run the app with `--proxy-headers` (and an
appropriate `--forwarded-allow-ips`) so it trusts `X-Forwarded-Proto` and serves
correct absolute URLs.

### PostgreSQL connection TLS (app ↔ database)

Set these in the `database_url` query string; libpq/psycopg consumes them.

| Parameter | Description |
|-----------|-------------|
| `sslmode` | `disable`, `allow`, `prefer`, `require`, `verify-ca`, or `verify-full` |
| `sslrootcert` | Path to the CA certificate used to verify the server (for `verify-ca`/`verify-full`) |
| `sslcert` | Client certificate path (for PostgreSQL client-certificate auth) |
| `sslkey` | Client private key path (for PostgreSQL client-certificate auth) |

## Configuration Examples

### Example 1: Development (Permissive)

Plain HTTP locally, TLS preferred but not required for the database:

```bash
# No inbound TLS; uvicorn serves HTTP for local development
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

```python
app = create_fraiseql_app(
    database_url="postgresql://user:pass@localhost:5432/mydb?sslmode=prefer",
    types=[User],
    queries=[users],
    production=False,  # enables the GraphQL playground
)
```

### Example 2: Staging (Standard)

Reverse proxy terminates HTTPS; database connection requires TLS:

```text
# nginx (staging) — TLS termination, proxy to the FraiseQL app
server {
    listen 443 ssl;
    server_name staging.example.com;
    ssl_certificate     /etc/fraiseql/cert.pem;
    ssl_certificate_key /etc/fraiseql/key.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    location / { proxy_pass http://127.0.0.1:8000; }
}
```

```python
app = create_fraiseql_app(
    database_url="postgresql://user:pass@db.internal:5432/mydb?sslmode=require",
    types=[User],
    queries=[users],
    production=True,
)
```

### Example 3: Production (Strict, with mTLS at the proxy)

TLS 1.3 only at the proxy, client certificates required (mTLS enforced by nginx),
and `verify-full` for the database:

```text
# nginx (production) — TLS 1.3 + mutual TLS (client certificates required)
server {
    listen 443 ssl;
    http2 on;
    server_name api.example.com;

    ssl_certificate     /etc/fraiseql/server-cert.pem;
    ssl_certificate_key /etc/fraiseql/server-key.pem;
    ssl_protocols       TLSv1.3;

    # Mutual TLS: require and verify client certificates
    ssl_client_certificate /etc/fraiseql/client-ca.pem;
    ssl_verify_client      on;

    location / {
        proxy_pass        http://127.0.0.1:8000;
        proxy_set_header  X-Forwarded-Proto $scheme;
        proxy_set_header  X-SSL-Client-Verify $ssl_client_verify;
    }
}
```

```python
app = create_fraiseql_app(
    database_url=(
        "postgresql://user:pass@db.internal:5432/mydb"
        "?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-bundle.crt"
    ),
    types=[User],
    queries=[users],
    mutations=[create_user],
    production=True,
)
```

## TLS Enforcement Levels

There is no FraiseQL enforcement API — you choose a posture at the proxy/ASGI
server and the database connection string. Three common profiles:

### 1. Permissive (Development)

- Inbound TLS optional (plain HTTP via `uvicorn` locally)
- Client certificates not required
- Database `sslmode=prefer`

**Usage**: Local development, testing.

### 2. Standard (Production)

- Inbound TLS required (HTTPS only), terminated by the reverse proxy with
  `ssl_protocols TLSv1.2 TLSv1.3`
- Client certificates optional
- Database `sslmode=require`

**Usage**: Default production setup.

### 3. Strict (Regulated Environments)

- Inbound TLS required, TLS 1.3 only (`ssl_protocols TLSv1.3`)
- Mutual TLS required (`ssl_verify_client on` at the proxy)
- Database `sslmode=verify-full`

**Usage**: PCI-DSS, HIPAA, SOC 2 compliance.

## PostgreSQL SSL Modes

PostgreSQL connections (via libpq/psycopg) support all standard SSL modes:

| Mode | Security | Behavior |
|------|----------|----------|
| `disable` | ❌ Unsafe | No SSL, unencrypted |
| `allow` | ⚠️ Moderate | Upgrade to SSL if available |
| `prefer` | ⚠️ Moderate | Try SSL first, fall back to unencrypted |
| `require` | ✅ Good | SSL required, no fallback |
| `verify-ca` | ✅ Better | SSL + verify CA certificate |
| `verify-full` | ✅ Best | SSL + verify CA and hostname |

**Recommendation for production**: Use `require`, or `verify-full` when you can
provide a CA certificate.

## Database URLs with TLS

The `database_url` (passed to `create_fraiseql_app` or set as
`FRAISEQL_DATABASE_URL`) carries all PostgreSQL TLS settings:

```text
# Without TLS
postgresql://user:pass@localhost:5432/mydb

# With TLS (require mode)
postgresql://user:pass@localhost:5432/mydb?sslmode=require

# With TLS (verify-full mode, verifying the server certificate against a CA)
postgresql://user:pass@localhost:5432/mydb?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca.pem

# With PostgreSQL client-certificate authentication
postgresql://user@localhost:5432/mydb?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca.pem&sslcert=/etc/ssl/certs/client.pem&sslkey=/etc/ssl/private/client.key
```

## Client Certificate Generation (mTLS)

If you require client certificates for inbound HTTPS (enforced at the reverse
proxy with `ssl_verify_client on`), generate a CA and per-client certificates:

### 1. Generate CA Key and Certificate

```bash
# CA private key
openssl genrsa -out ca-key.pem 4096

# CA certificate
openssl req -new -x509 -days 3650 -key ca-key.pem -out ca-cert.pem \
  -subj "/CN=fraiseql-ca/O=YourOrg/C=US"
```

### 2. Generate Client Certificate

```bash
# Client key
openssl genrsa -out client-key.pem 2048

# Client CSR
openssl req -new -key client-key.pem -out client.csr \
  -subj "/CN=client.example.com/O=YourOrg/C=US"

# Sign with CA
openssl x509 -req -days 365 -in client.csr \
  -CA ca-cert.pem -CAkey ca-key.pem -CAcreateserial \
  -out client-cert.pem
```

### 3. Point the proxy at the client CA

Configure the reverse proxy to require and verify client certificates against the
CA you created. For nginx:

```text
server {
    listen 443 ssl;
    server_name api.example.com;

    ssl_certificate        /etc/fraiseql/server-cert.pem;
    ssl_certificate_key    /etc/fraiseql/server-key.pem;
    ssl_protocols          TLSv1.3;

    ssl_client_certificate /etc/fraiseql/ca-cert.pem;
    ssl_verify_client      on;

    location / { proxy_pass http://127.0.0.1:8000; }
}
```

## Docker Compose Example

The app container runs the FraiseQL FastAPI app under `uvicorn`; an nginx
container in front of it terminates inbound TLS, and PostgreSQL is configured for
SSL so the app's `database_url` can use `sslmode=verify-full`:

```yaml
services:
  proxy:
    image: nginx:1.27
    ports:
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./certs:/etc/fraiseql:ro
    depends_on:
      - app

  app:
    build: .
    # Run the FraiseQL FastAPI app on plain HTTP behind the proxy
    command: uvicorn app:app --host 0.0.0.0 --port 8000 --proxy-headers
    environment:
      FRAISEQL_DATABASE_URL: postgresql://user:pass@postgres:5432/mydb?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca.pem
    volumes:
      - ./certs/ca.pem:/etc/ssl/certs/ca.pem:ro
    depends_on:
      - postgres

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: mydb
      POSTGRES_PASSWORD: password
    command: >
      -c ssl=on
      -c ssl_cert_file=/var/lib/postgresql/server.crt
      -c ssl_key_file=/var/lib/postgresql/server.key
    volumes:
      - ./certs/postgres-cert.pem:/var/lib/postgresql/server.crt:ro
      - ./certs/postgres-key.pem:/var/lib/postgresql/server.key:ro
```

## Kubernetes TLS Configuration

In Kubernetes, inbound TLS is typically handled by an Ingress (with
`cert-manager` provisioning certificates) rather than by the app pod. The app
pod just runs `uvicorn` on plain HTTP and connects to PostgreSQL with
`sslmode=verify-full`.

### Secret Setup (certificate used by the Ingress)

```bash
# Create TLS secret for the Ingress
kubectl create secret tls fraiseql-tls \
  --cert=./certs/cert.pem \
  --key=./certs/key.pem
```

### Ingress (inbound HTTPS termination)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: fraiseql
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  tls:
    - hosts:
        - api.example.com
      secretName: fraiseql-tls
  rules:
    - host: api.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: fraiseql
                port:
                  number: 8000
```

### Deployment (app on plain HTTP; DB TLS via the connection string)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fraiseql
spec:
  template:
    spec:
      containers:
        - name: fraiseql
          image: fraiseql-app:latest
          command:
            - uvicorn
            - app:app
            - --host
            - "0.0.0.0"
            - --port
            - "8000"
            - --proxy-headers
          env:
            - name: FRAISEQL_DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: fraiseql-db
                  key: database_url   # includes ?sslmode=verify-full&sslrootcert=...
```

## Verification and Testing

### 1. Test the HTTPS Connection (inbound)

```bash
# With curl (ignore self-signed cert warnings)
curl -k https://api.example.com/graphql

# With proper CA cert
curl --cacert /etc/ssl/certs/ca-cert.pem https://api.example.com/graphql

# With a client certificate (mTLS enforced at the proxy)
curl \
  --cacert /etc/ssl/certs/ca-cert.pem \
  --cert /etc/fraiseql/client-cert.pem \
  --key /etc/fraiseql/client-key.pem \
  https://api.example.com/graphql
```

### 2. Test the TLS Version

```bash
# Check that TLS 1.2 is accepted
openssl s_client -connect api.example.com:443 -tls1_2 < /dev/null

# Verify older versions are rejected (should fail when ssl_protocols excludes them)
openssl s_client -connect api.example.com:443 -tls1_1 < /dev/null  # Should fail
```

### 3. Test the PostgreSQL Connection (app ↔ database)

```bash
# Verify the encrypted PostgreSQL connection independently of the app
psql "postgresql://user@db.example.com/mydb?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca.pem"
```

Inside `psql`, confirm the session is encrypted:

```sql
SELECT ssl, version, cipher FROM pg_stat_ssl WHERE pid = pg_backend_pid();
```

## Security Best Practices

1. **Use TLS 1.3** when possible (set `ssl_protocols TLSv1.3` at the proxy).
2. **Verify the database certificate** with `sslmode=verify-full` and a pinned `sslrootcert`.
3. **Rotate certificates** before expiration (set calendar reminders or automate renewal).
4. **Use strong private keys** (2048-bit RSA minimum, 4096-bit preferred).
5. **Protect certificate files** with proper permissions (`chmod 600 key.pem`).
6. **Use certificate management tools**:
   - Let's Encrypt with Certbot (free automated renewal)
   - Caddy (automatic HTTPS) or Traefik (built-in ACME)
   - Kubernetes cert-manager (if using K8s)
7. **Monitor certificate expiration**:

   ```bash
   openssl x509 -enddate -noout -in /etc/fraiseql/cert.pem
   ```

8. **Use different keys per environment** (dev, staging, production).
9. **Store private keys in secrets management** (HashiCorp Vault, AWS Secrets Manager, Kubernetes Secrets).
10. **Keep the app on a private network** and let the proxy/load balancer be the only TLS-terminating, internet-facing component.

## Troubleshooting

### TLS Certificate Not Found (inbound)

```text
error: [Errno 2] No such file or directory: '/etc/fraiseql/cert.pem'
```

**Solution**: Verify the certificate/key paths passed to `uvicorn`
(`--ssl-certfile` / `--ssl-keyfile`) or referenced in the proxy config exist and
are readable by the serving process.

### TLS Version Too Old (inbound)

```text
error: no protocols available  (client offered only TLS 1.1)
```

**Solution**: Update the client's TLS version, or relax `ssl_protocols` at the
proxy (not recommended for production).

### Client Certificate Required (mTLS)

```text
400 Bad Request — No required SSL certificate was sent
```

**Solution**: Provide a client certificate when the proxy has
`ssl_verify_client on`, or set `ssl_verify_client off` to disable mTLS.

### Database Connection SSL Error (app ↔ database)

```text
error: connection requires a valid client certificate
error: server does not support SSL, but SSL was required
```

**Solution**: Ensure PostgreSQL has SSL enabled and `pg_hba.conf` permits the
connection, and that your `database_url` uses the correct `sslmode` (and
`sslrootcert`/`sslcert`/`sslkey` where required).

## References

- [TLS 1.3 RFC 8446](https://tools.ietf.org/html/rfc8446)
- [OWASP Transport Layer Protection](https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Protection_Cheat_Sheet.html)
- [PostgreSQL SSL Support](https://www.postgresql.org/docs/current/ssl-tcp.html)
- [Uvicorn deployment & HTTPS](https://www.uvicorn.org/deployment/)
- [nginx ngx_http_ssl_module](https://nginx.org/en/docs/http/ngx_http_ssl_module.html)
- [Let's Encrypt / Certbot](https://certbot.eff.org/)

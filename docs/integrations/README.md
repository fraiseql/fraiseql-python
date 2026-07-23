<!-- Skip to main content -->
---

title: Integrations
description: Integration guides for connecting FraiseQL with authentication providers, GraphQL clients, FastAPI, and PostgreSQL.
keywords: ["framework", "authentication", "fastapi", "postgresql", "graphql"]
tags: ["documentation", "reference"]
---

# Integrations

How to connect a FraiseQL v1 app to the rest of your stack. FraiseQL is a Python
runtime GraphQL framework for PostgreSQL, served over FastAPI, so most integration
happens at three layers: **authentication** (validating who is calling), the
**FastAPI app** (middleware, mounting, GraphQL clients), and **PostgreSQL itself**
(foreign data wrappers, functions, and extensions inside your views).

## Quick Navigation

### Authentication

Validate JWTs and enforce per-operation and per-field authorization. v1 ships an
Auth0 provider, a native/custom provider path, and PostgreSQL-backed token
revocation — all running inside the FastAPI app.

- **[Authentication Guide](authentication/README.md)** — Overview and setup
- **[Provider Selection Guide](authentication/provider-selection-guide.md)** — Choosing a provider
- **[Auth0 Setup](authentication/setup-auth0.md)** — Auth0 as the JWT issuer
- **[Google OAuth Setup](authentication/setup-google-oauth.md)** — Google login via Auth0 or a custom provider
- **[Keycloak Setup](authentication/setup-keycloak.md)** — Keycloak via Auth0 or a custom provider
- **[SCRAM Authentication](authentication/scram.md)** — PostgreSQL connection auth (scram-sha-256)
- **[API Reference](authentication/api-reference.md)** — Auth decorators and provider classes
- **[Deployment](authentication/deployment.md)** — Production auth configuration
- **[Monitoring](authentication/monitoring.md)** — Auth metrics and logging
- **[Security Checklist](authentication/security-checklist.md)** — Pre-deployment review
- **[Troubleshooting](authentication/troubleshooting.md)** — Common auth issues

### Python API

The Python authoring surface: decorators (`@fraiseql.type`, `@fraiseql.query`,
`@fraiseql.mutation`, `@fraiseql.subscription`), the CQRS repository (`db.find`,
`db.find_one`, `db.execute_function`), scalars, and `create_fraiseql_app`.

- **[Python Reference](sdk/python-reference.md)** — Complete Python authoring interface

### Monitoring

- **[Grafana Dashboard](monitoring/grafana-dashboard-8.7.json)** — Pre-built dashboard

## Authentication providers

v1 has three provider modes (`auth_provider` = `"auth0"`, `"custom"`, or `"none"`):

- **Auth0** — pass an `Auth0Provider(Auth0Config(...))`; Auth0 can also broker other
  identity providers (Google, Keycloak, any OIDC issuer).
- **Custom / native** — subclass `AuthProvider` to validate any OIDC/JWT issuer
  (Google, Keycloak, your own) using its JWKS, issuer, and audience.
- **None** — no auth (development only).

Authorization is enforced in Python: `requires_auth` / `requires_role` /
`requires_permission` decorators, an `Authorizer` attached via
`@fraiseql.query(authorizer=...)`, and field-level `authorize_fields`. Denied
access surfaces as a GraphQL error with `extensions.code = "FORBIDDEN"`.

See the [Authentication Guide](authentication/README.md) for setup.

## FastAPI integration

FraiseQL returns a standard FastAPI app from `create_fraiseql_app(...)`, so it
composes with the rest of the FastAPI ecosystem:

- **Middleware** — pass `middleware=[...]` to `create_fraiseql_app`, or add standard
  ASGI/FastAPI middleware (CORS, logging, tracing).
- **Mounting** — mount the FraiseQL app inside a larger FastAPI application alongside
  your own routes.
- **GraphQL clients** — the endpoint is plain GraphQL-over-HTTP (and
  GraphQL-over-WebSocket for subscriptions), so any GraphQL client works (Apollo
  Client, urql, graphql-request, `gql`, etc.). Set `production=False` to enable the
  built-in GraphQL playground.

## PostgreSQL integration

PostgreSQL is the deepest integration surface in v1. Bring external systems and
capabilities into your read views and write functions:

- **Foreign data wrappers (FDW)** — query remote PostgreSQL, other databases, or
  flat files through `postgres_fdw` / other FDWs inside your `v_`/`tv_` views.
- **Functions** — encapsulate write logic and integrations in `fn_` functions called
  by mutations via `db.execute_function`.
- **Extensions** — use `pgvector`, `pg_trgm`, `PostGIS`, `ltree`, and others directly;
  FraiseQL exposes matching WHERE operators for them.

---

**Last Updated**: June 19, 2026

<!-- Skip to main content -->
---

title: Operations Guide
description: Guide for deploying, monitoring, and maintaining a FraiseQL (Python/FastAPI/PostgreSQL) application in production.
keywords: ["deployment", "monitoring", "performance", "observability", "troubleshooting"]
tags: ["documentation", "reference"]
---

# Operations Guide

Operating a FraiseQL application in production. FraiseQL builds its GraphQL schema in
memory at startup and serves it from a FastAPI app (run under an ASGI server such as
`uvicorn`) backed by PostgreSQL. These pages cover configuring observability, tracing,
and tuning query performance.

## In This Section

- **[Observability](observability.md)** — Metrics, logging, and health signals for the running FastAPI app.
- **[Distributed Tracing](distributed-tracing.md)** — Trace requests across the app and into PostgreSQL.
- **[Observability Configuration](configuration.md)** — Configuration reference for the observability features.
- **[Performance Tuning Runbook](performance-tuning-runbook.md)** — Diagnose and optimize GraphQL/PostgreSQL query performance.

## Related Guides

- **[Production Deployment](../guides/production-deployment.md)** — Deploy the FastAPI app to production.
- **[Monitoring](../guides/monitoring.md)** — Day-to-day monitoring guidance.
- **[TLS Configuration](../configuration/tls-configuration.md)** — Terminate TLS for the app.
- **[Rate Limiting](../configuration/rate-limiting.md)** — Protect endpoints from abuse.
- **[PostgreSQL Authentication](../configuration/postgresql-authentication.md)** — Secure the database connection.

## Running in Production

1. **Deploy** — Run the FastAPI app under an ASGI server (`uvicorn app:app`) following the [Production Deployment](../guides/production-deployment.md) guide.
2. **Secure** — Configure [TLS](../configuration/tls-configuration.md), [rate limiting](../configuration/rate-limiting.md), and [PostgreSQL authentication](../configuration/postgresql-authentication.md).
3. **Observe** — Enable [observability](observability.md) and [distributed tracing](distributed-tracing.md).
4. **Tune** — Use the [Performance Tuning Runbook](performance-tuning-runbook.md) to diagnose slow queries.

## Support

- **Troubleshooting**: See the [troubleshooting guide](../guides/troubleshooting.md).

<!-- Skip to main content -->
---

title: FraiseQL Guides
description: Practical how-to guides for developers, DevOps, and DBAs building PostgreSQL-backed GraphQL APIs with FraiseQL.
keywords: ["debugging", "implementation", "best-practices", "deployment", "tutorial"]
tags: ["documentation", "reference"]
---

# FraiseQL Guides

Practical how-to guides for developers, DevOps teams, and DBAs building PostgreSQL-backed GraphQL APIs with FraiseQL. FraiseQL is a Python runtime framework: you define types, queries, and mutations with decorators, and the schema is built in memory at app startup and served over FastAPI.

---

## 🚀 Getting Started

- **[Understanding FraiseQL in 10 Minutes](understanding-fraiseql.md)** — Core concepts: the CQRS read/write split, views, and `fn_` functions
- **[Common Patterns](patterns.md)** — Real-world schema design patterns and solutions
- **[Trinity Pattern Guide](trinity-pattern-guide.md)** — The `pk_`/`id`/`identifier` identifier pattern

## 🎯 Evaluation & Decision Making

**Before you start building:**

- **[Choosing FraiseQL](choosing-fraiseql.md)** — Is FraiseQL right for your project? Use case analysis and decision matrix
- **[Decision Matrices](decision-matrices.md)** — Comparison tables for common architectural choices
- **[Consistency Model](consistency-model.md)** — FraiseQL's CAP theorem positioning (CP: Consistency + Partition Tolerance)

## 🛠️ Development Guides

- **[Developer Guide](development/developer-guide.md)** — Development environment setup
- **[Schema Design Best Practices](schema-design-best-practices.md)** — Designing tables, views, and types
- **[DDL Generation Guide](ddl-generation-guide.md)** — Creating table-backed (`tv_`) views
- **[Database Schema Migration Guide](database-migration-guide.md)** — Evolving your PostgreSQL schema safely
- **[Mutation SQL Requirements](mutation-sql-requirements.md)** — Writing `fn_` functions for mutations
- **[Filtering Guide](filtering.md)** — WHERE operators and query filters
- **[Nested Array Filtering](nested-array-filtering.md)** — Filtering inside nested JSONB arrays
- **[Error Handling Patterns](error-handling-patterns.md)** — Success/error union results and error shaping
- **[Advanced Features](advanced-features.md)** — Less common features and techniques

## 🔐 Authorization

- **[Authorization & RBAC Quick Start](authorization-quick-start.md)** — Field- and operation-level authorization in 5 minutes

## ⚡ Performance

- **[Performance Guide](performance-guide.md)** — End-to-end performance practices
- **[Performance & Optimization Guide](performance-optimization.md)** — Tuning queries, views, and caching
- **[Analytics Patterns](analytics-patterns.md)** — Runtime auto-aggregation and analytical query patterns
- **[Cascade Best Practices](cascade-best-practices.md)** — Cache cascade invalidation rules
- **[Migrating to Cascade](migrating-to-cascade.md)** — Adopting cascade-based cache invalidation

## 📊 Operations & Monitoring

- **[Production Deployment Guide](production-deployment.md)** — Deploying the FastAPI app to production
- **[Production Security Checklist](production-security-checklist.md)** — Pre-launch security review
- **[Monitoring & Observability](monitoring.md)** — Prometheus metrics and OpenTelemetry tracing
- **[Observability Guide](observability.md)** — Logging, tracing, and metrics best practices

## 🔌 Integrations

- **[Client Implementation Guides](clients/README.md)** — Querying FraiseQL from React, Vue, Flutter, React Native, and Node.js
- **[LangChain Integration](langchain-integration.md)** — Using FraiseQL with LangChain
- **[Integrations Overview](../integrations/README.md)** — Authentication providers and monitoring integrations

## 🩺 Troubleshooting

- **[Troubleshooting Guide](troubleshooting.md)** — General troubleshooting
- **[Troubleshooting Decision Tree](troubleshooting-decision-tree.md)** — Diagnose issues by symptom
- **[Troubleshooting Mutations](troubleshooting-mutations.md)** — Debugging `fn_`-backed mutations
- **[Common Gotchas & Pitfalls](common-gotchas.md)** — Frequent surprises and how to avoid them
- **[Common Mistakes](common-mistakes.md)** — Anti-patterns in FraiseQL implementations

---

## 🎯 By Use Case

**I want to...**

- **Evaluate if FraiseQL is right for me** → [Choosing FraiseQL](choosing-fraiseql.md)
- **Understand the core model** → [Understanding FraiseQL in 10 Minutes](understanding-fraiseql.md)
- **Understand consistency guarantees** → [Consistency Model](consistency-model.md)
- **Design a schema** → [Schema Design Best Practices](schema-design-best-practices.md)
- **Write a mutation** → [Mutation SQL Requirements](mutation-sql-requirements.md)
- **Filter query results** → [Filtering Guide](filtering.md)
- **Add authorization** → [Authorization Quick Start](authorization-quick-start.md)
- **Tune performance** → [Performance & Optimization Guide](performance-optimization.md)
- **Deploy to production** → [Production Deployment](production-deployment.md)
- **Set up monitoring** → [Monitoring & Observability](monitoring.md)
- **Integrate with Auth0** → [Auth0 Setup](../integrations/authentication/setup-auth0.md)
- **Query from a frontend** → [Client Implementation Guides](clients/README.md)

---

## 📚 Related Documentation

- **[Architecture](../architecture/)** — Deep dive into FraiseQL design
- **[Specifications](../specs/)** — Complete API and feature specifications
- **[Operations](../operations/)** — Day-to-day operations and troubleshooting
- **[Configuration](../configuration/)** — Security and operational configuration
- **[Enterprise](../enterprise/)** — RBAC, audit logging, KMS

---

## 📋 Document Metadata Guide

All guides in this directory follow a consistent metadata format for discoverability and context:

```text
| Metadata | Values | Example |
|----------|--------|---------|
| **Status** | ✅ Production Ready, ⚠️ Beta, 📝 Draft | ✅ Production Ready |
| **Audience** | Developers, DevOps, DBAs, Architects, SREs | Developers, Architects |
| **Reading Time** | Estimated minutes | 10-15 minutes |
| **Last Updated** | YYYY-MM-DD | 2026-02-05 |
```

**What these mean:**

- **Status**: Indicates feature stability and support level
  - ✅ **Production Ready** - Fully tested, supported, recommended for production use
  - ⚠️ **Beta** - Functional but may have breaking changes, use in staging first
  - 📝 **Draft** - Under development, may be incomplete or unstable

- **Audience**: Who should read this guide
  - **Developers** - Application engineers building with FraiseQL
  - **DevOps** - Infrastructure and deployment specialists
  - **DBAs** - Database administrators
  - **Architects** - System architects and technical leads
  - **SREs** - Site reliability engineers

- **Reading Time**: Estimated time to read the full guide
  - Quick references (3-5 minutes)
  - Quick starts (5-10 minutes)
  - Detailed guides (15-30 minutes)
  - Deep dives (30+ minutes)

<!-- Skip to main content -->
---

title: FraiseQL v2.0.0-alpha.1 Testing Guide
description: Welcome to the FraiseQL v2 alpha release! This guide helps you effectively test the system and provide valuable feedback.
keywords: []
tags: ["documentation", "reference"]
---

# FraiseQL v2.0.0-alpha.1 Testing Guide

Welcome to the FraiseQL v2 alpha release! This guide helps you effectively test the system and provide valuable feedback.

---

## 🎯 What We Need from Alpha Testers

### Critical Testing Areas (High Priority)

1. **Schema Compilation**
   - [ ] Define schemas in Python, TypeScript, Go, or PHP
   - [ ] Run `FraiseQL-cli compile` on your schema
   - [ ] Verify compiled schema matches your expectations
   - [ ] Test with edge cases (nullable fields, complex types, unions)

2. **Query Execution**
   - [ ] Run simple queries (SELECT-like operations)
   - [ ] Test filtering with WHERE operators
   - [ ] Test sorting and pagination
   - [ ] Execute mutations (INSERT/UPDATE operations)

3. **Database Support**
   - [ ] PostgreSQL (primary - most tested)
   - [ ] MySQL (secondary)
   - [ ] SQLite (development/testing)
   - [ ] SQL Server (enterprise)

4. **Authentication & Security**
   - [ ] Test OAuth2/OIDC flows (Google, GitHub, Auth0)
   - [ ] Verify rate limiting is working
   - [ ] Test field-level access control
   - [ ] Validate error messages don't leak sensitive info

### Important Testing Areas (Medium Priority)

1. **Federation** (if you have multiple services)
   - [ ] Setup Apollo Federation
   - [ ] Test entity resolution
   - [ ] Verify SAGA transactions work correctly

2. **Streaming & Performance**
   - [ ] Test Arrow Flight data export (if using analytics)
   - [ ] Stream large result sets with FraiseQL-wire
   - [ ] Monitor performance under load
   - [ ] Check memory usage patterns

3. **Integration Features**
   - [ ] Webhooks (Discord, Slack, custom)
   - [ ] Change Data Capture (CDC) events
   - [ ] Caching and query invalidation

4. **Operations**
   - [ ] Deploy to Docker and Kubernetes
   - [ ] Setup monitoring (Prometheus metrics)
   - [ ] Configure structured logging
   - [ ] Test health check endpoints

---

## ⚠️ Known Limitations (Alpha Phase)

### Feature Limitations

#### Not Included in Alpha

- Subscriptions/real-time queries (planned for v2.1)
- GraphQL directives beyond `@auth` and `@cache` (others planned for v2.1)
- Advanced performance optimizations (deferred to v2.1)
- Oracle database support (no Rust driver available)

### Partially Supported

- Language SDKs: Only Python, TypeScript, Go, PHP ready for alpha. Other languages coming in beta/GA.
- Integration providers: 11 webhook providers included; more planned for v2.1

### Performance Notes

The alpha release prioritizes **correctness over optimization**. You may observe:

- **P95 Latency**: ~145ms on typical queries (target is <100ms for GA)
- **Memory Usage**: Reasonable for typical workloads, but not yet micro-optimized
- **Arrow Flight**: Performs well (50x faster than JSON) but schema pre-loading can be optimized

These are **not blocking issues** and won't affect functionality.

### Breaking Changes from v1

FraiseQL v2 is a complete redesign and **not backwards compatible** with v1:

- **Schema format**: Completely different (v1 schema won't work)
- **Configuration**: Now TOML-based instead of environment variables
- **Database conventions**: New naming scheme (tb_*, v_*, fn_*)
- **API**: GraphQL is similar but with new field semantics

**Migration path**: Currently, you'll need to rewrite your schema for v2. A migration guide is coming in beta.

---

## 🚀 Quick Start for Testing

### 1. Install FraiseQL

#### Option A: From source

```bash
<!-- Code example in BASH -->
git clone https://github.com/FraiseQL/FraiseQL.git
cd FraiseQL
cargo build --release
./target/release/FraiseQL-cli --version
```text
<!-- Code example in TEXT -->

#### Option B: With Docker

```bash
<!-- Code example in BASH -->
docker build -t FraiseQL:alpha .
docker run FraiseQL:alpha FraiseQL-cli --version
```text
<!-- Code example in TEXT -->

### 2. Define a Test Schema

Create `schema.py`:

```python
<!-- Code example in Python -->
from uuid import UUID
from FraiseQL import type as fraiseql_type, query as fraiseql_query, schema

@fraiseql_type
class User:
    id: UUID                # ✅ UUID v4 (see Naming Patterns)
    name: str
    email: str | None

@fraiseql_query(sql_source="v_users")  # ✅ Read from v_users view, not tb_user
def users(limit: int = 10) -> list[User]:
    pass

schema.export_schema("schema.json")
```text
<!-- Code example in TEXT -->

Run: `python schema.py`

### 3. Compile Schema

```bash
<!-- Code example in BASH -->
FraiseQL-cli compile schema.json -o schema.compiled.json
```text
<!-- Code example in TEXT -->

### 4. Setup Database

For PostgreSQL, create your views:

```sql
<!-- Code example in SQL -->
CREATE VIEW v_users AS
SELECT id, name, email FROM tb_user;
```text
<!-- Code example in TEXT -->

For other databases, see [Database Schema Conventions](specs/schema-conventions.md).

### 5. Run Server

Create `config.toml`:

```toml
<!-- Code example in TOML -->
[server]
bind_addr = "0.0.0.0:8080"
database_url = "postgresql://localhost/testdb"

[FraiseQL.security]
rate_limiting.enabled = true
```text
<!-- Code example in TEXT -->

Start server:

```bash
<!-- Code example in BASH -->
FraiseQL-server -c config.toml --schema schema.compiled.json
```text
<!-- Code example in TEXT -->

### 6. Test Queries

```bash
<!-- Code example in BASH -->
curl -X POST http://localhost:8080/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ users(limit: 5) { id name email } }"}'
```text
<!-- Code example in TEXT -->

---

## 🐛 How to Report Issues

### Using GitHub Issues

1. Go to [FraiseQL Issues](https://github.com/FraiseQL/FraiseQL/issues)
2. Click **New Issue**
3. Use the appropriate template:
   - **Bug Report** — For broken functionality
   - **Feature Request** — For missing features
   - **Documentation** — For unclear docs

### What to Include

#### For bugs:

```text
<!-- Code example in TEXT -->
## Description
Brief description of the issue

## Steps to Reproduce

1. Define schema with...
2. Compile with...
3. Run query...

## Expected Behavior
What should happen

## Actual Behavior
What actually happened

## Environment

- FraiseQL version: 2.0.0-alpha.1
- Language: Python / TypeScript / Go / PHP
- Database: PostgreSQL 15 / MySQL 8.0 / etc.
- OS: Linux / macOS / Windows
- Error message (if applicable)
```text
<!-- Code example in TEXT -->

### For feature requests:

```text
<!-- Code example in TEXT -->
## Use Case
Why do you need this?

## Proposed Solution
How should this work?

## Current Workaround
Are you working around this now?
```text
<!-- Code example in TEXT -->

### Tag Your Issue

Please add the **`alpha`** label to alpha-specific issues. Other useful labels:

- `bug` — Something is broken
- `documentation` — Docs need improvement
- `performance` — Performance issue
- `security` — Security concern
- `question` — Need clarification

---

## 📊 Feedback We Want

### Schema & Type System

- [ ] Are type definitions intuitive?
- [ ] Is automatic WHERE operator generation working?
- [ ] Are field scalar types useful?
- [ ] Any missing type features?

### Query Execution

- [ ] Are query results correct?
- [ ] Is filtering working as expected?
- [ ] Pagination behavior correct?
- [ ] Performance acceptable?

### Security

- [ ] OAuth2/OIDC flow smooth?
- [ ] Rate limiting effective?
- [ ] Error messages appropriate (not too detailed)?
- [ ] Field-level auth working?

### Operations

- [ ] Docker setup straightforward?
- [ ] Kubernetes deployment clear?
- [ ] Monitoring metrics useful?
- [ ] Health checks working?

### Documentation

- [ ] Getting started guide clear?
- [ ] Examples helpful?
- [ ] Architecture docs understandable?
- [ ] Missing anything important?

---

## 🔍 Testing Checklist

Use this checklist to guide your testing:

### Basic Functionality

- [ ] Schema compiles without errors
- [ ] Server starts with compiled schema
- [ ] Simple query returns data
- [ ] Filtered queries return correct results
- [ ] Sorting works correctly
- [ ] Pagination works (limit/offset or cursor)

### Edge Cases

- [ ] Nullable fields handled correctly
- [ ] Empty result sets work
- [ ] Large result sets handled
- [ ] Special characters in filters work
- [ ] NULL comparisons work
- [ ] Complex nested queries work

### Security

- [ ] Unauthenticated queries rejected (if auth required)
- [ ] Field-level auth enforced
- [ ] SQL injection attempts rejected
- [ ] Rate limiting kicks in after threshold
- [ ] Audit logs record mutations

### Performance

- [ ] Query latency acceptable
- [ ] Memory usage reasonable
- [ ] Database connections pooled
- [ ] No N+1 queries detected
- [ ] Arrow Flight faster than JSON

### Deployment

- [ ] Docker image builds
- [ ] Docker container runs
- [ ] Kubernetes manifests apply
- [ ] Health checks respond
- [ ] Metrics exported to Prometheus

---

## 💬 Sharing Feedback

### GitHub Discussions

For non-urgent feedback, ideas, and questions:

- [GitHub Discussions](https://github.com/FraiseQL/FraiseQL/discussions)
- Create new discussion with category (Feedback, Questions, Ideas)

### Direct Communication

For confidential feedback or security issues:

- Email: <team@FraiseQL.dev>
- **For security issues**: Please don't open public issues. Email first.

### Community Discord

Discord server coming soon for real-time chat with the team and community.

---

## 📈 Performance Benchmarking

If you're interested in performance testing:

### Running Benchmarks

```bash
<!-- Code example in BASH -->
# Arrow vs JSON serialization
cargo bench -p FraiseQL-arrow

# Query execution performance
cargo bench -p FraiseQL-core
```text
<!-- Code example in TEXT -->

### What to Measure

- Query latency (P50, P95, P99)
- Throughput (queries/second)
- Memory usage at peak load
- CPU utilization
- Database connection overhead

---

## 🎓 Additional Resources

- **[Main README](../README.md)** — Project overview
- **[Architecture Guide](architecture/)** — System design
- **[Database Conventions](specs/schema-conventions.md)** — Schema naming
- **[Reference API](reference/)** — Complete API reference
- **[Language Examples](guides/language-generators.md)** — Code examples
- **[Troubleshooting](troubleshooting.md)** — Common issues

---

## ✅ Final Checklist Before Reporting

- [ ] Issue is not already reported (search GitHub issues)
- [ ] You're using v2.0.0-alpha.1 (check version)
- [ ] You've included steps to reproduce
- [ ] You've tested with the latest code (pull latest)
- [ ] Environment details are included
- [ ] You've added the `alpha` label

---

## 🙏 Thank You

Thank you for testing FraiseQL v2! Your feedback is crucial for making this the best GraphQL execution engine for relational databases.

### Happy testing!

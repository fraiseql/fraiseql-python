---
title: Dependencies
description: Python dependencies, Rust extensions, and PostgreSQL requirements
tags:
  - dependencies
  - requirements
  - Python
  - Rust
  - PostgreSQL
---

# FraiseQL Dependencies & Related Projects

> **FraiseQL is built on a foundation of purpose-built tools for PostgreSQL and GraphQL**

FraiseQL integrates several components to provide a complete, high-performance GraphQL framework. This guide explains each dependency and how they work together.

---

## Core Dependencies

### FraiseQL Ecosystem

FraiseQL is built on three core projects:

| Project | Type | Purpose | GitHub |
|---------|------|---------|--------|
| **confiture** | Python Package | Database migration management | [fraiseql/confiture](https://github.com/fraiseql/confiture) |
| **jsonb_ivm** | PostgreSQL Extension | Incremental View Maintenance | [fraiseql/jsonb_ivm](https://github.com/fraiseql/jsonb_ivm) |
| **pg_fraiseql_cache** | PostgreSQL Extension | CASCADE cache invalidation | *In development* |

---

## PostgreSQL Extensions

### jsonb_ivm

**Incremental JSONB View Maintenance for CQRS architectures**

```bash
# Install from GitHub
git clone https://github.com/fraiseql/jsonb_ivm.git
cd jsonb_ivm
make && sudo make install
```

**What it does**:

- Provides `jsonb_merge_shallow()` function for partial JSONB updates
- **10-100x faster** than full JSONB rebuilds
- Essential for FraiseQL's explicit sync pattern

**Usage in FraiseQL**:

```python
from fraiseql.ivm import setup_auto_ivm

recommendation = await setup_auto_ivm(db_pool, verbose=True)
# ✓ Detected jsonb_ivm v1.1
# IVM Analysis: 5/8 tables benefit from incremental updates
```

**Documentation**: [PostgreSQL Extensions Guide](./postgresql-extensions.md#jsonbivm-extension)

---

### pg_fraiseql_cache

**Intelligent cache invalidation with CASCADE rules**

```bash
# Install from GitHub
git clone https://github.com/fraiseql/pg_fraiseql_cache.git
cd pg_fraiseql_cache
make && sudo make install
```

**What it does**:

- Automatic CASCADE invalidation rules from GraphQL schema
- When User changes → related Post caches invalidate automatically
- Zero manual cache invalidation code

**Usage in FraiseQL**:

```python
from fraiseql.caching import setup_auto_cascade_rules

await setup_auto_cascade_rules(cache, schema, verbose=True)
# CASCADE: Detected relationship: User -> Post
# CASCADE: Created 3 CASCADE rules
```

**Documentation**: [CASCADE Best Practices](../guides/cascade-best-practices.md)

---

## Python Packages

### confiture

**PostgreSQL migrations, sweetly done 🍓**

```bash
# Install from PyPI (when published)
pip install confiture

# Or install from GitHub
pip install git+https://github.com/fraiseql/confiture.git
```

**What it does**:

- SQL-based migration management
- Simple CLI interface
- Safe rollback support
- Version tracking

**Usage in FraiseQL**:

```bash
# Initialize migrations
fraiseql migrate init

# Create migration
fraiseql migrate create initial_schema

# Apply migrations
fraiseql migrate up

# Check status
fraiseql migrate status
```

**Features**:

- Simple SQL files (no complex DSL)
- Automatic version tracking
- Safe rollback support
- Production-ready

**Documentation**: [Migrations Guide](./migrations.md)

---

## Development Setup

### For FraiseQL Development

If you're developing FraiseQL itself and need local copies:

```toml
# pyproject.toml
[project]
dependencies = [
  "confiture>=0.2.0",
  # ... other dependencies
]

[tool.uv.sources]
confiture = { path = "../confiture", editable = true }
```

This allows you to:

- Work on confiture and FraiseQL simultaneously
- Test changes immediately
- Contribute to both projects

### For FraiseQL Users

Users just install FraiseQL, which automatically pulls confiture from PyPI:

```bash
pip install "fraiseql<2"
# confiture is installed automatically as a dependency
```

PostgreSQL extensions need to be installed separately:

```bash
# Install extensions
git clone https://github.com/fraiseql/jsonb_ivm.git && \
  cd jsonb_ivm && make && sudo make install

git clone https://github.com/fraiseql/pg_fraiseql_cache.git && \
  cd pg_fraiseql_cache && make && sudo make install
```

Or use Docker (recommended):

```dockerfile
FROM postgres:17.5

# Install extensions automatically
RUN apt-get update && apt-get install -y \
    postgresql-server-dev-17 build-essential git ca-certificates

RUN git clone https://github.com/fraiseql/jsonb_ivm.git /tmp/jsonb_ivm && \
    cd /tmp/jsonb_ivm && make && make install

RUN git clone https://github.com/fraiseql/pg_fraiseql_cache.git /tmp/pg_fraiseql_cache && \
    cd /tmp/pg_fraiseql_cache && make && make install
```

---

## Architecture Overview

### How Components Work Together

```
┌──────────────────────────────────────────────────────────────────┐
│ FraiseQL Application                                              │
│                                                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  GraphQL    │  │  Caching     │  │  Database Ops        │   │
│  │  API        │──│  Layer       │──│  (CQRS Pattern)      │   │
│  └─────────────┘  └──────────────┘  └──────────────────────┘   │
│         │                │                      │                │
│         │                │                      │                │
│         ▼                ▼                      ▼                │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  confiture (Migrations)                                  │   │
│  │  - fraiseql migrate init/create/up/down                 │   │
│  │  - SQL-based schema management                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                   │
└───────────────────────────────┬───────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│ PostgreSQL Database                                               │
│                                                                   │
│  ┌─────────────────────┐  ┌────────────────────────────────┐   │
│  │  jsonb_ivm          │  │  pg_fraiseql_cache             │   │
│  │                     │  │                                 │   │
│  │  • jsonb_merge_     │  │  • cache_invalidate()          │   │
│  │    shallow()        │  │  • CASCADE rules               │   │
│  │                     │  │  • Relationship tracking       │   │
│  │  • 10-100x faster   │  │  • Automatic invalidation      │   │
│  │    incremental      │  │                                 │   │
│  │    updates          │  │                                 │   │
│  └─────────────────────┘  └────────────────────────────────┘   │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Tables                                                  │   │
│  │                                                          │   │
│  │  tb_user, tb_post ──sync──▶ tv_user, tv_post           │   │
│  │  (command side)              (query side)                │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Migrations** (confiture)
   - Developer runs `fraiseql migrate up`
   - Creates tb_* (command) and tv_* (query) tables
   - Sets up database schema

2. **Write Operations**
   - Application writes to tb_* tables
   - Explicit sync call: `await sync.sync_post([post_id])`
   - jsonb_ivm updates tv_* using `jsonb_merge_shallow()` (fast!)

3. **Cache Invalidation**
   - pg_fraiseql_cache detects related data changes
   - CASCADE automatically invalidates dependent caches
   - User:123 changes → Post:* where author_id=123 invalidated

4. **Read Operations**
   - GraphQL query reads from tv_* tables
   - Denormalized JSONB = single query
   - Cache hit = sub-millisecond response

---

## Optional Dependencies

FraiseQL works without the PostgreSQL extensions, but with reduced performance:

| Extension | With Extension | Without Extension | Fallback |
|-----------|----------------|-------------------|----------|
| jsonb_ivm | 1-2ms sync | 10-20ms sync | Full JSONB rebuild |
| pg_fraiseql_cache | Auto CASCADE | Manual invalidation | Application-level cache |

**Recommendation**: Install extensions for production use, but you can develop without them.

---

## Version Compatibility

### FraiseQL Ecosystem Versions

| Component | Current Version | Min PostgreSQL | Min Python |
|-----------|----------------|----------------|------------|
| fraiseql | 0.11.0 | 14+ | 3.13+ |
| confiture | 0.2.0 | 14+ | 3.11+ |
| jsonb_ivm | 1.1 | 14+ | N/A |
| pg_fraiseql_cache | 1.0 | 14+ | N/A |

---

## Contributing

All FraiseQL ecosystem projects welcome contributions:

- **FraiseQL Core**: ../..
- **confiture**: https://github.com/fraiseql/confiture
- **jsonb_ivm**: https://github.com/fraiseql/jsonb_ivm
- **pg_fraiseql_cache**: https://github.com/fraiseql/pg_fraiseql_cache

See each project's CONTRIBUTING.md for guidelines.

---

## See Also

- [PostgreSQL Extensions Guide](./postgresql-extensions.md) - Detailed extension docs
- [Migrations Guide](./migrations.md) - confiture usage
- [CASCADE Best Practices](../guides/cascade-best-practices.md) - Cascade patterns
- [Explicit Sync](./explicit-sync.md) - jsonb_ivm integration
- [Complete CQRS Example](../../examples/complete_cqrs_blog/) - All components working together

---

**Last Updated**: 2025-10-11
**FraiseQL Version**: 0.11.0

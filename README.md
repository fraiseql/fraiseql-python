# FraiseQL

[![Quality Gate](https://github.com/fraiseql/fraiseql-python/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/fraiseql/fraiseql-python/actions/workflows/ci.yml)
[![Documentation](https://github.com/fraiseql/fraiseql-python/actions/workflows/docs.yml/badge.svg?branch=dev)](https://github.com/fraiseql/fraiseql-python/actions/workflows/docs.yml)
[![Release](https://img.shields.io/github/v/release/fraiseql/fraiseql-python)](https://github.com/fraiseql/fraiseql-python/releases/latest)
[![Python](https://img.shields.io/badge/Python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**v1.9.17** | **Stable** | **Rust-Powered GraphQL for PostgreSQL**

**Python**: 3.13+ | **PostgreSQL**: 13+

---

## GraphQL for the LLM era. Simple. Powerful. Rust-fast

PostgreSQL returns JSONB. Rust transforms it. Zero Python overhead.

```python
# Complete GraphQL API in 15 lines
import fraiseql
from fraiseql.fastapi import create_fraiseql_app

@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    """A user in the system.

    Fields:
        id: Unique user identifier
        name: User's full name
        email: User's email address
    """
    id: int
    name: str
    email: str

@fraiseql.query
async def users(info) -> list[User]:
    """Get all users."""
    db = info.context["db"]
    return await db.find("v_user")

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users]
)
```

---

## 📌 FraiseQL Versions

FraiseQL has two versions with overlapping but complementary strengths:

### v1.9.16 (This Repository: `fraiseql-python`)

**Python framework with integrated Rust pipeline**

- ✅ **Stable, production-ready** (v1.9.16)
- 🐍 **Python 3.13+ native** - write schema in Python decorators
- 🚀 **Rust pipeline included** - 7-10x faster JSON transformation
- 📡 **FastAPI runtime** - immediate deployment, hot reload, development-friendly
- 🗄️ **PostgreSQL-only** - optimized for PostgreSQL expertise
- 🔄 **Iterative development** - no build step, rapid feedback loops

**Best for:** Python teams, rapid iteration, existing PostgreSQL codebases, teams that want Rust performance without leaving Python ecosystem

**Repository:** [fraiseql/fraiseql-python](https://github.com/fraiseql/fraiseql-python)

### v2 (Separate Repository: `fraiseql`)

**Compiled Rust engine with polyglot schema authoring**

- 🚀 **Beta stage** (v2.0.0-alpha.2) - feature-complete, actively developed
- 🔧 **16+ language support** - Python, TypeScript, Go, Java, Rust, etc. (same schema authoring experience)
- ⚡ **Compile-time optimization** - build-time schema validation, zero-cost abstractions
- 🛠️ **CLI compiler** - `fraiseql-cli compile schema.json`
- 🗄️ **Multi-database** - PostgreSQL, MySQL, SQLite, SQL Server
- 🎯 **Maximum performance** - no runtime interpretation, fully compiled

**Best for:** Teams with multiple language ecosystems, multi-database requirements, compile-time optimization, polyglot teams

**Repository:** [fraiseql/fraiseql](https://github.com/fraiseql/fraiseql)

### Comparison

| Aspect | v1.9.16 | v2 |
|--------|---------|-----|
| **Schema in Python** | ✅ Native | ✅ Supported (1 of 16+ languages) |
| **Rust Performance** | ✅ Included | ✅ Full engine in Rust |
| **PostgreSQL Support** | ✅ Full | ✅ Full + 3 others |
| **Deployment Model** | Runtime (FastAPI) | Build-time (CLI compile) |
| **Development Experience** | Hot reload, iterative | Compile step, maximum optimization |
| **Status** | ✅ Stable | 🚀 Beta |
| **Best Migration Path** | Native Python → v2 Python | Python → any language |

> **If you're using Python:** Both versions work great! v1 for rapid iteration, v2 for compile-time guarantees and multi-DB future-proofing. Both are actively maintained.

---

## Why FraiseQL?

- ⚡ **Rust Pipeline** - 7-10x faster JSON transformation, zero Python overhead
- 🔒 **Secure by Design** - Explicit field contracts prevent data leaks
- 🤖 **AI-Native** - LLMs generate correct code on first try
- 💰 **Save $5-48K/year** - Eliminate Redis, Sentry, APM tools
- 🔄 **GraphQL Cascade** - Automatic cache updates and side effect tracking
- ✨ **Auto-populated mutations** - status, message, errors handled automatically (50-60% less boilerplate)
- 🎯 **Auto-wired query params** - `where`, `orderBy`, `limit`, `offset` added automatically to list queries
- 📝 **Auto-documentation** - Attribute docstrings become GraphQL descriptions automatically
- 🔍 **Advanced filtering** - Full-text search, JSONB queries, array operations, regex
- 🧠 **Vector search** - pgvector integration for semantic search, RAG, recommendations (6 distance operators)
- 📋 **GraphQL compliant** - 85-90% GraphQL spec compliance with advanced fragment support

---

## Is This For You?

**✅ Perfect if you:**

- Build high-performance APIs with PostgreSQL
- Want 7-10x faster JSON processing
- Need enterprise security & compliance
- Prefer database-first architecture
- Use LLMs for code generation

**❌ Consider alternatives if:**

- You need multi-database support (PostgreSQL-only)
- Building your first GraphQL API (use simpler frameworks)
- Don't use JSONB columns in PostgreSQL

---

## How It Works

**Traditional GraphQL** (slow):

```
PostgreSQL → Rows → ORM deserialize → Python objects → GraphQL serialize → JSON → Response
            ╰─── Unnecessary roundtrips (2 conversions) ───╯
```

**FraiseQL** (fast):

```
PostgreSQL → JSONB → Rust field selection → HTTP Response
           ╰─ Zero Python overhead (1 conversion) ─╯
```

### Why This Is Better

1. **No ORM Overhead** - Database returns final JSONB, Rust transforms it
2. **No N+1 Queries** - PostgreSQL composes everything in one query
3. **Security Built-In** - View defines exactly what's exposed (impossible to leak)
4. **Recursion Safe** - View structure prevents depth attacks naturally
5. **AI-Friendly** - SQL + Python are massively trained; no magic frameworks

---

## Quick Start

```bash
pip install fraiseql
fraiseql init my-api
cd my-api
fraiseql dev
```

**Your GraphQL API is live at `http://localhost:8000/graphql`** 🎉

**Next steps:**

- [5-Minute Quickstart](docs/getting-started/quickstart.md)
- [First Hour Guide](docs/getting-started/first-hour.md) - Build a complete blog API
- [Understanding FraiseQL](docs/guides/understanding-fraiseql.md) - Architecture deep-dive

---

## Real Security, Not Theatre

### The Problem (ORM-based frameworks)

```python
class User(Base):  # SQLAlchemy
    id = Column(Integer)
    email = Column(String)
    password_hash = Column(String)  # ← Sensitive!
    api_key = Column(String)        # ← Sensitive!

@strawberry.type
class UserType:
    id: int
    email: str
    # Forgot to exclude password_hash and api_key!
```

**Result:** One mistake = data leak.

### The Solution (FraiseQL)

```sql
-- PostgreSQL view defines what's exposed
CREATE VIEW v_user AS
SELECT id,
  jsonb_build_object('id', id, 'email', email) as data
FROM tb_user;
-- password_hash and api_key aren't in JSONB = impossible to leak
```

**Result:** Structure defines the contract. No way to accidentally expose fields.

---

## Chaos Engineering & Resilience Testing

FraiseQL separates testing into two workflows:

| Aspect | Standard CI/CD | Chaos Engineering |
|--------|---|---|
| **Duration** | 15-20 min | 45-60 min |
| **Purpose** | Correctness | Resilience |
| **Trigger** | Every PR | Manual/Weekly |
| **Tests** | Unit + Integration | 71 chaos scenarios |
| **Blocks Merges** | Yes ✅ | No (informational) |
| **Environment** | Lightweight | Real PostgreSQL + Docker |

**Standard CI/CD:** Validates that features work correctly
**Chaos Tests:** Validates that system recovers from failures

[→ Learn about chaos engineering strategy](docs/archive/testing/chaos-engineering-strategy.md)

---

## Advanced Features

### Specialized Type System (50+ scalar types)

```python
from fraiseql.types import EmailAddress, PhoneNumber, IPv4, Money, LTree

@fraiseql.type(sql_source="v_users")
class User:
    email: EmailAddress      # Validated emails
    phone: PhoneNumber       # International phone numbers
    ip: IPv4                 # IP addresses with subnet operations
    balance: Money           # Currency with precision
    location: LTree          # Hierarchical paths
```

### Trinity Identifiers

Three ID types for different purposes:

- **pk_user** (int): Internal DB key, not exposed
- **id** (UUID): Public API, stable, never changes
- **identifier** (str): Human-readable slug, SEO-friendly

### GraphQL Cascade

Automatic cache invalidation when mutations change related data:

```graphql
mutation {
  createPost(input: {...}) {
    post { id title }
    cascade {
      updated { __typename }     # What changed
      invalidations { queryName } # Which queries to invalidate
    }
  }
}
```

---

## Enterprise Security Features

- **KMS Integration:** Vault, AWS KMS, GCP Cloud KMS
- **Security Profiles:** STANDARD, REGULATED, RESTRICTED (government-grade)
- **SBOM Generation:** Automated compliance (FedRAMP, NIS2, HIPAA, PCI-DSS)
- **Audit Logging:** Cryptographic chain (SHA-256 + HMAC)
- **Row-Level Security:** PostgreSQL RLS integration
- **Rate Limiting:** Per-endpoint and per-GraphQL operation

[🔐 Security Configuration](docs/production/security.md)

### 🔍 Security Feature Implementation Status

| Feature | Configured | Enforced | Tested | Production Ready | Notes |
|---------|-----------|----------|--------|------------------|-------|
| **Authentication** | ✅ | ✅ | ⚠️ Partial | ⚠️ Use with caution | Rust-based JWT validation via `PyAuthProvider` |
| **RBAC Framework** | ✅ | ✅ | ⚠️ Framework only | ⚠️ Use with caution | Permission resolution complete, enforcement verification tests pending |
| **Security Profiles** | ✅ | ⚠️ Partial | ⚠️ Partial | ❌ Not production ready | TLS/rate limiting enforced; query limits/audit pending |
| **Field Filtering (Mutations)** | ✅ | ✅ | ✅ | ✅ Production ready | Full implementation (v1.9.16+) |
| **Field Filtering (APQ)** | ✅ | ✅ | ⚠️ Partial | ⚠️ Limited scope | APQ queries only |
| **Field Filtering (Queries)** | ⚠️ | ⚠️ | ⚠️ | ⚠️ Verification needed | Non-APQ query filtering status unclear |
| **Rate Limiting** | ✅ | ✅ | ✅ | ✅ Production ready | Per-endpoint and per-operation |
| **CSRF Protection** | ✅ | ✅ | ✅ | ✅ Production ready | Automatic middleware |
| **Security Headers** | ✅ | ✅ | ✅ | ✅ Production ready | Defense in depth |
| **Body Size Limits** | ✅ | ✅ | ✅ | ✅ Production ready | Configurable per profile |
| **TLS Enforcement** | ✅ | ✅ | ✅ | ✅ Production ready | Profile-based |
| **Query Depth Limits** | ✅ Config | ❌ Pending | ❌ | ❌ Not ready | Validator middleware needed |
| **Query Complexity** | ✅ Config | ❌ Pending | ❌ | ❌ Not ready | AST analysis pending |
| **Introspection Policy** | ✅ Config | ❌ Pending | ❌ | ❌ Not ready | Control logic pending |
| **Audit Logging** | ✅ Config | ❌ Pending | ❌ | ❌ Not ready | Middleware implementation needed |

**Legend:**

- ✅ Complete and verified
- ⚠️ Partial implementation or limited scope
- ❌ Not implemented or not production ready

**Roadmap:**

- **v1.9.16**: Complete security profile enforcement (Issue #225)
- **v1.9.16**: Add RBAC enforcement verification tests
- **v1.9.16**: Unified field filtering for all query types
- **v1.9.16**: Full security audit and penetration testing

> **Important**: This matrix reflects current implementation status (v1.9.16). Security features are under active development. Always verify features meet your requirements before production deployment. See [Issue #225](https://github.com/fraiseql/fraiseql-python/issues/225) for implementation progress.

---

## Cost Savings: Replace 4 Services with 1 Database

| Service | Cost | FraiseQL Approach | Savings |
|---------|------|------------------|---------|
| Redis (caching) | $50-500/mo | PostgreSQL UNLOGGED tables | $600-6,000/yr |
| Sentry (error tracking) | $300-3,000/mo | PostgreSQL error logging | $3,600-36,000/yr |
| APM Tool | $100-500/mo | PostgreSQL traces | $1,200-6,000/yr |
| **Total** | **$450-4,000/mo** | **PostgreSQL only ($50/mo)** | **$5,400-48,000/yr** |

### 📋 Software Bill of Materials (SBOM)

- **Automated generation** via `fraiseql sbom generate`
- **Global compliance**: US EO 14028, EU NIS2/CRA, PCI-DSS 4.0, ISO 27001
- **CycloneDX 1.5 format** with cryptographic signing
- **CI/CD integration** for continuous compliance

### 🔑 Key Management Service (KMS)

- **HashiCorp Vault**: Production-ready with transit engine
- **AWS KMS**: Native integration with GenerateDataKey
- **GCP Cloud KMS**: Envelope encryption support
- **Local Provider**: Development-only with warnings

### 🛡️ Security Profiles

- `STANDARD`: Default protections for general applications
- `REGULATED`: PCI-DSS/HIPAA/SOC 2 compliance
- `RESTRICTED`: Government, defence, critical infrastructure
  - 🇺🇸 FedRAMP, DoD, NIST 800-53
  - 🇪🇺 NIS2 Essential Entities, EU CRA
  - 🇨🇦 CPCSC (defence contractors)
  - 🇦🇺 Essential Eight Level 3
  - 🇸🇬 Singapore CII operators

### 📊 Observability

- OpenTelemetry tracing with sensitive data sanitization
- Security event logging
- Audit trail support

### 🔒 Advanced Security Controls

- **Rate limiting** for API endpoints and GraphQL operations
- **CSRF protection** for mutations and forms
- **Security headers** middleware for defense in depth
- **Input validation** and sanitization
- **Field-level authorization** with role inheritance
- **Row-level security** via PostgreSQL RLS

**[📋 KMS Architecture](https://github.com/fraiseql/fraiseql-python/blob/main/docs/architecture/decisions/0003-kms-architecture.md)**

---

## Code Examples

### Complete CRUD API

```python
@fraiseql.input
class CreateUserInput:
    email: str  # AI sees exact input structure
    name: str

@fraiseql.success
class UserCreated:
    user_id: str  # AI sees success response
    # Note: @success auto-injects: status, message, updated_fields, id

@fraiseql.error
class ValidationError:
    error: str    # AI sees failure cases
    code: str = "VALIDATION_ERROR"

@fraiseql.mutation(function="fn_create_user", schema="public")
class CreateUser:
    input: CreateUserInput
    success: UserCreated
    failure: ValidationError  # Note: Use 'failure' field, not '@failure' decorator

# That's it! FraiseQL automatically:
# 1. Calls public.fn_create_user(input) with input as dict
# 2. Parses JSONB result into UserCreated or ValidationError
```

### Why AI Loves This

- ✅ **SQL + Python** - Massively trained languages (no proprietary DSLs)
- ✅ **JSONB everywhere** - Clear data structures, obvious contracts
- ✅ **Database functions** - Complete context in one file
- ✅ **Explicit logging** - AI can trace execution without debugging
- ✅ **No abstraction layers** - What you see is what executes

**Real Impact:** Claude Code, GitHub Copilot, and ChatGPT generate correct FraiseQL code on first try.

---

## 📖 Core Concepts

**New to FraiseQL?** Understanding these core concepts will help you make the most of the framework:

**[📚 Concepts & Glossary](https://github.com/fraiseql/fraiseql-python/blob/main/docs/core/concepts-glossary.md)** - Essential terminology and mental models:

- **CQRS Pattern** - Separate read models (views) from write models (functions)
- **Trinity Identifiers** - Three-tier ID system (`pk_*`, `id`, `identifier`) for performance and UX
- **JSONB Views** - PostgreSQL composes data once, eliminating N+1 queries
- **Database-First Architecture** - Start with PostgreSQL, GraphQL follows
- **Explicit Sync Pattern** - Table views (`tv_*`) for complex queries

**Quick links:**

- [Understanding FraiseQL](https://github.com/fraiseql/fraiseql-python/blob/main/docs/guides/understanding-fraiseql.md) - 10-minute architecture overview
- [Database API](https://github.com/fraiseql/fraiseql-python/blob/main/docs/core/database-api.md) - Connection pooling and query execution
- [Types and Schema](https://github.com/fraiseql/fraiseql-python/blob/main/docs/core/types-and-schema.md) - Complete type system guide
- [Filter Operators](https://github.com/fraiseql/fraiseql-python/blob/main/docs/advanced/filter-operators.md) - Advanced PostgreSQL filtering (arrays, full-text search, JSONB, regex)

---

## ✨ See How Simple It Is

### Complete CRUD API in 20 Lines

```python
from uuid import UUID
from fraiseql import type, query, mutation, input, success

@fraiseql.type(sql_source="v_note", jsonb_column="data")
class Note:
    id: int
    title: str
    content: str | None

@fraiseql.query
async def notes(info) -> list[Note]:
    return await info.context["db"].find("v_note")

@fraiseql.query
async def note(info, id: UUID) -> Note | None:
    """Get a note by ID."""
    db = info.context["db"]
    return await db.find_one("v_note", id=id)

# Step 3: Define mutations
@fraiseql.input
class CreateNoteInput:
    title: str
    content: str | None = None

@fraiseql.mutation
class CreateNote:
    input: CreateNoteInput
    success: Note

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[Note],
    queries=[notes],
    mutations=[CreateNote]
)
```

### Database-First Pattern

```sql
-- PostgreSQL view (composable, no N+1)
CREATE VIEW v_user AS
SELECT id,
  jsonb_build_object(
    'id', id,
    'name', name,
    'email', email,
    'posts', (
      SELECT jsonb_agg(...)
      FROM tb_post p
      WHERE p.user_id = tb_user.id
    )
  ) as data
FROM tb_user;
```

```python
# Python type mirrors the view
@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: int
    name: str
    email: str
    posts: list[Post]  # Nested relations! No N+1 queries!

# Step 3: Query it
@fraiseql.query
async def users(info) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user")
```

**No ORM. No complex resolvers. PostgreSQL composes data, Rust transforms it.**

### Mutations with Business Logic

```sql
CREATE OR REPLACE FUNCTION fn_publish_post(p_post_id UUID) RETURNS JSONB AS $$
DECLARE
    v_post RECORD;
BEGIN
    -- Get post with user info (Trinity pattern: JOIN on pk_user)
    SELECT p.*, u.email as user_email
    INTO v_post
    FROM tb_post p
    JOIN tb_user u ON p.fk_user = u.pk_user  -- ✅ Trinity: INTEGER FK to pk_user
    WHERE p.id = p_post_id;

    -- Validate post exists
    IF NOT FOUND THEN
        RETURN jsonb_build_object('success', false, 'error', 'Post not found');
    END IF;

    -- Validate not already published
    IF v_post.published_at IS NOT NULL THEN
        RETURN jsonb_build_object('success', false, 'error', 'Post already published');
    END IF;

    -- Update post
    UPDATE tb_post
    SET published_at = NOW()
    WHERE id = p_post_id;

    -- Sync projection table
    PERFORM fn_sync_tv_post(p_post_id);

    -- Log event
    INSERT INTO audit_log (action, details)
    VALUES ('post_published', jsonb_build_object('post_id', p_post_id, 'user_email', v_post.user_email));

    -- Return success
    RETURN jsonb_build_object('success', true, 'post_id', p_post_id);
END;
$$ LANGUAGE plpgsql;
```

**Business logic, validation, logging - all in the database function. Crystal clear for humans and AI.**

### Selective CASCADE Querying

Request only the CASCADE data you need:

```graphql
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    post { id title }

    # Option 1: No CASCADE (smallest payload)
    # Just omit the cascade field

    # Option 2: Metadata only
    cascade {
      metadata { affectedCount }
    }

    # Option 3: Full CASCADE
    cascade {
      updated { __typename id entity }
      deleted { __typename id }
      invalidations { queryName }
      metadata { affectedCount }
    }
  }
}
```

Performance: Not requesting CASCADE reduces response size by 2-10x.

---

## 💰 In PostgreSQL Everything

Replace 4 services with 1 database.

### Cost Savings Calculator

| Traditional Stack | FraiseQL Stack | Annual Savings |
|-------------------|----------------|----------------|
| PostgreSQL: $50/mo | PostgreSQL: $50/mo | - |
| **Redis Cloud:** $50-500/mo | ✅ **In PostgreSQL** | **$600-6,000/yr** |
| **Sentry:** $300-3,000/mo | ✅ **In PostgreSQL** | **$3,600-36,000/yr** |
| **APM Tool:** $100-500/mo | ✅ **In PostgreSQL** | **$1,200-6,000/yr** |
| **Total: $500-4,050/mo** | **Total: $50/mo** | **$5,400-48,000/yr** |

### How It Works

**Caching (Replaces Redis)**

```python
from fraiseql.caching import PostgresCache

cache = PostgresCache(db_pool)
await cache.set("user:123", user_data, ttl=3600)

# Uses PostgreSQL UNLOGGED tables
# - No WAL overhead = fast writes
# - Shared across instances
# - TTL-based expiration
# - Pattern-based deletion
```

**Error Tracking (Replaces Sentry)**

```python
from fraiseql.monitoring import init_error_tracker

tracker = init_error_tracker(db_pool, environment="production")
await tracker.capture_exception(error, context={...})

# Features:
# - Automatic error fingerprinting and grouping
# - Full stack trace capture
# - OpenTelemetry trace correlation
# - Custom notifications (Email, Slack, Webhook)
```

**Observability (Replaces APM)**

```sql
-- All traces and metrics stored in PostgreSQL
SELECT * FROM monitoring.traces
WHERE error_id = 'error-123'
  AND trace_id = 'trace-xyz';
```

**Grafana Dashboards**
Pre-built dashboards in `grafana/` query PostgreSQL directly:

- Error monitoring dashboard
- Performance metrics dashboard
- OpenTelemetry traces dashboard

### Operational Benefits

- ✅ **70% fewer services** to deploy and monitor
- ✅ **One database to backup** (not 4 separate systems)
- ✅ **No Redis connection timeouts** or cluster issues
- ✅ **No Sentry quota surprises** or rate limiting
- ✅ **ACID guarantees** for everything (no eventual consistency)
- ✅ **Self-hosted** - full control, no vendor lock-in

---

## 🏗️ Architecture Deep Dive

### Rust-First Execution

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   GraphQL       │ →  │   PostgreSQL     │ →  │   Rust          │
│   Request       │    │   JSONB Query    │    │   Transform     │
│                 │    │                  │    │   (7-10x faster)│
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                                        ↓
                                               ┌─────────────────┐
                                               │   FastAPI       │
                                               │   HTTP Response │
                                               └─────────────────┘
```

**Unified path for all queries:**

1. **GraphQL query** arrives at FastAPI
2. **Python resolver** calls PostgreSQL view/function
3. **PostgreSQL** returns pre-composed JSONB
4. **Rust pipeline** transforms JSONB based on GraphQL selection
5. **FastAPI** returns bytes directly (zero Python serialization)

### CQRS Pattern

FraiseQL implements Command Query Responsibility Segregation:

```
┌─────────────────────────────────────┐
│         GraphQL API                 │
├──────────────────┬──────────────────┤
│   QUERIES        │   MUTATIONS      │
│   (Reads)        │   (Writes)       │
├──────────────────┼──────────────────┤
│  v_* views       │  fn_* functions  │
│  tv_* tables     │  tb_* tables     │
│  JSONB ready     │  Business logic  │
└──────────────────┴──────────────────┘
```

**Queries use views:**

- `v_*` - Real-time views with JSONB computation
- `tv_*` - Denormalized tables with generated JSONB columns (for complex queries)

**Mutations use functions:**

- `fn_*` - Business logic, validation, side effects
- `tb_*` - Base tables for data storage

**[📊 Detailed Architecture Diagrams](https://github.com/fraiseql/fraiseql-python/blob/main/docs/guides/understanding-fraiseql.md)**

### Key Innovations

**1. Exclusive Rust Pipeline**

- PostgreSQL → Rust → HTTP (no Python JSON processing)
- 7-10x faster JSON transformation vs Python
- No GIL contention, compiled performance

**2. JSONB Views**

- Database composes data once
- Rust selects fields based on GraphQL query
- No N+1 query problems

**3. Table Views (tv_*)**

```sql
-- Denormalized JSONB table with explicit sync
CREATE TABLE tv_user (
    id INT PRIMARY KEY,
    data JSONB NOT NULL,  -- Regular column, not generated
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Sync function populates tv_* from v_* view
CREATE FUNCTION fn_sync_tv_user(p_user_id INT) RETURNS VOID AS $$
BEGIN
    INSERT INTO tv_user (id, data)
    SELECT id, data FROM v_user WHERE id = p_user_id
    ON CONFLICT (id) DO UPDATE SET
        data = EXCLUDED.data,
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- Mutations call sync explicitly
CREATE FUNCTION fn_create_user(p_name TEXT) RETURNS JSONB AS $$
DECLARE v_user_id INT;
BEGIN
    INSERT INTO tb_user (name) VALUES (p_name) RETURNING id INTO v_user_id;
    PERFORM fn_sync_tv_user(v_user_id);  -- ← Explicit sync call
    RETURN (SELECT data FROM tv_user WHERE id = v_user_id);
END;
$$ LANGUAGE plpgsql;
```

Benefits: Instant lookups, embedded relations, explicitly synchronized

**4. Zero-Copy Response**

- Direct RustResponseBytes to FastAPI
- No Python serialization overhead
- Optimal for high-throughput APIs

---

## 🎯 How FraiseQL Is Different

### Execution Path Comparison

| Framework | Data Flow | JSON Processing | Recursion Protection | Security Model |
|-----------|-----------|-----------------|----------------------|----------------|
| **FraiseQL** | PostgreSQL JSONB → Rust → HTTP | ✅ Rust (compiled) | ✅ View-enforced | ✅ Explicit contracts |
| Strawberry + SQLAlchemy | PostgreSQL → ORM → Python dict → JSON | ❌ Python (2 steps) | ⚠️ Middleware required | ❌ ORM over-fetching risk |
| Hasura | PostgreSQL → Haskell → JSON | ⚠️ Haskell | ⚠️ Middleware required | ⚠️ Complex permission system |
| PostGraphile | PostgreSQL → Node.js → JSON | ⚠️ JavaScript | ⚠️ Middleware required | ⚠️ Plugin-based |

### FraiseQL's Unique Advantages

- ✅ **Database returns final structure** (JSONB views)
- ✅ **Rust handles field selection** (compiled performance)
- ✅ **No Python in hot path** (zero serialization overhead)
- ✅ **No ORM abstraction** (SQL functions are business logic)
- ✅ **Built-in recursion protection** (view defines max depth, no middleware needed)
- ✅ **Secure by design** (explicit field contracts prevent data leaks)
- ✅ **AI-readable** (clear contracts, full context visible)
- ✅ **PostgreSQL-native** (caching, monitoring, APQ in one database)

---

## 🎯 Advanced Features

### Automatic Persisted Queries (APQ)

Enterprise-grade APQ with pluggable storage backends:

```python
from fraiseql import FraiseQLConfig

# Memory backend (zero configuration)
config = FraiseQLConfig(apq_storage_backend="memory")

# PostgreSQL backend (multi-instance coordination)
config = FraiseQLConfig(
    apq_storage_backend="postgresql",
    apq_storage_schema="apq_cache"
)
```

**How it works:**

1. Client sends query hash instead of full query
2. FraiseQL checks storage backend for cached query
3. PostgreSQL → Rust → HTTP (same fast path)
4. Bandwidth reduction with large queries

**[⚡ APQ Details](https://github.com/fraiseql/fraiseql-python/blob/main/docs/diagrams/apq-cache-flow.md)**

### Specialized Type System

Advanced operators for network types, hierarchical data, ranges, and nested arrays:

```graphql
query {
  servers(where: {
    ipAddress: { eq: "192.168.1.1" }          # → ::inet casting
    port: { gt: 1024 }                        # → ::integer casting
    location: { ancestor_of: "US.CA" }        # → ltree operations
    dateRange: { overlaps: "[2024-01-01,2024-12-31)" }

    # Nested array filtering with logical operators
    printServers(where: {
      AND: [
        { operatingSystem: { in: ["Linux", "Windows"] } }
        { OR: [
            { nTotalAllocations: { gte: 100 } }
            { NOT: { ipAddress: { isnull: true } } }
          ]
        }
      ]
    }) {
      hostname operatingSystem
    }
  }) {
    id name ipAddress port
  }
}
```

**50+ Specialized Scalar Types:**

**Financial & Trading:**

- CUSIP, ISIN, SEDOL, MIC, LEI - Security identifiers
- Money, Percentage, ExchangeRate - Financial values
- CurrencyCode, StockSymbol - Trading symbols

**Network & Infrastructure:**

- IPv4, IPv6, CIDR, MACAddress - Network addresses with subnet operations
- Hostname, DomainName, Port, EmailAddress - Internet identifiers
- APIKey, HashSHA256 - Security tokens

**Geospatial & Location:**

- Coordinate, Latitude, Longitude - Geographic coordinates with distance calculations
- PostalCode, Timezone - Location data

**Business & Logistics:**

- ContainerNumber, FlightNumber, TrackingNumber, VIN - Asset identifiers
- IBAN, LicensePlate - Financial & vehicle identifiers
- PhoneNumber, LocaleCode, LanguageCode - Contact & localization

**Technical & Data:**

- UUID, JSON, Date, DateTime, Time, DateRange - Standard types with validation
- LTree - Hierarchical data with ancestor/descendant queries
- SemanticVersion, Color, MIMEType, File, Image - Specialized formats
- HTML, Markdown - Rich text content

**Advanced Filtering:** Full-text search, JSONB queries, array operations, regex, vector similarity search on all types

#### Scalar Type Usage Examples

```python
from fraiseql import type
from fraiseql.types import (
    EmailAddress, PhoneNumber, Money, Percentage,
    CUSIP, ISIN, IPv4, MACAddress, LTree, DateRange
)

@fraiseql.type(sql_source="v_financial_data")
class FinancialRecord:
    id: int
    email: EmailAddress           # Validated email addresses
    phone: PhoneNumber           # International phone numbers
    balance: Money               # Currency amounts with precision
    margin: Percentage           # Percentages (0.00-100.00)
    security_id: CUSIP | ISIN    # Financial instrument identifiers

@fraiseql.type(sql_source="v_network_device")
class NetworkDevice:
    id: int
    ip_address: IPv4             # IPv4 addresses with subnet operations
    mac_address: MACAddress      # MAC addresses with validation
    location: LTree              # Hierarchical location paths
    maintenance_window: DateRange # Date ranges with overlap queries
```

```graphql
# Advanced filtering with specialized types
query {
  financialRecords(where: {
    balance: { gte: "1000.00" }           # Money comparison
    margin: { between: ["5.0", "15.0"] }   # Percentage range
    security_id: { eq: "037833100" }       # CUSIP validation
  }) {
    id balance margin security_id
  }

  networkDevices(where: {
    ip_address: { inSubnet: "192.168.1.0/24" }  # CIDR operations
    location: { ancestor_of: "US.CA.SF" }       # LTree hierarchy
    maintenance_window: { overlaps: "[2024-01-01,2024-12-31)" }
  }) {
    id ip_address location
  }
}
```

**[📖 Nested Array Filtering Guide](https://github.com/fraiseql/fraiseql-python/blob/main/docs/guides/nested-array-filtering.md)**

### Enterprise Security

```python
from fraiseql import authorized

@fraiseql.authorized(roles=["admin", "editor"])
@fraiseql.mutation
class DeletePost:
    """Only admins and editors can delete posts."""
    input: DeletePostInput
    success: DeleteSuccess
    failure: PermissionDenied

# Features:
# - Field-level authorization with role inheritance
# - Row-level security via PostgreSQL RLS
# - Unified audit logging with cryptographic chain (SHA-256 + HMAC)
# - Multi-tenant isolation
# - Rate limiting and CSRF protection
```

### Trinity Identifiers

Three types of identifiers per entity for different purposes:

```python
@fraiseql.type(sql_source="v_post")
class Post(TrinityMixin):
    """
    Trinity Pattern:
    - pk_post (int): Internal SERIAL key (NOT exposed, only in database)
    - id (UUID): Public API key (exposed, stable)
    - identifier (str): Human-readable slug (exposed, SEO-friendly)
    """

    # GraphQL exposed fields
    id: UUID                  # Public API (stable, secure)
    identifier: str | None    # Human-readable (SEO-friendly, slugs)
    title: str
    content: str
    # ... other fields

    # pk_post is NOT a field - accessed via TrinityMixin.get_internal_pk()
```

**Why three?**

- **pk_\*:** Fast integer joins (PostgreSQL only, never in GraphQL schema)
- **id:** Public API stability (UUID, exposed, never changes)
- **identifier:** Human-friendly URLs (exposed, SEO, readability)

---

## 🚀 Get Started in 5 Minutes

```bash
# Install
pip install fraiseql

# Create project
fraiseql init my-api
cd my-api

# Setup database
createdb my_api
psql my_api < schema.sql

# Start server
fraiseql dev
```

**Your GraphQL API is live at <http://localhost:8000/graphql>** 🎉

### Next Steps

- **📚 [First Hour Guide](https://github.com/fraiseql/fraiseql-python/blob/main/docs/getting-started/first-hour.md)** - Build a complete blog API (60 minutes, hands-on)
- **🧠 [Understanding FraiseQL](https://github.com/fraiseql/fraiseql-python/blob/main/docs/guides/understanding-fraiseql.md)** - Architecture deep dive (10 minute read)
- **⚡ [5-Minute Quickstart](https://github.com/fraiseql/fraiseql-python/blob/main/docs/getting-started/quickstart.md)** - Copy, paste, run
- **📖 [Full Documentation](https://github.com/fraiseql/fraiseql-python/tree/main/docs)** - Complete guides and references

### Prerequisites

- **Python 3.13+** (required for Rust pipeline integration and advanced type features)
- **PostgreSQL 13+**

**[📖 Detailed Installation Guide](docs/getting-started/installation.md)** - Platform-specific instructions, troubleshooting

---

## 🚦 Is FraiseQL Right for You?

### ✅ Perfect For

- **PostgreSQL-first teams** already using PostgreSQL extensively
- **Performance-critical APIs** requiring efficient data access
- **Multi-tenant SaaS** with per-tenant isolation needs
- **Cost-conscious startups** ($5-48K annual savings vs traditional stack)
- **AI-assisted development** teams using Claude/Copilot/ChatGPT
- **Operational simplicity** - one database for everything
- **Self-hosted infrastructure** - full control, no vendor lock-in

### ❌ Consider Alternatives

- **Multi-database support** - FraiseQL is PostgreSQL-specific
- **Simple CRUD APIs** - Traditional REST may be simpler
- **Non-PostgreSQL databases** - FraiseQL requires PostgreSQL
- **Microservices** - Better for monolithic or database-per-service

---

## 🛠️ CLI Commands

```bash
# Project management
fraiseql init <name>           # Create new project
fraiseql dev                   # Development server with hot reload
fraiseql check                 # Validate schema and configuration

# Code generation
fraiseql generate schema       # Export GraphQL schema
fraiseql generate types        # Generate TypeScript definitions

# Database utilities
fraiseql sql analyze <query>   # Analyze query performance
fraiseql sql explain <query>   # Show PostgreSQL execution plan
```

---

## Learn More

- **[Full Documentation](https://github.com/fraiseql/fraiseql-python/tree/main/docs)** - Comprehensive guides
- **[Architecture Decisions](https://github.com/fraiseql/fraiseql-python/tree/main/docs/architecture)** - Why we built it this way
- **[Performance Guide](https://github.com/fraiseql/fraiseql-python/blob/main/docs/performance/index.md)** - Optimization strategies
- **[Examples](https://github.com/fraiseql/fraiseql-python/tree/main/examples)** - Real-world applications

---

## Contributing

```bash
git clone https://github.com/fraiseql/fraiseql-python
cd fraiseql-python && make setup-dev
prek install  # 7-10x faster than pre-commit
```

[→ Contributing Guide](CONTRIBUTING.md)

---

## About

FraiseQL is created by **Lionel Hamayon** ([@evoludigit](https://github.com/evoludigit)).

**The Idea:** What if PostgreSQL returned JSON directly instead of Python serializing it? No ORM. No N+1 queries. No Python overhead. Just Rust transforming JSONB to HTTP.

**The Result:** A GraphQL framework that's 7-10x faster and designed for the LLM era.

---

## License

MIT License - see [LICENSE](LICENSE)

---

## 📋 Project Navigation

### FraiseQL Ecosystem

| Project | Version | Repository | Status | Best For |
|---------|---------|-----------|--------|----------|
| **fraiseql-python** (v1) | v1.9.16 | [fraiseql/fraiseql-python](https://github.com/fraiseql/fraiseql-python) | ✅ Stable | Python teams, rapid iteration |
| **fraiseql** (v2) | v2.0.0-alpha.2 | [fraiseql/fraiseql](https://github.com/fraiseql/fraiseql) | 🚀 Beta | Multi-language, multi-database |

**This Repository:** `fraiseql-python` (v1.9.16 - Python-based with Rust pipeline)

### Quick Navigation

**New to FraiseQL?**

- Start here: **[First Hour Guide](https://github.com/fraiseql/fraiseql-python/blob/main/docs/getting-started/first-hour.md)** (60 min, hands-on)
- Architecture overview: **[Understanding FraiseQL](https://github.com/fraiseql/fraiseql-python/blob/main/docs/guides/understanding-fraiseql.md)** (10 min read)
- Project structure: **[Strategic Overview](https://github.com/fraiseql/fraiseql-python/blob/main/docs/strategic/PROJECT_STRUCTURE.md)**

**Exploring v2?**

- v2 Repository: **[fraiseql/fraiseql](https://github.com/fraiseql/fraiseql)**
- v2 Documentation: **[fraiseql.readthedocs.io](https://fraiseql.readthedocs.io)**

**Troubleshooting:**

- **[Complete Version Roadmap](https://github.com/fraiseql/fraiseql-python/blob/main/dev/audits/version-status.md)** - Version status and feature matrix

---

## 🚀 Get Started Now

**Ready to build the most efficient GraphQL API in Python?**

```bash
pip install fraiseql && fraiseql init my-api
```

📚 Documentation: [github.com/fraiseql/fraiseql-python](https://github.com/fraiseql/fraiseql-python)

🚀 **PostgreSQL → Rust → Production**

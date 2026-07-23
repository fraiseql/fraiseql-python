---
title: FraiseQL Versioning Strategy
description: How FraiseQL v1 versions its Python package and your runtime-generated GraphQL schema.
keywords: ["versioning", "semver", "deprecation", "schema-evolution", "backward-compatibility"]
tags: ["documentation", "reference"]
---

# FraiseQL Versioning Strategy

**Status:** Reference
**Audience:** Application developers, platform engineers, operators

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Semantic Versioning (SemVer 2.0.0)](#1-semantic-versioning-semver-200)
3. [Breaking Change Policy](#2-breaking-change-policy)
4. [Deprecation Policy](#3-deprecation-policy)
5. [Schema Versioning](#4-schema-versioning)
6. [GraphQL API Versioning](#5-graphql-api-versioning)
7. [Error Code Versioning](#6-error-code-versioning)
8. [Running Multiple Versions](#7-running-multiple-versions)
9. [Upgrade Path](#8-upgrade-path)
10. [Client Versioning & Compatibility](#9-client-versioning--compatibility)
11. [Version Communication](#10-version-communication)
12. [Support & Long-Term Maintenance](#11-support--long-term-maintenance)
13. [Version Decision Tree](#12-version-decision-tree)
14. [Versioning Best Practices](#13-versioning-best-practices)
15. [Examples](#14-examples)
16. [Summary & Quick Reference](#15-summary--quick-reference)
17. [Appendix: Version Checking](#16-appendix-version-checking)

---

## Executive Summary

FraiseQL uses **semantic versioning (MAJOR.MINOR.PATCH)** with explicit breaking-change
policies to balance new features with stability. Versioning applies to two distinct things:

1. **The FraiseQL Python package** — published on PyPI as `fraiseql`, versioned with SemVer.
   The current release is `1.23.11`.
2. **Your GraphQL schema** — generated at application startup from your `@fraiseql.type`,
   `@fraiseql.query`, and `@fraiseql.mutation` decorators. This is *your* contract with
   *your* clients, and you evolve it on your own cadence.

These two are independent. Upgrading the FraiseQL package (a backward-compatible MINOR or
PATCH release) does not change the GraphQL schema your clients see. Likewise, evolving your
own schema does not require a new FraiseQL release.

**Core principle**: FraiseQL is a *runtime* framework. There is no compiled schema, no build
artifact, and no schema file to version. Your schema is assembled in memory at startup from
your Python code, every time the app boots. Backward-compatibility decisions are therefore
about API surface — package APIs on one side, GraphQL field/type shape on the other.

---

## 1. Semantic Versioning (SemVer 2.0.0)

The FraiseQL package follows semantic versioning with three-component version numbers.

### 1.1 Version Format

```text
MAJOR.MINOR.PATCH
  |      |      |
  |      |      └── Bug fixes and patches (no breaking changes)
  |      └────────── Features and improvements (backward-compatible)
  └──────────────── Breaking changes (incompatible with prior MAJOR version)
```

### 1.2 Version Examples

```text
1.0.0    → First stable release of the 1.x line
1.1.0    → Add a new feature, backward-compatible with 1.0.x
1.1.1    → Bug fix, backward-compatible with 1.1.0
1.23.11  → Current release: many backward-compatible features and fixes since 1.0.0
```

Within the entire `1.x` line, your code that imports and uses FraiseQL keeps working.
Features are added in MINOR releases; bugs are fixed in PATCH releases; neither breaks you.

### 1.3 Pre-release Versions

For beta testing and early access, FraiseQL may publish pre-release versions:

```text
1.24.0-beta.1    → Beta version, may still change before release
1.24.0-rc.1      → Release candidate, likely stable
1.24.0-rc.2      → Second RC before general availability
1.24.0           → General availability (stable)
```

**Stability commitment:**

- Never pin a pre-release version in production.
- Pre-releases are for testing and feedback.
- A migration note ships before any release that changes public behavior.
- Notable changes are announced in the changelog before they go stable.

> **Note on "v2".** FraiseQL v2 is a *separate product* in a separate repository, not a future
> major release of this package. This document covers FraiseQL v1 only. There is no
> v1 → v2 migration path described here; the two are independent codebases.

---

## 2. Breaking Change Policy

### 2.1 What Constitutes a Breaking Change

A breaking change is **any modification that requires code changes from people who use
FraiseQL or who call your GraphQL API**. For the package, breaking changes trigger a MAJOR
version bump. For your GraphQL schema, the same principles tell you whether a schema edit
will break your clients.

#### 2.1.1 GraphQL Schema Breaking Changes

These are decisions *you* make when you edit your decorated types and resolvers. They break
existing clients and should be treated like a major change to your API.

**Removals** (break clients):

```graphql
# BREAKING: Remove a field
# before
type User {
  id: ID!
  name: String!
  email: String   # removing this field
}

# after — clients that selected `email` now fail
type User {
  id: ID!
  name: String!
}
```

**Nullability and type changes** (break clients):

```graphql
# BREAKING: Change return type / nullability
# before
type Query {
  user(id: ID!): User      # may return null
}

# after returns User! (non-null)
# Clients that handled null must change their code
```

**Argument changes** (break clients):

```graphql
# BREAKING: Add a required argument
# before
type Query {
  posts: [Post!]!
}

# after
type Query {
  posts(limit: Int!): [Post!]!   # new required argument
}
```

**Input type changes** (break clients):

```graphql
# BREAKING: Add a required field to an input
# before
input CreateUserInput {
  name: String!
  email: String
}

# after
input CreateUserInput {
  name: String!
  email: String!      # now required
  roles: [String!]!   # new required field
}
```

**Enum value removal** (break clients):

```graphql
# BREAKING: Remove an enum value
# before
enum Role {
  ADMIN
  USER
  GUEST
}

# after removes GUEST — clients that send or match GUEST break
```

#### 2.1.2 Filter Operator Changes

FraiseQL exposes a set of filter operators on query arguments. Removing or re-defining one is
a breaking change for clients that rely on it.

**Removing an operator** (breaks clients):

```python
# BREAKING: Remove a supported operator
# Queries that use the removed operator fail. Clients must rewrite
# those queries (for example, switch from `regex` to `contains`).
```

**Changing operator semantics** (breaks clients):

```python
# BREAKING: Change operator behaviour
# Example: an `in` operator that was case-sensitive becomes case-insensitive.
# Queries that relied on case-sensitivity now return different results.
```

#### 2.1.3 Authorization Changes

**Removing an authorization rule** (breaking, with security impact):

```python
# BREAKING: Remove field-level masking
# Before: User.ssn masked for non-admins.
# After: masking removed (now exposed to everyone).
# Security expectations break; this is a serious change.
```

**Adding a row-level filter that changes results** (breaking):

```python
# BREAKING: Add row-level security that filters results
# Before: query returns all posts.
# After: only the current user's posts are returned.
# Clients that expected all posts now get fewer results.
```

#### 2.1.4 Error Code Changes

**Removing an error code** (breaks clients):

```python
# BREAKING: An error code your clients handle is removed.
# Before: a request fails with E_VALIDATION_EMAIL_001.
# After: a different code or format is returned.
# Client error handling breaks.
```

**Changing what an error code means** (breaks clients):

```python
# BREAKING: Re-define an error code.
# Before: E_DB_DEADLOCK means "deadlock — retry with backoff".
# After: the same code means "connection timeout".
# Client retry logic becomes wrong.
```

**Note**: Treat your error codes as part of your API contract — they should not change
meaning once clients depend on them.

#### 2.1.5 Type System Changes

**Removing a custom scalar** (breaks clients):

```graphql
# BREAKING: Remove a custom scalar
# before
scalar DateTime
scalar JSON
type Event {
  timestamp: DateTime!
  metadata: JSON
}

# after removes DateTime — clients that select `timestamp` break
```

**Changing scalar serialization** (breaks clients):

```graphql
# BREAKING: Change how a value is serialized
# Before: UUID serialized as "f47ac10b-58cc-4372-a567-0e02b2c3d479".
# After: UUID serialized without hyphens.
# Clients that parse the string representation break.
```

### 2.2 Non-Breaking Changes

These changes are safe and do not break existing clients.

#### 2.2.1 Safe Additions

**Adding new fields** (additive, safe):

```graphql
# SAFE: Add optional fields
# before
type User {
  id: ID!
  name: String!
  email: String
}

# after
type User {
  id: ID!
  name: String!
  email: String
  phone: String           # new optional field
  verifiedAt: DateTime    # new optional field
}
```

**Adding new types** (additive, safe):

```graphql
# SAFE: Add a new type and query
# Existing types (User, Post, Comment) are untouched.
# A new Product type and `products` query are added.
# Existing clients are unaffected.
```

**Adding new enum values** (safe when clients ignore unknown values):

```graphql
# SAFE: Add an enum value
# before
enum Role {
  ADMIN
  USER
}

# after
enum Role {
  ADMIN
  USER
  SUPER_ADMIN   # new value
}

# Clients that do not use SUPER_ADMIN are unaffected.
```

**Adding optional arguments** (additive, safe):

```graphql
# SAFE: Add optional arguments
# before
type Query {
  posts: [Post!]!
}

# after
type Query {
  posts(limit: Int, offset: Int): [Post!]!
}

# Existing queries with no arguments still work.
```

**Adding a new filter operator** (additive, safe):

```python
# SAFE: Add a new operator.
# Existing queries are unaffected; clients can opt into the new operator.
```

**Adding field-level masking** (restricts data, safe):

```python
# SAFE: Mask a field that was previously visible.
# Before: User.ssn visible to everyone.
# After: User.ssn masked for non-admins (returns null for regular users).
# Admin clients still see it; regular clients see null, which is safe.
```

**Making authorization stricter** (fewer results, safe):

```python
# SAFE: Make row-level security more restrictive.
# Before: query returns posts from all users.
# After: query returns only the current user's posts.
# Fewer results, stricter access — more secure, not less.
```

**Adding new error codes** (safe when clients ignore unknown codes):

```python
# SAFE: Add a new error code category.
# Existing handling still works; clients can add handling for new codes.
```

#### 2.2.2 Safe Modifications (PATCH-level)

**Performance improvements** (safe):

```text
SAFE: A query runs faster with identical results.
Behaviour unchanged; only performance improves.
```

**Bug fixes** (safe):

```text
SAFE: Fix incorrect behaviour to match the documented specification.
Example: the `in` operator was wrongly case-sensitive; it is fixed to be
case-insensitive per spec. This is a bug fix, not a breaking change.
```

**Documentation updates** (safe):

```text
SAFE: Documentation corrections with no code changes.
```

**Internal refactoring** (safe):

```text
SAFE: Rewrite internals (including the optional Rust hot path in
fraiseql_rs) without changing externally observable behaviour.
```

---

## 3. Deprecation Policy

### 3.1 Deprecation Lifecycle

A clean deprecation has three phases before anything is removed:

```text
ANNOUNCEMENT (a MINOR release)
     ↓
DEPRECATION  (kept working across subsequent MINOR releases, with warnings)
     ↓
REMOVAL      (the next MAJOR release)
```

Nothing that clients or users depend on is removed without first going through an
announced deprecation period.

### 3.2 Deprecation Timeline

Give people enough notice. A practical pattern within the `1.x` line:

```text
1.20.0  → Announce deprecation of a feature; it still works, warnings shown
1.21.0  → Still works, warnings continue
1.22.0  → Still works, warnings continue
1.23.0  → Still works, warnings continue
2.0.0   → Feature removed (separate MAJOR release)
```

### 3.3 Deprecation Announcement Format

When something is deprecated, the changelog should state:

```markdown
### Deprecated

- **`regex` filter operator**: Use the `contains` operator instead.
  - **Reason**: Regex carries performance overhead; most cases are better served by `contains`.
  - **Migration**: Replace `{name: {regex: "/pattern/"}}` with `{name: {contains: "pattern"}}`.
  - **Timeline**: Deprecated in this MINOR release; removal in the next MAJOR release.
```

### 3.4 Deprecation Warning at Runtime

When a deprecated feature is used, the GraphQL response can carry a warning in `extensions`:

```graphql
# Query uses a deprecated filter operator
query GetPosts {
  posts(where: { title: { regex: "/draft/" } }) {
    id
    title
  }
}
```

**Response includes a deprecation warning:**

```json
{
  "data": {
    "posts": []
  },
  "extensions": {
    "deprecations": [
      {
        "message": "Operator 'regex' is deprecated. Use 'contains' instead.",
        "code": "W_DEPRECATED_OPERATOR_REGEX",
        "location": { "line": 2, "column": 45 }
      }
    ]
  }
}
```

### 3.5 Migration Guidance

For each deprecation, communicate:

1. **Why** — the reason for the change.
2. **Impact** — who and what is affected.
3. **How to migrate** — step-by-step instructions.
4. **Timeline** — when it is removed.
5. **Help** — where to get support.

---

## 4. Schema Versioning

### 4.1 Your Schema Is Generated at Runtime

You define your schema in Python with decorators. At application startup FraiseQL reads those
decorators and builds an in-memory GraphQL schema — there is no compile step and no schema
artifact on disk. Versioning your schema therefore means versioning *your Python code* and
managing the compatibility of the GraphQL surface it produces.

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: str | None = None
```

You decide your own schema version (often the same number as your application release). It is
**independent of the FraiseQL package version**: a backward-compatible FraiseQL upgrade does
not change the GraphQL schema your decorators produce.

### 4.2 Schema Backward Compatibility

Use the breaking vs. non-breaking rules from [Section 2](#2-breaking-change-policy) to keep
schema edits safe.

**Backward-compatible edit (additive):**

```python
import fraiseql
from datetime import datetime
from fraiseql.types import ID

# v1 of your schema
@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: str | None = None

# v1.1 of your schema — additive, no clients break
@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: str | None = None
    phone: str | None = None              # new optional field
    created_at: datetime | None = None    # new optional field
```

When you add a field, also expose it in the corresponding `v_`/`tv_` PostgreSQL view's `data`
JSONB so the resolver can return it.

**Breaking schema edit (requires planning and client coordination):**

```python
import fraiseql
from fraiseql.types import ID

# before
@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: str | None = None

# after — `email` is now required: this breaks clients that relied on null
@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: str        # nullability change is breaking
```

### 4.3 No Schema Artifact to Version

Because the schema is built at startup, there is nothing to store, distribute, or load:

```text
Your decorated Python modules
       ↓  (at app startup, in memory)
build_fraiseql_schema(...) / create_fraiseql_app(...)
       ↓
graphql-core schema served over FastAPI
```

There is no schema file, no intermediate representation, and no recompilation. If you change
your Python code and restart the app, the new schema is built fresh. To compare schema
versions, snapshot the GraphQL SDL via introspection and diff those snapshots.

---

## 5. GraphQL API Versioning

### 5.1 The Schema Your Clients See

The GraphQL schema your clients query against is exactly what your decorators produce at
startup. You version it together with your application code:

```graphql
type Query {
  user(id: ID!): User
}
```

Clients write queries against this schema. Keep it additive (see
[Section 2.2](#22-non-breaking-changes)) and existing clients keep working.

### 5.2 Query Compatibility

**Across additive schema changes**, existing queries keep working:

```graphql
# Query written against your earlier schema
query GetUser {
  user(id: "123") {
    id
    name
    email
  }
}

# Still works after you add new optional fields — this query is unchanged.
```

**Across a breaking schema change**, queries may need updates:

```graphql
# Query written against your earlier filter shape
query GetPosts {
  posts(filter: { author_id: "123" }) {
    id
    title
  }
}

# After you changed the filter shape, clients must update
query GetPosts {
  posts(where: { author: { id: "123" } }) {
    id
    title
  }
}
```

### 5.3 Query Validation

FraiseQL validates incoming queries against the in-memory schema at request time, using
`graphql-core`. A query that selects a field which does not exist is rejected with a GraphQL
validation error:

```python
# At request time, queries are validated against the running schema.
# A selection like `nonexistent_field` produces a GraphQL validation error
# in the response — it never reaches the database.
```

---

## 6. Error Code Versioning

### 6.1 Error Code Stability

**Treat error codes as part of your API contract.** Once clients branch on a code, keep its
meaning stable.

#### 6.1.1 Error Code Format

A deterministic, structured format makes codes easy to handle:

```text
E_CATEGORY_SUBCATEGORY_NUMBER

E_VALIDATION_EMAIL_001   → Category: VALIDATION, Subcategory: EMAIL, Number: 001
E_DB_DEADLOCK_303        → Category: DB, Subcategory: DEADLOCK, Number: 303
E_AUTH_PERMISSION_401    → Category: AUTH, Subcategory: PERMISSION, Number: 401
```

#### 6.1.2 Stable Codes, Flexible Messages

```python
# The code and its meaning stay stable across releases
error_code = "E_VALIDATION_EMAIL_001"
message = "Email cannot be empty"
```

The human-readable **message can change** (more detail, better wording), but the code and its
semantics stay fixed.

#### 6.1.3 Adding New Error Codes (safe)

```python
# Existing codes
# E_VALIDATION_EMAIL_001  → email cannot be empty
# E_VALIDATION_EMAIL_002  → email format invalid

# New, additive code
# E_VALIDATION_EMAIL_003  → email already exists
```

Clients that do not handle `E_VALIDATION_EMAIL_003` still work — they receive an error they
did not explicitly handle, which is backward-compatible.

#### 6.1.4 Removing Error Codes (breaking)

```python
# Removing a code that clients handle breaks them.
# Deprecate it first, then remove it in a MAJOR release.
```

#### 6.1.5 Changing Error Code Semantics (breaking)

```python
# Do not re-purpose a code.
# Instead, introduce a new code and keep the old one stable:
#   keep   E_DB_TIMEOUT_304    → query execution timeout
#   add    E_DB_CONN_TIMEOUT_305 → connection timeout
```

---

## 7. Running Multiple Versions

### 7.1 One Schema per Process

A FraiseQL app builds **one** schema at startup from the decorators it imports. You cannot
serve two different schema versions from a single process; restart with different code to
serve a different schema.

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[users, user],
    mutations=[create_user],
    production=True,
)
# This process serves exactly the schema these decorators produce.
```

### 7.2 Multiple Versions via Multiple Deployments

To run two API versions at once, deploy two app instances behind a gateway:

```text
┌─────────────────────────────────┐
│ API Gateway / Reverse Proxy     │
└──────────┬──────────────────────┘
           │
           ├─→ App Instance A  (your schema v1)
           │
           └─→ App Instance B  (your schema v2)
```

Route by path, header, or hostname:

- Requests for schema v1 → Instance A
- Requests for schema v2 → Instance B

### 7.3 Rolling Out a Schema Change

To move clients from one schema to the next:

```text
1. Deploy a new app instance running the new schema.
2. Route new clients to the new instance.
3. Keep the old instance running for existing clients.
4. Migrate clients over gradually.
5. Once all clients have moved, decommission the old instance.
```

---

## 8. Upgrade Path

### 8.1 Upgrading the FraiseQL Package

Within the `1.x` line, upgrades are backward-compatible. Upgrade with `uv`:

```bash
# Upgrade to the latest 1.x release
uv add "fraiseql>=1.23,<2"

# Pin an exact version for reproducible builds
uv add "fraiseql==1.23.11"
```

A MINOR or PATCH upgrade should require no code changes. Read the changelog, run your test
suite, and deploy. Because the schema is rebuilt at startup, simply restarting the app picks
up any framework improvements.

### 8.2 Pre-Upgrade Checklist

```markdown
### Upgrade Checklist

- [ ] Read the changelog for the target release.
- [ ] Check for any deprecation warnings in your logs and address them.
- [ ] Run your full test suite against the new FraiseQL version.
- [ ] Verify your GraphQL schema is unchanged (diff introspection snapshots).
- [ ] Deploy to staging and smoke-test queries and mutations.
- [ ] Roll out to production; keep the previous version available for rollback.
```

### 8.3 Rollback

Because there is no schema artifact and no data-format migration in the framework itself,
rolling the FraiseQL package back to the previous version is a redeploy:

```bash
# Roll back to the previously deployed version
uv add "fraiseql==1.22.0"
```

If you also shipped a breaking change to *your own* schema, coordinate the rollback with
your clients and your PostgreSQL views as you would any API change.

---

## 9. Client Versioning & Compatibility

### 9.1 Pin the Package

Applications pin the FraiseQL package version for reproducible builds:

```python
# pyproject.toml dependency
# fraiseql>=1.23,<2   → any backward-compatible 1.x release
# fraiseql==1.23.11   → an exact pin
```

### 9.2 GraphQL Clients Track Your Schema

GraphQL clients (web apps, mobile apps, services) depend on *your* schema, not on the
FraiseQL package version. As long as you keep schema edits additive, those clients keep
working across your releases:

```text
You upgrade FraiseQL 1.22 → 1.23 (backward-compatible)
└─ Your GraphQL schema is unchanged
   └─ All GraphQL clients keep working with no changes

You add optional fields to your schema (additive)
└─ Existing GraphQL clients keep working
   └─ New clients can opt into the new fields

You make a breaking schema change
└─ Affected GraphQL clients must update their queries
```

### 9.3 Advertising the Version

You can expose the running version to clients however you prefer, for example via an HTTP
header set by your app or gateway:

```text
GET /graphql
Host: api.example.com

200 OK
X-FraiseQL-Version: 1.23.11
Content-Type: application/json
```

---

## 10. Version Communication

### 10.1 Changelog Format

Every release should ship a changelog. A backward-compatible MINOR release looks like:

```markdown
# 1.23.0 Changelog

**Compatibility:** Backward-compatible with 1.22.x

## New Features

- Added keyset pagination support for large result sets.
- Added `startsWith` and `endsWith` string filter operators.

## Bug Fixes

- Fixed WHERE-clause filtering on view-backed types.
- Fixed deadlock handling in concurrent mutations.

## Breaking Changes

- None — this is a backward-compatible MINOR release.

## Deprecations

- `regex` filter operator: use `contains` or `startsWith` instead.
  Deprecated now; removal planned for the next MAJOR release.

## Performance

- Query execution faster on average; reduced memory usage on the JSON hot path.

## Security

- Hardened LIKE-clause handling against injection.
- Improved authorization caching.
```

### 10.2 Migration Guidance for Breaking Changes

For any breaking change to your own API, give clients a clear before/after and a timeline.
A concise deprecation notice for a filter operator:

```markdown
# Deprecation Notice: `regex` filter operator

**Announced in:** the current MINOR release
**Removal planned:** the next MAJOR release

## Why
The `regex` operator carries performance overhead. `contains` and `startsWith` cover the
common cases with better performance, so we are consolidating the operator surface.

## Before
\`\`\`graphql
query SearchPosts {
  posts(where: { title: { regex: "/^draft/" } }) {
    id
    title
  }
}
\`\`\`

## After
\`\`\`graphql
query SearchPosts {
  posts(where: { title: { startsWith: "draft" } }) {
    id
    title
  }
}
\`\`\`
```

---

## 11. Support & Long-Term Maintenance

### 11.1 Support Window

FraiseQL's `1.x` line receives ongoing bug fixes and security patches in new PATCH and MINOR
releases. Stay close to the latest `1.x` to keep receiving them. Pin a known-good version for
production, and schedule regular, low-risk upgrades within the `1.x` line.

### 11.2 Security Patches

Security fixes are released as new versions on PyPI. Upgrade promptly when a security release
is published:

```bash
uv add "fraiseql>=1.23.11"
```

### 11.3 End-of-Life Behaviour

An application pinned to an older `1.x` version keeps running — nothing forces an upgrade —
but it stops receiving fixes once you fall behind. To keep getting bug fixes and security
patches, track the latest `1.x` release.

---

## 12. Version Decision Tree

Use this to decide whether a change to the package (or to your own schema) requires a MAJOR,
MINOR, or PATCH bump:

```text
Does the change modify externally observable behaviour?
│
├─ NO
│  └─ Is it a refactor, performance improvement, or doc fix?
│     ├─ YES → PATCH (e.g. 1.23.0 → 1.23.1)
│     └─ NO  → No version bump (internal only)
│
└─ YES
   │
   └─ Does the change break existing queries, schemas, or callers?
      │
      ├─ NO (addition, improvement, deprecation)
      │  └─ MINOR (e.g. 1.23.0 → 1.24.0)
      │
      └─ YES (removal, incompatibility, behaviour change)
         └─ MAJOR (e.g. 1.x → 2.0.0)
```

---

## 13. Versioning Best Practices

### 13.1 For Framework Maintainers

**Do:**

- Bump MAJOR for breaking changes, MINOR for backward-compatible features, PATCH for fixes.
- Test new releases against existing user code.
- Document breaking changes prominently and provide migration guidance.
- Deprecate before removing — announce in a MINOR release, remove in the next MAJOR.
- Keep error codes stable within a MAJOR version.

**Don't:**

- Remove public APIs or operators without a deprecation period.
- Re-purpose an error code's meaning.
- Break callers without a MAJOR bump.

### 13.2 For Application Developers

**Do:**

- Pin a specific FraiseQL version in production.
- Test upgrades on staging first.
- Read the changelog before upgrading.
- Address deprecation warnings as you see them.
- Keep your own GraphQL schema edits additive whenever possible.

**Don't:**

- Track a floating "latest" in production.
- Make breaking schema changes without coordinating with your clients.
- Ignore deprecation warnings.

---

## 14. Examples

### 14.1 Example: Adding a New Field (additive)

**Scenario**: Add an optional `phone` field to the `User` type.

```python
import fraiseql
from fraiseql.types import ID

# before
@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: str | None = None

# after — add an optional field
@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: str | None = None
    phone: str | None = None   # new optional field
```

Existing GraphQL queries keep working; clients can optionally select `phone`. Expose `phone`
in the `v_user` view's `data` JSONB so the resolver can return it.

**Classification**: additive — safe (MINOR-style change to your schema).

### 14.2 Example: Removing a Filter Operator (breaking)

**Scenario**: Remove the `regex` filter operator.

```graphql
# before — query using the regex operator works
query GetPosts {
  posts(where: { title: { regex: "/draft/" } }) {
    id
  }
}

# after — the regex operator is gone; this query errors.
# Clients must rewrite it, e.g. using startsWith:
query GetPosts {
  posts(where: { title: { startsWith: "draft" } }) {
    id
  }
}
```

**Classification**: breaking — requires a deprecation period, then removal in a MAJOR release.

### 14.3 Example: Bug Fix (PATCH)

**Scenario**: Fix WHERE-clause filtering on a view-backed type.

```text
before: WHERE clause not correctly applied for some view-backed types (bug)
after:  WHERE clause correctly applied (fixed)
```

**Classification**: bug fix — PATCH (e.g. 1.23.10 → 1.23.11).

### 14.4 Example: Deprecation then Removal

```text
1.20.0  Announce deprecation of the `regex` operator; it still works, warnings shown.
1.21.0  Still works, warnings shown.
1.22.0  Still works, warnings shown.
1.23.0  Still works, warnings shown.
2.0.0   Operator removed; queries using it fail validation.
```

Clients migrate at any point during the deprecation window.

---

## 15. Summary & Quick Reference

### 15.1 Versioning at a Glance

| Version Type | Use Case | Example |
|--------------|----------|---------|
| **MAJOR** | Breaking changes | 1.x → 2.0.0 |
| **MINOR** | New features, backward-compatible | 1.22.0 → 1.23.0 |
| **PATCH** | Bug fixes, performance | 1.23.10 → 1.23.11 |

### 15.2 Breaking Change Examples

**Requires a MAJOR bump (package) / breaks clients (your schema):**

- Remove a field from a type.
- Change a field's type or make it non-null.
- Remove or re-define a filter operator.
- Remove or re-purpose an error code.
- Remove a custom scalar or change its serialization.
- Add a required argument or required input field.

**Backward-compatible (MINOR-style):**

- Add an optional field.
- Add a new filter operator.
- Add a new type or query.
- Add a new enum value.
- Add a new error code.
- Add an optional argument.

**Bug fixes and performance (PATCH-style):**

- Fix incorrect behaviour.
- Improve performance.
- Update documentation.
- Refactor internals (including the optional `fraiseql_rs` hot path).

### 15.3 Deprecation & Stability

- **Deprecate before removing** — announce in a MINOR release, remove in the next MAJOR.
- **Error codes** — keep their meaning stable; add new codes rather than re-purposing old ones.
- **Schema** — generated at runtime; there is no artifact to version, so diff introspection
  snapshots to track changes.

---

## 16. Appendix: Version Checking

### 16.1 Programmatic Version Check

```python
import fraiseql

# Get the installed FraiseQL package version
print(fraiseql.__version__)
# Example: "1.23.11"
```

You can also read the installed version through the standard library:

```python
from importlib.metadata import version

print(version("fraiseql"))
# Example: "1.23.11"
```

### 16.2 GraphQL Introspection

Use introspection to snapshot your runtime schema (useful for diffing schema versions):

```graphql
{
  __schema {
    types {
      name
      description
    }
  }
}
```

### 16.3 Version Endpoint

Expose your application's version however you like, for example a small endpoint:

```bash
# Your app returns its version
curl https://api.example.com/version
# Example: {"version": "1.23.11"}
```

---

## Related Reading

- [Consistency Model](./consistency-model.md)
- [Error Handling Model](./error-handling-model.md)
- [Failure Modes and Recovery](./failure-modes-and-recovery.md)

---
title: Trinity Pattern Guide
description: Complete guide to three-tier identifier system
tags:
  - trinity
  - identifiers
  - pattern
  - UUID
  - guide
---

# Trinity Pattern Complete Guide

The Trinity Pattern is FraiseQL's three-identifier system for optimal performance, security, and user experience. Every entity in FraiseQL uses three types of identifiers working together.

## 🎯 Overview

The Trinity Pattern solves common database design problems:

- **Performance**: INTEGER primary keys for fast JOINs
- **Security**: Never expose internal database structure
- **UX**: Human-readable identifiers for URLs and references
- **Consistency**: Predictable patterns across all entities

## 🏗️ The Three Identifiers

### 1. pk_* - Internal Integer Primary Key

**Purpose**: Database performance (fast JOINs, small indexes)

**Type**: `INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY`

**Visibility**: NEVER exposed in GraphQL or APIs

**Usage**:

- PostgreSQL foreign key references
- Internal query optimization
- ltree path construction

```sql
CREATE TABLE tb_post (
    pk_post INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Never exposed to API
    ...
);
```

**Why INTEGER?**

- 4 bytes vs 16 bytes (UUID) = 75% smaller indexes
- Sequential IDs optimize B-tree performance
- Faster JOIN operations

**Security**: pk_* values MUST NOT be exposed:

- ❌ Never in JSONB: `jsonb_build_object('pk_post', pk_post)`
- ❌ Never in GraphQL types: `class Post: pk_post: int`
- ❌ Never in API responses
- ✅ Only in SQL: `JOIN ON tb_post.pk_post = fk_post`

### 2. id - Public UUID Identifier

**Purpose**: Public API, stable across environments

**Type**: `UUID DEFAULT gen_random_uuid() NOT NULL UNIQUE`

**Visibility**: ALWAYS exposed in GraphQL and APIs

**Usage**:

- GraphQL query parameters
- REST API endpoints
- External integrations
- Cross-instance references

```sql
CREATE TABLE tb_post (
    pk_post INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID DEFAULT gen_random_uuid() NOT NULL UNIQUE,  -- Public API
    ...
);
```

**Benefits**:

- Non-sequential (no information leakage about data volume)
- Globally unique (works across databases/instances)
- Can be generated client-side
- Stable even if pk_* changes (e.g., during migrations)

### 3. identifier - Human-Readable Slug

**Purpose**: SEO-friendly URLs, user-facing references

**Type**: `TEXT UNIQUE` (optional)

**Visibility**: Exposed when relevant (posts, users, products)

**Usage**:

- URLs: `/posts/getting-started-with-fraiseql`
- User references: `@username`
- Product SKUs: `laptop-dell-xps-13`

```sql
CREATE TABLE tb_post (
    pk_post INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID DEFAULT gen_random_uuid() NOT NULL UNIQUE,
    identifier TEXT UNIQUE,  -- Optional, for SEO
    ...
);
```

**When to include**:

- ✅ User-facing entities (users, posts, products, categories)
- ✅ SEO-important pages
- ❌ Internal entities (readings, logs, events)
- ❌ Transactional data without slug needs

## 📋 Complete Implementation Example

### Table Definition

```sql
-- Table with full Trinity pattern
CREATE TABLE tb_post (
    -- 1. Internal INTEGER pk (never exposed)
    pk_post INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 2. Public UUID (always exposed)
    id UUID DEFAULT gen_random_uuid() NOT NULL UNIQUE,

    -- 3. Human-readable slug (optional)
    identifier TEXT UNIQUE,

    -- Foreign keys reference pk_* (INTEGER)
    fk_user INTEGER NOT NULL REFERENCES tb_user(pk_user),

    -- Business fields
    title TEXT NOT NULL,
    content TEXT,
    is_published BOOLEAN DEFAULT false,

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for all three identifiers
CREATE INDEX idx_tb_post_id ON tb_post(id);
CREATE INDEX idx_tb_post_identifier ON tb_post(identifier);
CREATE INDEX idx_tb_post_fk_user ON tb_post(fk_user);
```

### View Definition

```sql
-- View exposes id + JSONB (no pk_post in JSONB!)
CREATE VIEW v_post AS
SELECT
    id,       -- Direct column for WHERE filtering
    pk_post,  -- Only if other views JOIN to this
    jsonb_build_object(
        'id', id::text,           -- ✅ Public UUID
        'identifier', identifier, -- ✅ Human slug
        'title', title,
        'content', content
        -- ❌ No 'pk_post' here!
    ) as data
FROM tb_post;
```

### GraphQL Type Definition

```python
from fraiseql.types import ID

@fraiseql.type(sql_source="v_post", jsonb_column="data")
class Post:
    id: ID          # ✅ Public
    identifier: str   # ✅ Public
    title: str
    content: str
    # ❌ No pk_post field
```

### Mutation Function

```sql
CREATE FUNCTION fn_create_post(p_input JSONB)
RETURNS JSONB AS $$
DECLARE
    v_post_id UUID;
    v_user_pk INTEGER;
BEGIN
    -- Resolve identifiers
    v_user_pk := core.get_pk_user(p_input->>'user_id');

    -- Create post
    INSERT INTO tb_post (fk_user, title, content)
    VALUES (v_user_pk, p_input->>'title', p_input->>'content')
    RETURNING id INTO v_post_id;

    -- Sync projection table
    PERFORM fn_sync_tv_post(v_post_id);

    RETURN jsonb_build_object(
        'success', true,
        'post_id', v_post_id
    );
END;
$$ LANGUAGE plpgsql;
```

## 🚨 Common Mistakes & Fixes

### ❌ Mistake 1: Exposing pk_* in JSONB

```sql
-- WRONG
CREATE VIEW v_user AS
SELECT
    id,
    jsonb_build_object(
        'pk_user', pk_user,  -- ❌ Security risk!
        'id', id,
        'name', name
    ) as data
FROM tb_user;
```

**Why wrong?**: Exposes internal database structure, enables enumeration attacks

**Fix**:

```sql
-- CORRECT
CREATE VIEW v_user AS
SELECT
    id,
    jsonb_build_object(
        'id', id,          -- ✅ Only public fields
        'name', name
    ) as data
FROM tb_user;
```

### ❌ Mistake 2: Foreign Keys to UUID

```sql
-- WRONG
CREATE TABLE tb_post (
    fk_user UUID REFERENCES tb_user(id)  -- ❌ Inefficient!
);
```

**Why wrong?**:

- 4x larger indexes (16 bytes vs 4 bytes)
- Slower JOIN performance
- Breaks Trinity pattern

**Fix**:

```sql
-- CORRECT
CREATE TABLE tb_post (
    fk_user INTEGER REFERENCES tb_user(pk_user)  -- ✅
);
```

### ❌ Mistake 3: Using SERIAL

```sql
-- WRONG (deprecated)
CREATE TABLE tb_user (
    pk_user SERIAL PRIMARY KEY  -- ❌ Old PostgreSQL syntax
);
```

**Fix**:

```sql
-- CORRECT (modern PostgreSQL)
CREATE TABLE tb_user (
    pk_user INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY  -- ✅
);
```

### ❌ Mistake 4: Missing id Column in Views

```sql
-- WRONG
CREATE VIEW v_user AS
SELECT
    jsonb_build_object('id', id, 'name', name) as data
FROM tb_user;
-- ❌ No direct 'id' column for WHERE filtering
```

**Fix**:

```sql
-- CORRECT
CREATE VIEW v_user AS
SELECT
    id,  -- ✅ Direct column for WHERE id = $1
    jsonb_build_object('id', id, 'name', name) as data
FROM tb_user;
```

### ❌ Mistake 5: Wrong Variable Naming

```sql
-- WRONG
CREATE FUNCTION create_post(...) RETURNS JSONB AS $$
DECLARE
    userId UUID;        -- ❌ camelCase
    user_pk INTEGER;    -- ❌ Missing v_ prefix
BEGIN
    -- ...
END;
$$;

-- CORRECT
CREATE FUNCTION create_post(...) RETURNS JSONB AS $$
DECLARE
    v_user_id UUID;     -- ✅ v_<entity>_id
    v_user_pk INTEGER;  -- ✅ v_<entity>_pk
BEGIN
    -- ...
END;
$$;
```

## 🔍 Verification Checklist

Verify your implementation follows the checklist in the "Manual Verification" section below.

Note: Automated verification tools are available in development environments.

### Manual Verification

**Tables**:

- [ ] Has `pk_<entity> INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY`
- [ ] Has `id UUID DEFAULT gen_random_uuid() NOT NULL UNIQUE`
- [ ] Has `identifier TEXT UNIQUE` (if user-facing)
- [ ] Foreign keys reference `pk_*` columns

**Views**:

- [ ] Has direct `id` column for WHERE filtering
- [ ] JSONB never contains `pk_*` fields
- [ ] Includes `pk_*` only if other views JOIN to it

**Functions**:

- [ ] Variables use `v_<entity>_pk`, `v_<entity>_id` naming
- [ ] Mutations call `fn_sync_tv_<entity>()`
- [ ] Return appropriate types (JSONB for app, simple for core)

**Python Types**:

- [ ] Never expose `pk_*` fields
- [ ] Match JSONB view structure exactly

## 📚 Advanced Patterns

### Hierarchical Data (ltree)

```sql
CREATE TABLE tb_category (
    pk_category INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID DEFAULT gen_random_uuid() NOT NULL UNIQUE,
    identifier TEXT UNIQUE,

    fk_parent INTEGER REFERENCES tb_category(pk_category),
    name TEXT NOT NULL,

    -- ltree path using INTEGER pks
    path LTREE GENERATED ALWAYS AS (
        CASE
            WHEN fk_parent IS NULL THEN pk_category::TEXT::LTREE
            ELSE (SELECT path FROM tb_category WHERE pk_category = fk_parent)
                 || pk_category::TEXT::LTREE
        END
    ) STORED
);

-- View includes pk_category for recursive queries
CREATE VIEW v_category AS
SELECT
    id,
    pk_category,  -- ✅ Needed for ltree operations
    jsonb_build_object(
        'id', id::text,
        'identifier', identifier,
        'name', name,
        'path', path::text
    ) as data
FROM tb_category;
```

### Projection Tables (tv_*)

```sql
-- Base table
CREATE TABLE tb_user (
    pk_user INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID DEFAULT gen_random_uuid() NOT NULL UNIQUE,
    name TEXT NOT NULL
);

-- View
CREATE VIEW v_user AS
SELECT
    id,
    jsonb_build_object('id', id::text, 'name', name) as data
FROM tb_user;

-- Projection table (materialized cache)
CREATE TABLE tv_user (
    id UUID PRIMARY KEY,  -- Simple PK, no Trinity
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Sync function
CREATE FUNCTION fn_sync_tv_user(p_id UUID) RETURNS VOID AS $$
BEGIN
    INSERT INTO tv_user (id, data)
    SELECT id, data FROM v_user WHERE id = p_id
    ON CONFLICT (id) DO UPDATE SET
        data = EXCLUDED.data,
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;
```

## 🔗 Related Documentation

- [Migration Guide](../archive/mutations/migration-guide.md)
- [Verification Tools](../archive/testing/developer-guide.md)

## 🎯 Summary

The Trinity Pattern provides:

- **Performance**: INTEGER primary keys for fast database operations
- **Security**: Never expose internal database structure
- **Consistency**: Predictable patterns across all entities
- **UX**: Human-readable identifiers for better user experience

Follow this guide and use the automated verification tools to ensure your FraiseQL implementations are secure, performant, and maintainable.

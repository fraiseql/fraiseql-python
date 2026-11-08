---
title: Advanced Patterns
description: Advanced architectural patterns and design strategies
tags:
  - patterns
  - architecture
  - advanced
  - design
  - best-practices
---

# FraiseQL v1 - Advanced Patterns (DEFAULT)

**Core patterns for FraiseQL v1**: Production-grade database architecture

---

## Pattern 1: Trinity Identifiers (DEFAULT)

### **The Problem**

Single-ID systems have trade-offs:

| ID Type | Pros | Cons |
|---------|------|------|
| **Serial/Autoincrement** | Fast joins, sequential | Not globally unique, exposes growth rate |
| **UUID** | Globally unique, secure | Slower joins, random order |
| **Slug/Username** | Human-friendly, SEO | Can't use as PK (changes), not all entities have one |

**Solution**: Use all three! Each for its purpose.

---

### **Trinity Pattern - Revised Naming**

```sql
-- ============================================
-- COMMAND SIDE (tb_*)
-- ============================================

CREATE TABLE tb_organisation (
    -- Primary Key: SERIAL for fast internal joins
    pk_organisation SERIAL PRIMARY KEY,

    -- Public ID: UUID for GraphQL API (secure, doesn't expose count)
    id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,

    -- Human identifier: TEXT for user-facing URLs
    identifier TEXT UNIQUE NOT NULL,  -- e.g., "acme-corp"

    -- Regular fields
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE tb_user (
    -- Primary Key: SERIAL (internal, fast)
    pk_user SERIAL PRIMARY KEY,

    -- Foreign Key: INT referencing pk_organisation (fast FK!)
    fk_organisation INT NOT NULL REFERENCES tb_organisation(pk_organisation),

    -- Public ID: UUID for GraphQL API
    id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,

    -- Human identifier: username/slug
    identifier TEXT UNIQUE NOT NULL,  -- e.g., "john-doe"

    -- Regular fields
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE tb_post (
    -- Primary Key: SERIAL
    pk_post SERIAL PRIMARY KEY,

    -- Foreign Key: INT referencing pk_user (fast!)
    fk_user INT NOT NULL REFERENCES tb_user(pk_user),

    -- Public ID: UUID
    id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,

    -- Human identifier: slug
    identifier TEXT UNIQUE NOT NULL,  -- e.g., "my-first-post"

    -- Regular fields
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for lookups
CREATE INDEX idx_tb_user_id ON tb_user(id);                      -- UUID lookups
CREATE INDEX idx_tb_user_identifier ON tb_user(identifier);      -- Slug lookups
CREATE INDEX idx_tb_user_fk_organisation ON tb_user(fk_organisation);  -- FK joins

-- ============================================
-- QUERY SIDE (tv_*)
-- ============================================

-- Clean! Only UUID and identifier exposed
CREATE TABLE tv_user (
    id UUID PRIMARY KEY,                -- Just UUID! (clean GraphQL API)
    identifier TEXT UNIQUE NOT NULL,
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE tv_post (
    id UUID PRIMARY KEY,
    identifier TEXT UNIQUE NOT NULL,
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Naming Convention** (FINAL):

- `pk_*` = SERIAL PRIMARY KEY (internal, fast joins)
- `fk_*` = INT FOREIGN KEY (references another table's pk_*)
- `id` = UUID (public API identifier, exposed in GraphQL)
- `identifier` = TEXT (human-readable: username, slug, etc.)

---

### **Benefits**

| Use Case | ID to Use | Why |
|----------|-----------|-----|
| **GraphQL ID field** | `id` (UUID) | Secure, globally unique, doesn't leak info |
| **Database joins** | `pk_*`, `fk_*` (SERIAL) | Fast INT joins (10x faster than UUID) |
| **User-facing URLs** | `identifier` (slug) | SEO-friendly, memorable |
| **API lookup** | `id` or `identifier` | Flexible, user chooses |

**Example GraphQL queries**:

```graphql
# By public UUID (secure)
query {
  user(id: "550e8400-e29b-41d4-a716-446655440000") {
    id
    identifier
    name
  }
}

# By human identifier (friendly)
query {
  user(identifier: "john-doe") {
    id
    identifier
    name
  }
}

# URL-friendly: /users/john-doe
```

---

### **Sync Functions**

```sql
-- Sync tv_user from tb_user (receives UUID)
CREATE OR REPLACE FUNCTION fn_sync_tv_user(p_id UUID)
RETURNS void AS $$
BEGIN
    INSERT INTO tv_user (id, identifier, data, updated_at)
    SELECT
        u.id,                -- UUID
        u.identifier,
        jsonb_build_object(
            'id', u.id::text,
            'identifier', u.identifier,
            'name', u.name,
            'email', u.email,
            'organisation', (
                SELECT jsonb_build_object(
                    'id', o.id::text,
                    'identifier', o.identifier,
                    'name', o.name
                )
                FROM tb_organisation o
                WHERE o.pk_organisation = u.fk_organisation  -- Fast INT join!
            ),
            'created_at', u.created_at
        ),
        NOW()
    FROM tb_user u
    WHERE u.id = p_id  -- Find by UUID
    ON CONFLICT (id) DO UPDATE
    SET data = EXCLUDED.data, updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- Sync tv_post from tb_post
CREATE OR REPLACE FUNCTION fn_sync_tv_post(p_id UUID)
RETURNS void AS $$
BEGIN
    INSERT INTO tv_post (id, identifier, data, updated_at)
    SELECT
        p.id,
        p.identifier,
        jsonb_build_object(
            'id', p.id::text,
            'identifier', p.identifier,
            'title', p.title,
            'content', p.content,
            'created_at', p.created_at,
            'author', (
                SELECT jsonb_build_object(
                    'id', u.id::text,
                    'identifier', u.identifier,
                    'name', u.name
                )
                FROM tb_user u
                WHERE u.pk_user = p.fk_user  -- Fast INT join!
            )
        ),
        NOW()
    FROM tb_post p
    WHERE p.id = p_id
    ON CONFLICT (id) DO UPDATE
    SET data = EXCLUDED.data, updated_at = NOW();
END;
$$ LANGUAGE plpgsql;
```

---

### **Python API (Clean!)**

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type
class Organisation:
    id: ID              # ✅ Clean! Just "id" (UUID)
    identifier: str       # "acme-corp"
    name: str

@fraiseql.type
class User:
    id: ID              # ✅ Clean! Just "id" (UUID)
    identifier: str       # "john-doe"
    name: str
    email: str
    organisation: Organisation

@fraiseql.type
class Post:
    id: ID              # ✅ Clean! Just "id" (UUID)
    identifier: str       # "my-first-post"
    title: str
    content: str
    author: User

# Query by UUID or identifier
@fraiseql.query
async def user(
    info,
    id: ID | None = None,
    identifier: str | None = None
) -> User | None:
    """Get user by UUID or identifier"""
    db = info.context["db"]

    if id:
        return await db.find_one("tv_user", "user", info, mandatory_filters={"id": id})
    elif identifier:
        return await db.find_one("tv_user", "user", info, mandatory_filters={"identifier": identifier})
    else:
        raise ValueError("Must provide id or identifier")

# Mutations return UUID
@fraiseql.mutation
async def create_user(
    info,
    organisation: str,  # Organisation identifier (human-friendly!)
    identifier: str,    # User identifier (username)
    name: str,
    email: str
) -> User:
    """Create user with human-friendly identifiers"""
    db = info.context["db"]

    # ✅ Just call the function - that's it! It gets the arguments as one jsonb,
    # and its OUT parameters come back as a dict.
    try:
        result = await db.execute_function(
            "fn_create_user",
            {
                "organisation_identifier": organisation,
                "identifier": identifier,
                "name": name,
                "email": email,
            },
        )
    except Exception as e:
        # Database raises meaningful errors
        raise GraphQLError(str(e))

    # Read from query side
    return await db.find_one("tv_user", "createUser", info, mandatory_filters={"id": result["user_id"]})
```

---

### **Configuration**

None: trinity identifiers are a naming convention, not a setting. `FraiseQLConfig` has no
option for them (it ignores unknown ones). Name the columns `pk_*`, `fk_*`, `id` and
`identifier` in your tables, expose `id` and `identifier` in the `tv_*` view, and declare
them on the type like any other field.

---

### **Why This Naming is Better**

**1. Intuitive Database Schema**

```sql
-- Crystal clear what each field does:
pk_user           -- "This is the primary key"
fk_organisation   -- "This is a foreign key to organisation"
id                -- "This is the public UUID identifier"
identifier        -- "This is the human-readable slug/username"
```

**2. Clean GraphQL Schema**

```graphql
type User {
  id: ID!         # ✅ Standard GraphQL convention (just "id")
  identifier: String!
  name: String!
}

# NOT:
type User {
  pkUser: UUID!     # ❌ Ugly, exposes internals
  internalId: Int!  # ❌ Confusing
}
```

**3. Fast Database Joins**

```sql
-- Joins use fast SERIAL integers
SELECT u.name, o.name, p.title
FROM tb_user u
JOIN tb_organisation o ON u.fk_organisation = o.pk_organisation  -- Fast INT!
JOIN tb_post p ON p.fk_user = u.pk_user                          -- Fast INT!
WHERE u.id = '550e8400-...'  -- Lookup by UUID
```

**Performance**: INT joins are ~10x faster than UUID joins

---

### **When to Use Trinity Pattern**

**✅ Use when (RECOMMENDED)**:

- Building public APIs (UUIDs are safer)
- Need fast internal joins (serial IDs)
- Want user-friendly URLs (slugs/usernames)
- Multi-tenant systems
- High-scale systems (millions+ rows)

**❌ Skip when**:

- Internal tools only
- Simple CRUD apps (< 10 tables)
- Single-tenant systems
- Low scale (< 100K rows)

---

## Pattern 2: Mutations as Database Functions (DEFAULT)

### **The Problem**

**Traditional approach** (Python-heavy):

```python
@fraiseql.mutation
async def create_user(info, name: str, email: str) -> User:
    db = info.context["db"]

    # ❌ Business logic in Python (not reusable)
    if not email_is_valid(email):
        raise ValueError("Invalid email")

    # ❌ Manual transaction management
    async def insert(conn):
        cur = await conn.execute(
            "INSERT INTO tb_user (name, email) VALUES (%s, %s) RETURNING id",
            (name, email),
        )
        (id,) = await cur.fetchone()

        # ❌ Manual sync (can forget!)
        await sync_tv_user(conn, id)
        return id

    id = await db.run_in_transaction(insert)

    return await db.find_one("tv_user", "createUser", info, mandatory_filters={"id": id})
```

**Problems**:

- Business logic in Python (not reusable from psql, cron, etc.)
- Manual transaction management (easy to mess up)
- Manual sync calls (can forget)
- Hard to test in isolation (need Python app)
- Can't call from other contexts

---

### **Better: Database Functions (DEFAULT)**

**All business logic in PostgreSQL**:

```sql
CREATE OR REPLACE FUNCTION fn_create_user(input JSONB, OUT user_id UUID) AS $$
DECLARE
    v_fk_organisation INT;
    v_id UUID;
BEGIN
    -- Resolve organisation by identifier (human-friendly!)
    SELECT pk_organisation INTO v_fk_organisation
    FROM tb_organisation
    WHERE identifier = input->>'organisation_identifier';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Organisation not found: %', input->>'organisation_identifier';
    END IF;

    -- Validation (in database)
    IF input->>'email' !~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$' THEN
        RAISE EXCEPTION 'Invalid email format';
    END IF;

    IF EXISTS (SELECT 1 FROM tb_user WHERE identifier = input->>'identifier') THEN
        RAISE EXCEPTION 'Identifier already taken';
    END IF;

    -- Insert (transaction is automatic)
    INSERT INTO tb_user (fk_organisation, identifier, name, email)
    VALUES (v_fk_organisation, input->>'identifier', input->>'name', input->>'email')
    RETURNING id INTO v_id;

    -- Sync to query side (explicit, same transaction)
    PERFORM fn_sync_tv_user(v_id);

    -- Return public UUID
    user_id := v_id;

EXCEPTION
    WHEN unique_violation THEN
        RAISE EXCEPTION 'User identifier or email already exists';
    WHEN others THEN
        RAISE;
END;
$$ LANGUAGE plpgsql;
```

**Python becomes trivial**:

```python
@fraiseql.mutation
async def create_user(
    info,
    organisation: str,  # Organisation identifier
    identifier: str,    # Username
    name: str,
    email: str
) -> User:
    """Create user (business logic in database)"""
    db = info.context["db"]

    # ✅ Just call the function - that's it! It gets the arguments as one jsonb,
    # and its OUT parameters come back as a dict.
    try:
        result = await db.execute_function(
            "fn_create_user",
            {
                "organisation_identifier": organisation,
                "identifier": identifier,
                "name": name,
                "email": email,
            },
        )
    except Exception as e:
        # Database raises meaningful errors
        raise GraphQLError(str(e))

    # Read from query side
    return await db.find_one("tv_user", "createUser", info, mandatory_filters={"id": result["user_id"]})
```

---

### **Benefits**

| Aspect | Python Logic | Database Function | Winner |
|--------|-------------|-------------------|--------|
| **Transaction** | Manual `async with` | Automatic | **DB** |
| **Validation** | Python code | SQL + constraints | **DB** |
| **Reusability** | Python only | psql, cron, triggers | **DB** |
| **Testing** | Need Python app | Direct SQL tests | **DB** |
| **Sync** | Manual await | Explicit in function | **DB** |
| **Atomic** | Hope you got it right | Guaranteed | **DB** |
| **Versioning** | Python migrations | SQL migrations | **DB** |
| **Performance** | Multiple round-trips | Single call | **DB** |

**Database functions win on every metric.**

---

### **Pattern Structure**

**Naming Convention**:

```
fn_create_*     Create entity (INSERT + sync) → OUT <entity>_id UUID
fn_update_*     Update entity (UPDATE + sync) → OUT <entity>_id UUID
fn_delete_*     Delete entity (DELETE + cascade) → OUT deleted BOOLEAN
fn_sync_tv_*    Sync command → query side
fn_*            Custom business logic
```

**Example: Complete CRUD**:

```sql
-- CREATE
CREATE FUNCTION fn_create_post(input JSONB, OUT post_id UUID) AS $$
DECLARE
    v_fk_user INT;
    v_id UUID;
BEGIN
    -- Resolve user by identifier (human-friendly API!)
    SELECT pk_user INTO v_fk_user
    FROM tb_user
    WHERE identifier = input->>'user_identifier';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'User not found: %', input->>'user_identifier';
    END IF;

    INSERT INTO tb_post (fk_user, identifier, title, content)
    VALUES (v_fk_user, input->>'identifier', input->>'title', input->>'content')
    RETURNING id INTO v_id;

    PERFORM fn_sync_tv_post(v_id);
    post_id := v_id;
END;
$$ LANGUAGE plpgsql;

-- UPDATE
CREATE FUNCTION fn_update_post(input JSONB, OUT post_id UUID) AS $$
BEGIN
    UPDATE tb_post
    SET title = input->>'title', content = input->>'content', updated_at = NOW()
    WHERE id = (input->>'id')::uuid;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Post not found';
    END IF;

    PERFORM fn_sync_tv_post((input->>'id')::uuid);
    post_id := (input->>'id')::uuid;
END;
$$ LANGUAGE plpgsql;

-- DELETE
CREATE FUNCTION fn_delete_post(input JSONB, OUT deleted BOOLEAN) AS $$
BEGIN
    -- Delete from query side first
    DELETE FROM tv_post WHERE id = (input->>'id')::uuid;

    -- Then from command side
    DELETE FROM tb_post WHERE id = (input->>'id')::uuid;

    deleted := FOUND;
END;
$$ LANGUAGE plpgsql;
```

**Python mutations** (all follow same trivial pattern):

```python
from fraiseql.types import ID

@fraiseql.mutation
async def create_post(
    info,
    author: str,        # Author identifier (username)
    identifier: str,    # Post slug
    title: str,
    content: str
) -> Post:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_create_post",
        {"user_identifier": author, "identifier": identifier, "title": title, "content": content},
    )
    return await db.find_one("tv_post", "createPost", info, mandatory_filters={"id": result["post_id"]})

@fraiseql.mutation
async def update_post(info, id: ID, title: str, content: str) -> Post:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_update_post", {"id": str(id), "title": title, "content": content}
    )
    return await db.find_one("tv_post", "updatePost", info, mandatory_filters={"id": result["post_id"]})

@fraiseql.mutation
async def delete_post(info, id: ID) -> bool:
    db = info.context["db"]
    result = await db.execute_function("fn_delete_post", {"id": str(id)})
    return result["deleted"]
```

**Pattern**: Python is thin wrapper. Database has all logic.

---

### **Testing Database Functions**

```sql
-- tests/test_mutations.sql (using pgTAP)

BEGIN;

SELECT plan(5);

-- Test: Create user with valid data
SELECT lives_ok(
    $$SELECT fn_create_user('acme-corp', 'john-doe', 'John Doe', 'john@example.com')$$,
    'Create user succeeds'
);

SELECT is(
    (SELECT name FROM tb_user WHERE identifier = 'john-doe'),
    'John Doe',
    'User inserted correctly'
);

SELECT is(
    (SELECT data->>'name' FROM tv_user WHERE identifier = 'john-doe'),
    'John Doe',
    'Query side synced correctly'
);

-- Test: Duplicate identifier fails
SELECT throws_ok(
    $$SELECT fn_create_user('acme-corp', 'john-doe', 'Jane Doe', 'jane@example.com')$$,
    'Identifier already taken',
    'Duplicate identifier rejected'
);

-- Test: Invalid email fails
SELECT throws_ok(
    $$SELECT fn_create_user('acme-corp', 'jane-doe', 'Jane Doe', 'not-an-email')$$,
    'Invalid email format',
    'Invalid email rejected'
);

SELECT finish();
ROLLBACK;
```

**Test directly in PostgreSQL** - no Python needed!

Run with: `psql -f tests/test_mutations.sql`

---

### **Configuration**

None: a class mutation names its SQL function with `function=` (`function="fn_create_user"`),
and FraiseQL calls that function. There is no prefix setting and nothing generates
missing functions.

---

### **Writing the Functions**

FraiseQL has no command that lists or generates these functions: write each one by hand.
For a new `tb_comment`, the pattern gives:

```sql
-- fn_create_comment, following the pattern
CREATE FUNCTION fn_create_comment(input JSONB, OUT comment_id UUID) AS $$
DECLARE
    v_fk_post INT;
    v_fk_user INT;
    v_id UUID;
BEGIN
    -- Resolve foreign keys by identifier
    SELECT pk_post INTO v_fk_post FROM tb_post WHERE identifier = input->>'post_identifier';
    IF NOT FOUND THEN RAISE EXCEPTION 'Post not found'; END IF;

    SELECT pk_user INTO v_fk_user FROM tb_user WHERE identifier = input->>'user_identifier';
    IF NOT FOUND THEN RAISE EXCEPTION 'User not found'; END IF;

    -- Insert
    INSERT INTO tb_comment (fk_post, fk_user, content)
    VALUES (v_fk_post, v_fk_user, input->>'content')
    RETURNING id INTO v_id;

    -- Sync
    PERFORM fn_sync_tv_comment(v_id);

    comment_id := v_id;
END;
$$ LANGUAGE plpgsql;
```

---

### **When to Use Database Functions**

**✅ Use when (RECOMMENDED - DEFAULT)**:

- **Any production application** ⭐
- Need transactional integrity
- Want testable business logic
- Multiple clients (Python, psql, cron)
- Complex validation
- Audit logging required

**❌ Skip when**:

- Prototype/demo only (no business logic)
- Very simple CRUD (no validation)
- Team unfamiliar with PL/pgSQL (train them!)

**Recommendation**: **Make this the DEFAULT in FraiseQL v1** ✅

---

## Combined Pattern: Trinity + Functions (Full Example)

### **Complete Schema**

```sql
-- ============================================
-- COMMAND SIDE: Trinity identifiers
-- ============================================

CREATE TABLE tb_organisation (
    pk_organisation SERIAL PRIMARY KEY,
    id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,
    identifier TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE tb_user (
    pk_user SERIAL PRIMARY KEY,
    fk_organisation INT NOT NULL REFERENCES tb_organisation(pk_organisation),
    id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,
    identifier TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE tb_post (
    pk_post SERIAL PRIMARY KEY,
    fk_user INT NOT NULL REFERENCES tb_user(pk_user),
    id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,
    identifier TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- QUERY SIDE: Clean UUID + identifier
-- ============================================

CREATE TABLE tv_user (
    id UUID PRIMARY KEY,
    identifier TEXT UNIQUE NOT NULL,
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE tv_post (
    id UUID PRIMARY KEY,
    identifier TEXT UNIQUE NOT NULL,
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- SYNC FUNCTIONS
-- ============================================

CREATE FUNCTION fn_sync_tv_user(p_id UUID) RETURNS void AS $$
BEGIN
    INSERT INTO tv_user (id, identifier, data, updated_at)
    SELECT
        u.id,
        u.identifier,
        jsonb_build_object(
            'id', u.id::text,
            'identifier', u.identifier,
            'name', u.name,
            'email', u.email,
            'organisation', (
                SELECT jsonb_build_object(
                    'id', o.id::text,
                    'identifier', o.identifier,
                    'name', o.name
                )
                FROM tb_organisation o
                WHERE o.pk_organisation = u.fk_organisation
            ),
            'created_at', u.created_at
        ),
        NOW()
    FROM tb_user u
    WHERE u.id = p_id
    ON CONFLICT (id) DO UPDATE
    SET data = EXCLUDED.data, updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION fn_sync_tv_post(p_id UUID) RETURNS void AS $$
BEGIN
    INSERT INTO tv_post (id, identifier, data, updated_at)
    SELECT
        p.id,
        p.identifier,
        jsonb_build_object(
            'id', p.id::text,
            'identifier', p.identifier,
            'title', p.title,
            'content', p.content,
            'created_at', p.created_at,
            'author', (
                SELECT jsonb_build_object(
                    'id', u.id::text,
                    'identifier', u.identifier,
                    'name', u.name
                )
                FROM tb_user u
                WHERE u.pk_user = p.fk_user
            )
        ),
        NOW()
    FROM tb_post p
    WHERE p.id = p_id
    ON CONFLICT (id) DO UPDATE
    SET data = EXCLUDED.data, updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- MUTATION FUNCTIONS with trinity IDs
-- ============================================

CREATE FUNCTION fn_create_user(input JSONB, OUT user_id UUID) AS $$
DECLARE
    v_fk_organisation INT;
    v_id UUID;
BEGIN
    -- Resolve by identifier (human-friendly!)
    SELECT pk_organisation INTO v_fk_organisation
    FROM tb_organisation
    WHERE identifier = input->>'organisation_identifier';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Organisation not found: %', input->>'organisation_identifier';
    END IF;

    -- Validation
    IF input->>'email' !~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$' THEN
        RAISE EXCEPTION 'Invalid email format';
    END IF;

    -- Insert
    INSERT INTO tb_user (fk_organisation, identifier, name, email)
    VALUES (v_fk_organisation, input->>'identifier', input->>'name', input->>'email')
    RETURNING id INTO v_id;

    -- Sync
    PERFORM fn_sync_tv_user(v_id);

    user_id := v_id;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION fn_create_post(input JSONB, OUT post_id UUID) AS $$
DECLARE
    v_fk_user INT;
    v_id UUID;
BEGIN
    -- Resolve user by identifier
    SELECT pk_user INTO v_fk_user
    FROM tb_user
    WHERE identifier = input->>'user_identifier';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'User not found: %', input->>'user_identifier';
    END IF;

    -- Insert
    INSERT INTO tb_post (fk_user, identifier, title, content)
    VALUES (v_fk_user, input->>'identifier', input->>'title', input->>'content')
    RETURNING id INTO v_id;

    -- Sync
    PERFORM fn_sync_tv_post(v_id);

    post_id := v_id;
END;
$$ LANGUAGE plpgsql;
```

### **Python API (Clean & Simple)**

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type
class Organisation:
    id: ID
    identifier: str
    name: str

@fraiseql.type
class User:
    id: ID
    identifier: str
    name: str
    email: str
    organisation: Organisation

@fraiseql.type
class Post:
    id: ID
    identifier: str
    title: str
    content: str
    author: User

# QUERIES
@fraiseql.query
async def user(
    info,
    id: ID | None = None,
    identifier: str | None = None
) -> User | None:
    db = info.context["db"]
    if id:
        return await db.find_one("tv_user", "user", info, mandatory_filters={"id": id})
    elif identifier:
        return await db.find_one("tv_user", "user", info, mandatory_filters={"identifier": identifier})
    raise ValueError("Must provide id or identifier")

# MUTATIONS (trivial - logic in database)
@fraiseql.mutation
async def create_user(
    info,
    organisation: str,
    identifier: str,
    name: str,
    email: str
) -> User:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_create_user",
        {
            "organisation_identifier": organisation,
            "identifier": identifier,
            "name": name,
            "email": email,
        },
    )
    return await db.find_one("tv_user", "createUser", info, mandatory_filters={"id": result["user_id"]})

@fraiseql.mutation
async def create_post(
    info,
    author: str,
    identifier: str,
    title: str,
    content: str
) -> Post:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_create_post",
        {"user_identifier": author, "identifier": identifier, "title": title, "content": content},
    )
    return await db.find_one("tv_post", "createPost", info, mandatory_filters={"id": result["post_id"]})
```

### **GraphQL Usage**

```graphql
# Create post with human-friendly identifiers!
mutation {
  createPost(
    author: "john-doe",           # Username (not UUID!)
    identifier: "my-first-post",   # Slug
    title: "My First Post",
    content: "Hello world"
  ) {
    id                            # UUID returned
    identifier                    # "my-first-post"
    title
    author {
      id
      identifier                  # "john-doe"
      name
    }
  }
}

# Query by identifier
query {
  user(identifier: "john-doe") {  # Human-friendly!
    id
    name
    organisation {
      identifier                  # "acme-corp"
      name
    }
  }
}

# URL-friendly: /posts/my-first-post
```

---

## Integration with FraiseQL v1

### **Configuration**

These patterns need no configuration: `FraiseQLConfig` has no options for them. A type names
its view with `sql_source=` (`tv_user`) and its JSONB column with `jsonb_column=` (`data` is
the default), and a class mutation names its function with `function=`.

### **Reading by UUID or identifier**

There is no separate query repository: the repository in `info.context["db"]` reads
a view by any of its columns, so a projection table with `id` and `identifier`
columns can be read by either:

```python
db = info.context["db"]
# By public UUID
await db.find_one("tv_user", "user", info, mandatory_filters={"id": user_id})
# By human identifier
await db.find_one("tv_user", "user", info, mandatory_filters={"identifier": "alice"})
```

---

## Summary: Why These Patterns are DEFAULT

### **Trinity Identifiers**

- ✅ Fast database joins (SERIAL)
- ✅ Secure public API (UUID)
- ✅ Human-friendly URLs (identifier)
- ✅ Clear naming (`pk_*`, `fk_*`, `id`, `identifier`)
- ✅ GraphQL best practices (just "id")

### **Mutations as Functions**

- ✅ Business logic in database (reusable)
- ✅ Automatic transactions
- ✅ Explicit sync calls
- ✅ Testable in SQL
- ✅ Single database round-trip
- ✅ Versioned with migrations

### **Interview Impact**

Shows you understand:

- Database performance (INT vs UUID joins)
- API security (don't expose sequential IDs)
- User experience (human-readable identifiers)
- Stored procedures (database-first thinking)
- Transaction management
- Separation of concerns
- Production patterns

**Perfect for Staff+ interviews** ⭐

---

## Next Steps

1. ✅ **Update V1_COMPONENT_PRDS.md** with trinity + functions
2. ✅ **Update V1_DOCUMENTATION_PLAN.md** Quick Start
3. ✅ **Update FRAISEQL_V1_BLUEPRINT.md** core patterns
4. ✅ **Create example migrations** showing full pattern

**These patterns are now the DEFAULT for FraiseQL v1!** 🚀

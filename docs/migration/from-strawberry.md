# Migrating from Strawberry to FraiseQL

**Estimated Time:** 2-3 weeks for a team of 2 engineers
**Difficulty:** Medium
**Risk Level:** Low (incremental migration possible)

---

## Overview

This guide helps teams migrate from **Strawberry GraphQL** to **FraiseQL**. Both frameworks prioritize modern Python features (dataclasses, type hints), making migration relatively straightforward.

### Key Differences

| Aspect | Strawberry | FraiseQL |
|--------|-----------|----------|
| **Type System** | Python dataclasses + decorators | Python dataclasses + decorators |
| **Database** | ORM-agnostic (SQLAlchemy, etc.) | PostgreSQL-first with views |
| **Performance** | Pure Python JSON | Rust pipeline (7-10x faster) |
| **Data Layer** | Manual resolvers | Automatic from views/tables |
| **Multi-tenancy** | Manual implementation | Built-in with trinity pattern |
| **Mutations** | Manual field resolvers | Database functions + CASCADE |

---

## Migration Strategy

### Recommended Approach: Parallel Run

1. **Week 1**: Set up FraiseQL alongside Strawberry
2. **Week 2**: Migrate queries incrementally
3. **Week 3**: Migrate mutations and cutover

### Alternative: Big Bang (1 week for small apps)

For applications with <20 types and simple queries.

---

## Step 1: Database Schema Migration (2-3 days)

### 1.1 Adopt Trinity Pattern

Strawberry typically uses simple table names. FraiseQL recommends the trinity pattern.

**Before (Strawberry):**

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY,
    email TEXT NOT NULL,
    name TEXT
);

CREATE TABLE posts (
    id UUID PRIMARY KEY,
    title TEXT,
    content TEXT,
    author_id UUID REFERENCES users(id)
);
```

**After (FraiseQL):**

```sql
-- Base tables (source of truth)
CREATE TABLE tb_user (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    name TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE tb_post (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    content TEXT,
    author_id UUID REFERENCES tb_user(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Views for GraphQL (what clients see)
CREATE VIEW v_user AS
SELECT id, email, name, created_at FROM tb_user;

CREATE VIEW v_post AS
SELECT id, title, content, author_id, created_at FROM tb_post;

-- Computed views (denormalized for performance)
CREATE TABLE tv_post_with_author AS
SELECT
    p.id,
    p.title,
    p.content,
    p.created_at,
    jsonb_build_object(
        'id', u.id,
        'name', u.name,
        'email', u.email
    ) as author
FROM tb_post p
JOIN tb_user u ON p.author_id = u.id;
```

**Migration Script:**

```sql
-- Rename existing tables
ALTER TABLE users RENAME TO tb_user;
ALTER TABLE posts RENAME TO tb_post;

-- Create views
CREATE VIEW v_user AS SELECT * FROM tb_user;
CREATE VIEW v_post AS SELECT * FROM tb_post;
```

**See:** [Trinity Pattern Guide](../core/trinity-pattern.md) for details.

---

## Step 2: Type Definitions (1 day)

### 2.1 Convert Strawberry Types to FraiseQL

**Before (Strawberry):**

```python
import strawberry
from typing import Optional

@strawberry.type
class User:
    id: strawberry.ID
    email: str
    name: Optional[str]

@strawberry.type
class Post:
    id: strawberry.ID
    title: str
    content: str
    author: User
```

**After (FraiseQL):**

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    email: str
    name: str | None
    created_at: str  # ISO 8601 timestamp

@fraiseql.type(sql_source="v_post")
class Post:
    id: ID
    title: str
    content: str
    author_id: ID
    created_at: str

    @fraiseql.field
    async def author(self, info) -> User:
        """Resolve author from database"""
        from fraiseql.database import get_db
        db = get_db(info.context)
        return await db.find_one("v_user", where={"id": self.author_id})
```

### Key Changes

1. **`@strawberry.type`** → **`@fraiseql.type(sql_source="v_user")`**
   - Add `sql_source` parameter pointing to database view

2. **`strawberry.ID`** → **`UUID`**
   - FraiseQL uses proper UUID type (PostgreSQL native)

3. **`Optional[str]`** → **`str | None`**
   - Modern Python 3.10+ union syntax

4. **Relationships**: Strawberry auto-resolves → FraiseQL explicit resolvers

---

## Step 3: Query Migration (2-3 days)

### 3.1 Simple Queries

**Before (Strawberry):**

```python
@strawberry.type
class Query:
    @strawberry.field
    async def user(self, id: strawberry.ID) -> Optional[User]:
        # Manual database query
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE id = $1",
                UUID(id)
            )
            if row:
                return User(**dict(row))
        return None
```

**After (FraiseQL):**

```python
@fraiseql.query
class Query:
    @fraiseql.field
    async def user(self, info, id: ID) -> User | None:
        """Get user by ID"""
        db = fraiseql.get_db(info.context)
        return await db.find_one("v_user", where={"id": id})
```

### 3.2 List Queries with Filtering

**Before (Strawberry):**

```python
@strawberry.type
class Query:
    @strawberry.field
    async def users(
        self,
        limit: int = 10,
        offset: int = 0,
        active: Optional[bool] = None
    ) -> list[User]:
        query = "SELECT * FROM users"
        params = []

        if active is not None:
            query += " WHERE is_active = $1"
            params.append(active)

        query += f" LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
        params.extend([limit, offset])

        async with db_pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [User(**dict(row)) for row in rows]
```

**After (FraiseQL):**

```python
@fraiseql.query
class Query:
    @fraiseql.field
    async def users(
        self,
        info,
        limit: int = 10,
        offset: int = 0,
        where: dict | None = None
    ) -> list[User]:
        """List users with filtering"""
        db = fraiseql.get_db(info.context)
        return await db.find(
            "v_user",
            where=where,
            limit=limit,
            offset=offset
        )
```

**GraphQL Query:**

```graphql
# Before (Strawberry) - limited filtering
query {
  users(limit: 10, active: true) {
    id
    email
    name
  }
}

# After (FraiseQL) - powerful filtering
query {
  users(
    limit: 10
    where: {
      is_active: { _eq: true }
      email: { _like: "%@example.com" }
    }
  ) {
    id
    email
    name
  }
}
```

---

## Step 4: Mutation Migration (2-3 days)

> **Field names:** these examples pass `name=` so each mutation is served under its class name (`CreatePost` → `createPost`). Without it, fraiseql 1.x serves a class whose `function=` differs from its name, such as `fn_create_post`, under the function's name (`fnCreatePost`) and the schema build emits a `FutureWarning`; from fraiseql 2.0 the class name is used. See [Mutation field names](../reference/decorators.md#mutation-field-names).

### 4.1 Simple Mutations

**Before (Strawberry):**

```python
@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_user(
        self,
        email: str,
        name: str
    ) -> User:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO users (email, name)
                VALUES ($1, $2)
                RETURNING *
                """,
                email, name
            )
            return User(**dict(row))
```

**After (FraiseQL):**

```python
@fraiseql.mutation(
    function="fn_create_user",
    schema="public",
    name="createUser",
)
class CreateUser:
    """Create a new user"""
    email: str
    name: str

# Database function:
# See [canonical fn_create_user()](../examples/canonical-examples.md#create-user-function)
# for the complete implementation with validation and error handling.

# Simple version for migration reference:
```sql
CREATE OR REPLACE FUNCTION fn_create_user(p_email TEXT, p_name TEXT)
RETURNS UUID AS $$
BEGIN
    INSERT INTO tb_user (email, name) VALUES (p_email, p_name) RETURNING id;
END;
$$ LANGUAGE plpgsql;
```

### 4.2 Complex Mutations with CASCADE

One of FraiseQL's killer features is automatic cache invalidation with CASCADE.

**Before (Strawberry):**

```python
@strawberry.mutation
async def create_post(
    self,
    title: str,
    content: str,
    author_id: ID
) -> Post:
    # Create post
    async with db_pool.acquire() as conn:
        post_row = await conn.fetchrow(
            """
            INSERT INTO posts (title, content, author_id)
            VALUES ($1, $2, $3)
            RETURNING *
            """,
            title, content, author_id
        )

        # Manually fetch author for response
        author_row = await conn.fetchrow(
            "SELECT * FROM users WHERE id = $1",
            author_id
        )

        return Post(
            **dict(post_row),
            author=User(**dict(author_row))
        )

    # Client must manually update cache or refetch
```

**After (FraiseQL with CASCADE):**

```python
@fraiseql.mutation(
    function="fn_create_post",
    name="createPost",
    enable_cascade=True  # Automatic cache invalidation!
)
class CreatePost:
    """Create a new post"""
    title: str
    content: str
    author_id: ID

# Database function:
CREATE OR REPLACE FUNCTION fn_create_post(
    input_title TEXT,
    input_content TEXT,
    input_author_id UUID
) RETURNS UUID AS $$
DECLARE
    new_post_id UUID;
BEGIN
    INSERT INTO tb_post (title, content, author_id)
    VALUES (input_title, input_content, input_author_id)
    RETURNING id INTO new_post_id;

    RETURN new_post_id;
END;
$$ LANGUAGE plpgsql;
```

**What CASCADE Does:**

- Automatically returns updated `User` object with new post count
- Invalidates client cache for affected entities
- No manual cache updates needed in frontend

**See:** [CASCADE Documentation](../features/graphql-cascade.md)

---

## Step 5: Resolver Migration (1-2 days)

### DataLoader Pattern

**Before (Strawberry with DataLoader):**

```python
from strawberry.dataloader import DataLoader

async def load_users(keys: list[UUID]) -> list[User]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM users WHERE id = ANY($1)",
            keys
        )
        users_by_id = {row['id']: User(**dict(row)) for row in rows}
        return [users_by_id.get(key) for key in keys]

user_loader = DataLoader(load_fn=load_users)

@strawberry.type
class Post:
    author_id: ID

    @strawberry.field
    async def author(self, info) -> User:
        return await info.context['user_loader'].load(self.author_id)
```

**After (FraiseQL):**

```python
@fraiseql.type(sql_source="v_post")
class Post:
    id: ID
    title: str
    author_id: ID

    @fraiseql.dataloader_field(
        loader_class=UserLoader,
        key_field="author_id"
    )
    async def author(self, info) -> User:
        pass  # Implementation auto-generated by decorator

# FraiseQL handles DataLoader creation automatically
```

**Benefit:** Less boilerplate, automatic batching.

---

## Step 6: Schema Setup (1 day)

### Application Configuration

**Before (Strawberry):**

```python
import strawberry
from strawberry.fastapi import GraphQLRouter

schema = strawberry.Schema(query=Query, mutation=Mutation)
graphql_app = GraphQLRouter(schema)

app.include_router(graphql_app, prefix="/graphql")
```

**After (FraiseQL):**

```python
from fraiseql import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://user:pass@localhost/db",
    enable_rust_pipeline=True,  # 7-10x JSON performance
    enable_cascade=True,  # Automatic cache invalidation
)
```

**Configuration Options:**

```python
app = create_fraiseql_app(
    database_url=os.environ["DATABASE_URL"],
    enable_rust_pipeline=True,
    enable_cascade=True,
    allow_introspection=True,  # GraphiQL in development
    cors_origins=["https://example.com"],

    # Multi-tenancy (if needed)
    tenant_id_header="X-Tenant-ID",
)
```

---

## Step 7: Testing Migration (1-2 days)

### Test Strategy

1. **Unit Tests**: Convert Strawberry resolver tests to FraiseQL
2. **Integration Tests**: Test PostgreSQL functions
3. **E2E Tests**: GraphQL queries through HTTP

### Example Test Migration

**Before (Strawberry):**

```python
import pytest
from app import schema

@pytest.mark.asyncio
async def test_create_user():
    query = """
        mutation {
            createUser(email: "test@example.com", name: "Test") {
                id
                email
                name
            }
        }
    """
    result = await schema.execute(query)
    assert result.errors is None
    assert result.data['createUser']['email'] == "test@example.com"
```

**After (FraiseQL):**

```python
import pytest
from fraiseql.testing import GraphQLClient

@pytest.mark.asyncio
async def test_create_user(graphql_client: GraphQLClient):
    result = await graphql_client.execute("""
        mutation {
            createUser(input: {email: "test@example.com", name: "Test"}) {
                id
                email
                name
            }
        }
    """)
    assert result.errors is None
    assert result.data['createUser']['email'] == "test@example.com"
```

---

## Common Pitfalls

### 1. Forgetting to Create Database Functions for Mutations

**Symptom:** `MutationError: Function fn_create_user does not exist`

**Fix:** Create PostgreSQL function before defining mutation:

```sql
CREATE OR REPLACE FUNCTION fn_create_user(...) RETURNS UUID AS $$
BEGIN
    -- Implementation
END;
$$ LANGUAGE plpgsql;
```

### 2. Using Wrong View Names

**Symptom:** `ViewNotFoundError: View v_users not found`

**Fix:** Ensure view name matches `sql_source` parameter:

```python
@fraiseql.type(sql_source="v_user")  # Must match view name exactly
class User:
    ...
```

### 3. Missing Trinity Pattern

**Symptom:** Multi-tenancy doesn't work, queries return all data

**Fix:** Adopt trinity pattern with `tb_`, `v_`, `tv_` prefixes.

### 4. Not Enabling Rust Pipeline

**Symptom:** Performance is similar to Strawberry

**Fix:** Enable Rust pipeline:

```python
app = create_fraiseql_app(enable_rust_pipeline=True)
```

---

## Performance Comparison

### Before (Strawberry)

- **Query Time**: 8-12ms (100 objects)
- **JSON Serialization**: Python `json.dumps()`
- **N+1 Queries**: Manual DataLoader setup

### After (FraiseQL)

- **Query Time**: 0.8-1.2ms (100 objects) - **10x faster**
- **JSON Serialization**: Rust pipeline
- **N+1 Queries**: Automatic DataLoader batching

**Benchmark:**

```bash
# Before
wrk -t4 -c100 -d30s http://localhost:8000/graphql
Requests/sec: 1,200

# After
wrk -t4 -c100 -d30s http://localhost:8000/graphql
Requests/sec: 12,000  # 10x improvement
```

---

## Migration Checklist

- [ ] Database schema migrated to trinity pattern
- [ ] Views created (`v_*` for all tables)
- [ ] Types converted to FraiseQL decorators
- [ ] Queries migrated to use `db.find()` / `db.find_one()`
- [ ] Mutations converted to PostgreSQL functions
- [ ] CASCADE enabled for mutations that need it
- [ ] DataLoaders converted to `@dataloader_field`
- [ ] Tests updated and passing
- [ ] Performance benchmarks run (should see 7-10x improvement)
- [ ] Production deployment checklist completed

---

## Support

- **Documentation**: [FraiseQL Docs](../README.md)
- **Discord**: [Join Community](https://discord.gg/fraiseql)
- **GitHub**: [Report Issues](https://github.com/fraiseql/fraiseql/issues)

---

## Next Steps

1. Read [Trinity Pattern Guide](../core/trinity-pattern.md)
2. Review [CASCADE Documentation](../features/graphql-cascade.md)
3. Check [Production Deployment Checklist](../tutorials/production-deployment.md)
4. Join Discord for migration support

**Estimated Total Time:** 2-3 weeks for 2 engineers
**Confidence Level:** High (many successful migrations)

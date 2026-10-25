# Migrating from PostGraphile to FraiseQL

**Estimated Time:** 3-4 days for 1 engineer
**Difficulty:** Low
**Risk Level:** Very Low (both are PostgreSQL-first)

---

## Overview

This guide helps teams migrate from **PostGraphile** to **FraiseQL**. This is the **easiest migration** since both frameworks are PostgreSQL-first and share similar philosophies.

### Key Similarities ✅

| Aspect | PostGraphile | FraiseQL |
|--------|--------------|----------|
| **Database** | PostgreSQL-first ✅ | PostgreSQL-first ✅ |
| **Schema Source** | Database introspection ✅ | Database views ✅ |
| **Functions** | PostgreSQL functions ✅ | PostgreSQL functions ✅ |
| **RLS** | Row-level security ✅ | Row-level security ✅ |
| **Performance** | Fast (C bindings) | Fast (Rust pipeline) |

### Key Differences

| Aspect | PostGraphile | FraiseQL |
|--------|--------------|----------|
| **Language** | Node.js/TypeScript | Python |
| **Type Safety** | GraphQL schema from DB | Python type hints |
| **Customization** | Plugins (makeExtendSchemaPlugin) | Python resolvers |
| **JSON Performance** | Node.js native | Rust (7-10x faster) |
| **CASCADE** | Manual | Automatic |

---

## Why Migrate?

### You Should Migrate If

1. **Python ecosystem**: Your team prefers Python over Node.js
2. **Type safety**: You want Python type hints for resolvers
3. **Performance**: You need 7-10x JSON serialization speedup
4. **CASCADE**: You want automatic cache invalidation
5. **Customization**: PostGraphile plugins feel too complex

### You Should Stay If

1. **Node.js shop**: Your entire stack is JavaScript/TypeScript
2. **Minimal custom logic**: PostGraphile auto-generation works perfectly
3. **Migration cost**: 3-4 days is still too much overhead

---

## Migration Strategy

### Recommended Approach: Direct Translation (3-4 days)

- **Day 1**: Set up FraiseQL, minimal schema
- **Day 2**: Migrate custom resolvers and functions
- **Day 3**: Testing and performance validation
- **Day 4**: Deployment and cutover

### Why So Fast?

- Database schema already optimal (PostgreSQL-first)
- Functions already in PostgreSQL
- Views likely already exist
- RLS policies already configured

**Main work:** Translating custom logic from TypeScript to Python.

---

## Step 1: Database Schema (Minimal Changes)

### 1.1 Trinity Pattern Alignment

PostGraphile typically uses simple table names. FraiseQL recommends the trinity pattern but **your existing schema probably works as-is**.

**Current (PostGraphile):**

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    name TEXT
);

CREATE TABLE posts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT,
    content TEXT,
    author_id UUID REFERENCES users(id)
);
```

**Option A: Keep As-Is (Quickest)**

```sql
-- Create views pointing to existing tables
CREATE VIEW v_user AS SELECT * FROM users;
CREATE VIEW v_post AS SELECT * FROM posts;
```

**Option B: Adopt Trinity Pattern (Recommended for Multi-tenancy)**

```sql
-- Rename tables
ALTER TABLE users RENAME TO tb_user;
ALTER TABLE posts RENAME TO tb_post;

-- Create views
CREATE VIEW v_user AS SELECT * FROM tb_user;
CREATE VIEW v_post AS SELECT * FROM tb_post;
```

**Decision:** If you don't need multi-tenancy, Option A is fine. Otherwise, Option B.

---

## Step 2: Custom Resolvers (1-2 days)

### 2.1 Simple Field Resolvers

**Before (PostGraphile + makeExtendSchemaPlugin):**

```typescript
// plugins/customResolvers.ts
import { makeExtendSchemaPlugin, gql } from "graphile-utils";

const CustomResolversPlugin = makeExtendSchemaPlugin({
  typeDefs: gql`
    extend type User {
      fullName: String!
    }
  `,
  resolvers: {
    User: {
      fullName(user) {
        return `${user.firstName} ${user.lastName}`;
      }
    }
  }
});
```

**After (FraiseQL):**

```python
@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    first_name: str
    last_name: str

    @fraiseql.field
    def full_name(self) -> str:
        """Computed field: full name"""
        return f"{self.first_name} {self.last_name}"
```

**Key Changes:**

- TypeScript → Python (simpler syntax)
- Plugin system → Direct decorator
- `gql` strings → Type hints

---

## Step 3: Custom Queries (1 day)

### 3.1 Basic Queries

**Before (PostGraphile - Auto-generated):**

```graphql
# No code needed - PostGraphile generates automatically
query {
  allUsers {
    nodes {
      id
      email
      name
    }
  }
}
```

**After (FraiseQL - Same auto-generation + customization):**

FraiseQL doesn't generate queries from the schema: each one is an `async` function.
A query returning `list[User]` gets `where`, `orderBy`, `limit` and `offset`
arguments, applied by `find`:

```python
@fraiseql.query
async def user(info, id: ID) -> User | None:
    """Get user by ID"""
    db = info.context["db"]
    return await db.find_one("v_user", "user", info, where={"id": id})


@fraiseql.query
async def users(info, limit: int = 100) -> list[User]:
    """List users"""
    db = info.context["db"]
    return await db.find("v_user", "users", info, limit=limit)
```

**GraphQL Query:**

```graphql
query {
  users(where: {email: {endswith: "@example.com"}}) {
    id
    email
    name
  }
}
```

---

## Step 4: Mutations (1 day)

> **Field names:** these examples pass `name=` so each mutation is served under its class name (`CreatePost` → `createPost`). Without it, fraiseql 1.x serves a class whose `function=` differs from its name, such as `fn_create_post`, under the function's name (`fnCreatePost`) and the schema build emits a `FutureWarning`; from fraiseql 2.0 the class name is used. See [Mutation field names](../reference/decorators.md#mutation-field-names).

### 4.1 Database Function Mutations

**Before (PostGraphile):**

```sql
-- Database function (same in both!)
CREATE OR REPLACE FUNCTION create_user(
    input_email TEXT,
    input_name TEXT
) RETURNS users AS $$
DECLARE
    new_user users;
BEGIN
    INSERT INTO users (email, name)
    VALUES (input_email, input_name)
    RETURNING * INTO new_user;

    RETURN new_user;
END;
$$ LANGUAGE plpgsql VOLATILE;
```

```typescript
// PostGraphile auto-generates GraphQL mutation
// No TypeScript code needed!
```

**After (FraiseQL):**

```sql
-- Same PostgreSQL function!
-- (Or rename to fn_create_user for consistency)
```

```python
@fraiseql.input
class CreateUserInput:
    email: str
    name: str


@fraiseql.success
class CreateUserSuccess:
    user: User


@fraiseql.error
class CreateUserError:
    """status, message, errors and code are added by @fraiseql.error"""


@fraiseql.mutation(function="fn_create_user", name="createUser")
class CreateUser:
    """Create a new user"""
    input: CreateUserInput
    success: CreateUserSuccess
    error: CreateUserError
```

**Key Insight:** your logic stays in PostgreSQL functions. FraiseQL calls a
mutation's function with the input as one `jsonb` argument and reads a
`mutation_response` back (`migrations/trinity/005_add_mutation_response.sql` has the
type and the `mutation_*` helpers), so a PostGraphile function taking separate
arguments needs a thin `fn_create_user(input jsonb)` wrapper.

### 4.2 Mutations with CASCADE

**Before (PostGraphile):**

```typescript
// Custom mutation with manual cache invalidation
import { makeExtendSchemaPlugin, gql } from "graphile-utils";

const CreatePostPlugin = makeExtendSchemaPlugin({
  typeDefs: gql`
    input CreatePostInput {
      title: String!
      content: String!
      authorId: UUID!
    }

    type CreatePostPayload {
      post: Post
    }

    extend type Mutation {
      createPost(input: CreatePostInput!): CreatePostPayload
    }
  `,
  resolvers: {
    Mutation: {
      async createPost(_query, args, context) {
        const { title, content, authorId } = args.input;
        const { rows } = await context.pgClient.query(
          'INSERT INTO posts (title, content, author_id) VALUES ($1, $2, $3) RETURNING *',
          [title, content, authorId]
        );

        // Manual: Client must refetch or update cache
        return { post: rows[0] };
      }
    }
  }
});
```

**After (FraiseQL with CASCADE):**

```python
@fraiseql.input
class CreatePostInput:
    title: str
    content: str
    author_id: ID


@fraiseql.success
class CreatePostSuccess:
    post: Post


@fraiseql.error
class CreatePostError:
    """status, message, errors and code are added by @fraiseql.error"""


@fraiseql.mutation(
    function="fn_create_post",
    name="createPost",
    enable_cascade=True  # the response carries the function's cascade
)
class CreatePost:
    """Create a new post"""
    input: CreatePostInput
    success: CreatePostSuccess
    error: CreatePostError
```

`fn_create_post` returns the cascade with the `cascade_*` helpers; see the
[Graphene guide](from-graphene.md#42-complex-mutations-with-cascade) for the function.

**CASCADE Benefits:**

- Automatically returns updated User with new post
- Client cache automatically invalidated
- No manual refetch needed

**See:** [CASCADE Documentation](../features/graphql-cascade.md)

---

## Step 5: RLS and Security (Minimal Changes)

### Row-Level Security

**Before (PostGraphile):**

```sql
-- RLS policies (same in both!)
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON users
USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

```typescript
// PostGraphile JWT claims → PostgreSQL session variables
// Handled by postgraphile library
```

**After (FraiseQL):**

```sql
-- Same RLS policies!
-- No changes needed
```

```python
from fastapi import Request

from fraiseql.fastapi import create_fraiseql_app


async def get_context(request: Request) -> dict:
    # In production, take the tenant from the verified token, never from the client
    return {"tenant_id": request.headers.get("X-Tenant-ID")}


app = create_fraiseql_app(
    database_url="postgresql://...",
    types=[User],
    queries=[user, users],
    context_getter=get_context,
)
```

Before each query and mutation, FraiseQL runs `SET LOCAL app.tenant_id` (and
`app.user_id`, `app.contact_id`) from the request context, so the policy's
`current_setting('app.tenant_id')` sees the request's tenant. Map other context keys
with `FraiseQLConfig(session_variables=...)`. See
[Multi-tenant SaaS](../patterns/saas-multi-tenant.md).

**Key Insight:** Your RLS policies work identically in FraiseQL!

---

## Step 6: Schema Setup (1 hour)

### Application Configuration

**Before (PostGraphile):**

```typescript
// server.ts
import { postgraphile } from "postgraphile";
import express from "express";

const app = express();

app.use(
  postgraphile(
    process.env.DATABASE_URL,
    "public",
    {
      watchPg: true,
      graphiql: true,
      enhanceGraphiql: true,
      dynamicJson: true,
      setofFunctionsContainNulls: false,
      ignoreRBAC: false,
      showErrorStack: "json",
      extendedErrors: ["hint", "detail", "errcode"],
      appendPlugins: [CustomResolversPlugin, CreatePostPlugin],
      graphileBuildOptions: {
        connectionFilterRelations: true,
        orderByNullsLast: true,
      },
    }
  )
);

app.listen(5000);
```

**After (FraiseQL):**

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://...",
    types=[User, Post],
    queries=[user, users],
    mutations=[CreateUser, CreatePost],
)

# Run with:
# uvicorn app:app --port 5000
```

The Rust pipeline is always on, cascades are turned on per mutation
(`enable_cascade=True`), and GraphiQL is served in development
(`enable_playground`, `introspection_policy` on `FraiseQLConfig`).

**Simpler:** No plugin system, just Python configuration.

---

## Step 7: Testing (1 day)

### Test Migration

**Before (PostGraphile + Jest):**

```typescript
import { createPostGraphileSchema } from "postgraphile";
import { graphql } from "graphql";

describe("User queries", () => {
  it("should fetch user by ID", async () => {
    const schema = await createPostGraphileSchema(dbUrl, "public");

    const result = await graphql(
      schema,
      `query { userById(id: "${userId}") { id email } }`
    );

    expect(result.data.userById.email).toBe("test@example.com");
  });
});
```

**After (FraiseQL + pytest):**

```python
from fastapi.testclient import TestClient


def test_user_by_id(app, user_id):
    """`app` is your create_fraiseql_app(...) app, against a test database"""
    with TestClient(app) as client:  # runs the app's lifespan, which opens the pool
        body = client.post("/graphql", json={
            "query": "query ($id: ID!) { user(id: $id) { id email } }",
            "variables": {"id": user_id},
        }).json()
    assert "errors" not in body
    assert body["data"]["user"]["email"] == "test@example.com"
```

**Similar complexity, different language.**

---

## Common Pitfalls

### 1. Forgetting Async/Await

PostGraphile uses promises, FraiseQL uses async/await.

**Fix:**

```python
# ✅ Correct
@fraiseql.query
async def user(info, id: ID) -> User | None:
    return await info.context["db"].find_one("v_user", "user", info, where={"id": id})
```

### 2. Smart Comments/Tags

PostGraphile uses smart comments (`@omit create,update`).
FraiseQL uses explicit decorators.

**Before (PostGraphile):**

```sql
COMMENT ON TABLE users IS E'@omit create,update';
```

**After (FraiseQL):**

```python
# Just don't create the mutation classes
# Only expose what you want
```

### 3. Nested Mutations

PostGraphile supports nested `create`/`connect` patterns.
FraiseQL uses explicit mutations.

**Solution:** Create separate mutations or use PostgreSQL functions with logic.

---

## Performance Comparison

### Before (PostGraphile)

- **Query Time**: 2-4ms (100 objects)
- **JSON Serialization**: Node.js native
- **Throughput**: ~5,000 req/s

### After (FraiseQL)

- **Query Time**: 0.8-1.2ms (100 objects) - **2-3x faster**
- **JSON Serialization**: Rust pipeline
- **Throughput**: ~12,000 req/s - **2-3x higher**

**Note:** Both are fast! FraiseQL's edge is in JSON-heavy workloads.

---

## Migration Checklist

- [ ] Database schema reviewed (trinity pattern optional)
- [ ] Views created if needed
- [ ] Custom TypeScript resolvers converted to Python
- [ ] Mutations mapped to PostgreSQL functions
- [ ] RLS policies verified (should work as-is)
- [ ] Tests converted to pytest
- [ ] Performance benchmarks run
- [ ] CASCADE enabled for appropriate mutations
- [ ] Deployment configuration updated

---

## Decision Matrix

| Factor | Keep PostGraphile | Migrate to FraiseQL |
|--------|-------------------|---------------------|
| **Team uses Python** | ❌ | ✅ |
| **Need JSON performance boost** | ❌ | ✅ (7-10x faster) |
| **Want automatic CASCADE** | ❌ | ✅ |
| **Minimal custom logic** | ✅ (auto-gen works great) | ➖ |
| **Node.js expertise** | ✅ | ❌ |
| **Plugin system works** | ✅ | ❌ |
| **Migration cost < 1 week** | ❌ | ✅ (3-4 days) |

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

**Estimated Total Time:** 3-4 days for 1 engineer
**Confidence Level:** Very High (easiest migration path)
**Recommendation:** Excellent choice if your team prefers Python over Node.js

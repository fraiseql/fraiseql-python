# Migrating from Graphene to FraiseQL

**Estimated Time:** 1-2 weeks for a team of 2 engineers
**Difficulty:** Medium-Low
**Risk Level:** Low (incremental migration possible)

---

## Overview

This guide helps teams migrate from **Graphene** to **FraiseQL**. Graphene is a mature Python GraphQL library, but FraiseQL offers significant performance improvements and PostgreSQL-first design.

### Key Differences

| Aspect | Graphene | FraiseQL |
|--------|----------|----------|
| **Type System** | Python classes + Meta | Python dataclasses + decorators |
| **Database** | ORM-focused (Django, SQLAlchemy) | PostgreSQL-first with views |
| **Performance** | Pure Python JSON | Rust pipeline (7-10x faster) |
| **Syntax** | Verbose class hierarchy | Modern Python 3.10+ |
| **Multi-tenancy** | Manual implementation | Built-in with trinity pattern |
| **Mutations** | Resolver methods | Database functions |

---

## Migration Strategy

### Recommended Approach: Incremental (1-2 weeks)

1. **Days 1-2**: Set up FraiseQL alongside Graphene
2. **Days 3-5**: Migrate queries type-by-type
3. **Days 6-8**: Migrate mutations
4. **Days 9-10**: Testing and cutover

### Why Faster Than Strawberry?

Graphene's verbose syntax actually makes migration easier:

- Clear type definitions → Easy to convert
- Explicit resolvers → Map directly to FraiseQL patterns
- Fewer magic features → Less to unlearn

---

## Step 1: Database Schema Migration (1-2 days)

### 1.1 From Django ORM to Trinity Pattern

Graphene is often used with Django. Here's how to migrate:

**Before (Django ORM + Graphene):**

```python
# models.py
from django.db import models

class User(models.Model):
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

class Post(models.Model):
    title = models.CharField(max_length=255)
    content = models.TextField()
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
```

**After (PostgreSQL + FraiseQL):**

```sql
-- Base tables (source of truth)
CREATE TABLE tb_user (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE tb_post (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    content TEXT,
    author_id UUID REFERENCES tb_user(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Views for GraphQL
CREATE VIEW v_user AS
SELECT id, email, name, created_at FROM tb_user;

CREATE VIEW v_post AS
SELECT id, title, content, author_id, created_at FROM tb_post;

-- Computed view with author embedded
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

**Migration Path:**

1. Keep Django models for existing app
2. Create PostgreSQL views pointing to Django tables
3. Gradually migrate logic to PostgreSQL functions
4. Eventually remove Django ORM

**See:** [Trinity Pattern Guide](../core/trinity-pattern.md)

---

## Step 2: Type Definitions (1 day)

### 2.1 Convert Graphene ObjectTypes

**Before (Graphene):**

```python
import graphene
from graphene_django import DjangoObjectType

class UserType(DjangoObjectType):
    class Meta:
        model = User
        fields = ("id", "email", "name", "created_at")

class PostType(DjangoObjectType):
    author = graphene.Field(UserType)

    class Meta:
        model = Post
        fields = ("id", "title", "content", "created_at")

    def resolve_author(self, info):
        return self.author
```

**After (FraiseQL):**

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    email: str
    name: str
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
        db = fraiseql.get_db(info.context)
        return await db.find_one("v_user", where={"id": self.author_id})
```

### Key Changes

1. **`DjangoObjectType`** → **`@fraiseql.type(sql_source="v_user")`**
   - No Meta class needed
   - Explicitly declare fields with type hints

2. **`graphene.Field(UserType)`** → **`async def author(self, info) -> User:`**
   - Explicit async resolver
   - Type hints for return type

3. **`graphene.ID`** → **`UUID`**
   - PostgreSQL native UUID type

---

## Step 3: Query Migration (1-2 days)

### 3.1 Simple Queries

**Before (Graphene):**

```python
class Query(graphene.ObjectType):
    user = graphene.Field(UserType, id=graphene.ID(required=True))
    users = graphene.List(UserType)

    def resolve_user(self, info, id):
        return User.objects.get(pk=id)

    def resolve_users(self, info):
        return User.objects.all()
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

    @fraiseql.field
    async def users(self, info, limit: int = 100) -> list[User]:
        """List users"""
        db = fraiseql.get_db(info.context)
        return await db.find("v_user", limit=limit)
```

### 3.2 Queries with Filtering

**Before (Graphene with django-filter):**

```python
from graphene_django.filter import DjangoFilterConnectionField

class Query(graphene.ObjectType):
    users = DjangoFilterConnectionField(UserType)

# GraphQL
query {
  users(email_Icontains: "example.com") {
    edges {
      node {
        id
        email
        name
      }
    }
  }
}
```

**After (FraiseQL):**

```python
@fraiseql.query
class Query:
    @fraiseql.field
    async def users(
        self,
        info,
        where: dict | None = None,
        limit: int = 100
    ) -> list[User]:
        """List users with filtering"""
        db = fraiseql.get_db(info.context)
        return await db.find("v_user", where=where, limit=limit)

# GraphQL (more powerful filtering)
query {
  users(where: {
    email: { endswith: "@example.com" }
    created_at: { gte: "2025-01-01" }
  }) {
    id
    email
    name
  }
}
```

**FraiseQL Filter Operators:**

- `eq`, `neq` (equals, not equals)
- `lt`, `lte`, `gt`, `gte` (comparisons)
- `contains`, `icontains` (substring matching - case-sensitive and case-insensitive)
- `startswith`, `endswith`, `istartswith`, `iendswith` (pattern matching)
- `in`, `nin` (array membership)
- `isnull` (null checks)
- `like`, `ilike` (SQL LIKE with explicit wildcards)

See [Filter Operators Reference](../advanced/filter-operators.md) for complete list

---

## Step 4: Mutation Migration (2-3 days)

> **Field names:** these examples show each mutation under its class name (`CreatePost` → `createPost`). In fraiseql 1.x, a class whose `function=` differs from its name, such as `fn_create_post`, is still served under the function's name (`fnCreatePost`), and the schema build emits a `FutureWarning`. Pass `name="createPost"` to get the names shown here now. See [Mutation field names](../reference/decorators.md#mutation-field-names).

### 4.1 Simple Mutations

**Before (Graphene):**

```python
class CreateUser(graphene.Mutation):
    class Arguments:
        email = graphene.String(required=True)
        name = graphene.String(required=True)

    user = graphene.Field(UserType)

    @staticmethod
    def mutate(root, info, email, name):
        user = User.objects.create(email=email, name=name)
        return CreateUser(user=user)

class Mutation(graphene.ObjectType):
    create_user = CreateUser.Field()
```

**After (FraiseQL):**

```python
@fraiseql.mutation(function="fn_create_user")
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

**Before (Graphene + Manual Cache Invalidation):**

```python
class CreatePost(graphene.Mutation):
    class Arguments:
        title = graphene.String(required=True)
        content = graphene.String(required=True)
        author_id = graphene.ID(required=True)

    post = graphene.Field(PostType)

    @staticmethod
    def mutate(root, info, title, content, author_id):
        author = User.objects.get(pk=author_id)
        post = Post.objects.create(
            title=title,
            content=content,
            author=author
        )

        # Manual: Client must refetch or update cache
        return CreatePost(post=post)
```

**After (FraiseQL with CASCADE):**

```python
@fraiseql.mutation(
    function="fn_create_post",
    enable_cascade=True  # Automatic cache invalidation!
)
class CreatePost:
    """Create a new post"""
    title: str
    content: str
    author_id: ID

# Database function
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

**CASCADE Benefits:**

- Automatically returns updated User with new post
- Client cache automatically invalidated
- No manual refetch needed

**See:** [CASCADE Documentation](../features/graphql-cascade.md)

---

## Step 5: Resolver Optimization (1 day)

### N+1 Query Problem

**Before (Graphene with DataLoader):**

```python
from promise import Promise
from promise.dataloader import DataLoader

class UserLoader(DataLoader):
    def batch_load_fn(self, keys):
        users = User.objects.filter(pk__in=keys)
        user_map = {user.id: user for user in users}
        return Promise.resolve([user_map.get(key) for key in keys])

class PostType(DjangoObjectType):
    author = graphene.Field(UserType)

    def resolve_author(self, info):
        return info.context.user_loader.load(self.author_id)

# Setup in context
from django.views.decorators.csrf import csrf_exempt
from graphene_django.views import GraphQLView

def get_context(request):
    return {
        'user_loader': UserLoader(),
    }

urlpatterns = [
    path('graphql/', csrf_exempt(GraphQLView.as_view(
        graphiql=True,
        schema=schema,
        get_context=get_context
    ))),
]
```

**After (FraiseQL with Auto DataLoader):**

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
        pass  # Auto-generated batching

# FraiseQL handles DataLoader setup automatically
```

**Benefit:** 50-80% less boilerplate code.

---

## Step 6: Schema Setup (1 day)

### Application Configuration

**Before (Graphene + Django):**

```python
# schema.py
import graphene

class Query(graphene.ObjectType):
    # ... query fields

class Mutation(graphene.ObjectType):
    # ... mutation fields

schema = graphene.Schema(query=Query, mutation=Mutation)

# urls.py
from django.urls import path
from graphene_django.views import GraphQLView
from .schema import schema

urlpatterns = [
    path('graphql/', GraphQLView.as_view(graphiql=True, schema=schema)),
]
```

**After (FraiseQL):**

```python
from fraiseql import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://user:pass@localhost/db",
    enable_rust_pipeline=True,  # 7-10x JSON performance
    enable_cascade=True,  # Automatic cache invalidation
    allow_introspection=True,  # GraphiQL
)
```

**With Django (Hybrid Approach):**

```python
# Keep Django for admin, auth, etc.
# Add FraiseQL for GraphQL API

from django.urls import path
from fraiseql import create_fraiseql_app

fraiseql_app = create_fraiseql_app(
    database_url=settings.DATABASES['default']['URL'],
    enable_rust_pipeline=True,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('graphql/', fraiseql_app),  # FraiseQL endpoint
]
```

---

## Step 7: Testing Migration (1 day)

### Test Strategy

1. **Unit Tests**: Convert Graphene resolver tests
2. **Integration Tests**: Test PostgreSQL functions
3. **Performance Tests**: Validate speed improvements

### Example Test Migration

**Before (Graphene + pytest):**

```python
from graphene.test import Client

def test_create_user():
    client = Client(schema)
    executed = client.execute('''
        mutation {
            createUser(email: "test@example.com", name: "Test") {
                user {
                    id
                    email
                    name
                }
            }
        }
    ''')
    assert executed['data']['createUser']['user']['email'] == "test@example.com"
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

### 1. Forgetting Async/Await

**Symptom:** `RuntimeWarning: coroutine was never awaited`

**Fix:** All FraiseQL resolvers are async:

```python
# ❌ Wrong
def resolve_user(self, info, id):
    return db.find_one("v_user", where={"id": id})

# ✅ Correct
async def user(self, info, id: ID) -> User | None:
    return await db.find_one("v_user", where={"id": id})
```

### 2. Using Django ORM Patterns

**Symptom:** Trying to use `.objects.filter()` syntax

**Fix:** Use FraiseQL database API:

```python
# ❌ Wrong (Django)
users = User.objects.filter(is_active=True)

# ✅ Correct (FraiseQL)
users = await db.find("v_user", where={"is_active": True})
```

### 3. Missing Database Functions

**Symptom:** `MutationError: Function fn_create_user does not exist`

**Fix:** Create PostgreSQL function before mutation:

```sql
CREATE OR REPLACE FUNCTION fn_create_user(...) RETURNS UUID AS $$ ... $$ LANGUAGE plpgsql;
```

### 4. Verbose GraphQL Syntax

**Symptom:** Mutations require too much nesting

**Fix:** FraiseQL uses flat input structure:

```graphql
# ❌ Graphene (verbose)
mutation {
  createUser(input: {
    clientMutationId: "1"
    email: "test@example.com"
  }) {
    user {
      id
    }
  }
}

# ✅ FraiseQL (clean)
mutation {
  createUser(input: {email: "test@example.com"}) {
    id
  }
}
```

---

## Performance Comparison

### Before (Graphene + Django)

- **Query Time**: 15-25ms (100 objects)
- **JSON Serialization**: Python with Django serializers
- **Database**: Django ORM (N+1 queries common)

### After (FraiseQL)

- **Query Time**: 1.5-2.5ms (100 objects) - **10x faster**
- **JSON Serialization**: Rust pipeline
- **Database**: Optimized PostgreSQL views

**Real-World Example:**

```bash
# Before (Graphene + Django)
ab -n 1000 -c 10 http://localhost:8000/graphql
Requests per second: 150

# After (FraiseQL)
ab -n 1000 -c 10 http://localhost:8000/graphql
Requests per second: 1,500  # 10x improvement
```

---

## Migration Checklist

- [ ] Database schema migrated to trinity pattern
- [ ] Views created (`v_*` for all tables)
- [ ] Types converted to FraiseQL `@type` decorators
- [ ] Queries migrated to async `db.find()`
- [ ] Mutations converted to PostgreSQL functions
- [ ] CASCADE enabled where appropriate
- [ ] DataLoaders replaced with `@dataloader_field`
- [ ] Tests updated to async
- [ ] Performance benchmarks run (should see 7-10x improvement)
- [ ] Django integration tested (if hybrid approach)

---

## Hybrid Django + FraiseQL

You can keep Django for admin/auth and use FraiseQL for GraphQL:

```python
# settings.py
INSTALLED_APPS = [
    'django.contrib.admin',  # Keep Django admin
    'django.contrib.auth',   # Keep Django auth
    # ... other Django apps
]

# urls.py
from django.contrib import admin
from django.urls import path
from fraiseql import create_fraiseql_app

fraiseql_app = create_fraiseql_app(
    database_url=settings.DATABASES['default']['URL'],
    enable_rust_pipeline=True,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/graphql/', fraiseql_app),
]
```

**Benefits:**

- Keep Django admin interface
- Keep Django authentication
- Get FraiseQL performance for API
- Gradual migration possible

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

**Estimated Total Time:** 1-2 weeks for 2 engineers
**Confidence Level:** High (simpler than Strawberry migration)

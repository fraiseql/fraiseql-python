# FraiseQL Migration Guides

**Purpose:** Comprehensive guides for migrating from other GraphQL frameworks to FraiseQL.

These guides provide step-by-step instructions, code examples, timeline estimates, and common pitfalls for migrating existing GraphQL APIs to FraiseQL.

---

## Available Migration Guides

### Framework-Specific Guides

| Framework | Difficulty | Time Estimate | Guide |
|-----------|-----------|---------------|-------|
| **PostGraphile** | ⭐ Low | 3-4 days (1 engineer) | [Migration Guide](./from-postgraphile.md) |
| **Graphene** | ⭐⭐ Medium | 1-2 weeks (2 engineers) | [Migration Guide](./from-graphene.md) |
| **Strawberry** | ⭐⭐ Medium | 2-3 weeks (2 engineers) | [Migration Guide](./from-strawberry.md) |

### Generic Resources

- **[Migration Checklist](./migration-checklist.md)**: Universal 10-phase checklist applicable to any framework migration

---

## Which Guide Should I Use?

### Migrating from PostGraphile → FraiseQL

**[PostGraphile Migration Guide](./from-postgraphile.md)**

- **Best for:** Teams already using PostgreSQL-first architecture
- **Why easiest:** Both frameworks share database-first philosophy
- **Main work:** Translating TypeScript plugins to Python resolvers
- **Database changes:** Minimal (your functions and RLS policies work as-is)
- **Time:** 3-4 days for 1 engineer

**Key advantages:**

- Database schema likely already optimal
- PostgreSQL functions reusable
- RLS policies work identically
- Views may already exist

### Migrating from Graphene → FraiseQL

**[Graphene Migration Guide](./from-graphene.md)**

- **Best for:** Django-based applications with ORM models
- **Why moderate:** Need to migrate from ORM to database-first approach
- **Main work:** Converting Django models → PostgreSQL views
- **Database changes:** Moderate (adopt trinity pattern, create views)
- **Time:** 1-2 weeks for 2 engineers

**Key considerations:**

- Migrate from Django ORM to direct PostgreSQL access
- Convert `DjangoObjectType` to `@fraiseql.type` decorators
- Move business logic from Python to PostgreSQL functions
- Adopt trinity pattern (tb_/v_/tv_)

### Migrating from Strawberry → FraiseQL

**[Strawberry Migration Guide](./from-strawberry.md)**

- **Best for:** Modern Python shops already using type hints
- **Why moderate:** Database layer needs restructuring
- **Main work:** Adopting database-first architecture + trinity pattern
- **Database changes:** Significant (create views, adopt trinity pattern, move mutations to functions)
- **Time:** 2-3 weeks for 2 engineers

**Key considerations:**

- Similar decorator syntax makes type conversion easy
- Need to adopt PostgreSQL-first approach
- Move resolver logic to database views/functions
- Implement trinity pattern from scratch

---

## Quick Decision Matrix

| Your Current Setup | Recommended Guide | Key Challenge |
|-------------------|------------------|---------------|
| **PostGraphile + TypeScript** | [PostGraphile](./from-postgraphile.md) | Language switch (TS → Python) |
| **PostGraphile + Minimal plugins** | [PostGraphile](./from-postgraphile.md) | Almost no changes needed |
| **Graphene + Django** | [Graphene](./from-graphene.md) | ORM → Database-first |
| **Graphene + SQLAlchemy** | [Graphene](./from-graphene.md) | ORM → Database-first |
| **Strawberry + Manual resolvers** | [Strawberry](./from-strawberry.md) | Database restructuring |
| **Strawberry + ORM** | [Strawberry](./from-strawberry.md) | Full architecture shift |
| **Other framework** | [Migration Checklist](./migration-checklist.md) | Follow generic process |

---

## Migration Process Overview

All migrations follow a similar high-level process:

### Phase 1: Assessment (1-2 days)

- Audit current schema (types, resolvers, mutations)
- Review database structure
- Estimate effort using framework-specific guide
- Plan rollback strategy

### Phase 2: Database Preparation (1-3 days)

- Adopt trinity pattern (tb_/v_/tv_)
- Create views for GraphQL exposure
- Set up Row-Level Security (RLS) if needed
- Migrate functions to fn_* pattern

### Phase 3: Type & Query Migration (2-3 days)

- Convert types to FraiseQL decorators
- Migrate queries to use `db.find()` / `db.find_one()`
- Implement custom resolvers
- Test extensively

### Phase 4: Mutation Migration (2-3 days)

- Create PostgreSQL functions for mutations
- Map mutations to functions with `@fraiseql.mutation`
- Enable CASCADE for automatic cache invalidation
- Verify mutation behavior

### Phase 5: Testing & Deployment (2-3 days)

- Run comprehensive test suite
- Performance benchmarks (expect 7-10x improvement)
- Blue-green deployment
- Monitor for 24-48 hours

**See:** [Migration Checklist](./migration-checklist.md) for complete 10-phase breakdown

---

## Common Migration Patterns

### Pattern 1: ORM Model → PostgreSQL View

**Before (Django ORM / SQLAlchemy):**

```python
class User(models.Model):
    email = models.EmailField()
    name = models.CharField(max_length=100)
```

**After (FraiseQL):**

```sql
-- Base table
CREATE TABLE tb_user (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    name TEXT
);

-- View for GraphQL
CREATE VIEW v_user AS SELECT * FROM tb_user;
```

```python
@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    email: str
    name: str | None
```

### Pattern 2: Resolver Logic → Database Function

**Before (Python resolver):**

```python
@strawberry.mutation
async def create_user(email: str, name: str) -> User:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO users (email, name) VALUES ($1, $2) RETURNING *",
            email, name
        )
        return User(**dict(row))
```

**After (FraiseQL + PostgreSQL):**

```sql
CREATE OR REPLACE FUNCTION fn_create_user(
    input_email TEXT,
    input_name TEXT
) RETURNS UUID AS $$
DECLARE
    new_user_id UUID;
BEGIN
    INSERT INTO tb_user (email, name)
    VALUES (input_email, input_name)
    RETURNING id INTO new_user_id;

    RETURN new_user_id;
END;
$$ LANGUAGE plpgsql;
```

```python
@fraiseql.mutation(function="fn_create_user", enable_cascade=True)
class CreateUser:
    """Create a new user"""
    email: str
    name: str
```

### Pattern 3: Manual Cache Invalidation → CASCADE

**Before (Manual cache management):**

```python
# Client must manually update cache after mutation
mutation {
    createPost(input: {...}) { id }
}

# Then refetch related data
query {
    user(id: "...") {
        posts { id title }
    }
}
```

**After (FraiseQL CASCADE):**

```python
@fraiseql.mutation(function="fn_create_post", enable_cascade=True)
class CreatePost:
    title: str
    content: str
    author_id: ID
```

> **Field names:** these examples show each mutation under its class name (`CreatePost` → `createPost`). In fraiseql 1.x, a class whose `function=` differs from its name, such as `fn_create_post`, is still served under the function's name (`fnCreatePost`), and the schema build emits a `FutureWarning`. Pass `name="createPost"` to get the names shown here now. See [Mutation field names](../reference/decorators.md#mutation-field-names).

```graphql
# CASCADE automatically returns updated User with new post
mutation {
    createPost(input: {...}) {
        id
        # CASCADE magic: author is automatically updated in response
    }
}
```

---

## Performance Expectations

After migration to FraiseQL, you should see:

| Metric | Typical Improvement |
|--------|-------------------|
| **Query Latency** | 5-10x faster |
| **JSON Serialization** | 7-10x faster (Rust pipeline) |
| **Throughput** | 5-10x higher (req/s) |
| **Memory Usage** | 30-50% lower |
| **CPU Usage** | 40-60% lower |

**Real-world example:**

- **Before (Strawberry):** 8-12ms for 100 objects, ~1,200 req/s
- **After (FraiseQL):** 0.8-1.2ms for 100 objects, ~12,000 req/s

**Benchmark your migration:**

```bash
# Run performance comparison
wrk -t4 -c100 -d30s http://localhost:8000/graphql
```

---

## Support & Resources

### Documentation

- [Trinity Pattern Guide](../core/trinity-pattern.md) - Database naming conventions
- [CASCADE Documentation](../features/graphql-cascade.md) - Automatic cache invalidation
- [Production Deployment Checklist](../tutorials/production-deployment.md) - Go-live preparation

### Community Support

- **Discord**: [Join Community](https://discord.gg/fraiseql)
- **GitHub Issues**: [Report Problems](https://github.com/fraiseql/fraiseql/issues)
- **Email**: support@fraiseql.com

### Professional Services

- **Consulting**: Available for enterprise migrations
- **Training**: 1-day workshops on FraiseQL architecture
- **Support Plans**: Priority support for production deployments

---

## Success Stories

> "Migrated from Strawberry in 2 weeks. Saw 8x performance improvement immediately. The trinity pattern made multi-tenancy trivial."
> — Senior Backend Engineer, SaaS company

> "PostGraphile → FraiseQL migration took us 3 days. Database functions worked as-is. Now we get Python type hints and 10x faster JSON."
> — Platform Architect, Enterprise B2B

> "Coming from Graphene/Django, the shift to database-first was an adjustment, but the performance gains justified it. CASCADE is a game-changer for frontend teams."
> — Tech Lead, E-commerce platform

---

## Contributing to Migration Guides

Found an issue or want to improve a guide?

1. **Report Issues**: [GitHub Issues](https://github.com/fraiseql/fraiseql/issues)
2. **Suggest Improvements**: Submit PRs with migration tips
3. **Share Your Story**: Help others by documenting your migration experience

---

**Ready to migrate?** Start with your framework-specific guide:

- [From PostGraphile](./from-postgraphile.md)
- [From Graphene](./from-graphene.md)
- [From Strawberry](./from-strawberry.md)
- [Generic Checklist](./migration-checklist.md)

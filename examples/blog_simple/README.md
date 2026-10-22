# FraiseQL Blog Simple - Complete Example Application

🟢 BEGINNER | ⏱️ 45 min | 🎯 Content Management | 🏷️ Trinity Pattern

A complete blog application demonstrating FraiseQL's fundamental patterns and best practices.

**What you'll learn:**

- Trinity Pattern for secure identifier management
- CQRS architecture with PostgreSQL functions
- Complete CRUD operations with enterprise patterns
- Authentication and role-based access control
- Database-first GraphQL API design

**Prerequisites:**

- None (great starting point!)

**Next steps:**

- `../blog_api/` - Add enterprise mutation patterns
- `../ecommerce/` - Complex business logic
- `../enterprise_patterns/` - Advanced enterprise features

## 🌟 Overview

This is a **production-ready blog application** that showcases:

- **Database-first architecture** with PostgreSQL functions
- **Command/Query separation** with views and materialized tables
- **CRUD operations** with comprehensive error handling
- **Real-time database testing** patterns
- **Authentication and authorization** flows

**Perfect for**: New FraiseQL projects, learning core patterns, simple content management systems.

## 🎯 Key Features

This example demonstrates FraiseQL's opinionated approach with **Trinity Pattern**:

- **GraphQL API** exposes only `id` (UUID) and `identifier` (slug) fields
- **Internal operations** use fast `pk_*` INT joins for performance
- **Security** through separate public/internal identifiers
- **See**: [Trinity Pattern Guide](../../docs/core/trinity-pattern.md) for complete explanation
- **Python code** uses UUIDs exclusively for relationships
- **Database layer** uses views with JOINs to expose UUID relationships
- **Mutations** delegate to PostgreSQL functions for business logic

## 🚀 Quick Start

### 1. Setup Database

```bash
# Start PostgreSQL (using Docker)
docker run -d --name blog_simple_db \
  -e POSTGRES_DB=fraiseql_blog_simple \
  -e POSTGRES_USER=fraiseql \
  -e POSTGRES_PASSWORD=fraiseql \
  -p 5432:5432 \
  postgres:16

# Setup database schema
psql postgresql://fraiseql:fraiseql@localhost:5432/fraiseql_blog_simple -f db/setup.sql
```

### 2. Install Dependencies

```bash
pip install fraiseql[fastapi] psycopg[binary]
```

### 3. Run Application

```bash
python app.py
```

Visit http://localhost:8000/graphql for GraphQL Playground.

## 🏗️ Architecture

```
blog_simple/
├── README.md                    # This documentation
├── app.py                       # FastAPI + FraiseQL application
├── models.py                    # Blog domain models with GraphQL types
├── db/
│   ├── setup.sql               # Complete database schema
│   └── seed_data.sql           # Sample blog data
├── tests/
│   ├── conftest.py             # Test fixtures
│   ├── test_queries.py         # Query testing
│   ├── test_mutations.py       # Mutation testing
│   └── test_integration.py     # End-to-end testing
└── docker-compose.yml          # Development environment
```

## 📊 Database Schema

### Core Tables

```sql
-- Users and authentication (Trinity Pattern)
CREATE TABLE tb_user (
    -- Trinity Identifiers
    pk_user INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- Internal (fast INT joins)
    id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,     -- Public API (secure UUID)
    identifier TEXT UNIQUE NOT NULL,                       -- Human-readable (username)

    -- User data
    email TEXT NOT NULL UNIQUE CHECK (email ~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'),
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'author', 'user')),
    profile_data JSONB DEFAULT '{}'::jsonb,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    CONSTRAINT chk_username_length CHECK (length(identifier) >= 3)
);

-- Blog posts (Trinity Pattern)
CREATE TABLE tb_post (
    -- Trinity Identifiers
    pk_post INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- Internal (fast INT joins)
    id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,     -- Public API (secure UUID)
    identifier TEXT UNIQUE NOT NULL,                       -- Human-readable (slug)

    -- Post data
    title TEXT NOT NULL CHECK (length(title) >= 1),
    content TEXT NOT NULL CHECK (length(content) >= 1),
    excerpt TEXT,
    fk_author INT NOT NULL REFERENCES tb_user(pk_user) ON DELETE CASCADE,  -- Fast INT FK!
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
    published_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'::jsonb,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Comments system (Trinity Pattern)
CREATE TABLE tb_comment (
    -- Trinity Identifiers
    pk_comment INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- Internal (fast INT joins)
    id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,        -- Public API (secure UUID)
    identifier TEXT UNIQUE,                                   -- Optional for comments

    -- Comment data
    fk_post INT NOT NULL REFERENCES tb_post(pk_post) ON DELETE CASCADE,       -- Fast INT FK!
    fk_author INT NOT NULL REFERENCES tb_user(pk_user) ON DELETE CASCADE,     -- Fast INT FK!
    fk_parent INT REFERENCES tb_comment(pk_comment) ON DELETE CASCADE,        -- Fast INT FK!
    content TEXT NOT NULL CHECK (length(content) >= 1),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tagging system (Trinity Pattern)
CREATE TABLE tb_tag (
    -- Trinity Identifiers
    pk_tag INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,   -- Internal (fast INT joins)
    id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,     -- Public API (secure UUID)
    identifier TEXT UNIQUE NOT NULL,                       -- Human-readable (slug)

    -- Tag data
    name TEXT NOT NULL UNIQUE CHECK (length(name) >= 1),
    color TEXT DEFAULT '#6366f1' CHECK (color ~ '^#[0-9A-Fa-f]{6}$'),
    description TEXT,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Post-tag relationships (many-to-many using INT FKs)
CREATE TABLE post_tags (
    fk_post INT NOT NULL REFERENCES tb_post(pk_post) ON DELETE CASCADE,
    fk_tag INT NOT NULL REFERENCES tb_tag(pk_tag) ON DELETE CASCADE,
    PRIMARY KEY (fk_post, fk_tag)
);
```

## 🏗️ Trinity Pattern Explained

This example uses FraiseQL's **Trinity Pattern** with three types of identifiers per entity:

### 1. **Internal IDs** (`pk_*`)

- **Purpose**: Fast database joins and internal operations
- **Type**: `INT GENERATED ALWAYS AS IDENTITY`
- **Example**: `pk_user`, `pk_post`, `pk_tag`
- **Benefits**: 10-100x faster JOINs than UUID joins

### 2. **Public IDs** (`id`)

- **Purpose**: External API exposure (secure, non-guessable)
- **Type**: `UUID DEFAULT gen_random_uuid()`
- **Example**: User UUIDs in URLs, API responses
- **Benefits**: Security through obscurity, no enumeration attacks

### 3. **Human IDs** (`identifier`)

- **Purpose**: User-friendly identifiers (usernames, slugs)
- **Type**: `TEXT UNIQUE NOT NULL`
- **Example**: `@john_doe`, `my-blog-post-title`
- **Benefits**: Readable URLs, SEO-friendly, user experience

### Foreign Key Strategy

```sql
-- Fast INT foreign keys (not UUID)
fk_author INT NOT NULL REFERENCES tb_user(pk_user) ON DELETE CASCADE
```

**Why This Matters**:

- **Performance**: INT joins are 10-100x faster than UUID joins
- **Security**: Public UUIDs prevent ID enumeration
- **UX**: Human identifiers are memorable and shareable
- **Flexibility**: All three types available for different use cases

### Learn More

- [Trinity Identifiers Guide](../../docs/archive/database/trinity-identifiers.md)
- [Table Naming Conventions](../../docs/archive/database/table-naming-conventions.md)
- [Migration Guide](../../docs/archive/database/migrations.md)

---

### Query Views

Views expose UUID relationships to the GraphQL API while maintaining fast INT joins internally:

```sql
-- User view
CREATE VIEW v_users AS
SELECT
    id,
    identifier,
    identifier AS username,  -- identifier serves as username
    email,
    role,
    profile_data,
    created_at,
    updated_at
FROM tb_user;

-- Posts view (with UUID author relationship from JOIN)
CREATE VIEW v_posts AS
SELECT
    p.id,
    p.identifier,
    p.identifier AS slug,  -- identifier serves as slug
    p.title,
    p.content,
    p.excerpt,
    p.status,
    p.published_at,
    p.created_at,
    p.updated_at,
    u.id AS author_id  -- ✅ UUID relationship from JOIN
FROM tb_post p
JOIN tb_user u ON p.fk_author = u.pk_user;

-- Comments view (with UUID relationships from JOINs)
CREATE VIEW v_comments AS
SELECT
    c.id,
    c.identifier,
    c.content,
    c.status,
    c.created_at,
    c.updated_at,
    p.id AS post_id,       -- ✅ UUID relationship from JOIN
    u.id AS author_id,     -- ✅ UUID relationship from JOIN
    pc.id AS parent_id     -- ✅ UUID relationship from JOIN
FROM tb_comment c
JOIN tb_post p ON c.fk_post = p.pk_post
JOIN tb_user u ON c.fk_author = u.pk_user
LEFT JOIN tb_comment pc ON c.fk_parent = pc.pk_comment;

-- Tags view
CREATE VIEW v_tags AS
SELECT
    id,
    identifier,
    name,
    identifier AS slug,  -- identifier serves as slug
    color,
    description,
    created_at
FROM tb_tag;
```

## 📝 GraphQL Schema

### Types

```python
@fraiseql.type(sql_source="v_users")
class User:
    id: str
    username: str
    email: str
    role: str
    created_at: datetime
    profile_data: dict

    @fraiseql.field
    async def posts(self, info: GraphQLResolveInfo) -> list[Post]:
        db = info.context["db"]
        return await db.find("v_posts", author_id=self.id)

@fraiseql.type(sql_source="v_posts")
class Post:
    id: str
    title: str
    slug: str
    content: str
    excerpt: str
    status: str
    published_at: datetime | None
    created_at: datetime
    author: User
    tags: list[Tag]
    comment_count: int

@fraiseql.type(sql_source="v_comments")
class Comment:
    id: str
    content: str
    created_at: datetime
    author: User
    parent_id: str | None

@fraiseql.type(sql_source="v_tags")
class Tag:
    id: str
    name: str
    slug: str
    color: str
    description: str | None
```

### Queries

```python
@fraiseql.query
async def posts(
    info: GraphQLResolveInfo,
    where: PostWhereInput | None = None,
    order_by: list[PostOrderByInput] | None = None,
    limit: int = 20,
    offset: int = 0
) -> list[Post]:
    """Query posts with filtering and pagination."""
    db = info.context["db"]
    return await db.find("v_posts", where=where, order_by=order_by, limit=limit, offset=offset)

@fraiseql.query
async def post(info: GraphQLResolveInfo, id: str | None = None, slug: str | None = None) -> Post | None:
    """Get single post by ID or slug."""
    db = info.context["db"]
    if id:
        return await db.find_one("v_posts", id=id)
    elif slug:
        return await db.find_one("v_posts", slug=slug)
    return None
```

### Mutations

```python
@fraiseql.input
class CreatePostInput:
    title: str
    content: str
    excerpt: str | None = None
    tag_ids: list[str] | None = None

@fraiseql.success
class CreatePostSuccess:
    post: Post
    message: str = "Post created successfully"

@fraiseql.error
class CreatePostError:
    message: str
    code: str

# fraiseql calls the SQL function create_post with the input as one jsonb, and
# turns the mutation_response it returns into CreatePostSuccess or CreatePostError
@fraiseql.mutation
class CreatePost:
    input: CreatePostInput
    success: CreatePostSuccess
    error: CreatePostError
```

## 🧪 Testing

### Test Structure

```python
# tests/conftest.py
import pytest
import psycopg
from fraiseql.cqrs import CQRSRepository

@pytest.fixture
async def db():
    """Database connection for testing."""
    conn = await psycopg.AsyncConnection.connect("postgresql://fraiseql:fraiseql@localhost/fraiseql_blog_simple_test")
    yield CQRSRepository(conn)
    await conn.close()

@pytest.fixture
async def sample_user(db):
    """Create sample user for testing."""
    user_data = {
        "username": "testuser",
        "email": "test@example.com",
        "password_hash": "hash",
        "role": "user"
    }
    user_id = await db.insert("users", user_data, returning="id")
    return await db.find_one("users", id=user_id)

# tests/test_queries.py
async def test_query_posts(db, sample_user):
    """Test basic post querying."""
    # Create sample post
    post_data = {
        "title": "Test Post",
        "content": "Test content",
        "author_id": sample_user["id"]
    }
    await db.insert("posts", post_data)

    # Query posts
    posts = await db.find("v_posts", limit=10)
    assert len(posts) == 1
    assert posts[0]["title"] == "Test Post"

# tests/test_mutations.py
async def test_create_post_mutation(graphql_client, sample_user):
    """Test post creation via GraphQL."""
    mutation = """
        mutation CreatePost($input: CreatePostInput!) {
            createPost(input: $input) {
                __typename
                ... on CreatePostSuccess {
                    post {
                        id
                        title
                        slug
                    }
                }
                ... on CreatePostError {
                    message
                }
            }
        }
    """

    result = await graphql_client.execute(
        mutation,
        variables={"input": {"title": "New Post", "content": "Content here"}}
    )

    assert result["data"]["createPost"]["__typename"] == "CreatePostSuccess"
```

### Running Tests

```bash
# Setup test database
createdb fraiseql_blog_simple_test
psql fraiseql_blog_simple_test -f db/setup.sql

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html
```

## 🔧 Configuration

### Environment Variables

```bash
# Database
DB_NAME=fraiseql_blog_simple
DB_USER=fraiseql
DB_PASSWORD=fraiseql
DB_HOST=localhost
DB_PORT=5432

# Application
ENV=development
LOG_LEVEL=info
```

### Docker Development

```yaml
# docker-compose.yml
version: '3.8'
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: fraiseql_blog_simple
      POSTGRES_USER: fraiseql
      POSTGRES_PASSWORD: fraiseql
    ports:
      - "5432:5432"
    volumes:
      - ./db:/docker-entrypoint-initdb.d

  app:
    build: .
    ports:
      - "8000:8000"
    depends_on:
      - db
    environment:
      DB_HOST: db
      DB_NAME: fraiseql_blog_simple
      DB_USER: fraiseql
      DB_PASSWORD: fraiseql
```

## 📚 Key Learning Points

This example demonstrates:

1. **FraiseQL Fundamentals**
   - Type definitions with SQL sources
   - Query and mutation resolvers
   - Database integration patterns
   - Error handling strategies

2. **Database Design**
   - PostgreSQL schema with relationships
   - Query-optimized views
   - JSONB for flexible data
   - Proper indexing strategies

3. **Testing Patterns**
   - Fixture-based database testing
   - GraphQL integration tests
   - Isolated test environments
   - Mock data strategies

4. **Production Readiness**
   - Environment configuration
   - Error handling and logging
   - Security considerations
   - Performance optimization

## 🚀 Next Steps

After mastering this simple example:

1. Explore **blog_enterprise** for advanced patterns
2. Study **authentication** and **authorization**
3. Learn **performance optimization** techniques
4. Implement **real-time subscriptions**
5. Add **caching** and **monitoring**

---

**This simple blog demonstrates FraiseQL's power for building clean, testable GraphQL APIs with PostgreSQL.**

## Support

- **Issues**: [GitHub Issues](../../issues)
- **Discussions**: [GitHub Discussions](../../discussions)
- **Discord**: [FraiseQL Community](https://discord.gg/fraiseql)
- **Documentation**: [FraiseQL Docs](../../docs)

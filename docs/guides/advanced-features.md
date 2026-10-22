# Advanced Features Guide

This guide covers FraiseQL's advanced features for building high-performance, real-time GraphQL APIs.

## Dataloader Fields

### The N+1 Problem

When fetching related data, naive implementations cause N+1 queries:

```python
# ❌ N+1 Problem
@fraiseql.field
async def author(self, info) -> User:
    db = info.context["db"]
    # This runs for EVERY post! (1 + N queries)
    return await db.find_one("v_user", mandatory_filters={"id": self.author_id})
```

**Query**:

```graphql
{
  posts {  # 1 query
    title
    author {  # N queries (one per post)!
      name
    }
  }
}
```

**Result**: 1 + 100 = 101 queries for 100 posts 😱

### Solution: @dataloader_field

The `@dataloader_field` decorator batches and caches database queries:

```python
from fraiseql import dataloader_field
from aiodataloader import DataLoader
from fraiseql.types import ID

# Step 1: Create DataLoader
class UserDataLoader(DataLoader):
    async def batch_load_fn(self, user_ids: list[UUID]) -> list[User]:
        """Load multiple users in a single query."""
        db = self.context["db"]
        users = await db.find("v_user", where={"id": {"in": user_ids}})

        # Return users in same order as user_ids
        user_map = {user.id: user for user in users}
        return [user_map.get(uid) for uid in user_ids]

# Step 2: Register DataLoader in context
app = create_fraiseql_app(
    database_url="...",
    context_factories={
        "UserDataLoader": lambda ctx: UserDataLoader(context=ctx)
    }
)

# Step 3: Use @dataloader_field
@fraiseql.type(sql_source="v_post")
class Post:
    id: ID
    title: str
    author_id: ID

    @dataloader_field(UserDataLoader, key_field="author_id")
    async def author(self) -> User:
        """Batches all author lookups into a single query!"""
        pass  # Decorator handles the loading
```

### How It Works

1. **Batching**: Collects all `author_id` values from posts
2. **Single Query**: Loads all users in one database call
3. **Caching**: Reuses loaded users within the same request

**Result**: 1 + 1 = 2 queries total (100x faster!) 🚀

### Complete Example

```python
import fraiseql
from fraiseql.types import ID
from aiodataloader import DataLoader

# DataLoader for users
class UserDataLoader(DataLoader):
    async def batch_load_fn(self, user_ids: list[UUID]) -> list[User]:
        db = self.context["db"]
        users = await db.find("v_user", where={"id": {"in": user_ids}})
        user_map = {user.id: user for user in users}
        return [user_map.get(uid) for uid in user_ids]

# DataLoader for comments (batch load comments by post_id)
class CommentDataLoader(DataLoader):
    async def batch_load_fn(self, post_ids: list[UUID]) -> list[list[Comment]]:
        db = self.context["db"]
        comments = await db.find("v_comment", where={"post_id": {"in": post_ids}})

        # Group comments by post_id
        comments_by_post = {pid: [] for pid in post_ids}
        for comment in comments:
            comments_by_post[comment.post_id].append(comment)

        return [comments_by_post[pid] for pid in post_ids]

# Types
@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    name: str
    email: str

@fraiseql.type(sql_source="v_comment")
class Comment:
    id: ID
    post_id: ID
    author_id: ID
    content: str

    @dataloader_field(UserDataLoader, key_field="author_id")
    async def author(self) -> User:
        pass

@fraiseql.type(sql_source="v_post")
class Post:
    id: ID
    title: str
    author_id: ID

    @dataloader_field(UserDataLoader, key_field="author_id")
    async def author(self) -> User:
        pass

    @dataloader_field(CommentDataLoader, key_field="id")
    async def comments(self) -> list[Comment]:
        pass

# App
app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User, Post, Comment],
    context_factories={
        "UserDataLoader": lambda ctx: UserDataLoader(context=ctx),
        "CommentDataLoader": lambda ctx: CommentDataLoader(context=ctx),
    }
)
```

**Query**:

```graphql
{
  posts {
    title
    author { name }        # Batched!
    comments {             # Batched!
      content
      author { name }      # Batched!
    }
  }
}
```

**Result**: Only 4 queries total (posts, users, comments, comment authors) regardless of data size!

---

## Subscriptions

### Real-Time Updates with GraphQL Subscriptions

Subscriptions enable real-time data streaming from server to client.

### Basic Subscription

```python
import fraiseql
from fraiseql import subscription

@subscription
async def post_created(info) -> Post:
    """Subscribe to new posts."""
    # Yield new posts as they're created
    async for post in info.context["post_stream"]:
        yield post
```

**GraphQL**:

```graphql
subscription {
  postCreated {
    id
    title
    author { name }
  }
}
```

### Subscription with Filters

```python
from fraiseql.types import ID

@subscription
async def post_created(info, author_id: ID | None = None) -> Post:
    """Subscribe to new posts, optionally filtered by author."""
    async for post in info.context["post_stream"]:
        # Filter by author if specified
        if author_id is None or post.author_id == author_id:
            yield post
```

**GraphQL**:

```graphql
subscription {
  postCreated(authorId: "550e8400-e29b-41d4-a716-446655440000") {
    id
    title
  }
}
```

### PostgreSQL LISTEN/NOTIFY Pattern

Use PostgreSQL's LISTEN/NOTIFY for efficient real-time updates:

```python
import asyncio
import asyncpg
from fraiseql import subscription

async def pg_listen_stream(connection, channel: str):
    """Listen to PostgreSQL notifications."""
    await connection.add_listener(channel, lambda c, pid, chan, payload: payload)

    while True:
        # Wait for notification
        await asyncio.sleep(0.1)  # Or use asyncio.Event for better performance

@subscription
async def post_created(info) -> Post:
    """Subscribe to new posts via PostgreSQL NOTIFY."""
    conn = info.context["db_connection"]
    db = info.context["db"]

    # Listen to 'post_created' channel
    async with conn.transaction():
        await conn.execute("LISTEN post_created")

        while True:
            # Wait for notification
            notification = await conn.wait_for_notification()
            post_id = notification.payload

            # Fetch the new post
            post = await db.find_one("v_post", mandatory_filters={"id": post_id})
            yield post
```

**PostgreSQL Trigger**:

```sql
-- Trigger to NOTIFY when post created
CREATE OR REPLACE FUNCTION notify_post_created()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('post_created', NEW.id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER post_created_trigger
AFTER INSERT ON tb_post
FOR EACH ROW
EXECUTE FUNCTION notify_post_created();
```

### Complete Subscription Example

```python
import fraiseql
from fraiseql.types import ID
import asyncpg

# Context setup
async def create_context(request):
    """Create context with database connection."""
    conn = await asyncpg.connect("postgresql://localhost/mydb")
    return {
        "db": FraiseQLRepository(conn),
        "db_connection": conn,
    }

# Subscription
@fraiseql.subscription
async def post_created(info, author_id: ID | None = None) -> Post:
    """Real-time post creation updates."""
    conn = info.context["db_connection"]
    db = info.context["db"]

    await conn.execute("LISTEN post_created")

    try:
        while True:
            notification = await conn.wait_for_notification(timeout=30)
            if notification is None:
                # Heartbeat to keep connection alive
                continue

            post_id = UUID(notification.payload)
            post = await db.find_one("v_post", mandatory_filters={"id": post_id})

            # Filter by author if specified
            if author_id is None or post.author_id == author_id:
                yield post
    finally:
        await conn.execute("UNLISTEN post_created")

# App
app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    subscriptions=[post_created],
    context_factory=create_context,
    enable_subscriptions=True,  # Enable WebSocket support
)
```

---

## GraphQL Cascade

### Automatic Cache Invalidation and Side Effects

GraphQL Cascade sends a mutation's side effects to the client with its result, so the
client can update or invalidate its cache without refetching.

### How It Works

1. **The SQL function returns the side effects**: the entities it created, updated or
   deleted, and the queries to invalidate, in the `cascade` field of its result
2. **FraiseQL passes them on**: with `@mutation(enable_cascade=True)`, the success type
   gets a `cascade` field
3. **The client applies them**: Apollo or Relay update or invalidate the cached queries

### Example

```python
import fraiseql
from fraiseql.types import ID


@fraiseql.type
class Post:
    id: ID
    title: str
    content: str


@fraiseql.input
class CreatePostInput:
    title: str
    content: str
    author_id: ID


@fraiseql.success
class CreatePostSuccess:
    message: str
    post: Post


@fraiseql.error
class CreatePostError:
    message: str
    code: str


@fraiseql.mutation(enable_cascade=True)
class CreatePost:
    input: CreatePostInput
    success: CreatePostSuccess
    error: CreatePostError
```

The SQL function `create_post(input jsonb)` declares the effects with the cascade helpers:

```sql
RETURN mutation_created(
    'Post created',
    v_post_data,
    'Post',
    cascade_merge(
        cascade_entity_created('Post', v_post_id, v_post_data),
        cascade_invalidate_cache(ARRAY['posts', 'user_posts'], 'INVALIDATE')
    )
);
```

**Result**: the response's `cascade` lists the new `Post` and tells the client to
invalidate its `posts` and `user_posts` queries.

See [GraphQL Cascade](../features/graphql-cascade.md) for the full function, the cascade
structure and client integration.

---

## Vector Search

### Semantic Search with pgvector

FraiseQL integrates with PostgreSQL's pgvector extension for semantic search and RAG (Retrieval-Augmented Generation).

### Setup

```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Add vector column to table
ALTER TABLE tb_post
ADD COLUMN embedding vector(1536);  -- OpenAI embedding size

-- Create index for fast similarity search
CREATE INDEX ON tb_post USING ivfflat (embedding vector_cosine_ops);
```

### Query with Vector Similarity

```python
@fraiseql.query
async def search_posts(
    info,
    query: str,
    limit: int = 10
) -> list[Post]:
    """Semantic search for posts."""
    db = info.context["db"]

    # Get query embedding (e.g., from OpenAI)
    query_embedding = await get_embedding(query)

    # Vector similarity search: nearest by cosine distance
    from fraiseql.sql.order_by_generator import OrderBy, OrderBySet

    return await db.find(
        "v_post",
        order_by=OrderBySet([OrderBy("embedding.cosine_distance", value=query_embedding)]),
        limit=limit,
    )
```

### Distance Operators

| Operator | Description | Use Case |
|----------|-------------|----------|
| `<->` | L2 distance | General similarity |
| `<#>` | Inner product | Normalized vectors |
| `<=>` | Cosine distance | Text embeddings (OpenAI) |

### Complete RAG Example

```python
import fraiseql
from openai import AsyncOpenAI

openai_client = AsyncOpenAI()

async def get_embedding(text: str) -> list[float]:
    """Get OpenAI embedding for text."""
    response = await openai_client.embeddings.create(
        model="text-embedding-ada-002",
        input=text
    )
    return response.data[0].embedding

@fraiseql.query
async def semantic_search(
    info,
    query: str,
    limit: int = 5
) -> list[Post]:
    """Semantic search with vector similarity."""
    db = info.context["db"]

    # Get query embedding
    embedding = await get_embedding(query)

    # Find similar posts
    posts = await db.execute_raw(
        """
        SELECT id, title, content,
               embedding <=> $1::vector AS similarity
        FROM v_post
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> $1::vector
        LIMIT $2
        """,
        embedding,
        limit
    )

    return posts
```

---

## Advanced Filtering

### Full-Text Search

```python
@fraiseql.query
async def search_posts(
    info,
    search: str,
    limit: int = 100
) -> list[Post]:
    """Full-text search in posts."""
    db = info.context["db"]

    return await db.find(
        "v_post",
        where={
            "tsv": {"@@": {"to_tsquery": search}}
        },
        order_by=[("ts_rank(tsv, to_tsquery($1))", "DESC")],
        limit=limit
    )
```

**PostgreSQL Setup**:

```sql
-- Add tsvector column
ALTER TABLE tb_post
ADD COLUMN tsv tsvector;

-- Update tsvector on insert/update
CREATE TRIGGER post_tsv_update
BEFORE INSERT OR UPDATE ON tb_post
FOR EACH ROW
EXECUTE FUNCTION
    tsvector_update_trigger(tsv, 'pg_catalog.english', title, content);

-- Index for fast full-text search
CREATE INDEX ON tb_post USING gin(tsv);
```

### JSONB Queries

```python
@fraiseql.query
async def users_with_preferences(
    info,
    theme: str
) -> list[User]:
    """Find users with specific theme preference."""
    db = info.context["db"]

    return await db.find(
        "v_user",
        where={
            "preferences": {"->": "theme", "=": theme}
        }
    )
```

### Array Operations

```python
@fraiseql.query
async def posts_with_tags(
    info,
    tags: list[str]
) -> list[Post]:
    """Find posts containing any of the given tags."""
    db = info.context["db"]

    return await db.find(
        "v_post",
        where={
            "tags": {"&&": tags}  # Overlap operator
        }
    )
```

### Regex Matching

```python
@fraiseql.query
async def users_by_email_pattern(
    info,
    pattern: str
) -> list[User]:
    """Find users matching email regex."""
    db = info.context["db"]

    return await db.find(
        "v_user",
        where={
            "email": {"~": pattern}  # Regex match
        }
    )
```

---

## Performance Best Practices

### 1. Use Dataloader for Related Data

✅ **DO:**

```python
@dataloader_field(UserDataLoader, key_field="author_id")
async def author(self) -> User:
    pass  # Batched and cached
```

❌ **DON'T:**

```python
@fraiseql.field
async def author(self, info) -> User:
    db = info.context["db"]
    return await db.find_one("v_user", mandatory_filters={"id": self.author_id})  # N+1 queries!
```

### 2. Index Vector Columns

```sql
-- IVFFlat index (faster queries, good for most cases)
CREATE INDEX ON tb_post USING ivfflat (embedding vector_cosine_ops);

-- HNSW index (best quality, slower inserts)
CREATE INDEX ON tb_post USING hnsw (embedding vector_cosine_ops);
```

### 3. Use Subscriptions for Real-Time, Polling for Updates

- **Subscriptions**: Real-time critical updates (chat, notifications)
- **Polling**: Periodic updates (dashboards, feeds)

### 4. Batch Cascade Invalidations

```sql
-- All invalidated in a single operation
cascade_invalidate_cache(ARRAY['posts', 'users', 'comments'], 'INVALIDATE')
```

---

## See Also

- [Decorators Reference](../reference/decorators.md) - Complete decorator documentation
- [Database API](../reference/database.md) - Advanced query patterns
- [Performance Guide](performance-guide.md) - Optimization tips

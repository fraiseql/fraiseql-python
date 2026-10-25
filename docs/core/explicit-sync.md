# Explicit Sync Pattern

> **Full visibility and control: Why FraiseQL uses explicit sync instead of database triggers**

FraiseQL's explicit sync pattern is a fundamental design decision that prioritizes **visibility, testability, and control** over automatic behavior. Instead of hidden database triggers, you explicitly call sync functions in your code—giving you complete control over when and how data synchronizes from the command side (tb_*) to the query side (tv_*).

---

## Philosophy: Explicit > Implicit

### The Problem with Triggers

Traditional **[CQRS](concepts-glossary.md#cqrs-command-query-responsibility-segregation)** implementations use database triggers to automatically sync data:

```sql
-- ❌ Hidden trigger (automatic, but invisible)
CREATE TRIGGER sync_post_to_view
AFTER INSERT OR UPDATE ON tb_post
FOR EACH ROW
EXECUTE FUNCTION sync_post_to_tv();
```

**Problems with triggers**:

| Issue | Impact |
|-------|--------|
| **Hidden** | Hard to debug (where does sync happen?) |
| **Untestable** | Can't mock in tests (requires real database) |
| **No control** | Always runs (can't skip, batch, or defer) |
| **Slow** | Runs for every row (no batch optimization) |
| **No metrics** | Can't track performance |
| **Hard to deploy** | Trigger code separate from application |

### FraiseQL's Solution: Explicit Sync

```python
from fraiseql.types import ID

# ✅ Explicit sync (visible in your code)
async def create_post(info, title: str, author_id: ID) -> Post:
    pool = info.context["db_pool"]  # an asyncpg pool, as in EntitySync below
    sync = info.context["sync"]

    # 1. Write to command side
    post_id = await pool.fetchval(
        "INSERT INTO tb_post (title, author_id) VALUES ($1, $2) RETURNING id",
        title, author_id
    )

    # 2. EXPLICIT SYNC 👈 THIS IS IN YOUR CODE!
    await sync.sync_post([post_id], mode='incremental')

    # 3. Read from query side
    db = info.context["db"]
    return await db.find_one("tv_post", "createPost", info, mandatory_filters={"id": post_id})
```

**Benefits of explicit sync**:

| Benefit | Impact |
|---------|--------|
| **Visible** | Sync is in your code (easy to find) |
| **Testable** | Mock sync in tests (fast unit tests) |
| **Controllable** | Skip, batch, or defer syncs as needed |
| **Fast** | Batch operations (10-100x faster) |
| **Observable** | Track performance metrics |
| **Deployable** | Sync code with your application |

---

## How Explicit Sync Works

### The CQRS Sync Flow

```
┌────────────────────────────────────────────────────────────┐
│ Explicit Sync Flow                                         │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  1. WRITE: Command Side (tb_*)                            │
│     INSERT INTO tb_post (title, author_id, content)       │
│     VALUES ('My Post', '123', '...')                       │
│     RETURNING id;                                          │
│          ↓                                                 │
│  2. SYNC: Your Code (EXPLICIT!)                           │
│     await sync.sync_post([post_id])                        │
│     ↓                                                      │
│     a) Fetch from tb_post + joins (denormalize)           │
│     b) Build JSONB structure                               │
│     c) Upsert to tv_post                                   │
│     d) Log metrics                                         │
│          ↓                                                 │
│  3. READ: Query Side (tv_*)                               │
│     SELECT data FROM tv_post WHERE id = $1;                │
│     → Returns denormalized JSONB (fast!)                   │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### Key Components

1. **Command Tables (tb_*)**: Normalized, write-optimized
2. **Query Tables (tv_*)**: Denormalized JSONB, read-optimized
3. **Sync Functions**: Your code that bridges tb_* → tv_*
4. **Sync Logging**: Metrics for monitoring performance

---

## Implementing Sync Functions

### Basic Sync Function

```python
from fraiseql.types import ID
import asyncpg


class EntitySync:
    """Handles synchronization from tb_* to tv_* tables."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def sync_post(self, post_ids: list[UUID], mode: str = "incremental") -> None:
        """
        Sync posts from tb_post to tv_post.

        Args:
            post_ids: List of post IDs to sync
            mode: 'incremental' (default) or 'full'

        Example:
            await sync.sync_post([post_id], mode='incremental')
        """
        async with self.pool.acquire() as conn:
            for post_id in post_ids:
                # 1. Fetch from command side (tb_post) with joins
                post_data = await conn.fetchrow(
                    """
                    SELECT
                        p.id,
                        p.title,
                        p.content,
                        p.published,
                        p.created_at,
                        jsonb_build_object(
                            'id', u.id,
                            'username', u.username,
                            'full_name', u.full_name
                        ) as author
                    FROM tb_post p
                    JOIN tb_user u ON u.id = p.author_id
                    WHERE p.id = $1
                    """,
                    post_id,
                )

                if not post_data:
                    continue

                # 2. Build denormalized JSONB structure
                jsonb_data = {
                    "id": str(post_data["id"]),
                    "title": post_data["title"],
                    "content": post_data["content"],
                    "published": post_data["published"],
                    "author": post_data["author"],
                    "created_at": post_data["created_at"].isoformat(),
                }

                # 3. Upsert to query side (tv_post)
                await conn.execute(
                    """
                    INSERT INTO tv_post (id, data, updated_at)
                    VALUES ($1, $2, NOW())
                    ON CONFLICT (id) DO UPDATE
                    SET data = $2, updated_at = NOW()
                    """,
                    post_id,
                    jsonb_data,
                )

                # 4. Log metrics (optional but recommended)
                await self._log_sync("post", post_id, mode, duration_ms=5, success=True)
```

### Sync with Nested Data

```python
from fraiseql.types import ID

async def sync_post_with_comments(self, post_ids: list[UUID]) -> None:
    """Sync posts with embedded comments (denormalized)."""
    async with self.pool.acquire() as conn:
        for post_id in post_ids:
            # Fetch post
            post_data = await conn.fetchrow("SELECT * FROM tb_post WHERE id = $1", post_id)

            # Fetch comments for this post
            comments = await conn.fetch(
                """
                SELECT
                    c.id,
                    c.content,
                    c.created_at,
                    jsonb_build_object(
                        'id', u.id,
                        'username', u.username
                    ) as author
                FROM tb_comment c
                JOIN tb_user u ON u.id = c.author_id
                WHERE c.post_id = $1
                ORDER BY c.created_at DESC
                """,
                post_id,
            )

            # Build denormalized structure with embedded comments
            jsonb_data = {
                "id": str(post_data["id"]),
                "title": post_data["title"],
                "author": {...},
                "comments": [
                    {
                        "id": str(c["id"]),
                        "content": c["content"],
                        "author": c["author"],
                        "created_at": c["created_at"].isoformat(),
                    }
                    for c in comments
                ],
            }

            # Upsert to tv_post
            await conn.execute(
                "INSERT INTO tv_post (id, data) VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET data = $2",
                post_id,
                jsonb_data,
            )
```

---

## Usage Patterns

### Pattern 1: Sync After Create

```python
import fraiseql
from fraiseql.types import ID


@fraiseql.mutation
async def create_post(info, title: str, content: str, author_id: ID) -> Post:
    """Create a post and sync immediately."""
    pool = info.context["db_pool"]
    sync = info.context["sync"]

    # 1. Write to command side
    post_id = await pool.fetchval(
        "INSERT INTO tb_post (title, content, author_id) VALUES ($1, $2, $3) RETURNING id",
        title, content, author_id
    )

    # 2. EXPLICIT SYNC
    await sync.sync_post([post_id])

    # 3. Also sync author (post count changed)
    await sync.sync_user([author_id])

    # 4. Read from query side (in a mutation, name the response field)
    db = info.context["db"]
    return await db.find_one("tv_post", "createPost", info, mandatory_filters={"id": post_id})
```

### Pattern 2: Batch Sync

```python
from fraiseql.types import ID

async def create_many_posts(posts: list[dict]) -> list[UUID]:
    """Create multiple posts and batch sync."""
    post_ids = []

    # 1. Create all posts (command side)
    for post_data in posts:
        post_id = await pool.fetchval(
            "INSERT INTO tb_post (...) VALUES (...) RETURNING id",
            post_data["title"], post_data["content"], post_data["author_id"]
        )
        post_ids.append(post_id)

    # 2. BATCH SYNC (much faster than individual syncs!)
    await sync.sync_post(post_ids, mode='incremental')

    return post_ids
```

**Performance**:

- Individual syncs: 5ms × 100 posts = **500ms**
- Batch sync: **50ms** (10x faster!)

### Pattern 3: Deferred Sync

```python
from fraiseql.types import ID

async def update_post(post_id: ID, data: dict, background_tasks: BackgroundTasks):
    """Update post and defer sync to background."""
    # 1. Write to command side
    await pool.execute("UPDATE tb_post SET ... WHERE id = $1", post_id)

    # 2. DEFERRED SYNC (non-blocking)
    background_tasks.add_task(sync.sync_post, [post_id])

    # 3. Return immediately (sync happens in background)
    return {"status": "updated", "id": str(post_id)}
```

**Use cases**:

- Non-critical updates (e.g., view count)
- Bulk operations
- Reducing mutation latency

### Pattern 4: Conditional Sync

```python
from fraiseql.types import ID

async def update_post(post_id: ID, old_data: dict, new_data: dict):
    """Only sync if data changed in a way that affects queries."""
    # Update command side
    await pool.execute("UPDATE tb_post SET ... WHERE id = $1", post_id)

    # Only sync if title or content changed (not view count)
    if new_data["title"] != old_data["title"] or new_data["content"] != old_data["content"]:
        await sync.sync_post([post_id])
    # else: Skip sync (view count doesn't appear in queries)
```

### Pattern 5: Cascade Sync

```python
from fraiseql.types import ID

async def delete_user(user_id: ID):
    """Delete user and cascade sync related entities."""
    # 1. Get user's posts before deleting
    post_ids = await pool.fetch("SELECT id FROM tb_post WHERE author_id = $1", user_id)

    # 2. Delete from command side (CASCADE will delete posts too)
    await pool.execute("DELETE FROM tb_user WHERE id = $1", user_id)

    # 3. EXPLICIT CASCADE SYNC
    await sync.delete_user([user_id])
    await sync.delete_post([p["id"] for p in post_ids])

    # Query side is now consistent
```

---

## Performance Optimization

### 1. Batch Operations

```python
# ❌ Slow: Individual syncs
for post_id in post_ids:
    await sync.sync_post([post_id])  # N database queries

# ✅ Fast: Batch sync
await sync.sync_post(post_ids)  # 1 database query
```

### 2. Parallel Syncs

```python
import asyncio

# ✅ Sync multiple entity types in parallel
await asyncio.gather(
    sync.sync_post(post_ids),
    sync.sync_user(user_ids),
    sync.sync_comment(comment_ids)
)

# All syncs happen concurrently!
```

### 3. Smart Denormalization

```python
# ✅ Only denormalize what GraphQL queries need
jsonb_data = {
    "id": str(post["id"]),
    "title": post["title"],  # Queried often
    "author": {
        "username": author["username"]  # Queried often
    }
    # Don't include: post["content"] if GraphQL doesn't query it in lists
}
```

### 4. Incremental vs Full Sync

```python
# Incremental: Sync specific entities (fast)
await sync.sync_post([post_id], mode='incremental')  # ~5ms

# Full: Sync all entities (slow, but thorough)
await sync.sync_all_posts(mode='full')  # ~500ms for 1000 posts

# Use incremental for:
# - After mutations
# - Real-time updates

# Use full for:
# - Initial setup
# - Recovery from errors
# - Scheduled maintenance
```

---

## Testing and Debugging

### Unit Testing with Mocks

```python
from unittest.mock import AsyncMock
import pytest


@pytest.mark.asyncio
async def test_create_post():
    """Test post creation without syncing."""
    # Mock the sync function
    sync = AsyncMock()

    # Create post
    post_id = await create_post(
        title="Test Post",
        content="...",
        author_id=UUID("..."),
        sync=sync
    )

    # Verify sync was called
    sync.sync_post.assert_called_once_with([post_id], mode='incremental')
```

**Benefits**:

- Fast tests (no database syncs)
- Verify sync is called correctly
- Test business logic independently

### Integration Testing

```python
@pytest.mark.asyncio
async def test_sync_integration(db_pool):
    """Test actual sync operation."""
    sync = EntitySync(db_pool)

    # Create in command side
    post_id = await db_pool.fetchval(
        "INSERT INTO tb_post (...) VALUES (...) RETURNING id",
        "Test", "...", author_id
    )

    # Sync to query side
    await sync.sync_post([post_id])

    # Verify query side has data
    row = await db_pool.fetchrow("SELECT data FROM tv_post WHERE id = $1", post_id)
    assert row is not None
    assert row["data"]["title"] == "Test"
```

### Debugging Sync Issues

The sync functions on this page are your own code: FraiseQL logs nothing for them.
Log in them with a logger of your own:

```python
import logging
import time

logger = logging.getLogger("myapp.sync")


async def sync_posts_logged(sync: EntitySync, post_ids: list[UUID]) -> None:
    start = time.perf_counter()
    logger.debug("syncing posts %s", post_ids)
    await sync.sync_post(post_ids)
    logger.debug("synced %d posts in %.1fms", len(post_ids), (time.perf_counter() - start) * 1000)
```

---

## IVM Integration

### Incremental View Maintenance (IVM)

FraiseQL's explicit sync can leverage PostgreSQL's IVM extension for even faster updates:

```sql
-- Create materialized view (instead of regular tv_* table)
CREATE MATERIALIZED VIEW tv_post AS
SELECT
    p.id,
    jsonb_build_object(
        'id', p.id,
        'title', p.title,
        'author', jsonb_build_object('username', u.username)
    ) as data
FROM tb_post p
JOIN tb_user u ON u.id = p.author_id;

-- Enable IVM
CREATE INCREMENTAL MATERIALIZED VIEW tv_post;
```

**With IVM**, sync becomes simpler:

```python
from fraiseql.types import ID

async def sync_post_with_ivm(self, post_ids: list[UUID]):
    """Sync with IVM extension (faster!)."""
    # IVM automatically maintains tv_post when tb_post changes
    # Just trigger a refresh
    await self.pool.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY tv_post")
```

**Performance**:

- Manual sync: ~5-10ms per entity
- IVM sync: ~1-2ms per entity (2-5x faster!)

### Setting up IVM

```python
from fraiseql.ivm import setup_auto_ivm

@app.on_event("startup")
async def setup_ivm():
    """Setup IVM for all tb_/tv_ pairs."""
    recommendation = await setup_auto_ivm(db_pool, verbose=True)

    # Apply recommended IVM SQL
    async with db_pool.acquire() as conn:
        await conn.execute(recommendation.setup_sql)

    logger.info("IVM configured for fast sync")
```

---

## Common Patterns

### Pattern: Multi-Entity Sync

```python
from fraiseql.types import ID

async def create_comment(post_id: ID, author_id: ID, content: str):
    """Create comment and sync all affected entities."""
    # 1. Write to command side
    comment_id = await pool.fetchval(
        "INSERT INTO tb_comment (...) VALUES (...) RETURNING id",
        post_id, author_id, content
    )

    # 2. SYNC ALL AFFECTED ENTITIES
    await asyncio.gather(
        sync.sync_comment([comment_id]),  # New comment
        sync.sync_post([post_id]),  # Post comment count changed
        sync.sync_user([author_id])  # User comment count changed
    )

    # All entities now consistent!
```

### Pattern: Optimistic Sync

```python
from fraiseql.types import ID

async def like_post(post_id: ID, user_id: ID):
    """Optimistic sync: update cache immediately, sync later."""
    # 1. Update cache optimistically (fast!)
    cached_post = await cache.get(f"post:{post_id}")
    cached_post["likes"] += 1
    await cache.set(f"post:{post_id}", cached_post)

    # 2. Write to command side
    await pool.execute(
        "INSERT INTO tb_post_like (post_id, user_id) VALUES ($1, $2)",
        post_id, user_id
    )

    # 3. Sync in background (eventual consistency)
    background_tasks.add_task(sync.sync_post, [post_id])

    # User sees immediate update!
```

### Pattern: Sync Validation

```python
from fraiseql.types import ID

async def sync_with_validation(self, post_ids: list[UUID]):
    """Sync with validation to ensure data integrity."""
    for post_id in post_ids:
        # Fetch from tb_post
        post_data = await conn.fetchrow("SELECT * FROM tb_post WHERE id = $1", post_id)

        if not post_data:
            logger.warning(f"Post {post_id} not found in tb_post, skipping sync")
            continue

        # Validate author exists
        author = await conn.fetchrow("SELECT * FROM tb_user WHERE id = $1", post_data["author_id"])
        if not author:
            logger.error(f"Author {post_data['author_id']} not found for post {post_id}")
            continue

        # Proceed with sync
        await self._do_sync(post_id, post_data, author)
```

---

## Migration from Triggers

### Replacing Triggers with Explicit Sync

**Before (triggers)**:

```sql
CREATE TRIGGER sync_post_trigger
AFTER INSERT OR UPDATE ON tb_post
FOR EACH ROW
EXECUTE FUNCTION sync_post_to_tv();
```

**After (explicit sync)**:

```python
# In your mutation code
async def create_post(...):
    post_id = await pool.fetchval("INSERT INTO tb_post ... RETURNING id")
    await sync.sync_post([post_id])  # Explicit!
```

### Migration Steps

1. **Add explicit sync calls** to all mutations
2. **Test** that sync calls work correctly
3. **Drop triggers** once confident
4. **Deploy** new code

```sql
-- Step 3: Drop old triggers
DROP TRIGGER IF EXISTS sync_post_trigger ON tb_post;
DROP FUNCTION IF EXISTS sync_post_to_tv();
```

---

## Best Practices

### 1. Always Sync After Writes

```python
# ✅ Good: Sync immediately
post_id = await create_post(...)
await sync.sync_post([post_id])

# ❌ Bad: Forget to sync
post_id = await create_post(...)
# Oops! Query side is now stale
```

### 2. Batch Syncs When Possible

```python
# ✅ Good: Batch sync
post_ids = await create_many_posts(...)
await sync.sync_post(post_ids)  # One call

# ❌ Bad: Individual syncs
for post_id in post_ids:
    await sync.sync_post([post_id])  # N calls
```

### 3. Log Sync Metrics

```python
import time
from fraiseql.types import ID

async def sync_post(self, post_ids: list[UUID]):
    start = time.time()

    # Do sync...

    duration_ms = (time.time() - start) * 1000
    await self._log_sync("post", post_ids, duration_ms)

    if duration_ms > 50:
        logger.warning(f"Slow sync: {duration_ms}ms for {len(post_ids)} posts")
```

### 4. Handle Sync Errors

```python
from fraiseql.types import ID

async def sync_post(self, post_ids: list[UUID]):
    for post_id in post_ids:
        try:
            await self._do_sync(post_id)
        except Exception as e:
            logger.error(f"Sync failed for post {post_id}: {e}")
            await self._log_sync_error("post", post_id, str(e))
            # Continue with next post (don't fail entire batch)
```

---

## See Also

- [rag-system](../../examples/rag-system/) - `tv_document_embedding`, kept in sync by the SQL functions in its `schema.sql`
- [CASCADE Best Practices](../guides/cascade-best-practices.md) - Cache invalidation with sync
- [Migrations Guide](./migrations.md) - Setting up tb_/tv_ tables
- [Database Patterns](../advanced/database-patterns.md) - Advanced sync patterns

---

**Last Updated**: 2025-10-11
**FraiseQL Version**: 0.1.0+

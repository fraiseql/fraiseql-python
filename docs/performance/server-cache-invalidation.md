# CASCADE Cache Invalidation

# Server-Side Cache Invalidation

> **Note**: This document describes server-side cache invalidation, not the [GraphQL Cascade](../features/graphql-cascade.md) client-side update feature.

> **Intelligent cache invalidation that automatically propagates when related data changes**

FraiseQL's CASCADE invalidation system automatically detects relationships in your GraphQL schema and sets up intelligent cache invalidation rules. When a `User` changes, all related `Post` caches are automatically invalidated—no manual configuration required.

---

## Overview

### The Cache Invalidation Problem

Traditional caching faces a fundamental challenge:

```python
# User changes
await update_user(user_id, new_name="Alice Smith")

# But cached posts still show old user name!
posts = await cache.get(f"user:{user_id}:posts")
# Returns: Posts with "Alice Johnson" (stale!)
```

**Common solutions**:

- ❌ **Time-based expiry**: Wasteful, can still serve stale data
- ❌ **Manual invalidation**: Error-prone, easy to forget
- ❌ **Invalidate everything**: Too aggressive, kills performance

### FraiseQL's Solution: CASCADE Invalidation

```python
# Setup CASCADE rules (once, at startup)
await setup_auto_cascade_rules(cache, schema, verbose=True)

# User changes
await update_user(user_id, new_name="Alice Smith")

# CASCADE automatically invalidates:
# - user:{user_id}
# - user:{user_id}:posts
# - post:* where author_id = user_id
# - Any other dependent caches
```

**Result**: Cache stays consistent automatically, no manual work needed.

---

## How CASCADE Works

### Relationship Detection

FraiseQL analyzes your GraphQL schema to detect relationships:

```graphql
type User {
  id: ID!
  name: String!
  posts: [Post!]!  # ← CASCADE detects this relationship
}

type Post {
  id: ID!
  title: String!
  author: User!  # ← CASCADE detects this too
  comments: [Comment!]!  # ← And this
}

type Comment {
  id: ID!
  content: String!
  author: User!  # ← This creates User → Comment CASCADE
  post: Post!  # ← And Post → Comment CASCADE
}
```

**CASCADE graph**:

```
User
 ├─> Post (author relationship)
 └─> Comment (author relationship)

Post
 └─> Comment (post relationship)
```

### Automatic Rule Creation

Based on the schema above, CASCADE creates these rules:

```python
# When User changes
CASCADE: user:{id} → invalidate:
  - user:{id}:posts
  - post:* where author_id={id}
  - comment:* where author_id={id}

# When Post changes
CASCADE: post:{id} → invalidate:
  - post:{id}:comments
  - comment:* where post_id={id}
  - user:{author_id}:posts  # Parent relationship
```

---

## Auto-Detection from Schema

### Setup at Application Startup

```python
from fraiseql import create_app
from fraiseql.caching import setup_auto_cascade_rules

app = create_app()

@app.on_event("startup")
async def setup_cascade():
    """Setup CASCADE invalidation rules from GraphQL schema."""

    # Auto-detect and setup CASCADE rules
    await setup_auto_cascade_rules(
        cache=app.cache,
        schema=app.schema,
        verbose=True  # Log detected rules
    )

    logger.info("CASCADE rules configured")
```

**Output** (when `verbose=True`):

```
CASCADE: Analyzing GraphQL schema...
CASCADE: Detected relationship: User -> Post (field: posts)
CASCADE: Detected relationship: User -> Comment (field: comments)
CASCADE: Detected relationship: Post -> Comment (field: comments)
CASCADE: Created 3 CASCADE rules
CASCADE: Rule 1: user:{id} cascades to post:author:{id}
CASCADE: Rule 2: user:{id} cascades to comment:author:{id}
CASCADE: Rule 3: post:{id} cascades to comment:post:{id}
✓ CASCADE rules configured
```

### Schema Requirements

For CASCADE to work, your schema needs relationship fields:

```graphql
# ✅ Good: Clear relationships
type User {
  posts: [Post!]!  # CASCADE can detect this
}

type Post {
  author: User!  # CASCADE can detect this
}
```

```graphql
# ❌ Bad: No explicit relationships
type User {
  id: ID!
  # No posts field - CASCADE can't detect relationship
}

type Post {
  author_id: ID!  # Just an ID, not a relationship
}
```

---

## Manual CASCADE Rules

### When Auto-Detection Isn't Enough

Sometimes you need custom CASCADE rules:

```python
from fraiseql.caching import CacheInvalidationRule

# Define custom CASCADE rule
rule = CacheInvalidationRule(
    entity_type="user",
    cascade_to=[
        "post:author:{id}",      # Invalidate all posts by this user
        "user:{id}:followers",   # Invalidate follower list
        "feed:follower:*"        # Invalidate feeds for all followers
    ]
)

# Register the rule
await cache.register_cascade_rule(rule)
```

### Complex CASCADE Patterns

#### Pattern 1: Multi-Level CASCADE

```python
# User → Post → Comment (2 levels deep)
user_rule = CacheInvalidationRule(
    entity_type="user",
    cascade_to=[
        "post:author:{id}",           # Direct: User's posts
        "comment:post_author:{id}"    # Indirect: Comments on user's posts
    ]
)

# When user changes:
# 1. Invalidate user's posts
# 2. Invalidate comments on those posts
# Result: Full cascade through 2 levels
```

#### Pattern 2: Bidirectional CASCADE

```python
# User ↔ Post (both directions)

# Forward: User → Post
user_to_post = CacheInvalidationRule(
    entity_type="user",
    cascade_to=["post:author:{id}"]
)

# Backward: Post → User
post_to_user = CacheInvalidationRule(
    entity_type="post",
    cascade_to=["user:{author_id}"]  # Invalidate author's cache
)

# When post changes, author's cache is invalidated
# When user changes, their posts are invalidated
```

#### Pattern 3: Conditional CASCADE

```python
# Only cascade published posts
published_posts_rule = CacheInvalidationRule(
    entity_type="user",
    cascade_to=["post:author:{id}"],
    condition=lambda data: data.get("published") is True
)

# CASCADE only triggers for published posts
```

---

## Performance Considerations

### CASCADE Overhead

**Cost of CASCADE**:

- Rule evaluation: **<1ms** per invalidation
- Pattern matching: **~0.1ms** per pattern
- Actual invalidation: **~0.5ms** per cache key

**Example**:

```python
# User changes → cascades to 10 posts
# Cost: 1ms + (10 × 0.5ms) = 6ms total

# Still much faster than cache miss!
# Cache miss would cost: ~50ms database query
```

### Optimizing CASCADE

#### 1. Limit CASCADE Depth

```python
# ✅ Good: 1-2 levels deep
User → Post → Comment  # 2 levels, reasonable

# ⚠️ Careful: 3+ levels deep
User → Post → Comment → Reply → Reaction  # 4 levels, may be expensive
```

#### 2. Use Selective CASCADE

```python
# ❌ Bad: Cascade everything
rule = CacheInvalidationRule(
    entity_type="user",
    cascade_to=["*"]  # Invalidates EVERYTHING!
)

# ✅ Good: Cascade specific patterns
rule = CacheInvalidationRule(
    entity_type="user",
    cascade_to=[
        "post:author:{id}",
        "comment:author:{id}"
    ]  # Only what's needed
)
```

#### 3. Batch CASCADE Operations

```python
# ✅ Batch invalidations
user_ids = [user1, user2, user3]

# Single CASCADE operation for all users
await cache.invalidate_batch([f"user:{uid}" for uid in user_ids])

# CASCADE propagates efficiently
```

### Monitoring CASCADE Performance

```python
# Track CASCADE metrics
@app.middleware("http")
async def track_cascade_metrics(request, call_next):
    start = time.time()

    response = await call_next(request)

    cascade_time = time.time() - start
    if cascade_time > 0.01:  # >10ms
        logger.warning(f"Slow CASCADE: {cascade_time:.2f}ms")

    return response
```

---

## Advanced Patterns

### Pattern 1: Lazy CASCADE

Instead of immediate invalidation, defer to background task:

```python
# Immediate: Invalidate now (default)
await cache.invalidate("user:123")

# Lazy: Queue for later invalidation
await cache.invalidate_lazy("user:123", delay=5.0)

# Useful for:
# - Non-critical caches
# - Batch processing
# - Reducing mutation latency
```

### Pattern 2: Partial CASCADE

Invalidate only specific fields, not entire cache:

```python
# Invalidate entire post
await cache.invalidate("post:123")

# Or: Invalidate only post title
await cache.invalidate_field("post:123", field="title")

# Author name changed? Only invalidate author field
await cache.invalidate_field("post:*", field="author.name")
```

### Pattern 3: Smart CASCADE

CASCADE based on data changes:

```python
# Only cascade if email changed (not password)
if old_user["email"] != new_user["email"]:
    await cache.invalidate(f"user:{user_id}")
    # Cascade: user's posts need new email

# If only password changed, no cascade needed
# (posts don't show password)
```

---

## Monitoring CASCADE

### CASCADE Metrics

```python
# Get CASCADE statistics
stats = await cache.get_cascade_stats()

print(stats)
# {
#     "total_invalidations_24h": 15234,
#     "cascade_triggered": 8521,
#     "avg_cascade_depth": 1.8,
#     "avg_cascade_time_ms": 4.2,
#     "most_frequent_cascades": [
#         {"pattern": "user -> post", "count": 4521},
#         {"pattern": "post -> comment", "count": 2134}
#     ]
# }
```

### CASCADE Visualization

```python
# Visualize CASCADE graph
cascade_graph = await cache.get_cascade_graph()

# Output:
# user:123
#  ├─> post:author:123 (12 keys invalidated)
#  ├─> comment:author:123 (45 keys invalidated)
#  └─> follower:following:123 (234 keys invalidated)
```

### Debugging CASCADE

```python
# Enable CASCADE logging
await cache.set_cascade_logging(enabled=True, level="DEBUG")

# Then monitor logs:
# [CASCADE] user:123 changed
# [CASCADE] → Evaluating rule: user -> post:author:{id}
# [CASCADE] → Matched 12 keys: post:author:123:*
# [CASCADE] → Invalidating: post:author:123:page:1
# [CASCADE] → Invalidating: post:author:123:page:2
# [CASCADE] → ... (10 more)
# [CASCADE] ✓ CASCADE complete in 5.2ms
```

---

## Integration with CQRS

### CASCADE in CQRS Pattern

When using explicit sync, CASCADE happens at the **query side** (tv_*):

```python
# Command side: Update tb_user
async with db.get_pool().connection() as conn:
    await conn.execute(
        "UPDATE tb_user SET name = %s WHERE id = %s",
        ("Alice Smith", user_id),
    )

# Explicit sync to query side
await sync.sync_user([user_id])

# CASCADE: tv_user changed → invalidate related caches
# - user:{user_id}:posts
# - post:* where author_id = {user_id}

# Next query will re-read from tv_post (which has updated author name)
```

**Key insight**: CASCADE works on denormalized `tv_*` tables, ensuring consistent reads.

---

## Troubleshooting

### CASCADE Not Triggering

**Problem**: User changes but posts still show old data.

**Solution**:

1. Check CASCADE rules are set up:

   ```python
   rules = await cache.get_cascade_rules()
   print(rules)  # Should show user -> post rule
   ```

2. Verify entity type matches:

   ```python
   # ✅ Correct
   await cache.invalidate("user:123")  # Matches "user" entity

   # ❌ Wrong
   await cache.invalidate("users:123")  # "users" != "user"
   ```

3. Enable CASCADE logging:

   ```python
   await cache.set_cascade_logging(True, level="DEBUG")
   ```

### Too Many Invalidations

**Problem**: CASCADE is invalidating too much, killing performance.

**Solution**:

1. Review CASCADE rules:

   ```python
   # ❌ Too broad
   rule = CacheInvalidationRule("user", cascade_to=["*"])

   # ✅ Specific
   rule = CacheInvalidationRule("user", cascade_to=["post:author:{id}"])
   ```

2. Limit CASCADE depth:

   ```python
   rule = CacheInvalidationRule(
       "user",
       cascade_to=["post:author:{id}"],
       max_depth=2  # Don't cascade more than 2 levels
   )
   ```

3. Use conditional CASCADE:

   ```python
   # Only cascade if published
   rule = CacheInvalidationRule(
       "post",
       condition=lambda data: data.get("published") is True
   )
   ```

---

## Best Practices

### 1. Start with Auto-Detection

```python
# ✅ Let FraiseQL detect relationships
await setup_auto_cascade_rules(cache, schema)

# Then add custom rules as needed
```

### 2. Monitor CASCADE Performance

```python
# Track CASCADE overhead
stats = await cache.get_cascade_stats()

if stats["avg_cascade_time_ms"] > 10:
    logger.warning("CASCADE is slow, review rules")
```

### 3. Use Selective CASCADE

```python
# ✅ CASCADE only what's needed
user_rule = CacheInvalidationRule(
    "user",
    cascade_to=[
        "post:author:{id}",
        "comment:author:{id}"
    ]
)

# ❌ Don't cascade everything
user_rule = CacheInvalidationRule("user", cascade_to=["*"])
```

### 4. Test CASCADE Rules

```python
# Test CASCADE in your test suite
async def test_user_cascade():
    # Create user and post
    user_id = await create_user(...)
    post_id = await create_post(author_id=user_id, ...)

    # Cache the post
    post = await cache.get(f"post:{post_id}")

    # Update user
    await update_user(user_id, name="New Name")

    # Verify CASCADE invalidated post cache
    assert await cache.get(f"post:{post_id}") is None
```

---

## See Also

- [GraphQL Cascade Example](../../examples/graphql-cascade/) - See CASCADE in action
- [Caching Guide](./caching.md) - General caching documentation
- [Explicit Sync Guide](../core/explicit-sync.md) - How sync works with CASCADE
- [Performance Tuning](./index.md) - Optimize CASCADE performance

---

**Last Updated**: 2025-10-11
**FraiseQL Version**: 0.1.0+

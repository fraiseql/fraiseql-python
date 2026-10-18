---
title: Cascade Best Practices
description: Best practices for GraphQL Cascade cache invalidation
tags:
  - cascade
  - best-practices
  - cache
  - invalidation
  - patterns
---

# GraphQL Cascade Best Practices

This guide provides recommendations for effectively using GraphQL Cascade in your FraiseQL applications. Cascade enables automatic cache updates and side effect tracking, but proper usage is key to maximizing benefits while avoiding pitfalls.

## Quick Decision Matrix

| Mutation Type | CASCADE? | Reason |
|--------------|----------|---------|
| Create post with author stats update | ✅ YES | Multiple entities affected, cache needs update |
| Update user preference (UI only) | ❌ NO | Single entity, no side effects |
| Bulk data import (100+ records) | ❌ NO | Large payload, server-side operation |
| Mobile app background sync | ❌ NO | Bandwidth concerns, not user-facing |
| Order creation (inventory update) | ✅ YES | Side effects (inventory) need cache update |
| Delete comment (update counts) | ✅ YES | Related entities (post, user) affected |
| Simple status toggle | ❌ NO | Single field update, no dependencies |
| Create invoice (update account balance) | ✅ YES | Financial side effects critical for UI |

**Rule of Thumb**:

- **Use CASCADE** when side effects affect entities the client cares about
- **Skip CASCADE** for simple CRUD or server-side operations

---

## When to Use Cascade

### ✅ Request CASCADE When

**You Need Cache Updates**

```graphql
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on CreatePostSuccess {
      post { id title }
      cascade {
        updated { __typename id entity }
        invalidations { queryName }
      }
    }
  }
}
```

Use CASCADE when your client needs to update its cache based on side effects.

**You're Using Apollo Client or Similar**
CASCADE works seamlessly with Apollo Client's automatic cache updates.

**You Have Complex Mutations**
Mutations that affect multiple entities benefit from CASCADE for consistency.

### ❌ Don't Request CASCADE When

**Simple Display-Only Mutations**

```graphql
mutation UpdateUserPreference($input: PreferenceInput!) {
  updatePreference(input: $input) {
    ... on UpdatePreferenceSuccess {
      message
      # No cascade needed - just showing success message
    }
  }
}
```

**Server-Side Only Operations**
Background jobs, webhooks, or API-to-API calls typically don't need CASCADE.

**Mobile Clients with Limited Bandwidth**
Mobile clients on slow connections should avoid CASCADE unless absolutely necessary.

### Partial CASCADE Selections

Request only the CASCADE fields you need:

```graphql
# Only need to know affected count
cascade {
  metadata { affectedCount }
}

# Only need invalidations for cache clearing
cascade {
  invalidations { queryName strategy }
}

# Only need updated entities (not deletes or invalidations)
cascade {
  updated {
    __typename
    id
    entity
  }
}
```

This reduces payload size while still getting needed side effect information.

### ✅ Good Candidates for Cascade

**Multi-Entity Mutations**

```sql
-- Creating a post updates both post and user entities
CREATE OR REPLACE FUNCTION graphql.create_post(input jsonb)
RETURNS jsonb AS $$
BEGIN
    -- Create post
    INSERT INTO tb_post (title, content, author_id) VALUES (...)
    RETURNING id INTO v_post_id;

    -- Update author's post count
    UPDATE tb_user SET post_count = post_count + 1 WHERE id = v_author_id;

    -- Return cascade for both entities
    RETURN jsonb_build_object(
        'success', true,
        'data', jsonb_build_object('id', v_post_id),
        '_cascade', app.build_cascade(
            updated => jsonb_build_array(
                app.cascade_entity('Post', v_post_id, 'CREATED', 'v_post'),
                app.cascade_entity('User', v_author_id, 'UPDATED', 'v_user')
            )
        )
    );
END;
$$ LANGUAGE plpgsql;
```

**List Invalidation Requirements**

```sql
-- New post requires invalidating post lists
'_cascade', app.build_cascade(
    updated => jsonb_build_array(
        app.cascade_entity('Post', v_post_id, 'CREATED', 'v_post')
    ),
    invalidations => jsonb_build_array(
        app.cascade_invalidation('posts', 'INVALIDATE', 'PREFIX'),
        app.cascade_invalidation('userPosts', 'INVALIDATE', 'EXACT')
    )
)
```

**Complex Business Logic**

- Order placement updating inventory, user balance, and order history
- User following updating follower counts and feed timelines
- Comment creation updating post stats and notification counts

### ❌ When to Skip Cascade

**Single Entity Updates**

```python
# Simple preference update - no cascade needed
@mutation  # Not enable_cascade=True
class UpdatePreferences:
    input: UpdatePreferencesInput
    success: UpdatePreferencesSuccess
    error: UpdatePreferencesError
```

**Frequent, Independent Updates**

- Real-time cursor position updates
- Typing indicators
- Presence status changes

**Large, Infrequent Operations**

- Bulk imports/exports
- Database migrations
- Administrative operations

---

## Mutations Without CASCADE

For simple mutations with no side effects, skip CASCADE entirely to reduce payload size and improve performance.

### GraphQL (No CASCADE Requested)

```graphql
mutation UpdateUserPreference($input: PreferenceInput!) {
  updatePreference(input: $input) {
    ... on UpdatePreferenceSuccess {
      message  # Just show success message
      # NO cascade field requested
    }
  }
}
```

**Response** (minimal payload):

```json
{
  "data": {
    "updatePreference": {
      "message": "Preference updated successfully"
    }
  }
}
```

### SQL Function (No CASCADE Tracking)

```sql
CREATE OR REPLACE FUNCTION fn_update_preference(
    p_user_id UUID,
    p_key TEXT,
    p_value TEXT
) RETURNS JSONB AS $$
BEGIN
    UPDATE tb_user_preferences
    SET value = p_value, updated_at = NOW()
    WHERE user_id = p_user_id AND key = p_key;

    -- Simple success response (no _cascade object)
    RETURN jsonb_build_object(
        'success', true,
        'message', 'Preference updated'
    );
    -- Note: No app.build_cascade() call
END;
$$ LANGUAGE plpgsql;
```

### Python Mutation (CASCADE Disabled)

```python
from fraiseql import mutation

@mutation  # Note: enable_cascade=False by default
class UpdatePreference:
    """Simple preference update - no side effects"""
    input: UpdatePreferenceInput
    success: UpdatePreferenceSuccess
    error: UpdatePreferenceError
```

**Benefits**:

- ✅ **Smaller payload**: ~50-80% reduction vs CASCADE response
- ✅ **Faster response**: No CASCADE tracking overhead
- ✅ **Lower bandwidth**: Critical for mobile clients
- ✅ **Simpler debugging**: Less data to inspect

**Use this pattern for**:

- User preferences/settings
- Simple status toggles
- Single-field updates
- Background operations

---

## Designing Cascade Data

### Entity Selection Principles

**Include All Affected Entities**

```sql
-- GOOD: Include both post and author
updated => jsonb_build_array(
    app.cascade_entity('Post', v_post_id, 'CREATED', 'v_post'),
    app.cascade_entity('User', v_author_id, 'UPDATED', 'v_user')
)

-- BAD: Missing author update
updated => jsonb_build_array(
    app.cascade_entity('Post', v_post_id, 'CREATED', 'v_post')
)
```

**Use Appropriate Operations**

- `CREATED`: New entities added to the system
- `UPDATED`: Existing entities modified
- `DELETED`: Entities removed (use `deleted` array)

**Keep Entity Data Complete**

```sql
-- GOOD: Complete entity data
CREATE VIEW v_post AS
SELECT id, jsonb_build_object(
    'id', id,
    'title', title,
    'content', content,
    'author_id', author_id,
    'created_at', created_at,
    'updated_at', updated_at,
    'like_count', like_count
) as data FROM tb_post;

-- BAD: Incomplete entity data
jsonb_build_object(
    'id', id,
    'title', title
    -- Missing other fields clients expect
)
```

### Invalidation Strategies

**Query-Specific Invalidations**

```sql
-- Invalidate specific query patterns
invalidations => jsonb_build_array(
    -- Invalidate all post-related queries
    app.cascade_invalidation('posts', 'INVALIDATE', 'PREFIX'),
    -- Invalidate user-specific queries
    app.cascade_invalidation('userPosts', 'INVALIDATE', 'EXACT')
)
```

**Scope Options**

- `PREFIX`: Invalidate queries starting with the name (e.g., `posts`, `postsConnection`)
- `EXACT`: Invalidate only exact query name matches
- `SUFFIX`: Invalidate queries ending with the name (less common)

**Strategic Invalidation**

```sql
-- For new posts: invalidate list queries but not individual post queries
invalidations => jsonb_build_array(
    app.cascade_invalidation('posts', 'INVALIDATE', 'PREFIX'),
    app.cascade_invalidation('feed', 'INVALIDATE', 'PREFIX')
)

-- For profile updates: invalidate user-specific queries
invalidations => jsonb_build_array(
    app.cascade_invalidation('userProfile', 'INVALIDATE', 'EXACT'),
    app.cascade_invalidation('currentUser', 'INVALIDATE', 'EXACT')
)
```

## Performance Optimization

### Payload Size Management

**Keep Cascade Payloads Reasonable**

```sql
-- GOOD: Essential entities only
-- Post creation affects: Post + Author (2 entities)

-- AVOID: Over-inclusive cascades
-- Don't include every related entity in the system
```

**Monitor Payload Sizes**

```python
# Track cascade payload sizes in production
cascade_size = Histogram('fraiseql_cascade_payload_bytes', 'Cascade payload size')
```

**Large Cascade Thresholds**

- **Small**: < 1KB (most mutations)
- **Medium**: 1-10KB (complex business logic)
- **Large**: > 10KB (review necessity)

### Client Cache Efficiency

**Prefer Entity Updates Over Invalidations**

```sql
-- GOOD: Update specific entities
updated => jsonb_build_array(
    app.cascade_entity('User', v_user_id, 'UPDATED', 'v_user')
)

-- LESS EFFICIENT: Invalidate and refetch
invalidations => jsonb_build_array(
    app.cascade_invalidation('userProfile', 'INVALIDATE', 'EXACT')
)
```

**Batch Related Updates**

```sql
-- GOOD: Single cascade with multiple updates
updated => jsonb_build_array(
    app.cascade_entity('Post', v_post_id, 'CREATED', 'v_post'),
    app.cascade_entity('User', v_author_id, 'UPDATED', 'v_user'),
    app.cascade_entity('Feed', v_feed_id, 'UPDATED', 'v_feed')
)
```

## Error Handling

### Cascade on Error Responses

**Include Cascade on Partial Success**

```sql
-- If some operations succeeded but validation failed
IF validation_error THEN
    RETURN jsonb_build_object(
        'success', false,
        'error', jsonb_build_object('code', 'VALIDATION_ERROR', ...),
        '_cascade', v_partial_cascade  -- Still include successful updates
    );
END IF;
```

**No Cascade on Complete Failure**

```sql
-- If nothing was actually changed
IF complete_failure THEN
    RETURN jsonb_build_object(
        'success', false,
        'error', jsonb_build_object('code', 'PERMISSION_DENIED', ...)
        -- No _cascade field
    );
END IF;
```

### Client Error Handling

**Graceful Cascade Processing**

```typescript
const result = await client.mutate({ mutation: CREATE_POST, variables });

if (result.data?.createPost.cascade) {
    try {
        await applyCascadeToCache(result.data.createPost.cascade);
    } catch (error) {
        // Log error but don't fail the mutation
        console.warn('Cascade application failed:', error);
        // Optionally invalidate entire cache as fallback
        client.cache.reset();
    }
}
```

**Validate Cascade Structure**

```typescript
function applyCascadeToCache(cascade: CascadeData) {
    // Validate structure before processing
    if (!cascade.updated && !cascade.deleted && !cascade.invalidations) {
        throw new Error('Invalid cascade structure');
    }

    // Process updates...
}
```

## Database Design

### Entity View Patterns

**Consistent View Naming**

```sql
-- Use v_ prefix for cascade views
CREATE VIEW v_user AS SELECT id, jsonb_build_object(...) as data FROM tb_user;
CREATE VIEW v_post AS SELECT id, jsonb_build_object(...) as data FROM tb_post;
CREATE VIEW v_comment AS SELECT id, jsonb_build_object(...) as data FROM tb_comment;
```

**Complete Entity Data**

```sql
-- Include all fields clients typically need
CREATE VIEW v_post AS
SELECT id, jsonb_build_object(
    'id', id,
    'title', title,
    'content', content,
    'author', jsonb_build_object(
        'id', author_id,
        'name', (SELECT name FROM tb_user WHERE id = author_id)
    ),
    'created_at', created_at,
    'updated_at', updated_at,
    'like_count', like_count,
    'comment_count', comment_count
) as data FROM tb_post;
```

**Performance Considerations**

```sql
-- Add indexes for cascade view performance
CREATE INDEX idx_post_author_id ON tb_post(author_id);
CREATE INDEX idx_user_id ON tb_user(id);

-- Ensure views are fast to query
EXPLAIN ANALYZE SELECT data FROM v_post WHERE id = 'some-uuid';
```

### Helper Function Usage

**Standard Helper Functions**

```sql
-- Use consistent helper functions across your application
CREATE OR REPLACE FUNCTION app.cascade_entity(text, uuid, text, text) RETURNS jsonb;
CREATE OR REPLACE FUNCTION app.cascade_invalidation(text, text, text) RETURNS jsonb;
CREATE OR REPLACE FUNCTION app.build_cascade(jsonb, jsonb, jsonb, jsonb) RETURNS jsonb;
```

**Custom Helpers for Your Domain**

```sql
-- Domain-specific cascade builders
CREATE OR REPLACE FUNCTION app.cascade_post_creation(uuid, uuid) RETURNS jsonb;
CREATE OR REPLACE FUNCTION app.cascade_user_update(uuid) RETURNS jsonb;
```

## Client Integration Patterns

### Apollo Client Best Practices

**Type-Safe Cascade Handling**

```typescript
interface CascadeUpdate {
    __typename: string;
    id: string;
    operation: 'CREATED' | 'UPDATED' | 'DELETED';
    entity: any;
}

interface CascadeData {
    updated: CascadeUpdate[];
    deleted: { __typename: string; id: string }[];
    invalidations: { queryName: string; strategy: string; scope: string }[];
    metadata: { timestamp: string; affectedCount: number };
}

function applyCascade(cache: ApolloCache, cascade: CascadeData) {
    // Apply updates
    cascade.updated.forEach(update => {
        const id = cache.identify({ __typename: update.__typename, id: update.id });
        cache.writeFragment({
            id,
            fragment: gql`fragment _ on ${update.__typename} { id }`,
            data: update.entity
        });
    });

    // Apply deletions
    cascade.deleted.forEach(deletion => {
        const id = cache.identify(deletion);
        cache.evict({ id });
    });

    // Apply invalidations
    cascade.invalidations.forEach(invalidation => {
        if (invalidation.strategy === 'INVALIDATE') {
            // Implement invalidation logic based on scope
        }
    });
}
```

**Optimistic Updates with Cascade**

```typescript
const [createPost] = useMutation(CREATE_POST, {
    optimisticResponse: {
        createPost: {
            id: 'temp-id',
            message: 'Post created',
            cascade: {
                // Include expected cascade data for optimistic updates
            }
        }
    },
    update: (cache, result) => {
        if (result.data?.createPost.cascade) {
            applyCascade(cache, result.data.createPost.cascade);
        }
    }
});
```

### Error Recovery

**Fallback Strategies**

```typescript
function applyCascadeWithFallback(cache: ApolloCache, cascade: CascadeData) {
    try {
        applyCascade(cache, cascade);
    } catch (error) {
        console.warn('Cascade application failed, falling back to cache reset');
        // Fallback: reset cache to force refetch
        cache.reset();
    }
}
```

**Partial Failure Handling**

```typescript
function applyCascadeRobust(cache: ApolloCache, cascade: CascadeData) {
    let successCount = 0;
    let failureCount = 0;

    // Apply updates individually
    cascade.updated.forEach(update => {
        try {
            const id = cache.identify(update);
            cache.writeFragment({
                id,
                fragment: gql`fragment _ on ${update.__typename} { id }`,
                data: update.entity
            });
            successCount++;
        } catch (error) {
            console.warn(`Failed to update ${update.__typename}:${update.id}`, error);
            failureCount++;
        }
    });

    // Log results
    if (failureCount > 0) {
        console.warn(`Cascade partially failed: ${successCount} successes, ${failureCount} failures`);
    }
}
```

## Monitoring and Observability

### Key Metrics to Track

**Performance Metrics**

```python
# Cascade processing time
cascade_processing_duration = Histogram(
    'fraiseql_cascade_processing_duration_seconds',
    'Time spent processing cascade data'
)

# Payload sizes
cascade_payload_bytes = Histogram(
    'fraiseql_cascade_payload_bytes',
    'Size of cascade payloads in bytes'
)

# Entity counts
cascade_entities_total = Counter(
    'fraiseql_cascade_entities_total',
    'Total entities processed via cascade',
    ['operation']  # CREATED, UPDATED, DELETED
)
```

**Effectiveness Metrics**

```python
# Cache hit improvements
cache_hit_rate = Gauge(
    'fraiseql_cache_hit_rate',
    'Client cache hit rate percentage'
)

# Network request reduction
network_requests_reduced_total = Counter(
    'fraiseql_network_requests_reduced_total',
    'Network requests eliminated by cascade'
)
```

**Error Metrics**

```python
# Cascade processing errors
cascade_errors_total = Counter(
    'fraiseql_cascade_errors_total',
    'Total cascade processing errors',
    ['error_type']
)
```

### Alerting Rules

**Performance Alerts**

```yaml
groups:
  - name: cascade_performance
    rules:
      - alert: HighCascadeProcessingTime
        expr: histogram_quantile(0.95, rate(fraiseql_cascade_processing_duration_seconds_bucket[5m])) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Cascade processing time is too high"

      - alert: LargeCascadePayloads
        expr: histogram_quantile(0.95, fraiseql_cascade_payload_bytes) > 50000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Cascade payloads are getting large"
```

**Error Alerts**

```yaml
      - alert: CascadeProcessingErrors
        expr: rate(fraiseql_cascade_errors_total[5m]) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High rate of cascade processing errors"
```

## Testing Strategies

### Unit Tests

**Test Cascade Data Structure**

```python
def test_cascade_data_structure():
    cascade = generate_cascade_data()
    assert 'updated' in cascade
    assert 'deleted' in cascade
    assert 'invalidations' in cascade
    assert 'metadata' in cascade

    for update in cascade['updated']:
        assert '__typename' in update
        assert 'id' in update
        assert 'operation' in update
        assert 'entity' in update
```

**Test Helper Functions**

```sql
-- Test cascade_entity function
SELECT app.cascade_entity('Post', '123e4567-e89b-12d3-a456-426614174000', 'CREATED', 'v_post');

-- Expected: Valid cascade entity JSONB
```

### Integration Tests

**End-to-End Cascade Flow**

```python
async def test_cascade_end_to_end():
    # Create test data
    # Execute mutation
    # Verify cascade in response
    # Verify client cache state
    # Verify UI updates without additional queries
```

**Error Scenarios**

```python
async def test_cascade_with_partial_failure():
    # Test cascade when some updates succeed but others fail
    # Verify partial cascade application
    # Verify error handling and logging
```

### Client Tests

**Apollo Cache Updates**

```typescript
it('applies cascade updates to cache', () => {
    const mockCache = new MockApolloCache();
    const cascade = createMockCascade();

    applyCascade(mockCache, cascade);

    expect(mockCache.writeFragment).toHaveBeenCalledTimes(cascade.updated.length);
    expect(mockCache.evict).toHaveBeenCalledTimes(cascade.invalidations.length);
});
```

## Migration and Rollback

### Gradual Adoption

**Start with Low-Risk Mutations**

1. Begin with read-heavy mutations (create operations)
2. Add cascade to update operations
3. Finally tackle delete operations

**Feature Flags**

```python
# Use environment variables for gradual rollout
ENABLE_CASCADE = os.getenv('ENABLE_CASCADE', 'false').lower() == 'true'

@mutation(enable_cascade=ENABLE_CASCADE)
class CreatePost:
    # ...
```

### Rollback Strategies

**Immediate Rollback**

1. Remove `enable_cascade=True` from mutations
2. Clients gracefully ignore cascade field
3. Monitor for performance improvements

**Partial Rollback**

1. Keep cascade enabled but reduce scope
2. Remove complex cascades, keep simple ones
3. Adjust invalidation strategies

**Full Rollback**

1. Remove all cascade-related code
2. Drop helper functions (optional)
3. Revert to traditional cache management

## Common Pitfalls

### Over-Cascading

**Problem**: Including too many entities in cascade
**Solution**: Include only directly affected entities
**Impact**: Large payloads, complex client logic

### Under-Cascading

**Problem**: Missing important entity updates
**Solution**: Audit all side effects of mutations
**Impact**: Inconsistent cache state, unnecessary refetches

### Inconsistent Entity Data

**Problem**: Cascade entity data doesn't match GraphQL schema
**Solution**: Keep views in sync with GraphQL types
**Impact**: Client errors, cache corruption

### Ignoring Performance

**Problem**: Not monitoring cascade impact
**Solution**: Track metrics and optimize based on data
**Impact**: Performance degradation, increased costs

## Advanced Patterns

### Conditional Cascade

**Based on Client Capabilities**

```sql
-- Include cascade only for clients that support it
IF input->>'client_supports_cascade' = 'true' THEN
    RETURN jsonb_build_object(
        'success', true,
        'data', ...,
        '_cascade', v_cascade
    );
ELSE
    RETURN jsonb_build_object(
        'success', true,
        'data', ...
    );
END IF;
```

**Selective Cascade**

```sql
-- Include different cascade data based on operation type
CASE input->>'operation_type'
    WHEN 'full' THEN
        -- Include all related entities
        v_cascade := app.build_full_cascade(v_post_id, v_author_id);
    WHEN 'minimal' THEN
        -- Include only essential updates
        v_cascade := app.build_minimal_cascade(v_post_id);
END CASE;
```

### Cascade Composition

**Reusable Cascade Components**

```sql
CREATE OR REPLACE FUNCTION app.cascade_user_stats(uuid) RETURNS jsonb;
CREATE OR REPLACE FUNCTION app.cascade_post_lists(uuid) RETURNS jsonb;
CREATE OR REPLACE FUNCTION app.cascade_notifications(uuid, uuid) RETURNS jsonb;

-- Compose complex cascades
v_cascade := app.build_cascade(
    updated => jsonb_build_array(
        app.cascade_entity('Post', v_post_id, 'CREATED', 'v_post'),
        app.cascade_user_stats(v_author_id)
    ),
    invalidations => jsonb_build_array(
        app.cascade_post_lists(v_author_id),
        app.cascade_notifications(v_post_id, v_author_id)
    )
);
```

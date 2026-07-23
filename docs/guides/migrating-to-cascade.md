---
title: Migrating to Cascade
description: Migration guide for GraphQL Cascade cache invalidation
tags:
  - cascade
  - migration
  - cache
  - invalidation
  - upgrade
---

# Migrating to GraphQL Cascade

This guide walks through adopting GraphQL Cascade in existing FraiseQL applications. Cascade enables automatic client cache updates, eliminating the need for follow-up queries after mutations.

## Quick Assessment: Is Cascade Right for Your App?

### ✅ Good Candidates for Cascade

- **Social Media/Community Apps**: Post creation with author stats updates
- **E-commerce**: Order placement with inventory adjustments
- **Content Management**: Article publishing with category/tag updates
- **Collaborative Tools**: Document edits with participant notifications
- **Real-time Dashboards**: Data updates with multiple dependent views

### ❌ Less Ideal for Cascade

- **Simple CRUD**: Single entity updates without side effects
- **Real-time Cursors**: Very frequent, independent updates
- **Administrative Bulk Operations**: Large-scale data imports
- **Complex Business Logic**: Heavy server-side processing

## Selection Filtering (v1.8.1+)

### Breaking Change: CASCADE Selection Awareness

Starting in v1.8.1, CASCADE data is only returned when explicitly requested in the GraphQL selection set.

### Before (v1.8.0 and earlier)

CASCADE was always included in responses if `enable_cascade=True` on the mutation, regardless of query selection:

```graphql
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on CreatePostSuccess {
      id
      message
      # cascade NOT requested
    }
  }
}
```

**Old Behavior**: Response included CASCADE anyway

```json
{
  "data": {
    "createPost": {
      "id": "123",
      "message": "Success",
      "cascade": { ... }  // Present even though not requested
    }
  }
}
```

### After (v1.8.1+)

CASCADE is only included when requested:

```graphql
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on CreatePostSuccess {
      id
      message
      # cascade NOT requested
    }
  }
}
```

**New Behavior**: No CASCADE in response

```json
{
  "data": {
    "createPost": {
      "id": "123",
      "message": "Success"
      // No cascade field
    }
  }
}
```

### Migration Steps

**Step 1**: Audit Your Queries

Find mutations that use CASCADE but don't request it:

```bash
# Search for mutations without cascade in selection
grep -r "createPost\|updatePost\|deletePost" src/graphql/mutations/
```

**Step 2**: Update Queries

Add `cascade` to selections where needed:

```diff
  mutation CreatePost($input: CreatePostInput!) {
    createPost(input: $input) {
      ... on CreatePostSuccess {
        id
        message
+       cascade {
+         updated { __typename id entity }
+         invalidations { queryName }
+       }
      }
    }
  }
```

**Step 3**: Test

Verify your application still works:

- Cache updates function correctly
- UI synchronization works
- No TypeScript errors from missing CASCADE

**Step 4**: Optimize

Remove CASCADE from queries that don't need it for performance:

```diff
  mutation UpdatePreference($input: PreferenceInput!) {
    updatePreference(input: $input) {
      ... on UpdatePreferenceSuccess {
        message
-       cascade {
-         updated { __typename id entity }
-       }
      }
    }
  }
```

### Backward Compatibility

If you need the old behavior temporarily:

```python
# Not recommended - for migration only
@fraiseql.mutation(
    enable_cascade=True,
    force_include_cascade=True,  # Always include (not implemented - use selection)
)
```

Instead, update your queries to explicitly request CASCADE.

### Performance Impact

After migration, you should see:

- 20-50% smaller response payloads (for mutations not using CASCADE)
- Faster mutation response times
- Reduced network bandwidth usage

## Migration Steps

### Phase 1: Preparation (1-2 days)

#### 1.1 Database Schema Updates

**Create Entity Views for Cascade Data**

```sql
-- Example: User entity view for cascade
CREATE VIEW v_user AS
SELECT
    id,
    jsonb_build_object(
        'id', id,
        'name', name,
        'email', email,
        'post_count', post_count,
        'updated_at', updated_at
    ) as data
FROM tb_user;
```

**Create Helper Functions** (Optional but recommended)

```sql
-- Helper functions for cascade construction
CREATE OR REPLACE FUNCTION app.cascade_entity(
    entity_type text,
    entity_id uuid,
    operation text,
    view_name text
) RETURNS jsonb AS $$
BEGIN
    RETURN jsonb_build_object(
        '__typename', entity_type,
        'id', entity_id,
        'operation', operation,
        'entity', (SELECT data FROM view_name WHERE id = entity_id)
    );
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION app.cascade_invalidation(
    query_name text,
    strategy text,
    scope text
) RETURNS jsonb AS $$
BEGIN
    RETURN jsonb_build_object(
        'queryName', query_name,
        'strategy', strategy,
        'scope', scope
    );
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION app.build_cascade(
    updated_entities jsonb DEFAULT '[]'::jsonb,
    deleted_entities jsonb DEFAULT '[]'::jsonb,
    invalidations jsonb DEFAULT '[]'::jsonb,
    metadata jsonb DEFAULT NULL
) RETURNS jsonb AS $$
BEGIN
    RETURN jsonb_build_object(
        'updated', updated_entities,
        'deleted', deleted_entities,
        'invalidations', invalidations,
        'metadata', COALESCE(metadata, jsonb_build_object(
            'timestamp', now(),
            'affectedCount', jsonb_array_length(updated_entities) + jsonb_array_length(deleted_entities)
        ))
    );
END;
$$ LANGUAGE plpgsql;
```

#### 1.2 Update PostgreSQL Functions

**Before** (Standard Mutation):

```sql
CREATE OR REPLACE FUNCTION graphql.create_post(input jsonb)
RETURNS jsonb AS $$
DECLARE
    v_post_id uuid;
BEGIN
    -- Create post
    INSERT INTO tb_post (title, content, author_id)
    VALUES (input->>'title', input->>'content', (input->>'author_id')::uuid)
    RETURNING id INTO v_post_id;

    -- Update author stats
    UPDATE tb_user SET post_count = post_count + 1 WHERE id = (input->>'author_id')::uuid;

    -- Return success
    RETURN jsonb_build_object(
        'success', true,
        'data', jsonb_build_object('id', v_post_id, 'message', 'Post created')
    );
END;
$$ LANGUAGE plpgsql;
```

**After** (With Cascade):

```sql
CREATE OR REPLACE FUNCTION graphql.create_post(input jsonb)
RETURNS jsonb AS $$
DECLARE
    v_post_id uuid;
    v_author_id uuid;
BEGIN
    -- Create post
    INSERT INTO tb_post (title, content, author_id)
    VALUES (input->>'title', input->>'content', (input->>'author_id')::uuid)
    RETURNING id INTO v_post_id;

    v_author_id := (input->>'author_id')::uuid;

    -- Update author stats
    UPDATE tb_user SET post_count = post_count + 1 WHERE id = v_author_id;

    -- Return with cascade data
    RETURN jsonb_build_object(
        'success', true,
        'data', jsonb_build_object('id', v_post_id, 'message', 'Post created'),
        '_cascade', app.build_cascade(
            jsonb_build_array(
                app.cascade_entity('Post', v_post_id, 'CREATED', 'v_post'),
                app.cascade_entity('User', v_author_id, 'UPDATED', 'v_user')
            ),
            '[]'::jsonb, -- deleted
            jsonb_build_array(
                app.cascade_invalidation('posts', 'INVALIDATE', 'PREFIX'),
                app.cascade_invalidation('userPosts', 'INVALIDATE', 'EXACT')
            )
        )
    );
END;
$$ LANGUAGE plpgsql;
```

### Phase 2: Application Code Updates (1 day)

#### 2.1 Update Mutation Decorators

**Before**:

```python
import fraiseql

@fraiseql.mutation
class CreatePost:
    input: CreatePostInput
    success: CreatePostSuccess
    error: CreatePostError
```

**After**:

```python
import fraiseql

@fraiseql.mutation(enable_cascade=True)
class CreatePost:
    input: CreatePostInput
    success: CreatePostSuccess
    error: CreatePostError
```

#### 2.2 Update GraphQL Queries

**Before** (Client needs follow-up queries):

```graphql
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    id
    message
  }
}
```

**After** (Client gets cascade data):

```graphql
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    id
    message
    cascade {
      updated {
        __typename
        id
        operation
        entity
      }
      invalidations {
        queryName
        strategy
        scope
      }
    }
  }
}
```

### Phase 3: Client Integration (2-3 days)

#### 3.1 Apollo Client Integration

**Basic Cascade Processing**:

```typescript
import { useMutation, gql } from '@apollo/client';

const CREATE_POST = gql`
  mutation CreatePost($input: CreatePostInput!) {
    createPost(input: $input) {
      id
      message
      cascade {
        updated {
          __typename
          id
          operation
          entity
        }
        deleted {
          __typename
          id
        }
        invalidations {
          queryName
          strategy
          scope
        }
      }
    }
  }
`;

function CreatePostComponent() {
  const [createPost, { loading, error }] = useMutation(CREATE_POST);

  const handleSubmit = async (input) => {
    const result = await createPost({ variables: { input } });

    // Cascade processing happens automatically
    // No manual cache updates needed!
  };

  return (
    // Your component JSX
  );
}
```

**Advanced Cascade Processing** (if you need custom logic):

```typescript
import { useMutation, gql, ApolloCache } from '@apollo/client';

function applyCascadeToCache(cache: ApolloCache<any>, cascade: any) {
  if (!cascade) return;

  // Apply entity updates
  cascade.updated?.forEach(update => {
    cache.writeFragment({
      id: cache.identify({ __typename: update.__typename, id: update.id }),
      fragment: gql`
        fragment CascadeUpdate on ${update.__typename} {
          id
        }
      `,
      data: update.entity
    });
  });

  // Apply invalidations
  cascade.invalidations?.forEach(invalidation => {
    if (invalidation.strategy === 'INVALIDATE') {
      cache.evict({
        fieldName: invalidation.queryName,
        args: invalidation.scope === 'PREFIX' ? undefined : {},
        broadcast: true
      });
    }
  });
}

function CreatePostComponent() {
  const [createPost] = useMutation(CREATE_POST, {
    update: (cache, result) => {
      const cascade = result.data?.createPost?.cascade;
      if (cascade) {
        applyCascadeToCache(cache, cascade);
      }
    }
  });

  // ... rest of component
}
```

#### 3.2 React Query Integration

```typescript
import { useMutation, useQueryClient } from '@tanstack/react-query';

function useCreatePost() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input) => {
      const response = await fetch('/graphql', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: CREATE_POST_MUTATION,
          variables: { input }
        })
      });
      return response.json();
    },
    onSuccess: (data) => {
      const cascade = data.data?.createPost?.cascade;
      if (cascade) {
        // Apply cascade updates
        cascade.updated?.forEach(update => {
          queryClient.setQueryData(
            [update.__typename.toLowerCase(), update.id],
            update.entity
          );
        });

        // Invalidate queries
        cascade.invalidations?.forEach(invalidation => {
          if (invalidation.strategy === 'INVALIDATE') {
            queryClient.invalidateQueries({
              queryKey: [invalidation.queryName],
              exact: invalidation.scope === 'EXACT'
            });
          }
        });
      }
    }
  });
}
```

#### 3.3 Relay Integration

```typescript
import { commitMutation, graphql } from 'react-relay';

const mutation = graphql`
  mutation CreatePostMutation($input: CreatePostInput!) {
    createPost(input: $input) {
      id
      message
      cascade {
        updated {
          __typename
          id
          operation
          entity
        }
        invalidations {
          queryName
          strategy
          scope
        }
      }
    }
  }
`;

function commitCreatePost(environment, input) {
  return commitMutation(environment, {
    mutation,
    variables: { input },
    updater: (store, data) => {
      const cascade = data.createPost?.cascade;
      if (!cascade) return;

      // Apply entity updates
      cascade.updated?.forEach(update => {
        const record = store.get(update.id);
        if (record) {
          // Update record with new data
          Object.keys(update.entity).forEach(key => {
            record.setValue(update.entity[key], key);
          });
        }
      });

      // Handle invalidations
      cascade.invalidations?.forEach(invalidation => {
        if (invalidation.strategy === 'INVALIDATE') {
          // Invalidate Relay store for query
          // Implementation depends on your Relay setup
        }
      });
    }
  });
}
```

### Phase 4: Testing & Validation (1-2 days)

#### 4.1 Unit Tests

```python
import pytest
from your_app.mutations import CreatePost

def test_cascade_enabled():
    """Test that cascade is properly enabled on mutation."""
    mutation = CreatePost()
    assert mutation.enable_cascade is True

def test_cascade_data_structure():
    """Test cascade data structure validation."""
    # Test with mock cascade data
    cascade_data = {
        "updated": [
            {
                "__typename": "Post",
                "id": "post-123",
                "operation": "CREATED",
                "entity": {"id": "post-123", "title": "Test"}
            }
        ],
        "deleted": [],
        "invalidations": [
            {
                "queryName": "posts",
                "strategy": "INVALIDATE",
                "scope": "PREFIX"
            }
        ],
        "metadata": {
            "timestamp": "2025-11-13T10:00:00Z",
            "affectedCount": 1,
            "depth": 1,
            "transactionId": "123456789"
        }
    }

    # Validate structure
    assert "updated" in cascade_data
    assert "deleted" in cascade_data
    assert "invalidations" in cascade_data
    assert "metadata" in cascade_data
```

#### 4.2 Integration Tests

```python
import pytest
from fastapi.testclient import TestClient

@pytest.mark.asyncio
async def test_cascade_end_to_end(client: TestClient, db_connection):
    """Test complete cascade flow."""
    # Setup test data
    await db_connection.execute("""
        INSERT INTO tb_user (id, name, post_count)
        VALUES ('user-123', 'Test User', 0)
    """)

    # Execute mutation
    response = client.post("/graphql", json={
        "query": """
            mutation CreatePost($input: CreatePostInput!) {
                createPost(input: $input) {
                    id
                    message
                    cascade {
                        updated {
                            __typename
                            id
                            operation
                            entity
                        }
                        invalidations {
                            queryName
                            strategy
                            scope
                        }
                    }
                }
            }
        """,
        "variables": {
            "input": {
                "title": "Test Post",
                "content": "Test content",
                "author_id": "user-123"
            }
        }
    })

    assert response.status_code == 200
    data = response.json()

    # Verify cascade data
    cascade = data["data"]["createPost"]["cascade"]
    assert cascade is not None
    assert len(cascade["updated"]) == 2  # Post + User
    assert len(cascade["invalidations"]) >= 1
```

#### 4.3 Client-Side Tests

```typescript
// Apollo Client test
describe('Cascade Integration', () => {
  it('applies cascade updates to cache', () => {
    const mockCache = createMockCache();
    const cascade = {
      updated: [
        {
          __typename: 'Post',
          id: 'post-123',
          operation: 'CREATED',
          entity: { id: 'post-123', title: 'Test Post' }
        }
      ],
      invalidations: [
        { queryName: 'posts', strategy: 'INVALIDATE', scope: 'PREFIX' }
      ]
    };

    applyCascadeToCache(mockCache, cascade);

    expect(mockCache.writeFragment).toHaveBeenCalledTimes(1);
    expect(mockCache.evict).toHaveBeenCalledTimes(1);
  });
});
```

### Phase 5: Deployment & Monitoring (1 day)

#### 5.1 Feature Flags

**Environment Variable Control**:

```bash
# Enable cascade globally
export FRAISEQL_ENABLE_CASCADE=true

# Or disable for safety
export FRAISEQL_ENABLE_CASCADE=false
```

**Per-Mutation Control** (recommended):

```python
import fraiseql

# Enable cascade for specific mutations
@fraiseql.mutation(enable_cascade=True)
class CreatePost:
    # This mutation uses cascade

@fraiseql.mutation(enable_cascade=False)
class UpdateProfile:
    # This mutation does not use cascade
```

#### 5.2 Monitoring Setup

**Performance Metrics**:

```python
# Add to your monitoring
cascade_processing_duration = Histogram(
    'fraiseql_cascade_processing_duration_seconds',
    'Time spent processing cascade data'
)

cascade_payload_bytes = Histogram(
    'fraiseql_cascade_payload_bytes',
    'Size of cascade payloads in bytes'
)

cascade_entities_total = Counter(
    'fraiseql_cascade_entities_total',
    'Total entities processed via cascade'
)
```

**Grafana Dashboard**:

- Cascade processing latency
- Payload size distribution
- Error rates
- Cache hit rate improvements

#### 5.3 Rollback Plan

**Immediate Rollback** (if issues arise):

1. Set `FRAISEQL_ENABLE_CASCADE=false`
2. No database changes needed
3. Clients ignore cascade field gracefully

**Complete Rollback**:

1. Remove `enable_cascade=True` from mutations
2. Update client code to remove cascade handling
3. Monitor for 24-48 hours

## Troubleshooting Common Issues

### Cascade Data Not Appearing

**Problem**: Cascade field is `null` or missing in GraphQL response.

**Solutions**:

1. **Check Mutation Decorator**: Ensure `@mutation(enable_cascade=True)`
2. **Verify PostgreSQL Function**: Confirm `_cascade` field in return JSONB
3. **Check Database Views**: Ensure entity views exist and are accessible
4. **Validate JSONB Structure**: Use `jsonb_pretty()` to inspect cascade data

```sql
-- Debug cascade data
SELECT jsonb_pretty(_cascade) FROM graphql.create_post('{"title": "Test", "author_id": "user-123"}');
```

### Client Cache Not Updating

**Problem**: Client cache doesn't reflect cascade changes.

**Solutions**:

1. **Check Apollo Client Version**: Ensure compatible version
2. **Verify Cache Updates**: Manually test cache.writeFragment calls
3. **Check Entity IDs**: Ensure `__typename` + `id` matches cache keys
4. **Validate Fragment Structure**: Ensure fragments match entity structure

### Performance Issues

**Problem**: Cascade processing is slow or memory-intensive.

**Solutions**:

1. **Limit Cascade Scope**: Only include necessary entities
2. **Optimize Database Views**: Add indexes for cascade view queries
3. **Batch Updates**: Group related entity updates
4. **Monitor Payload Size**: Keep cascade data under 50KB

```sql
-- Monitor cascade payload sizes
SELECT
    pg_size_pretty(pg_column_size(_cascade)) as cascade_size,
    jsonb_array_length(_cascade->'updated') as entities_updated
FROM graphql.create_post('{"title": "Test", "author_id": "user-123"}');
```

### Type Errors

**Problem**: TypeScript or GraphQL schema errors.

**Solutions**:

1. **Update GraphQL Schema**: Include cascade field in mutation responses
2. **Generate Types**: Regenerate TypeScript types after schema changes
3. **Validate Cascade Structure**: Ensure consistent `__typename` values

## Best Practices

### Database Design

- **Use Entity Views**: Create dedicated views for cascade data extraction
- **Index Cascade Views**: Add performance indexes on frequently cascaded entities
- **Consistent Naming**: Use `v_entity_name` pattern for cascade views
- **Validate Data**: Ensure views return complete, consistent entity data

### Application Architecture

- **Start Small**: Enable cascade on one mutation first
- **Feature Flags**: Use environment variables for gradual rollout
- **Error Handling**: Implement cascade error handling in clients
- **Monitoring**: Track cascade performance and usage metrics

### Client Integration

- **Apollo Client**: Leverage automatic cache updates when possible
- **Custom Logic**: Implement manual cache updates for complex scenarios
- **Error Boundaries**: Handle cascade processing errors gracefully
- **Testing**: Test cascade integration thoroughly

## Migration Checklist

### Database Preparation

- [ ] Create entity views for cascade data extraction
- [ ] Add cascade helper functions to schema
- [ ] Update PostgreSQL functions to include `_cascade` field
- [ ] Test cascade data generation

### Application Code Changes

- [ ] Add `enable_cascade=True` to mutation decorators
- [ ] Update GraphQL queries to request cascade field
- [ ] Implement client-side cascade processing logic
- [ ] Test cascade integration end-to-end

### Deployment Steps

- [ ] Enable feature flag in staging
- [ ] Deploy with cascade-enabled mutations
- [ ] Monitor performance and errors
- [ ] Gradually enable for production traffic

### Post-Deployment

- [ ] Monitor cascade performance metrics
- [ ] Collect user feedback
- [ ] Plan optimizations based on usage patterns
- [ ] Document lessons learned

## Support Resources

- **Documentation**: `docs/guides/cascade-best-practices.md`
- **Examples**: `examples/graphql-cascade/`
- **Community**: GitHub Discussions for questions
- **Enterprise**: Priority migration support available

---

**Migration Effort**: Low to Medium (2-5 days for typical application)
**Risk Level**: Low (opt-in feature with easy rollback)
**Performance Impact**: Minimal (typically < 5% overhead)

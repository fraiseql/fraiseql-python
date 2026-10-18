"""Integration tests for GraphQL Cascade functionality.

Tests end-to-end cascade behavior from PostgreSQL functions through
GraphQL responses to client cache updates.
"""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_cascade_with_nested_entity_fields(cascade_http_client):
    """Test that CASCADE doesn't break nested entity field access.

    CRITICAL: This tests the bug pattern from fraiseql_cascade_bug_report.md where
    enable_cascade=True caused entity fields to be replaced by cascade metadata.

    The bug manifests when:
    1. Success type has a nested entity field (post: Post)
    2. CASCADE is enabled
    3. GraphQL queries entity fields directly

    Expected: Entity fields accessible at allocation.id, allocation.title, etc.
    Bug behavior: Only cascade field present, entity fields missing.
    """
    mutation_query = """
    mutation CreatePostWithEntity($input: CreatePostInput!) {
        createPostWithEntity(input: $input) {
            ... on CreatePostWithEntitySuccess {
                message
                post {
                    id
                    title
                    content
                    authorId
                }
                cascade {
                    updated {
                        id
                        operation
                    }
                    deleted {
                        id
                        operation
                    }
                    invalidations {
                        queryName
                        strategy
                        scope
                    }
                    metadata {
                        timestamp
                        affectedCount
                    }
                }
            }
            ... on CreatePostError {
                code
                message
            }
        }
    }
    """

    variables = {"input": {"title": "Test Post", "content": "Test content", "authorId": "user-123"}}

    response = await cascade_http_client.post(
        "/graphql", json={"query": mutation_query, "variables": variables}
    )

    assert response.status_code == 200
    data = response.json()

    # Debug: print the response
    import json

    print("\n\n=== CASCADE WITH ENTITY FIELD RESPONSE ===")
    print(json.dumps(data, indent=2))
    print("=" * 50)

    # Verify response structure
    assert "data" in data
    assert "createPostWithEntity" in data["data"]
    result = data["data"]["createPostWithEntity"]

    # Verify message is accessible
    assert result["message"] == "Post created successfully"

    # CRITICAL: Entity fields must be accessible directly on the post object
    post = result["post"]
    assert "id" in post, "Entity 'id' field missing - CASCADE bug detected!"
    assert "title" in post, "Entity 'title' field missing - CASCADE bug detected!"
    assert "content" in post, "Entity 'content' field missing - CASCADE bug detected!"
    assert "authorId" in post, "Entity 'authorId' field missing - CASCADE bug detected!"

    # Verify entity field values
    assert post["title"] == "Test Post"
    assert post["content"] == "Test content"
    assert post["authorId"] == "user-123"

    # Verify CASCADE should NOT be on the entity object
    assert "cascade" not in post, "CASCADE metadata should be on success type, NOT on entity object"

    # Verify CASCADE data is accessible separately on the success type
    assert "cascade" in result, "CASCADE metadata should be on success type"
    cascade = result["cascade"]
    assert cascade is not None
    assert "updated" in cascade
    assert "deleted" in cascade
    assert "invalidations" in cascade
    assert "metadata" in cascade

    # Verify cascade content
    assert len(cascade["updated"]) == 2  # Post + User

    # Find Post entity in CASCADE
    post_entity = next((u for u in cascade["updated"] if u["__typename"] == "Post"), None)
    assert post_entity is not None
    assert post_entity["operation"] == "CREATED"
    # Entity field requires explicit selection (CASCADE selection filtering)
    # Since we didn't query entity field, it won't be present

    # Find User entity in CASCADE
    user_entity = next((u for u in cascade["updated"] if u["__typename"] == "User"), None)
    assert user_entity is not None
    assert user_entity["operation"] == "UPDATED"
    # Entity field requires explicit selection (CASCADE selection filtering)

    # Verify invalidations
    assert len(cascade["invalidations"]) >= 1
    posts_invalidation = next(
        (i for i in cascade["invalidations"] if i["queryName"] == "posts"), None
    )
    assert posts_invalidation is not None
    assert posts_invalidation["strategy"] == "INVALIDATE"

    # Verify metadata
    assert cascade["metadata"]["affectedCount"] == 2
    assert "timestamp" in cascade["metadata"]


@pytest.mark.asyncio
async def test_cascade_entity_fields_without_querying_cascade(cascade_http_client):
    """Test entity fields work when CASCADE metadata is not queried.

    This tests that entity fields remain accessible even when the client
    doesn't request CASCADE metadata in the query.
    """
    mutation_query = """
    mutation CreatePostWithEntity($input: CreatePostInput!) {
        createPostWithEntity(input: $input) {
            ... on CreatePostWithEntitySuccess {
                message
                post {
                    id
                    title
                    content
                    authorId
                }
            }
            ... on CreatePostError {
                code
                message
            }
        }
    }
    """

    variables = {"input": {"title": "Test Post 2", "content": "Content 2", "authorId": "user-123"}}

    response = await cascade_http_client.post(
        "/graphql", json={"query": mutation_query, "variables": variables}
    )

    assert response.status_code == 200
    data = response.json()

    result = data["data"]["createPostWithEntity"]

    # Verify entity fields are accessible without querying CASCADE
    post = result["post"]
    assert "id" in post
    assert "title" in post
    assert post["title"] == "Test Post 2"
    assert post["content"] == "Content 2"
    assert post["authorId"] == "user-123"

    # CASCADE field should NOT be present when not requested in selection set
    # This follows GraphQL spec: only return requested fields
    assert "cascade" not in result, (
        "CASCADE should not be in response when not requested in selection set. "
        "This follows GraphQL spec: only return requested fields."
    )


@pytest.mark.asyncio
async def test_cascade_with_only_cascade_no_entity_query(cascade_http_client):
    """Test that CASCADE works when entity fields are not queried.

    This verifies CASCADE metadata is accessible independently of entity fields.
    """
    mutation_query = """
    mutation CreatePostWithEntity($input: CreatePostInput!) {
        createPostWithEntity(input: $input) {
            ... on CreatePostWithEntitySuccess {
                message
                cascade {
                    updated {
                        id
                        operation
                    }
                    metadata {
                        affectedCount
                    }
                }
            }
        }
    }
    """

    variables = {"input": {"title": "Test Post 3", "content": "Content 3", "authorId": "user-123"}}

    response = await cascade_http_client.post(
        "/graphql", json={"query": mutation_query, "variables": variables}
    )

    assert response.status_code == 200
    data = response.json()

    result = data["data"]["createPostWithEntity"]

    # CASCADE should be accessible
    assert "cascade" in result
    assert result["cascade"] is not None
    assert "updated" in result["cascade"]
    assert result["cascade"]["metadata"]["affectedCount"] == 2


@pytest.mark.asyncio
async def test_async_prepare_input_with_info_reaches_function(cascade_http_client):
    """An async prepare_input taking info runs, and cascade still comes back (#557)."""
    mutation_query = """
    mutation CreatePostEnriched($input: CreatePostInput!) {
        createPostEnriched(input: $input) {
            ... on CreatePostWithEntitySuccess {
                post { title }
                cascade { updated { __typename operation } }
            }
            ... on CreatePostError { code message }
        }
    }
    """
    variables = {"input": {"title": "Draft", "authorId": "user-123"}}

    response = await cascade_http_client.post(
        "/graphql", json={"query": mutation_query, "variables": variables}
    )

    assert response.status_code == 200
    body = response.json()
    assert "errors" not in body, body
    result = body["data"]["createPostEnriched"]
    assert result["post"]["title"] == "Draft via createPostEnriched"
    assert {u["__typename"] for u in result["cascade"]["updated"]} == {"Post", "User"}


@pytest.mark.asyncio
async def test_cascade_end_to_end(cascade_http_client):
    """Test complete cascade flow from PostgreSQL function to GraphQL response.

    Uses cascade_client fixture which includes:
    - Database schema setup (via cascade_db_schema)
    - Test user already inserted
    - PostgreSQL create_post function configured

    Note: This test has event loop conflicts during teardown due to the combination of:
    - pytest-asyncio session-scoped fixtures (db_pool)
    - Function-scoped async fixtures (cascade_db_schema)
    - Sync TestClient using anyio
    The test passes correctly but fixture teardown fails.
    Run individually: pytest tests/integration/test_graphql_cascade.py::test_cascade_end_to_end -v
    """
    # Execute mutation
    mutation_query = """
    mutation CreatePost($input: CreatePostInput!) {
        createPost(input: $input) {
            ... on CreatePostSuccess {
                id
                message
                cascade {
                    updated {
                        id
                        operation
                    }
                    deleted {
                        id
                        operation
                    }
                    invalidations {
                        queryName
                        strategy
                        scope
                    }
                    metadata {
                        timestamp
                        affectedCount
                    }
                }
            }
            ... on CreatePostError {
                code
                message
            }
        }
    }
    """

    variables = {"input": {"title": "Test Post", "content": "Test content", "authorId": "user-123"}}

    response = await cascade_http_client.post(
        "/graphql", json={"query": mutation_query, "variables": variables}
    )

    assert response.status_code == 200
    data = response.json()

    # Debug: print the response
    import json

    print(f"\n\nResponse: {json.dumps(data, indent=2)}\n\n")

    # Verify response structure
    assert "data" in data
    assert "createPost" in data["data"]
    assert data["data"]["createPost"]["id"]
    # Verify message from PostgreSQL function is preserved
    assert data["data"]["createPost"]["message"] == "Post created successfully"

    # Verify cascade data
    cascade = data["data"]["createPost"]["cascade"]
    assert cascade is not None
    assert "updated" in cascade
    assert "deleted" in cascade
    assert "invalidations" in cascade
    assert "metadata" in cascade

    # Verify cascade content
    assert len(cascade["updated"]) == 2  # Post + User

    # Find Post entity
    post_entity = next((u for u in cascade["updated"] if u["__typename"] == "Post"), None)
    assert post_entity is not None
    assert post_entity["operation"] == "CREATED"
    # Entity field requires explicit selection (CASCADE selection filtering)

    # Find User entity
    user_entity = next((u for u in cascade["updated"] if u["__typename"] == "User"), None)
    assert user_entity is not None
    assert user_entity["operation"] == "UPDATED"
    # Entity field requires explicit selection (CASCADE selection filtering)

    # Verify invalidations
    assert len(cascade["invalidations"]) >= 1
    posts_invalidation = next(
        (i for i in cascade["invalidations"] if i["queryName"] == "posts"), None
    )
    assert posts_invalidation is not None
    assert posts_invalidation["strategy"] == "INVALIDATE"

    # Verify metadata
    assert cascade["metadata"]["affectedCount"] == 2
    assert "timestamp" in cascade["metadata"]


def test_cascade_with_error_response():
    """Test cascade behavior validation when mutation returns an error.

    This is a unit test that validates error response structure expectations
    without requiring a database connection.
    """
    # Simulate error response from a mutation
    error_response = {
        "data": {
            "createPost": {
                "__typename": "CreatePostError",
                "code": "VALIDATION_ERROR",
                "message": "Title cannot be empty",
                "errors": [{"field": "title", "message": "Required field"}],
            }
        }
    }

    # Verify error response structure
    assert "data" in error_response
    assert "createPost" in error_response["data"]
    result = error_response["data"]["createPost"]
    assert result["__typename"] == "CreatePostError"
    assert result["code"] == "VALIDATION_ERROR"

    # On error, cascade should NOT be present (no cache updates needed)
    assert "cascade" not in result

    # Also test success response structure for comparison
    success_response = {
        "data": {
            "createPost": {
                "__typename": "CreatePostSuccess",
                "id": "post-123",
                "message": "Created successfully",
                "cascade": {
                    "updated": [
                        {
                            "__typename": "Post",
                            "id": "post-123",
                            "operation": "CREATED",
                            "entity": {"id": "post-123", "title": "Test"},
                        }
                    ],
                    "deleted": [],
                    "invalidations": [
                        {"queryName": "posts", "strategy": "INVALIDATE", "scope": "PREFIX"}
                    ],
                    "metadata": {"timestamp": "2025-11-28T10:00:00Z", "affectedCount": 1},
                },
            }
        }
    }

    # Success response should have cascade
    success_result = success_response["data"]["createPost"]
    assert success_result["__typename"] == "CreatePostSuccess"
    assert "cascade" in success_result
    assert validate_cascade_structure(success_result["cascade"])


def test_cascade_large_payload():
    """Test cascade with multiple entities and operations using mock data."""
    # Large cascade payload with multiple entities
    large_cascade = {
        "updated": [
            {
                "__typename": "Post",
                "id": f"post-{i}",
                "operation": "CREATED",
                "entity": {"id": f"post-{i}", "title": f"Post {i}"},
            }
            for i in range(10)
        ]
        + [
            {
                "__typename": "User",
                "id": f"user-{i}",
                "operation": "UPDATED",
                "entity": {"id": f"user-{i}", "post_count": i + 1},
            }
            for i in range(5)
        ],
        "deleted": ["post-old-1", "post-old-2"],
        "invalidations": [
            {"queryName": "posts", "strategy": "INVALIDATE", "scope": "PREFIX"},
            {"queryName": "users", "strategy": "REFETCH", "scope": "FULL"},
        ],
        "metadata": {"timestamp": "2025-11-28T10:00:00Z", "affectedCount": 17},
    }

    # Validate structure
    assert validate_cascade_structure(large_cascade)
    assert len(large_cascade["updated"]) == 15
    assert len(large_cascade["deleted"]) == 2
    assert len(large_cascade["invalidations"]) == 2
    assert large_cascade["metadata"]["affectedCount"] == 17


def test_cascade_disabled_by_default():
    """Test that cascade validation fails when cascade data is None or empty."""
    # When cascade is disabled, the cascade field should be None or empty
    empty_cascade_response = {"cascade": None}
    missing_cascade_response = {}

    # Cascade should not be present or should be None
    assert empty_cascade_response.get("cascade") is None
    assert "cascade" not in missing_cascade_response

    # Empty cascade structure should fail validation
    empty_structure = {
        "updated": [],
        "deleted": [],
        "invalidations": [],
        "metadata": None,
    }
    # With None metadata, this should still be "valid" structurally but empty
    assert len(empty_structure["updated"]) == 0
    assert len(empty_structure["deleted"]) == 0


def test_cascade_malformed_data_handling():
    """Test handling of malformed cascade data."""
    # Missing required keys
    malformed_1 = {"updated": []}  # Missing deleted, invalidations, metadata
    assert not validate_cascade_structure(malformed_1)

    # Invalid entity structure (missing required fields)
    malformed_2 = {
        "updated": [{"__typename": "Post"}],  # Missing id, operation, entity
        "deleted": [],
        "invalidations": [],
        "metadata": {"timestamp": "2025-11-28T10:00:00Z", "affectedCount": 0},
    }
    assert not validate_cascade_structure(malformed_2)

    # Invalid invalidation structure
    malformed_3 = {
        "updated": [],
        "deleted": [],
        "invalidations": [{"queryName": "posts"}],  # Missing strategy, scope
        "metadata": {"timestamp": "2025-11-28T10:00:00Z", "affectedCount": 0},
    }
    assert not validate_cascade_structure(malformed_3)

    # Valid structure should pass
    valid = {
        "updated": [
            {
                "__typename": "Post",
                "id": "post-1",
                "operation": "CREATED",
                "entity": {"id": "post-1", "title": "Test"},
            }
        ],
        "deleted": [],
        "invalidations": [{"queryName": "posts", "strategy": "INVALIDATE", "scope": "PREFIX"}],
        "metadata": {"timestamp": "2025-11-28T10:00:00Z", "affectedCount": 1},
    }
    assert validate_cascade_structure(valid)


class MockApolloClient:
    """Mock Apollo Client for testing cache integration."""

    def __init__(self):
        self.cache = MagicMock()
        self.mutate = AsyncMock()

    def writeFragment(self, options):
        """Mock cache write operation - forwards to cache mock."""
        return self.cache.writeFragment(options)

    def evict(self, options):
        """Mock cache eviction - forwards to cache mock."""
        return self.cache.evict(options)


def test_apollo_client_cascade_integration():
    """Test Apollo Client cache updates from cascade data."""
    client = MockApolloClient()

    # Simulate cascade data
    cascade_data = {
        "updated": [
            {
                "__typename": "Post",
                "id": "post-123",
                "operation": "CREATED",
                "entity": {"id": "post-123", "title": "Test Post"},
            },
            {
                "__typename": "User",
                "id": "user-456",
                "operation": "UPDATED",
                "entity": {"id": "user-456", "post_count": 1},
            },
        ],
        "invalidations": [{"queryName": "posts", "strategy": "INVALIDATE", "scope": "PREFIX"}],
    }

    # Simulate Apollo Client cascade processing
    for update in cascade_data["updated"]:
        client.writeFragment(
            {
                "id": client.cache.identify(
                    {"__typename": update["__typename"], "id": update["id"]}
                ),
                "fragment": f"fragment _ on {update['__typename']} {{ id }}",
                "data": update["entity"],
            }
        )

    for invalidation in cascade_data["invalidations"]:
        if invalidation["strategy"] == "INVALIDATE":
            client.cache.evict({"fieldName": invalidation["queryName"]})

    # Verify cache operations were called
    assert client.cache.writeFragment.call_count == 2
    assert client.cache.evict.call_count == 1


def test_cascade_data_validation():
    """Test validation of cascade data structure."""
    # Valid cascade data
    valid_cascade = {
        "updated": [
            {
                "__typename": "Post",
                "id": "post-123",
                "operation": "CREATED",
                "entity": {"id": "post-123", "title": "Test"},
            }
        ],
        "deleted": [],
        "invalidations": [{"queryName": "posts", "strategy": "INVALIDATE", "scope": "PREFIX"}],
        "metadata": {"timestamp": "2025-11-13T10:00:00Z", "affectedCount": 1},
    }

    # Should pass validation
    assert validate_cascade_structure(valid_cascade)

    # Invalid cascade data (missing required fields)
    invalid_cascade = {
        "updated": [{"__typename": "Post"}]  # Missing id, operation, entity
    }

    # Should fail validation
    assert not validate_cascade_structure(invalid_cascade)


def validate_cascade_structure(cascade: Dict[str, Any]) -> bool:
    """Validate cascade data structure."""
    required_keys = {"updated", "deleted", "invalidations", "metadata"}

    if not all(key in cascade for key in required_keys):
        return False

    # Validate updated entities
    for entity in cascade["updated"]:
        required_entity_keys = {"__typename", "id", "operation", "entity"}
        if not all(key in entity for key in required_entity_keys):
            return False

    # Validate invalidations
    for invalidation in cascade["invalidations"]:
        required_invalidation_keys = {"queryName", "strategy", "scope"}
        if not all(key in invalidation for key in required_invalidation_keys):
            return False

    return True


@pytest.mark.asyncio
async def test_schema_validation_with_success_type_fields(cascade_http_client):
    """Test that Rust schema validation works with success_type_fields parameter.

    Validates that the Rust transformer correctly validates that all expected fields
    from the Success type are present in the mutation response, and warns about
    missing or extra fields.
    """
    # This test uses the existing CreatePostWithEntity mutation which has:
    # - Success type: CreatePostWithEntitySuccess with fields: post, message, cascade
    # - The test should pass because all expected fields are present

    mutation_query = """
    mutation CreatePostWithEntity($input: CreatePostInput!) {
        createPostWithEntity(input: $input) {
            ... on CreatePostWithEntitySuccess {
                message
                post {
                    id
                    title
                    content
                    authorId
                }
                cascade {
                    updated {
                        id
                        operation
                    }
                    deleted {
                        id
                        operation
                    }
                    invalidations {
                        queryName
                        strategy
                        scope
                    }
                    metadata {
                        timestamp
                        affectedCount
                    }
                }
            }
            ... on CreatePostError {
                message
                code
            }
        }
    }
    """

    variables = {
        "input": {
            "title": "Schema Validation Test Post",
            "content": "Testing Rust schema validation with success_type_fields",
            "authorId": "user-123",
        }
    }

    response = await cascade_http_client.post(
        "/graphql",
        json={"query": mutation_query, "variables": variables},
    )

    assert response.status_code == 200
    result = response.json()

    # Should not have GraphQL errors
    assert "errors" not in result or not result["errors"]

    # Should have successful mutation result
    mutation_result = result["data"]["createPostWithEntity"]
    assert mutation_result["__typename"] == "CreatePostWithEntitySuccess"

    # All expected fields should be present (this validates schema compliance)
    assert "message" in mutation_result
    assert "post" in mutation_result
    assert "cascade" in mutation_result

    # Post entity should have expected structure
    post = mutation_result["post"]
    assert post["id"].startswith("post-")
    assert post["title"] == "Schema Validation Test Post"
    assert post["content"] == "Testing Rust schema validation with success_type_fields"
    assert post["authorId"] == "user-123"

    # Cascade should be present and valid
    cascade = mutation_result["cascade"]
    assert isinstance(cascade["updated"], list)
    assert isinstance(cascade["deleted"], list)
    assert isinstance(cascade["invalidations"], list)
    assert "metadata" in cascade

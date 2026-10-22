"""Edge case tests for CASCADE selection filtering."""

import pytest

pytestmark = pytest.mark.integration


class TestCascadeEdgeCases:
    """Test edge cases and corner cases for CASCADE selection."""

    @pytest.mark.asyncio
    async def test_cascade_with_minimal_selection_set(self, cascade_http_client):
        """CASCADE field with minimal selection set."""
        mutation = """
            mutation CreatePostWithEntity($input: CreatePostInput!) {
                createPostWithEntity(input: $input) {
                    ... on CreatePostWithEntitySuccess {
                        message
                        cascade {
                            __typename
                            metadata {
                                affectedCount
                            }
                        }
                    }
                }
            }
        """

        variables = {
            "input": {"title": "Test Post", "content": "Test content", "authorId": "user-123"}
        }

        response = await cascade_http_client.post(
            "/graphql", json={"query": mutation, "variables": variables}
        )

        assert response.status_code == 200
        result = response.json()

        # Should succeed and include cascade with requested fields
        assert "errors" not in result
        response_data = result["data"]["createPostWithEntity"]

        assert "cascade" in response_data
        cascade = response_data["cascade"]

        # Selection filtering should only include requested fields
        # __typename might not be included if not explicitly requested in some cases
        assert "metadata" in cascade
        assert "affectedCount" in cascade["metadata"]
        assert cascade["metadata"]["affectedCount"] == 2

    @pytest.mark.asyncio
    async def test_cascade_field_not_in_success_type_selection(self, cascade_http_client):
        """No selection set on Success type at all."""
        mutation = """
            mutation CreatePostWithEntity($input: CreatePostInput!) {
                createPostWithEntity(input: $input) {
                    ... on CreatePostWithEntitySuccess {
                        message
                    }
                }
            }
        """

        variables = {
            "input": {
                "title": "Test Post",
                "content": "Test content",
                "authorId": "user-123",
            }
        }

        response = await cascade_http_client.post(
            "/graphql", json={"query": mutation, "variables": variables}
        )

        assert response.status_code == 200
        result = response.json()

        assert "errors" not in result
        response_data = result["data"]["createPostWithEntity"]

        assert response_data == {
            "__typename": "CreatePostWithEntitySuccess",
            "message": response_data["message"],
        }

    @pytest.mark.asyncio
    async def test_cascade_with_nested_field_selections(self, cascade_http_client):
        """CASCADE with nested field selections on cascade sub-fields."""
        mutation = """
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
                                timestamp
                            }
                        }
                    }
                }
            }
        """

        variables = {
            "input": {"title": "Test Post", "content": "Test content", "authorId": "user-123"}
        }

        response = await cascade_http_client.post(
            "/graphql", json={"query": mutation, "variables": variables}
        )

        assert response.status_code == 200
        result = response.json()

        assert "errors" not in result
        cascade = result["data"]["createPostWithEntity"]["cascade"]

        # Verify nested field selections were respected
        assert "updated" in cascade
        assert "metadata" in cascade

        # Check that nested fields are present
        for update in cascade["updated"]:
            assert "id" in update
            assert "operation" in update

        assert "affectedCount" in cascade["metadata"]
        assert "timestamp" in cascade["metadata"]

    @pytest.mark.asyncio
    async def test_mutation_without_cascade_enabled(self, cascade_http_client):
        """Mutation without enable_cascade should never return CASCADE."""
        # Use a mutation that doesn't have enable_cascade=True
        # (Assuming such a mutation exists in test schema)

        mutation = """
            mutation CreatePost($input: CreatePostInput!) {
                createPost(input: $input) {
                    ... on CreatePostSuccess {
                        id
                        message
                        # CASCADE field shouldn't even be in schema
                    }
                }
            }
        """

        variables = {
            "input": {
                "title": "Test Post",
                "content": "Test content",
                "authorId": "00000000-0000-0000-0000-000000000001",
            }
        }

        response = await cascade_http_client.post(
            "/graphql", json={"query": mutation, "variables": variables}
        )

        assert response.status_code == 200
        result = response.json()

        # Should succeed
        assert "errors" not in result
        response_data = result["data"]["createPost"]

        # CASCADE should not exist
        assert "cascade" not in response_data

    @pytest.mark.asyncio
    async def test_cascade_with_aliases(self, cascade_http_client):
        """CASCADE field with GraphQL alias."""
        mutation = """
            mutation CreatePostWithEntity($input: CreatePostInput!) {
                createPostWithEntity(input: $input) {
                    ... on CreatePostWithEntitySuccess {
                        message
                        sideEffects: cascade {
                            updated {
                                __typename
                                id
                            }
                        }
                    }
                }
            }
        """

        variables = {
            "input": {
                "title": "Test Post",
                "content": "Test content",
                "authorId": "user-123",
            }
        }

        response = await cascade_http_client.post(
            "/graphql", json={"query": mutation, "variables": variables}
        )

        assert response.status_code == 200
        result = response.json()

        assert "errors" not in result
        response_data = result["data"]["createPostWithEntity"]

        # CASCADE comes back under its alias
        assert "cascade" not in response_data
        assert response_data["sideEffects"]["updated"]

    @pytest.mark.asyncio
    async def test_cascade_selection_with_variables(self, cascade_http_client):
        """CASCADE selection with GraphQL variables and directives."""
        mutation = """
            mutation CreatePostWithEntity($input: CreatePostInput!, $includeCascade: Boolean!) {
                createPostWithEntity(input: $input) {
                    ... on CreatePostWithEntitySuccess {
                        message
                        cascade @include(if: $includeCascade) {
                            updated {
                                __typename
                                id
                            }
                        }
                    }
                }
            }
        """

        # Test with includeCascade = false
        variables = {
            "input": {
                "title": "Test Post",
                "content": "Test content",
                "authorId": "00000000-0000-0000-0000-000000000001",
            },
            "includeCascade": False,
        }

        response = await cascade_http_client.post(
            "/graphql", json={"query": mutation, "variables": variables}
        )

        assert response.status_code == 200
        result = response.json()

        assert "errors" not in result
        response_data = result["data"]["createPostWithEntity"]

        # CASCADE should not be present when @include(if: false)
        assert "cascade" not in response_data

    @pytest.mark.asyncio
    async def test_concurrent_mutations_different_cascade_selections(self, cascade_http_client):
        """Multiple concurrent mutations with different CASCADE selections."""
        import asyncio

        async def mutation_with_cascade():
            response = await cascade_http_client.post(
                "/graphql",
                json={
                    "query": """
                    mutation CreatePostWithEntity($input: CreatePostInput!) {
                        createPostWithEntity(input: $input) {
                            ... on CreatePostWithEntitySuccess {
                                message
                                cascade { updated { id } }
                            }
                        }
                    }
                    """,
                    "variables": {
                        "input": {
                            "title": "Post 1",
                            "content": "Content 1",
                            "authorId": "user-123",
                        }
                    },
                },
            )
            return response.json()

        async def mutation_without_cascade():
            response = await cascade_http_client.post(
                "/graphql",
                json={
                    "query": """
                    mutation CreatePostWithEntity($input: CreatePostInput!) {
                        createPostWithEntity(input: $input) {
                            ... on CreatePostWithEntitySuccess {
                                message
                            }
                        }
                    }
                    """,
                    "variables": {
                        "input": {
                            "title": "Post 2",
                            "content": "Content 2",
                            "authorId": "user-123",
                        }
                    },
                },
            )
            return response.json()

        # Run concurrently
        results = await asyncio.gather(mutation_with_cascade(), mutation_without_cascade())

        # First should have cascade
        assert "cascade" in results[0]["data"]["createPostWithEntity"]

        # Second should NOT have cascade
        assert "cascade" not in results[1]["data"]["createPostWithEntity"]


class TestCascadeNullHandling:
    """Test NULL and missing data handling."""

    @pytest.mark.asyncio
    async def test_cascade_when_no_side_effects(self, cascade_http_client):
        """CASCADE requested but mutation has no side effects."""
        mutation = """
            mutation UpdatePostTitle($input: CreatePostInput!) {
                updatePostTitle(input: $input) {
                    ... on UpdatePostTitleSuccess {
                        message
                        cascade {
                            updated {
                                id
                            }
                            deleted {
                                id
                            }
                            metadata {
                                affectedCount
                            }
                        }
                    }
                }
            }
        """

        variables = {
            "input": {
                "title": "Updated Title",
                "authorId": "user-123",
            }
        }

        response = await cascade_http_client.post(
            "/graphql", json={"query": mutation, "variables": variables}
        )

        assert response.status_code == 200
        result = response.json()

        assert "errors" not in result
        response_data = result["data"]["updatePostTitle"]

        # Cascade should be present with empty arrays
        assert "cascade" in response_data
        cascade = response_data["cascade"]

        # All arrays should be empty (no side effects)
        assert cascade["updated"] == []
        assert cascade["deleted"] == []
        assert cascade["metadata"]["affectedCount"] == 0

    @pytest.mark.asyncio
    async def test_cascade_with_null_fields(self, cascade_http_client):
        """CASCADE with null/missing optional fields."""
        mutation = """
            mutation CreatePostWithEntity($input: CreatePostInput!) {
                createPostWithEntity(input: $input) {
                    ... on CreatePostWithEntitySuccess {
                        message
                        cascade {
                            updated {
                                __typename
                                id
                            }
                            deleted {
                                __typename
                                id
                            }
                            invalidations {
                                queryName
                            }
                        }
                    }
                }
            }
        """

        variables = {
            "input": {
                "title": "Test Post",
                "content": "Test content",
                "authorId": "user-123",
            }
        }

        response = await cascade_http_client.post(
            "/graphql", json={"query": mutation, "variables": variables}
        )

        assert response.status_code == 200
        result = response.json()

        assert "errors" not in result
        cascade = result["data"]["createPostWithEntity"]["cascade"]

        # All requested fields should be present, even if empty
        assert "updated" in cascade
        assert "deleted" in cascade
        assert "invalidations" in cascade

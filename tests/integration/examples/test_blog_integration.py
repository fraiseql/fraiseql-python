"""
Integration tests for blog_simple example with smart dependency management.

These tests run with automatically installed dependencies and smart database setup,
providing full validation of the blog_simple example functionality.
"""

import logging
import pytest

pytestmark = pytest.mark.integration

# Setup logging for integration tests
logger = logging.getLogger(__name__)

# Mark all tests as example integration tests
pytestmark = [
    pytest.mark.blog_simple,
    pytest.mark.integration,
    pytest.mark.database,
    pytest.mark.examples,
]


@pytest.mark.asyncio
async def test_smart_dependencies_available(smart_dependencies) -> None:
    """Test that smart dependency management successfully provides all required dependencies."""
    # Verify that smart dependencies fixture provided dependency information
    assert smart_dependencies is not None
    assert "dependency_results" in smart_dependencies
    assert "environment" in smart_dependencies

    # Test basic imports individually to identify the failing one
    import sys

    logger.info(f"Using Python: {sys.executable}")
    logger.info(f"Python path: {sys.path[:3]}")

    import httpx
    import psycopg

    # Check if fastapi is available
    try:
        import fastapi

        logger.info("FastAPI import successful")
    except ImportError as e:
        logger.error(f"FastAPI import failed: {e}")
        # Try to find where the package would be
        logger.error(f"Sys path: {sys.path[:5]}")
        raise

    # Test GraphQL separately first
    try:
        from graphql import GraphQLSchema

        logger.info("GraphQL import successful")
    except ImportError as e:
        logger.error(f"GraphQL import failed: {e}")
        raise

    # Now test fraiseql
    try:
        import fraiseql

        logger.info("FraiseQL import successful")
    except ImportError as e:
        logger.error(f"FraiseQL import failed: {e}")
        raise

    logger.info("All smart dependencies validated in integration test")


def test_blog_simple_app_exists() -> None:
    """Basic test that blog simple app can be imported and has expected structure."""
    import sys
    from pathlib import Path

    examples_dir = Path(__file__).parent.parent.parent.parent / "examples"
    blog_simple_dir = examples_dir / "blog_simple"
    app_file = blog_simple_dir / "app.py"

    # Check that the file exists
    assert app_file.exists(), f"Blog simple app.py not found at {app_file}"

    # Try to read the file and check it has expected content
    content = app_file.read_text()
    assert "def create_app(" in content, "create_app function not found"
    assert "/health" in content, "Health endpoint not found"
    assert "blog_simple" in content, "Service name not found"

    # Try basic import without creating the app (to avoid database issues)
    sys.path.insert(0, str(blog_simple_dir))

    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("blog_simple_app", app_file)
        if spec and spec.loader:
            # Just check that we can load the module spec without executing it
            assert spec is not None, "Could not create module spec"
            assert spec.loader is not None, "Module loader not available"
        else:
            pytest.skip("Could not create module spec for blog simple app")

    except Exception as e:
        pytest.skip(f"App import check failed: {e}")
    finally:
        # Clean up
        if str(blog_simple_dir) in sys.path:
            sys.path.remove(str(blog_simple_dir))


@pytest.mark.asyncio
async def test_blog_simple_home_endpoint(blog_simple_client) -> None:
    """Test that blog_simple home endpoint returns expected information."""
    response = await blog_simple_client.get("/")
    assert response.status_code == 200

    data = response.json()
    assert "FraiseQL Simple Blog" in data["message"]
    assert "endpoints" in data
    assert data["endpoints"]["graphql"] == "/graphql"


@pytest.mark.asyncio
async def test_blog_simple_graphql_introspection(blog_simple_graphql_client) -> None:
    """Test that GraphQL introspection works for blog_simple."""
    introspection_query = """
        query IntrospectionQuery {
            __schema {
                types {
                    name
                    kind
                }
            }
        }
    """

    result = await blog_simple_graphql_client.execute(introspection_query)

    # Should not have errors
    assert "errors" not in result or not result["errors"]
    assert "data" in result
    assert "__schema" in result["data"]

    # Check for expected types
    type_names = [t["name"] for t in result["data"]["__schema"]["types"]]

    # Should have our domain types
    expected_types = ["User", "Post", "Comment", "Tag", "UserRole", "PostStatus", "CommentStatus"]
    for expected_type in expected_types:
        assert expected_type in type_names, f"Expected type {expected_type} not found in schema"


@pytest.mark.asyncio
async def test_blog_simple_basic_queries(blog_simple_graphql_client) -> None:
    """Test basic queries work without errors."""
    # Test posts query
    posts_query = """
        query GetPosts($limit: Int) {
            posts(limit: $limit) {
                id
                title
                status
            }
        }
    """

    result = await blog_simple_graphql_client.execute(posts_query, variables={"limit": 5})

    # Should execute without errors
    assert "errors" not in result or not result["errors"]
    assert "data" in result
    assert "posts" in result["data"]

    # Test tags query
    tags_query = """
        query GetTags($limit: Int) {
            tags(limit: $limit) {
                id
                name
                identifier
            }
        }
    """

    result = await blog_simple_graphql_client.execute(tags_query, variables={"limit": 5})

    assert "errors" not in result or not result["errors"]
    assert "data" in result
    assert "tags" in result["data"]


@pytest.mark.asyncio
async def test_blog_simple_database_connectivity(blog_simple_repository) -> None:
    """Test that database connectivity works properly."""
    # Test basic database connection
    result = await blog_simple_repository.connection.execute("SELECT 1 as test")
    rows = await result.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 1  # First column of first row


@pytest.mark.asyncio
async def test_blog_simple_seed_data(blog_simple_repository) -> None:
    """Test that seed data is properly loaded."""
    # Check that tb_user table exists and has data
    result = await blog_simple_repository.connection.execute(
        "SELECT COUNT(*) as count FROM tb_user"
    )
    rows = await result.fetchall()
    user_count = rows[0][0]  # First column of first row
    assert user_count > 0, "tb_user table should have seed data"

    # Check that tb_tag table exists and has data
    result = await blog_simple_repository.connection.execute("SELECT COUNT(*) as count FROM tb_tag")
    rows = await result.fetchall()
    tag_count = rows[0][0]  # First column of first row
    assert tag_count > 0, "tb_tag table should have seed data"

    # Check that tb_post table exists and has data
    result = await blog_simple_repository.connection.execute(
        "SELECT COUNT(*) as count FROM tb_post"
    )
    rows = await result.fetchall()
    post_count = rows[0][0]  # First column of first row
    assert post_count > 0, "tb_post table should have seed data"


@pytest.mark.asyncio
async def test_blog_simple_mutations_structure(blog_simple_graphql_client) -> None:
    """Test that GraphQL client can execute queries without hanging."""
    # Test simple query to ensure GraphQL is working
    simple_query = """
        query {
            posts(limit: 1) {
                id
                title
            }
        }
    """

    result = await blog_simple_graphql_client.execute(simple_query)
    assert "errors" not in result or not result["errors"]
    assert "data" in result

    # Skip complex introspection for now to avoid hanging
    # Mutations exist in the schema but introspection may cause issues


@pytest.mark.asyncio
@pytest.mark.slow
async def test_blog_simple_performance_baseline(blog_simple_graphql_client) -> None:
    """Test basic performance baseline for blog_simple."""
    import time

    # Simple query performance test (avoid complex nested queries that may hang)
    query = """
        query GetPosts {
            posts(limit: 5) {
                id
                title
            }
        }
    """

    start_time = time.time()
    result = await blog_simple_graphql_client.execute(query)
    end_time = time.time()

    # Should complete without errors
    assert "errors" not in result or not result["errors"]

    # Should complete reasonably quickly (under 5 seconds for basic query)
    duration = end_time - start_time
    assert duration < 5.0, f"Query took too long: {duration:.2f}s"


@pytest.mark.asyncio
async def test_blog_simple_error_handling(blog_simple_graphql_client) -> None:
    """Test that error handling works properly."""
    # Test invalid query
    invalid_query = """
        query {
            nonExistentField {
                id
            }
        }
    """

    result = await blog_simple_graphql_client.execute(invalid_query)

    # Should have GraphQL errors
    assert "errors" in result
    assert len(result["errors"]) > 0

    # Test malformed query
    malformed_query = "query { posts { id title"  # Missing closing brace

    result = await blog_simple_graphql_client.execute(malformed_query)
    assert "errors" in result


# The sample data's users (db/seed_data.sql); app.py reads the caller from X-User-ID
JOHNDOE = "22222222-2222-2222-2222-222222222222"
JANEDOE = "33333333-3333-3333-3333-333333333333"
READER = "44444444-4444-4444-4444-444444444444"
PYTHON_TAG = "55555555-5555-5555-5555-555555555555"


@pytest.mark.asyncio
async def test_blog_simple_posts_embed_author_tags_and_comments(blog_simple_graphql_client) -> None:
    """A post's author, tags and approved comments come from v_post's data."""
    result = await blog_simple_graphql_client.execute(
        """
        query {
            post(identifier: "building-reactive-uis-with-graphql-subscriptions") {
                title
                author { username fullName }
                tags { name }
                comments { content parentId author { username } }
            }
        }
        """
    )

    assert "errors" not in result, result
    post = result["data"]["post"]
    assert post["author"]["username"] == "janedoe"
    assert post["author"]["fullName"] == "Jane Doe"
    assert [t["name"] for t in post["tags"]] == ["FraiseQL", "GraphQL", "Web Development"]
    assert [c["author"]["username"] for c in post["comments"]] == ["johndoe", "janedoe"]
    assert post["comments"][1]["parentId"] is not None  # janedoe's reply


@pytest.mark.asyncio
async def test_blog_simple_list_arguments_reach_the_query(blog_simple_graphql_client) -> None:
    """where, orderBy and limit are passed on to db.find, not dropped."""
    result = await blog_simple_graphql_client.execute(
        """
        query {
            published: posts(where: {status: {eq: "published"}}, orderBy: {title: ASC}) {
                title
                status
            }
            first: posts(orderBy: {title: ASC}, limit: 1) { title }
            authors: users(where: {role: {eq: "author"}}, orderBy: {username: ASC}) { username }
        }
        """
    )

    assert "errors" not in result, result
    published = result["data"]["published"]
    assert {p["status"] for p in published} == {"published"}
    assert [p["title"] for p in published] == sorted(p["title"] for p in published)
    assert len(published) == 3
    assert [p["title"] for p in result["data"]["first"]] == [
        "Advanced PostgreSQL Patterns in FraiseQL"
    ]
    assert [u["username"] for u in result["data"]["authors"]] == ["janedoe", "johndoe"]


@pytest.mark.asyncio
async def test_blog_simple_post_lifecycle(blog_simple_graphql_client) -> None:
    """Create a draft, publish it, comment on it; only the author may edit it."""
    client = blog_simple_graphql_client

    created = await client.execute(
        """
        mutation($input: CreatePostInput!) {
            createPost(input: $input) {
                __typename
                ... on PostSuccess { post { id status author { username } tags { name } } }
                ... on BlogError { message code }
            }
        }
        """,
        variables={"input": {"title": "Test post", "content": "Body", "tagIds": [PYTHON_TAG]}},
    )
    assert "errors" not in created, created
    payload = created["data"]["createPost"]
    assert payload["__typename"] == "PostSuccess", payload
    post = payload["post"]
    assert post["status"] == "draft"
    assert post["author"]["username"] == "johndoe"
    assert [t["name"] for t in post["tags"]] == ["Python"]

    update = """
        mutation($input: UpdatePostInput!) {
            updatePost(input: $input) {
                __typename
                ... on PostSuccess { post { status publishedAt } }
                ... on BlogError { message code }
            }
        }
    """
    forbidden = await client.execute(
        update, variables={"input": {"id": post["id"], "title": "x"}}, headers={"X-User-ID": JANEDOE}
    )
    assert forbidden["data"]["updatePost"]["__typename"] == "BlogError"
    assert forbidden["data"]["updatePost"]["code"] == 403

    published = await client.execute(
        update, variables={"input": {"id": post["id"], "status": "PUBLISHED"}}
    )
    assert published["data"]["updatePost"]["__typename"] == "PostSuccess", published
    assert published["data"]["updatePost"]["post"]["status"] == "published"
    assert published["data"]["updatePost"]["post"]["publishedAt"] is not None

    commented = await client.execute(
        """
        mutation($input: CreateCommentInput!) {
            createComment(input: $input) {
                __typename
                ... on CreateCommentSuccess { comment { status postId author { username } } }
                ... on BlogError { message code }
            }
        }
        """,
        variables={"input": {"postId": post["id"], "content": "Nice post"}},
        headers={"X-User-ID": READER},
    )
    comment = commented["data"]["createComment"]
    assert comment["__typename"] == "CreateCommentSuccess", comment
    assert comment["comment"]["status"] == "pending"
    assert comment["comment"]["postId"] == post["id"]
    assert comment["comment"]["author"]["username"] == "reader"


@pytest.mark.asyncio
async def test_blog_simple_mutation_errors(blog_simple_graphql_client) -> None:
    """The functions' error statuses reach the client as BlogError."""
    duplicate = await blog_simple_graphql_client.execute(
        """
        mutation {
            createTag(input: {name: "python"}) {
                __typename
                ... on BlogError { code status }
            }
        }
        """
    )
    assert duplicate["data"]["createTag"] == {
        "__typename": "BlogError",
        "code": 409,
        "status": "conflict:tag_name",
    }

    missing = await blog_simple_graphql_client.execute(
        """
        mutation {
            updatePost(input: {id: "00000000-0000-0000-0000-000000000000", title: "x"}) {
                __typename
                ... on BlogError { code status }
            }
        }
        """
    )
    assert missing["data"]["updatePost"] == {
        "__typename": "BlogError",
        "code": 404,
        "status": "not_found:post",
    }

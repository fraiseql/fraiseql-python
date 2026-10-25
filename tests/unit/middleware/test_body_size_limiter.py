"""Tests for request body size limiting middleware."""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.gql.schema_builder import SchemaRegistry
from fraiseql.middleware.body_size_limiter import (
    BodySizeConfig,
    BodySizeLimiterMiddleware,
    RequestTooLargeError,
)


class TestBodySizeConfig:
    """Tests for BodySizeConfig."""

    def test_default_max_size_is_1mb(self):
        """Default max body size should be 1MB."""
        config = BodySizeConfig()
        assert config.max_body_size == 1_048_576  # 1MB in bytes

    def test_custom_max_size(self):
        """Custom max body size should be respected."""
        config = BodySizeConfig(max_body_size=500_000)
        assert config.max_body_size == 500_000

    def test_exempt_paths_default_empty(self):
        """Exempt paths should default to empty list."""
        config = BodySizeConfig()
        assert config.exempt_paths == []

    def test_human_readable_size_mb(self):
        """Should provide human-readable size string for MB."""
        config = BodySizeConfig(max_body_size=1_048_576)
        assert config.human_readable_size == "1.0 MB"

    def test_human_readable_size_kb(self):
        """Should provide human-readable size string for KB."""
        config = BodySizeConfig(max_body_size=512_000)
        # 512000 / 1024 = 500.0
        assert config.human_readable_size == "500.0 KB"


class TestBodySizeLimiterMiddleware:
    """Tests for BodySizeLimiterMiddleware."""

    @pytest.fixture
    def app_with_middleware(self):
        """Create FastAPI app with body size limiter."""
        app = FastAPI()
        config = BodySizeConfig(max_body_size=1000)  # 1KB for testing
        app.add_middleware(BodySizeLimiterMiddleware, config=config)

        @app.post("/graphql")
        async def graphql_endpoint():
            return {"status": "ok"}

        @app.get("/health")
        async def health():
            return {"status": "healthy"}

        return app

    @pytest.fixture
    def client(self, app_with_middleware):
        """Create test client."""
        return TestClient(app_with_middleware)

    def test_allows_small_request(self, client):
        """Requests under limit should succeed."""
        response = client.post(
            "/graphql",
            json={"query": "{ users { id } }"},
        )
        assert response.status_code == 200

    def test_rejects_large_request(self, client):
        """Requests over limit should be rejected with 413."""
        large_query = "x" * 2000  # 2KB, over 1KB limit
        response = client.post(
            "/graphql",
            json={"query": large_query},
        )
        assert response.status_code == 413
        assert "Request body too large" in response.json()["detail"]

    def test_get_requests_not_limited(self, client):
        """GET requests should not be size-limited."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_exempt_paths_not_limited(self):
        """Exempt paths should bypass size limit."""
        app = FastAPI()
        config = BodySizeConfig(
            max_body_size=100,
            exempt_paths=["/upload"],
        )
        app.add_middleware(BodySizeLimiterMiddleware, config=config)

        @app.post("/upload")
        async def upload():
            return {"status": "ok"}

        client = TestClient(app)
        response = client.post("/upload", content=b"x" * 200)
        assert response.status_code == 200

    def test_content_length_header_checked_first(self, client):
        """Should reject based on Content-Length header before reading body."""
        response = client.post(
            "/graphql",
            content=b"x" * 100,
            headers={"Content-Length": "999999"},
        )
        assert response.status_code == 413

    def test_rejects_chunked_transfer_over_limit(self):
        """Should reject chunked requests that exceed limit (no Content-Length)."""
        app = FastAPI()
        config = BodySizeConfig(max_body_size=100)
        app.add_middleware(BodySizeLimiterMiddleware, config=config)

        @app.post("/graphql")
        async def graphql_endpoint():
            return {"status": "ok"}

        client = TestClient(app)
        # Chunked transfer - no Content-Length header
        response = client.post(
            "/graphql",
            content=b"x" * 200,  # Over 100 byte limit
            headers={"Transfer-Encoding": "chunked"},
        )
        assert response.status_code == 413

    def test_streaming_body_cutoff(self):
        """Should stop reading body once limit exceeded (DoS protection)."""
        app = FastAPI()
        config = BodySizeConfig(max_body_size=1000)
        app.add_middleware(BodySizeLimiterMiddleware, config=config)

        @app.post("/graphql")
        async def graphql_endpoint():
            return {"status": "ok"}

        client = TestClient(app)
        # Send much larger body - should be cut off early
        response = client.post("/graphql", content=b"x" * 10000)
        assert response.status_code == 413


class TestRequestTooLargeError:
    """Tests for RequestTooLargeError exception."""

    def test_error_message_includes_limit(self):
        """Error message should include the limit."""
        error = RequestTooLargeError(
            max_size=1_000_000,
            actual_size=2_000_000,
        )
        # 1,000,000 bytes is approximately 976.6 KB
        assert "976.6 KB" in str(error) or "1000000" in str(error)

    def test_error_has_status_code_413(self):
        """Error should have HTTP 413 status code."""
        error = RequestTooLargeError(max_size=1000, actual_size=2000)
        assert error.status_code == 413


class TestBodyReachesTheApp:
    """The limiter passes the request body on, intact, to the app behind it."""

    @pytest.fixture
    def client(self):
        """Client for an app whose endpoint returns the body it received."""
        app = FastAPI()
        app.add_middleware(BodySizeLimiterMiddleware, config=BodySizeConfig(max_body_size=100))

        @app.post("/echo")
        async def echo(request: Request):
            return {"body": (await request.body()).decode()}

        return TestClient(app)

    def test_body_under_limit_reaches_endpoint(self, client):
        response = client.post("/echo", content=b'{"query": "{ hello }"}')
        assert response.status_code == 200
        assert response.json() == {"body": '{"query": "{ hello }"}'}

    def test_body_at_limit_reaches_endpoint(self, client):
        response = client.post("/echo", content=b"x" * 100)
        assert response.status_code == 200
        assert response.json() == {"body": "x" * 100}

    def test_streamed_body_under_limit_reaches_endpoint(self, client):
        def chunks():
            yield b"abc"
            yield b"def"

        response = client.post("/echo", content=chunks())
        assert response.status_code == 200
        assert response.json() == {"body": "abcdef"}

    def test_streamed_body_over_limit_without_content_length_is_413(self, client):
        def chunks():
            yield b"x" * 60
            yield b"x" * 60

        response = client.post("/echo", content=chunks())
        assert response.status_code == 413
        assert response.json()["max_size"] == 100

    def test_content_length_over_limit_is_413(self, client):
        response = client.post("/echo", content=b"x" * 101)
        assert response.status_code == 413


class TestGraphQLThroughLimiter:
    """A GraphQL POST through the limiter, on a FraiseQL app."""

    @pytest.fixture
    def client(self):
        SchemaRegistry.get_instance().clear()

        @fraiseql.query
        async def greeting(info, name: str) -> str:
            return f"hello {name}"

        app = create_fraiseql_app(
            database_url="postgresql://localhost/unused",
            queries=[greeting],
            production=False,
        )
        app.add_middleware(BodySizeLimiterMiddleware, config=BodySizeConfig(max_body_size=500))
        with TestClient(app) as client:
            yield client
        SchemaRegistry.get_instance().clear()

    def test_graphql_post_succeeds(self, client):
        response = client.post(
            "/graphql",
            json={"query": "query($n: String!) { greeting(name: $n) }", "variables": {"n": "bob"}},
        )
        assert response.status_code == 200
        assert response.json()["data"] == {"greeting": "hello bob"}

    def test_oversize_graphql_post_is_413(self, client):
        query = '{ greeting(name: "' + "x" * 600 + '") }'
        response = client.post("/graphql", json={"query": query})
        assert response.status_code == 413

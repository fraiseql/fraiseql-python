"""Test custom lifespan support."""

from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.fastapi import create_fraiseql_app

pytestmark = pytest.mark.integration

# Track lifecycle events
lifecycle_events = []


# Sample type and query


@pytest.mark.unit
@fraiseql.type
class Status:
    message: str
    custom_resource: str | None = None


async def get_status(info) -> Status:
    """Get application status."""
    # Check if custom resource was set in context
    custom_resource = getattr(info.context.get("app", {}), "state", {}).get("custom_resource")
    return Status(message="Running", custom_resource=custom_resource)


@pytest.fixture(autouse=True)
def reset_events(clear_registry) -> None:
    """Reset lifecycle events and the schema registry before each test.

    Collecting other test modules in the same process runs their module-level
    @fraiseql.query decorators, which register into the process-wide schema
    registry; the apps built here pass their types and queries explicitly.
    """
    global lifecycle_events
    lifecycle_events = []
    yield
    lifecycle_events = []


def test_default_lifespan() -> None:
    """Test that default lifespan works without custom lifespan."""
    app = create_fraiseql_app(
        database_url="postgresql://localhost/test",
        types=[Status],
        queries=[get_status],
        production=False,
    )

    # The app should work with default lifespan
    with TestClient(app) as client:
        response = client.post("/graphql", json={"query": "{ getStatus { message } }"})
        assert response.status_code == 200
        assert response.json()["data"]["getStatus"]["message"] == "Running"


def test_custom_lifespan() -> None:
    """Test that custom lifespan is called and integrated."""

    @asynccontextmanager
    async def custom_lifespan(app: FastAPI) -> None:
        """Custom lifespan that sets up additional resources."""
        # Startup
        lifecycle_events.append("custom_startup")

        # Set custom resource in app state
        app.state.custom_resource = "MyCustomResource"

        # Also set up a fake external connection
        fake_connection = {"connected": True}
        app.state.external_connection = fake_connection

        yield

        # Shutdown
        lifecycle_events.append("custom_shutdown")

        # Clean up fake connection
        fake_connection["connected"] = False

    app = create_fraiseql_app(
        database_url="postgresql://localhost/test",
        types=[Status],
        queries=[get_status],
        lifespan=custom_lifespan,
        production=False,
    )

    # Test that custom lifespan runs
    with TestClient(app) as client:
        # Verify startup was called
        assert "custom_startup" in lifecycle_events

        # Verify custom resource is accessible
        assert hasattr(app.state, "custom_resource")
        assert app.state.custom_resource == "MyCustomResource"

        # Verify external connection was set up
        assert hasattr(app.state, "external_connection")
        assert app.state.external_connection["connected"] is True

        # Make a request
        response = client.post(
            "/graphql", json={"query": "{ getStatus { message customResource } }"}
        )
        assert response.status_code == 200

        # Note: custom_resource won't be visible in GraphQL context
        # because it's in app.state, not in the GraphQL context
        data = response.json()["data"]["getStatus"]
        assert data["message"] == "Running"

    # Verify shutdown was called
    assert "custom_shutdown" in lifecycle_events


def test_custom_lifespan_with_context_getter() -> None:
    """Test custom lifespan combined with custom context getter."""

    @asynccontextmanager
    async def custom_lifespan(app: FastAPI) -> None:
        """Custom lifespan that sets up resources."""
        app.state.shared_data = {"initialized": True, "count": 0}
        yield
        app.state.shared_data = None

    async def custom_context_getter(request) -> dict[str, Any]:
        """Custom context that includes app state."""
        app = request.app
        return {
            "db": None,  # Would be real DB in production
            "user": None,
            "app": app,  # Include app to access state
            "shared_data": getattr(app.state, "shared_data", None),
        }

    app = create_fraiseql_app(
        database_url="postgresql://localhost/test",
        types=[Status],
        queries=[get_status],
        lifespan=custom_lifespan,
        context_getter=custom_context_getter,
        production=False,
    )

    with TestClient(app) as client:
        # Verify shared data is available
        assert app.state.shared_data == {"initialized": True, "count": 0}

        # Make request - the context getter should provide access to shared data
        response = client.post("/graphql", json={"query": "{ getStatus { message } }"})
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_lifespan_error_handling() -> None:
    """Test that errors in custom lifespan are handled properly using ASGI LifespanManager."""

    @asynccontextmanager
    async def failing_lifespan(app: FastAPI) -> None:
        """Lifespan that fails during startup."""
        lifecycle_events.append("failing_startup")
        msg = "Startup failed!"
        raise RuntimeError(msg)
        yield  # Never reached

    # Create app with failing lifespan
    app = create_fraiseql_app(
        database_url="postgresql://localhost/test",
        types=[Status],
        queries=[get_status],
        lifespan=failing_lifespan,
        production=False,
    )

    # Use ASGI LifespanManager to properly handle lifespan errors
    from asgi_lifespan import LifespanManager

    # This should raise an error during lifespan startup
    with pytest.raises(RuntimeError, match="Startup failed!"):
        async with LifespanManager(app):
            pass  # Should not reach here

    # Verify startup was attempted
    assert "failing_startup" in lifecycle_events

    # Explicit cleanup for CI/Tox environments to prevent async teardown hangs
    # Close any database pool that may have been created before the lifespan failure
    import asyncio

    from fraiseql.fastapi.dependencies import get_db_pool

    try:
        pool = get_db_pool()
        if pool:
            await pool.close()
            # Give time for pool cleanup to complete
            await asyncio.sleep(0.1)
    except RuntimeError:
        # No pool was set, which is fine
        pass


def test_lifespan_with_existing_app() -> None:
    """Test that custom lifespan works when extending existing app."""

    @asynccontextmanager
    async def existing_app_lifespan(app: FastAPI) -> None:
        """Lifespan for existing app."""
        app.state.from_existing = True
        yield
        app.state.from_existing = False

    # Create existing app with its own lifespan
    existing_app = FastAPI(lifespan=existing_app_lifespan)

    # Extend it with FraiseQL
    app = create_fraiseql_app(
        database_url="postgresql://localhost/test",
        types=[Status],
        queries=[get_status],
        app=existing_app,
        production=False,
    )

    # Should use the existing app's lifespan
    with TestClient(app) as client:
        assert app.state.from_existing is True

        response = client.post("/graphql", json={"query": "{ getStatus { message } }"})
        assert response.status_code == 200


def test_existing_app_gets_a_database_pool(clear_registry) -> None:
    """An app passed in opens fraiseql's pool and still runs its own startup once.

    clear_registry also unsets the pool an earlier test's app left behind, which
    used to hide that an app passed in never opened one.
    """
    from fraiseql.fastapi.dependencies import get_db_pool

    existing_app = FastAPI()

    @existing_app.on_event("startup")
    async def on_startup() -> None:
        lifecycle_events.append("existing_startup")

    app = create_fraiseql_app(
        database_url="postgresql://localhost/test",
        types=[Status],
        queries=[get_status],
        app=existing_app,
        production=False,
    )

    with pytest.raises(RuntimeError, match="Database pool not initialized"):
        get_db_pool()

    with TestClient(app):
        assert get_db_pool() is not None
        assert lifecycle_events == ["existing_startup"]

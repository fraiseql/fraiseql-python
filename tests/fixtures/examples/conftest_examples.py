"""
Shared fixtures for FraiseQL examples integration testing.

These fixtures provide intelligent dependency management and database setup
for example integration tests, with automatic installation and smart caching.
"""

import asyncio
import atexit
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import AsyncGenerator, Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

# Import smart management systems
from .dependency_manager import (
    SmartDependencyManager,
    get_dependency_manager,
    get_example_dependencies,
    InstallResult,
)
from .database_manager import ExampleDatabaseManager, get_database_manager
from .environment_detector import get_environment_detector, get_environment_config, Environment

# Setup logging for smart fixtures
logger = logging.getLogger(__name__)

# Add examples directory to Python path for imports
EXAMPLES_DIR = Path(__file__).parent.parent.parent.parent / "examples"
# Note: We don't add examples to sys.path globally to avoid contamination
# Each fixture will manage its own path isolation

# Conditional imports that will be available after smart dependencies
try:
    import psycopg
    from fraiseql.cqrs import CQRSRepository
    from httpx import AsyncClient

    DEPENDENCIES_AVAILABLE = True
except ImportError:
    # Will be installed by smart_dependencies fixture
    DEPENDENCIES_AVAILABLE = False
    psycopg = None
    CQRSRepository = None
    AsyncClient = None


def _cleanup_test_databases() -> None:
    """Clean up orphaned test databases at session end."""
    try:
        env = os.environ.copy()
        env["PGPASSWORD"] = "fraiseql"

        # Get list of test databases
        result = subprocess.run(
            ["psql", "-h", "localhost", "-U", "fraiseql", "-d", "postgres", "-t", "-c",
             "SELECT datname FROM pg_database WHERE datname LIKE 'blog%_test_%';"],
            capture_output=True, text=True, env=env, timeout=10
        )

        if result.returncode != 0:
            return

        databases = [db.strip() for db in result.stdout.strip().split("\n") if db.strip()]

        for db in databases:
            subprocess.run(
                ["psql", "-h", "localhost", "-U", "fraiseql", "-d", "postgres", "-c",
                 f"DROP DATABASE IF EXISTS {db};"],
                capture_output=True, env=env, timeout=5
            )

        if databases:
            logger.info(f"Cleaned up {len(databases)} orphaned test databases")
    except Exception as e:
        logger.debug(f"Database cleanup failed (non-fatal): {e}")


# Register cleanup at interpreter exit
atexit.register(_cleanup_test_databases)


def _reset_fraiseql_global_state() -> None:
    """Reset all FraiseQL global state to prevent test pollution."""
    try:
        # 1. Reset Rust schema registry FIRST (critical - prevents RwLock deadlock)
        try:
            from fraiseql._fraiseql_rs import reset_schema_registry_for_testing

            reset_schema_registry_for_testing()
            logger.debug("Rust schema registry reset")
        except ImportError:
            logger.debug("Rust extension not available, skipping Rust registry reset")

        # 2. Reset Python SchemaRegistry singleton
        from fraiseql.gql.builders.registry import SchemaRegistry

        registry = SchemaRegistry.get_instance()
        registry.clear()

        # 3. Reset TypeRegistry singleton
        from fraiseql.core.registry import TypeRegistry

        type_registry = TypeRegistry()
        type_registry.clear()

        # 4. Reset global FastAPI dependencies
        from fraiseql.fastapi.dependencies import set_auth_provider, set_db_pool, set_fraiseql_config

        set_db_pool(None)
        set_auth_provider(None)
        set_fraiseql_config(None)

        # 5. Reset view type registry (maps SQL views to Python types)
        from fraiseql.db import _view_type_registry

        _view_type_registry.clear()

        logger.debug("FraiseQL global state reset successfully")
    except Exception as e:
        logger.warning(f"Error resetting FraiseQL state: {e}")


@pytest.fixture
def reset_fraiseql_state():
    """Reset FraiseQL global state before and after a test.

    Use this fixture explicitly on tests that create FraiseQL apps to prevent
    pollution from singleton registries. Not autouse to avoid overhead on
    tests that don't need it.
    """
    _reset_fraiseql_global_state()  # Before test
    yield
    _reset_fraiseql_global_state()  # After test


@pytest.fixture(scope="module")
def reset_fraiseql_state_module():
    """Reset FraiseQL global state once per test module.

    More efficient than per-test reset when tests within a module use
    compatible schemas.
    """
    _reset_fraiseql_global_state()  # Before module
    yield
    _reset_fraiseql_global_state()  # After module


@pytest.fixture(scope="session")
def smart_dependencies() -> None:
    """Ensure all required dependencies are available for example tests."""
    # Skip complex dependency management - assume dependencies are available when running via uv
    # This assumes the tests are being run in the proper environment
    logger.info("Assuming example dependencies are available")
    return {
        "dependency_results": {
            "fraiseql": "available",
            "httpx": "available",
            "psycopg": "available",
            "fastapi": "available",
        },
        "environment": "local",
        "performance_profile": "development",
    }


@pytest_asyncio.fixture(scope="function", loop_scope="function")
async def blog_simple_db_url(smart_dependencies) -> AsyncGenerator[str, None]:
    """Setup blog_simple test database using smart database manager."""
    db_manager = get_database_manager()

    try:
        success, result = await db_manager.ensure_test_database("blog_simple")
        if not success:
            pytest.skip(f"Blog simple database setup failed: {result}")
        yield result
    except Exception as e:
        logger.warning(f"Blog simple database setup failed: {e}")
        pytest.skip(f"Blog simple database setup failed: {e}")
    # Note: We don't clean up test databases here as it can hang if other tests
    # have open connections. Test databases are unique (UUID suffix) and ephemeral.


@pytest_asyncio.fixture
async def blog_simple_db_connection(blog_simple_db_url) -> None:
    """Provide database connection for blog_simple tests."""
    try:
        import psycopg

        conn = await psycopg.AsyncConnection.connect(blog_simple_db_url)
        yield conn
        await conn.close()
    except Exception as e:
        pytest.skip(f"Database connection failed: {e}")


@pytest_asyncio.fixture
async def blog_simple_repository(blog_simple_db_connection) -> None:
    """Provide CQRS repository for blog_simple tests."""
    from fraiseql.cqrs import CQRSRepository

    repo = CQRSRepository(blog_simple_db_connection)
    yield repo


@pytest_asyncio.fixture
async def blog_simple_context(blog_simple_repository) -> dict[str, Any]:
    """Provide test context for blog_simple."""
    return {
        "db": blog_simple_repository,
        "user_id": UUID("22222222-2222-2222-2222-222222222222"),  # johndoe from seed data
        "tenant_id": UUID("11111111-1111-1111-1111-111111111111"),  # test tenant
        "organization_id": UUID("11111111-1111-1111-1111-111111111111"),
    }


@pytest_asyncio.fixture(scope="function", loop_scope="function")
async def blog_simple_app(smart_dependencies, blog_simple_db_url, monkeypatch) -> AsyncGenerator[Any, None]:
    """Create blog_simple app for testing with guaranteed dependencies."""
    import sys
    import importlib.util
    from urllib.parse import urlparse

    # Reset all FraiseQL state before creating app to ensure isolation
    _reset_fraiseql_global_state()

    blog_simple_dir = EXAMPLES_DIR / "blog_simple"
    app_file = blog_simple_dir / "app.py"

    # Parse the test database URL and set individual env vars
    # The example uses DB_NAME, DB_USER, etc. not DATABASE_URL
    # monkeypatch, not a bare assignment: these restore when the fixture ends.
    # A bare os.environ[...] leaked DATABASE_URL into every later test in a full
    # run, and `fraiseql query-stats` reads it as its --database-url default, so
    # a unit test written to prove nothing was configured reached a real server
    # instead (#470).
    parsed = urlparse(blog_simple_db_url)
    monkeypatch.setenv("DATABASE_URL", blog_simple_db_url)
    monkeypatch.setenv("DB_NAME", parsed.path.lstrip("/"))
    monkeypatch.setenv("DB_USER", parsed.username or "fraiseql")
    monkeypatch.setenv("DB_PASSWORD", parsed.password or "fraiseql")
    monkeypatch.setenv("DB_HOST", parsed.hostname or "localhost")
    monkeypatch.setenv("DB_PORT", str(parsed.port or 5432))

    try:
        # Force fresh module load using importlib (bypass Python cache)
        spec = importlib.util.spec_from_file_location(
            "blog_simple_app_module", app_file, submodule_search_locations=[str(blog_simple_dir)]
        )
        if spec is None or spec.loader is None:
            pytest.skip(f"Could not load app module from {app_file}")

        # Add directory to path for imports within the module
        sys.path.insert(0, str(blog_simple_dir))

        module = importlib.util.module_from_spec(spec)
        sys.modules["app"] = module  # Register so internal imports work
        spec.loader.exec_module(module)

        # Create app
        app = module.create_app()
        yield app

    except Exception as e:
        logger.warning(f"Blog simple app creation failed: {e}")
        pytest.skip(f"Blog simple app creation failed: {e}")
    finally:
        # Clean up
        if str(blog_simple_dir) in sys.path:
            sys.path.remove(str(blog_simple_dir))
        if "app" in sys.modules:
            del sys.modules["app"]
        # Clear any cached modules from the example
        modules_to_remove = [k for k in sys.modules.keys() if "blog_simple" in k.lower()]
        for mod in modules_to_remove:
            del sys.modules[mod]


@pytest_asyncio.fixture(scope="function", loop_scope="function")
async def blog_simple_client(blog_simple_app, blog_simple_db_url) -> AsyncGenerator[Any, None]:
    """HTTP client for blog_simple app with guaranteed dependencies."""
    import asyncio
    from httpx import AsyncClient, ASGITransport
    import psycopg_pool

    # Create and set pool manually to ensure database pool is initialized
    pool = psycopg_pool.AsyncConnectionPool(blog_simple_db_url)
    await pool.open()

    try:
        from fraiseql.fastapi.dependencies import set_db_pool

        set_db_pool(pool)

        transport = ASGITransport(app=blog_simple_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        from fraiseql.fastapi.dependencies import set_db_pool

        set_db_pool(None)

        # Close pool with short timeout - we don't need graceful shutdown in tests
        try:
            await asyncio.wait_for(pool.close(), timeout=2.0)
        except asyncio.TimeoutError:
            logger.debug("Pool close timed out, continuing")


@pytest_asyncio.fixture(scope="function", loop_scope="function")
async def blog_simple_graphql_client(blog_simple_client) -> None:
    """GraphQL client for blog_simple. Function-scoped for fresh state."""

    class GraphQLClient:
        def __init__(self, http_client: AsyncClient) -> None:
            self.client = http_client

        async def execute(self, query: str, variables: dict[str, Any] = None) -> dict[str, Any]:
            """Execute GraphQL query/mutation."""
            response = await self.client.post(
                "/graphql", json={"query": query, "variables": variables or {}}
            )
            return response.json()

    yield GraphQLClient(blog_simple_client)


@pytest_asyncio.fixture(scope="function", loop_scope="function")
async def blog_enterprise_db_url(smart_dependencies) -> AsyncGenerator[str, None]:
    """Setup blog_enterprise test database using smart database manager."""
    db_manager = get_database_manager()

    try:
        success, result = await db_manager.ensure_test_database("blog_enterprise")
        if not success:
            pytest.skip(f"Blog enterprise database setup failed: {result}")
        yield result
    except Exception as e:
        logger.warning(f"Blog enterprise database setup failed: {e}")
        pytest.skip(f"Blog enterprise database setup failed: {e}")
    # Note: We don't clean up test databases here as it can hang if other tests
    # have open connections. Test databases are unique (UUID suffix) and ephemeral.


@pytest_asyncio.fixture(scope="function", loop_scope="function")
async def blog_enterprise_app(
    smart_dependencies, blog_enterprise_db_url, monkeypatch
) -> AsyncGenerator[Any, None]:
    """Create blog_enterprise app for testing with guaranteed dependencies."""
    import sys
    import importlib.util
    from urllib.parse import urlparse

    # Reset all FraiseQL state before creating app to ensure isolation
    _reset_fraiseql_global_state()

    blog_enterprise_dir = EXAMPLES_DIR / "blog_enterprise"
    app_file = blog_enterprise_dir / "app.py"

    # Parse the test database URL and set individual env vars
    # The example uses DB_NAME, DB_USER, etc. not DATABASE_URL
    # monkeypatch, not a bare assignment: these restore when the fixture ends.
    # A bare os.environ[...] leaked DATABASE_URL into every later test in a full
    # run, and `fraiseql query-stats` reads it as its --database-url default, so
    # a unit test written to prove nothing was configured reached a real server
    # instead (#470).
    parsed = urlparse(blog_enterprise_db_url)
    monkeypatch.setenv("DATABASE_URL", blog_enterprise_db_url)
    monkeypatch.setenv("DB_NAME", parsed.path.lstrip("/"))
    monkeypatch.setenv("DB_USER", parsed.username or "fraiseql")
    monkeypatch.setenv("DB_PASSWORD", parsed.password or "fraiseql")
    monkeypatch.setenv("DB_HOST", parsed.hostname or "localhost")
    monkeypatch.setenv("DB_PORT", str(parsed.port or 5432))

    try:
        # Force fresh module load using importlib (bypass Python cache)
        spec = importlib.util.spec_from_file_location(
            "blog_enterprise_app_module",
            app_file,
            submodule_search_locations=[str(blog_enterprise_dir)],
        )
        if spec is None or spec.loader is None:
            pytest.skip(f"Could not load app module from {app_file}")

        # Add directory to path for imports within the module
        sys.path.insert(0, str(blog_enterprise_dir))

        module = importlib.util.module_from_spec(spec)
        sys.modules["app"] = module  # Register so internal imports work
        spec.loader.exec_module(module)

        # Create app
        app = module.create_app()
        yield app

    except Exception as e:
        logger.warning(f"Blog enterprise app creation failed: {e}")
        pytest.skip(f"Blog enterprise app creation failed: {e}")
    finally:
        # Clean up
        if str(blog_enterprise_dir) in sys.path:
            sys.path.remove(str(blog_enterprise_dir))
        if "app" in sys.modules:
            del sys.modules["app"]
        # Clear any cached modules from the example
        modules_to_remove = [k for k in sys.modules.keys() if "blog_enterprise" in k.lower()]
        for mod in modules_to_remove:
            del sys.modules[mod]


@pytest_asyncio.fixture(scope="function", loop_scope="function")
async def blog_enterprise_client(
    blog_enterprise_app, blog_enterprise_db_url
) -> AsyncGenerator[Any, None]:
    """HTTP client for blog_enterprise app with guaranteed dependencies."""
    import asyncio
    from httpx import AsyncClient, ASGITransport
    import psycopg_pool

    # Create and set pool manually to ensure database pool is initialized
    pool = psycopg_pool.AsyncConnectionPool(blog_enterprise_db_url)
    await pool.open()

    try:
        from fraiseql.fastapi.dependencies import set_db_pool

        set_db_pool(pool)

        transport = ASGITransport(app=blog_enterprise_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        from fraiseql.fastapi.dependencies import set_db_pool

        set_db_pool(None)

        # Close pool with short timeout - we don't need graceful shutdown in tests
        try:
            await asyncio.wait_for(pool.close(), timeout=2.0)
        except asyncio.TimeoutError:
            logger.debug("Pool close timed out, continuing")


# Sample data fixtures that work across examples
@pytest.fixture
def sample_user_data() -> None:
    """Sample user data for testing."""
    return {
        "username": f"testuser_{uuid4().hex[:8]}",
        "email": f"test_{uuid4().hex[:8]}@example.com",
        "password": "testpassword123",
        "role": "user",
        "profile_data": {
            "first_name": "Test",
            "last_name": "User",
            "bio": "Test user for integration testing",
        },
    }


@pytest.fixture
def sample_post_data() -> None:
    """Sample post data for testing."""
    return {
        "title": f"Test Post {uuid4().hex[:8]}",
        "content": "This is a test post with some content for integration testing purposes.",
        "excerpt": "This is a test excerpt for integration testing.",
        "status": "draft",
    }


@pytest.fixture
def sample_tag_data() -> None:
    """Sample tag data for testing."""
    return {
        "name": f"Test Tag {uuid4().hex[:8]}",
        "color": "#ff0000",
        "description": "A tag for integration testing purposes",
    }


@pytest.fixture
def sample_comment_data() -> None:
    """Sample comment data for testing."""
    return {
        "content": f"This is a test comment {uuid4().hex[:8]} with valuable insights for integration testing."
    }


# Cascade Example Fixtures - Removed
# The cascade fixtures are now in tests/fixtures/cascade/conftest.py
# to avoid conflicts and use the proper db_pool-based setup

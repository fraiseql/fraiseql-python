"""Unified database testing infrastructure with per-class isolation.

Architecture:
- Single PostgreSQL container per session
- Per-test-class: dedicated schema, dedicated connection pool
- Per-test-function: isolated connection with automatic transaction rollback
- Complete isolation: no shared state between test classes
- Fast cleanup: drop schema immediately after class completes
"""

import os
import uuid
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from typing import Any

import psycopg
import psycopg_pool
import pytest
import pytest_asyncio

try:
    from testcontainers.postgres import PostgresContainer

    HAS_DOCKER = True
except ImportError:
    HAS_DOCKER = False
    PostgresContainer = None

# Try to detect if Docker is actually available
if HAS_DOCKER:
    try:
        import docker

        client = docker.from_env()
        client.ping()
    except Exception:
        HAS_DOCKER = False

# Container cache - only ONE container per session
_container_cache = {}


@pytest.fixture(scope="session")
def postgres_container() -> Generator[Any]:
    """Single PostgreSQL container for entire test session.

    Uses docker/podman for test isolation with socket-based communication.
    Cached and reused for test reruns within same session.
    """
    # Skip if using external database (GitHub Actions, etc)
    # Only check TEST_DATABASE_URL (explicit external), not DATABASE_URL
    # (which may be set by example fixtures and should not prevent container creation)
    test_db_url = os.environ.get("TEST_DATABASE_URL")
    if test_db_url:
        yield None
        return

    if not HAS_DOCKER:
        pytest.skip("Docker not available")

    # Reuse existing container if available
    if "postgres" in _container_cache and _container_cache["postgres"].get_container_host_ip():
        yield _container_cache["postgres"]
        return

    container = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="fraiseql",
        password="fraiseql",
        dbname="fraiseql_test",
        driver="psycopg",  # psycopg3
    )

    try:
        container.start()
    except Exception as exc:
        pytest.skip(f"Docker container failed to start: {exc}")

    # Wait for database to be ready before proceeding
    url = container.get_connection_url().replace("postgresql+psycopg://", "postgresql://")
    _wait_for_database_ready(url)

    _container_cache["postgres"] = container

    yield container

    container.stop()
    _container_cache.pop("postgres", None)


@pytest.fixture(scope="session")
def postgres_url(postgres_container) -> str:
    """Get PostgreSQL connection URL.

    Priority order:
    1. Container URL (if container available) - for test isolation
    2. TEST_DATABASE_URL (explicit external database)
    3. DATABASE_URL (may be set by example fixtures)

    This ensures pgvector tests use the container even when examples
    fixtures have set DATABASE_URL.
    """
    # Prefer container URL for test isolation
    if postgres_container and "postgres" in _container_cache:
        container = _container_cache["postgres"]
        url = container.get_connection_url()
        # testcontainers returns postgresql+psycopg:// but psycopg3 expects postgresql://
        url = url.replace("postgresql+psycopg://", "postgresql://")
        return url

    # Fallback to explicit external database
    external_url = os.environ.get("TEST_DATABASE_URL")
    if external_url:
        return external_url

    # Last resort: DATABASE_URL (may be from examples)
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return db_url

    pytest.skip("No database available")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def session_db_pool(postgres_url) -> AsyncGenerator[psycopg_pool.AsyncConnectionPool]:
    """Session-scoped pool for setup/teardown operations only.

    This pool is used ONLY for:
    - Creating extensions (once per session)
    - Administrative operations

    All actual tests use per-class pools derived from this connection URL.
    """
    pool = psycopg_pool.AsyncConnectionPool(
        postgres_url,
        min_size=1,
        max_size=3,
        timeout=60,  # Increased from 30s to 60s for slower systems
        open=False,
    )

    await pool.open()
    await pool.wait()

    # Create extensions once for the session
    async with pool.connection() as conn:
        await conn.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
        await conn.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
        await conn.execute('CREATE EXTENSION IF NOT EXISTS "ltree"')

        # Try vector extension
        try:
            result = await conn.execute(
                "SELECT name FROM pg_available_extensions WHERE name = 'vector'"
            )
            if await result.fetchone():
                await conn.execute('CREATE EXTENSION IF NOT EXISTS "vector"')
        except Exception:
            pass

        # Try pg_fraiseql_cache extension
        try:
            await conn.execute('CREATE EXTENSION IF NOT EXISTS "pg_fraiseql_cache"')
        except Exception:
            pass

        await conn.commit()

    yield pool

    await pool.close()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def pgvector_available(postgres_container, postgres_url: str) -> bool:
    """Check if pgvector extension is available for testing.

    Returns True if pgvector extension can be used, False otherwise.
    This allows tests to skip gracefully when pgvector is not available.

    Note: Depends on postgres_container to ensure container is ready before checking.
    Includes retry logic to handle any remaining timing issues.

    With the updated fixtures, postgres_container will always be available (and
    postgres_url will prefer it), so pgvector tests will run in full suite.
    """
    import asyncio

    # Get URL from postgres_url fixture (which now prefers container)
    db_url = postgres_url

    # Try up to 5 times with 1-second delays
    # (Should succeed immediately if health check works)
    for attempt in range(5):
        try:
            async with await psycopg.AsyncConnection.connect(db_url, connect_timeout=3) as conn:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
                await conn.commit()
                return True
        except (psycopg.OperationalError, OSError):
            if attempt < 4:
                await asyncio.sleep(1)
                continue
            # Database is up but doesn't have pgvector - skip tests
            return False
        except psycopg.errors.InsufficientPrivilege:
            # Check if already installed
            try:
                async with await psycopg.AsyncConnection.connect(db_url) as check_conn:
                    result = await check_conn.execute("""
                        SELECT EXISTS(
                            SELECT 1 FROM pg_extension WHERE extname = 'vector'
                        )
                    """)
                    row = await result.fetchone()
                    return row[0] if row else False
            except Exception:
                return False
        except Exception:
            # Other errors (permissions, etc) - skip tests
            return False

    return False


# ============================================================================
# PER-TEST-CLASS FIXTURES
# ============================================================================


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def test_schema(request, postgres_url) -> AsyncGenerator[str]:
    """Create and provide an isolated test schema for the entire test class.

    Schema name format: test_<classname>_<random_suffix>
    Schema is automatically dropped after class completes.
    """
    # Generate unique schema name
    class_name = request.cls.__name__.lower() if request.cls else "test"
    suffix = uuid.uuid4().hex[:8]
    schema_name = f"test_{class_name}_{suffix}"

    # Create schema in a dedicated connection
    pool = psycopg_pool.AsyncConnectionPool(
        postgres_url,
        min_size=1,
        max_size=2,
        timeout=60,  # Increased from 30s to 60s for slower systems
        open=False,
    )

    await pool.open()
    await pool.wait()

    try:
        async with pool.connection() as conn:
            await conn.execute(f"CREATE SCHEMA {schema_name}")
            await conn.commit()

        yield schema_name

    finally:
        # Cleanup: drop schema with CASCADE
        try:
            async with pool.connection() as conn:
                await conn.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE")
                await conn.commit()
        except Exception:
            pass

        await pool.close()


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def class_db_pool(postgres_url) -> AsyncGenerator[psycopg_pool.AsyncConnectionPool]:
    """Per-class connection pool with minimal size.

    Each test class gets its own pool (min=1, max=5) to prevent contention
    and resource exhaustion across test classes.
    """
    pool = psycopg_pool.AsyncConnectionPool(
        postgres_url,
        min_size=1,
        max_size=5,
        timeout=60,  # Increased from 30s to 60s for slower systems
        open=False,
    )

    await pool.open()
    await pool.wait()

    # Verify pool is actually ready by testing a connection
    async with pool.connection() as conn:
        await conn.execute("SELECT 1")

    yield pool

    await pool.close()


@pytest_asyncio.fixture
async def db_connection(class_db_pool, test_schema) -> AsyncGenerator[psycopg.AsyncConnection]:
    """Per-function connection with automatic transaction rollback.

    Each test function gets a connection from the class pool,
    runs in a transaction, and automatically rolls back afterward.

    This ensures fast, deterministic cleanup without side effects.
    """
    async with class_db_pool.connection() as conn:
        # Set schema for this connection
        await conn.execute(f"SET search_path TO {test_schema}, public")

        # Start transaction
        await conn.execute("BEGIN")

        yield conn

        # Rollback to clean up
        try:
            await conn.execute("ROLLBACK")
        except Exception:
            pass


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def db_connection_committed(
    class_db_pool, test_schema
) -> AsyncGenerator[psycopg.AsyncConnection]:
    """Class-scoped connection factory for schema-specific operations.

    This fixture provides a way to execute commands within the test schema.
    The connection is acquired, used, and released within the fixture -
    do not hold it open across the test.

    Usage:
        # Create a table in the test schema
        await db_connection_committed.execute("CREATE TABLE test_table ...")
        await db_connection_committed.commit()
    """

    class SchemaConnection:
        """Wrapper that automatically sets search_path for all operations."""

        def __init__(self, pool, schema_name):
            self.pool = pool
            self.schema_name = schema_name
            self._conn = None

        async def _get_conn(self):
            """Get or create connection with schema set."""
            if self._conn is None:
                self._conn = await self.pool.connection().__aenter__()
                await self._conn.execute(f"SET search_path TO {self.schema_name}, public")
            return self._conn

        async def execute(self, query, *args: Any, **kwargs: Any):
            """Execute query in test schema."""
            conn = await self._get_conn()
            return await conn.execute(query, *args, **kwargs)

        def cursor(self, *args: Any, **kwargs: Any):
            """Return a cursor from the underlying connection."""

            # Return a cursor context manager that properly handles async
            class CursorContext:
                def __init__(self, wrapper):
                    self.wrapper = wrapper
                    self._cursor = None

                async def __aenter__(self):
                    conn = await self.wrapper._get_conn()
                    self._cursor = await conn.cursor(*args, **kwargs).__aenter__()
                    return self._cursor

                async def __aexit__(self, *exc_args: object):
                    if self._cursor:
                        await self._cursor.__aexit__(*exc_args)

            return CursorContext(self)

        async def commit(self):
            """Commit the connection."""
            if self._conn:
                await self._conn.commit()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object):
            if self._conn:
                ctx = self._conn
                self._conn = None
                await ctx.__aexit__(*args)

    wrapper = SchemaConnection(class_db_pool, test_schema)
    try:
        yield wrapper
    finally:
        # Close connection if still open
        if wrapper._conn:
            try:
                await wrapper._conn.close()
            except Exception:
                pass


@pytest.fixture
def clear_registry() -> Generator[None]:
    """Clear FraiseQL global registries before and after each test.

    This ensures no type or schema registry pollution between tests.
    """
    _clear_all_fraiseql_state()
    yield
    _clear_all_fraiseql_state()


@pytest.fixture(scope="class")
def clear_registry_class() -> Generator[None]:
    """Clear FraiseQL global registries before and after each test class.

    Use this for class-scoped fixtures that need a clean registry.
    """
    _clear_all_fraiseql_state()
    yield
    _clear_all_fraiseql_state()


def _clear_all_fraiseql_state() -> None:
    """Clear all FraiseQL global state.

    Resets:
    - Python SchemaRegistry
    - Rust schema registry
    - FastAPI global dependencies
    - GraphQL type caches
    - Type registry (view mappings)
    - Mutation registries
    """
    try:
        from fraiseql.core.graphql_type import _graphql_type_cache
        from fraiseql.db import _type_registry

        _graphql_type_cache.clear()
        _type_registry.clear()
    except ImportError:
        pass
    except Exception:
        pass

    # Clear view type registry
    try:
        from fraiseql.db import _view_type_registry

        _view_type_registry.clear()
    except ImportError:
        pass
    except Exception:
        pass

    # Clear SchemaRegistry
    try:
        from fraiseql.gql.schema_builder import SchemaRegistry

        SchemaRegistry.get_instance().clear()
    except Exception:
        pass

    # Reset Rust schema registry
    try:
        from fraiseql._fraiseql_rs import reset_schema_registry_for_testing

        reset_schema_registry_for_testing()
    except ImportError:
        pass
    except Exception:
        pass

    # Reset FastAPI dependencies
    try:
        from fraiseql.fastapi.dependencies import (
            set_auth_provider,
            set_db_pool,
            set_fraiseql_config,
        )

        set_db_pool(None)
        set_auth_provider(None)
        set_fraiseql_config(None)
    except ImportError:
        pass
    except Exception:
        pass

    # Clear mutation registries
    try:
        from fraiseql.mutations.decorators import clear_mutation_registries

        clear_mutation_registries()
    except ImportError:
        pass
    except Exception:
        pass


# ============================================================================
# LEGACY FIXTURES (DEPRECATED - for migration only)
# ============================================================================


@pytest_asyncio.fixture
async def db_cursor(db_connection) -> AsyncGenerator[psycopg.AsyncCursor]:
    """DEPRECATED: Use db_connection instead."""
    async with db_connection.cursor() as cur:
        yield cur


@pytest.fixture
def create_test_table() -> None:
    """DEPRECATED: Tables now created within test_schema automatically."""


@pytest.fixture
def create_test_view() -> None:
    """DEPRECATED: Views now created within test_schema automatically."""


@pytest.fixture
def create_fraiseql_app_with_db(
    postgres_url: str,
    clear_registry: None,
    class_db_pool: psycopg_pool.AsyncConnectionPool,
    test_schema: str,
) -> Any:
    """Factory fixture to create FraiseQL apps with real database connection.

    This fixture provides a factory function that creates properly configured
    FraiseQL apps using the real PostgreSQL container and pre-initialized pool.

    Usage:
        def test_something(create_fraiseql_app_with_db):
            app = create_fraiseql_app_with_db(
                types=[MyType],
                queries=[my_query],
                production=False
            )
            client = TestClient(app)
            # Use the app...
    """
    from fraiseql.fastapi.app import create_fraiseql_app
    from fraiseql.fastapi.dependencies import set_db_pool

    class SchemaAwarePool:
        def __init__(self, pool, schema):
            self._pool = pool
            self._schema = schema

        @asynccontextmanager
        async def connection(self):
            async with self._pool.connection() as conn:
                await conn.execute(f"SET search_path TO {self._schema}, public")
                yield conn

        def __getattr__(self, name):
            return getattr(self._pool, name)

    def _create_app(**kwargs: Any):
        """Create a FraiseQL app with proper database URL and pool."""
        # Use the real database URL from the container
        kwargs.setdefault("database_url", postgres_url)

        # Create the app
        app = create_fraiseql_app(**kwargs)

        # Manually set the database pool to bypass lifespan issues in tests
        wrapped_pool = SchemaAwarePool(class_db_pool, test_schema)
        set_db_pool(wrapped_pool)

        return app

    return _create_app


# ============================================================================
# TEST MARKERS & CONFIGURATION
# ============================================================================


def pytest_configure(config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "database: mark test as requiring database access")


def pytest_addoption(parser) -> None:
    """Add custom command line options."""
    if not any(opt.dest == "no_db" for opt in parser._anonymous.options if hasattr(opt, "dest")):
        parser.addoption(
            "--no-db", action="store_true", default=False, help="Skip database integration tests"
        )


def pytest_collection_modifyitems(config, items) -> None:
    """Modify test collection based on markers."""
    if config.getoption("--no-db"):
        skip_db = pytest.mark.skip(reason="Skipping database tests (--no-db flag)")
        for item in items:
            if "database" in item.keywords:
                item.add_marker(skip_db)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def _wait_for_database_ready(url: str, max_attempts: int = 30) -> None:
    """Wait for PostgreSQL to accept connections.

    Args:
        url: PostgreSQL connection URL
        max_attempts: Maximum retry attempts (default: 30 = 15 seconds)

    Raises:
        RuntimeError: If database doesn't become ready in time
    """
    import time

    for attempt in range(max_attempts):
        try:
            # Try synchronous connection (simpler for startup check)
            with psycopg.connect(url, connect_timeout=2) as conn:
                # Verify database is actually ready
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                return  # Success!
        except (psycopg.OperationalError, OSError):
            if attempt < max_attempts - 1:
                time.sleep(0.5)
            else:
                raise RuntimeError(
                    f"PostgreSQL container did not become ready after "
                    f"{max_attempts * 0.5:.1f} seconds"
                )

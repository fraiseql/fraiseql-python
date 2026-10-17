import os
from collections.abc import Generator

import pytest

# Import chaos database fixtures plugin (must be at top level)
# Use full module path for plugin import
try:
    pytest_plugins = ["tests.chaos.database_fixtures"]
except ImportError:
    # Skip if chaos fixtures not available
    pytest_plugins = []

# Check if Rust extension should be skipped for performance optimization
SKIP_RUST = os.getenv("FRAISEQL_SKIP_RUST") == "1"

# Try to import FraiseQL components, skip if not available
try:
    from fraiseql.config.schema_config import SchemaConfig
    from fraiseql.core.graphql_type import _graphql_type_cache
    from fraiseql.db import _type_registry
    from fraiseql.gql.schema_builder import SchemaRegistry

    FRAISEQL_AVAILABLE = True
except ImportError:
    FRAISEQL_AVAILABLE = False
    SchemaConfig = None  # type: ignore
    SchemaRegistry = None  # type: ignore
    _graphql_type_cache = None  # type: ignore
    _type_registry = None  # type: ignore

# Import fixtures from the new organized structure
# Import examples fixtures first as they don't require heavy dependencies
from tests.fixtures.examples.conftest_examples import (  # noqa: F401
    blog_enterprise_app,
    blog_enterprise_client,
    blog_enterprise_db_url,
    blog_simple_app,
    blog_simple_client,
    blog_simple_context,
    blog_simple_db_connection,
    blog_simple_db_url,
    blog_simple_graphql_client,
    blog_simple_repository,
    reset_fraiseql_state,
    reset_fraiseql_state_module,
    sample_comment_data,
    sample_post_data,
    sample_tag_data,
    sample_user_data,
    smart_dependencies,
)

# Try to import database and auth fixtures if dependencies are available
try:
    from tests.fixtures.database.database_conftest import (  # noqa: F401
        class_db_pool,
        clear_registry_class,
        create_fraiseql_app_with_db,
        create_test_table,
        create_test_view,
        db_connection,
        db_connection_committed,
        db_cursor,
        pgvector_available,
        postgres_container,
        postgres_url,
        test_schema,
    )
except ImportError:
    pass  # Skip database fixtures if dependencies not available

try:
    from tests.fixtures.auth.conftest_auth import (  # noqa: F401
        admin_context,
        auth_context,
        authenticated_request,
        mock_auth_context,
        mock_csrf_request,
        mock_request_with_auth,
        unauthenticated_context,
        user_context,
    )
except ImportError:
    pass  # Skip auth fixtures if dependencies not available

try:
    from tests.fixtures.cascade.conftest import (  # noqa: F401
        cascade_app,
        cascade_client,
        cascade_db_schema,
        cascade_http_client,
        mock_apollo_client,
    )
except ImportError:
    pass  # Skip cascade fixtures if dependencies not available

try:
    from tests.fixtures.security.aws_conftest import (  # noqa: F401
        aws_kms_client,
        aws_kms_mock,
        aws_region,
        kms_key_id,
    )
    from tests.fixtures.security.vault_conftest import (  # noqa: F401
        vault_container,
        vault_token,
        vault_transit_ready,
        vault_url,
    )
except ImportError:
    pass  # Skip security fixtures if dependencies not available

try:
    from tests.fixtures.graphql.conftest_graphql import (  # noqa: F401
        gql_context,
        gql_mock_pool,
        seed_graphql_data,
        setup_graphql_table,
    )
except ImportError:
    pass  # Skip GraphQL fixtures if dependencies not available


@pytest.fixture(scope="session")
def clear_type_caches() -> Generator[None]:
    """Clear type caches at session start and end.

    Use explicitly when tests need clean type registry state.

    Yields:
        None: This fixture performs setup/teardown only.
    """
    if FRAISEQL_AVAILABLE:
        # Clear at session start
        _graphql_type_cache.clear()  # type: ignore
        _type_registry.clear()  # type: ignore

    yield

    if FRAISEQL_AVAILABLE:
        # Clear at session end
        _graphql_type_cache.clear()  # type: ignore
        _type_registry.clear()  # type: ignore


@pytest.fixture
def clear_registry() -> Generator[None]:
    """Clear the schema registry before and after each test.

    Use explicitly on tests that need schema registry isolation.
    This fixture performs comprehensive cleanup of all FraiseQL global state
    including Rust schema registry and FastAPI dependencies.

    Yields:
        None: This fixture performs setup/teardown only.
    """
    _clear_all_fraiseql_state()
    yield
    _clear_all_fraiseql_state()


def _clear_all_fraiseql_state() -> None:
    """Comprehensive cleanup of all FraiseQL global state.

    Delegates to fraiseql.testing.clear_fraiseql_state() utility.
    """
    if not FRAISEQL_AVAILABLE:
        return

    from fraiseql.testing import clear_fraiseql_state

    clear_fraiseql_state()


@pytest.fixture(autouse=True)
def _reset_schema_config() -> Generator[None]:
    """Restore SchemaConfig's defaults after every test.

    SchemaConfig is a process-wide singleton, and `build_fraiseql_schema(camel_case_fields=False)`
    writes into it and leaves it there. Tests that convert types without building a schema
    then got snake_case names from whichever test ran before them in the same process,
    which under pytest-xdist depends on how tests land on workers.

    Yields:
        None: This fixture performs teardown only.
    """
    yield
    if FRAISEQL_AVAILABLE:
        SchemaConfig.reset()  # type: ignore


@pytest.fixture
def use_snake_case() -> Generator[None]:
    """Fixture to use snake_case field names in tests.

    Yields:
        None: This fixture performs setup/teardown only.
    """
    if not FRAISEQL_AVAILABLE:
        pytest.skip("FraiseQL not available - skipping snake_case fixture")

    # Save current config
    original_config = SchemaConfig.get_instance().camel_case_fields  # type: ignore

    # Set to snake_case
    SchemaConfig.set_config(camel_case_fields=False)  # type: ignore

    yield

    # Restore original config
    SchemaConfig.set_config(camel_case_fields=original_config)  # type: ignore


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip Rust-dependent tests when FRAISEQL_SKIP_RUST=1."""
    if SKIP_RUST:
        skip_rust = pytest.mark.skip(reason="Rust extension disabled via FRAISEQL_SKIP_RUST=1")
        for item in items:
            # Skip tests that import or use Rust extension
            if (
                any(marker in item.keywords for marker in ["rust"])
                or "rust" in str(item.fspath).lower()
            ):
                item.add_marker(skip_rust)


@pytest.fixture
async def setup_hybrid_table(class_db_pool, test_schema):
    """Set up hybrid table (machine + tv_allocation) for testing.

    Creates:
    - machine table (FK target)
    - tv_allocation hybrid table (hybrid: machine_id FK + data JSONB)
    - Sample data for testing

    Returns:
        dict with test data IDs
    """
    import uuid

    from fraiseql.db import register_type_for_view

    # Get connection, do setup, then release it before yielding
    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        # Set schema
        await cursor.execute(f"SET search_path TO {test_schema}")

        # Create machine table
        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS machine (
                id UUID PRIMARY KEY,
                name TEXT
            )
        """)

        # Create tv_allocation hybrid table
        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS tv_allocation (
                id UUID PRIMARY KEY,
                machine_id UUID REFERENCES machine(id),
                status TEXT,
                name TEXT,
                data JSONB,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Insert test machines
        machine1_id = uuid.uuid4()
        machine2_id = uuid.uuid4()

        await cursor.execute(
            "INSERT INTO machine (id, name) VALUES (%s, %s), (%s, %s)",
            (machine1_id, "Machine 1", machine2_id, "Machine 2"),
        )

        # Insert test allocations
        alloc1_id = uuid.uuid4()
        alloc2_id = uuid.uuid4()

        await cursor.execute(
            """
            INSERT INTO tv_allocation (id, machine_id, status, name, data)
            VALUES
                (%s, %s, 'active', 'Test Allocation 1', '{"device": {"name": "Device1"}}'::jsonb),
                (%s, %s, 'pending', 'Test Allocation 2', '{"device": {"name": "Device2"}}'::jsonb)
        """,
            (alloc1_id, machine1_id, alloc2_id, machine2_id),
        )

        await conn.commit()

    # Connection released here - outside the context manager

    # Register type metadata
    register_type_for_view(
        "tv_allocation",
        object,  # Dummy type for testing
        table_columns={"id", "machine_id", "status", "name", "data", "created_at"},
        fk_relationships={"machine": "machine_id"},
        has_jsonb_data=True,
        jsonb_column="data",
    )

    yield {
        "machine1_id": machine1_id,
        "machine2_id": machine2_id,
        "alloc1_id": alloc1_id,
        "alloc2_id": alloc2_id,
    }

    # Cleanup: get new connection for teardown
    async with class_db_pool.connection() as conn, conn.cursor() as cursor:
        await cursor.execute(f"SET search_path TO {test_schema}")
        await cursor.execute("DROP TABLE IF EXISTS tv_allocation CASCADE")
        await cursor.execute("DROP TABLE IF EXISTS machine CASCADE")
        await conn.commit()

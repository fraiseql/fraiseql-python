"""FastAPI application factory for FraiseQL."""

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import psycopg_pool
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from graphql import GraphQLSchema
from psycopg import AsyncConnection

from fraiseql.auth.auth0 import Auth0Config
from fraiseql.auth.base import AuthProvider
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.fastapi.dependencies import (
    get_db_pool,
    set_auth_provider,
    set_db_pool,
    set_fraiseql_config,
)
from fraiseql.fastapi.routers import create_graphql_router
from fraiseql.fastapi.turbo import TurboRegistry
from fraiseql.gql.schema_builder import build_fraiseql_schema
from fraiseql.introspection import AutoDiscovery
from fraiseql.utils import normalize_database_url

if TYPE_CHECKING:
    from fraiseql.security.authorization import Authorizer

logger = logging.getLogger(__name__)

# Global to store turbo registry for lifespan access
_global_turbo_registry = None


async def create_db_pool(database_url: str, **pool_kwargs: Any) -> psycopg_pool.AsyncConnectionPool:
    """Create async database connection pool with custom type handling."""

    # Configure how psycopg3 handles PostgreSQL types for each connection
    async def configure_types(conn: AsyncConnection) -> None:
        """Configure type adapters to keep dates as strings."""
        # Import here to avoid circular imports
        from psycopg.adapt import Loader

        # Create a custom loader that returns the raw text value
        class TextLoader(Loader):
            def load(self, data: Any) -> Any:
                # Return the raw text representation from PostgreSQL
                return data.decode("utf-8") if isinstance(data, bytes) else data

        # Register text loaders for date/time types
        # This prevents automatic conversion to Python date/datetime objects
        conn.adapters.register_loader("date", TextLoader)
        conn.adapters.register_loader("timestamp", TextLoader)
        conn.adapters.register_loader("timestamptz", TextLoader)
        conn.adapters.register_loader("time", TextLoader)
        conn.adapters.register_loader("timetz", TextLoader)

        # Note: row_factory cannot be set at connection level due to type constraints
        # The row_factory=dict_row is set on each cursor creation in db.py

    async def check_connection(conn: AsyncConnection) -> None:
        """Validate connection is alive before reuse.

        This prevents using connections that were terminated externally
        (e.g., by pg_terminate_backend() during database reseeding).

        Critical for multi-worker uvicorn setups where database connections
        can be terminated while workers are still running.

        See: https://github.com/fraiseql/fraiseql/issues/85
        """
        try:
            await conn.execute("SELECT 1")
        except Exception:
            # Connection is dead, raise to signal pool to create new connection
            logger.debug("Connection check failed, pool will create new connection")
            raise

    # Create pool with the configure callback
    # Use open=False to avoid deprecation warning in psycopg 3.2+
    pool = psycopg_pool.AsyncConnectionPool(
        database_url,
        configure=configure_types,
        check=check_connection,  # Validate connections before reuse
        open=False,  # Don't open in constructor to avoid deprecation warning
        **pool_kwargs,
    )

    # Open the pool explicitly as recommended
    await pool.open()

    return pool


async def discover_fraiseql_schema(
    database_url: str,
    view_pattern: str = "v_%",
    function_pattern: str = "fn_%",
    schemas: list[str] | None = None,
) -> dict[str, list]:
    """Discover GraphQL schema components from PostgreSQL database.

    This function introspects the database and generates types, queries, and mutations
    automatically from views and functions with @fraiseql annotations.

    Args:
        database_url: PostgreSQL connection URL
        view_pattern: Pattern for view discovery (default: "v_%")
        function_pattern: Pattern for function discovery (default: "fn_%")
        schemas: List of schemas to search (default: ["public"])

    Returns:
        Dictionary with discovered components:
        {
            'types': [User, Post, ...],
            'queries': [user, users, ...],
            'mutations': [createUser, ...],
        }

    Example:
        ```python
        from fraiseql.fastapi import discover_fraiseql_schema

        # Discover schema components
        schema_components = await discover_fraiseql_schema(
            "postgresql://user:pass@localhost/db"
        )

        # Use with create_fraiseql_app
        app = create_fraiseql_app(
            database_url="postgresql://user:pass@localhost/db",
            types=schema_components['types'],
            queries=schema_components['queries'],
            mutations=schema_components['mutations'],
        )
        ```
    """
    import psycopg_pool

    # Create connection pool
    pool = psycopg_pool.AsyncConnectionPool(database_url, min_size=1, max_size=10)
    await pool.open()

    try:
        # Initialize auto-discovery
        auto_discovery = AutoDiscovery(pool)

        # Discover all components
        return await auto_discovery.discover_all(
            view_pattern=view_pattern, function_pattern=function_pattern, schemas=schemas
        )
    finally:
        await pool.close()


def create_fraiseql_app(
    *,
    # Required configuration
    database_url: str | None = None,
    # Schema configuration
    types: Sequence[type] = (),
    mutations: Sequence[Callable[..., Any]] = (),
    queries: Sequence[type] = (),
    # Auto-discovery configuration
    auto_discover: bool = False,
    # Optional configuration
    config: FraiseQLConfig | None = None,
    auth: Auth0Config | AuthProvider | None = None,
    context_getter: Callable[[Request], Awaitable[dict[str, Any]]] | None = None,
    lifespan: Callable[[FastAPI], Any] | None = None,
    # App configuration
    title: str | None = None,
    version: str | None = None,
    description: str | None = None,
    # Environment
    production: bool = False,
    # Development auth configuration
    dev_auth_username: str | None = None,
    dev_auth_password: str | None = None,
    # Connection pool configuration
    connection_pool_size: int | None = None,
    connection_pool_max_overflow: int | None = None,
    connection_pool_timeout: float | None = None,
    connection_pool_recycle: int | None = None,
    # Schema registry configuration
    enable_schema_registry: bool = True,
    # FastAPI app to extend (optional)
    app: FastAPI | None = None,
    # Operation authorization (issue #362)
    authorizer: "Authorizer | None" = None,
) -> FastAPI:
    """Create a FastAPI application with FraiseQL GraphQL endpoint.

    Args:
        database_url: PostgreSQL connection URL
        types: Sequence of FraiseQL types to register
        mutations: Sequence of mutation resolver functions
        queries: Sequence of query types (if not using default QueryRoot)
        auto_discover: Enable automatic discovery of GraphQL schema from PostgreSQL metadata
        config: Full configuration object (overrides other params)
        auth: Authentication configuration or provider
        context_getter: Optional async function to build GraphQL context from request
        lifespan: Optional custom lifespan context manager for the FastAPI app
        title: API title
        version: API version
        description: API description
        production: Whether to use production optimizations
        dev_auth_username: Override username for development auth (defaults to env var or "admin")
        dev_auth_password: Override password for development auth (defaults to env var)
        connection_pool_size: Number of connections in the pool (default: 10 for dev, 20 for prod)
        connection_pool_max_overflow: Additional connections beyond pool_size (default: 10)
        connection_pool_timeout: Seconds to wait for available connection (default: 30.0)
        connection_pool_recycle: Seconds before recycling idle connections (default: 3600)
        enable_schema_registry: Whether to initialize Rust schema registry (default: True)
        app: Existing FastAPI app to extend (creates new if None)
        authorizer: Optional global default operation authorizer (issue #362). When
            provided it gates every root query/mutation and the three resolver-bypass
            paths (TurboRouter, /graphql/rust, APQ cache hits), and survives schema
            hot-reload. With no authorizer, behavior is byte-for-byte unchanged.

    Returns:
        Configured FastAPI application

    Example:
        ```python
        from fraiseql.fastapi import create_fraiseql_app
        from fraiseql.auth import Auth0Config
        import my_models
        import my_mutations

        # Basic usage with default pool settings
        app = create_fraiseql_app(
            database_url="postgresql://localhost/mydb",
            types=[my_models.User, my_models.Post],
            mutations=[my_mutations.create_user],
            auth=Auth0Config(
                domain="myapp.auth0.com",
                api_identifier="https://api.myapp.com"
            ),
            production=True
        )

        # Production with custom connection pool
        app = create_fraiseql_app(
            database_url="postgresql://db.prod.example.com/mydb",
            connection_pool_size=30,
            connection_pool_max_overflow=20,
            connection_pool_timeout=60.0,
            types=[my_models.User, my_models.Post],
            production=True
        )
        ```

        Auto-discovery example:
        ```python
        # Enable auto-discovery from PostgreSQL metadata
        app = create_fraiseql_app(
            database_url="postgresql://localhost/mydb",
            auto_discover=True  # Discovers types/queries/mutations from database
        )
        ```
    """
    # Create or get config
    if config is None:
        # Build config kwargs, only including explicitly provided values
        # This allows environment variables to be loaded for unprovided fields
        # Normalize database URL to handle both formats
        normalized_url = normalize_database_url(database_url or "postgresql://localhost/fraiseql")
        config_kwargs: dict[str, Any] = {
            "database_url": normalized_url,
            "environment": "production" if production else "development",
        }

        # Only add fields if they differ from defaults or are explicitly provided
        if title is not None:
            config_kwargs["app_name"] = title
        if version is not None:
            config_kwargs["app_version"] = version
        if dev_auth_username is not None:
            config_kwargs["dev_auth_username"] = dev_auth_username
        if dev_auth_password is not None:
            config_kwargs["dev_auth_password"] = dev_auth_password

        # Connection pool configuration
        # Default pool size: 10 for development, 20 for production
        if connection_pool_size is not None:
            config_kwargs["database_pool_size"] = connection_pool_size
        elif "database_pool_size" not in config_kwargs:
            # Apply environment-based defaults if not explicitly set
            config_kwargs["database_pool_size"] = 20 if production else 10

        if connection_pool_max_overflow is not None:
            config_kwargs["database_max_overflow"] = connection_pool_max_overflow

        if connection_pool_timeout is not None:
            config_kwargs["database_pool_timeout"] = int(connection_pool_timeout)

        if connection_pool_recycle is not None:
            config_kwargs["database_pool_recycle"] = connection_pool_recycle

        config = FraiseQLConfig(**config_kwargs)
    else:
        # If config is provided, override with explicit parameters
        if connection_pool_size is not None:
            config.database_pool_size = connection_pool_size
        if connection_pool_max_overflow is not None:
            config.database_max_overflow = connection_pool_max_overflow
        if connection_pool_timeout is not None:
            config.database_pool_timeout = int(connection_pool_timeout)
        if connection_pool_recycle is not None:
            config.database_pool_recycle = connection_pool_recycle

    # Setup authentication first so it's available for lifespan
    auth_provider: AuthProvider | None = None
    if auth is not None:
        if isinstance(auth, Auth0Config):
            auth_provider = auth.create_provider()
        elif isinstance(auth, AuthProvider):
            auth_provider = auth
        else:
            msg = "auth must be Auth0Config or AuthProvider instance"
            raise ValueError(msg)
        # If auth is provided, enable authentication
        config.auth_enabled = True
    elif config.auth_enabled and config.auth_provider == "auth0":
        # Auto-create Auth0 provider from config if not explicitly provided
        if not config.auth0_domain or not config.auth0_api_identifier:
            msg = "auth0_domain and auth0_api_identifier must be set when using auth0 provider"
            raise ValueError(msg)

        from fraiseql.auth.auth0 import Auth0Provider

        auth_provider = Auth0Provider(
            domain=config.auth0_domain,
            api_identifier=config.auth0_api_identifier,
            algorithms=config.auth0_algorithms,
        )

    set_auth_provider(auth_provider)
    set_fraiseql_config(config)

    # Create lifespan context manager for the app
    if lifespan is None:
        # Use default lifespan that manages database pool
        @asynccontextmanager
        async def default_lifespan(app: FastAPI) -> AsyncGenerator[None]:
            """Manage application lifecycle."""
            # Startup - only create pool if one doesn't already exist
            # (allows test fixtures to inject their own pool)
            try:
                existing_pool = get_db_pool()
            except RuntimeError:
                existing_pool = None
            pool_created_here = False

            if existing_pool is None:
                pool = await create_db_pool(
                    str(config.database_url),
                    min_size=2,  # Keep 2 connections warm for better performance
                    max_size=config.database_pool_size + config.database_max_overflow,
                    timeout=config.database_pool_timeout,
                    max_lifetime=config.database_pool_recycle,
                )
                set_db_pool(pool)
                pool_created_here = True

            yield

            # Shutdown - only close pool if we created it
            if pool_created_here:
                pool_to_close = get_db_pool()
                if pool_to_close:
                    await pool_to_close.close()

            if auth_provider and hasattr(auth_provider, "close"):
                await auth_provider.close()

        lifespan_to_use = default_lifespan
    else:
        # Wrap user's lifespan to ensure database pool is still managed
        @asynccontextmanager
        async def wrapped_lifespan(app: FastAPI) -> AsyncGenerator[None]:
            """Wrap user lifespan with FraiseQL resource management."""
            # Startup - initialize database pool
            pool = await create_db_pool(
                str(config.database_url),
                min_size=2,  # Keep 2 connections warm for better performance
                max_size=config.database_pool_size + config.database_max_overflow,
                timeout=config.database_pool_timeout,
                max_lifetime=config.database_pool_recycle,
            )
            set_db_pool(pool)

            # Call user's lifespan
            async with lifespan(app):
                yield

            # Shutdown - cleanup our resources
            pool_to_close = get_db_pool()
            if pool_to_close:
                await pool_to_close.close()

            if auth_provider and hasattr(auth_provider, "close"):
                await auth_provider.close()

        lifespan_to_use = wrapped_lifespan

    # Create or extend FastAPI app
    if app is None:
        app = FastAPI(
            title=config.app_name,
            version=config.app_version,
            description=description or "GraphQL API powered by FraiseQL",
            lifespan=lifespan_to_use,
        )

    # Setup CORS if enabled
    if config.cors_enabled:
        # Log warning if using wildcard in production
        if production and "*" in config.cors_origins:
            logger.warning(
                "CORS enabled with wildcard origin (*) in production. "
                "This may cause conflicts with reverse proxies that handle CORS. "
                "Consider disabling CORS in FraiseQL when using a reverse proxy."
            )

        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origins,
            allow_credentials=True,
            allow_methods=config.cors_methods,
            allow_headers=config.cors_headers,
        )

    # Setup development authentication if enabled and not in production
    if not production and config.dev_auth_password:
        from fraiseql.fastapi.dev_auth import DevAuthMiddleware

        logger.warning(
            "Development authentication enabled with username: %s. "
            "This should NEVER be used in production!",
            config.dev_auth_username,
        )

        app.add_middleware(
            DevAuthMiddleware,
            username=config.dev_auth_username,
            password=config.dev_auth_password,
        )

    # Auto-discover schema components if enabled
    auto_types = []
    auto_queries = []
    auto_mutations = []

    if auto_discover:
        logger.info("Auto-discovery enabled - performing discovery during app creation")
        # Perform synchronous discovery using the discover_fraiseql_schema function
        import asyncio

        async def sync_discover():
            return await discover_fraiseql_schema(
                str(config.database_url),
                view_pattern="v_%",
                function_pattern="fn_%",
                schemas=["public"],
            )

        # Run the async discovery in a new event loop
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            discovered = loop.run_until_complete(sync_discover())
            loop.close()

            auto_types.extend(discovered.get("types", []))
            auto_queries.extend(discovered.get("queries", []))
            auto_mutations.extend(discovered.get("mutations", []))

            logger.info(
                f"Auto-discovery completed: {len(auto_types)} types, "
                f"{len(auto_queries)} queries, {len(auto_mutations)} mutations"
            )
        except Exception as e:
            logger.error(f"Auto-discovery failed during app creation: {e}")
            # Continue with empty auto-discovered components

    # Build GraphQL schema
    # Combine both types and queries - types define GraphQL types, queries define query functions
    all_query_types = list(types) + list(queries) + auto_types + auto_queries
    all_mutations = list(mutations) + auto_mutations

    schema = build_fraiseql_schema(
        query_types=all_query_types,
        mutation_resolvers=all_mutations,
        camel_case_fields=config.auto_camel_case,
        authorizer=authorizer,
    )

    # Store configuration for potential schema refresh
    app.state._fraiseql_refresh_config = {
        "database_url": database_url,
        "original_types": list(types),
        "original_queries": list(queries),
        "original_mutations": list(mutations),
        "auto_discover": auto_discover,
        "camel_case_fields": config.auto_camel_case,
        "enable_schema_registry": enable_schema_registry,
        "config": config,
        "auth_provider": auth_provider,
        # Re-applied on hot-reload so the authorizer survives a schema rebuild (#362).
        "authorizer": authorizer,
    }
    app.state.graphql_schema = schema
    # Expose the configured authorizer for the bypass gates / reload closure (#362).
    app.state._fraiseql_authorizer = authorizer

    # Initialize Rust schema registry for type resolution
    # This enables correct __typename for nested JSONB objects and field aliasing
    if enable_schema_registry:
        import importlib
        import json
        import time

        from fraiseql.core.schema_serializer import SchemaSerializer

        try:
            _fraiseql_rs = importlib.import_module("fraiseql._fraiseql_rs")
            start_time = time.time()

            serializer = SchemaSerializer()
            schema_ir = serializer.serialize_schema(schema)
            schema_json = json.dumps(schema_ir)

            _fraiseql_rs.initialize_schema_registry(schema_json)

            initialization_time_ms = (time.time() - start_time) * 1000
            type_count = len(schema.type_map)

            logger.info(
                "Schema registry initialized successfully: types=%d, time=%.2fms",
                type_count,
                initialization_time_ms,
            )
        except Exception as e:
            # Log error but don't fail app startup - maintain backward compatibility
            logger.warning(
                "Failed to initialize schema registry (continuing with app startup): %s", str(e)
            )
    else:
        logger.debug("Schema registry initialization disabled by feature flag")

    # Create TurboRegistry if enabled (regardless of environment)
    turbo_registry = None
    # TurboRouter is always enabled for maximum performance
    if True:
        turbo_registry = TurboRegistry(max_size=config.turbo_router_cache_size)
        # Store TurboRegistry in app state for access in lifespan
        app.state.turbo_registry = turbo_registry
        # Also store globally for easier access
        global _global_turbo_registry
        _global_turbo_registry = turbo_registry

    # Create and mount GraphQL router
    graphql_router = create_graphql_router(
        schema=schema,
        config=config,
        auth_provider=auth_provider,
        context_getter=context_getter,
        turbo_registry=turbo_registry,
    )

    app.include_router(graphql_router)

    # Add health check endpoint
    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """Health check endpoint (liveness probe).

        Simple process-level health check. Returns 200 if the application
        process is running.

        Use for Kubernetes liveness probes to restart crashed pods.
        """
        return {"status": "healthy", "service": "fraiseql"}

    # Add readiness check endpoint
    @app.get("/ready")
    async def readiness_check(request: Request) -> dict[str, Any]:
        """Readiness check endpoint (readiness probe).

        Checks if the application is ready to serve traffic by validating:
        - Database connection pool is available
        - Database is reachable (simple query test)
        - GraphQL schema is loaded

        Returns:
            200 OK: Application ready to serve traffic
            503 Service Unavailable: Application not ready

        Use for Kubernetes readiness probes to route traffic only to ready pods.

        Example Response (Ready):
            ```json
            {
              "status": "ready",
              "checks": {
                "database": "ok",
                "schema": "ok"
              },
              "timestamp": 1670500000.0
            }
            ```

        Example Response (Not Ready):
            ```json
            {
              "status": "not_ready",
              "checks": {
                "database": "failed: connection timeout",
                "schema": "ok"
              },
              "timestamp": 1670500000.0
            }
            ```
        """
        import time

        from fastapi import status
        from fastapi.responses import JSONResponse

        checks: dict[str, str] = {}
        all_ready = True

        # Check 1: Database connection pool
        try:
            db_pool = get_db_pool()
            if db_pool is None:
                checks["database"] = "failed: pool not initialized"
                all_ready = False
            else:
                # Check 2: Database reachability (simple query)
                try:
                    async with db_pool.connection() as conn:
                        await conn.execute("SELECT 1")
                    checks["database"] = "ok"
                except Exception as e:
                    checks["database"] = f"failed: {str(e)[:100]}"
                    all_ready = False
        except Exception as e:
            checks["database"] = f"failed: {str(e)[:100]}"
            all_ready = False

        # Check 3: GraphQL schema loaded
        try:
            schema = getattr(app.state, "graphql_schema", None)
            if schema is None:
                checks["schema"] = "failed: not loaded"
                all_ready = False
            else:
                checks["schema"] = "ok"
        except Exception as e:
            checks["schema"] = f"failed: {str(e)[:100]}"
            all_ready = False

        # Build response
        response_status = "ready" if all_ready else "not_ready"
        http_status = status.HTTP_200_OK if all_ready else status.HTTP_503_SERVICE_UNAVAILABLE

        return JSONResponse(
            content={
                "status": response_status,
                "checks": checks,
                "timestamp": time.time(),
            },
            status_code=http_status,
        )

    # Add refresh_schema method to app instance
    async def refresh_schema() -> GraphQLSchema:
        """Refresh the GraphQL schema by re-introspecting the database.

        This rebuilds the schema from scratch, discovering new database functions
        and views that were created after app initialization. Primarily useful
        for testing scenarios where database functions are created dynamically.

        The method:
        1. Clears all Python and Rust caches
        2. Re-runs auto-discovery (if enabled)
        3. Rebuilds the GraphQL schema
        4. Reinitializes the Rust schema registry
        5. Updates TurboRegistry cache
        6. Replaces the GraphQL route handler

        Returns:
            The newly built GraphQLSchema instance

        Example:
            >>> # In test after creating database functions
            >>> await app.refresh_schema()
            >>> # New mutations now available in schema

        Raises:
            RuntimeError: If refresh config not found (app not created with create_fraiseql_app)

        Note:
            Schema refresh is expensive (~50-200ms) due to database introspection
            and schema rebuilding. Use sparingly, typically once per test class.
        """
        import importlib
        import json
        import time

        def _replace_graphql_router(
            app: FastAPI, new_schema: GraphQLSchema, refresh_config: dict[str, Any]
        ) -> None:
            """Replace GraphQL router with new schema (internal helper)."""
            from fraiseql.fastapi.routers import create_graphql_router

            # Remove existing GraphQL routes
            original_route_count = len(app.routes)
            app.routes[:] = [
                route
                for route in app.routes
                if not (hasattr(route, "path") and route.path == "/graphql")
            ]
            removed_routes = original_route_count - len(app.routes)
            logger.debug(f"Removed {removed_routes} GraphQL routes")

            # Create and mount new router
            new_router = create_graphql_router(
                schema=new_schema,
                config=refresh_config["config"],
                auth_provider=refresh_config["auth_provider"],
                turbo_registry=app.state.turbo_registry
                if hasattr(app.state, "turbo_registry")
                else None,
            )
            app.include_router(new_router)
            logger.debug("Mounted new GraphQL router")

        if not hasattr(app.state, "_fraiseql_refresh_config"):
            raise RuntimeError(
                "Cannot refresh schema: app not created with create_fraiseql_app(). "
                "Ensure app was created using the standard FraiseQL factory."
            )

        refresh_config = app.state._fraiseql_refresh_config
        logger.info("Starting schema refresh...")
        refresh_start = time.time()

        # Step 1: Clear all caches using utility
        from fraiseql.testing import clear_fraiseql_caches

        clear_fraiseql_caches()

        # Step 2: Get Rust module reference for later use
        _fraiseql_rs = None
        try:
            _fraiseql_rs = importlib.import_module("fraiseql._fraiseql_rs")
        except Exception:
            logger.warning("Rust extension not available")

        # Step 3: Re-run auto-discovery to find new functions
        # Note: We always run auto-discovery during refresh to find dynamically created functions,
        # even if auto_discover was originally disabled
        auto_types: list[type] = []
        auto_queries: list = []
        auto_mutations: list = []

        from fraiseql.fastapi.app import create_db_pool
        from fraiseql.introspection import AutoDiscovery

        logger.debug("Running auto-discovery...")
        # Create a temporary connection pool for auto-discovery
        pool = await create_db_pool(refresh_config["database_url"])
        try:
            discoverer = AutoDiscovery(pool)
            # Use a broad pattern to discover test functions and any other functions
            discovery_result = await discoverer.discover_all(function_pattern="test_%")
            auto_types = discovery_result["types"]
            auto_queries = discovery_result["queries"]
            auto_mutations = discovery_result["mutations"]
            logger.info(
                f"Auto-discovery: {len(auto_types)} types, "
                f"{len(auto_queries)} queries, {len(auto_mutations)} mutations"
            )
        finally:
            await pool.close()

        # Step 4: Rebuild GraphQL schema
        from fraiseql.gql.schema_builder import build_fraiseql_schema

        original_types_sample = (
            refresh_config["original_types"][:3]
            if isinstance(refresh_config["original_types"], list)
            else refresh_config["original_types"]
        )
        logger.debug(
            f"Original types: {type(refresh_config['original_types'])}, "
            f"value: {original_types_sample}"
        )
        logger.debug(f"Auto types: {type(auto_types)}, length: {len(auto_types)}")

        all_query_types = (
            refresh_config["original_types"]
            + refresh_config["original_queries"]
            + auto_types
            + auto_queries
        )
        all_mutations = refresh_config["original_mutations"] + auto_mutations

        new_schema = build_fraiseql_schema(
            query_types=all_query_types,
            mutation_resolvers=all_mutations,
            camel_case_fields=refresh_config["camel_case_fields"],
            # Re-apply the authorizer so it survives hot-reload, re-installing it on the
            # registry slot that the rebuilt resolver wrap and bypass gates read (#362).
            authorizer=refresh_config.get("authorizer"),
        )
        logger.debug(f"Rebuilt schema with {len(new_schema.type_map)} types")

        # Step 5: Reinitialize Rust schema registry
        if refresh_config["enable_schema_registry"] and _fraiseql_rs is not None:
            try:
                from fraiseql.core.schema_serializer import SchemaSerializer

                serializer = SchemaSerializer()
                schema_ir = serializer.serialize_schema(new_schema)
                schema_json = json.dumps(schema_ir)
                _fraiseql_rs.initialize_schema_registry(schema_json)

                # Clear query plan cache when schema changes
                _fraiseql_rs.clear_cache()
                logger.debug("Reinitialized Rust schema registry")
            except Exception as e:
                logger.warning(f"Failed to reinitialize Rust registry: {e}")

        # Step 6: Update app state and clear TurboRegistry
        old_schema = app.state.graphql_schema
        app.state.graphql_schema = new_schema

        if hasattr(app.state, "turbo_registry") and app.state.turbo_registry:
            app.state.turbo_registry.clear()
            logger.debug("Cleared TurboRegistry cache")

        # Step 7: Replace GraphQL router
        _replace_graphql_router(app, new_schema, refresh_config)

        # Validate refresh (development builds only)
        if logger.isEnabledFor(logging.DEBUG):
            from fraiseql.testing import validate_schema_refresh

            try:
                result = validate_schema_refresh(old_schema, new_schema)
                logger.debug(
                    f"Schema validation: {len(result['preserved_types'])} preserved, "
                    f"{len(result['new_types'])} new"
                )
            except AssertionError as e:
                logger.error(f"Schema refresh validation failed: {e}")
                raise

        refresh_duration = (time.time() - refresh_start) * 1000
        logger.info(f"Schema refresh completed in {refresh_duration:.2f}ms")

        return new_schema

    # Attach method to app instance
    app.refresh_schema = refresh_schema

    return app


# Convenience function for creating a production app
def create_production_app(**kwargs: Any) -> FastAPI:
    """Create a production-optimized FraiseQL app.

    This is equivalent to create_fraiseql_app with production=True
    and additional production defaults.
    """
    kwargs.setdefault("production", True)

    # Override config for production
    if "config" in kwargs:
        kwargs["config"].environment = "production"
        kwargs["config"].enable_introspection = False
        kwargs["config"].enable_playground = False

    return create_fraiseql_app(**kwargs)


# Import to avoid circular dependency


def get_global_turbo_registry() -> TurboRegistry | None:
    """Get the global turbo registry if available."""
    return _global_turbo_registry

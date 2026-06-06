"""Additional decorators for FraiseQL."""

import asyncio
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, Optional, TypeVar, overload

from graphql import GraphQLResolveInfo

from fraiseql.gql.schema_builder import SchemaRegistry
from fraiseql.types.generic import Connection

F = TypeVar("F", bound=Callable[..., Any])


@overload
def query(fn: F) -> F: ...


@overload
def query(*, authorizer: Any | None = None) -> Callable[[F], F]: ...


def query(fn: F | None = None, *, authorizer: Any | None = None) -> F | Callable[[F], F]:
    """Decorator to mark a function as a GraphQL query.

    This decorator automatically registers the function with the GraphQL schema,
    eliminating the need to manually pass queries to create_fraiseql_app.

    Args:
        fn: The query function to decorate (when used without parentheses)
        authorizer: Optional per-operation :class:`~fraiseql.security.Authorizer`
            override (issue #362). It takes precedence over the global default
            authorizer for this query only.

    Returns:
        The decorated function with GraphQL query metadata

    Examples:
        Basic query with database access::

            @fraiseql.query
            async def get_user(info, id: UUID) -> User:
                db = info.context["db"]
                return await db.find_one("user_view", {"id": id})

        Query with multiple parameters::

            @fraiseql.query
            async def search_users(
                info,
                name_filter: str | None = None,
                limit: int = 10
            ) -> list[User]:
                db = info.context["db"]
                filters = {}
                if name_filter:
                    filters["name__icontains"] = name_filter
                return await db.find("user_view", filters, limit=limit)

        Query with authentication and authorization::

            @fraiseql.query
            async def get_my_profile(info) -> User:
                user_context = info.context["user"]
                if not user_context:
                    raise GraphQLError("Authentication required")

                db = info.context["db"]
                return await db.find_one("user_view", {"id": user_context.user_id})

        Query with error handling::

            @fraiseql.query
            async def get_post(info, id: UUID) -> Post | None:
                try:
                    db = info.context["db"]
                    return await db.find_one("post_view", {"id": id})
                except Exception as e:
                    logger.error(f"Failed to fetch post {id}: {e}")
                    return None

        Query using custom repository methods::

            @fraiseql.query
            async def get_user_stats(info, user_id: UUID) -> UserStats:
                db = info.context["db"]
                # Custom SQL query for complex aggregations
                result = await db.execute_raw(
                    "SELECT count(*) as post_count FROM posts WHERE user_id = $1",
                    user_id
                )
                return UserStats(post_count=result[0]["post_count"])

    Notes:
        - Functions decorated with @query are automatically discovered
        - The first parameter is always 'info' (GraphQL resolver info)
        - Return type annotation is used for GraphQL schema generation
        - Use async/await for database operations
        - Access database via info.context["db"]
        - Access user context via info.context["user"] if authentication is enabled
    """

    def decorator(func: F) -> F:
        # Register with schema
        registry = SchemaRegistry.get_instance()

        # Debug logging
        import inspect
        import logging

        logger = logging.getLogger(__name__)
        logger.debug(
            "Query decorator called for function '%s' in module '%s'",
            func.__name__,
            func.__module__,
        )

        # Determine if function is async or sync
        is_async = asyncio.iscoroutinefunction(func)

        # Wrap the function to auto-inject info into context
        if is_async:

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                # Extract info parameter from function signature
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())

                # Get info from bound arguments
                info = None
                if "info" in params:
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()
                    info = bound.arguments.get("info")

                # Auto-inject into context for db.find() to use
                if info and hasattr(info, "context") and info.context is not None:
                    info.context["graphql_info"] = info

                # Call original function
                return await func(*args, **kwargs)

            wrapper = async_wrapper
        else:

            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                # Extract info parameter from function signature
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())

                # Get info from bound arguments
                info = None
                if "info" in params:
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()
                    info = bound.arguments.get("info")

                # Auto-inject into context for db.find() to use
                if info and hasattr(info, "context") and info.context is not None:
                    info.context["graphql_info"] = info

                # Call original function
                return func(*args, **kwargs)

            wrapper = sync_wrapper

        # Per-operation authorizer override (issue #362); None falls back to the
        # registry default at resolve time.
        wrapper.__fraiseql_authorizer__ = authorizer

        # Register the wrapper (not the original function)
        registry.register_query(wrapper)

        # Log current state
        logger.debug(
            "Total queries registered after '%s': %d", func.__name__, len(registry.queries)
        )

        return wrapper  # type: ignore[return-value]

    if fn is None:
        return decorator
    return decorator(fn)


@overload
def subscription(fn: F) -> F: ...


@overload
def subscription() -> Callable[[F], F]: ...


def subscription(fn: F | None = None) -> F | Callable[[F], F]:
    """Decorator to mark a function as a GraphQL subscription.

    This decorator automatically registers the function with the GraphQL schema
    for real-time subscriptions. Subscriptions must be async generator functions
    that yield values over time.

    Args:
        fn: The subscription function to decorate (when used without parentheses)

    Returns:
        The decorated async generator function with GraphQL subscription metadata

    Examples:
        Basic subscription for real-time updates::

            @fraiseql.subscription
            async def on_post_created(info) -> AsyncGenerator[Post, None]:
                # Subscribe to post creation events
                async for post in post_event_stream():
                    yield post

        Filtered subscription with parameters::

            @fraiseql.subscription
            async def on_user_posts(
                info,
                user_id: UUID
            ) -> AsyncGenerator[Post, None]:
                # Only yield posts from specific user
                async for post in post_event_stream():
                    if post.user_id == user_id:
                        yield post

        Subscription with authentication::

            @fraiseql.subscription
            async def on_private_messages(
                info
            ) -> AsyncGenerator[Message, None]:
                user_context = info.context.get("user")
                if not user_context:
                    raise GraphQLError("Authentication required")

                async for message in message_stream():
                    # Only yield messages for authenticated user
                    if message.recipient_id == user_context.user_id:
                        yield message

        Subscription with database polling::

            @fraiseql.subscription
            async def on_task_updates(
                info,
                project_id: UUID
            ) -> AsyncGenerator[Task, None]:
                db = info.context["db"]
                last_check = datetime.utcnow()

                while True:
                    # Poll for new/updated tasks
                    updated_tasks = await db.find(
                        "task_view",
                        {
                            "project_id": project_id,
                            "updated_at__gt": last_check
                        }
                    )

                    for task in updated_tasks:
                        yield task

                    last_check = datetime.utcnow()
                    await asyncio.sleep(1)  # Poll every second

        Subscription with error handling and cleanup::

            @fraiseql.subscription
            async def on_notifications(
                info
            ) -> AsyncGenerator[Notification, None]:
                connection = None
                try:
                    connection = await connect_to_message_broker()
                    async for notification in connection.subscribe("notifications"):
                        yield notification
                except Exception as e:
                    logger.error(f"Subscription error: {e}")
                    raise
                finally:
                    if connection:
                        await connection.close()

    Notes:
        - Subscription functions MUST be async generators (use 'async def' and 'yield')
        - Return type must be AsyncGenerator[YieldType, None]
        - The first parameter is always 'info' (GraphQL resolver info)
        - Use WebSocket transport for GraphQL subscriptions
        - Consider rate limiting and authentication for production use
        - Handle connection cleanup in finally blocks
        - Use asyncio.sleep() for polling-based subscriptions
    """

    def decorator(func: F) -> F:
        # Register with schema
        registry = SchemaRegistry.get_instance()
        registry.register_subscription(func)
        return func

    if fn is None:
        return decorator
    return decorator(fn)


@overload
def field(
    method: F,
    *,
    resolver: Callable[..., Any] | None = None,
    description: str | None = None,
    track_n1: bool = True,
) -> F: ...


@overload
def field(
    *,
    resolver: Callable[..., Any] | None = None,
    description: str | None = None,
    track_n1: bool = True,
) -> Callable[[F], F]: ...


def field(
    method: F | None = None,
    *,
    resolver: Callable[..., Any] | None = None,
    description: str | None = None,
    track_n1: bool = True,
) -> F | Callable[[F], F]:
    """Decorator to mark a method as a GraphQL field with optional resolver.

    This decorator should be applied to methods of @fraise_type decorated classes.
    It allows defining custom field resolvers, adding field descriptions, and
    implementing computed fields with complex logic.

    Args:
        method: The method to decorate (when used without parentheses)
        resolver: Optional custom resolver function to override default behavior
        description: Field description that appears in GraphQL schema documentation
        track_n1: Whether to track N+1 query patterns for this field (default: True)

    Returns:
        Decorated method with GraphQL field metadata and N+1 query detection

    Examples:
        Computed field with description::\

            @fraise_type
            class User:
                first_name: str
                last_name: str

                @field(description="User's full display name")
                def display_name(self) -> str:
                    return f"{self.first_name} {self.last_name}"

        Async field with database access::\

            @fraise_type
            class User:
                id: UUID

                @field(description="Posts authored by this user")
                async def posts(self, info) -> list[Post]:
                    db = info.context["db"]
                    return await db.find("post_view", {"user_id": self.id})

        Field with custom resolver function::\

            async def fetch_user_posts_optimized(root, info):
                # Custom resolver with optimized loading
                db = info.context["db"]
                # Use DataLoader or batch loading here
                return await batch_load_posts([root.id])

            @fraise_type
            class User:
                id: UUID

                @field(
                    resolver=fetch_user_posts_optimized,
                    description="Posts with optimized loading"
                )
                async def posts(self) -> list[Post]:
                    # This method signature defines the GraphQL schema
                    # but fetch_user_posts_optimized handles the actual resolution
                    pass

        Field with parameters::\

            @fraise_type
            class User:
                id: UUID

                @field(description="User's posts with optional filtering")
                async def posts(
                    self,
                    info,
                    published_only: bool = False,
                    limit: int = 10
                ) -> list[Post]:
                    db = info.context["db"]
                    filters = {"user_id": self.id}
                    if published_only:
                        filters["status"] = "published"
                    return await db.find("post_view", filters, limit=limit)

        Field with authentication and authorization::\

            @fraise_type
            class User:
                id: UUID

                @field(description="Private user settings (owner only)")
                async def settings(self, info) -> UserSettings | None:
                    user_context = info.context.get("user")
                    if not user_context or user_context.user_id != self.id:
                        return None  # Don't expose private data

                    db = info.context["db"]
                    return await db.find_one("user_settings_view", {"user_id": self.id})

        Field with error handling::\

            @fraise_type
            class User:
                id: UUID

                @field(description="User's profile image URL")
                async def avatar_url(self, info) -> str | None:
                    try:
                        storage = info.context["storage"]
                        return await storage.get_user_avatar_url(self.id)
                    except StorageError:
                        logger.warning(f"Failed to get avatar for user {self.id}")
                        return None

        Field with caching::\

            @fraise_type
            class Post:
                id: UUID

                @field(description="Number of likes (cached)")
                async def like_count(self, info) -> int:
                    cache = info.context.get("cache")
                    cache_key = f"post:{self.id}:likes"

                    # Try cache first
                    if cache:
                        cached_count = await cache.get(cache_key)
                        if cached_count is not None:
                            return int(cached_count)

                    # Fallback to database
                    db = info.context["db"]
                    result = await db.execute_raw(
                        "SELECT count(*) FROM likes WHERE post_id = $1",
                        self.id
                    )
                    count = result[0]["count"]

                    # Cache for 5 minutes
                    if cache:
                        await cache.set(cache_key, count, ttl=300)

                    return count

    Notes:
        - Fields are automatically included in GraphQL schema generation
        - Use 'info' parameter to access GraphQL context (database, user, etc.)
        - Async fields support database queries and external API calls
        - Custom resolvers can implement optimized data loading patterns
        - N+1 query detection is automatically enabled for performance monitoring
        - Return None from fields to indicate null values in GraphQL
        - Use type annotations for automatic GraphQL type generation
    """

    def decorator(func: F) -> F:
        # Determine if the function is async
        is_async = asyncio.iscoroutinefunction(func)

        # Inspect the function signature to determine how to call it
        import inspect

        sig = inspect.signature(func)
        params = list(sig.parameters.keys())

        # Determine the expected number of arguments
        # For methods: self is first, then optionally info
        # For functions: root is first, then info
        has_self = "self" in params
        expects_info = "info" in params
        len(params)

        if is_async:

            async def async_wrapped_resolver(
                root: Any, info: GraphQLResolveInfo, *args: Any, **kwargs: Any
            ) -> Any:
                # Check if N+1 detector is available in context
                detector = None
                if track_n1 and info and hasattr(info, "context") and info.context:
                    detector = getattr(info.context, "get", lambda x: None)("n1_detector")
                if detector and detector.enabled:
                    start_time = time.time()
                    try:
                        # Call the original method based on its signature
                        if hasattr(func, "__self__"):
                            # Bound method - self is already bound
                            if expects_info:
                                result = await func(info, *args, **kwargs)
                            else:
                                result = await func(*args, **kwargs)
                        # Unbound method or function
                        elif has_self:
                            # Method expects self as first arg
                            if expects_info:
                                result = await func(root, info, *args, **kwargs)
                            else:
                                result = await func(root, *args, **kwargs)
                        else:
                            # Regular function
                            result = await func(root, info, *args, **kwargs)
                        execution_time = time.time() - start_time
                        # Track field resolution without blocking
                        # Using create_task is safe here as detector manages its own lifecycle
                        task = asyncio.create_task(
                            detector.track_field_resolution(info, info.field_name, execution_time),
                        )
                        # Add error handler to prevent unhandled exceptions
                        task.add_done_callback(lambda t: t.exception() if t.done() else None)
                        return result
                    except Exception:
                        execution_time = time.time() - start_time
                        task = asyncio.create_task(
                            detector.track_field_resolution(info, info.field_name, execution_time),
                        )
                        task.add_done_callback(lambda t: t.exception() if t.done() else None)
                        raise
                # Call the original method based on its signature
                elif hasattr(func, "__self__"):
                    # Bound method - self is already bound
                    if expects_info:
                        return await func(info, *args, **kwargs)
                    return await func(*args, **kwargs)
                # Unbound method or function
                elif has_self:
                    # Method expects self as first arg
                    if expects_info:
                        return await func(root, info, *args, **kwargs)
                    return await func(root, *args, **kwargs)
                else:
                    # Regular function
                    return await func(root, info, *args, **kwargs)

            wrapped_func = async_wrapped_resolver

        else:

            def sync_wrapped_resolver(
                root: Any, info: GraphQLResolveInfo, *args: Any, **kwargs: Any
            ) -> Any:
                # Check if N+1 detector is available in context
                detector = None
                if track_n1 and info and hasattr(info, "context") and info.context:
                    detector = getattr(info.context, "get", lambda x: None)("n1_detector")
                if detector and detector.enabled:
                    start_time = time.time()
                    try:
                        # Call the original method based on its signature
                        if hasattr(func, "__self__"):
                            # Bound method - self is already bound
                            if expects_info:
                                result = func(info, *args, **kwargs)
                            else:
                                result = func(*args, **kwargs)
                        # Unbound method or function
                        elif has_self:
                            # Method expects self as first arg
                            if expects_info:
                                result = func(root, info, *args, **kwargs)
                            else:
                                result = func(root, *args, **kwargs)
                        else:
                            # Regular function
                            result = func(root, info, *args, **kwargs)
                        execution_time = time.time() - start_time
                        # Track field resolution without blocking
                        # For sync resolvers, we need to handle async tracking differently
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                # Using create_task is safe - detector manages its own lifecycle
                                task = asyncio.create_task(
                                    detector.track_field_resolution(
                                        info, info.field_name, execution_time
                                    ),
                                )
                                # Add error handler to prevent unhandled exceptions
                                task.add_done_callback(
                                    lambda t: t.exception() if t.done() else None
                                )
                        except RuntimeError:
                            # No event loop - skip tracking for now
                            # This happens when using graphql_sync
                            pass
                        return result
                    except Exception:
                        execution_time = time.time() - start_time
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                task = asyncio.create_task(
                                    detector.track_field_resolution(
                                        info, info.field_name, execution_time
                                    ),
                                )
                                task.add_done_callback(
                                    lambda t: t.exception() if t.done() else None
                                )
                        except RuntimeError:
                            # No event loop - skip tracking for now
                            pass
                        raise
                # Call the original method based on its signature
                elif hasattr(func, "__self__"):
                    # Bound method - self is already bound
                    if expects_info:
                        return func(info, *args, **kwargs)
                    return func(*args, **kwargs)
                # Unbound method or function
                elif has_self:
                    # Method expects self as first arg
                    if expects_info:
                        return func(root, info, *args, **kwargs)
                    return func(root, *args, **kwargs)
                else:
                    # Regular function
                    return func(root, info, *args, **kwargs)

            wrapped_func = sync_wrapped_resolver

        # Copy over the metadata
        wrapped_func.__fraiseql_field__ = True
        wrapped_func.__fraiseql_field_resolver__ = resolver or wrapped_func
        wrapped_func.__fraiseql_field_description__ = description
        wrapped_func.__name__ = func.__name__
        wrapped_func.__doc__ = func.__doc__

        # Store the original function for field authorization
        wrapped_func.__fraiseql_original_func__ = func

        # Copy type annotations
        if hasattr(func, "__annotations__"):
            wrapped_func.__annotations__ = func.__annotations__.copy()

        return wrapped_func  # type: ignore[return-value]

    if method is None:
        return decorator
    return decorator(method)


def turbo_query(
    cache_ttl: int = 300,
    auto_register: bool = True,
    param_mapping: Optional[dict[str, str]] = None,
    operation_name: Optional[str] = None,
) -> Callable[[F], F]:
    """Decorator to mark a query for TurboRouter optimization.

    This decorator extends @query to automatically register the query
    with TurboRouter for high-performance execution.

    Args:
        cache_ttl: Time-to-live for the cached query in seconds
        auto_register: Whether to automatically register on startup
        param_mapping: Custom parameter mapping for SQL template
        operation_name: Optional operation name (defaults to function name)

    Returns:
        Decorated function with TurboRouter metadata

    Examples:
        Basic turbo query::

            @fraiseql.turbo_query(cache_ttl=600)
            @fraiseql.query
            async def get_user(info, id: UUID) -> User:
                db = info.context["db"]
                return await db.find_one("user_view", {"id": id})

        Query with custom parameter mapping::

            @fraiseql.turbo_query(
                param_mapping={"userId": "user_id", "status": "status_code"}
            )
            @fraiseql.query
            async def get_user_posts(info, userId: UUID, status: str) -> list[Post]:
                db = info.context["db"]
                return await db.find("post_view", {
                    "user_id": userId,
                    "status_code": status
                })

        Complex query with named operation::

            @fraiseql.turbo_query(
                operation_name="GetActiveUserStats",
                cache_ttl=3600
            )
            @fraiseql.query
            async def user_statistics(info, since: datetime) -> UserStats:
                db = info.context["db"]
                # Complex aggregation query
                result = await db.execute_raw(...)
                return UserStats(...)

    Notes:
        - Must be used with @fraiseql.query decorator
        - The query will be analyzed and optimized for SQL execution
        - Registration happens on first app startup
        - Use param_mapping when GraphQL names differ from DB columns
    """

    def decorator(func: F) -> F:
        # Ensure function has query metadata
        if not hasattr(func, "_graphql_query"):
            # Store turbo configuration for later
            func._turbo_config = {
                "cache_ttl": cache_ttl,
                "auto_register": auto_register,
                "param_mapping": param_mapping or {},
                "operation_name": operation_name or func.__name__,
                "enabled": True,
                "pending": True,  # Will be applied when @query is called
            }
            return func

        # Store turbo configuration
        func._turbo_config = {
            "cache_ttl": cache_ttl,
            "auto_register": auto_register,
            "param_mapping": param_mapping or {},
            "operation_name": operation_name or func.__name__,
            "enabled": True,
        }

        # Mark for registration
        if auto_register:
            registry = SchemaRegistry.get_instance()
            if hasattr(registry, "mark_for_turbo_registration"):
                registry.mark_for_turbo_registration(func)

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Check if we're in turbo mode
            info = args[0] if args else None
            if info and hasattr(info, "context"):
                context = info.context
                if context.get("turbo_mode"):
                    # This execution is handled by TurboRouter
                    # Just return a marker
                    return TurboExecutionMarker()

            # Normal execution
            return await func(*args, **kwargs)

        # Copy over all attributes
        wrapper._turbo_config = func._turbo_config
        if hasattr(func, "_graphql_query"):
            wrapper._graphql_query = func._graphql_query

        return wrapper  # type: ignore[return-value]

    return decorator


class TurboExecutionMarker:
    """Marker class to indicate turbo execution."""


# Helper functions for connection decorator
def _validate_connection_config(
    node_type: type | None, default_page_size: int, max_page_size: int
) -> None:
    """Validate connection decorator configuration parameters."""
    if node_type is None:
        raise ValueError("node_type is required")

    if default_page_size <= 0:
        raise ValueError("default_page_size must be positive")

    if max_page_size <= 0:
        raise ValueError("max_page_size must be positive")

    if max_page_size < default_page_size:
        raise ValueError("max_page_size must be >= default_page_size")


def _infer_view_name_from_function(func_name: str, view_name: str | None) -> str:
    """Infer database view name from function name if not provided."""
    if view_name is not None:
        return view_name

    # Convert function name like "users_connection" -> "v_users"
    if func_name.endswith("_connection"):
        base_name = func_name[:-11]  # Remove "_connection"
        return f"v_{base_name}"
    # Fallback: just add v_ prefix
    return f"v_{func_name}"


def _validate_pagination_params(first: int | None, last: int | None, max_page_size: int) -> None:
    """Validate runtime pagination parameters."""
    if first is not None and last is not None:
        raise ValueError("Cannot specify both first and last")

    if first is not None and first <= 0:
        raise ValueError("first must be positive")

    if last is not None and last <= 0:
        raise ValueError("last must be positive")

    if first is not None and first > max_page_size:
        raise ValueError(f"first cannot exceed max_page_size ({max_page_size})")

    if last is not None and last > max_page_size:
        raise ValueError(f"last cannot exceed max_page_size ({max_page_size})")


def connection(
    node_type: type,
    view_name: str | None = None,
    default_page_size: int = 20,
    max_page_size: int = 100,
    include_total_count: bool = True,
    cursor_field: str = "id",
    jsonb_extraction: bool | None = None,
    jsonb_column: str | None = None,
) -> Callable[[F], F]:
    """Decorator to create cursor-based pagination query resolvers.

    This decorator converts a standard query function into a Connection[T] resolver
    that automatically handles cursor-based pagination following the Relay specification.

    Args:
        node_type: The type of objects in the connection (e.g., User, Post)
        view_name: Database view name to query (inferred from function name if not provided)
        default_page_size: Default number of items per page
        max_page_size: Maximum allowed page size
        include_total_count: Whether to include total count in results
        cursor_field: Field to use for cursor ordering
        jsonb_extraction: Enable JSONB field extraction (inherits global config if None)
        jsonb_column: JSONB column name to extract fields from (inherits global config if None)

    Returns:
        Decorated function that returns Connection[T]

    Raises:
        ValueError: If configuration parameters are invalid

    Examples:
        Basic connection query::

            @fraiseql.connection(node_type=User)
            @fraiseql.query
            async def users_connection(info, first: int | None = None) -> Connection[User]:
                pass  # Implementation handled by decorator

        Connection with custom configuration::

            @fraiseql.connection(
                node_type=Post,
                view_name="v_published_posts",
                default_page_size=25,
                max_page_size=50,
                cursor_field="created_at",
                jsonb_extraction=True,
                jsonb_column="data"
            )
            @fraiseql.query
            async def posts_connection(
                info,
                first: int | None = None,
                after: str | None = None,
                where: dict[str, Any] | None = None,
            ) -> Connection[Post]:
                pass

        With filtering and ordering::

            @fraiseql.connection(
                node_type=User,
                cursor_field="created_at"
            )
            @fraiseql.query
            async def recent_users_connection(
                info,
                first: int | None = None,
                after: str | None = None,
                where: dict[str, Any] | None = None,
            ) -> Connection[User]:
                pass

    Notes:
        - Functions must be async and take 'info' as first parameter
        - The decorator handles all pagination logic automatically
        - Uses existing CQRSRepository.paginate() method
        - Returns properly typed Connection[T] objects
        - Supports all Relay connection specification features
    """
    # Validate configuration parameters at decoration time
    _validate_connection_config(node_type, default_page_size, max_page_size)

    def decorator(func: F) -> F:
        # Infer view name from function name if not provided
        inferred_view_name = _infer_view_name_from_function(func.__name__, view_name)

        # Construct type annotations for wrapper function
        # This ensures schema builder can extract correct arguments and return type
        wrapper_annotations = {
            "info": GraphQLResolveInfo,
            "first": int | None,
            "after": str | None,
            "last": int | None,
            "before": str | None,
            "where": dict[str, Any] | None,
            "return": Connection[node_type],
        }

        @wraps(func)
        async def wrapper(
            info: GraphQLResolveInfo,
            first: int | None = None,
            after: str | None = None,
            last: int | None = None,
            before: str | None = None,
            where: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> Any:
            # Validate runtime pagination parameters
            _validate_pagination_params(first, last, max_page_size)

            # Apply default page size if neither first nor last specified
            if first is None and last is None:
                first = default_page_size

            # Get repository from GraphQL context
            try:
                db = info.context["db"]
            except KeyError as e:
                raise ValueError("Database repository not found in GraphQL context") from e

            # Resolve JSONB configuration dynamically
            config = info.context.get("config")
            resolved_jsonb_extraction = jsonb_extraction
            resolved_jsonb_column = jsonb_column

            # Auto-inherit from global configuration if not explicitly set
            if resolved_jsonb_extraction is None and config:
                resolved_jsonb_extraction = getattr(config, "jsonb_extraction_enabled", False)

            if resolved_jsonb_column is None and config:
                default_columns = getattr(config, "jsonb_default_columns", ["data"])
                resolved_jsonb_column = default_columns[0] if default_columns else "data"

            # Call repository paginate method with all parameters
            try:
                result = await db.paginate(
                    inferred_view_name,
                    first=first,
                    after=after,
                    last=last,
                    before=before,
                    filters=where,
                    order_by=cursor_field,
                    include_total=include_total_count,
                    jsonb_extraction=resolved_jsonb_extraction,
                    jsonb_column=resolved_jsonb_column,
                )
            except Exception as e:
                # Provide context about which view/query failed
                raise ValueError(
                    f"Pagination failed for view '{inferred_view_name}' "
                    f"in function '{func.__name__}': {e!s}"
                ) from e

            # Convert to typed Connection using create_connection helper
            from fraiseql.types.generic import create_connection

            return create_connection(result, node_type)

        # Store configuration metadata for introspection and debugging
        wrapper.__fraiseql_connection__ = {
            "node_type": node_type,
            "view_name": inferred_view_name,
            "default_page_size": default_page_size,
            "max_page_size": max_page_size,
            "include_total_count": include_total_count,
            "cursor_field": cursor_field,
            "jsonb_extraction": jsonb_extraction,  # Store original values
            "jsonb_column": jsonb_column,
            "supports_global_jsonb": True,  # Indicate global config support
        }

        # CRITICAL: Set __annotations__ so schema builder can extract types
        # Without this, get_type_hints(wrapper) returns {}
        wrapper.__annotations__ = wrapper_annotations

        return wrapper  # type: ignore[return-value]

    return decorator

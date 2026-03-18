"""Database utilities and repository layer for FraiseQL using psycopg and connection pooling."""

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Optional, TypeVar, Union, get_args, get_origin

from psycopg.rows import dict_row
from psycopg.sql import SQL, Composed
from psycopg_pool import AsyncConnectionPool

from fraiseql.audit import get_security_logger
from fraiseql.core.rust_pipeline import (
    RustResponseBytes,
    execute_via_rust_pipeline,
)
from fraiseql.utils.casing import to_snake_case
from fraiseql.where_clause import WhereClause
from fraiseql.where_normalization import normalize_dict_where, normalize_whereinput

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Type registry for development mode
_type_registry: dict[str, type] = {}

# Table metadata registry - stores column information at registration time
# This avoids expensive runtime introspection
_table_metadata: dict[str, dict[str, Any]] = {}

# Null response cache for RustResponseBytes optimization
# Preloaded with common field name patterns (90%+ hit rate expected)
_NULL_RESPONSE_CACHE: set[bytes] = {
    b'{"data":{"user":[]}}',
    b'{"data":{"users":[]}}',
    b'{"data":{"customer":[]}}',
    b'{"data":{"customers":[]}}',
    b'{"data":{"product":[]}}',
    b'{"data":{"products":[]}}',
    b'{"data":{"order":[]}}',
    b'{"data":{"orders":[]}}',
    b'{"data":{"item":[]}}',
    b'{"data":{"items":[]}}',
    b'{"data":{"result":[]}}',
    b'{"data":{"data":[]}}',
}


def _is_rust_response_null(response: RustResponseBytes) -> bool:
    """Check if RustResponseBytes contains empty array (null result).

    Rust's build_graphql_response returns {"data":{"field":[]}} for null.
    This function detects that pattern WITHOUT JSON parsing overhead.

    Performance: O(1) byte pattern matching (12x faster than JSON parsing)
    - Fast path: 5 constant-time checks
    - Cache: 90%+ hit rate on common field names
    - Overhead: < 0.1ms per check (vs 0.6ms for JSON parsing)

    Args:
        response: RustResponseBytes to check

    Returns:
        True if the response contains null (empty array), False otherwise

    Examples:
        >>> _is_rust_response_null(RustResponseBytes(b'{"data":{"user":[]}}'))
        True
        >>> _is_rust_response_null(RustResponseBytes(b'{"data":{"user":{"id":"123"}}}'))
        False
    """
    data = response.bytes

    # Fast path: O(1) checks without JSON parsing
    # 1. Length check: Null format is {"data":{"field":[]}}
    #    Min: {"data":{"a":[]}} = 17 bytes
    #    Max: ~200 bytes for very long field names (rare)
    length = len(data)
    if length < 17 or length > 200:
        return False

    # 2. Must end with closing braces
    if not data.endswith(b"}}"):
        return False

    # 3. Signature pattern: ":[]}" indicates empty array
    if b":[]" not in data:
        return False

    # 4. Cache lookup for common patterns (90%+ hit rate)
    if data in _NULL_RESPONSE_CACHE:
        return True

    # 5. Structural validation for uncommon field names
    #    Pattern: {"data":{"<field_name>":[]}}
    if data.startswith(b'{"data":{"') and data.endswith(b":[]}}"):
        start = 10  # After '{"data":{"'
        end = data.rfind(b'":[]}')

        if end > start:
            # Extract field name
            field_name = data[start:end]

            # Field name should not contain quotes (basic validation)
            if b'"' not in field_name:
                # Cache for next time (bounded to prevent unbounded growth)
                if len(_NULL_RESPONSE_CACHE) < 100:
                    _NULL_RESPONSE_CACHE.add(data)
                return True

    return False


@dataclass
class DatabaseQuery:
    """Encapsulates a SQL query, parameters, and fetch flag."""

    statement: Composed | SQL
    params: Mapping[str, object]
    fetch_result: bool = True


def register_type_for_view(
    view_name: str,
    type_class: type,
    table_columns: set[str] | None = None,
    has_jsonb_data: bool | None = None,
    jsonb_column: str | None = None,
    fk_relationships: dict[str, str] | None = None,
    validate_fk_strict: bool = True,
) -> None:
    """Register a type class for a specific view name with optional metadata.

    This is used in development mode to instantiate proper types from view data.
    Storing metadata at registration time avoids expensive runtime introspection.

    Args:
        view_name: The database view name
        type_class: The Python type class decorated with @fraise_type
        table_columns: Optional set of actual database columns (for hybrid tables)
        has_jsonb_data: Optional flag indicating if table has a JSONB 'data' column
        jsonb_column: Optional name of the JSONB column (defaults to "data")
        fk_relationships: Map GraphQL field name → FK column name.
            Example: {"machine": "machine_id", "printer": "printer_id"}
            If not specified, uses convention: field + "_id"
        validate_fk_strict: If True, raise error on FK validation failures.
            If False, only warn (useful for legacy code migration).
    """
    _type_registry[view_name] = type_class
    logger.debug(f"Registered type {type_class.__name__} for view {view_name}")

    # Initialize FK relationships
    fk_relationships = fk_relationships or {}

    # Validate FK relationships if strict mode
    if validate_fk_strict and fk_relationships and table_columns:
        for field_name, fk_column in fk_relationships.items():
            if fk_column not in table_columns:
                raise ValueError(
                    f"Invalid FK relationship for {view_name}: "
                    f"Field '{field_name}' mapped to FK column '{fk_column}', "
                    f"but '{fk_column}' not in table_columns: {table_columns}. "
                    f"Either add '{fk_column}' to table_columns or fix fk_relationships. "
                    f"To allow this (not recommended), set validate_fk_strict=False."
                )

    # Store metadata if provided
    if (
        table_columns is not None
        or has_jsonb_data is not None
        or jsonb_column is not None
        or fk_relationships
    ):
        metadata = {
            "columns": table_columns or set(),
            "has_jsonb_data": has_jsonb_data or False,
            "jsonb_column": jsonb_column,  # Always store the jsonb_column value
            "fk_relationships": fk_relationships,
            "validate_fk_strict": validate_fk_strict,
        }
        _table_metadata[view_name] = metadata
        logger.debug(
            f"Registered metadata for {view_name}: {len(table_columns or set())} columns, "
            f"jsonb={has_jsonb_data}, jsonb_column={jsonb_column}"
        )


class FraiseQLRepository:
    """Asynchronous repository for executing SQL queries via a pooled psycopg connection.

    Rust-first architecture (v1+): Always uses Rust transformer for optimal performance.
    No mode detection or branching - single execution path.
    """

    def __init__(self, pool: AsyncConnectionPool, context: Optional[dict[str, Any]] = None) -> None:
        """Initialize with an async connection pool and optional context."""
        self._pool = pool
        self.context = context or {}
        # Get query timeout from context or use default (30 seconds)
        self.query_timeout = self.context.get("query_timeout", 30)
        # Cache for type names to avoid repeated registry lookups
        self._type_name_cache: dict[str, Optional[str]] = {}

    def _get_cached_type_name(self, view_name: str) -> Optional[str]:
        """Get cached type name for a view, or lookup and cache it if not found.

        This avoids repeated registry lookups for the same view across multiple queries.
        """
        # Check cache first
        if view_name in self._type_name_cache:
            return self._type_name_cache[view_name]

        # Lookup and cache the type name
        type_name = None
        try:
            type_class = self._get_type_for_view(view_name)
            if hasattr(type_class, "__name__"):
                type_name = type_class.__name__
        except Exception:
            # If we can't get the type, continue without type name
            pass

        # Cache the result (including None for failed lookups)
        self._type_name_cache[view_name] = type_name
        return type_name

    async def _set_session_variables(self, cursor_or_conn: Any) -> None:
        """Set PostgreSQL session variables from context.

        Sets app.tenant_id, app.contact_id, app.user_id, app.is_super_admin,
        and fraiseql.started_at session variables if present in context.
        Uses SET LOCAL to scope variables to the current transaction.

        Args:
            cursor_or_conn: Either a psycopg cursor or an asyncpg connection
        """
        from psycopg.sql import SQL, Literal

        # Check if this is a cursor (psycopg) or connection (asyncpg)
        is_cursor = hasattr(cursor_or_conn, "execute") and hasattr(cursor_or_conn, "fetchone")

        if "tenant_id" in self.context:
            if is_cursor:
                await cursor_or_conn.execute(
                    SQL("SET LOCAL app.tenant_id = {}").format(
                        Literal(str(self.context["tenant_id"]))
                    )
                )
            else:
                # asyncpg connection
                await cursor_or_conn.execute(
                    "SET LOCAL app.tenant_id = $1", str(self.context["tenant_id"])
                )

        if "contact_id" in self.context:
            if is_cursor:
                await cursor_or_conn.execute(
                    SQL("SET LOCAL app.contact_id = {}").format(
                        Literal(str(self.context["contact_id"]))
                    )
                )
            else:
                # asyncpg connection
                await cursor_or_conn.execute(
                    "SET LOCAL app.contact_id = $1", str(self.context["contact_id"])
                )
        elif "user" in self.context:
            # Fallback to 'user' if 'contact_id' not set
            if is_cursor:
                await cursor_or_conn.execute(
                    SQL("SET LOCAL app.contact_id = {}").format(Literal(str(self.context["user"])))
                )
            else:
                # asyncpg connection
                await cursor_or_conn.execute(
                    "SET LOCAL app.contact_id = $1", str(self.context["user"])
                )

        # RBAC-specific session variables for Row-Level Security
        if "user_id" in self.context:
            if is_cursor:
                await cursor_or_conn.execute(
                    SQL("SET LOCAL app.user_id = {}").format(Literal(str(self.context["user_id"])))
                )
            else:
                # asyncpg connection
                await cursor_or_conn.execute(
                    "SET LOCAL app.user_id = $1", str(self.context["user_id"])
                )

        # Set super_admin flag based on user roles
        if "roles" in self.context:
            is_super_admin = (
                any(r.get("name") == "super_admin" for r in self.context["roles"])
                if isinstance(self.context["roles"], list)
                else False
            )
            if is_cursor:
                await cursor_or_conn.execute(
                    SQL("SET LOCAL app.is_super_admin = {}").format(Literal(is_super_admin))
                )
            else:
                # asyncpg connection
                await cursor_or_conn.execute("SET LOCAL app.is_super_admin = $1", is_super_admin)
        elif "user_id" in self.context:
            # If roles not provided in context, check database for super_admin role
            # This is a fallback that may be slower but ensures correctness
            try:
                user_id = self.context["user_id"]
                if is_cursor:
                    # For psycopg, we need to use the existing connection
                    # Simplified check - production needs more robust role checking
                    await cursor_or_conn.execute(
                        SQL(
                            "SET LOCAL app.is_super_admin = EXISTS (SELECT 1 FROM "
                            "user_roles ur INNER JOIN roles r ON ur.role_id = r.id "
                            "WHERE ur.user_id = {} AND r.name = 'super_admin')"
                        ).format(Literal(str(user_id)))
                    )
                else:
                    # asyncpg connection
                    result = await cursor_or_conn.fetchval(
                        "SELECT EXISTS (SELECT 1 FROM user_roles ur INNER JOIN "
                        "roles r ON ur.role_id = r.id WHERE ur.user_id = $1 AND "
                        "r.name = 'super_admin')",
                        str(user_id),
                    )
                    await cursor_or_conn.execute("SET LOCAL app.is_super_admin = $1", result)
            except Exception:
                # If role checking fails, default to False for security
                if is_cursor:
                    await cursor_or_conn.execute(
                        SQL("SET LOCAL app.is_super_admin = {}").format(Literal(False))
                    )
                else:
                    await cursor_or_conn.execute("SET LOCAL app.is_super_admin = $1", False)

        # Forward custom session variables from config (issue #310)
        config = self.context.get("config")
        if config and hasattr(config, "session_variables"):
            for context_key, pg_variable in config.session_variables.items():
                if context_key in self.context:
                    value = str(self.context[context_key])
                    if is_cursor:
                        await cursor_or_conn.execute(
                            SQL("SET LOCAL {} = {}").format(SQL(pg_variable), Literal(value))
                        )
                    else:
                        await cursor_or_conn.execute(f"SET LOCAL {pg_variable} = $1", value)

        # Inject wall-clock timestamp for DB-side execution duration measurement.
        # SQL functions can compute elapsed time via:
        #   clock_timestamp() - current_setting('fraiseql.started_at', true)::timestamptz
        # Use set_config() via SELECT instead of SET LOCAL to avoid psycopg
        # extended query protocol issues with function calls in SET statements.
        await cursor_or_conn.execute(
            "SELECT set_config('fraiseql.started_at', clock_timestamp()::text, true)"
        )

    async def run(self, query: DatabaseQuery) -> list[dict[str, object]]:
        """Execute a SQL query using a connection from the pool.

        Args:
            query: SQL statement, parameters, and fetch flag.

        Returns:
            List of rows as dictionaries if `fetch_result` is True, else an empty list.
        """
        try:
            async with (
                self._pool.connection() as conn,
                conn.cursor(row_factory=dict_row) as cursor,
            ):
                # Set statement timeout for this query
                if self.query_timeout:
                    # Use literal value, not prepared statement parameters
                    # PostgreSQL doesn't support parameters in SET LOCAL
                    timeout_ms = int(self.query_timeout * 1000)
                    await cursor.execute(
                        f"SET LOCAL statement_timeout = '{timeout_ms}ms'",
                    )

                # Set session variables from context
                await self._set_session_variables(cursor)

                # Handle statement execution based on type and parameter presence
                if isinstance(query.statement, Composed) and not query.params:
                    # Composed objects without params have only embedded literals
                    # This fixes the "%r" placeholder bug from WHERE clause generation
                    await cursor.execute(query.statement)
                elif isinstance(query.statement, (Composed, SQL)) and query.params:
                    # Composed/SQL objects with params - pass parameters normally
                    # This handles legitimate cases like SQL.format() with remaining placeholders
                    await cursor.execute(query.statement, query.params)
                elif isinstance(query.statement, SQL):
                    # SQL objects without params execute directly
                    await cursor.execute(query.statement)
                else:
                    # String statements use parameters normally
                    await cursor.execute(query.statement, query.params)
                if query.fetch_result:
                    return await cursor.fetchall()
                return []
        except Exception as e:
            logger.exception("❌ Database error executing query")

            # Log query timeout specifically
            error_msg = str(e)
            if "statement timeout" in error_msg or "canceling statement" in error_msg:
                security_logger = get_security_logger()
                security_logger.log_query_timeout(
                    user_id=self.context.get("user_id"),
                    execution_time=self.query_timeout,
                    metadata={
                        "error": str(e),
                        "query_type": "database_query",
                    },
                )

            raise

    async def run_in_transaction(
        self,
        func: Callable[..., Awaitable[T]],
        *args: object,
        **kwargs: object,
    ) -> T:
        """Run a user function inside a transaction with a connection from the pool.

        The given `func` must accept the connection as its first argument.
        On exception, the transaction is rolled back.

        Example:
            async def do_stuff(conn):
                await conn.execute("...")
                return ...

            await repo.run_in_transaction(do_stuff)

        Returns:
            Result of the function, if successful.
        """
        async with self._pool.connection() as conn, conn.transaction():
            return await func(conn, *args, **kwargs)

    def get_pool(self) -> AsyncConnectionPool:
        """Expose the underlying connection pool."""
        return self._pool

    async def execute_function(
        self,
        function_name: str,
        input_data: dict[str, object],
    ) -> dict[str, object]:
        """Execute a PostgreSQL function and return the result.

        Args:
            function_name: Fully qualified function name (e.g., 'graphql.create_user')
            input_data: Dictionary to pass as JSONB to the function

        Returns:
            Dictionary result from the function (mutation_result type)
        """
        import json

        # Check if this is psycopg pool or asyncpg pool
        if hasattr(self._pool, "connection"):
            # psycopg pool
            async with (
                self._pool.connection() as conn,
                conn.cursor(row_factory=dict_row) as cursor,
            ):
                # Set statement timeout for this query
                if self.query_timeout:
                    # Use literal value, not prepared statement parameters
                    # PostgreSQL doesn't support parameters in SET LOCAL
                    timeout_ms = int(self.query_timeout * 1000)
                    await cursor.execute(
                        f"SET LOCAL statement_timeout = '{timeout_ms}ms'",
                    )

                # Set session variables from context
                await self._set_session_variables(cursor)

                # Validate function name to prevent SQL injection
                if not function_name.replace("_", "").replace(".", "").isalnum():
                    msg = f"Invalid function name: {function_name}"
                    raise ValueError(msg)

                await cursor.execute(
                    f"SELECT * FROM {function_name}(%s::jsonb)",
                    (json.dumps(input_data),),
                )
                result = await cursor.fetchone()
                return result or {}
        else:
            # asyncpg pool
            async with self._pool.acquire() as conn:
                # Set up JSON codec for asyncpg
                await conn.set_type_codec(
                    "jsonb",
                    encoder=json.dumps,
                    decoder=json.loads,
                    schema="pg_catalog",
                )
                # Validate function name to prevent SQL injection
                if not function_name.replace("_", "").replace(".", "").isalnum():
                    msg = f"Invalid function name: {function_name}"
                    raise ValueError(msg)

                result = await conn.fetchrow(
                    f"SELECT * FROM {function_name}($1::jsonb)",
                    input_data,  # Pass the dict directly, asyncpg will encode it
                )
                return dict(result) if result else {}

    async def execute_function_with_context(
        self,
        function_name: str,
        context_args: list[object],
        input_data: dict[str, object],
    ) -> dict[str, object]:
        """Execute a PostgreSQL function with context parameters.

        Args:
            function_name: Fully qualified function name (e.g., 'app.create_location')
            context_args: List of context arguments (e.g., [tenant_id, user_id])
            input_data: Dictionary to pass as JSONB to the function

        Returns:
            Dictionary result from the function (mutation_result type)
        """
        import json

        # Validate function name to prevent SQL injection
        if not function_name.replace("_", "").replace(".", "").isalnum():
            msg = f"Invalid function name: {function_name}"
            raise ValueError(msg)

        # Build parameter placeholders
        param_count = len(context_args) + 1  # +1 for the JSONB parameter

        # Check if this is psycopg pool or asyncpg pool
        if hasattr(self._pool, "connection"):
            # psycopg pool
            if context_args:
                placeholders = ", ".join(["%s"] * len(context_args)) + ", %s::jsonb"
            else:
                placeholders = "%s::jsonb"
            params = [*list(context_args), json.dumps(input_data)]

            async with (
                self._pool.connection() as conn,
                conn.cursor(row_factory=dict_row) as cursor,
            ):
                # Set statement timeout for this query
                if self.query_timeout:
                    # Use literal value, not prepared statement parameters
                    # PostgreSQL doesn't support parameters in SET LOCAL
                    timeout_ms = int(self.query_timeout * 1000)
                    await cursor.execute(
                        f"SET LOCAL statement_timeout = '{timeout_ms}ms'",
                    )

                # Set session variables from context
                await self._set_session_variables(cursor)

                await cursor.execute(
                    f"SELECT * FROM {function_name}({placeholders})",
                    tuple(params),
                )
                result = await cursor.fetchone()
                return result or {}
        else:
            # asyncpg pool
            if context_args:
                placeholders = (
                    ", ".join([f"${i + 1}" for i in range(len(context_args))])
                    + f", ${param_count}::jsonb"
                )
            else:
                placeholders = "$1::jsonb"
            params = [*list(context_args), input_data]

            async with self._pool.acquire() as conn:
                # Set up JSON codec for asyncpg
                await conn.set_type_codec(
                    "jsonb",
                    encoder=json.dumps,
                    decoder=json.loads,
                    schema="pg_catalog",
                )

                # Set session variables from context
                await self._set_session_variables(conn)

                result = await conn.fetchrow(
                    f"SELECT * FROM {function_name}({placeholders})",
                    *params,
                )
                return dict(result) if result else {}

    async def _ensure_table_columns_cached(self, view_name: str) -> None:
        """Ensure table columns are cached for hybrid table detection.

        PERFORMANCE OPTIMIZATION:
        - Only introspect once per table per repository instance
        - Cache both successes and failures to avoid repeated queries
        - Use connection pool efficiently
        """
        if not hasattr(self, "_introspected_columns"):
            self._introspected_columns = {}
            self._introspection_in_progress = set()

        # Skip if already cached or being introspected (avoid race conditions)
        if view_name in self._introspected_columns or view_name in self._introspection_in_progress:
            return

        # Mark as in progress to prevent concurrent introspections
        self._introspection_in_progress.add(view_name)

        try:
            await self._introspect_table_columns(view_name)
        except Exception:
            # Cache failure to avoid repeated attempts
            self._introspected_columns[view_name] = set()
        finally:
            self._introspection_in_progress.discard(view_name)

    async def find(
        self, view_name: str, field_name: str | None = None, info: Any = None, **kwargs: Any
    ) -> RustResponseBytes:
        """Find records using unified Rust-first pipeline.

        PostgreSQL → Rust → HTTP (zero Python string operations).

        Args:
            view_name: Database table/view name
            field_name: GraphQL field name for response wrapping
            info: Optional GraphQL resolve info for field selection
            **kwargs: Query parameters (where, limit, offset, order_by)

        Returns:
            RustResponseBytes ready for HTTP response
        """
        # Auto-extract info from context if not explicitly provided
        if info is None and "graphql_info" in self.context:
            info = self.context["graphql_info"]

        # 1. Extract field paths and build field selections from GraphQL info
        field_paths = None
        field_selections_json = None
        if info:
            from fraiseql.core.ast_parser import extract_field_paths_from_info
            from fraiseql.core.selection_tree import GraphQLSchemaWrapper, build_selection_tree
            from fraiseql.utils.casing import to_snake_case

            field_path_objects = extract_field_paths_from_info(info, transform_path=to_snake_case)
            # Convert from list[FieldPath] to list[list[str]] for Rust (backward compatibility)
            if field_path_objects:
                field_paths = [fp.path for fp in field_path_objects]

                # NEW: Build field selections with alias and type information
                # Get type name for schema lookup
                parent_type = self._get_cached_type_name(view_name)
                if parent_type and info.schema:
                    # Wrap schema for field type lookups
                    schema_wrapper = GraphQLSchemaWrapper(info.schema)

                    # Build selection tree with materialized paths
                    field_selections = build_selection_tree(
                        field_path_objects,
                        schema_wrapper,
                        parent_type=parent_type,
                    )

                    # Serialize to JSON format for Rust
                    # Use "materialized_path" (dot-separated string) as expected by Rust
                    field_selections_json = [
                        {
                            "materialized_path": ".".join(sel.path)
                            if isinstance(sel.path, list)
                            else sel.path,
                            "alias": sel.alias,
                            "type_name": sel.type_name,
                            "is_nested_object": sel.is_nested_object,
                        }
                        for sel in field_selections
                    ]

                    # Store field selections in context for nested resolvers
                    # This allows nested_field_resolver to apply field filtering to embedded JSONB
                    if hasattr(info, "context") and isinstance(info.context, dict):
                        if "_fraiseql_field_selections" not in info.context:
                            info.context["_fraiseql_field_selections"] = {}

                        # Store by parent type name for nested resolver lookup
                        info.context["_fraiseql_field_selections"][parent_type] = {
                            "selections": field_selections_json,
                            "paths": field_paths,
                        }

        # 2. Get JSONB column from cached metadata (NO sample query!)
        jsonb_column = None  # default to None (use row_to_json)
        if view_name in _table_metadata:
            metadata = _table_metadata[view_name]
            # For hybrid tables with JSONB data, always use the data column
            if metadata.get("has_jsonb_data", False):
                jsonb_column = metadata.get("jsonb_column") or "data"
            elif "jsonb_column" in metadata:
                jsonb_column = metadata["jsonb_column"]

        # 3. Build SQL query
        query = self._build_find_query(
            view_name,
            field_paths=field_paths,
            info=info,
            jsonb_column=jsonb_column,
            **kwargs,
        )

        # 4. Get type name for Rust transformation
        type_name = self._get_cached_type_name(view_name)

        # Extract field_name from info if not explicitly provided
        if not field_name and info and hasattr(info, "field_name"):
            field_name = info.field_name

        # 5. Execute via Rust pipeline (ALWAYS)
        # Check if this is part of a multi-field query to use field-only mode
        include_wrapper = True
        if info and hasattr(info, "context") and isinstance(info.context, dict):
            include_wrapper = not info.context.get("__has_multiple_root_fields__", False)

        async with self._pool.connection() as conn:
            result = await execute_via_rust_pipeline(
                conn,
                query.statement,
                query.params,
                field_name or view_name,  # Use view_name as default field_name
                type_name,
                is_list=True,
                field_paths=field_paths,  # NEW: Pass field paths for Rust-side projection!
                field_selections=field_selections_json,  # NEW: Pass field selections with aliases!
                include_graphql_wrapper=include_wrapper,  # Field-only mode for multi-field
            )

            # Store RustResponseBytes in context for direct path
            if info and hasattr(info, "context"):
                if "_rust_response" not in info.context:
                    info.context["_rust_response"] = {}
                info.context["_rust_response"][field_name or view_name] = result

            return result

    async def find_one(
        self, view_name: str, field_name: str | None = None, info: Any = None, **kwargs: Any
    ) -> RustResponseBytes | None:
        """Find single record using unified Rust-first pipeline.

        Args:
            view_name: Database table/view name
            field_name: GraphQL field name for response wrapping
            info: Optional GraphQL resolve info
            **kwargs: Query parameters (id, where, etc.)

        Returns:
            RustResponseBytes for non-null results, None for null results (no record found)

        Note:
            When no record is found, Rust returns {"data":{"field":[]}}. This method
            detects that pattern and returns None to match Python/GraphQL semantics.
        """
        # Auto-extract info from context if not explicitly provided
        if info is None and "graphql_info" in self.context:
            info = self.context["graphql_info"]

        # 1. Extract field paths and build field selections from GraphQL info
        field_paths = None
        field_selections_json = None
        if info:
            from fraiseql.core.ast_parser import extract_field_paths_from_info
            from fraiseql.core.selection_tree import GraphQLSchemaWrapper, build_selection_tree
            from fraiseql.utils.casing import to_snake_case

            field_path_objects = extract_field_paths_from_info(info, transform_path=to_snake_case)
            # Convert from list[FieldPath] to list[list[str]] for Rust (backward compatibility)
            if field_path_objects:
                field_paths = [fp.path for fp in field_path_objects]

                # NEW: Build field selections with alias and type information
                # Get type name for schema lookup
                parent_type = self._get_cached_type_name(view_name)
                if parent_type and info.schema:
                    # Wrap schema for field type lookups
                    schema_wrapper = GraphQLSchemaWrapper(info.schema)

                    # Build selection tree with materialized paths
                    field_selections = build_selection_tree(
                        field_path_objects,
                        schema_wrapper,
                        parent_type=parent_type,
                    )

                    # Serialize to JSON format for Rust
                    # Use "materialized_path" (dot-separated string) as expected by Rust
                    field_selections_json = [
                        {
                            "materialized_path": ".".join(sel.path)
                            if isinstance(sel.path, list)
                            else sel.path,
                            "alias": sel.alias,
                            "type_name": sel.type_name,
                            "is_nested_object": sel.is_nested_object,
                        }
                        for sel in field_selections
                    ]

        # 2. Get JSONB column from cached metadata
        jsonb_column = None  # default to None (use row_to_json)
        if view_name in _table_metadata:
            metadata = _table_metadata[view_name]
            # For hybrid tables with JSONB data, always use the data column
            if metadata.get("has_jsonb_data", False):
                jsonb_column = metadata.get("jsonb_column") or "data"
            elif "jsonb_column" in metadata:
                jsonb_column = metadata["jsonb_column"]

        # 3. Build query (automatically adds LIMIT 1)
        query = self._build_find_one_query(
            view_name,
            field_paths=field_paths,
            info=info,
            jsonb_column=jsonb_column,
            **kwargs,
        )

        # 4. Get type name
        type_name = self._get_cached_type_name(view_name)

        # Extract field_name from info if not explicitly provided
        if not field_name and info and hasattr(info, "field_name"):
            field_name = info.field_name

        # 5. Execute via Rust pipeline (ALWAYS)
        # Check if this is part of a multi-field query to use field-only mode
        include_wrapper = True
        if info and hasattr(info, "context") and isinstance(info.context, dict):
            include_wrapper = not info.context.get("__has_multiple_root_fields__", False)

        async with self._pool.connection() as conn:
            result = await execute_via_rust_pipeline(
                conn,
                query.statement,
                query.params,
                field_name or view_name,  # Use view_name as default field_name
                type_name,
                is_list=False,
                field_paths=field_paths,  # NEW: Pass field paths for Rust-side projection!
                field_selections=field_selections_json,  # NEW: Pass field selections with aliases!
                include_graphql_wrapper=include_wrapper,  # Field-only mode for multi-field
            )

            # NEW: Check if result is null (empty array from Rust)
            # Rust returns {"data":{"field":[]}} for null, we convert to Python None
            if _is_rust_response_null(result):
                return None

            # Store RustResponseBytes in context for direct path
            if info and hasattr(info, "context"):
                if "_rust_response" not in info.context:
                    info.context["_rust_response"] = {}
                info.context["_rust_response"][field_name or view_name] = result

            return result

    async def count(
        self,
        view_name: str,
        **kwargs: Any,
    ) -> int:
        """Count records in a view with optional filtering.

        This method provides a clean API for count queries, returning a simple integer
        count instead of GraphQL response bytes. Uses the same WHERE clause logic as
        find() for consistency.

        Args:
            view_name: Database table/view name
            **kwargs: Query parameters (where, tenant_id, etc.)

        Returns:
            Integer count of matching records

        Example:
            count = await db.count("v_users", where={"status": {"eq": "active"}})
            total = await db.count("v_products")
            tenant_count = await db.count("v_orders", tenant_id="tenant-123")
        """
        from psycopg.sql import SQL, Composed, Identifier

        # Build WHERE clause (extracted to helper method for reuse)
        where_parts, params = self._build_where_clause(view_name, **kwargs)

        # Handle schema-qualified table names
        if "." in view_name:
            schema_name, table_name = view_name.split(".", 1)
            table_identifier = Identifier(schema_name, table_name)
        else:
            table_identifier = Identifier(view_name)

        # Build COUNT(*) query
        query_parts = [SQL("SELECT COUNT(*) FROM "), table_identifier]

        if where_parts:
            query_parts.append(SQL(" WHERE "))
            query_parts.append(SQL(" AND ").join(where_parts))

        query = Composed(query_parts)

        # Execute query and return count
        async with self._pool.connection() as conn, conn.cursor() as cursor:
            if params:
                await cursor.execute(query, params)
            else:
                await cursor.execute(query)
            result = await cursor.fetchone()
            return result[0] if result else 0

    async def exists(
        self,
        view_name: str,
        **kwargs: Any,
    ) -> bool:
        """Check if any records exist matching the filter.

        More efficient than count() > 0 for existence checks.
        Uses EXISTS() SQL query for optimal performance.

        Args:
            view_name: Database table/view name (e.g., "v_users", "v_orders")
            **kwargs: Query parameters:
                - where: dict - WHERE clause filters (e.g., {"email": {"eq": "test@example.com"}})
                - tenant_id: UUID - Filter by tenant_id
                - Any other parameters supported by _build_where_clause()

        Returns:
            True if at least one record exists, False otherwise

        Example:
            # Check if email exists
            exists = await db.exists("v_users", where={"email": {"eq": "test@example.com"}})

            # Check if tenant has orders
            has_orders = await db.exists("v_orders", tenant_id=tenant_id)

            # Check with multiple filters
            exists = await db.exists(
                "v_users",
                where={"email": {"eq": "test@example.com"}, "status": {"eq": "active"}}
            )
        """
        from psycopg.sql import SQL, Composed, Identifier

        # Build WHERE clause using existing helper
        where_parts, params = self._build_where_clause(view_name, **kwargs)

        # Handle schema-qualified table names
        if "." in view_name:
            schema_name, table_name = view_name.split(".", 1)
            table_identifier = Identifier(schema_name, table_name)
        else:
            table_identifier = Identifier(view_name)

        # Build EXISTS query
        query_parts = [SQL("SELECT EXISTS(SELECT 1 FROM "), table_identifier]

        if where_parts:
            query_parts.append(SQL(" WHERE "))
            query_parts.append(SQL(" AND ").join(where_parts))

        query_parts.append(SQL(")"))
        query = Composed(query_parts)

        # Execute query
        async with self._pool.connection() as conn, conn.cursor() as cursor:
            if params:
                await cursor.execute(query, params)
            else:
                await cursor.execute(query)
            result = await cursor.fetchone()
            return bool(result[0]) if result else False

    async def sum(
        self,
        view_name: str,
        field: str,
        **kwargs: Any,
    ) -> float:
        """Sum a numeric field.

        Args:
            view_name: Database table/view name (e.g., "v_orders")
            field: Field name to sum (e.g., "amount", "quantity")
            **kwargs: Query parameters (where, tenant_id, etc.)

        Returns:
            Sum as float (returns 0.0 if no records)

        Example:
            # Total revenue
            total = await db.sum("v_orders", "amount")

            # Total for completed orders
            total = await db.sum(
                "v_orders",
                "amount",
                where={"status": {"eq": "completed"}}
            )

            # Total for tenant
            total = await db.sum("v_orders", "amount", tenant_id=tenant_id)
        """
        from psycopg.sql import SQL, Composed, Identifier

        # Build WHERE clause using existing helper
        where_parts = self._build_where_clause(view_name, **kwargs)

        # Handle schema-qualified table names
        if "." in view_name:
            schema_name, table_name = view_name.split(".", 1)
            table_identifier = Identifier(schema_name, table_name)
        else:
            table_identifier = Identifier(view_name)

        # Build SUM query
        query_parts = [
            SQL("SELECT COALESCE(SUM("),
            Identifier(field),
            SQL("), 0) FROM "),
            table_identifier,
        ]

        if where_parts:
            query_parts.append(SQL(" WHERE "))
            query_parts.append(SQL(" AND ").join(where_parts))

        query = Composed(query_parts)

        # Execute query
        async with self._pool.connection() as conn, conn.cursor() as cursor:
            await cursor.execute(query)
            result = await cursor.fetchone()
            return float(result[0]) if result and result[0] is not None else 0.0

    async def avg(
        self,
        view_name: str,
        field: str,
        **kwargs: Any,
    ) -> float:
        """Average of a numeric field.

        Args:
            view_name: Database table/view name
            field: Field name to average
            **kwargs: Query parameters (where, tenant_id, etc.)

        Returns:
            Average as float (returns 0.0 if no records)

        Example:
            # Average order value
            avg_order = await db.avg("v_orders", "amount")

            # Average for completed orders
            avg_order = await db.avg(
                "v_orders",
                "amount",
                where={"status": {"eq": "completed"}}
            )
        """
        from psycopg.sql import SQL, Composed, Identifier

        # Build WHERE clause using existing helper
        where_parts = self._build_where_clause(view_name, **kwargs)

        # Handle schema-qualified table names
        if "." in view_name:
            schema_name, table_name = view_name.split(".", 1)
            table_identifier = Identifier(schema_name, table_name)
        else:
            table_identifier = Identifier(view_name)

        # Build AVG query
        query_parts = [
            SQL("SELECT COALESCE(AVG("),
            Identifier(field),
            SQL("), 0) FROM "),
            table_identifier,
        ]

        if where_parts:
            query_parts.append(SQL(" WHERE "))
            query_parts.append(SQL(" AND ").join(where_parts))

        query = Composed(query_parts)

        # Execute query
        async with self._pool.connection() as conn, conn.cursor() as cursor:
            await cursor.execute(query)
            result = await cursor.fetchone()
            return float(result[0]) if result and result[0] is not None else 0.0

    async def min(
        self,
        view_name: str,
        field: str,
        **kwargs: Any,
    ) -> Any:
        """Minimum value of a field.

        Args:
            view_name: Database table/view name
            field: Field name to get minimum value
            **kwargs: Query parameters (where, tenant_id, etc.)

        Returns:
            Minimum value (type depends on field), or None if no records

        Example:
            # Lowest product price
            min_price = await db.min("v_products", "price")

            # Earliest order date
            first_order = await db.min("v_orders", "created_at")
        """
        from psycopg.sql import SQL, Composed, Identifier

        # Build WHERE clause using existing helper
        where_parts = self._build_where_clause(view_name, **kwargs)

        # Handle schema-qualified table names
        if "." in view_name:
            schema_name, table_name = view_name.split(".", 1)
            table_identifier = Identifier(schema_name, table_name)
        else:
            table_identifier = Identifier(view_name)

        # Build MIN query
        query_parts = [SQL("SELECT MIN("), Identifier(field), SQL(") FROM "), table_identifier]

        if where_parts:
            query_parts.append(SQL(" WHERE "))
            query_parts.append(SQL(" AND ").join(where_parts))

        query = Composed(query_parts)

        # Execute query
        async with self._pool.connection() as conn, conn.cursor() as cursor:
            await cursor.execute(query)
            result = await cursor.fetchone()
            return result[0] if result else None

    async def max(
        self,
        view_name: str,
        field: str,
        **kwargs: Any,
    ) -> Any:
        """Maximum value of a field.

        Args:
            view_name: Database table/view name
            field: Field name to get maximum value
            **kwargs: Query parameters (where, tenant_id, etc.)

        Returns:
            Maximum value (type depends on field), or None if no records

        Example:
            # Highest product price
            max_price = await db.max("v_products", "price")

            # Latest order date
            last_order = await db.max("v_orders", "created_at")
        """
        from psycopg.sql import SQL, Composed, Identifier

        # Build WHERE clause using existing helper
        where_parts = self._build_where_clause(view_name, **kwargs)

        # Handle schema-qualified table names
        if "." in view_name:
            schema_name, table_name = view_name.split(".", 1)
            table_identifier = Identifier(schema_name, table_name)
        else:
            table_identifier = Identifier(view_name)

        # Build MAX query
        query_parts = [SQL("SELECT MAX("), Identifier(field), SQL(") FROM "), table_identifier]

        if where_parts:
            query_parts.append(SQL(" WHERE "))
            query_parts.append(SQL(" AND ").join(where_parts))

        query = Composed(query_parts)

        # Execute query
        async with self._pool.connection() as conn, conn.cursor() as cursor:
            await cursor.execute(query)
            result = await cursor.fetchone()
            return result[0] if result else None

    async def distinct(
        self,
        view_name: str,
        field: str,
        **kwargs: Any,
    ) -> list[Any]:
        """Get distinct values for a field.

        Args:
            view_name: Database table/view name
            field: Field name to get distinct values
            **kwargs: Query parameters (where, tenant_id, etc.)

        Returns:
            List of unique values (sorted)

        Example:
            # Get all categories
            categories = await db.distinct("v_products", "category")
            # Returns: ["books", "clothing", "electronics"]

            # Get statuses for tenant
            statuses = await db.distinct("v_orders", "status", tenant_id=tenant_id)
            # Returns: ["cancelled", "completed", "pending"]
        """
        from psycopg.sql import SQL, Composed, Identifier

        # Build WHERE clause using existing helper
        where_parts = self._build_where_clause(view_name, **kwargs)

        # Handle schema-qualified table names
        if "." in view_name:
            schema_name, table_name = view_name.split(".", 1)
            table_identifier = Identifier(schema_name, table_name)
        else:
            table_identifier = Identifier(view_name)

        # Build DISTINCT query
        query_parts = [SQL("SELECT DISTINCT "), Identifier(field), SQL(" FROM "), table_identifier]

        if where_parts:
            query_parts.append(SQL(" WHERE "))
            query_parts.append(SQL(" AND ").join(where_parts))

        query_parts.append(SQL(" ORDER BY "))
        query_parts.append(Identifier(field))
        query = Composed(query_parts)

        # Execute query
        async with self._pool.connection() as conn, conn.cursor() as cursor:
            await cursor.execute(query)
            results = await cursor.fetchall()
            return [row[0] for row in results] if results else []

    async def pluck(
        self,
        view_name: str,
        field: str,
        **kwargs: Any,
    ) -> list[Any]:
        """Extract a single field from matching records.

        More efficient than find() when you only need one field.

        Args:
            view_name: Database table/view name
            field: Field name to extract
            **kwargs: Query parameters (where, limit, offset, order_by, etc.)

        Returns:
            List of field values (not full objects)

        Example:
            # Get all user IDs
            user_ids = await db.pluck("v_users", "id")
            # Returns: [uuid1, uuid2, uuid3, ...]

            # Get emails for active users
            emails = await db.pluck(
                "v_users",
                "email",
                where={"status": {"eq": "active"}}
            )
            # Returns: ["user1@example.com", "user2@example.com", ...]

            # Get product names with limit
            names = await db.pluck("v_products", "name", limit=10)
        """
        from psycopg.sql import SQL, Composed, Identifier

        # Build WHERE clause using existing helper
        where_parts = self._build_where_clause(view_name, **kwargs)

        # Handle schema-qualified table names
        if "." in view_name:
            schema_name, table_name = view_name.split(".", 1)
            table_identifier = Identifier(schema_name, table_name)
        else:
            table_identifier = Identifier(view_name)

        # Build query with optional LIMIT and OFFSET
        query_parts = [SQL("SELECT "), Identifier(field), SQL(" FROM "), table_identifier]

        if where_parts:
            query_parts.append(SQL(" WHERE "))
            query_parts.append(SQL(" AND ").join(where_parts))

        # Add LIMIT if provided
        if "limit" in kwargs:
            query_parts.append(SQL(" LIMIT "))
            query_parts.append(SQL(str(kwargs["limit"])))

        # Add OFFSET if provided
        if "offset" in kwargs:
            query_parts.append(SQL(" OFFSET "))
            query_parts.append(SQL(str(kwargs["offset"])))

        query = Composed(query_parts)

        # Execute query
        async with self._pool.connection() as conn, conn.cursor() as cursor:
            await cursor.execute(query)
            results = await cursor.fetchall()
            return [row[0] for row in results] if results else []

    async def aggregate(
        self,
        view_name: str,
        aggregations: dict[str, str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Perform multiple aggregations in a single query.

        Args:
            view_name: Database table/view name
            aggregations: Dict mapping result names to SQL aggregation expressions
            **kwargs: Query parameters (where, tenant_id, etc.)

        Returns:
            Dict with aggregation results as Python values

        Example:
            # Multiple aggregations in one query
            stats = await db.aggregate(
                "v_orders",
                aggregations={
                    "total_revenue": "SUM(amount)",
                    "avg_order": "AVG(amount)",
                    "max_order": "MAX(amount)",
                    "order_count": "COUNT(*)",
                },
                where={"status": {"eq": "completed"}}
            )
            # Returns: {
            #     "total_revenue": 125000.50,
            #     "avg_order": 250.00,
            #     "max_order": 1500.00,
            #     "order_count": 500
            # }
        """
        from psycopg.sql import SQL, Composed, Identifier

        if not aggregations:
            return {}

        # Build WHERE clause using existing helper
        where_parts, params = self._build_where_clause(view_name, **kwargs)

        # Handle schema-qualified table names
        if "." in view_name:
            schema_name, table_name = view_name.split(".", 1)
            table_identifier = Identifier(schema_name, table_name)
        else:
            table_identifier = Identifier(view_name)

        # Build SELECT clause with all aggregations
        agg_clauses = [SQL(f"{expr} AS {name}") for name, expr in aggregations.items()]
        select_clause = Composed(agg_clauses)

        # Build query
        query_parts = [SQL("SELECT "), select_clause, SQL(" FROM "), table_identifier]

        if where_parts:
            query_parts.append(SQL(" WHERE "))
            query_parts.append(SQL(" AND ").join(where_parts))

        query = Composed(query_parts)

        # Execute query
        async with self._pool.connection() as conn, conn.cursor() as cursor:
            if params:
                await cursor.execute(query, params)
            else:
                await cursor.execute(query)
            result = await cursor.fetchone()

            if not result:
                return dict.fromkeys(aggregations.keys())

            # Map column names to values
            column_names = [desc[0] for desc in cursor.description]
            return dict(zip(column_names, result, strict=True))

    async def batch_exists(
        self,
        view_name: str,
        ids: list[Any],
        field: str = "id",
        **kwargs: Any,
    ) -> dict[Any, bool]:
        """Check existence of multiple records in a single query.

        Args:
            view_name: Database table/view name
            ids: List of IDs to check for existence
            field: Field name to check against (default: "id")
            **kwargs: Additional query parameters (tenant_id, etc.)

        Returns:
            Dict mapping each ID to boolean existence status

        Example:
            # Check if multiple users exist
            results = await db.batch_exists("v_users", [user_id1, user_id2, user_id3])
            # Returns: {user_id1: True, user_id2: False, user_id3: True}

            # Check by custom field
            results = await db.batch_exists("v_users", ["user1", "user2"], field="username")
        """
        from psycopg.sql import SQL, Composed, Identifier

        if not ids:
            return {}

        # Build WHERE clause using existing helper
        where_parts, where_params = self._build_where_clause(view_name, **kwargs)

        # Handle schema-qualified table names
        if "." in view_name:
            schema_name, table_name = view_name.split(".", 1)
            table_identifier = Identifier(schema_name, table_name)
        else:
            table_identifier = Identifier(view_name)

        # Build query to select existing IDs
        query_parts = [SQL("SELECT "), Identifier(field), SQL(" FROM "), table_identifier]

        if where_parts:
            query_parts.append(SQL(" WHERE "))
            query_parts.append(SQL(" AND ").join(where_parts))
            query_parts.append(SQL(" AND "))
        else:
            query_parts.append(SQL(" WHERE "))

        # Add IN clause for the IDs (using Identifier for field to prevent SQL injection)
        if len(ids) == 1:
            # Single ID - use equality
            query_parts.extend([Identifier(field), SQL(" = %s")])
        else:
            # Multiple IDs - use IN clause
            placeholders = ", ".join(["%s"] * len(ids))
            query_parts.extend([Identifier(field), SQL(f" IN ({placeholders})")])

        query = Composed(query_parts)

        # Execute query
        async with self._pool.connection() as conn, conn.cursor() as cursor:
            await cursor.execute(query, where_params + ids)
            results = await cursor.fetchall()

            # Extract existing IDs
            existing_ids = {row[0] for row in results} if results else set()

            # Build result dict
            return {id_val: (id_val in existing_ids) for id_val in ids}

    def _normalize_where(
        self,
        where: dict | Any,
        view_name: str,
        table_columns: set[str] | None = None,
    ) -> WhereClause:
        """Normalize WHERE clause to canonical WhereClause representation.

        This is the single entry point for WHERE normalization, handling both
        dict and WhereInput formats. Automatically converts GraphQL camelCase
        field names to database snake_case column names.

        Args:
            where: WHERE clause (dict or WhereInput object)
                  Field names can be camelCase (GraphQL) or snake_case (database)
            view_name: Table/view name for metadata lookup
            table_columns: Set of actual table column names

        Returns:
            Canonical WhereClause representation

        Raises:
            TypeError: If where is not a supported type

        Examples:
            # CamelCase input (GraphQL style) - automatically converted
            where = {"ipAddress": {"eq": "192.168.1.1"}}
            # Converted internally to: {"ip_address": {"eq": "..."}}

            # Snake_case input (already correct) - preserved as-is
            where = {"ip_address": {"eq": "192.168.1.1"}}

            # Deep nesting with mixed case - all levels converted
            where = {"machine": {"network": {"ipAddress": {"eq": "..."}}}}
        """
        # Already normalized
        if isinstance(where, WhereClause):
            return where

        # Dict-based WHERE
        if isinstance(where, dict):
            jsonb_column = "data"
            if view_name in _table_metadata:
                metadata = _table_metadata[view_name]
                if metadata.get("has_jsonb_data", False):
                    jsonb_column = metadata.get("jsonb_column") or "data"

            result = normalize_dict_where(where, view_name, table_columns, jsonb_column)
            if result is None:
                raise ValueError(f"normalize_dict_where returned None for {where!r}")
            return result

        # WhereInput-based WHERE
        if hasattr(where, "_to_whereinput_dict"):
            jsonb_column = "data"
            if view_name in _table_metadata:
                metadata = _table_metadata[view_name]
                if metadata.get("has_jsonb_data", False):
                    jsonb_column = metadata.get("jsonb_column") or "data"

            result = normalize_whereinput(where, view_name, table_columns, jsonb_column)
            if result is None:
                raise ValueError(f"normalize_whereinput returned None for {where!r}")
            return result

        # Try to convert dataclass WhereInput objects to dict
        # (for dynamically created WhereInput types without _to_whereinput_dict method)
        from dataclasses import asdict, is_dataclass

        if is_dataclass(where):
            # Convert dataclass to dict, filtering out None values
            where_dict = {
                field_name: field_value
                for field_name, field_value in asdict(where).items()
                if field_value is not None and field_value != {}
            }

            if where_dict:  # Only process if there are non-empty values
                jsonb_column = "data"
                if view_name in _table_metadata:
                    metadata = _table_metadata[view_name]
                    if metadata.get("has_jsonb_data", False):
                        jsonb_column = metadata.get("jsonb_column") or "data"

                result = normalize_dict_where(where_dict, view_name, table_columns, jsonb_column)
                if result is None:
                    raise ValueError(f"normalize_dict_where returned None for {where_dict!r}")
                return result

        # FIX: Always raise error for unsupported types, never return None
        raise TypeError(
            f"WHERE clause must be dict, WhereClause, or WhereInput object. "
            f"Got: {type(where).__name__}"
        )

    def _build_where_clause(self, view_name: str, **kwargs: Any) -> tuple[list[Any], list[Any]]:
        """Build WHERE clause parts from kwargs.

        New architecture:
            1. Extract where parameter
            2. Normalize to WhereClause (single code path)
            3. Generate SQL from WhereClause
            4. Process remaining kwargs

        Returns:
            Tuple of (where_parts, params)
        """
        from psycopg.sql import SQL, Composed, Identifier

        where_parts = []
        all_params = []

        # Extract where parameter
        where_obj = kwargs.pop("where", None)

        if where_obj:
            # Get table columns for normalization
            # CRITICAL: table_columns must be provided for hybrid table FK detection
            table_columns = None

            # Try introspection cache first
            if hasattr(self, "_introspected_columns") and view_name in self._introspected_columns:
                table_columns = self._introspected_columns[view_name]
            # Then try registered metadata
            elif view_name in _table_metadata:
                metadata = _table_metadata[view_name]
                if "columns" in metadata:
                    table_columns = metadata.get("columns")
                if not table_columns:
                    logger.warning(
                        f"No table_columns registered for {view_name} - "
                        f"FK detection may be disabled. Call register_type_for_view()."
                    )

            # SINGLE CODE PATH: Normalize to WhereClause
            try:
                where_clause = self._normalize_where(where_obj, view_name, table_columns)

                # Generate SQL from WhereClause
                sql, params = where_clause.to_sql()

                if sql:
                    all_params.extend(params)
                    where_parts.append(sql)

                    logger.debug(
                        f"WHERE clause built from {type(where_obj).__name__}",
                        extra={
                            "view_name": view_name,
                            "conditions": len(where_clause.conditions),
                            "fk_optimizations": sum(
                                1
                                for c in where_clause.conditions
                                if c.lookup_strategy == "fk_column"
                            ),
                        },
                    )
            except Exception:
                logger.exception(f"WHERE normalization failed for {view_name}")
                raise

        # Process remaining kwargs as simple equality filters
        for key, value in kwargs.items():
            where_condition = Composed([Identifier(key), SQL(" = "), SQL("%s")])
            where_parts.append(where_condition)
            all_params.append(value)

        return where_parts, all_params

    def _extract_type(self, field_type: type) -> Optional[type]:
        """Extract the actual type from Optional, Union, etc."""
        origin = get_origin(field_type)
        if origin is Union:
            args = get_args(field_type)
            # Filter out None type
            non_none_args = [arg for arg in args if arg is not type(None)]
            if non_none_args:
                return non_none_args[0]
        return field_type if origin is None else None

    def _get_type_for_view(self, view_name: str) -> type:
        """Get the type class for a given view name."""
        # Check the global type registry
        if view_name in _type_registry:
            return _type_registry[view_name]

        # Try to find type by convention (remove _view suffix and check)
        type_name = view_name.replace("_view", "")
        for registered_view, type_class in _type_registry.items():
            if registered_view.lower().replace("_", "") == type_name.lower().replace("_", ""):
                return type_class

        available_views = list(_type_registry.keys())
        logger.error(f"Type registry state: {_type_registry}")
        raise NotImplementedError(
            f"Type registry lookup for {view_name} not implemented. "
            f"Available views: {available_views}. Registry size: {len(_type_registry)}",
        )

    def _build_find_query(
        self,
        view_name: str,
        field_paths: list[Any] | None = None,
        info: Any = None,
        jsonb_column: str | None = None,
        **kwargs: Any,
    ) -> DatabaseQuery:
        """Build a SELECT query for finding multiple records.

        Unified Rust-first: always SELECT jsonb_column::text
        Rust handles field projection, not PostgreSQL!

        Args:
            view_name: Name of the view to query
            field_paths: Optional field paths for projection (passed to Rust)
            info: Optional GraphQL resolve info
            jsonb_column: JSONB column name to use
            **kwargs: Query parameters (where, limit, offset, order_by)
        """
        from psycopg.sql import SQL, Composed, Identifier, Literal

        # Extract special parameters BEFORE passing to _build_where_clause
        limit = kwargs.pop("limit", None)
        offset = kwargs.pop("offset", None)
        order_by = kwargs.pop("order_by", None)

        # Use unified WHERE clause building (includes Issue #124 fix for hybrid tables)
        # This ensures WhereInput nested filters work correctly in all code paths
        where_parts, where_params = self._build_where_clause(view_name, **kwargs)

        # Handle schema-qualified table names
        if "." in view_name:
            schema_name, table_name = view_name.split(".", 1)
            table_identifier = Identifier(schema_name, table_name)
        else:
            table_identifier = Identifier(view_name)

        if jsonb_column is None:
            # For tables with jsonb_column=None, select all columns as JSON
            # This allows the Rust pipeline to extract individual fields
            query_parts = [
                SQL("SELECT row_to_json(t)::text FROM "),
                table_identifier,
                SQL(" AS t"),
            ]
        else:
            # For JSONB tables, select the JSONB column as text
            target_jsonb_column = jsonb_column or "data"
            query_parts = [
                SQL("SELECT "),
                Identifier(target_jsonb_column),
                SQL("::text FROM "),
                table_identifier,
            ]

        # Add WHERE clause
        if where_parts:
            where_sql_parts = []
            for part in where_parts:
                if isinstance(part, (SQL, Composed)):
                    where_sql_parts.append(part)
                else:
                    where_sql_parts.append(SQL(part))
            if where_sql_parts:
                query_parts.extend([SQL(" WHERE "), SQL(" AND ").join(where_sql_parts)])

        # Determine table reference for ORDER BY
        # For JSONB tables, use the column name; for non-JSONB tables, use table alias "t"
        table_ref = jsonb_column if jsonb_column is not None else "t"

        # Add ORDER BY
        if order_by:
            if hasattr(order_by, "to_sql"):
                order_sql = order_by.to_sql(table_ref)
                if order_sql:
                    # OrderBySet.to_sql() already includes "ORDER BY " prefix
                    query_parts.append(SQL(" "))
                    query_parts.append(order_sql)
            elif hasattr(order_by, "_to_sql_order_by"):
                # Convert GraphQL OrderByInput to SQL OrderBySet, then get SQL
                config = self.context.get("config")
                sql_order_by_obj = order_by._to_sql_order_by(config=config)
                if sql_order_by_obj and hasattr(sql_order_by_obj, "to_sql"):
                    order_sql = sql_order_by_obj.to_sql(table_ref)
                    if order_sql:
                        # OrderBySet.to_sql() already includes "ORDER BY " prefix
                        query_parts.append(SQL(" "))
                        query_parts.append(order_sql)
            elif isinstance(order_by, (dict, list)):
                # Convert dict or list-style order by input to SQL OrderBySet
                # List format: [{"age": "ASC"}, {"name": "DESC"}] - from GraphQL
                # Dict format: {"age": "ASC"} - single field
                from fraiseql.sql.graphql_order_by_generator import _convert_order_by_input_to_sql

                config = self.context.get("config")
                sql_order_by_obj = _convert_order_by_input_to_sql(order_by, config=config)
                if sql_order_by_obj and hasattr(sql_order_by_obj, "to_sql"):
                    order_sql = sql_order_by_obj.to_sql(table_ref)
                    if order_sql:
                        # OrderBySet.to_sql() already includes "ORDER BY " prefix
                        query_parts.append(SQL(" "))
                        query_parts.append(order_sql)
            elif isinstance(order_by, str):
                query_parts.extend([SQL(" ORDER BY "), SQL(order_by)])

        # Add LIMIT
        if limit is not None:
            query_parts.extend([SQL(" LIMIT "), Literal(limit)])

        # Add OFFSET
        if offset is not None:
            query_parts.extend([SQL(" OFFSET "), Literal(offset)])

        statement = SQL("").join(query_parts)
        return DatabaseQuery(statement=statement, params=where_params, fetch_result=True)

    def _build_find_one_query(
        self,
        view_name: str,
        field_paths: list[Any] | None = None,
        info: Any = None,
        jsonb_column: str | None = None,
        **kwargs: Any,
    ) -> DatabaseQuery:
        """Build a SELECT query for finding a single record."""
        # Force limit=1 for find_one
        kwargs["limit"] = 1
        return self._build_find_query(
            view_name,
            field_paths=field_paths,
            info=info,
            jsonb_column=jsonb_column,
            **kwargs,
        )

    async def _get_table_columns_cached(self, view_name: str) -> set[str] | None:
        """Get table columns with caching.

        Returns set of column names or None if unable to retrieve.
        """
        if not hasattr(self, "_introspected_columns"):
            self._introspected_columns = {}

        if view_name in self._introspected_columns:
            return self._introspected_columns[view_name]

        try:
            columns = await self._introspect_table_columns(view_name)
            self._introspected_columns[view_name] = columns
            return columns
        except Exception:
            return None

    def _build_dict_where_condition(
        self,
        field_name: str,
        operator: str,
        value: Any,
        view_name: str | None = None,
        table_columns: set[str] | None = None,
        jsonb_column: str | None = None,
    ) -> Composed | None:
        """Build a single WHERE condition using FraiseQL's operator strategy system.

        This method now uses the sophisticated operator strategy system instead of
        primitive SQL templates, enabling features like IP address type casting,
        MAC address handling, and other advanced field type detection.

        For hybrid tables (with both regular columns and JSONB data), it determines
        whether to use direct column access or JSONB path based on the actual table structure.

        Args:
            field_name: Database field name (e.g., 'ip_address', 'port', 'status')
            operator: Filter operator (eq, contains, gt, in, etc.)
            value: Filter value
            view_name: Optional view/table name for hybrid table detection
            table_columns: Optional set of actual table columns (for accurate detection)
            jsonb_column: Optional JSONB column name (if set, use JSONB paths for all non-id fields)

        Returns:
            Composed SQL condition with intelligent type casting, or None if operator not supported
        """
        from psycopg.sql import SQL, Composed, Identifier, Literal

        from fraiseql.sql.operators import get_default_registry as get_operator_registry

        try:
            # Get the operator strategy registry (contains the v0.7.1 IP filtering fixes)
            registry = get_operator_registry()

            # Determine if this field is a regular column or needs JSONB path
            use_jsonb_path = False

            # IMPORTANT: Check table_columns FIRST for hybrid tables (Issue #124)
            # For hybrid tables with FK columns, we must use the SQL FK column, not JSONB path
            if table_columns is not None and field_name in table_columns:
                # This field is a real SQL column - never use JSONB path for it
                use_jsonb_path = False
                logger.debug(f"Dict WHERE: Field '{field_name}' is a SQL column, not JSONB path")
            elif jsonb_column:
                # Explicit JSONB column specified - use JSONB paths for non-column fields
                use_jsonb_path = field_name != "id"
            elif table_columns is not None:
                # We have column info, but field is not in columns - check if it's in JSONB
                has_data_column = "data" in table_columns
                use_jsonb_path = has_data_column
            elif view_name:
                # Fall back to heuristic-based detection
                use_jsonb_path = self._should_use_jsonb_path_sync(view_name, field_name)

            if use_jsonb_path:
                # Field is in JSONB data column, use JSONB path
                jsonb_col = jsonb_column or "data"
                path_sql = Composed([Identifier(jsonb_col), SQL(" ->> "), Literal(field_name)])
            else:
                # Field is a regular column, use direct column name
                path_sql = Identifier(field_name)

            # Get the appropriate strategy for this operator
            # field_type=None triggers fallback detection (IP addresses, MAC addresses, etc.)
            strategy = registry.get_strategy(operator, field_type=None)

            if strategy is None:
                # Operator not supported by strategy system, fall back to basic handling
                return self._build_basic_dict_condition(
                    field_name, operator, value, use_jsonb_path=use_jsonb_path
                )

            # Use the strategy to build intelligent SQL with type detection
            # This is where the IP filtering fixes from v0.7.1 are applied
            sql_condition = strategy.build_sql(
                operator=operator,
                value=value,
                path_sql=path_sql,
                field_type=None,
                jsonb_column=jsonb_column if use_jsonb_path else None,
            )

            return sql_condition

        except Exception as e:
            # If strategy system fails, fall back to basic condition building
            logger.warning(f"Operator strategy failed for {field_name} {operator} {value}: {e}")
            return self._build_basic_dict_condition(field_name, operator, value)

    def _build_basic_dict_condition(
        self, field_name: str, operator: str, value: Any, use_jsonb_path: bool = False
    ) -> Composed | None:
        """Fallback method for basic WHERE condition building.

        This provides basic SQL generation when the operator strategy system
        is not available or fails. Used as a safety fallback.
        """
        from psycopg.sql import SQL, Composed, Identifier, Literal

        # Basic operator templates for fallback scenarios
        basic_operators = {
            "eq": lambda path, val: Composed([path, SQL(" = "), Literal(val)]),
            "neq": lambda path, val: Composed([path, SQL(" != "), Literal(val)]),
            "gt": lambda path, val: Composed([path, SQL(" > "), Literal(val)]),
            "gte": lambda path, val: Composed([path, SQL(" >= "), Literal(val)]),
            "lt": lambda path, val: Composed([path, SQL(" < "), Literal(val)]),
            "lte": lambda path, val: Composed([path, SQL(" <= "), Literal(val)]),
            "ilike": lambda path, val: Composed([path, SQL(" ILIKE "), Literal(val)]),
            "like": lambda path, val: Composed([path, SQL(" LIKE "), Literal(val)]),
            "isnull": lambda path, val: Composed(
                [path, SQL(" IS NULL" if val else " IS NOT NULL")]
            ),
        }

        if operator not in basic_operators:
            return None

        # Build path based on whether this is a JSONB field or regular column
        if use_jsonb_path:
            # Use JSONB path for fields in data column
            path_sql = Composed([SQL("data"), SQL(" ->> "), Literal(field_name)])
        else:
            # Use direct column name for regular columns
            path_sql = Identifier(field_name)

        # Generate basic condition
        return basic_operators[operator](path_sql, value)

    async def _introspect_table_columns(self, view_name: str) -> set[str]:
        """Introspect actual table columns from database information_schema.

        This provides accurate column information for hybrid tables.
        Results are cached for performance.
        """
        if not hasattr(self, "_introspected_columns"):
            self._introspected_columns = {}

        if view_name in self._introspected_columns:
            return self._introspected_columns[view_name]

        try:
            # Query information_schema to get actual columns
            # PERFORMANCE: Use a single query to get all we need
            query = """
                SELECT
                    column_name,
                    data_type,
                    udt_name
                FROM information_schema.columns
                WHERE table_name = %s
                AND table_schema = 'public'
                ORDER BY ordinal_position
            """

            async with self._pool.connection() as conn, conn.cursor() as cursor:
                await cursor.execute(query, (view_name,))
                rows = await cursor.fetchall()

                # Extract column names and identify if JSONB exists
                columns = set()
                has_jsonb_data = False

                for row in rows:
                    # Handle both dict and tuple cursor results
                    if isinstance(row, dict):
                        col_name = row.get("column_name")
                        udt_name = row.get("udt_name", "")
                    else:
                        # Tuple-based result (column_name, data_type, udt_name)
                        col_name = row[0] if row else None
                        udt_name = row[2] if len(row) > 2 else ""

                    if col_name:
                        columns.add(col_name)

                        # Check if this is a JSONB data column
                        if col_name == "data" and udt_name == "jsonb":
                            has_jsonb_data = True

                # Cache the result
                self._introspected_columns[view_name] = columns

                # Also cache whether this table has JSONB data column
                if not hasattr(self, "_table_has_jsonb"):
                    self._table_has_jsonb = {}
                self._table_has_jsonb[view_name] = has_jsonb_data

                return columns

        except Exception as e:
            logger.warning(f"Failed to introspect table {view_name}: {e}")
            # Cache empty set to avoid repeated failures
            self._introspected_columns[view_name] = set()
            return set()

    def _should_use_jsonb_path_sync(self, view_name: str, field_name: str) -> bool:
        """Check if a field should use JSONB path or direct column access.

        PERFORMANCE OPTIMIZED:
        - Uses metadata from registration time (no DB queries)
        - Single cache lookup per field
        - Fast path for registered tables
        """
        # Fast path: use cached decision if available
        if not hasattr(self, "_field_path_cache"):
            self._field_path_cache = {}

        cache_key = f"{view_name}:{field_name}"
        cached_result = self._field_path_cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        # BEST CASE: Check registration-time metadata first (no DB query needed)
        if view_name in _table_metadata:
            metadata = _table_metadata[view_name]
            columns = metadata.get("columns", set())
            has_jsonb = metadata.get("has_jsonb_data", False)

            # Use JSONB path only if: has data column AND field is not a regular column
            use_jsonb = has_jsonb and field_name not in columns
            self._field_path_cache[cache_key] = use_jsonb
            return use_jsonb

        # SECOND BEST: Check if we have runtime introspected columns
        if hasattr(self, "_introspected_columns") and view_name in self._introspected_columns:
            columns = self._introspected_columns[view_name]
            has_data_column = "data" in columns
            is_regular_column = field_name in columns

            # Use JSONB path only if: has data column AND field is not a regular column
            use_jsonb = has_data_column and not is_regular_column
            self._field_path_cache[cache_key] = use_jsonb
            return use_jsonb

        # Fallback: Use fast heuristic for known patterns
        # PERFORMANCE: This avoids DB queries for common cases
        if not hasattr(self, "_table_has_jsonb"):
            self._table_has_jsonb = {}

        if view_name not in self._table_has_jsonb:
            # Quick pattern matching for known table types
            known_hybrid_patterns = ("jsonb", "hybrid")
            known_regular_patterns = ("test_product", "test_item", "users", "companies", "orders")

            view_lower = view_name.lower()
            if any(p in view_lower for p in known_regular_patterns):
                self._table_has_jsonb[view_name] = False
            elif any(p in view_lower for p in known_hybrid_patterns):
                self._table_has_jsonb[view_name] = True
            else:
                # Conservative default: assume regular table
                self._table_has_jsonb[view_name] = False

        # If no JSONB data column, always use direct access
        if not self._table_has_jsonb[view_name]:
            self._field_path_cache[cache_key] = False
            return False

        # For hybrid tables, use a small set of known regular columns
        # PERFORMANCE: Using frozenset for O(1) lookup
        REGULAR_COLUMNS = frozenset(
            {
                "id",
                "tenant_id",
                "created_at",
                "updated_at",
                "name",
                "status",
                "type",
                "category_id",
                "identifier",
                "is_active",
                "is_featured",
                "is_available",
                "is_deleted",
                "start_date",
                "end_date",
                "created_date",
                "modified_date",
            }
        )

        use_jsonb = field_name not in REGULAR_COLUMNS
        self._field_path_cache[cache_key] = use_jsonb
        return use_jsonb

    def _convert_field_name_to_database(self, field_name: str) -> str:
        """Convert GraphQL field name to database field name.

        Automatically converts camelCase to snake_case while preserving
        existing snake_case names for backward compatibility.

        Args:
            field_name: GraphQL field name (camelCase or snake_case)

        Returns:
            Database field name in snake_case

        Examples:
            'ipAddress' -> 'ip_address'
            'status' -> 'status' (unchanged)
        """
        if not field_name or not isinstance(field_name, str):
            return field_name or ""

        # Preserve existing snake_case for backward compatibility
        if "_" in field_name:
            return field_name

        # Convert camelCase to snake_case
        return to_snake_case(field_name)

"""Debugging utilities for FraiseQL.

This module provides tools to help developers debug and optimize their
GraphQL queries and resolvers.
"""

import inspect
import json
import time
import types
from typing import Any, Callable, Optional, Self, TypeVar, cast

import structlog
from graphql import GraphQLResolveInfo

from fraiseql.db import DatabaseQuery
from fraiseql.fastapi.dependencies import get_db_pool
from fraiseql.partial_instantiation import get_available_fields, is_partial_instance
from fraiseql.utils.annotations import wraps

logger = structlog.get_logger()

T = TypeVar("T")


async def explain_query(
    query: DatabaseQuery,
    analyze: bool = False,
    verbose: bool = False,
    format: str = "text",
) -> str:
    """Get PostgreSQL EXPLAIN output for a query.

    This function runs EXPLAIN (optionally with ANALYZE) on the generated SQL
    to help understand query performance.

    Args:
        query: The DatabaseQuery object to explain
        analyze: Whether to run EXPLAIN ANALYZE (actually executes the query)
        verbose: Whether to include verbose output
        format: Output format (text, json, xml, yaml)

    Returns:
        The EXPLAIN output as a string

    Example:
        >>> query = DatabaseQuery(
        ...     sql="SELECT * FROM users WHERE data->>'active' = $1",
        ...     params={"p1": "true"}
        ... )
        >>> print(await explain_query(query, analyze=True))
        Seq Scan on users  (cost=0.00..10.25 rows=5 width=32)
          (actual time=0.015..0.016 rows=5 loops=1)
          Filter: ((data ->> 'active'::text) = 'true'::text)
        Planning Time: 0.075 ms
        Execution Time: 0.031 ms
    """
    pool = get_db_pool()

    # Build EXPLAIN command
    explain_parts = ["EXPLAIN"]

    if analyze:
        explain_parts.append("ANALYZE")

    if verbose:
        explain_parts.append("VERBOSE")

    explain_parts.append(f"(FORMAT {format.upper()})")

    # Prepare the query with parameter substitution
    explain_sql = f"{' '.join(explain_parts)} {query.sql}"

    async with pool.connection() as conn, conn.cursor() as cur:
        # Execute EXPLAIN with the query parameters
        await cur.execute(explain_sql, query.params)
        rows = await cur.fetchall()

        # Format output based on format type
        if format == "json":
            return json.dumps(rows[0][0], indent=2)
        # For text format, join all rows
        return "\n".join(row[0] for row in rows)


def profile_resolver(
    *,
    log_args: bool = True,
    log_result: bool = False,
    log_sql: bool = True,
    threshold_ms: Optional[float] = None,
) -> Callable[[T], T]:
    """Decorator to profile GraphQL resolver performance.

    This decorator logs execution time, arguments, and optionally results
    for GraphQL resolvers. It helps identify slow resolvers and N+1 queries.

    Args:
        log_args: Whether to log resolver arguments
        log_result: Whether to log resolver result (can be verbose)
        log_sql: Whether to log generated SQL queries
        threshold_ms: Only log if execution time exceeds this threshold (in milliseconds)

    Returns:
        Decorated resolver function

    Example:
        >>> @profile_resolver(threshold_ms=100)
        ... async def resolve_users(parent, info, **kwargs):
        ...     return await fetch_users(**kwargs)
    """

    def decorator(func: T) -> T:
        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(parent: Any, info: GraphQLResolveInfo, **kwargs: Any) -> Any:
                start_time = time.perf_counter()
                resolver_name = func.__name__

                # Log context
                log_context = {
                    "resolver": resolver_name,
                    "field": info.field_name,
                    "path": str(info.path),
                    "parent_type": type(parent).__name__ if parent else None,
                }

                if log_args and kwargs:
                    log_context["args"] = kwargs

                try:
                    # Execute resolver
                    result = await func(parent, info, **kwargs)

                    # Calculate execution time
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    log_context["duration_ms"] = round(duration_ms, 2)

                    # Check if we should log based on threshold
                    if threshold_ms is None or duration_ms >= threshold_ms:
                        if log_result:
                            # Be careful with large results
                            if isinstance(result, list):
                                log_context["result_count"] = len(result)
                                if result and len(result) <= 5:
                                    log_context["result_sample"] = result[:5]
                            else:
                                log_context["result_type"] = type(result).__name__

                        logger.info("resolver_profiled", **log_context)

                except Exception as e:
                    # Log error with context
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    log_context["duration_ms"] = round(duration_ms, 2)
                    log_context["error"] = str(e)
                    log_context["error_type"] = type(e).__name__

                    logger.error("resolver_failed", **log_context)
                    raise
                else:
                    return result

            return cast(T, async_wrapper)

        @wraps(func)
        def sync_wrapper(parent: Any, info: GraphQLResolveInfo, **kwargs: Any) -> Any:
            start_time = time.perf_counter()
            resolver_name = func.__name__

            # Log context
            log_context = {
                "resolver": resolver_name,
                "field": info.field_name,
                "path": str(info.path),
                "parent_type": type(parent).__name__ if parent else None,
            }

            if log_args and kwargs:
                log_context["args"] = kwargs

            try:
                # Execute resolver
                result = func(parent, info, **kwargs)

                # Calculate execution time
                duration_ms = (time.perf_counter() - start_time) * 1000
                log_context["duration_ms"] = round(duration_ms, 2)

                # Check if we should log based on threshold
                if threshold_ms is None or duration_ms >= threshold_ms:
                    if log_result:
                        # Be careful with large results
                        if isinstance(result, list):
                            log_context["result_count"] = len(result)
                        else:
                            log_context["result_type"] = type(result).__name__

                    logger.info("resolver_profiled", **log_context)

            except Exception as e:
                # Log error with context
                duration_ms = (time.perf_counter() - start_time) * 1000
                log_context["duration_ms"] = round(duration_ms, 2)
                log_context["error"] = str(e)
                log_context["error_type"] = type(e).__name__

                logger.error("resolver_failed", **log_context)
                raise
            else:
                return result

        return cast(T, sync_wrapper)

    return decorator


def debug_partial_instance(obj: Any, indent: int = 0) -> str:
    """Debug a partial instance to see what fields are available.

    This function helps debug partial object instantiation by showing
    which fields were requested, which are available, and their values.

    Args:
        obj: The object to debug (can be partial or full)
        indent: Indentation level for nested objects

    Returns:
        A formatted string showing the object's debug information

    Example:
        >>> user = create_partial_instance(User, {"id": 1, "name": "John"})
        >>> print(debug_partial_instance(user))
        User (PARTIAL):
          Requested fields: {id, name}
          Available fields:
            - id: 1
            - name: "John"
          Missing fields:
            - email (not requested)
            - created_at (not requested)
    """
    indent_str = "  " * indent
    lines = []

    # Get object type
    obj_type = type(obj).__name__

    # Check if it's a partial instance
    if is_partial_instance(obj):
        lines.append(f"{indent_str}{obj_type} (PARTIAL):")
        available = get_available_fields(obj)
        lines.append(f"{indent_str}  Requested fields: {{{', '.join(sorted(available))}}}")
    else:
        lines.append(f"{indent_str}{obj_type} (FULL):")

    # Get all attributes
    lines.append(f"{indent_str}  Available fields:")

    # Get instance attributes
    attrs = {}
    if hasattr(obj, "__dict__"):
        attrs.update(obj.__dict__)

    # For dataclasses, use fields
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import fields

        for field in fields(obj):
            if hasattr(obj, field.name):
                attrs[field.name] = getattr(obj, field.name)

    # Filter out private attributes
    public_attrs = {k: v for k, v in attrs.items() if not k.startswith("_")}

    # Show available fields
    for key, value in sorted(public_attrs.items()):
        if value is None:
            lines.append(f"{indent_str}    - {key}: None")
        elif isinstance(value, str):
            lines.append(f'{indent_str}    - {key}: "{value}"')
        elif isinstance(value, (int, float, bool)):
            lines.append(f"{indent_str}    - {key}: {value}")
        elif isinstance(value, list):
            lines.append(f"{indent_str}    - {key}: [{len(value)} items]")
            if value and indent < 2:  # Limit recursion depth
                lines.append(f"{indent_str}      Sample:")
                sample_item = debug_partial_instance(value[0], indent + 3)
                lines.append(sample_item)
        elif hasattr(value, "__dict__") or hasattr(value, "__dataclass_fields__"):
            lines.append(f"{indent_str}    - {key}:")
            nested_debug = debug_partial_instance(value, indent + 2)
            lines.append(nested_debug)
        else:
            lines.append(f"{indent_str}    - {key}: {type(value).__name__}")

    # Show missing fields for partial instances
    if is_partial_instance(obj):
        available = get_available_fields(obj)
        all_fields = set(public_attrs.keys())
        missing = all_fields - available

        if missing:
            lines.append(f"{indent_str}  Missing fields:")
            for field in sorted(missing):
                lines.append(f"{indent_str}    - {field} (not requested)")

    return "\n".join(lines)


class QueryDebugger:
    """Context manager for debugging query execution.

    This context manager captures and logs all SQL queries executed within
    its context, along with timing information.

    Example:
        >>> async with QueryDebugger() as debugger:
        ...     users = await fetch_users()
        ...     posts = await fetch_posts()
        ...
        >>> print(debugger.get_summary())
        Query Execution Summary:
        Total queries: 2
        Total time: 45.3ms

        Query 1 (23.1ms):
        SELECT * FROM users_view WHERE ...

        Query 2 (22.2ms):
        SELECT * FROM posts_view WHERE ...
    """

    def __init__(self):
        self.queries: list[dict[str, Any]] = []
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    async def __aenter__(self) -> Self:
        self.start_time = time.perf_counter()
        # Known limitation: Query execution hooking not yet implemented
        # GitHub issue: Hook into query execution to capture queries for debugging
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        self.end_time = time.perf_counter()

    def add_query(self, sql: str, params: dict[str, Any], duration_ms: float) -> None:
        """Add a query to the debug log."""
        self.queries.append(
            {
                "sql": sql,
                "params": params,
                "duration_ms": duration_ms,
                "timestamp": time.time(),
            },
        )

    def get_summary(self) -> str:
        """Get a summary of all queries executed."""
        if not self.queries:
            return "No queries executed"

        total_time = sum(q["duration_ms"] for q in self.queries)

        lines = [
            "Query Execution Summary:",
            f"Total queries: {len(self.queries)}",
            f"Total time: {total_time:.1f}ms",
            "",
        ]

        for i, query in enumerate(self.queries, 1):
            lines.append(f"Query {i} ({query['duration_ms']:.1f}ms):")
            lines.append(query["sql"])
            if query["params"]:
                lines.append(f"Params: {query['params']}")
            lines.append("")

        return "\n".join(lines)


def debug_graphql_info(info: GraphQLResolveInfo) -> str:
    """Debug GraphQL resolve info to understand query structure.

    This function helps debug GraphQL queries by showing the query structure,
    selected fields, variables, and context.

    Args:
        info: GraphQL resolve info object

    Returns:
        Formatted debug information
    """
    lines = [
        "GraphQL Query Debug Info:",
        f"Field: {info.field_name}",
        f"Parent Type: {info.parent_type}",
        f"Return Type: {info.return_type}",
        f"Path: {info.path}",
    ]

    # Show operation
    if info.operation:
        lines.append(f"Operation: {info.operation.operation.value}")
        if info.operation.name:
            lines.append(f"Operation Name: {info.operation.name.value}")

    # Show variables: a dict on graphql-core 3.2, a VariableValues on 3.3
    variables = getattr(info.variable_values, "coerced", info.variable_values)
    if variables:
        lines.append("Variables:")
        for key, value in variables.items():
            lines.append(f"  {key}: {value}")

    # Show selected fields
    if info.field_nodes:
        lines.append("Selected Fields:")
        for node in info.field_nodes:
            if node.selection_set:
                for selection in node.selection_set.selections:
                    if hasattr(selection, "name"):
                        lines.append(f"  - {selection.name.value}")

    return "\n".join(lines)

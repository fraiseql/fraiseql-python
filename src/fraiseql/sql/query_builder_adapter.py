"""Adapter layer for switching between Python and Rust query builders.

This module provides a unified interface that can use either the legacy Python
query builder or the new Rust query builder based on feature flags.

Phase 7 Implementation - Production Integration
"""

import logging
import os
import random
import time
from collections.abc import Sequence
from typing import Any

from psycopg.sql import SQL, Composed

from fraiseql.config import (
    LOG_QUERY_BUILDER_MODE,
    RUST_QB_FALLBACK_ON_ERROR,
    RUST_QUERY_BUILDER_PERCENTAGE,
    USE_RUST_QUERY_BUILDER,
)

# Import Python builder (legacy, production)
from fraiseql.sql.sql_generator import build_sql_query as python_build_sql_query

# Import Rust builder (moved to unified FFI in Phase 3c)
# The query builder is now integrated into the Rust FFI pipeline
try:
    # For backward compatibility, we define a stub that reports unavailability
    # All query building is now handled by the unified Rust FFI boundary
    class RustQueryBuilder:
        """Deprecated: Query building now handled by unified Rust FFI.

        This class is a placeholder for backward compatibility.
        """

        @staticmethod
        def build(*args: any, **kwargs: any) -> None:
            """Deprecated query builder - no longer used."""
            raise NotImplementedError(
                "Direct RustQueryBuilder access has been moved to unified FFI layer. "
                "Use unified_ffi_adapter instead."
            )

    RUST_AVAILABLE = False  # Query building is now FFI-integrated
except ImportError:
    RUST_AVAILABLE = False

logger = logging.getLogger(__name__)

# Prometheus metrics (optional)
try:
    from fraiseql.monitoring.query_builder_metrics import (
        record_fallback as prom_record_fallback,
    )
    from fraiseql.monitoring.query_builder_metrics import (
        record_query_build,
        record_query_build_error,
        set_query_builder_mode,
    )

    PROMETHEUS_METRICS_AVAILABLE = True
except ImportError:
    PROMETHEUS_METRICS_AVAILABLE = False


class QueryBuilderMetrics:
    """Simple metrics collector for query builder usage."""

    def __init__(self) -> None:
        self.rust_calls = 0
        self.python_calls = 0
        self.rust_errors = 0
        self.rust_fallbacks = 0
        self.total_rust_time = 0.0
        self.total_python_time = 0.0

    def record_rust_call(self, duration: float) -> None:
        """Record successful Rust query builder call."""
        self.rust_calls += 1
        self.total_rust_time += duration

    def record_python_call(self, duration: float) -> None:
        """Record Python query builder call."""
        self.python_calls += 1
        self.total_python_time += duration

    def record_rust_error(self) -> None:
        """Record Rust query builder error."""
        self.rust_errors += 1

    def record_rust_fallback(self) -> None:
        """Record fallback from Rust to Python."""
        self.rust_fallbacks += 1

    def get_stats(self) -> dict[str, Any]:
        """Get current metrics."""
        total_calls = self.rust_calls + self.python_calls
        return {
            "rust_calls": self.rust_calls,
            "python_calls": self.python_calls,
            "rust_errors": self.rust_errors,
            "rust_fallbacks": self.rust_fallbacks,
            "total_calls": total_calls,
            "rust_percentage": ((self.rust_calls / total_calls * 100) if total_calls > 0 else 0),
            "rust_error_rate": (
                (self.rust_errors / self.rust_calls * 100) if self.rust_calls > 0 else 0
            ),
            "avg_rust_time_ms": (
                (self.total_rust_time / self.rust_calls * 1000) if self.rust_calls > 0 else 0
            ),
            "avg_python_time_ms": (
                (self.total_python_time / self.python_calls * 1000) if self.python_calls > 0 else 0
            ),
        }


# Global metrics instance
_metrics = QueryBuilderMetrics()


def get_query_builder_metrics() -> dict[str, Any]:
    """Get query builder usage metrics."""
    return _metrics.get_stats()


def build_sql_query(
    table: str,
    field_paths: Sequence[Any],
    where_clause: SQL | None = None,
    *,
    json_output: bool = False,
    typename: str | None = None,
    order_by: Sequence[tuple[str, str]] | None = None,
    group_by: Sequence[str] | None = None,
    auto_camel_case: bool = False,
    raw_json_output: bool = False,
    field_limit_threshold: int | None = None,
) -> Composed:
    """Build SQL query using Python or Rust based on feature flags.

    This is a drop-in replacement for sql_generator.build_sql_query that
    can dynamically switch between Python and Rust implementations.

    Args:
        table: Table name to query
        field_paths: Sequence of field paths to extract
        where_clause: Optional WHERE clause
        json_output: Whether to wrap output in jsonb_build_object
        typename: Optional GraphQL typename to include
        order_by: Optional list of (field_path, direction) tuples
        group_by: Optional list of field paths for GROUP BY
        auto_camel_case: Whether to preserve camelCase field paths
        raw_json_output: Whether to cast output to text
        field_limit_threshold: Field count threshold for full data column

    Returns:
        Composed SQL query
    """
    # Determine if we should use Rust
    use_rust = _should_use_rust()

    if LOG_QUERY_BUILDER_MODE:
        logger.debug(f"Query builder mode: {'Rust' if use_rust else 'Python'} (table={table})")

    if use_rust and RUST_AVAILABLE:
        try:
            start_time = time.perf_counter()
            result = _build_with_rust(
                table,
                field_paths,
                where_clause,
                json_output=json_output,
                typename=typename,
                order_by=order_by,
                group_by=group_by,
                auto_camel_case=auto_camel_case,
                raw_json_output=raw_json_output,
                field_limit_threshold=field_limit_threshold,
            )
            duration = time.perf_counter() - start_time
            _metrics.record_rust_call(duration)

            # Prometheus metrics
            if PROMETHEUS_METRICS_AVAILABLE:
                record_query_build("rust", duration)
                set_query_builder_mode(True)

            return result
        except Exception as e:
            _metrics.record_rust_error()

            # Prometheus metrics
            if PROMETHEUS_METRICS_AVAILABLE:
                record_query_build_error("rust")

            logger.warning(f"Rust query builder failed: {e}", exc_info=True)

            if RUST_QB_FALLBACK_ON_ERROR:
                _metrics.record_rust_fallback()

                # Prometheus metrics
                if PROMETHEUS_METRICS_AVAILABLE:
                    prom_record_fallback()

                logger.info("Falling back to Python query builder")
                # Fall through to Python implementation
            else:
                # Re-raise if fallback disabled
                raise

    # Use Python implementation (original)
    start_time = time.perf_counter()
    result = python_build_sql_query(
        table,
        field_paths,
        where_clause,
        json_output=json_output,
        typename=typename,
        order_by=order_by,
        group_by=group_by,
        auto_camel_case=auto_camel_case,
        raw_json_output=raw_json_output,
        field_limit_threshold=field_limit_threshold,
    )
    duration = time.perf_counter() - start_time
    _metrics.record_python_call(duration)

    # Prometheus metrics
    if PROMETHEUS_METRICS_AVAILABLE:
        record_query_build("python", duration)
        set_query_builder_mode(False)

    return result


def _should_use_rust() -> bool:
    """Determine if Rust query builder should be used.

    Returns:
        True if Rust should be used, False for Python
    """
    if not RUST_AVAILABLE:
        return False

    # Explicit disable - prefer Python (for debugging/fallback)
    # Environment variable: FRAISEQL_USE_PYTHON_QUERY_BUILDER=true
    use_python = os.getenv("FRAISEQL_USE_PYTHON_QUERY_BUILDER", "false").lower() in (
        "true",
        "1",
        "yes",
    )
    if use_python:
        return False

    # Explicit enable/disable
    if USE_RUST_QUERY_BUILDER:
        return True

    # Gradual rollout percentage
    if RUST_QUERY_BUILDER_PERCENTAGE > 0:
        # NOTE: S311 suppressed - random is fine for traffic sampling (not cryptographic)
        return random.randint(1, 100) <= RUST_QUERY_BUILDER_PERCENTAGE  # noqa: S311

    # Default to Rust (Phase A: all systems use Rust query builder)
    return True


def _build_with_rust(
    table: str,
    field_paths: Sequence[Any],
    where_clause: SQL | None = None,
    **kwargs: Any,
) -> Composed:
    """Build SQL query using Rust query builder.

    This function converts Python parameters to Rust format, calls the Rust
    builder, and converts the result back to Python Composed SQL.

    Args:
        table: Table name
        field_paths: Field paths to select
        where_clause: WHERE clause (Phase 7.1: converted to SQL string)
        **kwargs: Additional parameters (order_by, group_by, etc.)

    Returns:
        Composed SQL query

    Note:
        Phase 7.1: Supports WHERE SQL pass-through and ORDER BY tuples.
    """
    # Import here to avoid circular dependencies
    from fraiseql.core.graphql_parser import ParsedQuery
    from fraiseql.graphql.types import FieldSelection

    # 1. Create ParsedQuery from table + field_paths
    field_selections = [
        FieldSelection(
            name=getattr(fp, "field_name", str(fp)),
            selections=[],
            arguments=[],
        )
        for fp in field_paths
    ]

    # 2. Build arguments (empty - WHERE/ORDER BY passed via schema metadata)
    arguments = []

    # Create root field selection
    root_field = FieldSelection(
        name=table,
        selections=field_selections,
        arguments=arguments,
    )

    parsed_query = ParsedQuery(
        operation_type="query",
        operation_name=None,
        selections=[root_field],
        variables=[],
        fragments=[],
    )

    # 3. Build schema metadata with Phase 7.1 enhancements
    schema_metadata = _build_schema_metadata(table, field_paths, where_clause, kwargs)

    # 4. Call Rust builder
    builder = RustQueryBuilder()
    rust_result = builder.build_cached(parsed_query, schema_metadata)

    # 5. Convert Rust GeneratedQuery to Composed SQL
    sql_text = rust_result.sql

    return Composed([SQL(sql_text)])


def _build_schema_metadata(
    table: str,
    field_paths: Sequence[Any],
    where_clause: SQL | None,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Build schema metadata for Rust query builder.

    Phase 7.1: Integrates schema registry and passes WHERE SQL + ORDER BY.

    Args:
        table: Table name
        field_paths: Field paths to select
        where_clause: Optional WHERE clause (psycopg SQL object)
        kwargs: Additional parameters (order_by, etc.)

    Returns:
        Schema metadata dict for Rust
    """
    # Try to get schema from registry
    from fraiseql.db import _table_metadata

    metadata = _table_metadata.get(table, {})

    # Extract SQL columns from metadata or infer
    sql_columns = (
        list(metadata.get("columns", set()))
        if metadata.get("columns")
        else _infer_sql_columns(table, field_paths)
    )

    # Convert WHERE clause to SQL string (Phase 7.1)
    where_sql = None
    if where_clause is not None:
        from fraiseql.sql.sql_to_string import sql_to_string

        where_sql = sql_to_string(where_clause)
        if LOG_QUERY_BUILDER_MODE:
            logger.debug(f"Phase 7.1: Passing WHERE SQL to Rust: {where_sql}")

    # Convert ORDER BY to tuples (Phase 7.1)
    order_by_tuples = []
    if kwargs.get("order_by"):
        order_by = kwargs["order_by"]
        # order_by comes as list of (field, direction) tuples
        order_by_tuples = [(str(field), str(direction)) for field, direction in order_by]
        if LOG_QUERY_BUILDER_MODE:
            logger.debug(f"Phase 7.1: Passing ORDER BY to Rust: {order_by_tuples}")

    # Build table schema
    table_schema = {
        "view_name": table,
        "sql_columns": sql_columns,
        "jsonb_column": metadata.get("jsonb_column", "data"),
        "fk_mappings": metadata.get("fk_mappings", {}),
        "has_jsonb_data": metadata.get("has_jsonb_data", True),
        # Phase 7.1 additions
        "where_sql": where_sql,
        "order_by": order_by_tuples,
    }

    return {
        "tables": {table: table_schema},
        "types": {},
    }


def _infer_sql_columns(table: str, field_paths: Sequence[Any]) -> list[str]:
    """Infer SQL columns from field paths (fallback when schema unavailable).

    Phase 7.1: This is now a fallback - primary source is schema registry.

    Args:
        table: Table name
        field_paths: Field paths being selected

    Returns:
        List of common SQL column names
    """
    # Common SQL columns in FraiseQL
    # These are typically direct columns, not JSONB fields
    common_sql_columns = {
        "id",
        "uuid",
        "created_at",
        "updated_at",
        "deleted_at",
        "created_by",
        "updated_by",
        "status",
        "type",
    }

    # Return common columns as fallback
    return list(common_sql_columns)

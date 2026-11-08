"""Unified query executor with mode switching."""

import time
from typing import Any, Optional

from graphql import GraphQLSchema

from fraiseql.analysis.query_analyzer import QueryAnalyzer
from fraiseql.errors.masking import (
    INTERNAL_ERROR_CODE,
    INTERNAL_ERROR_MESSAGE,
    mask_database_error,
)
from fraiseql.execution.mode_selector import ExecutionMode, ModeSelector
from fraiseql.fastapi.json_encoder import clean_unset_values
from fraiseql.fastapi.turbo import TurboRouter
from fraiseql.graphql.execute import execute_graphql


class UnifiedExecutor:
    """Unified executor for all query execution modes."""

    def __init__(
        self,
        schema: GraphQLSchema,
        mode_selector: ModeSelector,
        turbo_router: Optional[TurboRouter] = None,
        query_analyzer: Optional[QueryAnalyzer] = None,
    ) -> None:
        """Initialize unified executor.

        Args:
            schema: GraphQL schema
            mode_selector: Mode selection logic
            turbo_router: Optional TurboRouter instance
            query_analyzer: Optional QueryAnalyzer instance
        """
        self.schema = schema
        self.mode_selector = mode_selector
        self.turbo_router = turbo_router
        self.query_analyzer = query_analyzer or QueryAnalyzer(schema)

        # Set dependencies in mode selector
        if turbo_router:
            mode_selector.set_turbo_registry(turbo_router.registry)
        mode_selector.set_query_analyzer(self.query_analyzer)

        # Metrics
        self._execution_counts = {
            ExecutionMode.NORMAL: 0,  # Only track unified execution
        }
        self._execution_times = {
            ExecutionMode.NORMAL: [],
        }

    async def execute(
        self,
        query: str,
        variables: Optional[dict[str, Any]] = None,
        operation_name: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute query using unified Rust-first pipeline.

        Args:
            query: GraphQL query string
            variables: Query variables
            operation_name: Operation name for multi-operation documents
            context: Request context

        Returns:
            GraphQL response dictionary
        """
        if context is None:
            context = {}

        if variables is None:
            variables = {}

        start_time = time.time()

        # Execute using standard GraphQL execution (resolvers use Rust pipeline internally)
        try:
            execution_result = await execute_graphql(
                self.schema,
                query,
                context_value=context,
                variable_values=variables,
                operation_name=operation_name,
                enable_introspection=getattr(
                    self.mode_selector.config, "enable_introspection", True
                ),
            )

            # Track metrics
            execution_time = time.time() - start_time
            # Use NORMAL mode for tracking (since we're unified)
            self._track_execution(ExecutionMode.NORMAL, execution_time)

            # 🚀 RUST RESPONSE BYTES PASS-THROUGH (Unified Executor):
            # Check if execution returned RustResponseBytes directly (zero-copy path)
            # This happens when resolvers return JSONB entities via Rust pipeline
            from fraiseql.core.rust_pipeline import RustResponseBytes

            if isinstance(execution_result, RustResponseBytes):
                # Return RustResponseBytes directly - it will be handled by the router
                return execution_result

            # Convert ExecutionResult to dict
            result = {}
            if execution_result.data is not None:
                result["data"] = execution_result.data
            if execution_result.errors:
                result["errors"] = [self._format_error(error) for error in execution_result.errors]

            # Add execution metadata if requested
            if context.get("include_execution_metadata"):
                if "extensions" not in result:
                    result["extensions"] = {}

                result["extensions"]["execution"] = {
                    "mode": "unified_rust",
                    "time_ms": round(execution_time * 1000, 2),
                }

            return result

        except Exception as e:
            # Log error
            import logging

            logger = logging.getLogger(__name__)
            logger.exception("Query execution failed in unified Rust mode")

            # Return error response (the exception's text stays in the log in production)
            if self._is_production:
                return {
                    "errors": [
                        {
                            "message": INTERNAL_ERROR_MESSAGE,
                            "extensions": {"code": INTERNAL_ERROR_CODE},
                        }
                    ]
                }
            return {
                "errors": [
                    {
                        "message": str(e),
                        "extensions": {
                            "code": "EXECUTION_ERROR",
                            "mode": "unified_rust",
                        },
                    }
                ]
            }

    @property
    def _is_production(self) -> bool:
        """Whether the configured environment is ``"production"``."""
        return getattr(self.mode_selector.config, "environment", None) == "production"

    def _format_error(self, error: Any) -> dict[str, Any]:
        """Format GraphQL error for response.

        Args:
            error: GraphQL error

        Returns:
            Formatted error dictionary
        """
        formatted = {
            "message": error.message,
        }

        if error.locations:
            formatted["locations"] = [
                {"line": loc.line, "column": loc.column} for loc in error.locations
            ]

        if error.path:
            formatted["path"] = error.path

        if error.extensions:
            formatted["extensions"] = clean_unset_values(error.extensions)

        if self._is_production:
            # A database error's message carries the failing SQL
            formatted = mask_database_error(formatted, error)

        return formatted

    def _track_execution(self, mode: ExecutionMode, execution_time: float) -> None:
        """Track execution metrics.

        Args:
            mode: Execution mode used
            execution_time: Time taken in seconds
        """
        self._execution_counts[mode] += 1

        # Keep last 100 execution times
        times = self._execution_times[mode]
        times.append(execution_time)
        if len(times) > 100:
            times.pop(0)

    def get_metrics(self) -> dict[str, Any]:
        """Get execution metrics.

        Returns:
            Dictionary of metrics
        """
        metrics = {
            "execution_counts": {
                mode.value: count for mode, count in self._execution_counts.items()
            },
            "average_execution_times": {},
            "mode_selector_metrics": self.mode_selector.get_mode_metrics(),
        }

        # Calculate average execution times
        for mode, times in self._execution_times.items():
            if times:
                avg_time = sum(times) / len(times)
                metrics["average_execution_times"][mode.value] = round(avg_time * 1000, 2)
            else:
                metrics["average_execution_times"][mode.value] = 0

        # Add cache metrics if available
        if self.turbo_router and hasattr(self.turbo_router.registry, "get_metrics"):
            metrics["turbo_cache_metrics"] = self.turbo_router.registry.get_metrics()

        return metrics

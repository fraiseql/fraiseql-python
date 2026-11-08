"""N+1 query detection for development mode.

This module provides tools to detect and warn about potential N+1 query patterns
in GraphQL resolvers during development.
"""

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Callable

from graphql import GraphQLResolveInfo

from fraiseql.utils.paths import format_path

logger = logging.getLogger(__name__)


@dataclass
class QueryPattern:
    """Represents a query pattern for N+1 detection."""

    field_path: str
    parent_type: str
    field_name: str
    resolver_name: str
    count: int = 0
    execution_times: list[float] = field(default_factory=list)

    @property
    def avg_execution_time(self) -> float:
        """Calculate average execution time."""
        if not self.execution_times:
            return 0.0
        return sum(self.execution_times) / len(self.execution_times)


@dataclass
class N1DetectionResult:
    """Result of N+1 query detection."""

    detected: bool
    patterns: list[QueryPattern]
    suggestions: list[str]
    total_queries: int
    threshold_exceeded: bool


class N1QueryDetector:
    """Detects potential N+1 query patterns in GraphQL execution."""

    def __init__(
        self,
        threshold: int = 10,
        time_window: float = 1.0,
        enabled: bool = True,
        raise_on_detection: bool = False,
    ) -> None:
        """Initialize N+1 query detector.

        Args:
            threshold: Number of similar queries to trigger detection
            time_window: Time window in seconds to group queries
            enabled: Whether detection is enabled
            raise_on_detection: Whether to raise exception on detection
        """
        self.threshold = threshold
        self.time_window = time_window
        self.enabled = enabled
        self.raise_on_detection = raise_on_detection

        # Track query patterns
        self._patterns: dict[str, QueryPattern] = {}
        self._pattern_timestamps: dict[str, list[float]] = defaultdict(list)
        self._current_request_id: str | None = None
        self._lock = asyncio.Lock()

    def start_request(self, request_id: str) -> None:
        """Start tracking a new request."""
        if not self.enabled:
            return

        self._current_request_id = request_id
        self._patterns.clear()
        self._pattern_timestamps.clear()

    def end_request(self) -> N1DetectionResult:
        """End request tracking and return detection results."""
        if not self.enabled:
            return N1DetectionResult(
                detected=False,
                patterns=[],
                suggestions=[],
                total_queries=0,
                threshold_exceeded=False,
            )

        # Analyze patterns
        detected_patterns = []
        suggestions = []
        total_queries = 0

        for pattern in self._patterns.values():
            total_queries += pattern.count

            # Check if pattern exceeds threshold
            if pattern.count > self.threshold:
                detected_patterns.append(pattern)

                # Generate suggestion
                suggestion = (
                    f"Field '{pattern.field_name}' on type '{pattern.parent_type}' "
                    f"was resolved {pattern.count} times. Consider using a DataLoader "
                    f"to batch these queries."
                )
                suggestions.append(suggestion)

        detected = len(detected_patterns) > 0
        threshold_exceeded = any(p.count > self.threshold for p in detected_patterns)

        result = N1DetectionResult(
            detected=detected,
            patterns=detected_patterns,
            suggestions=suggestions,
            total_queries=total_queries,
            threshold_exceeded=threshold_exceeded,
        )

        # Log warnings if patterns detected
        if detected:
            logger.warning("N+1 query pattern detected in request %s:", self._current_request_id)
            for suggestion in suggestions:
                logger.warning("  - %s", suggestion)

        # Optionally raise exception
        if self.raise_on_detection and threshold_exceeded:
            msg = f"N+1 query pattern detected: {len(detected_patterns)} patterns found"
            raise N1QueryDetectedError(
                msg,
                patterns=detected_patterns,
            )

        return result

    async def track_field_resolution(
        self,
        info: GraphQLResolveInfo,
        field_name: str,
        execution_time: float,
    ) -> None:
        """Track a field resolution for N+1 detection.

        Args:
            info: GraphQL resolve info
            field_name: Name of the field being resolved
            execution_time: Time taken to resolve the field
        """
        if not self.enabled or not self._current_request_id:
            return

        async with self._lock:
            # Build pattern key
            parent_type = info.parent_type.name if info.parent_type else "Unknown"
            # List indices dropped: the pattern is the field, not one list item
            field_path = format_path(info.path, keep_indices=False)
            pattern_key = f"{parent_type}.{field_name}"

            # Get or create pattern
            if pattern_key not in self._patterns:
                self._patterns[pattern_key] = QueryPattern(
                    field_path=field_path,
                    parent_type=parent_type,
                    field_name=field_name,
                    resolver_name=f"{parent_type}.{field_name}",
                )

            pattern = self._patterns[pattern_key]
            pattern.count += 1
            pattern.execution_times.append(execution_time)

            # Track timestamp for time window analysis
            current_time = time.time()
            self._pattern_timestamps[pattern_key].append(current_time)

            # Clean old timestamps outside time window
            cutoff_time = current_time - self.time_window
            self._pattern_timestamps[pattern_key] = [
                ts for ts in self._pattern_timestamps[pattern_key] if ts > cutoff_time
            ]


class N1QueryDetectedError(Exception):
    """Exception raised when N+1 query pattern is detected."""

    def __init__(self, message: str, patterns: list[QueryPattern]) -> None:
        super().__init__(message)
        self.patterns = patterns


# Global detector instance
_detector: N1QueryDetector | None = None


def get_detector() -> N1QueryDetector:
    """Get the global N+1 query detector instance."""
    global _detector
    if _detector is None:
        _detector = N1QueryDetector()
    return _detector


def configure_detector(
    threshold: int = 10,
    time_window: float = 1.0,
    enabled: bool = True,
    raise_on_detection: bool = False,
) -> N1QueryDetector:
    """Configure the global N+1 query detector.

    Args:
        threshold: Number of similar queries to trigger detection
        time_window: Time window in seconds to group queries
        enabled: Whether detection is enabled
        raise_on_detection: Whether to raise exception on detection

    Returns:
        Configured detector instance
    """
    global _detector
    _detector = N1QueryDetector(
        threshold=threshold,
        time_window=time_window,
        enabled=enabled,
        raise_on_detection=raise_on_detection,
    )
    return _detector


@asynccontextmanager
async def n1_detection_context(request_id: str) -> AsyncGenerator[N1QueryDetector]:
    """Context manager for N+1 query detection during a request.

    Args:
        request_id: Unique identifier for the request

    Yields:
        N1QueryDetector instance
    """
    detector = get_detector()
    detector.start_request(request_id)

    try:
        yield detector
    except Exception:
        # If there's an exception during execution, still run detection
        # but re-raise the original exception
        detector.end_request()
        raise
    else:
        # Normal completion - run detection and potentially raise N+1 error
        detector.end_request()


def track_resolver_execution(func: Callable[..., Any]) -> Callable:
    """Decorator to track resolver execution for N+1 detection.

    This decorator should be applied to GraphQL field resolvers
    to track their execution patterns.
    """

    async def wrapper(self: Any, info: GraphQLResolveInfo, *args: Any, **kwargs: Any) -> Any:
        detector = get_detector()

        if not detector.enabled:
            # Just execute the resolver without tracking
            return await func(self, info, *args, **kwargs)

        # Track execution time
        start_time = time.time()
        try:
            result = await func(self, info, *args, **kwargs)
            execution_time = time.time() - start_time

            # Track the field resolution
            field_name = info.field_name
            await detector.track_field_resolution(info, field_name, execution_time)

            return result
        except Exception:
            # Still track failed resolutions
            execution_time = time.time() - start_time
            field_name = info.field_name
            await detector.track_field_resolution(info, field_name, execution_time)
            raise

    # Handle sync functions
    if not asyncio.iscoroutinefunction(func):

        def sync_wrapper(self: Any, info: GraphQLResolveInfo, *args: Any, **kwargs: Any) -> Any:
            detector = get_detector()

            if not detector.enabled:
                return func(self, info, *args, **kwargs)

            start_time = time.time()
            try:
                result = func(self, info, *args, **kwargs)
                execution_time = time.time() - start_time

                # Create a task to track asynchronously
                field_name = info.field_name
                _ = asyncio.create_task(  # noqa: RUF006
                    detector.track_field_resolution(info, field_name, execution_time),
                )

                return result
            except Exception:
                execution_time = time.time() - start_time
                field_name = info.field_name
                _ = asyncio.create_task(  # noqa: RUF006
                    detector.track_field_resolution(info, field_name, execution_time),
                )
                raise

        return sync_wrapper

    return wrapper

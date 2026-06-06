"""Enhanced TurboRouter with query complexity analysis.

This module extends the basic TurboRouter with:
- Query complexity-based admission control
- Weighted cache management
- Adaptive cache sizing
- Performance metrics
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fraiseql.analysis import ComplexityScore, analyze_query_complexity
from fraiseql.analysis.complexity_config import ComplexityConfig
from fraiseql.fastapi.turbo import TurboQuery, TurboRegistry, TurboRouter

if TYPE_CHECKING:
    from graphql import GraphQLSchema

    from fraiseql.security.authorization import Authorizer


@dataclass
class EnhancedTurboQuery(TurboQuery):
    """TurboQuery with complexity analysis metadata."""

    complexity_score: ComplexityScore = field(default_factory=ComplexityScore)
    cache_weight: float = 1.0
    hit_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    avg_execution_time: float = 0.0

    def update_stats(self, execution_time: float) -> None:
        """Update query statistics after execution.

        Args:
            execution_time: Time taken to execute the query in seconds
        """
        self.hit_count += 1
        self.last_accessed = time.time()

        # Update average execution time
        if self.avg_execution_time == 0:
            self.avg_execution_time = execution_time
        else:
            # Exponential moving average
            self.avg_execution_time = 0.8 * self.avg_execution_time + 0.2 * execution_time

    @property
    def cache_score(self) -> float:
        """Calculate cache priority score.

        Considers:
        - Hit frequency
        - Complexity (lower is better for caching)
        - Execution time savings
        - Recency
        """
        # Normalize factors
        frequency_score = min(self.hit_count / 100, 1.0)  # Cap at 100 hits
        complexity_factor = 1.0 / (1.0 + self.cache_weight)  # Inverse - simpler is better
        time_savings = min(self.avg_execution_time * 1000, 1.0)  # ms saved, cap at 1
        recency = 1.0 / (1.0 + (time.time() - self.last_accessed) / 3600)  # Decay over hours

        return frequency_score * complexity_factor * time_savings * recency


class EnhancedTurboRegistry(TurboRegistry):
    """TurboRegistry with complexity-aware cache management."""

    def __init__(
        self,
        max_size: int = 1000,
        max_complexity: int | None = None,
        max_total_weight: float = 2000.0,
        schema: GraphQLSchema | None = None,
        config: ComplexityConfig | None = None,
    ) -> None:
        """Initialize the enhanced registry.

        Args:
            max_size: Maximum number of queries to cache
            max_complexity: Max complexity score for caching
                (uses config default if None)
            max_total_weight: Maximum total weight of cached queries
            schema: Optional GraphQL schema for analysis
            config: Complexity configuration (uses default if None)
        """
        super().__init__(max_size)
        self.config = config or ComplexityConfig.get_default()
        self.max_complexity = max_complexity or self.config.complex_query_threshold
        self.max_total_weight = max_total_weight
        self.schema = schema
        self._total_weight = 0.0
        self._metrics = {
            "total_queries_analyzed": 0,
            "queries_rejected_complexity": 0,
            "queries_evicted_weight": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }

    def analyze_query(self, query: str) -> tuple[ComplexityScore, float]:
        """Analyze a query's complexity.

        Args:
            query: GraphQL query string

        Returns:
            Tuple of (complexity_score, cache_weight)
        """
        self._metrics["total_queries_analyzed"] += 1
        score = analyze_query_complexity(query, self.schema, self.config)
        return score, score.cache_weight

    def should_cache(self, complexity_score: ComplexityScore) -> bool:
        """Determine if a query should be cached based on complexity.

        Args:
            complexity_score: The query's complexity score

        Returns:
            True if the query should be cached
        """
        should = complexity_score.should_cache(self.max_complexity)
        if not should:
            self._metrics["queries_rejected_complexity"] += 1
        return should

    def register(self, turbo_query: TurboQuery) -> str | None:
        """Register a TurboQuery with complexity analysis.

        Args:
            turbo_query: The TurboQuery to register

        Returns:
            The hash of the registered query, or None if rejected
        """
        # Analyze complexity
        complexity_score, cache_weight = self.analyze_query(turbo_query.graphql_query)

        # Check if we should cache
        if not self.should_cache(complexity_score):
            return None

        # Create enhanced query
        if not isinstance(turbo_query, EnhancedTurboQuery):
            enhanced = EnhancedTurboQuery(
                graphql_query=turbo_query.graphql_query,
                sql_template=turbo_query.sql_template,
                param_mapping=turbo_query.param_mapping,
                operation_name=turbo_query.operation_name,
                complexity_score=complexity_score,
                cache_weight=cache_weight,
            )
        else:
            enhanced = turbo_query
            enhanced.complexity_score = complexity_score
            enhanced.cache_weight = cache_weight

        query_hash = self.hash_query(enhanced.graphql_query)

        # Check if we have space (considering weight)
        if query_hash not in self._queries:
            self._evict_if_needed(cache_weight)

        # Add or update
        if query_hash in self._queries:
            old_weight = self._queries[query_hash].cache_weight
            self._total_weight -= old_weight
            self._queries.move_to_end(query_hash)

        self._queries[query_hash] = enhanced
        self._total_weight += cache_weight

        return query_hash

    def _evict_if_needed(self, new_weight: float) -> None:
        """Evict queries if needed to make space.

        Args:
            new_weight: Weight of the query to be added
        """
        # Evict by weight limit
        while self._total_weight + new_weight > self.max_total_weight and self._queries:
            self._evict_lowest_priority()

        # Evict by count limit
        while len(self._queries) >= self.max_size and self._queries:
            self._evict_lowest_priority()

    def _evict_lowest_priority(self) -> None:
        """Evict the query with the lowest cache priority score."""
        if not self._queries:
            return

        # Find query with lowest cache score
        min_score = float("inf")
        min_key = None

        for key, query in self._queries.items():
            if isinstance(query, EnhancedTurboQuery):
                score = query.cache_score
                if score < min_score:
                    min_score = score
                    min_key = key

        if min_key is None:
            # Fallback to LRU
            min_key = next(iter(self._queries))

        # Evict
        evicted = self._queries.pop(min_key)
        if isinstance(evicted, EnhancedTurboQuery):
            self._total_weight -= evicted.cache_weight
        self._metrics["queries_evicted_weight"] += 1

    def get(self, query: str) -> EnhancedTurboQuery | None:
        """Get a registered TurboQuery with metrics tracking.

        Args:
            query: GraphQL query string

        Returns:
            EnhancedTurboQuery if registered, None otherwise
        """
        result = super().get(query)

        if result is not None:
            self._metrics["cache_hits"] += 1
            # Ensure we return the correct type
            if isinstance(result, EnhancedTurboQuery):
                return result
            # This shouldn't happen if registry is used correctly
            return None
        self._metrics["cache_misses"] += 1
        return None

    def get_metrics(self) -> dict[str, Any]:
        """Get cache performance metrics.

        Returns:
            Dictionary of metrics
        """
        hit_rate = 0.0
        total_requests = self._metrics["cache_hits"] + self._metrics["cache_misses"]
        if total_requests > 0:
            hit_rate = self._metrics["cache_hits"] / total_requests

        return {
            **self._metrics,
            "cache_size": len(self._queries),
            "total_weight": self._total_weight,
            "hit_rate": hit_rate,
            "weight_utilization": self._total_weight / self.max_total_weight,
        }


class EnhancedTurboRouter(TurboRouter):
    """TurboRouter with complexity analysis and adaptive caching."""

    def __init__(
        self,
        registry: EnhancedTurboRegistry,
        default_authorizer: Authorizer | None = None,
    ) -> None:
        """Initialize the enhanced router.

        Args:
            registry: EnhancedTurboRegistry with complexity analysis
            default_authorizer: Optional global operation authorizer (issue #362),
                passed through to the base TurboRouter so a single gate in
                ``TurboRouter.execute`` covers both routers.
        """
        super().__init__(registry, default_authorizer=default_authorizer)
        self.registry: EnhancedTurboRegistry = registry  # Type hint override

    async def execute(
        self,
        query: str,
        variables: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Execute a query with performance tracking.

        Args:
            query: GraphQL query string
            variables: GraphQL variables
            context: Request context

        Returns:
            Query result if executed via turbo path, None otherwise
        """
        start_time = time.time()

        # Try to get from cache
        turbo_query = self.registry.get(query)
        if turbo_query is None:
            return None

        # Execute using parent class
        result = await super().execute(query, variables, context)

        # Update statistics
        if isinstance(turbo_query, EnhancedTurboQuery) and result is not None:
            execution_time = time.time() - start_time
            turbo_query.update_stats(execution_time)

        return result

    def should_register(self, query: str) -> bool:
        """Check if a query should be registered for turbo execution.

        Args:
            query: GraphQL query string

        Returns:
            True if the query should be registered
        """
        score, _ = self.registry.analyze_query(query)
        return self.registry.should_cache(score)

    def get_query_stats(self, query: str) -> dict[str, Any] | None:
        """Get statistics for a cached query.

        Args:
            query: GraphQL query string

        Returns:
            Query statistics or None if not cached
        """
        turbo_query = self.registry.get(query)
        if isinstance(turbo_query, EnhancedTurboQuery):
            return {
                "complexity_score": turbo_query.complexity_score.total_score,
                "cache_weight": turbo_query.cache_weight,
                "hit_count": turbo_query.hit_count,
                "avg_execution_time_ms": turbo_query.avg_execution_time * 1000,
                "cache_priority_score": turbo_query.cache_score,
            }
        return None

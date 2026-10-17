"""Enhanced TurboRouter with complexity-based caching and adaptive behavior."""

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional

from fraiseql.fastapi.turbo import TurboQuery, TurboRegistry, TurboRouter


@dataclass
class EnhancedTurboQuery(TurboQuery):
    """Extended TurboQuery with complexity metrics."""

    complexity_score: int = 0
    avg_execution_time: float = 0.0
    execution_count: int = 0
    last_executed: float = 0.0
    cache_hits: int = 0
    cache_weight: float = 1.0  # For weighted cache admission


class EnhancedTurboRegistry(TurboRegistry):
    """Advanced registry with complexity-based admission and eviction."""

    def __init__(
        self,
        max_size: int = 1000,
        max_total_weight: float = 2000.0,
        enable_adaptive_caching: bool = True,
    ) -> None:
        """Initialize enhanced registry.

        Args:
            max_size: Maximum number of queries to cache
            max_total_weight: Maximum total weight of cached queries
            enable_adaptive_caching: Enable complexity-based admission
        """
        super().__init__(max_size)
        self.max_total_weight = max_total_weight
        self.enable_adaptive_caching = enable_adaptive_caching
        self.total_weight = 0.0

    def calculate_cache_weight(self, query: EnhancedTurboQuery) -> float:
        """Calculate cache weight based on complexity and usage.

        Args:
            query: The query to evaluate

        Returns:
            Cache weight score
        """
        # Base weight on complexity
        weight = query.complexity_score / 10.0

        # Adjust for execution frequency
        if query.execution_count > 0:
            frequency_factor = min(query.execution_count / 100.0, 2.0)
            weight *= frequency_factor

        # Adjust for cache hit rate
        if query.cache_hits > 0:
            hit_rate = query.cache_hits / max(query.execution_count, 1)
            weight *= 1 + hit_rate

        return max(weight, 0.1)  # Minimum weight

    def should_admit(self, turbo_query: EnhancedTurboQuery) -> bool:
        """Determine if query should be admitted to cache.

        Args:
            turbo_query: Query to evaluate

        Returns:
            True if query should be cached
        """
        if not self.enable_adaptive_caching:
            return True

        # Always admit if under limits
        if len(self._queries) < self.max_size / 2:
            return True

        # Calculate weight
        weight = self.calculate_cache_weight(turbo_query)

        # Check if we have room for this weight
        if self.total_weight + weight <= self.max_total_weight:
            return True

        # Check if this query is better than the worst cached query
        if self._queries:
            worst_query = min(self._queries.values(), key=lambda q: q.cache_weight)
            if weight > worst_query.cache_weight * 1.5:
                return True

        return False

    def register(self, turbo_query: EnhancedTurboQuery) -> Optional[str]:
        """Register a TurboQuery with admission control.

        Args:
            turbo_query: The query to register

        Returns:
            Query hash if registered, None if rejected
        """
        # Check admission
        if not self.should_admit(turbo_query):
            return None

        query_hash = self.hash_query(turbo_query.graphql_query)

        # Update weight
        turbo_query.cache_weight = self.calculate_cache_weight(turbo_query)

        # Move to end if already exists
        if query_hash in self._queries:
            old_weight = self._queries[query_hash].cache_weight
            self.total_weight -= old_weight
            self._queries.move_to_end(query_hash)
        else:
            # Evict if necessary
            while (
                len(self._queries) >= self.max_size
                or self.total_weight + turbo_query.cache_weight > self.max_total_weight
            ):
                if not self._queries:
                    break

                # Evict least valuable query
                evict_hash, evict_query = min(
                    self._queries.items(), key=lambda item: item[1].cache_weight
                )
                self.total_weight -= evict_query.cache_weight
                del self._queries[evict_hash]

        # Add new query
        self._queries[query_hash] = turbo_query
        self.total_weight += turbo_query.cache_weight

        return query_hash

    def update_metrics(
        self, query_hash: str, execution_time: float, cache_hit: bool = True
    ) -> None:
        """Update query metrics after execution.

        Args:
            query_hash: Query hash
            execution_time: Time taken to execute
            cache_hit: Whether this was a cache hit
        """
        if query_hash in self._queries:
            query = self._queries[query_hash]

            # Update execution metrics
            query.execution_count += 1
            query.last_executed = time.time()

            # Update average execution time
            if query.avg_execution_time == 0:
                query.avg_execution_time = execution_time
            else:
                query.avg_execution_time = query.avg_execution_time * 0.9 + execution_time * 0.1

            if cache_hit:
                query.cache_hits += 1

            # Recalculate weight
            old_weight = query.cache_weight
            new_weight = self.calculate_cache_weight(query)
            query.cache_weight = new_weight

            self.total_weight += new_weight - old_weight

            # Move to end for LRU
            self._queries.move_to_end(query_hash)

    def get_metrics(self) -> dict[str, Any]:
        """Get registry metrics.

        Returns:
            Dictionary of metrics
        """
        return {
            "size": len(self._queries),
            "total_weight": round(self.total_weight, 2),
            "max_size": self.max_size,
            "max_total_weight": self.max_total_weight,
            "adaptive_caching_enabled": self.enable_adaptive_caching,
            "top_queries": [
                {
                    "hash": hash_[:8],
                    "complexity": q.complexity_score,
                    "weight": round(q.cache_weight, 2),
                    "executions": q.execution_count,
                    "cache_hits": q.cache_hits,
                    "avg_time_ms": round(q.avg_execution_time * 1000, 2),
                }
                for hash_, q in sorted(
                    self._queries.items(), key=lambda item: item[1].cache_weight, reverse=True
                )[:5]
            ],
        }


class EnhancedTurboRouter(TurboRouter):
    """TurboRouter with enhanced metrics and adaptive behavior."""

    def __init__(self, registry: EnhancedTurboRegistry) -> None:
        """Initialize enhanced router.

        Args:
            registry: Enhanced registry instance
        """
        self.registry = registry
        self._cache_misses = 0
        self._total_requests = 0

    async def execute(
        self,
        query: str,
        variables: dict[str, Any],
        context: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Execute query with enhanced metrics tracking.

        Args:
            query: GraphQL query string
            variables: Query variables
            context: Request context

        Returns:
            Query result if executed, None if not in cache
        """
        self._total_requests += 1
        start_time = time.time()

        # Look up query
        query_hash = self.registry.hash_query(query)
        turbo_query = self.registry.get(query)

        if turbo_query is None:
            self._cache_misses += 1
            return None

        # Get database
        db = context.get("db")
        if db is None:
            raise ValueError("Database connection not found in context")

        # Map variables
        sql_params = turbo_query.map_variables(variables)

        # Execute SQL
        result = await db.fetch(turbo_query.sql_template, sql_params)

        # Update metrics
        execution_time = time.time() - start_time
        self.registry.update_metrics(query_hash, execution_time, cache_hit=True)

        # Process result
        if result and len(result) > 0:
            row = result[0]
            if "result" in row:
                data = row["result"]

                # Extract root field name
                import re

                def extract_root_field_name(query_str: str) -> str | None:
                    """Extract the root field name from a GraphQL query, handling fragments."""
                    # Remove comments and normalize whitespace
                    clean_query = re.sub(r"#.*", "", query_str)
                    clean_query = " ".join(clean_query.split())

                    # Pattern 1: Named query (handles fragments before query)
                    named_query_match = re.search(
                        r"query\s+\w+[^{]*{\s*(\w+)", clean_query, re.DOTALL
                    )
                    if named_query_match:
                        return named_query_match.group(1)

                    # Pattern 2: Anonymous query starting with {
                    anonymous_query_match = re.search(r"^\s*{\s*(\w+)", clean_query)
                    if anonymous_query_match:
                        return anonymous_query_match.group(1)

                    # Pattern 3: Query keyword without name
                    fallback_match = re.search(r"query\s*{\s*(\w+)", clean_query)
                    if fallback_match:
                        return fallback_match.group(1)

                    return None

                def process_turbo_result(data: any, root_field: str) -> dict[str, any]:
                    """Process TurboRouter result with smart GraphQL response detection."""
                    # Case 1: Data is already a complete GraphQL response
                    if (
                        isinstance(data, dict)
                        and "data" in data
                        and isinstance(data["data"], dict)
                        and root_field in data["data"]
                    ):
                        return data

                    # Case 2: Data contains the field data directly
                    if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
                        # Extract the actual data and wrap with correct field name
                        field_data = data["data"]
                        if len(field_data) == 1 and root_field not in field_data:
                            # Single field with wrong name - use the data but correct field name
                            actual_data = next(iter(field_data.values()))
                            return {"data": {root_field: actual_data}}
                        return {"data": {root_field: field_data}}

                    # Case 3: Raw data - wrap normally
                    return {"data": {root_field: data}}

                root_field = extract_root_field_name(query)
                if root_field:
                    return process_turbo_result(data, root_field)

                return {"data": data}

        return {"data": None}

    def get_metrics(self) -> dict[str, Any]:
        """Get router metrics.

        Returns:
            Dictionary of metrics
        """
        hit_rate = 0.0
        if self._total_requests > 0:
            hit_rate = (self._total_requests - self._cache_misses) / self._total_requests

        return {
            "total_requests": self._total_requests,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": round(hit_rate, 3),
            "registry_metrics": self.registry.get_metrics(),
        }

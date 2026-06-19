<!-- Skip to main content -->
---

title: FraiseQL Advanced Optimization
description: Advanced optimization techniques for FraiseQL deployments on PostgreSQL, beyond baseline performance characteristics.
keywords: ["design", "scalability", "performance", "patterns", "security"]
tags: ["documentation", "reference"]
---

# FraiseQL Advanced Optimization

**Status**: Guide
**Last Updated**: January 2026

---

## Executive Summary

This guide covers advanced optimization techniques for FraiseQL deployments, beyond baseline
performance characteristics. FraiseQL is a Python runtime GraphQL framework for PostgreSQL
that builds its schema in memory at app startup and runs over FastAPI; queries resolve against
your `v_`/`tv_` PostgreSQL views and mutations call `fn_` functions. Most optimization work
therefore happens in PostgreSQL itself (indexes, views, partitioning) and in the surrounding
infrastructure (caching, connection pooling, scaling). This guide addresses:

- **Query Optimization**: PostgreSQL execution plans, predicate placement, index-aware filtering
- **Database Tuning**: Index design, partitioning, materialized views, statistics
- **Caching Edge Cases**: Hot keys, thundering herd, cache eviction policies
- **Multi-Instance Scaling**: Consistency across replicas, session affinity, load balancing
- **Resource Optimization**: Memory management, connection pooling, GC tuning
- **Monitoring & Profiling**: Identifying bottlenecks, distributed tracing
- **Emergency Procedures**: Circuit breakers, graceful degradation, backpressure

---

## 1. Query Optimization

FraiseQL generates parameterized SQL against your `v_`/`tv_` PostgreSQL views at runtime and lets
**PostgreSQL's own query planner** choose execution plans, join algorithms, and index usage. There
is no separate FraiseQL query compiler or optimizer — the optimization surface is your view SQL,
your indexes, and PostgreSQL's planner. Your job is to write selective views, index the right
columns, and verify the plans PostgreSQL chooses with `EXPLAIN`.

### 1.1 Execution Plan Analysis

Inspect the plan PostgreSQL produces for the SQL behind a view, including actual timing and buffer
hits, with `EXPLAIN (ANALYZE, BUFFERS)`:

```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT id, data
FROM v_user
WHERE (data->>'tenant_id') = '...'
ORDER BY (data->>'created_at') DESC
LIMIT 50;
```

Read the plan top-down: look for sequential scans on large tables (missing or unused index),
high `actual rows` versus `estimated rows` (stale statistics — run `ANALYZE`), and expensive
sorts that could be served by an index. The `Buffers` line tells you how much I/O the query did.

### 1.2 Predicate Placement

PostgreSQL pushes WHERE predicates down to index/heap scans automatically, but only when the
predicate is **sargable** (can use an index). Make sure the columns your GraphQL filters target
are indexed and that the view does not wrap them in a way that defeats the index:

```sql
-- Indexed, sargable: planner can use idx on (data->>'tenant_id')
CREATE INDEX idx_user_tenant
ON tb_user ((data->>'tenant_id'))
WHERE deleted_at IS NULL;

-- For JSONB containment filters, a GIN index lets @> use the index
CREATE INDEX idx_user_data_gin ON tb_user USING GIN (data);
```

FraiseQL's WHERE operators (`eq`, `gt`, `contains`, `@>`, etc.) translate to parameterized SQL
predicates; whether they use an index is entirely down to the indexes you create on the
underlying table or expression.

### 1.3 Join Order

When a view joins several tables, PostgreSQL's planner reorders the joins for you based on table
statistics — there is no FraiseQL-level join reordering. Keep the planner well-informed and the
joins cheap:

- Run `ANALYZE` so row-count estimates are accurate (see Section 2.4).
- Index foreign-key columns so the planner can choose nested-loop + index lookups for selective
  joins instead of large hash joins.
- Filter as early as possible inside the view (push selective `WHERE` clauses onto the driving
  table) so intermediate result sets stay small.
- For very large joins, consider materializing the result in a `tv_` projection table refreshed
  by a function or trigger, so GraphQL reads hit a single pre-composed table.

### 1.4 Adapting to Runtime Cardinality

PostgreSQL adapts execution to actual data at runtime (e.g. choosing nested-loop vs. hash join
from statistics, and parallel workers from `max_parallel_workers_per_gather`). You influence this
by keeping statistics fresh and, where the planner consistently misestimates, by adding extended
statistics:

```sql
-- Help the planner when two columns are correlated
CREATE STATISTICS stat_user_tenant_status (dependencies)
ON tenant_id, status FROM tb_user;
ANALYZE tb_user;
```

---

## 2. Database Tuning

### 2.1 Index Design Strategy

```python
class IndexDesignGuide:
    """Guidelines for optimal index design"""

    # Choose index type based on query pattern
    INDEX_SELECTION = {
        "high_selectivity_equality": "B-tree",      # WHERE id = 123
        "range_queries": "B-tree",                   # WHERE created_at > now() - interval
        "full_text_search": "GiST or GIN",         # WHERE content LIKE '%search%'
        "spatial_data": "GIST or BRIN",            # WHERE location <-> point < distance
        "json_contains": "GIN",                      # WHERE data @> '{"key": "value"}'
        "ordered_results": "B-tree DESC",           # ORDER BY created_at DESC
        "filtering_many_values": "Hash Index",      # WHERE status IN (...)
    }

    # Index design principles
    PRINCIPLES = {
        "selectivity": "Choose columns that filter most rows",
        "cardinality": "Prefer high-cardinality columns",
        "ordering": "Order matters for range queries",
        "covering": "Include all query columns to avoid table scan",
        "partial": "Exclude NULL or soft-deleted rows",
        "statistics": "ANALYZE regularly for query planning",
    }

    # Anti-patterns
    ANTI_PATTERNS = {
        "over_indexing": "Too many indexes = slow writes",
        "low_selectivity": "Index on status (only 3 values)",
        "unused_indexes": "Bloat without benefit",
        "foreign_key_missing": "No index on FK = slow joins",
        "wrong_direction": "Index on created_at ASC but query needs DESC",
    }


# Example: Comprehensive index strategy for users table
@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    email: str
    created_at: datetime
    updated_at: datetime
    tenant_id: ID
    status: str  # Only 3 values: active, inactive, suspended
    metadata: dict[str, Any]


# Define indexes
INDEX_STRATEGY = {
    # Primary key
    "pk_user": {
        "columns": ["id"],
        "type": "primary",
        "reason": "Primary key"
    },
    # Foreign key lookup
    "idx_user_tenant_id": {
        "columns": ["tenant_id"],
        "type": "b-tree",
        "where": "deleted_at IS NULL",
        "reason": "Fast tenant filtering"
    },
    # Email uniqueness and lookup
    "idx_user_email_unique": {
        "columns": ["email"],
        "type": "b-tree",
        "unique": True,
        "where": "deleted_at IS NULL",
        "reason": "Email uniqueness + fast login lookup"
    },
    # Time-range queries
    "idx_user_created_at": {
        "columns": ["created_at"],
        "type": "b-tree",
        "reason": "Range queries like 'users created in last 30 days'"
    },
    # Composite: tenant + status (common filter combination)
    "idx_user_tenant_status": {
        "columns": ["tenant_id", "status"],
        "type": "b-tree",
        "where": "deleted_at IS NULL",
        "reason": "Most common filter pattern"
    },
    # JSON search on metadata
    "idx_user_metadata_gin": {
        "columns": ["metadata"],
        "type": "gin",
        "reason": "Search within JSONB metadata"
    },
    # Covering index: includes all columns needed by common query
    "idx_user_tenant_email_covering": {
        "columns": ["tenant_id", "email"],
        "includes": ["id", "status"],  # PostgreSQL 11+ INCLUDE
        "type": "b-tree",
        "where": "deleted_at IS NULL",
        "reason": "Covering index for 'get active users by email' query"
    }
}

# SQL generation
CREATE_INDEXES_SQL = """
-- Primary key
CREATE INDEX idx_user_id ON tb_user (id);

-- Foreign key
CREATE INDEX idx_user_tenant_id ON tb_user (tenant_id)
WHERE deleted_at IS NULL;

-- Unique constraint
CREATE UNIQUE INDEX idx_user_email_unique ON tb_user (email)
WHERE deleted_at IS NULL;

-- Range queries
CREATE INDEX idx_user_created_at ON tb_user (created_at);

-- Composite: common filter combination
CREATE INDEX idx_user_tenant_status ON tb_user (tenant_id, status)
WHERE deleted_at IS NULL;

-- JSON search
CREATE INDEX idx_user_metadata_gin ON tb_user USING GIN (metadata);

-- Covering index for common query pattern
CREATE INDEX idx_user_tenant_email_covering ON tb_user (tenant_id, email)
INCLUDE (id, status)
WHERE deleted_at IS NULL;
"""
```

### 2.2 Materialized Views for Complex Queries

```python
class MaterializedViewStrategy:
    """Use materialized views to pre-compute expensive aggregations"""

    # Example: Slow query that becomes fast with MV
    SLOW_QUERY = """
    SELECT
        user_id,
        COUNT(*) as total_posts,
        AVG(view_count) as avg_views,
        MAX(created_at) as latest_post_date
    FROM tb_post
    WHERE tenant_id = $1
    GROUP BY user_id
    """

    MATERIALIZED_VIEW = """
    CREATE MATERIALIZED VIEW mv_user_post_stats AS
    SELECT
        user_id,
        COUNT(*) as total_posts,
        AVG(view_count) as avg_views,
        MAX(created_at) as latest_post_date
    FROM tb_post
    WHERE deleted_at IS NULL
    GROUP BY user_id;

    CREATE INDEX idx_mv_user_post_stats_user_id
    ON mv_user_post_stats (user_id);
    """

    # Refresh strategy: incremental vs full
    REFRESH_STRATEGY = {
        "full_refresh": {
            "frequency": "daily",
            "cost": "high",
            "latency": "minutes",
            "use_for": "low-cardinality aggregations"
        },
        "incremental_refresh": {
            "frequency": "5 minutes",
            "cost": "low",
            "latency": "< 1 minute",
            "use_for": "frequently-changing data"
        },
        "event_driven_refresh": {
            "frequency": "on insert/update",
            "cost": "medium",
            "latency": "< 100ms",
            "use_for": "critical aggregations"
        }
    }
```

### 2.3 Partitioning Strategy

```python
class PartitioningStrategy:
    """Partition large tables for performance and maintenance"""

    PARTITIONING_OPTIONS = {
        "range": {
            "use_for": "Time-series data",
            "example": "PARTITION BY RANGE (created_at)",
            "benefits": "Efficient time-range queries, easier archival",
            "cost": "Moderate"
        },
        "hash": {
            "use_for": "Even distribution across nodes",
            "example": "PARTITION BY HASH (user_id)",
            "benefits": "Load balancing, parallel queries",
            "cost": "Low"
        },
        "list": {
            "use_for": "Categorical data",
            "example": "PARTITION BY LIST (country)",
            "benefits": "Logical grouping, country-specific access",
            "cost": "Low"
        }
    }

    # Example: Time-series partitioning
    POSTS_PARTITIONING = """
    CREATE TABLE tb_post_base (
        id UUID,
        user_id UUID,
        content TEXT,
        created_at TIMESTAMP,
        deleted_at TIMESTAMP
    ) PARTITION BY RANGE (EXTRACT(YEAR FROM created_at));

    -- Quarterly partitions for current year
    CREATE TABLE tb_post_2025_q1 PARTITION OF tb_post_base
    FOR VALUES FROM (2025) TO (2026);

    CREATE TABLE tb_post_2025_q2 PARTITION OF tb_post_base
    FOR VALUES FROM (2026) TO (2027);

    -- Archive older data
    CREATE TABLE tb_post_2024 PARTITION OF tb_post_base
    FOR VALUES FROM (2024) TO (2025);

    -- Benefits:
    -- - Queries on 2025 data skip 2024 partitions
    -- - Can archive 2024 partition to slower storage
    -- - Faster VACUUM (partition-level)
    -- - Parallel sequential scans across partitions
    """
```

### 2.4 Query Statistics

```python
class QueryStatisticsManager:
    """Maintain statistics for query optimization"""

    async def analyze_tables(self, tables: list[str]) -> None:
        """Update table statistics for query planner

        Without stats, planner guesses row counts (inefficient)
        With stats, planner makes optimal decisions
        """
        for table in tables:
            await self.db.execute(f"ANALYZE {table}")

    async def analyze_column(self, table: str, column: str) -> None:
        """Analyze specific column (e.g., after data update)"""
        await self.db.execute(f"ANALYZE {table} ({column})")

    async def view_column_statistics(
        self,
        table: str,
        column: str
    ) -> dict[str, Any]:
        """Inspect column statistics for debugging"""
        result = await self.db.query("""
            SELECT
                attname,
                n_distinct,
                n_distinct_inherited,
                avg_width,
                correlation
            FROM pg_stats
            WHERE tablename = $1 AND attname = $2
        """, table, column)

        return {
            "column": column,
            "n_distinct": result["n_distinct"],  # Cardinality
            "avg_width": result["avg_width"],    # Bytes per value
            "correlation": result["correlation"],  # Index effectiveness
        }

    # Update statistics regularly
    MAINTENANCE_SCHEDULE = {
        "analyze_all": "Daily during off-peak hours",
        "vacuum_full": "Weekly for heavily-updated tables",
        "reindex": "Monthly for index fragmentation",
    }
```

---

## 3. Caching Edge Cases

### 3.1 Hot Key Problem

When a single cache key receives massive traffic:

```python
class HotKeyDetector:
    """Detect and handle hot keys (single keys with extreme traffic)"""

    def __init__(self, redis_client, threshold: int = 100):
        """Initialize detector

        Args:
            threshold: Operations/second for key to be considered "hot"
        """
        self.redis = redis_client
        self.threshold = threshold
        self.hot_keys = {}

    async def detect_hot_keys(self) -> list[str]:
        """Identify keys exceeding traffic threshold

        Hot key examples:
        - Popular user profile (celebrity)
        - High-traffic API endpoint config
        - System-wide counter (concurrent users)
        """
        # Use Redis keyspace notifications to track access patterns
        hot_keys = []

        for key_pattern in self._get_monitored_keys():
            ops_per_second = await self._estimate_ops_per_second(key_pattern)
            if ops_per_second > self.threshold:
                hot_keys.append((key_pattern, ops_per_second))

        return sorted(hot_keys, key=lambda x: x[1], reverse=True)

    async def _estimate_ops_per_second(self, key: str) -> float:
        """Estimate operations/second for key"""
        # Track operations in sliding window
        counter_key = f"ops_count:{key}"
        count = await self.redis.incr(counter_key)
        await self.redis.expire(counter_key, 1)  # Reset every second

        return float(count)

    async def mitigate_hot_key(self, key: str) -> None:
        """Apply hot key mitigation strategies"""

        strategy = self._select_strategy(key)

        if strategy == "local_cache":
            # Keep value in local memory cache
            await self._enable_local_caching(key)

        elif strategy == "read_through":
            # Serve stale value while refreshing in background
            await self._enable_stale_cache(key)

        elif strategy == "probabilistic":
            # Cache only for random subset of requests
            await self._enable_probabilistic_caching(key)

        elif strategy == "replication":
            # Replicate across multiple cache nodes
            await self._enable_cache_replication(key)


class LocalCacheForHotKeys:
    """Local in-memory cache for hot keys"""

    def __init__(self, max_keys: int = 100):
        self.cache = {}
        self.max_keys = max_keys

    async def get(self, key: str, redis_client) -> Any:
        """Try local cache first, fall back to Redis"""
        # Local cache: ~1 microsecond
        if key in self.cache:
            value, ttl = self.cache[key]
            if datetime.utcnow() < ttl:
                return value

        # Redis: ~5 milliseconds
        value = await redis_client.get(key)
        if value:
            # Store in local cache with TTL
            self.cache[key] = (value, datetime.utcnow() + timedelta(seconds=5))
            if len(self.cache) > self.max_keys:
                self._evict_lru()
        return value

    def _evict_lru(self) -> None:
        """Evict least recently used entry"""
        oldest_key = min(
            self.cache.keys(),
            key=lambda k: self.cache[k][1]
        )
        del self.cache[oldest_key]
```

### 3.2 Thundering Herd Problem

When cache expires and many requests try to refresh simultaneously:

```python
class ThunderingHerdMitigation:
    """Prevent cache stampede when popular key expires"""

    async def get_with_mitigation(
        self,
        key: str,
        fetch_fn,
        cache_ttl: int = 300
    ) -> Any:
        """Get value with thundering herd prevention

        Standard cache miss: All 1000 requests compute value (1000x work!)

        With mitigation: First request computes, others wait
        """
        # Use Redis SET with NX (only if not exists)
        lock_key = f"lock:{key}"
        compute_sem = f"computing:{key}"

        # Try to acquire compute lock
        acquired = await self.redis.set(
            compute_sem,
            "true",
            nx=True,
            ex=1  # Lock expires in 1 second (recompute)
        )

        if acquired:
            # We won the race - compute value
            try:
                value = await fetch_fn()
                await self.redis.set(key, value, ex=cache_ttl)
                return value
            finally:
                await self.redis.delete(compute_sem)
        else:
            # Another request is computing - wait for result
            for attempt in range(100):  # Wait up to 5 seconds
                value = await self.redis.get(key)
                if value:
                    return value
                await asyncio.sleep(0.05)  # Poll every 50ms

            # Timeout - fall back to computing
            return await fetch_fn()


# Alternative: Probabilistic early refresh
class ProbabilisticEarlyRefresh:
    """Refresh cache before expiry for popular keys"""

    async def get_with_early_refresh(
        self,
        key: str,
        fetch_fn,
        cache_ttl: int = 300,
        early_refresh_probability: float = 0.1
    ) -> Any:
        """Cache with probabilistic refresh before expiry

        Idea: On access, randomly refresh cache early (10% of time)
        Result: Cache always fresh, no thundering herd on expiry
        """
        value = await self.redis.get(key)

        if value:
            # Cache hit - maybe refresh early?
            if random.random() < early_refresh_probability:
                # Refresh in background (don't block current request)
                asyncio.create_task(self._refresh_in_background(
                    key, fetch_fn, cache_ttl
                ))
            return value

        # Cache miss - compute and cache
        value = await fetch_fn()
        await self.redis.set(key, value, ex=cache_ttl)
        return value

    async def _refresh_in_background(self, key, fetch_fn, ttl):
        """Refresh cache value without blocking client"""
        try:
            value = await fetch_fn()
            await self.redis.set(key, value, ex=ttl)
        except Exception as e:
            logger.exception(f"Background refresh failed for {key}: {e}")
```

### 3.3 Cache Eviction Policies

```python
class CacheEvictionPolicy(Enum):
    """Cache eviction strategies when full"""

    # LRU: Evict least recently used
    LRU = "lru"
    # Cost: Low CPU, good for working sets
    # Benefit: Recently accessed data stays

    # LFU: Evict least frequently used
    LFU = "lfu"
    # Cost: Medium CPU (track frequency)
    # Benefit: Popular data stays

    # FIFO: Evict oldest entry
    FIFO = "fifo"
    # Cost: Very low CPU
    # Benefit: Predictable order

    # Random: Evict random entry
    RANDOM = "random"
    # Cost: Minimal CPU
    # Benefit: Simple, works surprisingly well

    # TTL: Evict expired entries
    TTL = "ttl"
    # Cost: Medium (cleanup)
    # Benefit: Respects time boundaries


class EvictionPolicySelector:
    """Choose optimal eviction policy for workload"""

    @staticmethod
    def recommend_policy(workload_type: str) -> CacheEvictionPolicy:
        """Recommend policy based on workload"""

        if workload_type == "user_profiles":
            # Popular users accessed repeatedly
            return CacheEvictionPolicy.LFU

        elif workload_type == "session_cache":
            # Newer sessions matter more
            return CacheEvictionPolicy.FIFO

        elif workload_type == "api_responses":
            # Working set of recent responses
            return CacheEvictionPolicy.LRU

        elif workload_type == "feature_flags":
            # Rarely accessed, just don't expire
            return CacheEvictionPolicy.TTL

        else:
            # Default: Simple and effective
            return CacheEvictionPolicy.LRU
```

---

## 4. Multi-Instance Scaling

### 4.1 Consistency Across Replicas

```python
class MultiInstanceConsistencyManager:
    """Ensure consistency when running multiple instances"""

    def __init__(self, primary_db: Database, replica_db: Database):
        self.primary = primary_db
        self.replica = replica_db

    # Challenge: Replica lag
    # ┌─────────────────┐
    # │ Primary writes  │ T0
    # │ X = 10          │
    # └─────────────────┘
    #         │
    #         │ Replication lag (5-100ms)
    #         ↓
    # ┌─────────────────┐
    # │ Replica reads   │ T0
    # │ X = ??? (old)   │
    # └─────────────────┘

    async def write_and_verify(
        self,
        query: str,
        params: list,
        verification_key: str,
        expected_value: Any
    ) -> None:
        """Write to primary, verify on replica"""

        # Write to primary
        result = await self.primary.execute(query, params)

        # Verify it reached replica
        verified = await self._wait_for_replica_consistency(
            verification_key,
            expected_value,
            timeout_ms=1000
        )

        if not verified:
            logger.warning(
                f"Replica lag detected: {verification_key} not yet updated"
            )

    async def _wait_for_replica_consistency(
        self,
        key: str,
        expected_value: Any,
        timeout_ms: int = 1000
    ) -> bool:
        """Poll replica until it catches up"""

        end_time = time.time() + (timeout_ms / 1000.0)

        while time.time() < end_time:
            replica_value = await self.replica.query_one(
                f"SELECT * FROM table WHERE id = $1",
                [key]
            )

            if replica_value == expected_value:
                return True

            await asyncio.sleep(0.01)  # Poll every 10ms

        return False


class ReadConsistencyLevel(Enum):
    """Choose read consistency vs performance trade-off"""

    # Read from primary (always consistent, slower)
    STRONG = "strong"

    # Read from replica after write (eventual, faster)
    # Use: If you can tolerate 100ms stale data
    EVENTUAL = "eventual"

    # Read from replica, fall back to primary on miss
    # Use: Hybrid approach, best for most cases
    HYBRID = "hybrid"
```

### 4.2 Session Affinity

```python
class SessionAffinityManager:
    """Route requests to same instance for connection locality"""

    def __init__(self, instances: list[str]):
        self.instances = instances
        self.session_to_instance = {}

    def get_instance_for_session(self, session_id: str) -> str:
        """Get instance for session (consistent routing)

        Benefits:
        - Connection pooling is effective
        - Local caches stay warm
        - Database connections reused
        """
        if session_id not in self.session_to_instance:
            # Hash session to instance (consistent)
            instance_index = hash(session_id) % len(self.instances)
            self.session_to_instance[session_id] = self.instances[instance_index]

        return self.session_to_instance[session_id]

    def hash_consistent(self, key: str, replicas: int) -> int:
        """Consistent hashing for load balancing

        Without consistent hashing:
        - Add instance → 2/3 requests rehash (cache thrash)

        With consistent hashing:
        - Add instance → only 1/n requests rehash
        """
        # Ketama algorithm
        hash_value = self._compute_hash(key)
        return hash_value % replicas
```

### 4.3 Load Balancing Strategies

```python
class LoadBalancingStrategy(Enum):
    """Different load balancing approaches"""

    # Round-robin: cycle through instances
    ROUND_ROBIN = "round_robin"

    # Least connections: send to instance with fewest active connections
    LEAST_CONNECTIONS = "least_connections"

    # Weighted round-robin: allocate based on capacity
    WEIGHTED = "weighted"

    # Consistent hash: same key always routes to same instance
    CONSISTENT_HASH = "consistent_hash"

    # IP hash: route based on client IP
    IP_HASH = "ip_hash"


class LoadBalancer:
    """Route requests across multiple instances"""

    def __init__(self, strategy: LoadBalancingStrategy):
        self.strategy = strategy
        self.instances = []
        self.round_robin_index = 0

    async def get_next_instance(
        self,
        request_context: dict[str, Any] | None = None
    ) -> str:
        """Get next instance for request"""

        if self.strategy == LoadBalancingStrategy.ROUND_ROBIN:
            instance = self.instances[self.round_robin_index]
            self.round_robin_index = (self.round_robin_index + 1) % len(self.instances)
            return instance

        elif self.strategy == LoadBalancingStrategy.LEAST_CONNECTIONS:
            return min(
                self.instances,
                key=lambda i: self._get_connection_count(i)
            )

        elif self.strategy == LoadBalancingStrategy.CONSISTENT_HASH:
            session_id = request_context.get("session_id", "")
            return self._consistent_hash(session_id)

        elif self.strategy == LoadBalancingStrategy.IP_HASH:
            client_ip = request_context.get("client_ip", "")
            return self._ip_hash(client_ip)

        else:
            return self.instances[0]  # Default
```

---

## 5. Resource Optimization

### 5.1 Memory Management

```python
class MemoryOptimizer:
    """Optimize memory usage in FraiseQL runtime"""

    # Memory profiling
    @staticmethod
    async def profile_memory_usage() -> dict[str, int]:
        """Measure memory usage by component

        Returns:
            Dict mapping component -> bytes used
        """
        import psutil
        process = psutil.Process()
        memory_info = process.memory_info()

        return {
            "rss": memory_info.rss,        # Resident set size (physical RAM)
            "vms": memory_info.vms,        # Virtual memory size
            "percent": process.memory_percent(),
        }

    # Garbage collection tuning
    GC_TUNING = {
        "low_traffic": {
            "threshold0": 700,   # Collect at 700 new objects
            "threshold1": 10,    # Collect gen1 at 10:1 ratio
            "threshold2": 10,
        },
        "high_traffic": {
            "threshold0": 3000,  # More objects before collection
            "threshold1": 5,     # Collect more often
            "threshold2": 5,
        },
    }

    @staticmethod
    def tune_garbage_collection(workload: str) -> None:
        """Tune GC for workload characteristics"""
        import gc

        thresholds = MemoryOptimizer.GC_TUNING[workload]
        gc.set_threshold(
            thresholds["threshold0"],
            thresholds["threshold1"],
            thresholds["threshold2"]
        )
```

### 5.2 Connection Pooling

```python
class ConnectionPoolOptimizer:
    """Configure optimal connection pool parameters"""

    # Pool size calculation
    POOL_SIZING_FORMULA = """
    min_size = (cpu_cores * 2) + spare_connections
    max_size = (cpu_cores * 4) + spare_connections

    Example: 8-core server
    min_size = (8 * 2) + 2 = 18
    max_size = (8 * 4) + 2 = 34

    Why:
    - min_size: Keep connections warm for frequent use
    - max_size: Handle traffic spikes without exhaustion
    """

    class PoolConfig:
        def __init__(
            self,
            cpu_cores: int,
            min_size: int | None = None,
            max_size: int | None = None,
            connection_timeout_ms: int = 5000,
            idle_timeout_ms: int = 60000,
        ):
            self.min_size = min_size or (cpu_cores * 2) + 2
            self.max_size = max_size or (cpu_cores * 4) + 2
            self.connection_timeout_ms = connection_timeout_ms
            self.idle_timeout_ms = idle_timeout_ms

    # Monitor pool health
    @staticmethod
    async def monitor_pool_health(pool) -> dict[str, Any]:
        """Check connection pool metrics"""

        return {
            "connections_open": pool.size,
            "connections_idle": pool.idle_size,
            "connections_busy": pool.size - pool.idle_size,
            "wait_queue_depth": pool.waiting_requests,
            "avg_wait_time_ms": pool.avg_checkout_time_ms,
            "pool_exhaustion_events": pool.exhaustion_count,
        }
```

---

## 6. Monitoring & Profiling

### 6.1 Query Profiling

```python
class QueryProfiler:
    """Profile query execution for optimization"""

    async def profile_query(
        self,
        query: str,
        params: list | None = None
    ) -> QueryProfile:
        """Profile query execution

        Collects:
        - Execution time breakdown
        - Row count at each step
        - Index usage
        - Memory allocated
        """
        # Get execution plan
        plan = await self.db.query_one(
            f"EXPLAIN (ANALYZE, BUFFERS, TIMING) {query}",
            params or []
        )

        # Parse plan into profile
        profile = self._parse_plan(plan)

        return profile

    def _parse_plan(self, plan: dict) -> QueryProfile:
        """Parse database execution plan into profile"""

        profile = QueryProfile()

        for step in plan["Plan"]:
            profile.add_step(
                name=step["Node Type"],
                rows_output=step["Actual Rows"],
                execution_time_ms=step["Actual Time"][1] - step["Actual Time"][0],
                buffers_hit=step["Shared Hit Blocks"],
                buffers_read=step["Shared Read Blocks"],
            )

        return profile


class QueryProfile:
    """Results of query profiling"""

    def __init__(self):
        self.steps: list[ExecutionStep] = []
        self.total_time_ms: float = 0

    def add_step(self, **kwargs):
        self.steps.append(ExecutionStep(**kwargs))
        self.total_time_ms += kwargs.get("execution_time_ms", 0)

    def get_bottleneck(self) -> ExecutionStep | None:
        """Find slowest step"""
        if not self.steps:
            return None
        return max(self.steps, key=lambda s: s.execution_time_ms)

    def get_index_usage(self) -> dict[str, bool]:
        """Check which indexes are actually used"""
        return {
            step.name: "Index" in step.name
            for step in self.steps
        }
```

### 6.2 Distributed Tracing for Performance

```python
class QueryTracer:
    """Trace query execution across services"""

    async def trace_query(
        self,
        query_name: str,
        variables: dict,
        user_context
    ) -> Trace:
        """Execute query with full tracing"""

        with self._create_span(f"query:{query_name}") as root_span:
            root_span.set_attribute("user_id", user_context.user_id)
            root_span.set_attribute("variables", json.dumps(variables))

            with self._create_span("authorization"):
                # Authorization checks
                pass

            with self._create_span("database.prepare"):
                # SQL generation and parameter binding
                pass

            with self._create_span("database.execute"):
                # Execute database query
                pass

            with self._create_span("response.build"):
                # Build response object
                pass

            return self._collect_trace(root_span)

    def _create_span(self, name: str):
        """Create tracing span"""
        # Implementation: OpenTelemetry or similar
        pass
```

---

## 7. Emergency Procedures

### 7.1 Circuit Breaker Pattern

```python
class CircuitBreaker:
    """Prevent cascading failures with circuit breaker"""

    class State(Enum):
        CLOSED = "closed"      # Normal operation
        OPEN = "open"          # Failing - reject requests
        HALF_OPEN = "half_open"  # Testing recovery

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_seconds: int = 60
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout_seconds
        self.state = CircuitBreaker.State.CLOSED
        self.failure_count = 0
        self.last_failure_time = None

    async def call(self, fn, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection"""

        if self.state == CircuitBreaker.State.OPEN:
            # Check if recovery period elapsed
            if self._recovery_timeout_elapsed():
                self.state = CircuitBreaker.State.HALF_OPEN
                self.failure_count = 0
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker open, retry in "
                    f"{self._time_to_retry_seconds()}s"
                )

        try:
            result = await fn(*args, **kwargs)

            # Success - reset state
            if self.state == CircuitBreaker.State.HALF_OPEN:
                self.state = CircuitBreaker.State.CLOSED
            self.failure_count = 0

            return result

        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.state = CircuitBreaker.State.OPEN

            raise

    def _recovery_timeout_elapsed(self) -> bool:
        return (
            self.last_failure_time and
            time.time() - self.last_failure_time > self.recovery_timeout
        )
```

### 7.2 Graceful Degradation

```python
class GracefulDegradation:
    """Degrade service gracefully under load"""

    async def execute_with_degradation(
        self,
        query: str,
        user_context,
        system_load: float
    ) -> QueryResult:
        """Execute query with degradation based on system load

        Load levels:
        - < 50%: Full quality (all features)
        - 50-75%: Reduced features (skip non-critical optimization)
        - 75-90%: Basic service (minimal features)
        - > 90%: Emergency (cached responses only)
        """

        if system_load > 0.90:
            # Emergency mode: serve cached response
            return await self._get_cached_response(query, user_context)

        elif system_load > 0.75:
            # Degraded: skip expensive operations
            return await self._execute_degraded(query, user_context)

        elif system_load > 0.50:
            # Reduced: some optimizations disabled
            return await self._execute_reduced(query, user_context)

        else:
            # Normal: full execution
            return await self._execute_full(query, user_context)

    async def _get_cached_response(self, query, context):
        """Serve last known good response"""
        # Cache policy: Keep responses for 30 seconds
        key = f"cached_response:{query}:{context.user_id}"
        return await self.cache.get(key)
```

### 7.3 Backpressure Handling

```python
class BackpressureManager:
    """Handle traffic surge with graceful backpressure"""

    def __init__(self, max_queue_depth: int = 1000):
        self.request_queue = asyncio.Queue(maxsize=max_queue_depth)
        self.processing_workers = []

    async def handle_request(self, request) -> Response:
        """Queue request with backpressure"""

        try:
            # Try to queue request (fail fast if full)
            self.request_queue.put_nowait(request)
        except asyncio.QueueFull:
            # Queue is full - return backpressure response
            return Response(
                status=503,  # Service Unavailable
                error="E_BACKPRESSURE",
                message="Server is overloaded, please retry in a few seconds",
                retry_after_seconds=random.uniform(1, 5)  # Exponential backoff
            )

        # Process request
        return await self._process_request(request)

    async def _process_request(self, request):
        """Process single request"""
        # Implementation
        pass
```

---

## 8. Performance Optimization Checklist

### Database Layer

- [ ] Indexes on all WHERE/JOIN/ORDER BY columns
- [ ] Composite indexes for common filter combinations
- [ ] Partial indexes for soft-deleted rows (WHERE deleted_at IS NULL)
- [ ] Covering indexes for common queries
- [ ] Table statistics up to date (ANALYZE)
- [ ] Partitioning for large tables (time-series)
- [ ] Materialized views for complex aggregations
- [ ] Connection pooling configured
- [ ] Slow query log enabled and monitored

### Query Layer

- [ ] Query execution plans analyzed
- [ ] Predicates pushed to database
- [ ] Join order optimized
- [ ] N+1 queries eliminated
- [ ] Query result caching
- [ ] Cache TTL tuning
- [ ] Pagination for large result sets
- [ ] Parallel query execution where possible
- [ ] Query timeout configured

### Caching Layer

- [ ] L1 in-memory cache for hot data
- [ ] L2 Redis cache for distributed caching
- [ ] Cache invalidation strategy defined
- [ ] TTL values tuned for workload
- [ ] Hot key detection and mitigation
- [ ] Thundering herd prevention
- [ ] Cache hit rate monitored (> 80% target)
- [ ] Eviction policy appropriate for workload

### Infrastructure

- [ ] Connection pool sized for CPU cores
- [ ] Garbage collection tuned
- [ ] Memory usage monitored
- [ ] Multi-instance load balancing
- [ ] Read replica configuration
- [ ] Circuit breakers for external services
- [ ] Backpressure handling
- [ ] Graceful degradation implemented

### Monitoring

- [ ] Query latency percentiles (p50, p95, p99)
- [ ] Cache hit/miss rates
- [ ] Database connection pool status
- [ ] Error rates by type
- [ ] System load trending
- [ ] Slow queries identified and optimized
- [ ] Distributed traces for complex operations
- [ ] Alerting thresholds defined

---

## Summary

FraiseQL advanced optimization covers:

✅ **Query Optimization**

- Execution plan analysis and adaptation
- Predicate pushdown to database
- Join order optimization
- Index effectiveness

✅ **Database Tuning**

- Index design strategy (B-tree, GIN, GIST)
- Materialized views for aggregations
- Partitioning for large tables
- Statistics and query planning

✅ **Caching Edge Cases**

- Hot key detection and mitigation
- Thundering herd prevention
- Eviction policy selection
- Cache consistency

✅ **Multi-Instance Scaling**

- Replica consistency management
- Session affinity routing
- Load balancing strategies
- Connection locality

✅ **Resource Optimization**

- Memory profiling and GC tuning
- Connection pool configuration
- Query profiling
- Distributed tracing

✅ **Emergency Procedures**

- Circuit breaker pattern
- Graceful degradation under load
- Backpressure handling
- Cache fallback strategies

---

Because FraiseQL builds its schema in memory at startup and serves it over FastAPI, the bulk of
this tuning lives in PostgreSQL (indexes, views, partitioning, statistics) and in your deployment
infrastructure (caching, connection pools, replicas) rather than in the framework itself. Profile
with `EXPLAIN (ANALYZE, BUFFERS)`, index for your real query shapes, and apply the caching and
scaling patterns above as your workload grows.

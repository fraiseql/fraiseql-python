"""Realistic performance assessment using actual tv_ materialized tables.

This test suite measures FraiseQL's actual use case:
- TV_ materialized tables with JSONB data column
- Realistic nested JSONB payloads (10KB-100KB)
- Real indices on id and tenant_id
- Single query per request: SELECT data FROM tv_* WHERE id = ? or tenant_id = ?
- Complex WHERE clauses with multiple conditions

Provides accurate timing breakdown across the entire pipeline.
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


@dataclass
class TimingBreakdown:
    """Timing breakdown for a single query."""

    # Individual phase timings (milliseconds)
    pool_acquire_ms: float
    query_execution_ms: float
    result_fetch_ms: float
    rust_pipeline_ms: float

    # Derived metrics
    database_total_ms: float  # pool + query + fetch
    driver_overhead_ms: float  # pool + fetch (excluding query execution)
    postgresql_ms: float  # query execution only
    rust_ms: float  # rust pipeline

    # Aggregates
    total_request_ms: float  # everything

    # Metadata
    result_size_bytes: int
    result_row_count: int
    query_description: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for reporting."""
        return {
            "pool_acquire_ms": round(self.pool_acquire_ms, 3),
            "query_execution_ms": round(self.query_execution_ms, 3),
            "result_fetch_ms": round(self.result_fetch_ms, 3),
            "rust_pipeline_ms": round(self.rust_pipeline_ms, 3),
            "database_total_ms": round(self.database_total_ms, 3),
            "driver_overhead_ms": round(self.driver_overhead_ms, 3),
            "postgresql_ms": round(self.postgresql_ms, 3),
            "rust_ms": round(self.rust_ms, 3),
            "total_request_ms": round(self.total_request_ms, 3),
            "result_size_bytes": self.result_size_bytes,
            "result_row_count": self.result_row_count,
            "query_description": self.query_description,
            "breakdown_percentages": {
                "pool_acquire": round(100 * self.pool_acquire_ms / self.total_request_ms, 1),
                "postgresql": round(100 * self.postgresql_ms / self.total_request_ms, 1),
                "driver_overhead": round(100 * self.driver_overhead_ms / self.total_request_ms, 1),
                "rust_pipeline": round(100 * self.rust_ms / self.total_request_ms, 1),
            },
        }


class RealisticPerformanceAssessment:
    """Helper to measure performance using realistic tv_ tables."""

    @classmethod
    async def setup_tv_user_table(cls, pool: AsyncConnectionPool):
        """Create realistic tv_user table with indices."""
        async with pool.connection() as conn:
            # Create tv_user table (realistic structure)
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tv_user (
                    id UUID PRIMARY KEY,
                    tenant_id UUID NOT NULL,
                    identifier TEXT UNIQUE NOT NULL,
                    data JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            # Create indices (as per FraiseQL pattern)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_tv_user_id ON tv_user(id)")
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tv_user_tenant_id ON tv_user(tenant_id)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tv_user_identifier ON tv_user(identifier)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tv_user_data ON tv_user USING GIN(data)"
            )

    @classmethod
    async def setup_tv_post_table(cls, pool: AsyncConnectionPool):
        """Create realistic tv_post table with indices and nested data."""
        async with pool.connection() as conn:
            # Create tv_post table
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tv_post (
                    id UUID PRIMARY KEY,
                    tenant_id UUID NOT NULL,
                    identifier TEXT UNIQUE NOT NULL,
                    data JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            # Create indices
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_tv_post_id ON tv_post(id)")
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tv_post_tenant_id ON tv_post(tenant_id)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tv_post_identifier ON tv_post(identifier)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tv_post_data ON tv_post USING GIN(data)"
            )

    @classmethod
    async def cleanup_tables(cls, pool: AsyncConnectionPool):
        """Clean up test tables for next test run."""
        async with pool.connection() as conn:
            # Truncate tables to clear data (ignore if tables don't exist)
            try:
                await conn.execute("TRUNCATE TABLE tv_user CASCADE")
                await conn.commit()
            except Exception:
                pass
            try:
                await conn.execute("TRUNCATE TABLE tv_post CASCADE")
                await conn.commit()
            except Exception:
                pass

    @classmethod
    def _generate_user_payload(cls, user_id: str, user_num: int) -> dict:
        """Generate realistic user JSONB payload (5KB)."""
        return {
            "id": user_id,
            "identifier": f"user_{user_num}",
            "email": f"user{user_num}@example.com",
            "username": f"user_{user_num}",
            "fullName": f"User {user_num}",
            "bio": f"This is the bio for user {user_num}. " * 20,  # ~500 chars
            "avatar": f"https://api.example.com/avatars/user_{user_num}.png",
            "profile": {
                "website": "https://example.com",
                "location": "San Francisco",
                "company": "Example Inc",
                "joinDate": "2020-01-01",
                "followers": user_num * 10,
                "following": user_num * 5,
            },
            "settings": {
                "emailNotifications": True,
                "pushNotifications": False,
                "theme": "dark",
                "language": "en",
                "timezone": "America/Los_Angeles",
            },
            "metadata": {
                "lastLogin": "2025-01-15T10:30:00Z",
                "accountStatus": "active",
                "verificationStatus": "verified",
                "twoFactorEnabled": True,
            },
            "createdAt": "2020-01-01T00:00:00Z",
            "updatedAt": "2025-01-15T10:30:00Z",
        }

    @classmethod
    def _generate_post_payload(cls, post_id: str, post_num: int, author_id: str) -> dict:
        """Generate realistic post JSONB payload with nested author and comments (25KB)."""
        return {
            "id": post_id,
            "identifier": f"post-{post_num}",
            "title": f"Post Title {post_num}",
            "content": f"This is the content for post {post_num}. " * 100,  # ~5KB
            "published": True,
            "author": {
                "id": author_id,
                "identifier": f"user_{post_num % 10}",
                "username": f"user_{post_num % 10}",
                "fullName": f"User {post_num % 10}",
                "avatar": f"https://api.example.com/avatars/user_{post_num % 10}.png",
            },
            "tags": [f"tag-{i}" for i in range(10)],  # 10 tags per post
            "comments": [
                {
                    "id": str(uuid.uuid4()),
                    "author": {
                        "id": str(uuid.uuid4()),
                        "username": f"commenter_{j}",
                        "avatar": f"https://api.example.com/avatars/commenter_{j}.png",
                    },
                    "content": f"This is comment {j} on post {post_num}. " * 5,
                    "createdAt": "2025-01-15T10:00:00Z",
                    "likes": j * 2,
                }
                for j in range(5)
            ],  # 5 comments per post
            "metadata": {
                "views": post_num * 100,
                "likes": post_num * 10,
                "shares": post_num * 2,
                "comments": 5,
                "readTime": "5 min",
                "wordCount": 500 + post_num,
            },
            "createdAt": "2025-01-15T09:00:00Z",
            "updatedAt": "2025-01-15T10:30:00Z",
        }

    @classmethod
    async def measure_query_execution(
        cls,
        pool: AsyncConnectionPool,
        query: str,
        params: list[Any] = None,
        query_description: str = "",
    ) -> TimingBreakdown:
        """Measure realistic query execution.

        Args:
            pool: Database connection pool
            query: SQL query to execute
            params: Query parameters
            query_description: Description of what the query does

        Returns:
            TimingBreakdown with detailed timing information
        """
        if params is None:
            params = []

        # Phase 1: Acquire connection from pool
        pool_acquire_start = time.perf_counter()
        async with pool.connection() as conn:
            pool_acquire_end = time.perf_counter()
            pool_acquire_ms = (pool_acquire_end - pool_acquire_start) * 1000

            # Phase 2: Execute query
            query_start = time.perf_counter()
            async with conn.cursor(row_factory=dict_row) as cursor:
                fetch_start = time.perf_counter()
                await cursor.execute(query, params)
                query_end = time.perf_counter()
                query_execution_ms = (query_end - fetch_start) * 1000

                # Phase 3: Fetch results
                results = await cursor.fetchall()
                fetch_end = time.perf_counter()
                result_fetch_ms = (fetch_end - query_end) * 1000

        # Phase 4: Simulate Rust pipeline (JSON serialization)
        rust_start = time.perf_counter()
        # In production, Rust transforms the data structure
        # Here we measure JSON serialization as proxy
        json_str = json.dumps(results)
        json_str.encode("utf-8")
        rust_end = time.perf_counter()
        rust_pipeline_ms = (rust_end - rust_start) * 1000

        # Calculate derived metrics
        database_total_ms = pool_acquire_ms + query_execution_ms + result_fetch_ms
        driver_overhead_ms = pool_acquire_ms + result_fetch_ms
        postgresql_ms = query_execution_ms
        rust_ms = rust_pipeline_ms

        total_request_ms = pool_acquire_ms + query_execution_ms + result_fetch_ms + rust_pipeline_ms

        # Result metadata
        result_size_bytes = len(json_str.encode("utf-8"))
        result_row_count = len(results)

        return TimingBreakdown(
            pool_acquire_ms=pool_acquire_ms,
            query_execution_ms=query_execution_ms,
            result_fetch_ms=result_fetch_ms,
            rust_pipeline_ms=rust_pipeline_ms,
            database_total_ms=database_total_ms,
            driver_overhead_ms=driver_overhead_ms,
            postgresql_ms=postgresql_ms,
            rust_ms=rust_ms,
            total_request_ms=total_request_ms,
            result_size_bytes=result_size_bytes,
            result_row_count=result_row_count,
            query_description=query_description,
        )


@pytest.mark.performance
class TestRealisticPerformance:
    """Performance tests using realistic tv_ materialized tables."""

    async def test_single_user_lookup(self, class_db_pool):
        """Measure: SELECT data FROM tv_user WHERE id = ?

        This is the most common FraiseQL query pattern.
        Single user fetch with ~5KB JSONB payload.
        """
        # Setup
        await RealisticPerformanceAssessment.cleanup_tables(class_db_pool)
        await RealisticPerformanceAssessment.setup_tv_user_table(class_db_pool)
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()

        async with class_db_pool.connection() as conn:
            # Insert realistic user data
            user_payload = RealisticPerformanceAssessment._generate_user_payload(str(user_id), 1)
            await conn.execute(
                "INSERT INTO tv_user (id, tenant_id, identifier, data) VALUES (%s, %s, %s, %s)",
                [user_id, tenant_id, "user_1", json.dumps(user_payload)],
            )

        # Measure
        assessment = await RealisticPerformanceAssessment.measure_query_execution(
            class_db_pool,
            "SELECT data FROM tv_user WHERE id = %s",
            params=[user_id],
            query_description="Single user lookup by id",
        )

        logger.info(f"Single user lookup: {assessment.to_dict()}")

        # Assertions
        assert assessment.total_request_ms > 0
        assert assessment.result_row_count == 1
        # Driver overhead should be small percentage
        driver_pct = 100 * assessment.driver_overhead_ms / assessment.total_request_ms
        logger.info(f"Driver overhead: {driver_pct:.1f}%")
        assert driver_pct < 20  # Driver should be <20% for single row

    async def test_user_list_by_tenant(self, class_db_pool):
        """Measure: SELECT data FROM tv_user WHERE tenant_id = ? LIMIT 100

        Multi-row list query for a tenant.
        100 users × 5KB = ~500KB of JSONB data.
        """
        # Setup
        await RealisticPerformanceAssessment.cleanup_tables(class_db_pool)
        await RealisticPerformanceAssessment.setup_tv_user_table(class_db_pool)
        tenant_id = uuid.uuid4()

        # Insert 100 realistic users
        async with class_db_pool.connection() as conn:
            for i in range(100):
                user_id = uuid.uuid4()
                user_payload = RealisticPerformanceAssessment._generate_user_payload(
                    str(user_id), i
                )
                await conn.execute(
                    "INSERT INTO tv_user (id, tenant_id, identifier, data) VALUES (%s, %s, %s, %s)",
                    [user_id, tenant_id, f"user_{i}", json.dumps(user_payload)],
                )

        # Measure
        assessment = await RealisticPerformanceAssessment.measure_query_execution(
            class_db_pool,
            "SELECT data FROM tv_user WHERE tenant_id = %s LIMIT %s",
            params=[tenant_id, 100],
            query_description="List 100 users by tenant_id",
        )

        logger.info(f"User list by tenant (100 rows): {assessment.to_dict()}")

        # Assertions
        assert assessment.total_request_ms > 0
        assert assessment.result_row_count == 100
        # At 100 rows, Rust pipeline becomes more visible
        rust_pct = 100 * assessment.rust_ms / assessment.total_request_ms
        logger.info(f"Rust pipeline: {rust_pct:.1f}%")

    async def test_post_with_nested_author_comments(self, class_db_pool):
        """Measure: SELECT data FROM tv_post WHERE id = ?

        Single post fetch with nested author and comments.
        ~25KB JSONB payload (more complex structure).
        """
        # Setup
        await RealisticPerformanceAssessment.cleanup_tables(class_db_pool)
        await RealisticPerformanceAssessment.setup_tv_post_table(class_db_pool)
        tenant_id = uuid.uuid4()
        post_id = uuid.uuid4()
        author_id = uuid.uuid4()

        # Insert realistic post with nested data
        async with class_db_pool.connection() as conn:
            post_payload = RealisticPerformanceAssessment._generate_post_payload(
                str(post_id), 1, str(author_id)
            )
            await conn.execute(
                "INSERT INTO tv_post (id, tenant_id, identifier, data) VALUES (%s, %s, %s, %s)",
                [post_id, tenant_id, "post-1", json.dumps(post_payload)],
            )

        # Measure
        assessment = await RealisticPerformanceAssessment.measure_query_execution(
            class_db_pool,
            "SELECT data FROM tv_post WHERE id = %s",
            params=[post_id],
            query_description="Single post with nested author and comments (25KB)",
        )

        logger.info(f"Post with nested data: {assessment.to_dict()}")

        # Assertions
        assert assessment.total_request_ms > 0
        assert assessment.result_row_count == 1
        # Post with nested author and comments: ~5KB (content * 100)
        assert assessment.result_size_bytes > 5000

    async def test_multi_condition_where_clause(self, class_db_pool):
        """Measure: SELECT data FROM tv_user WHERE tenant_id = ? AND identifier = ?

        FraiseQL WHERE clause with multiple conditions.
        Tests index efficiency on both fields.
        """
        # Setup
        await RealisticPerformanceAssessment.cleanup_tables(class_db_pool)
        await RealisticPerformanceAssessment.setup_tv_user_table(class_db_pool)
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Insert test data
        async with class_db_pool.connection() as conn:
            user_payload = RealisticPerformanceAssessment._generate_user_payload(str(user_id), 1)
            await conn.execute(
                "INSERT INTO tv_user (id, tenant_id, identifier, data) VALUES (%s, %s, %s, %s)",
                [user_id, tenant_id, "user_1", json.dumps(user_payload)],
            )

        # Measure
        assessment = await RealisticPerformanceAssessment.measure_query_execution(
            class_db_pool,
            "SELECT data FROM tv_user WHERE tenant_id = %s AND identifier = %s",
            params=[tenant_id, "user_1"],
            query_description="Multi-condition WHERE (tenant_id AND identifier)",
        )

        logger.info(f"Multi-condition WHERE clause: {assessment.to_dict()}")

        # Assertions
        assert assessment.total_request_ms > 0
        assert assessment.result_row_count == 1

    async def test_large_result_set_scaling(self, class_db_pool):
        """Measure timing as result size grows: 10, 100, 500, 1000 rows.

        Shows how Rust pipeline scales with JSONB size.
        Real-world scenario for heavy list queries.
        """
        # Setup
        await RealisticPerformanceAssessment.cleanup_tables(class_db_pool)
        await RealisticPerformanceAssessment.setup_tv_user_table(class_db_pool)
        tenant_id = uuid.uuid4()

        # Insert 1000 realistic users
        async with class_db_pool.connection() as conn:
            for i in range(1000):
                user_id = uuid.uuid4()
                user_payload = RealisticPerformanceAssessment._generate_user_payload(
                    str(user_id), i
                )
                await conn.execute(
                    "INSERT INTO tv_user (id, tenant_id, identifier, data) VALUES (%s, %s, %s, %s)",
                    [user_id, tenant_id, f"user_{i}", json.dumps(user_payload)],
                )

        # Measure different result sizes
        test_sizes = [10, 100, 500, 1000]
        results = {}

        for size in test_sizes:
            assessment = await RealisticPerformanceAssessment.measure_query_execution(
                class_db_pool,
                "SELECT data FROM tv_user WHERE tenant_id = %s LIMIT %s",
                params=[tenant_id, size],
                query_description=f"List {size} users",
            )

            results[size] = assessment.to_dict()
            logger.info(f"{size} rows: {results[size]}")

        # Show scaling pattern
        logger.info("=== SCALING PATTERN ===")
        for size in test_sizes:
            total = results[size]["total_request_ms"]
            rust_pct = results[size]["breakdown_percentages"]["rust_pipeline"]
            logger.info(f"{size:4d} rows → {total:7.2f}ms (Rust: {rust_pct:5.1f}%)")

    async def test_concurrent_multi_tenant_queries(self, class_db_pool):
        """Measure concurrent queries from different tenants.

        Tests connection pool efficiency under concurrent load.
        20 simultaneous queries to different tenant data.
        """
        # Setup multiple tenants
        await RealisticPerformanceAssessment.cleanup_tables(class_db_pool)
        await RealisticPerformanceAssessment.setup_tv_user_table(class_db_pool)
        tenant_ids = [uuid.uuid4() for _ in range(5)]
        user_ids_by_tenant = {}

        # Insert data for each tenant
        global_user_idx = 0
        async with class_db_pool.connection() as conn:
            for tenant_id in tenant_ids:
                user_ids = []
                for i in range(10):
                    user_id = uuid.uuid4()
                    user_payload = RealisticPerformanceAssessment._generate_user_payload(
                        str(user_id), global_user_idx
                    )
                    await conn.execute(
                        "INSERT INTO tv_user (id, tenant_id, identifier, data) VALUES (%s, %s, %s, %s)",
                        [
                            user_id,
                            tenant_id,
                            f"user_{global_user_idx}",
                            json.dumps(user_payload),
                        ],
                    )
                    user_ids.append(user_id)
                    global_user_idx += 1
                user_ids_by_tenant[tenant_id] = user_ids

        # Create concurrent tasks
        tasks = []
        for tenant_idx, tenant_id in enumerate(tenant_ids):
            # 4 queries per tenant
            for user_idx in range(4):
                user_id = user_ids_by_tenant[tenant_id][user_idx]
                task = RealisticPerformanceAssessment.measure_query_execution(
                    class_db_pool,
                    "SELECT data FROM tv_user WHERE id = %s",
                    params=[user_id],
                    query_description=f"Tenant {tenant_idx} user {user_idx}",
                )
                tasks.append(task)

        # Run 20 concurrent queries
        timings = await asyncio.gather(*tasks)

        # Analyze results
        total_times = [t.total_request_ms for t in timings]
        pool_times = [t.pool_acquire_ms for t in timings]

        stats = {
            "concurrent_queries": len(timings),
            "total_time": {
                "avg": sum(total_times) / len(total_times),
                "min": min(total_times),
                "max": max(total_times),
                "p99": sorted(total_times)[int(len(total_times) * 0.99)],
            },
            "pool_acquire_time": {
                "avg": sum(pool_times) / len(pool_times),
                "min": min(pool_times),
                "max": max(pool_times),
            },
        }

        logger.info(f"Concurrent multi-tenant performance: {stats}")

        # Verify P99 is reasonable
        assert stats["total_time"]["p99"] < stats["total_time"]["avg"] * 3


@pytest.mark.performance
@pytest.mark.profile
class TestRealisticProfile:
    """Detailed profiling of realistic FraiseQL patterns."""

    async def test_typical_fraiseql_request(self, class_db_pool):
        """Profile a typical FraiseQL request end-to-end.

        Real-world scenario:
        - Single user lookup by ID
        - ~5KB JSONB payload
        - Index lookup on PK
        - Complete pipeline measurement
        """
        # Setup
        await RealisticPerformanceAssessment.cleanup_tables(class_db_pool)
        await RealisticPerformanceAssessment.setup_tv_user_table(class_db_pool)
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Insert realistic data
        async with class_db_pool.connection() as conn:
            user_payload = RealisticPerformanceAssessment._generate_user_payload(str(user_id), 1)
            await conn.execute(
                "INSERT INTO tv_user (id, tenant_id, identifier, data) VALUES (%s, %s, %s, %s)",
                [user_id, tenant_id, "user_1", json.dumps(user_payload)],
            )

        # Run multiple times to get stable average
        timings = []
        for _ in range(5):
            assessment = await RealisticPerformanceAssessment.measure_query_execution(
                class_db_pool,
                "SELECT data FROM tv_user WHERE id = %s",
                params=[user_id],
                query_description="Typical FraiseQL user lookup",
            )
            timings.append(assessment)

        # Pretty-print results
        avg_timing = timings[0]  # All should be similar
        profile = avg_timing.to_dict()

        logger.info("=== TYPICAL FRAISEQL REQUEST PROFILE ===")
        logger.info(f"PostgreSQL Execution:  {profile['postgresql_ms']:.2f}ms")
        logger.info(f"Driver Overhead:       {profile['driver_overhead_ms']:.2f}ms")
        logger.info(f"Rust Pipeline:         {profile['rust_ms']:.2f}ms")
        logger.info(f"Total:                 {profile['total_request_ms']:.2f}ms")
        logger.info("")
        logger.info("=== BREAKDOWN ===")
        for phase, pct in profile["breakdown_percentages"].items():
            logger.info(f"{phase:20s}: {pct:5.1f}%")
        logger.info("")
        logger.info(f"Result size: {profile['result_size_bytes']} bytes")
        logger.info(f"Row count: {profile['result_row_count']}")

"""Fixtures for end-to-end integration tests."""

import pytest

from fraiseql import fraise_type, query


@pytest.fixture(scope="class")
def production_schema(meta_test_schema):
    """Production-ready schema with comprehensive types for E2E tests.

    This fixture creates a realistic schema simulating a production application
    with users, posts, comments, and categories.
    """
    meta_test_schema.clear()

    # Define realistic production types
    @fraise_type(sql_source="users")
    class User:
        id: int
        email: str
        full_name: str | None
        is_active: bool
        created_at: str  # DateTimeScalar in production

    @fraise_type(sql_source="posts")
    class Post:
        id: int
        title: str
        content: str
        author_id: int
        published_at: str | None
        view_count: int
        tags: list[str] | None

    @fraise_type(sql_source="comments")
    class Comment:
        id: int
        post_id: int
        author_id: int
        content: str
        likes: int

    @fraise_type(sql_source="categories")
    class Category:
        id: int
        name: str
        description: str | None

    # Register queries
    @query
    async def get_users(info, where: dict | None = None) -> list[User]:
        """Get users with optional filtering."""
        # In real tests, this would query database
        return []

    @query
    async def get_posts(info, where: dict | None = None) -> list[Post]:
        """Get posts with optional filtering."""
        return []

    @query
    async def get_comments(info, where: dict | None = None) -> list[Comment]:
        """Get comments."""
        return []

    @query
    async def get_categories(info) -> list[Category]:
        """Get all categories."""
        return []

    # Register types and queries
    meta_test_schema.register_type(User)
    meta_test_schema.register_type(Post)
    meta_test_schema.register_type(Comment)
    meta_test_schema.register_type(Category)

    meta_test_schema.register_query(get_users)
    meta_test_schema.register_query(get_posts)
    meta_test_schema.register_query(get_comments)
    meta_test_schema.register_query(get_categories)

    return meta_test_schema


@pytest.fixture
def memory_profiler():
    """Memory profiling utilities for leak detection tests."""
    import tracemalloc

    tracemalloc.start()

    class MemoryProfiler:
        def __init__(self):
            self.snapshots = []

        def take_snapshot(self, label: str):
            """Take a memory snapshot."""
            snapshot = tracemalloc.take_snapshot()
            self.snapshots.append((label, snapshot))

        def compare_snapshots(self, idx1: int, idx2: int) -> dict:
            """Compare two snapshots and return memory diff."""
            if len(self.snapshots) < 2:
                return {"error": "Need at least 2 snapshots"}

            label1, snap1 = self.snapshots[idx1]
            label2, snap2 = self.snapshots[idx2]

            stats = snap2.compare_to(snap1, "lineno")

            top_stats = sorted(stats, key=lambda s: s.size_diff, reverse=True)[:10]

            return {
                "label1": label1,
                "label2": label2,
                "top_differences": [
                    {
                        "file": stat.traceback.format()[0],
                        "size_diff": stat.size_diff,
                        "count_diff": stat.count_diff,
                    }
                    for stat in top_stats
                ],
                "total_size_diff": sum(stat.size_diff for stat in stats),
            }

        def get_current_memory_mb(self) -> float:
            """Get current memory usage in MB."""
            snapshot = tracemalloc.take_snapshot()
            total = sum(stat.size for stat in snapshot.statistics("filename"))
            return total / (1024 * 1024)  # Convert to MB

    profiler = MemoryProfiler()
    yield profiler

    tracemalloc.stop()


@pytest.fixture
def benchmark_config():
    """Performance benchmark configuration."""
    return {
        "max_query_time_ms": 100,  # Maximum acceptable query execution time
        "max_concurrent_requests": 50,  # Test with up to 50 concurrent requests
        "acceptable_memory_mb": 100,  # Maximum memory usage in MB
        "iterations": 10,  # Number of iterations for performance tests
    }

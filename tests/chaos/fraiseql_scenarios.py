"""FraiseQL Test Scenarios for Chaos Engineering

This module provides realistic test scenarios that interact with actual FraiseQL
operations, making chaos engineering tests more valuable and representative.
"""

import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class GraphQLOperation:
    """Represents a GraphQL operation for testing."""

    name: str
    query: str
    variables: Optional[Dict[str, Any]] = None
    expected_complexity: int = 1

    def get_payload(self) -> Dict[str, Any]:
        """Get the GraphQL request payload."""
        payload: Dict[str, Any] = {"query": self.query}
        if self.variables:
            payload["variables"] = self.variables
        return payload


class FraiseQLTestScenarios:
    """Collection of realistic FraiseQL test scenarios."""

    @staticmethod
    def simple_user_query() -> GraphQLOperation:
        """Simple user query scenario."""
        return GraphQLOperation(
            name="simple_user_query",
            query="""
            query GetUser($id: ID!) {
                user(id: $id) {
                    id
                    name
                    email
                }
            }
            """,
            variables={"id": "123"},
            expected_complexity=5,
        )

    @staticmethod
    def complex_nested_query() -> GraphQLOperation:
        """Complex nested query with multiple relationships."""
        return GraphQLOperation(
            name="complex_nested_query",
            query="""
            query GetUserWithPosts($userId: ID!, $limit: Int) {
                user(id: $userId) {
                    id
                    name
                    posts(limit: $limit) {
                        id
                        title
                        content
                        comments {
                            id
                            author {
                                id
                                name
                            }
                            content
                        }
                    }
                }
            }
            """,
            variables={"userId": "123", "limit": 10},
            expected_complexity=50,
        )

    @staticmethod
    def mutation_create_post() -> GraphQLOperation:
        """Post creation mutation."""
        return GraphQLOperation(
            name="mutation_create_post",
            query="""
            mutation CreatePost($input: CreatePostInput!) {
                createPost(input: $input) {
                    id
                    title
                    content
                    author {
                        id
                        name
                    }
                }
            }
            """,
            variables={
                "input": {
                    "title": "Test Post",
                    "content": "This is a test post content.",
                    "authorId": "123",
                }
            },
            expected_complexity=15,
        )

    @staticmethod
    def batch_users_query(count: int = 20) -> GraphQLOperation:
        """Batch query for multiple users."""
        return GraphQLOperation(
            name=f"batch_users_query_{count}",
            query="""
            query GetUsers($ids: [ID!]!) {
                users(ids: $ids) {
                    id
                    name
                    email
                }
            }
            """,
            variables={"ids": [f"user_{i}" for i in range(count)]},
            expected_complexity=count * 3,
        )

    @staticmethod
    def search_query() -> GraphQLOperation:
        """Search query with filters."""
        return GraphQLOperation(
            name="search_query",
            query="""
            query SearchPosts($query: String!, $filters: PostFilters, $limit: Int) {
                searchPosts(query: $query, filters: $filters, limit: $limit) {
                    posts {
                        id
                        title
                        content
                        author {
                            id
                            name
                        }
                        tags
                    }
                    totalCount
                    hasMore
                }
            }
            """,
            variables={
                "query": "test search",
                "filters": {
                    "tags": ["test", "chaos"],
                    "dateRange": {"from": "2024-01-01", "to": "2024-12-31"},
                },
                "limit": 25,
            },
            expected_complexity=75,
        )

    @staticmethod
    def subscription_scenario() -> GraphQLOperation:
        """WebSocket subscription scenario (for connection chaos)."""
        return GraphQLOperation(
            name="subscription_scenario",
            query="""
            subscription OnNewPost($authorId: ID!) {
                newPost(authorId: $authorId) {
                    id
                    title
                    content
                    createdAt
                }
            }
            """,
            variables={"authorId": "123"},
            expected_complexity=10,
        )


class MockFraiseQLClient:
    """Mock FraiseQL client for chaos testing.

    This simulates FraiseQL behavior without requiring a full running instance.
    In production, this would be replaced with actual HTTP calls to FraiseQL.
    """

    def __init__(self, base_url: str = "http://localhost:8000/graphql"):
        self.base_url = base_url
        self.connection_pool_size = 10
        self.active_connections = 0
        # Chaos simulation state
        self.connection_disabled = False
        self.latency_ms = 0
        self.packet_loss_rate = 0.0

    def inject_connection_failure(self):
        """Simulate connection failure."""
        self.connection_disabled = True

    def inject_latency(self, latency_ms: int):
        """Simulate network latency."""
        self.latency_ms = latency_ms

    def inject_packet_loss(self, loss_rate: float):
        """Simulate packet loss."""
        self.packet_loss_rate = loss_rate

    def reset_chaos(self):
        """Reset all chaos conditions."""
        self.connection_disabled = False
        self.latency_ms = 0
        self.packet_loss_rate = 0.0

    def execute_query(self, operation: GraphQLOperation, timeout: float = 30.0) -> Dict[str, Any]:
        """Execute a GraphQL operation against FraiseQL.

        Simulates realistic FraiseQL behavior including:
        - Connection acquisition time
        - Query execution time based on complexity
        - Response formatting
        """
        start_time = time.time()

        # Check for chaos conditions
        if self.connection_disabled:
            time.sleep(0.001)  # Fast failure
            raise ConnectionError("Connection refused (chaos injection)")

        if random.random() < self.packet_loss_rate:
            time.sleep(0.001)  # Fast failure
            raise ConnectionError("Packet loss (chaos injection)")

        try:
            # Simulate connection acquisition
            self._acquire_connection()

            # Apply latency chaos
            if self.latency_ms > 0:
                time.sleep(self.latency_ms / 1000.0)

            # Simulate query execution based on complexity
            execution_time = self._calculate_execution_time(operation.expected_complexity)
            time.sleep(execution_time / 1000.0)

            # Simulate response
            response = self._generate_mock_response(operation)

            # Simulate connection release
            self._release_connection()

            total_time = time.time() - start_time
            response["_execution_time_ms"] = total_time * 1000

            return response

        except Exception as e:
            self._release_connection()
            raise e

    def _acquire_connection(self):
        """Simulate connection pool acquisition."""
        if self.active_connections >= self.connection_pool_size:
            raise ConnectionError("Connection pool exhausted")

        self.active_connections += 1
        # Simulate connection acquisition time
        time.sleep(0.005)  # 5ms

    def _release_connection(self):
        """Simulate connection release."""
        if self.active_connections > 0:
            self.active_connections -= 1

    def _calculate_execution_time(self, complexity: int) -> float:
        """Calculate realistic execution time based on query complexity.

        This simulates FraiseQL's actual performance characteristics.
        """
        base_time = 5.0  # 5ms base time
        complexity_factor = complexity / 10.0  # Scale complexity
        variable_factor = 1.0 + (time.time() % 0.2)  # Small variance

        return base_time + (complexity_factor * variable_factor)

    def _generate_mock_response(self, operation: GraphQLOperation) -> Dict[str, Any]:
        """Generate a mock GraphQL response."""
        # Simulate occasional errors
        if time.time() % 100 < 1:  # 1% error rate
            return {
                "errors": [
                    {"message": "Simulated GraphQL error", "extensions": {"code": "INTERNAL_ERROR"}}
                ],
                "data": None,
            }

        # Generate mock data based on operation
        if "GetUser" in operation.query:
            return {
                "data": {
                    "user": {
                        "id": operation.variables.get("id", "123")
                        if operation.variables
                        else "123",
                        "name": "Test User",
                        "email": "test@example.com",
                    }
                }
            }

        if "GetUsers" in operation.query:
            user_ids = operation.variables.get("ids", []) if operation.variables else []
            users = []
            for user_id in user_ids[:10]:  # Limit to 10 users
                users.append(
                    {
                        "id": user_id,
                        "name": f"User {user_id}",
                        "email": f"user_{user_id}@example.com",
                    }
                )

            return {"data": {"users": users}}

        if "CreatePost" in operation.query:
            return {
                "data": {
                    "createPost": {
                        "id": "post_123",
                        "title": "Test Post",
                        "content": "This is a test post content.",
                        "author": {"id": "123", "name": "Test User"},
                    }
                }
            }

        if "SearchPosts" in operation.query:
            return {
                "data": {
                    "searchPosts": {
                        "posts": [
                            {
                                "id": "post_1",
                                "title": "Test Post 1",
                                "content": "Content 1",
                                "author": {"id": "123", "name": "Author"},
                                "tags": ["test"],
                            }
                        ],
                        "totalCount": 1,
                        "hasMore": False,
                    }
                }
            }

        # Default response
        return {"data": {"result": "success"}}


# Convenience functions for common test scenarios


def execute_with_timeout(
    client: MockFraiseQLClient, operation: GraphQLOperation, timeout: float = 30.0
) -> Dict[str, Any]:
    """Execute operation with timeout handling."""
    import signal

    def timeout_handler(signum, frame):
        raise TimeoutError("Query execution timeout")

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(int(timeout))

    try:
        result = client.execute_query(operation, timeout)
        signal.alarm(0)  # Cancel alarm
        return result
    except TimeoutError:
        signal.alarm(0)
        raise


def execute_with_retry(
    client: MockFraiseQLClient,
    operation: GraphQLOperation,
    max_retries: int = 3,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """Execute operation with retry logic."""
    last_error: Optional[Exception] = None

    for attempt in range(max_retries):
        try:
            return execute_with_timeout(client, operation, timeout)
        except (ConnectionError, TimeoutError) as e:
            last_error = e
            if attempt < max_retries - 1:
                # Exponential backoff
                time.sleep(0.1 * (2**attempt))

    if last_error:
        raise last_error
    raise RuntimeError("Retry logic failed without specific error")


# Test scenario collections


class ChaosTestScenarios:
    """Predefined collections of test scenarios for chaos testing."""

    @staticmethod
    def connection_chaos_scenarios() -> List[GraphQLOperation]:
        """Scenarios for testing connection chaos."""
        return [
            FraiseQLTestScenarios.simple_user_query(),
            FraiseQLTestScenarios.batch_users_query(5),
        ]

    @staticmethod
    def latency_chaos_scenarios() -> List[GraphQLOperation]:
        """Scenarios for testing latency chaos."""
        return [
            FraiseQLTestScenarios.simple_user_query(),
            FraiseQLTestScenarios.complex_nested_query(),
            FraiseQLTestScenarios.search_query(),
        ]

    @staticmethod
    def load_chaos_scenarios() -> List[GraphQLOperation]:
        """Scenarios for testing under load chaos."""
        return [
            FraiseQLTestScenarios.batch_users_query(50),
            FraiseQLTestScenarios.search_query(),
        ]

    @staticmethod
    def mutation_chaos_scenarios() -> List[GraphQLOperation]:
        """Scenarios for testing mutation chaos."""
        return [
            FraiseQLTestScenarios.mutation_create_post(),
        ]

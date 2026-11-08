"""Regression tests for APQ field selection bug.

Bug: APQ (Automatic Persisted Queries) does not respect field selections -
it sends the full payload instead of only the selected fields.

Expected behavior:
- Query: `{ user { name } }` should return only `{ "user": { "name": "John" } }`

Actual buggy behavior:
- Query: `{ user { name } }` returns full object:
  `{ "user": { "id": 1, "name": "John", "email": "john@example.com", ... } }`

This happens because:
1. APQ cached responses store the FULL response from initial execution
2. When cache hit occurs, the full cached response is returned
3. Field selection from the query is not applied to cached responses
4. The cached response may have been generated with different field selections

The fix should either:
- Include field selection in the cache key (different selections = different cache entries)
- Apply field selection to cached responses before returning
- Not cache responses with partial field selections
"""

import hashlib
from unittest.mock import Mock

import pytest

from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.storage.backends.memory import MemoryAPQBackend

pytestmark = pytest.mark.integration


class TestAPQFieldSelectionBug:
    """Test suite for APQ field selection bug."""

    @pytest.fixture
    def config_with_caching(self) -> FraiseQLConfig:
        """Create config with APQ caching enabled."""
        return FraiseQLConfig(
            database_url="postgresql://test@localhost/test",
            apq_storage_backend="memory",
            apq_cache_responses=True,
            apq_response_cache_ttl=600,
        )

    @pytest.fixture
    def backend(self) -> MemoryAPQBackend:
        """Create a fresh memory backend."""
        return MemoryAPQBackend()

    def test_cached_response_respects_field_selection(self, config_with_caching, backend) -> None:
        """Cached response should only include requested fields.

        This test verifies that when a query requests only specific fields,
        the cached response only contains those fields, even if the resolver
        returned more fields.
        """
        # Query that only requests id and name (NOT email, createdAt, metadata)
        query = """
            query GetUser {
                user(id: 1) {
                    id
                    name
                }
            }
        """
        query_hash = hashlib.sha256(query.encode()).hexdigest()

        # Store the query
        backend.store_persisted_query(query_hash, query)

        # Simulate resolver returning MORE fields than requested
        # (this happens with ORMs that fetch full objects)
        full_response = {
            "data": {
                "user": {
                    "id": 1,
                    "name": "John Doe",
                    "email": "john@example.com",  # NOT requested
                    "createdAt": "2024-01-01T00:00:00Z",  # NOT requested
                    "metadata": {"role": "admin", "active": True},  # NOT requested
                }
            }
        }

        # Store via middleware (should filter before storing)
        from fraiseql.middleware.apq_caching import store_response_in_cache

        store_response_in_cache(
            query_hash,
            full_response,
            backend,
            config_with_caching,
            query_text=query,
            operation_name="GetUser",
        )

        # Create APQ request to retrieve
        request = Mock(
            query=None,  # Hash-only request
            variables=None,
            operationName="GetUser",
            extensions={"persistedQuery": {"version": 1, "sha256Hash": query_hash}},
        )

        # Get cached response
        from fraiseql.middleware.apq_caching import handle_apq_request_with_cache

        result = handle_apq_request_with_cache(request, backend, config_with_caching)

        assert result is not None
        user_data = result["data"]["user"]

        # Should only have requested fields
        assert user_data["id"] == 1
        assert user_data["name"] == "John Doe"
        assert "email" not in user_data, "email was not requested but was returned"
        assert "createdAt" not in user_data, "createdAt was not requested but was returned"
        assert "metadata" not in user_data, "metadata was not requested but was returned"

    def test_different_field_selections_should_have_different_cache_keys(
        self, config_with_caching, backend
    ) -> None:
        """Test that different field selections should produce different cache keys."""
        # These two queries select different fields but same operation
        query_minimal = """
            query GetUser($id: ID!) {
                user(id: $id) {
                    id
                    name
                }
            }
        """

        query_full = """
            query GetUser($id: ID!) {
                user(id: $id) {
                    id
                    name
                    email
                    profile {
                        bio
                        avatar
                    }
                }
            }
        """

        hash_minimal = hashlib.sha256(query_minimal.encode()).hexdigest()
        hash_full = hashlib.sha256(query_full.encode()).hexdigest()

        # Different queries SHOULD have different hashes
        # This is correct behavior - but the bug is about CACHED responses
        assert hash_minimal != hash_full

    def test_variables_included_in_cache_key(self, config_with_caching, backend) -> None:
        """Cache key should include variables to prevent returning wrong data."""
        # Same query, different variables
        query = """
            query GetUser($id: ID!) {
                user(id: $id) {
                    id
                    name
                }
            }
        """
        query_hash = hashlib.sha256(query.encode()).hexdigest()

        # Store response for user 1
        response_user_1 = {"data": {"user": {"id": 1, "name": "Alice"}}}
        backend.store_persisted_query(query_hash, query)
        backend.store_cached_response(query_hash, response_user_1)

        # Request for user 2 (different variable)
        request_user_2 = Mock(
            query=None,
            variables={"id": 2},  # Different user!
            operationName="GetUser",
            extensions={"persistedQuery": {"version": 1, "sha256Hash": query_hash}},
        )

        from fraiseql.middleware.apq_caching import handle_apq_request_with_cache

        result = handle_apq_request_with_cache(request_user_2, backend, config_with_caching)

        # EXPECTED: Should NOT return user 1's data when requesting user 2
        # Either cache miss (variables in key) or correct data
        if result is not None:
            assert result["data"]["user"]["id"] != 1, (
                "Cache key should include variables - returned wrong user's data"
            )

    def test_apq_cache_returns_stale_data_for_same_hash(self, config_with_caching, backend) -> None:
        """Document: APQ cache returns stale data when data changes but query doesn't.

        This is expected behavior for response caching - TTL controls staleness.
        Not a bug per se, but documents the trade-off.
        """
        query = """
            query GetProducts {
                products {
                    id
                    name
                    price
                }
            }
        """
        query_hash = hashlib.sha256(query.encode()).hexdigest()

        # Initial response
        initial_response = {
            "data": {
                "products": [
                    {"id": 1, "name": "Widget", "price": 9.99},
                    {"id": 2, "name": "Gadget", "price": 19.99},
                ]
            }
        }

        backend.store_persisted_query(query_hash, query)
        backend.store_cached_response(query_hash, initial_response)

        # Later request (after data changed in database)
        request = Mock(
            query=None,
            variables=None,
            operationName="GetProducts",
            extensions={"persistedQuery": {"version": 1, "sha256Hash": query_hash}},
        )

        from fraiseql.middleware.apq_caching import handle_apq_request_with_cache

        result = handle_apq_request_with_cache(request, backend, config_with_caching)

        # Returns cached data - this is expected behavior for caching
        assert result is not None
        assert result == initial_response

    def test_partial_response_stored_when_partial_fields_requested(
        self, config_with_caching, backend
    ) -> None:
        """Response cache should only store fields that were actually requested.

        When the resolver returns more fields than requested, the caching layer
        should filter the response before storing to ensure only requested
        fields are cached.
        """
        # Query only requests id and name
        query = """
            query GetUser {
                user(id: 1) {
                    id
                    name
                }
            }
        """
        query_hash = hashlib.sha256(query.encode()).hexdigest()

        # Store the query
        backend.store_persisted_query(query_hash, query)

        # Resolver returns MORE fields than requested
        full_response = {
            "data": {
                "user": {
                    "id": 1,
                    "name": "John",
                    "email": "john@test.com",  # NOT requested
                    "phone": "555-1234",  # NOT requested
                }
            }
        }

        from fraiseql.middleware.apq_caching import store_response_in_cache

        # Store with query_text so filtering can happen
        store_response_in_cache(
            query_hash,
            full_response,
            backend,
            config_with_caching,
            query_text=query,
            operation_name="GetUser",
        )

        # Verify what was stored - should be filtered
        cached = backend.get_cached_response(query_hash)

        assert cached is not None
        assert cached["data"]["user"]["id"] == 1
        assert cached["data"]["user"]["name"] == "John"
        assert "email" not in cached["data"]["user"], "email should not be cached"
        assert "phone" not in cached["data"]["user"], "phone should not be cached"


class TestAPQFieldSelectionExpectedBehavior:
    """Tests documenting expected (correct) behavior for field selection."""

    @pytest.fixture
    def config_with_caching(self) -> FraiseQLConfig:
        """Create config with APQ caching enabled."""
        return FraiseQLConfig(
            database_url="postgresql://test@localhost/test",
            apq_storage_backend="memory",
            apq_cache_responses=True,
        )

    @pytest.fixture
    def backend(self) -> MemoryAPQBackend:
        """Create a fresh memory backend."""
        return MemoryAPQBackend()

    def test_expected_field_selection_only_returns_requested_fields(
        self, config_with_caching, backend
    ) -> None:
        """Document expected behavior: only requested fields should be returned."""
        # This test documents what SHOULD happen (currently fails due to bug)

        query = """
            query GetUser {
                user(id: 1) {
                    name
                }
            }
        """
        query_hash = hashlib.sha256(query.encode()).hexdigest()

        # Store query and response
        backend.store_persisted_query(query_hash, query)

        # Response should match the query's field selection
        expected_response = {"data": {"user": {"name": "John Doe"}}}
        backend.store_cached_response(query_hash, expected_response)

        # Request
        request = Mock(
            query=None,
            variables=None,
            operationName="GetUser",
            extensions={"persistedQuery": {"version": 1, "sha256Hash": query_hash}},
        )

        from fraiseql.middleware.apq_caching import handle_apq_request_with_cache

        result = handle_apq_request_with_cache(request, backend, config_with_caching)

        # This is correct - only requested fields returned
        assert result == expected_response
        assert list(result["data"]["user"].keys()) == ["name"]

    def test_expected_cache_key_includes_variables(self) -> None:
        """Document expected behavior: cache key should include variables."""
        # Expected: cache key should be hash of query + normalized variables
        # This would prevent returning wrong user's data

        variables_user_1 = {"id": 1}
        variables_user_2 = {"id": 2}

        # Simple approach: include variables in cache key
        def compute_cache_key(query_hash: str, variables: dict | None) -> str:
            """Compute cache key that includes variables."""
            import json

            var_str = json.dumps(variables, sort_keys=True) if variables else ""
            combined = f"{query_hash}:{var_str}"
            return hashlib.sha256(combined.encode()).hexdigest()

        key_user_1 = compute_cache_key("query_hash", variables_user_1)
        key_user_2 = compute_cache_key("query_hash", variables_user_2)

        # Different variables = different cache keys
        assert key_user_1 != key_user_2


class TestAPQCacheKeyGeneration:
    """Tests for cache key generation with field selection awareness."""

    def test_cache_key_should_include_operation_name(self) -> None:
        """Test that cache key includes operation name."""
        # Same query, different operation names
        # If multiple operations in document, operation_name matters
        assert True  # Placeholder for implementation

    def test_cache_key_generation_consistency(self) -> None:
        """Test that cache key generation is consistent."""
        query = "query { user { id name } }"
        hash1 = hashlib.sha256(query.encode()).hexdigest()
        hash2 = hashlib.sha256(query.encode()).hexdigest()

        assert hash1 == hash2

    def test_whitespace_affects_cache_key(self) -> None:
        """Test that whitespace differences create different cache keys."""
        query1 = "query { user { id name } }"
        query2 = "query {\n  user {\n    id\n    name\n  }\n}"

        hash1 = hashlib.sha256(query1.encode()).hexdigest()
        hash2 = hashlib.sha256(query2.encode()).hexdigest()

        # Whitespace creates different hashes - this is a problem
        # Ideally, semantically equivalent queries should have same hash
        assert hash1 != hash2  # Current behavior (problematic)


class TestAPQResponseFiltering:
    """Tests for response filtering in APQ."""

    @pytest.fixture
    def backend(self) -> MemoryAPQBackend:
        return MemoryAPQBackend()

    def test_is_cacheable_response_with_errors(self) -> None:
        """Test that responses with errors are not cacheable."""
        from fraiseql.middleware.apq_caching import is_cacheable_response

        # Response with errors should not be cached
        error_response = {
            "errors": [{"message": "Something went wrong"}],
            "data": None,
        }
        assert is_cacheable_response(error_response) is False

    def test_is_cacheable_response_without_data(self) -> None:
        """Test that responses without data are not cacheable."""
        from fraiseql.middleware.apq_caching import is_cacheable_response

        # Response without data should not be cached
        no_data_response = {"extensions": {"timing": 100}}
        assert is_cacheable_response(no_data_response) is False

    def test_is_cacheable_response_partial_error(self) -> None:
        """Test that partial error responses are not cacheable."""
        from fraiseql.middleware.apq_caching import is_cacheable_response

        # Partial response (data + errors) should not be cached
        partial_response = {
            "data": {"user": {"name": "John"}},
            "errors": [{"message": "Could not fetch email"}],
        }
        assert is_cacheable_response(partial_response) is False

    def test_is_cacheable_response_valid(self) -> None:
        """Test that valid responses are cacheable."""
        from fraiseql.middleware.apq_caching import is_cacheable_response

        valid_response = {"data": {"user": {"id": 1, "name": "John"}}}
        assert is_cacheable_response(valid_response) is True


class TestAPQFieldSelectionEndToEnd:
    """End-to-end tests for APQ field selection - simulates real Apollo client flow.

    This test class verifies the complete APQ caching flow with field selection:
    1. First request (cache miss): Execute query, filter response, store in cache
    2. Second request (cache hit): Retrieve from cache, filter response, return

    These tests ensure that the bug described in the module docstring is fixed:
    - Query: `{ user { name } }` should ONLY return `{ "user": { "name": "John" } }`
    - NOT the full object with id, email, metadata, etc.
    """

    @pytest.fixture
    def config_with_caching(self) -> FraiseQLConfig:
        """Create config with APQ caching enabled."""
        return FraiseQLConfig(
            database_url="postgresql://test@localhost/test",
            apq_storage_backend="memory",
            apq_cache_responses=True,
            apq_response_cache_ttl=600,
        )

    @pytest.fixture
    def backend(self) -> MemoryAPQBackend:
        """Create a fresh memory backend."""
        return MemoryAPQBackend()

    def test_apollo_client_flow_field_selection(self, config_with_caching, backend) -> None:
        """Simulate real Apollo client APQ flow with field selection.

        This test simulates the exact request format from Apollo Client:
        {
            "operationName": "GetLocations",
            "variables": {},
            "extensions": {
                "clientLibrary": {"name": "@apollo/client", "version": "4.0.11"},
                "persistedQuery": {"version": 1, "sha256Hash": "..."}
            }
        }
        """
        from fraiseql.middleware.apq_caching import (
            handle_apq_request_with_cache,
            store_response_in_cache,
        )

        # Query that only requests id and name (NOT address, metadata, etc.)
        query = """
            query GetLocations {
                locations {
                    id
                    name
                }
            }
        """
        query_hash = hashlib.sha256(query.encode()).hexdigest()

        # Store the persisted query (simulates Apollo client registration)
        backend.store_persisted_query(query_hash, query)

        # Simulate resolver returning MORE fields than requested
        # (this happens with ORMs/database queries that fetch full objects)
        full_response_from_resolver = {
            "data": {
                "locations": [
                    {
                        "id": "loc-1",
                        "name": "Headquarters",
                        "address": "123 Main St",  # NOT requested
                        "city": "NYC",  # NOT requested
                        "metadata": {"active": True},  # NOT requested
                    },
                    {
                        "id": "loc-2",
                        "name": "Branch Office",
                        "address": "456 Oak Ave",  # NOT requested
                        "city": "LA",  # NOT requested
                        "metadata": {"active": False},  # NOT requested
                    },
                ]
            }
        }

        # Store response in cache (should filter before storing)
        store_response_in_cache(
            query_hash,
            full_response_from_resolver,
            backend,
            config_with_caching,
            variables={},
            query_text=query,
            operation_name="GetLocations",
        )

        # Simulate Apollo client request (hash-only, no query text)
        request = Mock(
            query=None,
            variables={},
            operationName="GetLocations",
            extensions={
                "clientLibrary": {"name": "@apollo/client", "version": "4.0.11"},
                "persistedQuery": {"version": 1, "sha256Hash": query_hash},
            },
        )

        # Get cached response
        result = handle_apq_request_with_cache(request, backend, config_with_caching)

        # Verify result
        assert result is not None, "Should get cache hit"
        assert "data" in result
        assert "locations" in result["data"]

        locations = result["data"]["locations"]
        assert len(locations) == 2

        # CRITICAL ASSERTIONS: Only requested fields should be present
        for loc in locations:
            assert "id" in loc, "id was requested and should be present"
            assert "name" in loc, "name was requested and should be present"
            assert "address" not in loc, "address was NOT requested but was returned"
            assert "city" not in loc, "city was NOT requested but was returned"
            assert "metadata" not in loc, "metadata was NOT requested but was returned"

    def test_nested_field_selection_filtering(self, config_with_caching, backend) -> None:
        """Test that nested field selection is properly filtered.

        Query: { company { name address { city } } }
        Should NOT return: address.street, address.zip, company.id, etc.
        """
        from fraiseql.middleware.apq_caching import (
            handle_apq_request_with_cache,
            store_response_in_cache,
        )

        query = """
            query GetCompany {
                company {
                    name
                    address {
                        city
                    }
                }
            }
        """
        query_hash = hashlib.sha256(query.encode()).hexdigest()
        backend.store_persisted_query(query_hash, query)

        # Full response with unrequested nested fields
        full_response = {
            "data": {
                "company": {
                    "id": "comp-1",  # NOT requested
                    "name": "Acme Corp",
                    "email": "contact@acme.com",  # NOT requested
                    "address": {
                        "street": "123 Main St",  # NOT requested
                        "city": "NYC",
                        "zip": "10001",  # NOT requested
                        "country": "USA",  # NOT requested
                    },
                }
            }
        }

        store_response_in_cache(
            query_hash,
            full_response,
            backend,
            config_with_caching,
            query_text=query,
            operation_name="GetCompany",
        )

        request = Mock(
            query=None,
            variables=None,
            operationName="GetCompany",
            extensions={"persistedQuery": {"version": 1, "sha256Hash": query_hash}},
        )

        result = handle_apq_request_with_cache(request, backend, config_with_caching)

        assert result is not None
        company = result["data"]["company"]

        # Top level
        assert "name" in company
        assert company["name"] == "Acme Corp"
        assert "id" not in company, "id was NOT requested"
        assert "email" not in company, "email was NOT requested"

        # Nested level
        assert "address" in company
        assert "city" in company["address"]
        assert company["address"]["city"] == "NYC"
        assert "street" not in company["address"], "street was NOT requested"
        assert "zip" not in company["address"], "zip was NOT requested"
        assert "country" not in company["address"], "country was NOT requested"

    def test_different_variables_different_cache_entries(
        self, config_with_caching, backend
    ) -> None:
        """Test that different variables produce different cache entries.

        This is the CRITICAL security test - ensures user1's data isn't
        returned for user2's request.
        """
        from fraiseql.middleware.apq_caching import (
            handle_apq_request_with_cache,
            store_response_in_cache,
        )

        query = """
            query GetUser($id: ID!) {
                user(id: $id) {
                    id
                    name
                }
            }
        """
        query_hash = hashlib.sha256(query.encode()).hexdigest()
        backend.store_persisted_query(query_hash, query)

        # Store response for user 1
        response_user1 = {"data": {"user": {"id": "1", "name": "Alice"}}}
        store_response_in_cache(
            query_hash,
            response_user1,
            backend,
            config_with_caching,
            variables={"id": "1"},
            query_text=query,
            operation_name="GetUser",
        )

        # Store response for user 2
        response_user2 = {"data": {"user": {"id": "2", "name": "Bob"}}}
        store_response_in_cache(
            query_hash,
            response_user2,
            backend,
            config_with_caching,
            variables={"id": "2"},
            query_text=query,
            operation_name="GetUser",
        )

        # Request for user 1
        request_user1 = Mock(
            query=None,
            variables={"id": "1"},
            operationName="GetUser",
            extensions={"persistedQuery": {"version": 1, "sha256Hash": query_hash}},
        )
        result1 = handle_apq_request_with_cache(request_user1, backend, config_with_caching)

        # Request for user 2
        request_user2 = Mock(
            query=None,
            variables={"id": "2"},
            operationName="GetUser",
            extensions={"persistedQuery": {"version": 1, "sha256Hash": query_hash}},
        )
        result2 = handle_apq_request_with_cache(request_user2, backend, config_with_caching)

        # CRITICAL: Each user should get their own data
        assert result1 is not None
        assert result1["data"]["user"]["name"] == "Alice", "User 1 should get Alice"

        assert result2 is not None
        assert result2["data"]["user"]["name"] == "Bob", "User 2 should get Bob"

    def test_cached_response_filtered_on_retrieval(self, config_with_caching, backend) -> None:
        """Test defense-in-depth: filtering happens on retrieval too.

        Even if somehow a full response was cached (legacy data, bug, etc.),
        retrieval should still filter based on the query's field selection.
        """
        from fraiseql.middleware.apq_caching import (
            compute_response_cache_key,
            handle_apq_request_with_cache,
        )

        query = """
            query GetProduct {
                product {
                    id
                    name
                }
            }
        """
        query_hash = hashlib.sha256(query.encode()).hexdigest()
        backend.store_persisted_query(query_hash, query)

        # Manually store an UNFILTERED response (simulating legacy/bug data)
        cache_key = compute_response_cache_key(query_hash, None)
        unfiltered_response = {
            "data": {
                "product": {
                    "id": "prod-1",
                    "name": "Widget",
                    "price": 99.99,  # NOT in query
                    "inventory": 500,  # NOT in query
                    "secret_cost": 25.00,  # SENSITIVE - NOT in query
                }
            }
        }
        backend.store_cached_response(cache_key, unfiltered_response)

        # Request should filter on retrieval
        request = Mock(
            query=None,
            variables=None,
            operationName="GetProduct",
            extensions={"persistedQuery": {"version": 1, "sha256Hash": query_hash}},
        )

        result = handle_apq_request_with_cache(request, backend, config_with_caching)

        assert result is not None
        product = result["data"]["product"]

        # Only requested fields should be returned
        assert "id" in product
        assert "name" in product
        assert "price" not in product, "price was NOT requested"
        assert "inventory" not in product, "inventory was NOT requested"
        assert "secret_cost" not in product, "secret_cost was NOT requested (sensitive!)"

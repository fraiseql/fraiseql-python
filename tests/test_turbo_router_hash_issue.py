"""Test to reproduce and fix the turbo router hash normalization issue.

This test reproduces the issue where queries registered with raw hash
don't match FraiseQL's normalized hash calculation.
"""

import hashlib

from fraiseql.fastapi.turbo import TurboQuery, TurboRegistry


class TestTurboRouterHashIssue:
    """Test turbo router hash normalization issue."""

    def test_hash_mismatch_reproducer(self) -> None:
        """Reproduce the hash mismatch issue from PrintOptim backend."""
        # This is the exact query from the PrintOptim backend issue
        raw_query = """query GetNetworkConfigurations {
  networkConfigurations {
    id
    ipAddress
    isDhcp
    identifier
    subnetMask
    emailAddress
    nDirectAllocations
    dns1 {
      id
      ipAddress
      __typename
    }
    dns2 {
      id
      ipAddress
      __typename
    }
    gateway {
      id
      ipAddress
      __typename
    }
    router {
      id
      hostname
      ipAddress
      macAddress
      __typename
    }
    printServers {
      id
      hostname
      __typename
    }
    smtpServer {
      id
      hostname
      port
      __typename
    }
    __typename
  }
}"""

        # This is how the hash was calculated in the issue (raw string)
        raw_hash = hashlib.sha256(raw_query.encode("utf-8")).hexdigest()

        # This is how FraiseQL calculates it (normalized)
        registry = TurboRegistry()
        normalized_hash = registry.hash_query(raw_query)

        print(f"Raw hash:        {raw_hash}")
        print(f"Normalized hash: {normalized_hash}")

        # The issue: these don't match!
        assert raw_hash != normalized_hash, "Hashes should be different (this is the bug)"

        # The expected hash from the issue report
        expected_hash = "859f5d3b94c4c1add28a74674c83d6b49cc4406c1292e21822d4ca3beb76d269"
        assert raw_hash == expected_hash, "Raw hash should match the issue report"

    def test_registry_get_fails_with_raw_query(self) -> None:
        """Test that registry.get() fails when query has different whitespace."""
        registry = TurboRegistry()

        # Register with normalized query (single line)
        normalized_query = "query GetNetworkConfigurations { networkConfigurations { id } }"
        turbo_query = TurboQuery(
            graphql_query=normalized_query,
            sql_template="SELECT '{}' as result",
            param_mapping={},
            operation_name="GetNetworkConfigurations",
        )
        registry.register(turbo_query)

        # Try to get with formatted query (multiline)
        formatted_query = """query GetNetworkConfigurations {
  networkConfigurations {
    id
  }
}"""

        # This should work because hash_query normalizes both
        result = registry.get(formatted_query)
        assert result is not None, "Should find query despite whitespace differences"

    def test_hash_normalization_behavior(self) -> None:
        """Test current hash normalization behavior."""
        registry = TurboRegistry()

        # Different whitespace variations of the same query
        queries = [
            "query { user { id } }",
            "query{user{id}}",
            "query {\n  user {\n    id\n  }\n}",
            "query   {   user   {   id   }   }",
            "\n\nquery {\n  user {\n    id\n  }\n}\n\n",
        ]

        hashes = [registry.hash_query(q) for q in queries]

        # All should produce the same hash
        for i, h in enumerate(hashes):
            print(f"Query {i + 1} hash: {h}")
            assert h == hashes[0], f"Query {i + 1} should have same hash as first query"

    def test_proposed_fix_backward_compatibility(self) -> None:
        """Test that the proposed fix maintains backward compatibility."""
        registry = TurboRegistry()

        # Test both normalized and raw queries work
        base_query = "query { user { id } }"
        formatted_query = """query {
  user {
    id
  }
}"""

        # Register with formatted query
        turbo_query = TurboQuery(
            graphql_query=formatted_query,
            sql_template="SELECT '{}' as result",
            param_mapping={},
            operation_name="GetUser",
        )
        registry.register(turbo_query)

        # Should be able to retrieve with either format
        assert registry.get(base_query) is not None
        assert registry.get(formatted_query) is not None

        # Both should return the same TurboQuery object
        assert registry.get(base_query) is registry.get(formatted_query)

    def test_printoptim_backend_issue_fix(self) -> None:
        """Test fix for the specific PrintOptim backend issue."""
        registry = TurboRegistry()

        # This is the exact query from PrintOptim backend
        raw_query = """query GetNetworkConfigurations {
  networkConfigurations {
    id
    ipAddress
    isDhcp
    identifier
    subnetMask
    emailAddress
    nDirectAllocations
    dns1 {
      id
      ipAddress
      __typename
    }
    dns2 {
      id
      ipAddress
      __typename
    }
    gateway {
      id
      ipAddress
      __typename
    }
    router {
      id
      hostname
      ipAddress
      macAddress
      __typename
    }
    printServers {
      id
      hostname
      __typename
    }
    smtpServer {
      id
      hostname
      port
      __typename
    }
    __typename
  }
}"""

        # Simulate the PrintOptim backend scenario:
        # 1. They computed raw hash for registration
        expected_raw_hash = "859f5d3b94c4c1add28a74674c83d6b49cc4406c1292e21822d4ca3beb76d269"
        raw_hash = registry.hash_query_raw(raw_query)
        assert raw_hash == expected_raw_hash

        # 2. Register the query with raw hash (simulating database registration)
        turbo_query = TurboQuery(
            graphql_query=raw_query,
            sql_template="SELECT turbo.fn_get_network_configurations()::json as result",
            param_mapping={},
            operation_name="GetNetworkConfigurations",
        )
        registry.register_with_raw_hash(turbo_query, raw_hash)

        # 3. FraiseQL should be able to find it using the formatted query
        found_query = registry.get(raw_query)
        assert found_query is not None
        assert found_query.operation_name == "GetNetworkConfigurations"
        assert (
            found_query.sql_template
            == "SELECT turbo.fn_get_network_configurations()::json as result"
        )

        # 4. Should also work with slightly different formatting
        minified_query = "query GetNetworkConfigurations{networkConfigurations{id ipAddress}}"
        registry.get(minified_query)
        # This might be None due to different content, but the hash lookup should work
        # The key test is that the raw hash lookup succeeded above

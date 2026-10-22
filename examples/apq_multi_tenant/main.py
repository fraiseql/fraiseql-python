#!/usr/bin/env python
"""Example: Multi-tenant APQ with tenant-specific caching.

Demonstrates how FraiseQL's built-in tenant-aware APQ caching works
for multi-tenant SaaS applications.
"""

import hashlib
from typing import Any

from fraiseql import FraiseQLConfig, create_fraiseql_app
from fraiseql.storage.backends.memory import MemoryAPQBackend


class APQBackendWithStats(MemoryAPQBackend):
    """Example backend that adds statistics tracking."""

    def __init__(self):
        super().__init__()
        self._stats = {
            "cache_hits": {},
            "cache_misses": {},
            "total_requests": 0,
        }

    def get_cached_response(self, hash_value: str, context: dict[str, Any] | None = None):
        """Track cache hits/misses."""
        self._stats["total_requests"] += 1
        tenant_id = self.extract_tenant_id(context) if context else "global"

        response = super().get_cached_response(hash_value, context)

        if response:
            self._stats["cache_hits"][tenant_id] = self._stats["cache_hits"].get(tenant_id, 0) + 1
            print(f"✓ Cache HIT for tenant '{tenant_id}'")
        else:
            self._stats["cache_misses"][tenant_id] = self._stats["cache_misses"].get(tenant_id, 0) + 1
            print(f"✗ Cache MISS for tenant '{tenant_id}'")

        return response

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics per tenant."""
        return self._stats


def simulate_multi_tenant_requests():
    """Simulate APQ requests from multiple tenants."""
    print("=" * 60)
    print("Multi-Tenant APQ Caching Example")
    print("=" * 60)

    # Create backend (built-in tenant support)
    backend = APQBackendWithStats()

    # Test queries
    queries = {
        "get_users": "query GetUsers { users { id name email } }",
        "get_products": "query GetProducts { products { id name price } }",
    }

    # Calculate hashes
    query_hashes = {name: hashlib.sha256(query.encode()).hexdigest() for name, query in queries.items()}

    # Simulate requests from different tenants
    tenants = [
        {"tenant_id": "acme-corp", "name": "ACME Corporation"},
        {"tenant_id": "globex-inc", "name": "Globex Inc"},
    ]

    print("\n--- Phase 1: Initial Requests (Cache Misses) ---")
    for tenant in tenants:
        context = {"user": {"metadata": {"tenant_id": tenant["tenant_id"]}}}

        for query_name, query_hash in query_hashes.items():
            # First request - cache miss
            cached = backend.get_cached_response(query_hash, context)
            assert cached is None

            # Store response
            response = {
                "data": {
                    query_name: f"Data for {tenant['name']}",
                    "tenant": tenant["tenant_id"],
                }
            }
            backend.store_cached_response(query_hash, response, context)

    print("\n--- Phase 2: Repeated Requests (Cache Hits) ---")
    for tenant in tenants:
        context = {"user": {"metadata": {"tenant_id": tenant["tenant_id"]}}}

        for query_name, query_hash in query_hashes.items():
            # Second request - cache hit
            cached = backend.get_cached_response(query_hash, context)
            assert cached is not None
            assert cached["data"]["tenant"] == tenant["tenant_id"]

    print("\n--- Phase 3: Verify Tenant Isolation ---")
    # Verify that tenants can't see each other's data
    acme_context = {"user": {"metadata": {"tenant_id": "acme-corp"}}}
    globex_context = {"user": {"metadata": {"tenant_id": "globex-inc"}}}

    test_hash = query_hashes["get_users"]
    acme_response = backend.get_cached_response(test_hash, acme_context)
    globex_response = backend.get_cached_response(test_hash, globex_context)

    assert acme_response["data"]["tenant"] == "acme-corp"
    assert globex_response["data"]["tenant"] == "globex-inc"
    print("✅ Tenant isolation verified - no data leakage")

    print("\n--- Cache Statistics ---")
    stats = backend.get_stats()
    for tenant_id in ["acme-corp", "globex-inc"]:
        hits = stats["cache_hits"].get(tenant_id, 0)
        misses = stats["cache_misses"].get(tenant_id, 0)
        hit_rate = (hits / (hits + misses) * 100) if (hits + misses) > 0 else 0
        print(f"{tenant_id:12} - Hits: {hits:3}, Misses: {misses:3}, Hit Rate: {hit_rate:.1f}%")


def create_multi_tenant_app():
    """Create a FraiseQL app with multi-tenant APQ support."""
    config = FraiseQLConfig(
        database_url="postgresql://localhost/multi_tenant_db",
        apq_storage_backend="memory",  # Built-in tenant support
        apq_cache_responses=True,
        apq_cache_ttl=3600,  # 1 hour
    )

    app = create_fraiseql_app(config)

    @app.middleware("http")
    async def add_tenant_context(request, call_next):
        """Extract tenant_id from JWT and add to request context."""
        # In production: decode JWT and extract tenant_id
        # token = request.headers.get("Authorization", "").replace("Bearer ", "")
        # payload = jwt.decode(token, SECRET_KEY)
        # request.state.tenant_id = payload.get("tenant_id")
        response = await call_next(request)
        return response

    return app


if __name__ == "__main__":
    simulate_multi_tenant_requests()

    print("\n" + "=" * 60)
    print("Example Complete!")
    print("=" * 60)
    print("\n✨ FraiseQL now has built-in tenant-aware APQ caching!")
    print("No custom backend needed - just pass context with tenant_id.")

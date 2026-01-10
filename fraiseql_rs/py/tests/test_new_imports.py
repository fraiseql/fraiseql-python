"""Test new organized submodule imports (Phase 6.5)

This test suite validates the new Python API with organized submodules.
These are the recommended imports going forward.
"""

import pytest


def test_schema_submodule_exists():
    """Test that schema submodule is available"""
    import _fraiseql_rs

    assert hasattr(_fraiseql_rs, 'schema')
    schema = _fraiseql_rs.schema
    assert hasattr(schema, 'TableSchema')
    assert hasattr(schema, 'SchemaMetadata')
    print("✓ schema submodule exists with TableSchema, SchemaMetadata")


def test_query_submodule_exists():
    """Test that query submodule is available"""
    import _fraiseql_rs

    assert hasattr(_fraiseql_rs, 'query')
    query = _fraiseql_rs.query
    assert hasattr(query, 'QueryBuilder')
    assert hasattr(query, 'GeneratedQuery')
    assert hasattr(query, 'CacheStats')
    assert callable(query.build_sql_query)
    assert callable(query.build_sql_query_cached)
    assert callable(query.get_cache_stats)
    assert callable(query.clear_cache)
    print("✓ query submodule exists with all query types/functions")


def test_errors_submodule_exists():
    """Test that errors submodule is available"""
    import _fraiseql_rs

    assert hasattr(_fraiseql_rs, 'errors')
    errors = _fraiseql_rs.errors
    assert hasattr(errors, 'SecurityError')
    print("✓ errors submodule exists with SecurityError")


def test_apq_submodule_exists():
    """Test that apq submodule is available"""
    import _fraiseql_rs

    assert hasattr(_fraiseql_rs, 'apq')
    apq = _fraiseql_rs.apq
    assert callable(apq.hash_query)
    assert callable(apq.verify_hash)
    assert callable(apq.hash_query_with_variables)
    assert callable(apq.verify_hash_with_variables)
    print("✓ apq submodule exists with all hasher functions")


def test_new_imports_schema():
    """Test using new schema submodule imports"""
    from _fraiseql_rs.schema import TableSchema, SchemaMetadata

    assert TableSchema
    assert SchemaMetadata
    print("✓ New-style schema imports work")


def test_new_imports_query():
    """Test using new query submodule imports"""
    from _fraiseql_rs.query import (
        QueryBuilder,
        GeneratedQuery,
        CacheStats,
        build_sql_query,
        build_sql_query_cached,
        get_cache_stats,
        clear_cache,
    )

    assert QueryBuilder
    assert GeneratedQuery
    assert CacheStats
    assert callable(build_sql_query)
    assert callable(build_sql_query_cached)
    assert callable(get_cache_stats)
    assert callable(clear_cache)
    print("✓ New-style query imports work")


def test_new_imports_errors():
    """Test using new errors submodule imports"""
    from _fraiseql_rs.errors import SecurityError

    assert SecurityError
    print("✓ New-style errors imports work")


def test_new_imports_apq():
    """Test using new apq submodule imports"""
    from _fraiseql_rs.apq import (
        hash_query,
        verify_hash,
        hash_query_with_variables,
        verify_hash_with_variables,
    )

    assert callable(hash_query)
    assert callable(verify_hash)
    assert callable(hash_query_with_variables)
    assert callable(verify_hash_with_variables)
    print("✓ New-style apq imports work")


def test_hash_query_new_api():
    """Test that hash_query works with new submodule import"""
    from _fraiseql_rs.apq import hash_query

    query = "{ users { id name } }"
    hash_value = hash_query(query)

    assert isinstance(hash_value, str)
    assert len(hash_value) == 64  # SHA-256 hex
    print(f"✓ apq.hash_query() works: {hash_value[:16]}...")


def test_verify_hash_new_api():
    """Test that verify_hash works with new submodule import"""
    from _fraiseql_rs.apq import hash_query, verify_hash

    query = "{ users { id name } }"
    hash_value = hash_query(query)

    assert verify_hash(query, hash_value)
    assert not verify_hash(query, "invalid_hash")
    print("✓ apq.verify_hash() works")


def test_all_submodules_accessible():
    """Verify all new submodules are accessible"""
    import _fraiseql_rs

    submodules = ['schema', 'query', 'errors', 'apq']

    for submodule in submodules:
        assert hasattr(_fraiseql_rs, submodule), f"Missing submodule: {submodule}"

    print(f"✓ All {len(submodules)} submodules accessible")


def test_submodule_isolation():
    """Test that submodules contain appropriate items"""
    import _fraiseql_rs

    # schema should have schema types
    assert hasattr(_fraiseql_rs.schema, 'TableSchema')
    assert not hasattr(_fraiseql_rs.schema, 'build_sql_query')

    # query should have query types and functions
    assert hasattr(_fraiseql_rs.query, 'QueryBuilder')
    assert hasattr(_fraiseql_rs.query, 'build_sql_query')

    # errors should have error types
    assert hasattr(_fraiseql_rs.errors, 'SecurityError')
    assert not hasattr(_fraiseql_rs.errors, 'hash_query')

    # apq should have hash functions
    assert hasattr(_fraiseql_rs.apq, 'hash_query')
    assert not hasattr(_fraiseql_rs.apq, 'TableSchema')

    print("✓ Submodules properly isolated with correct items")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])

"""Test backward compatibility of old top-level imports (Phase 6.5)

This test suite validates that the old Python API still works after
the Phase 6.5 refactoring to add organized submodules.

All these imports should continue to work exactly as before.
"""

import pytest


def test_version_function_exists():
    """Test that version() function is available at top level"""
    import _fraiseql_rs

    version = _fraiseql_rs.version()
    assert isinstance(version, str)
    assert len(version) > 0
    print(f"✓ version() = {version}")


def test_schema_types_top_level():
    """Test that schema types are available at top level (backward compat)"""
    import _fraiseql_rs

    # These should exist at top level
    assert hasattr(_fraiseql_rs, 'TableSchema')
    assert hasattr(_fraiseql_rs, 'SchemaMetadata')
    print("✓ TableSchema and SchemaMetadata available at top level")


def test_query_types_top_level():
    """Test that query types/functions are available at top level (backward compat)"""
    import _fraiseql_rs

    # These should exist at top level
    assert hasattr(_fraiseql_rs, 'QueryBuilder')
    assert hasattr(_fraiseql_rs, 'GeneratedQuery')
    assert hasattr(_fraiseql_rs, 'CacheStats')
    assert callable(_fraiseql_rs.build_sql_query)
    assert callable(_fraiseql_rs.build_sql_query_cached)
    assert callable(_fraiseql_rs.get_cache_stats)
    assert callable(_fraiseql_rs.clear_cache)
    print("✓ Query types and functions available at top level")


def test_errors_types_top_level():
    """Test that error types are available at top level (backward compat)"""
    import _fraiseql_rs

    # SecurityError should exist at top level
    assert hasattr(_fraiseql_rs, 'SecurityError')
    print("✓ SecurityError available at top level")


def test_apq_functions_top_level():
    """Test that APQ functions are available at top level (backward compat)"""
    import _fraiseql_rs

    # APQ functions should exist at top level
    assert callable(_fraiseql_rs.hash_query)
    assert callable(_fraiseql_rs.verify_hash)
    assert callable(_fraiseql_rs.hash_query_with_variables)
    assert callable(_fraiseql_rs.verify_hash_with_variables)
    print("✓ APQ functions available at top level")


def test_hash_query_old_api():
    """Test that hash_query works with old top-level import"""
    import _fraiseql_rs

    query = "{ users { id name } }"
    hash_value = _fraiseql_rs.hash_query(query)

    assert isinstance(hash_value, str)
    assert len(hash_value) == 64  # SHA-256 hex
    print(f"✓ hash_query() works: {hash_value[:16]}...")


def test_verify_hash_old_api():
    """Test that verify_hash works with old top-level import"""
    import _fraiseql_rs

    query = "{ users { id name } }"
    hash_value = _fraiseql_rs.hash_query(query)

    assert _fraiseql_rs.verify_hash(query, hash_value)
    assert not _fraiseql_rs.verify_hash(query, "invalid_hash")
    print("✓ verify_hash() works")


def test_old_imports_still_work():
    """Test using old-style imports"""
    # This is how old code would import
    from _fraiseql_rs import (
        build_sql_query,
        hash_query,
        GeneratedQuery,
        version,
    )

    assert callable(build_sql_query)
    assert callable(hash_query)
    assert version
    assert GeneratedQuery
    print("✓ Old-style imports work")


def test_backward_compat_all_exports():
    """Verify all old exports still exist"""
    import _fraiseql_rs

    old_exports = [
        # Version
        'version',
        # Schema
        'TableSchema', 'SchemaMetadata',
        # Query
        'QueryBuilder', 'GeneratedQuery', 'CacheStats',
        'build_sql_query', 'build_sql_query_cached',
        'get_cache_stats', 'clear_cache',
        # Errors
        'SecurityError',
        # APQ
        'hash_query', 'verify_hash',
        'hash_query_with_variables', 'verify_hash_with_variables',
    ]

    for export in old_exports:
        assert hasattr(_fraiseql_rs, export), f"Missing old export: {export}"

    print(f"✓ All {len(old_exports)} old exports available")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])

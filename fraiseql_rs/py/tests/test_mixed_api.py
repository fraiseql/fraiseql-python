"""Test mixing old and new API imports in same script (Phase 6.5)

This test suite validates that old and new API imports can be mixed
in the same Python script without conflicts.
"""

import pytest


def test_mixed_old_and_new_imports():
    """Test using old and new imports simultaneously"""
    # Old style
    from _fraiseql_rs import hash_query as old_hash_query, version

    # New style
    from _fraiseql_rs.apq import hash_query as new_hash_query

    query = "{ users { id } }"
    old_result = old_hash_query(query)
    new_result = new_hash_query(query)

    # Should produce identical results
    assert old_result == new_result
    assert isinstance(version, str)
    print(f"✓ Mixed imports produce identical results: {old_result[:16]}...")


def test_mixed_schema_imports():
    """Test mixing old and new schema imports"""
    # Old style
    from _fraiseql_rs import TableSchema as OldTableSchema

    # New style
    from _fraiseql_rs.schema import TableSchema as NewTableSchema

    # Should be the same class
    assert OldTableSchema is NewTableSchema
    print("✓ TableSchema is same class in both old and new imports")


def test_mixed_query_imports():
    """Test mixing old and new query imports"""
    # Old style
    from _fraiseql_rs import (
        build_sql_query as old_build,
        GeneratedQuery as OldQuery,
    )

    # New style
    from _fraiseql_rs.query import (
        build_sql_query as new_build,
        GeneratedQuery as NewQuery,
    )

    # Should be the same functions/classes
    assert old_build is new_build
    assert OldQuery is NewQuery
    print("✓ Query items are same in both old and new imports")


def test_mixed_error_imports():
    """Test mixing old and new error imports"""
    # Old style
    from _fraiseql_rs import SecurityError as OldError

    # New style
    from _fraiseql_rs.errors import SecurityError as NewError

    # Should be the same class
    assert OldError is NewError
    print("✓ SecurityError is same class in both old and new imports")


def test_mixed_apq_imports():
    """Test mixing old and new APQ imports"""
    # Old style
    from _fraiseql_rs import (
        hash_query as old_hash,
        verify_hash as old_verify,
    )

    # New style
    from _fraiseql_rs.apq import (
        hash_query as new_hash,
        verify_hash as new_verify,
    )

    # Should be the same functions
    assert old_hash is new_hash
    assert old_verify is new_verify
    print("✓ APQ functions are same in both old and new imports")


def test_real_world_mixed_script():
    """Simulate a real-world script using mixed imports"""
    # Some parts use old API
    from _fraiseql_rs import hash_query, version

    # Some parts use new API
    from _fraiseql_rs.query import build_sql_query, CacheStats
    from _fraiseql_rs.apq import verify_hash

    # Run actual operations
    query = "{ posts { id title } }"
    query_hash = hash_query(query)
    is_valid = verify_hash(query, query_hash)

    assert isinstance(version, str)
    assert len(query_hash) == 64
    assert is_valid
    print(f"✓ Real-world mixed script works (version={version}, hash={query_hash[:12]}...)")


def test_no_import_conflicts():
    """Verify that importing from both old and new doesn't cause conflicts"""
    # Import everything old way
    import _fraiseql_rs as old_api

    # Import everything new way
    from _fraiseql_rs import schema, query, errors, apq

    # Both should reference the same underlying objects
    assert old_api.TableSchema is schema.TableSchema
    assert old_api.build_sql_query is query.build_sql_query
    assert old_api.SecurityError is errors.SecurityError
    assert old_api.hash_query is apq.hash_query

    print("✓ No import conflicts - both APIs reference same objects")


def test_submodule_and_toplevel_consistency():
    """Verify submodule and top-level exports are identical"""
    import _fraiseql_rs

    # Schema
    assert _fraiseql_rs.TableSchema is _fraiseql_rs.schema.TableSchema
    assert _fraiseql_rs.SchemaMetadata is _fraiseql_rs.schema.SchemaMetadata

    # Query
    assert _fraiseql_rs.QueryBuilder is _fraiseql_rs.query.QueryBuilder
    assert _fraiseql_rs.GeneratedQuery is _fraiseql_rs.query.GeneratedQuery
    assert _fraiseql_rs.CacheStats is _fraiseql_rs.query.CacheStats
    assert _fraiseql_rs.build_sql_query is _fraiseql_rs.query.build_sql_query

    # Errors
    assert _fraiseql_rs.SecurityError is _fraiseql_rs.errors.SecurityError

    # APQ
    assert _fraiseql_rs.hash_query is _fraiseql_rs.apq.hash_query
    assert _fraiseql_rs.verify_hash is _fraiseql_rs.apq.verify_hash

    print("✓ All exports consistent between submodule and top-level")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])

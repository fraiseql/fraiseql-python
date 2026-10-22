"""Unit test for unified camelCase conversion in Rust mutation builder.

This test verifies that the auto_camel_case parameter works correctly
in the Rust build_mutation_response function.
"""

import json

from tests.unit.mutations.selection_document import UNFILTERED, legacy_document


def test_rust_build_mutation_response_with_camel_case_true():
    """Verify Rust converts to camelCase when auto_camel_case=True."""
    import fraiseql._fraiseql_rs as fraiseql_rs

    # Simple mutation result with snake_case fields
    mutation_json = json.dumps(
        {
            "id": "123",
            "ip_address": "192.168.1.1",
            "dns_server_name": "test-dns",
        }
    )

    result_bytes = fraiseql_rs.build_mutation_response(
        mutation_json,
        "createServer",
        "CreateServerSuccess",
        "CreateServerError",
        "test_server",  # entity_field_name in snake_case
        "TestServer",
        None,  # cascade_selections
        True,
        None,
        None,
        legacy_document(None, None, "test_server", None),
    )

    result = json.loads(result_bytes.decode("utf-8"))

    # Verify response structure
    assert "data" in result
    assert "createServer" in result["data"]
    mutation_result = result["data"]["createServer"]

    # Verify Success type
    assert mutation_result["__typename"] == "CreateServerSuccess"

    # CRITICAL: Verify entity_field_name was converted to camelCase
    assert "testServer" in mutation_result, "entity_field_name should be converted to camelCase"
    assert "test_server" not in mutation_result, "entity_field_name should NOT be snake_case"

    # Verify entity fields are camelCase
    test_server = mutation_result["testServer"]
    assert "ipAddress" in test_server, "Fields should be camelCase"
    assert "ip_address" not in test_server, "Fields should NOT be snake_case"
    assert "dnsServerName" in test_server, "Fields should be camelCase"
    assert "dns_server_name" not in test_server, "Fields should NOT be snake_case"


def test_rust_build_mutation_response_with_camel_case_false():
    """Verify Rust preserves snake_case when auto_camel_case=False."""
    import fraiseql._fraiseql_rs as fraiseql_rs

    # Simple mutation result with snake_case fields
    mutation_json = json.dumps(
        {
            "id": "123",
            "ip_address": "192.168.1.1",
            "dns_server_name": "test-dns",
        }
    )

    result_bytes = fraiseql_rs.build_mutation_response(
        mutation_json,
        "createServer",
        "CreateServerSuccess",
        "CreateServerError",
        "test_server",  # entity_field_name in snake_case
        "TestServer",
        None,  # cascade_selections
        False,
        None,
        None,
        legacy_document(None, None, "test_server", None),
    )

    result = json.loads(result_bytes.decode("utf-8"))

    # Verify response structure
    assert "data" in result
    assert "createServer" in result["data"]
    mutation_result = result["data"]["createServer"]

    # Verify Success type
    assert mutation_result["__typename"] == "CreateServerSuccess"

    # CRITICAL: Verify entity_field_name was NOT converted (stays snake_case)
    assert "test_server" in mutation_result, "entity_field_name should remain snake_case"
    assert "testServer" not in mutation_result, "entity_field_name should NOT be camelCase"

    # Verify entity fields remain snake_case
    test_server = mutation_result["test_server"]
    assert "ip_address" in test_server, "Fields should remain snake_case"
    assert "ipAddress" not in test_server, "Fields should NOT be camelCase"
    assert "dns_server_name" in test_server, "Fields should remain snake_case"
    assert "dnsServerName" not in test_server, "Fields should NOT be camelCase"


def test_rust_mutation_default_auto_camel_case_is_true():
    """Verify that auto_camel_case defaults to True for backward compatibility."""
    import fraiseql._fraiseql_rs as fraiseql_rs

    mutation_json = json.dumps(
        {
            "id": "123",
            "ip_address": "192.168.1.1",
        }
    )

    # Call without auto_camel_case parameter (should default to True)
    result_bytes = fraiseql_rs.build_mutation_response(
        mutation_json,
        "createServer",
        "CreateServerSuccess",
        "CreateServerError",
        "test_server",
        "TestServer",
        None,
        entity_selections=UNFILTERED,
    )

    result = json.loads(result_bytes.decode("utf-8"))
    mutation_result = result["data"]["createServer"]

    # Should be camelCase by default
    assert "testServer" in mutation_result, "Default should be auto_camel_case=True"
    test_server = mutation_result["testServer"]
    assert "ipAddress" in test_server, "Default should convert to camelCase"

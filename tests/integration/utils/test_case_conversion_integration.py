"""Integration tests for utils modules with real schema data.

These tests validate that utility functions work correctly with real GraphQL schemas
and database operations, not just isolated unit tests.
"""

import pytest
from graphql import graphql

# Import schema_builder to ensure SchemaRegistry is patched
import fraiseql.gql.schema_builder  # noqa: F401
from fraiseql import fraise_type, query
from fraiseql.utils.casing import to_camel_case, to_snake_case


@pytest.fixture(scope="class")
def utils_test_schema(meta_test_schema):
    """Schema registry with diverse field names for utils testing."""
    # Clear any existing registrations
    meta_test_schema.clear()

    # Create types with diverse field naming patterns
    @fraise_type(sql_source="test_case_conversion")
    class CaseConversionTestType:
        # Basic cases
        id: int
        name: str
        email_address: str

        # Edge cases from real schemas
        user_id: int
        user_id2: int  # Number suffix
        user2_fa_token: str  # Number + acronym
        api_v2_endpoint: str  # Version number
        xml_http_request: str  # Acronyms
        json_web_token: str  # Multiple acronyms
        html_css_parser: str  # Multiple acronyms
        ipv4_address: str  # Number prefix
        ipv6_address: str  # Number prefix
        sha256_hash: str  # Number prefix
        md5_checksum: str  # Number prefix
        http_status_code: int  # Acronym + word
        db_connection_pool: str  # Acronym + words
        sql_query_builder: str  # Acronym + words
        rest_api_client: str  # Acronym + words
        graphql_schema_parser: str  # Acronym + words

        # Complex real-world examples
        created_at_timestamp: str
        updated_by_user_id: int
        last_login_ip_address: str
        password_reset_token_hash: str
        email_verification_code: str
        two_factor_auth_enabled: bool
        oauth2_access_token: str
        jwt_refresh_token: str
        csrf_protection_token: str
        session_id_cookie: str

    @query
    async def get_case_conversion_test(info) -> list[CaseConversionTestType]:
        return []

    # Register types with schema
    meta_test_schema.register_type(CaseConversionTestType)
    meta_test_schema.register_query(get_case_conversion_test)

    return meta_test_schema


def extract_all_field_names(schema_registry):
    """Extract all field names from registered types in schema."""
    field_names = set()

    # Get all registered types
    for type_cls in schema_registry.types.values():
        # Get type hints (field annotations)
        type_hints = getattr(type_cls, "__annotations__", {})

        # Add all field names
        field_names.update(type_hints.keys())

        # Also check for any additional fields that might be registered
        definition = getattr(type_cls, "__fraiseql_definition__", None)
        if definition and hasattr(definition, "fields"):
            field_names.update(definition.fields.keys())

    return sorted(field_names)


class TestCaseConversionIntegration:
    """Integration tests for case conversion utilities with real schema data."""

    async def test_case_conversion_with_all_schema_fields(self, utils_test_schema):
        """Case conversion should work with ALL field names from real schema."""
        # Get all field names from the test schema
        all_fields = extract_all_field_names(utils_test_schema)

        assert len(all_fields) > 20, f"Expected many fields, got {len(all_fields)}: {all_fields}"

        # Test roundtrip conversion for every field
        for field_name in all_fields:
            # Skip special fields
            if field_name.startswith("__"):
                continue

            # Test camelCase -> snake_case -> camelCase roundtrip
            camel = to_camel_case(field_name)
            snake_back = to_snake_case(camel)

            # Should be consistent (allowing for some normalization)
            assert snake_back == field_name, (
                f"Roundtrip failed for {field_name}: {field_name} -> {camel} -> {snake_back}"
            )

    @pytest.mark.parametrize(
        ("field_name", "expected_camel"),
        [
            # Basic cases
            ("id", "id"),
            ("name", "name"),
            ("email_address", "emailAddress"),
            # Edge cases from real schemas
            ("user_id", "userId"),
            ("user_id2", "userId2"),  # Number suffix
            ("user2_fa_token", "user2FaToken"),  # Number + acronym
            ("api_v2_endpoint", "apiV2Endpoint"),  # Version number
            ("xml_http_request", "xmlHttpRequest"),  # Acronyms
            ("json_web_token", "jsonWebToken"),  # Multiple acronyms
            ("html_css_parser", "htmlCssParser"),  # Multiple acronyms
            ("ipv4_address", "ipv4Address"),  # Number prefix
            ("ipv6_address", "ipv6Address"),  # Number prefix
            ("sha256_hash", "sha256Hash"),  # Number prefix
            ("md5_checksum", "md5Checksum"),  # Number prefix
            ("http_status_code", "httpStatusCode"),  # Acronym + word
            ("db_connection_pool", "dbConnectionPool"),  # Acronym + words
            ("sql_query_builder", "sqlQueryBuilder"),  # Acronym + words
            ("rest_api_client", "restApiClient"),  # Acronym + words
            ("graphql_schema_parser", "graphqlSchemaParser"),  # Acronym + words
            # Complex real-world examples
            ("created_at_timestamp", "createdAtTimestamp"),
            ("updated_by_user_id", "updatedByUserId"),
            ("last_login_ip_address", "lastLoginIpAddress"),
            ("password_reset_token_hash", "passwordResetTokenHash"),
            ("email_verification_code", "emailVerificationCode"),
            ("two_factor_auth_enabled", "twoFactorAuthEnabled"),
            ("oauth2_access_token", "oauth2AccessToken"),
            ("jwt_refresh_token", "jwtRefreshToken"),
            ("csrf_protection_token", "csrfProtectionToken"),
            ("session_id_cookie", "sessionIdCookie"),
        ],
    )
    def test_case_conversion_edge_cases_from_real_schema(self, field_name, expected_camel):
        """Case conversion should handle edge cases extracted from real schemas."""
        # Test snake_case to camelCase
        result = to_camel_case(field_name)
        assert result == expected_camel, f"Expected {expected_camel}, got {result} for {field_name}"

        # Test roundtrip consistency
        snake_back = to_snake_case(result)
        assert snake_back == field_name, (
            f"Roundtrip failed: {field_name} -> {result} -> {snake_back}"
        )

    async def test_case_conversion_with_graphql_execution(self, utils_test_schema):
        """Case conversion should work in complete GraphQL execution pipeline."""
        schema = utils_test_schema.build_schema()

        # Test query with mixed case field selections
        query_str = """
        query {
            getCaseConversionTest {
                id
                name
                emailAddress
                userId
                apiV2Endpoint
                xmlHttpRequest
                jsonWebToken
                ipv4Address
                httpStatusCode
                createdAtTimestamp
                twoFactorAuthEnabled
            }
        }
        """

        # Should not raise validation errors
        result = await graphql(schema, query_str)
        assert not result.errors, f"GraphQL execution failed: {result.errors}"

    async def test_case_conversion_with_nested_data_structures(self, utils_test_schema):
        """Case conversion should work with nested GraphQL data structures."""
        from fraiseql.utils.casing import dict_keys_to_snake_case, transform_keys_to_camel_case

        # Test data that might come from GraphQL input
        input_data = {
            "user_id": 123,
            "email_address": "test@example.com",
            "api_v2_endpoint": "https://api.example.com/v2",
            "nested_object": {
                "xml_http_request": True,
                "json_web_token": "token123",
                "items": [{"item_name": "A", "item_value": 1}, {"item_name": "B", "item_value": 2}],
            },
        }

        # Convert to camelCase (for GraphQL response)
        camel_data = transform_keys_to_camel_case(input_data)

        # Verify structure is preserved
        assert "userId" in camel_data
        assert "emailAddress" in camel_data
        assert "apiV2Endpoint" in camel_data
        assert "nestedObject" in camel_data
        assert isinstance(camel_data["nestedObject"], dict)
        assert "xmlHttpRequest" in camel_data["nestedObject"]
        assert "jsonWebToken" in camel_data["nestedObject"]
        assert isinstance(camel_data["nestedObject"]["items"], list)
        assert len(camel_data["nestedObject"]["items"]) == 2

        # Test roundtrip: camelCase -> snake_case -> camelCase
        snake_data = dict_keys_to_snake_case(camel_data)
        camel_again = transform_keys_to_camel_case(snake_data)

        # Should be identical to original camelCase
        assert camel_again == camel_data

    async def test_case_conversion_performance_with_large_schema(self, utils_test_schema):
        """Case conversion should perform well with large numbers of fields."""
        import time

        # Get all field names
        all_fields = extract_all_field_names(utils_test_schema)

        # Filter out ALL-CAPS fields like AND/OR which don't roundtrip correctly
        # (AND -> AND -> and, not AND). These are special logical operators.
        filterable_fields = [f for f in all_fields if not f.isupper()]

        # Test conversion performance
        start_time = time.time()

        for _ in range(100):  # Simulate multiple conversions
            for field_name in filterable_fields:
                camel = to_camel_case(field_name)
                snake = to_snake_case(camel)
                assert snake == field_name, f"Roundtrip failed: {field_name} -> {camel} -> {snake}"

        end_time = time.time()
        duration = end_time - start_time

        # Should complete in reasonable time (< 1 second for 100 iterations)
        assert duration < 1.0, (
            f"Case conversion too slow: {duration:.2f}s for {len(filterable_fields)} fields"
        )

    def test_case_conversion_handles_special_characters(self):
        """Case conversion should handle fields with special characters gracefully."""
        # These should not crash (even if results aren't perfect)
        special_fields = [
            "field_with_underscores",
            "fieldWithCamelCase",
            "field_with_numbers_123",
            "field_with_mixed_123_Case",
            "_private_field",
            "field__with__double__underscores",
        ]

        for field in special_fields:
            # Should not raise exceptions
            camel = to_camel_case(field)
            snake = to_snake_case(camel)

            # Results should be strings
            assert isinstance(camel, str)
            assert isinstance(snake, str)

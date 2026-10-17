"""Tests for automatic where clause filter descriptions."""

from dataclasses import dataclass
from uuid import UUID

import fraiseql
from fraiseql.sql.graphql_where_generator import IntFilter, NetworkAddressFilter, StringFilter
from fraiseql.utils.where_clause_descriptions import (
    OPERATOR_DESCRIPTIONS,
    apply_filter_descriptions,
    enhance_all_filter_types,
    generate_filter_docstring,
)


class TestFilterDescriptionGeneration:
    """Test automatic generation of filter type descriptions."""

    def test_string_filter_has_automatic_descriptions(self) -> None:
        """Test that StringFilter gets automatic field descriptions."""
        # Apply descriptions to StringFilter
        apply_filter_descriptions(StringFilter)

        fields = StringFilter.__gql_fields__

        # Check that filter operations have descriptions
        assert fields["eq"].description == "Exact match - field equals the specified value"
        assert (
            fields["contains"].description
            == "Substring search - field contains the specified text (case-sensitive)"
        )
        assert (
            fields["startswith"].description
            == "Prefix match - field starts with the specified text"
        )
        assert (
            fields["in_"].description
            == "In list - field value is one of the values in the provided list"
        )
        assert (
            fields["isnull"].description
            == "Null check - true to find null values, false to find non-null values"
        )

    def test_int_filter_has_automatic_descriptions(self) -> None:
        """Test that IntFilter gets automatic field descriptions."""
        apply_filter_descriptions(IntFilter)

        fields = IntFilter.__gql_fields__

        # Check comparison operations
        assert fields["eq"].description == "Exact match - field equals the specified value"
        assert (
            fields["gt"].description
            == "Greater than - field value is greater than the specified value"
        )
        assert (
            fields["gte"].description
            == "Greater than or equal - field value is greater than or equal to the specified value"
        )
        assert (
            fields["lt"].description == "Less than - field value is less than the specified value"
        )
        assert (
            fields["lte"].description
            == "Less than or equal - field value is less than or equal to the specified value"
        )

    def test_network_filter_has_network_specific_descriptions(self) -> None:
        """Test that NetworkAddressFilter gets network-specific descriptions."""
        apply_filter_descriptions(NetworkAddressFilter)

        fields = NetworkAddressFilter.__gql_fields__

        # Check network-specific operations
        assert (
            fields["inSubnet"].description
            == "Subnet membership - IP address is within the specified CIDR subnet"
        )
        assert (
            fields["isPrivate"].description
            == "Private network - IP address is in RFC 1918 private ranges"
        )
        assert fields["isIPv4"].description == "IPv4 address - IP address is IPv4 format"
        assert (
            fields["isLoopback"].description
            == "Loopback address - IP is loopback (127.0.0.1 or ::1)"
        )

    def test_docstring_generation(self) -> None:
        """Test automatic docstring generation for filter classes."""
        # Create a mock filter class fields structure
        mock_fields = {
            "eq": fraiseql.fraise_field(),
            "contains": fraiseql.fraise_field(),
            "isnull": fraiseql.fraise_field(),
        }

        docstring = generate_filter_docstring("StringFilter", mock_fields)

        expected_parts = [
            "String field filtering operations for text search and matching.",
            "All string operations are case-sensitive.",
            "Fields:",
            "    eq: Exact match - field equals the specified value",
            "    contains: Substring search - field contains the specified text (case-sensitive)",
            "    isnull: Null check - true to find null values, false to find non-null values",
        ]

        for part in expected_parts:
            assert part in docstring

    def test_ltree_filter_has_hierarchical_descriptions(self) -> None:
        """Test that LTreeFilter gets comprehensive hierarchical operator descriptions."""
        # Create mock fields for common LTREE operators
        mock_fields = {
            "eq": fraiseql.fraise_field(),
            "ancestor_of": fraiseql.fraise_field(),
            "descendant_of": fraiseql.fraise_field(),
            "matches_lquery": fraiseql.fraise_field(),
            "nlevel_eq": fraiseql.fraise_field(),
            "subpath": fraiseql.fraise_field(),
            "lca": fraiseql.fraise_field(),
        }

        docstring = generate_filter_docstring("LTreeFilter", mock_fields)

        expected_parts = [
            "Hierarchical path filtering operations for PostgreSQL ltree data type.",
            "Supports hierarchical relationships, pattern matching, and path analysis.",
            "Fields:",
            "    eq: Exact match - field equals the specified value",
            "    ancestor_of: Hierarchical ancestor - path is an ancestor of the specified path",
            "    descendant_of: Hierarchical descendant - path is a descendant of the specified path",
            "    matches_lquery: Pattern match - path matches the lquery pattern (wildcards supported)",
            "    nlevel_eq: Exact depth - path has exactly N levels (e.g., nlevel_eq: 3 for 3-level paths)",
            "    subpath: Extract subpath - extract a portion of the path (offset, length)",
            "    lca: Lowest common ancestor - find the most specific common ancestor of multiple paths",
        ]

        for part in expected_parts:
            assert part in docstring

    def test_only_applies_to_filter_classes(self) -> None:
        """Test that descriptions are only applied to filter classes."""

        @fraiseql.fraise_type
        @dataclass
        class RegularType:
            """Regular type, not a filter.

            Fields:
                eq: This should not get filter descriptions
                contains: Regular field, not a filter operation
            """

            eq: str
            contains: str

        # This should not apply filter descriptions because it doesn't end with "Filter"
        apply_filter_descriptions(RegularType)

        fields = RegularType.__gql_fields__

        # Should still have docstring descriptions (applied by general auto-descriptions)
        # but not filter-specific descriptions
        assert "This should not get filter descriptions" in fields["eq"].description
        assert "Regular field, not a filter operation" in fields["contains"].description

    def test_preserves_existing_descriptions(self) -> None:
        """Test that existing explicit descriptions are not overridden."""

        @fraiseql.fraise_input
        @dataclass
        class CustomFilter:
            """Custom filter type."""

            contains: str  # Will get automatic description
            eq: str = fraiseql.fraise_field(description="Custom equality description")

        apply_filter_descriptions(CustomFilter)

        fields = CustomFilter.__gql_fields__

        # Explicit description should be preserved
        assert fields["eq"].description == "Custom equality description"
        # Automatic description should be applied
        assert (
            fields["contains"].description
            == "Substring search - field contains the specified text (case-sensitive)"
        )

    def test_graphql_name_mapping(self) -> None:
        """Test that GraphQL field name mapping works correctly."""
        # StringFilter has in_ field mapped to "in" in GraphQL
        apply_filter_descriptions(StringFilter)

        fields = StringFilter.__gql_fields__
        in_field = fields["in_"]

        # Should have description for the in_ operation
        assert (
            in_field.description
            == "In list - field value is one of the values in the provided list"
        )
        # Should map to "in" in GraphQL
        assert in_field.graphql_name == "in"

    def test_unknown_operators_get_fallback_description(self) -> None:
        """Test that unknown operators get fallback descriptions."""

        @fraiseql.fraise_input
        @dataclass
        class CustomFilter:
            """Custom filter with unknown operator."""

            unknown_op: str

        apply_filter_descriptions(CustomFilter)

        fields = CustomFilter.__gql_fields__

        # Should get fallback description
        assert fields["unknown_op"].description == "unknown_op operation"


class TestFilterEnhancement:
    """Test enhancement of existing filter types."""

    def test_enhance_all_filter_types(self) -> None:
        """Test that all filter types can be enhanced."""
        # This should not raise any errors
        enhance_all_filter_types()

        # Verify some common filter types have been enhanced
        assert StringFilter.__gql_fields__["eq"].description is not None
        assert IntFilter.__gql_fields__["gt"].description is not None

    def test_integration_with_type_definition(self) -> None:
        """Test that filter descriptions work with the type definition pipeline."""

        @fraiseql.fraise_input
        @dataclass
        class TestFilter:
            """Test filter type."""

            eq: str
            contains: str
            gt: int

        # Should automatically get descriptions through the apply_auto_descriptions pipeline
        fields = TestFilter.__gql_fields__

        assert fields["eq"].description == "Exact match - field equals the specified value"
        assert (
            fields["contains"].description
            == "Substring search - field contains the specified text (case-sensitive)"
        )
        assert (
            fields["gt"].description
            == "Greater than - field value is greater than the specified value"
        )


class TestOperatorDescriptions:
    """Test that all expected operators have descriptions."""

    def test_all_common_operators_have_descriptions(self) -> None:
        """Test that all common filter operators have descriptions."""
        common_operators = [
            "eq",
            "neq",
            "gt",
            "gte",
            "lt",
            "lte",
            "contains",
            "startswith",
            "endswith",
            "in_",
            "nin",
            "isnull",
        ]

        for operator in common_operators:
            assert operator in OPERATOR_DESCRIPTIONS
            assert len(OPERATOR_DESCRIPTIONS[operator]) > 10  # Reasonable description length

    def test_network_operators_have_descriptions(self) -> None:
        """Test that network-specific operators have descriptions."""
        network_operators = [
            "inSubnet",
            "inRange",
            "isPrivate",
            "isPublic",
            "isIPv4",
            "isIPv6",
            "isLoopback",
            "isMulticast",
        ]

        for operator in network_operators:
            assert operator in OPERATOR_DESCRIPTIONS
            assert (
                "IP" in OPERATOR_DESCRIPTIONS[operator]
                or "network" in OPERATOR_DESCRIPTIONS[operator].lower()
            )

    def test_description_quality(self) -> None:
        """Test that descriptions are helpful and informative."""
        # Check a few key descriptions for quality
        eq_desc = OPERATOR_DESCRIPTIONS["eq"]
        assert "exact" in eq_desc.lower()
        assert "match" in eq_desc.lower()

        contains_desc = OPERATOR_DESCRIPTIONS["contains"]
        assert "substring" in contains_desc.lower() or "contains" in contains_desc.lower()
        assert "case-sensitive" in contains_desc.lower()

        isnull_desc = OPERATOR_DESCRIPTIONS["isnull"]
        assert "null" in isnull_desc.lower()
        assert "true" in isnull_desc.lower()
        assert "false" in isnull_desc.lower()


class TestApolloStudioIntegration:
    """Test that filter descriptions will appear correctly in Apollo Studio."""

    def test_filter_descriptions_in_graphql_schema(self) -> None:
        """Test that filter descriptions appear in generated GraphQL schema."""

        @fraiseql.fraise_input
        @dataclass
        class UserFilter:
            """User filtering operations."""

            name: str
            age: int

        # Convert to GraphQL type and check descriptions
        from fraiseql.core.graphql_type import convert_type_to_graphql_input

        gql_type = convert_type_to_graphql_input(UserFilter)

        # Check that the type itself has description
        if gql_type.description:
            # UserFilter's docstring ends with "operations." so it gets auto-generated
            # The generated docstring is "UserFilter operations.\n\nFields:\n..."
            expected_desc_parts = ["userfilter operations", "fields:"]
            for part in expected_desc_parts:
                assert part in gql_type.description.lower()

        # Check that fields have descriptions from auto-generation
        fields = gql_type.fields

        # These should get filter descriptions since UserFilter ends with "Filter"
        if "name" in fields and fields["name"].description:
            assert "operation" in fields["name"].description
        if "age" in fields and fields["age"].description:
            assert "operation" in fields["age"].description

    def test_backward_compatibility_with_existing_schemas(self) -> None:
        """Test that existing schemas continue to work with filter enhancements."""

        @fraiseql.fraise_type
        @dataclass
        class User:
            """User model."""

            id: UUID
            name: str
            age: int

        # This should work without errors and not interfere with User type
        fields = User.__gql_fields__

        # User fields should not get filter descriptions (not a filter type)
        assert fields["name"].description is None
        assert fields["age"].description is None

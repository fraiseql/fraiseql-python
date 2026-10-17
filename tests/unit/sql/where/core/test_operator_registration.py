"""Integration tests for operator registration.

This module contains meta-tests that ensure all operator strategies are properly
registered in the ALL_OPERATORS dictionary. These tests prevent regressions where
operators exist in strategies but fail validation.

The network operators bug (where operators existed in NetworkOperatorStrategy but
were missing from ALL_OPERATORS) should have been caught by these tests.
"""

import pytest

from fraiseql.sql.operators import get_default_registry
from fraiseql.where_clause import ALL_OPERATORS, FieldCondition


class TestOperatorRegistrationIntegrity:
    """Meta-tests to ensure operator strategies and validation are synchronized."""

    def test_all_strategy_operators_are_in_all_operators(self):
        """All operators from registered strategies should be in ALL_OPERATORS.

        This is a META-TEST that catches missing operator registrations.
        If a strategy defines an operator but ALL_OPERATORS doesn't include it,
        this test fails.

        This test would have caught the network operators bug!
        """
        registry = get_default_registry()
        missing_operators = []

        for strategy in registry._strategies:
            if not hasattr(strategy, "SUPPORTED_OPERATORS"):
                # Some fallback strategies don't define SUPPORTED_OPERATORS
                continue

            strategy_name = strategy.__class__.__name__

            for operator in strategy.SUPPORTED_OPERATORS:
                # Skip internal/private operators
                if operator.startswith("_"):
                    continue

                # Check if operator is in ALL_OPERATORS
                if operator not in ALL_OPERATORS:
                    missing_operators.append({"operator": operator, "strategy": strategy_name})

        # Report all missing operators
        if missing_operators:
            error_msg = (
                f"Found {len(missing_operators)} operators in strategies "
                f"but missing from ALL_OPERATORS:\n"
            )
            for missing in missing_operators:
                error_msg += f"  ❌ {missing['operator']} (from {missing['strategy']})\n"
            error_msg += (
                "\nThese operators must be added to where_clause.py ALL_OPERATORS dict.\n"
                "Otherwise they will fail validation even though they have implementations."
            )
            pytest.fail(error_msg)

    def test_network_operators_specifically_registered(self):
        """Network operators should all be in ALL_OPERATORS (regression test)."""
        # These operators exist in NetworkOperatorStrategy and MUST be in ALL_OPERATORS
        required_network_operators = [
            "isIPv4",
            "isIPv6",
            "isPrivate",
            "isPublic",
            "inSubnet",
            "inRange",
            "overlaps",
            # lowercase variants
            "isipv4",
            "isipv6",
            "isprivate",
            "ispublic",
            "insubnet",
            "inrange",
        ]

        missing = []
        for operator in required_network_operators:
            if operator not in ALL_OPERATORS:
                missing.append(operator)

        if missing:
            pytest.fail(
                f"Network operators missing from ALL_OPERATORS: {missing}\n"
                f"Add these to NETWORK_OPERATORS dict in where_clause.py"
            )

    def test_postgresql_specific_operators_registered(self):
        """PostgreSQL-specific operators should be registered.

        Ensures operators from:
        - NetworkOperatorStrategy
        - MacAddressOperatorStrategy
        - LTreeOperatorStrategy
        - DateRangeOperatorStrategy

        are all in ALL_OPERATORS.
        """
        from fraiseql.sql.operators.postgresql.network_operators import (
            NetworkOperatorStrategy,
        )

        # Check NetworkOperatorStrategy
        network_strategy = NetworkOperatorStrategy()
        if hasattr(network_strategy, "SUPPORTED_OPERATORS"):
            for op in network_strategy.SUPPORTED_OPERATORS:
                if not op.startswith("_") and op not in ALL_OPERATORS:
                    pytest.fail(
                        f"Network operator '{op}' from NetworkOperatorStrategy "
                        f"is missing from ALL_OPERATORS"
                    )

        # Similar checks for other PostgreSQL strategies
        try:
            from fraiseql.sql.operators.postgresql.macaddr_operators import (
                MacAddressOperatorStrategy,
            )

            mac_strategy = MacAddressOperatorStrategy()
            if hasattr(mac_strategy, "SUPPORTED_OPERATORS"):
                for op in mac_strategy.SUPPORTED_OPERATORS:
                    if not op.startswith("_") and op not in ALL_OPERATORS:
                        pytest.fail(
                            f"MAC address operator '{op}' from MacAddressOperatorStrategy "
                            f"is missing from ALL_OPERATORS"
                        )
        except ImportError:
            pass  # Strategy might not exist yet

        try:
            from fraiseql.sql.operators.postgresql.ltree_operators import (
                LTreeOperatorStrategy,
            )

            ltree_strategy = LTreeOperatorStrategy()
            if hasattr(ltree_strategy, "SUPPORTED_OPERATORS"):
                for op in ltree_strategy.SUPPORTED_OPERATORS:
                    if not op.startswith("_") and op not in ALL_OPERATORS:
                        pytest.fail(
                            f"LTree operator '{op}' from LTreeOperatorStrategy "
                            f"is missing from ALL_OPERATORS"
                        )
        except ImportError:
            pass  # Strategy might not exist yet


class TestNetworkOperatorValidation:
    """Integration tests for network operators through complete validation pipeline."""

    @pytest.mark.parametrize(
        "operator",
        [
            "isIPv4",
            "isIPv6",
            "isPrivate",
            "isPublic",
            "inSubnet",
            "inRange",
            "overlaps",
            "strictleft",
            "strictright",
        ],
    )
    def test_network_operator_passes_field_condition_validation(self, operator):
        """Network operators should pass FieldCondition validation.

        This test validates the complete pipeline from user input to validation.
        If this fails, it means the operator is missing from ALL_OPERATORS.
        """
        # Determine appropriate test value based on operator
        if operator.startswith("is"):
            value = True
        else:
            value = "192.168.1.0/24"

        # Should NOT raise ValueError about invalid operator
        condition = FieldCondition(
            field_path=["ip_address"],
            operator=operator,
            value=value,
            lookup_strategy="sql_column",
            target_column="ip_address",
            jsonb_path=None,
        )

        assert condition.operator == operator
        assert condition.value == value

    @pytest.mark.parametrize(
        ("operator", "value"),
        [
            ("isIPv4", True),
            ("isIPv6", True),
            ("isPrivate", True),
            ("isPublic", True),
            ("inSubnet", "10.0.0.0/8"),
            ("inRange", "192.168.0.0/16"),
            ("overlaps", "172.16.0.0/12"),
        ],
    )
    def test_network_operator_with_realistic_values(self, operator, value):
        """Network operators with realistic values should pass validation."""
        condition = FieldCondition(
            field_path=["server", "ipAddress"],
            operator=operator,
            value=value,
            lookup_strategy="sql_column",
            target_column="ip_address",
        )

        assert condition.operator == operator
        assert condition.value == value

    def test_network_operator_camelcase_variants(self):
        """Both camelCase and lowercase variants should work."""
        # CamelCase variants
        camelcase_ops = {
            "isIPv4": True,
            "isIPv6": True,
            "isPrivate": True,
            "isPublic": True,
            "inSubnet": "192.168.1.0/24",
            "inRange": "10.0.0.0/8",
        }

        for operator, value in camelcase_ops.items():
            condition = FieldCondition(
                field_path=["ip"],
                operator=operator,
                value=value,
                lookup_strategy="sql_column",
                target_column="ip",
            )
            assert condition.operator == operator

        # lowercase variants
        lowercase_ops = {
            "isipv4": True,
            "isipv6": True,
            "isprivate": True,
            "ispublic": True,
            "insubnet": "192.168.1.0/24",
            "inrange": "10.0.0.0/8",
        }

        for operator, value in lowercase_ops.items():
            condition = FieldCondition(
                field_path=["ip"],
                operator=operator,
                value=value,
                lookup_strategy="sql_column",
                target_column="ip",
            )
            assert condition.operator == operator

    def test_network_operator_with_jsonb_path(self):
        """Network operators should work with JSONB paths."""
        condition = FieldCondition(
            field_path=["server", "ipAddress"],
            operator="isIPv4",
            value=True,
            lookup_strategy="jsonb_path",
            target_column="data",
            jsonb_path=["server", "ipAddress"],
        )

        assert condition.operator == "isIPv4"
        assert condition.lookup_strategy == "jsonb_path"

    def test_network_operator_invalid_operator_still_fails(self):
        """Invalid operators should still fail validation."""
        with pytest.raises(ValueError, match="Invalid operator"):
            FieldCondition(
                field_path=["ip"],
                operator="isTotallyNotAnOperator",
                value=True,
                lookup_strategy="sql_column",
                target_column="ip",
            )


class TestAllOperatorCategoriesRegistered:
    """Ensure all operator categories are properly registered."""

    def test_comparison_operators_registered(self):
        """Basic comparison operators should be in ALL_OPERATORS."""
        comparison_ops = ["eq", "neq", "gt", "gte", "lt", "lte"]

        for op in comparison_ops:
            assert op in ALL_OPERATORS, f"Comparison operator '{op}' missing from ALL_OPERATORS"

    def test_containment_operators_registered(self):
        """Containment operators should be in ALL_OPERATORS."""
        containment_ops = ["in", "nin"]

        for op in containment_ops:
            assert op in ALL_OPERATORS, f"Containment operator '{op}' missing from ALL_OPERATORS"

    def test_string_operators_registered(self):
        """String operators should be in ALL_OPERATORS."""
        string_ops = [
            "contains",
            "icontains",
            "startswith",
            "istartswith",
            "endswith",
            "iendswith",
            "like",
            "ilike",
        ]

        for op in string_ops:
            assert op in ALL_OPERATORS, f"String operator '{op}' missing from ALL_OPERATORS"

    def test_null_operators_registered(self):
        """NULL operators should be in ALL_OPERATORS."""
        assert "isnull" in ALL_OPERATORS, "NULL operator 'isnull' missing from ALL_OPERATORS"

    def test_vector_operators_registered(self):
        """Vector operators should be in ALL_OPERATORS."""
        vector_ops = [
            "cosine_distance",
            "l2_distance",
            "l1_distance",
            "hamming_distance",
            "jaccard_distance",
        ]

        for op in vector_ops:
            assert op in ALL_OPERATORS, f"Vector operator '{op}' missing from ALL_OPERATORS"

    def test_fulltext_operators_registered(self):
        """Fulltext operators should be in ALL_OPERATORS."""
        fulltext_ops = [
            "matches",
            "plain_query",
            "phrase_query",
            "websearch_query",
            "rank_gt",
            "rank_lt",
            "rank_cd_gt",
            "rank_cd_lt",
        ]

        for op in fulltext_ops:
            assert op in ALL_OPERATORS, f"Fulltext operator '{op}' missing from ALL_OPERATORS"

    def test_array_operators_registered(self):
        """Array operators should be in ALL_OPERATORS."""
        array_ops = [
            "array_eq",
            "array_neq",
            "array_contains",
            "array_contained_by",
            "contained_by",
            "array_overlaps",
            # Note: 'contains' is excluded from ALL_OPERATORS due to ambiguity
            "overlaps",
            "array_length_eq",
            "len_eq",
            "array_any_eq",
            "any_eq",
        ]

        for op in array_ops:
            assert op in ALL_OPERATORS, f"Array operator '{op}' missing from ALL_OPERATORS"

    def test_network_operators_registered(self):
        """Network operators should be in ALL_OPERATORS (regression test)."""
        network_ops = [
            "isIPv4",
            "isIPv6",
            "isPrivate",
            "isPublic",
            "inSubnet",
            "inRange",
            "overlaps",  # Also in array ops
            "strictleft",
            "strictright",
        ]

        for op in network_ops:
            assert op in ALL_OPERATORS, f"Network operator '{op}' missing from ALL_OPERATORS"

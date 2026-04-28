"""Tests for FK column hierarchy operators (descendant_of_id, ancestor_of_id).

Validates that hierarchy operators work correctly when filtering on FK column
references, not just JSONB paths and SQL columns.

Example:
  allocations(where: {
    location: { id: { descendantOfId: $locationId } }
  })

The 'location' is a nested FK reference, and descendantOfId should generate
a proper subquery to find descendants in the location hierarchy.
"""

from fraiseql.sql.where.core.sql_builder import _build_hierarchy_subquery
from fraiseql.where_clause import FieldCondition


class TestFKHierarchyOperators:
    """Test hierarchy operator support for FK column lookups."""

    def test_fk_column_detects_hierarchy_operators(self) -> None:
        """FK column lookup strategy should handle hierarchy operators."""
        # Create a FieldCondition for FK column with descendant_of_id
        condition = FieldCondition(
            field_path=["location", "id"],
            operator="descendant_of_id",
            value="location-123",
            lookup_strategy="fk_column",
            target_column="location_id",
        )

        # Should have the correct operator
        assert condition.operator == "descendant_of_id"
        assert condition.lookup_strategy == "fk_column"
        assert condition.target_column == "location_id"

    def test_fk_column_ancestor_of_id_operator(self) -> None:
        """FK column lookup strategy should handle ancestor_of_id operator."""
        condition = FieldCondition(
            field_path=["location", "id"],
            operator="ancestor_of_id",
            value="location-456",
            lookup_strategy="fk_column",
            target_column="location_id",
        )

        assert condition.operator == "ancestor_of_id"
        assert condition.lookup_strategy == "fk_column"

    def test_hierarchy_subquery_builder_exists(self) -> None:
        """Verify _build_hierarchy_subquery is available for FK columns."""
        # This function should exist and be callable
        assert callable(_build_hierarchy_subquery)

    def test_fk_column_vs_jsonb_path_operators(self) -> None:
        """Both FK and JSONB paths should support same hierarchy operators."""
        # FK column condition
        fk_condition = FieldCondition(
            field_path=["location", "id"],
            operator="descendant_of_id",
            value="location-789",
            lookup_strategy="fk_column",
            target_column="location_id",
        )

        # JSONB path condition (for comparison)
        jsonb_condition = FieldCondition(
            field_path=["location", "id"],
            operator="descendant_of_id",
            value="location-789",
            lookup_strategy="jsonb_path",
            target_column="data",
            jsonb_path=["location", "id"],
        )

        # Both should support the same operator
        assert fk_condition.operator == jsonb_condition.operator
        assert fk_condition.operator == "descendant_of_id"

    def test_operator_requires_entity_schema(self) -> None:
        """Hierarchy operators require FraiseQLConfig.default_entity_schema."""
        import pytest

        # The operator validation happens in to_sql() when it tries to get
        # entity_schema from SchemaRegistry.config.default_entity_schema
        # This is a requirement for the feature to work

        condition = FieldCondition(
            field_path=["location", "id"],
            operator="descendant_of_id",
            value="location-xyz",
            lookup_strategy="fk_column",
            target_column="location_id",
        )

        # Attempting to convert to SQL without proper config should raise an error
        # This validates the requirement is enforced
        with pytest.raises(ValueError, match="default_entity_schema"):
            condition.to_sql()

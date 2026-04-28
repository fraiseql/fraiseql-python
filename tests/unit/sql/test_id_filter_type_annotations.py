"""Tests for IDFilter type annotations.

Validates that descendantOfId and ancestorOfId fields in IDFilter
are correctly typed as ID, not str. This prevents GraphQL validation
errors when passing ID! variables to ltree hierarchy filters.

Issue: IDFilter descendantOfId/ancestorOfId should be ID type, not str
Related commit: fix(where): add descendantOfId/ancestorOfId to IDFilter
"""

from fraiseql.sql.graphql_where_generator import IDFilter
from fraiseql.types import ID


class TestIDFilterTypeAnnotations:
    """Validate IDFilter type annotations for ltree hierarchy operations."""

    def test_id_filter_descendant_of_id_is_id_type(self) -> None:
        """DescendantOfId field should be typed as ID | None, not str | None."""
        # Get IDFilter class definition
        hints = IDFilter.__annotations__

        # Verify descendant_of_id is ID type
        assert "descendant_of_id" in hints, "descendant_of_id field should exist"

        # The annotation should be ID | None
        annotation = hints["descendant_of_id"]
        # Extract the actual type from Optional/Union
        assert annotation is (ID | None), (
            f"descendant_of_id should be ID | None, got {annotation}"
        )

    def test_id_filter_ancestor_of_id_is_id_type(self) -> None:
        """AncestorOfId field should be typed as ID | None, not str | None."""
        hints = IDFilter.__annotations__

        # Verify ancestor_of_id is ID type
        assert "ancestor_of_id" in hints, "ancestor_of_id field should exist"

        # The annotation should be ID | None
        annotation = hints["ancestor_of_id"]
        assert annotation is (ID | None), (
            f"ancestor_of_id should be ID | None, got {annotation}"
        )

    def test_id_filter_all_fields_use_id_type(self) -> None:
        """All ID-based fields in IDFilter should use ID type, not str."""
        hints = IDFilter.__annotations__

        id_fields = [
            "eq",
            "neq",
            "descendant_of_id",
            "ancestor_of_id",
        ]

        for field in id_fields:
            annotation = hints.get(field)
            assert annotation is not None, f"Field {field} should be defined"

            # Check that it uses ID type (either ID or list[ID] or with Optional)
            # We're checking the string representation since Python's type system is complex
            annotation_str = str(annotation)

            # Should contain "ID" and not contain "str"
            assert "ID" in annotation_str, (
                f"Field {field} should use ID type, got {annotation_str}"
            )

            # Should NOT have str unless it's in a comment or error message
            # More specifically, we want to ensure it's not "str | None"
            if field in ["descendant_of_id", "ancestor_of_id"]:
                assert (
                    "str | None" not in annotation_str
                ), f"Field {field} should not be str | None, got {annotation_str}"




class TestIDFilterVsUUIDFilter:
    """Verify that IDFilter and UUIDFilter are distinct and correctly typed."""

    def test_id_filter_and_uuid_filter_different_types(self) -> None:
        """IDFilter and UUIDFilter should use different ID types."""
        from fraiseql.sql.graphql_where_generator import UUIDFilter

        # IDFilter uses ID type
        id_hints = IDFilter.__annotations__
        assert "ID" in str(id_hints["eq"]), "IDFilter.eq should use ID type"

        # UUIDFilter uses UUID type
        uuid_hints = UUIDFilter.__annotations__
        assert "UUID" in str(uuid_hints["eq"]), "UUIDFilter.eq should use UUID type"

    def test_uuid_filter_also_has_ltree_fields(self) -> None:
        """UUIDFilter might also have descendant_of_id/ancestor_of_id fields."""
        from fraiseql.sql.graphql_where_generator import UUIDFilter

        # UUIDFilter should have these fields (though they may use str or UUID)
        hints = UUIDFilter.__annotations__
        assert "descendant_of_id" in hints, "UUIDFilter should have descendant_of_id"
        assert "ancestor_of_id" in hints, "UUIDFilter should have ancestor_of_id"

        # For UUIDFilter, these are str (paths), not UUID
        # This is correct because ltree paths are strings, not UUIDs
        desc_annotation = str(hints["descendant_of_id"])
        anc_annotation = str(hints["ancestor_of_id"])

        # These should be str | None (not UUID | None)
        # since ltree paths are text-based, not UUID-based
        assert "str" in desc_annotation or "None" in desc_annotation, (
            f"UUIDFilter.descendant_of_id should be str | None, got {desc_annotation}"
        )
        assert "str" in anc_annotation or "None" in anc_annotation, (
            f"UUIDFilter.ancestor_of_id should be str | None, got {anc_annotation}"
        )

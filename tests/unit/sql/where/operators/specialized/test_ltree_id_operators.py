"""Tests for LTree ID-based hierarchy operators (Phase 1: Schema & Registration).

Covers:
- UUIDFilter has descendant_of_id and ancestor_of_id fields (Option B: _id field)
- is_operator_dict() recognizes the new operators
- LTREE_OPERATORS and ALL_OPERATORS include the new operators
- LTreeOperatorStrategy.SUPPORTED_OPERATORS does NOT include them
"""

from fraiseql.sql.operators import LTreeOperatorStrategy
from fraiseql.sql.where.core.sql_builder import is_operator_dict
from fraiseql.types import LTree
from fraiseql.where_clause import ALL_OPERATORS, LTREE_OPERATORS


class TestUUIDFilterFields:
    """Test that UUIDFilter dataclass accepts the new ID-based hierarchy operators.

    Option B: operators live on the UUID/ID field (e.g. locationId), not the
    ltree path field. The frontend passes a UUID and fraiseql resolves it to
    a path subquery internally.
    """

    def test_uuid_filter_has_descendant_of_id_field(self) -> None:
        """UUIDFilter should accept descendant_of_id as a string field."""
        from fraiseql.sql.graphql_where_generator import UUIDFilter

        f = UUIDFilter(descendant_of_id="some-uuid")
        assert f.descendant_of_id == "some-uuid"

    def test_uuid_filter_has_ancestor_of_id_field(self) -> None:
        """UUIDFilter should accept ancestor_of_id as a string field."""
        from fraiseql.sql.graphql_where_generator import UUIDFilter

        f = UUIDFilter(ancestor_of_id="another-uuid")
        assert f.ancestor_of_id == "another-uuid"

    def test_uuid_filter_id_fields_default_to_none(self) -> None:
        """New fields should default to None."""
        from fraiseql.sql.graphql_where_generator import UUIDFilter

        f = UUIDFilter()
        assert f.descendant_of_id is None
        assert f.ancestor_of_id is None

    def test_ltree_filter_does_not_have_descendant_of_id(self) -> None:
        """LTreeFilter should NOT have these fields — they belong on UUIDFilter."""
        from fraiseql.sql.graphql_where_generator import LTreeFilter

        assert not hasattr(LTreeFilter, "descendant_of_id")

    def test_ltree_filter_does_not_have_ancestor_of_id(self) -> None:
        """LTreeFilter should NOT have these fields — they belong on UUIDFilter."""
        from fraiseql.sql.graphql_where_generator import LTreeFilter

        assert not hasattr(LTreeFilter, "ancestor_of_id")


class TestIsOperatorDictRecognition:
    """Test that is_operator_dict recognizes the new operators."""

    def test_descendant_of_id_recognized_as_operator(self) -> None:
        """is_operator_dict should return True for descendant_of_id."""
        assert is_operator_dict({"descendant_of_id": "floor-uuid"}) is True

    def test_ancestor_of_id_recognized_as_operator(self) -> None:
        """is_operator_dict should return True for ancestor_of_id."""
        assert is_operator_dict({"ancestor_of_id": "floor-uuid"}) is True

    def test_combined_with_other_operators(self) -> None:
        """is_operator_dict should return True when mixed with other operators."""
        assert is_operator_dict({"descendant_of_id": "uuid", "eq": "val"}) is True


class TestLtreeOperatorsDict:
    """Test that LTREE_OPERATORS and ALL_OPERATORS include the new operators."""

    def test_descendant_of_id_in_ltree_operators(self) -> None:
        """LTREE_OPERATORS should contain descendant_of_id."""
        assert "descendant_of_id" in LTREE_OPERATORS

    def test_ancestor_of_id_in_ltree_operators(self) -> None:
        """LTREE_OPERATORS should contain ancestor_of_id."""
        assert "ancestor_of_id" in LTREE_OPERATORS

    def test_descendant_of_id_in_all_operators(self) -> None:
        """ALL_OPERATORS should contain descendant_of_id."""
        assert "descendant_of_id" in ALL_OPERATORS

    def test_ancestor_of_id_in_all_operators(self) -> None:
        """ALL_OPERATORS should contain ancestor_of_id."""
        assert "ancestor_of_id" in ALL_OPERATORS

    def test_descendant_of_id_maps_to_ltree_descendant_op(self) -> None:
        """descendant_of_id should map to the <@ operator (inner path comparison)."""
        assert LTREE_OPERATORS["descendant_of_id"] == "<@"

    def test_ancestor_of_id_maps_to_ltree_ancestor_op(self) -> None:
        """ancestor_of_id should map to the @> operator (inner path comparison)."""
        assert LTREE_OPERATORS["ancestor_of_id"] == "@>"


class TestLTreeOperatorStrategyExclusion:
    """Test that LTreeOperatorStrategy does NOT handle the new operators.

    These operators are intercepted in build_where_clause_recursive() before
    dispatch because they need db_field_name to derive the entity table and
    generate the nested IN subquery.
    """

    def test_descendant_of_id_not_supported_by_strategy(self) -> None:
        """LTreeOperatorStrategy should not claim to support descendant_of_id."""
        strategy = LTreeOperatorStrategy()
        assert strategy.supports_operator("descendant_of_id", LTree) is False

    def test_ancestor_of_id_not_supported_by_strategy(self) -> None:
        """LTreeOperatorStrategy should not claim to support ancestor_of_id."""
        strategy = LTreeOperatorStrategy()
        assert strategy.supports_operator("ancestor_of_id", LTree) is False

    def test_descendant_of_id_not_in_supported_operators_set(self) -> None:
        """descendant_of_id should not appear in SUPPORTED_OPERATORS."""
        assert "descendant_of_id" not in LTreeOperatorStrategy.SUPPORTED_OPERATORS

    def test_ancestor_of_id_not_in_supported_operators_set(self) -> None:
        """ancestor_of_id should not appear in SUPPORTED_OPERATORS."""
        assert "ancestor_of_id" not in LTreeOperatorStrategy.SUPPORTED_OPERATORS

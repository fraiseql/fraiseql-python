"""Unit tests for mutation field selection extraction and filtering.

Tests the Phase 6.1 field selection functionality for mutations.
"""

import json
from typing import Any

import pytest
from graphql import FieldNode, GraphQLResolveInfo, NameNode, SelectionSetNode

from fraiseql.mutations.mutation_resolver import (
    convert_selections_to_json,
    extract_field_selections,
)


class MockGraphQLResolveInfo:
    """Mock GraphQLResolveInfo for testing field extraction."""

    def __init__(self, field_nodes: list[FieldNode] | None = None):
        """Initialize mock resolve info."""
        self.field_nodes = field_nodes or []
        self.fragments = {}


def _create_field_node(
    name: str,
    selection_set: SelectionSetNode | None = None,
    alias: str | None = None,
) -> FieldNode:
    """Create a FieldNode for testing."""
    field_node = FieldNode(
        name=NameNode(value=name),
        selection_set=selection_set,
    )
    if alias:
        field_node.alias = NameNode(value=alias)
    return field_node


def _create_selection_set(field_nodes: list[FieldNode]) -> SelectionSetNode:
    """Create a SelectionSetNode from field nodes."""
    return SelectionSetNode(selections=tuple(field_nodes))


class TestExtractFieldSelections:
    """Tests for extract_field_selections() function."""

    def test_no_info_returns_none(self) -> None:
        """Extracting from None info returns None."""
        result = extract_field_selections(None)
        assert result is None

    def test_no_field_nodes_returns_none(self) -> None:
        """Info with no field nodes returns None."""
        info = MockGraphQLResolveInfo(field_nodes=[])
        result = extract_field_selections(info)
        assert result is None

    def test_simple_field_selection(self) -> None:
        """Extract simple flat field selection."""
        # Mutation selects: { id, name }
        field_nodes = [
            _create_field_node(
                "createUser",
                selection_set=_create_selection_set([
                    _create_field_node("id"),
                    _create_field_node("name"),
                ]),
            ),
        ]
        info = MockGraphQLResolveInfo(field_nodes=field_nodes)

        result = extract_field_selections(info)

        assert result is not None
        assert result == {"id": True, "name": True}

    def test_nested_field_selection(self) -> None:
        """Extract nested field selection (e.g., user { address { city } })."""
        # Mutation selects: { user { id, address { city } } }
        field_nodes = [
            _create_field_node(
                "createUser",
                selection_set=_create_selection_set([
                    _create_field_node(
                        "user",
                        selection_set=_create_selection_set([
                            _create_field_node("id"),
                            _create_field_node(
                                "address",
                                selection_set=_create_selection_set([
                                    _create_field_node("city"),
                                ]),
                            ),
                        ]),
                    ),
                ]),
            ),
        ]
        info = MockGraphQLResolveInfo(field_nodes=field_nodes)

        result = extract_field_selections(info)

        assert result is not None
        assert result == {
            "user": {
                "id": True,
                "address": {"city": True},
            },
        }

    def test_multiple_fields_mixed_nesting(self) -> None:
        """Extract multiple fields with mixed nesting levels."""
        # Mutation selects: { id, name, address { city, country } }
        field_nodes = [
            _create_field_node(
                "createLocation",
                selection_set=_create_selection_set([
                    _create_field_node("id"),
                    _create_field_node("name"),
                    _create_field_node(
                        "address",
                        selection_set=_create_selection_set([
                            _create_field_node("city"),
                            _create_field_node("country"),
                        ]),
                    ),
                ]),
            ),
        ]
        info = MockGraphQLResolveInfo(field_nodes=field_nodes)

        result = extract_field_selections(info)

        assert result is not None
        assert result == {
            "id": True,
            "name": True,
            "address": {
                "city": True,
                "country": True,
            },
        }

    def test_skips_typename_fields(self) -> None:
        """GraphQL __typename fields are skipped."""
        # Mutation selects: { __typename, id, name }
        field_nodes = [
            _create_field_node(
                "createUser",
                selection_set=_create_selection_set([
                    _create_field_node("__typename"),
                    _create_field_node("id"),
                    _create_field_node("name"),
                ]),
            ),
        ]
        info = MockGraphQLResolveInfo(field_nodes=field_nodes)

        result = extract_field_selections(info)

        assert result is not None
        # __typename should be skipped
        assert "__typename" not in result
        assert result == {"id": True, "name": True}

    def test_deeply_nested_selections(self) -> None:
        """Extract deeply nested field selections (3+ levels)."""
        # Mutation selects: { user { profile { address { coordinates { lat, lon } } } } }
        field_nodes = [
            _create_field_node(
                "createEntity",
                selection_set=_create_selection_set([
                    _create_field_node(
                        "user",
                        selection_set=_create_selection_set([
                            _create_field_node(
                                "profile",
                                selection_set=_create_selection_set([
                                    _create_field_node(
                                        "address",
                                        selection_set=_create_selection_set([
                                            _create_field_node(
                                                "coordinates",
                                                selection_set=_create_selection_set([
                                                    _create_field_node("lat"),
                                                    _create_field_node("lon"),
                                                ]),
                                            ),
                                        ]),
                                    ),
                                ]),
                            ),
                        ]),
                    ),
                ]),
            ),
        ]
        info = MockGraphQLResolveInfo(field_nodes=field_nodes)

        result = extract_field_selections(info)

        assert result is not None
        assert result == {
            "user": {
                "profile": {
                    "address": {
                        "coordinates": {
                            "lat": True,
                            "lon": True,
                        },
                    },
                },
            },
        }

    def test_empty_selection_set_returns_none(self) -> None:
        """Field with no selection set (leaf field) returns None."""
        field_nodes = [
            _create_field_node("createUser", selection_set=None),
        ]
        info = MockGraphQLResolveInfo(field_nodes=field_nodes)

        result = extract_field_selections(info)

        # Leaf field with no selection set - returns None
        assert result is None

    def test_multiple_field_nodes_merged(self) -> None:
        """Multiple field nodes are merged into single result."""
        # Two mutations executed in single query (unlikely but should handle)
        field_nodes = [
            _create_field_node(
                "createUser",
                selection_set=_create_selection_set([
                    _create_field_node("id"),
                ]),
            ),
            _create_field_node(
                "updateUser",
                selection_set=_create_selection_set([
                    _create_field_node("name"),
                ]),
            ),
        ]
        info = MockGraphQLResolveInfo(field_nodes=field_nodes)

        result = extract_field_selections(info)

        assert result is not None
        # Selections should be merged
        assert "id" in result or "name" in result


class TestConvertSelectionsToJson:
    """Tests for convert_selections_to_json() function."""

    def test_simple_dict_to_json(self) -> None:
        """Convert simple selection dict to JSON."""
        selections = {"id": True, "name": True}
        result = convert_selections_to_json(selections)

        assert result is not None
        parsed = json.loads(result)
        assert parsed == selections

    def test_nested_dict_to_json(self) -> None:
        """Convert nested selection dict to JSON."""
        selections = {
            "id": True,
            "address": {"city": True, "country": True},
        }
        result = convert_selections_to_json(selections)

        assert result is not None
        parsed = json.loads(result)
        assert parsed == selections

    def test_none_selections_returns_none(self) -> None:
        """None selections return None."""
        result = convert_selections_to_json(None)
        assert result is None

    def test_empty_dict_returns_none(self) -> None:
        """Empty selections dict returns None."""
        result = convert_selections_to_json({})
        assert result is None

    def test_complex_nested_selections(self) -> None:
        """Convert complex nested selections to JSON."""
        selections = {
            "id": True,
            "name": True,
            "user": {
                "id": True,
                "profile": {
                    "bio": True,
                    "avatar": {"url": True},
                },
            },
        }
        result = convert_selections_to_json(selections)

        assert result is not None
        parsed = json.loads(result)
        assert parsed == selections


class TestIntegration:
    """Integration tests combining extraction and conversion."""

    def test_extract_and_convert_workflow(self) -> None:
        """Test typical workflow: extract from info, convert to JSON."""
        # Create info with nested selections
        field_nodes = [
            _create_field_node(
                "createUser",
                selection_set=_create_selection_set([
                    _create_field_node("id"),
                    _create_field_node(
                        "address",
                        selection_set=_create_selection_set([
                            _create_field_node("city"),
                        ]),
                    ),
                ]),
            ),
        ]
        info = MockGraphQLResolveInfo(field_nodes=field_nodes)

        # Extract from info
        selections = extract_field_selections(info)
        assert selections is not None

        # Convert to JSON
        json_str = convert_selections_to_json(selections)
        assert json_str is not None

        # Verify round-trip
        parsed = json.loads(json_str)
        assert parsed == selections

    def test_mutation_resolver_usage_pattern(self) -> None:
        """Test the typical usage pattern in mutation resolvers."""
        from fraiseql.mutations.mutation_resolver import extract_field_selections

        # Simulate mutation resolver receiving info
        field_nodes = [
            _create_field_node(
                "createLocation",
                selection_set=_create_selection_set([
                    _create_field_node(
                        "location",
                        selection_set=_create_selection_set([
                            _create_field_node("id"),
                            _create_field_node("name"),
                        ]),
                    ),
                ]),
            ),
        ]
        info = MockGraphQLResolveInfo(field_nodes=field_nodes)

        # This is what mutation resolvers would do
        selections = extract_field_selections(info)
        json_selections = convert_selections_to_json(selections)

        # Verify we have the expected structure
        assert selections == {"location": {"id": True, "name": True}}
        assert json_selections is not None
        assert json.loads(json_selections) == selections


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_info_with_no_selection_set(self) -> None:
        """Info with field but no selection set."""
        field_nodes = [_create_field_node("mutationField")]
        info = MockGraphQLResolveInfo(field_nodes=field_nodes)

        result = extract_field_selections(info)

        # No selection set = no nested fields
        assert result is None

    def test_large_selection_tree(self) -> None:
        """Handle large selection trees without stack overflow."""
        # Create deeply nested structure (20 levels)
        current_selection: SelectionSetNode | None = None
        for i in range(20):
            field = _create_field_node(
                f"field_{i}",
                selection_set=current_selection,
            )
            current_selection = _create_selection_set([field])

        field_nodes = [_create_field_node("root", selection_set=current_selection)]
        info = MockGraphQLResolveInfo(field_nodes=field_nodes)

        # Should not raise RecursionError
        result = extract_field_selections(info)
        assert result is not None

    def test_many_sibling_fields(self) -> None:
        """Handle many sibling fields efficiently."""
        # Create selection with many fields
        many_fields = [_create_field_node(f"field_{i}") for i in range(100)]
        field_nodes = [
            _create_field_node(
                "root",
                selection_set=_create_selection_set(many_fields),
            ),
        ]
        info = MockGraphQLResolveInfo(field_nodes=field_nodes)

        result = extract_field_selections(info)

        assert result is not None
        assert len(result) == 100
        for i in range(100):
            assert f"field_{i}" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

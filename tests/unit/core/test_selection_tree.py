"""Tests for selection tree building with materialized path pattern."""

from fraiseql.core.ast_parser import FieldPath
from fraiseql.core.selection_tree import FieldSelection, build_selection_tree


class TestFieldSelectionDataClass:
    """Test the FieldSelection data structure."""

    def test_field_selection_creation(self) -> None:
        """Test that FieldSelection can be created with required fields."""
        selection = FieldSelection(
            path=["id"],
            alias="userId",
            type_name="UUID",
            is_nested_object=False,
        )

        assert selection.path == ["id"]
        assert selection.alias == "userId"
        assert selection.type_name == "UUID"
        assert selection.is_nested_object is False

    def test_field_selection_nested_path(self) -> None:
        """Test FieldSelection with nested path."""
        selection = FieldSelection(
            path=["equipment", "name"],
            alias="deviceName",
            type_name="String",
            is_nested_object=False,
        )

        assert selection.path == ["equipment", "name"]
        assert len(selection.path) == 2


class TestBuildSelectionTreeSimpleAliases:
    """Test building selection tree with simple (non-nested) aliases."""

    def test_builds_selection_with_simple_aliases(self) -> None:
        """Test that aliases are preserved with materialized paths."""
        # Simulate: query { users { userId: id, fullName: name } }
        field_paths = [
            FieldPath(alias="userId", path=["id"]),
            FieldPath(alias="fullName", path=["name"]),
        ]

        # Mock schema registry that returns type info
        from unittest.mock import Mock

        mock_registry = Mock()
        mock_registry.get_field_type.side_effect = lambda type_name, field_name: Mock(
            type_name="UUID" if field_name == "id" else "String",
            is_nested_object=False,
        )

        selections = build_selection_tree(
            field_paths,
            mock_registry,
            parent_type="User",
        )

        # Should build two selections
        assert len(selections) == 2

        # Check first selection (id → userId)
        id_sel = next(s for s in selections if s.path == ["id"])
        assert id_sel.alias == "userId"
        assert id_sel.type_name == "UUID"
        assert id_sel.is_nested_object is False

        # Check second selection (name → fullName)
        name_sel = next(s for s in selections if s.path == ["name"])
        assert name_sel.alias == "fullName"
        assert name_sel.type_name == "String"
        assert name_sel.is_nested_object is False

    def test_builds_selection_without_aliases(self) -> None:
        """Test that field names are used as aliases when no alias provided."""
        # Simulate: query { users { id, name } }
        field_paths = [
            FieldPath(alias="id", path=["id"]),  # No alias, so alias = field name
            FieldPath(alias="name", path=["name"]),
        ]

        from unittest.mock import Mock

        mock_registry = Mock()
        mock_registry.get_field_type.side_effect = lambda type_name, field_name: Mock(
            type_name="UUID" if field_name == "id" else "String",
            is_nested_object=False,
        )

        selections = build_selection_tree(
            field_paths,
            mock_registry,
            parent_type="User",
        )

        assert len(selections) == 2
        assert all(s.alias == s.path[0] for s in selections)  # alias == field name


class TestBuildSelectionTreeNestedAliases:
    """Test building selection tree with nested object aliases."""

    def test_builds_selection_with_nested_aliases(self) -> None:
        """Test nested aliases use materialized paths."""
        # Simulate: query {
        #   assignments {
        #     device: equipment {
        #       deviceName: name
        #     }
        #   }
        # }
        field_paths = [
            FieldPath(alias="device", path=["equipment"]),
            FieldPath(alias="deviceName", path=["equipment", "name"]),
        ]

        from unittest.mock import Mock

        mock_registry = Mock()

        def get_field_type(type_name, field_name) -> None:
            if type_name == "Assignment" and field_name == "equipment":
                return Mock(type_name="Equipment", is_nested_object=True)
            if type_name == "Equipment" and field_name == "name":
                return Mock(type_name="String", is_nested_object=False)
            return None

        mock_registry.get_field_type.side_effect = get_field_type

        selections = build_selection_tree(
            field_paths,
            mock_registry,
            parent_type="Assignment",
        )

        # Should build two selections with materialized paths
        assert len(selections) == 2

        # Check intermediate selection (equipment → device)
        equipment_sel = next(s for s in selections if s.path == ["equipment"])
        assert equipment_sel.alias == "device"
        assert equipment_sel.type_name == "Equipment"
        assert equipment_sel.is_nested_object is True

        # Check nested selection (equipment.name → deviceName)
        name_sel = next(s for s in selections if s.path == ["equipment", "name"])
        assert name_sel.alias == "deviceName"
        assert name_sel.type_name == "String"
        assert name_sel.is_nested_object is False

    def test_handles_deep_nesting(self) -> None:
        """Test deeply nested paths (3+ levels)."""
        # Simulate: query {
        #   users {
        #     profile {
        #       settings {
        #         darkMode: theme_dark_mode
        #       }
        #     }
        #   }
        # }
        field_paths = [
            FieldPath(alias="profile", path=["profile"]),
            FieldPath(alias="settings", path=["profile", "settings"]),
            FieldPath(alias="darkMode", path=["profile", "settings", "theme_dark_mode"]),
        ]

        from unittest.mock import Mock

        mock_registry = Mock()

        def get_field_type(type_name, field_name) -> None:
            if type_name == "User" and field_name == "profile":
                return Mock(type_name="Profile", is_nested_object=True)
            if type_name == "Profile" and field_name == "settings":
                return Mock(type_name="Settings", is_nested_object=True)
            if type_name == "Settings" and field_name == "theme_dark_mode":
                return Mock(type_name="Boolean", is_nested_object=False)
            return None

        mock_registry.get_field_type.side_effect = get_field_type

        selections = build_selection_tree(
            field_paths,
            mock_registry,
            parent_type="User",
        )

        # Should have 3 selections with materialized paths
        assert len(selections) == 3

        # Verify all paths are correct
        paths = [s.path for s in selections]
        assert ["profile"] in paths
        assert ["profile", "settings"] in paths
        assert ["profile", "settings", "theme_dark_mode"] in paths

        # Verify deepest selection has correct alias
        deepest = next(s for s in selections if len(s.path) == 3)
        assert deepest.alias == "darkMode"


class TestBuildSelectionTreeEdgeCases:
    """Test edge cases and error handling."""

    def test_handles_empty_field_paths(self) -> None:
        """Test with empty field path list."""
        from unittest.mock import Mock

        mock_registry = Mock()

        selections = build_selection_tree(
            [],
            mock_registry,
            parent_type="User",
        )

        assert selections == []

    def test_handles_missing_schema_type(self) -> None:
        """Test when schema registry doesn't have type info."""
        field_paths = [
            FieldPath(alias="unknownField", path=["unknown_field"]),
        ]

        from unittest.mock import Mock

        mock_registry = Mock()
        mock_registry.get_field_type.return_value = None  # Type not found

        selections = build_selection_tree(
            field_paths,
            mock_registry,
            parent_type="User",
        )

        # Should still create selection but with unknown type
        assert len(selections) == 1
        assert selections[0].type_name == "Unknown"
        assert selections[0].is_nested_object is False

    def test_deduplicates_selections_by_path(self) -> None:
        """Test that duplicate paths are deduplicated."""
        # Simulate: query {
        #   users {
        #     device: equipment { id, name }
        #     equipment { id, name }  # Same field, different alias
        #   }
        # }
        # This should deduplicate the intermediate "equipment" path
        field_paths = [
            FieldPath(alias="device", path=["equipment"]),
            FieldPath(alias="deviceId", path=["equipment", "id"]),
            FieldPath(alias="equipment", path=["equipment"]),  # Duplicate path!
            FieldPath(alias="equipmentId", path=["equipment", "id"]),  # Duplicate!
        ]

        from unittest.mock import Mock

        mock_registry = Mock()

        def get_field_type(type_name, field_name) -> None:
            if field_name == "equipment":
                return Mock(type_name="Equipment", is_nested_object=True)
            if field_name == "id":
                return Mock(type_name="UUID", is_nested_object=False)
            return None

        mock_registry.get_field_type.side_effect = get_field_type

        selections = build_selection_tree(
            field_paths,
            mock_registry,
            parent_type="Assignment",
        )

        # Should deduplicate: 2 unique paths total
        paths = [tuple(s.path) for s in selections]
        assert len(set(paths)) == len(paths)  # All paths unique

        # First occurrence should be kept for equipment
        equipment_sel = next(s for s in selections if s.path == ["equipment"])
        assert equipment_sel.alias == "device"  # First alias


def _object_registry():
    from unittest.mock import Mock

    def field_type(type_name, field_name):
        if field_name == "equipment":
            return Mock(type_name="Equipment", is_nested_object=True, graphql_name="equipment")
        return Mock(type_name="String", is_nested_object=False, graphql_name=field_name)

    registry = Mock()
    registry.get_field_type.side_effect = field_type
    return registry


class TestBuildSelectionTreeResponseKeys:
    """A FieldPath from extract_flat_paths names each segment: aliases above the leaf count."""

    # { d: equipment { id } e: equipment { n: name } }
    PATHS = [
        FieldPath("id", ["equipment", "id"], ("equipment", "id"), ("d", "id")),
        FieldPath("n", ["equipment", "name"], ("equipment", "name"), ("e", "n")),
    ]

    def test_by_alias_names_each_segment_by_its_response_key(self) -> None:
        selections = build_selection_tree(self.PATHS, _object_registry(), parent_type="Assignment")

        assert [(s.path, s.alias, s.response_path) for s in selections] == [
            (["equipment"], "d", ["d"]),
            (["equipment", "id"], "id", ["d", "id"]),
            (["equipment"], "e", ["e"]),
            (["equipment", "name"], "n", ["e", "n"]),
        ]

    def test_without_aliases_fields_are_named_and_merged(self) -> None:
        selections = build_selection_tree(
            self.PATHS, _object_registry(), parent_type="Assignment", by_alias=False
        )

        assert [(s.path, s.response_path) for s in selections] == [
            (["equipment"], ["equipment"]),
            (["equipment", "id"], ["equipment", "id"]),
            (["equipment", "name"], ["equipment", "name"]),
        ]

    def test_typename_is_typed_as_the_object_it_is_selected_on(self) -> None:
        paths = [
            FieldPath(
                "t", ["equipment", "__typename"], ("equipment", "__typename"), ("equipment", "t")
            )
        ]
        selections = build_selection_tree(paths, _object_registry(), parent_type="Assignment")

        assert selections[-1].type_name == "Equipment"
        assert selections[-1].response_path == ["equipment", "t"]

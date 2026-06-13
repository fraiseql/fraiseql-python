"""Unit tests for entity field selection extraction from GraphQL queries.

These tests verify the _extract_entity_field_selections() function which
parses GraphQL selection sets to extract nested field selections for entity
objects in mutation responses.

Related to GitHub issue #525.
"""

from unittest.mock import MagicMock

from graphql import FieldNode, InlineFragmentNode, TypeNode

from fraiseql.mutations.mutation_decorator import _extract_entity_field_selections


def create_field_node(name: str, selections: list | None = None) -> FieldNode:
    """Helper to create a FieldNode mock."""
    field = MagicMock(spec=FieldNode)
    field.name.value = name

    if selections is not None:
        field.selection_set = MagicMock()
        field.selection_set.selections = selections
    else:
        field.selection_set = None

    return field


def create_inline_fragment(type_name: str, selections: list) -> InlineFragmentNode:
    """Helper to create an InlineFragmentNode mock."""
    fragment = MagicMock(spec=InlineFragmentNode)

    # Create properly nested type_condition mock
    type_condition = MagicMock(spec=TypeNode)
    name_mock = MagicMock()
    name_mock.value = type_name
    type_condition.name = name_mock
    fragment.type_condition = type_condition

    # Create selection set mock
    fragment.selection_set = MagicMock()
    fragment.selection_set.selections = selections
    return fragment


class TestEntityFieldExtraction:
    """Test extraction of entity field selections from GraphQL queries."""

    def test_extract_simple_entity_fields(self):
        """Test extracting simple entity field selections.

        GraphQL:
            mutation {
                createLocation(input: $input) {
                    ... on CreateLocationSuccess {
                        location {
                            id
                            name
                        }
                    }
                }
            }
        """
        # Create mock info
        info = MagicMock()

        # Entity field selections: location { id, name }
        entity_selections = [
            create_field_node("id"),
            create_field_node("name"),
        ]

        # Success fragment: ... on CreateLocationSuccess { location { ... } }
        location_field = create_field_node("location", entity_selections)
        success_fragment = create_inline_fragment("CreateLocationSuccess", [location_field])

        # Mutation field: createLocation { ... }
        mutation_field = MagicMock(spec=FieldNode)
        mutation_field.selection_set = MagicMock()
        mutation_field.selection_set.selections = [success_fragment]

        info.field_nodes = [mutation_field]

        # Extract selections
        result = _extract_entity_field_selections(
            info, "CreateLocationSuccess", "location"
        )

        # Should return nested dict with fields
        assert result is not None
        assert "fields" in result
        assert set(result["fields"]) == {"id", "name"}

    def test_extract_nested_entity_fields(self):
        """Test extracting nested entity field selections.

        GraphQL:
            mutation {
                createLocation(input: $input) {
                    ... on CreateLocationSuccess {
                        location {
                            id
                            name
                            address {
                                id
                                formatted
                                city
                            }
                        }
                    }
                }
            }
        """
        info = MagicMock()

        # Nested address selections
        address_selections = [
            create_field_node("id"),
            create_field_node("formatted"),
            create_field_node("city"),
        ]
        address_field = create_field_node("address", address_selections)

        # Location selections with nested address
        location_selections = [
            create_field_node("id"),
            create_field_node("name"),
            address_field,
        ]
        location_field = create_field_node("location", location_selections)

        # Success fragment
        success_fragment = create_inline_fragment(
            "CreateLocationSuccess", [location_field]
        )

        mutation_field = MagicMock(spec=FieldNode)
        mutation_field.selection_set = MagicMock()
        mutation_field.selection_set.selections = [success_fragment]
        info.field_nodes = [mutation_field]

        # Extract selections
        result = _extract_entity_field_selections(
            info, "CreateLocationSuccess", "location"
        )

        # Should have top-level fields
        assert result is not None
        assert "fields" in result
        assert set(result["fields"]) == {"id", "name", "address"}

        # Should have nested address selections
        assert "address" in result
        assert "fields" in result["address"]
        assert set(result["address"]["fields"]) == {"id", "formatted", "city"}

    def test_extract_deeply_nested_fields(self):
        """Test extracting deeply nested field selections (3+ levels).

        GraphQL:
            location {
                id
                contract {
                    id
                    customer {
                        id
                        name
                    }
                }
            }
        """
        info = MagicMock()

        # Level 3: customer fields
        customer_selections = [
            create_field_node("id"),
            create_field_node("name"),
        ]
        customer_field = create_field_node("customer", customer_selections)

        # Level 2: contract fields
        contract_selections = [
            create_field_node("id"),
            customer_field,
        ]
        contract_field = create_field_node("contract", contract_selections)

        # Level 1: location fields
        location_selections = [
            create_field_node("id"),
            contract_field,
        ]
        location_field = create_field_node("location", location_selections)

        success_fragment = create_inline_fragment(
            "CreateLocationSuccess", [location_field]
        )

        mutation_field = MagicMock(spec=FieldNode)
        mutation_field.selection_set = MagicMock()
        mutation_field.selection_set.selections = [success_fragment]
        info.field_nodes = [mutation_field]

        result = _extract_entity_field_selections(
            info, "CreateLocationSuccess", "location"
        )

        # Verify nested structure
        assert result is not None
        assert set(result["fields"]) == {"id", "contract"}
        assert set(result["contract"]["fields"]) == {"id", "customer"}
        assert set(result["contract"]["customer"]["fields"]) == {"id", "name"}

    def test_no_entity_field_selected(self):
        """Test when entity field is not selected in query.

        GraphQL:
            mutation {
                createLocation(input: $input) {
                    ... on CreateLocationSuccess {
                        status
                        message
                    }
                }
            }
        """
        info = MagicMock()

        # Only status and message, no location field
        success_selections = [
            create_field_node("status"),
            create_field_node("message"),
        ]
        success_fragment = create_inline_fragment(
            "CreateLocationSuccess", success_selections
        )

        mutation_field = MagicMock(spec=FieldNode)
        mutation_field.selection_set = MagicMock()
        mutation_field.selection_set.selections = [success_fragment]
        info.field_nodes = [mutation_field]

        result = _extract_entity_field_selections(
            info, "CreateLocationSuccess", "location"
        )

        # Should return None when entity not selected
        assert result is None

    def test_empty_entity_selection(self):
        """Test when entity is selected but with no sub-fields.

        GraphQL:
            mutation {
                createLocation(input: $input) {
                    ... on CreateLocationSuccess {
                        location
                    }
                }
            }

        Note: GraphQL spec says empty selection means all fields.
        We return None to indicate "don't filter" (backward compat).
        """
        info = MagicMock()

        # location with no sub-selections
        location_field = create_field_node("location", [])

        success_fragment = create_inline_fragment(
            "CreateLocationSuccess", [location_field]
        )

        mutation_field = MagicMock(spec=FieldNode)
        mutation_field.selection_set = MagicMock()
        mutation_field.selection_set.selections = [success_fragment]
        info.field_nodes = [mutation_field]

        result = _extract_entity_field_selections(
            info, "CreateLocationSuccess", "location"
        )

        # Empty selection = return None (don't filter, return all fields)
        assert result is None

    def test_wrong_fragment_type(self):
        """Test when fragment is for different type (Error vs Success)."""
        info = MagicMock()

        # Fragment for Error type, looking for Success type
        error_selections = [
            create_field_node("code"),
            create_field_node("message"),
        ]
        error_fragment = create_inline_fragment(
            "CreateLocationError", error_selections
        )

        mutation_field = MagicMock(spec=FieldNode)
        mutation_field.selection_set = MagicMock()
        mutation_field.selection_set.selections = [error_fragment]
        info.field_nodes = [mutation_field]

        result = _extract_entity_field_selections(
            info, "CreateLocationSuccess", "location"
        )

        # Should return None when fragment type doesn't match
        assert result is None

    def test_no_field_nodes(self):
        """Test when info has no field nodes."""
        info = MagicMock()
        info.field_nodes = []

        result = _extract_entity_field_selections(
            info, "CreateLocationSuccess", "location"
        )

        assert result is None

    def test_none_info(self):
        """Test when info is None."""
        result = _extract_entity_field_selections(
            None, "CreateLocationSuccess", "location"
        )

        assert result is None

    def test_multiple_entity_fields(self):
        """Test extracting selections from multiple entity fields.

        GraphQL:
            mutation {
                updateMachineLocation(input: $input) {
                    ... on UpdateMachineLocationSuccess {
                        machine {
                            id
                            name
                        }
                        previousLocation {
                            id
                        }
                        newLocation {
                            id
                            name
                        }
                    }
                }
            }
        """
        info = MagicMock()

        # Create selections for each entity
        machine_selections = [
            create_field_node("id"),
            create_field_node("name"),
        ]
        machine_field = create_field_node("machine", machine_selections)

        prev_loc_selections = [create_field_node("id")]
        prev_loc_field = create_field_node("previousLocation", prev_loc_selections)

        new_loc_selections = [
            create_field_node("id"),
            create_field_node("name"),
        ]
        new_loc_field = create_field_node("newLocation", new_loc_selections)

        success_fragment = create_inline_fragment(
            "UpdateMachineLocationSuccess",
            [machine_field, prev_loc_field, new_loc_field],
        )

        mutation_field = MagicMock(spec=FieldNode)
        mutation_field.selection_set = MagicMock()
        mutation_field.selection_set.selections = [success_fragment]
        info.field_nodes = [mutation_field]

        # Extract machine selections
        machine_result = _extract_entity_field_selections(
            info, "UpdateMachineLocationSuccess", "machine"
        )
        assert machine_result is not None
        assert set(machine_result["fields"]) == {"id", "name"}

        # Extract previousLocation selections
        prev_result = _extract_entity_field_selections(
            info, "UpdateMachineLocationSuccess", "previousLocation"
        )
        assert prev_result is not None
        assert set(prev_result["fields"]) == {"id"}

        # Extract newLocation selections
        new_result = _extract_entity_field_selections(
            info, "UpdateMachineLocationSuccess", "newLocation"
        )
        assert new_result is not None
        assert set(new_result["fields"]) == {"id", "name"}

    def test_typename_excluded_from_selections(self):
        """Test that __typename is excluded from field selections.

        __typename is a GraphQL introspection field that should not
        be included in entity field filtering.
        """
        info = MagicMock()

        # Entity selections including __typename
        entity_selections = [
            create_field_node("__typename"),
            create_field_node("id"),
            create_field_node("name"),
        ]
        location_field = create_field_node("location", entity_selections)

        success_fragment = create_inline_fragment(
            "CreateLocationSuccess", [location_field]
        )

        mutation_field = MagicMock(spec=FieldNode)
        mutation_field.selection_set = MagicMock()
        mutation_field.selection_set.selections = [success_fragment]
        info.field_nodes = [mutation_field]

        result = _extract_entity_field_selections(
            info, "CreateLocationSuccess", "location"
        )

        # __typename should be excluded
        assert result is not None
        assert "__typename" not in result["fields"]
        assert set(result["fields"]) == {"id", "name"}

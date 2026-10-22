"""Unit tests for entity field selection extraction from GraphQL queries.

These tests verify the entity_selection() function which
parses GraphQL selection sets to extract nested field selections for entity
objects in mutation responses.

Related to GitHub issue #525.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from graphql import (
    FieldNode,
    FragmentDefinitionNode,
    InlineFragmentNode,
    NamedTypeNode,
    NameNode,
    OperationDefinitionNode,
    SelectionSetNode,
    build_schema,
    parse,
)

import fraiseql
from fraiseql.mutations.mutation_decorator import _request_entity_type
from tests.unit.mutations.selection_document import entity_selection, selected_field_names


def create_field_node(name: str, selections: list | None = None) -> FieldNode:
    """Helper to create a FieldNode."""
    selection_set = None if selections is None else SelectionSetNode(selections=tuple(selections))
    return FieldNode(name=NameNode(value=name), selection_set=selection_set)


def create_inline_fragment(type_name: str, selections: list) -> InlineFragmentNode:
    """Helper to create an InlineFragmentNode."""
    return InlineFragmentNode(
        type_condition=NamedTypeNode(name=NameNode(value=type_name)),
        selection_set=SelectionSetNode(selections=tuple(selections)),
    )


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
        mutation_field = create_field_node("mutation", [success_fragment])

        info.field_nodes = [mutation_field]

        # Extract selections
        result = entity_selection(info, "CreateLocationSuccess", "location")

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
        success_fragment = create_inline_fragment("CreateLocationSuccess", [location_field])

        mutation_field = create_field_node("mutation", [success_fragment])
        info.field_nodes = [mutation_field]

        # Extract selections
        result = entity_selection(info, "CreateLocationSuccess", "location")

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

        success_fragment = create_inline_fragment("CreateLocationSuccess", [location_field])

        mutation_field = create_field_node("mutation", [success_fragment])
        info.field_nodes = [mutation_field]

        result = entity_selection(info, "CreateLocationSuccess", "location")

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
        success_fragment = create_inline_fragment("CreateLocationSuccess", success_selections)

        mutation_field = create_field_node("mutation", [success_fragment])
        info.field_nodes = [mutation_field]

        result = entity_selection(info, "CreateLocationSuccess", "location")

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

        success_fragment = create_inline_fragment("CreateLocationSuccess", [location_field])

        mutation_field = create_field_node("mutation", [success_fragment])
        info.field_nodes = [mutation_field]

        result = entity_selection(info, "CreateLocationSuccess", "location")

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
        error_fragment = create_inline_fragment("CreateLocationError", error_selections)

        mutation_field = create_field_node("mutation", [error_fragment])
        info.field_nodes = [mutation_field]

        result = entity_selection(info, "CreateLocationSuccess", "location")

        # Should return None when fragment type doesn't match
        assert result is None

    def test_no_field_nodes(self):
        """Test when info has no field nodes."""
        info = MagicMock()
        info.field_nodes = []

        result = entity_selection(info, "CreateLocationSuccess", "location")

        assert result is None

    def test_none_info(self):
        """Test when info is None."""
        result = entity_selection(None, "CreateLocationSuccess", "location")

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

        mutation_field = create_field_node("mutation", [success_fragment])
        info.field_nodes = [mutation_field]

        # Extract machine selections
        machine_result = entity_selection(info, "UpdateMachineLocationSuccess", "machine")
        assert machine_result is not None
        assert set(machine_result["fields"]) == {"id", "name"}

        # Extract previousLocation selections
        prev_result = entity_selection(info, "UpdateMachineLocationSuccess", "previousLocation")
        assert prev_result is not None
        assert set(prev_result["fields"]) == {"id"}

        # Extract newLocation selections
        new_result = entity_selection(info, "UpdateMachineLocationSuccess", "newLocation")
        assert new_result is not None
        assert set(new_result["fields"]) == {"id", "name"}

    def test_typename_kept_in_selections(self):
        """__typename stays in the field selections.

        The Rust filter doesn't look it up as a column: it keeps the data's
        __typename, or the one from __type. Keeping it means a selection of
        only __typename filters the object down to it.
        """
        info = MagicMock()

        # Entity selections including __typename
        entity_selections = [
            create_field_node("__typename"),
            create_field_node("id"),
            create_field_node("name"),
        ]
        location_field = create_field_node("location", entity_selections)

        success_fragment = create_inline_fragment("CreateLocationSuccess", [location_field])

        mutation_field = create_field_node("mutation", [success_fragment])
        info.field_nodes = [mutation_field]

        result = entity_selection(info, "CreateLocationSuccess", "location")

        assert result is not None
        assert result["fields"] == ["__typename", "id", "name"]


_TYPED_SCHEMA = build_schema("""
    interface Node { id: ID! }
    type Address { city: String }
    type Person implements Node { id: ID! name: String }
    type Org implements Node { id: ID! title: String }
    union Owner = Person | Org
    type Location implements Node {
        id: ID!
        name: String
        address: Address
        owner: Node
        ownerU: Owner
        manager: Person
    }
    type CreateLocationSuccess {
        message: String
        location: Location
        mainLocation: Location
        node: Node
    }
    type Query { ping: String }
    type Mutation { createLocation: CreateLocationSuccess }
""")


def _typed_info(query: str) -> SimpleNamespace:
    """An info-like object for a parsed mutation and its fragments, against _TYPED_SCHEMA."""
    definitions = parse(query).definitions
    operation = definitions[0]
    assert isinstance(operation, OperationDefinitionNode)
    fragments = {d.name.value: d for d in definitions if isinstance(d, FragmentDefinitionNode)}
    return SimpleNamespace(
        schema=_TYPED_SCHEMA,
        field_nodes=list(operation.selection_set.selections),
        fragments=fragments,
    )


class TestTypeNameFromSchema:
    """__type tells Rust which __typename to add; only a concrete type has one."""

    def test_object_type_gets_its_name(self):
        info = _typed_info("""
            mutation { createLocation { ... on CreateLocationSuccess {
                location { id address { city } }
            } } }
        """)

        result = entity_selection(info, "CreateLocationSuccess", "location")

        assert result is not None
        assert result["__type"] == "Location"
        assert result["address"]["__type"] == "Address"

    def test_nested_interface_field_gets_no_type_name(self):
        """An object behind an interface is one of several types; its data says which."""
        info = _typed_info("""
            mutation { createLocation { ... on CreateLocationSuccess {
                location { id owner { id } }
            } } }
        """)

        result = entity_selection(info, "CreateLocationSuccess", "location")

        assert result is not None
        assert result["owner"] == {"fields": ["id"]}

    def test_interface_entity_gets_no_type_name(self):
        info = _typed_info("""
            mutation { createLocation { ... on CreateLocationSuccess { node { id } } } }
        """)

        result = entity_selection(info, "CreateLocationSuccess", "node")

        assert result == {"fields": ["id"]}


class TestNamedFragmentSpreads:
    """A spread selects its fragment's fields; it is not a field named after the fragment."""

    def test_named_fragment_on_entity_expands(self):
        info = _typed_info("""
            mutation { createLocation { ... on CreateLocationSuccess {
                location { ...LocFields }
            } } }
            fragment LocFields on Location { id name }
        """)

        result = entity_selection(info, "CreateLocationSuccess", "location")

        assert result == {"fields": ["id", "name"], "__type": "Location"}

    def test_named_fragment_inside_success_fragment(self):
        info = _typed_info("""
            mutation { createLocation { ... on CreateLocationSuccess { ...SF } } }
            fragment SF on CreateLocationSuccess { message location { id } }
        """)

        result = entity_selection(info, "CreateLocationSuccess", "location")
        success_fields = selected_field_names(info, "CreateLocationSuccess")

        assert result == {"fields": ["id"], "__type": "Location"}
        assert success_fields is not None
        assert sorted(success_fields) == ["location", "message"]

    def test_named_fragment_under_nested_concrete_field(self):
        info = _typed_info("""
            mutation { createLocation { ... on CreateLocationSuccess {
                location { id manager { ...PersonFields } }
            } } }
            fragment PersonFields on Person { name }
        """)

        result = entity_selection(info, "CreateLocationSuccess", "location")

        assert result is not None
        assert result["manager"] == {"fields": ["name"], "__type": "Person"}

    def test_spread_and_field_merge(self):
        """The same field selected directly and through a spread gives one entry."""
        info = _typed_info("""
            mutation { createLocation { ... on CreateLocationSuccess {
                location { id address { city } ...LocFields }
            } } }
            fragment LocFields on Location { id name address { city } }
        """)

        result = entity_selection(info, "CreateLocationSuccess", "location")

        assert result is not None
        assert result["fields"] == ["id", "address", "name"]
        assert result["address"] == {"fields": ["city"], "__type": "Address"}

    def test_fragment_on_implemented_interface_applies(self):
        info = _typed_info("""
            mutation { createLocation { ... on CreateLocationSuccess {
                location { ...NodeFields name }
            } } }
            fragment NodeFields on Node { id }
        """)

        result = entity_selection(info, "CreateLocationSuccess", "location")

        assert result is not None
        assert result["fields"] == ["id", "name"]


class TestFragmentsUnderAbstractFields:
    """Under an interface or union field, every fragment's fields are selected.

    The object's type is only known from its data, so the selection is the union of
    the fields of every fragment, whatever its type condition.
    """

    def test_inline_fragment_under_interface_field(self):
        info = _typed_info("""
            mutation { createLocation { ... on CreateLocationSuccess {
                location { id owner { ... on Person { name } } }
            } } }
        """)

        result = entity_selection(info, "CreateLocationSuccess", "location")

        assert result is not None
        assert result["owner"] == {"fields": ["name"]}

    def test_field_and_inline_fragment_under_interface_field(self):
        info = _typed_info("""
            mutation { createLocation { ... on CreateLocationSuccess {
                location { owner { id ... on Person { name } } }
            } } }
        """)

        result = entity_selection(info, "CreateLocationSuccess", "location")

        assert result is not None
        assert result["owner"] == {"fields": ["id", "name"]}

    def test_fragments_for_each_union_member(self):
        info = _typed_info("""
            mutation { createLocation { ... on CreateLocationSuccess {
                location { ownerU { __typename ... on Person { name } ... on Org { title } } }
            } } }
        """)

        result = entity_selection(info, "CreateLocationSuccess", "location")

        assert result is not None
        assert result["ownerU"] == {"fields": ["__typename", "name", "title"]}

    def test_named_fragment_under_interface_field(self):
        info = _typed_info("""
            mutation { createLocation { ... on CreateLocationSuccess {
                location { owner { ...PersonFields } }
            } } }
            fragment PersonFields on Person { name }
        """)

        result = entity_selection(info, "CreateLocationSuccess", "location")

        assert result is not None
        assert result["owner"] == {"fields": ["name"]}

    def test_typename_only(self):
        info = _typed_info("""
            mutation { createLocation { ... on CreateLocationSuccess {
                location { owner { __typename } }
            } } }
        """)

        result = entity_selection(info, "CreateLocationSuccess", "location")

        assert result is not None
        assert result["owner"] == {"fields": ["__typename"]}


class TestRequestEntityType:
    """The entity's __typename sent to Rust: the entity field's concrete schema type."""

    _QUERY = "mutation { createLocation { ... on CreateLocationSuccess { location { id } } } }"

    def test_concrete_entity_field(self):
        info = _typed_info(self._QUERY)

        assert _request_entity_type(info, "CreateLocationSuccess", "location", None) == "Location"

    def test_snake_case_entity_field_name(self):
        info = _typed_info(self._QUERY)

        name = _request_entity_type(info, "CreateLocationSuccess", "main_location", None)

        assert name == "Location"

    def test_interface_entity_field_gets_none(self):
        """Never an interface's name, even if the annotation would give one."""
        info = _typed_info(self._QUERY)

        assert _request_entity_type(info, "CreateLocationSuccess", "node", "Node") is None

    def test_annotation_without_schema(self):
        info = SimpleNamespace(schema=None, field_nodes=[], fragments={})

        name = _request_entity_type(info, "CreateLocationSuccess", "location", "Location")

        assert name == "Location"


@pytest.mark.usefixtures("clear_registry")
def test_interface_annotation_gives_no_entity_type():
    """An entity field annotated with an interface has no type name to give."""

    @fraiseql.interface
    class Node:
        id: str

    @fraiseql.type(implements=[Node])
    class Place:
        id: str

    @fraiseql.input
    class MovePlaceInput:
        id: str

    @fraiseql.success
    class MovePlaceSuccess:
        message: str
        node: Node

    @fraiseql.error
    class MovePlaceError:
        message: str

    @fraiseql.mutation
    class MovePlace:
        input: MovePlaceInput
        success: MovePlaceSuccess
        error: MovePlaceError

    definition = MovePlace.__fraiseql_mutation__
    assert definition.entity_field_name == "node"
    assert definition.entity_type is None

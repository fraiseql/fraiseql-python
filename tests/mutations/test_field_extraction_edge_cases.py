"""Test edge cases in field extraction."""

from graphql import parse
from tests.unit.mutations.selection_document import selected_field_names


class MockInfo:
    """Mock GraphQLResolveInfo for testing."""

    def __init__(self, field_nodes):
        self.field_nodes = field_nodes


def test_fragment_type_name_mismatch():
    """Test when fragment type doesn't match expected type."""
    query_string = """
    mutation {
        createMachine(input: {name: "test"}) {
            ... on CreateMachineSuccess {
                status
                message
            }
        }
    }
    """
    document = parse(query_string)
    mutation_field = document.definitions[0].selection_set.selections[0]
    mock_info = MockInfo([mutation_field])

    # Query has "... on CreateMachineSuccess"
    # But we're asking for "CreateMachineError"
    # Expected: Returns None (no match)
    result = selected_field_names(mock_info, "CreateMachineError")
    assert result is None, "Should return None when type doesn't match"


def test_named_fragments():
    """Test behavior with named fragments (supported as of Phase 0 fix)."""
    query_string = """
    fragment MachineFields on CreateMachineSuccess {
        status
        machine {
            id
        }
    }

    mutation {
        createMachine(input: {name: "test"}) {
            ...MachineFields
        }
    }
    """
    document = parse(query_string)
    mutation_field = document.definitions[1].selection_set.selections[0]

    # Create mock info with fragments
    class MockInfoWithFragments:
        def __init__(self, field_nodes, fragments):
            self.field_nodes = field_nodes
            self.fragments = fragments

    # Extract fragment definitions from document
    fragments = {
        defn.name.value: defn for defn in document.definitions if hasattr(defn, "type_condition")
    }
    mock_info = MockInfoWithFragments([mutation_field], fragments)

    # Named fragments are now supported
    # Expected: Returns fields from the named fragment
    result = selected_field_names(mock_info, "CreateMachineSuccess")
    assert result is not None, "Named fragments are now supported"
    assert "status" in result
    assert "machine" in result
    assert len(result) == 2


def test_multiple_fragments_same_type():
    """Test when multiple inline fragments match the same type."""
    query_string = """
    mutation {
        createMachine(input: {name: "test"}) {
            ... on CreateMachineSuccess {
                status
            }
            ... on CreateMachineSuccess {
                message
                machine { id }
            }
        }
    }
    """
    document = parse(query_string)
    mutation_field = document.definitions[0].selection_set.selections[0]
    mock_info = MockInfo([mutation_field])

    # Should collect fields from all matching fragments
    result = selected_field_names(mock_info, "CreateMachineSuccess")
    assert result is not None
    assert "status" in result
    assert "message" in result
    assert "machine" in result
    assert len(result) == 3


def test_no_inline_fragment():
    """Fields selected directly on the field are its selection (no fragment needed)."""
    query_string = """
    mutation {
        createMachine(input: {name: "test"}) {
            status
            machine {
                id
            }
        }
    }
    """
    document = parse(query_string)
    mutation_field = document.definitions[0].selection_set.selections[0]
    mock_info = MockInfo([mutation_field])

    # No "... on CreateMachineSuccess" fragment: the field's type is the success type
    # itself. Before #581 this meant "return every field"; it now selects these two.
    result = selected_field_names(mock_info, "CreateMachineSuccess")
    assert sorted(result) == ["machine", "status"]


def test_empty_fragment():
    """Test when fragment has no fields selected."""
    query_string = """
    mutation {
        createMachine(input: {name: "test"}) {
            ... on CreateMachineSuccess {
                __typename
            }
        }
    }
    """
    document = parse(query_string)
    mutation_field = document.definitions[0].selection_set.selections[0]
    mock_info = MockInfo([mutation_field])

    # Only __typename is selected (which is skipped)
    # Expected: Returns None (no real fields selected)
    result = selected_field_names(mock_info, "CreateMachineSuccess")
    assert result is None, "Should return None when only __typename selected"


def test_typename_skipped():
    """Test that __typename is not included in extracted fields."""
    query_string = """
    mutation {
        createMachine(input: {name: "test"}) {
            ... on CreateMachineSuccess {
                __typename
                status
            }
        }
    }
    """
    document = parse(query_string)
    mutation_field = document.definitions[0].selection_set.selections[0]
    mock_info = MockInfo([mutation_field])

    # __typename should be automatically filtered out
    result = selected_field_names(mock_info, "CreateMachineSuccess")
    assert result is not None
    assert "__typename" not in result
    assert "status" in result
    assert len(result) == 1


def test_no_info_or_field_nodes():
    """Test when info is None or has no field_nodes."""
    # Test with None info
    result = selected_field_names(None, "CreateMachineSuccess")
    assert result is None

    # Test with no field_nodes
    mock_info = MockInfo([])
    result = selected_field_names(mock_info, "CreateMachineSuccess")
    assert result is None

    # Test with info that has field_nodes = None
    class MockInfoNoNodes:
        field_nodes = None

    mock_info_no_nodes = MockInfoNoNodes()
    result = selected_field_names(mock_info_no_nodes, "CreateMachineSuccess")
    assert result is None


def test_field_node_no_selection_set():
    """Test when field_node has no selection_set."""
    query_string = """
    mutation {
        simpleField
    }
    """
    document = parse(query_string)
    mutation_field = document.definitions[0].selection_set.selections[0]
    mock_info = MockInfo([mutation_field])

    # Field has no selection_set (leaf field)
    result = selected_field_names(mock_info, "CreateMachineSuccess")
    assert result is None


def test_union_with_both_success_and_error():
    """Test extracting fields from a union with both success and error types."""
    query_string = """
    mutation {
        createMachine(input: {name: "test"}) {
            ... on CreateMachineSuccess {
                status
                message
                machine { id }
            }
            ... on CreateMachineError {
                status
                message
                errors
            }
        }
    }
    """
    document = parse(query_string)
    mutation_field = document.definitions[0].selection_set.selections[0]
    mock_info = MockInfo([mutation_field])

    # Extract for Success type
    success_fields = selected_field_names(mock_info, "CreateMachineSuccess")
    assert success_fields is not None
    assert "status" in success_fields
    assert "message" in success_fields
    assert "machine" in success_fields
    assert "errors" not in success_fields

    # Extract for Error type
    error_fields = selected_field_names(mock_info, "CreateMachineError")
    assert error_fields is not None
    assert "status" in error_fields
    assert "message" in error_fields
    assert "errors" in error_fields
    assert "machine" not in error_fields


def test_nested_fields_only_top_level_extracted():
    """Test that only top-level fields are extracted, not nested fields."""
    query_string = """
    mutation {
        createMachine(input: {name: "test"}) {
            ... on CreateMachineSuccess {
                status
                machine {
                    id
                    name
                    configuration {
                        setting1
                        setting2
                    }
                }
            }
        }
    }
    """
    document = parse(query_string)
    mutation_field = document.definitions[0].selection_set.selections[0]
    mock_info = MockInfo([mutation_field])

    # Should extract only top-level fields: status, machine
    # Not nested fields like id, name, configuration
    result = selected_field_names(mock_info, "CreateMachineSuccess")
    assert result is not None
    assert "status" in result
    assert "machine" in result
    # Nested fields should NOT be included
    assert "id" not in result
    assert "name" not in result
    assert "configuration" not in result
    assert len(result) == 2

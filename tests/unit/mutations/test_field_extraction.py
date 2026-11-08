"""Test field extraction from GraphQL info object."""

from tests.unit.mutations.selection_document import info_for, selected_field_names


def test_extract_mutation_selected_fields_from_fragment():
    """Fields of an inline fragment on the type, without __typename."""
    info = info_for(
        "mutation { createMachine { ... on CreateMachineSuccess"
        " { __typename status machine { id } } } }"
    )

    assert set(selected_field_names(info, "CreateMachineSuccess")) == {"status", "machine"}


def test_extract_mutation_selected_fields_no_matching_fragment():
    """A fragment on another type selects nothing on this one."""
    info = info_for("mutation { createMachine { ... on OtherType { status } } }")

    assert selected_field_names(info, "CreateMachineSuccess") is None


def test_extract_mutation_selected_fields_none_info():
    """Without info, nothing is selected."""
    assert selected_field_names(None, "CreateMachineSuccess") is None

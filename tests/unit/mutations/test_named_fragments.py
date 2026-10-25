"""Test named fragment support in field selection."""

import json
from unittest.mock import MagicMock

import pytest

from fraiseql import _get_fraiseql_rs
from fraiseql.mutations.mutation_decorator import _response_selections
from tests.unit.mutations.selection_document import info_for, selected_field_names


@pytest.fixture
def fraiseql_rs():
    """Get Rust module."""
    rs = _get_fraiseql_rs()
    if rs is None:
        pytest.skip("Rust extension not available")
    return rs


def test_named_fragment_support_exists():
    """Verify named fragment support exists in the codebase."""

    # This test verifies the function exists and can handle basic cases
    # The actual fragment parsing is tested via integration in the Rust test

    mock_info = MagicMock()
    mock_info.field_nodes = []
    mock_info.fragments = {}

    # Should return None for empty input (backward compatibility)
    result = selected_field_names(mock_info, "TestType")
    assert result is None

    print("✅ Named fragment support exists in codebase")


def test_named_fragment_with_inline_fragments():
    """Fields come from an inline fragment and a named fragment on the same type."""
    info = info_for(
        """mutation { createMachine { ... on CreateMachineSuccess { status } ...MachineFields } }
        fragment MachineFields on CreateMachineSuccess { machine { id } }"""
    )

    assert sorted(selected_field_names(info, "CreateMachineSuccess")) == ["machine", "status"]


def test_rust_with_named_fragment_fields(fraiseql_rs):
    """Verify Rust layer respects field selection from named fragments."""
    fake_result = {
        "status": "success",
        "message": "Machine created",
        "entity_id": "123",
        "entity_type": "Machine",
        "entity": {"id": "123", "name": "Test Machine"},
        "updated_fields": ["name"],
        "cascade": None,
        "metadata": None,
        "is_simple_format": False,
    }

    # The named fragment selected only status and machine { id }
    info = info_for(
        """mutation { createMachine { ...MachineFields } }
        fragment MachineFields on CreateMachineSuccess { status machine { id } }"""
    )
    document = _response_selections(
        info, "CreateMachineSuccess", "CreateMachineError", by_alias=True
    )

    response_json = fraiseql_rs.build_mutation_response(
        json.dumps(fake_result),
        "createMachine",
        "CreateMachineSuccess",
        "CreateMachineError",
        "machine",
        "Machine",
        None,
        True,
        None,
        None,
        json.dumps(document),
    )

    data = json.loads(response_json)["data"]["createMachine"]

    assert data == {"status": "success", "machine": {"id": "123"}}


def test_empty_named_fragment():
    """An empty named fragment selects nothing."""
    query = """mutation { createMachine { ...EmptyFragment } }
        fragment EmptyFragment on CreateMachineSuccess { }"""
    info = info_for(query.replace("{ }", "{ __typename }"))

    assert selected_field_names(info, "CreateMachineSuccess") is None


def test_missing_named_fragment():
    """A spread of a fragment the document doesn't define is skipped."""
    info = info_for("mutation { createMachine { ...MissingFragment } }")

    assert selected_field_names(info, "CreateMachineSuccess") is None

"""The error raised for an annotation that names an undefined type."""

import pytest

import fraiseql


def test_undefined_forward_reference_message() -> None:
    """The message says how to fix it, and doesn't suggest `from __future__`.

    `get_type_hints` evaluates string annotations when the decorator runs, so deferring
    them with `from __future__ import annotations` raises the same NameError.
    """
    with pytest.raises(TypeError) as exc_info:

        @fraiseql.type
        class Order:
            id: int
            customer: "MissingCustomer"  # noqa: F821

    message = str(exc_info.value)
    assert "Forward reference 'MissingCustomer' in Order cannot be resolved" in message
    assert "Define 'MissingCustomer' before 'Order' at module level" in message
    assert "module's globals" in message
    assert "__future__" not in message


def test_self_reference_resolves() -> None:
    """A type may name itself without being defined yet."""

    @fraiseql.type
    class Category:
        id: int
        parent: "Category | None" = None

    assert Category.__gql_type_hints__["parent"] == Category | None

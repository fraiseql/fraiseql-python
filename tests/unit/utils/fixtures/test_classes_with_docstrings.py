"""Test fixture classes with attribute-level docstrings for testing extraction.

These classes must be in a separate file so that inspect.getsource() can find their source code.
"""

from dataclasses import dataclass
from uuid import UUID

from fraiseql import fraise_type


@fraise_type
@dataclass
class UserWithDocstrings:
    """A user in the system."""

    id: UUID
    """Unique user identifier."""

    name: str
    """User's full name."""

    email: str
    """User's email address."""


@fraise_type
@dataclass
class ProductWithDocstrings:
    """A product in the catalog."""

    id: UUID
    """Product identifier."""

    name: str
    """Product name."""

    price: float = 0.0
    """Product price in USD."""

    status: str = "active"
    """Product availability status."""


@fraise_type
@dataclass
class OrderWithMultilineDocstrings:
    """An order in the system."""

    id: UUID
    """
    Unique order identifier.
    Generated automatically on creation.
    """

    description: str
    """
    Detailed description of the order.
    Can span multiple lines.
    """


@fraise_type
@dataclass
class MixedDocumentation:
    """A type with mixed documentation."""

    id: UUID
    """Has docstring."""

    name: str
    # No docstring

    email: str
    """Has docstring."""

    age: int
    # No docstring


@fraise_type
@dataclass
class AllQuoteTypes:
    """Class with all quote types."""

    single: str
    "Single quotes docstring."

    double: str
    "Double quotes docstring."

    triple_single: str
    """Triple single quotes docstring."""

    triple_double: str
    """Triple double quotes docstring."""


@fraise_type
@dataclass
class PriorityTest:
    """Test priority of description sources.

    Fields:
        name: This should be overridden
        email: This stays (no attribute docstring)
    """

    name: str
    """User's full name (from attribute docstring)."""

    email: str

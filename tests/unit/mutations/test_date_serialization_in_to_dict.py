"""Test date serialization in FraiseQL input objects' to_dict method."""

import datetime as dt

import fraiseql
from fraiseql.types.definitions import UNSET


@fraiseql.input
class CreateOrderInput:
    """Input with date field for testing serialization."""

    client_order_id: str
    order_date: dt.date
    delivery_date: dt.date | None = UNSET


class TestDateSerializationInToDict:
    """Test date serialization in to_dict method."""

    def test_date_field_serialized_to_iso_string(self) -> None:
        """Date fields should be serialized to ISO strings in to_dict method."""
        order_input = CreateOrderInput(client_order_id="ORDER2025", order_date=dt.date(2025, 2, 15))

        result = order_input.to_dict()

        assert result["client_order_id"] == "ORDER2025"
        assert result["order_date"] == "2025-02-15"  # Date serialized to ISO string
        assert "delivery_date" not in result  # UNSET field excluded

    def test_optional_date_field_serialized_when_set(self) -> None:
        """Optional date fields should be serialized when set."""
        order_input = CreateOrderInput(
            client_order_id="ORDER2025",
            order_date=dt.date(2025, 2, 15),
            delivery_date=dt.date(2025, 3, 1),
        )

        result = order_input.to_dict()

        assert result["client_order_id"] == "ORDER2025"
        assert result["order_date"] == "2025-02-15"
        assert result["delivery_date"] == "2025-03-01"  # Set date serialized

    def test_json_method_also_serializes_dates(self) -> None:
        """__json__ method should also serialize dates correctly."""
        order_input = CreateOrderInput(client_order_id="ORDER2025", order_date=dt.date(2025, 2, 15))

        result = order_input.__json__()

        assert result["client_order_id"] == "ORDER2025"
        assert result["order_date"] == "2025-02-15"

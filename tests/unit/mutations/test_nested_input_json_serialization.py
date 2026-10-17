"""Test for JSON serialization fix with nested FraiseQL input objects.

This test demonstrates that the v0.7.14 bug report issue is now resolved
in v0.7.15 with built-in JSON serialization support for FraiseQL input objects.
"""

import json

import pytest

import fraiseql
from fraiseql.fastapi.json_encoder import FraiseQLJSONEncoder
from fraiseql.types.definitions import UNSET


@fraiseql.input
class CreateNestedPublicAddressInput:
    """Nested input for creating public address (used within other inputs)."""

    street_number: str | None = UNSET
    street_name: str
    postal_code: str


@fraiseql.input
class CreateLocationInput:
    """Input that contains nested address input."""

    name: str
    address: CreateNestedPublicAddressInput | None = UNSET


class TestNestedInputJSONSerialization:
    """Test JSON serialization of nested FraiseQL input objects."""

    def test_nested_fraiseql_input_now_works_with_fraiseql_encoder(self) -> None:
        """🟢 GREEN: Nested FraiseQL input objects now work with FraiseQLJSONEncoder."""
        # Create nested input object
        nested_address = CreateNestedPublicAddressInput(
            street_number="456", street_name="Oak Ave", postal_code="67890"
        )

        location_input = CreateLocationInput(name="Test Location", address=nested_address)

        # This should now work with FraiseQLJSONEncoder
        result = json.dumps(location_input, cls=FraiseQLJSONEncoder)
        assert isinstance(result, str)

        # Parse to verify the structure
        parsed = json.loads(result)
        assert parsed["name"] == "Test Location"
        assert parsed["address"]["street_number"] == "456"

    def test_nested_address_object_now_works_with_fraiseql_encoder(self) -> None:
        """🟢 GREEN: Individual FraiseQL input objects now work with FraiseQLJSONEncoder."""
        nested_address = CreateNestedPublicAddressInput(
            street_number="456", street_name="Oak Ave", postal_code="67890"
        )

        # This should now work with FraiseQLJSONEncoder
        result = json.dumps(nested_address, cls=FraiseQLJSONEncoder)
        assert isinstance(result, str)

        parsed = json.loads(result)
        assert parsed["street_number"] == "456"
        assert parsed["street_name"] == "Oak Ave"
        assert parsed["postal_code"] == "67890"

    def test_dict_with_nested_fraiseql_object_now_works_with_fraiseql_encoder(self) -> None:
        """🟢 GREEN: Dict containing FraiseQL objects now works with FraiseQLJSONEncoder."""
        nested_address = CreateNestedPublicAddressInput(
            street_number="456", street_name="Oak Ave", postal_code="67890"
        )

        data = {"name": "Test Location", "address": nested_address}

        # This should now work with FraiseQLJSONEncoder
        result = json.dumps(data, cls=FraiseQLJSONEncoder)
        assert isinstance(result, str)

        parsed = json.loads(result)
        assert parsed["name"] == "Test Location"
        assert parsed["address"]["street_number"] == "456"

    def test_unset_value_now_works_with_fraiseql_encoder(self) -> None:
        """🟢 GREEN: UNSET values now work with FraiseQLJSONEncoder."""
        # This should now work with FraiseQLJSONEncoder
        result = json.dumps(UNSET, cls=FraiseQLJSONEncoder)
        assert result == "null"

    def test_nested_object_with_unset_fields_now_works_with_fraiseql_encoder(self) -> None:
        """🟢 GREEN: FraiseQL objects with UNSET fields now work with FraiseQLJSONEncoder."""
        # Create object with UNSET field
        nested_address = CreateNestedPublicAddressInput(
            street_name="Oak Ave",
            postal_code="67890",
            # street_number is UNSET by default
        )

        # Verify it has UNSET field
        assert nested_address.street_number is UNSET

        # This should now work with FraiseQLJSONEncoder
        result = json.dumps(nested_address, cls=FraiseQLJSONEncoder)
        assert isinstance(result, str)

        parsed = json.loads(result)
        assert parsed["street_name"] == "Oak Ave"
        assert parsed["postal_code"] == "67890"
        assert "street_number" not in parsed  # UNSET fields are excluded

    def test_standard_json_still_fails_as_expected(self) -> None:
        """Standard JSON serialization still fails but that's expected behavior."""
        nested_address = CreateNestedPublicAddressInput(
            street_number="456", street_name="Oak Ave", postal_code="67890"
        )

        # Standard JSON.dumps still fails, which is expected - users should use FraiseQLJSONEncoder
        with pytest.raises(
            TypeError,
            match="Object of type CreateNestedPublicAddressInput is not JSON serializable",
        ):
            json.dumps(nested_address)

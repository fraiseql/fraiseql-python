"""Custom JSON encoder for FraiseQL FastAPI responses."""

import datetime as dt
import decimal
import ipaddress
import json
import uuid
from typing import Any

from fastapi.responses import JSONResponse

from fraiseql.types.definitions import UNSET


def clean_unset_values(obj: Any) -> Any:
    """Recursively clean UNSET values from an object, converting them to None.

    This is useful for cleaning data structures before they get serialized
    by standard JSON encoders that don't handle UNSET values.

    Args:
        obj: The object to clean (dict, list, or primitive)

    Returns:
        A copy of the object with all UNSET values converted to None
    """
    if obj is UNSET:
        return None
    if isinstance(obj, dict):
        return {key: clean_unset_values(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [clean_unset_values(item) for item in obj]
    return obj


class FraiseQLJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles FraiseQL and PostgreSQL types."""

    def default(self, obj: Any) -> Any:
        """Encode non-standard types to JSON-serializable format."""
        # Handle UNSET (convert to None for JSON serialization)
        if obj is UNSET:
            return None

        # Handle FraiseQL types (classes decorated with @fraiseql.type)
        if hasattr(obj, "__fraiseql_definition__"):
            # Check if the object has a custom __json__ method and use it
            if hasattr(obj, "__json__") and callable(obj.__json__):
                return obj.__json__()

            # Convert FraiseQL type instance to dictionary using its __dict__
            # This allows proper JSON serialization of @fraiseql.type decorated classes
            obj_dict = {}
            for attr_name in dir(obj):
                # Skip private attributes, methods, and special FraiseQL attributes
                # But include __cascade__ for GraphQL cascade functionality
                if (
                    (not attr_name.startswith("_") or attr_name == "__cascade__")
                    and not attr_name.startswith("__gql_")
                    and not (attr_name.startswith("__fraiseql_") and attr_name != "__cascade__")
                    and not callable(getattr(obj, attr_name, None))
                ):
                    value = getattr(obj, attr_name, None)

                    # Skip descriptor instances (like LazyWhereInputProperty, LazyOrderByProperty)
                    # When accessed on an instance, descriptors might return themselves
                    if value is not None and hasattr(value, "__get__"):
                        # This is a descriptor instance, skip it
                        continue

                    if value is not None:
                        # Rename __cascade__ to cascade in the output
                        key = "cascade" if attr_name == "__cascade__" else attr_name
                        obj_dict[key] = value
            return obj_dict

        # Handle date and datetime
        if isinstance(obj, dt.datetime):
            return obj.isoformat()
        if isinstance(obj, dt.date):
            return obj.isoformat()
        if isinstance(obj, dt.time):
            return obj.isoformat()

        # Handle UUID
        if isinstance(obj, uuid.UUID):
            return str(obj)

        # A string keeps every digit, as the Decimal scalar does; a float rounds
        if isinstance(obj, decimal.Decimal):
            return str(obj)

        # Handle IP addresses
        if isinstance(obj, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
            return str(obj)

        # Handle bytes
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")

        # Handle Python Enums (convert to their value)
        if hasattr(obj, "__class__") and hasattr(obj.__class__, "__bases__"):
            # Check if it's an Enum
            import enum

            if isinstance(obj, enum.Enum):
                return obj.value

        # Handle dataclasses
        if hasattr(obj, "__dataclass_fields__"):
            # Convert dataclass to dictionary
            import dataclasses

            return dataclasses.asdict(obj)

        # Handle sets (convert to list)
        if isinstance(obj, set):
            return list(obj)

        # Handle tuples (convert to list)
        if isinstance(obj, tuple):
            return list(obj)

        # Handle special float values that might break JSON
        if isinstance(obj, float):
            import math

            if math.isnan(obj):
                return None  # Convert NaN to null
            if math.isinf(obj):
                return None  # Convert infinity to null for JSON safety
            # Regular floats pass through normally

        # Fall back to default
        return super().default(obj)


class FraiseQLJSONResponse(JSONResponse):
    """Custom JSON response that uses FraiseQLJSONEncoder."""

    def render(self, content: Any) -> bytes:
        """Render content using FraiseQLJSONEncoder."""
        return json.dumps(
            content,
            cls=FraiseQLJSONEncoder,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")

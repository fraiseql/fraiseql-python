"""Custom Scalar WHERE Filter Tests

These tests verify that custom scalar types can be used in WHERE clause
filtering. The filter generator should create scalar-specific filter types
(e.g., CIDRFilter, CUSIPFilter) with standard operators (eq, ne, in, etc.)
that accept the scalar type instead of defaulting to String.

Expected behavior:
1. Filter type generation: CIDRFilter for CIDRScalar fields
2. Operator support: eq, ne, in, notIn, contains, startsWith, endsWith
3. Type safety: Operators accept scalar type, not String
4. Caching: Same filter type reused across fields
5. GraphQL query: WHERE clause works with custom scalar variables
"""

from typing import Union, get_args, get_origin

from fraiseql import fraise_type
from fraiseql.sql.graphql_where_generator import create_graphql_where_input
from fraiseql.types.scalars import CIDRScalar, ColorScalar, CUSIPScalar


def test_custom_scalar_filter_is_generated():
    """Filter generator should create ScalarNameFilter for custom scalars."""

    @fraise_type
    class TestType:
        id: int
        ip_network: CIDRScalar

    where_input = create_graphql_where_input(TestType)

    # Should generate TestTypeWhereInput
    assert where_input is not None
    assert where_input.__name__ == "TestTypeWhereInput"

    # Should have ip_network field (snake_case, not camelCase)
    assert "ip_network" in where_input.__annotations__

    # Field should be a CIDRFilter, not StringFilter
    # For now, this will fail because custom scalars default to StringFilter
    ip_filter_type = where_input.__annotations__["ip_network"]
    # Remove Optional wrapper for comparison
    from typing import get_args, get_origin

    if get_origin(ip_filter_type) is Union:
        args = get_args(ip_filter_type)
        non_none_args = [arg for arg in args if arg is not type(None)]
        ip_filter_type = non_none_args[0] if non_none_args else ip_filter_type

    # CIDRScalar now maps to NetworkAddressFilter for full network operator support
    assert ip_filter_type.__name__ == "NetworkAddressFilter"


def test_custom_scalar_filter_has_standard_operators():
    """Custom scalar filters should have eq, ne, in, notIn, etc."""

    @fraise_type
    class TestType:
        cusip: CUSIPScalar

    where_input = create_graphql_where_input(TestType)
    cusip_filter_type = where_input.__annotations__["cusip"]

    # Remove Optional wrapper
    if get_origin(cusip_filter_type) is Union:
        args = get_args(cusip_filter_type)
        non_none_args = [arg for arg in args if arg is not type(None)]
        cusip_filter_type = non_none_args[0] if non_none_args else cusip_filter_type

    # Should be CUSIPFilter, not StringFilter
    assert cusip_filter_type.__name__ == "CUSIPFilter"


def test_custom_scalar_filter_uses_scalar_type():
    """Filter operators should use the scalar type, not String."""

    @fraise_type
    class TestType:
        color: ColorScalar

    where_input = create_graphql_where_input(TestType)
    color_filter_type = where_input.__annotations__["color"]

    # Remove Optional wrapper
    if get_origin(color_filter_type) is Union:
        args = get_args(color_filter_type)
        non_none_args = [arg for arg in args if arg is not type(None)]
        color_filter_type = non_none_args[0] if non_none_args else color_filter_type

    # Should be ColorFilter, not StringFilter
    assert color_filter_type.__name__ == "ColorFilter"


def test_filter_type_is_cached():
    """Same scalar type should reuse the same filter type instance."""

    @fraise_type
    class TypeA:
        cusip1: CUSIPScalar
        cusip2: CUSIPScalar

    @fraise_type
    class TypeB:
        cusip: CUSIPScalar

    where_a = create_graphql_where_input(TypeA)
    where_b = create_graphql_where_input(TypeB)

    # Both should use the SAME CUSIPFilter instance (cached)
    cusip_filter_a1 = where_a.__annotations__["cusip1"]
    cusip_filter_a2 = where_a.__annotations__["cusip2"]
    cusip_filter_b = where_b.__annotations__["cusip"]

    # Remove Optional wrappers for comparison
    def unwrap_optional(filter_type):
        if get_origin(filter_type) is Union:
            args = get_args(filter_type)
            non_none_args = [arg for arg in args if arg is not type(None)]
            return non_none_args[0] if non_none_args else filter_type
        return filter_type

    cusip_filter_a1 = unwrap_optional(cusip_filter_a1)
    cusip_filter_a2 = unwrap_optional(cusip_filter_a2)
    cusip_filter_b = unwrap_optional(cusip_filter_b)

    # For now this will fail because they all default to StringFilter
    # But when implemented, they should be the same CUSIPFilter instance
    assert cusip_filter_a1 is cusip_filter_a2
    assert cusip_filter_a1 is cusip_filter_b


def test_nullable_custom_scalar_filter():
    """Nullable scalar fields should still get proper filters."""
    from typing import Optional

    @fraise_type
    class TestType:
        optional_cusip: Optional[CUSIPScalar]

    where_input = create_graphql_where_input(TestType)

    # Should still have the filter
    assert "optional_cusip" in where_input.__annotations__

    # Filter type should still be CUSIPFilter
    cusip_filter_type = where_input.__annotations__["optional_cusip"]
    # Remove Optional wrapper for comparison
    if get_origin(cusip_filter_type) is Union:
        args = get_args(cusip_filter_type)
        non_none_args = [arg for arg in args if arg is not type(None)]
        cusip_filter_type = non_none_args[0] if non_none_args else cusip_filter_type

    # This should be CUSIPFilter but currently defaults to StringFilter
    assert cusip_filter_type.__name__ == "CUSIPFilter"


def test_list_of_custom_scalars():
    """List fields with custom scalars should work."""

    @fraise_type
    class TestType:
        tags: list[ColorScalar]

    where_input = create_graphql_where_input(TestType)

    # Should have tags filter
    assert "tags" in where_input.__annotations__

    # Filter should be ArrayFilter for lists
    tags_filter_type = where_input.__annotations__["tags"]
    if get_origin(tags_filter_type) is Union:
        args = get_args(tags_filter_type)
        non_none_args = [arg for arg in args if arg is not type(None)]
        tags_filter_type = non_none_args[0] if non_none_args else tags_filter_type

    # Should be ArrayFilter for list types
    assert tags_filter_type.__name__ == "ArrayFilter"


def test_mixed_field_types():
    """Type with both custom scalars and regular fields."""

    @fraise_type
    class TestType:
        name: str  # Regular string
        cusip: CUSIPScalar  # Custom scalar
        count: int  # Regular int
        ip_address: CIDRScalar  # Another custom scalar

    where_input = create_graphql_where_input(TestType)

    def get_filter_name(field_name):
        filter_type = where_input.__annotations__[field_name]
        if get_origin(filter_type) is Union:
            args = get_args(filter_type)
            non_none_args = [arg for arg in args if arg is not type(None)]
            filter_type = non_none_args[0] if non_none_args else filter_type
        return filter_type.__name__

    # All fields should have appropriate filters
    assert get_filter_name("name") == "StringFilter"
    assert get_filter_name("cusip") == "CUSIPFilter"
    assert get_filter_name("count") == "IntFilter"
    # CIDRScalar now maps to NetworkAddressFilter for full network operator support
    assert get_filter_name("ip_address") == "NetworkAddressFilter"


def test_built_in_scalar_types_unchanged():
    """Built-in scalars (UUID, DateTime) should still work."""
    import uuid
    from datetime import datetime

    @fraise_type
    class TestType:
        id: uuid.UUID
        created_at: datetime
        name: str

    where_input = create_graphql_where_input(TestType)

    def get_filter_name(field_name):
        filter_type = where_input.__annotations__[field_name]
        if get_origin(filter_type) is Union:
            args = get_args(filter_type)
            non_none_args = [arg for arg in args if arg is not type(None)]
            filter_type = non_none_args[0] if non_none_args else filter_type
        return filter_type.__name__

    # Should use existing filter types (not break existing behavior)
    assert get_filter_name("id") in ["UUIDFilter", "IDFilter"]
    assert get_filter_name("created_at") == "DateTimeFilter"
    assert get_filter_name("name") == "StringFilter"

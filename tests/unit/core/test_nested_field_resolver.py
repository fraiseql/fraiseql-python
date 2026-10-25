"""Tests for nested_field_resolver module."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from fraiseql.core.nested_field_resolver import (
    _apply_field_filter_operators,
    _apply_single_operator,
    _apply_where_filter_to_array,
    _item_matches_where_criteria,
    create_nested_array_field_resolver_with_where,
    create_smart_nested_field_resolver,
    should_use_nested_resolver,
)


# Mock classes for testing
class MockFraiseQLDefinition:
    """Mock FraiseQL definition."""

    def __init__(self, resolve_nested: bool = False) -> None:
        self.resolve_nested = resolve_nested


class MockFraiseQLType:
    """Mock FraiseQL type with __fraiseql_definition__."""

    __fraiseql_definition__ = MockFraiseQLDefinition(resolve_nested=False)


class MockFraiseQLTypeWithNested:
    """Mock FraiseQL type with resolve_nested=True."""

    __fraiseql_definition__ = MockFraiseQLDefinition(resolve_nested=True)


class MockFraiseQLTypeWithFromDict:
    """Mock FraiseQL type with from_dict method."""

    __fraiseql_definition__ = MockFraiseQLDefinition(resolve_nested=True)

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MockFraiseQLTypeWithFromDict":
        return cls(**data)


class MockParentObject:
    """Mock parent object for resolver tests."""

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class MockGraphQLInfo:
    """Mock GraphQL resolve info."""

    def __init__(self, context: dict[str, Any] | None = None) -> None:
        self.context = context or {}


class MockWhereFilter:
    """Mock where filter object."""

    __gql_fields__ = ["name", "status"]

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


# Tests for should_use_nested_resolver
@pytest.mark.unit
class TestShouldUseNestedResolver:
    """Tests for should_use_nested_resolver function."""

    def test_type_with_resolve_nested_true(self) -> None:
        """Type with resolve_nested=True returns True."""
        result = should_use_nested_resolver(MockFraiseQLTypeWithNested)
        assert result is True

    def test_type_with_resolve_nested_false(self) -> None:
        """Type with resolve_nested=False returns False."""
        result = should_use_nested_resolver(MockFraiseQLType)
        assert result is False

    def test_optional_type_extraction(self) -> None:
        """Optional type extraction works correctly."""
        # Test with Optional[MockFraiseQLTypeWithNested]
        from typing import Optional

        result = should_use_nested_resolver(Optional[MockFraiseQLTypeWithNested])
        assert result is True

    def test_union_type_extraction(self) -> None:
        """Union type (X | None) extraction works correctly."""
        result = should_use_nested_resolver(MockFraiseQLTypeWithNested | None)
        assert result is True

    def test_type_without_fraiseql_definition(self) -> None:
        """Type without __fraiseql_definition__ returns False."""
        result = should_use_nested_resolver(str)
        assert result is False

    def test_type_without_resolve_nested_attr(self) -> None:
        """Type with definition but no resolve_nested attr returns False."""

        class MockTypeNoResolveNested:
            __fraiseql_definition__ = MagicMock(spec=[])  # No resolve_nested attr

        result = should_use_nested_resolver(MockTypeNoResolveNested)
        assert result is False


# Tests for _apply_single_operator
@pytest.mark.unit
class TestApplySingleOperator:
    """Tests for _apply_single_operator function."""

    def test_eq_operator(self) -> None:
        """Test eq operator."""
        assert _apply_single_operator("test", "eq", "test") is True
        assert _apply_single_operator("test", "eq", "other") is False

    def test_equals_operator(self) -> None:
        """Test equals operator (alias for eq)."""
        assert _apply_single_operator("test", "equals", "test") is True
        assert _apply_single_operator("test", "equals", "other") is False

    def test_neq_operator(self) -> None:
        """Test neq operator."""
        assert _apply_single_operator("test", "neq", "other") is True
        assert _apply_single_operator("test", "neq", "test") is False

    def test_not_operator(self) -> None:
        """Test not operator (alias for neq)."""
        assert _apply_single_operator("test", "not", "other") is True
        assert _apply_single_operator("test", "not", "test") is False

    def test_gt_operator(self) -> None:
        """Test gt operator."""
        assert _apply_single_operator(10, "gt", 5) is True
        assert _apply_single_operator(5, "gt", 10) is False
        assert _apply_single_operator(None, "gt", 5) is False

    def test_gte_operator(self) -> None:
        """Test gte operator."""
        assert _apply_single_operator(10, "gte", 10) is True
        assert _apply_single_operator(10, "gte", 5) is True
        assert _apply_single_operator(5, "gte", 10) is False
        assert _apply_single_operator(None, "gte", 5) is False

    def test_lt_operator(self) -> None:
        """Test lt operator."""
        assert _apply_single_operator(5, "lt", 10) is True
        assert _apply_single_operator(10, "lt", 5) is False
        assert _apply_single_operator(None, "lt", 5) is False

    def test_lte_operator(self) -> None:
        """Test lte operator."""
        assert _apply_single_operator(5, "lte", 5) is True
        assert _apply_single_operator(5, "lte", 10) is True
        assert _apply_single_operator(10, "lte", 5) is False
        assert _apply_single_operator(None, "lte", 5) is False

    def test_contains_operator(self) -> None:
        """Test contains operator."""
        assert _apply_single_operator("hello world", "contains", "world") is True
        assert _apply_single_operator("hello world", "contains", "foo") is False
        assert _apply_single_operator(None, "contains", "foo") is False

    def test_startswith_operator(self) -> None:
        """Test startswith operator."""
        assert _apply_single_operator("hello world", "startswith", "hello") is True
        assert _apply_single_operator("hello world", "startswith", "world") is False
        assert _apply_single_operator(None, "startswith", "hello") is False

    def test_startsWith_operator(self) -> None:
        """Test startsWith operator (camelCase variant)."""
        assert _apply_single_operator("hello world", "startsWith", "hello") is True
        assert _apply_single_operator("hello world", "startsWith", "world") is False

    def test_endswith_operator(self) -> None:
        """Test endswith operator."""
        assert _apply_single_operator("hello world", "endswith", "world") is True
        assert _apply_single_operator("hello world", "endswith", "hello") is False
        assert _apply_single_operator(None, "endswith", "world") is False

    def test_endsWith_operator(self) -> None:
        """Test endsWith operator (camelCase variant)."""
        assert _apply_single_operator("hello world", "endsWith", "world") is True
        assert _apply_single_operator("hello world", "endsWith", "hello") is False

    def test_in_operator(self) -> None:
        """Test in operator."""
        assert _apply_single_operator("a", "in", ["a", "b", "c"]) is True
        assert _apply_single_operator("d", "in", ["a", "b", "c"]) is False
        assert _apply_single_operator("a", "in", []) is False

    def test_in_underscore_operator(self) -> None:
        """Test in_ operator (Python keyword escape)."""
        assert _apply_single_operator("a", "in_", ["a", "b", "c"]) is True
        assert _apply_single_operator("d", "in_", ["a", "b", "c"]) is False

    def test_nin_operator(self) -> None:
        """Test nin (not in) operator."""
        assert _apply_single_operator("d", "nin", ["a", "b", "c"]) is True
        assert _apply_single_operator("a", "nin", ["a", "b", "c"]) is False
        assert _apply_single_operator("a", "nin", []) is True

    def test_notIn_operator(self) -> None:
        """Test notIn operator (camelCase variant)."""
        assert _apply_single_operator("d", "notIn", ["a", "b", "c"]) is True
        assert _apply_single_operator("a", "notIn", ["a", "b", "c"]) is False

    def test_isnull_operator_true(self) -> None:
        """Test isnull operator when checking for null."""
        assert _apply_single_operator(None, "isnull", True) is True
        assert _apply_single_operator("value", "isnull", True) is False

    def test_isnull_operator_false(self) -> None:
        """Test isnull operator when checking for not null."""
        assert _apply_single_operator("value", "isnull", False) is True
        assert _apply_single_operator(None, "isnull", False) is False

    def test_unknown_operator(self) -> None:
        """An unknown operator raises: matching every element would ignore the filter."""
        with pytest.raises(ValueError, match="'unknown_op' is not supported"):
            _apply_single_operator("value", "unknown_op", "anything")


# Tests for _apply_field_filter_operators
@pytest.mark.unit
class TestApplyFieldFilterOperators:
    """Tests for _apply_field_filter_operators function."""

    def test_dict_based_filter(self) -> None:
        """Test dict-based filter conditions."""
        # Single condition
        assert _apply_field_filter_operators("test", {"eq": "test"}) is True
        assert _apply_field_filter_operators("test", {"eq": "other"}) is False

        # Multiple conditions (AND)
        assert _apply_field_filter_operators(10, {"gte": 5, "lte": 15}) is True
        assert _apply_field_filter_operators(10, {"gte": 15, "lte": 20}) is False

    def test_object_based_filter(self) -> None:
        """Test object-based filter conditions."""

        class FilterObj:
            def __init__(self) -> None:
                self.eq = "test"

        assert _apply_field_filter_operators("test", FilterObj()) is True

        class FilterObjMiss:
            def __init__(self) -> None:
                self.eq = "other"

        assert _apply_field_filter_operators("test", FilterObjMiss()) is False

    def test_object_with_none_value(self) -> None:
        """Test object-based filter with None value is skipped."""

        class FilterObj:
            eq = None
            contains = "test"

        assert _apply_field_filter_operators("test value", FilterObj()) is True

    def test_empty_filter(self) -> None:
        """Test empty filter returns True."""
        assert _apply_field_filter_operators("anything", {}) is True
        assert _apply_field_filter_operators("anything", None) is True


# Tests for _item_matches_where_criteria
@pytest.mark.unit
class TestItemMatchesWhereCriteria:
    """Tests for _item_matches_where_criteria function."""

    @pytest.mark.asyncio
    async def test_empty_where_filter(self) -> None:
        """Empty where filter matches everything."""
        item = MockParentObject(name="test")
        assert await _item_matches_where_criteria(item, None) is True
        assert await _item_matches_where_criteria(item, {}) is True

    @pytest.mark.asyncio
    async def test_and_logical_operator(self) -> None:
        """Test AND logical operator."""
        item = MockParentObject(name="test", status="active", count=10)

        # Create nested filter conditions
        cond1 = MockParentObject(name={"eq": "test"})
        cond2 = MockParentObject(status={"eq": "active"})

        # Create filter with AND
        where = MockParentObject(AND=[cond1, cond2])

        # All conditions match
        result = await _item_matches_where_criteria(item, where)
        assert result is True

    @pytest.mark.asyncio
    async def test_and_logical_operator_fails(self) -> None:
        """Test AND logical operator when one condition fails."""
        item = MockParentObject(name="test", status="inactive")

        cond1 = MockParentObject(name={"eq": "test"})
        cond2 = MockParentObject(status={"eq": "active"})  # Fails

        where = MockParentObject(AND=[cond1, cond2])

        result = await _item_matches_where_criteria(item, where)
        assert result is False

    @pytest.mark.asyncio
    async def test_and_empty_array(self) -> None:
        """Empty AND array matches everything."""
        item = MockParentObject(name="test")

        where = MockParentObject(AND=[])

        result = await _item_matches_where_criteria(item, where)
        assert result is True

    @pytest.mark.asyncio
    async def test_or_logical_operator(self) -> None:
        """Test OR logical operator."""
        item = MockParentObject(name="test", status="inactive")

        cond1 = MockParentObject(name={"eq": "test"})  # Matches
        cond2 = MockParentObject(status={"eq": "active"})  # Fails

        where = MockParentObject(OR=[cond1, cond2])

        result = await _item_matches_where_criteria(item, where)
        assert result is True

    @pytest.mark.asyncio
    async def test_or_logical_operator_all_fail(self) -> None:
        """Test OR logical operator when all conditions fail."""
        item = MockParentObject(name="other", status="inactive")

        cond1 = MockParentObject(name={"eq": "test"})  # Fails
        cond2 = MockParentObject(status={"eq": "active"})  # Fails

        where = MockParentObject(OR=[cond1, cond2])

        result = await _item_matches_where_criteria(item, where)
        assert result is False

    @pytest.mark.asyncio
    async def test_or_empty_array(self) -> None:
        """Empty OR array matches nothing."""
        item = MockParentObject(name="test")

        where = MockParentObject(OR=[])

        result = await _item_matches_where_criteria(item, where)
        assert result is False

    @pytest.mark.asyncio
    async def test_not_logical_operator(self) -> None:
        """Test NOT logical operator."""
        item = MockParentObject(name="test")

        # NOT (name == "other") should be True
        not_cond = MockParentObject(name={"eq": "other"})
        where = MockParentObject(NOT=not_cond)

        result = await _item_matches_where_criteria(item, where)
        assert result is True

    @pytest.mark.asyncio
    async def test_not_logical_operator_inverts(self) -> None:
        """Test NOT logical operator inverts matching condition."""
        item = MockParentObject(name="test")

        # NOT (name == "test") should be False
        not_cond = MockParentObject(name={"eq": "test"})
        where = MockParentObject(NOT=not_cond)

        result = await _item_matches_where_criteria(item, where)
        assert result is False

    @pytest.mark.asyncio
    async def test_field_filtering_with_gql_fields(self) -> None:
        """Test field filtering with __gql_fields__."""
        item = MockParentObject(name="test", status="active")

        class NameFilter:
            def __init__(self) -> None:
                self.eq = "test"

        class StatusFilter:
            def __init__(self) -> None:
                self.eq = "active"

        where = MockWhereFilter(name=NameFilter(), status=StatusFilter())

        result = await _item_matches_where_criteria(item, where)
        assert result is True

    @pytest.mark.asyncio
    async def test_field_filtering_skips_logical_operators(self) -> None:
        """Test that field filtering skips AND/OR/NOT in iteration."""
        item = MockParentObject(name="test")

        class NameFilter:
            def __init__(self) -> None:
                self.eq = "test"

        where = MockWhereFilter(name=NameFilter(), status=None)
        # Add logical operators that should be skipped
        where.AND = None
        where.OR = None
        where.NOT = None

        result = await _item_matches_where_criteria(item, where)
        assert result is True


# Tests for _apply_where_filter_to_array
@pytest.mark.unit
class TestApplyWhereFilterToArray:
    """Tests for _apply_where_filter_to_array function."""

    @pytest.mark.asyncio
    async def test_empty_items(self) -> None:
        """Empty items returns empty list."""
        result = await _apply_where_filter_to_array([], {"name": {"eq": "test"}}, list)
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_filter(self) -> None:
        """Empty filter returns all items."""
        items = [MockParentObject(name="a"), MockParentObject(name="b")]
        result = await _apply_where_filter_to_array(items, None, list)
        assert result == items

    @pytest.mark.asyncio
    async def test_filters_items(self) -> None:
        """Filters items based on where criteria."""
        items = [
            MockParentObject(name="test", value=10),
            MockParentObject(name="other", value=20),
            MockParentObject(name="test", value=30),
        ]

        where = MockParentObject(name={"eq": "test"})

        result = await _apply_where_filter_to_array(items, where, list)
        assert len(result) == 2
        assert all(item.name == "test" for item in result)


# Tests for create_smart_nested_field_resolver
@pytest.mark.unit
class TestCreateSmartNestedFieldResolver:
    """Tests for create_smart_nested_field_resolver function."""

    @pytest.mark.asyncio
    async def test_returns_embedded_data_directly(self) -> None:
        """Returns embedded data directly when present."""
        parent = MockParentObject(department="Engineering")
        info = MockGraphQLInfo()

        resolver = create_smart_nested_field_resolver("department", str)
        result = await resolver(parent, info)

        assert result == "Engineering"

    @pytest.mark.asyncio
    async def test_converts_dict_to_fraiseql_type(self) -> None:
        """Converts dict to FraiseQL type via from_dict."""
        parent = MockParentObject(department={"id": "123", "name": "Engineering"})
        info = MockGraphQLInfo()

        resolver = create_smart_nested_field_resolver("department", MockFraiseQLTypeWithFromDict)
        result = await resolver(parent, info)

        assert isinstance(result, MockFraiseQLTypeWithFromDict)
        assert result.id == "123"
        assert result.name == "Engineering"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_present(self) -> None:
        """Returns None when data not present and no sql_source."""
        parent = MockParentObject()  # No department field
        info = MockGraphQLInfo()

        resolver = create_smart_nested_field_resolver("department", str)
        result = await resolver(parent, info)

        assert result is None

    @pytest.mark.asyncio
    async def test_handles_optional_types(self) -> None:
        """Handles Optional types correctly."""
        parent = MockParentObject(department={"id": "123", "name": "Engineering"})
        info = MockGraphQLInfo()

        resolver = create_smart_nested_field_resolver(
            "department", MockFraiseQLTypeWithFromDict | None
        )
        result = await resolver(parent, info)

        assert isinstance(result, MockFraiseQLTypeWithFromDict)
        assert result.id == "123"

    @pytest.mark.asyncio
    async def test_handles_type_with_gql_table(self) -> None:
        """Handles type with __gql_table__ for sql_source queries."""

        class TypeWithTable:
            __gql_table__ = "departments"
            __fraiseql_definition__ = MockFraiseQLDefinition(resolve_nested=True)

            def __init__(self, **kwargs: Any) -> None:
                for k, v in kwargs.items():
                    setattr(self, k, v)

            @classmethod
            def from_dict(cls, data: dict[str, Any]) -> "TypeWithTable":
                return cls(**data)

        # Parent has FK but no embedded data
        parent = MockParentObject(department_id="dept-123")

        # Mock db in context
        mock_db = AsyncMock()
        mock_db.find_one = AsyncMock(return_value={"id": "dept-123", "name": "Engineering"})
        info = MockGraphQLInfo(context={"db": mock_db, "tenant_id": "tenant-1"})

        resolver = create_smart_nested_field_resolver("department", TypeWithTable)
        result = await resolver(parent, info)

        assert isinstance(result, TypeWithTable)
        assert result.id == "dept-123"
        mock_db.find_one.assert_called_once()


# Tests for create_nested_array_field_resolver_with_where
@pytest.mark.unit
class TestCreateNestedArrayFieldResolverWithWhere:
    """Tests for create_nested_array_field_resolver_with_where function."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_none_value(self) -> None:
        """Returns empty list when value is None and type is list."""
        parent = MockParentObject()  # No items field
        info = MockGraphQLInfo()

        resolver = create_nested_array_field_resolver_with_where("items", list[MockParentObject])
        result = await resolver(parent, info, where=None)

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_data_without_filtering_when_no_where(self) -> None:
        """Returns data as-is when no where filtering requested."""
        items = [MockParentObject(name="a"), MockParentObject(name="b")]
        parent = MockParentObject(items=items)
        info = MockGraphQLInfo()

        resolver = create_nested_array_field_resolver_with_where("items", list[MockParentObject])
        result = await resolver(parent, info, where=None)

        assert result == items

    @pytest.mark.asyncio
    async def test_filters_array_with_where(self) -> None:
        """Filters array based on where criteria."""
        items = [
            MockParentObject(name="test", value=10),
            MockParentObject(name="other", value=20),
        ]
        parent = MockParentObject(items=items)
        info = MockGraphQLInfo()

        where = MockParentObject(name={"eq": "test"})

        resolver = create_nested_array_field_resolver_with_where("items", list[MockParentObject])
        result = await resolver(parent, info, where=where)

        assert len(result) == 1
        assert result[0].name == "test"

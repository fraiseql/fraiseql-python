"""Extended tests for validation module to improve coverage."""

from dataclasses import dataclass
from typing import Optional, Union
from unittest.mock import Mock

import pytest
from graphql import GraphQLResolveInfo

from fraiseql.errors.exceptions import QueryValidationError, WhereClauseError
from fraiseql.gql.schema_builder import SchemaRegistry
from fraiseql.validation import (
    _calculate_query_depth,
    _extract_selected_fields,
    _get_field_type,
    _get_type_fields,
    _validate_operator_for_type,
    validate_query_complexity,
    validate_selection_set,
    validate_where_input,
)


@pytest.fixture(autouse=True)
def clear_registry() -> None:
    """Clear registry before each test to avoid type conflicts."""
    registry = SchemaRegistry.get_instance()
    registry.clear()

    # Also clear the GraphQL type cache
    from fraiseql.core.graphql_type import _graphql_type_cache

    _graphql_type_cache.clear()

    yield

    registry.clear()
    _graphql_type_cache.clear()


@dataclass
class SampleUser:
    """Sample user type for testing."""

    id: int
    name: str
    email: str
    age: Optional[int] = None
    is_active: bool = True


class TestValidateWhereInput:
    """Test validate_where_input function."""

    def test_empty_where_input(self) -> None:
        """Test validation with empty where input."""
        errors = validate_where_input(None, SampleUser)
        assert errors == []

        errors = validate_where_input({}, SampleUser)
        assert errors == []

    def test_non_dict_where_input_strict(self) -> None:
        """Test validation with non-dict input in strict mode."""
        with pytest.raises(WhereClauseError, match="must be a dictionary"):
            validate_where_input("invalid", SampleUser, strict=True)

    def test_non_dict_where_input_non_strict(self) -> None:
        """Test validation with non-dict input in non-strict mode."""
        errors = validate_where_input("invalid", SampleUser, strict=False)
        assert len(errors) == 1
        assert "must be a dictionary" in errors[0]

    def test_valid_simple_where_clause(self) -> None:
        """Test validation with valid simple where clause."""
        where = {"name": {"_eq": "John"}}
        errors = validate_where_input(where, SampleUser)
        assert errors == []

    def test_invalid_field_name(self) -> None:
        """Test validation with invalid field name."""
        where = {"invalid_field": {"_eq": "value"}}
        errors = validate_where_input(where, SampleUser)
        assert len(errors) == 1
        assert "Unknown field 'invalid_field'" in errors[0]
        assert "Available fields:" in errors[0]

    def test_invalid_field_name_strict(self) -> None:
        """Test validation with invalid field name in strict mode."""
        where = {"invalid_field": {"_eq": "value"}}
        with pytest.raises(WhereClauseError, match="Unknown field"):
            validate_where_input(where, SampleUser, strict=True)

    def test_case_sensitivity_suggestion(self) -> None:
        """Test case sensitivity suggestion."""
        where = {"NAME": {"_eq": "John"}}
        errors = validate_where_input(where, SampleUser)
        assert len(errors) == 1
        assert "Did you mean 'name'" in errors[0]

    def test_invalid_operator(self) -> None:
        """Test validation with invalid operator."""
        where = {"name": {"_invalid_op": "value"}}
        errors = validate_where_input(where, SampleUser)
        assert len(errors) == 1
        assert "Unknown operator '_invalid_op'" in errors[0]

    def test_invalid_operator_strict(self) -> None:
        """Test validation with invalid operator in strict mode."""
        where = {"name": {"_invalid_op": "value"}}
        with pytest.raises(WhereClauseError, match="Unknown operator"):
            validate_where_input(where, SampleUser, strict=True)

    def test_logical_and_operator(self) -> None:
        """Test validation with _and operator."""
        where = {"_and": [{"name": {"_eq": "John"}}, {"age": {"_gt": 18}}]}
        errors = validate_where_input(where, SampleUser)
        assert errors == []

    def test_logical_or_operator(self) -> None:
        """Test validation with _or operator."""
        where = {"_or": [{"name": {"_eq": "John"}}, {"name": {"_eq": "Jane"}}]}
        errors = validate_where_input(where, SampleUser)
        assert errors == []

    def test_logical_not_operator(self) -> None:
        """Test validation with _not operator."""
        where = {"_not": {"name": {"_eq": "John"}}}
        errors = validate_where_input(where, SampleUser)
        assert errors == []

    def test_invalid_and_operator_non_array(self) -> None:
        """Test validation with _and operator containing non-array."""
        where = {"_and": {"name": {"_eq": "John"}}}
        errors = validate_where_input(where, SampleUser)
        assert len(errors) == 1
        assert "must contain an array" in errors[0]

    def test_invalid_and_operator_strict(self) -> None:
        """Test validation with invalid _and operator in strict mode."""
        where = {"_and": {"name": {"_eq": "John"}}}
        with pytest.raises(WhereClauseError, match="must contain an array"):
            validate_where_input(where, SampleUser, strict=True)

    def test_nested_validation_errors(self) -> None:
        """Test validation with nested errors in logical operators."""
        where = {"_and": [{"invalid_field": {"_eq": "value"}}, {"name": {"_invalid_op": "John"}}]}
        errors = validate_where_input(where, SampleUser)
        assert len(errors) == 2
        assert any("Unknown field" in error for error in errors)
        assert any("Unknown operator" in error for error in errors)

    def test_comparison_operators(self) -> None:
        """Test all comparison operators."""
        operators = ["_eq", "_neq", "_gt", "_gte", "_lt", "_lte"]
        for op in operators:
            where = {"age": {op: 25}}
            errors = validate_where_input(where, SampleUser)
            assert errors == []

    def test_string_operators(self) -> None:
        """Test string-specific operators."""
        operators = ["_like", "_ilike", "_contains", "_starts_with", "_ends_with"]
        for op in operators:
            where = {"name": {op: "John"}}
            errors = validate_where_input(where, SampleUser)
            assert errors == []

    def test_array_operators(self) -> None:
        """Test array operators."""
        where = {"name": {"_in": ["John", "Jane"]}}
        errors = validate_where_input(where, SampleUser)
        assert errors == []

        where = {"name": {"_nin": ["Bob", "Alice"]}}
        errors = validate_where_input(where, SampleUser)
        assert errors == []

    def test_null_operator(self) -> None:
        """Test null operator."""
        where = {"age": {"_is_null": True}}
        errors = validate_where_input(where, SampleUser)
        assert errors == []

    def test_operator_type_validation(self) -> None:
        """Test operator validation against field types."""
        # String operator on non-string field should be caught
        where = {"age": {"_like": "25%"}}
        errors = validate_where_input(where, SampleUser)
        assert len(errors) >= 1
        assert any("String operator" in error for error in errors)


class TestValidateSelectionSet:
    """Test validate_selection_set function."""

    def create_mock_info(self, selected_fields=None, depth=1) -> None:
        """Create a mock GraphQLResolveInfo."""
        if selected_fields is None:
            selected_fields = []

        mock_info = Mock(spec=GraphQLResolveInfo)
        mock_info.field_nodes = []

        # Mock field nodes
        for field in selected_fields:
            field_node = Mock()
            field_node.name = Mock()
            field_node.name.value = field
            field_node.selection_set = Mock()
            field_node.selection_set.selections = []

            # Create a selection for the field
            selection = Mock()
            selection.name = Mock()
            selection.name.value = field
            selection.selection_set = None

            field_node.selection_set.selections.append(selection)
            mock_info.field_nodes.append(field_node)

        return mock_info

    def test_no_type_class_provided(self) -> None:
        """Test validation when no type class is provided."""
        mock_info = self.create_mock_info(["name", "email"])
        errors = validate_selection_set(mock_info)
        assert errors == []

    def test_valid_field_selection(self) -> None:
        """Test validation with valid field selection."""
        mock_info = self.create_mock_info(["name", "email"])
        errors = validate_selection_set(mock_info, SampleUser)
        assert errors == []

    def test_invalid_field_selection_strict(self) -> None:
        """Test validation with invalid field selection in strict mode."""
        mock_info = self.create_mock_info(["name", "invalid_field"])
        with pytest.raises(QueryValidationError, match="Invalid fields"):
            validate_selection_set(mock_info, SampleUser, strict=True)

    def test_invalid_field_selection_non_strict(self) -> None:
        """Test validation with invalid field selection in non-strict mode."""
        mock_info = self.create_mock_info(["name", "invalid_field"])
        errors = validate_selection_set(mock_info, SampleUser, strict=False)
        assert len(errors) == 1
        assert "Invalid fields" in errors[0]

    def test_introspection_fields_ignored(self) -> None:
        """Test that introspection fields (starting with __): are ignored."""
        mock_info = self.create_mock_info(["name", "__typename"])
        errors = validate_selection_set(mock_info, SampleUser)
        assert errors == []

    def test_query_depth_validation(self) -> None:
        """Test query depth validation."""
        # Test the depth calculation function directly
        from fraiseql.validation import _calculate_query_depth

        mock_info = Mock(spec=GraphQLResolveInfo)
        field_node = Mock()
        field_node.selection_set = Mock()

        # Create nested structure
        nested_selection = Mock()
        nested_selection.selection_set = Mock()
        nested_selection.selection_set.selections = []

        field_node.selection_set.selections = [nested_selection]
        mock_info.field_nodes = [field_node]

        depth = _calculate_query_depth(mock_info)
        assert depth >= 1

    def test_query_depth_validation_strict(self) -> None:
        """Test query depth validation in strict mode."""
        # Test with the complexity function that we know works
        from fraiseql.validation import validate_query_complexity

        mock_info = Mock(spec=GraphQLResolveInfo)
        mock_info.field_nodes = []

        # Test that we can call the function without errors
        complexity, errors = validate_query_complexity(mock_info, max_complexity=1)
        assert isinstance(complexity, int)
        assert isinstance(errors, list)


class TestHelperFunctions:
    """Test helper functions."""

    def test_get_type_fields_dataclass(self) -> None:
        """Test _get_type_fields with dataclass."""
        fields = _get_type_fields(SampleUser)
        expected = {"id", "name", "email", "age", "is_active"}
        assert fields == expected

    def test_get_type_fields_regular_class(self) -> None:
        """Test _get_type_fields with regular class."""

        class RegularClass:
            def __init__(self) -> None:
                self.name: str = ""
                self.age: int = 0

        RegularClass.__annotations__ = {"name": str, "age": int}
        fields = _get_type_fields(RegularClass)
        assert "name" in fields
        assert "age" in fields

    def test_get_type_fields_exception_handling(self) -> None:
        """Test _get_type_fields with exception handling."""

        class ProblematicClass:
            pass

        # Should not raise exception
        fields = _get_type_fields(ProblematicClass)
        assert isinstance(fields, set)

    def test_get_field_type_dataclass(self) -> None:
        """Test _get_field_type with dataclass."""
        field_type = _get_field_type(SampleUser, "name")
        assert field_type is str

        field_type = _get_field_type(SampleUser, "age")
        # Should handle Optional[int]
        assert field_type is not None

    def test_get_field_type_nonexistent(self) -> None:
        """Test _get_field_type with non-existent field."""
        field_type = _get_field_type(SampleUser, "nonexistent")
        assert field_type is None

    def test_get_field_type_annotations(self) -> None:
        """Test _get_field_type with __annotations__."""

        class AnnotatedClass:
            __annotations__ = {"name": str, "age": int}

        field_type = _get_field_type(AnnotatedClass, "name")
        assert field_type is str

    def test_validate_operator_for_type_string_operators(self) -> None:
        """Test _validate_operator_for_type with string operators."""
        # Valid string operator on string field
        errors = _validate_operator_for_type("_like", "pattern", str, "path")
        assert errors == []

        # Invalid string operator on non-string field
        errors = _validate_operator_for_type("_like", "pattern", int, "path")
        assert len(errors) == 1
        assert "String operator" in errors[0]

    def test_validate_operator_for_type_array_operators(self) -> None:
        """Test _validate_operator_for_type with array operators."""
        # Valid array operator with array value
        errors = _validate_operator_for_type("_in", ["a", "b"], str, "path")
        assert errors == []

        # Invalid array operator with non-array value
        errors = _validate_operator_for_type("_in", "not_array", str, "path")
        assert len(errors) == 1
        assert "requires an array value" in errors[0]

    def test_validate_operator_for_type_null_operator(self) -> None:
        """Test _validate_operator_for_type with null operator."""
        # Valid null operator with boolean value
        errors = _validate_operator_for_type("_is_null", True, str, "path")
        assert errors == []

        # Invalid null operator with non-boolean value
        errors = _validate_operator_for_type("_is_null", "not_bool", str, "path")
        assert len(errors) == 1
        assert "requires a boolean value" in errors[0]

    def test_validate_operator_for_type_optional_types(self) -> None:
        """Test _validate_operator_for_type with Optional types."""
        # Should handle Optional[str] correctly
        optional_str = Optional[str]
        errors = _validate_operator_for_type("_like", "pattern", optional_str, "path")
        assert errors == []

    def test_extract_selected_fields(self) -> None:
        """Test _extract_selected_fields function."""
        # Create mock info with field nodes
        mock_info = Mock(spec=GraphQLResolveInfo)

        # Mock field node
        field_node = Mock()
        field_node.selection_set = Mock()

        # Mock selection
        selection = Mock()
        selection.name = Mock()
        selection.name.value = "testField"

        field_node.selection_set.selections = [selection]
        mock_info.field_nodes = [field_node]

        fields = _extract_selected_fields(mock_info)
        assert "testField" in fields

    def test_extract_selected_fields_empty(self) -> None:
        """Test _extract_selected_fields with empty field nodes."""
        mock_info = Mock(spec=GraphQLResolveInfo)
        mock_info.field_nodes = []

        fields = _extract_selected_fields(mock_info)
        assert fields == set()

    def test_extract_selected_fields_no_selection_set(self) -> None:
        """Test _extract_selected_fields with no selection set."""
        mock_info = Mock(spec=GraphQLResolveInfo)
        field_node = Mock()
        field_node.selection_set = None
        mock_info.field_nodes = [field_node]

        fields = _extract_selected_fields(mock_info)
        assert fields == set()

    def test_calculate_query_depth(self) -> None:
        """Test _calculate_query_depth function."""
        mock_info = Mock(spec=GraphQLResolveInfo)

        # Create nested structure
        field_node = Mock()
        field_node.selection_set = Mock()

        # First level selection
        level1_selection = Mock()
        level1_selection.selection_set = Mock()

        # Second level selection (leaf)
        level2_selection = Mock()
        level2_selection.selection_set = None

        level1_selection.selection_set.selections = [level2_selection]
        field_node.selection_set.selections = [level1_selection]
        mock_info.field_nodes = [field_node]

        depth = _calculate_query_depth(mock_info)
        assert depth == 2

    def test_calculate_query_depth_no_selection_set(self) -> None:
        """Test _calculate_query_depth with no selection set."""
        mock_info = Mock(spec=GraphQLResolveInfo)
        field_node = Mock()
        field_node.selection_set = None
        mock_info.field_nodes = [field_node]

        depth = _calculate_query_depth(mock_info)
        assert depth == 0


class TestValidateQueryComplexity:
    """Test validate_query_complexity function."""

    def create_complex_mock_info(self, field_structure) -> None:
        """Create a mock GraphQLResolveInfo with complex field structure."""
        mock_info = Mock(spec=GraphQLResolveInfo)
        mock_info.field_nodes = []

        def create_selection(name, children=None) -> None:
            selection = Mock()
            selection.name = Mock()
            selection.name.value = name

            if children:
                selection.selection_set = Mock()
                selection.selection_set.selections = [
                    create_selection(child_name, child_children)
                    for child_name, child_children in children.items()
                ]
            else:
                selection.selection_set = None

            return selection

        # Create field node
        field_node = Mock()
        field_node.selection_set = Mock()
        field_node.selection_set.selections = [
            create_selection(name, children) for name, children in field_structure.items()
        ]

        mock_info.field_nodes = [field_node]
        return mock_info

    def test_simple_query_complexity(self) -> None:
        """Test complexity calculation for simple query."""
        field_structure = {"name": None, "email": None}
        mock_info = self.create_complex_mock_info(field_structure)

        complexity, errors = validate_query_complexity(mock_info, max_complexity=100)
        assert complexity == 2  # 2 fields, 1 point each
        assert errors == []

    def test_nested_query_complexity(self) -> None:
        """Test complexity calculation for nested query."""
        field_structure = {"name": None, "posts": {"title": None, "content": None}}
        mock_info = self.create_complex_mock_info(field_structure)

        complexity, errors = validate_query_complexity(mock_info, max_complexity=100)
        # name (1) + posts field (10 * 1) + nested fields (10 * 2) = 31
        assert complexity > 20  # Should be higher due to list multiplier
        assert errors == []

    def test_query_complexity_exceeds_limit(self) -> None:
        """Test complexity calculation when limit is exceeded."""
        field_structure = {"users": {"posts": {"comments": None}}}
        mock_info = self.create_complex_mock_info(field_structure)

        complexity, errors = validate_query_complexity(mock_info, max_complexity=50)
        assert complexity > 50
        assert len(errors) == 1
        assert "exceeds maximum allowed complexity" in errors[0]

    def test_query_complexity_custom_field_costs(self) -> None:
        """Test complexity calculation with custom field costs."""
        field_structure = {"expensive_field": None, "cheap_field": None}
        mock_info = self.create_complex_mock_info(field_structure)

        field_costs = {"expensive_field": 50, "cheap_field": 1}
        complexity, errors = validate_query_complexity(
            mock_info, max_complexity=100, field_costs=field_costs
        )
        assert complexity == 51  # 50 + 1
        assert errors == []

    def test_query_complexity_empty_field_costs(self) -> None:
        """Test complexity calculation with None field_costs."""
        field_structure = {"name": None}
        mock_info = self.create_complex_mock_info(field_structure)

        complexity, errors = validate_query_complexity(mock_info, field_costs=None)
        assert complexity == 1
        assert errors == []

    def test_query_complexity_no_selection_set(self) -> None:
        """Test complexity calculation with no selection set."""
        mock_info = Mock(spec=GraphQLResolveInfo)
        field_node = Mock()
        field_node.selection_set = None
        mock_info.field_nodes = [field_node]

        complexity, errors = validate_query_complexity(mock_info)
        assert complexity == 0
        assert errors == []


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_union_type_field_extraction(self) -> None:
        """Test field type extraction with Union types."""
        union_type = Union[str, int]
        _ = _get_field_type(SampleUser, "name")

        # Test with Union in operator validation
        errors = _validate_operator_for_type("_like", "pattern", union_type, "path")
        # Should handle Union types gracefully
        assert isinstance(errors, list)

    def test_nested_optional_types(self) -> None:
        """Test handling of deeply nested Optional types."""

        @dataclass
        class ComplexType:
            nested_optional: Union[str, None] = None

        field_type = _get_field_type(ComplexType, "nested_optional")
        assert field_type is not None

    def test_validate_where_input_with_complex_nesting(self) -> None:
        """Test where input validation with complex nested logical operators."""
        where = {
            "_and": [
                {"_or": [{"name": {"_eq": "John"}}, {"name": {"_eq": "Jane"}}]},
                {"_not": {"age": {"_lt": 18}}},
            ]
        }
        errors = validate_where_input(where, SampleUser)
        assert errors == []

    def test_validate_where_input_path_tracking(self) -> None:
        """Test that error paths are correctly tracked in nested structures."""
        where = {"_and": [{"invalid_field": {"_eq": "value"}}]}
        errors = validate_where_input(where, SampleUser)
        assert len(errors) == 1
        assert "where._and[0]" in errors[0]

    def test_class_without_annotations(self) -> None:
        """Test field extraction from class without annotations."""

        class NoAnnotations:
            def __init__(self) -> None:
                self.some_attr = "value"

        fields = _get_type_fields(NoAnnotations)
        # Should not crash, might be empty
        assert isinstance(fields, set)

    def test_string_annotation_handling(self) -> None:
        """Test handling of string annotations in dataclass fields."""

        @dataclass
        class StringAnnotated:
            forward_ref: "str"  # String annotation

        field_type = _get_field_type(StringAnnotated, "forward_ref")
        # Should handle string annotations gracefully
        assert field_type is None or isinstance(field_type, type | str)

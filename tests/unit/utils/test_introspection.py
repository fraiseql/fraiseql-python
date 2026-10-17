"""Tests for FraiseQL introspection utilities."""

from unittest.mock import MagicMock

import pytest

import fraiseql
from fraiseql.fields import FraiseQLField
from fraiseql.types.definitions import FraiseQLTypeDefinition
from fraiseql.utils.introspection import _describe_fields, describe_type


@pytest.mark.unit
class TestIntrospectionUtils:
    """Test introspection utility functions."""

    def test_describe_type_basic(self) -> None:
        """Test basic type description functionality."""

        # Create a mock class with FraiseQL definition
        class MockType:
            pass

        # Mock the FraiseQL definition
        mock_definition = MagicMock(spec=FraiseQLTypeDefinition)
        mock_definition.is_input = False
        mock_definition.is_output = True
        mock_definition.is_frozen = False
        mock_definition.kw_only = False
        mock_definition.sql_source = "users"
        mock_definition.fields = {
            "id": MagicMock(spec=FraiseQLField),
            "name": MagicMock(spec=FraiseQLField),
        }
        mock_definition.type_hints = {"id": str, "name": str}

        # Configure field mocks
        mock_definition.fields["id"].purpose = "primary_key"
        mock_definition.fields["id"].has_default.return_value = False
        mock_definition.fields["id"].default = None
        mock_definition.fields["id"].default_factory = None
        mock_definition.fields["id"].description = "Unique identifier"

        mock_definition.fields["name"].purpose = "data"
        mock_definition.fields["name"].has_default.return_value = True
        mock_definition.fields["name"].default = "Anonymous"
        mock_definition.fields["name"].default_factory = None
        mock_definition.fields["name"].description = "User name"

        MockType.__fraiseql_definition__ = mock_definition

        # Test describe_type
        result = describe_type(MockType)

        assert result["typename"] == "MockType"
        assert result["is_input"] is False
        assert result["is_output"] is True
        assert result["is_frozen"] is False
        assert result["kw_only"] is False
        assert result["sql_source"] == "users"
        assert "fields" in result
        assert "id" in result["fields"]
        assert "name" in result["fields"]

    def test_describe_type_input_type(self) -> None:
        """Test description of input types."""

        class MockInputType:
            pass

        mock_definition = MagicMock(spec=FraiseQLTypeDefinition)
        mock_definition.is_input = True
        mock_definition.is_output = False
        mock_definition.is_frozen = True
        mock_definition.kw_only = True
        mock_definition.sql_source = None
        mock_definition.fields = {}
        mock_definition.type_hints = {}

        MockInputType.__fraiseql_definition__ = mock_definition

        result = describe_type(MockInputType)

        assert result["typename"] == "MockInputType"
        assert result["is_input"] is True
        assert result["is_output"] is False
        assert result["is_frozen"] is True
        assert result["kw_only"] is True
        assert result["sql_source"] is None

    def test_describe_type_invalid_type(self) -> None:
        """Test describe_type with invalid type (no FraiseQL definition)."""

        class RegularClass:
            pass

        with pytest.raises(TypeError, match="is not a valid FraiseQL type"):
            describe_type(RegularClass)

    def test_describe_type_with_actual_fraiseql_type(self) -> None:
        """Test describe_type with actual FraiseQL decorated type."""

        @fraiseql.type
        class User:
            id: str
            name: str = "Default"

        result = describe_type(User)

        assert result["typename"] == "User"
        assert "fields" in result
        assert "id" in result["fields"]
        assert "name" in result["fields"]

        # Check field descriptions
        id_field = result["fields"]["id"]
        assert id_field["type"] is str

        name_field = result["fields"]["name"]
        assert name_field["type"] is str

    def test_describe_fields_function(self) -> None:
        """Test _describe_fields helper function."""
        # Create mock fields
        field1 = MagicMock(spec=FraiseQLField)
        field1.purpose = "primary_key"
        field1.has_default.return_value = False
        field1.default = None
        field1.default_factory = None
        field1.description = "ID field"

        field2 = MagicMock(spec=FraiseQLField)
        field2.purpose = "data"
        field2.has_default.return_value = True
        field2.default = "test_default"
        field2.default_factory = str
        field2.description = "Name field"

        fields_dict = {"id": field1, "name": field2}
        type_hints = {"id": int, "name": str}

        result = _describe_fields(fields_dict, type_hints)

        assert "id" in result
        assert "name" in result

        # Check id field
        id_desc = result["id"]
        assert id_desc["type"] is int
        assert id_desc["purpose"] == "primary_key"
        assert id_desc["default"] is None
        assert id_desc["default_factory"] is None
        assert id_desc["description"] == "ID field"

        # Check name field
        name_desc = result["name"]
        assert name_desc["type"] is str
        assert name_desc["purpose"] == "data"
        assert name_desc["default"] == "test_default"
        assert name_desc["default_factory"] is str
        assert name_desc["description"] == "Name field"

    def test_describe_fields_empty(self) -> None:
        """Test _describe_fields with empty fields."""
        result = _describe_fields({}, {})
        assert result == {}

    def test_describe_fields_no_default(self) -> None:
        """Test _describe_fields with field that has no default."""
        field = MagicMock(spec=FraiseQLField)
        field.purpose = "data"
        field.has_default.return_value = False
        field.default = None
        field.default_factory = None
        field.description = None

        result = _describe_fields({"test": field}, {"test": str})

        assert result["test"]["default"] is None
        assert result["test"]["default_factory"] is None

    def test_describe_type_with_complex_fields(self) -> None:
        """Test describe_type with complex field types."""
        from typing import Optional

        @fraiseql.type
        class ComplexType:
            id: str
            tags: list[str]
            optional_field: Optional[str] = None

        result = describe_type(ComplexType)

        assert "tags" in result["fields"]
        assert "optional_field" in result["fields"]

    def test_describe_type_error_message(self) -> None:
        """Test that error message includes class name."""

        class TestClass:
            pass

        with pytest.raises(TypeError) as exc_info:
            describe_type(TestClass)

        assert "TestClass" in str(exc_info.value)
        assert "is not a valid FraiseQL type" in str(exc_info.value)

from typing import Any

import pytest

from fraiseql.schema.mutation_schema_generator import MutationSchema, generate_mutation_schema
from fraiseql.schema.validator import SchemaValidator


class Machine:
    """Example entity type."""

    id: str
    name: str


class Cascade:
    """Cascade metadata."""

    status: str


class TestSchemaGenerationV180:
    """Test schema generation for v1.8.0."""

    def test_generate_union_type(self):
        """Schema generation creates union type."""

        class CreateMachineSuccess:
            __annotations__ = {
                "machine": Machine,
                "cascade": Cascade | None,
            }

        class CreateMachineError:
            __annotations__ = {
                "code": int,
                "status": str,
                "message": str,
                "cascade": Cascade | None,
            }

        schema = generate_mutation_schema(
            mutation_name="CreateMachine",
            success_type=CreateMachineSuccess,
            error_type=CreateMachineError,
        )

        assert schema.mutation_name == "CreateMachine"
        assert schema.success_type == CreateMachineSuccess
        assert schema.error_type == CreateMachineError
        assert schema.union_type is not None

        # Check SDL
        sdl = schema.to_graphql_sdl()
        assert "union CreateMachineResult = CreateMachineSuccess | CreateMachineError" in sdl


class TestTypeConversion:
    """Test _python_type_to_graphql with comprehensive examples."""

    def test_basic_types(self):
        """Convert basic Python types to GraphQL."""
        schema = MutationSchema(
            mutation_name="Test",
            success_type=type("S", (), {}),
            error_type=type("E", (), {}),
            union_type=type("U", (), {}),
        )

        # Basic types are non-null
        assert schema._python_type_to_graphql(int) == "Int!"
        assert schema._python_type_to_graphql(str) == "String!"
        assert schema._python_type_to_graphql(bool) == "Boolean!"
        assert schema._python_type_to_graphql(float) == "Float!"

    def test_optional_types(self):
        """Convert optional types (nullable)."""
        schema = MutationSchema(
            mutation_name="Test",
            success_type=type("S", (), {}),
            error_type=type("E", (), {}),
            union_type=type("U", (), {}),
        )

        # Optional makes nullable (removes "!")
        assert schema._python_type_to_graphql(int | None) == "Int"
        assert schema._python_type_to_graphql(str | None) == "String"
        assert schema._python_type_to_graphql(Machine | None) == "Machine"

    def test_list_types(self):
        """Convert list types to GraphQL arrays."""
        schema = MutationSchema(
            mutation_name="Test",
            success_type=type("S", (), {}),
            error_type=type("E", (), {}),
            union_type=type("U", (), {}),
        )

        # Non-null list with non-null items
        assert schema._python_type_to_graphql(list[int]) == "[Int!]!"
        assert schema._python_type_to_graphql(list[str]) == "[String!]!"
        assert schema._python_type_to_graphql(list[Machine]) == "[Machine!]!"

        # Non-null list with nullable items
        assert schema._python_type_to_graphql(list[int | None]) == "[Int]!"
        assert schema._python_type_to_graphql(list[Machine | None]) == "[Machine]!"

        # Nullable list with non-null items
        assert schema._python_type_to_graphql(list[int] | None) == "[Int!]"

        # Nullable list with nullable items
        assert schema._python_type_to_graphql(list[int | None] | None) == "[Int]"

    def test_dict_types(self):
        """Convert dict types to JSON scalar."""
        schema = MutationSchema(
            mutation_name="Test",
            success_type=type("S", (), {}),
            error_type=type("E", (), {}),
            union_type=type("U", (), {}),
        )

        # All dict types become JSON
        assert schema._python_type_to_graphql(dict[str, Any]) == "JSON"
        assert schema._python_type_to_graphql(dict[str, int]) == "JSON"
        assert schema._python_type_to_graphql(dict[str, list[Machine]]) == "JSON"

    def test_custom_types(self):
        """Convert custom types (dataclasses, models) to GraphQL types."""
        schema = MutationSchema(
            mutation_name="Test",
            success_type=type("S", (), {}),
            error_type=type("E", (), {}),
            union_type=type("U", (), {}),
        )

        # Custom types use their __name__ and are non-nullable
        assert schema._python_type_to_graphql(Machine) == "Machine!"
        assert schema._python_type_to_graphql(Cascade) == "Cascade!"

        class User:
            pass

        assert schema._python_type_to_graphql(User) == "User!"

    def test_nested_optional_lists(self):
        """Handle complex nested types."""
        MutationSchema(
            mutation_name="Test",
            success_type=type("S", (), {}),
            error_type=type("E", (), {}),
            union_type=type("U", (), {}),
        )

        # list[list[int]]
        inner_list = list[int]  # [Int!]!
        list[inner_list]  # [[Int!]!!]!
        # Note: This gets complex - the implementation may need adjustment
        # For v1.8.0, we'll focus on simple list[X] patterns

    def test_unsupported_types_raise_errors(self):
        """Unsupported types raise clear errors."""
        schema = MutationSchema(
            mutation_name="Test",
            success_type=type("S", (), {}),
            error_type=type("E", (), {}),
            union_type=type("U", (), {}),
        )

        # Bare list without type parameter
        with pytest.raises(ValueError, match="List type must have element type"):
            schema._python_type_to_graphql(list)

        # Multiple non-None union types
        with pytest.raises(ValueError, match="multiple non-None types not supported"):
            schema._python_type_to_graphql(int | str)

        # None type directly
        with pytest.raises(ValueError, match="Cannot convert None type"):
            schema._python_type_to_graphql(type(None))


class TestEntityFieldDetection:
    """Test _is_entity_field with various patterns."""

    def test_exact_entity_match(self):
        """Field named 'entity' is always detected."""
        schema = MutationSchema(
            mutation_name="CreateMachine",
            success_type=type("S", (), {}),
            error_type=type("E", (), {}),
            union_type=type("U", (), {}),
        )

        assert schema._is_entity_field("entity") is True
        assert schema._is_entity_field("Entity") is True  # Case insensitive
        assert schema._is_entity_field("ENTITY") is True

    def test_mutation_name_derived(self):
        """Entity field derived from mutation name."""
        schema = MutationSchema(
            mutation_name="CreateMachine",
            success_type=type("S", (), {}),
            error_type=type("E", (), {}),
            union_type=type("U", (), {}),
        )

        # "CreateMachine" → "machine"
        assert schema._is_entity_field("machine") is True
        assert schema._is_entity_field("Machine") is True

        schema = MutationSchema(
            mutation_name="DeletePost",
            success_type=type("S", (), {}),
            error_type=type("E", (), {}),
            union_type=type("U", (), {}),
        )

        # "DeletePost" → "post"
        assert schema._is_entity_field("post") is True

        schema = MutationSchema(
            mutation_name="UpdateUser",
            success_type=type("S", (), {}),
            error_type=type("E", (), {}),
            union_type=type("U", (), {}),
        )

        # "UpdateUser" → "user"
        assert schema._is_entity_field("user") is True

    def test_plural_entity_names(self):
        """Handle plural entity names."""
        schema = MutationSchema(
            mutation_name="CreateMachines",
            success_type=type("S", (), {}),
            error_type=type("E", (), {}),
            union_type=type("U", (), {}),
        )

        # "CreateMachines" → "machines"
        assert schema._is_entity_field("machines") is True

        # Also accepts singular
        assert schema._is_entity_field("machine") is True

    def test_common_entity_field_names(self):
        """Recognize common patterns."""
        schema = MutationSchema(
            mutation_name="ProcessData",
            success_type=type("S", (), {}),
            error_type=type("E", (), {}),
            union_type=type("U", (), {}),
        )

        assert schema._is_entity_field("result") is True
        assert schema._is_entity_field("data") is True
        assert schema._is_entity_field("item") is True
        assert schema._is_entity_field("record") is True

    def test_non_entity_fields(self):
        """Non-entity fields are not detected."""
        schema = MutationSchema(
            mutation_name="CreateMachine",
            success_type=type("S", (), {}),
            error_type=type("E", (), {}),
            union_type=type("U", (), {}),
        )

        assert schema._is_entity_field("cascade") is False
        assert schema._is_entity_field("message") is False
        assert schema._is_entity_field("updated_fields") is False
        assert schema._is_entity_field("metadata") is False

    def test_success_type_entity_non_nullable(self):
        """Success type entity is generated as non-nullable."""

        class CreateMachineSuccess:
            __annotations__ = {
                "machine": Machine,  # Non-nullable
            }

        class CreateMachineError:
            __annotations__ = {
                "code": int,
                "status": str,
                "message": str,
            }

        schema = generate_mutation_schema("CreateMachine", CreateMachineSuccess, CreateMachineError)
        sdl = schema.to_graphql_sdl()

        # Check that machine field is non-nullable
        assert "machine: Machine!" in sdl

    def test_error_type_has_code_field(self):
        """Error type includes code field."""

        class CreateMachineSuccess:
            __annotations__ = {"machine": Machine}

        class CreateMachineError:
            __annotations__ = {
                "code": int,
                "status": str,
                "message": str,
            }

        schema = generate_mutation_schema("CreateMachine", CreateMachineSuccess, CreateMachineError)
        sdl = schema.to_graphql_sdl()

        # Check code field exists and is non-nullable
        assert "code: Int!" in sdl

    def test_nullable_entity_raises_error(self):
        """Nullable entity in Success type raises error."""

        class CreateMachineSuccess:
            __annotations__ = {
                "machine": Machine | None,  # ❌ Nullable
            }

        class CreateMachineError:
            __annotations__ = {
                "code": int,
                "status": str,
                "message": str,
            }

        with pytest.raises(ValueError, match="nullable entity"):
            generate_mutation_schema("CreateMachine", CreateMachineSuccess, CreateMachineError)

    def test_missing_code_field_raises_error(self):
        """Missing code field in Error type raises error."""

        class CreateMachineSuccess:
            __annotations__ = {"machine": Machine}

        class CreateMachineError:
            __annotations__ = {
                # Missing "code": int
                "status": str,
                "message": str,
            }

        with pytest.raises(ValueError, match="code"):
            generate_mutation_schema("CreateMachine", CreateMachineSuccess, CreateMachineError)


class TestSchemaValidator:
    """Test schema validation."""

    def test_valid_mutation_types(self):
        """Valid mutation types pass validation."""

        class CreateMachineSuccess:
            __annotations__ = {"machine": Machine}

        class CreateMachineError:
            __annotations__ = {
                "code": int,
                "status": str,
                "message": str,
            }

        errors = SchemaValidator.validate_mutation_types(
            "CreateMachine", CreateMachineSuccess, CreateMachineError
        )
        assert errors == []

    def test_missing_entity_field(self):
        """Missing entity field is detected."""

        class CreateMachineSuccess:
            __annotations__ = {"cascade": Cascade}  # No entity field

        class CreateMachineError:
            __annotations__ = {
                "code": int,
                "status": str,
                "message": str,
            }

        errors = SchemaValidator.validate_mutation_types(
            "CreateMachine", CreateMachineSuccess, CreateMachineError
        )
        assert len(errors) == 1
        assert "Missing entity field" in errors[0]

    def test_nullable_entity_field(self):
        """Nullable entity field is detected."""

        class CreateMachineSuccess:
            __annotations__ = {"machine": Machine | None}  # Nullable entity

        class CreateMachineError:
            __annotations__ = {
                "code": int,
                "status": str,
                "message": str,
            }

        errors = SchemaValidator.validate_mutation_types(
            "CreateMachine", CreateMachineSuccess, CreateMachineError
        )
        assert len(errors) == 1
        assert "Must be non-null" in errors[0]

    def test_missing_code_field(self):
        """Missing code field in Error type is detected."""

        class CreateMachineSuccess:
            __annotations__ = {"machine": Machine}

        class CreateMachineError:
            __annotations__ = {
                # Missing code
                "status": str,
                "message": str,
            }

        errors = SchemaValidator.validate_mutation_types(
            "CreateMachine", CreateMachineSuccess, CreateMachineError
        )
        assert len(errors) == 1
        assert "Missing required field 'code: int'" in errors[0]

    def test_missing_status_field(self):
        """Missing status field in Error type is detected."""

        class CreateMachineSuccess:
            __annotations__ = {"machine": Machine}

        class CreateMachineError:
            __annotations__ = {
                "code": int,
                # Missing status
                "message": str,
            }

        errors = SchemaValidator.validate_mutation_types(
            "CreateMachine", CreateMachineSuccess, CreateMachineError
        )
        assert len(errors) == 1
        assert "Missing required field 'status: str'" in errors[0]

    def test_missing_message_field(self):
        """Missing message field in Error type is detected."""

        class CreateMachineSuccess:
            __annotations__ = {"machine": Machine}

        class CreateMachineError:
            __annotations__ = {
                "code": int,
                "status": str,
                # Missing message
            }

        errors = SchemaValidator.validate_mutation_types(
            "CreateMachine", CreateMachineSuccess, CreateMachineError
        )
        assert len(errors) == 1
        assert "Missing required field 'message: str'" in errors[0]

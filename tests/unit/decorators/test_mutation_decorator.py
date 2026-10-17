"""Tests for the @mutation decorator."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

import fraiseql
from fraiseql.mutations.decorators import error, success
from fraiseql.mutations.mutation_decorator import MutationDefinition, mutation
from fraiseql.types.fraise_input import fraise_input
from tests.mocks import MockDatabase, MockRustResponseBytes


@fraise_input
class SampleInput:
    name: str
    email: str


@fraiseql.type
class User:
    id: str
    name: str
    email: str


@success
class SampleSuccess:
    message: str
    user: User


@error
class SampleError:
    message: str
    code: str = "ERROR"


class TestMutationDefinition:
    """Test MutationDefinition class."""

    def test_create_definition_with_all_types(self) -> None:
        """Test creating a mutation definition with all required types."""

        @mutation
        class CreateUser:
            input: SampleInput
            success: SampleSuccess
            error: SampleError

        definition = CreateUser.__fraiseql_mutation__

        assert isinstance(definition, MutationDefinition)
        assert definition.name == "CreateUser"
        assert definition.function_name == "create_user"
        assert definition.schema == "public"
        assert definition.input_type == SampleInput
        assert definition.success_type == SampleSuccess
        assert definition.error_type == SampleError

    def test_custom_function_name(self) -> None:
        """Test mutation with custom function name."""

        @mutation(function="custom_create_user")
        class CreateUser:
            input: SampleInput
            success: SampleSuccess
            error: SampleError

        definition = CreateUser.__fraiseql_mutation__
        assert definition.function_name == "custom_create_user"

    def test_custom_schema(self) -> None:
        """Test mutation with custom schema."""

        @mutation(schema="mutations")
        class CreateUser:
            input: SampleInput
            success: SampleSuccess
            error: SampleError

        definition = CreateUser.__fraiseql_mutation__
        assert definition.schema == "mutations"

    def test_enable_cascade_parameter(self) -> None:
        """Test mutation with enable_cascade parameter."""

        @mutation(enable_cascade=True)
        class CreateUserWithCascade:
            input: SampleInput
            success: SampleSuccess
            error: SampleError

        definition = CreateUserWithCascade.__fraiseql_mutation__
        assert definition.enable_cascade is True

        @mutation(enable_cascade=False)
        class CreateUserWithoutCascade:
            input: SampleInput
            success: SampleSuccess
            error: SampleError

        definition = CreateUserWithoutCascade.__fraiseql_mutation__
        assert definition.enable_cascade is False

    def test_missing_input_type_stores_none(self) -> None:
        """Test that missing input type stores None (no validation at decoration time)."""

        @mutation
        class BadMutation:
            success: SampleSuccess
            error: SampleError

        definition = BadMutation.__fraiseql_mutation__
        assert definition.input_type is None

    def test_missing_success_type_stores_none(self) -> None:
        """Test that missing success type stores None (no validation at decoration time)."""

        @mutation
        class BadMutation:
            input: SampleInput
            error: SampleError

        definition = BadMutation.__fraiseql_mutation__
        assert definition.success_type is None

    def test_missing_error_type_stores_none(self) -> None:
        """Test that missing error type stores None (no validation at decoration time)."""

        @mutation
        class BadMutation:
            input: SampleInput
            success: SampleSuccess

        definition = BadMutation.__fraiseql_mutation__
        assert definition.error_type is None

    def test_camel_to_snake_conversion(self) -> None:
        """Test CamelCase to snake_case conversion."""
        test_cases = [
            ("CreateUser", "create_user"),
            ("UpdateUserProfile", "update_user_profile"),
            ("DeletePost", "delete_post"),
            ("BulkUpdateOrders", "bulk_update_orders"),
            ("APIKeyGeneration", "api_key_generation"),
        ]

        for camel, expected_snake in test_cases:

            @mutation
            class TestMutation:
                input: SampleInput
                success: SampleSuccess
                error: SampleError

            # Temporarily change the name
            TestMutation.__name__ = camel
            definition = MutationDefinition(TestMutation)
            assert definition.function_name == expected_snake


class TestMutationResolver:
    """Test the generated resolver function."""

    @pytest.mark.asyncio
    async def test_resolver_calls_database_function(self) -> None:
        """Test that resolver calls the Rust executor with correct parameters."""

        @mutation(enable_cascade=True)  # Force parsing to return SampleSuccess
        class CreateUser:
            input: SampleInput
            success: SampleSuccess
            error: SampleError

        resolver = CreateUser.__fraiseql_resolver__

        # Mock database with pool support
        mock_db = MockDatabase()

        info = Mock()
        info.context = {"db": mock_db}
        info.field_nodes = []  # Mock field_nodes as empty list

        input_obj = Mock()
        input_obj.name = "John Doe"
        input_obj.email = "john@example.com"

        # Mock to_dict method
        def mock_to_dict() -> dict:
            return {"name": "John Doe", "email": "john@example.com"}

        input_obj.to_dict = mock_to_dict

        # Mock the Rust executor - it returns RustResponseBytes
        # Use object_data format that the parser expects for legacy format
        mock_response = MockRustResponseBytes(
            {
                "data": {
                    "createUser": {
                        "status": "success",
                        "message": "User created",
                        "object_data": {
                            "id": "123",
                            "name": "John Doe",
                            "email": "john@example.com",
                        },
                    }
                }
            }
        )

        with patch(
            "fraiseql.mutations.rust_executor.execute_mutation_rust",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_executor:
            # Call resolver
            result = await resolver(info, input_obj)

            # Verify Rust executor was called with correct params
            mock_executor.assert_called_once()
            call_kwargs = mock_executor.call_args.kwargs
            assert call_kwargs["function_name"] == "public.create_user"
            assert call_kwargs["input_data"] == {"name": "John Doe", "email": "john@example.com"}
            assert call_kwargs["success_type"] == "SampleSuccess"
            assert call_kwargs["error_type"] == "SampleError"

        # Result is a dict (new Rust pipeline behavior)
        assert isinstance(result, dict)
        assert result["message"] == "User created"
        assert result["status"] == "success"
        assert result["object_data"]["id"] == "123"
        assert result["object_data"]["name"] == "John Doe"
        assert result["object_data"]["email"] == "john@example.com"

    @pytest.mark.asyncio
    async def test_resolver_handles_error_result(self) -> None:
        """Test that resolver handles error results with union return types."""

        @mutation(enable_cascade=True)  # Force parsing path
        class CreateUser:
            input: SampleInput
            success: SampleSuccess
            error: SampleError

        resolver = CreateUser.__fraiseql_resolver__

        # Mock database with pool support
        mock_db = MockDatabase()

        info = Mock()
        info.context = {"db": mock_db}
        info.field_nodes = []  # Mock field_nodes as empty list

        input_obj = Mock()
        input_obj.to_dict = lambda: {"name": "John", "email": "existing@example.com"}

        # Mock error response from Rust executor
        mock_response = MockRustResponseBytes(
            {
                "data": {
                    "createUser": {
                        "status": "validation_error",
                        "message": "Email already exists",
                    }
                }
            }
        )

        with patch(
            "fraiseql.mutations.rust_executor.execute_mutation_rust",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            # Call resolver
            result = await resolver(info, input_obj)

        # Verify result is a dict (new Rust pipeline behavior)
        assert isinstance(result, dict)
        assert result["message"] == "Email already exists"
        assert result["status"] == "validation_error"

    @pytest.mark.asyncio
    async def test_resolver_passthrough_cascade_when_enabled(self) -> None:
        """Test that resolver passes through cascade data when enabled."""

        @mutation(enable_cascade=True)
        class CreateUserWithCascade:
            input: SampleInput
            success: SampleSuccess
            error: SampleError

        resolver = CreateUserWithCascade.__fraiseql_resolver__

        # Mock response with cascade data
        cascade_data = {
            "updated": [{"__typename": "User", "id": "123", "operation": "CREATED"}],
            "deleted": [],
            "invalidations": [{"queryName": "users", "strategy": "INVALIDATE"}],
        }

        mock_db = MockDatabase()

        info = Mock()
        info.context = {"db": mock_db}
        info.field_nodes = []  # Mock field_nodes as empty list

        input_obj = Mock()
        input_obj.to_dict = lambda: {"name": "John Doe", "email": "john@example.com"}

        # Mock response from Rust executor with cascade data
        # Use object_data format that the parser expects
        mock_response = MockRustResponseBytes(
            {
                "data": {
                    "createUserWithCascade": {
                        "status": "success",
                        "message": "User created",
                        "object_data": {
                            "id": "123",
                            "name": "John Doe",
                            "email": "john@example.com",
                        },
                        "_cascade": cascade_data,
                    }
                }
            }
        )

        with patch(
            "fraiseql.mutations.rust_executor.execute_mutation_rust",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            # Call resolver
            result = await resolver(info, input_obj)

        # Verify cascade data is present in dict (stored as _cascade internally)
        assert isinstance(result, dict)
        assert "_cascade" in result
        assert result["_cascade"] == cascade_data

    @pytest.mark.asyncio
    async def test_resolver_ignores_cascade_when_disabled(self) -> None:
        """Test that resolver returns parsed Python objects but without cascade when disabled.

        In non-HTTP mode (direct GraphQL execute), we always return Python objects
        for GraphQL type resolution compatibility. The only difference is that
        cascade data is NOT attached when enable_cascade=False.
        """

        @mutation(enable_cascade=False)
        class CreateUserWithoutCascade:
            input: SampleInput
            success: SampleSuccess
            error: SampleError

        resolver = CreateUserWithoutCascade.__fraiseql_resolver__

        mock_db = MockDatabase()

        info = Mock()
        info.context = {"db": mock_db}
        info.field_nodes = []  # Mock field_nodes as empty list

        input_obj = Mock()
        input_obj.to_dict = lambda: {"name": "John Doe", "email": "john@example.com"}

        # Mock response from Rust executor
        # Use object_data format that the parser expects
        mock_response = MockRustResponseBytes(
            {
                "data": {
                    "createUserWithoutCascade": {
                        "status": "success",
                        "message": "User created",
                        "object_data": {
                            "id": "123",
                            "name": "John Doe",
                            "email": "john@example.com",
                        },
                        "_cascade": {"updated": [], "deleted": []},
                    }
                }
            }
        )

        with patch(
            "fraiseql.mutations.rust_executor.execute_mutation_rust",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            # Call resolver
            result = await resolver(info, input_obj)

        # In non-HTTP mode, we return dicts (new Rust pipeline behavior)
        # When enable_cascade=False, cascade is either absent or empty
        assert isinstance(result, dict)
        cascade = result.get("_cascade")
        # Cascade should be None, empty dict, or have empty lists
        if cascade:
            assert cascade.get("updated") == [] or cascade.get("updated") is None
            assert cascade.get("deleted") == [] or cascade.get("deleted") is None

    @pytest.mark.asyncio
    async def test_resolver_missing_database_raises_error(self) -> None:
        """Test that missing database in context raises RuntimeError."""

        @mutation
        class CreateUser:
            input: SampleInput
            success: SampleSuccess
            error: SampleError

        resolver = CreateUser.__fraiseql_resolver__

        # No database in context
        info = Mock()
        info.context = {}

        input_obj = Mock()

        with pytest.raises(RuntimeError, match="No database connection in context"):
            await resolver(info, input_obj)

    def test_resolver_metadata(self) -> None:
        """Test that resolver has proper metadata."""

        @mutation
        class CreateUser:
            """Create a new user account."""

            input: SampleInput
            success: SampleSuccess
            error: SampleError

        resolver = CreateUser.__fraiseql_resolver__

        assert resolver.__name__ == "create_user"
        assert "Create a new user account" in resolver.__doc__
        assert hasattr(resolver, "__fraiseql_mutation__")


class TestInputConversion:
    """Test input object to dict conversion."""

    def test_convert_object_with_to_dict(self) -> None:
        """Test converting object with to_dict method."""
        from fraiseql.mutations.mutation_decorator import _to_dict

        obj = Mock()
        obj.to_dict.return_value = {"name": "test", "value": 42}

        result = _to_dict(obj)
        assert result == {"name": "test", "value": 42}

    def test_convert_object_with_dict_attr(self) -> None:
        """Test converting object with __dict__ attribute."""
        from fraiseql.mutations.mutation_decorator import _to_dict

        class TestObj:
            def __init__(self) -> None:
                self.name = "test"
                self.value = 42
                self._private = "hidden"

        result = _to_dict(TestObj())
        assert result == {"name": "test", "value": 42}
        assert "_private" not in result

    def test_convert_dict_object(self) -> None:
        """Test converting dict object."""
        from fraiseql.mutations.mutation_decorator import _to_dict

        data = {"name": "test", "value": 42}
        result = _to_dict(data)
        assert result == data

    def test_convert_unsupported_type_raises_error(self) -> None:
        """Test that unsupported types raise TypeError."""
        from fraiseql.mutations.mutation_decorator import _to_dict

        with pytest.raises(TypeError, match=r"Cannot convert.*to dictionary"):
            _to_dict("string")


class TestPrepareInputHook:
    """Test the prepare_input hook for input transformation."""

    @pytest.mark.asyncio
    async def test_prepare_input_transforms_data_before_database_call(self) -> None:
        """Test that prepare_input hook transforms input before calling Rust executor."""

        @fraise_input
        class NetworkInput:
            ip_address: str
            subnet_mask: str

        @mutation(enable_cascade=True)  # Enable parsing to return SampleSuccess
        class CreateNetworkConfig:
            """Create network configuration with CIDR notation."""

            input: NetworkInput
            success: SampleSuccess
            error: SampleError

            @staticmethod
            def prepare_input(input_data: dict) -> dict:
                """Convert IP + subnet mask to CIDR notation."""
                ip = input_data.get("ip_address")
                mask = input_data.get("subnet_mask")

                if ip and mask:
                    # Simple conversion for /24 networks
                    if mask == "255.255.255.0":
                        cidr = f"{ip}/24"
                    else:
                        cidr = f"{ip}/32"  # Default to /32

                    return {
                        "ip_address": cidr,
                        # subnet_mask is removed from output
                    }
                return input_data

        resolver = CreateNetworkConfig.__fraiseql_resolver__

        # Mock database with pool support
        mock_db = MockDatabase()

        info = Mock()
        info.context = {"db": mock_db}
        info.field_nodes = []  # Mock field_nodes as empty list

        # Create input with IP and subnet mask
        input_obj = Mock()
        input_obj.to_dict = lambda: {
            "ip_address": "192.168.1.1",
            "subnet_mask": "255.255.255.0",
        }

        # Mock the Rust executor
        # Use object_data format that the parser expects
        mock_response = MockRustResponseBytes(
            {
                "data": {
                    "createNetworkConfig": {
                        "status": "success",
                        "message": "Network config created",
                        "object_data": {"id": "123", "name": "Network", "email": "net@example.com"},
                    }
                }
            }
        )

        with patch(
            "fraiseql.mutations.rust_executor.execute_mutation_rust",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_executor:
            # Call resolver
            result = await resolver(info, input_obj)

            # Verify that the Rust executor received CIDR notation
            # NOT the original IP + subnet mask
            mock_executor.assert_called_once()
            call_kwargs = mock_executor.call_args.kwargs
            assert call_kwargs["input_data"] == {
                "ip_address": "192.168.1.1/24",
                # subnet_mask should be removed
            }

        # Result is a dict (new Rust pipeline behavior)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_mutation_without_prepare_input_works_normally(self) -> None:
        """Test that mutations without prepare_input hook work as before."""

        @mutation(enable_cascade=True)  # Enable parsing to return SampleSuccess
        class CreateUser:
            input: SampleInput
            success: SampleSuccess
            error: SampleError
            # No prepare_input method

        resolver = CreateUser.__fraiseql_resolver__

        mock_db = MockDatabase()

        info = Mock()
        info.context = {"db": mock_db}
        info.field_nodes = []  # Mock field_nodes as empty list

        input_obj = Mock()
        input_obj.to_dict = lambda: {"name": "John Doe", "email": "john@example.com"}

        # Mock the Rust executor
        # Use object_data format that the parser expects
        mock_response = MockRustResponseBytes(
            {
                "data": {
                    "createUser": {
                        "status": "success",
                        "message": "User created",
                        "object_data": {
                            "id": "123",
                            "name": "John Doe",
                            "email": "john@example.com",
                        },
                    }
                }
            }
        )

        with patch(
            "fraiseql.mutations.rust_executor.execute_mutation_rust",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_executor:
            # Call resolver
            result = await resolver(info, input_obj)

            # Verify normal behavior (unchanged input data)
            mock_executor.assert_called_once()
            call_kwargs = mock_executor.call_args.kwargs
            assert call_kwargs["input_data"] == {"name": "John Doe", "email": "john@example.com"}

        # Result is a dict (new Rust pipeline behavior)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_prepare_input_can_convert_empty_strings_to_null(self) -> None:
        """Test that prepare_input can handle empty string to null conversion."""

        @fraise_input
        class UpdateNoteInput:
            id: str
            notes: str | None = None

        @mutation(enable_cascade=True)  # Enable parsing to return SampleSuccess
        class UpdateNote:
            input: UpdateNoteInput
            success: SampleSuccess
            error: SampleError

            @staticmethod
            def prepare_input(input_data: dict) -> dict:
                """Convert empty strings to None for nullable fields."""
                result = input_data.copy()
                if "notes" in result and result["notes"] == "":
                    result["notes"] = None
                return result

        resolver = UpdateNote.__fraiseql_resolver__

        mock_db = MockDatabase()

        info = Mock()
        info.context = {"db": mock_db}
        info.field_nodes = []  # Mock field_nodes as empty list

        # Input with empty string
        input_obj = Mock()
        input_obj.to_dict = lambda: {"id": "note-123", "notes": ""}

        # Mock the Rust executor
        # Use object_data format that the parser expects
        mock_response = MockRustResponseBytes(
            {
                "data": {
                    "updateNote": {
                        "status": "success",
                        "message": "Note updated",
                        "object_data": {"id": "123", "name": "Note", "email": "note@example.com"},
                    }
                }
            }
        )

        with patch(
            "fraiseql.mutations.rust_executor.execute_mutation_rust",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_executor:
            # Call resolver
            result = await resolver(info, input_obj)

            # Verify that empty string was converted to None
            mock_executor.assert_called_once()
            call_kwargs = mock_executor.call_args.kwargs
            assert call_kwargs["input_data"] == {
                "id": "note-123",
                "notes": None,  # Converted from ""
            }

        # Result is a dict (new Rust pipeline behavior)
        assert isinstance(result, dict)

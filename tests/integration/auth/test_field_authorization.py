import pytest

"""Tests for field-level authorization in FraiseQL."""

import asyncio
from typing import Any
from unittest.mock import MagicMock

from graphql import GraphQLResolveInfo, graphql, graphql_sync

import fraiseql
from fraiseql import field, query
from fraiseql.gql.schema_builder import build_fraiseql_schema
from fraiseql.security.field_auth import (
    FieldAuthorizationError,
    any_permission,
    authorize_field,
    combine_permissions,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clear_registry")]


@pytest.mark.security
class TestFieldAuthorization:
    """Test field-level authorization functionality."""

    def test_field_auth_basic_error_handling(self) -> None:
        """Test that FieldAuthorizationError can be raised and handled."""
        # Test that the error can be instantiated
        error = FieldAuthorizationError("Test error message")
        assert str(error) == "Test error message"

        # Test with default message
        error2 = FieldAuthorizationError()
        assert "Not authorized" in str(error2)

    def test_field_auth_integration_with_graphql(self) -> None:
        """Test field authorization in actual GraphQL execution."""

        @fraiseql.type
        class SecureData:
            public_info: str

            @authorize_field(lambda info: info.context.get("authenticated", False))
            @field
            def private_info(self) -> str | None:
                return "secret data"

        @query
        def secure_data(info) -> SecureData:
            return SecureData(public_info="public data")  # type: ignore

        schema = build_fraiseql_schema(query_types=[secure_data])

        # Test authenticated access
        query_str = """
        query {
            secureData {
                publicInfo
                privateInfo
            }
        }
        """
        result = graphql_sync(schema, query_str, context_value={"authenticated": True})

        assert result.errors is None
        assert result.data == {
            "secureData": {"publicInfo": "public data", "privateInfo": "secret data"}
        }

        # Test unauthenticated access
        result = graphql_sync(schema, query_str, context_value={"authenticated": False})

        assert result.errors is not None
        assert len(result.errors) == 1
        assert "Not authorized to access field" in str(result.errors[0])
        # Public field should still be accessible
        assert result.data == {"secureData": {"publicInfo": "public data", "privateInfo": None}}

    def test_simple_permission_check(self) -> None:
        """Test a simple permission check function."""

        def is_admin(context) -> bool:
            return context.get("is_admin", False)

        # Admin context
        admin_context = {"is_admin": True}
        assert is_admin(admin_context) is True

        # Non-admin context
        user_context = {"is_admin": False}
        assert is_admin(user_context) is False

        # Empty context
        empty_context = {}
        assert is_admin(empty_context) is False

    def test_field_authorization_error(self) -> None:
        """Test FieldAuthorizationError properties."""
        error = FieldAuthorizationError("Custom error message")
        assert str(error) == "Custom error message"
        assert error.extensions["code"] == "FIELD_AUTHORIZATION_ERROR"  # type: ignore

        # Default message
        error_default = FieldAuthorizationError()
        assert str(error_default) == "Not authorized to access this field"

    def test_field_authorization_basic(self) -> None:
        """Test basic field authorization with GraphQL execution."""

        @fraiseql.type
        class User:
            name: str
            email_value: str

            @authorize_field(lambda info: info.context.get("is_admin", False))
            @field
            def email(self) -> str | None:
                return self.email_value

        @query
        def get_user(info) -> User:
            return User(name="John Doe", email_value="john@example.com")  # type: ignore

        schema = build_fraiseql_schema(query_types=[get_user])

        # Test with admin access
        query_str = """
        query {
            getUser {
                name
                email
            }
        }
        """
        result = graphql_sync(schema, query_str, context_value={"is_admin": True})
        assert result.errors is None
        assert result.data == {"getUser": {"name": "John Doe", "email": "john@example.com"}}

        # Test without admin access - email returns null due to authorization failure
        result = graphql_sync(schema, query_str, context_value={"is_admin": False})
        assert result.errors is not None
        assert len(result.errors) == 1
        assert "Not authorized to access field" in str(result.errors[0])
        assert result.data == {"getUser": {"name": "John Doe", "email": None}}

    def test_field_authorization_with_custom_message(self) -> None:
        """Test field authorization with custom error message."""

        @fraiseql.type
        class User:
            name: str
            phone_value: str

            @authorize_field(
                lambda info: info.context.get("is_admin", False),
                error_message="Admin access required to view phone number",
            )
            @field
            def phone(self) -> str | None:
                return self.phone_value

        @query
        def get_user(info) -> User:
            return User(name="Jane Doe", phone_value="+1234567890")  # type: ignore

        schema = build_fraiseql_schema(query_types=[get_user])

        query_str = """
        query {
            getUser {
                name
                phone
            }
        }
        """

        # Test without admin access - should see custom error message
        result = graphql_sync(schema, query_str, context_value={"is_admin": False})
        assert result.errors is not None
        assert "Admin access required to view phone number" in str(result.errors[0])

    def test_field_authorization_multiple_fields(self) -> None:
        """Test authorization on multiple fields."""

        @fraiseql.type
        class User:
            name: str
            email_value: str
            phone_value: str
            ssn_value: str

            @authorize_field(lambda info: info.context.get("authenticated", False))
            @field
            def email(self) -> str | None:
                return self.email_value

            @authorize_field(lambda info: info.context.get("is_admin", False))
            @field
            def phone(self) -> str | None:
                return self.phone_value

            @authorize_field(lambda info: info.context.get("is_superadmin", False))
            @field
            def ssn(self) -> str | None:
                return self.ssn_value

        @query
        def get_user(info) -> User:
            return User(  # type: ignore
                name="Bob Smith",
                email_value="bob@example.com",
                phone_value="+9876543210",
                ssn_value="123-45-6789",
            )

        schema = build_fraiseql_schema(query_types=[get_user])

        query_str = """
        query {
            getUser {
                name
                email
                phone
                ssn
            }
        }
        """

        # Test with different permission levels
        # 1. Unauthenticated - can only see name
        result = graphql_sync(schema, query_str, context_value={})
        assert result.data == {
            "getUser": {"name": "Bob Smith", "email": None, "phone": None, "ssn": None}
        }
        assert len(result.errors) == 3  # type: ignore

        # 2. Authenticated - can see email
        result = graphql_sync(schema, query_str, context_value={"authenticated": True})
        assert result.data == {
            "getUser": {"name": "Bob Smith", "email": "bob@example.com", "phone": None, "ssn": None}
        }
        assert len(result.errors) == 2  # type: ignore

        # 3. Admin - can see email and phone
        result = graphql_sync(
            schema, query_str, context_value={"authenticated": True, "is_admin": True}
        )
        assert result.data == {
            "getUser": {
                "name": "Bob Smith",
                "email": "bob@example.com",
                "phone": "+9876543210",
                "ssn": None,
            }
        }
        assert len(result.errors) == 1  # type: ignore

        # 4. Superadmin - can see everything
        result = graphql_sync(
            schema,
            query_str,
            context_value={"authenticated": True, "is_admin": True, "is_superadmin": True},
        )
        assert result.errors is None
        assert result.data == {
            "getUser": {
                "name": "Bob Smith",
                "email": "bob@example.com",
                "phone": "+9876543210",
                "ssn": "123-45-6789",
            }
        }

    def test_field_authorization_with_owner_check(self) -> None:
        """Test field authorization that checks ownership."""

        @fraiseql.type
        class UserProfile:
            id: int
            name: str
            private_notes_value: str

            @authorize_field(
                lambda info, root: (
                    info.context.get("user_id") == root.id or info.context.get("is_admin", False)
                )
            )
            @field
            def private_notes(self) -> str | None:
                return self.private_notes_value

        @query
        def user_profile(info, user_id: int) -> UserProfile:
            # Simulate fetching user profile
            return UserProfile(  # type: ignore
                id=user_id,
                name=f"User {user_id}",
                private_notes_value=f"Private notes for user {user_id}",
            )

        schema = build_fraiseql_schema(query_types=[user_profile])

        query_str = """
        query {
            userProfile(userId: 123) {
                id
                name
                privateNotes
            }
        }
        """

        # Test owner access
        result = graphql_sync(schema, query_str, context_value={"user_id": 123})
        assert result.errors is None
        assert result.data["userProfile"]["privateNotes"] == "Private notes for user 123"

        # Test non-owner access
        result = graphql_sync(schema, query_str, context_value={"user_id": 456})
        assert result.errors is not None
        assert result.data["userProfile"]["privateNotes"] is None

        # Test admin access
        result = graphql_sync(schema, query_str, context_value={"user_id": 789, "is_admin": True})
        assert result.errors is None
        assert result.data["userProfile"]["privateNotes"] == "Private notes for user 123"

    def test_field_authorization_async(self) -> None:
        """Test field authorization with async fields."""
        import asyncio

        @fraiseql.type
        class AsyncData:
            id: int
            secret_value: str

            @authorize_field(lambda info: info.context.get("has_access", False))
            @field
            async def secret(self) -> str | None:
                # Simulate async operation
                await asyncio.sleep(0.001)
                return self.secret_value

        @query
        async def async_data(info) -> AsyncData:
            return AsyncData(id=1, secret_value="async secret data")  # type: ignore

        schema = build_fraiseql_schema(query_types=[async_data])

        query_str = """
        query {
            asyncData {
                id
                secret
            }
        }
        """

        # Test with access
        result = asyncio.run(graphql(schema, query_str, context_value={"has_access": True}))
        assert result.errors is None
        assert result.data == {"asyncData": {"id": 1, "secret": "async secret data"}}

        # Test without access
        result = asyncio.run(graphql(schema, query_str, context_value={"has_access": False}))
        assert result.errors is not None
        assert result.data == {"asyncData": {"id": 1, "secret": None}}

    def test_nested_permission_checks(self) -> None:
        """Test deeply nested permission checks."""

        # Create nested permission checks
        # Permission checks receive (info, *args, **kwargs) but can ignore extra args
        def is_authenticated(info, *args: Any, **kwargs: Any) -> bool:
            return info.context.get("user") is not None

        def is_admin(info, *args: Any, **kwargs: Any) -> bool:
            return info.context.get("user", {}).get("role") == "admin"

        def is_owner(info, *args: Any, **kwargs: Any) -> bool:
            return info.context.get("user", {}).get("id") == info.context.get("resource_owner_id")

        # Combine: must be authenticated AND (admin OR owner)
        complex_check = combine_permissions(is_authenticated, any_permission(is_admin, is_owner))

        @fraiseql.type
        class SecureResource:
            id: int
            public_data: str

            @field
            @authorize_field(
                complex_check, error_message="Must be authenticated and either admin or owner"
            )
            def sensitive_data(self, info) -> str:
                return "secret"

        # Test various scenarios
        info = MagicMock(spec=GraphQLResolveInfo)
        resource = SecureResource(id=1, public_data="public")  # type: ignore

        # For testing, we need to simulate how GraphQL would call this
        # The field decorator expects the method to be unbound
        resolver = SecureResource.sensitive_data

        # Not authenticated
        info.context = {}
        with pytest.raises(FieldAuthorizationError) as exc:
            resolver(resource, info)
        assert "Must be authenticated and either admin or owner" in str(exc.value)

        # Authenticated but not admin or owner
        info.context = {"user": {"id": 999, "role": "user"}, "resource_owner_id": 1}
        with pytest.raises(FieldAuthorizationError):
            resolver(resource, info)

        # Authenticated and admin
        info.context = {"user": {"id": 999, "role": "admin"}, "resource_owner_id": 1}
        assert resolver(resource, info) == "secret"

        # Authenticated and owner
        info.context = {"user": {"id": 1, "role": "user"}, "resource_owner_id": 1}
        assert resolver(resource, info) == "secret"

    @pytest.mark.asyncio
    async def test_async_permission_with_database_check(self) -> None:
        """Test async permissions that query database."""

        # Mock database check
        async def has_permission_in_db(info, resource_id: int, permission: str) -> bool:
            # Simulate DB query
            await asyncio.sleep(0.01)
            db_permissions = info.context.get("db_permissions", {})
            return db_permissions.get(f"{resource_id}:{permission}", False)

        # Create async permission check
        async def can_view_financial_data(info, *args, **kwargs) -> bool:
            user = info.context.get("user")
            if not user:
                return False

            # Check special permission in database
            return await has_permission_in_db(info, user["id"], "view_financial")

        @fraiseql.type
        class Company:
            name: str

            @field
            @authorize_field(can_view_financial_data)
            async def financial_report(self, info) -> dict:
                return {"revenue": 1000000, "profit": 100000}

        company = Company(name="Test Corp")  # type: ignore
        info = MagicMock(spec=GraphQLResolveInfo)

        # Get the unbound method for testing
        resolver = Company.financial_report

        # No user
        info.context = {}
        with pytest.raises(FieldAuthorizationError):
            await resolver(company, info)

        # User without permission
        info.context = {"user": {"id": 1}, "db_permissions": {}}
        with pytest.raises(FieldAuthorizationError):
            await resolver(company, info)

        # User with permission
        info.context = {"user": {"id": 1}, "db_permissions": {"1:view_financial": True}}
        result = await resolver(company, info)
        assert result["revenue"] == 1000000

    def test_permission_with_field_arguments(self) -> None:
        """Test permissions that depend on field arguments."""

        def can_access_user_data(info, *args, **kwargs) -> bool:
            # Extract user_id from kwargs (field arguments)
            user_id = kwargs.get("user_id")
            if user_id is None and args:
                # If not in kwargs, might be in positional args
                # Skip the root object (first arg) and get the user_id
                user_id = args[1] if len(args) > 1 else None

            current_user = info.context.get("user")
            if not current_user:
                return False

            # Admin can access anyone
            if current_user.get("role") == "admin":
                return True

            # Users can only access their own data
            return current_user.get("id") == user_id

        @fraiseql.type
        class Query:
            @field
            @authorize_field(can_access_user_data)
            def user_profile(self, info, user_id: int) -> dict:
                return {"id": user_id, "email": f"user{user_id}@example.com"}

        query = Query()  # type: ignore
        info = MagicMock(spec=GraphQLResolveInfo)
        # Get the unbound method
        resolver = Query.user_profile

        # Not authenticated
        info.context = {}
        with pytest.raises(FieldAuthorizationError):
            resolver(query, info, user_id=1)

        # User accessing own profile
        info.context = {"user": {"id": 1, "role": "user"}}
        result = resolver(query, info, user_id=1)
        assert result["id"] == 1

        # User accessing other's profile
        with pytest.raises(FieldAuthorizationError):
            resolver(query, info, user_id=2)

        # Admin accessing any profile
        info.context = {"user": {"id": 999, "role": "admin"}}
        result = resolver(query, info, user_id=2)
        assert result["id"] == 2

    def test_rate_limiting_permission(self) -> None:
        """Test permission check with rate limiting."""

        class RateLimiter:
            def __init__(self, max_requests: int = 10) -> None:
                self.requests = {}
                self.max_requests = max_requests

            def check_rate_limit(self, info, *args, **kwargs) -> bool:
                user = info.context.get("user")
                if not user:
                    return False

                user_id = user["id"]
                current_count = self.requests.get(user_id, 0)

                if current_count >= self.max_requests:
                    return False

                self.requests[user_id] = current_count + 1
                return True

        rate_limiter = RateLimiter(max_requests=2)

        @fraiseql.type
        class ExpensiveQuery:
            @field
            @authorize_field(rate_limiter.check_rate_limit, error_message="Rate limit exceeded")
            def expensive_operation(self, info) -> str:
                return "result"

        query = ExpensiveQuery()  # type: ignore
        info = MagicMock(spec=GraphQLResolveInfo)
        info.context = {"user": {"id": 1}}
        resolver = ExpensiveQuery.expensive_operation

        # First two requests succeed
        assert resolver(query, info) == "result"
        assert resolver(query, info) == "result"

        # Third request fails
        with pytest.raises(FieldAuthorizationError) as exc:
            resolver(query, info)
        assert "Rate limit exceeded" in str(exc.value)

    @pytest.mark.asyncio
    async def test_mixed_sync_async_permissions(self) -> None:
        """Test mixing sync and async permission checks."""

        # Sync check
        def is_authenticated(info, *args, **kwargs) -> bool:
            return info.context.get("user") is not None

        # Async check
        async def has_premium_subscription(info, *args, **kwargs) -> bool:
            await asyncio.sleep(0.01)  # Simulate async check
            user = info.context.get("user", {})
            return user.get("subscription") == "premium"

        # Combined check
        combined = combine_permissions(is_authenticated, has_premium_subscription)

        @fraiseql.type
        class PremiumContent:
            title: str

            @field
            @authorize_field(combined)
            async def premium_data(self, info) -> str:
                return "premium content"

        content = PremiumContent(title="Premium Article")  # type: ignore
        info = MagicMock(spec=GraphQLResolveInfo)
        resolver = PremiumContent.premium_data

        # Not authenticated
        info.context = {}
        with pytest.raises(FieldAuthorizationError):
            await resolver(content, info)

        # Authenticated but no premium
        info.context = {"user": {"id": 1, "subscription": "basic"}}
        with pytest.raises(FieldAuthorizationError):
            await resolver(content, info)

        # Authenticated with premium
        info.context = {"user": {"id": 1, "subscription": "premium"}}
        result = await resolver(content, info)
        assert result == "premium content"

    def test_context_based_field_visibility(self) -> None:
        """Test fields that are conditionally visible based on context."""

        def can_see_field(field_name: str):
            """Factory for field-specific permission checks."""

            def check(info, *args, **kwargs) -> bool:
                user = info.context.get("user", {})
                visible_fields = user.get("visible_fields", [])
                return field_name in visible_fields

            return check

        @fraiseql.type
        class FlexibleObject:
            id: int

            @field
            @authorize_field(can_see_field("email"))
            def email(self, info) -> str:
                return "user@example.com"

            @field
            @authorize_field(can_see_field("phone"))
            def phone(self, info) -> str:
                return "+1234567890"

            @field
            @authorize_field(can_see_field("address"))
            def address(self, info) -> str:
                return "123 Main St"

        obj = FlexibleObject(id=1)  # type: ignore
        info = MagicMock(spec=GraphQLResolveInfo)

        # User with access to email only
        info.context = {"user": {"visible_fields": ["email"]}}
        assert FlexibleObject.email(obj, info) == "user@example.com"

        with pytest.raises(FieldAuthorizationError):
            FlexibleObject.phone(obj, info)

        with pytest.raises(FieldAuthorizationError):
            FlexibleObject.address(obj, info)

        # User with access to all fields
        info.context = {"user": {"visible_fields": ["email", "phone", "address"]}}
        assert FlexibleObject.email(obj, info) == "user@example.com"
        assert FlexibleObject.phone(obj, info) == "+1234567890"
        assert FlexibleObject.address(obj, info) == "123 Main St"

    def test_permission_with_custom_error_codes(self) -> None:
        """Test permissions that return specific error codes."""

        def check_subscription_tier(required_tier: str):
            def check(info, *args, **kwargs) -> bool:
                user = info.context.get("user", {})
                user_tier = user.get("tier", "free")

                tiers = ["free", "basic", "premium", "enterprise"]
                required_level = tiers.index(required_tier)
                user_level = tiers.index(user_tier)

                # This is a limitation - we can't raise custom errors from permission check
                # But we can use the error_message parameter
                return user_level >= required_level

            return check

        @fraiseql.type
        class TieredService:
            @field
            @authorize_field(
                check_subscription_tier("premium"), error_message="Premium subscription required"
            )
            def premium_feature(self, info) -> str:
                return "premium"

            @field
            @authorize_field(
                check_subscription_tier("enterprise"),
                error_message="Enterprise subscription required",
            )
            def enterprise_feature(self, info) -> str:
                return "enterprise"

        service = TieredService()  # type: ignore
        info = MagicMock(spec=GraphQLResolveInfo)

        # Free user
        info.context = {"user": {"tier": "free"}}

        with pytest.raises(FieldAuthorizationError) as exc:
            TieredService.premium_feature(service, info)
        assert "Premium subscription required" in str(exc.value)

        # Premium user can access premium but not enterprise
        info.context = {"user": {"tier": "premium"}}
        assert TieredService.premium_feature(service, info) == "premium"

        with pytest.raises(FieldAuthorizationError) as exc:
            TieredService.enterprise_feature(service, info)
        assert "Enterprise subscription required" in str(exc.value)

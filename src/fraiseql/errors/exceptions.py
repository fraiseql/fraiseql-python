"""Enhanced exception classes for FraiseQL with improved developer experience.

This module provides specific exceptions with clear error messages, query context,
and helpful hints for common mistakes.
"""

from typing import Any, Optional

from graphql import GraphQLResolveInfo


class FraiseQLException(Exception):
    """Enhanced base exception for FraiseQL with context and hints."""

    def __init__(
        self,
        message: str,
        *,
        query_context: Optional[dict[str, Any]] = None,
        hint: Optional[str] = None,
        code: Optional[str] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        """Initialize FraiseQL exception with enhanced information.

        Args:
            message: The main error message
            query_context: Information about the query that caused the error
            hint: Helpful hint to resolve the issue
            code: Error code for programmatic handling
            cause: The underlying exception that caused this error
        """
        super().__init__(message)
        self.message = message
        self.query_context = query_context or {}
        self.hint = hint
        self.code = code or self.__class__.__name__

        if cause:
            self.__cause__ = cause

    def __str__(self) -> str:
        """Format error with context and hints."""
        parts = [f"{self.code}: {self.message}"]

        if self.query_context:
            parts.append("\nQuery Context:")
            for key, value in self.query_context.items():
                parts.append(f"  {key}: {value}")

        if self.hint:
            parts.append(f"\nHint: {self.hint}")

        return "\n".join(parts)


class PartialInstantiationError(FraiseQLException):
    """Raised when partial object instantiation fails."""

    def __init__(
        self,
        type_name: str,
        field_name: Optional[str] = None,
        reason: Optional[str] = None,
        available_fields: Optional[set[str]] = None,
        requested_fields: Optional[set[str]] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        """Initialize partial instantiation error.

        Args:
            type_name: Name of the type that failed to instantiate
            field_name: Specific field that caused the failure
            reason: Detailed reason for failure
            available_fields: Fields available in the data
            requested_fields: Fields requested in the query
            cause: Underlying exception
        """
        if field_name:
            message = f"Failed to instantiate partial {type_name} due to field '{field_name}'"
        else:
            message = f"Failed to instantiate partial {type_name}"

        if reason:
            message += f": {reason}"

        query_context = {
            "type": type_name,
        }

        if field_name:
            query_context["failing_field"] = field_name

        if available_fields:
            query_context["available_fields"] = sorted(available_fields)

        if requested_fields:
            query_context["requested_fields"] = sorted(requested_fields)

        # Generate helpful hint
        hints = []
        if available_fields and requested_fields:
            missing = requested_fields - available_fields
            if missing:
                hints.append(f"Missing fields in data: {', '.join(sorted(missing))}")

        if field_name and available_fields:
            hints.append(f"Available fields: {', '.join(sorted(available_fields))}")

        hints.append(
            "Check that your database view returns all requested fields in the 'data' JSONB column",
        )

        super().__init__(
            message,
            query_context=query_context,
            hint=" | ".join(hints),
            code="PARTIAL_INSTANTIATION_ERROR",
            cause=cause,
        )


class WhereClauseError(FraiseQLException):
    """Raised when WHERE clause generation or validation fails."""

    def __init__(
        self,
        message: str,
        where_input: Optional[dict[str, Any]] = None,
        field_name: Optional[str] = None,
        operator: Optional[str] = None,
        supported_operators: Optional[list[str]] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        """Initialize WHERE clause error.

        Args:
            message: Error message
            where_input: The where input that caused the error
            field_name: Field name in the where clause
            operator: Operator that failed
            supported_operators: List of supported operators
            cause: Underlying exception
        """
        query_context = {}

        if where_input:
            query_context["where_input"] = where_input

        if field_name:
            query_context["field"] = field_name

        if operator:
            query_context["operator"] = operator

        # Generate hints
        hints = []

        if operator and supported_operators:
            hints.append(f"Supported operators: {', '.join(supported_operators)}")

        if operator == "_eq" and isinstance(where_input, dict):
            hints.append("For equality, use: {field_name: {_eq: value}}")

        if "_and" in str(where_input) or "_or" in str(where_input):
            hints.append(
                "Logical operators should contain arrays: {_and: [{condition1}, {condition2}]}",
            )

        super().__init__(
            message,
            query_context=query_context,
            hint=" | ".join(hints) if hints else None,
            code="WHERE_CLAUSE_ERROR",
            cause=cause,
        )


class QueryValidationError(FraiseQLException):
    """Raised when query validation fails."""

    def __init__(
        self,
        message: str,
        type_name: Optional[str] = None,
        invalid_fields: Optional[list[str]] = None,
        valid_fields: Optional[list[str]] = None,
        query_info: Optional[GraphQLResolveInfo] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        """Initialize query validation error.

        Args:
            message: Error message
            type_name: GraphQL type name
            invalid_fields: Fields that are invalid
            valid_fields: Valid fields for the type
            query_info: GraphQL resolve info
            cause: Underlying exception
        """
        query_context = {}

        if type_name:
            query_context["type"] = type_name

        if invalid_fields:
            query_context["invalid_fields"] = invalid_fields

        if query_info:
            query_context["operation"] = query_info.operation.operation.value
            if query_info.operation.name:
                query_context["operation_name"] = query_info.operation.name.value

        # Generate hints
        hints = []

        if invalid_fields and valid_fields:
            hints.append(f"Valid fields for {type_name}: {', '.join(sorted(valid_fields))}")

        if invalid_fields:
            for field in invalid_fields:
                # Check for common typos
                if valid_fields:
                    similar = [f for f in valid_fields if f.lower() == field.lower()]
                    if similar:
                        hints.append(f"Did you mean '{similar[0]}' instead of '{field}'?")

        super().__init__(
            message,
            query_context=query_context,
            hint=" | ".join(hints) if hints else None,
            code="QUERY_VALIDATION_ERROR",
            cause=cause,
        )


class DatabaseQueryError(FraiseQLException):
    """Raised when database query execution fails."""

    def __init__(
        self,
        message: str,
        sql: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
        view_name: Optional[str] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        """Initialize database query error.

        Args:
            message: Error message
            sql: SQL query that failed
            params: Query parameters
            view_name: Database view name
            cause: Underlying exception
        """
        query_context = {}

        if view_name:
            query_context["view"] = view_name

        if sql:
            # Truncate long SQL for readability
            query_context["sql"] = sql if len(sql) < 500 else sql[:500] + "..."

        if params:
            query_context["params"] = params

        # Generate hints based on common database errors
        hints = []

        error_msg = str(cause) if cause else message

        if "does not exist" in error_msg:
            if view_name:
                hints.append(
                    f"Create the view '{view_name}' or check the view name "
                    "in @fraise_type decorator",
                )
            hints.append("Run 'fraiseql generate views' to create missing views")

        if "permission denied" in error_msg:
            hints.append("Check database user permissions for the view")

        if "syntax error" in error_msg:
            hints.append("This might be a bug in FraiseQL's SQL generation. Please report it.")

        super().__init__(
            message,
            query_context=query_context,
            hint=" | ".join(hints) if hints else None,
            code="DATABASE_QUERY_ERROR",
            cause=cause,
        )


class TypeRegistrationError(FraiseQLException):
    """Raised when type registration fails."""

    def __init__(
        self,
        type_name: str,
        reason: str,
        existing_types: Optional[list[str]] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        """Initialize type registration error.

        Args:
            type_name: Name of the type that failed to register
            reason: Reason for registration failure
            existing_types: List of already registered types
            cause: Underlying exception
        """
        message = f"Failed to register type '{type_name}': {reason}"

        query_context = {
            "type": type_name,
            "reason": reason,
        }

        if existing_types:
            query_context["registered_types"] = sorted(existing_types)

        # Generate hints
        hints = []

        if "already registered" in reason.lower():
            hints.append("Each type name must be unique across your application")
            hints.append("Consider using a different name or checking for duplicate registrations")

        if "missing" in reason.lower() and "@fraise_type" in reason.lower():
            hints.append("Make sure to decorate your type with @fraise_type")

        super().__init__(
            message,
            query_context=query_context,
            hint=" | ".join(hints) if hints else None,
            code="TYPE_REGISTRATION_ERROR",
            cause=cause,
        )


class ResolverError(FraiseQLException):
    """Raised when a resolver fails."""

    def __init__(
        self,
        resolver_name: str,
        reason: str,
        query_info: Optional[GraphQLResolveInfo] = None,
        args: Optional[dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        """Initialize resolver error.

        Args:
            resolver_name: Name of the resolver that failed
            reason: Reason for failure
            query_info: GraphQL resolve info
            args: Arguments passed to the resolver
            cause: Underlying exception
        """
        message = f"Resolver '{resolver_name}' failed: {reason}"

        query_context = {
            "resolver": resolver_name,
        }

        if args:
            query_context["arguments"] = args

        if query_info:
            query_context["field"] = query_info.field_name
            if query_info.path is not None:
                query_context["path"] = query_info.path.as_list()

        # Generate hints
        hints = []

        if "connection" in reason.lower():
            hints.append("Check database connection and pool configuration")

        if "timeout" in reason.lower():
            hints.append("Query may be too complex or database may be slow")
            hints.append("Consider adding indexes or optimizing the query")

        super().__init__(
            message,
            query_context=query_context,
            hint=" | ".join(hints) if hints else None,
            code="RESOLVER_ERROR",
            cause=cause,
        )

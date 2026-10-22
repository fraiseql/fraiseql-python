"""Custom GraphQL execution with passthrough support."""

import asyncio
import json
import logging
from typing import Any, Optional

from graphql import (
    ExecutionResult,
    GraphQLError,
    GraphQLSchema,
    parse,
)

from fraiseql.core.rust_pipeline import RustResponseBytes

logger = logging.getLogger(__name__)


def _rust_response_bytes_middleware(next: Any, root: Any, info: Any, **kwargs: Any) -> Any:
    """Middleware to detect and capture RustResponseBytes from resolvers.

    This middleware wraps resolver execution and checks if the result is RustResponseBytes.
    If it is, we store it in the context so execute_graphql() can return it directly,
    bypassing GraphQL's type coercion and serialization.

    This is the key to the pass-through architecture: detect RustResponseBytes BEFORE
    GraphQL-core tries to serialize it. Without this, GraphQL would reject RustResponseBytes
    as a type error (e.g., "Expected Iterable but got RustResponseBytes").

    Args:
        next: Next resolver in the middleware chain
        root: Root value passed to resolver
        info: GraphQL resolve info containing context
        **kwargs: Additional resolver arguments

    Returns:
        The resolver result (unchanged) - RustResponseBytes is captured in context
    """
    result = next(root, info, **kwargs)

    # Handle async resolvers
    if asyncio.iscoroutine(result):

        async def async_wrapper():
            resolved = await result
            # Check if resolved value is RustResponseBytes
            if (
                isinstance(resolved, RustResponseBytes)
                and hasattr(info, "context")
                and isinstance(info.context, dict)
            ):
                _capture(info, resolved)
                logger.debug("Middleware captured RustResponseBytes from async resolver")
            return resolved

        return async_wrapper()

    # Check sync result
    if (
        isinstance(result, RustResponseBytes)
        and hasattr(info, "context")
        and isinstance(info.context, dict)
    ):
        _capture(info, result)
        logger.debug("Middleware captured RustResponseBytes from sync resolver")

    return result


def _capture(info: Any, response: RustResponseBytes) -> None:
    """Record a resolver's RustResponseBytes, with its response key, for execute_graphql()."""
    marker = info.context.get("__rust_response_bytes_marker__")
    if marker is None:
        return
    marker["rust_response"] = response
    path = getattr(info, "path", None)
    if path is not None and path.prev is None:
        marker["root_fields"][path.key] = response


def _merge_rust_responses(
    result: ExecutionResult, root_fields: dict[str, RustResponseBytes]
) -> ExecutionResult:
    """One result for an operation whose root fields include RustResponseBytes.

    Each RustResponseBytes holds a complete ``{"data": {<field>: ...}}`` response
    for its field; its value goes under the field's response key (its alias), in
    the operation's field order. graphql-core's errors about those fields (it can't
    complete RustResponseBytes) are dropped; errors Rust reported are kept.
    """
    data = dict(result.data or {})
    errors = [
        error for error in result.errors or [] if not (error.path and error.path[0] in root_fields)
    ]
    for key, response in root_fields.items():
        payload = json.loads(bytes(response))
        values = payload.get("data") or {}
        data[key] = values.get(key, next(iter(values.values()), None))
        errors.extend(
            GraphQLError(
                error.get("message", ""),
                path=error.get("path"),
                extensions=error.get("extensions"),
            )
            for error in payload.get("errors") or []
        )
    return ExecutionResult(data=data, errors=errors or None, extensions=result.extensions)


def _should_block_introspection(enable_introspection: bool, context_value: Any) -> tuple[bool, str]:
    """Check if introspection should be blocked based on configuration and authentication.

    Args:
        enable_introspection: Traditional boolean flag for introspection
        context_value: GraphQL context containing config and user information

    Returns:
        Tuple of (should_block, reason) indicating if introspection should be blocked
    """
    if not enable_introspection:
        # Traditional boolean-based blocking
        return True, "Introspection is disabled"

    if not context_value or not hasattr(context_value.get("config", {}), "introspection_policy"):
        # No policy configuration, use default (allow)
        return False, ""

    # New policy-based checking
    from fraiseql.fastapi.config import IntrospectionPolicy

    config = context_value.get("config", {})
    policy = getattr(config, "introspection_policy", IntrospectionPolicy.PUBLIC)

    if policy == IntrospectionPolicy.DISABLED:
        return True, "Introspection is disabled by policy"
    if policy == IntrospectionPolicy.PUBLIC:
        return False, ""
    if policy == IntrospectionPolicy.AUTHENTICATED:
        # Check if user is authenticated
        user_context = context_value.get("user")
        if not user_context:
            return True, "Introspection requires authentication"
        logger.info(f"Introspection allowed for authenticated user: {user_context}")
        return False, ""

    # Unknown policy, default to blocking for security
    return True, f"Unknown introspection policy: {policy}"


async def execute_graphql(
    schema: GraphQLSchema,
    source: str,
    root_value: Any = None,
    context_value: Any = None,
    variable_values: Optional[dict[str, Any]] = None,
    operation_name: Optional[str] = None,
    enable_introspection: bool = True,
) -> ExecutionResult | RustResponseBytes:
    """Execute GraphQL with unified Rust-first architecture and introspection control.

    All queries now use the unified Rust pipeline for optimal performance.

    This function implements the RustResponseBytes pass-through architecture:
    - Middleware detects when resolvers return RustResponseBytes
    - If detected, returns RustResponseBytes directly (bypassing GraphQL serialization)
    - Otherwise, returns standard ExecutionResult

    Args:
        schema: GraphQL schema to execute against
        source: GraphQL query string
        root_value: Root value for execution
        context_value: Context passed to resolvers
        variable_values: Query variables
        operation_name: Operation name for multi-operation documents
        enable_introspection: Whether to allow introspection queries (default: True)

    Returns:
        ExecutionResult containing the query result or validation errors, OR
        RustResponseBytes if the resolver returned it (direct pass-through for zero-copy)
    """
    # Parse the query
    try:
        document = parse(source)
    except Exception as e:
        return ExecutionResult(data=None, errors=[e])

    # Use standard GraphQL execution
    from graphql.execution import execute
    from graphql.validation import validate

    # Always validate the document against the schema
    validation_rules = []

    # Check if introspection should be blocked
    should_block_introspection, introspection_block_reason = _should_block_introspection(
        enable_introspection, context_value
    )

    # Add introspection validation rule if should be blocked
    if should_block_introspection:
        from graphql import NoSchemaIntrospectionCustomRule

        validation_rules.append(NoSchemaIntrospectionCustomRule)
        logger.info(f"Introspection blocked: {introspection_block_reason}")

    # Validate the document against the schema
    validation_errors = validate(schema, document, validation_rules or None)
    if validation_errors:
        if should_block_introspection and validation_rules:
            logger.warning(
                "Introspection query blocked: %s (reason: %s)",
                [err.message for err in validation_errors],
                introspection_block_reason,
            )
        else:
            logger.warning(
                "Schema validation failed: %s", [err.message for err in validation_errors]
            )
        return ExecutionResult(data=None, errors=validation_errors)

    # 🚀 RUST RESPONSE BYTES DETECTION:
    # Create a context wrapper that will capture RustResponseBytes if returned by resolvers
    # This allows us to detect it even if GraphQL-core rejects it due to type mismatch
    if context_value is None:
        context_value = {}

    # Add a special key to track if any resolver returns RustResponseBytes
    rust_response_marker: dict[str, Any] = {"rust_response": None, "root_fields": {}}
    if isinstance(context_value, dict):
        context_value["__rust_response_bytes_marker__"] = rust_response_marker

    result = execute(
        schema,
        document,
        root_value,
        context_value,
        variable_values,
        operation_name,
        middleware=[_rust_response_bytes_middleware],
    )

    # Handle async result if needed
    if asyncio.iscoroutine(result):
        result = await result

    # Ensure we have an ExecutionResult
    if not isinstance(result, ExecutionResult):
        raise TypeError(f"Expected ExecutionResult, got {type(result)}")

    # An operation with several root fields (two mutations, say) can't be answered
    # by one field's RustResponseBytes: merge them with the rest of the result
    root_fields = rust_response_marker["root_fields"]
    if root_fields and len(result.data or root_fields) > 1:
        logger.debug("Merging RustResponseBytes of %d root fields", len(root_fields))
        return _serialize_fraise_types_in_result(_merge_rust_responses(result, root_fields))

    # 🚀 RUST RESPONSE BYTES PASS-THROUGH:
    # Check if middleware captured RustResponseBytes from any resolver
    # If so, return it directly to bypass GraphQL serialization (zero-copy path)
    if rust_response_marker["rust_response"] is not None:
        logger.debug("Detected RustResponseBytes via middleware - returning directly")
        return rust_response_marker["rust_response"]

    # Fallback: Check if result.data contains RustResponseBytes (for cases without type mismatch)
    if isinstance(result.data, dict):
        for value in result.data.values():
            if isinstance(value, RustResponseBytes):
                logger.debug("Detected RustResponseBytes in result.data - returning directly")
                return value

    # Clean @fraise_type objects before returning to prevent JSON serialization issues
    cleaned_result = _serialize_fraise_types_in_result(result)
    return cleaned_result


def _serialize_fraise_types_in_result(result: ExecutionResult) -> ExecutionResult:
    """Convert @fraise_type objects to dicts for JSON serialization.

    This function processes the GraphQL ExecutionResult to convert any @fraise_type
    objects (those decorated with @fraiseql.type) into plain dictionaries that can
    be safely serialized to JSON. This prevents "Object of type X is not JSON
    serializable" errors when the GraphQL library attempts to serialize the response.

    Args:
        result: The ExecutionResult from GraphQL execution

    Returns:
        A new ExecutionResult with all @fraise_type objects converted to dicts
    """
    import logging

    logger = logging.getLogger(__name__)
    logger.info(f"_serialize_fraise_types_in_result called: has_data={result.data is not None}")

    if result.data:
        logger.info(f"Cleaning data of type: {type(result.data)}")
        cleaned_data = _clean_fraise_types(result.data)
        logger.info(f"Cleaned data type: {type(cleaned_data)}")
        return ExecutionResult(
            data=cleaned_data, errors=result.errors, extensions=result.extensions
        )
    return result


def _clean_fraise_types(obj: Any, _seen: set | None = None) -> Any:
    """Recursively convert @fraise_type objects to dictionaries.

    This function walks through a data structure and converts any objects that
    have the __fraiseql_definition__ attribute (indicating they are @fraise_type
    objects) into plain dictionaries using the same logic as FraiseQLJSONEncoder.

    Args:
        obj: The object to clean (can be dict, list, @fraise_type object, or primitive)
        _seen: Internal parameter to track seen objects and prevent infinite recursion

    Returns:
        The cleaned object with all @fraise_type objects converted to dicts
    """
    if _seen is None:
        _seen = set()

    # Debug logging at the start
    import logging

    logger = logging.getLogger(__name__)
    if hasattr(obj, "__class__"):
        logger.info(f"_clean_fraise_types called on: {obj.__class__.__name__}")

    # 🚀 DIRECT PATH: Handle RustResponseBytes - pass through as-is
    # RustResponseBytes is already the complete GraphQL response and should not be processed
    from fraiseql.core.rust_pipeline import RustResponseBytes

    if isinstance(obj, RustResponseBytes):
        logger.info("Detected RustResponseBytes - passing through directly")
        return obj

    # Handle FraiseQL types first (objects with __fraiseql_definition__)
    if hasattr(obj, "__fraiseql_definition__"):
        # Convert @fraise_type object to dictionary with recursive cleaning
        obj_dict = {}

        # Add __typename field for GraphQL union type resolution
        # This allows the GraphQL union resolver to identify the correct type
        if hasattr(obj, "__class__") and hasattr(obj.__class__, "__name__"):
            obj_dict["__typename"] = obj.__class__.__name__

            # CRITICAL FIX: Force errors array population for frontend compatibility
            # If this is an Error type with null errors field, auto-populate it
            class_name = obj.__class__.__name__

            # Debug logging
            import logging

            logger = logging.getLogger(__name__)
            logger.info(f"Processing object: {class_name}")
            logger.info(f"Has errors attr: {hasattr(obj, 'errors')}")
            if hasattr(obj, "errors"):
                logger.info(f"Errors value: {obj.errors}")
            logger.info(f"Has status attr: {hasattr(obj, 'status')}")
            logger.info(f"Has message attr: {hasattr(obj, 'message')}")

            if (
                class_name.endswith("Error")
                and hasattr(obj, "errors")
                and obj.errors is None
                and hasattr(obj, "status")
                and hasattr(obj, "message")
            ):
                # Create error structure from the status and message
                status = getattr(obj, "status", "")
                message = getattr(obj, "message", "Unknown error")

                # Extract error code and identifier from status
                if ":" in status:
                    error_code = 422  # Unprocessable Entity for noop: statuses
                    identifier = status.split(":", 1)[1] if ":" in status else "unknown_error"
                else:
                    error_code = 500  # Internal Server Error for other statuses
                    identifier = "general_error"

                # Create error object
                error_obj = {
                    "code": error_code,
                    "identifier": identifier,
                    "message": message,
                    "details": {},
                }

                obj_dict["errors"] = [error_obj]
                # Also force-set on the original object to ensure consistency
                obj.errors = [error_obj]

        for attr_name in dir(obj):
            # Skip private attributes, methods, and special FraiseQL attributes
            if (
                not attr_name.startswith("_")
                and not attr_name.startswith("__gql_")
                and not attr_name.startswith("__fraiseql_")
                and not callable(getattr(obj, attr_name, None))
            ):
                value = getattr(obj, attr_name, None)
                if value is not None:
                    # Recursively clean the value
                    obj_dict[attr_name] = _clean_fraise_types(value, _seen)
        return obj_dict

    # Handle Python Enums (convert to their value)
    if hasattr(obj, "__class__") and hasattr(obj.__class__, "__bases__"):
        import enum

        if isinstance(obj, enum.Enum):
            return obj.value

    # Handle circular references for non-@fraise_type objects
    obj_id = id(obj)
    is_complex = isinstance(obj, (dict, list)) or (
        hasattr(obj, "__dict__") and not isinstance(obj, (str, int, float, bool, type(None)))
    )

    if is_complex and obj_id in _seen:
        return obj  # Return as-is to break circular reference

    # Add complex objects to seen set
    if is_complex:
        _seen.add(obj_id)

    try:
        # Handle lists - recursively clean each item
        if isinstance(obj, list):
            return [_clean_fraise_types(item, _seen) for item in obj]

        # Handle dicts - recursively clean each value
        if isinstance(obj, dict):
            return {k: _clean_fraise_types(v, _seen) for k, v in obj.items()}

        # Handle objects with __dict__ that might contain @fraise_type objects
        if hasattr(obj, "__dict__") and not isinstance(obj, (str, int, float, bool, type(None))):
            # For objects that aren't primitives, check their attributes
            cleaned_obj = obj
            for attr_name in dir(obj):
                if not attr_name.startswith("_") and hasattr(obj, attr_name):
                    attr_value = getattr(obj, attr_name, None)
                    if attr_value is not None and not callable(attr_value):
                        cleaned_value = _clean_fraise_types(attr_value, _seen)
                        # Only modify if the value actually changed
                        if cleaned_value is not attr_value:
                            # Create a copy to avoid modifying the original
                            if cleaned_obj is obj:
                                import copy

                                cleaned_obj = copy.copy(obj)
                            setattr(cleaned_obj, attr_name, cleaned_value)
            return cleaned_obj

        # Return primitives and other objects as-is
        return obj

    finally:
        # Remove from seen set when done processing
        if is_complex:
            _seen.discard(obj_id)

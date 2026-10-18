"""Rust-first mutation executor.

PostgreSQL -> Rust -> HTTP bytes (zero Python parsing)
"""

import json
import logging
from typing import Any, Type

from fraiseql.core.rust_pipeline import RustResponseBytes
from fraiseql.utils.casing import dict_keys_to_snake_case

logger = logging.getLogger(__name__)

# Statuses the Rust pipeline answers with the error type (MutationStatus::from_str)
_ERROR_STATUS_PREFIXES = (
    "failed:",
    "validation:",
    "unauthorized:",
    "forbidden:",
    "not_found:",
    "conflict:",
    "timeout:",
    "noop:",
)

# SQL functions _warn_if_untyped_entity has warned about, once each per process
_warned_untyped_entity: set[str] = set()


def _warn_if_untyped_entity(function_name: str, result: dict[str, Any]) -> None:
    """Warn once per SQL function about a success entity that gets no __typename.

    Called when the caller had no entity type to pass (the entity field is an interface
    or union, or unknown). Rust then names the entity after the result's entity_type, or
    keeps a __typename from its data; with neither, the entity has no __typename.
    """
    if function_name in _warned_untyped_entity:
        return
    if "status" in result:
        status = str(result["status"]).lower()
        if status.startswith(_ERROR_STATUS_PREFIXES) or result.get("entity_type"):
            return
        entity = result.get("entity")
    else:
        entity = result  # Simple format: the result is the entity
    if not isinstance(entity, dict) or "__typename" in entity:
        return
    _warned_untyped_entity.add(function_name)
    logger.warning(
        "SQL function %s returned an entity without entity_type; __typename left out",
        function_name,
    )


def _get_fraiseql_rs():
    """Lazy-load Rust extension."""
    try:
        import importlib

        return importlib.import_module("fraiseql._fraiseql_rs")
    except ImportError as e:
        raise ImportError(
            "fraiseql Rust extension not available. "
            "Reinstall: pip install --force-reinstall fraiseql"
        ) from e


async def execute_mutation_rust(
    conn: Any,
    function_name: str,
    input_data: dict[str, Any],
    field_name: str,
    success_type: str,
    error_type: str,
    entity_field_name: str | None = None,
    entity_type: str | None = None,
    context_args: list[Any] | None = None,
    cascade_selections: str | None = None,
    config: Any | None = None,
    success_type_class: Type | None = None,
    success_type_fields: list[str] | None = None,
    error_type_fields: list[str] | None = None,
    entity_selections: str | None = None,
) -> RustResponseBytes:
    """Execute mutation via Rust-first pipeline.

    Supports both simple format (just entity JSONB) and full mutation_response format.
    Rust auto-detects the format based on presence of 'status' field.

    Args:
        conn: PostgreSQL async connection
        function_name: Full function name (e.g., "app.create_user")
        input_data: Mutation input as dict
        field_name: GraphQL field name (e.g., "createUser")
        success_type: GraphQL success type name
        error_type: GraphQL error type name
        entity_field_name: Field name for entity (e.g., "user")
        entity_type: Entity type for __typename (e.g., "User") when the result's
            entity_type is NULL; None for an entity field typed as an interface or union
        context_args: Optional context arguments
        cascade_selections: Optional cascade selections JSON
        config: Optional FraiseQLConfig instance. If None, uses global config.
        success_type_class: Python Success type class for entity flattening.
            If provided, will flatten entity JSONB fields to match Success type schema.
        success_type_fields: List of field names expected in Success type for validation.
        error_type_fields: List of field names expected in Error type for field selection.
        entity_selections: Optional entity field selections JSON (GitHub issue #525).
            Specifies which fields to include in nested entity objects.

    Returns:
        RustResponseBytes ready for HTTP response
    """
    fraiseql_rs = _get_fraiseql_rs()

    # Get config if not provided
    if config is None:
        try:
            from fraiseql.gql.builders.registry import SchemaRegistry

            registry = SchemaRegistry.get_instance()
            config = registry.config if registry else None
        except (ImportError, AttributeError):
            config = None

    # Extract auto_camel_case from config (default True for backward compatibility)
    auto_camel_case = getattr(config, "auto_camel_case", True) if config else True

    # Convert input keys to snake_case before serializing to JSON for PostgreSQL
    # This ensures jsonb_populate_record() works correctly with composite types
    # that use snake_case field names (PostgreSQL convention)
    if auto_camel_case:
        input_data = dict_keys_to_snake_case(input_data)

    # Convert input to JSON
    input_json = json.dumps(input_data, separators=(",", ":"))

    # Build SQL query using psycopg placeholders (%s)
    # Wrap with row_to_json() to handle composite type returns as JSON
    if context_args:
        placeholders = ", ".join(["%s"] * len(context_args))
        query = f"SELECT row_to_json({function_name}({placeholders}, %s::jsonb))"
        params = (*context_args, input_json)
    else:
        query = f"SELECT row_to_json({function_name}(%s::jsonb))"
        params = (input_json,)

    # Execute query
    async with conn.cursor() as cursor:
        await cursor.execute(query, params)
        row = await cursor.fetchone()

    # Handle no result
    if not row or row[0] is None:
        error_json = json.dumps(
            {
                "status": "failed:no_result",
                "message": "No result returned from mutation",
                "entity_id": None,
                "entity_type": None,
                "entity": None,
                "updated_fields": None,
                "cascade": None,
                "metadata": None,
            }
        )
        response_bytes = fraiseql_rs.build_mutation_response(
            error_json,
            field_name,
            success_type,
            error_type,
            entity_field_name,
            entity_type,
            None,  # cascade_selections
            auto_camel_case,  # Pass config flag
            success_type_fields,  # Success type field list
            error_type_fields,  # Error type field list
            None,  # entity_selections (not needed for error case)
        )
        return RustResponseBytes(response_bytes)

    # Get mutation result
    mutation_result = row[0]

    # Handle different result types from psycopg
    if isinstance(mutation_result, dict):
        # psycopg returned a dict (from JSONB or row_to_json composite)
        # Check for mutation_response format (has 'status' and 'entity' fields)
        if "status" in mutation_result and "entity" in mutation_result:
            # mutation_response format from row_to_json - pass through as-is
            pass
        elif "object_data" in mutation_result:
            # Legacy composite type format - convert to mutation_response
            mutation_result = {
                "entity_id": str(mutation_result.get("id")) if mutation_result.get("id") else None,
                "updated_fields": mutation_result.get("updated_fields"),
                "status": mutation_result.get("status"),
                "message": mutation_result.get("message"),
                "entity": mutation_result.get("object_data"),  # object_data -> entity
                "metadata": mutation_result.get("extra_metadata"),  # extra_metadata -> metadata
                "entity_type": (
                    mutation_result.get("extra_metadata", {}).get("entity")
                    if isinstance(mutation_result.get("extra_metadata"), dict)
                    else None
                ),
                "cascade": None,
            }

        if entity_type is None:
            _warn_if_untyped_entity(function_name, mutation_result)
        mutation_json = json.dumps(mutation_result, separators=(",", ":"), default=str)
    elif isinstance(mutation_result, tuple):
        # psycopg returned a tuple from composite type
        # mutation_response order:
        # (status, message, entity_id, entity_type, entity, updated_fields, cascade, metadata)
        if len(mutation_result) == 8:
            # mutation_response format
            composite_dict = {
                "status": mutation_result[0],
                "message": mutation_result[1],
                "entity_id": str(mutation_result[2]) if mutation_result[2] else None,
                "entity_type": mutation_result[3],
                "entity": mutation_result[4],
                "updated_fields": list(mutation_result[5]) if mutation_result[5] else None,
                "cascade": mutation_result[6],
                "metadata": mutation_result[7],
            }
        else:
            # Legacy format: (id, updated_fields, status, message, object_data, extra_metadata)
            composite_dict = {
                "entity_id": str(mutation_result[0]) if mutation_result[0] else None,
                "updated_fields": list(mutation_result[1]) if mutation_result[1] else None,
                "status": mutation_result[2],
                "message": mutation_result[3],
                "entity": mutation_result[4],  # object_data -> entity
                "metadata": mutation_result[5],  # extra_metadata -> metadata
                "cascade": None,
            }
            # Extract entity_type from metadata if present
            if composite_dict["metadata"] and isinstance(composite_dict["metadata"], dict):
                composite_dict["entity_type"] = composite_dict["metadata"].get("entity")
        if entity_type is None:
            _warn_if_untyped_entity(function_name, composite_dict)
        mutation_json = json.dumps(composite_dict, separators=(",", ":"), default=str)
    elif isinstance(mutation_result, str):
        # Already a JSON string
        mutation_json = mutation_result
    else:
        # Unknown type - try to convert to JSON
        mutation_json = json.dumps(mutation_result, separators=(",", ":"), default=str)

    # Transform via Rust (auto-detects simple vs full format)
    response_bytes = fraiseql_rs.build_mutation_response(
        mutation_json,
        field_name,
        success_type,
        error_type,
        entity_field_name,
        entity_type,
        cascade_selections,
        auto_camel_case,  # Pass config flag
        success_type_fields,  # Pass field list for schema validation
        error_type_fields,  # Pass error type field list for auto-injection
        entity_selections,  # Pass entity field selections (GitHub issue #525)
    )

    # Validate Rust response structure
    # Parse the response to check for required fields
    try:
        response_dict = json.loads(response_bytes.decode("utf-8"))
        data = response_dict.get("data", {})
        mutation_result = data.get(field_name)

        if mutation_result and isinstance(mutation_result, dict):
            typename = mutation_result.get("__typename")

            # Success type: entity must be non-null
            if typename == success_type:
                entity_field = entity_field_name or "entity"
                if entity_field in mutation_result and mutation_result[entity_field] is None:
                    raise ValueError(
                        f"Success type '{typename}' returned null entity. "
                        f"This indicates a logic error in the mutation or Rust pipeline. "
                        f"Validation failures should return Error type, not Success type."
                    )

            # Error type: code field must be present
            elif typename == error_type:
                if "code" not in mutation_result:
                    raise ValueError(
                        f"Error type '{typename}' missing required 'code' field. "
                        f"Ensure Rust pipeline includes code field."
                    )
                if not isinstance(mutation_result["code"], int):
                    raise ValueError(
                        f"Error type '{typename}' has invalid 'code' type: {type(mutation_result['code'])}. "  # noqa: E501
                        f"Expected int (422, 404, 409, 500)."
                    )

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        # If we can't parse the response, log warning but don't fail
        # This preserves backward compatibility during migration
        logger.warning(f"Could not validate Rust response structure: {e}")

    return RustResponseBytes(response_bytes, schema_type=success_type)

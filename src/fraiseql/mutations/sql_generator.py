"""Serialize input dataclasses into PostgreSQL JSON function calls.

This module includes utilities for converting dataclass-based GraphQL inputs into
SQL-safe JSON objects for use with PostgreSQL functions. Supports common types like
UUIDs, enums, IP addresses, and nested dataclasses. Fields set to `fraiseql.UNSET`
are automatically excluded from the resulting JSON object.
"""

import datetime
import enum
import ipaddress
import json
import logging
import uuid
from collections.abc import Mapping
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass

from psycopg import sql
from psycopg.types.json import Jsonb

from fraiseql.db import DatabaseQuery
from fraiseql.sql.identifiers import qualified_identifier
from fraiseql.types.definitions import UNSET
from fraiseql.utils.casing import to_snake_case

logger = logging.getLogger(__name__)


def _serialize_basic(value: object) -> object:
    if isinstance(value, uuid.UUID | ipaddress.IPv4Address | ipaddress.IPv6Address):
        return str(value)
    if isinstance(value, datetime.date | datetime.datetime):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def _serialize_value(value: object, field_type: object = None) -> object:
    if value is UNSET:
        return None

    result: object

    if isinstance(value, str):
        result = value.strip()
    elif is_dataclass(value):
        result = {
            f.name: _serialize_value(getattr(value, f.name), f.type)
            for f in dataclass_fields(value)
            if getattr(value, f.name) is not UNSET
        }
    elif hasattr(value, "__fraiseql_definition__"):
        # Handle FraiseQL input objects (not dataclasses but similar structure)
        result = {
            field_name: _serialize_value(getattr(value, field_name), field_type)
            for field_name, field_type in value.__annotations__.items()
            if hasattr(value, field_name) and getattr(value, field_name) is not UNSET
        }
    elif isinstance(value, list):
        result = [_serialize_value(v) for v in value if v is not UNSET]
        if not result and field_type and getattr(field_type, "__origin__", None) is list:
            args = getattr(field_type, "__args__", [])
            if args and args[0] is uuid.UUID:
                result = []
    elif isinstance(value, dict):
        # Convert camelCase keys to snake_case for consistent database field naming
        # This ensures nested input objects use the same field naming convention
        # as direct input objects, fixing the inconsistency described in the issue
        result = {to_snake_case(k): _serialize_value(v) for k, v in value.items() if v is not UNSET}
    else:
        result = _serialize_basic(value)

    return result


def generate_insert_json_call(
    *,
    input_object: object,
    context: Mapping[str, object],
    sql_function_name: str,
    context_keys: tuple[str, ...] = ("tenant_id", "contact_id"),
) -> DatabaseQuery:
    """Serialize a dataclass instance to a JSON SQL function call.

    Converts the given input dataclass into a JSON object and generates a
    parameterized SQL call to a PostgreSQL function. Fields with value `UNSET`
    are skipped and not included in the resulting JSON payload.
    """
    if not is_dataclass(input_object):
        msg = "Expected a dataclass instance for `input_object`"
        raise TypeError(msg)

    json_data = {
        f.name: _serialize_value(value, f.type)
        for f in dataclass_fields(input_object)
        if (value := getattr(input_object, f.name)) is not UNSET
    }

    try:
        json.dumps(json_data)
    except TypeError as e:
        logger.exception(
            "❌ Failed to serialize input JSON for SQL function '%s'",
            sql_function_name,
        )
        msg = f"Cannot serialize input JSON for '{sql_function_name}': {e}"
        raise TypeError(msg) from e

    params = {f"auth_{key}": context[key] for key in context_keys if key in context}
    params["input_json"] = Jsonb(json_data)

    placeholders = [sql.Placeholder(f"auth_{key}") for key in context_keys if key in context]
    placeholders.append(sql.Placeholder("input_json"))

    statement = sql.SQL("SELECT * FROM {}({})").format(
        qualified_identifier(sql_function_name),
        sql.SQL(", ").join(placeholders),
    )

    return DatabaseQuery(
        statement=statement,
        params=params,
        fetch_result=True,
    )

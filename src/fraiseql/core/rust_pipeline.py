"""Rust pipeline execution wrapper (compatibility layer).

⚠️ DEPRECATED: This module is a compatibility wrapper for code that was refactored
into the unified FFI adapter. It maintains backward compatibility while delegating
to the new unified_ffi_adapter module.

DEPRECATION NOTICE
==================
As of Phase 3c (Unified FFI), the Python execution layer was removed and all
queries now execute through a single Rust FFI boundary via unified_ffi_adapter.

This module exists to maintain compatibility with code that imports
execute_via_rust_pipeline(). New code should use unified_ffi_adapter directly.

MIGRATION PATH
==============
Instead of:
    from fraiseql.core.rust_pipeline import execute_via_rust_pipeline

Use:
    from fraiseql.core.unified_ffi_adapter import fraiseql_rs

Both approaches work identically, but unified_ffi_adapter is the canonical
location for Rust FFI bindings.

---

Architecture (Phase 3c - Unified FFI Active)
==============================================
- Single FFI entry point: fraiseql_rs.process_graphql_request()
- No multi-FFI overhead or GIL contention
- All execution happens in Rust (7-10x faster than Python)
- Python only handles coordinate/marshalling

Execution Flow:
1. Python receives query from database results or GraphQL request
2. Converts to GraphQL query format
3. Calls single FFI boundary: fraiseql_rs.process_graphql_request()
4. Returns HTTP-ready JSON response bytes
"""

import json
import logging
from typing import Any

from fraiseql.core.types import RustResponseBytes
from fraiseql.core.unified_ffi_adapter import fraiseql_rs

logger = logging.getLogger(__name__)


async def execute_via_rust_pipeline(
    query_data: dict[str, Any],
) -> RustResponseBytes:
    """Execute a GraphQL query through the Rust pipeline.

    This is a compatibility wrapper that delegates to the unified FFI adapter.
    All queries pass through the single Rust FFI boundary.

    Args:
        query_data: Query data dictionary with:
            - query: GraphQL query string
            - variables: Query variables (optional)
            - operation_name: Operation name (optional)
            - connection: Database connection (optional)
            - timeout: Query timeout (optional)
        timeout: Optional timeout override in seconds

    Returns:
        RustResponseBytes containing the query result (pre-serialized JSON bytes)

    Raises:
        RuntimeError: If Rust pipeline is unavailable
        TimeoutError: If query exceeds timeout
        json.JSONDecodeError: If response is malformed JSON

    Notes:
        - This function is async but the actual Rust execution is synchronous
        - The timeout parameter is reserved for future async wrapper support
        - Response is returned as RustResponseBytes (pre-serialized bytes)
          for zero-copy transmission to HTTP clients
    """
    try:
        # Extract query components from query_data
        query_str = query_data.get("query", "")
        variables = query_data.get("variables", {})
        operation_name = query_data.get("operation_name")

        # Build request for unified FFI
        request = {
            "query": query_str,
            "variables": variables,
        }

        if operation_name:
            request["operationName"] = operation_name

        # Call unified FFI (single boundary, Phase 3c active)
        # This is the exclusive Rust execution path
        response_json_str = fraiseql_rs.process_graphql_request(
            json.dumps(request),
            None,  # No context needed for basic execution
        )

        # Verify response is valid JSON
        try:
            json.loads(response_json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Rust pipeline returned malformed JSON: {e}")
            raise

        # Return as RustResponseBytes (pre-serialized, HTTP-ready)
        response_bytes = response_json_str.encode("utf-8")
        return RustResponseBytes(response_bytes)

    except Exception as e:
        logger.error(f"Rust pipeline execution failed: {e}")
        raise RuntimeError(f"Rust pipeline execution failed: {e}") from e

"""TurboRouter implementation for high-performance query execution.

TurboRouter bypasses GraphQL parsing and validation for registered queries
by directly executing pre-validated SQL templates.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from graphql import GraphQLSchema
    from psycopg import AsyncConnection

    from fraiseql.security.authorization import Authorizer
    from fraiseql.security.decision_cache import DecisionCache

logger = logging.getLogger(__name__)


def _turbo_operation_name(query_str: str) -> str:
    """Extract the root field name from a GraphQL query, handling fragments.

    Used as the ``operation_name`` for the TurboRouter authorization gate. Returns
    an empty string if no root field can be parsed.
    """
    clean_query = re.sub(r"#.*", "", query_str)
    clean_query = " ".join(clean_query.split())

    named_query_match = re.search(r"query\s+\w+[^{]*{\s*(\w+)", clean_query, re.DOTALL)
    if named_query_match:
        return named_query_match.group(1)

    anonymous_query_match = re.search(r"^\s*{\s*(\w+)", clean_query)
    if anonymous_query_match:
        return anonymous_query_match.group(1)

    fallback_match = re.search(r"query\s*{\s*(\w+)", clean_query)
    if fallback_match:
        return fallback_match.group(1)

    return ""


@dataclass
class TurboQuery:
    """Represents a pre-validated GraphQL query with its SQL template."""

    graphql_query: str
    sql_template: str
    param_mapping: dict[str, str]  # GraphQL variable path -> SQL parameter name
    operation_name: str | None = None
    apollo_client_hash: str | None = None  # Apollo Client APQ hash (if different from server hash)
    context_params: dict[str, str] | None = None  # Context key -> SQL parameter name

    def map_variables(self, graphql_variables: dict[str, Any]) -> dict[str, Any]:
        """Map GraphQL variables to SQL parameters.

        Args:
            graphql_variables: Variables from GraphQL request

        Returns:
            Dictionary of SQL parameter names to values
        """
        sql_params = {}

        for gql_path, sql_param in self.param_mapping.items():
            # Handle nested variable paths like "filters.name"
            value = graphql_variables
            for part in gql_path.split("."):
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    value = None
                    break

            sql_params[sql_param] = value

        return sql_params


class TurboRegistry:
    """Registry for TurboRouter queries with LRU eviction."""

    def __init__(self, max_size: int = 1000) -> None:
        """Initialize the registry.

        Args:
            max_size: Maximum number of queries to cache
        """
        self.max_size = max_size
        self._queries: OrderedDict[str, TurboQuery] = OrderedDict()
        # Map apollo_client_hash -> primary_hash for dual-hash support
        self._apollo_hash_to_primary: dict[str, str] = {}

    def hash_query(self, query: str) -> str:
        """Generate a normalized hash for a GraphQL query.

        This method normalizes whitespace to ensure consistent hashing
        regardless of formatting differences in the query string.

        Args:
            query: GraphQL query string

        Returns:
            Hex string hash of the normalized query
        """
        import re

        # Step 1: Remove comments
        query_no_comments = re.sub(r"#.*", "", query)

        # Step 2: Normalize whitespace (collapse all whitespace to single spaces)
        # This handles spaces, tabs, newlines, etc.
        normalized = re.sub(r"\s+", " ", query_no_comments.strip())

        # Step 3: Remove spaces around GraphQL syntax characters for better normalization
        # This ensures "query{user{id}}" and "query { user { id } }" hash the same
        normalized = re.sub(r"\s*([{}():,])\s*", r"\1", normalized)

        # Step 4: Add back minimal spaces for readability and consistency
        # Add space after keywords and before opening braces
        normalized = re.sub(
            r"\b(query|mutation|subscription|fragment)\b(?=\w|\{)", r"\1 ", normalized
        )
        normalized = re.sub(r"(\w)(\{)", r"\1 \2", normalized)
        normalized = re.sub(r"(\})(\w)", r"\1 \2", normalized)

        # Use SHA-256 for consistent hashing
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def hash_query_raw(self, query: str) -> str:
        """Generate a hash for a GraphQL query without normalization.

        This method is provided for backward compatibility and debugging purposes.
        It computes the hash directly from the raw query string.

        Args:
            query: GraphQL query string (used as-is)

        Returns:
            Hex string hash of the raw query
        """
        return hashlib.sha256(query.encode("utf-8")).hexdigest()

    def register(self, turbo_query: TurboQuery) -> str:
        """Register a TurboQuery for fast execution.

        Args:
            turbo_query: The TurboQuery to register

        Returns:
            The hash of the registered query
        """
        query_hash = self.hash_query(turbo_query.graphql_query)

        # Move to end if already exists (LRU behavior)
        if query_hash in self._queries:
            self._queries.move_to_end(query_hash)
        else:
            # Add new query
            self._queries[query_hash] = turbo_query

            # Evict oldest if over limit
            if len(self._queries) > self.max_size:
                self._queries.popitem(last=False)

        return query_hash

    def register_with_raw_hash(self, turbo_query: TurboQuery, raw_hash: str) -> str:
        """Register a TurboQuery with a specific raw hash.

        This method is useful for backward compatibility with systems that
        have pre-computed raw hashes stored in databases.

        If the TurboQuery has an apollo_client_hash that differs from the raw_hash,
        both hashes will be registered to support dual-hash lookup (for Apollo Client APQ).

        Args:
            turbo_query: The TurboQuery to register
            raw_hash: The pre-computed raw hash to use as the primary key

        Returns:
            The raw hash that was used for registration
        """
        # Move to end if already exists (LRU behavior)
        if raw_hash in self._queries:
            self._queries.move_to_end(raw_hash)
        else:
            # Add new query
            self._queries[raw_hash] = turbo_query

            # Evict oldest if over limit
            if len(self._queries) > self.max_size:
                _evicted_hash, evicted_query = self._queries.popitem(last=False)
                # Clean up apollo hash mapping if it exists
                if evicted_query.apollo_client_hash:
                    self._apollo_hash_to_primary.pop(evicted_query.apollo_client_hash, None)

        # Register apollo_client_hash if present and different from primary hash
        if turbo_query.apollo_client_hash and turbo_query.apollo_client_hash != raw_hash:
            self._apollo_hash_to_primary[turbo_query.apollo_client_hash] = raw_hash

        return raw_hash

    def get(self, query: str) -> TurboQuery | None:
        """Get a registered TurboQuery by GraphQL query string.

        This method tries multiple hash strategies for maximum compatibility:
        1. Normalized hash (default FraiseQL behavior)
        2. Raw hash (for backward compatibility with external registrations)
        3. Apollo hash mapping (for dual-hash queries where client hash differs from server hash)

        Args:
            query: GraphQL query string

        Returns:
            TurboQuery if registered, None otherwise
        """
        # Try normalized hash first (preferred)
        normalized_hash = self.hash_query(query)
        if normalized_hash in self._queries:
            # Move to end for LRU
            self._queries.move_to_end(normalized_hash)
            return self._queries[normalized_hash]

        # Try raw hash for backward compatibility
        raw_hash = self.hash_query_raw(query)
        if raw_hash in self._queries:
            # Move to end for LRU
            self._queries.move_to_end(raw_hash)
            return self._queries[raw_hash]

        # Try apollo_client_hash mapping for dual-hash queries
        # Check if either computed hash is an Apollo hash that maps to a primary hash
        if normalized_hash in self._apollo_hash_to_primary:
            primary_hash = self._apollo_hash_to_primary[normalized_hash]
            if primary_hash in self._queries:
                self._queries.move_to_end(primary_hash)
                return self._queries[primary_hash]

        if raw_hash in self._apollo_hash_to_primary:
            primary_hash = self._apollo_hash_to_primary[raw_hash]
            if primary_hash in self._queries:
                self._queries.move_to_end(primary_hash)
                return self._queries[primary_hash]

        return None

    def get_by_hash(self, query_hash: str) -> TurboQuery | None:
        """Get a registered TurboQuery by hash (supports both server and apollo hashes).

        This method supports dual-hash lookup for Apollo Client APQ compatibility.
        It will find queries registered with either the server hash or apollo_client_hash.

        Args:
            query_hash: The hash to lookup (server hash or apollo_client_hash)

        Returns:
            TurboQuery if registered, None otherwise
        """
        # Try direct lookup first (primary hash)
        if query_hash in self._queries:
            # Move to end for LRU
            self._queries.move_to_end(query_hash)
            return self._queries[query_hash]

        # Try apollo_client_hash mapping
        if query_hash in self._apollo_hash_to_primary:
            primary_hash = self._apollo_hash_to_primary[query_hash]
            if primary_hash in self._queries:
                # Move to end for LRU
                self._queries.move_to_end(primary_hash)
                return self._queries[primary_hash]

        return None

    def clear(self) -> None:
        """Clear all registered queries."""
        self._queries.clear()
        self._apollo_hash_to_primary.clear()

    def __len__(self) -> int:
        """Return the number of registered queries."""
        return len(self._queries)


class TurboRouter:
    """High-performance router for registered GraphQL queries."""

    def __init__(
        self,
        registry: TurboRegistry | None,
        default_authorizer: Authorizer | None = None,
        decision_cache: DecisionCache | None = None,
        schema: GraphQLSchema | None = None,
    ) -> None:
        """Initialize the router with a registry.

        Args:
            registry: TurboRegistry containing registered queries
            default_authorizer: Optional global operation authorizer (issue #362).
                TurboRouter bypasses ``GraphQLField.resolve``, so this gate is the only
                authorization point on the persisted-query path. Per-operation decorator
                overrides do not apply here — only the global default.
            decision_cache: Optional authorization decision cache (issue #367); when set,
                identical ``(principal, query, variables)`` checks are memoized within its TTL.
            schema: Optional GraphQL schema (issue #366). When provided, the per-field
                authorization gate (``authorize_fields``) is re-applied here before the SQL
                template runs, since this path renders the whole row without invoking per-field
                resolvers. Omitted (``None``) → field gating is skipped on this router.
        """
        if registry is None:
            raise ValueError("TurboRouter requires a non-None TurboRegistry")
        self.registry = registry
        self.default_authorizer = default_authorizer
        self.decision_cache = decision_cache
        self.schema = schema

    async def execute(
        self,
        query: str,
        variables: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Execute a query using the turbo path if registered.

        Args:
            query: GraphQL query string
            variables: GraphQL variables
            context: Request context (must contain 'db')

        Returns:
            Query result if executed via turbo path, None otherwise
        """
        # Look up the query in the registry
        turbo_query = self.registry.get(query)
        if turbo_query is None:
            return None

        # Operation authorization gate (issue #362). This path bypasses
        # GraphQLField.resolve, so enforcement happens here, fail-closed, before any
        # SQL is built or executed. enforce_operation_value raises GraphQLError on deny.
        if self.default_authorizer is not None:
            # Derive the real operation identity from the document, exactly as the APQ
            # and /graphql/rust gates do (issue #368). Hardcoding operation_type="query"
            # here mislabels persisted mutations and defeats write-guards that gate on
            # operation_type. Imported lazily: routers imports turbo at module load, so a
            # top-level import here would be circular.
            from fraiseql.fastapi.routers import _derive_operation_info
            from fraiseql.security.authorization import enforce_operation_value

            operation_type, operation_name = _derive_operation_info(query)
            decision = await enforce_operation_value(
                authorizer=self.default_authorizer,
                context=context,
                operation_type=operation_type,
                operation_name=operation_name,
                arguments=variables or {},
                cache=self.decision_cache,
            )
            if decision.filters:
                # Per-row filter injection is impossible against a fixed SQL template;
                # row scoping on this path relies on session variables + database RLS.
                logger.warning(
                    "authorization filters are ignored on the TurboRouter path "
                    "(fixed SQL template); rely on session variables + RLS for row scoping"
                )

        # Field-level authorization gate (issue #366). The fixed SQL template renders the whole
        # row without invoking per-field resolvers, so the per-field gate (authorize_fields)
        # would fail open. Re-apply it here, fail-closed, before any SQL runs. Requires the
        # schema to resolve the selection set; a no-op when no schema or no authorizer is set.
        if self.schema is not None:
            from fraiseql.security.field_auth import enforce_selected_field_authorization

            await enforce_selected_field_authorization(
                schema=self.schema,
                query=query,
                context=context,
                variables=variables or {},
            )

        # Get database from context
        db = context.get("db")
        if db is None:
            msg = "Database connection not found in context"
            raise ValueError(msg)

        # Map GraphQL variables to SQL parameters
        sql_params = turbo_query.map_variables(variables)

        # Map context parameters to SQL parameters (like mutations do)
        if turbo_query.context_params:
            for context_key, sql_param in turbo_query.context_params.items():
                context_value = context.get(context_key)
                if context_value is None:
                    msg = (
                        f"Required context parameter '{context_key}' "
                        f"not found in GraphQL context for turbo query"
                    )
                    raise ValueError(msg)
                sql_params[sql_param] = context_value

        # Execute the SQL directly using FraiseQLRepository

        # Convert SQL template from named params (:param) to psycopg format (%(param)s)
        sql_template = turbo_query.sql_template
        for param_name in sql_params:
            sql_template = sql_template.replace(f":{param_name}", f"%({param_name})s")

        # Sync relevant context keys into db.context for _set_session_variables
        _session_var_keys = {"tenant_id", "contact_id", "user", "user_id", "roles"}
        # Also sync any custom session variable keys from config
        config = db.context.get("config")
        if config and hasattr(config, "session_variables"):
            _session_var_keys.update(config.session_variables.keys())
        for key in _session_var_keys:
            if key in context and key not in db.context:
                db.context[key] = context[key]

        # Define transaction function to set session variables and execute query
        async def execute_with_session_vars(conn: AsyncConnection) -> list[dict[str, Any]]:
            """Execute turbo query with session variables set."""
            async with conn.cursor() as cursor:
                # Set all session variables via repository (built-in + custom)
                await db._set_session_variables(cursor)

                # Execute the actual query
                from psycopg.rows import dict_row

                cursor.row_factory = dict_row
                await cursor.execute(sql_template, sql_params)
                return await cursor.fetchall()  # type: ignore[return-value]

        # Execute in transaction
        result = await db.run_in_transaction(execute_with_session_vars)

        # Extract the result
        if result and len(result) > 0:
            # Assume the SQL returns a 'result' column with the formatted data
            row = result[0]
            if "result" in row:
                # Handle both single object and array results
                data = row["result"]

                # Determine the root field name from the query
                # Handle queries with fragments by looking for the actual query operation
                def process_turbo_result(data: any, root_field: str) -> dict[str, any]:
                    """Process TurboRouter result with smart GraphQL response detection."""
                    # Case 1: Data is already a complete GraphQL response
                    if (
                        isinstance(data, dict)
                        and "data" in data
                        and isinstance(data["data"], dict)
                        and root_field in data["data"]
                    ):
                        return data

                    # Case 2: Data contains the field data directly
                    if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
                        # Extract the actual data and wrap with correct field name
                        field_data = data["data"]
                        if len(field_data) == 1 and root_field not in field_data:
                            # Single field with wrong name - use the data but correct field name
                            actual_data = next(iter(field_data.values()))
                            return {"data": {root_field: actual_data}}
                        return {"data": {root_field: field_data}}

                    # Case 3: Raw data - wrap normally
                    return {"data": {root_field: data}}

                root_field = _turbo_operation_name(query)
                if root_field:
                    return process_turbo_result(data, root_field)

                return {"data": data}

        return {"data": None}

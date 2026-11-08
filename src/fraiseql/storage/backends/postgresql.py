"""PostgreSQL-based APQ storage backend for FraiseQL."""

import json
import logging
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Optional

from .base import APQStorageBackend

logger = logging.getLogger(__name__)

_TABLE_PREFIX_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*\.)?[A-Za-z_][A-Za-z0-9_]*$")


class PostgreSQLAPQBackend(APQStorageBackend):
    """PostgreSQL APQ storage backend with tenant isolation.

    Stores persisted queries and cached responses in two PostgreSQL tables, so they
    survive restarts and are shared by every instance that uses the same database.

    The backend interface is synchronous, so the backend uses its own small synchronous
    connection pool (``psycopg_pool.ConnectionPool``), opened on first use, not the
    application's async pool. Each lookup is one indexed query; the text of a persisted
    query is also kept in process once read, since a hash always names the same text.
    ``blocking_io`` is set, so the ``/graphql`` route makes its calls in a worker
    thread, not on the event loop.

    Features:
    - Tables created on first use (``auto_create_tables``)
    - Tenant-isolated response caching
    - Graceful error handling: a failed read is a miss, a failed write is logged
    """

    blocking_io = True  # one query per call: the request path calls it in a worker thread

    def __init__(
        self,
        config: dict[str, Any],
        pool: Optional[Any] = None,
        *,
        database_url: str | None = None,
        response_ttl: int | None = None,
    ) -> None:
        """Initialize the PostgreSQL backend with configuration.

        Nothing connects here: the pool is opened, and the tables created, on first use.

        Args:
            config: Backend configuration (``apq_backend_config``)
                - database_url: Database to store APQ data in (default: the
                  ``database_url`` argument, i.e. the app's ``database_url``)
                - table_prefix: Prefix for the APQ table names, optionally with a
                  schema (``"myschema.apq_"``) (default: "apq_")
                - auto_create_tables: Whether to create tables automatically (default: True)
                - connection_timeout: Seconds to wait for a connection (default: 30)
                - pool_max_size: Maximum connections in the backend's pool (default: 4)
            pool: Optional synchronous ``psycopg_pool.ConnectionPool`` to use instead of
                opening one
            database_url: Database URL used when ``config`` has none
            response_ttl: Seconds a cached response stays valid; ``None`` or 0 means it
                does not expire
        """
        self._config = config
        self._table_prefix = config.get("table_prefix", "apq_")
        if not _TABLE_PREFIX_PATTERN.match(self._table_prefix):
            raise ValueError(f"Invalid APQ table_prefix: {self._table_prefix!r}")
        self._queries_table = f"{self._table_prefix}queries"
        self._responses_table = f"{self._table_prefix}responses"
        self._auto_create_tables = config.get("auto_create_tables", True)
        self._connection_timeout = config.get("connection_timeout", 30)
        self._database_url = config.get("database_url") or database_url
        self._response_ttl = response_ttl or None
        self._pool_max_size = config.get("pool_max_size", 4)

        if pool is not None:
            from psycopg_pool import AsyncConnectionPool

            if isinstance(pool, AsyncConnectionPool):
                raise TypeError(
                    "PostgreSQLAPQBackend needs a synchronous psycopg_pool.ConnectionPool; "
                    "pass database_url to let it open one"
                )
        self._pool = pool
        self._owns_pool = False
        self._lock = threading.Lock()
        self._tables_lock = threading.Lock()
        self._tables_ready = not self._auto_create_tables
        self._query_text_cache: dict[str, str] = {}

        logger.debug(
            f"PostgreSQL APQ backend initialized: "
            f"queries_table={self._queries_table}, "
            f"responses_table={self._responses_table}"
        )

    def get_persisted_query(self, hash_value: str) -> Optional[str]:
        """Retrieve stored query by hash.

        Args:
            hash_value: SHA256 hash of the persisted query

        Returns:
            GraphQL query string if found, None otherwise
        """
        if not hash_value:
            return None

        cached = self._query_text_cache.get(hash_value)
        if cached is not None:
            return cached

        try:
            sql = f"SELECT query FROM {self._queries_table} WHERE hash = %s"
            result = self._fetch_one(sql, (hash_value,))

            if result:
                logger.debug(f"Retrieved APQ query with hash {hash_value[:8]}...")
                self._query_text_cache[hash_value] = result[0]
                return result[0]
            logger.debug(f"APQ query not found for hash {hash_value[:8]}...")
            return None

        except Exception as e:
            logger.warning(f"Failed to retrieve persisted query: {e}")
            return None

    def store_persisted_query(self, hash_value: str, query: str) -> None:
        """Store query by hash.

        Args:
            hash_value: SHA256 hash of the query
            query: GraphQL query string to store

        Raises:
            ValueError: If ``hash_value`` is not the SHA-256 of ``query`` (a database
                failure is logged, not raised)
        """
        from fraiseql.storage.apq_store import check_query_hash

        check_query_hash(hash_value, query)
        try:
            self._execute_query(self._upsert_query_sql(), (hash_value, query))
            self._query_text_cache[hash_value] = query
            logger.debug(f"Stored APQ query with hash {hash_value[:8]}...")

        except Exception as e:
            logger.warning(f"Failed to store persisted query: {e}")

    def register_queries(self, queries: list[str]) -> dict[str, str]:
        """Register queries in one transaction; raises if they can't be stored.

        Unlike ``store_persisted_query``, a failure is not swallowed: registering the
        pre-approved queries of ``apq_mode='required'`` must not fail silently.
        """
        from fraiseql.storage.apq_store import compute_query_hash

        result = {compute_query_hash(query): query for query in queries}
        if not result:
            return result
        with self._connection() as conn, conn.transaction(), conn.cursor() as cursor:
            cursor.executemany(self._upsert_query_sql(), list(result.items()))
        self._query_text_cache.update(result)
        return result

    def get_cached_response(
        self, hash_value: str, context: Optional[dict[str, Any]] = None
    ) -> Optional[dict[str, Any]]:
        """Get cached JSON response for APQ hash with tenant isolation.

        Args:
            hash_value: SHA256 hash of the persisted query
            context: Optional request context containing user/tenant information

        Returns:
            Cached GraphQL response dict if found and not expired, None otherwise
        """
        if not hash_value:
            return None

        try:
            # Extract tenant_id from context
            tenant_id = self.extract_tenant_id(context) if context else None

            # Query with tenant isolation
            if tenant_id:
                sql = (
                    f"SELECT response FROM {self._responses_table} "
                    f"WHERE hash = %s AND tenant_id = %s"
                )
                params: tuple = (hash_value, tenant_id)
                log_suffix = f" for tenant {tenant_id}"
            else:
                sql = (
                    f"SELECT response FROM {self._responses_table} "
                    f"WHERE hash = %s AND tenant_id IS NULL"
                )
                params = (hash_value,)
                log_suffix = " (global)"
            if self._response_ttl:
                sql += " AND updated_at > NOW() - make_interval(secs => %s)"
                params = (*params, self._response_ttl)

            result = self._fetch_one(sql, params)

            if result:
                logger.debug(f"Retrieved cached response for hash {hash_value[:8]}...{log_suffix}")
                response = result[0]
                # psycopg decodes jsonb to a dict; a str comes from other drivers or mocks
                return json.loads(response) if isinstance(response, str) else response
            logger.debug(f"Cached response not found for hash {hash_value[:8]}...{log_suffix}")
            return None

        except Exception as e:
            logger.warning(f"Failed to retrieve cached response: {e}")
            return None

    def store_cached_response(
        self, hash_value: str, response: dict[str, Any], context: Optional[dict[str, Any]] = None
    ) -> None:
        """Store pre-computed JSON response for APQ hash with tenant isolation.

        Args:
            hash_value: SHA256 hash of the persisted query
            response: GraphQL response dict to cache
            context: Optional request context containing user/tenant information
        """
        try:
            # Extract tenant_id from context
            tenant_id = self.extract_tenant_id(context) if context else None
            response_json = json.dumps(response)

            # Store with tenant isolation (the unique index treats NULL as '')
            sql = f"""
                INSERT INTO {self._responses_table} (hash, tenant_id, response, created_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (hash, COALESCE(tenant_id, '')) DO UPDATE SET
                    response = EXCLUDED.response,
                    updated_at = NOW()
            """
            self._execute_query(sql, (hash_value, tenant_id, response_json))

            log_suffix = f" for tenant {tenant_id}" if tenant_id else " (global)"
            logger.debug(f"Stored cached response for hash {hash_value[:8]}...{log_suffix}")

        except Exception as e:
            logger.warning(f"Failed to store cached response: {e}")

    def close(self) -> None:
        """Close the connection pool the backend opened (a pool passed in is left open)."""
        if self._owns_pool and self._pool is not None:
            self._pool.close()
            self._pool = None
            self._owns_pool = False

    def _upsert_query_sql(self) -> str:
        return f"""
            INSERT INTO {self._queries_table} (hash, query, created_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (hash) DO UPDATE SET
                query = EXCLUDED.query,
                updated_at = NOW()
        """

    def _ensure_tables_exist(self, conn: Any) -> None:
        """Create the APQ tables on ``conn`` if they don't exist."""
        conn.execute(self._get_create_queries_table_sql())
        for statement in self._get_create_responses_table_sql().split(";"):
            if statement.strip():
                conn.execute(statement)
        logger.debug("APQ tables ensured to exist")

    def _get_create_queries_table_sql(self) -> str:
        """Get SQL for creating the queries table."""
        return f"""
            CREATE TABLE IF NOT EXISTS {self._queries_table} (
                hash VARCHAR(64) PRIMARY KEY,
                query TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """

    def _get_create_responses_table_sql(self) -> str:
        """Get SQL for creating the responses table with tenant support.

        One row per (hash, tenant): a unique index on ``(hash, COALESCE(tenant_id, ''))``,
        since a primary key cannot hold an expression or a nullable column.
        """
        index_base = self._responses_table.replace(".", "_")
        return f"""
            CREATE TABLE IF NOT EXISTS {self._responses_table} (
                hash VARCHAR(64) NOT NULL,
                tenant_id VARCHAR(255),
                response JSONB NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            CREATE UNIQUE INDEX IF NOT EXISTS {index_base}_hash_tenant_key
                ON {self._responses_table} (hash, COALESCE(tenant_id, ''));
            CREATE INDEX IF NOT EXISTS idx_{index_base}_tenant
                ON {self._responses_table} (tenant_id) WHERE tenant_id IS NOT NULL;
        """

    def _get_connection(self) -> Any:
        """Return the connection pool, opening it on first use."""
        if self._pool is None:
            with self._lock:
                if self._pool is None:
                    if not self._database_url:
                        raise RuntimeError(
                            "PostgreSQL APQ backend has no database: set database_url "
                            "(apq_backend_config or the app's database_url)"
                        )
                    from psycopg_pool import ConnectionPool

                    self._pool = ConnectionPool(
                        self._database_url,
                        min_size=1,
                        max_size=self._pool_max_size,
                        timeout=self._connection_timeout,
                        kwargs={"autocommit": True},
                        open=True,
                        name="fraiseql-apq",
                    )
                    self._owns_pool = True
        return self._pool

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        """Yield a pooled connection, creating the tables on first use."""
        with self._get_connection().connection() as conn:
            if not self._tables_ready:
                # Calls run in worker threads: create the tables once.
                with self._tables_lock:
                    if not self._tables_ready:
                        self._ensure_tables_exist(conn)
                        self._tables_ready = True
            yield conn

    def _execute_query(self, sql: str, params: Optional[tuple] = None) -> None:
        """Execute a SQL statement.

        Args:
            sql: SQL query to execute
            params: Query parameters
        """
        with self._connection() as conn:
            conn.execute(sql, params or ())

    def _fetch_one(self, sql: str, params: Optional[tuple] = None) -> Optional[tuple]:
        """Fetch one row from a SQL query.

        Args:
            sql: SQL query to execute
            params: Query parameters

        Returns:
            First row as tuple or None if no results
        """
        with self._connection() as conn:
            return conn.execute(sql, params or ()).fetchone()

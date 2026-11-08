"""CQRS Repository base class for FraiseQL."""

from typing import Any, TypeVar
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.sql import SQL, Composed, Literal

from fraiseql.sql.where_generator import _make_filter_field_composed

from .executor import CQRSExecutor

T = TypeVar("T")


class CQRSRepository:
    """Base repository implementing CQRS pattern with views and SQL functions.

    This repository provides a clean separation between read and write operations
    following the Command Query Responsibility Segregation (CQRS) pattern. Write
    operations are performed through PostgreSQL functions while read operations
    query materialized views or tables directly.

    The repository handles:
    - Command operations (create, update, delete) via SQL functions
    - Query operations (read, list, search) via direct SQL with JSONB
    - Pagination, filtering, and sorting
    - Relationship loading (one-to-many, many-to-many)
    - Batch operations for performance
    - Transaction management

    Example:
        ```python
        async with get_db_connection() as conn:
            repo = CQRSRepository(conn)

            # Create a new user
            user = await repo.create("user", {
                "name": "John Doe",
                "email": "john@example.com"
            })

            # Query users with filtering
            users = await repo.list_entities(
                User,
                where={"status": {"eq": "active"}},
                order_by=[("created_at", "DESC")],
                limit=10
            )

            # Load relationships
            user_with_posts = await repo.load_one_to_many(
                user, "posts", Post, "user_id"
            )
        ```

    Note:
        This repository assumes PostgreSQL with JSONB support and requires
        appropriate SQL functions and views to be created in the database.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        """Initialize repository with database connection."""
        self.connection = connection
        self.executor = CQRSExecutor(connection)

    # Command methods (write operations via SQL functions)

    async def create(self, entity_type: str, input_data: dict[str, Any]) -> dict[str, Any]:
        """Create an entity using SQL function.

        Args:
            entity_type: Type of entity to create (e.g., 'user', 'post')
            input_data: Dictionary of input data

        Returns:
            Result dictionary from SQL function
        """
        function_name = f"fn_create_{entity_type.lower()}"
        return await self.executor.execute_function(function_name, input_data)

    async def update(self, entity_type: str, input_data: dict[str, Any]) -> dict[str, Any]:
        """Update an entity using SQL function.

        Args:
            entity_type: Type of entity to update
            input_data: Dictionary of input data (must include 'id')

        Returns:
            Result dictionary from SQL function
        """
        function_name = f"fn_update_{entity_type.lower()}"
        return await self.executor.execute_function(function_name, input_data)

    async def delete(self, entity_type: str, entity_id: UUID) -> dict[str, Any]:
        """Delete an entity using SQL function.

        Args:
            entity_type: Type of entity to delete
            entity_id: ID of entity to delete

        Returns:
            Result dictionary from SQL function
        """
        function_name = f"fn_delete_{entity_type.lower()}"
        return await self.executor.execute_function(function_name, {"id": str(entity_id)})

    async def call_function(self, function_name: str, input_data: dict[str, Any]) -> dict[str, Any]:
        """Call a custom SQL function.

        Args:
            function_name: Name of the SQL function
            input_data: Dictionary of input data

        Returns:
            Result dictionary from SQL function
        """
        return await self.executor.execute_function(function_name, input_data)

    # Alias for mutations
    execute_function = call_function

    # Query methods (read operations from views)

    async def get_by_id(self, view_name: str, entity_id: UUID) -> dict[str, Any] | None:
        """Get an entity by ID from the read view.

        Args:
            view_name: Name of the view (e.g., 'v_users')
            entity_id: ID of the entity

        Returns:
            Dictionary with camelCase fields or None if not found
        """
        async with self.connection.cursor() as cursor:
            await cursor.execute(
                SQL("SELECT data FROM {} WHERE id = %s").format(SQL(view_name)),
                (entity_id,),
            )
            result = await cursor.fetchone()

            if not result:
                return None

            return result[0]

    async def query(
        self,
        view_name: str,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query entities from read view with filtering and pagination.

        Args:
            view_name: Name of the view (e.g., 'v_posts')
            filters: Optional filters to apply (with camelCase keys)
            order_by: Optional ordering
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of dictionaries with camelCase fields
        """
        # Build query using SQL composition
        query_parts = [SQL("SELECT data FROM {} WHERE 1=1").format(SQL(view_name))]

        # Apply filters using proper WHERE clause generation
        if filters:
            for key, value in filters.items():
                if isinstance(value, dict):
                    # Map GraphQL field names to operator strategy names
                    # nin (GraphQL) -> notin (operator strategy)
                    mapped_value = {}
                    for op, val in value.items():
                        if op == "nin":
                            mapped_value["notin"] = val
                        else:
                            mapped_value[op] = val

                    # Use proper WHERE clause generation for operator filters
                    # e.g., {"name": {"contains": "router"}} -> data->>'name' LIKE '%router%'
                    where_condition = _make_filter_field_composed(key, mapped_value, "data", None)
                    if where_condition:
                        query_parts.append(SQL(" AND "))
                        query_parts.append(where_condition)
                elif isinstance(value, list):
                    # Handle array contains queries - use Literal for safety
                    query_parts.append(SQL(" AND data->{} ?| ").format(Literal(key)))
                    query_parts.append(Literal(value))
                else:
                    # Handle simple equality (backward compatibility) - use Literal for safety
                    query_parts.append(SQL(" AND data->>{} = ").format(Literal(key)))
                    # Convert booleans to lowercase strings to match JSON format
                    if isinstance(value, bool):
                        query_parts.append(Literal(str(value).lower()))
                    else:
                        query_parts.append(Literal(str(value)))

        # Apply ordering
        if order_by:
            # Parse order_by (e.g., "createdAt_desc" -> "createdAt DESC")
            parts = order_by.split("_")
            if parts[-1].lower() in ("asc", "desc"):
                direction = parts[-1].upper()
                field = "_".join(parts[:-1])
            else:
                direction = "ASC"
                field = order_by

            order_sql = SQL(" ORDER BY data->>{} ").format(Literal(field))
            if direction == "DESC":
                order_sql += SQL("DESC")
            else:
                order_sql += SQL("ASC")
            query_parts.append(order_sql)

        # Apply pagination - use Literal for consistency
        query_parts.append(SQL(" LIMIT "))
        query_parts.append(Literal(limit))
        query_parts.append(SQL(" OFFSET "))
        query_parts.append(Literal(offset))

        # Compose final query
        query = Composed(query_parts)

        # Execute query (no params needed - everything is in Literals)
        async with self.connection.cursor() as cursor:
            await cursor.execute(query)
            results = await cursor.fetchall()

            return [row[0] for row in results]

    async def query_raw(self, query: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        """Execute a raw query and return results.

        Args:
            query: SQL query to execute
            params: Optional query parameters

        Returns:
            List of result dictionaries
        """
        async with self.connection.cursor() as cursor:
            await cursor.execute(SQL(query), params or [])
            results = await cursor.fetchall()
            return [row[0] if len(row) == 1 else dict(row) for row in results]

    # Generic methods for more flexible usage

    async def select_from_json_view(
        self,
        view_name: str,
        *,
        where: dict[str, Any] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Select from a JSON view with optional filtering.

        This is a more generic alternative to specific query methods.

        Args:
            view_name: Name of the view (e.g., 'v_users')
            where: Optional WHERE conditions (uses camelCase keys)
            order_by: Optional ORDER BY clause
            limit: Optional LIMIT
            offset: Optional OFFSET (default 0)

        Returns:
            List of dictionaries with camelCase fields

        Example:
            users = await repo.select_from_json_view(
                "v_users",
                where={"isActive": True},
                order_by="createdAt DESC",
                limit=10
            )
        """
        return await self.query(
            view_name=view_name,
            filters=where,
            order_by=order_by,
            limit=limit or 100,  # Default limit to prevent accidental large queries
            offset=offset,
        )

    async def select_one_from_json_view(
        self,
        view_name: str,
        *,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Select a single record from a JSON view.

        Args:
            view_name: Name of the view (e.g., 'v_users')
            where: Optional WHERE conditions (uses camelCase keys)

        Returns:
            Single dictionary with camelCase fields or None

        Example:
            user = await repo.select_one_from_json_view(
                "v_users",
                where={"email": "user@example.com"}
            )
        """
        results = await self.select_from_json_view(view_name, where=where, limit=1)
        return results[0] if results else None

    async def query_interface(
        self,
        interface_view_name: str,
        *,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query from an interface view (UNION ALL view) with polymorphic type information.

        Interface views should include a '__typename' field to identify the concrete type.

        Example interface view SQL:
            CREATE VIEW v_node AS
            SELECT id, data || jsonb_build_object('__typename', 'User') as data
            FROM users
            UNION ALL
            SELECT id, data || jsonb_build_object('__typename', 'Article') as data
            FROM articles
            UNION ALL
            SELECT id, data || jsonb_build_object('__typename', 'Page') as data
            FROM pages;

        Args:
            interface_view_name: Name of the interface view (e.g., 'v_node', 'v_publishable')
            filters: Optional filters to apply
            order_by: Optional ordering
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of dictionaries with type information preserved

        Example:
            nodes = await repo.query_interface(
                "v_node",
                filters={"created_at": {"$gt": "2024-01-01"}},
                order_by="created_at DESC",
                limit=10
            )
        """
        # Build query using SQL composition
        query_parts = [SQL("SELECT data FROM {} WHERE 1=1").format(SQL(interface_view_name))]
        params = []

        # Apply filters
        if filters:
            for key, value in filters.items():
                if isinstance(value, dict):
                    # Handle operators like $gt, $lt, etc
                    for op, val in value.items():
                        if op == "$gt":
                            query_parts.append(SQL(" AND data->>{} > %s").format(Literal(key)))
                            params.append(str(val))
                        elif op == "$lt":
                            query_parts.append(SQL(" AND data->>{} < %s").format(Literal(key)))
                            params.append(str(val))
                        elif op == "$gte":
                            query_parts.append(SQL(" AND data->>{} >= %s").format(Literal(key)))
                            params.append(str(val))
                        elif op == "$lte":
                            query_parts.append(SQL(" AND data->>{} <= %s").format(Literal(key)))
                            params.append(str(val))
                elif isinstance(value, list):
                    query_parts.append(SQL(" AND data->{} ?| %s").format(Literal(key)))
                    params.append(value)
                else:
                    query_parts.append(SQL(" AND data->>{} = %s").format(Literal(key)))
                    params.append(str(value))

        # Apply ordering
        if order_by:
            parts = order_by.split(" ")
            field = parts[0]
            direction = parts[1].upper() if len(parts) > 1 else "ASC"
            order_sql = SQL(" ORDER BY data->>{} ").format(Literal(field))
            if direction == "DESC":
                order_sql += SQL("DESC")
            else:
                order_sql += SQL("ASC")
            query_parts.append(order_sql)

        # Apply limit and offset
        if limit:
            query_parts.append(SQL(" LIMIT %s"))
            params.append(limit)
        if offset:
            query_parts.append(SQL(" OFFSET %s"))
            params.append(offset)

        # Compose final query
        query = Composed(query_parts)

        # Execute query
        async with self.connection.cursor() as cursor:
            await cursor.execute(query, params)
            results = await cursor.fetchall()
            return [row[0] for row in results]

    async def get_polymorphic_by_id(
        self,
        interface_view_name: str,
        entity_id: UUID,
        type_mapping: dict[str, type] | None = None,
    ) -> Any | None:
        """Get a polymorphic entity by ID from an interface view.

        Args:
            interface_view_name: Name of the interface view
            entity_id: ID of the entity
            type_mapping: Optional mapping of __typename values to Python types

        Returns:
            Entity instance or dictionary if type mapping not provided

        Example:
            user = await repo.get_polymorphic_by_id(
                "v_node",
                user_id,
                {"User": User, "Article": Article, "Page": Page}
            )
        """
        async with self.connection.cursor() as cursor:
            await cursor.execute(
                SQL("SELECT data FROM {} WHERE id = %s").format(SQL(interface_view_name)),
                (entity_id,),
            )
            result = await cursor.fetchone()

            if not result:
                return None

            data = result[0]

            # If type mapping provided and __typename exists, instantiate the correct type
            if type_mapping and "__typename" in data:
                type_name = data["__typename"]
                if type_name in type_mapping:
                    # Remove __typename before instantiation
                    entity_data = {k: v for k, v in data.items() if k != "__typename"}
                    return type_mapping[type_name](**entity_data)

            return data

    async def paginate(
        self,
        view_name: str,
        *,
        first: int | None = None,
        after: str | None = None,
        last: int | None = None,
        before: str | None = None,
        filters: dict[str, Any] | None = None,
        order_by: str = "id",
        order_direction: str = "ASC",
        include_total: bool = True,
    ) -> dict[str, Any]:
        """Paginate query results using PostgreSQL cursors.

        This method provides efficient cursor-based pagination following
        the Relay connection specification.

        Args:
            view_name: Database view to query
            first: Number of items to fetch forward
            after: Cursor to start after (forward pagination)
            last: Number of items to fetch backward
            before: Cursor to end before (backward pagination)
            filters: Optional WHERE clause filters
            order_by: Field to order by (must be unique)
            order_direction: ASC or DESC
            include_total: Whether to include total count

        Returns:
            Dictionary with edges, page_info, and optional total_count

        Example:
            result = await repo.paginate(
                "v_posts",
                first=20,
                after=cursor,
                filters={"author_id": user_id},
                order_by="created_at",
                order_direction="DESC"
            )

            # Convert to typed Connection
            from fraiseql import Connection
            posts_connection = Connection[Post].from_dict(result)
        """
        from .pagination import paginate_query as _paginate_query

        return await _paginate_query(
            self,
            view_name,
            first=first,
            after=after,
            last=last,
            before=before,
            filters=filters,
            order_by=order_by,
            order_direction=order_direction,
            include_total=include_total,
        )

    # Batch operations

    async def batch_create(
        self,
        entity_type: str,
        inputs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Batch create multiple entities.

        Args:
            entity_type: Type of entity to create
            inputs: List of input dictionaries

        Returns:
            List of result dictionaries
        """
        results = []
        for input_data in inputs:
            result = await self.create(entity_type, input_data)
            results.append(result)
        return results

    async def batch_update(
        self,
        entity_type: str,
        updates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Batch update multiple entities.

        Args:
            entity_type: Type of entity to update
            updates: List of update dictionaries (must include 'id')

        Returns:
            List of result dictionaries
        """
        results = []
        for update_data in updates:
            result = await self.update(entity_type, update_data)
            results.append(result)
        return results

    async def batch_delete(
        self,
        entity_type: str,
        entity_ids: list[UUID],
    ) -> list[dict[str, Any]]:
        """Batch delete multiple entities.

        Args:
            entity_type: Type of entity to delete
            entity_ids: List of entity IDs to delete

        Returns:
            List of result dictionaries
        """
        results = []
        for entity_id in entity_ids:
            result = await self.delete(entity_type, entity_id)
            results.append(result)
        return results

    # Transaction support

    def transaction(self) -> Any:
        """Create a transaction context manager.

        Returns:
            Transaction context manager
        """
        return self.connection.transaction()

    # Utility methods

    def _convert_order_by_to_tuples(self, order_by: Any) -> list[tuple[str, str]] | None:
        """Convert any OrderBy format to list of tuples.

        Args:
            order_by: OrderBy in any format (GraphQL dicts, tuples, OrderBySet)

        Returns:
            List of (field, direction) tuples or None
        """
        if not order_by:
            return None

        # Already a list of tuples
        if isinstance(order_by, list) and order_by and isinstance(order_by[0], tuple):
            return order_by

        # GraphQL format - convert using FraiseQL
        if isinstance(order_by, (list, dict)):
            try:
                from fraiseql.sql.graphql_order_by_generator import _convert_order_by_input_to_sql

                order_by_set = _convert_order_by_input_to_sql(order_by)
                if order_by_set:
                    return [(instr.field, instr.direction) for instr in order_by_set.instructions]
            except ImportError:
                pass

        # OrderBySet object
        if hasattr(order_by, "instructions"):
            return [(instr.field, instr.direction) for instr in order_by.instructions]

        return None

    def _get_view_name(self, entity_class: type) -> str:
        """Get view name for an entity class.

        Args:
            entity_class: Entity class

        Returns:
            View name (e.g., 'vw_user')
        """
        # Convert class name to snake_case and add vw_ prefix
        class_name = entity_class.__name__
        # Simple conversion: CamelCase -> snake_case
        import re

        snake_case = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", class_name).lower()
        return f"vw_{snake_case}"

    def _get_function_name(self, operation: str, entity_type: str) -> str:
        """Get function name for an operation.

        Args:
            operation: Operation type (create, update, delete)
            entity_type: Entity type

        Returns:
            Function name (e.g., 'fn_create_user')
        """
        return f"fn_{operation}_{entity_type}"

    # Query execution

    async def execute_query(
        self,
        query: str | SQL | Composed,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a raw SQL query.

        Args:
            query: SQL query (string or composed)
            params: Optional parameters

        Returns:
            List of result dictionaries
        """
        return await self.executor.execute_query(query, params)

    # Alias methods for backward compatibility and common patterns

    async def find_by_id(self, entity_class: type[T], entity_id: UUID) -> dict[str, Any] | None:
        """Find entity by ID using entity class.

        Args:
            entity_class: Entity class to determine view name
            entity_id: ID of the entity

        Returns:
            Entity dict or None
        """
        view_name = self._get_view_name(entity_class)
        return await self.get_by_id(view_name, entity_id)

    async def list_entities(
        self,
        entity_class: type[T],
        *,
        where: dict[str, Any] | None = None,
        order_by: list[tuple[str, str]] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List entities with optional filtering and ordering.

        Args:
            entity_class: Entity class to determine view name
            where: Optional WHERE conditions
            order_by: Optional ordering as list of (field, direction) tuples
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of entity dictionaries
        """
        view_name = self._get_view_name(entity_class)

        # Convert order_by to tuples, then to string format
        order_by_str = None
        if order_by:
            # First, ensure we have tuples regardless of input format
            order_by_tuples = self._convert_order_by_to_tuples(order_by)
            if order_by_tuples:
                parts = []
                for field, direction in order_by_tuples:
                    parts.append(f"{field} {direction}")
                order_by_str = ", ".join(parts)

        return await self.select_from_json_view(
            view_name,
            where=where,
            order_by=order_by_str,
            limit=limit,
            offset=offset,
        )

    async def find_by_view(
        self,
        view_name: str,
        *,
        where: dict[str, Any] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Find entities by view name with optional filtering.

        Args:
            view_name: Name of the database view
            where: Optional WHERE conditions
            order_by: Optional ORDER BY clause
            limit: Maximum number of results

        Returns:
            List of entity dictionaries
        """
        return await self.select_from_json_view(
            view_name,
            where=where,
            order_by=order_by,
            limit=limit,
        )

    async def count(
        self,
        entity_class: type[T],
        *,
        where: dict[str, Any] | None = None,
    ) -> int:
        """Count entities in a view with optional filtering.

        Args:
            entity_class: Entity class to determine view name
            where: Optional WHERE conditions

        Returns:
            Count of matching entities
        """
        view_name = self._get_view_name(entity_class)

        # Build count query
        query_parts = [SQL("SELECT COUNT(*) FROM {}").format(SQL(view_name))]
        params = []

        if where:
            query_parts.append(SQL(" WHERE "))
            conditions = []
            for key, value in where.items():
                if isinstance(value, dict) and "eq" in value:
                    # Handle GraphQL where format
                    conditions.append(SQL("data->>{} = %s").format(Literal(key)))
                    params.append(str(value["eq"]))
                else:
                    conditions.append(SQL("data->>{} = %s").format(Literal(key)))
                    params.append(str(value))
            query_parts.append(SQL(" AND ").join(conditions))

        query = Composed(query_parts)

        async with self.connection.cursor() as cursor:
            await cursor.execute(query, params)
            result = await cursor.fetchone()
            return result[0] if result else 0

    async def exists(
        self,
        entity_class: type[T],
        entity_id: UUID,
    ) -> bool:
        """Check if an entity exists by ID.

        Args:
            entity_class: Entity class to determine view name
            entity_id: ID of the entity to check

        Returns:
            True if entity exists
        """
        result = await self.find_by_id(entity_class, entity_id)
        return result is not None

    # Note: FraiseQL Philosophy on Relationships
    # =========================================
    # In FraiseQL, relationships should be composed at the database view level,
    # not loaded separately in application code. This ensures:
    # 1. Single query for all data (no N+1 problems)
    # 2. Better performance through PostgreSQL optimization
    # 3. GraphQL schema matches database view structure
    # 4. Simpler application code
    #
    # Example view with relationships:
    # CREATE VIEW user_view AS
    # SELECT
    #     u.id,
    #     jsonb_build_object(
    #         'id', u.id,
    #         'name', u.name,
    #         'posts', COALESCE(
    #             (SELECT jsonb_agg(jsonb_build_object(
    #                 'id', p.id,
    #                 'title', p.title
    #             )) FROM posts p WHERE p.user_id = u.id),
    #             '[]'::jsonb
    #         )
    #     ) as data
    # FROM users u;
    #
    # This is why we don't have load_one_to_many or load_many_to_many methods.

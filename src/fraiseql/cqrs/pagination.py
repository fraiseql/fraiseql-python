"""PostgreSQL cursor-based pagination for FraiseQL.

This module provides native cursor-based pagination using PostgreSQL's capabilities,
returning results in the Connection[T] format for GraphQL compatibility.
"""

import base64
from typing import Any, TypeVar

from psycopg import AsyncConnection
from psycopg.sql import SQL, Literal

from fraiseql.db import _view_identifier

from .repository import CQRSRepository

T = TypeVar("T")


def encode_cursor(value: str) -> str:
    """Encode a cursor value to base64 for opaque cursor handling."""
    return base64.b64encode(value.encode()).decode()


def decode_cursor(cursor: str) -> str:
    """Decode a base64 cursor back to its original value."""
    return base64.b64decode(cursor.encode()).decode()


class PaginationParams:
    """Parameters for cursor-based pagination."""

    def __init__(
        self,
        first: int | None = None,
        after: str | None = None,
        last: int | None = None,
        before: str | None = None,
        order_by: str = "id",
        order_direction: str = "ASC",
    ) -> None:
        """Initialize pagination parameters.

        Args:
            first: Number of items to fetch forward
            after: Cursor to start after (forward pagination)
            last: Number of items to fetch backward
            before: Cursor to end before (backward pagination)
            order_by: Field to order by (must be unique)
            order_direction: ASC or DESC
        """
        # Validate pagination arguments
        if first is not None and last is not None:
            msg = "Cannot specify both 'first' and 'last'"
            raise ValueError(msg)

        if first is not None and first < 0:
            msg = "'first' must be non-negative"
            raise ValueError(msg)

        if last is not None and last < 0:
            msg = "'last' must be non-negative"
            raise ValueError(msg)

        self.first = first
        self.after = after
        self.last = last
        self.before = before
        self.order_by = order_by
        self.order_direction = order_direction.upper()

        # Determine pagination direction
        self.is_forward = first is not None or (first is None and last is None)
        self.is_backward = last is not None

        # Set default limit if not specified
        if self.first is None and self.last is None:
            self.first = 20  # Default page size


class CursorPaginator:
    """Implements cursor-based pagination for PostgreSQL JSONB views."""

    def __init__(self, connection: AsyncConnection) -> None:
        """Initialize paginator with database connection."""
        self.connection = connection

    async def paginate(
        self,
        view_name: str,
        params: PaginationParams,
        filters: dict[str, Any] | None = None,
        include_total: bool = True,
    ) -> dict[str, Any]:
        """Paginate query results using PostgreSQL cursors.

        Args:
            view_name: Database view to query
            params: Pagination parameters
            filters: Optional WHERE clause filters
            include_total: Whether to include total count

        Returns:
            Dictionary with edges, page_info, and optional total_count
        """
        # Build the main query
        query_parts = [SQL("SELECT id, data FROM {}").format(_view_identifier(view_name))]
        query_params = []
        where_clauses = []

        # Add filters
        if filters:
            for key, value in filters.items():
                if isinstance(value, list):
                    # Handle array containment
                    where_clauses.append(SQL("data->{} ?| %s").format(Literal(key)))
                    query_params.append(value)
                else:
                    # Handle equality
                    where_clauses.append(SQL("data->>{} = %s").format(Literal(key)))
                    query_params.append(str(value))

        # Handle cursor positioning
        cursor_field = SQL("data->>{}").format(Literal(params.order_by))

        if params.after:
            cursor_value = decode_cursor(params.after)
            if params.order_direction == "ASC":
                where_clauses.append(SQL("{} > %s").format(cursor_field))
            else:
                where_clauses.append(SQL("{} < %s").format(cursor_field))
            query_params.append(cursor_value)

        if params.before:
            cursor_value = decode_cursor(params.before)
            if params.order_direction == "ASC":
                where_clauses.append(SQL("{} < %s").format(cursor_field))
            else:
                where_clauses.append(SQL("{} > %s").format(cursor_field))
            query_params.append(cursor_value)

        # Build WHERE clause
        if where_clauses:
            query_parts.append(SQL(" WHERE ") + SQL(" AND ").join(where_clauses))

        # Build ORDER BY clause
        if params.is_backward:
            # Reverse order for backward pagination
            reverse_direction = "DESC" if params.order_direction == "ASC" else "ASC"
            order_clause = SQL(" ORDER BY {} ").format(cursor_field) + (
                SQL("DESC") if reverse_direction == "DESC" else SQL("ASC")
            )
            query_parts.append(order_clause)
        else:
            order_clause = SQL(" ORDER BY {} ").format(cursor_field) + (
                SQL("DESC") if params.order_direction == "DESC" else SQL("ASC")
            )
            query_parts.append(order_clause)

        # Add LIMIT
        limit = params.first if params.is_forward else params.last
        if limit is None:
            msg = "Either 'first' or 'last' must be specified"
            raise ValueError(msg)
        # Fetch one extra to determine if there are more pages
        query_parts.append(SQL(" LIMIT %s"))
        query_params.append(limit + 1)

        # Execute main query
        query = SQL("").join(query_parts)

        async with self.connection.cursor() as cursor:
            await cursor.execute(query, query_params)
            rows = await cursor.fetchall()

        # Process results
        has_extra = len(rows) > limit
        if has_extra:
            rows = rows[:limit]  # Remove the extra row

        # Reverse results for backward pagination
        if params.is_backward:
            rows.reverse()

        # Build edges
        edges = []
        for _row_id, row_data in rows:
            cursor_value = row_data.get(params.order_by)
            if cursor_value is not None:
                edges.append(
                    {
                        "node": row_data,
                        "cursor": encode_cursor(str(cursor_value)),
                    },
                )

        # Build page info
        page_info = {
            "has_next_page": has_extra if params.is_forward else (params.after is not None),
            "has_previous_page": has_extra if params.is_backward else (params.before is not None),
            "start_cursor": edges[0]["cursor"] if edges else None,
            "end_cursor": edges[-1]["cursor"] if edges else None,
        }

        # Get total count if requested
        total_count = None
        if include_total:
            total_count = await self._get_total_count(view_name, filters)
            page_info["total_count"] = total_count

        return {
            "edges": edges,
            "page_info": page_info,
            "total_count": total_count,
        }

    async def _get_total_count(self, view_name: str, filters: dict[str, Any] | None = None) -> int:
        """Get total count of items matching filters.

        Args:
            view_name: Database view to query
            filters: Optional WHERE clause filters

        Returns:
            Total count of matching items
        """
        query_parts = [SQL("SELECT COUNT(*) FROM {}").format(_view_identifier(view_name))]
        query_params = []

        if filters:
            where_clauses = []
            for key, value in filters.items():
                if isinstance(value, list):
                    where_clauses.append(SQL("data->{} ?| %s").format(Literal(key)))
                    query_params.append(value)
                else:
                    where_clauses.append(SQL("data->>{} = %s").format(Literal(key)))
                    query_params.append(str(value))

            if where_clauses:
                query_parts.append(SQL(" WHERE ") + SQL(" AND ").join(where_clauses))

        query = SQL("").join(query_parts)

        async with self.connection.cursor() as cursor:
            await cursor.execute(query, query_params)
            result = await cursor.fetchone()
            return result[0] if result else 0


# Extension to CQRSRepository
async def paginate_query(
    repository: CQRSRepository,
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
    """Add pagination support to CQRSRepository.

    This method extends the repository with cursor-based pagination.

    Args:
        repository: CQRSRepository instance to use for pagination
        view_name: Database view to query
        first: Number of items to fetch forward
        after: Cursor to start after
        last: Number of items to fetch backward
        before: Cursor to end before
        filters: Optional WHERE clause filters
        order_by: Field to order by
        order_direction: ASC or DESC
        include_total: Whether to include total count

    Returns:
        Dictionary ready to be converted to Connection[T]
    """
    paginator = CursorPaginator(repository.connection)
    params = PaginationParams(
        first=first,
        after=after,
        last=last,
        before=before,
        order_by=order_by,
        order_direction=order_direction,
    )

    return await paginator.paginate(
        view_name,
        params,
        filters=filters,
        include_total=include_total,
    )

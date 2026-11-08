"""Common DataLoader implementations.

Each loader reads a table (or view) through the repository's ``run``, one query
per batch, and returns its rows as dicts.
"""

from collections import defaultdict
from typing import Any
from uuid import UUID

from psycopg.sql import SQL, Identifier

from fraiseql.db import DatabaseQuery
from fraiseql.optimization.dataloader import DataLoader
from fraiseql.sql.identifiers import qualified_identifier


def _check_name(name: str, what: str, allow_dot: bool) -> None:
    allowed = name.replace("_", "").replace(".", "") if allow_dot else name.replace("_", "")
    if not allowed.isalnum():
        msg = f"Invalid {what}: {name}"
        raise ValueError(msg)


async def _rows_by_key(db: Any, table: str, key_field: str, keys: list[Any]) -> list[dict]:
    """Rows of ``table`` whose ``key_field`` (a uuid column) is one of ``keys``."""
    _check_name(table, "table name", allow_dot=True)
    _check_name(key_field, "key field", allow_dot=False)
    statement = SQL("SELECT * FROM {} WHERE {} = ANY(%(keys)s::uuid[])").format(
        qualified_identifier(table), Identifier(key_field)
    )
    return await db.run(DatabaseQuery(statement, {"keys": list(keys)}))


class UserLoader(DataLoader[UUID, dict[str, Any]]):
    """DataLoader for loading users by ID (from the ``users`` table by default)."""

    def __init__(self, db: Any, table: str = "users") -> None:
        super().__init__()
        self.db = db
        self.table = table

    async def batch_load(self, user_ids: list[UUID]) -> list[dict | None]:
        """Load multiple users in one query, in the order of ``user_ids``."""
        users = await _rows_by_key(self.db, self.table, "id", user_ids)
        return self.sort_by_keys(users, user_ids)


class ProjectLoader(DataLoader[UUID, dict[str, Any]]):
    """DataLoader for loading projects by ID (from the ``projects`` table by default)."""

    def __init__(self, db: Any, table: str = "projects") -> None:
        super().__init__()
        self.db = db
        self.table = table

    async def batch_load(self, project_ids: list[UUID]) -> list[dict | None]:
        """Load multiple projects in one query, in the order of ``project_ids``."""
        projects = await _rows_by_key(self.db, self.table, "id", project_ids)
        return self.sort_by_keys(projects, project_ids)


class TasksByProjectLoader(DataLoader[UUID, list[dict[str, Any]]]):
    """DataLoader for the latest tasks of each project (``tasks`` table by default).

    Each project gets up to ``limit`` tasks, newest ``created_at`` first. A row
    carries its rank, ``rn``, too.
    """

    def __init__(self, db: Any, limit: int = 100, table: str = "tasks") -> None:
        super().__init__()
        self.db = db
        self.limit = limit
        self.table = table

    async def batch_load(self, project_ids: list[UUID]) -> list[list[dict]]:
        """Load tasks for multiple projects."""
        _check_name(self.table, "table name", allow_dot=True)
        statement = SQL(
            "WITH ranked_tasks AS ("
            " SELECT *, ROW_NUMBER() OVER ("
            "  PARTITION BY project_id ORDER BY created_at DESC"
            " ) AS rn"
            " FROM {}"
            " WHERE project_id = ANY(%(keys)s::uuid[])"
            ") SELECT * FROM ranked_tasks WHERE rn <= %(limit)s"
            " ORDER BY project_id, created_at DESC"
        ).format(qualified_identifier(self.table))
        rows = await self.db.run(
            DatabaseQuery(statement, {"keys": list(project_ids), "limit": self.limit})
        )

        tasks_by_project = defaultdict(list)
        for row in rows:
            tasks_by_project[row["project_id"]].append(dict(row))

        return [tasks_by_project.get(pid, []) for pid in project_ids]


class GenericForeignKeyLoader(DataLoader[UUID, dict[str, Any]]):
    """Generic loader of the rows of ``table`` by a uuid ``key_field``."""

    def __init__(self, db: Any, table: str, key_field: str = "id") -> None:
        super().__init__()
        self.db = db
        self.table = table
        self.key_field = key_field

    async def batch_load(self, keys: list[UUID]) -> list[dict | None]:
        """Load multiple records by key, in the order of ``keys``."""
        items = await _rows_by_key(self.db, self.table, self.key_field, keys)
        return self.sort_by_keys(items, keys, self.key_field)

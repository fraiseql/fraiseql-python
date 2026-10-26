"""Hide database error details from GraphQL clients in production.

A PostgreSQL error's message carries the failing SQL (``LINE 1: SELECT ...``),
relation and column names, and PL/pgSQL context. With ``environment="production"``
an error raised by the database is answered with a generic message instead; the
full error is still logged by the code that caught it.

The exception is ``RAISE EXCEPTION`` in a function (SQLSTATE ``P0001``): its
primary message is written by the function's author for the caller, so it is
kept, without the DETAIL, HINT and CONTEXT lines that follow it.
"""

from typing import Any

import psycopg

INTERNAL_ERROR_MESSAGE = "Internal server error"
INTERNAL_ERROR_CODE = "INTERNAL_SERVER_ERROR"


RAISED_BY_FUNCTION = "P0001"


def is_database_error(error: BaseException | None) -> bool:
    """Whether *error*, or an error it wraps, was raised by the database.

    Follows ``GraphQLError.original_error`` and the ``__cause__`` /
    ``__context__`` chain.
    """
    return _database_error(error) is not None


def _database_error(error: BaseException | None) -> psycopg.Error | None:
    """The first ``psycopg.Error`` in *error*'s chain, if any."""
    seen: set[int] = set()
    pending = [error]
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, psycopg.Error):
            return current
        pending.extend(
            [getattr(current, "original_error", None), current.__cause__, current.__context__]
        )
    return None


def mask_database_error(formatted: dict[str, Any], error: BaseException) -> dict[str, Any]:
    """Return *formatted* with a generic message when *error* came from the database.

    ``path`` and ``locations`` are kept, so the client still knows which field failed.
    A ``RAISE EXCEPTION`` keeps its primary message (see the module docstring). Any
    other error is returned unchanged.
    """
    db_error = _database_error(error)
    if db_error is None:
        return formatted
    message = INTERNAL_ERROR_MESSAGE
    if db_error.sqlstate == RAISED_BY_FUNCTION:
        message = db_error.diag.message_primary or str(db_error).split("\n", 1)[0]
    masked: dict[str, Any] = {"message": message}
    masked.update((key, formatted[key]) for key in ("locations", "path") if key in formatted)
    masked["extensions"] = {"code": INTERNAL_ERROR_CODE}
    return masked

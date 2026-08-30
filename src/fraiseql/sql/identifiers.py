"""Render database object names as the identifiers PostgreSQL resolves.

A schema-qualified name has to become two identifiers — ``"myschema"."v_stats"``.
Passed whole to a single-argument :class:`~psycopg.sql.Identifier` it renders as
``"myschema.v_stats"``, one quoted relation name that happens to contain a dot,
and the statement fails with ``relation "myschema.v_stats" does not exist``.

This module holds no FraiseQL imports so that every layer can reach it: the
repository (:mod:`fraiseql.db`) imports both :mod:`fraiseql.sql` and
:mod:`fraiseql.mutations`, so those two cannot import the helper back from
there.
"""

from psycopg.sql import Identifier

__all__ = ["qualified_identifier"]


def qualified_identifier(name: str) -> Identifier:
    """Split a possibly schema-qualified name into the identifiers it names.

    Applies to any qualified database object — a view, a table, or a function.
    Unqualified names are returned as a single identifier, unchanged.

    Args:
        name: A relation or function name, optionally ``schema.``-qualified.

    Returns:
        ``Identifier(schema, object)`` for a qualified name, ``Identifier(name)``
        otherwise.
    """
    if "." in name:
        schema_name, object_name = name.split(".", 1)
        return Identifier(schema_name, object_name)
    return Identifier(name)

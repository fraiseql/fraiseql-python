"""The cascade selections sent to Rust carry the field names Rust reads, nothing else.

``extract_cascade_selections`` also parsed ``updated(include: ..., exclude: ...)``
and the inline fragments under ``entity`` into ``include``, ``exclude`` and
``entity_selections``. Rust's ``CascadeSelections`` filters on ``fields`` only,
``Cascade.updated`` takes no arguments, and the entity is a JSON scalar, so the
extra keys were built on every mutation and never read.
"""

import json
from types import SimpleNamespace

import pytest
from graphql import parse

from fraiseql.mutations.cascade_selections import extract_cascade_selections

pytestmark = pytest.mark.unit


def _selections(query: str) -> dict:
    operation = parse(query).definitions[0]
    info = SimpleNamespace(field_nodes=list(operation.selection_set.selections))
    return json.loads(extract_cascade_selections(info))


def test_only_field_names_are_sent() -> None:
    selections = _selections(
        """
        mutation {
          createPost {
            ... on CreatePostSuccess {
              cascade {
                updated(include: ["Post"], exclude: ["User"]) {
                  __typename id operation
                  entity { id ... on Post { title } }
                }
                deleted { __typename id }
                invalidations { queryName strategy }
                metadata { timestamp affectedCount }
              }
            }
          }
        }
        """
    )

    assert selections == {
        "fields": ["updated", "deleted", "invalidations", "metadata"],
        "updated": {"fields": ["__typename", "id", "operation", "entity"]},
        "deleted": {"fields": ["__typename", "id"]},
        "invalidations": {"fields": ["queryName", "strategy"]},
        "metadata": {"fields": ["timestamp", "affectedCount"]},
    }


def test_cascade_without_subfields() -> None:
    assert _selections("mutation { createPost { cascade } }") == {"fields": []}

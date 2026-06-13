"""Registry authorizer-slot + build-funnel threading tests (issue #362, phase 1)."""

from __future__ import annotations

from typing import Any

import pytest

import fraiseql
from fraiseql.gql.builders import SchemaRegistry


@fraiseql.type
class _Thing:
    id: int


async def _probe_query(info) -> list[_Thing]:
    return []


def _register_minimal_query() -> None:
    """Register one type + query so schema builds don't fail on an empty Query."""
    registry = SchemaRegistry.get_instance()
    registry.register_type(_Thing)
    registry.register_query(_probe_query)


class _DummyAuthorizer:
    async def authorize_operation(
        self,
        *,
        context: dict[str, Any],
        operation_type: str,
        operation_name: str,
        arguments: dict[str, Any],
    ) -> bool:
        return True


@pytest.fixture(autouse=True)
def _clean_registry():
    registry = SchemaRegistry.get_instance()
    registry.clear()
    yield
    registry.clear()


def test_default_authorizer_defaults_none() -> None:
    registry = SchemaRegistry.get_instance()
    assert registry.default_authorizer is None


def test_set_default_authorizer() -> None:
    registry = SchemaRegistry.get_instance()
    dummy = _DummyAuthorizer()
    registry.set_default_authorizer(dummy)
    assert registry.default_authorizer is dummy


def test_clear_resets_default_authorizer() -> None:
    registry = SchemaRegistry.get_instance()
    registry.set_default_authorizer(_DummyAuthorizer())
    registry.clear()
    assert registry.default_authorizer is None


def test_build_fraiseql_schema_threads_authorizer() -> None:
    from fraiseql.gql.schema_builder import build_fraiseql_schema

    _register_minimal_query()
    dummy = _DummyAuthorizer()
    build_fraiseql_schema(authorizer=dummy)
    assert SchemaRegistry.get_instance().default_authorizer is dummy


def test_build_without_authorizer_leaves_none() -> None:
    from fraiseql.gql.schema_builder import build_fraiseql_schema

    _register_minimal_query()
    build_fraiseql_schema()
    assert SchemaRegistry.get_instance().default_authorizer is None


def test_legacy_build_threads_authorizer() -> None:
    from fraiseql.gql.graphql_entrypoint import build_fraiseql_schema as legacy_build

    _register_minimal_query()
    dummy = _DummyAuthorizer()
    legacy_build(authorizer=dummy)
    assert SchemaRegistry.get_instance().default_authorizer is dummy


def test_legacy_build_without_authorizer_leaves_none() -> None:
    from fraiseql.gql.graphql_entrypoint import build_fraiseql_schema as legacy_build

    _register_minimal_query()
    legacy_build()
    assert SchemaRegistry.get_instance().default_authorizer is None

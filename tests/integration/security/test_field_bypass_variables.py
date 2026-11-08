"""Field-level authorization on a resolver-bypass path, with arguments given as variables.

``enforce_selected_field_authorization`` passes each gated field's arguments to the
authorizer. On graphql-core 3.3, arguments given as variables arrived as ``{}``.

Separate from ``test_field_bypass_paths.py``, which uses ``from __future__ import
annotations``: fraiseql cannot resolve the string annotation ``list[Secret]`` on a
``fraise_field``.
"""

from typing import Any
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from tests.integration.security.test_field_bypass_paths import (  # noqa: F401 - autouse fixture
    _clean_registry,
    _is_forbidden,
    _noop_lifespan,
)

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.config import FraiseQLConfig
from fraiseql.fields import fraise_field
from fraiseql.gql.builders import SchemaRegistry

pytestmark = pytest.mark.integration


@fraiseql.type
class Secret:
    id: int
    level: str


@fraiseql.type(authorize_fields=["secrets"])
class Vault:
    """Vault whose filterable ``secrets`` list is gated, with ``where`` passed to the policy."""

    id: int
    secrets: list[Secret] = fraise_field(
        default_factory=list, supports_where_filtering=True, nested_where_type=Secret
    )


@fraiseql.query
async def vault(info) -> Vault:
    return Vault(id=1)


class DenyTopSecret:
    """Denies ``Vault.secrets`` filtered to ``level: "top"``: a policy that reads ``where``."""

    async def authorize_operation(
        self, *, operation_type: str, operation_name: str, arguments: dict[str, Any], **_: Any
    ) -> bool:
        if operation_type == "field" and operation_name == "Vault.secrets":
            level = (arguments.get("where") or {}).get("level") or {}
            return level.get("eq") != "top"
        return True


def test_rust_endpoint_passes_variable_arguments_to_the_field_gate() -> None:
    """Arguments given as variables reach the authorizer on the /graphql/rust path.

    On graphql-core 3.3 they arrived as ``{}``, so a policy that denies a specific ``where``
    filter allowed it, and the Rust pipeline served the field.
    """
    config = FraiseQLConfig(
        database_url="postgresql://test:test@localhost/test",
        environment="development",
        enable_rust_endpoint=True,
    )
    app = create_fraiseql_app(
        config=config, types=[Secret, Vault], queries=[vault], lifespan=_noop_lifespan
    )
    SchemaRegistry.get_instance().set_default_authorizer(DenyTopSecret())

    calls: list[Any] = []

    async def _spy(*args: Any, **kwargs: Any) -> bytes:
        calls.append((args, kwargs))
        return b'{"data": {"vault": {"secrets": [{"id": 1}]}}}'

    query = "query Q($where: SecretWhereInput) { vault { secrets(where: $where) { id } } }"
    with (
        mock.patch("fraiseql._fraiseql_rs.execute_graphql_query", new=_spy),
        TestClient(app) as client,
    ):
        denied = client.post(
            "/graphql/rust", json={"query": query, "variables": {"where": {"level": {"eq": "top"}}}}
        ).json()
        assert calls == [], "Rust pipeline ran despite a denied gated field"
        allowed = client.post(
            "/graphql/rust",
            json={"query": query, "variables": {"where": {"level": {"eq": "public"}}}},
        ).json()

    assert _is_forbidden(denied), "expected FIELD_AUTHORIZATION_ERROR for level top"
    assert not _is_forbidden(allowed)
    assert len(calls) == 1, "Rust pipeline should run for an allowed argument"

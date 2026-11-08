"""Auth decorators work on root fields queried together.

A query with two or more root fields runs on fraiseql's multi-field path, which
calls each root resolver with its own resolve info (_MultiFieldResolveInfo), not
graphql-core's GraphQLResolveInfo. requires_auth, requires_role,
requires_permission, requires_any_role and requires_any_permission checked
``isinstance(info, GraphQLResolveInfo)`` and failed every such query with
"First argument must be GraphQLResolveInfo", although each field alone worked.
"""

import pytest
from fastapi.testclient import TestClient

import fraiseql
from fraiseql.auth.base import AuthProvider, InvalidTokenError, UserContext
from fraiseql.auth.decorators import (
    requires_any_permission,
    requires_any_role,
    requires_auth,
    requires_permission,
    requires_role,
)
from fraiseql.fastapi import create_fraiseql_app

pytestmark = pytest.mark.integration

_USERS = {
    "admin-token": UserContext(user_id="root", roles=["admin"], permissions=["reports:read"]),
    "user-token": UserContext(user_id="alice", roles=["user"], permissions=[]),
}


class _TokenTable(AuthProvider):
    async def validate_token(self, token: str) -> dict:
        if token not in _USERS:
            raise InvalidTokenError("unknown token")
        return {"sub": _USERS[token].user_id}

    async def get_user_from_token(self, token: str) -> UserContext:
        await self.validate_token(token)
        return _USERS[token]


@fraiseql.type
class Who:
    user_id: str


@pytest.fixture
def client(clear_registry):
    @fraiseql.query
    @requires_auth
    async def me(info) -> Who:
        return Who(user_id=info.context["user"].user_id)

    @fraiseql.query
    @requires_role("admin")
    async def admin_only(info) -> Who:
        return Who(user_id=info.context["user"].user_id)

    @fraiseql.query
    @requires_permission("reports:read")
    async def report_reader(info) -> Who:
        return Who(user_id=info.context["user"].user_id)

    @fraiseql.query
    @requires_any_role("admin", "auditor")
    async def admin_or_auditor(info) -> Who:
        return Who(user_id=info.context["user"].user_id)

    @fraiseql.query
    @requires_any_permission("reports:read", "reports:write")
    async def any_report_permission(info) -> Who:
        return Who(user_id=info.context["user"].user_id)

    app = create_fraiseql_app(
        # The lifespan opens a pool; no query uses it, so it needn't connect
        database_url="postgresql://nobody@127.0.0.1:1/none",
        types=[Who],
        queries=[me, admin_only, report_reader, admin_or_auditor, any_report_permission],
        auth=_TokenTable(),
        production=False,
    )
    with TestClient(app) as test_client:
        yield test_client


def _post(client: TestClient, query: str, token: str) -> dict:
    response = client.post(
        "/graphql", json={"query": query}, headers={"Authorization": f"Bearer {token}"}
    )
    return response.json()


_ALL_FIVE = (
    "{ me { userId } adminOnly { userId } reportReader { userId } "
    "adminOrAuditor { userId } anyReportPermission { userId } }"
)


def test_every_decorator_passes_an_authorized_user_on_the_multi_field_path(client) -> None:
    body = _post(client, _ALL_FIVE, "admin-token")

    assert "errors" not in body, body
    assert {field: value["userId"] for field, value in body["data"].items()} == {
        "me": "root",
        "adminOnly": "root",
        "reportReader": "root",
        "adminOrAuditor": "root",
        "anyReportPermission": "root",
    }


def test_decorators_still_refuse_on_the_multi_field_path(client) -> None:
    body = _post(client, _ALL_FIVE, "user-token")

    assert body["data"]["me"]["userId"] == "alice"
    refused = {error["path"][0]: error["extensions"]["code"] for error in body["errors"]}
    assert refused == {
        "adminOnly": "FORBIDDEN",
        "reportReader": "FORBIDDEN",
        "adminOrAuditor": "FORBIDDEN",
        "anyReportPermission": "FORBIDDEN",
    }

"""First-class operation authorization example (issue #362).

Demonstrates the supported `create_fraiseql_app(authorizer=...)` entry point with two
authorizers:

- ``DenyMutationsAuthorizer`` — a cross-cutting rule ("read-only principals may not run
  mutations") expressed without touching any private registry attribute.
- ``TenantScopeAuthorizer`` — row scoping: every read is transparently limited to the
  principal's tenant via ``AuthorizationDecision.allow(filters=...)``.

Run the file directly to print the resulting schema, or import ``build_app`` in a test.
"""

from __future__ import annotations

from typing import Any

import fraiseql
from fraiseql import AuthorizationDecision, create_fraiseql_app


@fraiseql.type
class Document:
    """A tenant-scoped document."""

    id: int
    title: str


@fraiseql.query
async def documents(info) -> list[Document]:
    """List documents (scoped to the principal's tenant by the authorizer)."""
    db = info.context["db"]
    # No tenant filter is hand-written here — the authorizer injects it.
    return await db.find("v_document")


@fraiseql.mutation
async def create_document(info, title: str) -> Document:
    """Create a document (blocked for read-only principals by the authorizer)."""
    db = info.context["db"]
    return await db.find_one("v_document", title=title)


class DenyMutationsAuthorizer:
    """Read-only principals may run queries but never mutations."""

    async def authorize_operation(
        self,
        *,
        context: dict[str, Any],
        operation_type: str,
        operation_name: str,
        arguments: dict[str, Any],
    ) -> AuthorizationDecision:
        user = context.get("user") or {}
        if operation_type == "mutation" and user.get("role") == "readonly":
            return AuthorizationDecision.deny(
                code="READ_ONLY_PRINCIPAL",
                message="this principal may not run mutations",
            )
        return AuthorizationDecision.allow()


class TenantScopeAuthorizer:
    """Allow everything, but scope every read to the principal's tenant."""

    async def authorize_operation(
        self,
        *,
        context: dict[str, Any],
        operation_type: str,
        operation_name: str,
        arguments: dict[str, Any],
    ) -> AuthorizationDecision:
        user = context.get("user")
        if user is None:
            return AuthorizationDecision.deny(message="authentication required")
        if operation_type == "query":
            return AuthorizationDecision.allow(filters={"tenant_id": user["tenant_id"]})
        return AuthorizationDecision.allow()


def build_app(*, authorizer: Any):
    """Build a FraiseQL app gated by the given authorizer."""
    return create_fraiseql_app(
        database_url="postgresql://localhost/example",
        types=[Document],
        queries=[documents],
        mutations=[create_document],
        authorizer=authorizer,
    )


if __name__ == "__main__":
    app = build_app(authorizer=DenyMutationsAuthorizer())
    print(f"Built app with {len(app.routes)} routes and a deny-mutations authorizer.")

"""``debug_graphql_info`` with a real ``GraphQLResolveInfo``."""

from typing import Any

from graphql import build_schema, graphql_sync

from fraiseql.debug.debug import debug_graphql_info


def test_debug_graphql_info_lists_variables() -> None:
    """On graphql-core 3.3, ``info.variable_values`` is a ``VariableValues``, not a dict."""
    schema = build_schema("type Query { doc(id: Int): String }")
    output: list[str] = []

    def resolve(_root: Any, info: Any, **_kwargs: Any) -> str:
        output.append(debug_graphql_info(info))
        return "doc"

    schema.query_type.fields["doc"].resolve = resolve
    result = graphql_sync(schema, "query Q($id: Int) { doc(id: $id) }", variable_values={"id": 5})

    assert result.errors is None
    assert "Variables:\n  id: 5" in output[0]

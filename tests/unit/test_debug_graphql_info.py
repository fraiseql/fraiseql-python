"""Debug helpers with a real ``GraphQLResolveInfo``."""

from typing import Any

from graphql import build_schema, graphql_sync
from structlog.testing import capture_logs

from fraiseql.debug.debug import debug_graphql_info, profile_resolver
from fraiseql.errors.exceptions import ResolverError


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


def _resolve_in_list(resolver: Any) -> None:
    """Run ``resolver`` as ``Post.author`` under ``posts[0]``."""
    schema = build_schema("type Query { posts: [Post] } type Post { author: String }")
    schema.query_type.fields["posts"].resolve = lambda *_args, **_kwargs: [{}]
    schema.get_type("Post").fields["author"].resolve = resolver
    result = graphql_sync(schema, "{ posts { author } }")
    assert result.errors is None


def test_debug_graphql_info_shows_the_response_path() -> None:
    output: list[str] = []

    def resolve(_root: Any, info: Any, **_kwargs: Any) -> str:
        output.append(debug_graphql_info(info))
        return "Ada"

    _resolve_in_list(resolve)

    assert "Path: posts.0.author\n" in output[0]


def test_profile_resolver_logs_the_response_path() -> None:
    @profile_resolver()
    def resolve(_root: Any, info: Any, **_kwargs: Any) -> str:
        return "Ada"

    with capture_logs() as logs:
        _resolve_in_list(resolve)

    assert [log["path"] for log in logs if log["event"] == "resolver_profiled"] == [
        ["posts", 0, "author"]
    ]


def test_resolver_error_context_has_the_response_path() -> None:
    errors: list[ResolverError] = []

    def resolve(_root: Any, info: Any, **_kwargs: Any) -> str:
        errors.append(ResolverError("author", "boom", query_info=info))
        return "Ada"

    _resolve_in_list(resolve)

    assert errors[0].query_context["path"] == ["posts", 0, "author"]

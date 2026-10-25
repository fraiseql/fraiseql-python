"""Which queries select a field resolver, the case db.find answers with typed rows for."""

import pytest

import fraiseql
from fraiseql import build_fraiseql_schema
from fraiseql.core.field_resolvers import _reaching, operation_selects_field_resolver


@pytest.fixture
def schema(clear_registry):
    @fraiseql.type
    class Comment:
        id: int
        replies: list["Comment"]

        @fraiseql.field
        def shout(self) -> str:
            return "!"

    @fraiseql.type
    class Post:
        id: int
        comments: list[Comment]
        top_comment: Comment | None = None

        @fraiseql.field
        async def like_count(self, info) -> int:
            return 0

    @fraiseql.type
    class Tag:
        name: str

    @fraiseql.query
    async def posts(info) -> list[Post]:
        return []

    @fraiseql.query
    async def tags(info) -> list[Tag]:
        return []

    return build_fraiseql_schema(query_types=[posts, tags])


@pytest.mark.parametrize(
    ("query", "variables", "expected"),
    [
        ("{ posts { id } }", None, False),
        ("{ posts { likeCount } }", None, True),
        ("{ posts { n: likeCount } }", None, True),
        ("{ posts { comments { id } } }", None, False),
        ("{ posts { comments { shout } } }", None, True),
        ("{ posts { topComment { replies { replies { shout } } } } }", None, True),
        ("{ posts { ...P } } fragment P on Post { likeCount }", None, True),
        ("{ posts { ... on Post { comments { shout } } } }", None, True),
        ("query($s: Boolean!) { posts { likeCount @skip(if: $s) } }", {"s": True}, False),
        ("query($s: Boolean!) { posts { likeCount @include(if: $s) } }", {"s": True}, True),
        ("{ tags { name } posts { id } }", None, False),
        ("{ tags { name } posts { likeCount } }", None, True),
    ],
)
def test_selects_field_resolver(schema, query, variables, expected) -> None:
    assert operation_selects_field_resolver(schema, query, None, variables) is expected


def test_types_a_resolver_is_reached_from(schema) -> None:
    assert _reaching(schema) == {"Query", "Post", "Comment"}


def test_a_schema_without_field_resolvers_reaches_none(clear_registry) -> None:
    @fraiseql.type
    class Plain:
        id: int

    @fraiseql.query
    async def plains(info) -> list[Plain]:
        return []

    schema = build_fraiseql_schema(query_types=[plains])

    assert _reaching(schema) == frozenset()
    assert operation_selects_field_resolver(schema, "{ plains { id } }") is False


@pytest.fixture
def nested_schema(clear_registry):
    from fraiseql.fields import fraise_field

    @fraiseql.type
    class Device:
        hostname: str

    @fraiseql.type(sql_source="v_department", resolve_nested=True)
    class Department:
        id: int

    @fraiseql.type
    class Network:
        id: int
        department: Department | None
        devices: list[Device] = fraise_field(
            default_factory=list, supports_where_filtering=True, nested_where_type=Device
        )

    @fraiseql.query
    async def networks(info) -> list[Network]:
        return []

    return build_fraiseql_schema(query_types=[networks])


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        # a nested-array where filters in its resolver; without one the rows are right
        ('{ networks { devices(where: {hostname: {eq: "a"}}) { hostname } } }', True),
        ("query($w: DeviceWhereInput) { networks { devices(where: $w) { hostname } } }", True),
        ("{ networks { devices { hostname } } }", False),
        ("{ networks { id } }", False),
    ],
)
def test_nested_resolvers_count_as_field_resolvers(nested_schema, query, expected) -> None:
    assert operation_selects_field_resolver(nested_schema, query) is expected

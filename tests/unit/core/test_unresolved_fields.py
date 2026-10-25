"""Which selected fields are field resolvers db.find's Rust rows won't run."""

import fraiseql
from fraiseql.core.unresolved_fields import selected_field_resolvers


def test_field_resolvers_at_any_depth(clear_registry) -> None:
    @fraiseql.type
    class Comment:
        id: int

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

    paths = [
        ["id"],
        ["like_count"],
        ["comments", "id"],
        ["comments", "shout"],
        ["top_comment", "shout"],
        ["missing", "deeper"],
    ]
    assert selected_field_resolvers(Post, paths) == [("Post", "like_count"), ("Comment", "shout")]


def test_plain_fields_are_not_resolvers(clear_registry) -> None:
    @fraiseql.type
    class Plain:
        id: int
        name: str

    assert selected_field_resolvers(Plain, [["id"], ["name"]]) == []

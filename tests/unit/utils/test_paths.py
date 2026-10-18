"""``format_path`` on graphql-core response paths."""

from graphql.pyutils import Path

from fraiseql.utils.paths import format_path

PATH = Path(Path(None, "posts", "Query"), 0, None).add_key("author", "Post")


def test_format_path_keeps_list_indices_by_default() -> None:
    assert format_path(PATH) == "posts.0.author"


def test_format_path_can_drop_list_indices() -> None:
    assert format_path(PATH, keep_indices=False) == "posts.author"


def test_format_path_of_no_path_is_empty() -> None:
    assert format_path(None) == ""

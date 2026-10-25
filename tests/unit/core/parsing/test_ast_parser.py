import pytest

from fraiseql.core.ast_parser import FieldPath, extract_flat_paths, parse_query_ast


def _unaliased(*path: str) -> FieldPath:
    return FieldPath(alias=path[-1], path=list(path), names=path, response_keys=path)


@pytest.mark.unit
def test_simple_flat_selection() -> None:
    query = """
    query {
        user {
            id
            name
        }
    }
    """
    op, fragments = parse_query_ast(query)
    paths = extract_flat_paths(op.selection_set, fragments)
    assert paths == [_unaliased("user", "id"), _unaliased("user", "name")]


def test_aliasing_and_nested() -> None:
    query = """
    query {
        account {
            user: profile {
                age
                nickname: username
            }
        }
    }
    """
    op, fragments = parse_query_ast(query)
    paths = extract_flat_paths(op.selection_set, fragments)
    assert paths == [
        FieldPath(
            alias="age",
            path=["account", "profile", "age"],
            names=("account", "profile", "age"),
            response_keys=("account", "user", "age"),
        ),
        FieldPath(
            alias="nickname",
            path=["account", "profile", "username"],
            names=("account", "profile", "username"),
            response_keys=("account", "user", "nickname"),
        ),
    ]


def test_path_segments_are_transformed_names_and_keys_are_not() -> None:
    op, fragments = parse_query_ast("query { authorInfo { n: firstName } }")
    paths = extract_flat_paths(op.selection_set, fragments, transform_path=str.upper)
    assert paths == [
        FieldPath(
            alias="n",
            path=["AUTHORINFO", "FIRSTNAME"],
            names=("authorInfo", "firstName"),
            response_keys=("authorInfo", "n"),
        )
    ]


def test_a_field_path_without_names_still_builds() -> None:
    path = FieldPath(alias="id", path=["user", "id"])
    assert path.names is None
    assert path.response_keys is None


def test_named_fragment() -> None:
    query = """
    query {
        person {
            ...personFields
        }
    }

    fragment personFields on Person {
        id
        name
    }
    """
    op, fragments = parse_query_ast(query)
    paths = extract_flat_paths(op.selection_set, fragments)
    assert paths == [_unaliased("person", "id"), _unaliased("person", "name")]


def test_inline_fragment() -> None:
    query = """
    query {
        node {
            __typename
            ... on User {
                id
            }
        }
    }
    """
    op, fragments = parse_query_ast(query)
    paths = extract_flat_paths(op.selection_set, fragments)
    assert paths == [_unaliased("node", "__typename"), _unaliased("node", "id")]

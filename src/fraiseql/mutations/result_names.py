"""Names of mutation result unions.

A mutation's result union is named after its GraphQL field: ``createPost`` ->
``CreatePostResult``. Up to fraiseql 1.28 it was named after the success type
(``PostSuccess`` -> ``PostResult``); fraiseql 1.x keeps that rule for mutations
that work with it (see ``MutationTypeBuilder``).
"""


def result_union_name(field_name: str) -> str:
    """Return the result union name for a mutation field: ``createPost`` -> ``CreatePostResult``.

    Works for camelCase and snake_case field names (``create_post`` -> ``CreatePostResult``).
    """
    pascal = "".join(part[:1].upper() + part[1:] for part in field_name.split("_"))
    return f"{pascal}Result"


def legacy_result_union_name(success_type: type) -> str:
    """Return the legacy result union name: ``CreatePostSuccess`` -> ``CreatePostResult``."""
    return f"{success_type.__name__.removesuffix('Success')}Result"

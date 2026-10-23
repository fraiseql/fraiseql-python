"""A bare ``@skip`` / ``@include`` (no ``if``) doesn't raise in ``_should_include_field``.

graphql-core leaves an absent argument list as ``None``, and the loop over
``directive.arguments`` raised ``TypeError``. The multi-field path caught it,
logged a traceback and fell back to standard execution, whose validation
returns the real error ("argument 'if' ... is required").
"""

import pytest
from graphql import parse

from fraiseql.fastapi.routers import _should_include_field

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("directive", ["@skip", "@include"])
def test_bare_directive_leaves_the_field_in(directive) -> None:
    field = parse(f"{{ users {directive} {{ id }} }}").definitions[0].selection_set.selections[0]
    assert field.directives[0].arguments is None or not field.directives[0].arguments
    assert _should_include_field(field, {}) is True

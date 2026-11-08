"""A "failed:<reason>" status gets the code of "<reason>:".

The trinity helpers return failed:validation, failed:not_found and
failed:<conflict type> (failed:duplicate by default). The Rust response builder
reads them the same way (fraiseql_rs/src/mutation/test_status_only.rs).
"""

import pytest

from fraiseql.mutations.error_config import DEFAULT_ERROR_CONFIG


@pytest.mark.parametrize(
    ("status", "code"),
    [
        ("failed:validation", 422),
        ("failed:not_found", 404),
        ("failed:unauthorized", 401),
        ("failed:forbidden", 403),
        ("failed:conflict", 409),
        ("failed:duplicate", 409),
        ("failed:timeout", 408),
        ("FAILED:Validation", 422),
        ("failed:validation:email", 422),
        ("failed:exception", 500),
        ("failed:", 500),
        ("failed:not_found_anywhere", 500),
        ("validation:email", 422),
        ("not_found:user", 404),
        ("noop:unchanged", 422),
    ],
)
def test_error_code(status: str, code: int) -> None:
    assert DEFAULT_ERROR_CONFIG.get_error_code(status) == code

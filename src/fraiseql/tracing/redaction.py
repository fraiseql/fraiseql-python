"""Redaction of sensitive GraphQL variables before they reach a trace."""

from typing import Any

REDACTED = "[REDACTED]"

SENSITIVE_KEY_PATTERNS = frozenset(
    {
        "password",
        "token",
        "secret",
        "key",
        "auth",
        "credential",
        "api_key",
        "apikey",
        "session",
        "cookie",
        "authorization",
    }
)


def redact_variables(
    variables: dict[str, Any], patterns: frozenset[str] | set[str] = SENSITIVE_KEY_PATTERNS
) -> dict[str, Any]:
    """Return *variables* with the value of every key containing a pattern redacted.

    Keys are matched case-insensitively at any depth, inside dicts and lists.
    """

    def redact(key: str, value: Any) -> Any:
        if any(pattern in key.lower() for pattern in patterns):
            return REDACTED
        if isinstance(value, dict):
            return {k: redact(k, v) for k, v in value.items()}
        if isinstance(value, list):
            return [redact(str(i), item) for i, item in enumerate(value)]
        return value

    return {k: redact(k, v) for k, v in variables.items()}

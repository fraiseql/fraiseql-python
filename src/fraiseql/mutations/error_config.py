"""Configurable error detection for mutations."""

from dataclasses import dataclass, field
from typing import Pattern


@dataclass
class MutationErrorConfig:
    """Configurable error detection for mutations.

    Defines patterns for detecting success vs error responses from database
    operations, including status keywords, error prefixes, and HTTP-like codes.
    """

    # Success keywords (unchanged)
    success_keywords: set[str] = field(
        default_factory=lambda: {
            "success",
            "completed",
            "ok",
            "done",
            "new",
            "existing",
            "updated",
            "deleted",
            "synced",
            "created",  # Added for enterprise compatibility
            "cancelled",  # Added for enterprise compatibility
        },
    )

    # Error prefixes - NOW INCLUDES noop:, blocked:, etc.
    error_prefixes: set[str] = field(
        default_factory=lambda: {
            # Validation/business rule failures
            "noop:",  # Validation/business rule failures (422)
            "blocked:",  # Blocked operations (422)
            "skipped:",  # Skipped operations (422)
            "ignored:",  # Ignored operations (422)
            # Traditional errors
            "error:",
            "failed:",  # System failures (500)
            "validation:",  # Input validation failures (422)
            "unauthorized:",  # Auth failures (401)
            "forbidden:",  # Permission failures (403)
            "not_found:",  # Missing resources (404)
            "timeout:",  # Timeouts (408)
            "conflict:",  # Conflicts (409)
        },
    )

    # All errors are Error type

    # Error keywords (unchanged)
    error_keywords: set[str] = field(
        default_factory=lambda: {
            "error",
            "failed",
            "fail",
            "invalid",
            "timeout",
        },
    )

    # Custom regex pattern for error detection (optional)
    error_pattern: Pattern[str] | None = None

    # DEPRECATED: always_return_as_data
    # Use success_keywords and error_prefixes instead
    always_return_as_data: bool = False

    def is_error_status(self, status: str) -> bool:
        """Check if a status should be treated as a GraphQL error.

        Returns True for noop:* statuses.

        Args:
            status: The status string from the mutation result

        Returns:
            True if this should be Error type, False if Success type
        """
        if not status:
            return False

        if self.always_return_as_data:
            # DEPRECATED: For backward compatibility only
            import warnings

            warnings.warn(
                "always_return_as_data is deprecated. "
                "Use success_keywords and error_prefixes instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            return False

        status_lower = status.lower()

        # Check success keywords first
        if status_lower in self.success_keywords:
            return False

        # All non-success prefixes are errors

        # Check error prefixes (includes noop: now)
        for prefix in self.error_prefixes:
            if status_lower.startswith(prefix):
                return True

        # Check error keywords
        if any(keyword in status_lower for keyword in self.error_keywords):
            return True

        # Check custom pattern if provided
        if self.error_pattern and self.error_pattern.match(status):
            return True

        # Default: not an error (unknown statuses are success for backward compat)
        return False

    def get_error_code(self, status: str) -> int:
        """Map status string to REST-like error code.

        Args:
            status: The status string from the mutation result

        Returns:
            Application-level error code (422, 404, 409, 500, etc.)
        """
        if not status:
            return 500

        status_lower = status.lower()

        # Validation/business rule failures
        if status_lower.startswith(("noop:", "blocked:", "skipped:", "ignored:")):
            return 422  # Unprocessable Entity

        # "failed:<reason>", what the trinity helpers return (failed:validation,
        # failed:not_found, failed:duplicate), is read like "<reason>:"; any other
        # "failed:" status is a system failure
        failed = status_lower.startswith("failed:")
        category = status_lower.removeprefix("failed:").split(":", 1)[0]
        if failed and category == "duplicate":
            return 409  # Conflict
        return _ERROR_CODES.get(category, 500)


# Codes of the error status prefixes, as the Rust response builder maps them
_ERROR_CODES = {
    "validation": 422,  # Unprocessable Entity
    "not_found": 404,  # Not Found
    "unauthorized": 401,  # Unauthorized
    "forbidden": 403,  # Forbidden
    "conflict": 409,  # Conflict
    "timeout": 408,  # Request Timeout
}


# Updated default configuration
DEFAULT_ERROR_CONFIG = MutationErrorConfig(
    success_keywords={
        "success",
        "completed",
        "ok",
        "done",
        "new",
        "existing",
        "updated",
        "deleted",
        "synced",
        "created",  # Added for enterprise compatibility
        "cancelled",  # Added for enterprise compatibility
    },
    error_prefixes={
        # Validation/business rule failures
        "noop:",
        "blocked:",
        "skipped:",
        "ignored:",
        # Traditional errors
        "error:",
        "failed:",
        "validation:",
        "unauthorized:",
        "forbidden:",
        "not_found:",
        "timeout:",
        "conflict:",
    },
)

# DEPRECATED: STRICT_STATUS_CONFIG
# Use DEFAULT_ERROR_CONFIG instead
STRICT_STATUS_CONFIG = DEFAULT_ERROR_CONFIG


# DEPRECATED: ALWAYS_DATA_CONFIG
# All errors are Error type
def ALWAYS_DATA_CONFIG() -> MutationErrorConfig:  # noqa: D103
    import warnings

    warnings.warn(
        "ALWAYS_DATA_CONFIG is deprecated. All errors return Error type with appropriate codes.",
        DeprecationWarning,
        stacklevel=2,
    )
    return MutationErrorConfig(always_return_as_data=True)

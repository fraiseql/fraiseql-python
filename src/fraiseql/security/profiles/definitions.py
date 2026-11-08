"""Security profile definitions and configurations.

This module defines the security profiles that provide pre-configured
security settings for different deployment scenarios.

**What a profile enforces (1.31)**: nothing on its own. A profile is a
value; ``FraiseQLConfig`` has no ``security_profile`` setting, and
``ProfileEnforcer.apply_to_app`` doesn't work (the app fails to start: it adds
middleware without the configuration they need). A setting takes effect only
where you pass it on:

Enforced, once you pass it on:
- ``max_body_size``: ``BodySizeLimiterMiddleware`` with
  ``ProfileEnforcer.get_body_size_config()`` (413 over the limit).
- ``rate_limit_enabled``, ``rate_limit_requests_per_minute``:
  ``RateLimiterMiddleware`` with ``ProfileEnforcer.get_rate_limit_config()``
  (429 with ``Retry-After``).
- ``max_query_depth``, ``max_query_complexity``: ``FraiseQLConfig(max_query_depth=...,
  complexity_max_score=...)``; see ``fraiseql.gql.query_limits``.
- ``introspection_policy``: ``FraiseQLConfig(introspection_policy=...)``
  (the profile's ``ENABLED`` is the config's ``"public"``).
- ``tls_required``: ``ProfileEnforcer.validate_request_context`` answers 426 to a
  plain-HTTP request, when your code calls it.

Not enforced anywhere: ``mtls_required``, ``min_tls_version``,
``auth_required``, ``token_expiry_minutes``, ``audit_level``,
``audit_field_access``, ``error_detail_level``.

See ``docs/specs/security-compliance.md`` ("Applying a profile").
"""

from dataclasses import dataclass
from enum import Enum


class SecurityProfile(Enum):
    """Available security profile levels."""

    STANDARD = "standard"
    REGULATED = "regulated"
    RESTRICTED = "restricted"


class AuditLevel(Enum):
    """Audit logging levels."""

    MINIMAL = "minimal"
    STANDARD = "standard"
    ENHANCED = "enhanced"
    VERBOSE = "verbose"


class ErrorDetailLevel(Enum):
    """Error detail levels for API responses."""

    FULL = "full"
    SAFE = "safe"
    MINIMAL = "minimal"


class IntrospectionPolicy(Enum):
    """GraphQL introspection policies."""

    ENABLED = "enabled"
    AUTHENTICATED = "authenticated"
    DISABLED = "disabled"


@dataclass
class SecurityProfileConfig:
    """Configuration for a security profile.

    Nothing here is enforced until it is passed on to the middleware or to
    ``FraiseQLConfig``; the module docstring says where each setting goes.

    Attributes:
        profile: The security profile level
        tls_required: Whether TLS is required (``validate_request_context``)
        mtls_required: Whether mutual TLS is required (not enforced)
        min_tls_version: Minimum TLS version (not enforced)
        auth_required: Whether authentication is required (not enforced)
        token_expiry_minutes: Token expiry time in minutes (not enforced)
        introspection_policy: GraphQL introspection policy
            (``FraiseQLConfig.introspection_policy``)
        max_query_depth: Maximum GraphQL query depth
            (``FraiseQLConfig.max_query_depth``)
        max_query_complexity: Maximum GraphQL query complexity
            (``FraiseQLConfig.complexity_max_score``)
        max_body_size: Maximum request body size in bytes
            (``BodySizeLimiterMiddleware``)
        rate_limit_enabled: Whether rate limiting is enabled
            (``RateLimiterMiddleware``)
        rate_limit_requests_per_minute: Rate limit requests per minute
            (``RateLimiterMiddleware``)
        audit_level: Audit logging level (not enforced)
        audit_field_access: Whether to audit field access (not enforced)
        error_detail_level: Error detail level for responses (not enforced)
    """

    profile: SecurityProfile

    # TLS settings
    tls_required: bool = False
    mtls_required: bool = False
    min_tls_version: str = "1.2"

    # Authentication settings
    auth_required: bool = True
    token_expiry_minutes: int = 60

    # GraphQL security settings
    introspection_policy: IntrospectionPolicy = IntrospectionPolicy.AUTHENTICATED
    max_query_depth: int = 10
    max_query_complexity: int = 1000
    max_body_size: int = 1_048_576  # 1MB

    # Rate limiting settings
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 100

    # Audit settings
    audit_level: AuditLevel = AuditLevel.STANDARD
    audit_field_access: bool = False

    # Error handling settings
    error_detail_level: ErrorDetailLevel = ErrorDetailLevel.SAFE

    def to_dict(self) -> dict:
        """Convert configuration to dictionary for serialization."""
        return {
            "profile": self.profile.value,
            "tls_required": self.tls_required,
            "mtls_required": self.mtls_required,
            "min_tls_version": self.min_tls_version,
            "auth_required": self.auth_required,
            "token_expiry_minutes": self.token_expiry_minutes,
            "introspection_policy": self.introspection_policy.value,
            "max_query_depth": self.max_query_depth,
            "max_query_complexity": self.max_query_complexity,
            "max_body_size": self.max_body_size,
            "rate_limit_enabled": self.rate_limit_enabled,
            "rate_limit_requests_per_minute": self.rate_limit_requests_per_minute,
            "audit_level": self.audit_level.value,
            "audit_field_access": self.audit_field_access,
            "error_detail_level": self.error_detail_level.value,
        }


# Pre-defined security profiles

STANDARD_PROFILE = SecurityProfileConfig(
    profile=SecurityProfile.STANDARD,
    tls_required=False,
    mtls_required=False,
    min_tls_version="1.2",
    auth_required=True,
    token_expiry_minutes=60,
    introspection_policy=IntrospectionPolicy.AUTHENTICATED,
    max_query_depth=15,
    max_query_complexity=1000,
    max_body_size=1_048_576,  # 1MB
    rate_limit_enabled=True,
    rate_limit_requests_per_minute=100,
    audit_level=AuditLevel.STANDARD,
    audit_field_access=False,
    error_detail_level=ErrorDetailLevel.SAFE,
)

REGULATED_PROFILE = SecurityProfileConfig(
    profile=SecurityProfile.REGULATED,
    tls_required=True,
    mtls_required=False,
    min_tls_version="1.2",
    auth_required=True,
    token_expiry_minutes=15,
    introspection_policy=IntrospectionPolicy.DISABLED,
    max_query_depth=10,
    max_query_complexity=1000,
    max_body_size=1_048_576,  # 1MB
    rate_limit_enabled=True,
    rate_limit_requests_per_minute=50,
    audit_level=AuditLevel.ENHANCED,
    audit_field_access=True,
    error_detail_level=ErrorDetailLevel.SAFE,
)

RESTRICTED_PROFILE = SecurityProfileConfig(
    profile=SecurityProfile.RESTRICTED,
    tls_required=True,
    mtls_required=True,
    min_tls_version="1.3",
    auth_required=True,
    token_expiry_minutes=5,
    introspection_policy=IntrospectionPolicy.DISABLED,
    max_query_depth=5,
    max_query_complexity=500,
    max_body_size=524_288,  # 512KB
    rate_limit_enabled=True,
    rate_limit_requests_per_minute=10,
    audit_level=AuditLevel.VERBOSE,
    audit_field_access=True,
    error_detail_level=ErrorDetailLevel.MINIMAL,
)


def get_profile(profile: str | SecurityProfile) -> SecurityProfileConfig:
    """Get a security profile configuration by name or enum.

    Args:
        profile: Profile name as string or SecurityProfile enum

    Returns:
        SecurityProfileConfig for the requested profile

    Raises:
        ValueError: If profile name is invalid
    """
    if isinstance(profile, SecurityProfile):
        profile_name = profile.value
    else:
        profile_name = profile.lower()

    profiles = {
        "standard": STANDARD_PROFILE,
        "regulated": REGULATED_PROFILE,
        "restricted": RESTRICTED_PROFILE,
    }

    if profile_name not in profiles:
        available = ", ".join(profiles.keys())
        raise ValueError(
            f"Unknown security profile '{profile_name}'. Available profiles: {available}"
        )

    return profiles[profile_name]

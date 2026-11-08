"""Tests for security profiles."""

from unittest.mock import Mock

import pytest

from fraiseql.security.profiles import (
    REGULATED_PROFILE,
    RESTRICTED_PROFILE,
    STANDARD_PROFILE,
    IntrospectionPolicy,
    ProfileEnforcer,
    QueryValidatorConfig,
    SecurityProfile,
    SecurityProfileConfig,
    get_profile,
)


class TestSecurityProfile:
    """Tests for SecurityProfile enum."""

    def test_standard_profile_exists(self):
        assert SecurityProfile.STANDARD.value == "standard"

    def test_regulated_profile_exists(self):
        assert SecurityProfile.REGULATED.value == "regulated"

    def test_restricted_profile_exists(self):
        assert SecurityProfile.RESTRICTED.value == "restricted"


class TestSecurityProfileConfig:
    """Tests for SecurityProfileConfig."""

    def test_standard_profile_allows_introspection(self):
        assert STANDARD_PROFILE.introspection_policy == IntrospectionPolicy.AUTHENTICATED

    def test_regulated_profile_disables_introspection(self):
        assert REGULATED_PROFILE.introspection_policy == IntrospectionPolicy.DISABLED

    def test_restricted_profile_requires_mtls(self):
        assert RESTRICTED_PROFILE.mtls_required is True

    def test_restricted_profile_smaller_body_size(self):
        assert RESTRICTED_PROFILE.max_body_size == 524_288  # 512KB

    def test_to_dict_serialization(self):
        result = STANDARD_PROFILE.to_dict()
        assert result["profile"] == "standard"
        assert "max_body_size" in result


class TestGetProfile:
    """Tests for get_profile function."""

    def test_get_by_string(self):
        profile = get_profile("standard")
        assert profile.profile == SecurityProfile.STANDARD

    def test_get_by_enum(self):
        profile = get_profile(SecurityProfile.REGULATED)
        assert profile.profile == SecurityProfile.REGULATED

    def test_invalid_profile_raises(self):
        with pytest.raises(ValueError):
            get_profile("invalid")


class TestQueryValidatorConfig:
    """Test QueryValidatorConfig dataclass."""

    def test_query_validator_config_creation(self):
        """Test creating a QueryValidatorConfig instance."""
        config = QueryValidatorConfig(
            max_depth=10,
            max_complexity=1000,
            introspection_enabled=True,
            field_validation_enabled=True,
        )

        assert config.max_depth == 10
        assert config.max_complexity == 1000
        assert config.introspection_enabled is True
        assert config.field_validation_enabled is True

    def test_query_validator_config_to_dict(self):
        """Test converting QueryValidatorConfig to dictionary."""
        config = QueryValidatorConfig(
            max_depth=5,
            max_complexity=500,
            introspection_enabled=False,
            field_validation_enabled=True,
        )

        expected = {
            "max_depth": 5,
            "max_complexity": 500,
            "introspection_enabled": False,
            "field_validation_enabled": True,
        }

        assert config.to_dict() == expected


class TestProfileEnforcer:
    """Test ProfileEnforcer class."""

    def test_profile_enforcer_creation(self):
        """Test creating a ProfileEnforcer instance."""
        enforcer = ProfileEnforcer(STANDARD_PROFILE)
        assert enforcer.profile_config == STANDARD_PROFILE

    def test_get_body_size_config(self):
        """Test getting body size config from profile."""
        enforcer = ProfileEnforcer(STANDARD_PROFILE)

        config = enforcer.get_body_size_config()

        assert config.max_body_size == STANDARD_PROFILE.max_body_size
        assert config.exempt_methods == {"GET", "HEAD", "OPTIONS"}
        assert config.exempt_paths == []

    def test_get_rate_limit_config(self):
        """Test getting rate limit config from profile."""
        enforcer = ProfileEnforcer(STANDARD_PROFILE)

        config = enforcer.get_rate_limit_config()

        assert config.enabled == STANDARD_PROFILE.rate_limit_enabled
        assert config.requests_per_minute == STANDARD_PROFILE.rate_limit_requests_per_minute
        assert config.requests_per_hour == STANDARD_PROFILE.rate_limit_requests_per_minute * 60
        assert config.burst_size == min(10, STANDARD_PROFILE.rate_limit_requests_per_minute // 6)
        assert config.window_type == "sliding"
        assert config.whitelist == []
        assert config.blacklist == []

    def test_get_query_validator_config(self):
        """Test getting query validator config from profile."""
        enforcer = ProfileEnforcer(STANDARD_PROFILE)

        config = enforcer.get_query_validator_config()

        assert config.max_depth == STANDARD_PROFILE.max_query_depth
        assert config.max_complexity == STANDARD_PROFILE.max_query_complexity
        assert config.introspection_enabled is True  # STANDARD allows authenticated introspection
        assert config.field_validation_enabled is True

    def test_get_query_validator_config_regulated(self):
        """Test query validator config for regulated profile."""
        enforcer = ProfileEnforcer(REGULATED_PROFILE)

        config = enforcer.get_query_validator_config()

        assert config.max_depth == REGULATED_PROFILE.max_query_depth
        assert config.max_complexity == REGULATED_PROFILE.max_query_complexity
        assert config.introspection_enabled is False  # REGULATED disables introspection
        assert config.field_validation_enabled is True

    def test_get_middleware_stack(self):
        """Test getting middleware stack from profile."""
        enforcer = ProfileEnforcer(STANDARD_PROFILE)

        middleware_stack = enforcer.get_middleware_stack()

        # Should include body size limiter, rate limiter, security headers, CSRF protection
        assert len(middleware_stack) == 4

        # Check middleware classes (without instantiating)
        middleware_classes = [item[0] for item in middleware_stack]
        middleware_names = [cls.__name__ for cls in middleware_classes]

        assert "BodySizeLimiterMiddleware" in middleware_names
        assert "RateLimiterMiddleware" in middleware_names
        assert "SecurityHeadersMiddleware" in middleware_names
        assert "CSRFProtectionMiddleware" in middleware_names

    def test_get_middleware_stack_disabled_rate_limit(self):
        """Test middleware stack when rate limiting is disabled."""
        # Create a custom profile with rate limiting disabled
        custom_profile = SecurityProfileConfig(
            profile=SecurityProfile.STANDARD,
            rate_limit_enabled=False,
            max_body_size=1_048_576,
            max_query_depth=15,
            max_query_complexity=1000,
            rate_limit_requests_per_minute=100,
        )

        enforcer = ProfileEnforcer(custom_profile)
        middleware_stack = enforcer.get_middleware_stack()

        # Should still include body size limiter, security headers, CSRF protection
        # but not rate limiter
        assert len(middleware_stack) == 3

        middleware_classes = [item[0] for item in middleware_stack]
        middleware_names = [cls.__name__ for cls in middleware_classes]

        assert "BodySizeLimiterMiddleware" in middleware_names
        assert "RateLimiterMiddleware" not in middleware_names
        assert "SecurityHeadersMiddleware" in middleware_names
        assert "CSRFProtectionMiddleware" in middleware_names

    def test_validate_request_context_https_required(self):
        """Test request validation when HTTPS is required."""
        enforcer = ProfileEnforcer(REGULATED_PROFILE)

        # Mock request with HTTP
        mock_request = Mock()
        mock_request.url.scheme = "http"

        with pytest.raises(Exception) as exc_info:
            enforcer.validate_request_context(mock_request)

        assert "HTTPS required" in str(exc_info.value)

    def test_validate_request_context_https_allowed(self):
        """Test request validation when HTTPS is not required."""
        enforcer = ProfileEnforcer(STANDARD_PROFILE)

        # Mock request with HTTP (should be allowed)
        mock_request = Mock()
        mock_request.url.scheme = "http"
        mock_request.headers = {}  # No content-length header

        context = enforcer.validate_request_context(mock_request)

        assert context["profile"] == "standard"
        assert context["tls_required"] is False
        assert context["validation_passed"] is True

    def test_validate_request_context_body_size_check(self):
        """Test request validation with body size check."""
        enforcer = ProfileEnforcer(STANDARD_PROFILE)

        # Mock request with large content-length
        mock_request = Mock()
        mock_request.url.scheme = "https"
        mock_request.headers = {"content-length": str(STANDARD_PROFILE.max_body_size + 1)}

        with pytest.raises(Exception) as exc_info:
            enforcer.validate_request_context(mock_request)

        assert "Request body too large" in str(exc_info.value)

    def test_apply_to_app(self):
        """Test applying profile to FastAPI app."""
        enforcer = ProfileEnforcer(STANDARD_PROFILE)

        # Mock FastAPI app
        mock_app = Mock()
        mock_app.add_middleware = Mock()
        mock_app.state = Mock()

        enforcer.apply_to_app(mock_app)

        # Should have called add_middleware for each middleware in the stack
        assert mock_app.add_middleware.call_count == 4

        # Should have set profile config and enforcer on app state
        assert mock_app.state.security_profile == STANDARD_PROFILE
        assert mock_app.state.profile_enforcer == enforcer

    def test_default_key_func(self):
        """Test default rate limiting key function."""
        enforcer = ProfileEnforcer(STANDARD_PROFILE)

        # Mock request with client
        mock_request = Mock()
        mock_client = Mock()
        mock_client.host = "192.168.1.1"
        mock_request.client = mock_client

        # Create a simple object without user_id
        class MockState:
            pass

        mock_request.state = MockState()

        key = enforcer._default_key_func(mock_request)
        assert key == "192.168.1.1"

    def test_default_key_func_with_user(self):
        """Test default key function with authenticated user."""
        enforcer = ProfileEnforcer(STANDARD_PROFILE)

        # Mock request with client and user
        mock_request = Mock()
        mock_client = Mock()
        mock_client.host = "192.168.1.1"
        mock_request.client = mock_client

        # Create a simple object with user_id
        class MockState:
            user_id = "user123"

        mock_request.state = MockState()

        key = enforcer._default_key_func(mock_request)
        assert key == "192.168.1.1:user123"

    def test_default_key_func_anonymous(self):
        """Test default key function for anonymous requests."""
        enforcer = ProfileEnforcer(STANDARD_PROFILE)

        # Mock request without client
        mock_request = Mock()
        mock_request.client = None

        # Create a simple object without user_id
        class MockState:
            pass

        mock_request.state = MockState()

        key = enforcer._default_key_func(mock_request)
        assert key == "anonymous"


class TestProfileEnforcerIntegration:
    """Integration tests for ProfileEnforcer with different profiles."""

    @pytest.mark.parametrize(
        ("profile", "expected_middleware_count"),
        [
            (STANDARD_PROFILE, 4),  # body size, rate limit, security headers, csrf
            (REGULATED_PROFILE, 4),  # same as standard
            (RESTRICTED_PROFILE, 4),  # same as standard
        ],
    )
    def test_middleware_stack_sizes(self, profile, expected_middleware_count):
        """Test middleware stack sizes for different profiles."""
        enforcer = ProfileEnforcer(profile)
        middleware_stack = enforcer.get_middleware_stack()

        assert len(middleware_stack) == expected_middleware_count

    def test_restricted_profile_strictness(self):
        """Test that restricted profile has strictest settings."""
        enforcer = ProfileEnforcer(RESTRICTED_PROFILE)

        body_config = enforcer.get_body_size_config()
        rate_config = enforcer.get_rate_limit_config()
        query_config = enforcer.get_query_validator_config()

        # Restricted should have smallest body size limit
        assert body_config.max_body_size == RESTRICTED_PROFILE.max_body_size
        assert body_config.max_body_size < STANDARD_PROFILE.max_body_size

        # Restricted should have lowest rate limits
        assert rate_config.requests_per_minute == RESTRICTED_PROFILE.rate_limit_requests_per_minute
        assert rate_config.requests_per_minute < STANDARD_PROFILE.rate_limit_requests_per_minute

        # Restricted should have lowest query limits
        assert query_config.max_depth == RESTRICTED_PROFILE.max_query_depth
        assert query_config.max_depth < STANDARD_PROFILE.max_query_depth
        assert query_config.introspection_enabled is False

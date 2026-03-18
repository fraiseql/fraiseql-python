"""Tests for FraiseQLConfig session_variables validation."""

import pytest
from pydantic import ValidationError

from fraiseql.fastapi.config import FraiseQLConfig

DB_URL = "postgresql://localhost/test"


@pytest.mark.unit
class TestSessionVariablesConfigValidation:
    """Test session_variables configuration validation."""

    def test_valid_session_variable_names(self) -> None:
        """Accept valid PostgreSQL session variable names."""
        config = FraiseQLConfig(
            database_url=DB_URL,
            session_variables={
                "locale": "app.locale",
                "timezone": "app.timezone",
                "tenant_mode": "app.tenant_mode",
            },
        )
        assert config.session_variables == {
            "locale": "app.locale",
            "timezone": "app.timezone",
            "tenant_mode": "app.tenant_mode",
        }

    def test_empty_session_variables(self) -> None:
        """Empty dict is the default and is valid."""
        config = FraiseQLConfig(database_url=DB_URL)
        assert config.session_variables == {}

    def test_reject_sql_injection_semicolon(self) -> None:
        """Reject variable names containing semicolons."""
        with pytest.raises(ValidationError, match="Invalid characters"):
            FraiseQLConfig(
                database_url=DB_URL,
                session_variables={"locale": "app.locale; DROP TABLE users"},
            )

    def test_reject_sql_injection_quotes(self) -> None:
        """Reject variable names containing quotes."""
        with pytest.raises(ValidationError, match="Invalid characters"):
            FraiseQLConfig(
                database_url=DB_URL,
                session_variables={"locale": "app.locale' OR '1'='1"},
            )

    def test_reject_sql_injection_comment(self) -> None:
        """Reject variable names containing SQL comments."""
        with pytest.raises(ValidationError, match="Invalid characters"):
            FraiseQLConfig(
                database_url=DB_URL,
                session_variables={"locale": "app.locale--comment"},
            )

    def test_reject_empty_variable_name(self) -> None:
        """Reject empty variable name."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            FraiseQLConfig(
                database_url=DB_URL,
                session_variables={"locale": ""},
            )

    def test_reject_whitespace_only_variable_name(self) -> None:
        """Reject whitespace-only variable name."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            FraiseQLConfig(
                database_url=DB_URL,
                session_variables={"locale": "   "},
            )

    def test_reject_spaces_in_variable_name(self) -> None:
        """Reject variable names containing spaces."""
        with pytest.raises(ValidationError, match="Invalid characters"):
            FraiseQLConfig(
                database_url=DB_URL,
                session_variables={"locale": "app locale"},
            )

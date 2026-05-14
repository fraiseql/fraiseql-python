"""Tests for FraiseQLConfig collation validation."""

import pytest
from pydantic import ValidationError

from fraiseql.fastapi.config import FraiseQLConfig


@pytest.mark.unit
class TestCollationConfigValidation:
    """Test collation configuration validation."""

    def test_valid_collation_names(self):
        """Test various valid collation formats."""
        valid_collations = [
            "en_US.utf8",
            "fr_FR.utf8",
            "C",
            "POSIX",
            "de_DE.UTF-8",
            "ja_JP.eucjp",
        ]

        for collation in valid_collations:
            config = FraiseQLConfig(
                database_url="postgresql://localhost/test",
                default_string_collation=collation
            )
            assert config.default_string_collation == collation

    def test_none_collation(self):
        """Test that None is valid (no global default)."""
        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            default_string_collation=None
        )
        assert config.default_string_collation is None

    def test_sql_injection_protection_double_quote(self):
        """Test that double quotes are rejected."""
        with pytest.raises(ValidationError, match="Invalid characters"):
            FraiseQLConfig(
                database_url="postgresql://localhost/test",
                default_string_collation='en_US"; DROP TABLE--'
            )

    def test_sql_injection_protection_single_quote(self):
        """Test that single quotes are rejected."""
        with pytest.raises(ValidationError, match="Invalid characters"):
            FraiseQLConfig(
                database_url="postgresql://localhost/test",
                default_string_collation="C' OR '1'='1"
            )

    def test_sql_injection_protection_semicolon(self):
        """Test that semicolons are rejected."""
        with pytest.raises(ValidationError, match="Invalid characters"):
            FraiseQLConfig(
                database_url="postgresql://localhost/test",
                default_string_collation="fr_FR; DELETE FROM"
            )

    def test_sql_injection_protection_double_dash(self):
        """Test that double dashes (SQL comments) are rejected."""
        with pytest.raises(ValidationError, match="Invalid characters"):
            FraiseQLConfig(
                database_url="postgresql://localhost/test",
                default_string_collation="'; DROP TABLE users--"
            )

    def test_sql_injection_protection_block_comment(self):
        """Test that block comment markers are rejected."""
        with pytest.raises(ValidationError, match="Invalid characters"):
            FraiseQLConfig(
                database_url="postgresql://localhost/test",
                default_string_collation="/* comment */"
            )

    def test_sql_injection_protection_backslash(self):
        """Test that backslashes are rejected."""
        with pytest.raises(ValidationError, match="Invalid characters"):
            FraiseQLConfig(
                database_url="postgresql://localhost/test",
                default_string_collation="en_US\\escape"
            )

    def test_empty_string_rejected(self):
        """Test that empty string is rejected."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            FraiseQLConfig(
                database_url="postgresql://localhost/test",
                default_string_collation=""
            )

    def test_whitespace_only_rejected(self):
        """Test that whitespace-only string is rejected."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            FraiseQLConfig(
                database_url="postgresql://localhost/test",
                default_string_collation="   "
            )

    def test_config_without_collation_field(self):
        """Test that config works when collation field is omitted."""
        config = FraiseQLConfig(
            database_url="postgresql://localhost/test"
        )
        assert config.default_string_collation is None

    def test_collation_with_dots_allowed(self):
        """Test that dots (common in collation names) are allowed."""
        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            default_string_collation="en_US.utf8"
        )
        assert config.default_string_collation == "en_US.utf8"

    def test_collation_with_hyphens_allowed(self):
        """Test that hyphens (common in collation names) are allowed."""
        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            default_string_collation="de_DE.UTF-8"
        )
        assert config.default_string_collation == "de_DE.UTF-8"

    def test_collation_with_underscores_allowed(self):
        """Test that underscores (common in collation names) are allowed."""
        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            default_string_collation="en_US"
        )
        assert config.default_string_collation == "en_US"

    def test_collation_case_preserved(self):
        """Test that collation name case is preserved."""
        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            default_string_collation="POSIX"
        )
        assert config.default_string_collation == "POSIX"

    def test_config_serialization_with_collation(self):
        """Test that config with collation can be serialized."""
        config = FraiseQLConfig(
            database_url="postgresql://localhost/test",
            default_string_collation="fr_FR.utf8"
        )
        # Should be able to dump to dict
        config_dict = config.model_dump()
        assert config_dict["default_string_collation"] == "fr_FR.utf8"

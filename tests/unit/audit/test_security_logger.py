"""Tests for SecurityLogger — issue #326."""

import logging

from fraiseql.audit.security_logger import SecurityLogger


def test_graceful_degradation_on_permission_error(tmp_path):
    """SecurityLogger should not crash when log file is not writable."""
    # Point to a path that doesn't exist inside a read-only directory
    unwritable = tmp_path / "readonly"
    unwritable.mkdir()
    unwritable.chmod(0o444)
    log_path = str(unwritable / "security_events.log")

    # Should not raise — falls back to stderr-only logging
    sec_logger = SecurityLogger(log_to_file=True, log_to_stdout=False, log_file_path=log_path)

    # Logger should still be functional (no file handler, but no crash)
    assert sec_logger is not None

    # Cleanup
    unwritable.chmod(0o755)


def test_graceful_degradation_warning_logged(tmp_path, caplog):
    """Should log a warning when file handler creation fails."""
    unwritable = tmp_path / "readonly"
    unwritable.mkdir()
    unwritable.chmod(0o444)
    log_path = str(unwritable / "security_events.log")

    with caplog.at_level(logging.WARNING, logger="fraiseql.security"):
        SecurityLogger(log_to_file=True, log_to_stdout=False, log_file_path=log_path)

    assert any("Cannot write security log" in record.message for record in caplog.records)

    # Cleanup
    unwritable.chmod(0o755)


def test_env_var_overrides_default_path(tmp_path, monkeypatch):
    """FRAISEQL_SECURITY_LOG_PATH env var should override the default path."""
    log_path = str(tmp_path / "custom_security.log")
    monkeypatch.setenv("FRAISEQL_SECURITY_LOG_PATH", log_path)

    sec_logger = SecurityLogger(log_to_file=True, log_to_stdout=False)
    assert sec_logger is not None

    # The file should have been created at the env var path
    assert (tmp_path / "custom_security.log").exists()


def test_explicit_path_takes_precedence_over_env(tmp_path, monkeypatch):
    """Explicit log_file_path should take precedence over env var."""
    env_path = str(tmp_path / "env_security.log")
    explicit_path = str(tmp_path / "explicit_security.log")
    monkeypatch.setenv("FRAISEQL_SECURITY_LOG_PATH", env_path)

    SecurityLogger(log_to_file=True, log_to_stdout=False, log_file_path=explicit_path)

    assert (tmp_path / "explicit_security.log").exists()
    assert not (tmp_path / "env_security.log").exists()


def test_file_logging_works_when_writable(tmp_path):
    """Normal case: file handler should work when path is writable."""
    log_path = str(tmp_path / "security_events.log")
    sec_logger = SecurityLogger(log_to_file=True, log_to_stdout=False, log_file_path=log_path)
    assert sec_logger is not None
    assert (tmp_path / "security_events.log").exists()

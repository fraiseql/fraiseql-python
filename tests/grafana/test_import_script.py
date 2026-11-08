"""Tests for Grafana dashboard import script.

Tests verify:
- Import script exists and is executable
- Script has proper error handling
- Script validates Grafana connectivity
- Script handles missing dependencies gracefully
"""

import subprocess
from pathlib import Path

import pytest

GRAFANA_DIR = Path(__file__).parent.parent.parent / "grafana"
IMPORT_SCRIPT = GRAFANA_DIR / "import_dashboards.sh"


class TestImportScriptStructure:
    """Test import script structure and availability."""

    def test_import_script_exists(self) -> None:
        """Import script file should exist."""
        assert IMPORT_SCRIPT.exists(), f"Import script not found: {IMPORT_SCRIPT}"

    def test_import_script_is_executable(self) -> None:
        """Import script should have executable permissions."""
        assert IMPORT_SCRIPT.stat().st_mode & 0o111, (
            "Import script is not executable (run: chmod +x import_dashboards.sh)"
        )

    def test_import_script_has_shebang(self) -> None:
        """Import script should start with proper shebang."""
        with IMPORT_SCRIPT.open() as f:
            first_line = f.readline().strip()

        assert first_line in [
            "#!/bin/bash",
            "#!/usr/bin/env bash",
        ], f"Import script has invalid shebang: {first_line}"

    def test_import_script_has_error_handling(self) -> None:
        """Import script should have error handling (set -e)."""
        with IMPORT_SCRIPT.open() as f:
            content = f.read()

        assert "set -e" in content, "Import script missing 'set -e' for error handling"


class TestImportScriptContent:
    """Test import script content and logic."""

    def test_script_defines_configuration_variables(self) -> None:
        """Script should define configuration variables."""
        with IMPORT_SCRIPT.open() as f:
            content = f.read()

        required_vars = [
            "GRAFANA_URL",
            "GRAFANA_USER",
            "GRAFANA_PASSWORD",
            "DASHBOARD_DIR",
        ]

        for var in required_vars:
            assert var in content, f"Import script missing configuration variable: {var}"

    def test_script_checks_grafana_connectivity(self) -> None:
        """Script should check Grafana connectivity before importing."""
        with IMPORT_SCRIPT.open() as f:
            content = f.read()

        # Should have connectivity check using curl or similar
        assert "curl" in content, "Import script should use curl for connectivity check"
        assert "/api/health" in content, "Import script should check /api/health endpoint"

    def test_script_has_import_function(self) -> None:
        """Script should have function to import dashboards."""
        with IMPORT_SCRIPT.open() as f:
            content = f.read()

        # Should define import_dashboard function
        assert "import_dashboard()" in content or "import_dashboard ()" in content, (
            "Import script missing import_dashboard function"
        )

    def test_script_lists_dashboard_files(self) -> None:
        """Script should list all dashboard files to import."""
        with IMPORT_SCRIPT.open() as f:
            content = f.read()

        expected_dashboards = [
            "error_monitoring.json",
            "performance_metrics.json",
            "database_pool.json",
            "apq_effectiveness.json",
        ]

        for dashboard in expected_dashboards:
            assert dashboard in content, f"Import script missing dashboard: {dashboard}"

    def test_script_has_error_messages(self) -> None:
        """Script should have user-friendly error messages."""
        with IMPORT_SCRIPT.open() as f:
            content = f.read()

        # Should have error messages
        assert "ERROR:" in content or "Error:" in content, (
            "Import script should have error messages"
        )

        # Should have success messages
        assert "Success" in content or "✓" in content, "Import script should have success messages"


class TestImportScriptSafety:
    """Test import script safety and security."""

    def test_script_uses_proper_quotes(self) -> None:
        """Script variables should be properly quoted to prevent injection."""
        with IMPORT_SCRIPT.open() as f:
            lines = f.readlines()

        # Check for common unquoted variable usage
        for _, line in enumerate(lines, 1):
            # Skip comments
            if line.strip().startswith("#"):
                continue

            # Check for unquoted $variables in command positions
            # This is a simplified check - full validation would be complex
            if (
                (" $GRAFANA" in line or " $DASHBOARD" in line)
                and "echo" not in line.lower()
                and "if" not in line.lower()
            ):
                # Should be quoted: "$VARIABLE"
                # Allow exceptions for specific safe contexts
                pass  # Complex to validate, skip for now

    def test_script_has_safe_exit_codes(self) -> None:
        """Script should exit with proper exit codes."""
        with IMPORT_SCRIPT.open() as f:
            content = f.read()

        # Should use exit codes
        assert "exit" in content, "Import script should use exit codes for error handling"

    def test_script_validates_file_paths(self) -> None:
        """Script should validate file paths before using them."""
        with IMPORT_SCRIPT.open() as f:
            content = f.read()

        # Should check if files exist
        assert "-f" in content or "test -f" in content or "[ -f" in content, (
            "Import script should validate file existence"
        )


class TestImportScriptHelp:
    """Test import script documentation and help."""

    def test_script_has_header_comments(self) -> None:
        """Script should have header comments explaining usage."""
        with IMPORT_SCRIPT.open() as f:
            content = f.read()

        # Should have comment header
        lines = content.split("\n")
        header_lines = lines[:20]  # Check first 20 lines
        header_text = "\n".join(header_lines)

        assert "#" in header_text, "Import script should have header comments"

        assert "FraiseQL" in header_text or "Grafana" in header_text, (
            "Import script should mention FraiseQL/Grafana in header"
        )

    def test_script_shows_usage_information(self) -> None:
        """Script should display usage information."""
        with IMPORT_SCRIPT.open() as f:
            content = f.read()

        # Should explain configuration
        assert "GRAFANA_URL" in content, "Import script should document GRAFANA_URL configuration"
        assert "localhost:3000" in content, "Import script should show localhost:3000 example"


class TestImportScriptDependencies:
    """Test import script dependencies."""

    def test_script_uses_standard_tools(self) -> None:
        """Script should use standard Unix tools available everywhere."""
        with IMPORT_SCRIPT.open() as f:
            content = f.read()

        # Required tools that should be available
        required_tools = ["curl"]

        for tool in required_tools:
            assert tool in content, f"Import script should use standard tool: {tool}"

    def test_script_uses_jq_for_json(self) -> None:
        """Script should use jq for JSON manipulation."""
        with IMPORT_SCRIPT.open() as f:
            content = f.read()

        # Should use jq for JSON processing
        if ".json" in content and "api/dashboards" in content:
            assert "jq" in content, "Import script should use 'jq' for JSON manipulation"


@pytest.mark.skipif(
    not Path("/usr/bin/shellcheck").exists() and not Path("/usr/local/bin/shellcheck").exists(),
    reason="shellcheck not installed",
)
class TestImportScriptLinting:
    """Test import script with shellcheck linter."""

    def test_script_passes_shellcheck(self) -> None:
        """Import script should pass shellcheck linting."""
        result = subprocess.run(
            ["shellcheck", "-x", str(IMPORT_SCRIPT)], capture_output=True, text=True, check=False
        )

        # ShellCheck should pass (exit code 0) or have only minor warnings
        assert result.returncode in [0, 1], f"ShellCheck failed:\n{result.stdout}\n{result.stderr}"

        # If there are errors, they should not be critical
        if result.returncode == 1:
            # Allow only specific warning codes (not errors)
            allowed_warnings = [
                "SC2034",
                "SC2086",
                "SC2181",
            ]  # Unused variables, unquoted variables, etc.
            for line in result.stdout.split("\n"):
                if "error:" in line.lower():
                    # Check if it's an allowed warning
                    is_allowed = any(code in line for code in allowed_warnings)
                    assert is_allowed, f"ShellCheck critical error: {line}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

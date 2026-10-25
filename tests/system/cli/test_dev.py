import pytest

pytestmark = pytest.mark.integration

"""Tests for the dev command."""

from pathlib import Path
from unittest.mock import patch

from fraiseql.cli.main import cli


@pytest.mark.unit
class TestDevCommand:
    """Test the fraiseql dev command."""

    def test_dev_requires_project(self, cli_runner, temp_project_dir) -> None:
        """Test that dev command requires being in a project directory."""
        result = cli_runner.invoke(cli, ["dev"])

        assert result.exit_code != 0
        assert "Not in a FraiseQL project directory" in result.output
        assert "Run 'fraiseql init' to create a new project" in result.output

    def test_dev_starts_server(self, cli_runner, temp_project_dir) -> None:
        """Test that dev starts the server (mocking uvicorn)."""
        # Create a minimal project structure
        Path("pyproject.toml").write_text('[project]\nname = "test"')

        # We still need to mock uvicorn.run since we don't want to actually start a server
        with patch("fraiseql.cli.commands.dev.uvicorn") as mock_uvicorn:
            result = cli_runner.invoke(cli, ["dev"])

            assert result.exit_code == 0
            assert "Starting FraiseQL development server" in result.output
            assert "GraphQL API: http://127.0.0.1:8000/graphql" in result.output
            assert "Auto-reload: enabled" in result.output

            # Verify uvicorn was called
            mock_uvicorn.run.assert_called_once_with(
                "src.main:app",
                host="127.0.0.1",
                port=8000,
                reload=True,
                log_level="info",
                app_dir=str(Path.cwd()),
            )

    def test_dev_custom_options(self, cli_runner, temp_project_dir) -> None:
        """Test dev command with custom options."""
        Path("pyproject.toml").write_text('[project]\nname = "test"')

        with patch("fraiseql.cli.commands.dev.uvicorn") as mock_uvicorn:
            result = cli_runner.invoke(
                cli,
                [
                    "dev",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "3000",
                    "--no-reload",
                    "--app",
                    "myapp:application",
                ],
            )

            assert result.exit_code == 0
            assert "GraphQL API: http://0.0.0.0:3000/graphql" in result.output
            assert "Auto-reload: enabled" not in result.output

            mock_uvicorn.run.assert_called_once_with(
                "myapp:application",
                host="0.0.0.0",
                port=3000,
                reload=False,
                log_level="info",
                app_dir=str(Path.cwd()),
            )

    def test_dev_loads_env_file(self, cli_runner, temp_project_dir) -> None:
        """Test that dev loads .env file if present."""
        Path("pyproject.toml").write_text('[project]\nname = "test"')
        Path(".env").write_text("DATABASE_URL=postgresql://test/db\nSECRET=123")

        with patch("fraiseql.cli.commands.dev.uvicorn"):
            # Check if dotenv is available
            try:
                import dotenv  # noqa: F401

                with patch("fraiseql.cli.commands.dev.load_dotenv") as mock_load:
                    result = cli_runner.invoke(cli, ["dev"])

                    assert result.exit_code == 0
                    assert "Loading environment from .env file" in result.output
                    mock_load.assert_called_once()
            except ImportError:
                # If dotenv is not installed, just check it doesn't crash
                result = cli_runner.invoke(cli, ["dev"])
                assert result.exit_code == 0

    def test_dev_handles_missing_uvicorn(self, cli_runner, temp_project_dir) -> None:
        """Test error when uvicorn is not installed."""
        Path("pyproject.toml").write_text('[project]\nname = "test"')

        # Force uvicorn to be None
        with patch("fraiseql.cli.commands.dev.uvicorn", None):
            result = cli_runner.invoke(cli, ["dev"])

            assert result.exit_code != 0
            assert "uvicorn not installed" in result.output
            assert "pip install uvicorn" in result.output

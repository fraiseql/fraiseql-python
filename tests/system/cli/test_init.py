import pytest

pytestmark = pytest.mark.integration

"""Tests for the init command."""

from pathlib import Path

from fraiseql.cli.commands.init import FRAISEQL_PIN, REQUIRES_PYTHON
from fraiseql.cli.main import cli


@pytest.mark.unit
class TestInitCommand:
    """Test the fraiseql init command."""

    def test_init_creates_project_structure(self, cli_runner, temp_project_dir) -> None:
        """Test that init creates the expected project structure."""
        result = cli_runner.invoke(cli, ["init", "myproject"])

        assert result.exit_code == 0
        assert "Creating FraiseQL project 'myproject'" in result.output
        assert "Project 'myproject' created successfully!" in result.output

        # Check directory structure
        project_path = temp_project_dir / "myproject"
        assert project_path.exists()
        assert (project_path / "src").exists()
        assert (project_path / "src" / "types").exists()
        assert (project_path / "src" / "mutations").exists()
        assert (project_path / "src" / "queries").exists()
        assert (project_path / "tests").exists()
        assert (project_path / "db" / "migrations").exists()

        # Check files
        assert (project_path / ".env").exists()
        assert (project_path / ".gitignore").exists()
        assert (project_path / "pyproject.toml").exists()
        assert (project_path / "README.md").exists()
        assert (project_path / "src" / "main.py").exists()

    def test_init_with_existing_directory(self, cli_runner, temp_project_dir) -> None:
        """Test that init fails if directory already exists."""
        # Create directory first
        Path("myproject").mkdir()

        result = cli_runner.invoke(cli, ["init", "myproject"])

        assert result.exit_code != 0
        assert "Directory 'myproject' already exists" in result.output

    def test_init_basic_template(self, cli_runner, temp_project_dir) -> None:
        """Test basic template creation."""
        result = cli_runner.invoke(cli, ["init", "myproject", "--template", "basic"])

        assert result.exit_code == 0

        # Check main.py has basic User type
        main_py = (temp_project_dir / "myproject" / "src" / "main.py").read_text()
        assert "@fraiseql.type" in main_py
        assert "class User:" in main_py
        assert "fraiseql.create_fraiseql_app" in main_py

    def test_init_blog_template(self, cli_runner, temp_project_dir) -> None:
        """Test blog template creation."""
        result = cli_runner.invoke(cli, ["init", "myproject", "--template", "blog"])

        assert result.exit_code == 0

        # Check blog types were created
        types_dir = temp_project_dir / "myproject" / "src" / "types"
        assert (types_dir / "user.py").exists()
        assert (types_dir / "post.py").exists()
        assert (types_dir / "comment.py").exists()

        # Check content
        user_py = (types_dir / "user.py").read_text()
        assert "class User:" in user_py
        assert 'posts: list["Post"]' in user_py

    def test_init_custom_database_url(self, cli_runner, temp_project_dir) -> None:
        """Test custom database URL in .env file."""
        custom_url = "postgresql://user:pass@host:5432/mydb"
        result = cli_runner.invoke(cli, ["init", "myproject", "--database-url", custom_url])

        assert result.exit_code == 0

        # Check .env file
        env_content = (temp_project_dir / "myproject" / ".env").read_text()
        assert f"DATABASE_URL={custom_url}" in env_content

    def test_init_no_git(self, cli_runner, temp_project_dir) -> None:
        """Test --no-git flag skips git initialization."""
        result = cli_runner.invoke(cli, ["init", "myproject", "--no-git"])

        assert result.exit_code == 0
        assert "Initialized git repository" not in result.output

        # Check no .git directory
        assert not (temp_project_dir / "myproject" / ".git").exists()

    def test_init_pyproject_content(self, cli_runner, temp_project_dir) -> None:
        """Test pyproject.toml has correct content."""
        result = cli_runner.invoke(cli, ["init", "testproject"])

        assert result.exit_code == 0

        pyproject = (temp_project_dir / "testproject" / "pyproject.toml").read_text()
        assert 'name = "testproject"' in pyproject
        assert FRAISEQL_PIN in pyproject
        assert f'requires-python = "{REQUIRES_PYTHON}"' in pyproject
        assert "[tool.ruff]" in pyproject
        assert "[tool.pyright]" in pyproject

    def test_init_creates_proper_gitignore(self, cli_runner, temp_project_dir) -> None:
        """Test .gitignore contains necessary patterns."""
        result = cli_runner.invoke(cli, ["init", "myproject"])

        assert result.exit_code == 0

        gitignore = (temp_project_dir / "myproject" / ".gitignore").read_text()
        assert "__pycache__/" in gitignore
        assert ".env" in gitignore
        assert ".venv/" in gitignore
        assert "*.egg-info/" in gitignore

"""Initialize a new FraiseQL project."""

import shutil
import subprocess
from pathlib import Path

import click

# v1 and v2 share the `fraiseql` name on PyPI and the bare name resolves to v2,
# which is a different framework. A generated project must pin below 2.
FRAISEQL_PIN = "fraiseql>=1.25,<2"
REQUIRES_PYTHON = ">=3.13,<3.14"
PYTHON_TAG = "py313"
PYTHON_VERSION = "3.13"

# Credentials for the Postgres this project ships with, kept in one place so
# .env and docker-compose.yml cannot drift apart.
DB_USER = "fraiseql"
DB_PASSWORD = "fraiseql"
# Deliberately far from 5432: a developer with PostgreSQL already installed
# would otherwise hit "port is already allocated" on their first
# docker compose up. The container still listens on 5432 internally.
DB_PORT = 54320


def _database_name(project_name: str) -> str:
    """Return a name usable as an unquoted PostgreSQL identifier."""
    return project_name.replace("-", "_").replace(".", "_")


@click.command()
@click.argument("project_name")
@click.option(
    "--template",
    type=click.Choice(["basic", "blog", "ecommerce", "fastapi-rag"]),
    default="basic",
    help="Project template to use",
)
@click.option(
    "--database-url",
    default=None,
    help="PostgreSQL database URL (defaults to the bundled docker compose service)",
)
@click.option(
    "--no-git",
    is_flag=True,
    help="Skip git initialization",
)
def init(project_name: str, template: str, database_url: str | None, no_git: bool) -> None:
    """Initialize a new FraiseQL project.

    Creates a new directory with the given PROJECT_NAME and sets up
    a basic FraiseQL application structure.
    """
    project_path = Path(project_name)

    # Check if directory already exists
    if project_path.exists():
        click.echo(f"Error: Directory '{project_name}' already exists", err=True)
        msg = f"Directory '{project_name}' already exists"
        raise click.ClickException(msg)

    db_name = _database_name(project_name)
    if database_url is None:
        database_url = f"postgresql://{DB_USER}:{DB_PASSWORD}@localhost:{DB_PORT}/{db_name}"

    click.echo(f"🚀 Creating FraiseQL project '{project_name}'...")

    # Create project directory
    project_path.mkdir(parents=True)

    # Create directory structure. The db/ layout matches what `fraiseql migrate
    # init` expects, so the two commands agree about where migrations live.
    directories = [
        "src",
        "src/types",
        "src/mutations",
        "src/queries",
        "tests",
        "db/schema",
        "db/seeds/common",
        "db/seeds/development",
        "db/migrations",
        "db/environments",
    ]

    for directory in directories:
        (project_path / directory).mkdir(parents=True, exist_ok=True)

    # Create .env file
    env_content = f"""# FraiseQL Configuration
FRAISEQL_DATABASE_URL={database_url}
FRAISEQL_AUTO_CAMEL_CASE=true

# Fail fast while developing. Without this a missing database costs 30s per
# query while the connection pool retries.
FRAISEQL_DATABASE_POOL_TIMEOUT=5

# Uncomment to put HTTP basic auth in front of /graphql, as user 'admin'.
# Every request then needs credentials, GraphiQL's included.
# FRAISEQL_DEV_AUTH_PASSWORD=development-only-password

# Production settings (uncomment for production)
# FRAISEQL_ENVIRONMENT=production
# SECRET_KEY=your-secret-key-here
"""
    (project_path / ".env").write_text(env_content)

    # Create docker-compose.yml so a real database is one command away rather
    # than a prerequisite the user has to satisfy before anything works.
    compose_content = f"""services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: {db_name}
      POSTGRES_USER: {DB_USER}
      POSTGRES_PASSWORD: {DB_PASSWORD}
    ports:
      - "{DB_PORT}:5432"
    volumes:
      - {db_name}_data:/var/lib/postgresql/data
      # Applied once, the first time this volume is created.
      - ./db/schema:/docker-entrypoint-initdb.d
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U {DB_USER} -d {db_name}"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  {db_name}_data:
"""
    (project_path / "docker-compose.yml").write_text(compose_content)

    # Schema for the shipped database, loaded automatically by the container.
    schema_content = """-- Loaded by docker-entrypoint-initdb.d the first time the volume
-- is created. To re-run it: docker compose down -v && docker compose up -d

CREATE TABLE IF NOT EXISTS tb_user (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- FraiseQL reads one JSONB column per row, so the object is composed in SQL
-- instead of being assembled from joins in Python.
CREATE OR REPLACE VIEW v_user AS
SELECT
    id,
    jsonb_build_object(
        'id', id,
        'name', name,
        'email', email,
        'created_at', created_at
    ) AS data
FROM tb_user;

INSERT INTO tb_user (name, email) VALUES
    ('Ada Lovelace', 'ada@example.com'),
    ('Alan Turing', 'alan@example.com')
ON CONFLICT (email) DO NOTHING;
"""
    (project_path / "db" / "schema" / "001_users.sql").write_text(schema_content)

    # Create .gitignore
    gitignore_content = """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
.venv/
pip-log.txt
pip-delete-this-directory.txt
.tox/
.coverage
.coverage.*
.cache
.pytest_cache/
htmlcov/
*.cover
.hypothesis/

# Environment
.env
.env.*

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db

# Project
/dist/
/build/
*.egg-info/
"""
    (project_path / ".gitignore").write_text(gitignore_content)

    # Create pyproject.toml
    pyproject_content = f"""[project]
name = "{project_name}"
version = "0.1.0"
description = "A FraiseQL GraphQL API"
requires-python = "{REQUIRES_PYTHON}"
dependencies = [
    # The bare name resolves to FraiseQL v2 on PyPI, a different framework.
    "{FRAISEQL_PIN}",
    "uvicorn>=0.34.3",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.5",
    "pytest-asyncio>=0.21.0",
    "ruff>=0.8.4",
]

[tool.ruff]
line-length = 100
target-version = "{PYTHON_TAG}"

[tool.pyright]
pythonVersion = "{PYTHON_VERSION}"
typeCheckingMode = "strict"
"""
    (project_path / "pyproject.toml").write_text(pyproject_content)

    # Create main app file based on template
    if template == "basic":
        create_basic_template(project_path)
    elif template == "blog":
        create_blog_template(project_path)
    elif template == "ecommerce":
        create_ecommerce_template(project_path)
    elif template == "fastapi-rag":
        create_fastapi_rag_template(project_path)

    # Create README
    readme_content = f"""# {project_name}

A FraiseQL GraphQL API.

## Getting started

1. Create a virtual environment and install the project:

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\\Scripts\\activate
   pip install -e ".[dev]"
   ```

2. Start the development server:

   ```bash
   fraiseql dev
   ```

   Your API is live at <http://localhost:8000/graphql>. Open it and run:

   ```graphql
   {{ users {{ id name email }} }}
   ```

   It answers with an empty list until you finish step 3.

3. Start the bundled PostgreSQL:

   ```bash
   docker compose up -d
   ```

   The container loads `db/schema/*.sql` the first time it starts, which
   creates `v_user` and seeds two rows. Re-run the query above and it
   returns them.

## Configuration

Settings live in `.env` and are read by FraiseQL directly. The one that
matters most is `FRAISEQL_DATABASE_URL`, which already points at the
database `docker compose` starts for you.

## Changing the schema

```bash
fraiseql migrate create add_something   # writes db/migrations/<timestamp>_add_something
fraiseql migrate up                     # applies pending migrations
fraiseql migrate status                 # shows what has been applied
```

`fraiseql migrate` on its own only prints help; the subcommands do the work.

## Project structure

- `src/` — application source code
  - `types/` — FraiseQL type definitions
  - `mutations/` — GraphQL mutations
  - `queries/` — custom query logic
- `db/schema/` — SQL loaded into a fresh database
- `db/migrations/` — incremental schema changes
- `tests/` — test files

## Learn more

- [FraiseQL documentation](https://fraiseql.readthedocs.io)
- [GraphQL](https://graphql.org)
"""
    (project_path / "README.md").write_text(readme_content)

    # Initialize git repository
    if not no_git:
        try:
            subprocess.run(["git", "init", "-q"], check=True, cwd=str(project_path))
            subprocess.run(["git", "add", "."], check=True, cwd=str(project_path))
            subprocess.run(
                ["git", "commit", "-q", "-m", "Initial commit from FraiseQL CLI"],
                check=True,
                cwd=str(project_path),
            )
            click.echo("✅ Initialized git repository")
        except subprocess.CalledProcessError as e:
            click.echo(f"⚠️ Git initialization failed: {e}", err=True)

    click.echo(
        f"""
✨ Project '{project_name}' created successfully!

Next steps:
1. cd {project_name}
2. python -m venv .venv
3. source .venv/bin/activate  # On Windows: .venv\\Scripts\\activate
4. pip install -e ".[dev]"
5. fraiseql dev            # serves http://localhost:8000/graphql right away
6. docker compose up -d    # starts PostgreSQL and loads db/schema/*.sql

Happy coding! 🎉
""",
    )


def create_basic_template(project_path: Path) -> None:
    """Create a basic template with simple User type."""
    # Create main.py
    main_content = '''"""Main application entry point."""

import os
from datetime import datetime

import fraiseql
from dotenv import load_dotenv
from psycopg import OperationalError

load_dotenv()


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    """A user in the system."""

    id: int
    name: str
    email: str
    created_at: datetime


@fraiseql.query
async def users(info) -> list[User]:
    """Every row of the v_user view, oldest first."""
    db = info.context["db"]
    try:
        return await db.find("v_user", "users", info, order_by=[("id", "ASC")])
    except OperationalError:
        # No database yet. `docker compose up -d` starts the one this project
        # ships with; delete this guard once you always have one.
        return []


# @fraiseql.query registers `users` on import, so it needs no queries= here.
app = fraiseql.create_fraiseql_app(
    types=[User],
    database_url=os.getenv("FRAISEQL_DATABASE_URL"),
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
'''
    (project_path / "src" / "main.py").write_text(main_content)

    # Create __init__.py files
    (project_path / "src" / "__init__.py").write_text("")
    (project_path / "src" / "types" / "__init__.py").write_text("")


def create_blog_template(project_path: Path) -> None:
    """Create a blog template with User, Post, and Comment types."""
    # Create types
    user_type = '''"""User type definition."""

import fraiseql
from fraiseql import fraise_field
from fraiseql.types import ID


@fraiseql.type
class User:
    """A blog author."""
    id: ID
    username: str = fraise_field(description="Unique username")
    email: str = fraise_field(description="Email address")
    bio: str | None = fraise_field(description="User biography")
    avatar_url: str | None = fraise_field(description="Profile picture URL")
    created_at: str = fraise_field(description="Account creation date")
    posts: list["Post"] = fraise_field(description="Posts written by this user")
'''

    post_type = '''"""Post type definition."""

import fraiseql
from fraiseql import fraise_field
from fraiseql.types import ID

from .user import User
from .comment import Comment


@fraiseql.type
class Post:
    """A blog post."""
    id: ID
    title: str = fraise_field(description="Post title")
    slug: str = fraise_field(description="URL-friendly slug")
    content: str = fraise_field(description="Post content in Markdown")
    excerpt: str | None = fraise_field(description="Short summary")
    author: User = fraise_field(description="Post author")
    published_at: str | None = fraise_field(description="Publication date")
    updated_at: str = fraise_field(description="Last update date")
    tags: list[str] = fraise_field(description="Post tags")
    comments: list[Comment] = fraise_field(description="Post comments")
    is_published: bool = fraise_field(description="Whether post is published")
'''

    comment_type = '''"""Comment type definition."""

import fraiseql
from fraiseql import fraise_field
from fraiseql.types import ID

from .user import User


@fraiseql.type
class Comment:
    """A comment on a blog post."""
    id: ID
    content: str = fraise_field(description="Comment text")
    author: User = fraise_field(description="Comment author")
    created_at: str = fraise_field(description="When comment was posted")
    updated_at: str = fraise_field(description="Last edit time")
    is_approved: bool = fraise_field(description="Whether comment is approved")
'''

    # Write type files
    (project_path / "src" / "types" / "user.py").write_text(user_type)
    (project_path / "src" / "types" / "post.py").write_text(post_type)
    (project_path / "src" / "types" / "comment.py").write_text(comment_type)

    # Create main.py
    main_content = '''"""Blog API main application."""

import os

import fraiseql
from dotenv import load_dotenv

from src.types.comment import Comment
from src.types.post import Post
from src.types.user import User

load_dotenv()


@fraiseql.query
async def users(info) -> list[User]:
    """List all users.

    Point this at a view once you have one, the way the basic template does:

        db = info.context["db"]
        return await db.find("v_user", "users", info)
    """
    return []


@fraiseql.query
async def posts(info) -> list[Post]:
    """List all posts. See `users` for how to back this with a view."""
    return []


@fraiseql.query
async def comments(info) -> list[Comment]:
    """List all comments. See `users` for how to back this with a view."""
    return []


# @fraiseql.query registers each resolver on import, so no queries= here.
app = fraiseql.create_fraiseql_app(
    types=[User, Post, Comment],
    database_url=os.getenv("FRAISEQL_DATABASE_URL"),
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
'''
    (project_path / "src" / "main.py").write_text(main_content)

    # Create __init__.py files
    (project_path / "src" / "__init__.py").write_text("")
    (project_path / "src" / "types" / "__init__.py").write_text(
        """from .user import User
from .post import Post
from .comment import Comment

__all__ = ["User", "Post", "Comment"]
""",
    )


def create_ecommerce_template(project_path: Path) -> None:
    """Create an e-commerce template."""
    # This would create Product, Order, Customer types
    # For brevity, using basic template for now
    create_basic_template(project_path)
    click.echo("Note: E-commerce template uses basic structure for now")


def create_fastapi_rag_template(project_path: Path) -> None:
    """Create a FastAPI + LangChain RAG template."""
    template_path = Path(__file__).parent.parent.parent.parent.parent / "templates" / "fastapi-rag"

    # Copy all template files to project directory
    for item in template_path.iterdir():
        if item.is_file():
            shutil.copy2(item, project_path / item.name)
        elif item.is_dir():
            shutil.copytree(item, project_path / item.name, dirs_exist_ok=True)

    # Remove the default .env and replace with .env.example
    if (project_path / ".env").exists():
        (project_path / ".env").unlink()
    shutil.move(project_path / ".env.example", project_path / ".env")

    click.echo("✅ Created FastAPI RAG template with LangChain integration")

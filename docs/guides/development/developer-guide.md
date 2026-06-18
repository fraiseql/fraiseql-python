<!-- Skip to main content -->
---

title: FraiseQL Developer Guide
description: Setup, development workflow, testing, and code standards for working on FraiseQL.
keywords: ["development", "testing", "workflow", "python", "contributing"]
tags: ["documentation", "reference"]
---

# FraiseQL Developer Guide

Welcome! This guide covers setup, the development workflow, testing, and code
standards for working on FraiseQL — a runtime GraphQL framework for PostgreSQL,
written in Python with an optional Rust acceleration extension (`fraiseql_rs`).

For contribution mechanics (forking, PR process, commit format), see the
[Contributing Guide](../../../CONTRIBUTING.md). This document focuses on
day-to-day development.

## Table of Contents

1. [Development Setup](#development-setup)
2. [Project Structure](#project-structure)
3. [Development Workflow](#development-workflow)
4. [Testing Strategy](#testing-strategy)
5. [Code Standards](#code-standards)
6. [Debugging & Troubleshooting](#debugging--troubleshooting)

## Development Setup

### Prerequisites

- **Python 3.13** (the project targets `>=3.13,<3.14`)
- **uv** — package/environment manager ([install](https://docs.astral.sh/uv/))
- **Rust toolchain** — to build the optional `fraiseql_rs` extension ([rustup](https://rustup.rs/))
- **PostgreSQL 14+** — required for integration tests (the Makefile runs it via Docker)

### Initial Setup

```bash
# Clone the repository
git clone git@github.com:fraiseql/fraiseql-python.git
cd fraiseql-python

# Create the virtualenv (runtime + dev dependencies) and build the Rust extension
uv sync

# Install pre-commit hooks
uv run pre-commit install
```

The LangChain/LlamaIndex integrations are opt-in extras and are not installed by
default. To work on them: `uv sync --extra langchain --extra llamaindex`.

### Database Setup

Integration tests use a Docker-managed PostgreSQL:

```bash
make db-up        # start the test database(s)
make db-status    # check health
make db-down      # stop
make db-reset     # remove volumes and recreate
```

## Project Structure

```text
fraiseql_v1/
├── src/fraiseql/             # Main Python package
│   ├── decorators/           # @fraise_type, @query, @mutation
│   ├── gql/                  # GraphQL schema building
│   ├── mutations/            # Mutation execution
│   ├── sql/                  # SQL generation
│   ├── types/                # Type system and scalars
│   ├── fastapi/              # FastAPI integration
│   ├── integrations/         # Optional LangChain / LlamaIndex integrations
│   └── db.py                 # Database abstraction
│
├── tests/
│   ├── unit/                 # Unit tests (no database)
│   ├── integration/          # Integration tests (require PostgreSQL)
│   ├── chaos/                # Chaos-engineering scenarios
│   └── e2e/                  # End-to-end tests
│
├── fraiseql_rs/              # Optional Rust extension (PyO3)
├── Makefile                  # Development commands (see `make help`)
├── pyproject.toml            # Package config, dependencies, tool settings
└── uv.lock                   # Locked dependencies
```

Run `make help` for the full list of convenience commands.

## Development Workflow

### Setting Up a Feature Branch

`dev` is the default integration branch; `main` tracks production. Branch off `dev`:

```bash
git checkout dev
git pull origin dev
git checkout -b feature/your-feature-name

git status   # should be "nothing to commit, working tree clean"
```

### Development Cycle

```bash
# 1. Make changes
$EDITOR src/fraiseql/...

# 2. Format and lint
make format          # uv run ruff format src/
make lint            # uv run ruff check src/

# 3. Type-check
uv run ty check

# 4. Run tests
make test-unit                       # fast, no database
make test-integration                # requires PostgreSQL (make db-up first)

# 5. Commit, push, open a PR targeting dev
git commit -am "feat(scope): describe the change"
git push -u origin feature/your-feature-name
```

`make check` runs format + lint + test in one step.

### Working on the Rust extension

After changing `fraiseql_rs/`, rebuild it into your environment and run the
strict Clippy gate:

```bash
uv run maturin develop                                  # rebuild the extension
cargo clippy --manifest-path fraiseql_rs/Cargo.toml --all-features -- -D warnings
cargo fmt --manifest-path fraiseql_rs/Cargo.toml
```

### Running Specific Tests

```bash
# A single test, verbose, stop on first failure
uv run pytest tests/unit/test_file.py::test_name -xvs

# A directory
uv run pytest tests/unit/ -q

# By keyword
uv run pytest -k "schema and not slow"

# With logging
uv run pytest tests/ -o log_cli=true -o log_cli_level=DEBUG
```

## Testing Strategy

FraiseQL uses **pytest** with `pytest-asyncio`. Tests are organized by scope:

```text
tests/unit/          Fast, isolated, no database
tests/integration/   Medium speed, real PostgreSQL
tests/chaos/         Failure-injection scenarios
tests/e2e/           Full end-to-end flows
```

### Writing Tests

```python
import pytest


@pytest.mark.asyncio
async def test_feature_happy_path(test_db_connection):
    result = await schema.execute("{ users { id name } }")
    assert not result.errors
    assert result.data["users"][0]["name"] == "Alice"


@pytest.mark.asyncio
async def test_feature_error_case():
    result = await schema.execute("{ users { nonexistent } }")
    assert result.errors
```

### Coverage

```bash
uv run pytest --cov=fraiseql --cov-report=html
# open htmlcov/index.html
```

## Code Standards

### Style and Typing

- **Python 3.13** with modern union syntax: `X | None`, not `Optional[X]`.
- **Built-in generics**: `list` / `dict` / `set`, not `typing.List` / `Dict` / `Set`.
- Formatting and linting via **Ruff** (`make format`, `make lint`); config in `pyproject.toml`.
- Type checking via **ty** (not mypy): `uv run ty check`.

```python
# ✅ Modern style
def get_user(user_id: int) -> User | None:
    ...


# ❌ Old style
from typing import Optional


def get_user(user_id: int) -> Optional["User"]:
    ...
```

### Documentation

Every public function and class should have a docstring:

```python
def get_user(user_id: int) -> User | None:
    """Get a single user by ID.

    Args:
        user_id: The unique user identifier.

    Returns:
        The User, or None if not found.

    Raises:
        DatabaseError: If the database connection fails.
    """
    ...
```

### Error Handling

Use the `FraiseQLError` hierarchy and return structured results rather than
raising bare exceptions across boundaries:

```python
from fraiseql.types.errors import Error
```

Always use parameterized SQL — never interpolate user input into query strings.

## Debugging & Troubleshooting

### Logging

FraiseQL uses [structlog](https://www.structlog.org/). Raise verbosity in tests
with pytest's logging flags:

```bash
uv run pytest tests/unit/test_file.py -o log_cli=true -o log_cli_level=DEBUG
```

For the Rust extension, set `RUST_LOG=debug` in the environment.

### Quick Debugging

```python
import pytest

# Drop into the debugger on failure
# uv run pytest tests/unit/test_file.py --pdb

# Print without capture
# uv run pytest -s tests/unit/test_file.py
```

### Common Issues

**`ImportError` / stale Rust extension** — rebuild it: `uv run maturin develop`,
then `uv sync`.

**`database connection refused` in integration tests** — the test database isn't
running. Start it with `make db-up`; it may take 10–20 seconds to become healthy
(`make db-status`). Confirm `DATABASE_URL` if you point at an external instance.

**Integration tests for LangChain/LlamaIndex are skipped** — their extras aren't
installed. Run `uv sync --extra langchain --extra llamaindex` first.

**Pre-commit hook fails** — reproduce the failing check directly (`make lint`,
`make format`, `uv run ty check`) and fix, rather than bypassing with
`--no-verify`.

## See Also

- [Contributing Guide](../../../CONTRIBUTING.md) — fork/PR workflow and standards
- [Architecture Principles](../../../.claude/ARCHITECTURE_PRINCIPLES.md) — design decisions

Happy coding! 🚀

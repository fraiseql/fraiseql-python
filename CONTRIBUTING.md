# Contributing to FraiseQL

Thank you for your interest in contributing to FraiseQL! This document provides guidelines and instructions for contributing.

FraiseQL (this repository, `fraiseql-python`) is a **runtime GraphQL framework for PostgreSQL**, written in Python with an optional Rust acceleration extension (`fraiseql_rs`).

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Development Workflow](#development-workflow)
- [Code Style](#code-style)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Release Process](#release-process)
- [Architecture Guidelines](#architecture-guidelines)

---

## Code of Conduct

Be respectful, professional, and collaborative. We're building something great together!

---

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork**:

   ```bash
   git clone git@github.com:YOUR_USERNAME/fraiseql-python.git
   cd fraiseql-python
   ```

3. **Add the upstream remote**:

   ```bash
   git remote add upstream git@github.com:fraiseql/fraiseql-python.git
   ```

---

## Development Setup

### Prerequisites

- **Python** 3.13 (the project targets `>=3.13,<3.14`)
- **uv** (package/environment manager — install via the [uv docs](https://docs.astral.sh/uv/))
- **Rust** toolchain (needed to build the optional `fraiseql_rs` extension; install via [rustup](https://rustup.rs/))
- **PostgreSQL** 14+ (for integration tests)
- **Make** (optional, for convenience commands)

### Install Dependencies

```bash
# Create the virtualenv with runtime + dev dependencies and build the Rust extension
uv sync

# Install the pre-commit hooks
uv run pre-commit install
```

`uv sync` installs the runtime dependencies plus the `dev` dependency group
(linters and test tooling). The optional integration libraries (LangChain,
LlamaIndex) are **not** installed by default — see [Optional extras](#optional-extras).

### Optional extras

The LangChain and LlamaIndex integrations live behind opt-in extras so the
default install stays lean:

| Extra | Pulls in |
|-------|----------|
| `langchain` | langchain, langchain-community, langchain-core, langchain-text-splitters, langsmith |
| `llamaindex` | llama-index, llama-index-core, banks, pillow, pypdf |
| `llm` | both of the above (convenience aggregate) |

Install with pip:

```bash
pip install "fraiseql[llm]"          # both integrations
pip install "fraiseql[langchain]"    # LangChain only
pip install "fraiseql[llamaindex]"   # LlamaIndex only
```

…or add them to your local dev environment:

```bash
uv sync --extra langchain --extra llamaindex
```

### Run Tests

```bash
# Unit tests (fast, no database)
make test-unit            # or: uv run pytest tests/unit/ -q

# Integration tests (requires PostgreSQL)
make test-integration

# Everything
make test

# A single test, verbose
uv run pytest tests/unit/test_file.py::test_name -xvs
```

The LangChain/LlamaIndex integration tests **skip automatically** unless their
extras are installed. To exercise them, sync the extras first:

```bash
uv sync --extra langchain --extra llamaindex
uv run pytest \
  tests/integration/test_langchain_vectorstore_integration.py \
  tests/integration/test_llamaindex_vectorstore_integration.py
```

---

## Development Workflow

### 1. Create a Feature Branch

`dev` is the default integration branch; `main` tracks production. Branch off `dev`:

```bash
git checkout dev
git pull upstream dev
git checkout -b feature/my-feature
```

### 2. Make Changes

- Write code following our [Code Style](#code-style)
- Add tests for new functionality (write the failing test first)
- Update documentation if needed

### 3. Run Checks Locally

```bash
make format        # format with ruff  (uv run ruff format src/)
make lint          # lint with ruff    (uv run ruff check src/)
uv run ty check    # type-check with ty
make test          # unit + integration tests
make check         # format + lint + test in one step
```

### 4. Commit Changes

```bash
git add .
git commit -m "feat(scope): description

- Detailed change 1
- Detailed change 2"
```

**Commit Message Format:**

```text
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Code style changes (formatting)
- `refactor`: Code refactoring
- `perf`: Performance improvement
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

### 5. Push and Create PR

```bash
git push -u origin feature/my-feature
```

Then open a Pull Request on GitHub targeting `dev`.

---

## Code Style

FraiseQL uses the [Ruff](https://docs.astral.sh/ruff/) toolchain and modern Python conventions (config in `pyproject.toml`).

**Key points:**

- **Python 3.13** with modern union syntax: `X | None`, not `Optional[X]`
- **Built-in generics**: `list` / `dict` / `set`, not `typing.List` / `Dict` / `Set`
- **Formatting & linting**: `ruff format` / `ruff check`
- **Type checking**: `ty` (not mypy) — `uv run ty check`
- **Docstrings**: required for public functions and classes

**Example:**

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

### Rust extension

Changes to the optional `fraiseql_rs` extension must pass the strict Clippy gate:

```bash
cargo clippy --manifest-path fraiseql_rs/Cargo.toml --all-features -- -D warnings
cargo fmt --manifest-path fraiseql_rs/Cargo.toml
```

Rebuild the extension into your environment with `uv run maturin develop`.

---

## Testing

FraiseQL uses **pytest** with `pytest-asyncio`.

### Test Levels

1. **Unit tests** (`tests/unit/`) — fast, no database:

   ```python
   import pytest


   @pytest.mark.asyncio
   async def test_query_execution():
       result = await schema.execute("{ users { id name } }")
       assert result.data["users"][0]["name"] == "Alice"
   ```

2. **Integration tests** (`tests/integration/`) — require PostgreSQL:

   ```python
   @pytest.mark.asyncio
   async def test_user_creation(test_db_connection):
       result = await schema.execute(
           'mutation { createUser(name: "Bob") { id } }'
       )
       assert result.data["createUser"]["id"]
   ```

Other suites live in `tests/chaos/` (chaos engineering) and `tests/e2e/`
(end-to-end).

### Test Database

Integration tests use a Docker-managed PostgreSQL:

```bash
make db-up              # start the test database(s)
make test-integration   # run integration tests
make db-down            # stop the database(s)
make db-reset           # reset (remove volumes)
```

### Coverage

```bash
uv run pytest --cov=fraiseql --cov-report=html
# open htmlcov/index.html
```

---

## Pull Request Process

### PR Checklist

Before submitting a PR, ensure:

- [ ] All tests pass (`make test`)
- [ ] Code is formatted and lint-clean (`make format`, `make lint`)
- [ ] Type checks pass (`uv run ty check`)
- [ ] Tests are added for new functionality
- [ ] Documentation is updated (if needed)
- [ ] Commit messages follow the conventional format
- [ ] PR targets `dev` and explains the change

### PR Review Process

1. **Automated checks** run via GitHub Actions — the `CI Success`,
   `Security Gate ✅`, and `Compliance Validation` gates must pass
2. **Code review** by maintainers
3. **Address feedback** if requested
4. **Merge** once approved and CI passes

### After Merge

Your change merges into `dev` and ships to `main` on the next `dev → main`
sync, included in the next release.

---

## Release Process

Releases are managed by maintainers:

1. Version bump in `pyproject.toml` (the runtime `__version__` is read from package metadata)
2. Update `CHANGELOG.md`
3. `dev` is synced to `main`
4. `make release` builds and publishes the wheel + sdist to PyPI

---

## Architecture Guidelines

FraiseQL v1 is a **runtime GraphQL framework**: Python decorators define types,
queries, and mutations, and FraiseQL generates the GraphQL schema and executes
queries against PostgreSQL at runtime.

- **Decorator API**: `@fraise_type`, `@query`, `@mutation` define the schema.
- **SQL generation**: queries compile to parameterized SQL — never string interpolation.
- **Optional Rust acceleration**: `fraiseql_rs` (PyO3) speeds up hot paths; the framework runs in pure Python without it.
- **FastAPI integration**: served over ASGI with configurable middleware.

See [`.claude/CLAUDE.md`](.claude/CLAUDE.md) and
[`.claude/ARCHITECTURE_PRINCIPLES.md`](.claude/ARCHITECTURE_PRINCIPLES.md) for
detailed architecture documentation.

---

## Getting Help

- **Questions**: Open a GitHub Discussion
- **Bugs**: File a GitHub Issue
- **Security**: see [SECURITY.md](SECURITY.md) — please do not report vulnerabilities via public issues

---

## License

By contributing, you agree that your contributions will be licensed under the
project's [MIT License](LICENSE).

---

**Thank you for contributing to FraiseQL!** 🚀

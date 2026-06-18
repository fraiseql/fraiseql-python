# Contributing to FraiseQL

Thank you for your interest in contributing to FraiseQL v2! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Development Workflow](#development-workflow)
- [Code Style](#code-style)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Release Process](#release-process)

---

## Code of Conduct

Be respectful, professional, and collaborative. We're building something great together!

---

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork**:

   ```bash
   git clone git@github.com:YOUR_USERNAME/fraiseql.git
   cd fraiseql
   ```

3. **Add upstream remote**:

   ```bash
   git remote add upstream git@github.com:fraiseql/fraiseql.git
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

```bash
git checkout v2-development
git pull upstream v2-development
git checkout -b feature/my-feature
```

### 2. Make Changes

- Write code following our [Code Style](#code-style)
- Add tests for new functionality
- Update documentation if needed

### 3. Run Checks Locally

```bash
# Format code
make fmt

# Run linter
make clippy

# Run tests
make test

# Or run all checks
make check
```

### 4. Commit Changes

```bash
git add .
git commit -m "feat(scope): description

- Detailed change 1
- Detailed change 2"
```

**Commit Message Format:**

```
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
git push origin feature/my-feature
```

Then create a Pull Request on GitHub targeting `v2-development`.

---

## Code Style

### Rust Style

We follow the official [Rust Style Guide](https://doc.rust-lang.org/nightly/style-guide/).

**Key points:**

- **Line width**: 100 characters
- **Indentation**: 4 spaces
- **Imports**: Organized with `cargo fmt`
- **Documentation**: Required for public items
- **Error handling**: Use `Result` and `?` operator

**Example:**

```rust
/// Calculate the sum of two numbers.
///
/// # Arguments
///
/// * `a` - First number
/// * `b` - Second number
///
/// # Returns
///
/// Sum of a and b
///
/// # Example
///
/// ```
/// let result = add(2, 3);
/// assert_eq!(result, 5);
/// ```
pub fn add(a: i32, b: i32) -> i32 {
    a + b
}
```

### Linting

All code must pass Clippy with no warnings:

```bash
cargo clippy --all-targets --all-features -- -D warnings
```

---

## Testing

### Test Levels

1. **Unit Tests**: Test individual functions/modules

   ```rust
   #[cfg(test)]
   mod tests {
       use super::*;

       #[test]
       fn test_addition() {
           assert_eq!(add(2, 2), 4);
       }
   }
   ```

2. **Integration Tests**: Test module interactions

   ```rust
   // tests/integration/test_schema.rs
   #[test]
   fn test_schema_loading() {
       let schema = CompiledSchema::load("test.json").unwrap();
       assert!(schema.is_valid());
   }
   ```

3. **End-to-End Tests**: Test complete flows

   ```rust
   // tests/e2e/test_query_execution.rs
   #[tokio::test]
   async fn test_query_execution() {
       let executor = setup_executor().await;
       let result = executor.execute("query { users { id } }").await.unwrap();
       assert!(!result.has_errors());
   }
   ```

### Test Database

Integration tests require PostgreSQL:

```bash
# Create test database (local setup)
make db-setup-local

# Or use Docker containers
make db-up

# Run integration tests
make test-integration

# Clean up (local)
make db-teardown-local

# Or stop Docker containers
make db-down
```

### Coverage

We aim for **85%+ test coverage**:

```bash
# Generate coverage report
make coverage

# View report at target/llvm-cov/html/index.html
```

---

## Pull Request Process

### PR Checklist

Before submitting a PR, ensure:

- [ ] Code compiles without warnings
- [ ] All tests pass (`make test`)
- [ ] Code is formatted (`make fmt`)
- [ ] Clippy passes (`make clippy`)
- [ ] Documentation is updated (if needed)
- [ ] Tests are added for new functionality
- [ ] Commit messages follow conventional format
- [ ] PR description explains the change

### PR Review Process

1. **Automated checks** run via GitHub Actions
2. **Code review** by maintainers
3. **Address feedback** if requested
4. **Merge** once approved and CI passes

### After Merge

The PR will be merged into `v2-development`. Your contribution will be included in the next release!

---

## Release Process

Releases are managed by maintainers:

1. Version bump in `Cargo.toml`
2. Update `CHANGELOG.md`
3. Create git tag (`v2.x.x`)
4. CI builds and publishes to crates.io and PyPI

---

## Architecture Guidelines

FraiseQL v2 is a **compiled GraphQL execution engine**. Key principles:

### 1. Separation of Concerns

- **Compilation Layer**: Schema definition → SQL compilation (build-time via fraiseql-cli)
- **Runtime Layer**: Query execution → Result streaming (runtime via fraiseql-server)
- **Database Layer**: Data storage and retrieval (multi-database support)

See `.claude/ARCHITECTURE_PRINCIPLES.md` for detailed architecture documentation.

### 2. Layered Optionality

- **Core**: Minimal build includes GraphQL execution engine only
- **Extensions**: Optional features via Cargo features (Arrow, Observers, Wire)
- **Configuration**: All behavior controlled via fraiseql.toml or environment variables

### 3. World-Class Engineering

- **No `unsafe` code** (forbidden at compile time via Cargo.toml lints)
- **Comprehensive error handling** with Result types and context
- **Extensive documentation** for all public APIs
- **Thorough testing** (2,400+ tests: unit, integration, E2E, chaos)
- **Performance-conscious** design with zero-copy patterns and compile-time optimization

---

## Getting Help

- **Questions**: Open a GitHub Discussion
- **Bugs**: File a GitHub Issue
- **Security**: Email <security@fraiseql.dev>

---

## License

By contributing, you agree that your contributions will be licensed under the same license as the project (MIT OR Apache-2.0).

---

**Thank you for contributing to FraiseQL v2!** 🚀

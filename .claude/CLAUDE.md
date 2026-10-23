# FraiseQL v1 Development Guide

## Vision

**FraiseQL v1 is a Python GraphQL framework** that transforms database schema into GraphQL APIs at runtime. Using decorators, developers define types and queries, while FraiseQL automatically generates resolvers and executes queries against PostgreSQL, MySQL, SQLite, or SQL Server.

## Core Architecture Principle

```text
Developer Code              FraiseQL Runtime          Database
(Python)                   (Python + Rust)           (PostgreSQL/MySQL/etc)
    ↓                            ↓                          ↓
@fraiseql.type        →  GraphQL Schema         →   SQL Query Execution
@fraiseql.query       →  Query Resolution       →   Result Set Handling
FastAPI Integration   →  HTTP Server/GraphQL   →   Connection Pooling
```

**Key Point**: FraiseQL is a **runtime GraphQL framework**—not a compiler. Python code with decorators is executed at runtime to generate and serve GraphQL APIs.

**Architecture**: Layered Python framework with optional Rust extension (`fraiseql_rs`) for performance-critical operations like mutations and field selection optimization.

---

## Project Standards

### Technology Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| **Package** | Python 3.13+ | Developer ergonomics, rapid iteration |
| **Optional Extension** | Rust (PyO3) | Performance for mutations, complex queries |
| **Database Support** | PostgreSQL (primary), MySQL, SQLite, SQL Server | Multi-database support |
| **Testing** | pytest + pytest-asyncio | Comprehensive async test framework |
| **Linting** | Ruff (astral suite) | Fast, strict code quality |

**NOT SUPPORTED**: Oracle (no driver support)

### Code Quality

```toml
# Python linting with Ruff
[tool.ruff.lint]
select = [
    "E", "W", "F",     # Errors, warnings, Pyflakes
    "I",               # isort (import sorting)
    "B",               # flake8-bugbear
    "UP",              # pyupgrade
    "SIM", "PERF",     # Code simplification and performance
    "RUF"              # Ruff-specific rules
]
ignore = []            # No exemptions for v1.9.18+

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["PLR2004"]  # Magic values OK in tests
```

### Type Annotations

Use modern Python 3.10+ union syntax:

```python
def get_user(user_id: int) -> User | None:     # ✅ Good
def get_user(user_id: int) -> Optional[User]:   # ❌ Old style
```

---

## Development Workflow

### Implementation Status

FraiseQL v1 is production-ready with full feature support:

- **Core**: GraphQL schema generation and query execution
- **Decorators**: `@fraiseql.type`, `@fraiseql.query`, `@fraiseql.mutation`
- **Database**: Introspection, multi-database support, connection pooling
- **Extensions**: Optional Rust acceleration via `fraiseql_rs`
- **Integration**: FastAPI, ASGI, customizable middleware

### Workflow Pattern

```bash
# 1. Create feature branch
git checkout -b feature/description

# 2. Implement changes
# Follow test-driven development (RED → GREEN → REFACTOR → CLEANUP)

# 3. Verify code quality
uv run ruff check src/
uv run ruff format src/
uv run pytest tests/

# 4. Commit with descriptive message
git commit -m "feat(scope): Clear description of work

## Changes

- Change 1
- Change 2

## Verification
✅ ruff checks pass
✅ pytest passes
✅ No type errors
"

# 5. Push and create PR
git push -u origin feature/description
```

### Fast Development Cycle

```bash
# Format and check
uv run ruff check --fix src/
uv run ruff format src/

# Run tests
uv run pytest tests/ -xvs
uv run pytest tests/unit/  -q  # Unit tests only (fast)

# Type checking
uv run pytest --co       # Collect tests
uv run pytest tests/ -x  # Stop on first failure
```

---

## Architecture Guidelines

### 1. Decorator-Based API Definition

**Type Definition:**

```python
from fraiseql import fraise_type

@fraise_type(sql_source="v_user")  # a view with an id column and a data JSONB column
class User:
    """User in the system"""
    id: int
    name: str
    email: str
    created_at: str
```

**Query Definition:**

```python
import fraiseql

@fraiseql.query
async def users(info, limit: int = 10, offset: int = 0) -> list[User]:
    """Get all users with pagination"""
    return await info.context["db"].find("v_user", "users", info, limit=limit, offset=offset)
```

**Mutation Definition:**

```python
import fraiseql

@fraiseql.input
class CreateUserInput:
    name: str
    email: str

@fraiseql.success
class CreateUserSuccess:
    user: User

@fraiseql.error
class CreateUserError:
    """status, message, errors and code are added by @fraiseql.error"""

@fraiseql.mutation  # calls the SQL function create_user(input jsonb) -> mutation_response
class CreateUser:
    """Create a new user"""
    input: CreateUserInput
    success: CreateUserSuccess
    error: CreateUserError
```

### 2. Runtime Schema Generation

FraiseQL generates GraphQL schema at startup:

1. **Introspection**: Read database structure (tables, columns, constraints)
2. **Type Mapping**: Map Python types to GraphQL types
3. **Resolver Generation**: Create resolvers for each field automatically
4. **Query Building**: Generate efficient SQL for GraphQL queries
5. **Execution**: Execute queries with connection pooling and caching

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://user:pass@localhost/dbname",
    types=[User],
    queries=[users],
    mutations=[CreateUser],
)

# Or the schema alone:
from fraiseql import build_fraiseql_schema

schema = build_fraiseql_schema(query_types=[users], mutation_resolvers=[CreateUser])
```

### 3. Database Abstraction

FraiseQL abstracts database differences via **SQL generation**:

- **PostgreSQL**: Full feature support (JSONB, custom types, array ops)
- **MySQL**: Core features (views, joins, filtering)
- **SQLite**: Local development and testing
- **SQL Server**: Enterprise support (transactions, CTEs)

**Pattern**: SQL generators per database, unified interface for queries.

### 4. Error Handling

Use `FraiseQLError` hierarchy for all errors:

A class mutation's SQL function returns a `mutation_response`; its status picks the
`success` or the `error` type (`@fraiseql.error` adds `status`, `message`, `errors` and
`code`), so a failure the function reports is data in the response, not a GraphQL error.


### 5. Query Optimization

**Performance Features:**

1. **Automatic Caching**: Query result caching with cache invalidation
2. **Batch Loading**: N+1 prevention via `@dataloader_field`
3. **Field Selection**: Select only requested fields from DB
4. **Connection Pooling**: Reuse DB connections
5. **Rust Acceleration**: Optional PyO3 extension for mutations

```python
import fraiseql
from fraiseql.optimization.dataloader import DataLoader

class UserLoader(DataLoader[int, dict]):
    def __init__(self, db) -> None:
        super().__init__()
        self.db = db

    async def batch_load(self, user_ids: list[int]) -> list[dict | None]:
        ...  # one query for every id, results in the order of user_ids

@fraiseql.type
class Post:
    id: int
    author_id: int

    @fraiseql.dataloader_field(UserLoader, key_field="author_id")  # Prevents N+1 queries
    async def author(self, info) -> User | None:
        """Loaded in batch for every post in the response"""
```

### 6. Testing Strategy

**Unit Tests** (in `tests/unit/`):

```python
from graphql import graphql

from fraiseql import build_fraiseql_schema

async def test_query_execution():
    """Test GraphQL query without database"""
    schema = build_fraiseql_schema(query_types=[users])
    result = await graphql(schema, "{ __type(name: \"User\") { name } }")
    assert result.data["__type"]["name"] == "User"
```

**Integration Tests** (in `tests/integration/`):

```python
from fastapi.testclient import TestClient

def test_user_creation_full_flow(app):
    """Test end-to-end mutation with real database (through HTTP)"""
    with TestClient(app) as client:  # runs the app's lifespan, which opens the pool
        body = client.post("/graphql", json={"query": """
            mutation { createUser(input: {name: "Bob", email: "bob@example.com"}) {
              ... on CreateUserSuccess { user { id } }
            } }"""}).json()
    assert body["data"]["createUser"]["user"]["id"]
```

**Fixtures** (in `tests/fixtures/`):

- Database setup/teardown
- Mock connections
- Sample data loading
- Chaos engineering scenarios

### 7. Security Features

**Built-in Security:**

1. **Rate Limiting** - Protect auth endpoints from brute force
2. **Field Authorization** - `@requires_permission` on fields
3. **Input Validation** - Type coercion and constraint checking
4. **Error Sanitization** - Hide internal error details
5. **SQL Injection Prevention** - Parameterized queries always
6. **CORS Support** - Configurable CORS headers
7. **JWT Integration** - Auth0, custom JWT validation
8. **Audit Logging** - Track sensitive operations

All configurable via `FraiseQLConfig` or environment variables.

---

## Key Files & Directories

```text
fraiseql_v1/
├── .claude/
│   ├── CLAUDE.md              # This file (development guide)
│   ├── ARCHITECTURE_PRINCIPLES.md  # Detailed architecture
│   └── README.md              # Overview
│
├── src/fraiseql/              # Main Python package
│   ├── decorators/            # @type, @query, @mutation
│   ├── gql/                   # GraphQL schema building
│   ├── mutations/             # Mutation execution
│   ├── sql/                   # SQL generation
│   ├── db.py                  # Database abstraction
│   ├── types/                 # Type system and scalars
│   └── fastapi/               # FastAPI integration
│
├── tests/                     # Test suite
│   ├── unit/                  # Unit tests (no DB)
│   ├── integration/           # Integration tests (with DB)
│   ├── fixtures/              # Test fixtures and conftest
│   ├── chaos/                 # Chaos engineering tests
│   └── regression/            # Bug regression tests
│
├── fraiseql_rs/               # Optional Rust extension
│   ├── src/                   # PyO3 bindings
│   └── Cargo.toml             # Rust package config
│
├── examples/                  # Example applications
│   ├── basic/                 # Simple blog app
│   ├── fastapi/               # FastAPI integration example
│   └── federation/            # Multi-database example
│
├── Makefile                   # Development commands
├── pyproject.toml             # Python package config
├── uv.lock                    # Locked dependencies
└── Cargo.toml                 # Rust workspace config
```

---

## Common Tasks

### Add a New GraphQL Type

1. Create Python dataclass with `@fraise_type` decorator
2. Add fields with type hints
3. FraiseQL automatically maps to database columns
4. Use `@query` or `@mutation` to expose operations

### Add a New Query

1. Define an `async def` resolver with `@fraiseql.query`, taking `info`
2. Read the view with `info.context["db"].find(...)` / `.find_one(...)`
3. Add parameters and type hints
4. FraiseQL builds the GraphQL field; a list query also gets `where`, `orderBy`, `limit`, `offset`

### Add Database Support

1. Implement SQL generation in `src/fraiseql/sql/`
2. Add connection handler in `src/fraiseql/db.py`
3. Add tests for new dialect
4. Document in guides

### Fix a Bug

1. Write failing test first (TDD: RED phase)
2. Fix the bug (GREEN phase)
3. Refactor if needed (REFACTOR phase)
4. Run full test suite, fix linting (CLEANUP phase)
5. Commit with `fix(scope):` prefix

---

## Performance Guidelines

### Development Build

```bash
# Fast iteration (no optimization)
uv run pytest tests/unit/ -q
uv sync
```

### Testing Performance

```bash
# Use pytest parallelization
uv run pytest tests/ -n auto

# Run only unit tests (no DB required)
uv run pytest tests/unit/ -q
```

### Release Build

```bash
# Build optimized package
uv run maturin build --release

# Wheels include native Rust extension
dist/fraiseql-1.9.18-*.whl
```

---

## Documentation Standards

### Code Documentation

```python
def get_user(user_id: int) -> User | None:
    """Get a single user by ID.

    Fetches the user from the database using their primary key.
    Returns None if the user doesn't exist.

    Args:
        user_id: The unique user identifier

    Returns:
        The User object, or None if not found

    Raises:
        DatabaseError: If database connection fails
    """
```

### Commit Messages

```text
feat(types): Add enum argument coercion support

## Changes

- Add enum type coercion for GraphQL arguments
- Support Python enum to GraphQL enum conversion
- Add comprehensive tests for enum coercion

## Verification
✅ ruff checks pass (no warnings)
✅ All 2,566 tests pass
✅ No performance regressions
```

**Types**: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`

---

## Troubleshooting

### Import Errors

```bash
# Reinstall package in development mode
uv sync
uv pip install -e .
```

### Test Failures

```bash
# Run single test with output
uv run pytest tests/unit/test_file.py::test_name -xvs

# Run with detailed traceback
uv run pytest tests/ --tb=long

# Run with logging
uv run pytest tests/ -o log_cli=true
```

### Database Connection Issues

```bash
# Check connection string
echo $DATABASE_URL

# Test connection
python -c "import psycopg2; psycopg2.connect(os.getenv('DATABASE_URL'))"

# View connection logs
uv run pytest tests/ -o log_cli_level=DEBUG
```

---

## Release Process

### Pre-Release Checks

```bash
# Verify version consistency
grep '__version__' src/fraiseql/__init__.py
grep '^version' pyproject.toml

# Run full checks
make release-check

# Build distribution
make release-build
```

### Publish to PyPI

```bash
# Automated release (recommended)
make release

# Or step-by-step
make release-build     # Build wheel + sdist
make release-publish   # Upload to PyPI
```

---

## Next Steps

For detailed architecture documentation, see:

- `.claude/ARCHITECTURE_PRINCIPLES.md` - Comprehensive architectural decisions
- `docs/` - Full documentation suite
- `examples/` - Working example applications
- `tests/` - Test patterns and best practices

---

## Quick Reference

```bash
# Formatting and linting
uv run ruff check --fix src/       # Auto-fix issues
uv run ruff format src/            # Format code

# Testing
uv run pytest tests/unit/ -q       # Unit tests (fast)
uv run pytest tests/ -x            # All tests, stop on first failure
uv run pytest --cov=fraiseql       # Coverage report

# Development
uv sync                            # Install dependencies
uv pip install -e .               # Install in editable mode
```

---

**Remember**: FraiseQL v1 is a runtime framework. Schemas are defined with Python decorators and executed dynamically against databases at runtime.

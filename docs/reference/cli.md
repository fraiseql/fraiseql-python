---
title: CLI Reference
description: Complete command-line interface reference for FraiseQL development tools
tags:
  - CLI
  - command-line
  - tools
  - development
  - scaffolding
  - codegen
---

# CLI Reference

Complete command-line interface reference for FraiseQL. The CLI provides project scaffolding, development server, code generation, and SQL utilities.

## Installation

The CLI is installed automatically with FraiseQL:

```bash
pip install "fraiseql<2"
fraiseql --version
```

## Global Options

| Option | Description |
|--------|-------------|
| `--version` | Show FraiseQL version and exit |
| `--help` | Show help message and exit |

## Commands Overview

| Command | Purpose | Use Case |
|---------|---------|----------|
| [`fraiseql init`](#fraiseql-init) | Create new project | Starting a new FraiseQL project |
| [`fraiseql dev`](#fraiseql-dev) | Development server | Local development with hot reload |
| [`fraiseql check`](#fraiseql-check) | Validate project | Pre-deployment validation |
| [`fraiseql generate`](#fraiseql-generate) | Code generation | Schema, migrations, CRUD |
| [`fraiseql sql`](#fraiseql-sql) | SQL utilities | View generation, patterns, validation |

---

## fraiseql init

Initialize a new FraiseQL project with complete directory structure.

### Usage

```bash
fraiseql init PROJECT_NAME [OPTIONS]
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `PROJECT_NAME` | Yes | Name of the project directory to create |

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--template [basic\|blog\|ecommerce]` | `basic` | Project template to use |
| `--database-url TEXT` | the bundled compose service | PostgreSQL connection URL |
| `--no-git` | Flag | Skip git repository initialization |

### Templates

**basic** - Simple User type with minimal setup

- Single `src/main.py` with User type
- Basic project structure
- Ideal for learning or simple APIs

**blog** - Complete blog application structure

- User, Post, Comment types in separate files
- Organized `src/types/` directory
- Demonstrates relationships and imports

**ecommerce** - E-commerce application (work in progress)

- Currently uses basic template
- Future: Product, Order, Customer types

### Generated Structure

```
my-project/
├── src/
│   ├── __init__.py
│   ├── main.py              # Application entry point
│   ├── types/               # FraiseQL type definitions
│   ├── mutations/           # GraphQL mutations
│   └── queries/             # Custom query logic
├── db/
│   ├── schema/              # SQL loaded into a fresh database
│   │   └── 001_users.sql    # tb_user, v_user, and two seed rows
│   ├── seeds/               # Environment-specific seed data
│   ├── migrations/          # Incremental schema changes
│   └── environments/        # Per-environment migration config
├── tests/                   # Test files
├── docker-compose.yml      # PostgreSQL for local development
├── .env                     # Environment variables
├── .gitignore              # Git ignore patterns
├── pyproject.toml          # Project configuration
└── README.md               # Project documentation
```

The `db/` layout is the one `fraiseql migrate init` expects, so the two
commands agree about where migrations live.

### Environment Variables

The `.env` file is created with:

```bash
FRAISEQL_DATABASE_URL=postgresql://fraiseql:fraiseql@localhost:54320/my_project
FRAISEQL_AUTO_CAMEL_CASE=true
FRAISEQL_DATABASE_POOL_TIMEOUT=5
```

The URL points at the PostgreSQL in the generated `docker-compose.yml`, which
publishes port 54320 rather than 5432 so it cannot collide with a PostgreSQL
already installed on the machine.

`FRAISEQL_DEV_AUTH_PASSWORD` is written commented out. Uncommenting it puts
HTTP basic auth in front of `/graphql`, so every request — including
GraphiQL's — then needs credentials.

### Examples

**Basic project:**

```bash
fraiseql init my-api
cd my-api
```

**Blog template with custom database:**

```bash
fraiseql init blog-api \
  --template blog \
  --database-url postgresql://user:pass@localhost/blog_db
```

**Skip git initialization:**

```bash
fraiseql init quick-test --no-git
```

### Next Steps After Init

```bash
cd PROJECT_NAME
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
fraiseql dev              # serves /graphql immediately, with no database
docker compose up -d      # starts PostgreSQL and loads db/schema/*.sql
```

`fraiseql dev` works before the database exists: queries resolve to empty
results until `docker compose up -d` has run, and the server says so once at
startup instead of repeating pool errors.

---

## fraiseql dev

Start the development server with hot-reloading enabled.

### Usage

```bash
fraiseql dev [OPTIONS]
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--host TEXT` | `127.0.0.1` | Host to bind to |
| `--port INTEGER` | `8000` | Port to bind to |
| `--reload/--no-reload` | `--reload` | Enable auto-reload on code changes |
| `--app TEXT` | `src.main:app` | Application import path (module:attribute) |

### Requirements

- Must be run from a FraiseQL project directory (contains `pyproject.toml`)
- Requires `uvicorn` to be installed
- Loads environment variables from `.env` if present

### Environment Loading

Automatically loads `.env` file if it exists:

```bash
📋 Loading environment from .env file
🚀 Starting FraiseQL development server...
   GraphQL API: http://127.0.0.1:8000/graphql
   Interactive GraphiQL: http://127.0.0.1:8000/graphql
   Auto-reload: enabled

   Press CTRL+C to stop
```

### Examples

**Standard development:**

```bash
fraiseql dev
# Server at http://127.0.0.1:8000/graphql
```

**Custom host and port:**

```bash
fraiseql dev --host 0.0.0.0 --port 3000
# Server at http://0.0.0.0:3000/graphql
```

**Disable auto-reload:**

```bash
fraiseql dev --no-reload
# Useful for performance testing
```

**Custom app location:**

```bash
fraiseql dev --app myapp.server:application
```

### Troubleshooting

**"Not in a FraiseQL project directory"**

- Ensure you're in the project root with `pyproject.toml`
- Run `fraiseql init` if starting new project

**"uvicorn not installed"**

```bash
pip install uvicorn
# Or: pip install -e ".[dev]"
```

**Port already in use**

```bash
fraiseql dev --port 8001
```

---

## fraiseql check

Validate project structure and FraiseQL type definitions.

### Usage

```bash
fraiseql check
```

### Validation Steps

1. **Project Structure** - Checks for required directories
   - ✅ `src/` directory
   - ✅ `tests/` directory
   - ✅ `migrations/` directory

2. **Application File** - Validates `src/main.py` exists

3. **Type Import** - Ensures FraiseQL app can be imported

4. **Schema Building** - Validates GraphQL schema generation

### Output

```bash
🔍 Checking FraiseQL project...

📁 Checking project structure...
  ✅ src/
  ✅ tests/
  ✅ migrations/

🐍 Validating FraiseQL types...
  ✅ Found FraiseQL app
  📊 Registered types: 5
  📊 Input types: 3
  ✅ GraphQL schema builds successfully!
  📊 Schema contains 12 custom types

✨ All checks passed!
```

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All checks passed |
| `1` | Validation failed (check output for details) |

### Examples

**Pre-deployment validation:**

```bash
fraiseql check
if [ $? -eq 0 ]; then
  echo "Ready to deploy"
  docker build .
fi
```

**CI/CD integration:**

```yaml
# .github/workflows/test.yml
- name: Validate FraiseQL project
  run: fraiseql check
```

### Common Issues

**"No 'app' found in src/main.py"**

- Ensure you have: `app = fraiseql.create_fraiseql_app(...)`

**"Schema validation failed"**

- Check all type definitions for syntax errors
- Ensure all referenced types are imported

---

## fraiseql generate

Code generation commands for schema, migrations, and CRUD operations.

### Usage

```bash
fraiseql generate [COMMAND] [OPTIONS]
```

### Subcommands

| Command | Purpose |
|---------|---------|
| [`schema`](#generate-schema) | Export GraphQL schema file |
| [`migration`](#generate-migration) | Generate database migration SQL |
| [`crud`](#generate-crud) | Generate CRUD mutation boilerplate |

---

### generate schema

Export GraphQL schema to a file for client-side tooling.

**Usage:**

```bash
fraiseql generate schema [OPTIONS]
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `-o, --output TEXT` | `schema.graphql` | Output file path |

**Examples:**

```bash
# Generate schema.graphql
fraiseql generate schema

# Custom output path
fraiseql generate schema -o graphql/schema.graphql

# Use in client code generation
fraiseql generate schema -o schema.graphql
graphql-codegen --schema schema.graphql
```

**Output Format:**

```graphql
type User {
  id: ID!
  email: String!
  name: String!
  createdAt: String!
}

type Query {
  users: [User!]!
  user(id: ID!): User
}
```

---

### generate migration

Generate database migration SQL for a FraiseQL type.

**Usage:**

```bash
fraiseql generate migration ENTITY_NAME [OPTIONS]
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `ENTITY_NAME` | Yes | Name of the entity (e.g., User, Post) |

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--table TEXT` | `{entity_name}s` | Custom table name |

**Generated Migration Includes:**

1. **Table creation** with JSONB data column
2. **Indexes** on data (GIN), created_at, deleted_at
3. **Updated_at trigger** for automatic timestamp updates
4. **View creation** for FraiseQL queries
5. **Soft delete support** via deleted_at column

**Examples:**

```bash
# Generate migration for User type
fraiseql generate migration User
# Creates: migrations/20241010120000_create_users.sql

# Custom table name
fraiseql generate migration Post --table blog_posts
# Creates: migrations/20241010120000_create_blog_posts.sql
```

**Generated SQL Structure:**

```sql
-- Create table with JSONB
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    data JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_users_data ON users USING gin(data);
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at);
CREATE INDEX IF NOT EXISTS idx_users_deleted_at ON users(deleted_at) WHERE deleted_at IS NULL;

-- Updated_at trigger
CREATE OR REPLACE FUNCTION update_users_updated_at()...

-- View for FraiseQL
CREATE OR REPLACE VIEW v_users AS
SELECT id, data, created_at, updated_at
FROM users
WHERE deleted_at IS NULL;
```

**Apply Migration:**

```bash
psql $DATABASE_URL -f migrations/20241010120000_create_users.sql
```

---

### generate crud

Generate CRUD mutations boilerplate for a type.

**Usage:**

```bash
fraiseql generate crud TYPE_NAME
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `TYPE_NAME` | Yes | Name of the type (e.g., User, Product) |

**Generated Files:**

Creates `src/mutations/{type_name}_mutations.py` with:

- Input types (Create, Update)
- Result types (Success, Error, Result union)
- Mutation functions (create, update, delete)

**Examples:**

```bash
# Generate CRUD for User type
fraiseql generate crud User
# Creates: src/mutations/user_mutations.py

# Generate CRUD for Product type
fraiseql generate crud Product
# Creates: src/mutations/product_mutations.py
```

**Generated Structure:**

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.input
class CreateUserInput:
    name: str

@input
class UpdateUserInput:
    id: ID
    name: str | None

@success
class UserSuccess:
    user: User
    message: str

@error
class UserError:
    message: str
    code: str

@result
class UserResult:
    pass

@fraiseql.mutation
async def create_user(input: CreateUserInput, repository: CQRSRepository) -> UserResult:
    # Call your CQRS repository methods
    result = await repository.create(input)
    return UserResult(user=result)
```

**Next Steps:**

1. Import and register mutations in your app
2. Customize input fields and validation logic
3. Implement repository calls with proper error handling

---

## fraiseql sql

SQL helper commands for view generation, patterns, and validation.

### Usage

```bash
fraiseql sql [COMMAND] [OPTIONS]
```

### Subcommands

| Command | Purpose |
|---------|---------|
| [`generate-view`](#sql-generate-view) | Generate SQL view for a type |
| [`generate-setup`](#sql-generate-setup) | Complete SQL setup (table + view + indexes) |
| [`generate-pattern`](#sql-generate-pattern) | Common SQL patterns (pagination, filtering, etc.) |
| [`validate`](#sql-validate) | Validate SQL for FraiseQL compatibility |
| [`explain`](#sql-explain) | Explain SQL in beginner-friendly terms |

---

### sql generate-view

Generate a SQL view definition from a FraiseQL type.

**Usage:**

```bash
fraiseql sql generate-view TYPE_NAME [OPTIONS]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-m, --module TEXT` | Python module containing the type (e.g., `src.types`) |
| `-t, --table TEXT` | Custom table name (default: inferred from type) |
| `-v, --view TEXT` | Custom view name (default: `v_{table}`) |
| `-e, --exclude TEXT` | Fields to exclude (can be repeated) |
| `--with-comments/--no-comments` | Include explanatory comments (default: yes) |
| `-o, --output FILE` | Output file (default: stdout) |

**Examples:**

```bash
# Generate view for User type
fraiseql sql generate-view User --module src.types

# Exclude sensitive fields
fraiseql sql generate-view User -e password -e secret_token

# Custom table and view names
fraiseql sql generate-view User --table tb_users --view v_user_public

# Save to file
fraiseql sql generate-view User -o migrations/001_user_view.sql
```

---

### sql generate-setup

Generate complete SQL setup including table, indexes, and view.

**Usage:**

```bash
fraiseql sql generate-setup TYPE_NAME [OPTIONS]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-m, --module TEXT` | Python module containing the type |
| `--with-table` | Include table creation SQL |
| `--with-indexes` | Include index creation SQL |
| `--with-data` | Include sample data INSERT statements |
| `-o, --output FILE` | Output file path |

**Examples:**

```bash
# Complete setup with table and indexes
fraiseql sql generate-setup User --with-table --with-indexes

# Include sample data for testing
fraiseql sql generate-setup User --with-table --with-indexes --with-data

# Save complete setup
fraiseql sql generate-setup User --with-table --with-indexes -o db/schema.sql
```

---

### sql generate-pattern

Generate common SQL patterns for queries.

**Usage:**

```bash
fraiseql sql generate-pattern PATTERN_TYPE TABLE_NAME [OPTIONS]
```

**Pattern Types:**

| Pattern | Description | Required Options |
|---------|-------------|------------------|
| `pagination` | LIMIT/OFFSET pagination | `--limit`, `--offset` |
| `filtering` | WHERE clause filtering | `-w field=value` (repeatable) |
| `sorting` | ORDER BY clause | `-o field:direction` (repeatable) |
| `relationship` | JOIN with child table | `--child-table`, `--foreign-key` |
| `aggregation` | GROUP BY with aggregates | `--group-by` |

**Options:**

| Option | Description |
|--------|-------------|
| `--limit INTEGER` | Pagination limit (default: 20) |
| `--offset INTEGER` | Pagination offset (default: 0) |
| `-w, --where TEXT` | Filter condition (format: `field=value`) |
| `-o, --order TEXT` | Order specification (format: `field:direction`) |
| `--child-table TEXT` | Child table for relationships |
| `--foreign-key TEXT` | Foreign key column name |
| `--group-by TEXT` | Field to group by |

**Examples:**

```bash
# Pagination pattern
fraiseql sql generate-pattern pagination users --limit 10 --offset 20

# Filtering pattern with multiple conditions
fraiseql sql generate-pattern filtering users \
  -w email=test@example.com \
  -w is_active=true

# Sorting pattern
fraiseql sql generate-pattern sorting users \
  -o name:ASC \
  -o created_at:DESC

# Relationship pattern (users with their posts)
fraiseql sql generate-pattern relationship users \
  --child-table posts \
  --foreign-key user_id

# Aggregation pattern (posts per user)
fraiseql sql generate-pattern aggregation posts --group-by user_id
```

**Generated Output Example (pagination):**

```sql
-- Pagination pattern for users
SELECT *
FROM users
ORDER BY id
LIMIT 10 OFFSET 20;
```

---

### sql validate

Validate SQL for FraiseQL compatibility.

**Usage:**

```bash
fraiseql sql validate SQL_FILE
```

**Checks:**

- View returns JSONB data
- Contains 'data' column
- Compatible with FraiseQL query patterns

**Examples:**

```bash
# Validate a view definition
fraiseql sql validate migrations/001_user_view.sql

# Output on success:
# ✓ SQL is valid for FraiseQL
# ✓ Has 'data' column
# ✓ Returns JSONB

# Output on failure:
# ✗ SQL has issues:
#   - Missing 'data' column
#   - Does not return JSONB
```

---

### sql explain

Explain SQL in beginner-friendly terms.

**Usage:**

```bash
fraiseql sql explain SQL_FILE
```

**Provides:**

- Human-readable explanation of SQL operations
- Common mistake detection
- Optimization suggestions

**Examples:**

```bash
fraiseql sql explain migrations/001_user_view.sql

# Output:
# SQL Explanation:
# This creates a view named 'v_users' that:
# - Selects data from the 'users' table
# - Returns JSONB objects with fields: id, name, email
# - Uses jsonb_build_object for efficient JSON construction
#
# Potential Issues:
#   - Consider adding an index on frequently filtered columns
#   - Missing WHERE clause may return soft-deleted records
```

---

## Workflow Examples

### Complete Project Setup

```bash
# 1. Create project
fraiseql init blog-api --template blog
cd blog-api

# 2. Set up Python environment
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. Generate database migrations
fraiseql generate migration User
fraiseql generate migration Post
fraiseql generate migration Comment

# 4. Apply migrations
psql $DATABASE_URL -f migrations/*_create_users.sql
psql $DATABASE_URL -f migrations/*_create_posts.sql
psql $DATABASE_URL -f migrations/*_create_comments.sql

# 5. Generate CRUD operations
fraiseql generate crud User
fraiseql generate crud Post
fraiseql generate crud Comment

# 6. Validate project
fraiseql check

# 7. Start development server
fraiseql dev
```

### Pre-Deployment Checklist

```bash
# Validate project structure and types
fraiseql check

# Generate latest schema for frontend
fraiseql generate schema -o frontend/schema.graphql

# Validate all custom SQL views
for sql in migrations/*.sql; do
  fraiseql sql validate "$sql"
done

# Run tests
pytest

# Deploy
docker build -t my-api .
docker push my-api
```

### Database Development Workflow

```bash
# 1. Generate view from Python type
fraiseql sql generate-view User --module src.types -o views/user.sql

# 2. Validate the generated SQL
fraiseql sql validate views/user.sql

# 3. Explain the SQL for review
fraiseql sql explain views/user.sql

# 4. Apply to database
psql $DATABASE_URL -f views/user.sql
```

---

## Environment Variables

FraiseQL CLI respects these environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | - | PostgreSQL connection string |
| `FRAISEQL_DATABASE_URL` | - | Alternative database URL |
| `FRAISEQL_AUTO_CAMEL_CASE` | `false` | Auto-convert snake_case to camelCase |
| `FRAISEQL_DEV_AUTH_PASSWORD` | - | Development auth password |
| `FRAISEQL_ENVIRONMENT` | `development` | Environment (development/production) |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | General error (check stderr output) |
| `2` | Invalid command or missing arguments |

---

## Troubleshooting

### Command Not Found

```bash
# Ensure fraiseql is installed
pip install "fraiseql<2"

# Check installation
which fraiseql
fraiseql --version
```

### Not in Project Directory

Most commands require you to be in a FraiseQL project directory:

```bash
# Check for pyproject.toml
ls pyproject.toml

# Or initialize new project
fraiseql init my-project
cd my-project
```

### Import Errors

```bash
# Install development dependencies
pip install -e ".[dev]"

# Ensure virtual environment is activated
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows
```

### Database Connection Issues

```bash
# Set DATABASE_URL environment variable
export DATABASE_URL="postgresql://user:pass@localhost/dbname"

# Or add to .env file
echo "FRAISEQL_DATABASE_URL=postgresql://localhost/mydb" >> .env
```

---

## Tips and Best Practices

1. **Always validate before deploying**: Use `fraiseql check` in CI/CD pipelines

2. **Generate schema for frontend teams**: Keep `schema.graphql` in version control

   ```bash
   fraiseql generate schema -o schema.graphql
   git add schema.graphql
   ```

3. **Use migrations for database changes**: Generate migrations with timestamps for proper ordering

4. **Validate custom SQL**: Always run `fraiseql sql validate` on hand-written views

5. **Development workflow**: Use `fraiseql dev` with auto-reload for fast iteration

6. **Script common tasks**:

   ```bash
   # scripts/reset-db.sh
   psql $DATABASE_URL -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
   for sql in migrations/*.sql; do psql $DATABASE_URL -f "$sql"; done
   fraiseql check
   ```

---

## See Also

- [5-Minute Quickstart](../getting-started/quickstart.md) - Get started quickly
- [Database API](../core/database-api.md) - Repository patterns
- [Production Deployment](../tutorials/production-deployment.md) - Deployment guide
- [Configuration](../core/configuration.md) - Application configuration

---

**Need help?** Run any command with `--help` for detailed usage information:

```bash
fraiseql --help
fraiseql init --help
fraiseql generate --help
fraiseql sql generate-view --help
```

---
title: Project Structure
description: Recommended project layout and file organization
tags:
  - project
  - structure
  - organization
  - best-practices
---

# Project Structure Guide

This guide explains the recommended project structure for FraiseQL applications, created automatically by `fraiseql init`.

## Visual Structure

```
my-project/
├── src/                          # 📁 Application source code
│   ├── main.py                  # 🚀 GraphQL schema & FastAPI app
│   ├── types/                   # 🏷️  GraphQL type definitions
│   │   ├── user.py             #   └─ User, Post, Comment types
│   │   ├── post.py
│   │   └── __init__.py
│   ├── queries/                 # 🔍 Custom query resolvers
│   │   ├── user_queries.py     #   └─ Complex business logic
│   │   └── __init__.py
│   ├── mutations/              # ✏️  Mutation handlers
│   │   ├── user_mutations.py   #   └─ Data modification ops
│   │   └── __init__.py
│   └── __init__.py
├── tests/                       # 🧪 Test suite
│   ├── test_user.py            #   └─ Unit & integration tests
│   └── conftest.py
├── migrations/                  # 🗃️  Database evolution
│   ├── 001_initial_schema.sql  #   └─ Versioned schema changes
│   └── 002_add_indexes.sql
├── .env                         # 🔐 Environment config
├── .gitignore                  # 🚫 Git ignore rules
├── pyproject.toml              # 📦 Dependencies & config
└── README.md                   # 📖 Project documentation
```

## Overview

FraiseQL projects follow a database-first architecture with clear separation of concerns. The structure emphasizes:

- **Database-first design**: Schema and views come first
- **Modular organization**: Separate directories for different concerns
- **Scalable patterns**: Easy to grow from minimal to enterprise

## Template Selection Guide

Choose the right starting template based on your project needs:

### 🚀 Quickstart (No Template)

**Best for**: Learning FraiseQL, prototypes, experimentation
**What you get**: Single-file app with basic CRUD operations
**When to use**: First time with FraiseQL, proof-of-concepts
**Evolution path**: Migrate to minimal template when growing

### 📦 Minimal Template

**Best for**: Simple applications, MVPs, small projects
**Features**:

- Single-file GraphQL schema
- Basic CRUD operations
- PostgreSQL integration
- Development server setup
**Example**: Todo app, simple blog, basic API

### 🏗️ Standard Template

**Best for**: Production applications, medium complexity
**Features**:

- Multi-file organization (types, queries, mutations)
- User authentication & authorization
- Query result caching
- Comprehensive testing setup
- Migration system
**Example**: SaaS app, e-commerce platform, content management

### 🏢 Enterprise Template

**Best for**: Large-scale applications, high traffic
**Features**:

- Multi-tenant architecture
- Advanced caching (APQ, result caching)
- Monitoring & observability
- Microservices-ready structure
- Performance optimizations
**Example**: Enterprise platforms, high-traffic APIs

### Evolution Path

```
Quickstart → Minimal → Standard → Enterprise
    ↓          ↓         ↓          ↓
 Learning   Simple    Production  Scale
Prototypes   Apps       Apps      Apps
```

**Migration Tips**:

- **Quickstart → Minimal**: Use `fraiseql init` and move code to organized structure
- **Minimal → Standard**: Split into multiple files, add authentication
- **Standard → Enterprise**: Add multi-tenancy, advanced caching, monitoring

## Best Practices by Template

### Quickstart Best Practices

- ✅ Keep it simple - single file for learning
- ✅ Focus on GraphQL concepts over architecture
- ✅ Use for experimentation and prototyping
- ❌ Don't use for production applications
- ❌ Don't add complex business logic

**Example Projects**: [Todo App Quickstart](../getting-started/quickstart.md)

### Minimal Template Best Practices

- ✅ Single-file schema for simple domains
- ✅ Clear type definitions with descriptions
- ✅ Basic error handling and validation
- ✅ Database-first design principles
- ❌ Don't mix concerns in main.py
- ❌ Don't skip input validation

**Example Projects**: [Simple Blog](../../examples/blog_simple/), [Basic API](../../examples/)

### Standard Template Best Practices

- ✅ Separate types, queries, and mutations
- ✅ Comprehensive test coverage
- ✅ Authentication and authorization
- ✅ Query result caching
- ✅ Proper error handling
- ❌ Don't put business logic in resolvers
- ❌ Don't skip database migrations

**Example Projects**: [Blog](../../examples/blog_simple/), [E-commerce](../../examples/ecommerce/)

### Enterprise Template Best Practices

- ✅ Multi-tenant data isolation
- ✅ Advanced performance optimizations
- ✅ Comprehensive monitoring
- ✅ Microservices communication patterns
- ✅ Automated testing and deployment
- ❌ Don't compromise on security
- ❌ Don't skip performance monitoring

**Example Projects**: [Enterprise Blog](../../examples/blog_enterprise/), [Multi-tenant App](../../examples/apq_multi_tenant/)

## Directory Structure

```
my-project/
├── src/                    # Application source code
│   ├── main.py            # GraphQL schema and FastAPI app
│   ├── types/             # GraphQL type definitions
│   │   ├── user.py        # User type
│   │   ├── post.py        # Post type
│   │   └── __init__.py
│   ├── queries/           # Custom query resolvers
│   │   ├── user_queries.py
│   │   └── __init__.py
│   ├── mutations/         # Mutation handlers
│   │   ├── user_mutations.py
│   │   └── __init__.py
│   └── __init__.py
├── tests/                 # Test files
│   ├── test_user.py
│   └── conftest.py
├── migrations/            # Database schema changes
│   ├── 001_initial_schema.sql
│   └── 002_add_indexes.sql
├── .env                   # Environment configuration
├── .gitignore            # Git ignore rules
├── pyproject.toml        # Python dependencies and config
└── README.md             # Project documentation
```

## Directory Purposes

### `src/` - Application Code

**Purpose**: Contains all Python application code organized by responsibility.

- **`main.py`**: Entry point with GraphQL schema definition and FastAPI app
- **`types/`**: GraphQL type definitions using `@fraiseql.type` decorators
- **`queries/`**: Custom query resolvers for complex business logic
- **`mutations/`**: Mutation handlers for data modification operations

### `tests/` - Test Suite

**Purpose**: Comprehensive test coverage for reliability.

- Unit tests for individual functions
- Integration tests for database operations
- API tests for GraphQL endpoints
- Performance tests for critical paths

### `migrations/` - Database Evolution

**Purpose**: Version-controlled database schema changes.

- SQL files for schema modifications
- Named with timestamps or sequential numbers
- Applied with `fraiseql migrate` command

### Configuration Files

- **`.env`**: Environment variables (database URLs, secrets)
- **`pyproject.toml`**: Python dependencies and tool configuration
- **`.gitignore`**: Excludes sensitive files from version control

## File Organization Patterns

### Type Definitions (`src/types/`)

```python
# src/types/user.py
import fraiseql
from fraiseql import fraise_field
from fraiseql.types import ID

@fraiseql.type
class User:
    """A user in the system."""
    id: ID = fraise_field(description="User ID")
    username: str = fraise_field(description="Unique username")
    email: str = fraise_field(description="Email address")
    created_at: str = fraise_field(description="Account creation date")
```

### Query Resolvers (`src/queries/`)

```python
# src/queries/user_queries.py
import fraiseql
from fraiseql import fraise_field
from fraiseql import fraise_field

from ..types.user import User

@fraiseql.type
class UserQueries:
    """User-related query operations."""

    users: list[User] = fraise_field(description="List all users")
    user_by_username: User | None = fraise_field(description="Find user by username")

    async def resolve_users(self, info):
        db = info.context["db"]
        return await db.find("v_user", "users", info)

    async def resolve_user_by_username(self, info, username: str):
        db = info.context["db"]
        return await db.find_one("v_user", mandatory_filters={"username": username})
```

### Mutation Handlers (`src/mutations/`)

```python
# src/mutations/user_mutations.py
import fraiseql
from fraiseql import fraise_field
from fraiseql import fraise_field
from fraiseql.types import ID

from ..types.user import User

@input
class CreateUserInput:
    """Input for creating a new user."""
    username: str = fraise_field(description="Desired username")
    email: str = fraise_field(description="Email address")

@fraiseql.type
class UserMutations:
    """User-related mutation operations."""

    create_user: User = fraise_field(description="Create a new user account")

    async def resolve_create_user(self, info, input: CreateUserInput):
        db = info.context["db"]
        result = await db.execute_function("fn_create_user", {
            "username": input.username,
            "email": input.email
        })
        return await db.find_one("v_user", mandatory_filters={"id": result["id"]})
```

### Main Application (`src/main.py`)

```python
# src/main.py
import os

import fraiseql
from fraiseql import fraise_field
from fraiseql import fraise_field

from .types.user import User
from .queries.user_queries import UserQueries
from .mutations.user_mutations import UserMutations

@fraiseql.type
class QueryRoot(UserQueries):
    """Root query type combining all query operations."""
    pass

@fraiseql.type
class MutationRoot(UserMutations):
    """Root mutation type combining all mutation operations."""
    pass

# Create the FastAPI app
app = fraiseql.create_fraiseql_app(
    queries=[QueryRoot],
    mutations=[MutationRoot],
    database_url=os.getenv("FRAISEQL_DATABASE_URL"),
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
```

## Database Organization

### Schema Files (`migrations/`)

```
migrations/
├── 001_initial_schema.sql     # Core tables and views
├── 002_add_user_auth.sql      # Authentication tables
├── 003_add_indexes.sql        # Performance indexes
└── 004_add_audit_triggers.sql # Audit logging
```

### Naming Conventions

**Tables**:

- `tb_entity` - Base tables (e.g., `tb_user`, `tb_post`)
- `tb_entity_history` - Audit/history tables

**Views**:

- `v_entity` - Regular views for queries
- `tv_entity` - Materialized views for performance

**Functions**:

- `fn_operation_entity` - Mutation functions (e.g., `fn_create_user`)

## Scaling Patterns

### From Minimal to Standard

1. **Split main.py**: Move types to `src/types/`
2. **Add authentication**: Create user management
3. **Add caching**: Enable query result caching
4. **Add tests**: Comprehensive test coverage

### From Standard to Enterprise

1. **Multi-tenancy**: Add tenant isolation
2. **Advanced caching**: APQ and result caching
3. **Monitoring**: Add observability
4. **Microservices**: Split into services

## Best Practices

### Code Organization

- One type per file in `src/types/`
- Group related operations in query/mutation files
- Use clear, descriptive names
- Add docstrings to all public functions

### Database Design

- Design views for query patterns, not storage
- Use functions for complex business logic
- Index columns used in WHERE clauses
- Plan for growth and partitioning

### Testing Strategy

- Unit tests for pure functions
- Integration tests for database operations
- API tests for GraphQL endpoints
- Performance tests for critical queries

### Configuration Management

- Use `.env` for environment-specific settings
- Never commit secrets to version control
- Document all configuration options
- Use sensible defaults

## Tooling Integration

### Development Tools

```bash
# Start development server
fraiseql dev

# Run tests
pytest

# Format code
ruff format

# Type checking
mypy
```

### Production Deployment

- Use environment variables for configuration
- Set up proper logging and monitoring
- Configure database connection pooling
- Enable caching and performance optimizations

## Migration from Quickstart

When your quickstart project grows:

1. **Run `fraiseql init`**: Create proper structure
2. **Move code**: Migrate from single file to organized modules
3. **Add tests**: Create comprehensive test suite
4. **Add migrations**: Version control database changes
5. **Configure CI/CD**: Set up automated testing and deployment

This structure provides a solid foundation that scales from simple prototypes to complex, production-ready applications.

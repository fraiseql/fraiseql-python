# Query Patterns Example

🟡 INTERMEDIATE | ⏱️ 20 min | 🎯 Query Registration | 🏷️ Patterns

A comprehensive demonstration of all three ways to register GraphQL queries in FraiseQL, showing the evolution from explicit registration to automatic discovery.

**What you'll learn:**

- Three different approaches to query registration
- Pros and cons of each registration method
- When to use each pattern in real applications
- Best practices for organizing GraphQL resolvers

**Prerequisites:**

- `../blog_simple/` - Basic FraiseQL concepts
- Understanding of GraphQL queries and resolvers

**Next steps:**

- `../enterprise_patterns/` - Advanced enterprise features

## Overview

This example demonstrates three distinct patterns for registering GraphQL queries in FraiseQL:

1. **@fraiseql.query decorator** (Recommended) - Clean, automatic registration
2. **QueryRoot class with @fraiseql.field** - Traditional class-based approach
3. **Explicit function registration** - Manual control over registration

Each pattern is shown with complete working code and GraphQL examples.

## Pattern 1: @fraiseql.query Decorator (RECOMMENDED)

The cleanest and most intuitive approach - queries are automatically registered when the module is imported.

### Code Example

```python
@fraiseql.query
async def get_user(info, id: UUID) -> User:
    """Get a user by ID."""
    # Your database logic here
    return User(id=id, name="John", email="john@example.com")

@fraiseql.query
async def list_users(info, role: str | None = None) -> list[User]:
    """List users with optional role filter."""
    # Your database logic here
    return users
```

### GraphQL Usage

```graphql
query {
  getUser(id: "123e4567-e89b-12d3-a456-426614174000") {
    id
    name
    email
  }

  listUsers(role: "admin") {
    id
    name
    email
  }
}
```

### When to Use

- ✅ New projects
- ✅ Simple to complex applications
- ✅ Automatic registration (no manual lists)
- ✅ Clean, readable code

## Pattern 2: QueryRoot Class with @fraiseql.field

Traditional class-based approach where you define a root query class with field decorators.

### Code Example

```python
@fraiseql.type
class QueryRoot:
    """Root query type for field-based queries."""

    @fraiseql.field(description="Get API version")
    def api_version(self, root, info) -> str:
        return "1.0.0"

    @fraiseql.field
    async def stats(self, root, info) -> dict[str, int]:
        return {"total_users": 156, "active_sessions": 42}
```

### GraphQL Usage

```graphql
query {
  apiVersion
  stats {
    totalUsers
    activeSessions
  }
}
```

### When to Use

- ✅ Migrating from other GraphQL libraries
- ✅ Complex query hierarchies
- ✅ Need method-based organization
- ✅ Familiar class-based patterns

## Pattern 3: Explicit Function Registration

Manual control over query registration - functions must be explicitly listed in `create_fraiseql_app()`.

### Code Example

```python
# Function is NOT decorated
async def search_posts(info, query: str, published_only: bool = True) -> list[Post]:
    """Search posts by title or content."""
    # Your search logic here
    return posts

# Must be explicitly registered
app = create_fraiseql_app(
    database_url="postgresql://localhost/example",
    types=[User, Post],
    queries=[search_posts],  # Explicit list required
)
```

### GraphQL Usage

```graphql
query {
  searchPosts(query: "fraiseql", publishedOnly: true) {
    id
    title
    content
    published
  }
}
```

### When to Use

- ✅ Need explicit control over what's exposed
- ✅ Dynamic query registration
- ✅ Complex routing logic
- ✅ Advanced security requirements

## Quick Start

### 1. Prerequisites

- Python 3.13+
- PostgreSQL (optional - examples use mock data)

### 2. Install Dependencies

```bash
pip install fraiseql fastapi uvicorn
```

### 3. Run Examples

```bash
# Pattern 1: Decorator approach (recommended)
python blog_pattern.py

# Pattern 2 & 3: Class and explicit registration
python app.py
```

Visit http://localhost:8000/graphql for GraphQL Playground.

## Pattern Comparison

| Aspect | @query Decorator | QueryRoot Class | Explicit Registration |
|--------|------------------|-----------------|----------------------|
| **Ease of Use** | ⭐⭐⭐ | ⭐⭐ | ⭐ |
| **Code Clarity** | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ |
| **Flexibility** | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| **Migration Friendly** | ⭐⭐ | ⭐⭐⭐ | ⭐ |
| **Performance** | Same | Same | Same |
| **Recommended For** | New projects | Class-based code | Advanced use cases |

## Key Learning Points

### Automatic vs Explicit Registration

**@fraiseql.query decorator:**

- Zero-configuration registration
- Functions are discovered automatically
- Clean separation of concerns
- Best for most applications

**Explicit registration:**

- Complete control over API surface
- Can conditionally register queries
- Better for complex security requirements
- More verbose but more explicit

### Best Practices

1. **Use @fraiseql.query for new projects** - it's the most maintainable
2. **Group related queries logically** - either by decorator or class organization
3. **Document query parameters** - use descriptive names and types
4. **Handle errors gracefully** - return appropriate GraphQL errors
5. **Consider performance** - database queries should be optimized

## Testing the Examples

### With Mock Data

The examples include mock data, so they work without a database:

```bash
python blog_pattern.py
# Visit http://localhost:8000/graphql
```

### With Real Database

For production-like testing, set up PostgreSQL and modify the query functions to use real database calls.

## Next Steps

After mastering these patterns:

1. **Add mutations** - See `../blog_simple/` for mutations backed by SQL functions
2. **Add authentication** - See `../saas-starter/` for user management
3. **Add enterprise patterns** - See `../enterprise_patterns/` for production features
4. **Add real database integration** - Replace mock data with actual queries

---

**FraiseQL Query Registration Patterns**. Demonstrates three approaches to GraphQL query registration, from automatic discovery to explicit control.

## Support

- **Issues**: [GitHub Issues](../../issues)
- **Discussions**: [GitHub Discussions](../../discussions)
- **Discord**: [FraiseQL Community](https://discord.gg/fraiseql)
- **Documentation**: [FraiseQL Docs](../../docs)

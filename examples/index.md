# FraiseQL Examples Index

Welcome to the FraiseQL examples collection! This index organizes all 20+ examples by difficulty level and use case to help you find the right starting point for your project.

## 🎯 Quick Start Recommendation

**New to FraiseQL? Start here:**

- **[`todo_quickstart.py`](todo_quickstart.py)** - 5-minute introduction to basic GraphQL API
- **[`blog_api/`](blog_api/README.md)** - Complete content management system with enterprise patterns

---

## 📊 Examples by Difficulty

### 🟢 Beginner (Start Here)

Perfect for learning FraiseQL fundamentals. These examples focus on core concepts with minimal complexity.

| Example | Description | Key Concepts | Time |
|---------|-------------|--------------|------|
| [`todo_quickstart.py`](todo_quickstart.py) | **RECOMMENDED START** - Simple todo app | Basic types, queries, mutations | 5 min |
| [`blog_api/`](blog_api/README.md) | Content management with enterprise patterns | CQRS, audit trails, mutation results | 15 min |
| [`health_check_example.py`](health_check_example.py) | Basic health check endpoints | Simple queries, FastAPI integration | 5 min |

### 🟡 Intermediate (Build Skills)

These examples demonstrate real-world patterns and integrations for production applications.

| Example | Description | Key Concepts | Time |
|---------|-------------|--------------|------|
| [`ecommerce/`](ecommerce/README.md) | Complete e-commerce platform | Complex queries, business logic, auth | 30 min |
| [`apq_multi_tenant/`](apq_multi_tenant/README.md) | Multi-tenant APQ caching | SaaS patterns, performance optimization | 20 min |
| [`caching_example.py`](caching_example.py) | PostgreSQL-native caching | Performance, Redis alternatives | 15 min |
| [`security/`](security/README.md) | Authentication & security patterns | JWT, role-based access, validation | 25 min |
| [`turbo_router_with_complexity.py`](turbo_router_with_complexity.py) | Pre-compiled query routing | Performance optimization, query planning | 20 min |
| [`complex_nested_where_clauses.py`](complex_nested_where_clauses.py) | Advanced query patterns | Complex filtering, nested conditions | 15 min |

### 🟠 Advanced (Production Ready)

Enterprise-grade examples showcasing advanced patterns, scalability, and production considerations.

| Example | Description | Key Concepts | Time |
|---------|-------------|--------------|------|
| [`enterprise_patterns/`](enterprise_patterns/README.md) | **ALL PATTERNS** - Complete enterprise reference | Audit trails, multi-tenancy, validation layers | 45 min |
| [`blog_enterprise/`](blog_enterprise/README.md) | Enterprise blog with DDD | Domain-driven design, event sourcing | 40 min |
| [`complete_cqrs_blog/`](complete_cqrs_blog/README.md) | Full CQRS implementation | Command-query separation, Docker, migrations | 35 min |
| [`analytics_dashboard/`](analytics_dashboard/README.md) | Business intelligence platform | TimescaleDB, complex analytics, dashboards | 40 min |
| [`saas-starter/`](saas-starter/README.md) | Multi-tenant SaaS foundation | Tenant isolation, billing, user management | 50 min |

### 🔴 Specialized (Domain Specific)

Examples for specific use cases and integrations.

| Example | Description | Key Concepts | Time |
|---------|-------------|--------------|------|
| [`native-auth-app/`](native-auth-app/README.md) | Vue.js authentication app | Frontend integration, JWT handling | 25 min |
| [`hybrid_tables.py`](hybrid_tables.py) | Hybrid relational/document patterns | Flexible schemas, JSONB usage | 20 min |
| [`token_revocation_example.py`](token_revocation_example.py) | Advanced auth patterns | Token management, revocation strategies | 15 min |
| [`turbo_router_with_complexity.py`](turbo_router_with_complexity.py) | Complex routing scenarios | Advanced query optimization | 25 min |

---

## 🏗️ Examples by Use Case

### 🛍️ E-commerce & Business

- [`ecommerce/`](ecommerce/README.md) - Complete online store
- [`saas-starter/`](saas-starter/README.md) - SaaS application foundation
- [`analytics_dashboard/`](analytics_dashboard/README.md) - Business intelligence

### 📝 Content Management

- [`blog_api/`](blog_api/README.md) - Enterprise content system
- [`blog_enterprise/`](blog_enterprise/README.md) - Advanced blogging platform
- [`complete_cqrs_blog/`](complete_cqrs_blog/README.md) - CQRS blog implementation

### 🔐 Authentication & Security

- [`security/`](security/README.md) - Security best practices
- [`native-auth-app/`](native-auth-app/README.md) - Frontend auth integration
- [`token_revocation_example.py`](token_revocation_example.py) - Token management

### ⚡ Performance & Caching

- [`apq_multi_tenant/`](apq_multi_tenant/README.md) - Multi-tenant query caching
- [`caching_example.py`](caching_example.py) - PostgreSQL caching
- [`turbo_router_with_complexity.py`](turbo_router_with_complexity.py) - Query pre-compilation

### 🏢 Enterprise Patterns

- [`enterprise_patterns/`](enterprise_patterns/README.md) - All enterprise patterns

---

## 📚 Learning Paths

### 🚀 Complete Beginner Path

1. **[`todo_quickstart.py`](todo_quickstart.py)** - Learn the basics (5 min)
2. **[`blog_api/`](blog_api/README.md)** - Build a real application (15 min)
3. **[`ecommerce/`](ecommerce/README.md)** - Add complexity (30 min)
4. **[`enterprise_patterns/`](enterprise_patterns/README.md)** - Master advanced patterns (45 min)

### 🏢 Production Developer Path

1. **[`blog_api/`](blog_api/README.md)** - Enterprise patterns foundation
2. **[`apq_multi_tenant/`](apq_multi_tenant/README.md)** - Performance optimization
3. **[`security/`](security/README.md)** - Security implementation
4. **[`saas-starter/`](saas-starter/README.md)** - Scalable architecture

### 🔧 Performance Specialist Path

1. **[`caching_example.py`](caching_example.py)** - Caching fundamentals
2. **[`turbo_router_with_complexity.py`](turbo_router_with_complexity.py)** - Query optimization
3. **[`apq_multi_tenant/`](apq_multi_tenant/README.md)** - Advanced caching
4. **[`analytics_dashboard/`](analytics_dashboard/README.md)** - High-performance analytics

### 🏗️ Enterprise Architect Path

1. **[`enterprise_patterns/`](enterprise_patterns/README.md)** - All enterprise patterns
2. **[`blog_enterprise/`](blog_enterprise/README.md)** - Domain-driven design
3. **[`complete_cqrs_blog/`](complete_cqrs_blog/README.md)** - CQRS implementation

---

## 🔧 Development Tools & Utilities

### Setup & Configuration

- [`_template-readme.md`](_template-readme.md) - Template for new examples

### Testing & Validation

All examples include automated testing. Run tests with:

```bash
# Test a specific example
cd examples/example_name
pytest

# Test all examples
cd examples
find . -name "*test*.py" -exec pytest {} \;
```

---

## 🤝 Contributing Examples

### Adding New Examples

1. Create a new directory under `examples/`
2. Follow the established structure (see [`_template-readme.md`](_template-readme.md))
3. Add comprehensive documentation
4. Include automated tests
5. Update this INDEX.md file

### Example Structure

```
example_name/
├── README.md          # Comprehensive documentation
├── main.py           # Main application code
├── models.py         # GraphQL type definitions
├── mutations.py      # GraphQL mutations
├── queries.py        # GraphQL queries
├── schema.sql        # Database schema
├── requirements.txt  # Python dependencies
├── test_*.py         # Automated tests
└── docker-compose.yml # (Optional) Development environment
```

### Quality Standards

- ✅ Working code that runs without errors
- ✅ Comprehensive README with setup instructions
- ✅ Automated tests with good coverage
- ✅ Realistic, production-relevant examples
- ✅ Clear difficulty level and use case
- ✅ Cross-references to related examples

---

## 📖 Documentation Links

- **[Main Documentation](../docs/README.md)** - Complete FraiseQL documentation
- **[Quick Start](../docs/getting-started/quickstart.md)** - Getting started guide
- **[Core Concepts](../docs/core/README.md)** - Fundamental concepts
- **[Performance Guide](../docs/performance/performance-guide.md)** - Optimization techniques
- **[Production Deployment](../docs/production/README.md)** - Production setup

---

## 🆘 Need Help?

- **Issues**: [GitHub Issues](../../issues)
- **Discussions**: [GitHub Discussions](../../discussions)
- **Discord**: [FraiseQL Community](https://discord.gg/fraiseql)

---

*This index helps you navigate 20+ FraiseQL examples. Start with beginner examples and progress to advanced patterns as you build your expertise.*

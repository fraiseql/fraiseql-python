# Security Policy

## Supported Versions

| Version                   | Supported          |
| ------------------------- | ------------------ |
| Latest 1.x release        | :white_check_mark: |
| Any earlier 1.x release   | :x:                |

Fixes ship in the next release cut from `dev`. There are no maintenance branches and
older minors are not backported, so "supported" means the most recent release on PyPI.

Note that v1 is this repository, `fraiseql-python`. The separate v2 project
(`fraiseql/fraiseql`) has its own security policy; report v2 issues there.

## Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security issue, please follow these steps:

### 1. Do NOT Open a Public Issue

Please do not report security vulnerabilities through public GitHub issues.

### 2. Email Security Team

**Report via GitHub Security Advisories**: [Create a Security Advisory](https://github.com/fraiseql/fraiseql-python/security/advisories/new)

If you prefer email, send details to: **security@fraiseql.com** (response may be delayed)

Include:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### 3. Response Timeline

- **Initial Response**: Within 48 hours
- **Status Update**: Within 7 days
- **Fix Timeline**: Depends on severity

## Security Features

FraiseQL includes several built-in security features:

### 1. SQL Injection Prevention

All queries use parameterized statements:

```python
# Safe - parameters are properly escaped
repo.find("users_view", email=user_input)
```

### 2. Authentication & Authorization

Support for Auth0 and custom providers:

```python
from fraiseql.auth import Auth0Provider

auth = Auth0Provider(
    domain="your-domain.auth0.com",
    audience="your-api"
)
```

### 3. Field-Level Authorization

Control access at the field level:

```python
@fraiseql.field
@requires_auth
@requires_permission("read:sensitive_data")
def sensitive_field(user: User, info: Info) -> str:
    return user.sensitive_data
```

### 4. Query Complexity Limits

Prevent resource exhaustion:

```python
from fraiseql import ComplexityConfig

config = ComplexityConfig(
    max_complexity=1000,
    max_depth=10
)
```

### 5. Rate Limiting

Built-in rate limiting support:

```python
from fraiseql.auth import RateLimitConfig

rate_limit = RateLimitConfig(
    requests_per_minute=100,
    burst=20
)
```

### 6. CSRF Protection

Automatic CSRF token validation:

```python
from fraiseql import FraiseQLConfig

config = FraiseQLConfig(
    csrf_protection=True
)
```

### 7. Introspection Control

Disable introspection in production:

```python
config = FraiseQLConfig(
    introspection_enabled=False  # Disable in production
)
```

## Security Best Practices

### 1. Environment Variables

Never commit secrets:

```python
# Use environment variables
DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")
```

### 2. HTTPS Only

Always use HTTPS in production:

```python
app.add_middleware(
    HTTPSRedirectMiddleware
)
```

### 3. Database Permissions

Use least-privilege principle:

```sql
-- Read-only user for queries
CREATE USER fraiseql_reader WITH PASSWORD 'secure_password';
GRANT SELECT ON ALL TABLES IN SCHEMA public TO fraiseql_reader;
```

### 4. Input Validation

Validate all user inputs:

```python
from pydantic import BaseModel, EmailStr

class UserInput(BaseModel):
    email: EmailStr  # Validated email
    age: int  # Type validation
```

### 5. Dependency Updates

Keep dependencies up to date:

```bash
pip list --outdated
pip install --upgrade fraiseql
```

### 6. Audit Logging

Enable audit logs for sensitive operations:

```python
from fraiseql.enterprise.audit import AuditLogger

audit = AuditLogger()
audit.log_mutation("update_user", user_id=123)
```

## Known Issues

Check the [Security Advisories](https://github.com/fraiseql/fraiseql-python/security/advisories) page for known vulnerabilities.

## Disclosure Policy

When we receive a security report:

1. We confirm the issue
2. We develop a fix
3. We prepare a security advisory
4. We release the fix
5. We publicly disclose the issue

We aim to coordinate disclosure with the reporter.

## Security Updates

Subscribe to security announcements:

- Watch the GitHub repository
- Follow our security mailing list
- Check release notes for security fixes

## Third-Party Dependencies

FraiseQL depends on several packages. We monitor security advisories for:

- FastAPI
- Strawberry GraphQL
- PostgreSQL drivers
- Authentication libraries

## Compliance

FraiseQL can help meet compliance requirements:

- **GDPR**: Field-level data access control
- **SOC 2**: Audit logging and access controls
- **HIPAA**: Encryption and access controls

Contact us for compliance documentation.

## Questions?

For security questions that aren't vulnerabilities:

- Open a GitHub discussion
- Email: security@fraiseql.com

Thank you for helping keep FraiseQL secure!

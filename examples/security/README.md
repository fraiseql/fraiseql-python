# FraiseQL Security Example

This example demonstrates how to build a production-ready GraphQL API with comprehensive security features using FraiseQL's security module.

`secure_graphql_api.py` keeps its posts in memory, so it runs without a database: the point is the security setup. See [`../blog_simple/`](../blog_simple/README.md) for queries and mutations on PostgreSQL.

## Security Features Implemented

### 🛡️ Rate Limiting

- **GraphQL Operation-Aware**: Different limits for queries, mutations, and subscriptions
- **Complexity-Based**: Rate limiting based on query complexity (simple, medium, complex)
- **Redis Support**: Distributed rate limiting with Redis for horizontal scaling
- **User-Based**: Different limits for authenticated vs anonymous users

### 🔒 CSRF Protection

- **Mutation Protection**: All mutations require valid CSRF tokens
- **Multiple Token Sources**: Supports tokens in headers, cookies, or GraphQL variables
- **Session Integration**: Tokens are bound to the session when a session middleware sets `request.state.session_id` (or a `session_id` cookie)
- **Configurable**: Separate configs for production and development

### 🛡️ Security Headers

- **Content Security Policy**: Strict CSP with configurable directives
- **Frame Protection**: X-Frame-Options to prevent clickjacking
- **HSTS**: HTTP Strict Transport Security for HTTPS enforcement
- **Cross-Origin Policies**: CORP, COOP, and COEP headers
- **Feature Control**: Permissions-Policy to disable dangerous browser features

### ✅ Input Validation

- **GraphQL Schema Validation**: Type-safe inputs with FraiseQL
- **Custom Validators**: Additional business logic validation
- **Sanitization**: XSS and injection prevention
- **Error Handling**: Structured error responses with codes

## Quick Start

### 1. Install Dependencies

```bash
pip install fraiseql fastapi uvicorn
# Optional: Redis for distributed rate limiting
pip install redis
```

### 2. Basic Setup

```python
from fastapi import FastAPI
from fraiseql.security import setup_security

app = FastAPI()

# One-line security setup
setup_security(
    app=app,
    secret_key="your-secret-key",
    environment="production",
    domain="api.example.com",
    trusted_origins={"https://app.example.com"},
)
```

### 3. Run the Example

```bash
# Development mode
ENVIRONMENT=development python secure_graphql_api.py

# Production mode
ENVIRONMENT=production \
SECRET_KEY=your-secret-key \
DOMAIN=api.example.com \
TRUSTED_ORIGINS=https://app.example.com \
python secure_graphql_api.py
```

## Configuration Options

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ENVIRONMENT` | Environment (development/production) | `development` |
| `SECRET_KEY` | Secret key for CSRF tokens | `dev-secret-key...` |
| `DOMAIN` | Application domain | `api.example.com` |
| `TRUSTED_ORIGINS` | Comma-separated trusted origins | `https://app.example.com` |
| `REDIS_URL` | Redis URL for distributed rate limiting | None |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://localhost/secure_blog` |

### Security Configurations

#### Production Setup

```python
from fraiseql.security import setup_production_security

security = setup_production_security(
    app=app,
    secret_key="strong-secret-key",
    domain="api.example.com",
    trusted_origins={"https://app.example.com", "https://admin.example.com"},
    redis_client=redis_client,  # Optional
)
```

#### Development Setup

```python
from fraiseql.security import setup_development_security

security = setup_development_security(app=app, secret_key="dev-secret-key")
```

#### Custom GraphQL Setup

```python
from fraiseql.security import create_security_config_for_graphql, setup_security

config = create_security_config_for_graphql(
    secret_key="your-secret-key",
    environment="production",
    trusted_origins=["https://app.example.com"],
    enable_introspection=False,
    redis_client=redis_client,
)

security = setup_security(app, custom_config=config)
```

## Testing Security Features

### 1. Rate Limiting

```bash
# Test query rate limiting
for i in {1..150}; do
  curl -X POST http://localhost:8000/graphql \
    -H "Content-Type: application/json" \
    -d '{"query": "{ posts { id } }"}' &
done
wait

# Should see 429 responses after hitting the limit
```

### 2. CSRF Protection

```bash
# Get CSRF token
TOKEN=$(curl -s http://localhost:8000/csrf-token | jq -r .csrf_token)

# Valid mutation with CSRF token
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer valid-token" \
  -H "X-CSRF-Token: $TOKEN" \
  -d '{"query": "mutation { createPost(input: {title: \"Test\", content: \"Hello World\"}) { id } }"}'

# Mutation without CSRF token: 403
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer valid-token" \
  -d '{"query": "mutation { createPost(input: {title: \"Test\", content: \"Hello World\"}) { id } }"}'
```

Mutations need the token in the `X-CSRF-Token` header (or as a `csrf_token`
GraphQL variable), in every environment. Every response also sets a `csrf_token`
cookie, but the cookie alone doesn't count: the browser would send it with a forged
request too. In production, a mutation whose `Origin` (or `Referer`) isn't one of
`TRUSTED_ORIGINS` is rejected as well.

Without `Authorization: Bearer valid-token`, mutations return an `UNAUTHENTICATED` error.

### 3. Security Headers

```bash
# Check security headers
curl -I http://localhost:8000/graphql

# Should include:
# X-Frame-Options: SAMEORIGIN
# X-Content-Type-Options: nosniff
# Strict-Transport-Security: max-age=31536000; includeSubDomains
# Content-Security-Policy: default-src 'self'; ...
```

### 4. Input Validation

```bash
# Valid input
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer valid-token" \
  -H "X-CSRF-Token: $TOKEN" \
  -d '{"query": "mutation { createPost(input: {title: \"Valid Title\", content: \"This is valid content with enough characters.\"}) { id title } }"}'

# Invalid input (too short)
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer valid-token" \
  -H "X-CSRF-Token: $TOKEN" \
  -d '{"query": "mutation { createPost(input: {title: \"Hi\", content: \"Short\"}) { id title } }"}'

# The response has an error with extensions.code VALIDATION_ERROR
```

## Advanced Configuration

### Custom Rate Limits

```python
from fraiseql.security import RateLimit, RateLimitRule, SecurityConfig, setup_security

custom_rules = [
    RateLimitRule(
        path_pattern="/graphql",
        rate_limit=RateLimit(requests=100, window=60),
        message="GraphQL rate limit exceeded",
    ),
    RateLimitRule(
        path_pattern="/admin/*",
        rate_limit=RateLimit(requests=10, window=60),
        message="Admin rate limit exceeded",
    ),
]

config = SecurityConfig(secret_key="your-secret-key", custom_rate_limits=custom_rules)
setup_security(app, secret_key="your-secret-key", custom_config=config)
```

### Custom CSRF Configuration

```python
from fraiseql.security import CSRFConfig, CSRFTokenStorage, SecurityConfig, setup_security

csrf_config = CSRFConfig(
    secret_key="your-secret-key",
    token_timeout=3600,  # 1 hour
    require_for_mutations=True,
    require_for_subscriptions=False,
    storage=CSRFTokenStorage.COOKIE,
    check_referrer=True,
    trusted_origins={"https://app.example.com"},
)

config = SecurityConfig(secret_key="your-secret-key", custom_csrf_config=csrf_config)
setup_security(app, secret_key="your-secret-key", custom_config=config)
```

### Custom Security Headers

```python
from fraiseql.security import (
    ContentSecurityPolicy,
    CSPDirective,
    SecurityConfig,
    SecurityHeadersConfig,
    setup_security,
)

# Create custom CSP
csp = ContentSecurityPolicy()
csp.add_directive(CSPDirective.DEFAULT_SRC, "'self'")
csp.add_directive(CSPDirective.SCRIPT_SRC, ["'self'", "https://trusted-cdn.com"])
csp.add_directive(CSPDirective.CONNECT_SRC, ["'self'", "https://api.example.com"])

headers_config = SecurityHeadersConfig(
    csp=csp,
    hsts_max_age=31536000,
    hsts_include_subdomains=True,
    cross_origin_embedder_policy="require-corp",
)

config = SecurityConfig(secret_key="your-secret-key", custom_security_headers=headers_config)
setup_security(app, secret_key="your-secret-key", custom_config=config)
```

## Monitoring Security

### Logging Security Events

```python
import logging

# Configure security event logging
logging.basicConfig(level=logging.INFO)
security_logger = logging.getLogger("fraiseql.security")

# Security events are automatically logged:
# - Rate limit violations
# - CSRF validation failures
# - Suspicious input patterns
# - Authentication failures
```

## Production Deployment

### Docker

```dockerfile
FROM python:3.13-slim

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . /app
WORKDIR /app

ENV ENVIRONMENT=production
ENV SECRET_KEY=${SECRET_KEY}
ENV DOMAIN=${DOMAIN}
ENV TRUSTED_ORIGINS=${TRUSTED_ORIGINS}

EXPOSE 8000
CMD ["python", "secure_graphql_api.py"]
```

### Environment Variables for Production

```bash
# Required
SECRET_KEY=your-32-character-secret-key-here
DOMAIN=api.yourdomain.com
TRUSTED_ORIGINS=https://app.yourdomain.com,https://admin.yourdomain.com

# Optional
REDIS_URL=redis://redis:6379/0
DATABASE_URL=postgresql://user:pass@db:5432/app
PORT=8000
HOST=0.0.0.0
```

### Security Checklist

- [ ] Strong secret key (32+ characters)
- [ ] HTTPS enforced in production
- [ ] Trusted origins configured
- [ ] Redis for distributed rate limiting
- [ ] Security headers verified
- [ ] CSRF protection tested
- [ ] Input validation confirmed
- [ ] Error handling reviewed
- [ ] Monitoring and logging configured
- [ ] Regular security updates

## Common Patterns

### Authentication Integration

```python
async def auth_middleware(request: Request, call_next):
    """JWT authentication middleware."""
    auth_header = request.headers.get("Authorization")

    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            request.state.user_id = payload["user_id"]
            request.state.is_authenticated = True
        except jwt.InvalidTokenError:
            request.state.user_id = None
            request.state.is_authenticated = False

    return await call_next(request)
```

### Role-Based Access Control

```python
from graphql import GraphQLError, GraphQLResolveInfo


@fraiseql.mutation
async def admin_only_mutation(info: GraphQLResolveInfo) -> str:
    """Mutation that requires admin role."""
    # Put is_admin in the context from your context_getter
    if not info.context.get("is_admin"):
        raise GraphQLError("Admin access required", extensions={"code": "FORBIDDEN"})

    return "Admin operation successful"
```

fraiseql also has decorators for this: `requires_role`, `requires_permission`
(and `requires_auth`) in `fraiseql.auth`.

## Contributing

See the main [FraiseQL contributing guide](../../CONTRIBUTING.md) for development setup and guidelines.

## License

This example is part of the FraiseQL project. See the [LICENSE](../../LICENSE) file for details.

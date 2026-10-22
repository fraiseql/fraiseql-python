# FraiseQL Blog Enterprise - Advanced Example Application

An enterprise-grade blog application demonstrating advanced FraiseQL patterns and best practices.

## 🌟 Overview

This is a **production-ready enterprise blog application** that showcases:

- **Domain-driven design** with bounded contexts
- **Advanced PostgreSQL patterns** (stored procedures, triggers, materialized views)
- **Enterprise authentication** with role-based access control
- **Multi-tenant architecture** support
- **Performance optimization** with caching and query optimization
- **Event sourcing** and audit trails

**Perfect for**: Large-scale applications, enterprise systems, complex business domains.

## 🏗️ Architecture

### Domain-Driven Design Structure

```
blog_enterprise/
├── README.md
├── app.py                          # Application entry point
├── domain/
│   ├── __init__.py
│   ├── common/
│   │   ├── base_classes.py         # Domain base classes
│   │   ├── events.py               # Domain events
│   │   └── exceptions.py           # Domain exceptions
│   ├── content/
│   │   ├── post.py                 # Post aggregate
│   │   ├── comment.py              # Comment entity
│   │   └── value_objects.py        # Content value objects
│   ├── users/
│   │   ├── user.py                 # User aggregate
│   │   ├── authentication.py       # Auth domain services
│   │   └── value_objects.py        # User value objects
│   ├── taxonomy/
│   │   ├── tag.py                  # Tag entity
│   │   └── category.py             # Category aggregate
│   └── management/
│       ├── organization.py         # Multi-tenant organization
│       └── audit.py                # Audit logging
├── infrastructure/
│   ├── database/
│   │   ├── migrations/             # Database migrations
│   │   ├── functions/              # PostgreSQL functions
│   │   ├── triggers/               # Database triggers
│   │   └── views/                  # Materialized views
│   ├── repositories/               # Repository implementations
│   ├── events/                     # Event handlers
│   └── auth/                       # Authentication infrastructure
├── application/
│   ├── commands/                   # Command handlers (CQRS)
│   ├── queries/                    # Query handlers (CQRS)
│   ├── services/                   # Application services
│   └── policies/                   # Business policies
└── tests/
    ├── unit/                       # Unit tests
    ├── integration/                # Integration tests
    └── e2e/                        # End-to-end tests
```

### Key Enterprise Patterns

1. **Bounded Contexts**: Clear separation between Content, Users, Taxonomy, and Management
2. **Aggregates**: Rich domain models with business logic encapsulation
3. **Domain Events**: Decoupled communication between contexts
4. **CQRS**: Separated command and query responsibilities
5. **Event Sourcing**: Complete audit trail of all changes
6. **Multi-tenancy**: Organization-based data isolation

## 🚀 Quick Start

### 1. Setup with Docker

```bash
# Clone and navigate
git clone <repository>
cd examples/blog_enterprise

# Start all services (PostgreSQL, Redis, Application)
docker-compose up -d

# Setup database with enterprise schema
docker-compose exec app python -m scripts.setup_database

# Load sample enterprise data
docker-compose exec app python -m scripts.load_sample_data
```

### 2. Manual Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Setup PostgreSQL with enterprise extensions
createdb fraiseql_blog_enterprise
psql fraiseql_blog_enterprise -f infrastructure/database/migrations/001_initial_schema.sql

# Setup Redis for caching (optional but recommended)
redis-server

# Run application
python app.py
```

### 3. Access Points

- **GraphQL API**: http://localhost:8000/graphql
- **GraphQL Playground**: http://localhost:8000/graphql (dev only)
- **Admin Interface**: http://localhost:8000/admin
- **Metrics**: http://localhost:8000/metrics
- **Health Check**: http://localhost:8000/health

## 📊 Enterprise Database Schema

### Multi-Tenant Foundation

```sql
-- Organizations (tenant isolation)
CREATE TABLE tb_organization (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    subscription_tier TEXT NOT NULL DEFAULT 'basic',
    settings JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Audit fields
    created_by UUID,
    updated_by UUID,
    version INTEGER DEFAULT 1
);

-- Row Level Security for multi-tenancy
ALTER TABLE tb_organization ENABLE ROW LEVEL SECURITY;
```

### Advanced User Management

```sql
-- Users with enterprise features
CREATE TABLE tb_user (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES tb_organization(id),
    username TEXT NOT NULL,
    email TEXT NOT NULL,
    password_hash TEXT,

    -- Enterprise auth
    sso_provider TEXT,
    sso_external_id TEXT,
    two_factor_enabled BOOLEAN DEFAULT FALSE,
    two_factor_secret TEXT,

    -- Role-based access
    role TEXT NOT NULL DEFAULT 'user',
    permissions JSONB DEFAULT '[]'::jsonb,

    -- Profile and preferences
    profile_data JSONB DEFAULT '{}'::jsonb,
    preferences JSONB DEFAULT '{}'::jsonb,

    -- Status and metadata
    status TEXT NOT NULL DEFAULT 'active',
    last_login_at TIMESTAMPTZ,
    email_verified_at TIMESTAMPTZ,

    -- Audit trail
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID,
    updated_by UUID,
    version INTEGER DEFAULT 1,

    -- Constraints
    UNIQUE (organization_id, username),
    UNIQUE (organization_id, email)
);
```

### Content Management

```sql
-- Posts with enterprise features
CREATE TABLE tb_post (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES tb_organization(id),

    -- Content
    title TEXT NOT NULL,
    slug TEXT NOT NULL,
    content TEXT NOT NULL,
    excerpt TEXT,

    -- Authoring
    author_id UUID NOT NULL REFERENCES tb_user(id),
    editor_ids UUID[] DEFAULT '{}',

    -- Publishing workflow
    status TEXT NOT NULL DEFAULT 'draft',
    scheduled_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,

    -- SEO and metadata
    seo_title TEXT,
    seo_description TEXT,
    seo_keywords TEXT[],
    featured_image_url TEXT,
    custom_fields JSONB DEFAULT '{}'::jsonb,

    -- Analytics
    view_count INTEGER DEFAULT 0,
    like_count INTEGER DEFAULT 0,
    share_count INTEGER DEFAULT 0,

    -- Workflow and approval
    approval_status TEXT DEFAULT 'pending',
    approved_by UUID REFERENCES tb_user(id),
    approved_at TIMESTAMPTZ,
    rejection_reason TEXT,

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID,
    updated_by UUID,
    version INTEGER DEFAULT 1,

    UNIQUE (organization_id, slug)
);
```

### Event Sourcing

```sql
-- Domain events for audit trail
CREATE TABLE tb_domain_event (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES tb_organization(id),

    -- Event identification
    aggregate_type TEXT NOT NULL,
    aggregate_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    event_version INTEGER NOT NULL,

    -- Event data
    event_data JSONB NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,

    -- Context
    user_id UUID REFERENCES tb_user(id),
    correlation_id UUID,
    causation_id UUID,

    -- Timing
    occurred_at TIMESTAMPTZ DEFAULT NOW(),

    -- Ensure event ordering
    sequence_number BIGSERIAL,

    -- Indexes for performance
    INDEX (organization_id, aggregate_type, aggregate_id),
    INDEX (organization_id, event_type, occurred_at),
    INDEX (correlation_id)
);
```

## 🏢 Enterprise Features

### Multi-Tenancy

```python
# Automatic tenant isolation
@fraiseql.query
async def posts(info: GraphQLResolveInfo) -> list[Post]:
    db = info.context["db"]
    org_id = info.context["organization_id"]

    # All queries automatically filtered by organization
    return await db.find("posts", organization_id=org_id)

# Tenant-aware caching
@fraiseql.field
@cache_per_tenant(ttl=300)
async def popular_posts(self, info: GraphQLResolveInfo) -> list[Post]:
    # Cached per organization
    pass
```

### Role-Based Access Control

```python
# Declarative permissions
from fraiseql.auth import requires_permission

@fraiseql.mutation
@requires_permission("content.create")
async def create_post(
    info: GraphQLResolveInfo, input: CreatePostInput
) -> CreatePostSuccess | CreatePostError:
    # Only users with content.create permission can execute
    ...

# Field-level authorization
@fraiseql.field
@authorize_field("admin", "content_manager")
async def draft_posts(self, info: GraphQLResolveInfo) -> list[Post]:
    # Only admins and content managers can see drafts
    pass
```

### Domain Events

```python
# Event publishing
class Post(DomainAggregate):
    def publish(self):
        self.status = PostStatus.PUBLISHED
        self.published_at = datetime.utcnow()

        # Emit domain event
        self.emit_event(PostPublishedEvent(
            post_id=self.id,
            title=self.title,
            author_id=self.author_id,
            published_at=self.published_at
        ))

# Event handlers
@event_handler(PostPublishedEvent)
async def send_notification(event: PostPublishedEvent):
    # Send notifications to subscribers
    pass

@event_handler(PostPublishedEvent)
async def update_analytics(event: PostPublishedEvent):
    # Update analytics dashboard
    pass
```

### Advanced Caching

```python
# Multi-layer caching strategy
@fraiseql.query
@cache_strategy(
    redis_ttl=300,           # Redis cache for 5 minutes
    memory_ttl=60,           # In-memory cache for 1 minute
    tags=["posts", "content"] # Cache invalidation tags
)
async def trending_posts(info: GraphQLResolveInfo) -> list[Post]:
    # Expensive query cached at multiple layers
    pass

# Cache invalidation on mutations
@fraiseql.mutation
@invalidate_cache_tags("posts", "content")
class UpdatePost:
    pass
```

### Performance Monitoring

```python
# Query performance tracking
@fraiseql.query
@track_performance("posts_query")
async def posts(info: GraphQLResolveInfo) -> list[Post]:
    # Automatically tracked performance metrics
    pass

# Custom metrics
@metrics.histogram("post_creation_duration")
async def create_post():
    # Custom business metrics
    pass
```

## 🧪 Enterprise Testing

### Test Categories

```python
# Unit tests with domain models
class TestPostAggregate:
    def test_post_publishing_workflow(self):
        post = Post.create("Title", "Content")
        post.submit_for_approval()
        post.approve(approver_id="admin")
        post.publish()

        # Verify domain events
        events = post.get_uncommitted_events()
        assert any(isinstance(e, PostPublishedEvent) for e in events)

# Integration tests with database
class TestPostRepository:
    async def test_find_by_organization(self, db_session):
        repo = PostRepository(db_session)
        posts = await repo.find_by_organization(org_id)

        assert all(p.organization_id == org_id for p in posts)

# End-to-end tests
class TestBlogWorkflow:
    async def test_complete_publishing_workflow(self, graphql_client):
        # Create -> Submit -> Approve -> Publish -> Notify
        pass
```

### Load Testing

```python
# Performance benchmarks
@pytest.mark.benchmark
async def test_posts_query_performance(benchmark, graphql_client):
    query = "query { posts(first: 100) { id title } }"

    result = await benchmark(graphql_client.execute, query)

    # Should handle 100 posts in < 50ms
    assert benchmark.stats["mean"] < 0.05
```

## 🔐 Enterprise Security

### Authentication Options

```python
# Multiple auth providers
AUTH_PROVIDERS = {
    "saml": SAMLProvider(),
    "oauth2": OAuth2Provider(),
    "ldap": LDAPProvider(),
    "native": NativeProvider()
}

# JWT with custom claims
async def create_jwt_token(user: User) -> str:
    claims = {
        "sub": str(user.id),
        "org": str(user.organization_id),
        "role": user.role,
        "permissions": user.permissions,
        "tenant": user.organization.slug
    }
    return encode_jwt(claims)
```

### Data Protection

```sql
-- Encryption at rest
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Encrypted sensitive fields
ALTER TABLE tb_user ADD COLUMN encrypted_pii BYTEA;

-- ❌ AVOID: Business Logic Triggers (Implicit, AI-hostile)
-- CREATE TRIGGER audit_changes
--     AFTER INSERT OR UPDATE OR DELETE ON tb_post
--     FOR EACH ROW EXECUTE FUNCTION audit_table_changes();

-- ✅ FRAISEQL'S TWO-LAYER PATTERN (Explicit + Infrastructure)

-- Layer 1: Explicit Application Code (AI-Visible)
-- Mutation functions call log_and_return_mutation() explicitly
CREATE FUNCTION create_post_with_audit(
    p_tenant_id UUID,
    p_user_id UUID,
    p_title TEXT,
    p_content TEXT
) RETURNS TABLE(
    entity_id UUID,
    entity_type TEXT,
    operation_type TEXT,
    success BOOLEAN
) AS $$
DECLARE
    v_post_id UUID;
BEGIN
    -- Business logic
    INSERT INTO tb_post (title, content, author_id, tenant_id)
    VALUES (p_title, p_content, p_user_id, p_tenant_id)
    RETURNING id INTO v_post_id;

    -- Explicit audit logging (AI can see this!)
    RETURN QUERY SELECT * FROM log_and_return_mutation(
        p_tenant_id := p_tenant_id,
        p_user_id := p_user_id,
        p_entity_type := 'post',
        p_entity_id := v_post_id,
        p_operation_type := 'INSERT',
        p_operation_subtype := 'new',
        p_changed_fields := ARRAY['title', 'content'],
        p_message := 'Post created',
        p_old_data := NULL,
        p_new_data := (SELECT row_to_json(p) FROM tb_post p WHERE id = v_post_id),
        p_metadata := jsonb_build_object('client', 'web')
    );
END;
$$ LANGUAGE plpgsql;

-- Layer 2: Infrastructure Trigger (Tamper-Proof Crypto Chain)
-- ONLY on audit_events table, ONLY for cryptographic integrity
CREATE TRIGGER populate_crypto_trigger
    BEFORE INSERT ON audit_events
    FOR EACH ROW EXECUTE FUNCTION populate_crypto_fields();

-- Why this pattern works:
-- ✅ Audit logging is explicit and visible to AI
-- ✅ CDC data (changed_fields, old/new data) is explicit
-- ✅ Crypto integrity is infrastructure-level (tamper-proof)
-- ✅ Testable and traceable code paths
-- ✅ See docs/database/avoid-triggers.md for details
```

## 📈 Monitoring and Observability

### Metrics Collection

```python
# Business metrics
METRICS = {
    "posts_created_total": Counter("posts_created_total"),
    "user_sessions_active": Gauge("user_sessions_active"),
    "query_duration": Histogram("query_duration_seconds"),
    "cache_hit_rate": Gauge("cache_hit_rate")
}

# Health checks
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "database": await check_database(),
        "cache": await check_redis(),
        "version": __version__
    }
```

### Distributed Tracing

```python
# OpenTelemetry integration
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

@tracer.start_as_current_span("create_post")
async def create_post(data: CreatePostData):
    span = trace.get_current_span()
    span.set_attribute("post.title", data.title)
    span.set_attribute("user.id", str(data.author_id))

    # Business logic with tracing
    pass
```

## 🚀 Deployment

### Production Configuration

```yaml
# docker-compose.prod.yml
version: '3.8'
services:
  app:
    image: blog-enterprise:latest
    environment:
      - ENV=production
      - DATABASE_URL=postgresql://...
      - REDIS_URL=redis://...
      - JWT_SECRET=...
    deploy:
      replicas: 3
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 256M

  db:
    image: postgres:16
    environment:
      POSTGRES_DB: blog_enterprise_prod
    volumes:
      - postgres_data:/var/lib/postgresql/data
    deploy:
      resources:
        limits:
          memory: 2G
```

### Kubernetes Deployment

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: blog-enterprise
spec:
  replicas: 3
  selector:
    matchLabels:
      app: blog-enterprise
  template:
    spec:
      containers:
      - name: app
        image: blog-enterprise:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: blog-secrets
              key: database-url
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
```

## 📚 Advanced Patterns Demonstrated

1. **Domain-Driven Design**
   - Bounded contexts and aggregates
   - Domain events and event handlers
   - Rich domain models with business logic

2. **CQRS and Event Sourcing**
   - Separated command and query models
   - Event store for complete audit trail
   - Eventual consistency patterns

3. **Multi-Tenancy**
   - Organization-based data isolation
   - Tenant-aware caching and queries
   - Scalable tenant management

4. **Enterprise Security**
   - SSO integration (SAML, OAuth2)
   - Role-based access control
   - Field-level authorization

5. **Performance Optimization**
   - Multi-layer caching strategy
   - Query optimization and indexing
   - Connection pooling and batching

6. **Observability**
   - Structured logging and metrics
   - Distributed tracing
   - Health checks and monitoring

## 🔍 Key Differences from Simple Blog

| Feature | Blog Simple | Blog Enterprise |
|---------|-------------|-----------------|
| **Architecture** | Single file, basic structure | DDD with bounded contexts |
| **Database** | Simple tables | Complex schema with audit |
| **Authentication** | Basic user roles | SSO, 2FA, RBAC |
| **Tenancy** | Single tenant | Multi-tenant with isolation |
| **Caching** | None | Multi-layer with Redis |
| **Events** | None | Domain events + handlers |
| **Testing** | Basic integration | Unit + Integration + E2E |
| **Deployment** | Docker only | Docker + Kubernetes |
| **Monitoring** | Health check only | Full observability stack |

---

**This enterprise blog demonstrates FraiseQL's power for building complex, scalable GraphQL APIs that meet enterprise requirements for security, performance, and maintainability.**

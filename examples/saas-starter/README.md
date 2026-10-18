# SaaS Starter Template

Production-ready multi-tenant SaaS application starter built with FraiseQL. Get from zero to MVP in hours, not weeks.

## What This Template Provides

A **complete, production-ready SaaS foundation** with:

- ✅ Multi-tenant architecture with PostgreSQL Row-Level Security (RLS)
- ✅ User management with JWT authentication
- ✅ Organization/workspace management
- ✅ Subscription & billing integration (Stripe-ready)
- ✅ Role-based access control per organization
- ✅ Team invitations and member management
- ✅ Usage tracking and analytics
- ✅ Audit logs and activity tracking
- ✅ API rate limiting per tenant
- ✅ FastAPI integration with GraphQL

## Use Cases

This starter is perfect for:

- B2B SaaS applications
- Team collaboration tools
- Project management platforms
- Analytics dashboards
- CRM/ERP systems
- Any multi-tenant application

## Architecture

### Multi-Tenancy Pattern

Uses the **shared database, separate schemas** approach with Row-Level Security:

```
┌─────────────────────────────────────────────┐
│ Application Layer                            │
│ ┌─────────┐  ┌─────────┐  ┌─────────┐      │
│ │ Org A   │  │ Org B   │  │ Org C   │      │
│ │ Users   │  │ Users   │  │ Users   │      │
│ └────┬────┘  └────┬────┘  └────┬────┘      │
└──────┼───────────┼─────────────┼───────────┘
       │           │             │
┌──────▼───────────▼─────────────▼───────────┐
│ PostgreSQL with Row-Level Security          │
│ ┌─────────────────────────────────────────┐ │
│ │ Tenant-Isolated Data                    │ │
│ │ WHERE organization_id = current_tenant  │ │
│ └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

### Key Features

#### 1. Automatic Tenant Isolation

All queries automatically filter by `organization_id`:

```python
@fraiseql.query
async def projects(info: Info, limit: int = 50) -> list[Project]:
    """Get projects for current organization."""
    # Tenant ID automatically injected from JWT
    tenant_id = info.context["tenant_id"]

    return await info.context.repo.find(
        "projects_view",
        where={"organization_id": tenant_id},
        limit=limit
    )
```

#### 2. PostgreSQL Row-Level Security

Database-level tenant isolation:

```sql
-- Enable RLS on projects table
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see their organization's projects
CREATE POLICY projects_tenant_isolation ON projects
    FOR ALL
    TO authenticated_user
    USING (organization_id = current_setting('app.current_tenant')::UUID);
```

#### 3. Subscription & Billing

Stripe-ready billing integration:

```graphql
mutation UpgradeSubscription($plan: String!) {
  upgradeSubscription(planId: $plan) {
    ... on SubscriptionSuccess {
      subscription {
        id
        plan
        status
        currentPeriodEnd
        features
      }
      checkoutUrl
    }
    ... on SubscriptionError {
      message
      code
    }
  }
}
```

#### 4. Team Management

Invite users and manage roles:

```graphql
mutation InviteTeamMember($email: String!, $role: String!) {
  inviteTeamMember(email: $email, role: $role) {
    ... on InviteSuccess {
      invitation {
        id
        email
        role
        expiresAt
      }
      inviteUrl
    }
    ... on InviteError {
      message
      code
    }
  }
}
```

## Setup

### 1. Install Dependencies

```bash
cd examples/saas-starter
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Database
DATABASE_URL=postgresql://localhost/saas_starter

# JWT Authentication
JWT_SECRET=your-secret-key-here
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# Stripe (optional)
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Email (optional)
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=your-sendgrid-api-key
FROM_EMAIL=noreply@yourapp.com

# Application
FRONTEND_URL=http://localhost:3000
```

### 3. Setup Database

```bash
# Create database
createdb saas_starter

# Run migrations
psql saas_starter < schema.sql

# Optional: Load sample data
psql saas_starter < seed_data.sql
```

### 4. Run the Application

```bash
python main.py
```

The API will be available at:

- **GraphQL API:** http://localhost:8000/graphql
- **GraphQL Playground:** http://localhost:8000/graphql
- **API Documentation:** http://localhost:8000/docs

## Core Features

### Authentication & Registration

#### Register New Organization

```graphql
mutation Register($input: RegisterInput!) {
  register(input: $input) {
    ... on AuthSuccess {
      user {
        id
        email
        name
      }
      organization {
        id
        name
      }
      token
    }
    ... on AuthError {
      message
      code
    }
  }
}
```

Variables:

```json
{
  "input": {
    "email": "founder@startup.com",
    "password": "SecurePassword123!",
    "name": "Jane Founder",
    "organizationName": "Startup Inc"
  }
}
```

#### Login

```graphql
mutation Login($email: String!, $password: String!) {
  login(email: $email, password: $password) {
    ... on AuthSuccess {
      token
      user { id email name }
      organization { id name plan }
    }
    ... on AuthError {
      message
    }
  }
}
```

### Organization Management

#### Get Current Organization

```graphql
query CurrentOrganization {
  currentOrganization {
    id
    name
    plan
    subscriptionStatus
    memberCount
    createdAt

    subscription {
      plan
      status
      currentPeriodEnd
      features
    }

    usage {
      projects
      storage
      apiCalls
      seats
    }
  }
}
```

#### Update Organization Settings

```graphql
mutation UpdateOrganization($input: OrganizationUpdateInput!) {
  updateOrganization(input: $input) {
    id
    name
    settings
    updatedAt
  }
}
```

### Team Management

#### List Team Members

```graphql
query TeamMembers {
  teamMembers {
    id
    name
    email
    role
    status
    lastActive
    invitedAt
    joinedAt
  }
}
```

#### Invite Team Member

```graphql
mutation InviteTeamMember($email: String!, $role: String!) {
  inviteTeamMember(email: $email, role: $role) {
    ... on InviteSuccess {
      invitation {
        id
        email
        role
        token
        expiresAt
      }
      inviteUrl
    }
  }
}
```

#### Accept Invitation

```graphql
mutation AcceptInvitation($token: String!, $password: String!, $name: String!) {
  acceptInvitation(token: $token, password: $password, name: $name) {
    ... on AuthSuccess {
      token
      user { id email name }
    }
  }
}
```

#### Update Member Role

```graphql
mutation UpdateMemberRole($userId: UUID!, $newRole: String!) {
  updateMemberRole(userId: $userId, role: $newRole) {
    id
    role
    updatedAt
  }
}
```

#### Remove Team Member

```graphql
mutation RemoveTeamMember($userId: UUID!) {
  removeTeamMember(userId: $userId) {
    success
    message
  }
}
```

### Subscription & Billing

#### Get Available Plans

```graphql
query AvailablePlans {
  subscriptionPlans {
    id
    name
    price
    interval
    features
    limits {
      projects
      storage
      apiCalls
      seats
    }
  }
}
```

#### Upgrade Subscription

```graphql
mutation UpgradeSubscription($planId: String!) {
  upgradeSubscription(planId: $planId) {
    ... on SubscriptionSuccess {
      subscription {
        id
        plan
        status
        currentPeriodEnd
      }
      checkoutUrl  # Stripe checkout URL
    }
    ... on SubscriptionError {
      message
      code
    }
  }
}
```

#### Cancel Subscription

```graphql
mutation CancelSubscription($reason: String) {
  cancelSubscription(reason: $reason) {
    subscription {
      status
      cancelsAt
    }
  }
}
```

#### View Usage & Billing

```graphql
query BillingInfo {
  currentOrganization {
    usage {
      projects
      storage
      apiCalls
      seats
      period {
        start
        end
      }
    }

    subscription {
      plan
      status
      amount
      currency
      currentPeriodEnd
      cancelAtPeriodEnd
    }

    invoices(limit: 12) {
      id
      amount
      currency
      status
      paidAt
      invoiceUrl
    }
  }
}
```

### Usage Tracking

#### Track Feature Usage

```python
from models import track_usage

@fraiseql.query
async def projects(info: Info) -> list[Project]:
    """Get projects - automatically tracks API usage."""
    # Track API call
    await track_usage(
        info.context["organization_id"],
        usage_type="api_call",
        amount=1
    )

    return await info.context.repo.find("projects_view", ...)
```

#### Check Usage Limits

```graphql
query CheckLimits {
  currentOrganization {
    usage {
      projects
      storage
      apiCalls
      seats
    }
    limits {
      projects
      storage
      apiCalls
      seats
    }
    limitsExceeded {
      type
      current
      limit
    }
  }
}
```

### Activity Logs

#### View Organization Activity

```graphql
query ActivityLog($limit: Int = 50) {
  activityLog(limit: $limit) {
    id
    actor { name email }
    action
    resource
    resourceId
    details
    ipAddress
    userAgent
    createdAt
  }
}
```

## Security Features

### 1. Row-Level Security (RLS)

All tables use PostgreSQL RLS for database-level isolation:

```sql
-- Projects can only be accessed by their organization
CREATE POLICY projects_isolation ON projects
    USING (organization_id = current_setting('app.current_tenant')::UUID);

-- Users can only see members of their organization
CREATE POLICY users_isolation ON users
    USING (organization_id = current_setting('app.current_tenant')::UUID);
```

### 2. Role-Based Access Control

```python
from fraiseql.auth import requires_role

@fraiseql.mutation
@requires_role("owner", "admin")
async def delete_project(info: Info, project_id: UUID):
    """Only owners and admins can delete projects."""
    return await info.context.repo.delete("projects", project_id)
```

**Built-in roles:**

- `owner` - Full access, billing, team management
- `admin` - Full access except billing
- `member` - Read/write access to resources
- `readonly` - Read-only access

### 3. JWT Authentication

Secure token-based authentication:

```python
# Token payload includes tenant context
{
    "user_id": "...",
    "organization_id": "...",
    "role": "admin",
    "exp": 1234567890
}
```

### 4. API Rate Limiting

Per-tenant rate limiting:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=lambda: context["organization_id"])

@app.route("/graphql")
@limiter.limit("1000/hour")  # Per organization
async def graphql_endpoint():
    ...
```

## Multi-Tenant Best Practices

### 1. Always Filter by Tenant

```python
# ✅ Good: Explicit tenant filter
projects = await repo.find(
    "projects",
    where={"organization_id": tenant_id}
)

# ❌ Bad: Missing tenant filter
projects = await repo.find("projects")  # Leaks data!
```

### 2. Use Database Views

```sql
-- Tenant-aware view
CREATE VIEW projects_view AS
SELECT * FROM projects
WHERE organization_id = current_setting('app.current_tenant')::UUID;
```

### 3. Validate Tenant in Mutations

```python
@fraiseql.mutation
async def update_project(info: Info, project_id: UUID, ...):
    # Verify project belongs to tenant
    project = await repo.find_one("projects", project_id)
    if project["organization_id"] != info.context["tenant_id"]:
        raise PermissionDeniedError("Access denied")

    return await repo.update("projects", project_id, ...)
```

### 4. Set Tenant Context on Every Request

```python
@app.middleware("http")
async def set_tenant_context(request, call_next):
    # Extract from JWT
    token = request.headers.get("Authorization")
    payload = decode_jwt(token)

    # Set PostgreSQL session variable
    await db.execute(
        "SET LOCAL app.current_tenant = %s",
        [payload["organization_id"]]
    )

    return await call_next(request)
```

## Billing Integration

### Stripe Integration

```python
import stripe

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

@fraiseql.mutation
async def create_checkout_session(info: Info, plan_id: str):
    """Create Stripe checkout session."""
    org = await get_current_organization(info)

    session = stripe.checkout.Session.create(
        customer=org["stripe_customer_id"],
        payment_method_types=["card"],
        line_items=[{
            "price": plan_id,
            "quantity": 1,
        }],
        mode="subscription",
        success_url=f"{FRONTEND_URL}/billing/success",
        cancel_url=f"{FRONTEND_URL}/billing",
        client_reference_id=str(org["id"]),
    )

    return {"checkoutUrl": session.url}
```

### Webhook Handler

```python
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhooks."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    event = stripe.Webhook.construct_event(
        payload, sig_header, STRIPE_WEBHOOK_SECRET
    )

    if event["type"] == "customer.subscription.updated":
        subscription = event["data"]["object"]
        await update_subscription_status(subscription)

    elif event["type"] == "invoice.payment_succeeded":
        invoice = event["data"]["object"]
        await record_payment(invoice)

    return {"status": "success"}
```

## Deployment

### Environment Variables

```bash
# Required
DATABASE_URL=postgresql://user:pass@host:5432/db
JWT_SECRET=your-secret-key

# Optional
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
SENTRY_DSN=https://...
REDIS_URL=redis://localhost:6379
```

### Docker Deployment

```dockerfile
FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Database Migrations

```bash
# Using Alembic
alembic init migrations
alembic revision -m "Initial schema"
alembic upgrade head
```

## Frontend Integration

### React + Apollo Client

```typescript
import { ApolloClient, InMemoryCache, createHttpLink } from '@apollo/client';
import { setContext } from '@apollo/client/link/context';

const httpLink = createHttpLink({
  uri: 'http://localhost:8000/graphql',
});

const authLink = setContext((_, { headers }) => {
  const token = localStorage.getItem('token');
  return {
    headers: {
      ...headers,
      authorization: token ? `Bearer ${token}` : "",
    }
  }
});

const client = new ApolloClient({
  link: authLink.concat(httpLink),
  cache: new InMemoryCache()
});
```

### Next.js Example

```typescript
// pages/projects.tsx
import { useQuery, gql } from '@apollo/client';

const GET_PROJECTS = gql`
  query GetProjects {
    projects {
      id
      name
      description
      createdAt
    }
  }
`;

export default function ProjectsPage() {
  const { data, loading } = useQuery(GET_PROJECTS);

  if (loading) return <Loading />;

  return (
    <div>
      {data.projects.map(project => (
        <ProjectCard key={project.id} project={project} />
      ))}
    </div>
  );
}
```

## Testing

### Unit Tests

```python
import pytest
from main import app

@pytest.mark.asyncio
async def test_tenant_isolation():
    """Verify users can only see their org's data."""
    # Create two orgs
    org_a = await create_organization("Org A")
    org_b = await create_organization("Org B")

    # Create project for Org A
    project = await create_project(org_a["id"], "Project A")

    # Query as Org B
    context = {"tenant_id": org_b["id"]}
    result = await graphql_query(
        "query { projects { id } }",
        context=context
    )

    # Should not see Org A's project
    assert len(result["projects"]) == 0
```

### Integration Tests

```bash
pytest tests/integration/ -v
```

## Performance Optimization

### 1. Database Indexes

```sql
-- Index on tenant + frequently queried fields
CREATE INDEX idx_projects_org_created
    ON projects(organization_id, created_at DESC);

-- Index for cross-tenant queries (admin)
CREATE INDEX idx_subscriptions_status
    ON subscriptions(status) WHERE status = 'active';
```

### 2. Query Optimization

```python
# Use DataLoader for N+1 prevention
from fraiseql import dataloader_field

@fraiseql.type
class Project:
    id: UUID
    name: str

    @dataloader_field
    async def owner(self, info: Info) -> User:
        # Batched loading
        return await info.context.loaders.users.load(self.owner_id)
```

### 3. Caching

```python
from aiocache import cached

@cached(ttl=300)  # 5 minutes
@fraiseql.query
async def subscription_plans() -> list[SubscriptionPlan]:
    """Cache rarely-changing data."""
    return await load_subscription_plans()
```

## Related Examples

- [`../fastapi/`](../fastapi/README.md) - FastAPI integration patterns
- [`../enterprise_patterns/cqrs/`](../enterprise_patterns/cqrs/README.md) - CQRS architecture

## Production Checklist

- [ ] Set strong `JWT_SECRET`
- [ ] Enable HTTPS/TLS in production
- [ ] Configure proper CORS origins
- [ ] Set up monitoring (Sentry, DataDog, etc.)
- [ ] Configure backup strategy for PostgreSQL
- [ ] Set up log aggregation
- [ ] Implement rate limiting
- [ ] Configure email service (SendGrid, AWS SES)
- [ ] Set up Stripe webhook endpoint
- [ ] Test disaster recovery procedures
- [ ] Document API for frontend team
- [ ] Set up CI/CD pipeline

## Next Steps

1. **Customize for your domain** - Adapt models to your business
2. **Add your features** - Build on this foundation
3. **Integrate Stripe** - Set up billing and subscriptions
4. **Build frontend** - Connect with React, Vue, or Next.js
5. **Deploy to production** - Use Docker, Kubernetes, or your favorite PaaS

---

**This template provides everything you need to build a production-ready multi-tenant SaaS application with FraiseQL. Ship your MVP in days, not months!** 🚀

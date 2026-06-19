<!-- Skip to main content -->
---

title: Common Patterns - Real-World Solutions
description: - GraphQL fundamentals (types, fields, queries, mutations)
keywords: ["workflow", "debugging", "implementation", "best-practices", "deployment", "saas", "realtime", "ecommerce"]
tags: ["documentation", "reference"]
---

# Common Patterns - Real-World Solutions

**Status:** ✅ Production Ready
**Audience:** Developers, Architects
**Reading Time:** 20-30 minutes
**Last Updated:** 2026-06-19

## Prerequisites

**Required Knowledge:**

- GraphQL fundamentals (types, fields, queries, mutations)
- FraiseQL schema definition and configuration (see [getting-started](../getting-started/quickstart.md))
- Authentication and authorization concepts
- Multi-tenancy and data isolation patterns (PostgreSQL Row-Level Security)
- Caching strategies and trade-offs
- Pagination and filtering techniques
- Error handling best practices
- PostgreSQL views, functions, and the `tb_`/`v_`/`fn_` conventions

**Required Software:**

- FraiseQL v1 (latest)
- Python 3.13+
- PostgreSQL 14+
- curl or Postman (for API testing)
- Git (optional, for version control)

**Required Infrastructure:**

- A FastAPI app built with `create_fraiseql_app(...)` and served by `uvicorn`
- PostgreSQL database
- Example data loaded in database (for testing patterns)

**Optional but Recommended:**

- Test database with sample data
- GraphQL IDE (the built-in playground when `production=False`, Apollo Sandbox, Postman)
- API monitoring tools
- Logging and debugging tools

**Time Estimate per Pattern:** 20-60 minutes depending on complexity

---

## Pattern 1: User Authentication

### Problem

How do I add user authentication to my GraphQL API?

### Solution

Model the write side as a PostgreSQL function (`fn_register_user`) called from a
mutation, the read side as a `v_user` view, and verify the request's JWT in the
FastAPI context getter. Reads stay in views; writes (and password hashing) live in
PostgreSQL functions.

### Schema Definition (Python)

```python
import fraiseql
from fraiseql.types import ID, EmailAddress, DateTime


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    email: EmailAddress
    name: str
    created_at: DateTime


@fraiseql.success
class AuthSuccess:
    token: str
    user: User


@fraiseql.error
class AuthError:
    message: str
    code: str = "AUTH_ERROR"


@fraiseql.input
class RegisterInput:
    email: EmailAddress
    password: str
    name: str


@fraiseql.input
class LoginInput:
    email: EmailAddress
    password: str
```

### Implementation

The write logic — email validation, uniqueness, password hashing — belongs in the
PostgreSQL function `fn_register_user`. The mutation resolver simply calls it and maps
the JSONB result to the success or error union member.

```python
@fraiseql.query
async def me(info) -> User | None:
    """Return the authenticated user from the request context."""
    user_id = info.context.get("user_id")
    if user_id is None:
        return None
    db = info.context["db"]
    return await db.find_one("v_user", id=user_id)


@fraiseql.mutation
async def register(info, input: RegisterInput) -> AuthSuccess | AuthError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_register_user",
        {"email": input.email, "password": input.password, "name": input.name},
    )
    if not result.get("success"):
        return AuthError(message=result.get("message", "Registration failed"))
    return AuthSuccess(token=result["token"], user=User(**result["user"]))


@fraiseql.mutation
async def login(info, input: LoginInput) -> AuthSuccess | AuthError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_login", {"email": input.email, "password": input.password}
    )
    if not result.get("success"):
        return AuthError(message="Invalid credentials", code="INVALID_CREDENTIALS")
    return AuthSuccess(token=result["token"], user=User(**result["user"]))
```

The PostgreSQL function hashes the password with `pgcrypto` and returns a JSONB
envelope:

```sql
CREATE OR REPLACE FUNCTION fn_register_user(payload jsonb)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
    v_id uuid;
BEGIN
    IF EXISTS (SELECT 1 FROM tb_user WHERE email = payload->>'email') THEN
        RETURN jsonb_build_object('success', false, 'message', 'Email already registered');
    END IF;

    INSERT INTO tb_user (id, email, password_hash, name)
    VALUES (
        gen_random_uuid(),
        payload->>'email',
        crypt(payload->>'password', gen_salt('bf', 12)),  -- bcrypt, cost 12
        payload->>'name'
    )
    RETURNING id INTO v_id;

    RETURN jsonb_build_object(
        'success', true,
        'token', '<issued by your auth layer>',
        'user', (SELECT data FROM v_user WHERE id = v_id)
    );
END;
$$;
```

JWT verification happens once, in the FastAPI context getter, and the decoded
`user_id` is placed on `info.context`:

```python
from fastapi import Request
from fraiseql.fastapi import create_fraiseql_app


async def get_context(request: Request) -> dict:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    user_id = verify_jwt(token) if token else None   # your JWT validation
    return {"user_id": user_id}


app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[User],
    queries=[me],
    mutations=[register, login],
    context_getter=get_context,
    production=False,
)
```

### Usage

```graphql
# Register
mutation {
  register(input: { email: "alice@example.com", password: "secure-password", name: "Alice" }) {
    ... on AuthSuccess {
      token
      user { id name email }
    }
    ... on AuthError { message code }
  }
}

# Login
mutation {
  login(input: { email: "alice@example.com", password: "secure-password" }) {
    ... on AuthSuccess { token user { id name email } }
    ... on AuthError { message }
  }
}

# Get current user (with Authorization header)
query {
  me { id name email }
}
```

### Trade-offs & Security

**JWT vs Sessions**:

- JWT: Stateless, scales horizontally, no server storage
- Sessions: Stateful, easier to revoke, more control

**FraiseQL recommends JWT** for simplicity and scalability.

**Security Considerations**:

- ✅ Hash passwords with `pgcrypto`'s bcrypt (cost 12+) inside the `fn_` function
- ✅ Use HTTPS only (TLS 1.3+)
- ✅ Store secret key in environment (not git)
- ✅ Set token expiration (24 hours recommended)
- ✅ Refresh tokens for long sessions
- ✅ Validate email format before storing (the `EmailAddress` scalar helps)

---

## Pattern 2: Pagination

### Problem

How do I handle large result sets without overwhelming the client or server?

### Solution

FraiseQL ships a Relay-style `Connection`/`Edge`/`PageInfo` generic, and the CQRS
repository's `find(...)` already accepts `limit`, `offset`, `order_by`, and `where`.
Build cursor-based pagination on top of a `v_user` view.

### Schema Definition (Python)

```python
import fraiseql
from fraiseql.types import ID

# Connection, Edge, and PageInfo are provided by FraiseQL.
from fraiseql import Connection


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: str
```

`Connection[User]` resolves to a connection type with `edges { node cursor }` and
`page_info { has_next_page has_previous_page start_cursor end_cursor }` — the standard
Relay shape, generated by FraiseQL's `Connection`, `Edge`, and `PageInfo` types.

### Implementation

The resolver decodes the incoming cursor to an offset, fetches one extra row to detect
a next page, and builds the connection. All data comes from the `v_user` view through
`db.find`.

```python
import base64


def _encode_cursor(offset: int) -> str:
    return base64.b64encode(str(offset).encode()).decode()


def _decode_cursor(cursor: str) -> int:
    return int(base64.b64decode(cursor.encode()).decode())


@fraiseql.query
async def users(info, first: int = 10, after: str | None = None) -> Connection[User]:
    db = info.context["db"]
    first = min(first, 100)            # cap page size
    offset = _decode_cursor(after) + 1 if after else 0

    rows = await db.find("v_user", order_by="created_at_desc", limit=first + 1, offset=offset)
    has_next_page = len(rows) > first
    rows = rows[:first]

    edges = [
        {"node": User(**row), "cursor": _encode_cursor(offset + idx)}
        for idx, row in enumerate(rows)
    ]
    return Connection.from_dict({
        "edges": edges,
        "page_info": {
            "has_next_page": has_next_page,
            "has_previous_page": offset > 0,
            "start_cursor": edges[0]["cursor"] if edges else None,
            "end_cursor": edges[-1]["cursor"] if edges else None,
        },
    })
```

### Usage

```graphql
query GetFirstPage {
  users(first: 10) {
    edges {
      node { id name }
      cursor
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}

query GetNextPage {
  users(first: 10, after: "MTA=") {
    edges {
      node { id name }
      cursor
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
```

### Performance Characteristics

| Scenario | Performance | Notes |
|----------|-------------|-------|
| First page (10 items) | ~5ms | Single database query against the view |
| Mid-range (offset 10k) | ~50ms | Index scan, not full table |
| Last page (offset 1M) | ~500ms | Index scan from end |

**Optimization**:

- ✅ Add a database index on the ordering column (e.g. `created_at`)
- ✅ Use offset-based cursors for small pages
- ✅ Consider keyset pagination (a `WHERE created_at < :cursor` in the view) for very large datasets

---

## Pattern 3: Filtering & Search

### Problem

How do I add search and filtering to my GraphQL API?

### Solution

Pass a `where` dictionary to `db.find`. FraiseQL's WHERE generator translates it into
parameterized SQL against the view's JSONB `data` column, supporting operators like
`eq`, `gte`, `lte`, `contains`, and `icontains`. For full-text search, query a `tsvector`
column built inside the view.

### Schema Definition (Python)

```python
import fraiseql
from fraiseql.types import ID, DateTime


@fraiseql.input
class UserFilter:
    name: str | None = None
    email: str | None = None
    created_after: DateTime | None = None
    created_before: DateTime | None = None


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: str
    created_at: DateTime
```

### Implementation

The resolver builds the `where` mapping from the filter input and delegates the SQL
generation to `db.find`. Parameters are always bound, never interpolated.

```python
@fraiseql.query
async def users(info, filter: UserFilter | None = None, search: str | None = None) -> list[User]:
    db = info.context["db"]
    where: dict = {}

    if filter is not None:
        if filter.name is not None:
            where["name"] = {"icontains": filter.name}
        if filter.email is not None:
            where["email"] = {"eq": filter.email}
        if filter.created_after is not None:
            where["created_at"] = {"gte": filter.created_after}
        if filter.created_before is not None:
            where.setdefault("created_at", {})["lte"] = filter.created_before

    if search is not None:
        # `search_text` is a tsvector exposed by the view; see the SQL below.
        where["search_text"] = {"matches": search}

    rows = await db.find("v_user", where=where, order_by="created_at_desc", limit=100)
    return [User(**row) for row in rows]
```

### Usage

```graphql
# Search by name
query {
  users(filter: { name: "alice" }) {
    id
    name
    email
  }
}

# Filter by date range
query {
  users(filter: {
    createdAfter: "2026-01-01T00:00:00Z"
    createdBefore: "2026-01-31T23:59:59Z"
  }) {
    id
    name
    createdAt
  }
}

# Combine filter and search
query {
  users(
    filter: { createdAfter: "2026-01-01T00:00:00Z" }
    search: "alice"
  ) {
    id
    name
    email
  }
}
```

### Full-Text Search Performance

Expose a `tsvector` inside the view and back it with a GIN index on the underlying table:

```sql
-- On the write table: precompute and index the search vector.
ALTER TABLE tb_user
    ADD COLUMN search_text tsvector
    GENERATED ALWAYS AS (to_tsvector('english', name || ' ' || email)) STORED;

CREATE INDEX idx_user_search ON tb_user USING GIN (search_text);

-- In v_user, surface it in the data JSONB so the WHERE generator can target it.
```

With index:

- Unfiltered search: ~100ms
- Filtered search: ~20ms
- Multiple filters: ~50ms

---

## Pattern 4: Real-Time Updates (Subscriptions)

### Problem

How do I add WebSocket subscriptions for real-time updates?

### Solution

Decorate an **async generator** with `@fraiseql.subscription`. FraiseQL serves the
GraphQL-over-WebSocket transport and streams every value you `yield`. The event source
is yours — most commonly PostgreSQL `LISTEN/NOTIFY`, but it can be polling or any other
async stream.

### Schema Definition (Python)

```python
import fraiseql
from fraiseql.types import ID
from collections.abc import AsyncGenerator


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: str
```

### Implementation

The subscription resolver is an `async def` generator. Here it bridges PostgreSQL
`LISTEN/NOTIFY` to GraphQL: a `fn_`/trigger publishes on a channel, and the generator
yields each fresh `User`.

```python
@fraiseql.subscription
async def user_created(info) -> AsyncGenerator[User, None]:
    db = info.context["db"]
    async for payload in db.listen("user_created"):   # LISTEN on a NOTIFY channel
        user_id = payload["id"]
        user = await db.find_one("v_user", id=user_id)
        if user is not None:
            yield User(**user)


@fraiseql.subscription
async def user_updated(info, user_id: ID) -> AsyncGenerator[User, None]:
    db = info.context["db"]
    async for payload in db.listen(f"user_updated:{user_id}"):
        user = await db.find_one("v_user", id=user_id)
        if user is not None:
            yield User(**user)
```

On the PostgreSQL side, a trigger on `tb_user` issues the `NOTIFY`:

```sql
CREATE OR REPLACE FUNCTION fn_notify_user_created()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_notify('user_created', jsonb_build_object('id', NEW.id)::text);
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_user_created
    AFTER INSERT ON tb_user
    FOR EACH ROW EXECUTE FUNCTION fn_notify_user_created();
```

### Usage

```graphql
# Subscribe to new users
subscription {
  userCreated {
    id
    name
    email
  }
}

# Subscribe to updates for a specific user
subscription {
  userUpdated(userId: "123") {
    id
    name
    email
  }
}
```

### Scaling Subscriptions

PostgreSQL `LISTEN/NOTIFY` fans out to every connected backend that issues `LISTEN`, so
running several FastAPI workers against the same database already distributes
subscription delivery — no separate message broker is required. For very high fan-out,
keep per-connection work light (a single `find_one` per event) and cap the number of
concurrent subscriptions per connection.

---

## Pattern 5: File Uploads

### Problem

How do I handle file uploads in a GraphQL API?

### Solution

FraiseQL exposes a `File` scalar. Accept the upload in a mutation, validate size and
MIME type in Python, push the bytes to object storage (e.g. S3), and persist the
resulting URL via a `fn_` function.

### Schema Definition (Python)

```python
import fraiseql
from fraiseql.types import ID, File


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    avatar_url: str | None


@fraiseql.success
class UploadSuccess:
    user: User


@fraiseql.error
class UploadError:
    message: str
    code: str = "UPLOAD_ERROR"
```

### Implementation

```python
MAX_AVATAR_BYTES = 5_000_000
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}


@fraiseql.mutation
async def upload_user_avatar(info, user_id: ID, file: File) -> UploadSuccess | UploadError:
    if len(file.content) > MAX_AVATAR_BYTES:
        return UploadError(message="File size exceeds 5MB limit")
    if file.mimetype not in ALLOWED_MIME:
        return UploadError(message="Only JPEG, PNG, or WebP allowed")

    s3 = info.context["s3"]
    url = await s3.put_object(
        key=f"avatars/{user_id}/{file.filename}",
        body=file.content,
        content_type=file.mimetype,
    )

    db = info.context["db"]
    result = await db.execute_function(
        "fn_set_user_avatar", {"user_id": str(user_id), "avatar_url": url}
    )
    if not result.get("success"):
        return UploadError(message=result.get("message", "Failed to update avatar"))
    return UploadSuccess(user=User(**result["user"]))
```

### Client Usage

```graphql
mutation UploadAvatar($userId: ID!, $file: File!) {
  uploadUserAvatar(userId: $userId, file: $file) {
    ... on UploadSuccess {
      user { id name avatarUrl }
    }
    ... on UploadError { message }
  }
}
```

JavaScript client (GraphQL multipart request spec):

```javascript
const input = document.querySelector('input[type="file"]');
const formData = new FormData();

formData.append('operations', JSON.stringify({
  query: `mutation UploadAvatar($userId: ID!, $file: File!) {
    uploadUserAvatar(userId: $userId, file: $file) { ... }
  }`,
  variables: { userId: '123', file: null }
}));

formData.append('map', JSON.stringify({
  0: ['variables.file']
}));

formData.append('0', input.files[0]);

fetch('/graphql', {
  method: 'POST',
  body: formData
});
```

---

## Pattern 6: Caching

### Problem

How do I cache query results to reduce database load?

### Solution

Use FraiseQL's PostgreSQL-backed result cache. Wrap the repository in a
`CachedRepository`, configure TTLs with `CacheConfig`, and let cascade rules invalidate
cached results when the underlying tables change.

### Schema Definition (Python)

```python
import fraiseql
from fraiseql.types import ID


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: str
```

### Implementation

`CachedRepository` sits in front of the CQRS repository. Cache keys are derived from the
view and arguments; `setup_auto_cascade_rules` registers invalidation so that writes to
`tb_user` evict the relevant cached entries automatically.

```python
from fraiseql.caching import (
    PostgresCache,
    ResultCache,
    CachedRepository,
    CacheConfig,
    setup_auto_cascade_rules,
)


def build_cached_repo(repo, pool):
    backend = PostgresCache(pool)
    result_cache = ResultCache(
        backend,
        CacheConfig(default_ttl=300),   # 5 minutes
    )
    cached = CachedRepository(repo, result_cache)
    setup_auto_cascade_rules(result_cache)  # invalidate on writes to tracked tables
    return cached


@fraiseql.query
async def user(info, id: ID) -> User | None:
    # info.context["db"] is the CachedRepository; cache lookup is transparent.
    db = info.context["db"]
    row = await db.find_one("v_user", id=id)
    return User(**row) if row else None
```

### Caching Strategy

**Layer 1: PostgreSQL result cache (`PostgresCache`)**

- Speed: a single indexed lookup
- Cost: a cache table in your database
- Best for: hot read queries shared across all app workers

**Layer 2: HTTP cache headers**

- Speed: browser/CDN cache
- Cost: cache-control discipline on responses
- Best for: public, slowly-changing data

Because the cache lives in PostgreSQL, every FastAPI worker sees the same cache and the
same cascade invalidation — no separate cache cluster to operate.

### Performance Impact

```text
Without cache:

- Query time: 50ms
- Database load: 100 queries/sec

With result cache (50% hit rate):

- Query time: 25ms (average)
- Database load: 50 queries/sec
- Reduction: 50%

With result cache (80% hit rate):

- Query time: 10ms (average)
- Database load: 20 queries/sec
- Reduction: 80%
```

---

## Troubleshooting

### "JWT token validation failing: 'Invalid token signature'"

**Cause:** Token signed with different key or issuer mismatch.

**Diagnosis:**

1. Check token issuer: `echo $JWT_ISSUER`
2. Verify public key: Compare with OAuth provider
3. Decode token: `jwt decode $token` (check `iss` claim)

**Solutions:**

- Verify `JWT_ISSUER` environment variable matches provider
- Ensure public key is current (providers rotate keys)
- Check token expiration: `jq '.exp' token.json`
- Regenerate token if expired

### "Pagination cursor returning empty or wrong records"

**Cause:** Cursor encoding/decoding mismatch or data ordering changed.

**Diagnosis:**

1. Decode cursor: `base64 -d cursor`
2. Verify sort order matches: `SELECT id FROM v_user ORDER BY created_at, id LIMIT 10;`
3. Check if records were deleted/reordered

**Solutions:**

- Ensure consistent sort order: `ORDER BY created_at DESC, id DESC`
- Don't change sort order mid-pagination
- Use a stable cursor (record ID + timestamp)
- Handle deleted records gracefully (skip and get next)

### "Full-text search not finding results"

**Cause:** Index not created or query format wrong.

**Diagnosis:**

1. Check if index exists: `SELECT * FROM pg_indexes WHERE tablename = 'tb_user';`
2. Test search manually: `SELECT id FROM tb_user WHERE search_text @@ to_tsquery('john');`
3. Verify column contains data: `SELECT COUNT(*) FROM tb_user WHERE name IS NOT NULL;`

**Solutions:**

- Create the GIN index: `CREATE INDEX idx_user_search ON tb_user USING GIN (search_text);`
- Use query syntax: `&` (AND), `|` (OR), `!` (NOT)
- Index must be functional for performance
- For stemming: Use a language-specific dictionary

### "Subscription WebSocket connection drops unexpectedly"

**Cause:** Connection timeout, server restart, or network issue.

**Diagnosis:**

1. Check server logs for connection drops
2. Verify network connection: `ping server`
3. Check WebSocket URL: `wss://...` for production, `ws://...` for local

**Solutions:**

- Implement reconnection logic in the client
- Increase connection timeout if needed
- Use persistent connections (TCP keepalive)
- For server restarts: graceful shutdown closes connections cleanly
- Monitor connection health: send heartbeats every 30 seconds

### "File upload fails: 'Multipart form data parsing error'"

**Cause:** Request format incorrect or file too large.

**Diagnosis:**

1. Check Content-Type header: should be `multipart/form-data`
2. Check file size: compare to your validation limit
3. Verify field name matches the schema

**Solutions:**

- Use the correct Content-Type: `multipart/form-data`
- Enforce a max file size in the mutation resolver (see Pattern 5)
- Ensure the file field name matches the GraphQL input
- For large files: implement chunked upload

### "Cache hit rate is low (<30%)"

**Cause:** Cache key too specific or cache table too small.

**Diagnosis:**

1. Inspect cache stats via `CacheStats`
2. Check cache table size: `SELECT pg_size_pretty(pg_total_relation_size('fraiseql_cache'));`
3. Analyze popular queries: which queries run most frequently?

**Solutions:**

- Raise the TTL in `CacheConfig` so results stay cached longer
- Simplify the cache key (avoid embedding volatile arguments)
- Pre-warm the cache: load frequently-accessed data at startup
- Confirm cascade rules aren't over-invalidating (check `setup_auto_cascade_rules` scope)

### "Real-time subscription updates have latency >2 seconds"

**Cause:** Slow `LISTEN/NOTIFY` round-trip or heavy per-event work.

**Diagnosis:**

1. Confirm the trigger fires: `SELECT pg_notify('user_created', '{}');` and watch the subscriber
2. Monitor network latency: `ping subscription_server`
3. Check the per-event query performance: `EXPLAIN ANALYZE SELECT data FROM v_user WHERE id = ...;`

**Solutions:**

- Keep the per-event resolver light (a single `find_one`)
- Index the view's `id` lookup
- Ensure the WebSocket connects directly to the server (not through a heavy proxy)
- Use batching: combine multiple changes into a single notification payload

### "Pattern implementation doesn't match example - authentication failing"

**Cause:** Environment setup missing or configuration incorrect.

**Diagnosis:**

1. Follow setup guide: [Authentication Setup](../integrations/authentication/README.md)
2. Check environment variables: `env | grep OAUTH`
3. Verify credentials in the OAuth provider console

**Solutions:**

- Ensure all prerequisites from the guide are met
- Confirm the context getter places `user_id` on `info.context`
- Test with curl first before implementation
- Enable debug logging via `FRAISEQL_LOG_LEVEL=DEBUG`
- Review the Security Checklist for common mistakes

---

## Summary

You now know how to implement:

✅ User authentication with JWT tokens and `fn_` functions
✅ Cursor-based pagination with FraiseQL's `Connection`
✅ Filtering and full-text search via `db.find(where=...)`
✅ Real-time updates with async-generator subscriptions over WebSocket
✅ File uploads to cloud storage
✅ PostgreSQL-backed result caching with cascade invalidation

## Next Steps

- **Ready to deploy?** → [Deployment Guide](./production-deployment.md)
- **Need help?** → [Troubleshooting Guide](./troubleshooting.md)
- **Want more patterns?** → Explore more guides in the [guides](../guides/) directory

---

## See Also

**Related Guides:**

- **[Authorization Quick Start](./authorization-quick-start.md)** — Field-level RBAC and role-based access control
- **[Testing Checklist](../reference/testing-checklist.md)** — Unit, integration, and end-to-end testing for patterns
- **[Consistency Model](./consistency-model.md)** — Understanding data consistency in FraiseQL
- **[Performance Tuning](../operations/performance-tuning-runbook.md)** — Optimizing pattern implementations
- **[Schema Design Best Practices](./schema-design-best-practices.md)** — Designing schemas for common patterns

**Integration Guides:**

- **[Authentication Providers](../integrations/authentication/provider-selection-guide.md)** — Choosing OAuth2/OIDC providers

**Deployment & Operations:**

- **[Production Deployment](./production-deployment.md)** — Deploying pattern implementations to production
- **[Monitoring & Observability](./monitoring.md)** — Observing pattern behavior in production
- **[Security Deployment Checklist](../guides/production-security-checklist.md)** — Hardening patterns for security

**Troubleshooting:**

- **[Troubleshooting Decision Tree](../guides/troubleshooting-decision-tree.md)** — Route to the correct guide for your problem
- **[Troubleshooting Guide](./troubleshooting.md)** — FAQ and common solutions

---

**Questions?** See [troubleshooting.md](./troubleshooting.md) for FAQ and solutions, or open an issue on [GitHub](https://github.com/fraiseql/fraiseql).

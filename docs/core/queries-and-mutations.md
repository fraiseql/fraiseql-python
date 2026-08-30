---
title: Queries & Mutations
description: GraphQL queries and mutations with resolvers and business logic
tags:
  - queries
  - mutations
  - resolvers
  - GraphQL
  - CQRS
---

# Queries and Mutations

Decorators and patterns for defining GraphQL queries, mutations, and subscriptions.

**📍 Navigation**: [← Types & Schema](types-and-schema.md) • [Database API →](database-api.md) • [Performance →](../performance/index.md)

## @fraiseql.query Decorator

**Purpose**: Mark async functions as GraphQL queries

**Signature**:

```python
import fraiseql

@fraiseql.query
async def query_name(info, param1: Type1, param2: Type2 = default) -> ReturnType:
    pass
```

**Parameters**:

| Parameter | Required | Description |
|-----------|----------|-------------|
| info | Yes | GraphQL resolver info (first parameter) |
| ... | Varies | Query parameters with type annotations |

**Returns**: Any GraphQL type (fraise_type, list, scalar)

**Examples**:

Basic query with database access:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.query
async def get_user(info, id: ID) -> User:
    db = info.context["db"]
    # Returns RustResponseBytes - automatically processed by exclusive Rust pipeline
    return await db.find_one("v_user", id=id)
```

Query with multiple parameters:

```python
import fraiseql

@fraiseql.query
async def search_users(
    info,
    name_filter: str | None = None,
    limit: int = 10
) -> list[User]:
    db = info.context["db"]
    filters = {}
    if name_filter:
        filters["name__icontains"] = name_filter
    # Exclusive Rust pipeline handles camelCase conversion and __typename injection
    return await db.find("v_user", **filters, limit=limit)
```

Query with authentication:

```python
import fraiseql

from graphql import GraphQLError

@fraiseql.query
async def get_my_profile(info) -> User:
    user_context = info.context.get("user")
    if not user_context:
        raise GraphQLError("Authentication required")

    db = info.context["db"]
    # Exclusive Rust pipeline works with authentication automatically
    return await db.find_one("v_user", id=user_context.user_id)
```

Query with error handling:

```python
import fraiseql

import logging
from fraiseql.types import ID

logger = logging.getLogger(__name__)

@fraiseql.query
async def get_post(info, id: ID) -> Post | None:
    try:
        db = info.context["db"]
        # Exclusive Rust pipeline handles JSON processing automatically
        return await db.find_one("v_post", id=id)
    except Exception as e:
        logger.error(f"Failed to fetch post {id}: {e}")
        return None
```

Query using custom repository methods:

```python
import fraiseql
from fraiseql.types import ID


@fraiseql.query
async def get_user_stats(info, user_id: ID) -> UserStats:
    db = info.context["db"]
    # Custom SQL query for complex aggregations
    # Exclusive Rust pipeline handles result processing automatically
    result = await db.execute_raw(
        "SELECT count(*) as post_count FROM posts WHERE user_id = $1",
        user_id
    )
    return UserStats(post_count=result[0]["post_count"])
```

**Notes**:

- Functions decorated with @fraiseql.query are automatically discovered and registered
- The first parameter is always 'info' (GraphQL resolver info)
- Return type annotation is used for GraphQL schema generation
- Use async/await for database operations
- Access repository via `info.context["db"]` (provides exclusive Rust pipeline integration)
- Access user context via `info.context["user"]` (if authentication enabled)
- Exclusive Rust pipeline automatically handles camelCase conversion and __typename injection

## Auto-Wired Query Parameters

FraiseQL automatically adds common query parameters based on return type annotations. This reduces boilerplate and ensures consistent API patterns.

### List Queries (`list[T]`)

Queries returning `list[FraiseType]` automatically get these parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `where` | `{TypeName}WhereInput` | Filter conditions |
| `orderBy` | `[{TypeName}OrderByInput!]` | Sort criteria (multiple fields supported) |
| `limit` | `Int` | Maximum results to return |
| `offset` | `Int` | Number of results to skip |

**Example**:

```python
@fraiseql.query
async def users(info) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user")
```

GraphQL schema automatically includes:

```graphql
type Query {
  users(
    where: UserWhereInput
    orderBy: [UserOrderByInput!]
    limit: Int
    offset: Int
  ): [User!]!
}
```

**Usage**:

```graphql
query {
  users(
    where: { age: { gte: 18 } }
    orderBy: [{ createdAt: DESC }]
    limit: 10
    offset: 0
  ) {
    id
    name
  }
}
```

### Connection Queries (`Connection[T]`)

Queries returning `Connection[FraiseType]` automatically get Relay pagination parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `first` | `Int` | Number of items from the start |
| `after` | `String` | Cursor for forward pagination |
| `last` | `Int` | Number of items from the end |
| `before` | `String` | Cursor for backward pagination |
| `where` | `{TypeName}WhereInput` | Filter conditions |
| `orderBy` | `[{TypeName}OrderByInput!]` | Sort criteria |

**Example**:

```python
from fraiseql.types.generic import Connection

@fraiseql.query
async def users_connection(info) -> Connection[User]:
    db = info.context["db"]
    return await db.paginate("v_user", info=info)
```

### Manual Parameter Override

If you declare a parameter manually, FraiseQL will use your declaration instead of auto-wiring:

```python
@fraiseql.query
async def users(
    info,
    where: UserWhereInput | None = None,  # Your type takes precedence
    limit: int = 50  # Custom default
) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user", where=where, limit=limit)
```

### Validation

Auto-wired pagination parameters include built-in validation:

- `limit`, `offset`, `first`, `last` must be non-negative (returns GraphQL error if negative)

### Exclusions

Some types are excluded from `orderBy` auto-wiring:

- Types with vector/embedding fields (e.g., `list[float]` fields named `embedding`, `vector`, etc.)
- These types use `VectorOrderBy` which requires special distance-based ordering

### Collation Support

FraiseQL supports PostgreSQL collation for locale-aware text sorting in `orderBy` clauses.

**Global Default Collation**:

!!! warning "Not currently applied"
    This setting has no effect yet. Applying it safely needs field *types* in the
    ORDER BY builder, which does not distinguish a text field from a numeric one --
    and collating a numeric field either sorts it lexicographically or fails
    outright. Only a per-field collation reaches the SQL today. This has always
    been its effective behaviour.

Configure a default collation for all text sorting:

```python
from fraiseql.fastapi import FraiseQLConfig

config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    default_string_collation="fr_FR.utf8"  # French locale sorting
)
```

**Per-Field Collation**:

Override collation for specific fields in GraphQL queries:

```graphql
query {
  users(orderBy: [
    { field: "lastName", direction: ASC, collation: "fr_FR.utf8" }
  ]) {
    id
    lastName
  }
}
```

**Skip Global Default**:

Use explicit `null` to skip the global collation:

```graphql
query {
  users(orderBy: [
    { field: "id", direction: ASC, collation: null }
  ]) {
    id
  }
}
```

**Collation Precedence**:

1. Per-field explicit value (highest priority)
2. Explicit `null`
3. `default_string_collation` from config, on text fields only
4. PostgreSQL database default (lowest priority)

Step 3 applies only where the sort key resolves to a string on the type
registered for the view; anything else, including a field that cannot be
resolved, falls straight through to step 4.

**Common Collations**:

- `"C"` - Byte-order sorting (fastest, case-sensitive)
- `"POSIX"` - Equivalent to `"C"`
- `"en_US.utf8"` - US English locale-aware sorting
- `"fr_FR.utf8"` - French locale-aware sorting (handles accents)
- `"de_DE.utf8"` - German locale-aware sorting

**Performance Note**: For best performance, create indexes with matching collation:

```sql
CREATE INDEX idx_users_name_fr
ON users ((data->>'name') COLLATE "fr_FR.utf8");
```

**Check Available Collations**:

```sql
SELECT collname FROM pg_collation ORDER BY collname;
```

## @fraiseql.field Decorator

**Purpose**: Mark methods as GraphQL fields with optional custom resolvers

**Signature**:

```python
import fraiseql

@fraiseql.field(
    resolver: Callable[..., Any] | None = None,
    description: str | None = None,
    track_n1: bool = True
)
def method_name(self, info, ...params) -> ReturnType:
    pass
```

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| method | Callable | - | The method to decorate (when used without parentheses) |
| resolver | Callable \| None | None | Optional custom resolver function |
| description | str \| None | None | Field description for GraphQL schema |
| track_n1 | bool | True | Track N+1 query patterns for performance monitoring |

**Examples**:

Computed field with description:

```python
import fraiseql

@fraiseql.type
class User:
    first_name: str
    last_name: str

    @fraiseql.field(description="User's full display name")
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}"
```

Async field with database access:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type
class User:
    id: ID

    @fraiseql.field(description="Posts authored by this user")
    async def posts(self, info) -> list[Post]:
        db = info.context["db"]
        return await db.find("v_post", user_id=self.id)
```

Field with custom resolver function:

```python
import fraiseql
from fraiseql.types import ID

async def fetch_user_posts_optimized(root, info):
    """Custom resolver with optimized batch loading."""
    db = info.context["db"]
    # Use DataLoader or batch loading here
    return await batch_load_posts([root.id])

@fraiseql.type
class User:
    id: ID

    @fraiseql.field(
        resolver=fetch_user_posts_optimized,
        description="Posts with optimized loading"
    )
    async def posts(self) -> list[Post]:
        # This signature defines GraphQL schema
        # but fetch_user_posts_optimized handles actual resolution
        pass
```

Field with parameters:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type
class User:
    id: ID

    @fraiseql.field(description="User's posts with optional filtering")
    async def posts(
        self,
        info,
        published_only: bool = False,
        limit: int = 10
    ) -> list[Post]:
        db = info.context["db"]
        filters = {"user_id": self.id}
        if published_only:
            filters["status"] = "published"
        return await db.find("v_post", **filters, limit=limit)
```

Field with authentication/authorization:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type
class User:
    id: ID

    @fraiseql.field(description="Private user settings (owner only)")
    async def settings(self, info) -> UserSettings | None:
        user_context = info.context.get("user")
        if not user_context or user_context.user_id != self.id:
            return None  # Don't expose private data

        db = info.context["db"]
        return await db.find_one("v_user_settings", user_id=self.id)
```

Field with caching:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type
class Post:
    id: ID

    @fraiseql.field(description="Number of likes (cached)")
    async def like_count(self, info) -> int:
        cache = info.context.get("cache")
        cache_key = f"post:{self.id}:likes"

        # Try cache first
        if cache:
            cached_count = await cache.get(cache_key)
            if cached_count is not None:
                return int(cached_count)

        # Fallback to database
        db = info.context["db"]
        result = await db.execute_raw(
            "SELECT count(*) FROM likes WHERE post_id = $1",
            self.id
        )
        count = result[0]["count"]

        # Cache for 5 minutes
        if cache:
            await cache.set(cache_key, count, ttl=300)

        return count
```

**Notes**:

- Fields are automatically included in GraphQL schema generation
- Use 'info' parameter to access GraphQL context (database, user, etc.)
- Async fields support database queries and external API calls
- Custom resolvers can implement optimized data loading patterns
- N+1 query detection is automatically enabled for performance monitoring
- Return None from fields to indicate null values in GraphQL
- Type annotations enable automatic GraphQL type generation

## @connection Decorator

**Purpose**: Create cursor-based pagination query resolvers following Relay specification

**Signature**:

```python
import fraiseql

@connection(
    node_type: type,
    view_name: str | None = None,
    default_page_size: int = 20,
    max_page_size: int = 100,
    include_total_count: bool = True,
    cursor_field: str = "id",
    jsonb_extraction: bool | None = None,
    jsonb_column: str | None = None
)
@fraiseql.query
async def query_name(
    info,
    first: int | None = None,
    after: str | None = None,
    where: dict | None = None
) -> Connection[NodeType]:
    pass  # Implementation handled by decorator
```

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| node_type | type | Required | Type of objects in the connection |
| view_name | str \| None | None | Database view name (inferred from function name if omitted) |
| default_page_size | int | 20 | Default number of items per page |
| max_page_size | int | 100 | Maximum allowed page size |
| include_total_count | bool | True | Include total count in results |
| cursor_field | str | "id" | Field to use for cursor ordering |
| jsonb_extraction | bool \| None | None | Enable JSONB field extraction (inherits from global config if None) |
| jsonb_column | str \| None | None | JSONB column name (inherits from global config if None) |

**Returns**: Connection[T] with edges, page_info, and total_count

**Raises**: ValueError if configuration parameters are invalid

**Examples**:

Basic connection query:

```python
import fraiseql
from fraiseql.types import Connection
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    name: str
    email: str

@connection(node_type=User)
@fraiseql.query
async def users_connection(info, first: int | None = None) -> Connection[User]:
    pass  # Implementation handled by decorator
```

Connection with custom configuration:

```python
import fraiseql

@connection(
    node_type=Post,
    view_name="v_published_posts",
    default_page_size=25,
    max_page_size=50,
    cursor_field="created_at",
    jsonb_extraction=True,
    jsonb_column="data"
)
@fraiseql.query
async def posts_connection(
    info,
    first: int | None = None,
    after: str | None = None,
    where: dict[str, Any] | None = None
) -> Connection[Post]:
    pass
```

With filtering and ordering:

```python
import fraiseql

@connection(node_type=User, cursor_field="created_at")
@fraiseql.query
async def recent_users_connection(
    info,
    first: int | None = None,
    after: str | None = None,
    where: dict[str, Any] | None = None
) -> Connection[User]:
    pass
```

**GraphQL Usage**:

```graphql
query {
  usersConnection(first: 10, after: "cursor123") {
    edges {
      node {
        id
        name
        email
      }
      cursor
    }
    pageInfo {
      hasNextPage
      hasPreviousPage
      startCursor
      endCursor
      totalCount
    }
    totalCount
  }
}
```

**Notes**:

- Functions must be async and take 'info' as first parameter
- The decorator handles all pagination logic automatically
- Uses existing repository.paginate() method
- Returns properly typed Connection[T] objects
- Supports all Relay connection specification features
- View name is inferred from function name (e.g., users_connection → v_users)

## @fraiseql.mutation Decorator

**Purpose**: Define GraphQL mutations with PostgreSQL function backing

**Signature**:

Function-based mutation:

```python
import fraiseql

@fraiseql.mutation
async def mutation_name(info, input: InputType) -> ReturnType:
    pass
```

Class-based mutation:

```python
import fraiseql

@fraiseql.mutation(
    function: str | None = None,
    schema: str | None = None,
    context_params: dict[str, str] | None = None,
    error_config: MutationErrorConfig | None = None
)
class MutationName:
    input: InputType
    success: SuccessType
    failure: FailureType  # or error: ErrorType
```

**Parameters (Class-based)**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| function | str \| None | None | PostgreSQL function name (defaults to snake_case of class name) |
| schema | str \| None | "public" | PostgreSQL schema containing the function |
| context_params | dict[str, str] \| None | None | Maps GraphQL context keys to PostgreSQL function parameters |
| error_config | MutationErrorConfig \| None | None | **DEPRECATED** - Only used in non-HTTP mode. See [Status String Conventions](../archive/mutations/status-strings.md) for HTTP mode error handling |

**Examples**:

Simple function-based mutation:

```python
import fraiseql

@fraiseql.mutation
async def create_user(info, input: CreateUserInput) -> User:
    db = info.context["db"]
    result = await db.execute_function("fn_create_user", {
        "name": input.name,
        "email": input.email
    })
    return await db.find_one("v_user", id=result["id"])
```

Basic class-based mutation:

```python
import fraiseql

@input
class CreateUserInput:
    name: str
    email: str

@fraiseql.type
class CreateUserSuccess:
    user: User
    message: str

@fraiseql.type
class CreateUserError:
    code: str
    message: str
    field: str | None = None

@fraiseql.mutation
class CreateUser:
    input: CreateUserInput
    success: CreateUserSuccess
    failure: CreateUserError

# Automatically calls PostgreSQL function: public.create_user(input)
# and parses result into CreateUserSuccess or CreateUserError
```

Mutation with custom PostgreSQL function:

```python
import fraiseql

@fraiseql.mutation(function="register_new_user", schema="auth")
class RegisterUser:
    input: RegistrationInput
    success: RegistrationSuccess
    failure: RegistrationError

# Calls: auth.register_new_user(input) instead of default name
```

Mutation with context parameters:

```python
import fraiseql

@fraiseql.mutation(
    function="create_location",
    schema="app",
    context_params={
        "tenant_id": "input_pk_organization",
        "user": "input_created_by"
    }
)
class CreateLocation:
    input: CreateLocationInput
    success: CreateLocationSuccess
    failure: CreateLocationError

# Calls: app.create_location(tenant_id, user_id, input)
# Where tenant_id comes from info.context["tenant_id"]
# And user_id comes from info.context["user"].user_id
```

Mutation with validation:

```python
import fraiseql
from fraiseql.types import ID

@input
class UpdateUserInput:
    id: ID
    name: str | None = None
    email: str | None = None

@fraiseql.mutation
async def update_user(info, input: UpdateUserInput) -> User:
    db = info.context["db"]
    user_context = info.context.get("user")

    # Authorization check
    if not user_context:
        raise GraphQLError("Authentication required")

    # Validation
    if input.email and not is_valid_email(input.email):
        raise GraphQLError("Invalid email format")

    # Update logic
    updates = {}
    if input.name:
        updates["name"] = input.name
    if input.email:
        updates["email"] = input.email

    if not updates:
        raise GraphQLError("No fields to update")

    return await db.update_one("v_user", where={"id": input.id}, updates=updates)
```

Multi-step mutation with transaction:

```python
import fraiseql

@fraiseql.mutation
async def transfer_funds(
    info,
    input: TransferInput
) -> TransferResult:
    db = info.context["db"]

    async with db.transaction():
        # Validate source account
        source = await db.find_one(
            "v_account",
            where={"id": input.source_account_id}
        )
        if not source or source.balance < input.amount:
            raise GraphQLError("Insufficient funds")

        # Validate destination account
        dest = await db.find_one(
            "v_account",
            where={"id": input.destination_account_id}
        )
        if not dest:
            raise GraphQLError("Destination account not found")

        # Perform transfer
        await db.update_one(
            "v_account",
            where={"id": source.id},
            updates={"balance": source.balance - input.amount}
        )
        await db.update_one(
            "v_account",
            where={"id": dest.id},
            updates={"balance": dest.balance + input.amount}
        )

        # Log transaction
        transfer = await db.create_one("v_transfer", data={
            "source_account_id": input.source_account_id,
            "destination_account_id": input.destination_account_id,
            "amount": input.amount,
            "created_at": datetime.utcnow()
        })

        return TransferResult(
            transfer=transfer,
            new_source_balance=source.balance - input.amount,
            new_dest_balance=dest.balance + input.amount
        )
```

Mutation with input transformation (prepare_input hook):

```python
import fraiseql

@input
class NetworkConfigInput:
    ip_address: str
    subnet_mask: str

@fraiseql.mutation
class CreateNetworkConfig:
    input: NetworkConfigInput
    success: NetworkConfigSuccess
    failure: NetworkConfigError

    @staticmethod
    def prepare_input(input_data: dict) -> dict:
        """Transform IP + subnet mask to CIDR notation."""
        ip = input_data.get("ip_address")
        mask = input_data.get("subnet_mask")

        if ip and mask:
            # Convert subnet mask to CIDR prefix
            cidr_prefix = {
                "255.255.255.0": 24,
                "255.255.0.0": 16,
                "255.0.0.0": 8,
            }.get(mask, 32)

            return {
                "ip_address": f"{ip}/{cidr_prefix}",
                # subnet_mask field is removed
            }
        return input_data

# Frontend sends: { ipAddress: "192.168.1.1", subnetMask: "255.255.255.0" }
# Database receives: { ip_address: "192.168.1.1/24" }
```

**PostgreSQL Function Requirements**:

For class-based mutations, the PostgreSQL function should:

1. Accept input as JSONB parameter
2. Return a result with 'success' boolean field
3. Include either 'data' field (success) or 'error' field (failure)

Example PostgreSQL function:

```sql
CREATE OR REPLACE FUNCTION public.create_user(input jsonb)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
    user_id uuid;
    result jsonb;
BEGIN
    -- Insert user
    INSERT INTO users (name, email, created_at)
    VALUES (
        input->>'name',
        input->>'email',
        now()
    )
    RETURNING id INTO user_id;

    -- Return success response
    result := jsonb_build_object(
        'success', true,
        'data', jsonb_build_object(
            'id', user_id,
            'name', input->>'name',
            'email', input->>'email',
            'message', 'User created successfully'
        )
    );

    RETURN result;
EXCEPTION
    WHEN unique_violation THEN
        -- Return error response
        result := jsonb_build_object(
            'success', false,
            'error', jsonb_build_object(
                'code', 'EMAIL_EXISTS',
                'message', 'Email address already exists',
                'field', 'email'
            )
        );
        RETURN result;
END;
$$;
```

**Notes**:

- Function-based mutations provide full control over implementation
- Class-based mutations automatically integrate with PostgreSQL functions
- Use transactions for multi-step operations to ensure data consistency
- PostgreSQL functions handle validation and business logic at database level
- Context parameters enable tenant isolation and user tracking
- Success/error types provide structured response handling
- All mutations are automatically registered with GraphQL schema
- prepare_input hook allows transforming input data before database calls
- prepare_input is called after GraphQL validation but before PostgreSQL function

## @subscription Decorator

**Purpose**: Mark async generator functions as GraphQL subscriptions for real-time updates

**Signature**:

```python
@subscription
async def subscription_name(info, ...params) -> AsyncGenerator[ReturnType, None]:
    async for item in event_stream():
        yield item
```

**Examples**:

Basic subscription:

```python
from typing import AsyncGenerator

@subscription
async def on_post_created(info) -> AsyncGenerator[Post, None]:
    # Subscribe to post creation events
    async for post in post_event_stream():
        yield post
```

Filtered subscription with parameters:

```python
from fraiseql.types import ID

@subscription
async def on_user_posts(
    info,
    user_id: ID
) -> AsyncGenerator[Post, None]:
    # Only yield posts from specific user
    async for post in post_event_stream():
        if post.user_id == user_id:
            yield post
```

Subscription with authentication:

```python
@subscription
async def on_private_messages(info) -> AsyncGenerator[Message, None]:
    user_context = info.context.get("user")
    if not user_context:
        raise GraphQLError("Authentication required")

    async for message in message_stream():
        # Only yield messages for authenticated user
        if message.recipient_id == user_context.user_id:
            yield message
```

Subscription with database polling:

```python
import asyncio
from fraiseql.types import ID

@subscription
async def on_task_updates(
    info,
    project_id: ID
) -> AsyncGenerator[Task, None]:
    db = info.context["db"]
    last_check = datetime.utcnow()

    while True:
        # Poll for new/updated tasks
        updated_tasks = await db.find(
            "v_task",
            where={
                "project_id": project_id,
                "updated_at__gt": last_check
            }
        )

        for task in updated_tasks:
            yield task

        last_check = datetime.utcnow()
        await asyncio.sleep(1)  # Poll every second
```

**Notes**:

- Subscription functions MUST be async generators (use 'async def' and 'yield')
- Return type must be AsyncGenerator[YieldType, None]
- The first parameter is always 'info' (GraphQL resolver info)
- Use WebSocket transport for GraphQL subscriptions
- Consider rate limiting and authentication for production use
- Handle connection cleanup in finally blocks
- Use asyncio.sleep() for polling-based subscriptions

## See Also

- **[Mutation SQL Requirements](../guides/mutation-sql-requirements.md)** - Complete guide to writing PostgreSQL functions for mutations
- **[Error Handling Patterns](../guides/error-handling-patterns.md)** - Error handling philosophy and advanced patterns
- [Types and Schema](./types-and-schema.md) - Define types for use in queries and mutations
- [Decorators Reference](../reference/decorators.md) - Complete decorator API
- [Database API](../reference/database.md) - Database operations for queries and mutations

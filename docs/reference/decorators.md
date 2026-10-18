---
title: Decorators Reference
description: Complete reference for all FraiseQL decorators (@fraiseql.type, @fraiseql.query, @fraiseql.mutation)
tags:
  - decorators
  - API
  - type
  - query
  - mutation
  - Python
---

# Decorators Reference

Complete reference for all FraiseQL decorators with signatures, parameters, and examples.

## Type Decorators

### @fraiseql.type / @fraise_type

**Purpose**: Define GraphQL object types

**Signature**:

```python
import fraiseql

@fraiseql.type(
    sql_source: str | None = None,
    jsonb_column: str | None = "data",
    implements: list[type] | None = None,
    resolve_nested: bool = False
)
```

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| sql_source | str \| None | None | Database table/view name for automatic query generation |
| jsonb_column | str \| None | "data" | JSONB column name. Use None for regular column tables |
| implements | list[type] \| None | None | List of GraphQL interface types |
| resolve_nested | bool | False | Resolve nested instances via separate queries |

**Examples**: See [Types and Schema](../core/types-and-schema.md)

### @input / @fraise_input

**Purpose**: Define GraphQL input types

**Signature**:

```python
import fraiseql

@input
class InputName:
    field1: str
    field2: int | None = None
```

**Parameters**: None (decorator takes no arguments)

**Examples**: See [Types and Schema](../core/types-and-schema.md)

### @enum / @fraise_enum

**Purpose**: Define GraphQL enum types from Python Enum classes

**Signature**:

```python
@enum
class EnumName(Enum):
    VALUE1 = "value1"
    VALUE2 = "value2"
```

**Parameters**: None

**Examples**: See [Types and Schema](../core/types-and-schema.md)

### @interface / @fraise_interface

**Purpose**: Define GraphQL interface types

**Signature**:

```python
@interface
class InterfaceName:
    field1: str
    field2: int
```

**Parameters**: None

**Examples**: See [Types and Schema](../core/types-and-schema.md)

## Query Decorators

### @fraiseql.query

**Purpose**: Mark async functions as GraphQL queries

**Signature**:

```python
import fraiseql

@fraiseql.query
async def query_name(info, param1: Type1, param2: Type2 = default) -> ReturnType:
    pass
```

**Parameters**: None (decorator takes no arguments)

**First Parameter**: Always `info` (GraphQL resolver info)

**Return Type**: Any GraphQL type (fraise_type, list, scalar, Connection, etc.)

**Examples**:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.query
async def get_user(info, id: ID) -> User:
    db = info.context["db"]
    return await db.find_one("v_user", where={"id": id})

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
    return await db.find("v_user", where=filters, limit=limit)
```

**See Also**: [Queries and Mutations](../core/queries-and-mutations.md#query-decorator)

### @connection

**Purpose**: Create cursor-based pagination queries

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
```

**Parameters**:

| Parameter | Type | Default | Required | Description |
|-----------|------|---------|----------|-------------|
| node_type | type | - | Yes | Type of objects in the connection |
| view_name | str \| None | None | No | Database view name (inferred from function name if omitted) |
| default_page_size | int | 20 | No | Default number of items per page |
| max_page_size | int | 100 | No | Maximum allowed page size |
| include_total_count | bool | True | No | Include total count in results |
| cursor_field | str | "id" | No | Field to use for cursor ordering |
| jsonb_extraction | bool \| None | None | No | Enable JSONB field extraction (inherits from global config) |
| jsonb_column | str \| None | None | No | JSONB column name (inherits from global config) |

**Must be used with**: @fraiseql.query decorator

**Returns**: Connection[T]

**Examples**:

```python
import fraiseql
from fraiseql.types import Connection
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user")
class User:
    id: ID
    name: str

@connection(node_type=User)
@fraiseql.query
async def users_connection(info, first: int | None = None) -> Connection[User]:
    pass  # Implementation handled by decorator

@connection(
    node_type=Post,
    view_name="v_published_posts",
    default_page_size=25,
    max_page_size=50,
    cursor_field="created_at"
)
@fraiseql.query
async def posts_connection(
    info,
    first: int | None = None,
    after: str | None = None
) -> Connection[Post]:
    pass
```

**See Also**: [Queries and Mutations](../core/queries-and-mutations.md#connection-decorator)

## Mutation Decorators

### @fraiseql.mutation

**Purpose**: Define GraphQL mutations

**Function-based Signature**:

```python
import fraiseql

@fraiseql.mutation
async def mutation_name(info, input: InputType) -> ReturnType:
    pass
```

**Class-based Signature**:

```python
import fraiseql

@fraiseql.mutation(
    function: str | None = None,
    schema: str | None = None,
    context_params: dict[str, str] | None = None,
    error_config: MutationErrorConfig | None = None,
    name: str | None = None,
    result_name: str | None = None,
)
class MutationName:
    input: InputType
    success: SuccessType
    failure: FailureType
```

**Parameters (Class-based)**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| function | str \| None | None | PostgreSQL function name (defaults to snake_case of class name). It only picks the SQL function: several mutations may share one |
| schema | str \| None | "public" | PostgreSQL schema containing the function |
| context_params | dict[str, str] \| None | None | Maps GraphQL context keys to PostgreSQL function parameters |
| error_config | MutationErrorConfig \| None | None | Error configuration for this mutation. If not specified, uses `default_error_config` from `FraiseQLConfig` (if set). **DEPRECATED** - Only used in non-HTTP mode. HTTP mode uses [status string taxonomy](../archive/mutations/status-strings.md) |
| name | str \| None | None | GraphQL field name, used as given. See [Field names](#mutation-field-names) |
| result_name | str \| None | None | GraphQL name of the result union, used as given. See [Result union names](#mutation-result-union-names) |

#### Mutation field names

A class mutation's GraphQL field is named after the class: `CreateUser` becomes
`createUser` (`create_user` with `camel_case_fields=False`). A function
mutation is named after the function. `name=` sets the field name directly.
`function=` doesn't change the field name.

Two mutations with the same field name make the schema build raise a
`ValueError` that names both. Give one of them a different `name=`.

!!! warning "Names taken from `function=` until 2.0.0"
    Up to fraiseql 1.28, a class mutation was named after its `function=`:
    `RegisterUser` with `function="register_new_user"` was served as
    `registerNewUser`. In 1.x, such a mutation keeps that name, and the schema
    build emits one `FutureWarning` listing every field whose name changes in
    fraiseql 2.0.0:

    ```text
    These mutation names will change in the next major release of fraiseql (2.0.0):
      field 'registerNewUser' -> 'registerUser'
    To keep a name, pass name="..." (field) or result_name="..." (union) to @mutation.
    ```

    To keep the current name, pass it: `@fraiseql.mutation(function="register_new_user", name="registerNewUser")`.
    To adopt the new one now, pass `name="registerUser"`. Either removes the
    mutation from the warning.

    Mutations that shared a `function=` lost a field before 1.29. They get the
    class-derived names straight away, with no warning.

    For an auto-discovered mutation, the new name is the `name:` in its
    `@fraiseql:mutation` comment; set it to the current name to keep it.

#### Mutation result union names

A mutation whose success and error types differ returns a union of the two.
Each mutation gets its own union, named after its field: `createUser` returns
`CreateUserResult`. `result_name=` sets the union name directly. Several
mutations may share success and error types; each still gets its own union.
When the success and error types are the same class, there is no union and
`result_name=` is ignored.

Two mutations with the same union name make the schema build raise a
`ValueError` that names both. Give one of them a different `result_name=`.

!!! warning "Names taken from the success type until 2.0.0"
    Up to fraiseql 1.28, the union was named after the success type:
    `UpdatePostTitle` with `success: PostSuccess` returned `PostResult`, and two
    mutations sharing a success type failed the schema build with
    `multiple types named '...Result'`. In 1.x, a mutation that works keeps its
    union name, and the same `FutureWarning` as for field names lists it:

    ```text
      result union 'PostResult' -> 'UpdatePostTitleResult'
    ```

    Pass `result_name="PostResult"` to keep the current name, or
    `result_name="UpdatePostTitleResult"` to adopt the new one now. Mutations
    that shared a success type get the new names straight away, with no warning.
    An auto-discovered mutation takes `result_name:` in its `@fraiseql:mutation`
    comment.

**Global Default**: If you don't specify `error_config` on a mutation, FraiseQL will use `default_error_config` from your `FraiseQLConfig` (if set). This allows you to set a global error handling strategy and override it per-mutation when needed.

```python
from fraiseql import FraiseQLConfig, DEFAULT_ERROR_CONFIG, STRICT_STATUS_CONFIG

# Set global default
config = FraiseQLConfig(
    database_url="postgresql://localhost/mydb",
    default_error_config=DEFAULT_ERROR_CONFIG,
)

# Uses global default
@fraiseql.mutation(function="create_user")
class CreateUser:
    input: CreateUserInput
    success: CreateUserSuccess
    failure: CreateUserError

# Overrides global default
@fraiseql.mutation(
    function="delete_user",
    error_config=STRICT_STATUS_CONFIG,  # Override
)
class DeleteUser:
    input: DeleteUserInput
    success: DeleteUserSuccess
    failure: DeleteUserError
```

**See**: [FraiseQLConfig.default_error_config](./config.md#default_error_config) for details.

**Examples**:

```python
import fraiseql

# Function-based
@fraiseql.mutation
async def create_user_account(info, input: CreateUserInput) -> User:
    db = info.context["db"]
    return await db.create_one("v_user", data=input.__dict__)

# Class-based
@fraiseql.mutation
class CreateUser:
    input: CreateUserInput
    success: CreateUserSuccess
    failure: CreateUserError

# With custom function (name= sets the field to "registerUser"; without it,
# fraiseql 1.x names the field after the function, "registerNewUser", and warns)
@fraiseql.mutation(function="register_new_user", schema="auth", name="registerUser")
class RegisterUser:
    input: RegistrationInput
    success: RegisterUserSuccess
    failure: RegisterUserError

# With context parameters - maps context to PostgreSQL function params
@fraiseql.mutation(
    function="create_location",
    context_params={
        "tenant_id": "input_pk_organization",
        "user_id": "input_created_by"
    }
)
class CreateLocation:
    input: CreateLocationInput
    success: CreateLocationSuccess
    failure: CreateLocationError
```

**How context_params Works**:

`context_params` automatically injects GraphQL context values as PostgreSQL function parameters:

```python
import fraiseql

# GraphQL mutation
@fraiseql.mutation(
    function="create_location",
    context_params={
        "tenant_id": "input_pk_organization",  # info.context["tenant_id"] → p_pk_organization
        "user_id": "input_created_by"          # info.context["user_id"] → p_created_by
    }
)
class CreateLocation:
    input: CreateLocationInput
    success: CreateLocationSuccess
    failure: CreateLocationError

# PostgreSQL function signature
# CREATE FUNCTION create_location(
#     p_pk_organization uuid,   -- From info.context["tenant_id"]
#     p_created_by uuid,         -- From info.context["user_id"]
#     input jsonb                -- From mutation input
# ) RETURNS jsonb
```

**Real-World Example**:

```python
import fraiseql

# Context from JWT
async def get_context(request: Request) -> dict:
    token = extract_jwt(request)
    return {
        "tenant_id": token["tenant_id"],
        "user_id": token["user_id"]
    }

# Mutation with context injection
@fraiseql.mutation(
    function="create_order",
    context_params={
        "tenant_id": "input_tenant_id",
        "user_id": "input_created_by"
    }
)
class CreateOrder:
    input: CreateOrderInput
    success: CreateOrderSuccess
    failure: CreateOrderFailure

# PostgreSQL function
# CREATE FUNCTION create_order(
#     p_tenant_id uuid,      -- Automatically from context!
#     p_created_by uuid,     -- Automatically from context!
#     input jsonb
# ) RETURNS jsonb AS $$
# BEGIN
#     -- p_tenant_id and p_created_by are available
#     -- No need to extract from input JSONB
#     INSERT INTO tb_order (tenant_id, data)
#     VALUES (p_tenant_id, jsonb_set(input, '{created_by}', to_jsonb(p_created_by)));
# END;
# $$ LANGUAGE plpgsql;
```

**Benefits**:

- **Security**: Tenant/user IDs come from verified JWT, not user input
- **Simplicity**: No need to pass tenant_id in mutation input
- **Consistency**: Context injection happens automatically on every mutation


**See Also**: [Queries and Mutations](../core/queries-and-mutations.md#mutation-decorator)

### @success / @error / @result

**Purpose**: Helper decorators for mutation result types

**Usage**:

```python
from fraiseql.mutations.decorators import success, error

@success
class CreateUserSuccess:
    user: User
    message: str

@error
class CreateUserError:
    code: str
    message: str
    field: str | None = None

@fraiseql.mutation
async def create_user(info, input: CreateUserInput) -> CreateUserSuccess | CreateUserError:
    ...
```

**Note**: These are type markers, not required for mutations. Use @fraiseql.type instead for most cases.

!!! warning "`result()` is deprecated"
    `fraiseql.result(success_cls, error_cls)` builds a union type from a success
    and an error class. It is deprecated since 1.29 and removed in fraiseql 2.0.0:
    annotate `Success | Error` instead, and the mutation's union is named as
    described in [Result union names](#mutation-result-union-names).

## Field Decorators

### @field

**Purpose**: Mark methods as GraphQL fields with custom resolvers

**Signature**:

```python
import fraiseql

@field(
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
| method | Callable | - | Method to decorate (when used without parentheses) |
| resolver | Callable \| None | None | Optional custom resolver function |
| description | str \| None | None | Field description for GraphQL schema |
| track_n1 | bool | True | Track N+1 query patterns for performance monitoring |

**Examples**:

```python
import fraiseql

@fraiseql.type
class User:
    first_name: str
    last_name: str

    @field(description="Full display name")
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @field(description="User's posts")
    async def posts(self, info) -> list[Post]:
        db = info.context["db"]
        return await db.find("v_post", where={"user_id": self.id})

    @field(description="Posts with parameters")
    async def recent_posts(
        self,
        info,
        limit: int = 10
    ) -> list[Post]:
        db = info.context["db"]
        return await db.find(
            "v_post",
            where={"user_id": self.id},
            order_by="created_at DESC",
            limit=limit
        )
```

**See Also**: [Queries and Mutations](../core/queries-and-mutations.md#field-decorator)

### @dataloader_field

**Purpose**: Automatically use DataLoader for field resolution

**Signature**:

```python
@dataloader_field(
    loader_class: type[DataLoader],
    key_field: str,
    description: str | None = None
)
async def method_name(self, info) -> ReturnType:
    pass  # Implementation is auto-generated
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| loader_class | type[DataLoader] | Yes | DataLoader class to use for loading |
| key_field | str | Yes | Field name on parent object containing the key to load |
| description | str \| None | No | Field description for GraphQL schema |

**Examples**:

```python
from fraiseql import dataloader_field
from fraiseql.optimization.dataloader import DataLoader
from fraiseql.types import ID

# Define DataLoader
class UserDataLoader(DataLoader):
    async def batch_load(self, keys: list[UUID]) -> list[User | None]:
        db = self.context["db"]
        users = await db.find("v_user", where={"id__in": keys})
        # Return in same order as keys
        user_map = {user.id: user for user in users}
        return [user_map.get(key) for key in keys]

# Use in type
@fraiseql.type
class Post:
    author_id: ID

    @dataloader_field(UserDataLoader, key_field="author_id")
    async def author(self, info) -> User | None:
        """Load post author using DataLoader."""
        pass  # Implementation is auto-generated

# GraphQL query automatically batches author loads
# query {
#   posts {
#     title
#     author { name }  # Batched into single query
#   }
# }
```

**Benefits**:

- Eliminates N+1 query problems
- Automatic batching of requests
- Built-in caching within single request
- Type-safe implementation

**See Also**: Optimization documentation

## Subscription Decorators

### @subscription

**Purpose**: Mark async generator functions as GraphQL subscriptions

**Signature**:

```python
@subscription
async def subscription_name(info, ...params) -> AsyncGenerator[ReturnType, None]:
    async for item in event_stream():
        yield item
```

**Parameters**: None

**Return Type**: Must be AsyncGenerator[YieldType, None]

**Examples**:

```python
from typing import AsyncGenerator
from fraiseql.types import ID

@subscription
async def on_post_created(info) -> AsyncGenerator[Post, None]:
    async for post in post_event_stream():
        yield post

@subscription
async def on_user_posts(
    info,
    user_id: ID
) -> AsyncGenerator[Post, None]:
    async for post in post_event_stream():
        if post.user_id == user_id:
            yield post
```

**See Also**: [Queries and Mutations](../core/queries-and-mutations.md#subscription-decorator)

## Authentication Decorators

### @requires_auth

**Purpose**: Require authentication for resolver

**Signature**:

```python
@requires_auth
async def resolver_name(info, ...params) -> ReturnType:
    pass
```

**Parameters**: None

**Examples**:

```python
import fraiseql

from fraiseql.auth import requires_auth

@fraiseql.query
@requires_auth
async def get_my_profile(info) -> User:
    user = info.context["user"]  # Guaranteed to be authenticated
    db = info.context["db"]
    return await db.find_one("v_user", where={"id": user.user_id})

@fraiseql.mutation
@requires_auth
async def update_profile(info, input: UpdateProfileInput) -> User:
    user = info.context["user"]
    db = info.context["db"]
    return await db.update_one(
        "v_user",
        where={"id": user.user_id},
        updates=input.__dict__
    )
```

**Raises**: GraphQLError with code "UNAUTHENTICATED" if not authenticated

### @requires_permission

**Purpose**: Require specific permission for resolver

**Signature**:

```python
@requires_permission(permission: str)
async def resolver_name(info, ...params) -> ReturnType:
    pass
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| permission | str | Yes | Permission string required (e.g., "users:write") |

**Examples**:

```python
import fraiseql

from fraiseql.auth import requires_permission
from fraiseql.types import ID

@fraiseql.mutation
@requires_permission("users:write")
async def create_user(info, input: CreateUserInput) -> User:
    db = info.context["db"]
    return await db.create_one("v_user", data=input.__dict__)

@fraiseql.mutation
@requires_permission("users:delete")
async def delete_user(info, id: ID) -> bool:
    db = info.context["db"]
    await db.delete_one("v_user", where={"id": id})
    return True
```

**Raises**:

- GraphQLError with code "UNAUTHENTICATED" if not authenticated
- GraphQLError with code "FORBIDDEN" if missing permission

### @requires_role

**Purpose**: Require specific role for resolver

**Signature**:

```python
@requires_role(role: str)
async def resolver_name(info, ...params) -> ReturnType:
    pass
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| role | str | Yes | Role name required (e.g., "admin") |

**Examples**:

```python
import fraiseql

from fraiseql.auth import requires_role

@fraiseql.query
@requires_role("admin")
async def get_all_users(info) -> list[User]:
    db = info.context["db"]
    return await db.find("v_user")

@fraiseql.mutation
@requires_role("admin")
async def admin_action(info, input: AdminActionInput) -> Result:
    # Admin-only mutation
    pass
```

**Raises**:

- GraphQLError with code "UNAUTHENTICATED" if not authenticated
- GraphQLError with code "FORBIDDEN" if missing role

### @requires_any_permission

**Purpose**: Require any of the specified permissions

**Signature**:

```python
@requires_any_permission(*permissions: str)
async def resolver_name(info, ...params) -> ReturnType:
    pass
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *permissions | str | Yes | Variable number of permission strings |

**Examples**:

```python
import fraiseql

from fraiseql.auth import requires_any_permission
from fraiseql.types import ID

@fraiseql.mutation
@requires_any_permission("users:write", "admin:all")
async def update_user(info, id: ID, input: UpdateUserInput) -> User:
    # Can be performed by users:write OR admin:all
    db = info.context["db"]
    return await db.update_one("v_user", where={"id": id}, updates=input.__dict__)
```

**Raises**:

- GraphQLError with code "UNAUTHENTICATED" if not authenticated
- GraphQLError with code "FORBIDDEN" if missing all permissions

### @requires_any_role

**Purpose**: Require any of the specified roles

**Signature**:

```python
@requires_any_role(*roles: str)
async def resolver_name(info, ...params) -> ReturnType:
    pass
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *roles | str | Yes | Variable number of role names |

**Examples**:

```python
import fraiseql

from fraiseql.auth import requires_any_role
from fraiseql.types import ID

@fraiseql.query
@requires_any_role("admin", "moderator")
async def moderate_content(info, id: ID) -> ModerationResult:
    # Can be performed by admin OR moderator
    pass
```

**Raises**:

- GraphQLError with code "UNAUTHENTICATED" if not authenticated
- GraphQLError with code "FORBIDDEN" if missing all roles

## Decorator Combinations

**Stacking decorators**:

```python
import fraiseql, connection, type
from fraiseql.auth import requires_auth, requires_permission
from fraiseql.types import Connection
from fraiseql.types import ID

# Multiple decorators - order matters
@connection(node_type=User)
@fraiseql.query
@requires_auth
@requires_permission("users:read")
async def users_connection(info, first: int | None = None) -> Connection[User]:
    pass

# Field-level auth
@fraiseql.type
class User:
    id: ID
    name: str

    @field(description="Private settings")
    @requires_auth
    async def settings(self, info) -> UserSettings:
        # Only accessible to authenticated users
        pass
```

**Decorator Order Rules**:

1. Type decorators (@fraiseql.type, @input, @enum, @interface) - First
2. Query/Mutation/Subscription decorators - Second
3. Connection decorator - Before @fraiseql.query
4. Auth decorators - After query/mutation/field decorators
5. Field decorators (@field, @dataloader_field) - On methods

## See Also

- [Types and Schema](../core/types-and-schema.md) - Type system details
- [Queries and Mutations](../core/queries-and-mutations.md) - Query and mutation patterns
- [Configuration](../core/configuration.md) - Configure decorator behavior

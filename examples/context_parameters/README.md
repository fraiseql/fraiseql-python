# Context Parameters Example

This example demonstrates how to use context parameters in FraiseQL mutations to pass authentication context (like tenant_id and user_id) to PostgreSQL functions.

## Problem Statement

Many enterprise applications use PostgreSQL functions that require context parameters for:

- Multi-tenant data isolation
- Audit trails
- Row-level security
- Business logic that depends on the current user/organization

Traditional FraiseQL mutations only support single JSONB parameter functions:

```sql
CREATE FUNCTION create_location(input_data JSONB) RETURNS mutation_result
```

But many existing enterprise systems use functions with context parameters:

```sql
CREATE FUNCTION app.create_location(
    input_pk_organization UUID,  -- Tenant/Organization ID
    input_created_by UUID,       -- User/Contact ID
    input_json JSONB             -- Actual mutation input
) RETURNS app.mutation_result
```

## Solution: Context Parameters

FraiseQL now supports context parameters that automatically extract values from the GraphQL context and pass them to PostgreSQL functions.

## Usage

### 1. Define your mutation with context parameters

```python
from uuid import UUID

import fraiseql
from fraiseql.mutations import mutation

@fraiseql.input
class CreateLocationInput:
    name: str
    address: str
    latitude: float
    longitude: float

@fraiseql.success
class CreateLocationSuccess:
    location_id: UUID
    message: str

@fraiseql.error
class CreateLocationError:
    message: str
    code: str

@mutation(
    function="create_location",
    schema="app",
    context_params={
        "tenant_id": "input_pk_organization",  # GraphQL context key -> SQL param name
        "user": "input_created_by"             # Will extract user_id from UserContext
    }
)
class CreateLocation:
    input: CreateLocationInput
    success: CreateLocationSuccess
    error: CreateLocationError
```

### 2. Set up your GraphQL context

Your FastAPI app should provide the context values that your mutations need:

```python
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.auth import Auth0Provider

# Configure auth provider (extracts user context from JWT)
auth_provider = Auth0Provider(
    domain="myapp.auth0.com",
    api_identifier="https://api.myapp.com"
)

app = create_fraiseql_app(
    types=[Location],
    mutations=[CreateLocation],
    auth_provider=auth_provider,
    context_getter=get_context  # Your custom context function
)

async def get_context(request, background_tasks):
    """Build GraphQL context with tenant_id and user info."""
    return {
        "db": get_database(),
        "tenant_id": extract_tenant_from_request(request),
        "user": request.state.user,  # Set by auth middleware
    }
```

### 3. Create your PostgreSQL function

```sql
-- Create the mutation result type
CREATE TYPE app.mutation_result AS (
    status TEXT,
    message TEXT,
    object_data JSONB,
    extra_metadata JSONB
);

-- Create the mutation function with context parameters
CREATE OR REPLACE FUNCTION app.create_location(
    input_pk_organization UUID,  -- Tenant ID (from context)
    input_created_by UUID,       -- User ID (from context)
    input_json JSONB             -- Mutation input data
) RETURNS app.mutation_result
LANGUAGE plpgsql
AS $$
DECLARE
    v_location_id UUID;
    v_result app.mutation_result;
BEGIN
    -- Validate tenant access
    IF NOT EXISTS (
        SELECT 1 FROM organizations
        WHERE id = input_pk_organization
        AND active = true
    ) THEN
        v_result.status := 'error';
        v_result.message := 'Invalid organization';
        RETURN v_result;
    END IF;

    -- Create location with tenant isolation
    INSERT INTO locations (
        id,
        organization_id,
        created_by,
        name,
        address,
        latitude,
        longitude,
        created_at
    ) VALUES (
        gen_random_uuid(),
        input_pk_organization,  -- Ensures tenant isolation
        input_created_by,       -- Audit trail
        input_json->>'name',
        input_json->>'address',
        (input_json->>'latitude')::NUMERIC,
        (input_json->>'longitude')::NUMERIC,
        NOW()
    ) RETURNING id INTO v_location_id;

    -- Return success result
    v_result.status := 'success';
    v_result.message := 'Location created successfully';
    v_result.object_data := jsonb_build_object(
        'location_id', v_location_id
    );

    RETURN v_result;
END;
$$;
```

### 4. Execute the mutation

```graphql
mutation CreateLocation($input: CreateLocationInput!) {
    createLocation(input: $input) {
        ... on CreateLocationSuccess {
            locationId
            message
        }
        ... on CreateLocationError {
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
        "name": "Main Office",
        "address": "123 Business St",
        "latitude": 37.7749,
        "longitude": -122.4194
    }
}
```

## How It Works

1. **Context Extraction**: The mutation resolver extracts values from `info.context` using the keys specified in `context_params`
2. **Parameter Mapping**: Values are mapped to PostgreSQL function parameter names
3. **Function Call**: The database layer calls your function with: `SELECT app.create_location($1, $2, $3)`
4. **Type Safety**: Context parameters are validated at runtime

## Context Parameter Types

### Direct Values

```python
context_params={
    "tenant_id": "input_pk_organization"  # Pass tenant_id directly
}
```

### UserContext Objects

```python
context_params={
    "user": "input_created_by"  # Extracts user_id from UserContext automatically
}
```

The resolver automatically extracts `user_id` from `UserContext` objects when the context key is "user".

## Benefits

✅ **Enterprise Ready**: Works with existing multi-tenant database architectures
✅ **Security**: Context parameters ensure proper tenant isolation and audit trails
✅ **Clean Separation**: Business data separate from context data
✅ **Type Safety**: Runtime validation of required context parameters
✅ **Backward Compatible**: Existing single-parameter mutations continue to work

## Migration from Wrapper Functions

If you currently use wrapper functions to work around the single-parameter limitation:

**Before (Workaround):**

```sql
-- Wrapper function (can be removed)
CREATE FUNCTION app.create_location(input_data JSONB)
RETURNS app.mutation_result AS $$
DECLARE
    v_org_id UUID := (input_data->>'organization_id')::UUID;
    v_user_id UUID := (input_data->>'created_by')::UUID;
BEGIN
    -- Remove context from input and call real function
    RETURN app.create_location_impl(
        v_org_id,
        v_user_id,
        input_data - 'organization_id' - 'created_by'
    );
END;
$$;
```

**After (Native Support):**

```python
@mutation(
    function="create_location_impl",  # Call the real function directly
    schema="app",
    context_params={
        "tenant_id": "input_pk_organization",
        "user": "input_created_by"
    }
)
class CreateLocation:
    # Same as before
```

You can remove the wrapper functions and call your original multi-parameter functions directly.

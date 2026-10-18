# FraiseQL Mutations Demo

This demo shows how to use FraiseQL's PostgreSQL function-based mutation system with the **modern `mutation_response` type** (8 fields).

## Features Demonstrated

- Type-safe mutations using the `@mutation` decorator
- Automatic resolver generation that calls PostgreSQL functions
- Success/Error union types with proper parsing
- Complex object instantiation from JSONB
- Real-world error handling patterns
- **Modern mutation_response format** with cascade support

## Setup

1. Start the PostgreSQL database:

   ```bash
   docker-compose up -d
   ```

2. Apply the database schema:

   ```bash
   psql -h localhost -U fraiseql -d postgres -f setup.sql
   psql -h localhost -U fraiseql -d postgres -f mutation_functions.sql
   ```

3. Install dependencies (if not already installed):

   ```bash
   pip install psycopg[async]
   ```

4. Run the demo:

   ```bash
   python examples/mutations_demo/demo.py
   ```

## Migration Note

This example uses the **modern `mutation_response` type** (8 fields) introduced in FraiseQL v1.8.0.

## What It Does

The demo performs these operations:

1. **Creates a user** - Shows successful user creation
2. **Handles duplicates** - Demonstrates conflict detection with helpful suggestions
3. **Updates a user** - Shows partial updates with field tracking
4. **Handles not found** - Shows error handling for missing records
5. **Deletes a user** - Demonstrates deletion with data return
6. **Builds GraphQL schema** - Shows how mutations integrate with the schema

## Key Concepts

### PostgreSQL Functions

All mutations are implemented as PostgreSQL functions that:

- Accept JSONB input
- Return a standardized `mutation_response` type (8 fields: status, message, entity_id, entity_type, entity, updated_fields, cascade, metadata)
- Handle all business logic in the database
- Provide rich error information

### Type Safety

The FraiseQL mutation classes ensure:

- Input validation through `@fraiseql.input` types
- Success/Error discrimination through union types
- Automatic JSONB to Python object conversion
- Full GraphQL schema integration

### Error Handling

Errors can include:

- Detailed messages
- Related objects (e.g., conflicting user)
- Suggestions (e.g., alternative email)
- Validation errors per field

## Database Schema

The demo uses a simple users table with JSONB storage:

```sql
CREATE TABLE tb_user (
    id UUID PRIMARY KEY,
    data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE
);
```

This pattern allows flexible schema evolution while maintaining PostgreSQL's powerful querying capabilities.

## Extending

To add your own mutations:

1. Define input/success/error types
2. Create a PostgreSQL function returning `mutation_result`
3. Write a `@fraiseql.mutation` class named after the function (`CreateUser` calls `create_user`)
4. Add to schema with `build_fraiseql_schema()`

The system automatically handles the rest!

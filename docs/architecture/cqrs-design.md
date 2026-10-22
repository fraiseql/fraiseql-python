# CQRS Design Architecture

**Last Updated**: 2025-12-30
**Status**: Complete
**Audience**: Backend developers, database designers

---

## Overview

FraiseQL implements the **CQRS (Command Query Responsibility Segregation)** pattern, separating read operations (queries) from write operations (mutations) for optimal performance and maintainability.

---

## CQRS Pattern in FraiseQL

```mermaid
flowchart TD
    A[GraphQL Request] --> B{Operation Type?}

    B -->|Query| C[Read Path]
    B -->|Mutation| D[Write Path]

    C --> E[PostgreSQL Views]
    D --> F[PostgreSQL Functions]

    E --> G[Optimized for Reading]
    F --> H[Optimized for Writing]

    G --> I[JSONB Pre-formatted]
    H --> J[Business Logic]

    I --> K[Rust Pipeline]
    J --> L[Validation & Constraints]

    K --> M[Fast Response]
    L --> N[Reliable Updates]

    style C fill:#e8f5e9
    style D fill:#fff3e0
    style E fill:#c8e6c9
    style F fill:#ffe0b2
```

**Key Principle**: Different data structures for reading vs writing leads to better performance and clearer code.

---

## Query Path (Read Operations)

### View-Based Queries

```mermaid
flowchart LR
    A[GraphQL Query] --> B[FraiseQL Schema]
    B --> C[SELECT from View]
    C --> D[(v_user)]
    D --> E[JSONB Result]
    E --> F[Rust Pipeline]
    F --> G[JSON Response]

    style D fill:#e8f5e9
    style F fill:#c8e6c9
```

**PostgreSQL View Example**:

```sql
-- Read-optimized view
CREATE VIEW v_user AS
SELECT
    id,  -- Public UUID
    jsonb_build_object(
        'id', id,
        'name', name,
        'email', email,
        'createdAt', created_at
    ) AS data
FROM tb_user;
```

**GraphQL Type**:

```python
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    """A user in the system.

    Fields:
        id: Unique user identifier
        name: User's full name
        email: User's email address
        created_at: When the user was created
    """
    id: ID
    name: str
    email: str
    created_at: datetime
```

**Benefits of View-Based Queries**:

- ✅ **Pre-formatted data** - JSONB already in response format
- ✅ **Rust pipeline** - Zero Python serialization overhead
- ✅ **Denormalized reads** - Fast joins via Trinity Pattern (`pk_*`)
- ✅ **Field selection** - Only requested fields extracted
- ✅ **Security** - Views expose only public `id` (UUID), hide `pk_*`

---

## Mutation Path (Write Operations)

### Function-Based Mutations

```mermaid
flowchart LR
    A[GraphQL Mutation] --> B[FraiseQL Schema]
    B --> C[CALL fn_create_user]
    C --> D[(PostgreSQL Function)]
    D --> E{Validation}
    E -->|Success| F[INSERT INTO tb_user]
    E -->|Error| G[Return Error JSONB]
    F --> H[Return Success JSONB]
    G --> I[GraphQL Error Response]
    H --> J[GraphQL Success Response]

    style D fill:#fff3e0
    style F fill:#ffe0b2
```

**PostgreSQL Function Example**:

A class mutation calls its function with the input as one `jsonb` and reads the
`mutation_response` it returns (`mutation_response` and the `mutation_*` helpers come
from `migrations/trinity/005_add_mutation_response.sql`):

```sql
-- Write-optimized function
CREATE OR REPLACE FUNCTION create_user(input jsonb)
RETURNS mutation_response AS $$
DECLARE
    v_user_id UUID;
BEGIN
    -- Validation
    IF coalesce(input->>'email', '') = '' THEN
        RETURN mutation_validation_error('Email is required', 'email');
    END IF;

    -- Check uniqueness
    IF EXISTS (SELECT 1 FROM tb_user WHERE email = input->>'email') THEN
        RETURN mutation_conflict('Email already exists');
    END IF;

    -- Insert
    INSERT INTO tb_user (name, email)
    VALUES (input->>'name', input->>'email')
    RETURNING id INTO v_user_id;

    -- Success response
    RETURN mutation_created(
        'User created', (SELECT data FROM v_user WHERE id = v_user_id), 'User'
    );
END;
$$ LANGUAGE plpgsql;
```

**GraphQL Mutation**:

```python
@fraiseql.input
class CreateUserInput:
    name: str
    email: str


@fraiseql.success
class CreateUserSuccess:
    user: User


@fraiseql.error
class CreateUserError:
    field: str | None = None


@fraiseql.mutation
class CreateUser:
    """Create a new user: calls create_user(input jsonb).

    Returns CreateUserSuccess with the new user, or CreateUserError with the
    message and status the function returned.
    """

    input: CreateUserInput
    success: CreateUserSuccess
    error: CreateUserError
```

**Benefits of Function-Based Mutations**:

- ✅ **Business logic in database** - Consistent validation rules
- ✅ **Transactional integrity** - ACID guarantees
- ✅ **Security** - Functions control what can be modified
- ✅ **Audit logging** - All changes go through known entry points
- ✅ **Performance** - No round-trips for validation queries

---

## Schema Separation

```mermaid
flowchart TD
    A[Database] --> B{Schema Type}

    B -->|Read Schema| C[Views Layer]
    B -->|Write Schema| D[Functions Layer]
    B -->|Data Schema| E[Tables Layer]

    C --> F[v_user<br/>v_post<br/>v_comment]
    D --> G[fn_create_*<br/>fn_update_*<br/>fn_delete_*]
    E --> H[tb_user<br/>tb_post<br/>tb_comment]

    F --> I[GraphQL Queries]
    G --> J[GraphQL Mutations]
    H --> K[Internal Storage]

    style C fill:#e8f5e9
    style D fill:#fff3e0
    style E fill:#e3f2fd
```

**Three-Layer Pattern**:

| Layer | Prefix | Purpose | Exposed To |
|-------|--------|---------|------------|
| **Tables** | `tb_*` | Data storage | Internal only |
| **Views** | `v_*` | Read-optimized queries | GraphQL queries |
| **Functions** | `fn_*` | Write operations | GraphQL mutations |

**Example Structure**:

```sql
-- Layer 1: Data storage (internal)
CREATE TABLE tb_user (
    pk_user INTEGER PRIMARY KEY,
    id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    identifier TEXT UNIQUE,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Layer 2: Read-optimized view (exposed to queries)
CREATE VIEW v_user AS
SELECT
    id,  -- Public UUID only
    jsonb_build_object(
        'id', id,
        'name', name,
        'email', email,
        'identifier', identifier,
        'createdAt', created_at
    ) AS data
FROM tb_user;

-- Layer 3: Write functions (exposed to mutations)
CREATE FUNCTION fn_create_user(...) RETURNS JSONB AS $$...$$;
CREATE FUNCTION fn_update_user(...) RETURNS JSONB AS $$...$$;
CREATE FUNCTION fn_delete_user(...) RETURNS JSONB AS $$...$$;
```

---

## Query vs Mutation Characteristics

### Queries (Read Path)

```mermaid
flowchart TD
    A[Query Request] --> B[View Selection]
    B --> C{Filters?}
    C -->|Yes| D[WHERE Clause]
    C -->|No| E[All Rows]
    D --> F[Join Views]
    E --> F
    F --> G[JSONB Extraction]
    G --> H[Rust Field Selection]
    H --> I[Response]

    style B fill:#e8f5e9
    style H fill:#c8e6c9
```

**Characteristics**:

- 📖 **Read-only** - No data modification
- ⚡ **Performance-focused** - Denormalized views, JSONB pre-formatting
- 🔄 **Cacheable** - Same query always returns same result
- 🔒 **Secure by default** - Views expose only allowed fields
- 🚀 **Rust pipeline** - Zero Python serialization

**Example**:

```graphql
# Query (read)
query {
  users(where: { email: { _eq: "john@example.com" } }) {
    id
    name
    email
  }
}
```

---

### Mutations (Write Path)

```mermaid
flowchart TD
    A[Mutation Request] --> B[Input Validation]
    B --> C{Valid?}
    C -->|No| D[Return Error]
    C -->|Yes| E[Call PostgreSQL Function]
    E --> F[Business Logic]
    F --> G{Success?}
    G -->|No| H[ROLLBACK]
    G -->|Yes| I[COMMIT]
    H --> J[Error Response]
    I --> K[Success Response]
    K --> L[Cache Invalidation]

    style E fill:#fff3e0
    style F fill:#ffe0b2
```

**Characteristics**:

- ✏️ **Write operations** - Modify data
- 🔒 **Validated** - Business rules enforced
- 🔄 **Transactional** - ACID guarantees
- 🚫 **Not cacheable** - Side effects
- 📝 **Audit trail** - All changes logged

**Example**:

```graphql
# Mutation (write)
mutation {
  createUser(name: "John Doe", email: "john@example.com") {
    success
    userId
    error
  }
}
```

---

## Integration with Trinity Pattern

CQRS and Trinity Pattern work together:

```mermaid
flowchart TD
    A[Client Request] --> B{Operation Type?}

    B -->|Query| C[View Layer]
    B -->|Mutation| D[Function Layer]

    C --> E[Expose: id UUID]
    D --> F[Accept: id UUID]

    E --> G[Hide: pk_* INTEGER]
    F --> H[Resolve to: pk_* INTEGER]

    G --> I[Security via Views]
    H --> J[Performance via Functions]

    I --> K[Fast Joins]
    J --> K

    style C fill:#e8f5e9
    style D fill:#fff3e0
```

**Views (Read)**:

- Expose only public `id` (UUID)
- Hide internal `pk_*` (INTEGER)
- Use fast `pk_*` joins internally

**Functions (Write)**:

- Accept public `id` (UUID) as input
- Resolve to `pk_*` (INTEGER) internally
- Perform fast operations using `pk_*`

**Example**:

```sql
-- View exposes UUID
CREATE VIEW v_comment AS
SELECT
    c.id,  -- Public UUID
    jsonb_build_object(
        'id', c.id,
        'userId', u.id,  -- Public UUID relationship
        'postId', p.id,  -- Public UUID relationship
        'content', c.content
    ) AS data
FROM tb_comment c
JOIN tb_user u ON u.pk_user = c.pk_user      -- Fast integer join
JOIN tb_post p ON p.pk_post = c.pk_post      -- Fast integer join
;

-- Function accepts UUID, uses pk_* internally
CREATE FUNCTION fn_create_comment(
    p_user_id UUID,      -- Public UUID
    p_post_id UUID,      -- Public UUID
    p_content TEXT
) RETURNS JSONB AS $$
DECLARE
    v_pk_user INTEGER;
    v_pk_post INTEGER;
BEGIN
    -- Resolve UUID → pk_* (once)
    SELECT pk_user INTO v_pk_user FROM tb_user WHERE id = p_user_id;
    SELECT pk_post INTO v_pk_post FROM tb_post WHERE id = p_post_id;

    -- Use fast integer FK
    INSERT INTO tb_comment (pk_user, pk_post, content)
    VALUES (v_pk_user, v_pk_post, p_content);

    RETURN jsonb_build_object('success', true);
END;
$$ LANGUAGE plpgsql;
```

---

## Error Handling in CQRS

### Query Errors (Read Path)

```mermaid
flowchart TD
    A[Query] --> B{View Exists?}
    B -->|No| C[Schema Error]
    B -->|Yes| D{Valid Filters?}
    D -->|No| E[Validation Error]
    D -->|Yes| F[Execute Query]
    F --> G{SQL Error?}
    G -->|Yes| H[Database Error]
    G -->|No| I[Success]

    style C fill:#ffcccc
    style E fill:#ffcccc
    style H fill:#ffcccc
    style I fill:#ccffcc
```

**Query errors are rare**:

- Schema validation catches issues early
- Views are read-only (no data integrity issues)
- Filters validated before SQL execution

---

### Mutation Errors (Write Path)

```mermaid
flowchart TD
    A[Mutation] --> B{Input Valid?}
    B -->|No| C[Return Validation Error JSONB]
    B -->|Yes| D[Call Function]
    D --> E{Business Rules OK?}
    E -->|No| F[Return Business Error JSONB]
    E -->|Yes| G{Database Constraints OK?}
    G -->|No| H[Return Constraint Error JSONB]
    G -->|Yes| I[Return Success JSONB]

    style C fill:#ffe0b2
    style F fill:#ffe0b2
    style H fill:#ffe0b2
    style I fill:#c8e6c9
```

**Mutation error handling is explicit**:

```sql
CREATE FUNCTION fn_create_user(
    p_name TEXT,
    p_email TEXT
) RETURNS JSONB AS $$
BEGIN
    -- Validation error
    IF p_email IS NULL THEN
        RETURN jsonb_build_object(
            'success', false,
            'error', 'Email is required',
            'code', 'VALIDATION_ERROR'
        );
    END IF;

    -- Business rule error
    IF EXISTS (SELECT 1 FROM tb_user WHERE email = p_email) THEN
        RETURN jsonb_build_object(
            'success', false,
            'error', 'Email already exists',
            'code', 'DUPLICATE_EMAIL'
        );
    END IF;

    -- Success
    INSERT INTO tb_user (name, email) VALUES (p_name, p_email);
    RETURN jsonb_build_object('success', true);

EXCEPTION
    WHEN OTHERS THEN
        -- Database error
        RETURN jsonb_build_object(
            'success', false,
            'error', SQLERRM,
            'code', 'DATABASE_ERROR'
        );
END;
$$ LANGUAGE plpgsql;
```

---

## Performance Benefits

### Query Performance

| Aspect | Traditional ORM | FraiseQL CQRS |
|--------|-----------------|---------------|
| **Serialization** | Python objects → JSON | JSONB → Rust → JSON |
| **Joins** | ORM N+1 queries | Denormalized views |
| **Field Selection** | Full objects loaded | Only requested fields |
| **Overhead** | 25-60ms | 0.1-1ms |

**Speedup**: **25-60x faster** than traditional ORM approaches

---

### Mutation Performance

| Aspect | Traditional ORM | FraiseQL CQRS |
|--------|-----------------|---------------|
| **Round-trips** | Multiple queries | Single function call |
| **Validation** | Application layer | Database layer |
| **Transactions** | Manual management | Automatic in function |
| **Audit** | Application code | Database triggers |

**Benefits**:

- ✅ Fewer network round-trips
- ✅ Consistent validation rules
- ✅ Guaranteed transactional integrity
- ✅ Centralized audit logging

---

## Best Practices

### ✅ DO

1. **Use views for all queries**

   ```sql
   CREATE VIEW v_user AS ...  -- ✅ Read-optimized
   ```

2. **Use functions for all mutations**

   ```sql
   CREATE FUNCTION fn_create_user(...) RETURNS JSONB ...  -- ✅ Write-controlled
   ```

3. **Return JSONB from functions**

   ```sql
   RETURN jsonb_build_object('success', true, 'userId', v_id);  -- ✅ Structured
   ```

4. **Expose only public `id` in views**

   ```sql
   SELECT id, data FROM v_user;  -- ✅ UUID only
   ```

5. **Use `pk_*` internally for joins**

   ```sql
   JOIN tb_post p ON p.pk_post = c.pk_post  -- ✅ Fast
   ```

---

### ❌ DON'T

1. **Don't query tables directly**

   ```python
   SELECT * FROM tb_user  -- ❌ Use v_user instead
   ```

2. **Don't write INSERT/UPDATE in application code**

   ```python
   await db.execute("INSERT INTO tb_user ...")  -- ❌ Use fn_create_user()
   ```

3. **Don't expose `pk_*` in views**

   ```sql
   SELECT pk_user, id FROM v_user  -- ❌ Internal only
   ```

4. **Don't use UUID for foreign keys**

   ```sql
   user_id UUID REFERENCES tb_user(id)  -- ❌ Slow, use pk_user
   ```

5. **Don't skip validation in functions**

   ```sql
   INSERT INTO tb_user VALUES (...)  -- ❌ Validate first
   ```

---

## Naming Conventions

FraiseQL uses consistent naming for CQRS components:

| Component | Prefix | Example | Purpose |
|-----------|--------|---------|---------|
| **Tables** | `tb_` | `tb_user` | Data storage |
| **Views** | `v_` | `v_user` | Read operations |
| **Create Functions** | `fn_create_` | `fn_create_user` | Insert new records |
| **Update Functions** | `fn_update_` | `fn_update_user` | Modify existing records |
| **Delete Functions** | `fn_delete_` | `fn_delete_user` | Remove records |
| **Custom Functions** | `fn_` | `fn_promote_user` | Business operations |

**Consistency ensures**:

- Clear intent (table vs view vs function)
- Easy to find related components
- Obvious what each component does

---

## Related Documentation

- [Request Flow](request-flow.md) - How queries and mutations are executed
- [Trinity Pattern](trinity-pattern.md) - Three-identifier database design
- [Type System](type-system.md) - Type mapping across layers
- [Database Patterns](../advanced/database-patterns.md) - More CQRS examples

---

## Summary

FraiseQL's CQRS design provides:

✅ **Clear Separation** - Queries use views, mutations use functions
✅ **Performance** - Read-optimized views with Rust pipeline
✅ **Security** - Views expose only allowed fields, functions control writes
✅ **Reliability** - Business logic in database with ACID guarantees
✅ **Maintainability** - Consistent patterns and naming conventions
✅ **Integration** - Works seamlessly with Trinity Pattern for optimal performance

**Golden Rule**: Never query tables directly or write data without functions.

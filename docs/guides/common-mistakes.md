# Common Mistakes in FraiseQL Implementation

This guide documents the most common mistakes found during Trinity pattern verification, with real examples and fixes.

## 🚨 Security Violations

### Mistake 1: Exposing pk_* in JSONB

**Severity**: ERROR (Security Risk)

**Problem**: Internal primary keys exposed in API responses, enabling enumeration attacks.

**❌ Wrong**:

```sql
CREATE VIEW v_user AS
SELECT
    id,
    jsonb_build_object(
        'pk_user', pk_user,  -- ❌ NEVER expose pk_*
        'id', id,
        'email', email
    ) as data
FROM tb_user;
```

**✅ Correct**:

```sql
CREATE VIEW v_user AS
SELECT
    id,
    jsonb_build_object(
        'id', id,          -- ✅ Only public fields
        'email', email
    ) as data
FROM tb_user;
```

**Why it matters**: pk_* values are sequential and reveal database structure. Exposing them allows attackers to enumerate users, posts, etc.

**Detection**: Automated verification flags this as ERROR.

---

### Mistake 2: Foreign Keys to UUID Instead of INTEGER

**Severity**: ERROR (Performance Issue)

**Problem**: Foreign keys reference UUID columns instead of INTEGER pk_*, causing slow JOINs.

**❌ Wrong**:

```sql
CREATE TABLE tb_post (
    pk_post INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID DEFAULT gen_random_uuid() NOT NULL UNIQUE,
    fk_user UUID REFERENCES tb_user(id),  -- ❌ UUID FK (slow!)
    title TEXT NOT NULL
);
```

**✅ Correct**:

```sql
CREATE TABLE tb_post (
    pk_post INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID DEFAULT gen_random_uuid() NOT NULL UNIQUE,
    fk_user INTEGER REFERENCES tb_user(pk_user),  -- ✅ INTEGER FK (fast!)
    title TEXT NOT NULL
);
```

**Why it matters**: UUID FKs are 4x larger (16 bytes vs 4 bytes) and slower to JOIN.

**Detection**: Automated verification flags this as ERROR.

---

## 🐌 Performance Issues

### Mistake 3: Missing Direct id Column in Views

**Severity**: ERROR (Query Performance)

**Problem**: Views don't include direct `id` column, forcing JSONB queries.

**❌ Wrong**:

```sql
CREATE VIEW v_user AS
SELECT
    jsonb_build_object('id', id, 'name', name) as data
FROM tb_user;
-- ❌ No direct 'id' column for WHERE filtering
```

**✅ Correct**:

```sql
CREATE VIEW v_user AS
SELECT
    id,  -- ✅ Direct column for WHERE id = $1
    jsonb_build_object('id', id, 'name', name) as data
FROM tb_user;
```

**Why it matters**: Without direct `id` column, queries like `WHERE id = $1` can't use indexes.

**Detection**: Automated verification flags this as ERROR.

---

### Mistake 4: Using SERIAL Instead of GENERATED

**Severity**: WARNING (Deprecated Syntax)

**Problem**: Using old PostgreSQL SERIAL syntax instead of modern GENERATED.

**❌ Wrong**:

```sql
CREATE TABLE tb_user (
    pk_user SERIAL PRIMARY KEY,  -- ❌ Deprecated
    id UUID DEFAULT gen_random_uuid() NOT NULL UNIQUE,
    name TEXT NOT NULL
);
```

**✅ Correct**:

```sql
CREATE TABLE tb_user (
    pk_user INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- ✅ Modern
    id UUID DEFAULT gen_random_uuid() NOT NULL UNIQUE,
    name TEXT NOT NULL
);
```

**Why it matters**: SERIAL is deprecated and less flexible than GENERATED.

**Detection**: Automated verification flags this as WARNING.

---

## 🏗️ Architecture Issues

### Mistake 5: Inconsistent Variable Naming

**Severity**: WARNING (Code Quality)

**Problem**: Function variables don't follow naming conventions.

**❌ Wrong**:

```sql
CREATE FUNCTION create_post(...) RETURNS JSONB AS $$
DECLARE
    userId UUID;        -- ❌ camelCase
    user_pk INTEGER;    -- ❌ Missing v_ prefix
    postId UUID;        -- ❌ camelCase + no v_ prefix
BEGIN
    -- ...
END;
$$ LANGUAGE plpgsql;
```

**✅ Correct**:

```sql
CREATE FUNCTION create_post(...) RETURNS JSONB AS $$
DECLARE
    v_user_id UUID;     -- ✅ v_<entity>_id
    v_user_pk INTEGER;  -- ✅ v_<entity>_pk
    v_post_id UUID;     -- ✅ v_<entity>_id
BEGIN
    -- ...
END;
$$ LANGUAGE plpgsql;
```

**Why it matters**: Consistent naming makes code more readable and maintainable.

**Detection**: Automated verification flags this as WARNING.

---

### Mistake 6: Missing Projection Table Sync

**Severity**: ERROR (Data Consistency)

**Problem**: Mutations modify base tables but don't sync projection tables.

**❌ Wrong**:

```sql
CREATE FUNCTION fn_create_user(...) RETURNS JSONB AS $$
BEGIN
    INSERT INTO tb_user (...) VALUES (...);
    -- ❌ Missing sync call!
    RETURN jsonb_build_object('success', true);
END;
$$ LANGUAGE plpgsql;
```

**✅ Correct**:

```sql
CREATE FUNCTION fn_create_user(...) RETURNS JSONB AS $$
DECLARE
    v_user_id UUID;
BEGIN
    INSERT INTO tb_user (...) VALUES (...) RETURNING id INTO v_user_id;
    PERFORM fn_sync_tv_user(v_user_id);  -- ✅ Sync projection table
    RETURN jsonb_build_object('success', true, 'user_id', v_user_id);
END;
$$ LANGUAGE plpgsql;
```

**Why it matters**: Projection tables cache data for fast reads. Without sync, they become stale.

**Detection**: Automated verification flags this as ERROR (with exceptions for DELETE operations).

---

## 📋 Pattern Inconsistencies

### Mistake 7: Missing Trinity Identifiers

**Severity**: ERROR (Pattern Violation)

**Problem**: Tables missing one or more Trinity identifiers.

**❌ Wrong**:

```sql
CREATE TABLE users (  -- ❌ Wrong table name
    id SERIAL PRIMARY KEY,  -- ❌ SERIAL + no pk_ prefix
    username TEXT UNIQUE,
    email TEXT UNIQUE
);
-- ❌ Missing UUID id, no identifier field
```

**✅ Correct**:

```sql
CREATE TABLE tb_user (  -- ✅ tb_ prefix
    pk_user INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- ✅ pk_ prefix
    id UUID DEFAULT gen_random_uuid() NOT NULL UNIQUE,         -- ✅ UUID id
    identifier TEXT UNIQUE,  -- ✅ Human-readable (optional)
    username TEXT UNIQUE,
    email TEXT UNIQUE
);
```

**Why it matters**: Inconsistent patterns make the codebase harder to understand and maintain.

**Detection**: Automated verification flags missing Trinity elements as ERROR.

---

### Mistake 8: Wrong Table Naming

**Severity**: INFO (Convention)

**Problem**: Tables don't follow `tb_<entity>` naming convention.

**❌ Wrong**:

```sql
CREATE TABLE users (...);        -- ❌ Plural
CREATE TABLE User (...);         -- ❌ PascalCase
CREATE TABLE tbl_user (...);     -- ❌ tbl_ prefix
```

**✅ Correct**:

```sql
CREATE TABLE tb_user (...);      -- ✅ tb_ prefix, singular
CREATE TABLE tb_blog_post (...); -- ✅ tb_ prefix, descriptive
```

**Why it matters**: Consistent naming makes the schema self-documenting.

**Detection**: Not currently automated (INFO level documentation issue).

---

## 🔧 Python/Type Issues

### Mistake 9: Python Types Exposing pk_*

**Severity**: ERROR (Security)

**Problem**: Python GraphQL types expose internal pk_* fields.

**❌ Wrong**:

```python
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user")
class User:
    pk_user: int      # ❌ NEVER expose pk_*
    id: ID
    name: str
```

**✅ Correct**:

```python
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user")
class User:
    id: ID          # ✅ Only public fields
    name: str
```

**Why it matters**: Same security issue as exposing pk_* in JSONB.

**Detection**: Automated verification flags this as ERROR.

---

### Mistake 10: Python Types Not Matching JSONB

**Severity**: ERROR (Runtime Errors)

**Problem**: Python type fields don't match JSONB view structure.

**❌ Wrong**:

```sql
-- View
CREATE VIEW v_user AS SELECT id, jsonb_build_object('id', id, 'name', name) as data FROM tb_user;
```

```python
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID
    name: str
    email: str  # ❌ Not in JSONB!
```

**✅ Correct**:

```python
from fraiseql.types import ID

@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID      # ✅ Matches JSONB
    name: str     # ✅ Matches JSONB
```

**Why it matters**: Mismatched types cause runtime GraphQL errors.

**Detection**: Automated verification flags this as ERROR.

---

## 🏭 Real-World Examples Found

During verification, these mistakes were found in actual examples:

### From examples/simple_blog/ (Before Fix)

- ❌ Missing Trinity pattern entirely
- ❌ Using SERIAL instead of GENERATED
- ❌ Foreign keys to id instead of pk_*
- ❌ Views without direct id columns

## 🛠️ Quick Fixes

### Automated Fixes

Automated verification tools are available during development. For released versions, use the manual checklist below.

### Manual Checklist

- [ ] All tables have Trinity identifiers
- [ ] Foreign keys reference pk_* columns
- [ ] Views have direct id columns
- [ ] JSONB never contains pk_* fields
- [ ] Functions call sync for tv_* tables
- [ ] Python types match JSONB structure
- [ ] Variable naming follows conventions

## 📚 Prevention

1. **Use the template**: Start new examples from `examples/_TEMPLATE/`
2. **Run verification early**: Check compliance during development
3. **Follow the guide**: Reference `docs/guides/trinity-pattern-guide.md`
4. **CI enforcement**: PRs automatically verify pattern compliance

## 🔗 Related Resources

- [Trinity Pattern Guide](./trinity-pattern-guide.md)
- [Migration Guide](../archive/mutations/migration-guide.md)
- [Verification Tools](../archive/testing/developer-guide.md)
- [Example Template](../../examples/_TEMPLATE/)

Remember: These patterns exist for good reasons. Following them ensures your FraiseQL implementation is secure, performant, and maintainable.

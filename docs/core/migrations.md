---
title: Database Migrations
description: Database schema migrations and version management
tags:
  - migrations
  - schema
  - database
  - versioning
  - DDL
---

# Database Migrations

> **Manage your database schema with confidence using FraiseQL's integrated migration system**

FraiseQL provides a robust migration management system through the `fraiseql migrate` CLI, making it easy to evolve your database schema over time while maintaining consistency across development, staging, and production environments.

---

## Overview

### Why Migrations?

Database migrations allow you to:

- **Version control** your database schema alongside your code
- **Collaborate** with team members without schema conflicts
- **Deploy** confidently knowing the database state is predictable
- **Roll back** changes if something goes wrong
- **Document** schema changes over time

### FraiseQL's Approach

FraiseQL's migration system is powered by **confiture** (https://github.com/fraiseql/confiture):

- **Simple**: plain SQL migrations (`.up.sql` / `.down.sql`), or Python when you need it
- **Integrated**: Built into the `fraiseql` CLI
- **Safe**: each migration runs in a transaction, applied migrations are tracked so
  they never run twice, and concurrent `migrate up` runs are serialized by a lock
- **Flexible**: Works with any PostgreSQL schema

---

## Quick Start

### Initialize Migrations

```bash
# Navigate to your project
cd my-fraiseql-project

# Initialize migration system
fraiseql migrate init
```

This creates a `db/` directory:

```text
db/
├── README.md
├── environments/
│   └── local.yaml        # database connection for `migrate up/down/status`
├── migrations/           # migration files
├── schema/
│   ├── 00_common/extensions.sql
│   └── 10_tables/example.sql
└── seeds/
    ├── common/
    ├── development/
    └── test/
```

`db/environments/local.yaml` holds the database connection:

```yaml
name: local
include_dirs:
  - db/schema/00_common
  - db/schema/10_tables
exclude_dirs: []

database_url: postgresql://postgres:postgres@localhost:5432/fraiseql_local
```

Edit `database_url` to point at your database. Older projects have a `database:`
mapping (`host`, `port`, `database`, `user`, `password`) instead; it still works,
and FraiseQL turns it into a URL for you.

### Create Your First Migration

A migration is either a pair of SQL files or a Python file. Both kinds can live in
the same directory and are applied in version order.

**SQL migration.** Write two files that share a version and a name, the version
being a timestamp:

```text
db/migrations/20260115103000_initial_schema.up.sql
db/migrations/20260115103000_initial_schema.down.sql
```

```sql
-- 20260115103000_initial_schema.up.sql

-- Users table
CREATE TABLE tb_user (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Posts table
CREATE TABLE tb_post (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    author_id UUID NOT NULL REFERENCES tb_user(id),
    published BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

```sql
-- 20260115103000_initial_schema.down.sql
DROP TABLE tb_post;
DROP TABLE tb_user;
```

Every `.up.sql` needs its `.down.sql`: `migrate up` refuses to run without it.

**Python migration.** `fraiseql migrate create` writes one for you:

```bash
fraiseql migrate create initial_schema
# Creates db/migrations/20260115103000_initial_schema.py
```

```python
from confiture.models.migration import Migration


class InitialSchema(Migration):
    """Migration: initial_schema."""

    version = "20260115103000"
    name = "initial_schema"

    def up(self) -> None:
        self.execute("CREATE TABLE tb_user (...)")

    def down(self) -> None:
        self.execute("DROP TABLE tb_user")
```

### Apply the Migration

```bash
fraiseql migrate up

# ⚡ Applied 20260115103000_initial_schema ✅
#
# ✅ Successfully applied 1 migration(s)!
```

---

## Migration Commands

`up`, `down` and `status` read the connection from `--config`
(default `db/environments/local.yaml`), and every command except `init` takes
`--migrations-dir` (default `db/migrations`). Use another environment file to
target another database:

```bash
fraiseql migrate up --config db/environments/production.yaml
```

### `fraiseql migrate init [PATH]`

Create the `db/` layout shown above in `PATH` (default: the current directory).
If `db/` already exists, it asks before overwriting files.

### `fraiseql migrate create <name>`

Create a Python migration named `<timestamp>_<name>.py`, with a `Migration`
subclass whose `up()` and `down()` you fill in.

```bash
fraiseql migrate create add_comments_table
```

**Naming conventions:**

- Use descriptive names: `add_comments_table`, `add_email_index`
- Use snake_case
- Be specific: `add_user_bio_column` not `update_users`

### `fraiseql migrate up`

Apply pending migrations, oldest first.

```bash
# Apply every pending migration
fraiseql migrate up

# Apply pending migrations up to and including this version
fraiseql migrate up --target 20260116142000
```

If a migration fails, its transaction is rolled back, the command stops and exits
non-zero, and migrations applied before it in the same run stay applied.

### `fraiseql migrate down`

Roll back applied migrations, newest first, after asking for confirmation.

```bash
# Roll back the most recent migration
fraiseql migrate down

# Roll back the last 2 migrations
fraiseql migrate down --steps 2
```

**⚠️ Warning**: Only use `down` in development. In production, prefer forward-only migrations.

### `fraiseql migrate status`

List every migration file and whether it is applied.

```bash
fraiseql migrate status
```

```text
                 FraiseQL Migrations
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Version        ┃ Name               ┃ Status     ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ 20260115103000 │ initial_schema     │ ✅ applied │
│ 20260116142000 │ add_comments_table │ ⏳ pending │
└────────────────┴────────────────────┴────────────┘

📊 Total: 2 migrations (1 applied, 1 pending)
```

If the database can't be reached, it still lists the files, with status `unknown`.

---

## Migration File Structure

### Basic Structure

```sql
-- 20260115103000_add_user_profile.up.sql
--
-- Adds support for user profiles with bio and avatar.

-- Create table
CREATE TABLE tb_user_profile (
    user_id UUID PRIMARY KEY REFERENCES tb_user(id) ON DELETE CASCADE,
    bio TEXT,
    avatar_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Add index
CREATE INDEX idx_user_profile_user ON tb_user_profile(user_id);

-- Add initial data (if needed)
INSERT INTO tb_user_profile (user_id, bio)
SELECT id, 'Default bio'
FROM tb_user
WHERE created_at < NOW() - INTERVAL '1 day';
```

```sql
-- 20260115103000_add_user_profile.down.sql
DROP TABLE tb_user_profile;
```

### Migration Best Practices

1. **One purpose per migration**

   ```sql
   -- ✅ Good: Focused on one change
   -- 20260120090000_add_email_verification.up.sql

   ALTER TABLE tb_user ADD COLUMN email_verified BOOLEAN DEFAULT FALSE;
   CREATE INDEX idx_user_email_verified ON tb_user(email_verified);
   ```

   ```sql
   -- ❌ Bad: Multiple unrelated changes
   -- 20260120090000_various_updates.up.sql

   ALTER TABLE tb_user ADD COLUMN email_verified BOOLEAN;
   CREATE TABLE tb_settings (...);  -- Unrelated!
   ALTER TABLE tb_post ADD COLUMN views INTEGER;  -- Also unrelated!
   ```

2. **Write a real `down`**

   The `.down.sql` file (or `down()` method) should undo exactly what `up` did,
   so `fraiseql migrate down` leaves the schema as it was.

3. **Handle existing data**

   ```sql
   -- 20260125110000_make_email_required.up.sql

   -- First, ensure all existing users have emails
   UPDATE tb_user SET email = username || '@example.com'
   WHERE email IS NULL;

   -- Now make it NOT NULL
   ALTER TABLE tb_user ALTER COLUMN email SET NOT NULL;
   ```

---

## CQRS Migrations

When using FraiseQL's CQRS pattern, your migrations will include both command (`tb_*`) and query (`tv_*`) tables.

### Example: Adding a CQRS Entity

```sql
-- 20260201100000_add_comments.up.sql

-- ============================================================================
-- COMMAND SIDE: Normalized table for writes
-- ============================================================================

CREATE TABLE tb_comment (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_id UUID NOT NULL REFERENCES tb_post(id) ON DELETE CASCADE,
    author_id UUID NOT NULL REFERENCES tb_user(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_comment_post ON tb_comment(post_id);
CREATE INDEX idx_comment_author ON tb_comment(author_id);

-- ============================================================================
-- QUERY SIDE: Denormalized table for reads
-- ============================================================================

CREATE TABLE tv_comment (
    id UUID PRIMARY KEY,
    data JSONB NOT NULL,  -- Contains comment + author info
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- GIN index for fast JSONB queries
CREATE INDEX idx_tv_comment_data ON tv_comment USING GIN(data);

-- ============================================================================
-- SYNC TRACKING (optional but recommended)
-- ============================================================================

-- Track when each entity was last synced
CREATE TABLE sync_history (
    entity_type TEXT NOT NULL,
    entity_id UUID NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (entity_type, entity_id)
);

CREATE INDEX idx_sync_history_synced ON sync_history(synced_at DESC);
```

### Initial Data Sync

After creating `tv_*` tables, you'll need to perform an initial sync:

```python
# In your application startup
from your_app.sync import EntitySync

@app.on_event("startup")
async def initial_sync():
    sync = EntitySync(db_pool)

    # Sync all existing data to query side
    await sync.sync_all_comments()
    logger.info("Initial comment sync complete")
```

---

## Production Deployment

### Safe Production Migrations

1. **Always test migrations first**

   ```bash
   # Apply against a development or staging database
   fraiseql migrate up --config db/environments/staging.yaml

   # Verify application works
   ./test_suite.sh
   ```

2. **Don't add `BEGIN` / `COMMIT`**

   Each migration already runs in its own transaction, and a failure rolls back
   everything that migration did. A `COMMIT` inside the file would end that
   transaction early.

3. **Run what can't be in a transaction from a Python migration**

   `CREATE INDEX CONCURRENTLY` doesn't lock writes, but PostgreSQL refuses to run
   it inside a transaction. Set `transactional = False` on a Python migration:

   ```python
   class AddPostCreatedIndex(Migration):
       version = "20260301120000"
       name = "add_post_created_index"
       transactional = False  # required for CONCURRENTLY

       def up(self) -> None:
           self.execute(
               "CREATE INDEX CONCURRENTLY idx_post_created ON tb_post(created_at)"
           )

       def down(self) -> None:
           self.execute("DROP INDEX CONCURRENTLY idx_post_created")
   ```

   A non-transactional migration that fails midway is not rolled back, so keep it
   to one statement.

4. **Have a rollback plan**

   ```bash
   # Before applying migration
   pg_dump -U user -d database > backup_before_migration.sql

   # Apply migration
   fraiseql migrate up --config db/environments/production.yaml

   # If something goes wrong
   psql -U user -d database < backup_before_migration.sql
   ```

### Deployment Process

```bash
#!/bin/bash
# deploy.sh - Safe production deployment

set -e  # Exit on error

CONFIG=db/environments/production.yaml

echo "1. Creating database backup..."
pg_dump -U $DB_USER -d $DB_NAME > backup_$(date +%Y%m%d_%H%M%S).sql

echo "2. Running migrations..."
fraiseql migrate up --config $CONFIG

echo "3. Verifying database state..."
fraiseql migrate status --config $CONFIG

echo "4. Running application tests..."
./test_suite.sh

echo "✓ Deployment complete!"
```

---

## Troubleshooting

### Migration Modified After Being Applied

**Problem**: An applied migration file was edited. Recent confiture releases
compare each applied file with the checksum recorded when it ran, and refuse to
continue:

```text
Error: Checksum verification failed for 1 migration(s): 20260115103000.
Migration files have been modified after application.
```

**Solution**: Restore the applied file, and make the change in a new migration
instead.

### Migration Failed

**Problem**: `fraiseql migrate up` stopped with an error.

```text
Error: Failed to apply migration 20260201100000 (add_comments): SQL execution failed | ...
```

**Solution**: The failed migration's transaction was rolled back, so nothing it
did remains, and it isn't recorded as applied. Fix the file and run
`fraiseql migrate up` again. Migrations applied before it in the same run stay
applied.

(A migration with `transactional = False` is the exception: check by hand what it
left behind before re-running it.)

### Migration Tracking Out of Sync

**Problem**: The recorded migrations and the actual schema don't match.

**Solution**: Applied migrations are recorded in the `tb_confiture` table. Inspect it
before changing anything:

```sql
SELECT * FROM tb_confiture;
```

Prefer fixing the schema with a new migration over editing this table by hand.

---

## Advanced Patterns

### Data Migrations

When you need to migrate large amounts of data:

```sql
-- 20260310090000_migrate_user_preferences.up.sql

-- Create new table
CREATE TABLE tb_user_preferences (
    user_id UUID PRIMARY KEY REFERENCES tb_user(id),
    preferences JSONB NOT NULL DEFAULT '{}'
);

-- Migrate data in batches (for large datasets)
DO $$
DECLARE
    batch_size INTEGER := 1000;
    offset_val INTEGER := 0;
    rows_affected INTEGER;
BEGIN
    LOOP
        INSERT INTO tb_user_preferences (user_id, preferences)
        SELECT id, jsonb_build_object('theme', 'light', 'language', 'en')
        FROM tb_user
        ORDER BY id
        LIMIT batch_size OFFSET offset_val;

        GET DIAGNOSTICS rows_affected = ROW_COUNT;
        EXIT WHEN rows_affected = 0;

        offset_val := offset_val + batch_size;
        RAISE NOTICE 'Migrated % users', offset_val;
    END LOOP;
END $$;
```

### Zero-Downtime Migrations

For critical production systems:

```sql
-- Step 1: Add new column (nullable)
ALTER TABLE tb_user ADD COLUMN new_email TEXT;

-- Step 2: Backfill data (in batches, over time)
-- (Done by application or background job)

-- Step 3: Make column required (in next migration, after backfill)
ALTER TABLE tb_user ALTER COLUMN new_email SET NOT NULL;

-- Step 4: Drop old column (in yet another migration)
ALTER TABLE tb_user DROP COLUMN old_email;
```

---

## Integration with FraiseQL Features

### CASCADE Rules

When you create foreign keys, consider CASCADE implications:

```sql
-- 20260320100000_add_comments.up.sql

CREATE TABLE tb_comment (
    id UUID PRIMARY KEY,
    post_id UUID NOT NULL REFERENCES tb_post(id) ON DELETE CASCADE,
    -- ☝️ When post deleted, comments are automatically deleted
    author_id UUID NOT NULL REFERENCES tb_user(id) ON DELETE SET NULL
    -- ☝️ When user deleted, comments remain but author_id becomes NULL
);
```

FraiseQL's auto-CASCADE will detect these relationships and set up cache invalidation rules automatically.

### IVM Setup

After migrations that add tb_/tv_ pairs, update your IVM setup:

```python
# In application startup
from fraiseql.ivm import setup_auto_ivm

@app.on_event("startup")
async def setup_ivm():
    # Analyze schema and setup IVM
    recommendation = await setup_auto_ivm(db_pool, verbose=True)

    # Apply recommended SQL
    async with db_pool.connection() as conn:
        await conn.execute(recommendation.setup_sql)
```

---

## See Also

- Complete CQRS Example (../../examples/complete_cqrs_blog/)
- [CASCADE Best Practices](../guides/cascade-best-practices.md)
- [Explicit Sync Guide](./explicit-sync.md)
- [Database Patterns](../advanced/database-patterns.md)
- [confiture on GitHub](https://github.com/fraiseql/confiture) - Migration library

---

**Last Updated**: 2026-10-17
**FraiseQL Version**: 1.27.0+

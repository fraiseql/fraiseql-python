---
title: PostgreSQL Extensions
description: Required and optional PostgreSQL extensions for FraiseQL
tags:
  - PostgreSQL
  - extensions
  - pgvector
  - pg_trgm
  - database
---

# PostgreSQL Extensions

> **FraiseQL integrates with PostgreSQL extensions for maximum performance**

FraiseQL is designed to work with several PostgreSQL extensions that enhance performance and functionality. This guide covers installation and configuration of these extensions.

---

## Overview

### Available Extensions

FraiseQL works with these PostgreSQL extensions:

| Extension | Purpose | Required? | Performance Impact |
|-----------|---------|-----------|-------------------|
| **jsonb_ivm** | Incremental View Maintenance | Optional | 10-100x faster sync |
| **pg_fraiseql_cache** | Cache invalidation with CASCADE | Optional | Automatic invalidation |
| **uuid-ossp** | UUID generation | Recommended | Standard IDs |

All extensions are **optional** - FraiseQL will detect and use them if available, or fall back to pure SQL implementations.

---

## jsonb_ivm Extension

### What It Does

The `jsonb_ivm` extension provides **incremental JSONB view maintenance** for CQRS architectures:

```sql
-- Instead of rebuilding entire JSONB:
UPDATE tv_user SET data = (
  SELECT jsonb_build_object(...)  -- Rebuilds all fields (slow)
  FROM tb_user WHERE id = $1
);

-- With jsonb_ivm, merge only changed fields:
UPDATE tv_user SET data = jsonb_merge_shallow(
  data,  -- Keep unchanged fields
  (SELECT jsonb_build_object('name', name) FROM tb_user WHERE id = $1)  -- Only changed
);
```

**Performance**: 10-100x faster for partial updates!

### Installation from Source

The `jsonb_ivm` extension is available on GitHub:

```bash
# Clone the repository
git clone https://github.com/fraiseql/jsonb_ivm.git
cd jsonb_ivm

# Build and install (requires PostgreSQL development headers)
make
sudo make install

# Verify installation
psql -d your_database -c "CREATE EXTENSION jsonb_ivm;"
```

### Installation Requirements

```bash
# Ubuntu/Debian
sudo apt-get install postgresql-server-dev-17 build-essential

# macOS with Homebrew
brew install postgresql@17

# Arch Linux
sudo pacman -S postgresql-libs base-devel
```

### Using jsonb_ivm in Docker

Add to your `Dockerfile` or `docker-compose.yml`:

```dockerfile
FROM postgres:17.5

# Install build tools
RUN apt-get update && apt-get install -y \
    postgresql-server-dev-17 \
    build-essential \
    git \
    ca-certificates

# Clone and install jsonb_ivm extension
RUN git clone https://github.com/fraiseql/jsonb_ivm.git /tmp/jsonb_ivm && \
    cd /tmp/jsonb_ivm && \
    make && make install

# Clean up
RUN apt-get remove -y build-essential git && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* /tmp/jsonb_ivm
```

For development, you can also use a local copy:

```yaml
# docker-compose.yml
services:
  postgres:
    build:
      context: .
      dockerfile: Dockerfile.postgres
      args:
        - JSONB_IVM_VERSION=main  # or specific tag/commit
```

### Enable in Database

```sql
-- Enable extension (run once per database)
CREATE EXTENSION IF NOT EXISTS jsonb_ivm;

-- Verify installation
SELECT * FROM pg_extension WHERE extname = 'jsonb_ivm';

-- Check version
SELECT extversion FROM pg_extension WHERE extname = 'jsonb_ivm';
-- Expected: 1.1
```

### Using with FraiseQL

FraiseQL automatically detects and uses `jsonb_ivm`:

```python
from fraiseql.ivm import setup_auto_ivm

@app.on_event("startup")
async def setup():
    # Analyzes tv_ tables and recommends IVM strategy
    recommendation = await setup_auto_ivm(
        db_pool,
        verbose=True  # Shows detected extensions
    )

    # Output:
    # ✓ Detected jsonb_ivm v1.1
    # IVM Analysis: 5/8 tables benefit from incremental updates (est. 25.3x speedup)
```

---

## pg_fraiseql_cache Extension

### What It Does

The `pg_fraiseql_cache` extension provides **intelligent cache invalidation** with CASCADE rules:

```sql
-- When user changes, automatically invalidate related caches:
SELECT cache_invalidate('user', '123');

-- CASCADE automatically invalidates:
-- - user:123
-- - user:123:posts
-- - post:* where author_id = 123
```

### Installation

The extension is available on GitHub:

```bash
# Clone the repository
git clone https://github.com/fraiseql/pg_fraiseql_cache.git
cd pg_fraiseql_cache

# Build and install
make
sudo make install

# Enable in database
psql -d your_database -c "CREATE EXTENSION pg_fraiseql_cache;"
```

### Using with FraiseQL

```python
from fraiseql.caching import setup_auto_cascade_rules

@app.on_event("startup")
async def setup():
    # Auto-detect CASCADE rules from GraphQL schema
    await setup_auto_cascade_rules(
        cache=app.cache,
        schema=app.schema,
        verbose=True
    )

    # Output:
    # CASCADE: Analyzing GraphQL schema...
    # CASCADE: Detected relationship: User -> Post (field: posts)
    # CASCADE: Created 3 CASCADE rules
```

---

## Installation Methods

### Method 1: Docker (Recommended for Development)

The easiest way is to use Docker with pre-built extensions:

```yaml
# docker-compose.yml
version: '3.8'

services:
  postgres:
    build:
      context: .
      dockerfile: Dockerfile.postgres
    environment:
      POSTGRES_USER: fraiseql
      POSTGRES_PASSWORD: fraiseql
      POSTGRES_DB: myapp
    ports:
      - "5432:5432"
```

```dockerfile
# Dockerfile.postgres
FROM postgres:17.5

# Install dependencies
RUN apt-get update && apt-get install -y \
    postgresql-server-dev-17 \
    build-essential \
    git \
    ca-certificates

# Clone and install jsonb_ivm
RUN git clone https://github.com/fraiseql/jsonb_ivm.git /tmp/jsonb_ivm && \
    cd /tmp/jsonb_ivm && \
    make && make install

# Clone and install pg_fraiseql_cache
RUN git clone https://github.com/fraiseql/pg_fraiseql_cache.git /tmp/pg_fraiseql_cache && \
    cd /tmp/pg_fraiseql_cache && \
    make && make install

# Clean up
RUN apt-get remove -y build-essential git && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* /tmp/*
```

### Method 2: System Installation

For production or system-wide installation:

```bash
# Clone and install jsonb_ivm
git clone https://github.com/fraiseql/jsonb_ivm.git
cd jsonb_ivm
make && sudo make install
cd ..

# Clone and install pg_fraiseql_cache
git clone https://github.com/fraiseql/pg_fraiseql_cache.git
cd pg_fraiseql_cache
make && sudo make install
cd ..

# Enable in your database
psql -d your_database <<EOF
CREATE EXTENSION IF NOT EXISTS jsonb_ivm;
CREATE EXTENSION IF NOT EXISTS pg_fraiseql_cache;
EOF
```

### Method 3: Development with Hot Reload

For active development:

```bash
# Clone and build in debug mode
git clone https://github.com/fraiseql/jsonb_ivm.git
cd jsonb_ivm
make clean && make CFLAGS="-g -O0"
sudo make install

# Reload in PostgreSQL
psql -d your_database <<EOF
DROP EXTENSION IF EXISTS jsonb_ivm CASCADE;
CREATE EXTENSION jsonb_ivm;
EOF
```

---

## Docker Setup

### Complete Example

Here's a complete `docker-compose.yml` with all extensions:

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:17.5
    environment:
      POSTGRES_USER: fraiseql
      POSTGRES_PASSWORD: fraiseql
      POSTGRES_DB: myapp
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init_extensions.sql:/docker-entrypoint-initdb.d/01_extensions.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U fraiseql"]
      interval: 5s
      timeout: 5s
      retries: 5

  app:
    build: .
    environment:
      DATABASE_URL: postgresql://fraiseql:fraiseql@postgres:5432/myapp
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "8000:8000"

volumes:
  postgres_data:
```

```sql
-- init_extensions.sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS jsonb_ivm;
CREATE EXTENSION IF NOT EXISTS pg_fraiseql_cache;
```

---

## Verification

### Check Installed Extensions

```sql
-- List all installed extensions
SELECT extname, extversion, extrelocatable
FROM pg_extension
WHERE extname IN ('jsonb_ivm', 'pg_fraiseql_cache', 'uuid-ossp')
ORDER BY extname;
```

Expected output:

```
    extname       | extversion | extrelocatable
------------------+------------+----------------
 jsonb_ivm        | 1.1        | t
 pg_fraiseql_cache| 1.0        | t
 uuid-ossp        | 1.1        | t
```

### Test jsonb_ivm

```sql
-- Test jsonb_merge_shallow function
SELECT jsonb_merge_shallow(
  '{"name": "Alice", "age": 30, "city": "NYC"}'::jsonb,
  '{"age": 31}'::jsonb
);

-- Expected: {"name": "Alice", "age": 31, "city": "NYC"}
-- (only age was updated, other fields kept)
```

### Test from FraiseQL

```python
# test_extensions.py
import asyncio
from fraiseql.ivm import IVMAnalyzer

async def test_extensions():
    analyzer = IVMAnalyzer(db_pool)

    # Check jsonb_ivm
    has_ivm = await analyzer.check_extension()
    print(f"jsonb_ivm available: {has_ivm}")
    print(f"Version: {analyzer.extension_version}")

test_extensions()
```

---

## Troubleshooting

### Extension Not Found

**Problem**: `ERROR: could not open extension control file`

**Solution**:

```bash
# Find PostgreSQL extension directory
pg_config --sharedir

# Expected: /usr/share/postgresql/17

# Check if extension files are there
ls /usr/share/postgresql/17/extension/jsonb_ivm*

# If not, reinstall:
cd /home/lionel/code/jsonb_ivm
sudo make install
```

### Build Errors

**Problem**: `fatal error: postgres.h: No such file or directory`

**Solution**: Install PostgreSQL development headers

```bash
# Ubuntu/Debian
sudo apt-get install postgresql-server-dev-17

# macOS
brew install postgresql@17

# Arch Linux
sudo pacman -S postgresql-libs
```

### Permission Errors

**Problem**: `ERROR: permission denied to create extension`

**Solution**: You need superuser privileges

```bash
# Connect as superuser
psql -U postgres -d your_database

# Then create extension
CREATE EXTENSION jsonb_ivm;

# Grant usage to your app user
GRANT USAGE ON SCHEMA public TO fraiseql_user;
```

### Version Mismatch

**Problem**: Extension version doesn't match after update

**Solution**: Upgrade the extension

```sql
-- Check current version
SELECT extversion FROM pg_extension WHERE extname = 'jsonb_ivm';

-- Upgrade to latest
ALTER EXTENSION jsonb_ivm UPDATE TO '1.1';

-- Or reinstall
DROP EXTENSION jsonb_ivm CASCADE;
CREATE EXTENSION jsonb_ivm;
```

---

## Performance Impact

### With vs Without Extensions

| Operation | Without Extensions | With jsonb_ivm | Speedup |
|-----------|-------------------|----------------|---------|
| Update single field | 15ms (full rebuild) | 1.2ms (merge) | **12x** |
| Update 10 records | 150ms | 15ms | **10x** |
| Bulk sync 1000 records | 15s | 200ms | **75x** |

### When Extensions Aren't Available

FraiseQL gracefully falls back to pure SQL:

```python
# FraiseQL checks for jsonb_ivm
if has_jsonb_ivm:
    # Use fast incremental merge
    sql = "UPDATE tv_user SET data = jsonb_merge_shallow(data, $1)"
else:
    # Fall back to full rebuild (slower but works)
    sql = "UPDATE tv_user SET data = $1"
```

You'll see a warning in logs:

```
[WARNING] jsonb_ivm extension not installed, using fallback (slower)
[INFO] For better performance, install jsonb_ivm: see docs/core/postgresql-extensions.md
```

---

## See Also

- [Explicit Sync Guide](./explicit-sync.md) - How sync uses jsonb_ivm
- [CASCADE Best Practices](../guides/cascade-best-practices.md) - Cascade patterns
- [Migrations Guide](./migrations.md) - Setting up databases with confiture

### GitHub Repositories

- [jsonb_ivm](https://github.com/fraiseql/jsonb_ivm) - Incremental View Maintenance extension
- [pg_fraiseql_cache](https://github.com/fraiseql/pg_fraiseql_cache) - Cache invalidation extension
- [confiture](https://github.com/fraiseql/confiture) - Migration management library

---

**Last Updated**: 2025-10-11
**FraiseQL Version**: 0.1.0+

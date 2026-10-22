# DDL Organization in FraiseQL

> **Best practices for structuring database schemas using confiture-style numbered prefixes**

FraiseQL embraces [confiture](https://github.com/fraiseql/confiture)'s deterministic file ordering approach for organizing database DDL (Data Definition Language) files. This guide explains how to structure your database schema files for projects of any size.

---

## Quick Start

**Choose your project size:**

| Size | Files | Structure | When to Use |
|------|-------|-----------|-------------|
| **XS** | 1 file | `0_schema/schema.sql` | Prototypes, demos, microservices |
| **S** | <20 | `0_schema/01_tables.sql` | Small blogs, simple APIs |
| **M** | 20-100 | `0_schema/01_tables/010_users.sql` | Production APIs, SaaS apps |
| **L** | 100-500 | `0_schema/01_core/010_users/0101_user.sql` | Enterprise apps, complex domains |
| **XL** | 500+ | `0_schema/00_common/000_security/00001_roles.sql` | Multi-tenant, platforms |

**Key principle**: Start small, grow structure as needed.

---

## Philosophy

### Deterministic Ordering

FraiseQL uses **numbered prefixes** to control SQL execution order through alphabetical sorting. This approach:

- ✅ **Explicit**: Dependencies are clear from file names
- ✅ **Scalable**: Works for 5 files or 500 files
- ✅ **Predictable**: Same order every time
- ✅ **Flexible**: Easy to insert new files without renumbering

### Number of Digits = Depth Level

The key insight from confiture: **match numbering to directory depth**

```
XS (Extra Small) → Single file     (schema.sql)
S  (Small)       → Flat            (0_schema/01_tables.sql)
M  (Medium)      → 1 level deep    (0_schema/01_tables/010_users.sql)
L  (Large)       → 2 levels deep   (0_schema/01_domain/010_users/0101_user.sql)
XL (Extra Large) → 3+ levels deep  (0_schema/00_common/000_security/0000_roles/00001_admin.sql)
```

**Key principle**: **Number of digits = depth level**

- **Level 1** (top-level directories): **1 digit** (`0_schema/`, `1_seed/`)
- **Level 2** (subdirectories): **2 digits** (`01_tables/`, `10_users/`)
- **Level 3** (sub-subdirectories): **3 digits** (`010_user/`, `101_profile/`)
- **Level 4** (files): **4 digits** (`0101_tb_user.sql`, `1011_tb_profile.sql`)
- **Level 5+**: Add one digit per level

**Visual example with materialized paths:**

```
db/
└── 0_schema/                      ← Level 1 (1 digit: "0")
    ├── 00_common/                 ← Level 2 (2 digits: "0" + "0")
    │   └── 001_extensions.sql     ← Level 3 (3 digits: "0" + "0" + "1")
    └── 01_tables/                 ← Level 2 (2 digits: "0" + "1")
        ├── 010_users/             ← Level 3 (3 digits: "0" + "1" + "0")
        │   └── 0101_tb_user.sql   ← Level 4 (4 digits: "0" + "1" + "0" + "1")
        └── 011_posts/             ← Level 3 (3 digits: "0" + "1" + "1")
            └── 0111_tb_post.sql   ← Level 4 (4 digits: "0" + "1" + "1" + "1")
```

**Reading the path**: File `0101_tb_user.sql` decodes as:

- `0` = in `0_schema/` directory (level 1)
- `01` = in `01_tables/` subdirectory (level 2)
- `010` = in `010_users/` subdirectory (level 3)
- `0101` = this file (level 4)
- **Full path**: `0_schema/01_tables/010_users/0101_tb_user.sql`

---

## Size-Based Organization

### XS Projects (Single File, <100 lines)

**Use a single schema file**:

```
db/
├── 0_schema/
│   └── schema.sql     # Everything in one file
└── 1_seed_dev/
    └── seed_data.sql  # Optional: development seed data
```

**When to use**: Prototypes, demos, learning examples, microservices with 1-2 tables

**Example**: Simple todo app with `users` and `todos` tables

**Numbering logic**:

- **Level 1** (top-level directories): **1 digit** - `0_schema/`, `1_seed_dev/`
- Files inside have no numbering prefix when there's only one file per directory

---

### S Projects (Flat, <20 files)

**Use flat structure with numbered files**:

```
db/
├── 0_schema/
│   ├── 00_extensions.sql
│   ├── 01_tables.sql
│   ├── 02_views.sql
│   ├── 03_functions.sql
│   └── 04_triggers.sql
├── 10_seed_common/
│   └── 11_base_data.sql
└── 20_seed_dev/
    └── 21_test_data.sql
```

**When to use**: Small blogs, simple APIs, basic CRUD apps

**Numbering logic**:

- **Level 1** (directories): **1-2 digits** - `0_schema/`, `10_seed_common/`, `20_seed_dev/`
- **Level 2** (files): **2-3 digits** - Inherits parent's prefix:
  - Within `0_schema/`: `00_`, `01_`, `02_`, `03_`, `04_` (inherits `0` from parent)
  - Within seed directories: `11_`, `21_`, etc. (inherits first digit from parent)

---

### M Projects (1 level deep, 20-100 files)

**Use subdirectories to organize related files**:

```
db/
├── 0_schema/
│   ├── 00_common/
│   │   └── 001_extensions.sql
│   ├── 01_write/                # Command side (tb_* tables + indexes)
│   │   ├── 010_tb_user.sql      # tb_user + indexes
│   │   ├── 011_tb_post.sql      # tb_post + indexes
│   │   └── 012_tb_comment.sql   # tb_comment + indexes
│   ├── 02_views/
│   │   ├── 020_tv_user.sql
│   │   └── 021_tv_post.sql
│   └── 03_functions/
│       └── 030_fn_user_mutations.sql
├── 10_seed_common/
│   └── 11_base_data.sql
└── 20_seed_dev/
    └── 21_test_users.sql
```

**When to use**: Production APIs, SaaS applications, standard business apps

**Numbering logic**:

- **Level 1** (directories): **1-2 digits** - `0_schema/`, `10_seed_common/`, `20_seed_dev/`
- **Level 2** (subdirectories): **2 digits** - `00_common/`, `01_tables/`, `02_views/`, `03_functions/`
- **Level 3** (files in schema): **3 digits** - Inherits parent's 2 digits + adds 1, with descriptive suffixes
- **Level 2** (files in seed): **2 digits** - Inherits first digit from parent

---

### L Projects (2 levels deep, 100-500 files)

**Use 2-digit prefixes** at each level (3 levels total):

```
db/
├── 0_schema/
│   ├── 00_common/
│   │   ├── 000_security/
│   │   │   ├── 0001_roles.sql
│   │   │   └── 0002_schemas.sql
│   │   ├── 001_extensions/
│   │   │   └── 0011_extensions.sql
│   │   └── 002_types/
│   │       └── 0021_enums.sql
│   │
│   ├── 01_core_domain/
│   │   ├── 010_users/
│   │   │   ├── 0101_user_table.sql
│   │   │   └── 0102_user_profile.sql
│   │   ├── 011_content/
│   │   │   ├── 0111_posts_table.sql
│   │   │   └── 0112_comments_table.sql
│   │   └── 012_analytics/
│   │       └── 0121_events_table.sql
│   │
│   ├── 02_views/
│   │   ├── 020_user_views/
│   │   │   └── 0201_user_stats.sql
│   │   └── 021_content_views/
│   │       └── 0211_post_with_author.sql
│   │
│   └── 03_functions/
│       ├── 030_user_functions/
│       │   └── 0301_fn_create_user.sql
│       └── 031_content_functions/
│           └── 0311_fn_publish_post.sql
│
├── 10_seed_common/
│   └── 11_reference_data.sql
│
└── 20_seed_dev/
    └── 21_test_users.sql
```

**When to use**: Enterprise applications, complex domains, multi-bounded contexts

**Numbering logic**:

- Level 1: `0_schema/`, `10_seed_common/`, `20_seed_dev/`
- Level 2 within `0_schema/`: `00_common/`, `01_core_domain/`, `02_views/`, `03_functions/`
- Level 3 within `00_common/`: `000_security/`, `001_extensions/`, `002_types/` (inherits `00`)
- Level 3 within `01_core_domain/`: `010_users/`, `011_content/`, `012_analytics/` (inherits `01`)
- Level 4 files within `000_security/`: `0001_`, `0002_` (inherits `000`)
- Level 4 files within `0101_user_table.sql` (inherits `010`)
- **Each level inherits parent's full prefix and adds one more digit**

---

### XL Projects (3+ levels deep, 500+ files)

**Use hierarchical numbering** with inherited prefixes (4+ levels total):

```
db/
├── 0_schema/
│   ├── 00_common/
│   │   ├── 000_security/
│   │   │   ├── 0000_roles/
│   │   │   │   ├── 00001_admin_role.sql
│   │   │   │   └── 00002_user_role.sql
│   │   │   ├── 0001_schemas/
│   │   │   │   └── 00011_create_schemas.sql
│   │   │   └── 0002_permissions/
│   │   │       └── 00021_grant_permissions.sql
│   │   ├── 001_extensions/
│   │   │   ├── 0011_postgis.sql
│   │   │   └── 0012_pg_trgm.sql
│   │   └── 002_types/
│   │       ├── 0021_enums.sql
│   │       └── 0022_composite_types.sql
│   │
│   ├── 01_domain_users/
│   │   ├── 010_core/
│   │   │   ├── 0101_tb_user.sql
│   │   │   ├── 0102_tb_profile.sql
│   │   │   └── 0103_tb_auth.sql
│   │   └── 011_views/
│       └── 0111_tv_user.sql
│   │
│   ├── 02_domain_content/
│   │   ├── 020_core/
│   │   │   ├── 0201_tb_post.sql
│   │   │   └── 0202_tb_comment.sql
│   │   └── 021_views/
│       └── 0211_tv_content.sql
│   │
│   └── 09_finalize/
│       └── 091_analyze.sql
│
├── 10_seed_common/
│   └── 11_countries.sql
│
└── 20_seed_dev/
    └── 21_test_data.sql
```

**When to use**: Multi-tenant SaaS, enterprise systems, platform products

**Numbering logic**:

- Level 1: `0_schema/`, `10_seed_common/`, `20_seed_dev/`
- Level 2 within `00_`: `00_common/`, `01_domain_users/`, `02_domain_content/`, `09_finalize/`
- Level 3 within `00_common/`: `000_security/`, `001_extensions/`, `002_types/`
- Level 4 within `000_security/`: `0000_roles/`, `0001_schemas/`, `0002_permissions/`
- Level 5 files within `0000_roles/`: `00001_`, `00002_`
- **Each level adds one digit to parent's prefix** - materialized path!

---

## Recommended Structure

### Standard Execution Order

FraiseQL follows PostgreSQL dependency order:

**Top-level directories:**

```
0_schema/              # DDL (CREATE statements)
10_seed_common/         # Production reference data
20_seed_dev/            # Development/test data
30_seed_staging/        # Staging-specific data
50_post_build/          # Post-build scripts (REFRESH, ANALYZE)
```

**Within 0_schema/ (CQRS Pattern):**

```
00_  Common              (Extensions, schemas, types, security)
01_  Write (Command)     (CREATE TABLE tb_* - normalized writes, source of truth)
02_  Read (Query)        (CREATE TABLE tv_* or VIEW v_* - denormalized reads)
03_  Functions           (CREATE FUNCTION - mutations, business logic)
04_  Triggers            (CREATE TRIGGER - sync mechanisms)
05_  Indexes             (CREATE INDEX - performance optimization)
06_  Security            (RLS policies, row-level security)
09_  Finalization        (GRANT, permissions, analyze)
```

**FraiseQL CQRS Convention:**

- **`01_write/`**: Contains all `tb_*` tables (normalized, source of truth)
- **`02_read/`**: Contains all `v_*` or `tv_*` views/tables (denormalized, optimized)
- **`03_functions/`**: Mutation functions and business logic
- Write tables load **before** read views (dependency order)

**Key**: Files within `0_schema/` use `00_`, `01_`, `02_`, `03_`, etc. (inheriting `0` from parent)

### Gaps Are Intentional

Always leave gaps in numbering to allow insertion without renumbering:

```
✅ GOOD: 01_, 03_, 05_, 07_
   → Easy to add 02_new_feature or 04_another_feature later

❌ BAD: 01_, 02_, 03_, 04_
   → Must renumber everything to insert between 01_ and 02_
```

**Why gaps matter:**

- Start with: `01_users/`, `03_posts/`, `05_comments/`
- Later add: `02_profiles/` between users and posts
- Later add: `04_tags/` between posts and comments
- No renumbering needed!

---

## Bounded Context Mapping (Large Apps)

For enterprise applications with multiple bounded contexts (domains), the numbering system maps naturally to DDD patterns:

### Example: E-commerce Platform

```
db/
└── 0_schema/
    ├── 00_common/                    # Shared kernel
    │   ├── 001_extensions.sql
    │   ├── 002_types.sql
    │   └── 003_security.sql
    │
    ├── 01_write/                     # COMMAND SIDE: All write tables (tb_*)
    │   ├── 010_identity/             # Identity bounded context
    │   │   ├── 0101_user.sql         # tb_user
    │   │   ├── 0102_role.sql         # tb_role
    │   │   └── 0103_permission.sql   # tb_permission
    │   ├── 011_catalog/              # Catalog bounded context
    │   │   ├── 0111_product.sql      # tb_product
    │   │   ├── 0112_category.sql     # tb_category
    │   │   └── 0113_inventory.sql    # tb_inventory
    │   ├── 012_order/                # Order bounded context
    │   │   ├── 0121_order.sql        # tb_order
    │   │   ├── 0122_order_item.sql   # tb_order_item
    │   │   └── 0123_payment.sql      # tb_payment
    │   └── 013_shipping/             # Shipping bounded context
    │       ├── 0131_shipment.sql     # tb_shipment
    │       └── 0132_tracking.sql     # tb_tracking
    │
    ├── 02_read/                      # QUERY SIDE: All read views (v_* or tv_*)
    │   ├── 020_identity/             # Identity bounded context
    │   │   └── 0201_user_with_roles.sql  # v_user_with_roles
    │   ├── 021_catalog/              # Catalog bounded context
    │   │   └── 0211_product_catalog.sql  # v_product_catalog
    │   ├── 022_order/                # Order bounded context
    │   │   └── 0221_order_summary.sql    # v_order_summary
    │   └── 023_shipping/             # Shipping bounded context
    │       └── 0231_shipment_status.sql  # v_shipment_status
    │
    ├── 03_functions/                 # BUSINESS LOGIC: All mutations and logic
│   ├── 030_identity/             # Identity bounded context
│   │   └── 0301_fn_auth.sql
│   ├── 031_catalog/              # Catalog bounded context
│   │   └── 0311_fn_catalog.sql
│   ├── 032_order/                # Order bounded context
│   │   └── 0321_fn_order.sql
│   └── 033_shipping/             # Shipping bounded context
│       └── 0331_fn_shipping.sql
│
├── 04_triggers/                  # SYNC: Cross-context sync mechanisms
│   └── 041_tr_sync.sql
    │
    └── 09_finalize/
        └── 091_grants.sql
```

### Numbering Strategy for Bounded Contexts

**Top-level context allocation within `0_schema/`:**

```
00_  Shared kernel / Common           (Extensions, types, shared utilities)
01_  Identity & Access Management     (Users, roles, auth)
02_  Core domain #1                   (Your main business domain)
03_  Core domain #2                   (Another critical domain)
04_  Supporting domain #1             (Supporting subdomain)
05_  Supporting domain #2
...
08_  Generic subdomains               (Notifications, audit, etc.)
09_  Infrastructure                   (Finalization, cleanup)
```

**Materialized Path Encoding:**

- All files in `01_write/` start with `01`: `010_`, `0101_`, `01011_`
- All files in `02_read/` start with `02`: `020_`, `0201_`, `02011_`
- All files in `03_functions/` start with `03`: `030_`, `0301_`, `03011_`

**Within each layer, contexts are numbered:**

- `01_write/010_identity/` - Identity write tables
- `01_write/011_catalog/` - Catalog write tables
- `02_read/020_identity/` - Identity read views
- `02_read/021_catalog/` - Catalog read views

**Benefits:**

- **CQRS enforced by structure** - write side completely loaded before read side
- **Layer-first organization** - see architectural layers clearly
- **File number encodes layer + context**: `0201` = `0_schema/02_read/020_identity/0201_view.sql`
- **Context isolation within layers** - easy to see all writes or all reads per context
- **Team ownership by layer** - DBA team owns write layer, query optimization team owns read layer

### Adding New Bounded Contexts

With gaps, adding contexts is trivial:

```
Initial (within 01_write/):
├── 010_identity/
├── 012_catalog/                     # Gap left intentionally
└── 014_order/

Later add (within 01_write/):
├── 010_identity/
├── 011_customer/
├── 012_catalog/
├── 013_pricing/
└── 014_order/

# Same numbering pattern in 02_read/ and 03_functions/
```

**No files renamed!** The materialized path numbers stay stable.

### Context Dependencies

The numbering also shows context dependencies:

```
0_schema/
  ├── 00_common/              # Shared by all
  │     ↓
  ├── 01_write/               # ALL command tables (tb_*)
  │   ├── 010_identity/       # tb_user, tb_role
  │   ├── 011_catalog/        # tb_product, tb_category
  │   ├── 012_order/          # tb_order, tb_order_item
  │   └── 013_shipping/       # tb_shipment
  │     ↓
  ├── 02_read/                # ALL query views (v_* or tv_*)
  │   ├── 020_identity/       # v_user_with_roles
  │   ├── 021_catalog/        # v_product_catalog
  │   ├── 022_order/          # v_order_summary
  │   └── 023_shipping/       # v_shipment_status
  │     ↓
  └── 03_functions/           # ALL business logic
      ├── 030_identity/       # Auth functions
      ├── 031_catalog/        # Catalog mutations
      ├── 032_order/          # Order mutations
      └── 033_shipping/       # Shipping mutations
```

**Load order guarantees:**

1. All write tables load completely before any read views
2. All read views load completely before any functions
3. Within each layer, contexts load in order (identity → catalog → order → shipping)

**Materialized Path Example:**

- File `0121_order.sql` decodes to:
  - `0` = in `0_schema/`
  - `01` = in `01_write/` (command side)
  - `012` = in `012_order/` (order context)
  - `0121` = this file (tb_order table)
- Full path: `0_schema/01_write/012_order/0121_order.sql`

**Cross-layer example** - same entity in different layers:

- `0121_order.sql` = `0_schema/01_write/012_order/0121_order.sql` (tb_order - write)
- `0221_order_summary.sql` = `0_schema/02_read/022_order/0221_order_summary.sql` (v_order_summary - read)
- `0321_order_mutations.sql` = `0_schema/03_functions/032_order/0321_order_mutations.sql` (business logic)

---

## Examples

### Example 1: Blog Simple (S - 2-digit)

```
examples/blog_simple/db/
└── 0_schema/
    ├── 00_common.sql           # Extensions, types
    ├── 01_write.sql            # tb_user, tb_post, tb_comment (command side)
    ├── 02_read.sql             # v_user, v_post, v_comment (query side)
    ├── 03_functions.sql        # Mutation functions
    ├── 04_triggers.sql         # updated_at, slug generation
    ├── 05_indexes.sql          # Performance indexes
    ├── 06_security.sql         # RLS policies
    └── 09_finalize.sql         # Grant statements
```

**Total: 8 files** → Small flat structure with CQRS separation (01=write, 02=read, 03=functions)

---

### Example 2: Blog API (M - 3-digit, CQRS)

```
examples/blog_api/db/
├── 0_schema/
│   ├── 00_common/
│   │   ├── 001_extensions.sql
│   │   └── 002_types.sql
│   ├── 01_write/                # Command side (tb_* tables + indexes)
│   │   ├── 011_tb_user.sql      # tb_user + indexes
│   │   ├── 012_tb_post.sql      # tb_post + indexes
│   │   └── 013_tb_comment.sql   # tb_comment + indexes
│   ├── 02_read/                 # Query side (v_* or tv_* views/tables)
│   │   ├── 021_tv_user.sql      # v_user or tv_user
│   │   ├── 022_tv_post.sql      # v_post or tv_post
│   │   └── 023_tv_comment.sql   # v_comment or tv_comment
│   ├── 03_functions/            # Business logic
│   │   ├── 031_fn_user.sql
│   │   ├── 032_fn_post.sql
│   │   └── 033_fn_comment.sql
└── 04_triggers/             # Sync mechanisms
    └── 041_tr_sync.sql
└── 10_seed_common/
    └── 11_sample_data.sql
```

**Total: ~13 files** → Medium structure with clear CQRS separation (01=write, 02=read, 03=functions)

---

### Example 3: E-commerce API (L - 4-digit)

```
db/schema/
├── 00_common/
│   ├── 000_security/
│   │   └── 0001_extensions.sql
│   └── 001_types/
│       └── 0010_enums.sql
│
├── 01_core_domain/
│   ├── 010_customers/
│   │   ├── 0101_customer_table.sql
│   │   └── 0102_customer_address.sql
│   ├── 020_products/
│   │   ├── 0201_product_table.sql
│   │   ├── 0202_category_table.sql
│   │   └── 0203_product_category.sql
│   ├── 030_orders/
│   │   ├── 0301_order_table.sql
│   │   └── 0302_order_item_table.sql
│   └── 040_cart/
│       ├── 0401_cart_table.sql
│       └── 0402_cart_item_table.sql
│
├── 02_views/
│   ├── 010_customer_views/
│   │   └── 0101_customer_orders.sql
│   ├── 020_product_views/
│   │   └── 0201_products_with_categories.sql
│   └── 030_order_views/
│       └── 0301_orders_with_items.sql
│
├── 03_functions/
│   ├── 010_customer_functions/
│   │   └── 0101_customer_mutations.sql
│   ├── 020_product_functions/
│   │   └── 0201_product_mutations.sql
│   ├── 030_order_functions/
│   │   └── 0301_order_mutations.sql
│   └── 040_cart_functions/
│       └── 0401_cart_mutations.sql
│
└── 09_seeds/
    └── 0901_sample_products.sql
```

**Total: ~20 files** → Large 4-digit numbering with hierarchy

---

## Best Practices

### 1. Start Small, Grow as Needed

Begin with the smallest structure that works. Refactor as you grow:

```
Project start:   1 file      → XS: Single schema.sql
After 1 month:   5-10 files  → S: Refactor to 2-digit (10_, 20_, 30_)
After 6 months:  25 files    → M: Refactor to 3-digit (010_, 020_)
After 1 year:    100 files   → L: Refactor to 4-digit (0101_, 0102_)
Enterprise:      500+ files  → XL: Multi-level hierarchy
```

### 2. Group Related Entities

Keep related tables, views, and functions together:

```
010_users/
├── 0101_tb_user.sql          # Table + indexes
├── 0102_tb_user_profile.sql  # Related table + indexes
└── 0103_tr_user.sql          # Triggers
```

### 3. Document Your Numbering System

Add a `README.md` in your schema directory:

```markdown
# Schema Organization

## Top-Level Numbers
- `00_common`: Infrastructure (extensions, types, security)
- `01_core_domain`: Core business entities
- `02_views`: Read-optimized views (CQRS query side)
- `03_functions`: Business logic mutations
- `09_seeds`: Sample/test data

## Domain Numbers (Second Level)
- `010_`: Users domain
- `020_`: Content domain
- `030_`: Analytics domain
```

### 4. Use Descriptive Names

File names should be self-documenting:

```
✅ GOOD:
0101_user_table.sql
0102_user_profile_table.sql
0201_user_stats_view.sql

❌ BAD:
01_init.sql
02_data.sql
03_misc.sql
```

### 5. Handle Dependencies Explicitly

Ensure dependencies load before dependents:

```sql
-- ❌ BAD: View before table
10_user_stats_view.sql
20_users_table.sql          -- ERROR: users doesn't exist!

-- ✅ GOOD: Table before view
10_users_table.sql
20_user_stats_view.sql      -- OK: users exists
```

### 6. FraiseQL CQRS Pattern

FraiseQL uses **[CQRS (Command Query Responsibility Segregation)](concepts-glossary.md#cqrs-command-query-responsibility-segregation)** with explicit directory separation:

```
0_schema/
├── 00_common/                # Extensions, types (if needed)
├── 01_write/                 # COMMAND SIDE (ALWAYS FIRST)
│   ├── 011_user.sql          # tb_user - normalized, source of truth
│   ├── 012_post.sql          # tb_post - write-optimized
│   └── 013_comment.sql       # tb_comment
│
├── 02_read/                  # QUERY SIDE (DEPENDS ON WRITE)
│   ├── 021_user_view.sql     # v_user or tv_user - denormalized
│   ├── 022_post_view.sql     # v_post or tv_post - read-optimized
│   └── 023_comment_view.sql  # v_comment or tv_comment
│
└── 03_functions/             # BUSINESS LOGIC (DEPENDS ON BOTH)
    ├── 031_user_mutations.sql
    └── 032_post_mutations.sql
```

**Naming Conventions:**

- **Command side (write)**: `tb_*` tables (e.g., `tb_user`, `tb_post`)
- **Query side (read)**:
  - `v_*` views (e.g., `v_user`, `v_post_with_author`)
  - `tv_*` Trinity views/tables (e.g., `tv_user`, `tv_post`)

**Directory Names (following confiture style):**

- **`01_write/`** - Contains all `tb_*` tables + their indexes
- **`02_read/`** - Contains all `v_*` or `tv_*` views/tables
- **`03_functions/`** - Mutation functions and business logic

**Standard CQRS Load Order:**

1. **`00_common/`** - Extensions, types, shared utilities
2. **`01_write/`** - Command tables (`tb_*`) + indexes - source of truth
3. **`02_read/`** - Query views/tables (`v_*`/`tv_*`) - depend on write tables
4. **`03_functions/`** - Business logic - may use both write and read
5. **`04_triggers/`** - Sync mechanisms

---

## Migration Integration

### Schema Files vs Migrations

FraiseQL uses **both** approaches:

1. **Schema files** (this guide): Source of truth for fresh builds
2. **Migrations** (sequential): Incremental changes to existing databases

```
db/
├── schema/                    # Organized DDL (confiture style)
│   ├── 010_tables/
│   │   └── 011_user.sql
│   └── 020_views/
│       └── 021_user_view.sql
│
└── migrations/                # Sequential migrations
    ├── 001_initial_schema.sql
    ├── 002_add_user_bio.sql
    └── 003_add_post_tags.sql
```

### Workflow

1. **Fresh database**: Build from `schema/` files
2. **Existing database**: Apply `migrations/` sequentially
3. **After migration**: Update corresponding `schema/` files

```bash
# Development: Fresh build
confiture build --from db/schema --to my_database

# Production: Apply migrations
fraiseql migrate up

# Maintenance: Keep schema files in sync
vim db/schema/010_tables/011_user.sql  # Add bio column
```

### Creating Migrations from Schema Changes

When you modify schema files, create a migration:

```bash
# 1. Edit schema file
vim db/schema/010_tables/011_user.sql
# Add: bio TEXT

# 2. Create migration
fraiseql migrate create add_user_bio

# 3. Write migration content
vim db/migrations/004_add_user_bio.sql
# ALTER TABLE tb_user ADD COLUMN bio TEXT;

# 4. Apply migration
fraiseql migrate up
```

**Key principle**: Schema files are source of truth. Migrations are derived.

---

## File Naming Conventions

### Tables

```
{number}_tb_{entity}.sql

Examples:
0101_tb_user.sql
0201_tb_post.sql
0301_tb_order.sql
```

### Views

```
{number}_tv_{entity}.sql

Examples:
0101_tv_user.sql
0201_tv_post_with_author.sql
0301_tv_order_summary.sql
```

### Functions

```
{number}_fn_{operation}_{entity}.sql

Examples:
0301_fn_create_user.sql
0311_fn_publish_post.sql
0321_fn_cancel_order.sql
```

### Triggers

```
{number}_tr_{trigger_name}.sql

Examples:
0301_tr_update_timestamp.sql
0411_tr_invalidate_cache.sql
```

### Security

```
{number}_sec_{policy_name}.sql

Examples:
0601_sec_rls_user_data.sql
0611_sec_grant_permissions.sql
```

---

## Environment-Specific Files

Use confiture's environment configs to load different files per environment:

```yaml
# db/environments/production.yaml
includes:
  - ../schema              # Only schema

# db/environments/development.yaml
includes:
  - ../schema              # Schema
  - ../seeds/development   # Dev seeds
  - ../debug               # Debug tools
```

---

## Common Mistakes

### ❌ Mistake 1: No Number Prefixes

```
schema/
├── extensions.sql
├── tables.sql            # Which comes first?
├── views.sql             # Depends on filesystem!
└── functions.sql
```

**Fix**: Add numbered prefixes

### ❌ Mistake 2: No Gaps

```
001_extensions.sql
002_types.sql
003_tables.sql           # Hard to insert between!
```

**Fix**: Use 010_, 020_, 030_

### ❌ Mistake 3: Wrong Size Classification

```
# 100+ files but using S (2-digit flat) structure
10_user.sql
11_user_profile.sql
12_user_settings.sql
13_post.sql
14_post_tag.sql
...
89_analytics.sql         # Unmanageable!
```

**Fix**: Refactor to L (4-digit hierarchical) structure

---

## Quick Reference

| Size | Files | Depth | Numbering | Example |
|------|-------|-------|-----------|---------|
| **XS** | 1 | Flat | N/A | `0_schema/schema.sql` |
| **S** | <20 | Flat | 2-digit | `0_schema/01_tables.sql` |
| **M** | 20-100 | 1 level | 3-digit | `0_schema/01_tables/011_users.sql` |
| **L** | 100-500 | 2 levels | 4-digit | `0_schema/01_domain/010_users/0101_user.sql` |
| **XL** | 500+ | 3+ levels | 5+ digits | `0_schema/00_common/000_security/0000_roles/00001_admin.sql` |

**Materialized Path**: Each level adds one digit to parent (e.g., `00_` → `001_` → `0011_` → `00111_`)

---

## See Also

- **[confiture: Organizing SQL Files](https://github.com/fraiseql/confiture/blob/main/docs/organizing-sql-files/)** - Original documentation
- **[FraiseQL Migrations](./migrations.md)** - Migration workflow
- **[Database Patterns](../advanced/database-patterns.md)** - CQRS and other patterns
- **[CQRS Example](../../examples/blog_api/)** - Blog with tb_/tv_ tables and sync functions

---

**Last Updated**: 2025-10-16
**FraiseQL Version**: 0.11.5+

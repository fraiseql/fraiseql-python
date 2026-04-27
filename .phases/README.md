# LTree ID-Based Hierarchy Operators

## Goal

Add `descendant_of_id` and `ancestor_of_id` operators to fraiseql's filter system.
These operators accept a UUID and are placed on the **UUID/ID field** (e.g. `locationId`),
automatically resolving the UUID to its ltree path via a nested subquery against the
entity's source table.

## Motivation

When filtering by hierarchy (e.g., "all allocations on this floor and its children"),
the frontend knows the floor's UUID but not its ltree path. Currently, the frontend
would need to either:

1. Make a separate query to resolve UUID → path, then filter by path (two round trips)
2. Use a custom backend resolver (defeats the purpose of a generic framework)

With `descendant_of_id`, the GraphQL query becomes:

```graphql
allocations(where: { locationId: { descendantOfId: $locationId } })
```

And fraiseql generates:

```sql
(data->>'location_id')::uuid IN (
  SELECT id FROM "tenant"."tb_location"
  WHERE path <@ (SELECT path FROM "tenant"."tb_location" WHERE id = 'floor-uuid'::uuid)::ltree
)
```

## Design Decision: Option B — operator on the _id field (UUID), not the _path field

Option A (rejected): `locationPath: { descendantOfId: uuid }` — leaks ltree internals
to the frontend. The developer must know about ltree columns to use hierarchy filtering.

Option B (chosen): `locationId: { descendantOfId: uuid }` — frontend-friendly. The
developer uses the UUID field they already know. fraiseql derives the entity table
from the `_id` suffix and generates a nested IN subquery.

The extra subquery level is well-optimized by PostgreSQL when ltree indexes are present.

## Convention: Column Name → Entity Table

```text
{entity}_id  →  {schema}.tb_{entity}
```

The schema is **not hardcoded** — it must be passed by the caller (via
`FraiseQLConfig.default_entity_schema`).

Examples (with schema = `"tenant"`):

- `location_id` → `"tenant"."tb_location"` (selects `id`, filters by `path`)
- `department_id` → `"tenant"."tb_department"`
- `category_id` → `"tenant"."tb_category"`

The `_id` suffix is stripped to get the entity name. The subquery uses `Identifier()`
for both schema and table name (preventing SQL injection even if `entity_schema` comes
from env vars).

## SQL Pattern

`descendant_of_id` on field `location_id` with uuid `floor-uuid`:

```sql
(data->>'location_id')::uuid IN (
  SELECT id FROM "tenant"."tb_location"
  WHERE path <@ (SELECT path FROM "tenant"."tb_location" WHERE id = 'floor-uuid'::uuid)::ltree
)
```

`ancestor_of_id` on field `location_id` with uuid `floor-uuid`:

```sql
(data->>'location_id')::uuid IN (
  SELECT id FROM "tenant"."tb_location"
  WHERE path @> (SELECT path FROM "tenant"."tb_location" WHERE id = 'floor-uuid'::uuid)::ltree
)
```

## Design Decision: Intercept in sql_builder.py, NOT in operator strategies

The `descendant_of_id` / `ancestor_of_id` operators need the `db_field_name` to derive
the entity table name (e.g., `location_id` → `tenant.tb_location`). This information
is available in `build_where_clause_recursive()` at line 134 of `sql_builder.py`, but
is NOT available in the operator strategy `build_sql()` signature.

Rather than threading `field_name` through 14+ operator strategy classes via `**kwargs`
(which was attempted and rejected), we intercept these special operators in
`build_where_clause_recursive()` BEFORE dispatching to the operator registry. This keeps
the operator strategy interface clean and limits the change surface.

## Schema for Entity Tables

The `tb_*` normalized tables (e.g., `tb_location`) live in a **different schema** from the
views being queried (e.g., `public.v_allocations`). The view schema cannot be used to infer
the entity table schema.

**New config field**: `default_entity_schema: str | None = None` on `FraiseQLConfig`.
This tells fraiseql where the `tb_*` tables live (e.g., `"tenant"`).

**Resolution order** for the `entity_schema` parameter:

1. **Explicit `entity_schema` parameter** passed to `build_where_clause()` / `build_where_clause_graphql()`
2. **`FraiseQLConfig.default_entity_schema`** — set by the application developer

The WHERE clause builders receive `entity_schema` as an explicit parameter — they don't
access global config. The caller (db.py, resolver) is responsible for reading the config
and passing it through.

If `descendant_of_id` / `ancestor_of_id` is used but no `entity_schema` is available,
a `ValueError` is raised with a clear message pointing to the config field.

## Phase Overview

| Phase | Title | Description |
|-------|-------|-------------|
| 1 | Schema & Registration | Add operators to UUIDFilter, is_operator_dict, where_clause.py |
| 2 | SQL Generation | Implement interception in build_where_clause_recursive() |
| 3 | Testing | Unit tests for entity table derivation, SQL generation, edge cases |
| 4 | Finalize | Code cleanup, documentation removal, final verification |

## Current Status

[x] Phase 1 - Complete
[x] Phase 2 - Complete
[x] Phase 3 - Complete
[ ] Phase 4 - Not Started

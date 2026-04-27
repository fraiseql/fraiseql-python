# Phase 2: SQL Generation

## Objective

Implement the core SQL generation for `descendant_of_id` and `ancestor_of_id` by intercepting
these operators in `build_where_clause_recursive()` before they reach the operator strategy chain.

The operators live on `_id` fields (UUID). fraiseql derives the entity table from the `_id`
suffix and generates a nested IN subquery:

```sql
-- descendant_of_id on location_id with uuid 'floor-uuid'
(data->>'location_id')::uuid IN (
  SELECT id FROM "tenant"."tb_location"
  WHERE path <@ (SELECT path FROM "tenant"."tb_location" WHERE id = 'floor-uuid'::uuid)::ltree
)
```

## Success Criteria

- [ ] `_resolve_entity_name(db_field_name)` correctly derives entity name from `_id` field name
- [ ] `_build_hierarchy_subquery(entity_schema, entity_name, uuid_value, op)` generates correct IN subquery with `Identifier()` for schema/table
- [ ] `build_where_clause_recursive()` accepts optional `entity_schema` and intercepts `descendant_of_id`
- [ ] `build_where_clause_recursive()` intercepts `ancestor_of_id` and generates correct SQL
- [ ] Non-`_id` fields with `descendant_of_id` raise ValueError with helpful message
- [ ] Using `descendant_of_id` / `ancestor_of_id` without `entity_schema` raises `ValueError`
- [ ] `FraiseQLConfig.default_entity_schema` added as new config field

## TDD Cycles

### Cycle 1: Entity name derivation helper

- **RED**: Write tests:
  - `_resolve_entity_name("location_id")` → `"location"`
  - `_resolve_entity_name("department_id")` → `"department"`
  - `_resolve_entity_name("some_field")` → raises ValueError (no `_id` suffix)
  - `_resolve_entity_name("id")` → raises ValueError (empty entity name)
- **GREEN**: Add helper function to `src/fraiseql/sql/where/core/sql_builder.py`:

  ```python
  def _resolve_entity_name(db_field_name: str) -> str:
      """Derive entity name from UUID column name.

      Convention: {entity}_id → entity name (e.g., "location")

      Args:
          db_field_name: Database column name (e.g., "location_id")

      Returns:
          Entity name (e.g., "location")

      Raises:
          ValueError: If field name doesn't end with '_id' or entity is empty
      """
      if not db_field_name.endswith("_id"):
          raise ValueError(
              f"Cannot derive entity table from '{db_field_name}': "
              f"field must end with '_id' (e.g., 'location_id')"
          )
      entity = db_field_name.removesuffix("_id")
      if not entity:
          raise ValueError(
              f"Cannot derive entity table from '{db_field_name}': "
              f"entity name is empty (field is just 'id')"
          )
      return entity
  ```

- **REFACTOR**: N/A
- **CLEANUP**: Lint, format

### Cycle 2: Hierarchy subquery builder

- **RED**: Write tests that `_build_hierarchy_subquery("tenant", "location", "some-uuid", "descendant")` generates:

  ```sql
  (data->>'location_id')::uuid IN (
    SELECT id FROM "tenant"."tb_location"
    WHERE path <@ (SELECT path FROM "tenant"."tb_location" WHERE id = 'some-uuid'::uuid)::ltree
  )
  ```

  The JSONB `->>` returns text; cast it to `::uuid` so comparison is UUID-to-UUID and
  PostgreSQL can use the UUID index on `id`. No `::text` cast on the subquery side.
  And `ancestor` variant uses `@>`. Verify that `Identifier()` is used (not `SQL()`) for schema and table names.
- **GREEN**: Add helper function to `src/fraiseql/sql/where/core/sql_builder.py`:

  ```python
  def _build_hierarchy_subquery(
      entity_schema: str,
      entity_name: str,
      uuid_value: str,
      ltree_op: str,  # "<@" for descendant, "@>" for ancestor
      jsonb_path: Composed,
  ) -> Composable:
      """Build nested IN subquery for UUID-based hierarchy filtering.

      Generates:
        ({field})::uuid IN (
          SELECT id FROM "schema"."tb_entity"
          WHERE path {op} (SELECT path FROM "schema"."tb_entity" WHERE id = '{uuid}'::uuid)::ltree
        )

      Casts the JSONB field to ::uuid (not id::text) so PostgreSQL can use
      the UUID index on the id column.

      Uses Identifier() for schema and table names to prevent SQL injection.
      """
      schema_id = Identifier(entity_schema)
      table_id = Identifier(f"tb_{entity_name}")
      uuid_lit = Literal(str(uuid_value))
      op_sql = SQL(ltree_op)
      return SQL(
          "({field})::uuid IN ("
          "SELECT id FROM {schema}.{table} "
          "WHERE path {op} ("
          "SELECT path FROM {schema}.{table} WHERE id = {uuid}::uuid"
          ")::ltree"
          ")"
      ).format(
          field=jsonb_path,
          schema=schema_id,
          table=table_id,
          op=op_sql,
          uuid=uuid_lit,
      )
  ```

- **REFACTOR**: N/A
- **CLEANUP**: Lint, format

### Cycle 3: Thread `entity_schema` parameter through public functions

- **RED**: Write test that `build_where_clause({"location_id": {"descendant_of_id": "abc-123"}}, entity_schema="tenant")` generates SQL containing `IN` and `tenant.tb_location`
  Also: test that calling without `entity_schema` when `descendant_of_id` is present raises `ValueError`
- **GREEN**: Add optional `entity_schema: str | None = None` parameter to:
  1. `build_where_clause_recursive(where_dict, path=None, entity_schema=None)` — thread it through recursive calls
  2. `build_where_clause(where_dict, entity_schema=None)` — pass to recursive
  3. `build_where_clause_graphql(graphql_where, entity_schema=None)` — pass to recursive

  Add interception logic in `build_where_clause_recursive()`, inside the
  `for operator, op_value in value.items()` loop (around line 148), BEFORE the registry dispatch:

  ```python
  for operator, op_value in value.items():
      if op_value is None:
          continue

      # Intercept ID-based ltree hierarchy operators before registry dispatch
      if operator in ("descendant_of_id", "ancestor_of_id"):
          if entity_schema is None:
              raise ValueError(
                  f"Operator '{operator}' requires entity_schema. "
                  f"Set FraiseQLConfig.default_entity_schema or pass "
                  f"entity_schema= to build_where_clause()."
              )
          entity_name = _resolve_entity_name(db_field_name)
          ltree_op = "<@" if operator == "descendant_of_id" else "@>"
          condition = _build_hierarchy_subquery(
              entity_schema, entity_name, op_value, ltree_op, jsonb_path
          )
          conditions.append(condition)
          continue

      # ... existing registry dispatch code ...
  ```

- **REFACTOR**: N/A
- **CLEANUP**: Lint, format

### Cycle 4: ancestor_of_id

- **RED**: Write test that `build_where_clause({"location_id": {"ancestor_of_id": "abc-123"}}, entity_schema="tenant")` generates SQL containing `@>` inside the subquery
- **GREEN**: Already handled in Cycle 3 (both operators implemented together)
- **REFACTOR**: N/A
- **CLEANUP**: Verify both operators work, commit

### Cycle 5: Error handling for non-`_id` fields and missing entity_schema

- **RED**: Write tests:
  - Using `descendant_of_id` on a field without `_id` suffix raises `ValueError`
  - Using `descendant_of_id` without passing `entity_schema` raises `ValueError`
- **GREEN**: Already handled by `_resolve_entity_name()` and the `entity_schema is None` guard
- **REFACTOR**: N/A
- **CLEANUP**: Lint, format, commit

### Cycle 6: Add `default_entity_schema` to FraiseQLConfig

- **RED**: Write test that `FraiseQLConfig` accepts `default_entity_schema` field
- **GREEN**: Add field to `FraiseQLConfig` in `src/fraiseql/fastapi/config.py`:

  ```python
  default_entity_schema: str | None = None  # Schema where tb_* entity tables live (for ltree ID operators)
  ```

  Place it after the existing `default_query_schema` field.
  **Note**: `None` by default — the tb_* tables often live in a tenant-specific schema,
  and we want a clear error if it's needed but not configured.
- **REFACTOR**: N/A
- **CLEANUP**: Lint, format, commit

### Cycle 7: Wire entity_schema at caller level (db.py)

- **RED**: Verify that `db._build_where_clause()` reads `default_entity_schema` from
  config and passes it to the WHERE builders.
- **GREEN**: In `db.py._build_where_clause()`:

  ```python
  # Read entity_schema from config (for ltree ID operators)
  entity_schema = None
  from fraiseql.gql.builders.registry import SchemaRegistry
  registry = SchemaRegistry.get_instance()
  if registry.config:
      entity_schema = registry.config.default_entity_schema
  ```

  Pass `entity_schema` to `build_where_clause()` / `build_where_clause_graphql()`.
  No `try/except` or `hasattr` needed — `default_entity_schema` is added in this PR
  and must exist on `FraiseQLConfig`. If it doesn't, that's a real bug to surface.
- **REFACTOR**: N/A
- **CLEANUP**: Lint, format, commit

## Key Design Notes

### Why intercept BEFORE registry dispatch?

The operator registry dispatches to strategy `build_sql()` which has this signature:

```python
def build_sql(self, operator, value, path_sql, field_type=None, jsonb_column=None)
```

It does NOT receive `db_field_name`, which is needed to derive the entity table.
Rather than modifying the `BaseOperatorStrategy` interface (14+ classes), we handle
the UUID→path resolution at the call site where `db_field_name` is in scope.

### What about the LTreeOperatorStrategy?

The operators are NOT registered in `SUPPORTED_OPERATORS`. They are intercepted
in `build_where_clause_recursive()` before operator dispatch, so the strategy's
`build_sql()` is never called for them.

### Why NOT camelCase conversion issues?

The `_camel_to_snake()` function converts GraphQL `descendantOfId` → `descendant_of_id`.
Verify this explicitly in Phase 3 tests. If the conversion is wrong, fix it there.

## Files Modified

- `src/fraiseql/sql/where/core/sql_builder.py` — main changes (helpers + interception + `entity_schema` param). Import `Identifier` from `psycopg.sql`.
- `src/fraiseql/fastapi/config.py` — add `default_entity_schema` field to `FraiseQLConfig`
- `src/fraiseql/db.py` — wire `entity_schema` from config into WHERE clause builders

## Dependencies

- Phase 1 complete (operators registered)

## Status

[x] Complete

## Implementation Notes

- `_camel_to_snake(operator)` is used in interception so both `descendant_of_id` and
  `descendantOfId` are accepted as operator names.
- Both `"descendantOfId"` / `"ancestorOfId"` added to `is_operator_dict` so GraphQL-style
  camelCase dicts are recognised as operator dicts (not recursed into as nested objects).
- `FieldCondition.to_sql()` in `where_clause.py` also handles these operators by reading
  `entity_schema` from `SchemaRegistry.get_instance().config.default_entity_schema`,
  covering the db.py → WhereClause path.

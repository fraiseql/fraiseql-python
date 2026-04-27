# Phase 1: Schema & Registration

## Objective

Register `descendant_of_id` and `ancestor_of_id` as recognized operators throughout the fraiseql pipeline.
Operators live on **UUID/ID fields** (Option B) — e.g. `locationId: { descendantOfId: $uuid }`.

## Success Criteria

- [x] `UUIDFilter` dataclass has `descendant_of_id` and `ancestor_of_id` fields
- [x] `LTreeFilter` does NOT have these fields (they belong on UUID fields, not ltree fields)
- [x] `is_operator_dict()` recognizes the new operators
- [x] `where_clause.py` LTREE_OPERATORS dict includes the new operators (logical grouping)
- [x] `LTreeOperatorStrategy.SUPPORTED_OPERATORS` does NOT include them (they are intercepted before dispatch)

## TDD Cycles

### Cycle 1: Add fields to UUIDFilter

- **RED**: Write test that `UUIDFilter` accepts `descendant_of_id` and `ancestor_of_id` fields,
  and that `LTreeFilter` does NOT have them
- **GREEN**: Add fields to `UUIDFilter` in `src/fraiseql/sql/graphql_where_generator.py` (after `isnull`):

  ```python
  descendant_of_id: str | None = None  # IN (SELECT id FROM tb_entity WHERE path <@ subquery)
  ancestor_of_id: str | None = None  # IN (SELECT id FROM tb_entity WHERE path @> subquery)
  ```

- **REFACTOR**: N/A
- **CLEANUP**: Lint, format

### Cycle 2: Register in is_operator_dict

- **RED**: Write test that `is_operator_dict({"descendant_of_id": "some-uuid"})` returns True
- **GREEN**: Add to the `operators` set in `src/fraiseql/sql/where/core/sql_builder.py` (after `"descendant_of"`):

  ```python
  "descendant_of_id",
  "ancestor_of_id",
  ```

- **REFACTOR**: N/A (simple set addition)
- **CLEANUP**: Lint, format

### Cycle 3: Register in where_clause.py

- **RED**: Write test that new operators appear in `LTREE_OPERATORS` and `ALL_OPERATORS`
- **GREEN**: Add to `LTREE_OPERATORS` dict in `src/fraiseql/where_clause.py` (after `"descendant_of"`):

  ```python
  "descendant_of_id": "<@",   # inner ltree comparison for descendant_of_id
  "ancestor_of_id": "@>",     # inner ltree comparison for ancestor_of_id
  ```

  Note: These map to the inner `<@` / `@>` used inside the nested subquery.
  The outer SQL is an `IN (...)` pattern, not a direct ltree comparison on the field.
- **REFACTOR**: N/A
- **CLEANUP**: Lint, format

### Cycle 4: Verify NOT registered in LTreeOperatorStrategy.SUPPORTED_OPERATORS

- **RED**: Write test that `LTreeOperatorStrategy.supports_operator("descendant_of_id", LTree)` returns **False**
  (These operators are intercepted in `build_where_clause_recursive()` before dispatch.
  Registering them in the strategy would be misleading — the strategy's `build_sql()` cannot
  handle them because it lacks the `db_field_name` needed for entity table derivation.)
- **GREEN**: No code change needed — operators are not in `SUPPORTED_OPERATORS` by default
- **REFACTOR**: N/A
- **CLEANUP**: Lint, format, commit

## Files Modified

- `src/fraiseql/sql/graphql_where_generator.py` — UUIDFilter fields
- `src/fraiseql/sql/where/core/sql_builder.py` — is_operator_dict set
- `src/fraiseql/where_clause.py` — LTREE_OPERATORS dict

## Dependencies

- None (first phase)

## Status

[x] Complete

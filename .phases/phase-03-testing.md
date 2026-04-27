# Phase 3: Testing

## Objective

Comprehensive test coverage for the new operators, including unit tests, integration tests,
and edge cases. All tests use the Option B pattern: operator on the `_id` field (UUID),
e.g. `locationId: { descendantOfId: $uuid }`.

## Success Criteria

- [ ] Unit tests for `_resolve_entity_name()` with multiple entity names (including empty-entity edge case)
- [ ] Unit tests for `_build_hierarchy_subquery()` SQL output (verify `Identifier()` quoting)
- [ ] Integration tests for full `build_where_clause()` with new operators
- [ ] Edge case tests (None values, non-`_id` fields, missing entity_schema)
- [ ] camelCase → snake_case conversion verified explicitly
- [ ] Test that existing ltree operators still work unchanged (regression)
- [ ] All existing tests still pass

## TDD Cycles

### Cycle 1: Create test file

- **RED**: Create `tests/unit/sql/where/operators/specialized/test_ltree_id_sql.py`
- **GREEN**: Scaffold test class with imports
- **REFACTOR**: N/A
- **CLEANUP**: Verify test file discovered by pytest

### Cycle 2: Entity name derivation tests

- **RED**: Tests for `_resolve_entity_name`:

  ```python
  def test_location_id():
      assert _resolve_entity_name("location_id") == "location"

  def test_department_id():
      assert _resolve_entity_name("department_id") == "department"

  def test_category_id():
      assert _resolve_entity_name("category_id") == "category"

  def test_no_id_suffix_raises():
      with pytest.raises(ValueError, match="must end with '_id'"):
          _resolve_entity_name("location_path")

  def test_just_id_raises():
      # "id" alone → entity would be empty string
      with pytest.raises(ValueError, match="entity name is empty"):
          _resolve_entity_name("id")
  ```

- **GREEN**: Verify existing implementation handles all cases
- **REFACTOR**: Add guard for empty entity name if needed
- **CLEANUP**: Lint, format

### Cycle 3: SQL subquery generation tests

- **RED**: Tests for `_build_hierarchy_subquery`:

  ```python
  def test_descendant_subquery_sql_structure():
      from psycopg.sql import SQL
      jsonb_path = SQL("data->>'location_id'")
      result = _build_hierarchy_subquery("tenant", "location", "abc-123", "<@", jsonb_path)
      sql_str = result.as_string(None)
      assert '"tenant"' in sql_str          # Identifier-quoted schema
      assert '"tb_location"' in sql_str     # Identifier-quoted table
      assert "::uuid" in sql_str
      assert "::ltree" in sql_str
      assert "<@" in sql_str
      assert " IN " in sql_str             # outer IN pattern

  def test_ancestor_subquery_uses_right_op():
      from psycopg.sql import SQL
      jsonb_path = SQL("data->>'location_id'")
      result = _build_hierarchy_subquery("tenant", "location", "abc-123", "@>", jsonb_path)
      sql_str = result.as_string(None)
      assert "@>" in sql_str
  ```

- **GREEN**: Verify output matches expected SQL
- **REFACTOR**: N/A
- **CLEANUP**: Lint, format

### Cycle 4: Full integration — descendant_of_id

- **RED**: Test complete where clause generation:

  ```python
  def test_descendant_of_id_full_where():
      where = {"locationId": {"descendantOfId": "550e8400-e29b-41d4-a716-446655440000"}}
      result = build_where_clause(where, entity_schema="tenant")
      sql_str = result.as_string(None)
      assert " IN " in sql_str
      assert '"tenant"' in sql_str
      assert '"tb_location"' in sql_str
      assert "location_id" in sql_str
      assert "<@" in sql_str
  ```

- **GREEN**: Verify camelCase→snake_case conversion works (`locationId` → `location_id`, `descendantOfId` → `descendant_of_id`)
- **REFACTOR**: N/A
- **CLEANUP**: Lint, format

### Cycle 5: Full integration — ancestor_of_id

- **RED**: Test complete where clause generation:

  ```python
  def test_ancestor_of_id_full_where():
      where = {"locationId": {"ancestorOfId": "550e8400-e29b-41d4-a716-446655440000"}}
      result = build_where_clause(where, entity_schema="tenant")
      sql_str = result.as_string(None)
      assert " IN " in sql_str
      assert '"tenant"' in sql_str
      assert '"tb_location"' in sql_str
      assert "@>" in sql_str
  ```

- **GREEN**: Verify
- **REFACTOR**: N/A
- **CLEANUP**: Lint, format

### Cycle 6: camelCase conversion verification

- **RED**: Explicitly test the conversion:

  ```python
  def test_camel_to_snake_descendant_of_id():
      from fraiseql.sql.where.core.sql_builder import _camel_to_snake
      assert _camel_to_snake("descendantOfId") == "descendant_of_id"

  def test_camel_to_snake_ancestor_of_id():
      from fraiseql.sql.where.core.sql_builder import _camel_to_snake
      assert _camel_to_snake("ancestorOfId") == "ancestor_of_id"
  ```

- **GREEN**: If `_camel_to_snake` is not exported, test indirectly via `build_where_clause`
- **REFACTOR**: N/A
- **CLEANUP**: Lint, format

### Cycle 7: Edge cases

- **RED**: Test edge cases:

  ```python
  def test_none_value_skipped():
      """descendant_of_id: None should be skipped (existing behavior)."""
      where = {"locationId": {"descendantOfId": None}}
      result = build_where_clause(where)
      sql_str = result.as_string(None)
      assert sql_str == "TRUE"  # No conditions generated

  def test_combined_with_other_operators():
      """Can combine descendant_of_id with other operators on same UUID field."""
      where = {"locationId": {
          "descendantOfId": "some-uuid",
          "eq": "another-uuid",
      }}
      result = build_where_clause(where, entity_schema="tenant")
      sql_str = result.as_string(None)
      assert " IN " in sql_str
      assert "= " in sql_str

  def test_non_id_field_raises():
      """Using descendant_of_id on non-_id field should raise ValueError."""
      where = {"status": {"descendantOfId": "some-uuid"}}
      with pytest.raises(ValueError, match="must end with '_id'"):
          build_where_clause(where, entity_schema="tenant")

  def test_missing_entity_schema_raises():
      """Using descendant_of_id without entity_schema should raise ValueError."""
      where = {"locationId": {"descendantOfId": "some-uuid"}}
      with pytest.raises(ValueError, match="entity_schema"):
          build_where_clause(where)  # No entity_schema passed
  ```

- **GREEN**: Verify
- **REFACTOR**: N/A
- **CLEANUP**: Lint, format

### Cycle 8: Regression — existing ltree operators unchanged

- **RED**: Verify existing ltree operators still work (they are on ltree fields, not UUID fields):

  ```python
  def test_descendant_of_still_works():
      """Regular descendant_of (path-based on ltree field) must still work."""
      where = {"locationPath": {"descendantOf": "root.floor1"}}
      result = build_where_clause(where)
      sql_str = result.as_string(None)
      assert "<@" in sql_str
      assert "root.floor1" in sql_str
      assert " IN " not in sql_str  # No subquery for path-based

  def test_ancestor_of_still_works():
      where = {"locationPath": {"ancestorOf": "root.floor1.room2"}}
      result = build_where_clause(where)
      sql_str = result.as_string(None)
      assert "@>" in sql_str
      assert " IN " not in sql_str
  ```

- **GREEN**: Verify no regressions
- **REFACTOR**: N/A
- **CLEANUP**: Lint, format, commit

## Files Created/Modified

- `tests/unit/sql/where/operators/specialized/test_ltree_id_sql.py` (new)

## Dependencies

- Phase 2 complete (SQL generation implemented)

## Status

[x] Complete

## Implementation Notes

All cycles were completed as part of Phase 2's TDD discipline.
`test_ltree_id_sql.py` was written before Phase 2 implementation (RED first),
so the file already covers the full Phase 3 checklist.

Notable: `test_just_id_raises` expects `"entity name is empty"` for bare `"id"`,
but `"id"` doesn't end with `"_id"` so the first guard fires. Added
`test_underscore_id_alone_raises` with `"_id"` to cover the empty-entity case.

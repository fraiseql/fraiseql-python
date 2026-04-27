# Phase 4: Finalize

## Objective

Clean up, verify, and prepare for release.

## Steps

### 1. Quality Control Review

- [ ] `_resolve_entity_table()` handles edge cases (empty entity, bare "path")
- [ ] SQL injection not possible (Literal() used for UUID value, Identifier() for schema/table names)
- [ ] Error messages are clear and actionable
- [ ] No unnecessary complexity added

### 2. Security Audit

- [ ] UUID values are properly escaped via `Literal()`
- [ ] Entity table name derivation is deterministic (no user input in table name beyond field name)
- [ ] `entity_schema` comes from `FraiseQLConfig.default_entity_schema` (developer-controlled) — not from user input
- [ ] Schema and table names use `Identifier()` (not `SQL()`) — safe even if `entity_schema` is set from env vars
- [ ] Field names come from GraphQL schema (not user-controlled)

### 3. Archaeology Removal

- [ ] Remove all phase markers from code
- [ ] Remove debug prints/logs
- [ ] Remove commented-out code
- [ ] No TODO/FIXME remaining

### 4. Final Verification

- [ ] All tests pass: `uv run pytest`
- [ ] All lints pass: `uv run ruff check`
- [ ] Formatting clean: `uv run ruff format --check`
- [ ] Existing test suite passes (no regressions)

### 5. Version Bump

- [ ] Bump fraiseql version (patch or minor as appropriate)
- [ ] Update CHANGELOG if one exists

## Post-Implementation: PrintOptim Backend Integration

After fraiseql is released with these operators, the printoptim_backend needs:

1. **Bump fraiseql dependency** in `pyproject.toml`
2. **Add `location_path` to Allocation's `table_columns`** in
   `src/printoptim_backend/entrypoints/api/gql_types/scd/gql_allocation.py`
3. **Frontend PR #183** will then work with subtree semantics automatically
   (the `eq` filter on `locationId` should be changed to `descendantOfId` on `locationPath`)

These steps are OUTSIDE the fraiseql repo and should be done in printoptim_backend.

## Status

[x] Complete

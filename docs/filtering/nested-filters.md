# Nested Filters in FraiseQL

FraiseQL supports filtering on related objects using two different approaches depending on your table structure.

## Filter Types

### FK-Based Nested Filters

Used when filtering by a related object's ID, leveraging foreign key columns.

**Example**:

```python
where = {"machine": {"id": {"eq": machine_uuid}}}
```

**Generated SQL**:

```sql
SELECT * FROM allocations WHERE machine_id = '01451122-5021-0000-5000-000000000072'::uuid
```

**When to use**:

- Filtering by related object ID
- Hybrid tables with both FK columns and JSONB data
- Best performance (uses indexed FK column)

### JSONB-Based Nested Filters

Used when filtering by fields within JSONB-stored related objects.

**Example**:

```python
where = {"machine": {"name": {"contains": "Printer"}}}
```

**Generated SQL**:

```sql
SELECT * FROM allocations
WHERE data->'machine'->>'name' LIKE '%Printer%'
```

**When to use**:

- Filtering by related object fields (not ID)
- JSONB-stored related data
- When FK column doesn't exist

### Mixed Nested Filters

You can combine both approaches in a single filter.

**Example**:

```python
where = {
    "machine": {
        "id": {"eq": machine_uuid},
        "name": {"contains": "Printer"}
    }
}
```

**Generated SQL**:

```sql
SELECT * FROM allocations
WHERE machine_id = '01451122-5021-0000-5000-000000000072'::uuid
  AND data->'machine'->>'name' LIKE '%Printer%'
```

## Best Practices

### Performance Considerations

1. **Use FK-based filters when possible**
   - FK columns are indexed
   - Much faster than JSONB path queries
   - Equivalent results

2. **Direct FK filter vs nested filter**

   ```python
   # These are equivalent, but direct FK is clearer:

   # Nested (implicit FK)
   allocations(where: { machine: { id: { eq: $id } } })

   # Direct FK (explicit, recommended)
   allocations(where: { machineId: { eq: $id } })
   ```

### Trinity Pattern Considerations

For databases using the Trinity Pattern (UUID public ID + INTEGER internal PK):

- FK columns reference internal INTEGER PKs
- GraphQL exposes UUID `id` fields
- FraiseQL automatically resolves:
  - Nested filter: `machine: { id: { eq: $uuid } }` → `machine_id = (SELECT pk WHERE id = $uuid)`
  - Direct filter: `machineId: { eq: $uuid }` → Same resolution

## Limitations

1. **FK resolution is one level deep**
   - `{ machine: { id: { eq: $id } } }` can use the `machine_id` column
   - Deeper filters (`{ machine: { owner: { name: { eq: $name } } } }`) follow the
     JSONB path (`data -> 'machine' -> 'owner' ->> 'name'`), so the view's JSONB must
     hold the nested object

2. **Metadata requirements**
   - FK detection works best with type metadata
   - Register types: `register_type_for_view("view_name", Type)`
   - Without metadata, falls back to heuristics

3. **JSONB path performance**
   - JSONB filters can be slower than FK filters
   - Consider adding JSONB indexes for frequently filtered paths:

     ```sql
     CREATE INDEX idx_machine_name ON allocations
     USING GIN ((data->'machine'));
     ```

## Troubleshooting

### "Unsupported operator: id" Error

**Cause**: Fixed in FraiseQL v1.8.0-alpha.4+

**Solution**: Upgrade to latest version or use direct FK filter:

```python
# Instead of:
allocations(where: { machine: { id: { eq: $id } } })

# Use:
allocations(where: { machineId: { eq: $id } })
```

### Empty Results from Nested Filter

**Possible causes**:

1. Table metadata not registered
2. FK column naming mismatch
3. JSONB path structure mismatch

**Debug steps**:

1. Enable debug logging: `FRAISEQL_LOG_LEVEL=DEBUG`
2. Check generated SQL in logs
3. Verify FK column exists: `SELECT column_name FROM information_schema.columns WHERE table_name = 'your_table'`
4. Verify JSONB structure: `SELECT data FROM your_table LIMIT 1`

## Examples

See `tests/regression/issue_124/` for complete working examples.

# LTREE Hierarchical Data

An organization chart stored with PostgreSQL's `ltree`: each employee's
`org_path` is the chain of managers down to them (`alice.bob.david` reports to
`alice.bob`), so "everyone under David" or "everyone above Frank" is one indexed
comparison instead of a recursive query.

## Running it

```bash
cd organization-chart
createdb org_chart
psql org_chart -f setup.sql

pip install fraiseql fastapi uvicorn
DATABASE_URL=postgresql://localhost/org_chart python schema.py
```

Then try the queries in `queries.graphql` at `http://localhost:8000/graphql`.

## How it works

- `setup.sql` creates `tb_employee` with an `org_path LTREE` column and a GiST
  index, and the `v_employee` view fraiseql reads. The view exposes `org_path` and
  its `level` (`nlevel(org_path)`) as columns next to the `data` JSONB.
- `schema.py` types `org_path` as `LTree` and calls `register_type_for_view` with
  the view's columns, so filters on `org_path` compare the ltree column itself.
- `reports` filters with `descendant_of` (`<@`) and a level bound;
  `chainOfCommand` with `ancestor_of` (`@>`). `employees` takes fraiseql's
  `where` argument, which offers the ltree operators on `orgPath`, for example
  `descendantOf`, `ancestorOf` and `matchesLquery`.

## The ltree operators used

| Filter | SQL | Meaning |
|---|---|---|
| `descendant_of: "alice.bob"` | `org_path <@ 'alice.bob'` | at or below `alice.bob` |
| `ancestor_of: "alice.bob.david"` | `org_path @> 'alice.bob.david'` | at or above it |
| `matches_lquery: "*.eva.*{1}"` | `org_path ~ '*.eva.*{1}'` | exactly one level below `eva` |

`descendant_of` and `ancestor_of` include the path itself; `reports` and
`chainOfCommand` exclude it with the `level` filter.

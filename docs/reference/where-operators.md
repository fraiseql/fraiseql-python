# WHERE Clause Operators Reference

FraiseQL provides a rich set of WHERE clause operators for filtering, searching, and comparing data in your GraphQL queries. Operators are translated directly to **PostgreSQL** SQL (including JSONB and PostgreSQL-specific operators) at runtime when a query is executed.

## Overview

Filters are supplied through the generated `where:` input argument on a query. Each field exposes the operators appropriate for its type, and FraiseQL maps each operator to the equivalent PostgreSQL expression:

- **Type-aware filtering** — each field only accepts operators valid for its column type.
- **Direct SQL translation** — operators map to PostgreSQL operators (`=`, `LIKE`, `ILIKE`, `@>`, `&&`, etc.) for efficient, index-friendly query plans.
- **Boolean composition** — combine conditions with `AND` / `OR` / `NOT`.
- **Specialized families** — hierarchical paths (`ltree`) and vector similarity (`pgvector`) have dedicated references; see [LTree operators](./ltree-operators.md) and [Vector operators](./vector-operators.md).

A `where:` filter is an input object keyed by field name; each field holds an object keyed by operator name:

```graphql
query {
  users(where: {
    status: { eq: "active" }
    age: { gte: 18 }
  }) {
    id
    name
  }
}
```

Multiple fields at the same level are combined with `AND`.

---

## Comparison Operators

Comparison operators work with comparable scalar types (numeric, string, date, datetime, UUID, etc.).

| Operator | SQL | Description | Example |
|----------|-----|-------------|---------|
| `eq` | `=` | Equal | `{ age: { eq: 25 } }` |
| `neq` | `!=` / `<>` | Not equal | `{ status: { neq: "inactive" } }` |
| `gt` | `>` | Greater than | `{ age: { gt: 18 } }` |
| `gte` | `>=` | Greater than or equal | `{ age: { gte: 21 } }` |
| `lt` | `<` | Less than | `{ age: { lt: 65 } }` |
| `lte` | `<=` | Less than or equal | `{ age: { lte: 65 } }` |
| `in` | `IN (...)` | Value in list | `{ status: { in: ["active", "pending"] } }` |
| `nin` / `notin` | `NOT IN (...)` | Value not in list | `{ status: { nin: ["deleted", "archived"] } }` |
| `isnull` | `IS NULL` / `IS NOT NULL` | NULL check | `{ deletedAt: { isnull: true } }` |

`notin` is an accepted alias for `nin`.

```graphql
query {
  users(where: {
    age: { gte: 18, lte: 65 }
    status: { in: ["active", "pending"] }
    deletedAt: { isnull: true }
  }) {
    id
    name
  }
}
```

This translates to roughly:

```sql
WHERE (data->>'age')::int >= 18
  AND (data->>'age')::int <= 65
  AND data->>'status' IN ('active', 'pending')
  AND data->>'deleted_at' IS NULL
```

Numeric comparisons (`gt`, `gte`, `lt`, `lte`) apply to numeric, date, datetime, and lexically to text. The equality, list, and NULL operators apply to all scalar types.

---

## Text and Pattern Operators

Text operators provide substring matching, prefix/suffix matching, and regular-expression matching, each with a case-insensitive variant.

### Substring, prefix, and suffix

| Operator | SQL | Description | Case-sensitive |
|----------|-----|-------------|:---:|
| `contains` | `LIKE '%value%'` | Contains substring | Yes |
| `icontains` | `ILIKE '%value%'` | Contains substring | No |
| `startswith` | `LIKE 'value%'` | Starts with | Yes |
| `istartswith` | `ILIKE 'value%'` | Starts with | No |
| `endswith` | `LIKE '%value'` | Ends with | Yes |
| `iendswith` | `ILIKE '%value'` | Ends with | No |

```graphql
query {
  users(where: {
    email: { contains: "@example.com" }
    name: { icontains: "smith" }
    city: { istartswith: "san" }
  }) {
    id
  }
}
```

```sql
WHERE data->>'email' LIKE '%@example.com%'
  AND data->>'name' ILIKE '%smith%'
  AND data->>'city' ILIKE 'san%'
```

### LIKE patterns

| Operator | SQL | Description |
|----------|-----|-------------|
| `like` | `LIKE` | Match a user-supplied SQL `LIKE` pattern |
| `ilike` | `ILIKE` | Case-insensitive `LIKE` pattern |

Wildcards follow PostgreSQL `LIKE` semantics: `%` matches any sequence of characters and `_` matches a single character.

```graphql
query {
  users(where: {
    name: { like: "John%" }
    email: { ilike: "%@example.com" }
  }) {
    id
  }
}
```

### Regular expressions

| Operator | SQL | Description |
|----------|-----|-------------|
| `matches` | `~` | POSIX regex match (case-sensitive) |
| `imatches` | `~*` | POSIX regex match (case-insensitive) |
| `not_matches` | `!~` | Negated POSIX regex match |

These use PostgreSQL POSIX regular expressions (`^`, `$`, `.`, `*`, `+`, `?`, `[...]`, `(...)`, `|`).

```graphql
query {
  users(where: {
    email: { matches: "^[a-z0-9._%+-]+@example\\.com$" }
  }) {
    id
  }
}
```

```sql
WHERE data->>'email' ~ '^[a-z0-9._%+-]+@example\.com$'
```

---

## Array Operators

Array operators work with array-valued fields (JSONB arrays). They map to PostgreSQL's array/containment operators.

### Equality

| Operator | SQL | Description |
|----------|-----|-------------|
| `eq` / `array_eq` | `=` | Array equals |
| `neq` / `array_neq` | `!=` | Array not equal |

### Containment and overlap

| Operator | SQL | Description |
|----------|-----|-------------|
| `contains` / `array_contains` | `@>` | Array contains **all** the given elements |
| `contained_by` / `array_contained_by` | `<@` | Array is a subset of the given elements |
| `overlaps` / `array_overlaps` | `&&` | Arrays share **at least one** element |

```graphql
query {
  posts(where: {
    tags: { contains: ["important", "urgent"] }
  }) {
    id
  }
  reviewQueue: posts(where: {
    tags: { overlaps: ["todo", "review", "pending"] }
  }) {
    id
  }
}
```

```sql
-- contains: must have every listed tag
WHERE data->'tags' @> '["important", "urgent"]'::jsonb

-- overlaps: must share at least one tag
WHERE data->'tags' && '["todo", "review", "pending"]'::text[]
```

Distinguishing the three:

- `contains` — the field must include **all** supplied elements.
- `overlaps` — the field must include **at least one** supplied element.
- `contained_by` — the field must be a **subset** of the supplied elements.

### Array length and element matching

| Operator | SQL | Description |
|----------|-----|-------------|
| `len_eq` | `array_length(...) =` | Length equals |
| `len_neq` | `array_length(...) !=` | Length not equal |
| `len_gt` | `array_length(...) >` | Length greater than |
| `len_gte` | `array_length(...) >=` | Length greater than or equal |
| `len_lt` | `array_length(...) <` | Length less than |
| `len_lte` | `array_length(...) <=` | Length less than or equal |
| `any_eq` | `= ANY(...)` | Any element equals the value |
| `all_eq` | `= ALL(...)` | All elements equal the value |

```graphql
query {
  posts(where: {
    tags: { len_gte: 1 }
    statuses: { any_eq: "completed" }
  }) {
    id
  }
}
```

---

## Hierarchical Path and Vector Operators

Two specialized operator families have their own dedicated references:

- **LTree (hierarchical paths)** — operators such as `ancestor_of`, `descendant_of`, `matches_lquery`, and `nlevel_*` for PostgreSQL `ltree` columns. See [LTree operators](./ltree-operators.md).
- **Vector similarity (pgvector)** — distance operators such as `cosine_distance`, `l2_distance`, `inner_product`, and `hamming_distance` for embedding search. See [Vector operators](./vector-operators.md).

---

## Logical Operators

Combine field conditions with boolean operators. Conditions at the same level are `AND`-combined by default.

| Operator | SQL | Description |
|----------|-----|-------------|
| `AND` | `AND` | All conditions must match |
| `OR` | `OR` | At least one condition must match |
| `NOT` | `NOT` | Negate the condition |

```graphql
query {
  users(where: {
    AND: [
      { age: { gte: 18 } },
      { OR: [
        { status: { eq: "active" } },
        { status: { eq: "pending" } }
      ] },
      { NOT: { email: { isnull: true } } }
    ]
  }) {
    id
    name
  }
}
```

---

## Combining Operators

Operators across fields and families compose freely in a single `where:` input:

```graphql
query {
  products(where: {
    AND: [
      { price: { gte: 100, lte: 500 } },
      { tags: { overlaps: ["featured", "bestseller"] } },
      { name: { icontains: "pro" } },
      { discontinuedAt: { isnull: true } }
    ]
  }) {
    id
    name
    price
  }
}
```

---

## Performance Notes

WHERE operators translate to PostgreSQL expressions, so the relevant PostgreSQL indexing strategies apply:

| Field type | Recommended index | Operators it accelerates |
|------------|-------------------|--------------------------|
| Text / scalar | B-tree | `eq`, `gt`, `gte`, `lt`, `lte`, `in` |
| Text pattern (`LIKE`/`ILIKE`) | `pg_trgm` GIN/GiST | `contains`, `icontains`, `startswith`, `like`, `ilike` |
| JSONB / array | GIN | `contains`, `contained_by`, `overlaps` |
| `ltree` | GiST | `ancestor_of`, `descendant_of`, `matches_lquery` |
| `vector` (pgvector) | HNSW / IVFFlat | distance operators |

Tips:

1. Filter on indexed fields where possible.
2. Combine narrow filters with `AND` to reduce the candidate set early.
3. Anchored patterns (`startswith` / `LIKE 'value%'`) use B-tree indexes; unanchored substring patterns benefit from a `pg_trgm` index.
4. Add a GIN index on JSONB array fields you filter with `contains` / `overlaps`.

---

## See Also

- [LTree operators](./ltree-operators.md) — hierarchical path filtering
- [Vector operators](./vector-operators.md) — pgvector similarity search
- [Scalars reference](./scalars.md) — scalar types accepted by these operators
- [Type system](../foundation/09-type-system.md) — how fields and types are defined

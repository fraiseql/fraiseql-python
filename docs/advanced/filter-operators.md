# PostgreSQL Filter Operators Reference

FraiseQL provides comprehensive PostgreSQL operator support for advanced filtering beyond basic equality and comparison. These operators leverage PostgreSQL's powerful features for arrays, full-text search, JSONB, and text pattern matching.

**Status**: ✅ Fully implemented and tested (3645 tests passing)

## Overview

All operators are available through the GraphQL `where` input types and are automatically generated based on your field types. The operator system is:

- **Type-safe**: Operators are only available for compatible field types
- **SQL injection safe**: Uses parameterized queries
- **Performance-optimized**: Generates efficient PostgreSQL queries
- **Intelligent**: Automatically selects optimal operators (e.g., native vs JSONB arrays)

## Quick Reference

| Category | Operators | Use Case |
|----------|-----------|----------|
| **Arrays** | `contains`, `overlaps`, `len_gt`, `any_eq`, etc. | Filter by array contents, length, element matching |
| **Full-Text Search** | `matches`, `plain_query`, `websearch_query`, `rank_gt` | Search text with relevance ranking |
| **JSONB** | `has_key`, `contains`, `path_exists`, `get_path` | Query JSON structure and content |
| **Text Regex** | `matches`, `imatches`, `not_matches` | POSIX regular expression matching |

---

## Array Operators

**Use Case**: Filter records based on PostgreSQL array columns or JSONB arrays

**Requirements**:

- PostgreSQL array columns (e.g., `TEXT[]`, `INTEGER[]`) or JSONB arrays
- GIN indexes recommended for performance

**Key Feature**: FraiseQL automatically detects whether you're filtering on native array columns or JSONB arrays and uses the optimal operator:

- **Native columns** (e.g., `tags TEXT[]`): Uses `&&` operator with GIN index
- **JSONB arrays** (e.g., `data->'tags'`): Uses `?|` operator

### Available Operators

#### `eq` - Array Equality

**Description**: Exact array match (same elements in same order)
**GraphQL Type**: `[String]` (or appropriate array type)
**PostgreSQL Operator**: `=`

**Example**:

```graphql
query {
  products(where: {
    tags: { eq: ["electronics", "gadget"] }
  }) {
    id
    name
    tags
  }
}
```

**SQL Generated**:

```sql
SELECT * FROM v_product
WHERE tags = ARRAY['electronics', 'gadget']::text[]
```

---

#### `neq` - Array Inequality

**Description**: Arrays are not equal
**GraphQL Type**: `[String]`
**PostgreSQL Operator**: `!=`

**Example**:

```graphql
query {
  products(where: {
    tags: { neq: ["old", "deprecated"] }
  }) {
    id
    name
  }
}
```

---

#### `contains` - Array Contains Element

**Description**: Array contains the specified element
**GraphQL Type**: `String` (single element)
**PostgreSQL Operator**: `@>`

**Example**:

```graphql
query {
  products(where: {
    tags: { contains: "electronics" }
  }) {
    id
    name
    tags
  }
}
```

**SQL Generated**:

```sql
-- Native array column
WHERE tags @> ARRAY['electronics']::text[]

-- JSONB array (automatic detection)
WHERE data->'tags' @> '["electronics"]'::jsonb
```

**Performance Note**: Create GIN index for fast containment queries:

```sql
CREATE INDEX idx_products_tags ON tb_product USING gin(tags);
```

---

#### `contained_by` - Array Contained By

**Description**: Array is a subset of the provided array
**GraphQL Type**: `[String]`
**PostgreSQL Operator**: `<@`

**Example**:

```graphql
query {
  products(where: {
    tags: { contained_by: ["electronics", "gadget", "tool", "premium"] }
  }) {
    id
    name
    tags
  }
}
```

**Use Case**: Find products whose tags are entirely within a whitelist.

---

#### `overlaps` - Array Overlaps (Intersection)

**Description**: Arrays have at least one element in common
**GraphQL Type**: `[String]`
**PostgreSQL Operators**: `&&` (native) or `?|` (JSONB) - automatically selected

**Example**:

```graphql
query {
  products(where: {
    tags: { overlaps: ["electronics", "featured"] }
  }) {
    id
    name
    tags
  }
}
```

**SQL Generated**:

```sql
-- Native array column (optimal performance with GIN index)
WHERE tags && ARRAY['electronics', 'featured']::text[]

-- JSONB array (automatically detected and converted)
WHERE data->'tags' ?| '{"electronics","featured"}'
```

**Performance Note**: This is the most common array filter operator. Always use GIN indexes:

```sql
CREATE INDEX idx_products_tags_gin ON tb_product USING gin(tags);
```

---

#### `len_eq`, `len_neq`, `len_gt`, `len_gte`, `len_lt`, `len_lte` - Array Length

**Description**: Compare array length
**GraphQL Type**: `Int`
**PostgreSQL Function**: `array_length(arr, 1)` or `jsonb_array_length()`

**Example**:

```graphql
query {
  products(where: {
    tags: { len_gte: 3 }
  }) {
    id
    name
    tags
  }
}
```

**SQL Generated**:

```sql
-- Native array
WHERE array_length(tags, 1) >= 3

-- JSONB array
WHERE jsonb_array_length(data->'tags') >= 3
```

**Use Case**: Find products with many tags, or ensure minimum categorization.

---

#### `any_eq` - Any Element Equals

**Description**: At least one array element equals the value
**GraphQL Type**: `String`
**PostgreSQL Operator**: `= ANY()`

**Example**:

```graphql
query {
  products(where: {
    tags: { any_eq: "premium" }
  }) {
    id
    name
  }
}
```

**SQL Generated**:

```sql
WHERE 'premium' = ANY(tags)
```

---

#### `all_eq` - All Elements Equal

**Description**: All array elements equal the value
**GraphQL Type**: `String`
**PostgreSQL Operator**: `= ALL()`

**Example**:

```graphql
query {
  statuses(where: {
    checks: { all_eq: "passed" }
  }) {
    id
    name
  }
}
```

**Use Case**: Find records where all array elements meet a condition (e.g., all tests passed).

---

## Full-Text Search Operators

**Use Case**: Search text content with PostgreSQL's full-text search capabilities

**Requirements**:

- `tsvector` column in your table
- GIN index on the tsvector column (critical for performance)
- Trigger to auto-update tsvector on INSERT/UPDATE

### Setting Up Full-Text Search

```sql
-- Add tsvector column
ALTER TABLE tb_post ADD COLUMN search_vector tsvector;

-- Create GIN index (essential for performance)
CREATE INDEX idx_post_search ON tb_post USING gin(search_vector);

-- Auto-update trigger
CREATE TRIGGER tb_post_search_vector_update
BEFORE INSERT OR UPDATE ON tb_post
FOR EACH ROW EXECUTE FUNCTION
  tsvector_update_trigger(search_vector, 'pg_catalog.english', title, content);
```

Expose in your view:

```sql
CREATE VIEW v_post AS
SELECT
  id,
  jsonb_build_object(
    'id', id,
    'title', title,
    'content', content,
    'search_vector', search_vector::text
  ) as data,
  search_vector  -- Keep for efficient filtering
FROM tb_post;
```

### Available Operators

#### `matches` - Basic Text Search

**Description**: Match tsvector against tsquery
**GraphQL Type**: `String`
**PostgreSQL Operator**: `@@`

**Example**:

```graphql
query {
  posts(where: {
    searchVector: { matches: "python" }
  }) {
    id
    title
  }
}
```

**SQL Generated**:

```sql
WHERE search_vector @@ to_tsquery('english', 'python')
```

---

#### `plain_query` - Plain Text Query

**Description**: Convert plain text to tsquery (AND between words)
**GraphQL Type**: `String`
**PostgreSQL Function**: `plainto_tsquery()`

**Example**:

```graphql
query {
  posts(where: {
    searchVector: { plain_query: "javascript tutorial" }
  }) {
    id
    title
  }
}
```

**SQL Generated**:

```sql
WHERE search_vector @@ plainto_tsquery('english', 'javascript tutorial')
```

**Behavior**: Searches for documents containing both "javascript" AND "tutorial" (in any order).

---

#### `phrase_query` - Phrase Search

**Description**: Search for exact phrase
**GraphQL Type**: `String`
**PostgreSQL Function**: `phraseto_tsquery()`

**Example**:

```graphql
query {
  posts(where: {
    searchVector: { phrase_query: "programming basics" }
  }) {
    id
    title
  }
}
```

**SQL Generated**:

```sql
WHERE search_vector @@ phraseto_tsquery('english', 'programming basics')
```

**Behavior**: Matches "programming basics" as an exact phrase (words adjacent in order).

---

#### `websearch_query` - Web-Style Search

**Description**: Web search engine style queries (supports OR, quotes, -)
**GraphQL Type**: `String`
**PostgreSQL Function**: `websearch_to_tsquery()`

**Example**:

```graphql
query {
  posts(where: {
    searchVector: { websearch_query: "javascript OR python" }
  }) {
    id
    title
  }
}
```

**SQL Generated**:

```sql
WHERE search_vector @@ websearch_to_tsquery('english', 'javascript OR python')
```

**Supported Syntax**:

- `javascript OR python` - Either term
- `javascript -tutorial` - JavaScript but NOT tutorial
- `"exact phrase"` - Exact phrase match
- `javascript & python` - Both terms (AND)

---

#### `rank_gt`, `rank_gte`, `rank_lt`, `rank_lte` - Relevance Ranking

**Description**: Filter by relevance score
**GraphQL Type**: `Float`
**PostgreSQL Function**: `ts_rank()`

**Example**:

```graphql
query {
  posts(where: {
    searchVector: {
      plain_query: "python",
      rank_gt: 0.1
    }
  }) {
    id
    title
  }
}
```

**SQL Generated**:

```sql
WHERE search_vector @@ plainto_tsquery('english', 'python')
  AND ts_rank(search_vector, plainto_tsquery('english', 'python')) > 0.1
```

**Use Case**: Filter out low-relevance matches to show only high-quality results.

---

#### `rank_cd_gt`, `rank_cd_gte`, `rank_cd_lt`, `rank_cd_lte` - Cover Density Ranking

**Description**: Filter by cover density (proximity of matching terms)
**GraphQL Type**: `Float`
**PostgreSQL Function**: `ts_rank_cd()`

**Example**:

```graphql
query {
  posts(where: {
    searchVector: {
      websearch_query: "python graphql",
      rank_cd_gt: 0.2
    }
  }) {
    id
    title
  }
}
```

**Use Case**: Find documents where search terms appear close together (better relevance signal than `ts_rank()`).

---

## JSONB Operators

**Use Case**: Query and filter JSONB columns for structure and content

**Requirements**:

- JSONB column type
- GIN index recommended for key/containment operations

**Performance Setup**:

```sql
-- GIN index for key existence and containment
CREATE INDEX idx_product_attributes ON tb_product USING gin(attributes);

-- GIN index with jsonb_path_ops for containment only (smaller, faster)
CREATE INDEX idx_product_attributes_path ON tb_product
  USING gin(attributes jsonb_path_ops);
```

### Available Operators

#### `has_key` - Key Existence

**Description**: JSONB object has the specified key
**GraphQL Type**: `String`
**PostgreSQL Operator**: `?`

**Example**:

```graphql
query {
  products(where: {
    attributes: { has_key: "ram" }
  }) {
    id
    name
  }
}
```

**SQL Generated**:

```sql
WHERE attributes ? 'ram'
```

**Use Case**: Find products with specific attributes, regardless of value.

---

#### `has_any_keys` - Any Key Exists

**Description**: JSONB has at least one of the specified keys
**GraphQL Type**: `[String]`
**PostgreSQL Operator**: `?|`

**Example**:

```graphql
query {
  products(where: {
    attributes: { has_any_keys: ["ram", "storage"] }
  }) {
    id
    name
  }
}
```

**SQL Generated**:

```sql
WHERE attributes ?| ARRAY['ram', 'storage']
```

---

#### `has_all_keys` - All Keys Exist

**Description**: JSONB has all of the specified keys
**GraphQL Type**: `[String]`
**PostgreSQL Operator**: `?&`

**Example**:

```graphql
query {
  products(where: {
    attributes: { has_all_keys: ["brand", "storage"] }
  }) {
    id
    name
  }
}
```

**SQL Generated**:

```sql
WHERE attributes ?& ARRAY['brand', 'storage']
```

---

#### `contains` - JSONB Contains

**Description**: Left JSONB contains right JSONB
**GraphQL Type**: `JSON` (dict or list)
**PostgreSQL Operator**: `@>`

**Example**:

```graphql
query {
  products(where: {
    attributes: { contains: {brand: "Apple"} }
  }) {
    id
    name
  }
}
```

**SQL Generated**:

```sql
WHERE attributes @> '{"brand": "Apple"}'::jsonb
```

**Use Case**: Find records with specific JSON structure/values. Works with nested objects.

---

#### `strictly_contains` - Strict JSONB Contains

**Description**: Same as `contains` but with type coercion
**GraphQL Type**: `JSON`
**PostgreSQL Operator**: `@>`

**Example**:

```graphql
query {
  configs(where: {
    settings: { strictly_contains: {enabled: true, version: 2} }
  }) {
    id
    name
  }
}
```

---

#### `contained_by` - JSONB Contained By

**Description**: Left JSONB is contained by right JSONB
**GraphQL Type**: `JSON`
**PostgreSQL Operator**: `<@`

**Example**:

```graphql
query {
  products(where: {
    attributes: { contained_by: {brand: "Apple", storage: "128GB", color: "black", ram: "8GB"} }
  }) {
    id
    name
  }
}
```

**Use Case**: Find records whose attributes are a subset of the provided object.

---

#### `path_exists` - JSONPath Exists

**Description**: JSONPath query returns any results
**GraphQL Type**: `String` (JSONPath expression)
**PostgreSQL Operator**: `@?`

**Example**:

```graphql
query {
  orders(where: {
    metadata: { path_exists: "$.items[*].price" }
  }) {
    id
  }
}
```

**SQL Generated**:

```sql
WHERE metadata @? '$.items[*].price'
```

**Use Case**: Check if a JSON path exists without extracting values.

---

#### `path_match` - JSONPath Match

**Description**: JSONPath query predicate matches
**GraphQL Type**: `String` (JSONPath predicate)
**PostgreSQL Operator**: `@@`

**Example**:

```graphql
query {
  products(where: {
    attributes: { path_match: "$.price < 100" }
  }) {
    id
    name
  }
}
```

**SQL Generated**:

```sql
WHERE attributes @@ '$.price < 100'
```

---

#### `get_path` - Get JSON Path Value

**Description**: Extract value at JSON path
**GraphQL Type**: `[String]` (path array)
**PostgreSQL Operator**: `#>`

**Example**:

```graphql
query {
  products(where: {
    metadata: { get_path: ["specs", "cpu"], eq: "Intel i7" }
  }) {
    id
    name
  }
}
```

**SQL Generated**:

```sql
WHERE metadata #> '{specs,cpu}' = '"Intel i7"'::jsonb
```

---

#### `get_path_text` - Get JSON Path as Text

**Description**: Extract value at JSON path as text
**GraphQL Type**: `[String]` (path array)
**PostgreSQL Operator**: `#>>`

**Example**:

```graphql
query {
  products(where: {
    metadata: { get_path_text: ["specs", "cpu"], contains: "Intel" }
  }) {
    id
    name
  }
}
```

**SQL Generated**:

```sql
WHERE metadata #>> '{specs,cpu}' LIKE '%Intel%'
```

---

## Text Regex Operators

**Use Case**: Pattern matching with POSIX regular expressions

**Requirements**: PostgreSQL text columns

**Performance Note**: Regex operators cannot use indexes and will perform sequential scans. Use full-text search for better performance on large datasets.

### Available Operators

#### `matches` - Regex Match

**Description**: Text matches POSIX regular expression
**GraphQL Type**: `String`
**PostgreSQL Operator**: `~`

**Example**:

```graphql
query {
  products(where: {
    sku: { matches: "^PROD-[0-9]{4}$" }
  }) {
    id
    sku
  }
}
```

**SQL Generated**:

```sql
WHERE sku ~ '^PROD-[0-9]{4}$'
```

**Use Case**: Validate format (e.g., SKU codes, phone numbers, IDs).

---

#### `imatches` - Case-Insensitive Regex

**Description**: Case-insensitive regex match
**GraphQL Type**: `String`
**PostgreSQL Operator**: `~*`

**Example**:

```graphql
query {
  users(where: {
    email: { imatches: ".*@company\\.com$" }
  }) {
    id
    email
  }
}
```

**SQL Generated**:

```sql
WHERE email ~* '.*@company\.com$'
```

---

#### `not_matches` - Negated Regex

**Description**: Text does NOT match regex
**GraphQL Type**: `String`
**PostgreSQL Operator**: `!~`

**Example**:

```graphql
query {
  products(where: {
    name: { not_matches: "^(test|demo)" }
  }) {
    id
    name
  }
}
```

**SQL Generated**:

```sql
WHERE name !~ '^(test|demo)'
```

**Use Case**: Exclude test/demo data, filter out specific patterns.

---

## Type Safety & Error Handling

### Operator Availability

Operators are only available for compatible field types. The GraphQL schema will only expose operators that make sense for each field:

**Works**:

```graphql
query {
  products(where: { tags: { overlaps: ["electronics"] } }) { id }  # ✅ Array field
  posts(where: { searchVector: { matches: "python" } }) { id }     # ✅ tsvector field
}
```

**Fails at GraphQL validation**:

```graphql
query {
  products(where: { id: { overlaps: ["foo"] } }) { id }  # ❌ ID is not an array
  posts(where: { title: { rank_gt: 0.5 } }) { id }       # ❌ String is not tsvector
}
```

### Runtime Type Safety

Some specialized operators require explicit type information:

**Required**:

- Typed Pydantic models with proper annotations
- GraphQL schema (provides type information)
- Table/view with known column types

**May return `None` (no filter)**:

- Dynamic queries without type hints
- Applying specialized operators to incompatible types

This is intentional to prevent incorrect SQL generation.

---

## Performance Best Practices

### Indexing Strategy

**Array operators** - Use GIN indexes:

```sql
CREATE INDEX idx_products_tags ON tb_product USING gin(tags);
```

**Full-text search** - GIN index is essential:

```sql
CREATE INDEX idx_posts_search ON tb_post USING gin(search_vector);
```

**JSONB operators**:

```sql
-- General purpose (supports all operations)
CREATE INDEX idx_product_attrs ON tb_product USING gin(attributes);

-- Containment only (smaller, faster)
CREATE INDEX idx_product_attrs_path ON tb_product
  USING gin(attributes jsonb_path_ops);
```

**Text regex** - Cannot be indexed. Consider alternatives:

- Use full-text search for text content
- Use `LIKE` with prefix (`name LIKE 'prefix%'`) which can use btree index
- Consider computed columns with functional indexes if pattern is fixed

### Query Optimization

**1. Combine filters efficiently**:

```graphql
query {
  products(where: {
    AND: [
      { tags: { overlaps: ["electronics"] } },  # Fast with GIN index
      { price: { lte: 100 } }                   # Fast with btree index
    ]
  }) { id name }
}
```

**2. Avoid sequential scans**:

```graphql
# ❌ Bad: Regex without index
products(where: { name: { matches: ".*widget.*" } })

# ✅ Good: Use full-text search instead
products(where: { searchVector: { plain_query: "widget" } })
```

**3. Use relevance ranking for full-text**:

```graphql
query {
  posts(where: {
    searchVector: {
      websearch_query: "python graphql",
      rank_gt: 0.1  # Filter low-relevance results
    }
  }) {
    id
    title
  }
}
```

**4. Limit result sets**:

```graphql
query {
  products(
    where: { tags: { overlaps: ["electronics"] } },
    limit: 20,
    offset: 0
  ) { id name }
}
```

---

## Common Use Cases

### E-commerce Product Filtering

```graphql
query {
  products(where: {
    AND: [
      { tags: { overlaps: ["electronics", "featured"] } },      # Category filter
      { attributes: { contains: {inStock: true} } },            # Availability
      { price: { gte: 50, lte: 500 } },                         # Price range
      { searchVector: { websearch_query: "laptop gaming" } }   # Text search
    ]
  }) {
    id
    name
    price
    tags
  }
}
```

### Content Management System

```graphql
query {
  articles(where: {
    AND: [
      { status: { eq: "published" } },
      { tags: { contains: "tutorial" } },
      { searchVector: {
        websearch_query: "graphql api",
        rank_gt: 0.15
      } }
    ]
  }) {
    id
    title
    publishedAt
  }
}
```

### User Permissions Query

```graphql
query {
  users(where: {
    AND: [
      { roles: { overlaps: ["admin", "moderator"] } },
      { permissions: { has_key: "manage_users" } },
      { metadata: { path_exists: "$.lastLogin" } }
    ]
  }) {
    id
    email
    roles
  }
}
```

---

## Migration Notes

### Upgrading from Basic Filtering

If you're currently using basic `eq`, `in`, etc., you can now use advanced operators:

**Before**:

```graphql
# Limited to exact match
products(where: { tags: { in: ["electronics"] } })
```

**After**:

```graphql
# Rich array operations
products(where: {
  tags: {
    overlaps: ["electronics", "gadget"],  # Any match
    len_gte: 2                            # At least 2 tags
  }
})
```

### No Breaking Changes

All existing queries continue to work. New operators are additive and opt-in.

---

## Troubleshooting

### "Operator not available for field"

**Problem**: GraphQL schema doesn't show expected operator
**Solution**: Ensure field type is correctly annotated:

```python
import fraiseql

@fraiseql.type
class Product:
    tags: list[str]           # ✅ Exposes array operators
    metadata: dict            # ✅ Exposes JSONB operators
    search_vector: str        # ❌ Needs TSVector type hint
```

### "Query timeout on large dataset"

**Problem**: Slow queries on tables with many rows
**Solution**:

1. Add appropriate indexes (GIN for arrays/JSONB/fulltext)
2. Use `EXPLAIN ANALYZE` to verify index usage
3. Add `limit` to queries
4. Consider materialized views for complex filters

### "Full-text search returns no results"

**Problem**: `tsvector` not properly configured
**Solution**:

1. Verify `tsvector` column exists and is populated
2. Check trigger is updating `tsvector` on changes
3. Verify language configuration matches your content
4. Use `ts_debug()` to troubleshoot tokenization

**Debug query**:

```sql
SELECT * FROM ts_debug('english', 'your search text');
```

### "Array overlaps not working on JSONB"

**Problem**: Using wrong operator for JSONB arrays
**Solution**: FraiseQL handles this automatically. Ensure your view structure is correct:

```sql
-- ✅ Correct: Keep native array column for filtering
CREATE VIEW v_product AS
SELECT
  id,
  tags,  -- Native array column available for WHERE clause
  jsonb_build_object('id', id, 'tags', tags) as data
FROM tb_product;
```

---

## Further Reading

- [Where Input Types](./where-input-types.md) - Basic filtering documentation
- [Nested Array Filtering](./nested-array-filtering.md) - Complex array queries
- [PostgreSQL Array Documentation](https://www.postgresql.org/docs/current/arrays.html)
- [PostgreSQL Full-Text Search](https://www.postgresql.org/docs/current/textsearch.html)
- [PostgreSQL JSONB Documentation](https://www.postgresql.org/docs/current/datatype-json.html)

---

**Questions or issues?** File an issue on the [FraiseQL GitHub repository](https://github.com/lionel-rowe/fraiseql).

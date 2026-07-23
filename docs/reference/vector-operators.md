# Vector Search Operators Reference

FraiseQL supports all 6 pgvector distance operators for vector similarity search. This reference provides a quick overview of each operator's purpose, use cases, and characteristics.

## Overview

Vector similarity search enables semantic search by comparing high-dimensional vectors (embeddings) using specialized distance metrics. Each operator serves different similarity concepts and use cases.

| Operator | Symbol | Range | Best For |
|----------|--------|-------|----------|
| Cosine Distance | `<=>` | 0.0 - 2.0 | Text similarity, semantic search |
| L2 Distance | `<->` | 0.0 - ∞ | Spatial similarity, exact matches |
| Inner Product | `<#>` | -∞ - ∞ | Learned similarity metrics |
| L1 Distance | `<+>` | 0.0 - ∞ | Sparse vectors, grid distances |
| Hamming Distance | `<~>` | 0 - dim | Binary vectors, hashing |
| Jaccard Distance | `<%>` | 0.0 - 1.0 | Set similarity, sparse binary |

## Distance Operators

### 1. Cosine Distance (`<=>`)

**Use when:** Comparing document similarity, semantic search (most common)

**Characteristics:**

- Measures angle between vectors (normalized)
- Range: 0.0 (identical) to 2.0 (opposite)
- Best for: Text embeddings, semantic similarity

**Example:**

```sql
-- Find similar documents
SELECT * FROM documents
ORDER BY embedding <=> '[0.1, 0.2, 0.3]'::vector
LIMIT 10;
```

### 2. L2 Distance (`<->`)

**Use when:** Euclidean distance needed, spatial similarity, exact matches

**Characteristics:**

- Measures straight-line distance in vector space
- Range: 0.0 (identical) to ∞ (very different)
- Best for: Image similarity, spatial data, precise matches

**Example:**

```sql
-- Find spatially similar items
SELECT * FROM images
ORDER BY embedding <-> '[0.5, 0.3, 0.8]'::vector
LIMIT 5;
```

### 3. Inner Product (`<#>`)

**Use when:** Dot product similarity, learned similarity metrics

**Characteristics:**

- Negative inner product (more negative = more similar)
- Range: -∞ to ∞
- Best for: Pre-trained embeddings, recommendation systems

**Example:**

```sql
-- Recommendation based on learned similarity
SELECT * FROM products
ORDER BY embedding <#> '[0.2, 0.7, 0.1]'::vector
LIMIT 10;
```

### 4. L1 Distance (`<+>`)

**Use when:** Manhattan distance, sparse vectors, grid-based distances

**Characteristics:**

- Sum of absolute differences
- Range: 0.0 (identical) to ∞ (very different)
- Best for: Sparse data, categorical features, grid navigation

**Example:**

```sql
-- Sparse vector similarity
SELECT * FROM features
ORDER BY embedding <+> '[0.0, 0.5, 0.0, 0.3]'::vector
LIMIT 8;
```

### 5. Hamming Distance (`<~>`)

**Use when:** Binary vectors, hash-based similarity

**Characteristics:**

- Count of differing bits
- Range: 0 (identical) to dimension size (completely different)
- Best for: Binary embeddings, locality-sensitive hashing

**Example:**

```sql
-- Binary hash similarity
SELECT * FROM hashes
ORDER BY embedding <~> '0101010101'::bit(10)
LIMIT 5;
```

### 6. Jaccard Distance (`<%>`)

**Use when:** Set similarity, sparse binary features

**Characteristics:**

- Measures set overlap (1 - Jaccard similarity)
- Range: 0.0 (identical sets) to 1.0 (no overlap)
- Best for: Tag similarity, sparse binary data

**Example:**

```sql
-- Set-based similarity
SELECT * FROM tags
ORDER BY embedding <%> '1010001010'::bit(10)
LIMIT 7;
```

## Choosing the Right Operator

### Decision Tree

```
Does your data have binary values?
├── YES → Sparse binary? → Jaccard Distance (<%>)
│   └── Dense binary? → Hamming Distance (<~>)
└── NO → Text embeddings? → Cosine Distance (<=>)
    └── Spatial data? → L2 Distance (<->)
        └── Sparse floats? → L1 Distance (<+>)
            └── Pre-trained embeddings? → Inner Product (<#>)
```

### Common Use Cases

| Use Case | Recommended Operator | Why |
|----------|---------------------|-----|
| Text Search | Cosine Distance | Handles semantic meaning, normalized |
| Image Similarity | L2 Distance | Euclidean distance in visual space |
| Recommendations | Inner Product | Optimized for learned embeddings |
| Sparse Features | L1 Distance | Robust to outliers, grid-like |
| Hash Matching | Hamming Distance | Efficient for binary comparisons |
| Tag Overlap | Jaccard Distance | Measures set intersection |

## Performance Considerations

### Index Types

- **HNSW**: Best for high-dimensional vectors (384+), approximate search
- **IVFFlat**: Good for medium datasets, exact search with speed tradeoff

### Query Optimization

```sql
-- Use appropriate index
CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops);

-- Pre-filter when possible
SELECT * FROM documents
WHERE tenant_id = '123'  -- Filter first
ORDER BY embedding <=> query_vector  -- Then vector search
LIMIT 10;
```

### Vector Dimensions

- **Small (64-256)**: Any operator works well
- **Medium (384-768)**: Cosine/L2 preferred
- **Large (1024+)**: Consider HNSW indexing, cosine preferred

## Related Documentation

- **[pgvector Feature Guide](../features/pgvector.md)** - Complete setup and usage guide
- **[RAG Tutorial](../ai-ml/rag-tutorial.md)** - End-to-end vector search implementation
- **[Vector Search Examples](../../examples/rag-system/)** - Working code examples

## See Also

- [pgvector GitHub Repository](https://github.com/pgvector/pgvector)
- [Vector Search Best Practices](https://github.com/pgvector/pgvector#best-practices)

# Vector Search Example

A GraphQL query that orders documents by similarity with each of pgvector's six
distance operators, optionally narrowed by category.

## Running it

```bash
# A PostgreSQL with pgvector, e.g. docker run -e POSTGRES_PASSWORD=pg -p 5432:5432 pgvector/pgvector:pg16
createdb vectordb
psql vectordb -f schema.sql

pip install -r requirements.txt
DATABASE_URL=postgresql://localhost/vectordb python main.py
```

`schema.sql` creates a `documents` table with a 384-dimension `embedding` and a
64-bit `binary_hash`, and four sample documents. Their embeddings come from
`sample_embedding(seed)`, a stand-in for an embedding model: in a real app you
store your model's output.

## How it works

- `Document` maps the `documents` table (`jsonb_column=None`), and
  `register_type_for_view(..., has_jsonb_data=False)` tells fraiseql its columns,
  so filters and ordering use them directly.
- `search_documents` takes one distance argument and orders by it with
  `OrderBy("embedding.cosine_distance", value=vector)`: an ordering by distance
  carries the vector to compare with. `category` becomes
  `where={"category": {"eq": ...}}`.

## Querying

```graphql
# Semantic search: the closest documents to a query embedding
query ($v: [Float!]) {
  searchDocuments(cosineDistance: $v, limit: 3) { title category }
}

# Same, among technical documents only
query ($v: [Float!]) {
  searchDocuments(cosineDistance: $v, category: "technical") { title }
}

# Binary similarity on the 64-bit hash
{
  searchDocuments(hammingDistance: "1100110011001100110011001100110011001100110011001100110011001100") {
    title
  }
}
```

`l2Distance`, `innerProduct` and `l1Distance` take a vector like
`cosineDistance`; `jaccardDistance` takes a bit string like `hammingDistance`.

## Distance semantics

| Argument | pgvector | Range |
|---|---|---|
| `cosineDistance` | `<=>` | 0.0 (identical) to 2.0 (opposite) |
| `l2Distance` | `<->` | 0.0 (identical) to ∞ |
| `innerProduct` | `<#>` | more negative = more similar |
| `l1Distance` | `<+>` | 0.0 (identical) to ∞ |
| `hammingDistance` | `<~>` | 0 to the bit length |
| `jaccardDistance` | `<%>` | 0.0 (identical sets) to 1.0 (no overlap) |

Results come back most similar first.

## Performance tips

1. Index vector columns (`schema.sql` has an HNSW index for cosine distance)
2. Match the column's dimensions to your embedding model
3. Limit results
4. Check query plans with `EXPLAIN` to see the index used

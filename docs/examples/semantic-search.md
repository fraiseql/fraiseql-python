# Semantic Search with pgvector

This example demonstrates how to implement semantic search using FraiseQL and PostgreSQL pgvector. We'll build a document search system that can find relevant content based on meaning rather than exact keyword matches.

## Overview

Semantic search uses vector embeddings to understand the meaning and context of text, enabling more intelligent search experiences. This example shows:

- Setting up a document database with vector embeddings
- Implementing semantic search queries
- Combining vector similarity with traditional filters
- Building a RAG (Retrieval-Augmented Generation) system

See [pgvector support](../features/pgvector.md) for the full list of distance operators
and how a vector field is filtered and sorted.

## Prerequisites

- PostgreSQL with pgvector extension
- An embedding model (a hosted API or a local model)
- Document corpus for embedding

## Database Schema

```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create documents table
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    content TEXT,
    embedding vector(1536),        -- dimension of your text embedding model
    image_embedding vector(1536),  -- optional: an image model's embedding
    category TEXT,
    tags TEXT[],
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create HNSW index for fast similarity search
CREATE INDEX documents_embedding_hnsw
ON documents
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- Create additional indexes for filtering
CREATE INDEX documents_category_idx ON documents (category);
CREATE INDEX documents_tags_idx ON documents USING gin (tags);
```

The distance operators work on a `vector` column of the view, not on a vector inside a
JSONB `data` column. This example reads the table itself, so the type is declared
without a JSONB column (`jsonb_column=None`); a view with a `data` column and the
vector as a column beside it works too (see [pgvector support](../features/pgvector.md)).

## Python Setup

```python
import asyncio
import json
import time

from psycopg.sql import SQL

import fraiseql
from fraiseql.db import DatabaseQuery, FraiseQLRepository
from fraiseql.types import ID


@fraiseql.type(sql_source="documents", jsonb_column=None)
class Document:
    id: ID
    title: str
    content: str | None
    embedding: list[float]  # Vector field, detected by its name
    image_embedding: list[float] | None  # A second vector field
    category: str | None
    tags: list[str] | None
```

## Embedding Generation

FraiseQL doesn't generate embeddings: call your embedding provider (a hosted API or a
local model) in `generate_embedding`. Its dimension must match the column's
(`vector(1536)` above).

```python
async def generate_embedding(text: str) -> list[float]:
    """Return the embedding of `text` from your embedding provider."""
    raise NotImplementedError("call your embedding model here")


async def generate_document_embedding(doc: dict) -> list[float]:
    """Generate embedding for a document combining title and content."""
    text = f"{doc['title']}\n\n{doc['content']}"
    return await generate_embedding(text)


def to_vector(embedding: list[float]) -> str:
    """Format an embedding as a pgvector literal."""
    return "[" + ",".join(str(x) for x in embedding) + "]"
```

## Data Ingestion

`db.run()` runs a SQL statement with named parameters; `fetch_result=False` for a
statement that returns no rows:

```python
INSERT_DOCUMENT = SQL(
    "INSERT INTO documents (title, content, embedding, category, tags)"
    " VALUES (%(title)s, %(content)s, %(embedding)s::vector, %(category)s, %(tags)s)"
)


async def ingest_documents(db: FraiseQLRepository, documents: list[dict]) -> None:
    """Ingest documents with embeddings into the database."""
    for doc in documents:
        embedding = await generate_document_embedding(doc)
        await db.run(
            DatabaseQuery(
                INSERT_DOCUMENT,
                {
                    "title": doc["title"],
                    "content": doc["content"],
                    "embedding": to_vector(embedding),
                    "category": doc.get("category"),
                    "tags": doc.get("tags", []),
                },
                fetch_result=False,
            )
        )
```

## Basic Semantic Search

`db.find()` returns a ready-made GraphQL response (`RustResponseBytes`): a resolver
returns it as is, and Python code reads the rows from it with `json.loads(bytes(...))`.

```python
def rows(result, field_name: str = "documents") -> list[dict]:
    """The rows of a find() response, for use in Python code."""
    return json.loads(bytes(result))["data"][field_name]


async def search_by_embedding(
    db: FraiseQLRepository,
    embedding: list[float],
    limit: int = 10,
) -> list[dict]:
    """The documents nearest to an embedding, nearest first."""
    result = await db.find(
        "documents",
        "documents",
        order_by={"embedding": {"cosine_distance": embedding}},
        limit=limit,
    )
    return rows(result)


async def semantic_search(db: FraiseQLRepository, query: str, limit: int = 10) -> list[dict]:
    """Perform semantic search on documents."""
    query_embedding = await generate_embedding(query)
    return await search_by_embedding(db, query_embedding, limit)
```

As a GraphQL query, the resolver returns what `find()` returns, and selects the
fields the client asked for:

```python
@fraiseql.query
async def search_documents(info, query: str, limit: int = 10) -> list[Document]:
    """Documents nearest to a text query."""
    query_embedding = await generate_embedding(query)
    return await info.context["db"].find(
        "documents",
        "searchDocuments",
        info,
        order_by={"embedding": {"cosine_distance": query_embedding}},
        limit=limit,
    )
```

## Advanced Search Features

### Hybrid Search (Vector + Filters)

A distance filter takes the query vector and the largest distance to keep
(`threshold`); it composes with the other operators:

```python
async def hybrid_search(
    db: FraiseQLRepository,
    query: str,
    category: str | None = None,
    tags: list[str] | None = None,
    max_distance: float = 0.5,
    limit: int = 10,
) -> list[dict]:
    """Combine vector similarity with traditional filters."""
    query_embedding = await generate_embedding(query)

    where = {
        "embedding": {"cosine_distance": {"vector": query_embedding, "threshold": max_distance}}
    }
    if category:
        where["category"] = {"eq": category}
    if tags:
        where["tags"] = {"overlaps": tags}  # PostgreSQL array overlap (&&)

    result = await db.find(
        "documents",
        "documents",
        where=where,
        order_by={"embedding": {"cosine_distance": query_embedding}},
        limit=limit,
    )
    return rows(result)
```

### Search with Different Distance Metrics

```python
DISTANCE_OPERATORS = {
    "cosine": "cosine_distance",  # <=>
    "l2": "l2_distance",  # <->
    "inner_product": "inner_product",  # <#> (negative inner product)
}


async def search_with_distance_metric(
    db: FraiseQLRepository,
    query: str,
    metric: str = "cosine",
    limit: int = 10,
) -> list[dict]:
    """Search using different distance metrics."""
    query_embedding = await generate_embedding(query)
    operator = DISTANCE_OPERATORS.get(metric, "cosine_distance")

    result = await db.find(
        "documents",
        "documents",
        order_by={"embedding": {operator: query_embedding}},
        limit=limit,
    )
    return rows(result)
```

## RAG System Implementation

```python
async def retrieve_relevant_context(
    db: FraiseQLRepository,
    question: str,
    max_tokens: int = 2000,
    limit: int = 5,
) -> str:
    """Retrieve relevant context for RAG systems."""
    documents = await semantic_search(db, question, limit=limit)

    context_parts = []
    total_tokens = 0
    for doc in documents:
        content_tokens = len((doc["content"] or "").split()) * 1.3  # Rough token estimate
        if total_tokens + content_tokens > max_tokens:
            break
        context_parts.append(f"Document: {doc['title']}\n{doc['content']}")
        total_tokens += content_tokens

    return "\n\n".join(context_parts)


async def rag_query(db: FraiseQLRepository, question: str, llm_client) -> str:
    """Complete RAG query: retrieve context and generate answer."""
    context = await retrieve_relevant_context(db, question)

    prompt = f"""
    Based on the following context, answer the question.

    Context:
    {context}

    Question: {question}

    Answer:
    """

    return await llm_client.generate(prompt)  # your LLM client
```

## GraphQL API Usage

A list query over `Document` gets `where`, `orderBy`, `limit` and `offset`. A vector
operator takes the query vector as `{dense: [...]}`, and a `where` on it needs
`distanceWithin`, the largest distance to keep:

```python
@fraiseql.query
async def documents(info) -> list[Document]:
    return await info.context["db"].find("documents", "documents", info)
```

```graphql
# Semantic search
query SearchDocuments($embedding: [Float!]!, $limit: Int) {
  documents(
    where: { embedding: { cosineDistance: { dense: $embedding }, distanceWithin: 0.5 } }
    orderBy: { embedding: { cosineDistance: { dense: $embedding } } }
    limit: $limit
  ) {
    id
    title
    content
    category
    tags
  }
}
```

```graphql
# Hybrid search
query HybridSearch($embedding: [Float!]!, $category: String, $tags: [String!], $limit: Int) {
  documents(
    where: {
      embedding: { cosineDistance: { dense: $embedding }, distanceWithin: 0.5 }
      category: { eq: $category }
      tags: { overlaps: $tags }
    }
    orderBy: { embedding: { cosineDistance: { dense: $embedding } } }
    limit: $limit
  ) {
    id
    title
    content
    category
    tags
  }
}
```

## Performance Optimization

### Index Tuning

```sql
-- For high-dimensional vectors (1536+), use HNSW
CREATE INDEX documents_embedding_hnsw
ON documents USING hnsw (embedding vector_cosine_ops)
WITH (
  m = 16,              -- Number of connections per layer
  ef_construction = 64  -- Build-time search quality
);

-- For lower dimensions, consider IVFFlat
CREATE INDEX documents_embedding_ivfflat
ON documents USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);    -- Number of clusters
```

### Query Optimization

```python
async def search_examples(db: FraiseQLRepository, query: str) -> None:
    # Use appropriate limits to control result size
    results = await semantic_search(db, query, limit=20)

    # Combine with other filters to reduce search space
    results = await hybrid_search(db, query, category="technical", limit=10)


async def batch_search(db: FraiseQLRepository, queries: list[str]) -> list[list[dict]]:
    # Run independent searches concurrently
    return await asyncio.gather(*(semantic_search(db, query) for query in queries))
```

## Complete Example Application

```python
from fastapi import FastAPI

from fraiseql.fastapi import create_fraiseql_app
from fraiseql.fastapi.app import create_db_pool

DATABASE_URL = "postgresql://localhost/mydb"

# Sample documents
SAMPLE_DOCUMENTS = [
    {
        "title": "Python Programming Guide",
        "content": "Python is a high-level programming language known for its simplicity...",
        "category": "programming",
        "tags": ["python", "programming", "tutorial"],
    },
    {
        "title": "Machine Learning Basics",
        "content": "Machine learning is a subset of artificial intelligence...",
        "category": "ml",
        "tags": ["machine-learning", "ai", "data-science"],
    },
    # ... more documents
]

# The GraphQL API: documents and searchDocuments
app: FastAPI = create_fraiseql_app(
    database_url=DATABASE_URL,
    types=[Document],
    queries=[documents, search_documents],
)


async def main() -> None:
    # A script outside the app builds its own pool and repository
    pool = await create_db_pool(DATABASE_URL)
    db = FraiseQLRepository(pool)
    try:
        await ingest_documents(db, SAMPLE_DOCUMENTS)

        results = await semantic_search(db, "programming languages")
        print(f"Found {len(results)} documents")

        hybrid_results = await hybrid_search(db, "artificial intelligence", category="ml")
        print(f"Found {len(hybrid_results)} ML documents")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
```

## Distance Semantics Explanation

### Cosine Distance

- **Range**: 0.0 (identical) to 2.0 (opposite)
- **Best for**: Text similarity, semantic search
- **Interpretation**: Lower values = more similar

### L2 Distance

- **Range**: 0.0 (identical) to ∞ (very different)
- **Best for**: Spatial data, exact matches
- **Interpretation**: Euclidean distance in vector space

### Inner Product

- **Range**: -∞ to ∞ (more negative = more similar)
- **Best for**: Learned similarity metrics
- **Interpretation**: pgvector's `<#>` returns the negative inner product, so sorting
  ascending puts the most similar first

## Troubleshooting

### Common Issues

**"extension 'vector' does not exist"**

```bash
# Install pgvector on your system
sudo apt-get install postgresql-16-pgvector  # Ubuntu/Debian
# or
brew install pgvector  # macOS
```

**Slow queries without indexes**

```sql
-- Check if your queries use the index
EXPLAIN SELECT * FROM documents
ORDER BY embedding <=> '[...]'::vector LIMIT 10;
-- Should show "Index Scan" not "Seq Scan"
```

**Dimension mismatches**

```sql
-- Check vector dimensions
SELECT id, vector_dims(embedding) as dims FROM documents LIMIT 5;
-- All should show the same dimension (e.g., 1536)
```

**Memory issues with large result sets**: use smaller limits (`limit=50`, not 1000)
and `offset` for further pages.

## Additional Examples

### Recommendation System

```python
async def get_similar_documents(
    db: FraiseQLRepository,
    document_id: ID,
    limit: int = 5,
) -> list[dict]:
    """Find documents similar to a given document."""
    source = rows(
        await db.find("documents", "documents", where={"id": {"eq": str(document_id)}}, limit=1)
    )
    if not source:
        return []
    source_embedding = source[0]["embedding"]

    result = await db.find(
        "documents",
        "documents",
        where={"id": {"neq": str(document_id)}},  # Exclude the source document
        order_by={"embedding": {"cosine_distance": source_embedding}},
        limit=limit,
    )
    return rows(result)
```

### Content Deduplication

A cosine distance below 0.1 means a cosine similarity above 0.9:

```python
async def find_duplicate_content(
    db: FraiseQLRepository,
    content: str,
    max_distance: float = 0.1,
) -> list[dict]:
    """Find documents whose content embedding is within max_distance."""
    content_embedding = await generate_embedding(content)

    result = await db.find(
        "documents",
        "documents",
        where={
            "embedding": {"cosine_distance": {"vector": content_embedding, "threshold": max_distance}}
        },
        order_by={"embedding": {"cosine_distance": content_embedding}},
        limit=10,
    )
    return rows(result)
```

### Multi-Modal Search

Each vector field is filtered and sorted on its own (`image_embedding` here):

```python
async def search_by_image(
    db: FraiseQLRepository,
    image_embedding: list[float],
    text_query: str | None = None,
    max_distance: float = 0.5,
    limit: int = 10,
) -> list[dict]:
    """Search documents by image embedding, optionally also near a text query."""
    where = {
        "image_embedding": {
            "cosine_distance": {"vector": image_embedding, "threshold": max_distance}
        }
    }
    if text_query:
        text_embedding = await generate_embedding(text_query)
        where["embedding"] = {
            "cosine_distance": {"vector": text_embedding, "threshold": max_distance}
        }

    result = await db.find(
        "documents",
        "documents",
        where=where,
        order_by={"image_embedding": {"cosine_distance": image_embedding}},
        limit=limit,
    )
    return rows(result)
```

## Advanced Patterns

### Query Expansion

```python
async def expanded_search(
    db: FraiseQLRepository,
    query: str,
    expand_terms: list[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search with the average embedding of the query and its expansion terms."""
    texts = [query, *(expand_terms or [])]
    embeddings = await asyncio.gather(*(generate_embedding(text) for text in texts))

    combined_embedding = [sum(values) / len(embeddings) for values in zip(*embeddings)]
    return await search_by_embedding(db, combined_embedding, limit)
```

### Cached Embeddings

```python
embedding_cache: dict[str, list[float]] = {}


async def get_cached_embedding(text: str) -> list[float]:
    """Get embedding with caching to reduce calls to the embedding model."""
    cache_key = text.lower().strip()
    if cache_key not in embedding_cache:
        embedding_cache[cache_key] = await generate_embedding(text)
    return embedding_cache[cache_key]
```

Use a size- and time-bounded cache (such as `cachetools.TTLCache`) in production.

### Batch Processing

```python
async def batch_semantic_search(
    db: FraiseQLRepository,
    queries: list[str],
    limit: int = 10,
) -> list[list[dict]]:
    """Process multiple semantic searches in parallel."""
    embeddings = await asyncio.gather(*(generate_embedding(query) for query in queries))
    return await asyncio.gather(
        *(search_by_embedding(db, embedding, limit) for embedding in embeddings)
    )
```

## Performance Monitoring

```python
async def benchmark_search(
    db: FraiseQLRepository,
    query: str,
    runs: int = 10,
) -> dict[str, float]:
    """Benchmark search performance."""
    query_embedding = await generate_embedding(query)

    times = []
    for _ in range(runs):
        start_time = time.perf_counter()
        await search_by_embedding(db, query_embedding, limit=10)
        times.append(time.perf_counter() - start_time)

    return {
        "avg_time": sum(times) / len(times),
        "min_time": min(times),
        "max_time": max(times),
        "runs": runs,
    }
```

## Next Steps

- **Experiment with different embedding models** (hosted or local)
- **Implement query expansion** for better search results
- **Add relevance scoring** and ranking
- **Build recommendation systems** using vector similarity
- **Implement caching** for frequently searched embeddings
- **Add A/B testing** for different search strategies
- **Implement search analytics** and user behavior tracking

## References

- [FraiseQL pgvector Documentation](../features/pgvector.md)
- [pgvector GitHub](https://github.com/pgvector/pgvector)
- [Sentence Transformers](https://www.sbert.net/)
- [Vector Search Best Practices](https://github.com/pgvector/pgvector#best-practices)

This example provides a solid foundation for building semantic search applications with FraiseQL and pgvector.

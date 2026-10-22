# Semantic Search with pgvector

This example demonstrates how to implement semantic search using FraiseQL and PostgreSQL pgvector. We'll build a document search system that can find relevant content based on meaning rather than exact keyword matches.

## Overview

Semantic search uses vector embeddings to understand the meaning and context of text, enabling more intelligent search experiences. This example shows:

- Setting up a document database with vector embeddings
- Implementing semantic search queries
- Combining vector similarity with traditional filters
- Building a RAG (Retrieval-Augmented Generation) system

## Prerequisites

- PostgreSQL with pgvector extension
- Python with required ML libraries
- Document corpus for embedding

## Database Schema

```sql
-- Enable pgvector extension
CREATE EXTENSION vector;

-- Create documents table
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    content TEXT,
    embedding vector(1536),  -- OpenAI text-embedding-ada-002
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

## Python Setup

```python
import asyncio
from typing import List
from fraiseql.types import ID

import openai
from fraiseql import fraise_type
from fraiseql.db import FraiseQLRepository

# Configure OpenAI (or your preferred embedding provider)
openai.api_key = "your-api-key"

@fraise_type
class Document:
    id: ID
    title: str
    content: str
    embedding: List[float]  # Vector field detected by name
    category: str
    tags: List[str]
    created_at: str
    updated_at: str
```

## Embedding Generation

```python
async def generate_embedding(text: str) -> List[float]:
    """Generate embeddings using OpenAI's API."""
    response = await openai.Embedding.acreate(
        input=text,
        model="text-embedding-ada-002"
    )
    return response["data"][0]["embedding"]

async def generate_document_embedding(doc: dict) -> List[float]:
    """Generate embedding for a document combining title and content."""
    text = f"{doc['title']}\n\n{doc['content']}"
    return await generate_embedding(text)
```

## Data Ingestion

```python
async def ingest_documents(repo: FraiseQLRepository, documents: List[dict]):
    """Ingest documents with embeddings into the database."""

    # Generate embeddings for all documents
    for doc in documents:
        embedding = await generate_document_embedding(doc)
        doc['embedding'] = embedding

    # Bulk insert (you'd implement this based on your data source)
    for doc in documents:
        await repo.execute("""
            INSERT INTO documents (title, content, embedding, category, tags)
            VALUES (%s, %s, %s::vector, %s, %s)
        """, (
            doc['title'],
            doc['content'],
            f"[{','.join(str(x) for x in doc['embedding'])}]",
            doc.get('category'),
            doc.get('tags', [])
        ))
```

## Basic Semantic Search

```python
async def semantic_search(
    repo: FraiseQLRepository,
    query: str,
    limit: int = 10
) -> List[dict]:
    """Perform semantic search on documents."""

    # Generate embedding for the search query
    query_embedding = await generate_embedding(query)

    # Search using vector similarity
    result = await repo.find(
        "documents",
        where={
            "embedding": {
                "cosine_distance": query_embedding
            }
        },
        order_by={
            "embedding": {
                "cosine_distance": query_embedding
            }
        },
        limit=limit,
    )

    return extract_graphql_data(result, "documents")
```

## Advanced Search Features

### Hybrid Search (Vector + Text)

```python
async def hybrid_search(
    repo: FraiseQLRepository,
    query: str,
    category: str = None,
    tags: List[str] = None,
    limit: int = 10
) -> List[dict]:
    """Combine vector similarity with traditional filters."""

    query_embedding = await generate_embedding(query)

    # Build where clause
    where_clause = {
        "embedding": {
            "cosine_distance": query_embedding
        }
    }

    # Add category filter if specified
    if category:
        where_clause["category"] = {"eq": category}

    # Add tags filter if specified
    if tags:
        where_clause["tags"] = {"overlap": tags}  # PostgreSQL array overlap

    result = await repo.find(
        "documents",
        where=where_clause,
        order_by={
            "embedding": {
                "cosine_distance": query_embedding
            }
        },
        limit=limit,
    )

    return extract_graphql_data(result, "documents")
```

### Search with Different Distance Metrics

```python
async def search_with_distance_metric(
    repo: FraiseQLRepository,
    query: str,
    metric: str = "cosine",
    limit: int = 10
) -> List[dict]:
    """Search using different distance metrics."""

    query_embedding = await generate_embedding(query)

    # Choose distance operator based on metric
    distance_operators = {
        "cosine": "cosine_distance",
        "l2": "l2_distance",
        "inner_product": "inner_product"
    }

    operator = distance_operators.get(metric, "cosine_distance")

    result = await repo.find(
        "documents",
        where={
            "embedding": {
                operator: query_embedding
            }
        },
        order_by={
            "embedding": {
                operator: query_embedding
            }
        },
        limit=limit,
    )

    return extract_graphql_data(result, "documents")
```

## RAG System Implementation

```python
async def retrieve_relevant_context(
    repo: FraiseQLRepository,
    question: str,
    max_tokens: int = 2000,
    limit: int = 5
) -> str:
    """Retrieve relevant context for RAG systems."""

    # Search for relevant documents
    documents = await semantic_search(repo, question, limit=limit)

    # Combine content from relevant documents
    context_parts = []
    total_tokens = 0

    for doc in documents:
        # Estimate tokens (rough approximation)
        content_tokens = len(doc['content'].split()) * 1.3  # Rough token estimate

        if total_tokens + content_tokens > max_tokens:
            break

        context_parts.append(f"Document: {doc['title']}\n{doc['content']}")
        total_tokens += content_tokens

    return "\n\n".join(context_parts)

async def rag_query(
    repo: FraiseQLRepository,
    question: str,
    llm_client
) -> str:
    """Complete RAG query: retrieve context and generate answer."""

    # Retrieve relevant context
    context = await retrieve_relevant_context(repo, question)

    # Generate answer using LLM with context
    prompt = f"""
    Based on the following context, answer the question.

    Context:
    {context}

    Question: {question}

    Answer:
    """

    response = await llm_client.generate(prompt)
    return response
```

## GraphQL API Usage

```python
# GraphQL query for semantic search
query SearchDocuments($embedding: [Float!]!, $limit: Int) {
  documents(
    where: {
      embedding: {
        cosine_distance: $embedding
      }
    }
    orderBy: {
      embedding: {
        cosine_distance: $embedding
      }
    }
    limit: $limit
  ) {
    id
    title
    content
    category
    tags
  }
}

# GraphQL query for hybrid search
query HybridSearch(
  $embedding: [Float!]!
  $category: String
  $tags: [String!]
  $limit: Int
) {
  documents(
    where: {
      embedding: {
        cosine_distance: $embedding
      }
      category: { eq: $category }
      tags: { overlap: $tags }
    }
    orderBy: {
      embedding: {
        cosine_distance: $embedding
      }
    }
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
# Use appropriate limits to control result size
results = await semantic_search(repo, query, limit=20)

# Combine with other filters to reduce search space
results = await hybrid_search(repo, query, category="technical", limit=10)

# Use async processing for batch operations
async def batch_search(queries: List[str]) -> List[List[dict]]:
    tasks = [semantic_search(repo, query) for query in queries]
    return await asyncio.gather(*tasks)
```

## Complete Example Application

```python
import asyncio
from fastapi import FastAPI
from fraiseql.fastapi import FraiseQLApp

# Sample documents
SAMPLE_DOCUMENTS = [
    {
        "title": "Python Programming Guide",
        "content": "Python is a high-level programming language known for its simplicity and readability...",
        "category": "programming",
        "tags": ["python", "programming", "tutorial"]
    },
    {
        "title": "Machine Learning Basics",
        "content": "Machine learning is a subset of artificial intelligence that enables computers to learn...",
        "category": "ml",
        "tags": ["machine-learning", "ai", "data-science"]
    },
    # ... more documents
]

async def main():
    # Initialize FraiseQL app
    app = FraiseQLApp()

    # Get repository
    repo = app.get_repository()

    # Ingest sample data
    await ingest_documents(repo, SAMPLE_DOCUMENTS)

    # Perform searches
    results = await semantic_search(repo, "programming languages")
    print(f"Found {len(results)} documents")

    hybrid_results = await hybrid_search(
        repo,
        "artificial intelligence",
        category="ml"
    )
    print(f"Found {len(hybrid_results)} ML documents")

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
- **Interpretation**: Dot product of normalized vectors

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

**Memory issues with large result sets**

```python
# Use smaller limits and pagination
results = await semantic_search(repo, query, limit=50)  # Not 1000
```

## Additional Examples

### Recommendation System

```python
from fraiseql.types import ID

async def get_similar_products(
    repo: FraiseQLRepository,
    product_id: ID,
    limit: int = 5
) -> List[dict]:
    """Find products similar to a given product."""

    # Get the source product's embedding
    source_result = await repo.find("products", where={"id": {"eq": str(product_id)}})
    source_products = extract_graphql_data(source_result, "products")

    if not source_products:
        return []

    source_embedding = source_products[0]["embedding"]

    # Find similar products (excluding the source product)
    result = await repo.find(
        "products",
        where={
            "id": {"neq": str(product_id)},  # Exclude source product
            "embedding": {"cosine_distance": source_embedding}
        },
        order_by={"embedding": {"cosine_distance": source_embedding}},
        limit=limit,
    )

    return extract_graphql_data(result, "products")
```

### Content Deduplication

```python
async def find_duplicate_content(
    repo: FraiseQLRepository,
    content: str,
    threshold: float = 0.95
) -> List[dict]:
    """Find documents with similar content using embeddings."""

    # Generate embedding for the content
    content_embedding = await generate_embedding(content)

    # Find documents with high similarity (low distance)
    # Cosine distance < 0.1 means similarity > 0.95
    result = await repo.find(
        "documents",
        where={
            "embedding": {"cosine_distance": content_embedding}
        },
        order_by={"embedding": {"cosine_distance": content_embedding}},
        limit=10,
    )

    documents = extract_graphql_data(result, "documents")

    # Filter by similarity threshold
    similar_docs = []
    for doc in documents:
        # Calculate similarity from distance
        similarity = 1 - (doc.get("cosine_distance", 1) / 2)
        if similarity >= threshold:
            doc["similarity"] = similarity
            similar_docs.append(doc)

    return similar_docs
```

### Multi-Modal Search

```python
async def search_by_image(
    repo: FraiseQLRepository,
    image_embedding: List[float],
    text_query: str = None,
    limit: int = 10
) -> List[dict]:
    """Search documents using image embeddings, optionally combined with text."""

    where_clause = {"image_embedding": {"cosine_distance": image_embedding}}

    # Add text search if provided
    if text_query:
        text_embedding = await generate_embedding(text_query)
        where_clause["embedding"] = {"cosine_distance": text_embedding}

    result = await repo.find(
        "documents",
        where=where_clause,
        order_by={"image_embedding": {"cosine_distance": image_embedding}},
        limit=limit,
    )

    return extract_graphql_data(result, "documents")
```

## Advanced Patterns

### Query Expansion

```python
async def expanded_search(
    repo: FraiseQLRepository,
    query: str,
    expand_terms: List[str] = None
) -> List[dict]:
    """Search with query expansion for better results."""

    # Generate embedding for original query
    base_embedding = await generate_embedding(query)

    # If expansion terms provided, combine embeddings
    if expand_terms:
        expanded_texts = [query] + expand_terms
        embeddings = await asyncio.gather(*[
            generate_embedding(text) for text in expanded_texts
        ])

        # Average the embeddings (simple approach)
        combined_embedding = []
        for i in range(len(embeddings[0])):
            combined_embedding.append(
                sum(emb[i] for emb in embeddings) / len(embeddings)
            )
    else:
        combined_embedding = base_embedding

    return await semantic_search(repo, combined_embedding)
```

### Cached Embeddings

```python
import asyncio
from typing import Dict, Tuple
from cachetools import TTLCache

# Cache for embeddings (TTL: 1 hour)
embedding_cache = TTLCache(maxsize=1000, ttl=3600)

async def get_cached_embedding(text: str) -> List[float]:
    """Get embedding with caching to reduce API calls."""

    cache_key = text.lower().strip()

    if cache_key in embedding_cache:
        return embedding_cache[cache_key]

    embedding = await generate_embedding(text)
    embedding_cache[cache_key] = embedding

    return embedding
```

### Batch Processing

```python
async def batch_semantic_search(
    repo: FraiseQLRepository,
    queries: List[str],
    limit: int = 10
) -> List[List[dict]]:
    """Process multiple semantic searches in parallel."""

    # Generate embeddings in parallel
    embeddings = await asyncio.gather(*[
        generate_embedding(query) for query in queries
    ])

    # Execute searches in parallel
    search_tasks = [
        semantic_search(repo, embedding, limit)
        for embedding in embeddings
    ]

    return await asyncio.gather(*search_tasks)
```

## Integration Examples

### With OpenAI

```python
import openai

async def openai_semantic_search(
    repo: FraiseQLRepository,
    query: str,
    model: str = "text-embedding-ada-002"
) -> List[dict]:
    """Semantic search using OpenAI embeddings."""

    # Generate embedding
    response = await openai.Embedding.acreate(
        input=query,
        model=model
    )
    embedding = response["data"][0]["embedding"]

    return await semantic_search(repo, embedding)
```

### With Cohere

```python
import cohere

async def cohere_semantic_search(
    repo: FraiseQLRepository,
    query: str,
    model: str = "embed-english-v3.0"
) -> List[dict]:
    """Semantic search using Cohere embeddings."""

    co = cohere.Client(api_key="your-api-key")

    response = co.embed(
        texts=[query],
        model=model,
        input_type="search_query"
    )

    embedding = response.embeddings[0]
    return await semantic_search(repo, embedding)
```

### With Sentence Transformers

```python
from sentence_transformers import SentenceTransformer

# Load model once
model = SentenceTransformer('all-MiniLM-L6-v2')

async def local_semantic_search(
    repo: FraiseQLRepository,
    query: str
) -> List[dict]:
    """Semantic search using local Sentence Transformers."""

    # Generate embedding locally (no API calls)
    embedding = model.encode(query).tolist()

    return await semantic_search(repo, embedding)
```

## Performance Monitoring

```python
import time

async def benchmark_search(
    repo: FraiseQLRepository,
    query: str,
    runs: int = 10
) -> Dict[str, float]:
    """Benchmark search performance."""

    query_embedding = await generate_embedding(query)

    times = []
    for _ in range(runs):
        start_time = time.time()

        await semantic_search(repo, query_embedding, limit=10)

        end_time = time.time()
        times.append(end_time - start_time)

    return {
        "avg_time": sum(times) / len(times),
        "min_time": min(times),
        "max_time": max(times),
        "runs": runs
    }
```

## Next Steps

- **Experiment with different embedding models** (Cohere, Sentence Transformers)
- **Implement query expansion** for better search results
- **Add relevance scoring** and ranking
- **Build recommendation systems** using vector similarity
- **Implement caching** for frequently searched embeddings
- **Add A/B testing** for different search strategies
- **Implement search analytics** and user behavior tracking

## References

- [FraiseQL pgvector Documentation](../features/pgvector.md)
- [pgvector GitHub](https://github.com/pgvector/pgvector)
- [OpenAI Embeddings Guide](https://platform.openai.com/docs/guides/embeddings)
- [Cohere Embeddings](https://docs.cohere.com/docs/embeddings)
- [Sentence Transformers](https://www.sbert.net/)
- [Vector Search Best Practices](https://github.com/pgvector/pgvector#best-practices)

This example provides a solid foundation for building semantic search applications with FraiseQL and pgvector.

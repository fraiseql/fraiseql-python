# Building a RAG System with FraiseQL

**Time to Complete:** 60-90 minutes
**Difficulty:** Intermediate
**Prerequisites:** FraiseQL v1.8.0+, PostgreSQL 14+, OpenAI API key

---

## What You'll Build

A complete Retrieval-Augmented Generation (RAG) system that combines:

- **Semantic Search**: Find documents by meaning, not just keywords
- **Vector Embeddings**: Store document representations using pgvector
- **GraphQL API**: Query documents and perform similarity search
- **LangChain Integration**: Advanced RAG pipelines with question answering

## Why RAG Matters

Traditional search systems match keywords, but RAG understands **semantic meaning**:

- ❌ Traditional: "database performance" → matches only exact words
- ✅ RAG: "how to make my queries faster" → understands the intent

RAG systems are essential for:

- **Knowledge bases** that answer questions from documentation
- **Customer support** that finds relevant help articles
- **Research tools** that discover related content
- **Chatbots** that provide accurate, contextual responses

---

## Prerequisites

### Software Requirements

```bash
# PostgreSQL 14+ with pgvector extension
createdb ragdb
psql ragdb -c "CREATE EXTENSION vector;"

# Python 3.8+
python --version  # Should be 3.8 or higher
```

### API Keys

You'll need an OpenAI API key for embeddings and language models:

```bash
# Get your key from https://platform.openai.com/api-keys
export OPENAI_API_KEY="your-api-key-here"
```

### Install Dependencies

```bash
# Clone FraiseQL (if you haven't already)
git clone https://github.com/fraiseql/fraiseql.git
cd fraiseql/examples/rag-system

# Install all dependencies
pip install -r requirements.txt
```

---

## Step 1: Database Schema Setup

The Trinity Pattern provides clean separation between commands and queries:

```sql
-- Load the schema
psql ragdb < schema.sql
```

### Understanding the Trinity Pattern

1. **`tb_document`** - Command table for storing documents
2. **`v_document`** - Read view for accessing documents
3. **`tv_document_embedding`** - Table view with vector embeddings

This pattern gives you:

- **Performance**: Optimized read/write operations
- **Clarity**: Clear separation of concerns
- **Scalability**: Easy to extend and maintain

### Key Schema Features

```sql
-- Documents with metadata
CREATE TABLE tb_document (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT,                    -- Where the document came from
    metadata JSONB DEFAULT '{}',     -- Flexible metadata storage
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Vector embeddings for semantic search
CREATE TABLE tv_document_embedding (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES tb_document(id),
    embedding vector(1536),          -- OpenAI embedding dimensions
    embedding_model TEXT NOT NULL DEFAULT 'text-embedding-ada-002',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Performance indexes
CREATE INDEX ON tv_document_embedding
USING hnsw (embedding vector_cosine_ops);
```

---

## Step 2: Start the Application

```bash
# Set your database URL
export DATABASE_URL="postgresql://localhost:5432/ragdb"

# Start the application
python app.py
```

You should see:

```
🚀 RAG System Example

📝 GraphQL endpoint: http://localhost:8000/graphql
🔍 REST endpoints:
   • POST /api/documents/search - Semantic search
   • POST /api/rag/ask - RAG question answering
   • POST /api/documents/embed - Create with embedding
   • GET /api/rag/status - Embeddings and LLM availability
   • GET /health - Health check
```

Visit http://localhost:8000/graphql to open the GraphQL playground.

---

## Step 3: Add Documents

### Using the REST API

Documents are added through the REST endpoint, which embeds their content. (The
GraphQL API reads documents: `documents` and `document`.)

```bash
curl -X POST "http://localhost:8000/api/documents/embed" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Security by Design in FraiseQL",
    "content": "FraiseQL provides security through automatic PostgreSQL session variable injection from JWT tokens. Views automatically filter by tenant_id using current_setting(), making it impossible to query other tenants data. The framework uses explicit field contracts to prevent data leaks and implements row-level security at the database level, not application level.",
    "source": "blog",
    "metadata": {"category": "security", "difficulty": "intermediate", "tags": ["security", "multi-tenancy"]}
  }'
```

---

## Step 4: Generate Embeddings

Embeddings are numerical representations of text that capture semantic meaning.

### Understanding Embeddings

- **Dimensions**: 1536 for OpenAI's text-embedding-ada-002
- **Similarity**: Cosine similarity (0 = identical, 2 = opposite)
- **Storage**: Stored as PostgreSQL vector type

### Manual Embedding Generation

```python
from langchain_openai import OpenAIEmbeddings

# Initialize embeddings
embeddings = OpenAIEmbeddings(openai_api_key="your-api-key")

# Generate embedding for a text
text = "How does vector search work?"
embedding = embeddings.embed_query(text)

print(f"Embedding dimensions: {len(embedding)}")  # 1536
print(f"First 5 values: {embedding[:5]}")
```

### Automatic Embedding with the Application

The application automatically generates embeddings when you use the `/api/documents/embed` endpoint.

---

## Step 5: Semantic Search

Now for the magic! Search documents by meaning, not just keywords.

### Using the REST API

The REST API handles embedding generation automatically:

```bash
curl -X POST "http://localhost:8000/api/documents/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How does FraiseQL improve GraphQL performance?",
    "limit": 5
  }'
```

Expected response:

```json
{
  "query": "How does FraiseQL improve GraphQL performance?",
  "results": [
    {
      "id": "123e4567-e89b-12d3-a456-426614174000",
      "title": "FraiseQL Performance Benefits",
      "content": "FraiseQL delivers 10-100x performance improvements...",
      "similarity": 0.92,
      "source": "documentation"
    }
  ]
}
```

### Understanding Similarity Scores

- **0.9 - 1.0**: Very similar (exact meaning match)
- **0.7 - 0.9**: Similar (related concepts)
- **0.5 - 0.7**: Somewhat related (loose connection)
- **0.0 - 0.5**: Not similar (different topics)

---

## Step 6: RAG Question Answering

The ultimate RAG feature: answer questions using retrieved context.

### How RAG Works

1. **Question**: User asks a question
2. **Retrieval**: Find relevant documents via semantic search
3. **Context**: Combine retrieved documents as context
4. **Generation**: Use LLM to answer with context

### Using the RAG Endpoint

```bash
curl -X POST "http://localhost:8000/api/rag/ask" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How does FraiseQL achieve better performance than traditional GraphQL frameworks?",
    "context_limit": 3
  }'
```

Expected response:

```json
{
  "question": "How does FraiseQL achieve better performance than traditional GraphQL frameworks?",
  "answer": "Based on the provided documentation, FraiseQL achieves superior performance through several key innovations:\n\n1. **Rust Pipeline**: FraiseQL uses a Rust pipeline that transforms PostgreSQL JSONB directly to HTTP responses, eliminating Python serialization overhead entirely.\n\n2. **Direct JSONB Passthrough**: Traditional frameworks follow: PostgreSQL → Rows → ORM → Python objects → GraphQL serialize → JSON. FraiseQL follows: PostgreSQL → JSONB → Rust field selection → HTTP Response.\n\n3. **10-100x Performance Improvement**: By bypassing Python object serialization and using Rust for field selection, FraiseQL delivers 10-100x faster query performance.\n\n4. **PostgreSQL-Native Features**: Built-in caching, error tracking, and monitoring within PostgreSQL eliminate external service dependencies and network overhead.",
  "sources": [
    {
      "id": "doc-1",
      "title": "FraiseQL Performance Benefits",
      "similarity": 0.95
    }
  ]
}
```

### Python Client for RAG

```python
import asyncio
from app import RAGService

async def rag_demo():
    # Initialize RAG service
    rag = RAGService(
        database_url="postgresql://localhost:5432/ragdb",
        openai_api_key="your-api-key"
    )

    # Ask a question
    response = await rag.answer_question(
        "What makes FraiseQL different from other GraphQL frameworks?"
    )

    print(f"Question: {response['question']}")
    print(f"Answer: {response['answer']}")
    print(f"Sources used: {len(response['sources'])}")

    for source in response['sources']:
        print(f"  - {source['title']} (similarity: {source['similarity']:.3f})")

asyncio.run(rag_demo())
```

---

## Step 7: Advanced Features

### Filtering with Metadata

List the documents from one source with GraphQL:

```graphql
query DocumentationSources {
  documents(source: "documentation", limit: 10) {
    id
    title
    metadata
  }
}
```

### Hybrid Search (Semantic + Keyword)

```python
async def hybrid_search(query: str, category: str = None):
    """Combine semantic and keyword search"""
    rag = RAGService(database_url, api_key)

    # Semantic search
    semantic_results = await rag.semantic_search(query)

    # Filter by category if specified
    if category:
        semantic_results = [
            r for r in semantic_results
            if r.get('metadata', {}).get('category') == category
        ]

    return semantic_results
```

### Batch Document Processing

```python
async def batch_import_documents(file_path: str):
    """Import multiple documents from a file"""
    import json

    rag = RAGService(database_url, api_key)

    with open(file_path, 'r') as f:
        documents = json.load(f)

    for doc in documents:
        await rag.add_document_with_embedding(
            title=doc['title'],
            content=doc['content'],
            source=doc.get('source', 'import'),
            metadata=doc.get('metadata', {})
        )

    print(f"Imported {len(documents)} documents")
```

---

## Step 8: Performance Optimization

### Database Indexes

Ensure you have the right indexes for performance:

```sql
-- Check existing indexes
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename IN ('tb_document', 'tv_document_embedding');

-- Essential indexes for performance
CREATE INDEX IF NOT EXISTS idx_tb_document_created_at
ON tb_document (created_at);

CREATE INDEX IF NOT EXISTS idx_tv_document_embedding_hnsw
ON tv_document_embedding USING hnsw (embedding vector_cosine_ops);
```

### Query Performance Analysis

```sql
-- Analyze query performance
EXPLAIN (ANALYZE, BUFFERS)
SELECT d.title, (1 - (e.embedding <=> query_embedding)) as similarity
FROM tb_document d
JOIN tv_document_embedding e ON d.id = e.document_id
WHERE (1 - (e.embedding <=> query_embedding)) > 0.7
ORDER BY (e.embedding <=> query_embedding)
LIMIT 10;
```

### Caching Strategies

```python
# Cache frequent embeddings
from functools import lru_cache

@lru_cache(maxsize=1000)
def get_cached_embedding(text: str):
    """Cache embeddings to avoid recomputation"""
    return embeddings.embed_query(text)

# Cache search results
import redis
redis_client = redis.Redis(host='localhost', port=6379, db=0)

async def cached_search(query: str):
    cache_key = f"search:{hash(query)}"
    cached = redis_client.get(cache_key)

    if cached:
        return json.loads(cached)

    results = await rag.semantic_search(query)
    redis_client.setex(cache_key, 3600, json.dumps(results))
    return results
```

---

## Step 9: Testing Your RAG System

### Unit Tests

```python
import pytest
from app import RAGService

@pytest.mark.asyncio
async def test_document_creation():
    rag = RAGService(test_db_url, test_api_key)

    doc_id = await rag.add_document_with_embedding(
        title="Test Document",
        content="This is a test document for unit testing."
    )

    assert doc_id is not None
    assert isinstance(doc_id, str)

@pytest.mark.asyncio
async def test_semantic_search():
    rag = RAGService(test_db_url, test_api_key)

    results = await rag.semantic_search("test document", limit=5)

    assert isinstance(results, list)
    assert len(results) >= 0
    if results:
        assert 'similarity' in results[0]
        assert 'title' in results[0]

@pytest.mark.asyncio
async def test_rag_question_answering():
    rag = RAGService(test_db_url, test_api_key)

    response = await rag.answer_question("What is this test about?")

    assert 'question' in response
    assert 'answer' in response
    assert 'sources' in response
```

### Integration Tests

```bash
# Test GraphQL endpoint
curl -X POST "http://localhost:8000/graphql" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "{ documents(limit: 5) { id title } }"
  }'

# Test semantic search
curl -X POST "http://localhost:8000/api/documents/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "limit": 3}'

# Test RAG endpoint
curl -X POST "http://localhost:8000/api/rag/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "What can I do with this system?"}'
```

---

## Step 10: Production Deployment

### Environment Configuration

```bash
# Production environment variables
export DATABASE_URL="postgresql://user:password@prod-host:5432/ragdb"
export OPENAI_API_KEY="prod-api-key"
export SIMILARITY_THRESHOLD="0.7"
export MAX_CONTEXT_DOCUMENTS="5"
export EMBEDDING_MODEL="text-embedding-ada-002"
```

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash app
USER app

EXPOSE 8000

CMD ["python", "app.py"]
```

### Docker Compose

```yaml
version: '3.8'

services:
  postgres:
    image: pgvector/pgvector:pg15
    environment:
      POSTGRES_DB: ragdb
      POSTGRES_USER: raguser
      POSTGRES_PASSWORD: ragpass
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./schema.sql:/docker-entrypoint-initdb.d/01-schema.sql
    ports:
      - "5432:5432"

  rag-app:
    build: .
    environment:
      DATABASE_URL: postgresql://raguser:ragpass@postgres:5432/ragdb
      OPENAI_API_KEY: ${OPENAI_API_KEY}
    ports:
      - "8000:8000"
    depends_on:
      - postgres

volumes:
  postgres_data:
```

### Monitoring and Observability

```python
# Add monitoring to your application
from prometheus_client import Counter, Histogram, generate_latest

# Metrics
search_counter = Counter('rag_searches_total', 'Total semantic searches')
search_duration = Histogram('rag_search_duration_seconds', 'Search duration')
qa_counter = Counter('rag_questions_total', 'Total RAG questions')

# Use in your endpoints
@app.post("/api/documents/search")
async def search_endpoint(search_query: SearchQuery):
    search_counter.inc()

    with search_duration.time():
        results = await rag_service.semantic_search(
            search_query.query,
            limit=search_query.limit
        )

    return {"query": search_query.query, "results": results}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")
```

---

## Troubleshooting

### Common Issues

#### 1. pgvector Extension Not Found

```bash
# Error: "extension 'vector' does not exist"
psql ragdb -c "CREATE EXTENSION vector;"
```

#### 2. OpenAI API Key Issues

```bash
# Check your API key
curl -H "Authorization: Bearer $OPENAI_API_KEY" \
  https://api.openai.com/v1/models

# Make sure it's set in your environment
echo $OPENAI_API_KEY
```

#### 3. Embedding Dimension Mismatch

```sql
-- Check your embedding dimensions
SELECT
  embedding_model,
  COUNT(*) as count,
  ARRAY_LENGTH(embedding, 1) as dimensions
FROM tv_document_embedding
GROUP BY embedding_model;
```

#### 4. Performance Issues

```sql
-- Check if HNSW index is being used
EXPLAIN (ANALYZE)
SELECT * FROM tv_document_embedding
WHERE embedding <=> query_embedding < 0.3
ORDER BY embedding <=> query_embedding
LIMIT 10;
```

### Debug Mode

Enable debug logging:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Add logging to your functions
async def semantic_search(query: str, limit: int = 5):
    logger.debug(f"Semantic search query: {query}")

    # ... your code

    logger.debug(f"Found {len(results)} results")
    return results
```

---

## Next Steps

Congratulations! You've built a complete RAG system with FraiseQL. Here's what to explore next:

### 📚 Advanced Topics

- **[Vector Operators Reference](../features/pgvector.md)** - All pgvector operators and use cases
- **[Embedding Strategies](../guides/langchain-integration.md)** - Different embedding models and techniques
- **[Performance Guide](../performance/index.md)** - Optimize your RAG system for production

### 🚀 Production Features

- **Authentication**: Add JWT-based authentication with automatic session variable injection
- **Rate Limiting**: Implement API rate limiting using PostgreSQL-native caching
- **Monitoring**: Set up comprehensive monitoring using FraiseQL's built-in error tracking
- **Scaling**: Horizontal scaling with connection pooling and Rust pipeline optimization

### 🔧 Extensions

- **Document Processing**: Support for PDF, Word, and other formats
- **Multiple Embedding Models**: Support for local and alternative models
- **Real-time Updates**: WebSocket subscriptions for live updates
- **Multi-tenancy**: Isolate data by tenant or organization

### 🎯 Use Cases

- **Knowledge Base**: Build a company knowledge base
- **Customer Support**: Create intelligent FAQ systems
- **Research Assistant**: Build research tools for academics
- **Content Discovery**: Implement content recommendation systems

---

## 🎉 Summary

You've successfully:

✅ **Set up** a PostgreSQL database with pgvector
✅ **Created** a Trinity Pattern schema for documents and embeddings
✅ **Built** a GraphQL API with FraiseQL
✅ **Implemented** semantic search with vector similarity
✅ **Developed** RAG question answering with an OpenAI-compatible chat model
✅ **Optimized** performance with proper indexing
✅ **Deployed** a production-ready RAG system

Your RAG system is now ready for production use! You can:

- Add documents through the REST API and read them with GraphQL
- Perform semantic search to find relevant content
- Answer questions using retrieved context
- Scale to thousands of documents with proper indexing

Happy building! 🚀

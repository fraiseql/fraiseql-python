# RAG System Example

A complete Retrieval-Augmented Generation (RAG) system built with FraiseQL, LangChain, and PostgreSQL pgvector. This example demonstrates how to build production-ready RAG applications with semantic search, document management, and question-answering capabilities.

## 🏗️ Architecture

This example follows the **Trinity Pattern** for database design:

- **`tb_document`** - Command table for document storage
- **`v_document`** - Read view for document access
- **`tv_document_embedding`** - Table view with vector embeddings for semantic search

## 🚀 Features

- **Document Management**: Create, store, and manage documents with metadata
- **Vector Embeddings**: Automatic embedding generation using OpenAI or local models
- **Semantic Search**: Find similar documents using cosine similarity
- **RAG Question Answering**: Answer questions using retrieved context
- **GraphQL API**: Full GraphQL schema for all operations
- **REST Endpoints**: Additional REST endpoints for RAG-specific operations
- **Performance Optimized**: HNSW indexes for fast vector search

## 📋 Prerequisites

- PostgreSQL 14+ with pgvector extension
- Python 3.8+
- OpenAI API key (or local embedding model)

## 🛠️ Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Database Setup

```bash
# Create database
createdb ragdb

# Enable pgvector extension
psql ragdb -c "CREATE EXTENSION vector;"

# Load schema
psql ragdb < schema.sql
```

### 3. Environment Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit with your configuration
nano .env
```

Required environment variables:

```bash
DATABASE_URL=postgresql://localhost:5432/ragdb
OPENAI_API_KEY=your_openai_api_key_here
```

### 4. Run the Application

```bash
python app.py
```

The application will be available at:

- **GraphQL Playground**: http://localhost:8000/graphql
- **REST API**: http://localhost:8000/api

## 📚 Usage Examples

### GraphQL Operations

#### Create Document

```graphql
mutation CreateDocument {
  createDocument(
    title: "Introduction to RAG"
    content: "Retrieval-Augmented Generation combines vector search with language models..."
    source: "documentation"
    metadata: {category: "ai-ml", difficulty: "intermediate"}
  ) {
    id
    title
    createdAt
  }
}
```

#### List Documents

```graphql
query GetDocuments {
  documents(limit: 10) {
    id
    title
    source
    metadata
    createdAt
  }
}
```

#### Semantic Search

```graphql
query SearchDocuments {
  searchDocuments(
    queryEmbedding: [0.1, 0.2, 0.3, ...],  # Your query embedding
    limit: 5,
    similarityThreshold: 0.7
  ) {
    id
    title
    content
    similarity
  }
}
```

### REST API Operations

#### Semantic Search

```bash
curl -X POST "http://localhost:8000/api/documents/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How does RAG work?",
    "limit": 5
  }'
```

#### RAG Question Answering

```bash
curl -X POST "http://localhost:8000/api/rag/ask" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are the benefits of using RAG systems?",
    "context_limit": 3
  }'
```

#### Create Document with Embedding

```bash
curl -X POST "http://localhost:8000/api/documents/embed" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Vector Databases",
    "content": "Vector databases store high-dimensional vectors for similarity search...",
    "source": "blog",
    "metadata": {"category": "database", "author": "AI Engineer"}
  }'
```

## 🔧 Python Client Usage

```python
import asyncio
from app import RAGService

async def main():
    # Initialize RAG service
    rag = RAGService(
        database_url="postgresql://localhost:5432/ragdb",
        openai_api_key="your-api-key"
    )

    # Add document with embedding
    doc_id = await rag.add_document_with_embedding(
        title="FraiseQL Guide",
        content="FraiseQL automatically generates GraphQL APIs from PostgreSQL...",
        source="docs"
    )
    print(f"Created document: {doc_id}")

    # Semantic search
    results = await rag.semantic_search("GraphQL generation", limit=3)
    for doc in results:
        print(f"{doc['title']}: {doc['similarity']:.3f}")

    # RAG question answering
    answer = await rag.answer_question("How does FraiseQL work?")
    print(f"Answer: {answer['answer']}")
    print(f"Sources: {[s['title'] for s in answer['sources']]}")

asyncio.run(main())
```

## 🎯 Key Concepts

### Trinity Pattern

The database schema follows the Trinity Pattern:

1. **`tb_document`** - Transaction table for writes (commands)
2. **`v_document`** - View for reads (queries)
3. **`tv_document_embedding`** - Table view with computed columns (vectors)

This pattern provides:

- Clear separation of concerns
- Optimized read/write performance
- Consistent naming conventions

### Vector Similarity Search

The system uses cosine similarity for semantic search:

```sql
-- Similarity calculation (0 = identical, 2 = opposite)
similarity = 1 - (embedding <=> query_embedding)

-- HNSW index for fast approximate search
CREATE INDEX ON tv_document_embedding
USING hnsw (embedding vector_cosine_ops);
```

### RAG Pipeline

1. **Document Processing**: Chunk and embed documents
2. **Vector Storage**: Store embeddings in PostgreSQL
3. **Retrieval**: Find relevant documents via similarity search
4. **Generation**: Use retrieved context in LLM prompts

## 📊 Performance Considerations

### Vector Search Optimization

- **HNSW Indexes**: Use for production workloads
- **Dimensionality**: Match embedding model dimensions (1536 for ada-002)
- **Similarity Threshold**: Filter out low-similarity results
- **Batch Operations**: Process multiple documents efficiently

### Database Indexes

```sql
-- Essential indexes for performance
CREATE INDEX ON tb_document (created_at);
CREATE INDEX ON tb_document (source);
CREATE INDEX ON tv_document_embedding (document_id);
CREATE INDEX ON tv_document_embedding USING hnsw (embedding vector_cosine_ops);
```

## 🔍 Monitoring

### Query Performance

```sql
-- Check index usage
EXPLAIN (ANALYZE, BUFFERS)
SELECT d.title, (1 - (e.embedding <=> query_embedding)) as similarity
FROM tb_document d
JOIN tv_document_embedding e ON d.id = e.document_id
ORDER BY (e.embedding <=> query_embedding)
LIMIT 10;
```

### Vector Statistics

```sql
-- Embedding statistics
SELECT
  COUNT(*) as total_documents,
  COUNT(DISTINCT embedding_model) as models_used,
  AVG(ARRAY_LENGTH(embedding, 1)) as avg_dimensions
FROM tv_document_embedding;
```

## 🧪 Testing

```bash
# Test database connection
python -c "from app import app; print('✅ App loads successfully')"

# Test GraphQL schema
curl http://localhost:8000/graphql -H "Content-Type: application/json" -d '{"query":"{ __schema { types { name } } }"}'

# Test semantic search
curl -X POST "http://localhost:8000/api/documents/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "test query", "limit": 3}'
```

## 🚀 Production Deployment

### Environment Variables

```bash
# Production settings
DATABASE_URL=postgresql://user:pass@host:5432/ragdb
OPENAI_API_KEY=prod-api-key
EMBEDDING_MODEL=text-embedding-ada-002
SIMILARITY_THRESHOLD=0.7
MAX_CONTEXT_DOCUMENTS=5
```

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8000

CMD ["python", "app.py"]
```

### Scaling Considerations

- **Connection Pooling**: Use PgBouncer for database connections
- **Caching**: Cache frequent queries and embeddings
- **Batch Processing**: Process documents in batches
- **Monitoring**: Track query performance and vector index health

## 🔗 Related Examples

- **Vector Search**: `/examples/vector_search` - Advanced vector operations
- **Blog API**: `/examples/blog_api` - GraphQL patterns

## 📖 Further Reading

- [FraiseQL Documentation](https://fraiseql.com/docs)
- [pgvector Documentation](https://github.com/pgvector/pgvector)
- [LangChain RAG Guide](https://python.langchain.com/docs/use_cases/question_answering)
- [Trinity Pattern Guide](../../docs/core/trinity-pattern.md)

## 🤝 Contributing

Contributions welcome! Please read the contributing guidelines and submit pull requests.

## 📄 License

MIT License - see LICENSE file for details.

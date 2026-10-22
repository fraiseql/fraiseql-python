# Docker Setup for RAG System

This directory contains Docker configuration for running and testing the RAG system example.

## Quick Start

### Prerequisites

- Docker and Docker Compose installed
- OpenAI API key (for embedding generation and LLM)

### Run the Test Suite

```bash
# Set your OpenAI API key
export OPENAI_API_KEY="your-openai-api-key"

# Run end-to-end tests
./test-rag-system.sh
```

The test script will:

1. Build Docker images
2. Start PostgreSQL with pgvector and the RAG application
3. Run comprehensive tests:
   - GraphQL schema introspection
   - Document queries
   - Document creation (GraphQL)
   - Document creation with embeddings (REST)
   - Semantic search
   - RAG question answering
   - Database verification

### Manual Testing

If you want to run the services manually without the test script:

```bash
# Set your OpenAI API key
export OPENAI_API_KEY="your-openai-api-key"

# Start services
docker-compose up -d

# Watch logs
docker-compose logs -f

# Stop services
docker-compose down

# Stop and remove data
docker-compose down -v
```

## Services

### PostgreSQL (pgvector)

- **Image**: `pgvector/pgvector:pg16`
- **Port**: 5432
- **Database**: ragdb
- **User**: raguser
- **Password**: ragpass
- **Features**:
  - pgvector extension enabled
  - Sample documents loaded from schema.sql

### RAG Application

- **Build**: From local Dockerfile
- **Port**: 8001 on the host (8000 in the container, leaving 8000 to a local vLLM)
- **Endpoints**:
  - GraphQL Playground: http://localhost:8001/graphql
  - Health Check: http://localhost:8001/health
  - Model status: http://localhost:8001/api/rag/status
  - REST API: http://localhost:8001/api/...

## Testing Without OpenAI API Key

The application will start without an OpenAI API key, but embedding-related features will be disabled:

```bash
# Start without OpenAI
unset OPENAI_API_KEY
docker-compose up -d

# GraphQL operations still work
curl http://localhost:8001/graphql -H "Content-Type: application/json" \
  -d '{"query":"{ documents(limit: 5) { id title } }"}'
```

## Troubleshooting

### Services won't start

```bash
# Check logs
docker-compose logs postgres
docker-compose logs rag-app

# Verify PostgreSQL is ready
docker-compose exec postgres pg_isready -U raguser -d ragdb

# Restart services
docker-compose restart
```

### "Connection refused" errors

Wait for services to be fully healthy:

```bash
# Check service health
docker-compose ps

# Wait for health checks to pass
watch docker-compose ps
```

### Embedding generation fails

Verify OpenAI API key is set:

```bash
# Check which models are available
curl http://localhost:8001/api/rag/status

# Should show:
# {
#   "status": "healthy",
#   "embeddings": "available",
#   "llm": "available"
# }
```

### Reset everything

```bash
# Stop and remove all containers and volumes
docker-compose down -v

# Remove images
docker-compose down --rmi all -v

# Rebuild from scratch
docker-compose build --no-cache
docker-compose up -d
```

## Database Access

Connect to PostgreSQL directly:

```bash
# Using docker-compose
docker-compose exec postgres psql -U raguser -d ragdb

# Check documents
SELECT COUNT(*) FROM tb_document;

# Check embeddings
SELECT COUNT(*) FROM tv_document_embedding;

# View sample documents
SELECT id, title, source FROM tb_document LIMIT 5;
```

## Development

### Rebuild after code changes

```bash
# Rebuild and restart
docker-compose up -d --build

# Or rebuild specific service
docker-compose build rag-app
docker-compose up -d rag-app
```

### Mount local code for development

Add to `docker-compose.yml` under `rag-app`:

```yaml
volumes:
  - ./app.py:/app/app.py:ro
```

This allows editing code without rebuilding (restart required).

## Performance

### Check database performance

```bash
docker-compose exec postgres psql -U raguser -d ragdb -c "
  EXPLAIN ANALYZE
  SELECT d.title, (1 - (e.embedding <=> '[0.1,0.2,...]'::vector)) as similarity
  FROM tb_document d
  JOIN tv_document_embedding e ON d.id = e.document_id
  ORDER BY (e.embedding <=> '[0.1,0.2,...]'::vector)
  LIMIT 10;
"
```

### Monitor resource usage

```bash
# Container stats
docker stats

# Logs with timestamps
docker-compose logs -f --timestamps
```

## Architecture

```
┌─────────────────────────────────────────────┐
│  Host Machine                                │
│  ┌─────────────────────────────────────┐   │
│  │ Docker Network                       │   │
│  │                                      │   │
│  │  ┌──────────────┐   ┌────────────┐ │   │
│  │  │ PostgreSQL   │   │ RAG App    │ │   │
│  │  │ + pgvector   │◄──┤ FastAPI    │ │   │
│  │  │              │   │ FraiseQL   │ │   │
│  │  │ Port: 5432   │   │ LangChain  │ │   │
│  │  └──────────────┘   │            │ │   │
│  │         │            │ Port: 8000 │ │   │
│  │         │            └────────────┘ │   │
│  │         │                    │       │   │
│  │         └────────────────────┘       │   │
│  │         Persistent Volume            │   │
│  └─────────────────────────────────────┘   │
│                  │                          │
│                  ▼                          │
│          OpenAI API (external)              │
└─────────────────────────────────────────────┘
```

## Files

- `Dockerfile` - Application container definition
- `docker-compose.yml` - Multi-container orchestration
- `.dockerignore` - Files excluded from Docker build
- `test-rag-system.sh` - Automated end-to-end test script
- `DOCKER.md` - This file

## Notes

- The PostgreSQL data is persisted in a Docker volume (`postgres_data`)
- Sample documents are automatically loaded on first startup
- The application runs as a non-root user (`app`)
- Health checks ensure services are ready before tests run
- All tests can run without manual intervention

## Next Steps

After verifying the Docker setup works:

1. Review test results
2. Try manual queries in GraphQL playground
3. Test REST endpoints with curl
4. Experiment with semantic search
5. Deploy to production with proper secrets management

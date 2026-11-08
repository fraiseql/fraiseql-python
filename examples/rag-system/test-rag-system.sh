#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Detect docker-compose command (support both old and new syntax)
if command -v docker-compose &> /dev/null; then
    DC="docker-compose"
elif command -v docker &> /dev/null && docker compose version &> /dev/null; then
    DC="docker compose"
else
    echo -e "${RED}ERROR: Neither 'docker-compose' nor 'docker compose' is available${NC}"
    exit 1
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}RAG System End-to-End Test${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Check embedding configuration
if [ -z "$OPENAI_API_KEY" ] && [ "${USE_LOCAL_EMBEDDINGS}" != "true" ]; then
    echo -e "${YELLOW}⚠ Neither OPENAI_API_KEY nor USE_LOCAL_EMBEDDINGS is set${NC}"
    echo -e "${BLUE}ℹ Using local embeddings by default...${NC}"
    export USE_LOCAL_EMBEDDINGS="true"
fi

if [ -n "$OPENAI_API_KEY" ]; then
    echo -e "${GREEN}✓ OPENAI_API_KEY is set (using OpenAI embeddings)${NC}\n"
elif [ "${USE_LOCAL_EMBEDDINGS}" = "true" ]; then
    echo -e "${GREEN}✓ USE_LOCAL_EMBEDDINGS is set (using local sentence-transformers)${NC}\n"
fi

# Build and start services
echo -e "${BLUE}Step 1: Building Docker images...${NC}"
$DC build
echo -e "${GREEN}✓ Docker images built${NC}\n"

echo -e "${BLUE}Step 2: Starting services...${NC}"
$DC up -d
echo -e "${GREEN}✓ Services started${NC}\n"

# Wait for services to be healthy
echo -e "${BLUE}Step 3: Waiting for services to be healthy...${NC}"
sleep 5

# Check PostgreSQL
echo -n "  Checking PostgreSQL... "
for i in {1..30}; do
    if $DC exec -T postgres pg_isready -U raguser -d ragdb >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}✗ PostgreSQL failed to start${NC}"
        $DC logs postgres
        exit 1
    fi
    sleep 1
done

# Wait for app to be ready
echo -n "  Checking RAG app... "
for i in {1..60}; do
    if curl -s http://localhost:8001/health >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        break
    fi
    if [ $i -eq 60 ]; then
        echo -e "${RED}✗ RAG app failed to start${NC}"
        $DC logs rag-app
        exit 1
    fi
    sleep 1
done

echo ""

# Test 1: GraphQL Schema
echo -e "${BLUE}Test 1: GraphQL Schema Introspection${NC}"
SCHEMA_RESPONSE=$(curl -s http://localhost:8001/graphql \
  -H "Content-Type: application/json" \
  -d '{"query":"{ __schema { queryType { fields { name } } } }"}')

if echo "$SCHEMA_RESPONSE" | grep -q '"documents"'; then
    echo -e "${GREEN}✓ GraphQL schema loads correctly${NC}"
else
    echo -e "${RED}✗ GraphQL schema failed${NC}"
    echo "$SCHEMA_RESPONSE"
    exit 1
fi
echo ""

# Test 2: Query existing documents (from schema.sql seed data)
echo -e "${BLUE}Test 2: Query Existing Documents${NC}"
DOCS_RESPONSE=$(curl -s http://localhost:8001/graphql \
  -H "Content-Type: application/json" \
  -d '{"query":"{ documents(limit: 5) { id title source } }"}')

if echo "$DOCS_RESPONSE" | grep -q "FraiseQL"; then
    echo -e "${GREEN}✓ Documents query works (found sample data)${NC}"
    DOC_COUNT=$(echo "$DOCS_RESPONSE" | grep -o '"title"' | wc -l)
    echo -e "  Found ${GREEN}${DOC_COUNT}${NC} documents"
else
    echo -e "${RED}✗ Documents query failed${NC}"
    echo "$DOCS_RESPONSE"
    exit 1
fi
echo ""

# Test 3: Model availability
echo -e "${BLUE}Test 3: Model Status${NC}"
STATUS_RESPONSE=$(curl -s http://localhost:8001/api/rag/status)
echo -e "  ${GREEN}${STATUS_RESPONSE}${NC}"
echo ""

# Test 4: Create document with embedding via REST API
echo -e "${BLUE}Test 4: Create Document with Embedding (REST)${NC}"
EMBED_RESPONSE=$(curl -s -X POST "http://localhost:8001/api/documents/embed" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Docker Test Document",
    "content": "This document tests embedding generation with OpenAI in Docker.",
    "source": "docker-test",
    "metadata": {"test": true, "environment": "docker"}
  }')

if echo "$EMBED_RESPONSE" | grep -q "id"; then
    echo -e "${GREEN}✓ Document with embedding created${NC}"
    EMBED_DOC_ID=$(echo "$EMBED_RESPONSE" | grep -o '"id":"[^"]*"' | cut -d'"' -f4)
    echo -e "  Document ID: ${GREEN}${EMBED_DOC_ID}${NC}"
else
    echo -e "${RED}✗ Embedding creation failed${NC}"
    echo "$EMBED_RESPONSE"
    exit 1
fi
echo ""

# Test 5: Semantic search via REST API
echo -e "${BLUE}Test 5: Semantic Search${NC}"
SEARCH_RESPONSE=$(curl -s -X POST "http://localhost:8001/api/documents/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is FraiseQL and how does it work?",
    "limit": 3
  }')

if echo "$SEARCH_RESPONSE" | grep -q "similarity"; then
    echo -e "${GREEN}✓ Semantic search works${NC}"
    RESULT_COUNT=$(echo "$SEARCH_RESPONSE" | grep -o '"similarity"' | wc -l)
    echo -e "  Found ${GREEN}${RESULT_COUNT}${NC} results"

    # Show top result
    TOP_TITLE=$(echo "$SEARCH_RESPONSE" | grep -o '"title":"[^"]*"' | head -1 | cut -d'"' -f4)
    TOP_SIMILARITY=$(echo "$SEARCH_RESPONSE" | grep -o '"similarity":[0-9.]*' | head -1 | cut -d':' -f2)
    echo -e "  Top result: ${GREEN}${TOP_TITLE}${NC} (similarity: ${TOP_SIMILARITY})"
else
    echo -e "${RED}✗ Semantic search failed${NC}"
    echo "$SEARCH_RESPONSE"
    exit 1
fi
echo ""

# Test 6: RAG question answering
echo -e "${BLUE}Test 6: RAG Question Answering${NC}"
RAG_RESPONSE=$(curl -s -X POST "http://localhost:8001/api/rag/ask" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How does FraiseQL achieve better performance?",
    "context_limit": 3
  }')

if echo "$RAG_RESPONSE" | grep -q "answer"; then
    echo -e "${GREEN}✓ RAG question answering works${NC}"
    ANSWER=$(echo "$RAG_RESPONSE" | grep -o '"answer":"[^"]*"' | cut -d'"' -f4 | head -c 100)
    SOURCES=$(echo "$RAG_RESPONSE" | grep -o '"title"' | wc -l)
    echo -e "  Answer (first 100 chars): ${GREEN}${ANSWER}...${NC}"
    echo -e "  Sources used: ${GREEN}${SOURCES}${NC}"
else
    echo -e "${RED}✗ RAG question answering failed${NC}"
    echo "$RAG_RESPONSE"
    exit 1
fi
echo ""

# Test 7: Database verification
echo -e "${BLUE}Test 7: Database Verification${NC}"
echo -n "  Checking document count... "
DOC_COUNT=$($DC exec -T postgres psql -U raguser -d ragdb -t -c "SELECT COUNT(*) FROM tb_document;" | tr -d '[:space:]')
echo -e "${GREEN}${DOC_COUNT} documents${NC}"

echo -n "  Checking embedding count... "
EMB_COUNT=$($DC exec -T postgres psql -U raguser -d ragdb -t -c "SELECT COUNT(*) FROM tv_document_embedding;" | tr -d '[:space:]')
echo -e "${GREEN}${EMB_COUNT} embeddings${NC}"

if [ "$EMB_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ Database has embeddings${NC}"
else
    echo -e "${YELLOW}⚠ No embeddings found (may not have OPENAI_API_KEY)${NC}"
fi
echo ""

# Summary
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}All Tests Passed! ✓${NC}"
echo -e "${BLUE}========================================${NC}\n"

echo -e "${YELLOW}Services are still running. You can:${NC}"
echo -e "  • Visit GraphQL playground: ${BLUE}http://localhost:8001/graphql${NC}"
echo -e "  • View logs: ${BLUE}${DC} logs -f${NC}"
echo -e "  • Stop services: ${BLUE}${DC} down${NC}"
echo -e "  • Stop and remove data: ${BLUE}${DC} down -v${NC}\n"

# Optional: Keep container running for manual inspection
read -p "Do you want to stop the containers now? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "\n${BLUE}Stopping services...${NC}"
    $DC down
    echo -e "${GREEN}✓ Services stopped${NC}"
else
    echo -e "\n${GREEN}Services are still running.${NC}"
    echo -e "Run ${BLUE}${DC} down${NC} when you're done.\n"
fi

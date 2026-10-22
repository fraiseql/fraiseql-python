"""RAG System Example - Retrieval-Augmented Generation with FraiseQL and pgvector.

GraphQL (fraiseql) serves the documents. REST endpoints add documents with their
embedding, search them semantically, and answer questions from them with an
OpenAI-compatible chat model (OpenAI, or a local vLLM server).
"""

import asyncio
import inspect
import os
from datetime import datetime

import psycopg
import uvicorn
from fastapi import HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel

import fraiseql
from fraiseql.db import register_type_for_view
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.types import ID, JSON

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/ragdb")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002")


# ============================================================================
# GRAPHQL
# ============================================================================


@fraiseql.type(sql_source="v_document", jsonb_column=None)
class Document:
    """A document of the knowledge base."""

    id: ID
    title: str
    content: str
    source: str | None
    metadata: JSON
    created_at: datetime
    updated_at: datetime


# v_document has plain columns, no JSONB data column. column_mapping makes
# ordering use the created_at column too (filters already use table_columns).
register_type_for_view(
    "v_document",
    Document,
    table_columns={"id", "title", "content", "source", "metadata", "created_at", "updated_at"},
    has_jsonb_data=False,
    column_mapping={"created_at": "created_at"},
)


@fraiseql.query
async def documents(info, source: str | None = None, limit: int = 50) -> list[Document]:
    """List documents, newest first, optionally from one source."""
    db = info.context["db"]
    return await db.find(
        "v_document",
        "documents",
        info,
        where={"source": {"eq": source}} if source else None,
        order_by=[{"created_at": "desc"}],
        limit=limit,
    )


@fraiseql.query
async def document(info, id: ID) -> Document | None:
    """Get a document by ID."""
    db = info.context["db"]
    return await db.find_one("v_document", "document", info, mandatory_filters={"id": id})


# ============================================================================
# RAG SERVICE
# ============================================================================


class RAGService:
    """Embeds, searches and answers, with OpenAI or local models."""

    def __init__(
        self,
        database_url: str,
        openai_api_key: str | None = None,
        use_local_models: bool = False,
        local_model_url: str = "http://localhost:8000/v1",
        llm_model: str | None = None,
    ):
        self.database_url = database_url

        try:
            from local_embeddings import get_embedding_provider

            self.embeddings = get_embedding_provider(
                provider="local" if use_local_models else "auto",
                openai_api_key=openai_api_key,
            )
        except Exception as e:
            print(f"⚠️  No embedding provider: {e}")
            self.embeddings = None

        # Both OpenAI and vLLM speak the OpenAI chat API
        try:
            from openai import AsyncOpenAI
        except ImportError:
            print("⚠️  openai not installed: pip install openai")
            self.llm = None
        else:
            if use_local_models or not openai_api_key:
                self.llm = AsyncOpenAI(base_url=local_model_url, api_key="not-needed-for-local")
            else:
                self.llm = AsyncOpenAI(api_key=openai_api_key)
        self.llm_model = llm_model or ("local-model" if use_local_models else "gpt-4o-mini")

    async def embed(self, text: str) -> list[float]:
        """Embed a text with whichever provider is configured."""
        if self.embeddings is None:
            raise HTTPException(status_code=503, detail="Embeddings not available")
        if hasattr(self.embeddings, "aembed_query"):
            return await self.embeddings.aembed_query(text)
        if inspect.iscoroutinefunction(self.embeddings.embed_query):
            return await self.embeddings.embed_query(text)
        return await asyncio.to_thread(self.embeddings.embed_query, text)

    async def semantic_search(
        self, query: str, limit: int = 5, similarity_threshold: float = 0.7
    ) -> list[dict]:
        """Find the documents closest to query with search_documents_by_embedding."""
        embedding = await self.embed(query)
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            cur = await conn.execute(
                "SELECT id, title, content, source, metadata, similarity"
                " FROM search_documents_by_embedding(%s::vector, %s::integer, %s::real)",
                (embedding, limit, similarity_threshold),
            )
            columns = [c.name for c in cur.description]
            return [dict(zip(columns, row, strict=True)) for row in await cur.fetchall()]

    async def add_document_with_embedding(
        self, title: str, content: str, source: str | None = None, metadata: dict | None = None
    ) -> str:
        """Store a document and its embedding with create_document_with_embedding."""
        embedding = await self.embed(content)
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            cur = await conn.execute(
                "SELECT create_document_with_embedding(%s, %s, %s, %s, %s::vector, %s)",
                (title, content, source, Jsonb(metadata or {}), embedding, EMBEDDING_MODEL),
            )
            (doc_id,) = await cur.fetchone()
            return str(doc_id)

    async def answer_question(
        self, question: str, context_limit: int = 3, similarity_threshold: float = 0.7
    ) -> dict:
        """Answer question from the closest documents."""
        if self.llm is None:
            raise HTTPException(status_code=503, detail="LLM not available")

        sources = await self.semantic_search(
            question, limit=context_limit, similarity_threshold=similarity_threshold
        )
        context = "\n\n".join(f"Document: {doc['title']}\n{doc['content']}" for doc in sources)
        response = await self.llm.chat.completions.create(
            model=self.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": "Answer the question from the context only. "
                    "If the context doesn't say, answer that you don't know.",
                },
                {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
            ],
        )

        return {
            "question": question,
            "answer": response.choices[0].message.content,
            "sources": [
                {"id": str(doc["id"]), "title": doc["title"], "similarity": doc["similarity"]}
                for doc in sources
            ],
        }


_rag_service: RAGService | None = None


def rag_service() -> RAGService:
    """Build the RAG service on first use, from the environment."""
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService(
            database_url=DATABASE_URL,
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            use_local_models=os.getenv("USE_LOCAL_EMBEDDINGS", "false").lower()
            in ("true", "1", "yes"),
            local_model_url=os.getenv("LOCAL_MODEL_URL", "http://localhost:8000/v1"),
            llm_model=os.getenv("LLM_MODEL"),
        )
    return _rag_service


# ============================================================================
# APP
# ============================================================================

app = create_fraiseql_app(
    database_url=DATABASE_URL,
    types=[Document],
    queries=[documents, document],
    title="RAG System API",
)


class DocumentCreate(BaseModel):
    title: str
    content: str
    source: str | None = None
    metadata: dict = {}


class SearchQuery(BaseModel):
    query: str
    limit: int = 5
    similarity_threshold: float = 0.7


class RAGQuery(BaseModel):
    question: str
    context_limit: int = 3
    similarity_threshold: float = 0.7


@app.post("/api/documents/search")
async def search_endpoint(search_query: SearchQuery):
    """Search documents semantically."""
    results = await rag_service().semantic_search(
        search_query.query,
        limit=search_query.limit,
        similarity_threshold=search_query.similarity_threshold,
    )
    return {"query": search_query.query, "results": results}


@app.post("/api/rag/ask")
async def ask_endpoint(rag_query: RAGQuery):
    """Answer a question from the documents."""
    return await rag_service().answer_question(
        rag_query.question,
        context_limit=rag_query.context_limit,
        similarity_threshold=rag_query.similarity_threshold,
    )


@app.post("/api/documents/embed")
async def embed_document(doc: DocumentCreate):
    """Create a document with its embedding."""
    doc_id = await rag_service().add_document_with_embedding(
        doc.title, doc.content, source=doc.source, metadata=doc.metadata
    )
    return {"id": doc_id, "message": "Document created with embedding"}


# fraiseql serves /health itself (used by the Dockerfile); this reports the models
@app.get("/api/rag/status")
async def rag_status():
    """Report whether embeddings and the LLM are available."""
    service = rag_service()
    return {
        "status": "healthy",
        "embeddings": "available" if service.embeddings is not None else "unavailable",
        "llm": "available" if service.llm is not None else "unavailable",
    }


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))

    print("🚀 RAG System Example")
    print(f"\n📝 GraphQL endpoint: http://localhost:{port}/graphql")
    print("🔍 REST endpoints:")
    print("   • POST /api/documents/search - Semantic search")
    print("   • POST /api/rag/ask - RAG question answering")
    print("   • POST /api/documents/embed - Create with embedding")
    print("   • GET /api/rag/status - Embeddings and LLM availability")
    print("   • GET /health - Health check")
    print("\n⚙️  Environment variables:")
    print("   • DATABASE_URL - PostgreSQL connection")
    print("   • OPENAI_API_KEY - For OpenAI embeddings and answers")
    print("   • USE_LOCAL_EMBEDDINGS - 'true' for sentence-transformers and a local vLLM")
    print("   • LOCAL_MODEL_URL - vLLM server URL (default: http://localhost:8000/v1)")
    print("   • LLM_MODEL - chat model name (default: gpt-4o-mini, or local-model)")

    uvicorn.run(app, host="0.0.0.0", port=port)

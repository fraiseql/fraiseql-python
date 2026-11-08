# RAG System Example

Retrieval-augmented generation with FraiseQL and PostgreSQL pgvector: store
documents with their embeddings, find the ones closest to a question, and answer
from them with a chat model.

- **GraphQL** (fraiseql) serves the documents: `documents(source, limit)` and
  `document(id)`.
- **REST** endpoints do the model work: embed and store a document, search
  semantically, answer a question.
- Models: OpenAI, or local ones (sentence-transformers for embeddings, a vLLM
  server for answers). Both answer through the OpenAI chat API.

## Database

`schema.sql` follows the trinity pattern:

- `tb_document`: the documents (command side)
- `v_document`: the view fraiseql reads (query side)
- `tv_document_embedding`: one embedding per document, with an HNSW index
- `create_document_with_embedding`, `update_document_embedding` and
  `search_documents_by_embedding`: the SQL functions the REST endpoints call

The embedding column is `vector(1536)`, the size of OpenAI's
`text-embedding-ada-002`. With another model, change it to that model's size
(384 for the default local model, `all-MiniLM-L6-v2`) before loading the schema.

## Running it

```bash
createdb ragdb
psql ragdb -f schema.sql

pip install -r requirements.txt
export DATABASE_URL=postgresql://localhost:5432/ragdb
export OPENAI_API_KEY=...          # or USE_LOCAL_EMBEDDINGS=true, see local-models.md
python app.py
```

Or with Docker, see [docker.md](docker.md).

| Variable | Default | Use |
|---|---|---|
| `DATABASE_URL` | `postgresql://localhost:5432/ragdb` | PostgreSQL with pgvector |
| `OPENAI_API_KEY` | — | OpenAI embeddings and answers |
| `USE_LOCAL_EMBEDDINGS` | `false` | `true` for sentence-transformers and a local vLLM |
| `LOCAL_MODEL_URL` | `http://localhost:8000/v1` | the vLLM server |
| `LLM_MODEL` | `gpt-4o-mini`, or `local-model` | chat model name |
| `EMBEDDING_MODEL` | `text-embedding-ada-002` | recorded with each embedding |

## Using it

Add a document; the app embeds its content:

```bash
curl -X POST http://localhost:8000/api/documents/embed \
  -H "Content-Type: application/json" \
  -d '{"title": "Sourdough", "content": "Sourdough bread needs a starter and a long rise.",
       "source": "kitchen", "metadata": {"tags": ["bread"]}}'
```

Search by meaning (`similarity_threshold` defaults to 0.7):

```bash
curl -X POST http://localhost:8000/api/documents/search \
  -H "Content-Type: application/json" \
  -d '{"query": "How does FraiseQL improve performance?", "limit": 3}'
```

Ask a question; the answer comes with the documents it used:

```bash
curl -X POST http://localhost:8000/api/rag/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How does FraiseQL achieve better performance?", "context_limit": 3}'
```

Read documents with GraphQL at `http://localhost:8000/graphql`:

```graphql
{
  documents(source: "documentation", limit: 5) {
    id
    title
    metadata
    createdAt
  }
}
```

`GET /api/rag/status` says whether embeddings and the LLM are available;
`GET /health` is fraiseql's own health check.

## How the GraphQL side works

`v_document` has plain columns rather than a JSONB `data` column, so `Document`
is declared with `jsonb_column=None` and registered with
`register_type_for_view(..., table_columns=..., has_jsonb_data=False)`. The
`column_mapping` entry lets `order_by` use the `created_at` column as well.

## Files

- `app.py`: the GraphQL types and queries, the RAG service and the REST endpoints
- `local_embeddings.py`: embedding providers (OpenAI, sentence-transformers,
  OpenAI-compatible servers)
- `schema.sql`: tables, view, functions and sample documents
- `docker-compose.yml`, `Dockerfile`, [docker.md](docker.md): running with Docker
- [local-models.md](local-models.md): running without OpenAI
- `test-rag-system.sh`: an end-to-end check against the Docker setup

## Further reading

- [RAG tutorial](../../docs/ai-ml/rag-tutorial.md)
- [pgvector](https://github.com/pgvector/pgvector)

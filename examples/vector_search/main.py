"""Vector Search Example - the six pgvector distance operators.

Run schema.sql on a database with pgvector, then:

    DATABASE_URL=postgresql://localhost/vectordb python main.py
"""

import os
from datetime import datetime

import fraiseql
from fraiseql.db import register_type_for_view
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.sql.order_by_generator import OrderBy, OrderBySet
from fraiseql.types import ID


@fraiseql.type(sql_source="documents", jsonb_column=None)
class Document:
    """Document with vector embeddings and binary hash for similarity search."""

    id: ID
    title: str
    content: str
    embedding: list[float]  # Vector embedding (384 dimensions)
    binary_hash: str  # Binary hash for Hamming/Jaccard (64 bits)
    category: str
    created_at: datetime


# documents is a plain table, not a view with a JSONB data column: tell fraiseql
# its columns so filters and ordering use them directly.
register_type_for_view(
    "documents",
    Document,
    table_columns={"id", "title", "content", "embedding", "binary_hash", "category", "created_at"},
    has_jsonb_data=False,
)


@fraiseql.query
async def search_documents(
    info,
    # Float vector operators
    cosine_distance: list[float] | None = None,
    l2_distance: list[float] | None = None,
    inner_product: list[float] | None = None,
    l1_distance: list[float] | None = None,
    # Binary vector operators
    hamming_distance: str | None = None,
    jaccard_distance: str | None = None,
    # Filters
    category: str | None = None,
    limit: int = 10,
) -> list[Document]:
    """Order documents by similarity to a vector, most similar first.

    Give one distance argument; it orders the results. category narrows them.

    - Semantic search: cosine_distance: [0.1, 0.2, 0.3, ...]
    - Binary search: hamming_distance: "10101010..."
    """
    vector_field, operator, value = "embedding", None, None
    for name, given in [
        ("cosine_distance", cosine_distance),
        ("l2_distance", l2_distance),
        ("inner_product", inner_product),
        ("l1_distance", l1_distance),
    ]:
        if given is not None:
            operator, value = name, given
            break
    for name, given in [
        ("hamming_distance", hamming_distance),
        ("jaccard_distance", jaccard_distance),
    ]:
        if given is not None:
            vector_field, operator, value = "binary_hash", name, given
            break

    where = {"category": {"eq": category}} if category else None
    # A distance ordering carries the vector to compare with, so it is an OrderBy
    # rather than an orderBy input
    order_by = (
        OrderBySet([OrderBy(f"{vector_field}.{operator}", value=value)]) if operator else None
    )

    db = info.context["db"]
    return await db.find(
        "documents",
        "searchDocuments",
        info,
        where=where,
        order_by=order_by,
        limit=limit,
    )


app = create_fraiseql_app(
    database_url=os.getenv("DATABASE_URL", "postgresql://localhost:5432/vectordb"),
    types=[Document],
    queries=[search_documents],
)


if __name__ == "__main__":
    import uvicorn

    print("🚀 Vector Search Example")
    print("📊 Supports all 6 pgvector distance operators:")
    print("   • cosine_distance (<=>) - Semantic similarity")
    print("   • l2_distance (<->) - Euclidean distance")
    print("   • inner_product (<#>) - Learned similarity")
    print("   • l1_distance (<+>) - Manhattan distance")
    print("   • hamming_distance (<~>) - Binary Hamming")
    print("   • jaccard_distance (<%>) - Set similarity")
    print("\n📝 GraphQL endpoint: http://localhost:8000/graphql")

    uvicorn.run(app, host="0.0.0.0", port=8000)

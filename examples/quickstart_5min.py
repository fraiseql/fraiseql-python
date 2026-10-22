"""5-Minute Quickstart Example

This is the complete code from the 5-minute quickstart guide.

Setup instructions:

1. Install FraiseQL: pip install fraiseql

2. Create database: createdb quickstart_notes

3. Run schema: psql quickstart_notes < quickstart_5min_schema.sql

4. Run this file: python quickstart_5min.py

Database Schema:

```sql

-- Simple notes table

CREATE TABLE tb_note (

    id SERIAL PRIMARY KEY,

    title VARCHAR(200) NOT NULL,

    content TEXT,

    created_at TIMESTAMP DEFAULT NOW()

);

-- Notes view for GraphQL queries

CREATE VIEW v_note AS

SELECT

    id,

    jsonb_build_object(

        'id', id,

        'title', title,

        'content', content,

        'created_at', created_at

    ) AS data

FROM tb_note;

-- SQL function for creating notes (CQRS pattern)

CREATE OR REPLACE FUNCTION fn_create_note(input jsonb)

RETURNS jsonb AS $$

DECLARE

    new_id int;

BEGIN

    INSERT INTO tb_note (title, content)

    VALUES (input->>'title', input->>'content')

    RETURNING id INTO new_id;

    RETURN jsonb_build_object('success', true, 'id', new_id);

END;

$$ LANGUAGE plpgsql;

-- Sample data

INSERT INTO tb_note (title, content) VALUES

    ('Welcome to FraiseQL', 'This is your first note!'),

    ('GraphQL is awesome', 'Queries and mutations made simple'),

    ('Database-first design', 'Views compose data for optimal performance');

```

"""

from datetime import datetime

import uvicorn

import fraiseql
from fraiseql.fastapi import create_fraiseql_app


# Define GraphQL types
@fraiseql.type(sql_source="v_note", jsonb_column="data")
class Note:
    """A simple note with title and content."""

    id: int
    title: str
    content: str | None
    created_at: datetime


# Define input types
@fraiseql.input
class CreateNoteInput:
    """Input for creating a new note."""

    title: str
    content: str | None = None


# Define success/error types
@fraiseql.success
class CreateNoteSuccess:
    """Success response for note creation."""

    note: Note
    message: str = "Note created successfully"


@fraiseql.error
class ValidationError:
    """Validation error."""

    message: str
    code: str = "VALIDATION_ERROR"


# Queries
@fraiseql.query
async def notes(info) -> list[Note]:
    """Get all notes."""
    db = info.context["db"]
    return await db.find("v_note", "notes", info, order_by=[("created_at", "DESC")])


@fraiseql.query
async def notes_filtered(info, title_contains: str | None = None) -> list[Note]:
    """Get notes with optional title filtering."""
    db = info.context["db"]
    where = {}
    if title_contains:
        where = {"title": {"ilike": f"%{title_contains}%"}}
    return await db.find("v_note", "notesFiltered", info, where=where, order_by=[("created_at", "DESC")])


@fraiseql.query
async def note(info, id: int) -> Note | None:
    """Get a single note by ID."""
    db = info.context["db"]
    return await db.find_one("v_note", "note", info, id=id)


# Mutations
@fraiseql.mutation
async def create_note(info, input: CreateNoteInput) -> CreateNoteSuccess | ValidationError:
    """Create a new note."""
    db = info.context["db"]

    try:
        # Call SQL function (CQRS pattern)
        result = await db.execute_function("fn_create_note", {
            "title": input.title,
            "content": input.content,
        })

        if not result.get("success"):
            return ValidationError(message="Failed to create note")

        # Fetch the created note via Rust pipeline
        note = await db.find_one("v_note", "note", info, id=result["id"])
        return CreateNoteSuccess(note=note)

    except Exception as e:
        return ValidationError(message=f"Failed to create note: {e!s}")


# Collect types, queries, and mutations for app creation
QUICKSTART_TYPES = [Note]
QUICKSTART_QUERIES = [notes, notes_filtered, note]
QUICKSTART_MUTATIONS = [create_note]


# Create and run the app
if __name__ == "__main__":
    import os

    # Allow database URL to be overridden via environment variable
    database_url = os.getenv("DATABASE_URL", "postgresql://localhost/quickstart_notes")

    app = create_fraiseql_app(
        database_url=database_url,
        types=QUICKSTART_TYPES,
        queries=QUICKSTART_QUERIES,
        mutations=QUICKSTART_MUTATIONS,
        title="Notes API",
        description="Simple note-taking GraphQL API",
        production=False,  # Enable GraphQL playground
    )

    print("🚀 Notes API running at http://localhost:8000/graphql")
    print("📖 GraphQL Playground: http://localhost:8000/graphql")

    uvicorn.run(app, host="0.0.0.0", port=8000)

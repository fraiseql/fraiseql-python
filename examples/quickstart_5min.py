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

-- What a mutation function returns: fraiseql reads these 8 fields

-- (migrations/trinity/005_add_mutation_response.sql defines it too, with helpers)

CREATE TYPE mutation_response AS (

    status text, message text, entity_id text, entity_type text,

    entity jsonb, updated_fields text[], cascade jsonb, metadata jsonb

);

-- SQL function for creating notes (CQRS pattern): the CreateNote mutation calls it

-- with the input as one jsonb

CREATE OR REPLACE FUNCTION create_note(input jsonb)

RETURNS mutation_response AS $$

DECLARE

    new_id int;

BEGIN

    INSERT INTO tb_note (title, content)

    VALUES (input->>'title', input->>'content')

    RETURNING id INTO new_id;

    RETURN ROW('new', 'Note created', new_id::text, 'Note',

               (SELECT data FROM v_note WHERE id = new_id),

               NULL, NULL, NULL)::mutation_response;

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
    return await db.find_one("v_note", "note", info, mandatory_filters={"id": id})


# Mutations: fraiseql calls the SQL function create_note with the input as one
# jsonb, and turns the mutation_response it returns into CreateNoteSuccess or
# ValidationError
@fraiseql.mutation
class CreateNote:
    """Create a new note."""

    input: CreateNoteInput
    success: CreateNoteSuccess
    error: ValidationError


# Collect types, queries, and mutations for app creation
QUICKSTART_TYPES = [Note]
QUICKSTART_QUERIES = [notes, notes_filtered, note]
QUICKSTART_MUTATIONS = [CreateNote]


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

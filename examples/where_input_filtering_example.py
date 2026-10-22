"""Where Input Types & Filtering Example

This example demonstrates FraiseQL's automatic Where input type generation
and powerful filtering capabilities.

Run with: python where_input_filtering_example.py
"""

from datetime import datetime

import uvicorn

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.sql import create_graphql_where_input


# Define GraphQL types
@fraiseql.type(sql_source="v_note", jsonb_column="data")
class Note:
    """A note with filtering capabilities."""

    id: int
    title: str
    content: str | None
    created_at: datetime
    priority: str = "normal"  # low, normal, high
    tags: list[str] = []


# Generate Where input types automatically
NoteWhereInput = create_graphql_where_input(Note)


# Queries demonstrating different filtering approaches
@fraiseql.query
async def notes(info, where=None) -> list[Note]:  # where: NoteWhereInput | None = None
    """Get notes with automatic Where input filtering."""
    db = info.context["db"]
    return await db.find("v_note", where=where)


@fraiseql.query
async def notes_by_priority(info, priority: str) -> list[Note]:
    """Get notes by priority (simple parameter approach)."""
    db = info.context["db"]
    return await db.find("v_note", "notes", info, priority=priority)


@fraiseql.query
async def high_priority_notes(info) -> list[Note]:
    """Get high priority notes using Where input programmatically."""
    db = info.context["db"]

    # Create where filter programmatically
    where_filter = NoteWhereInput(priority={"eq": "high"})
    return await db.find("v_note", where=where_filter)


# Input types for mutations
@fraiseql.input
class CreateNoteInput:
    """Input for creating a new note."""

    title: str
    content: str | None = None
    priority: str = "normal"
    tags: list[str] = []


@fraiseql.input
class UpdateNoteInput:
    """Input for updating a note."""

    id: int
    title: str | None = None
    content: str | None = None
    priority: str | None = None
    tags: list[str] | None = None


# Success/error types
@fraiseql.success
class CreateNoteSuccess:
    """Success response for note creation."""

    note: Note
    message: str = "Note created successfully"


@fraiseql.success
class UpdateNoteSuccess:
    """Success response for note update."""

    note: Note
    message: str = "Note updated successfully"


@fraiseql.error
class NoteError:
    """Error response for note operations."""

    message: str
    code: str


# Mutations. Each calls the SQL function named after it (create_note, update_note),
# which takes the input as one jsonb and returns a mutation_response (see the
# setup notes at the bottom of this file).
@fraiseql.mutation
class CreateNote:
    """Create a new note."""

    input: CreateNoteInput
    success: CreateNoteSuccess
    error: NoteError


@fraiseql.mutation
class UpdateNote:
    """Update an existing note."""

    input: UpdateNoteInput
    success: UpdateNoteSuccess
    error: NoteError


# Collect all types, queries, and mutations
EXAMPLE_TYPES = [Note]
EXAMPLE_QUERIES = [notes, notes_by_priority, high_priority_notes]
EXAMPLE_MUTATIONS = [CreateNote, UpdateNote]


# Create and run the app
if __name__ == "__main__":
    import os

    # Database setup - create these tables/views first:
    # CREATE TABLE tb_note (id SERIAL PRIMARY KEY, title VARCHAR(200) NOT NULL,
    #                       content TEXT, priority VARCHAR(20) DEFAULT 'normal',
    #                       tags TEXT[] DEFAULT '{}', created_at TIMESTAMP DEFAULT NOW());
    # CREATE VIEW v_note AS SELECT id, jsonb_build_object('id', id, 'title', title,
    #                       'content', content, 'priority', priority, 'tags', tags,
    #                       'created_at', created_at) AS data FROM tb_note;
    #
    # The mutations call these functions. mutation_response and the mutation_*
    # helpers come from migrations/trinity/005_add_mutation_response.sql.
    #
    # CREATE FUNCTION create_note(input jsonb) RETURNS mutation_response AS $$
    # DECLARE v_id int;
    # BEGIN
    #     INSERT INTO tb_note (title, content, priority, tags)
    #     VALUES (input->>'title', input->>'content',
    #             coalesce(input->>'priority', 'normal'),
    #             coalesce(ARRAY(SELECT jsonb_array_elements_text(input->'tags')), '{}'))
    #     RETURNING id INTO v_id;
    #     RETURN mutation_created('Note created',
    #         (SELECT data FROM v_note WHERE id = v_id), 'Note');
    # END;
    # $$ LANGUAGE plpgsql;
    #
    # CREATE FUNCTION update_note(input jsonb) RETURNS mutation_response AS $$
    # BEGIN
    #     UPDATE tb_note SET
    #         title = coalesce(input->>'title', title),
    #         content = coalesce(input->>'content', content),
    #         priority = coalesce(input->>'priority', priority),
    #         tags = CASE WHEN input ? 'tags' AND input->'tags' <> 'null'
    #                     THEN ARRAY(SELECT jsonb_array_elements_text(input->'tags'))
    #                     ELSE tags END
    #     WHERE id = (input->>'id')::int;
    #     IF NOT FOUND THEN
    #         RETURN mutation_not_found('Note', input->>'id');
    #     END IF;
    #     RETURN mutation_updated('Note updated',
    #         (SELECT data FROM v_note WHERE id = (input->>'id')::int),
    #         ARRAY(SELECT jsonb_object_keys(jsonb_strip_nulls(input - 'id'))), 'Note');
    # END;
    # $$ LANGUAGE plpgsql;

    database_url = os.getenv("DATABASE_URL", "postgresql://localhost/fraiseql_where_example")

    app = create_fraiseql_app(
        database_url=database_url,
        types=EXAMPLE_TYPES,
        queries=EXAMPLE_QUERIES,
        mutations=EXAMPLE_MUTATIONS,
        title="Where Input Filtering Example",
        description="Demonstrates FraiseQL's automatic Where input type generation and filtering",
        production=False,
    )

    print("🚀 Where Input Filtering Example running at http://localhost:8000/graphql")
    print("📖 GraphQL Playground: http://localhost:8000/graphql")
    print("\nTry these queries:")
    print("""
# Get all notes
query { notes { id title priority tags } }

# Filter with Where input
query {
  notes(where: {
    priority: { eq: "high" },
    title: { contains: "meeting" }
  }) {
    id title content priority
  }
}

# Complex filtering with AND/OR
query {
  notes(where: {
    AND: [
      { priority: { in: ["high", "normal"] } },
      { title: { contains: "project" } }
    ]
  }) {
    id title priority tags
  }
}
""")

    uvicorn.run(app, host="0.0.0.0", port=8000)

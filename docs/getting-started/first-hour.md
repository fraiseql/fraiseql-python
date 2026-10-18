---
title: First Hour Guide
description: Progressive tutorial for your first hour with FraiseQL
tags:
  - tutorial
  - getting-started
  - learning
  - guide
  - beginner
---

# Your First Hour with FraiseQL

Welcome! You've just completed the 5-minute quickstart and have a working GraphQL API. Now let's spend the next 55 minutes building your skills progressively. By the end, you'll understand how to extend FraiseQL applications and implement production patterns.

## Prerequisites

Before starting, ensure you have the necessary imports in your `app.py`:

```python
from fraiseql.types import ID
from datetime import datetime

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.sql import create_graphql_where_input
```

**Note**: This tutorial requires Python 3.13+ and uses modern type syntax (`list[str]`, `str | None`) instead of the older `typing` module imports.

## Minute 0-5: Quickstart Recap

**[Complete the 5-minute quickstart first](quickstart.md)**

You should now have:

- A working GraphQL API at `http://localhost:8000/graphql`
- A PostgreSQL database with a `v_note` view
- A basic note-taking app

✅ **Checkpoint**: Can you run this query and get results?

```graphql
query {
  notes {
    id
    title
    content
  }
}
```

## Minute 5-15: Understanding What You Built

**[Read the Understanding Guide](../guides/understanding-fraiseql.md)**

Key concepts you should now understand:

- **Database-first GraphQL**: Start with PostgreSQL, not GraphQL types
- **JSONB Views**: `tb_*` tables → `v_*` views → GraphQL responses (see [JSONB View Pattern](../core/concepts-glossary.md#jsonb-view-pattern))
- **[CQRS Pattern](../core/concepts-glossary.md#cqrs-command-query-responsibility-segregation)**: Reads (views) vs Writes (PostgreSQL functions)
- **Naming Conventions**: `tb_*`, `v_*`, `fn_*`, `tv_*`

✅ **Checkpoint**: Can you explain why FraiseQL uses JSONB views instead of traditional ORMs?

> **💡 Advanced Filtering**: FraiseQL supports powerful PostgreSQL operators including array filtering, full-text search, JSONB queries, and regex matching. See [Filter Operators Reference](../advanced/filter-operators.md) for details.

## Minute 15-30: Extend Your API - Add Tags to Notes

**Challenge**: Add a "tags" feature so notes can be categorized.

### Step 1: Update Database Schema

First, add a tags column to your note table:

```sql
-- Add tags column to tb_note
ALTER TABLE tb_note ADD COLUMN tags TEXT[] DEFAULT '{}';

-- Update sample data with tags
UPDATE tb_note SET tags = ARRAY['work', 'urgent'] WHERE title = 'First Note';
UPDATE tb_note SET tags = ARRAY['personal', 'ideas'] WHERE title = 'Second Note';

-- Add a note with 'work' in the title for filter examples
INSERT INTO tb_note (title, content, tags)
VALUES ('Work Meeting Notes', 'Discussed Q4 project timeline', ARRAY['work', 'meeting']);
```

### Step 2: Update the View

Modify `v_note` to include tags. **Important**: Views must include both an `id` column AND a `data` column containing the JSONB object:

```sql
-- Drop and recreate view with tags
DROP VIEW v_note;
CREATE VIEW v_note AS
SELECT
    id,  -- Required: FraiseQL queries filter by this column
    jsonb_build_object(
        'id', id,
        'title', title,
        'content', content,
        'tags', tags
    ) as data  -- Required: Contains the GraphQL response data
FROM tb_note;
```

**Why both columns?** The `id` column enables efficient WHERE clause filtering (`WHERE id = $1`), while the `data` column contains the complete JSONB object returned to GraphQL.

**After making schema changes, restart your server** to pick up the new view definition.

### Step 3: Update Python Type

Add tags to your Note type:

```python
# app.py
@fraiseql.type
class Note:
    id: ID
    title: str
    content: str
    tags: list[str]  # Add this line
```

### Step 4: Add Filtering with Where Input Types

FraiseQL provides automatic Where input type generation for powerful, type-safe filtering:

```python
# app.py
# Generate automatic Where input type for Note
NoteWhereInput = create_graphql_where_input(Note)

@fraiseql.query
async def notes(info, where: NoteWhereInput | None = None) -> list[Note]:
    """Get notes with optional filtering."""
    db = info.context["db"]
    # Use repository's find method with where parameter
    return await db.find("v_note", where=where)
```

**Restart your server** to register the updated query with where filtering.

### Step 5: Test Your Changes

Test the powerful filtering capabilities:

```graphql
query {
  # Get all notes
  notes {
    id
    title
    tags
  }

  # Filter notes by title containing "work"
  workNotes: notes(where: { title: { contains: "work" } }) {
    title
    content
  }

  # Filter notes with specific tag using array contains
  urgentNotes: notes(where: { tags: { contains: "urgent" } }) {
    title
    tags
  }

  # Combine multiple conditions
  complexFilter: notes(where: {
    AND: [
      { title: { contains: "meeting" } },
      { tags: { contains: "work" } }
    ]
  }) {
    title
    content
    tags
  }
}
```

**Available Filter Operators:**

- `eq`, `neq` - equals, not equals
- `contains`, `startswith`, `endswith` - string matching
- `gt`, `gte`, `lt`, `lte` - comparisons
- `in`, `nin` - list membership
- `isnull` - null checking
- `AND`, `OR`, `NOT` - logical operators

and many more specialized operators for specific Postgresql types (CIDR, LTREE etc.)

✅ **Checkpoint**: Can you create a note with tags and use the various filtering operators?

## Minute 30-45: Add a Mutation - Delete Notes

**Challenge**: Add the ability to delete notes.

### Step 1: Create Delete Function (Basic Pattern)

Create a PostgreSQL function for deletion that returns a simple boolean:

```sql
-- Create basic delete function (returns boolean)
CREATE OR REPLACE FUNCTION fn_delete_note(note_id UUID)
RETURNS BOOLEAN AS $$
BEGIN
    DELETE FROM tb_note WHERE id = note_id;
    RETURN FOUND;  -- Returns true if a row was deleted, false otherwise
END;
$$ LANGUAGE plpgsql;
```

### Step 2: Add Python Mutation (Basic Pattern)

Add a simple mutation to your app:

```python
# app.py
@fraiseql.mutation
async def delete_note(info, id: ID) -> bool:
    """Delete a note by ID (returns true if deleted, false if not found)."""
    db = info.context["db"]
    return await db.fetchval("SELECT fn_delete_note($1)", id)
```

**Restart your server** to register the new mutation.

### Step 3: Test the Mutation

Try this in GraphQL playground:

```graphql
mutation {
  deleteNote(id: "your-note-id-here")
}
```

### Step 4: Improve Error Handling (Production Pattern)

The boolean return is simple but doesn't provide error details. Let's improve this with structured success/failure types.

**First, update the database function** to return JSONB with error information:

```sql
-- Improved function that returns JSONB with error details
CREATE OR REPLACE FUNCTION fn_delete_note(note_id UUID)
RETURNS JSONB AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM tb_note WHERE id = note_id;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;

    IF deleted_count = 0 THEN
        RETURN jsonb_build_object(
            'success', false,
            'message', 'Note not found',
            'code', 'NOT_FOUND'
        );
    ELSE
        RETURN jsonb_build_object(
            'success', true,
            'message', 'Note deleted successfully'
        );
    END IF;
END;
$$ LANGUAGE plpgsql;
```

**Next, define success and failure types** using FraiseQL decorators:

```python
# app.py
@fraiseql.success
class DeleteNoteSuccess:
    """Successful deletion response."""
    message: str = "Note deleted successfully"

@fraiseql.failure
class DeleteNoteError:
    """Deletion error response."""
    message: str
    code: str = "NOT_FOUND"

@fraiseql.mutation
async def delete_note(info, id: ID) -> DeleteNoteSuccess | DeleteNoteError:
    """Delete a note by ID with detailed error handling."""
    db = info.context["db"]
    # Call function that returns JSONB directly from database
    # FraiseQL automatically maps JSONB to the appropriate type
    result = await db.fetchval("SELECT fn_delete_note($1)", id)

    # Return the appropriate type based on success field
    if result.get("success"):
        return DeleteNoteSuccess(message=result["message"])
    else:
        return DeleteNoteError(
            message=result["message"],
            code=result.get("code", "UNKNOWN_ERROR")
        )
```

**Why this pattern?** Using `@success` and `@error` decorators creates a proper GraphQL union type, allowing clients to handle success and error cases explicitly in their queries.

**Restart your server** to register the updated mutation with new types.

✅ **Checkpoint**: Can you delete a note and handle the case where the note doesn't exist?

## Minute 45-60: Production Patterns - Timestamps

**Challenge**: Add `created_at` and `updated_at` timestamps with automatic updates.

### Step 1: Add Timestamp Columns

```sql
-- Add timestamp columns
ALTER TABLE tb_note ADD COLUMN created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
ALTER TABLE tb_note ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();

-- Update existing records
UPDATE tb_note SET created_at = NOW(), updated_at = NOW();
```

### Step 2: Create Update Trigger

```sql
-- Function to update updated_at
-- ℹ️ FraiseQL Best Practice: Use DEFAULT instead of triggers
-- Triggers hide logic from AI and make code harder to understand.
-- For timestamp updates, use explicit application code:

-- Python mutation example:
-- @mutation
-- async def update_note(id: str, title: str, context: Context) -> Note:
--     return await context.db.update("tb_note", id, {
--         "title": title,
--         "updated_at": datetime.utcnow()  # Explicit!
--     })

-- Or use DEFAULT for automatic creation timestamps:
-- created_at TIMESTAMPTZ DEFAULT NOW()  -- Set once on INSERT
```

### Step 3: Update View

```sql
-- Recreate view with timestamps
DROP VIEW v_note;
CREATE VIEW v_note AS
SELECT
    id,  -- Required: enables WHERE clause filtering
    jsonb_build_object(
        'id', id,
        'title', title,
        'content', content,
        'tags', tags,
        'createdAt', created_at,
        'updatedAt', updated_at
    ) as data  -- Required: contains GraphQL response
FROM tb_note;
```

**Restart your server** after updating the view.

### Step 4: Update Python Type

```python
# app.py
@fraiseql.type(sql_source="v_note")
class Note:
    id: ID
    title: str
    content: str
    tags: list[str]
    created_at: datetime  # Add this
    updated_at: datetime  # Add this
```

**What is `sql_source`?** This parameter tells FraiseQL which database view to query. It's optional when the view name matches the class name (e.g., class `Note` → view `v_note`), but becomes required if:

- The view name doesn't follow the `v_{lowercase_class_name}` pattern
- You want to explicitly document the data source
- You're using a table view (`tv_*`) instead of a regular view

In this example, we could omit `sql_source` since FraiseQL automatically infers `v_note` from the class name `Note`. However, being explicit makes the code more readable and maintainable.

**Restart your server** to register the updated Note type with timestamps.

### Step 5: Test Automatic Updates

Create a note, then update it and verify `updated_at` changes but `created_at` stays the same.

✅ **Checkpoint**: Do timestamps update automatically when you modify notes?

## 🎉 Congratulations

You've completed your first hour with FraiseQL! You now know how to:

- ✅ Extend existing APIs with new fields
- ✅ Add filtering capabilities
- ✅ Implement write operations (mutations)
- ✅ Handle errors gracefully
- ✅ Add production-ready features like timestamps

## What's Next?

### Immediate Next Steps (2-3 hours)

- **[Beginner Learning Path](../tutorials/beginner-path.md)** - Deep dive into all core concepts
- **[Blog API Tutorial](../tutorials/blog-api.md)** - Build a complete application

### Explore Examples (30 minutes each)

- **E-commerce API (../examples/ecommerce/)** - Shopping cart, products, orders
- **[Subscriptions](../architecture/realtime/subscriptions.md)** - Subscriptions and real-time updates
- **Multi-tenant SaaS (../examples/apq_multi_tenant/)** - Enterprise patterns

### Advanced Topics

- **[Performance Guide](../guides/performance-guide.md)** - Optimization techniques
- **[Multi-tenancy](../advanced/multi-tenancy.md)** - Building SaaS applications


### Need Help?

- **[Troubleshooting Guide](../guides/troubleshooting.md)** - Common issues and solutions
- **[Quick Reference](../reference/quick-reference.md)** - Copy-paste code patterns
- **[GitHub Discussions](../discussions)** - Community support

---

**Ready for more?** The [Beginner Learning Path](../tutorials/beginner-path.md) will take you from here to building production applications! 🚀

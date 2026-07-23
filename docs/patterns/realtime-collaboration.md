---
title: Real-Time Collaboration with Subscriptions
description: Blueprint for building collaborative tools (like Google Docs, Figma, Notion) with real-time synchronization using FraiseQL subscriptions backed by PostgreSQL LISTEN/NOTIFY.
keywords: ["realtime", "collaboration", "subscriptions", "websocket", "postgresql", "listen-notify"]
tags: ["documentation", "patterns"]
---

# Real-Time Collaboration with Subscriptions

**Status:** Production Ready
**Complexity:** Advanced
**Audience:** Frontend architects, real-time systems engineers
**Reading Time:** 25-30 minutes

Blueprint for building collaborative tools (like Google Docs, Figma, Notion) with
real-time synchronization using FraiseQL subscriptions.

In FraiseQL v1 a subscription is an **async-generator resolver** served over a
GraphQL WebSocket connection. You write the generator; FraiseQL streams whatever it
yields to the subscribed client. The natural event source for collaboration is
PostgreSQL **`LISTEN`/`NOTIFY`**: a trigger on a write table emits `NOTIFY` on a
channel, and the resolver `async for`s those notifications, re-reads a read view,
and `yield`s the fresh value. Everything — documents, operations, presence, comments
— lives in PostgreSQL.

---

## Architecture Overview

```text
Collaborators (browsers)
        |   GraphQL over WebSocket (graphql-transport-ws)
        v
FastAPI app  (create_fraiseql_app)
  - @fraiseql.query      reads v_/tv_ views
  - @fraiseql.mutation   calls fn_ functions (which also NOTIFY)
  - @fraiseql.subscription  async generators: LISTEN a channel -> re-read view -> yield
        |
        v
PostgreSQL
  - tb_document, tb_document_change, tb_presence, tb_comment   (write tables)
  - triggers: AFTER INSERT/UPDATE -> NOTIFY <channel>, <id>
  - v_document, v_document_change, v_presence, v_comment       (read views, data JSONB)
  - fn_apply_operation, fn_update_presence, fn_add_comment     (write functions)
```

The flow for a single edit:

1. A client sends an `applyOperation` **mutation**. The resolver calls a `fn_` function
   that writes a row into `tb_document_change` and updates `tb_document`.
2. A PostgreSQL **trigger** on `tb_document_change` issues
   `NOTIFY document_change, '<document_id>'`.
3. Every **subscription** resolver that is `LISTEN`-ing on the `document_change`
   channel for that document wakes up, re-reads `v_document_change`, and `yield`s the
   new change.
4. FraiseQL pushes the yielded payload down each subscribed WebSocket to the other
   collaborators.

There is no external broker. PostgreSQL is the source of truth and the message bus.

---

## Schema Design

FraiseQL's convention separates the normalized write tables (`tb_`) from the read
views (`v_`) that build a `data` JSONB column. Internal `pk_` keys stay hidden; the
public surface is the `id` UUID.

### Write tables

```sql
-- Documents (editable items)
CREATE TABLE tb_document (
    pk_document   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id            UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    workspace_id  UUID NOT NULL,
    title         TEXT NOT NULL,
    content_type  TEXT NOT NULL,          -- text, rich-text, spreadsheet, drawing
    content       TEXT NOT NULL DEFAULT '',
    created_by    UUID NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at    TIMESTAMPTZ              -- soft delete
);
CREATE INDEX idx_document_workspace ON tb_document (workspace_id);
CREATE INDEX idx_document_updated   ON tb_document (updated_at);

-- Permissions (who can edit/view)
CREATE TABLE tb_document_permission (
    pk_document_permission BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id           UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    fk_document  BIGINT NOT NULL REFERENCES tb_document (pk_document) ON DELETE CASCADE,
    user_id      UUID NOT NULL,
    permission   TEXT NOT NULL,           -- view, edit, comment, manage
    granted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fk_document, user_id)
);

-- Changes / operations (one row per edit)
CREATE TABLE tb_document_change (
    pk_document_change BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id           UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    fk_document  BIGINT NOT NULL REFERENCES tb_document (pk_document) ON DELETE CASCADE,
    user_id      UUID NOT NULL,
    operation    JSONB NOT NULL,          -- { "type": "insert", "position": 100, "content": "text" }
    vector_clock JSONB NOT NULL,          -- causality, e.g. { "user_1": 5, "user_2": 3 }
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_change_document ON tb_document_change (fk_document, pk_document_change);

-- Presence (who is currently editing)
CREATE TABLE tb_presence (
    pk_presence  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id           UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    fk_document  BIGINT NOT NULL REFERENCES tb_document (pk_document) ON DELETE CASCADE,
    user_id      UUID NOT NULL,
    cursor_position INT,
    selection_start INT,
    selection_end   INT,
    color        TEXT,                     -- "#FF5733"
    last_activity TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fk_document, user_id)
);
CREATE INDEX idx_presence_activity ON tb_presence (fk_document, last_activity);

-- Comments
CREATE TABLE tb_comment (
    pk_comment   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id           UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    fk_document  BIGINT NOT NULL REFERENCES tb_document (pk_document) ON DELETE CASCADE,
    fk_parent    BIGINT REFERENCES tb_comment (pk_comment) ON DELETE CASCADE,
    user_id      UUID NOT NULL,
    content      TEXT NOT NULL,
    position     INT,                      -- where in the document, for inline comments
    resolved     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_comment_document ON tb_comment (fk_document);
```

### Read views (the GraphQL query/subscription sources)

Each view exposes the public `id` plus a `data` JSONB column built with
`jsonb_build_object(...)`. Never put `pk_*` inside `data`.

```sql
CREATE VIEW v_document AS
SELECT
    d.id,
    d.workspace_id,
    jsonb_build_object(
        'id',            d.id,
        'title',         d.title,
        'contentType',   d.content_type,
        'content',       d.content,
        'createdBy',     d.created_by,
        'createdAt',     d.created_at,
        'updatedAt',     d.updated_at
    ) AS data
FROM tb_document d
WHERE d.deleted_at IS NULL;

CREATE VIEW v_document_change AS
SELECT
    c.id,
    d.id AS document_id,
    jsonb_build_object(
        'id',           c.id,
        'userId',       c.user_id,
        'operation',    c.operation,
        'vectorClock',  c.vector_clock,
        'createdAt',    c.created_at
    ) AS data
FROM tb_document_change c
JOIN tb_document d ON d.pk_document = c.fk_document;

CREATE VIEW v_presence AS
SELECT
    p.id,
    d.id AS document_id,
    jsonb_build_object(
        'userId',         p.user_id,
        'cursorPosition', p.cursor_position,
        'selectionStart', p.selection_start,
        'selectionEnd',   p.selection_end,
        'color',          p.color,
        'lastActivity',   p.last_activity
    ) AS data
FROM tb_presence p
JOIN tb_document d ON d.pk_document = p.fk_document;

CREATE VIEW v_comment AS
SELECT
    c.id,
    d.id AS document_id,
    jsonb_build_object(
        'id',         c.id,
        'userId',     c.user_id,
        'content',    c.content,
        'position',   c.position,
        'resolved',   c.resolved,
        'createdAt',  c.created_at
    ) AS data
FROM tb_comment c
JOIN tb_document d ON d.pk_document = c.fk_document;
```

---

## Triggers: turn writes into NOTIFY events

The bridge between a mutation and every live subscription is a trigger that emits a
`NOTIFY`. The payload is just the document `id`, so listeners know which document
changed; they re-read the view to get the fresh data.

```sql
-- Notify on every new change row
CREATE OR REPLACE FUNCTION fn_notify_document_change() RETURNS TRIGGER AS $$
DECLARE
    v_document_id UUID;
BEGIN
    SELECT id INTO v_document_id FROM tb_document WHERE pk_document = NEW.fk_document;
    PERFORM pg_notify('document_change', v_document_id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_document_change_notify
    AFTER INSERT ON tb_document_change
    FOR EACH ROW
    EXECUTE FUNCTION fn_notify_document_change();

-- Notify on presence updates
CREATE OR REPLACE FUNCTION fn_notify_presence() RETURNS TRIGGER AS $$
DECLARE
    v_document_id UUID;
BEGIN
    SELECT id INTO v_document_id FROM tb_document WHERE pk_document = NEW.fk_document;
    PERFORM pg_notify('presence', v_document_id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_presence_notify
    AFTER INSERT OR UPDATE ON tb_presence
    FOR EACH ROW
    EXECUTE FUNCTION fn_notify_presence();

-- Notify on new comments
CREATE OR REPLACE FUNCTION fn_notify_comment() RETURNS TRIGGER AS $$
DECLARE
    v_document_id UUID;
BEGIN
    SELECT id INTO v_document_id FROM tb_document WHERE pk_document = NEW.fk_document;
    PERFORM pg_notify('comment', v_document_id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_comment_notify
    AFTER INSERT ON tb_comment
    FOR EACH ROW
    EXECUTE FUNCTION fn_notify_comment();
```

> `pg_notify` payloads are capped at 8000 bytes, which is why we send only the
> document `id` and re-read the view rather than shipping the whole row over the
> channel.

---

## Write functions (`fn_`)

Mutations never touch tables directly. They call PostgreSQL functions that hold the
write logic and return JSONB describing success or failure. Because the writes go
through `tb_document_change` / `tb_presence` / `tb_comment`, the triggers above fire
automatically — the mutation does not have to `NOTIFY` by hand.

```sql
CREATE OR REPLACE FUNCTION fn_apply_operation(
    p_document_id  UUID,
    p_user_id      UUID,
    p_operation    JSONB,
    p_vector_clock JSONB
) RETURNS JSONB AS $$
DECLARE
    v_pk_document BIGINT;
    v_change      tb_document_change;
BEGIN
    SELECT pk_document INTO v_pk_document
    FROM tb_document
    WHERE id = p_document_id AND deleted_at IS NULL;

    IF v_pk_document IS NULL THEN
        RETURN jsonb_build_object('success', false, 'message', 'document not found');
    END IF;

    INSERT INTO tb_document_change (fk_document, user_id, operation, vector_clock)
    VALUES (v_pk_document, p_user_id, p_operation, p_vector_clock)
    RETURNING * INTO v_change;

    -- Apply the operation to the materialized content (insert/delete on text).
    UPDATE tb_document
    SET content = CASE p_operation->>'type'
            WHEN 'insert' THEN
                left(content, (p_operation->>'position')::int)
                || (p_operation->>'content')
                || substr(content, (p_operation->>'position')::int + 1)
            WHEN 'delete' THEN
                left(content, (p_operation->>'position')::int)
                || substr(content,
                          (p_operation->>'position')::int
                          + (p_operation->>'length')::int + 1)
            ELSE content
        END,
        updated_at = now()
    WHERE pk_document = v_pk_document;

    RETURN jsonb_build_object('success', true, 'change_id', v_change.id);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_update_presence(
    p_document_id     UUID,
    p_user_id         UUID,
    p_cursor_position INT,
    p_selection_start INT,
    p_selection_end   INT,
    p_color           TEXT
) RETURNS JSONB AS $$
DECLARE
    v_pk_document BIGINT;
BEGIN
    SELECT pk_document INTO v_pk_document FROM tb_document WHERE id = p_document_id;
    IF v_pk_document IS NULL THEN
        RETURN jsonb_build_object('success', false, 'message', 'document not found');
    END IF;

    INSERT INTO tb_presence
        (fk_document, user_id, cursor_position, selection_start, selection_end, color)
    VALUES
        (v_pk_document, p_user_id, p_cursor_position,
         p_selection_start, p_selection_end, p_color)
    ON CONFLICT (fk_document, user_id) DO UPDATE
        SET cursor_position = EXCLUDED.cursor_position,
            selection_start = EXCLUDED.selection_start,
            selection_end   = EXCLUDED.selection_end,
            color           = EXCLUDED.color,
            last_activity   = now();

    RETURN jsonb_build_object('success', true);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_add_comment(
    p_document_id UUID,
    p_user_id     UUID,
    p_content     TEXT,
    p_position    INT
) RETURNS JSONB AS $$
DECLARE
    v_pk_document BIGINT;
    v_comment     tb_comment;
BEGIN
    SELECT pk_document INTO v_pk_document FROM tb_document WHERE id = p_document_id;
    IF v_pk_document IS NULL THEN
        RETURN jsonb_build_object('success', false, 'message', 'document not found');
    END IF;

    INSERT INTO tb_comment (fk_document, user_id, content, position)
    VALUES (v_pk_document, p_user_id, p_content, p_position)
    RETURNING * INTO v_comment;

    RETURN jsonb_build_object('success', true, 'comment_id', v_comment.id);
END;
$$ LANGUAGE plpgsql;
```

---

## FraiseQL Schema

Types map to the read views. Queries and mutations follow the CQRS split; the
subscriptions are async generators backed by `LISTEN/NOTIFY`.

```python
# collaboration_schema.py
from collections.abc import AsyncGenerator
from datetime import datetime

import fraiseql
from fraiseql.types import ID, JSON


@fraiseql.type(sql_source="v_document", jsonb_column="data")
class Document:
    id: ID
    title: str
    content_type: str
    content: str               # current materialized document state
    created_by: ID
    created_at: datetime
    updated_at: datetime


@fraiseql.type(sql_source="v_document_change", jsonb_column="data")
class DocumentChange:
    """A single applied operation."""

    id: ID
    user_id: ID
    operation: JSON            # { type, position, content }
    vector_clock: JSON         # causality across users
    created_at: datetime


@fraiseql.type(sql_source="v_presence", jsonb_column="data")
class Presence:
    """Real-time editor presence."""

    user_id: ID
    cursor_position: int | None
    selection_start: int | None
    selection_end: int | None
    color: str | None
    last_activity: datetime


@fraiseql.type(sql_source="v_comment", jsonb_column="data")
class Comment:
    id: ID
    user_id: ID
    content: str
    position: int | None
    resolved: bool
    created_at: datetime


@fraiseql.input
class ApplyOperationInput:
    document_id: ID
    operation: JSON
    vector_clock: JSON


@fraiseql.input
class UpdatePresenceInput:
    document_id: ID
    cursor_position: int
    selection_start: int | None = None
    selection_end: int | None = None
    color: str | None = None


@fraiseql.input
class AddCommentInput:
    document_id: ID
    content: str
    position: int | None = None


@fraiseql.success
class ChangeSuccess:
    change: DocumentChange


@fraiseql.error
class ChangeError:
    message: str
    code: str = "OPERATION_FAILED"
```

### Queries (reads)

```python
@fraiseql.query
async def document(info, id: ID) -> Document | None:
    db = info.context["db"]
    return await db.find_one("v_document", id=id)


@fraiseql.query
async def document_changes(info, document_id: ID) -> list[DocumentChange]:
    """Changes for a document, oldest first (used to catch up on reconnect)."""
    db = info.context["db"]
    return await db.find("v_document_change", document_id=document_id)


@fraiseql.query
async def comments(info, document_id: ID) -> list[Comment]:
    db = info.context["db"]
    return await db.find("v_comment", document_id=document_id)
```

### Mutations (writes via `fn_`)

```python
@fraiseql.mutation
async def apply_operation(
    info, input: ApplyOperationInput
) -> ChangeSuccess | ChangeError:
    db = info.context["db"]
    user_id = info.context["user_id"]
    result = await db.execute_function(
        "fn_apply_operation",
        {
            "p_document_id": input.document_id,
            "p_user_id": user_id,
            "p_operation": input.operation,
            "p_vector_clock": input.vector_clock,
        },
    )
    if not result.get("success"):
        return ChangeError(message=result.get("message", "failed"))
    change = await db.find_one("v_document_change", id=result["change_id"])
    return ChangeSuccess(change=change)


@fraiseql.mutation
async def update_presence(info, input: UpdatePresenceInput) -> bool:
    db = info.context["db"]
    user_id = info.context["user_id"]
    result = await db.execute_function(
        "fn_update_presence",
        {
            "p_document_id": input.document_id,
            "p_user_id": user_id,
            "p_cursor_position": input.cursor_position,
            "p_selection_start": input.selection_start,
            "p_selection_end": input.selection_end,
            "p_color": input.color,
        },
    )
    return bool(result.get("success"))


@fraiseql.mutation
async def add_comment(info, input: AddCommentInput) -> Comment | None:
    db = info.context["db"]
    user_id = info.context["user_id"]
    result = await db.execute_function(
        "fn_add_comment",
        {
            "p_document_id": input.document_id,
            "p_user_id": user_id,
            "p_content": input.content,
            "p_position": input.position,
        },
    )
    if not result.get("success"):
        return None
    return await db.find_one("v_comment", id=result["comment_id"])
```

---

## Subscriptions: async generators over LISTEN/NOTIFY

A subscription resolver is an **async generator**. It opens a dedicated PostgreSQL
connection, runs `LISTEN <channel>`, and `async for`s incoming notifications. When a
notification arrives whose payload matches the subscribed document, it re-reads the
relevant view and `yield`s the fresh value. FraiseQL serves each yielded value to the
client over the WebSocket.

```python
# realtime.py
from collections.abc import AsyncGenerator

import fraiseql
from fraiseql.types import ID


async def _listen(pool, channel: str, document_id: str) -> AsyncGenerator[None, None]:
    """Yield once per NOTIFY on `channel` whose payload is `document_id`."""
    async with pool.connection() as conn:
        await conn.execute(f"LISTEN {channel}")
        async for notify in conn.notifies():
            if notify.payload == str(document_id):
                yield None


@fraiseql.subscription
async def document_change_stream(
    info, document_id: ID
) -> AsyncGenerator[DocumentChange, None]:
    """Stream every change applied to a document by anyone."""
    db = info.context["db"]
    pool = info.context["pool"]
    last_seen = None
    async for _ in _listen(pool, "document_change", document_id):
        changes = await db.find("v_document_change", document_id=document_id)
        for change in changes:
            if last_seen is None or change.created_at > last_seen:
                last_seen = change.created_at
                yield change


@fraiseql.subscription
async def presence_stream(
    info, document_id: ID
) -> AsyncGenerator[Presence, None]:
    """Stream presence updates (cursor moves, joins, leaves)."""
    db = info.context["db"]
    pool = info.context["pool"]
    async for _ in _listen(pool, "presence", document_id):
        for presence in await db.find("v_presence", document_id=document_id):
            yield presence


@fraiseql.subscription
async def comment_stream(
    info, document_id: ID
) -> AsyncGenerator[Comment, None]:
    """Stream new comments as they are posted."""
    db = info.context["db"]
    pool = info.context["pool"]
    async for _ in _listen(pool, "comment", document_id):
        for comment in await db.find("v_comment", document_id=document_id):
            yield comment
```

Transport is GraphQL-over-WebSocket. FraiseQL's `SubscriptionManager` /
`WebSocketConnection` handle both the modern `graphql-transport-ws` protocol and the
legacy `graphql-ws` one, so the standard clients (Apollo, urql, `graphql-ws`) connect
without custom code.

### Subscription helpers

FraiseQL ships helpers you can layer onto a subscription:

- **`subscription_filter`** — drop yielded values that don't match a predicate
  (for example, never echo a user's own edit back to them).
- **`complexity`** — bound the cost of a subscription so a client can't open an
  unbounded fan-out.
- **`with_lifecycle`** — run setup/teardown around the generator (for example, write
  a presence row on connect and remove it on disconnect).
- **subscription result `cache`** — reuse a recently computed payload across
  subscribers of the same document.

```python
from fraiseql.subscriptions import subscription_filter


@fraiseql.subscription
@subscription_filter(lambda change, info: change.user_id != info.context["user_id"])
async def others_changes(
    info, document_id: ID
) -> AsyncGenerator[DocumentChange, None]:
    """Like document_change_stream, but skips the caller's own changes."""
    db = info.context["db"]
    pool = info.context["pool"]
    last_seen = None
    async for _ in _listen(pool, "document_change", document_id):
        for change in await db.find("v_document_change", document_id=document_id):
            if last_seen is None or change.created_at > last_seen:
                last_seen = change.created_at
                yield change
```

You can also gate a subscription with an authorizer, exactly as for queries:

```python
@fraiseql.subscription(authorizer=document_viewer_authorizer)
async def guarded_stream(
    info, document_id: ID
) -> AsyncGenerator[DocumentChange, None]:
    ...
```

### Wiring it into the app

```python
from fraiseql.fastapi import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/collab",
    types=[Document, DocumentChange, Presence, Comment],
    queries=[document, document_changes, comments],
    mutations=[apply_operation, update_presence, add_comment],
    subscriptions=[document_change_stream, presence_stream, comment_stream],
    production=False,   # enables the GraphQL playground (and WebSocket testing)
)
```

Run it like any FastAPI app:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

---

## Conflict resolution

For documents with concurrent edits, resolve order deterministically before applying:

1. **Vector clocks** — track causality between users' operations.
2. **Position-based transform** — adjust an operation's position against operations
   that landed earlier.
3. **User-ID tiebreaker** — when two inserts target the same position, order by user
   ID so every replica converges on the same result.

This logic can live in the client (apply optimistically, reconcile on the incoming
stream) and/or in the `fn_apply_operation` function (authoritative ordering). A simple
position transform:

```python
def transform_operation(incoming: dict, applied: dict) -> dict:
    """Shift `incoming` so it stays correct after `applied` already landed."""
    if applied.get("type") == "insert" and incoming.get("position", 0) >= applied["position"]:
        shift = len(applied.get("content", ""))
        return {**incoming, "position": incoming["position"] + shift}
    if applied.get("type") == "delete" and incoming.get("position", 0) > applied["position"]:
        shift = applied.get("length", 0)
        return {**incoming, "position": max(applied["position"], incoming["position"] - shift)}
    return incoming
```

Because the authoritative `content` is rebuilt inside `fn_apply_operation`, the server
is always the tiebreaker of record; clients converge by replaying the
`document_change_stream`.

---

## Client integration (React + Apollo)

The client subscribes over WebSocket and applies incoming operations.

```typescript
import { useMutation, useQuery, useSubscription, gql } from "@apollo/client";

const DOCUMENT = gql`
  query Document($id: ID!) {
    document(id: $id) {
      id
      title
      content
    }
  }
`;

const APPLY_OPERATION = gql`
  mutation ApplyOperation($input: ApplyOperationInput!) {
    applyOperation(input: $input) {
      ... on ChangeSuccess {
        change { id operation createdAt }
      }
      ... on ChangeError {
        message
        code
      }
    }
  }
`;

const CHANGE_STREAM = gql`
  subscription ChangeStream($documentId: ID!) {
    documentChangeStream(documentId: $documentId) {
      id
      userId
      operation
      vectorClock
      createdAt
    }
  }
`;

const PRESENCE_STREAM = gql`
  subscription PresenceStream($documentId: ID!) {
    presenceStream(documentId: $documentId) {
      userId
      cursorPosition
      color
    }
  }
`;

export function CollaborativeEditor({ documentId }: { documentId: string }) {
  const { data: doc } = useQuery(DOCUMENT, { variables: { id: documentId } });
  const { data: change } = useSubscription(CHANGE_STREAM, {
    variables: { documentId },
  });
  const { data: presence } = useSubscription(PRESENCE_STREAM, {
    variables: { documentId },
  });
  const [applyOperation] = useMutation(APPLY_OPERATION);

  // Apply remote changes streamed from other editors.
  // Send local edits via applyOperation(...) — the server's trigger NOTIFYs
  // every other subscriber on the "document_change" channel.

  return <Editor doc={doc} change={change} presence={presence} onEdit={applyOperation} />;
}
```

Send presence updates on a debounce so cursor movement doesn't flood the channel:

```typescript
const pushPresence = useDebouncedCallback((position: number) => {
  updatePresence({
    variables: { input: { documentId, cursorPosition: position } },
  });
}, 500);
```

---

## Performance and operational notes

- **One `LISTEN` connection per subscription stream.** `LISTEN/NOTIFY` requires a
  session-level connection, so keep a small dedicated pool for subscriptions and put a
  ceiling on concurrent streams (the `complexity` helper helps here).
- **Payloads carry only the `id`.** Re-reading the view keeps notifications tiny and
  under PostgreSQL's 8000-byte limit, and guarantees subscribers see committed data.
- **Debounce presence.** Send cursor updates at most every ~500ms.
- **Archive old changes.** Move `tb_document_change` rows older than your retention
  window to cold storage; the materialized `content` is the snapshot.
- **Snapshot periodically.** The `content` column is already a snapshot, so reconnecting
  clients only need to replay changes since their last seen `created_at`.

---

## See Also

- [Patterns overview](./README.md)
- [E-commerce workflows](./ecommerce-workflows.md) — mutations via `fn_` functions
- [Multi-tenant SaaS](./saas-multi-tenant.md) — document ownership and permissions via RLS
- [Subscriptions architecture](../architecture/realtime/subscriptions.md) — WebSocket transport internals
- [Core concepts](../foundation/02-core-concepts.md) — the `tb_`/`v_`/`fn_` CQRS model

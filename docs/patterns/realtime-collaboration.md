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
        'content_type',   d.content_type,
        'content',       d.content,
        'created_by',     d.created_by,
        'created_at',     d.created_at,
        'updated_at',     d.updated_at
    ) AS data
FROM tb_document d
WHERE d.deleted_at IS NULL;

CREATE VIEW v_document_change AS
SELECT
    c.id,
    d.id AS document_id,
    jsonb_build_object(
        'id',           c.id,
        'user_id',       c.user_id,
        'operation',    c.operation,
        'vector_clock',  c.vector_clock,
        'created_at',    c.created_at
    ) AS data
FROM tb_document_change c
JOIN tb_document d ON d.pk_document = c.fk_document;

CREATE VIEW v_presence AS
SELECT
    p.id,
    d.id AS document_id,
    jsonb_build_object(
        'user_id',         p.user_id,
        'cursor_position', p.cursor_position,
        'selection_start', p.selection_start,
        'selection_end',   p.selection_end,
        'color',          p.color,
        'last_activity',   p.last_activity
    ) AS data
FROM tb_presence p
JOIN tb_document d ON d.pk_document = p.fk_document;

CREATE VIEW v_comment AS
SELECT
    c.id,
    d.id AS document_id,
    jsonb_build_object(
        'id',         c.id,
        'user_id',     c.user_id,
        'content',    c.content,
        'position',   c.position,
        'resolved',   c.resolved,
        'created_at',  c.created_at
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
write logic and return a `mutation_response` describing success or failure. A class
mutation calls its function with its `context_params` first (here the user's id, from
the request context) and then the input as one `jsonb`. `mutation_response` and the
`mutation_*` helpers come from `migrations/trinity/005_add_mutation_response.sql`.
Because the writes go through `tb_document_change` / `tb_presence` / `tb_comment`, the
triggers above fire automatically — the mutation does not have to `NOTIFY` by hand.

```sql
CREATE OR REPLACE FUNCTION fn_apply_operation(p_user_id UUID, input JSONB)
RETURNS mutation_response AS $$
DECLARE
    v_pk_document BIGINT;
    v_change_id   UUID;
    v_operation   JSONB := input->'operation';
BEGIN
    SELECT pk_document INTO v_pk_document
    FROM tb_document
    WHERE id = (input->>'document_id')::uuid AND deleted_at IS NULL;

    IF v_pk_document IS NULL THEN
        RETURN mutation_not_found('Document', input->>'document_id');
    END IF;

    INSERT INTO tb_document_change (fk_document, user_id, operation, vector_clock)
    VALUES (v_pk_document, p_user_id, v_operation, input->'vector_clock')
    RETURNING id INTO v_change_id;

    -- Apply the operation to the materialized content (insert/delete on text).
    UPDATE tb_document
    SET content = CASE v_operation->>'type'
            WHEN 'insert' THEN
                left(content, (v_operation->>'position')::int)
                || (v_operation->>'content')
                || substr(content, (v_operation->>'position')::int + 1)
            WHEN 'delete' THEN
                left(content, (v_operation->>'position')::int)
                || substr(content,
                          (v_operation->>'position')::int
                          + (v_operation->>'length')::int + 1)
            ELSE content
        END,
        updated_at = now()
    WHERE pk_document = v_pk_document;

    RETURN mutation_created(
        'Operation applied',
        (SELECT data FROM v_document_change WHERE id = v_change_id),
        'DocumentChange'
    );
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_update_presence(p_user_id UUID, input JSONB)
RETURNS mutation_response AS $$
DECLARE
    v_pk_document BIGINT;
    v_presence_id UUID;
BEGIN
    SELECT pk_document INTO v_pk_document
    FROM tb_document
    WHERE id = (input->>'document_id')::uuid;
    IF v_pk_document IS NULL THEN
        RETURN mutation_not_found('Document', input->>'document_id');
    END IF;

    INSERT INTO tb_presence
        (fk_document, user_id, cursor_position, selection_start, selection_end, color)
    VALUES
        (v_pk_document, p_user_id, (input->>'cursor_position')::int,
         (input->>'selection_start')::int, (input->>'selection_end')::int,
         input->>'color')
    ON CONFLICT (fk_document, user_id) DO UPDATE
        SET cursor_position = EXCLUDED.cursor_position,
            selection_start = EXCLUDED.selection_start,
            selection_end   = EXCLUDED.selection_end,
            color           = EXCLUDED.color,
            last_activity   = now()
    RETURNING id INTO v_presence_id;

    RETURN mutation_success(
        'Presence updated',
        (SELECT data FROM v_presence WHERE id = v_presence_id),
        'Presence'
    );
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_add_comment(p_user_id UUID, input JSONB)
RETURNS mutation_response AS $$
DECLARE
    v_pk_document BIGINT;
    v_comment_id  UUID;
BEGIN
    SELECT pk_document INTO v_pk_document
    FROM tb_document
    WHERE id = (input->>'document_id')::uuid;
    IF v_pk_document IS NULL THEN
        RETURN mutation_not_found('Document', input->>'document_id');
    END IF;

    INSERT INTO tb_comment (fk_document, user_id, content, position)
    VALUES (v_pk_document, p_user_id, input->>'content', (input->>'position')::int)
    RETURNING id INTO v_comment_id;

    RETURN mutation_created(
        'Comment added',
        (SELECT data FROM v_comment WHERE id = v_comment_id),
        'Comment'
    );
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
class ApplyOperationSuccess:
    change: DocumentChange


@fraiseql.success
class UpdatePresenceSuccess:
    presence: Presence


@fraiseql.success
class AddCommentSuccess:
    comment: Comment


@fraiseql.error
class DocumentError:
    message: str
```

### Queries (reads)

```python
@fraiseql.query
async def document(info, id: ID) -> Document | None:
    db = info.context["db"]
    return await db.find_one("v_document", mandatory_filters={"id": id})


@fraiseql.query
async def document_changes(info, document_id: ID) -> list[DocumentChange]:
    """Changes for a document, oldest first (used to catch up on reconnect)."""
    db = info.context["db"]
    return await db.find("v_document_change", mandatory_filters={"document_id": document_id})


@fraiseql.query
async def comments(info, document_id: ID) -> list[Comment]:
    db = info.context["db"]
    return await db.find("v_comment", mandatory_filters={"document_id": document_id})
```

### Mutations (writes via `fn_`)

Each class mutation calls the function named by `function=`, passing
`info.context["user_id"]` first (`context_params`) and then the input as one
`jsonb`; the `mutation_response` comes back as the success or the error type.

```python
@fraiseql.mutation(
    function="fn_apply_operation",
    name="applyOperation",
    context_params={"user_id": "p_user_id"},
)
class ApplyOperation:
    input: ApplyOperationInput
    success: ApplyOperationSuccess
    error: DocumentError


@fraiseql.mutation(
    function="fn_update_presence",
    name="updatePresence",
    context_params={"user_id": "p_user_id"},
)
class UpdatePresence:
    input: UpdatePresenceInput
    success: UpdatePresenceSuccess
    error: DocumentError


@fraiseql.mutation(
    function="fn_add_comment",
    name="addComment",
    context_params={"user_id": "p_user_id"},
)
class AddComment:
    input: AddCommentInput
    success: AddCommentSuccess
    error: DocumentError
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
        changes = await db.find("v_document_change", mandatory_filters={"document_id": document_id})
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
        for presence in await db.find("v_presence", mandatory_filters={"document_id": document_id}):
            yield presence


@fraiseql.subscription
async def comment_stream(
    info, document_id: ID
) -> AsyncGenerator[Comment, None]:
    """Stream new comments as they are posted."""
    db = info.context["db"]
    pool = info.context["pool"]
    async for _ in _listen(pool, "comment", document_id):
        for comment in await db.find("v_comment", mandatory_filters={"document_id": document_id}):
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
        for change in await db.find("v_document_change", mandatory_filters={"document_id": document_id}):
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
    mutations=[ApplyOperation, UpdatePresence, AddComment],
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
      ... on ApplyOperationSuccess {
        change { id operation createdAt }
      }
      ... on DocumentError {
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

---
title: Subscriptions
description: Real-time GraphQL subscriptions in FraiseQL v1, served over WebSocket from async-generator resolvers.
keywords: ["subscriptions", "websocket", "graphql-ws", "realtime", "listen-notify"]
tags: ["documentation", "reference"]
---

# Subscriptions

## Table of Contents

1. [Overview](#1-overview)
2. [Defining a subscription](#2-defining-a-subscription)
3. [Driving updates](#3-driving-updates)
4. [Filtering, complexity, and lifecycle](#4-filtering-complexity-and-lifecycle)
5. [Authorization](#5-authorization)
6. [Client usage](#6-client-usage)
7. [Operational notes](#7-operational-notes)

---

## 1. Overview

FraiseQL v1 implements **standard GraphQL subscriptions** delivered over a
WebSocket connection. A subscription is an ordinary GraphQL operation whose
resolver is an **async generator**: every value it `yield`s becomes one
subscription payload sent to the client.

The model is intentionally simple:

- You write an `async def` resolver that `yield`s values (an *async generator*).
- FraiseQL streams whatever you yield to the subscribing client over WebSocket.
- The **event source is your generator**. It can be backed by PostgreSQL
  `LISTEN/NOTIFY`, by polling a view, or by any external stream — FraiseQL does
  not mandate one.

**Transport.** FraiseQL speaks GraphQL-over-WebSocket and supports both
protocols:

- `graphql-transport-ws` — the modern protocol (uses `next` / `complete`
  message types).
- `graphql-ws` — the legacy Apollo protocol (uses `data` message types).

The WebSocket handshake, sub-protocol negotiation, keep-alive, and per-operation
lifecycle are handled internally by `WebSocketConnection` and
`SubscriptionManager`; you do not implement protocol framing yourself.

There is **no event-log table, no change-data-capture polling runtime, and no
server-side event replay or buffering** in v1. A subscription lives entirely
inside its WebSocket connection. If the connection drops, the client reconnects
and resubscribes (see [Operational notes](#7-operational-notes)).

---

## 2. Defining a subscription

Decorate an async generator with `@fraiseql.subscription`. The resolver receives
`info` first (the GraphQL resolve info, with `info.context["db"]` available),
followed by your declared arguments. Annotate the return type as
`AsyncGenerator[T, None]`, where `T` is the GraphQL type you stream.

```python
import fraiseql
from collections.abc import AsyncGenerator
from uuid import UUID


@fraiseql.subscription
async def task_updates(info, project_id: UUID) -> AsyncGenerator[Task, None]:
    """Stream task changes for a single project."""
    async for task in watch_project_tasks(info, project_id):
        yield task
```

Key points:

- The function **must** be an async generator (`async def` + `yield`).
  Decorating a plain coroutine raises a `TypeError`.
- The yielded type is taken from the `AsyncGenerator[T, None]` annotation and
  becomes the subscription's GraphQL field type.
- Arguments are regular typed parameters (`project_id: UUID` above) and appear
  as GraphQL subscription arguments.
- The resolver runs once per subscribing client, with that client's arguments.

`watch_project_tasks` is *your* code — the next section shows two ways to
implement it.

---

## 3. Driving updates

FraiseQL streams whatever your generator yields. The two common ways to produce
those values from PostgreSQL are `LISTEN/NOTIFY` and polling.

### 3.1 PostgreSQL `LISTEN/NOTIFY`

This is the push-based approach with the lowest latency. A trigger on your write
table (`tb_*`) calls `NOTIFY` on a channel whenever a row changes, and the
generator wakes up on each notification, fetches the current row from the read
view (`v_*`), and yields it.

Database side — a trigger that announces changes:

```sql
CREATE OR REPLACE FUNCTION fn_notify_task_change()
RETURNS trigger AS $$
BEGIN
    -- Announce the affected task's public id on a per-project channel.
    PERFORM pg_notify(
        'task_changes',
        json_build_object(
            'project_id', NEW.fk_project,
            'task_id', NEW.id
        )::text
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_notify_task_change
    AFTER INSERT OR UPDATE ON tb_task
    FOR EACH ROW
    EXECUTE FUNCTION fn_notify_task_change();
```

Resolver side — listen on the channel and yield matching tasks:

```python
import json
import fraiseql
from collections.abc import AsyncGenerator
from uuid import UUID


@fraiseql.subscription
async def task_updates(info, project_id: UUID) -> AsyncGenerator[Task, None]:
    """Stream task changes for one project via LISTEN/NOTIFY."""
    db = info.context["db"]

    async for payload in db.listen("task_changes"):
        event = json.loads(payload)
        if event["project_id"] != str(project_id):
            continue  # not our project — skip

        task = await db.find_one("v_task", id=event["task_id"])
        if task is not None:
            yield task
```

The exact API for consuming notifications depends on how your connection/pool is
wired (for example, a `LISTEN` on a dedicated connection that exposes an async
iterator of notification payloads). The important pattern is: subscribe to a
channel, and on each notification re-read the affected row from your `v_`/`tv_`
view and `yield` it.

### 3.2 Polling a view

When you cannot add triggers, or the source is a periodically refreshed
projection (`tv_*`), poll a read view on an interval and yield only what changed.

```python
import asyncio
import fraiseql
from collections.abc import AsyncGenerator
from uuid import UUID


@fraiseql.subscription
async def task_updates(info, project_id: UUID) -> AsyncGenerator[Task, None]:
    """Stream task changes for one project by polling a view."""
    db = info.context["db"]
    seen: dict[str, str] = {}  # task id -> last-seen updated_at

    while True:
        tasks = await db.find("v_task", fk_project=project_id)
        for task in tasks:
            if seen.get(task.id) != task.updated_at:
                seen[task.id] = task.updated_at
                yield task
        await asyncio.sleep(1.0)
```

Polling trades latency and database load for simplicity. Prefer `LISTEN/NOTIFY`
when you control the schema and need low latency.

---

## 4. Filtering, complexity, and lifecycle

FraiseQL ships a few helper decorators that compose with `@fraiseql.subscription`.
Stack the helper **below** `@fraiseql.subscription`.

### 4.1 `subscription_filter` — gate a subscription

`subscription_filter(expression)` evaluates a small, sandboxed boolean
expression before the stream runs and refuses the subscription if it is false.
The expression can reference the connecting `user`, the subscription arguments,
and (when applicable) a loaded `project`/`resource`.

```python
import fraiseql
from fraiseql.subscriptions import subscription_filter
from collections.abc import AsyncGenerator
from uuid import UUID


@fraiseql.subscription
@subscription_filter("project.is_public or user.has_access")
async def project_updates(info, project_id: UUID) -> AsyncGenerator[Task, None]:
    async for task in watch_project_tasks(info, project_id):
        yield task
```

Only a restricted set of names and attributes is allowed in the expression
(boolean operators, comparisons, and attributes such as `is_public`,
`has_access`, `is_owner`, `role`, `permissions`, `id`, `status`). Anything else
is rejected, so the filter cannot run arbitrary code.

### 4.2 `complexity` — bound cost and depth

`complexity(score=..., max_depth=...)` rejects subscriptions whose computed cost
or selection-set depth exceeds the configured limits, protecting the server from
expensive live queries.

```python
import fraiseql
from fraiseql.subscriptions import complexity
from collections.abc import AsyncGenerator


@fraiseql.subscription
@complexity(score=100, max_depth=5)
async def expensive_feed(info) -> AsyncGenerator[Event, None]:
    async for event in watch_events(info):
        yield event
```

### 4.3 `with_lifecycle` — setup / teardown hooks

`with_lifecycle(on_start=..., on_event=..., on_complete=...)` runs hooks around
the stream: `on_start` when the client subscribes, `on_event` for each yielded
value (it can transform the value), and `on_complete` when the subscription
ends — including on disconnect — making it the right place to release resources.

```python
import fraiseql
from fraiseql.subscriptions import with_lifecycle
from collections.abc import AsyncGenerator


@fraiseql.subscription
@with_lifecycle(
    on_start=open_resources,
    on_event=annotate_event,
    on_complete=close_resources,
)
async def audited_feed(info) -> AsyncGenerator[Event, None]:
    async for event in watch_events(info):
        yield event
```

### 4.4 `cache` — reuse recent results

`cache(ttl=...)` memoizes the most recent yielded value for a short window
(default 5 seconds), so identical subscriptions sharing a cache do not all
recompute the same result.

```python
import fraiseql
from fraiseql.subscriptions import cache
from collections.abc import AsyncGenerator


@fraiseql.subscription
@cache(ttl=10)  # reuse results for 10 seconds
async def live_stats(info) -> AsyncGenerator[Stats, None]:
    async for stats in compute_stats(info):
        yield stats
```

---

## 5. Authorization

Pass a per-operation `authorizer` to the decorator to control who may open a
subscription:

```python
import fraiseql
from collections.abc import AsyncGenerator
from uuid import UUID


@fraiseql.subscription(authorizer=project_member_authorizer)
async def task_updates(info, project_id: UUID) -> AsyncGenerator[Task, None]:
    async for task in watch_project_tasks(info, project_id):
        yield task
```

- The `authorizer` mirrors `@fraiseql.query` / `@fraiseql.mutation`: it takes
  precedence over the global default authorizer **for this subscription only**.
- Authorization is evaluated **once, at subscribe time** (when the client sends
  the `subscribe` message), not on every yielded value. If it fails, the
  subscription is rejected and no stream is opened.
- When no `authorizer` is supplied, the registry's default authorizer applies.

`subscription_filter` (see above) is complementary: use the `authorizer` for the
authentication/authorization decision, and `subscription_filter` for declarative
access gates expressed inline.

---

## 6. Client usage

Connect over WebSocket with a `graphql-transport-ws` client (the
[`graphql-ws`](https://github.com/enisdenjo/graphql-ws) library is the common
choice; the legacy `graphql-ws` Apollo protocol is also accepted).

```javascript
import { createClient } from 'graphql-ws';

const client = createClient({
  url: 'ws://localhost:8000/graphql',
  connectionParams: {
    Authorization: `Bearer ${token}`,
  },
});

const subscription = `
  subscription TaskUpdates($projectId: UUID!) {
    taskUpdates(projectId: $projectId) {
      id
      title
      status
      updatedAt
    }
  }
`;

const unsubscribe = client.subscribe(
  { query: subscription, variables: { projectId: '...' } },
  {
    next: (payload) => console.log('task changed', payload.data.taskUpdates),
    error: (err) => console.error('subscription error', err),
    complete: () => console.log('subscription complete'),
  },
);

// Later, to stop receiving updates:
// unsubscribe();
```

The handshake (`connection_init` / `connection_ack`), the `subscribe` /
`next` / `complete` message flow, and sub-protocol negotiation are handled by the
client library on one side and by FraiseQL's `WebSocketConnection` /
`SubscriptionManager` on the other.

---

## 7. Operational notes

- **Per-connection.** Each subscription is bound to a single WebSocket
  connection and runs its own async generator. There is no shared server-side
  fan-out buffer and no cross-process coordination.
- **No server-side replay.** FraiseQL does not persist a stream of past events.
  On disconnect, restart, or crash, the client simply **reconnects and
  resubscribes**; it will receive updates from that point forward. If your
  application needs gap-free delivery, make the generator re-read current state
  on each (re)subscribe — for example, emit the latest snapshot from a `v_`/`tv_`
  view first, then stream subsequent changes.
- **Resource cleanup.** When a client disconnects, FraiseQL stops iterating the
  generator. Use `with_lifecycle(on_complete=...)` (or a `finally` block in your
  generator) to release listeners, cursors, or background tasks.
- **Latency vs. load.** `LISTEN/NOTIFY` gives near-immediate delivery; polling
  trades latency for simplicity. Choose per subscription.
- **Authentication.** Authorization is enforced at subscribe time via the
  per-operation `authorizer` (see [Authorization](#5-authorization)).

---

## Related

- [Integration patterns](../integration/integration-patterns.md) — connecting
  FraiseQL to other systems.
- [Consistency model](../reliability/consistency-model.md) — read/write
  consistency guarantees.
- [Failure modes and recovery](../reliability/failure-modes-and-recovery.md) —
  reconnection and degradation behavior.
- [Core concepts](../../foundation/02-core-concepts.md) — types, queries, and
  the CQRS read/write model.
- [First hour](../../getting-started/first-hour.md) — getting a FraiseQL app
  running.

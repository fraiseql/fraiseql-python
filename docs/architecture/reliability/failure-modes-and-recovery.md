---
title: Failure Modes and Recovery
description: How a FraiseQL v1 deployment fails and recovers, covering the FastAPI process, the PostgreSQL connection pool, query execution, caching, and authentication.
keywords: ["reliability", "recovery", "postgresql", "connection pool", "operations"]
tags: ["documentation", "reference"]
---

# Failure Modes and Recovery

**Audience:** Operations engineers, SREs, infrastructure architects, security teams

---

## 1. Overview

This document describes how a FraiseQL v1 deployment fails and recovers. FraiseQL v1
is a Python runtime GraphQL framework that runs as a FastAPI/ASGI application in front
of a single PostgreSQL database. Understanding the failure modes of each part — the
application process, the database connection pool, query execution, caching, and
authentication — helps operators design resilient deployments.

A note on scope: FraiseQL itself is a single application process. It does **not**
provide built-in multi-instance coordination, automatic failover, or read-replica
routing. Those are deployment and PostgreSQL concerns. Where this document discusses
clustering, load balancing, or failover, treat it as **optional deployment guidance**,
not a feature FraiseQL manages on your behalf.

### 1.1 Design Philosophy

> **Fail fast, recover gracefully.**

When FraiseQL encounters a failure, it:

1. **Detects** the failure as early as possible
2. **Stops processing** the affected request (no partial or corrupt state)
3. **Reports** a structured error to the client
4. **Recovers** automatically where the underlying mechanism allows (for example,
   reconnecting a dropped database connection)
5. **Surfaces** the error in logs and metrics so operations can intervene if needed

### 1.2 Recovery Time Objectives (RTO)

The figures below are **deployment-dependent guidance**, not guarantees made by
FraiseQL. Actual recovery time depends on your container orchestrator, load balancer,
PostgreSQL configuration, and network. Measure them in your own environment.

| Component | Typical RTO | Recovery mechanism |
|-----------|-------------|--------------------|
| **Single FraiseQL process** | seconds to a minute | Orchestrator/supervisor restarts the process |
| **Database connection** | seconds | Pool reconnects on next use |
| **Connection pool exhaustion** | depends on query duration | Waiting requests proceed as connections free up |
| **Cache backend** | seconds | Bypass cache, read from database |
| **Entire database** | minutes (operational) | DBA restart / restore / replica promotion |
| **Authentication provider** | minutes (operational) | Provider recovery |

### 1.3 Recovery Point Objectives (RPO)

| Component | RPO | Data loss |
|-----------|-----|-----------|
| **Committed mutations** | 0 (durable in PostgreSQL) | None |
| **In-flight mutations** | Transaction boundary | None (atomic — commits or rolls back) |
| **Cache entries** | Variable (TTL) | None — query re-executes against the database |
| **Subscription events** | Per connection | Events that occur while a client is disconnected are not delivered to that client unless your view/source captures them |

---

## 2. Failure Modes by Component

### 2.1 FraiseQL Process Failures

#### 2.1.1 Application Crash (Process Dies)

**When:** Unhandled exception at startup, OOM kill, `SIGKILL`, host failure.

**Client impact:**

- All in-flight requests on that process fail.
- Clients see a connection reset, or a 502/503 from a load balancer.

**Detection:** A health check (or the load balancer's TCP probe) fails because the
process is no longer accepting connections.

**Recovery:**

- **Automatic (if configured):** Your supervisor restarts it — systemd restarts the
  service, or Kubernetes restarts the pod.
- **Data impact:** None. PostgreSQL holds all durable state; an in-flight mutation
  either committed before the crash or was rolled back by PostgreSQL when the
  connection dropped.

A single-process deployment is unavailable for the duration of the restart. If you run
multiple FraiseQL processes behind a load balancer (optional deployment topology),
traffic continues on the surviving processes while the failed one restarts. FraiseQL
does not coordinate this — your load balancer does.

#### 2.1.2 Memory Exhaustion (OOM)

**When:** A query returns an unexpectedly large result set, a memory leak accumulates,
or the cache grows unbounded.

**Client impact:** Requests slow down, then the process is OOM-killed and behaves as in
2.1.1.

**Detection:** Memory usage trends toward the container/VM limit.

**Recovery:**

- **Automatic:** The OOM-killed process is restarted by your supervisor.
- **Manual:** Reduce result-set sizes (paginate, add filters), bound cache size, raise
  the memory limit.
- **Prevention:** Set container/VM memory limits, paginate large reads, and put TTL and
  size bounds on any cache.

#### 2.1.3 CPU Saturation

**When:** High request volume or expensive queries saturate available CPU.

**Client impact:** Latency rises; under sustained saturation, requests may time out.

**Detection:** CPU usage approaches 100%; p99 latency climbs.

**Recovery:**

- **Manual:** Run more FraiseQL processes (horizontal scale-out behind a load
  balancer), or optimize the hot queries.
- **Prevention:** Rate limiting, statement timeouts, and bounding query complexity.

#### 2.1.4 Resource Leak (Connections / Tasks)

**When:** Connections or background tasks (for example, abandoned WebSocket
subscriptions) accumulate over time.

**Client impact:** Memory and file-descriptor usage grow slowly, eventually leading to
an OOM crash (2.1.2) or refused connections.

**Detection:** Steadily rising open-connection or task counts over hours or days.

**Recovery:**

- **Manual:** Restart the affected process.
- **Prevention:** Bound the connection pool, set keep-alive/idle timeouts on WebSocket
  subscriptions, and monitor connection and task counts.

---

### 2.2 Database Connection Failures

FraiseQL uses `psycopg_pool.AsyncConnectionPool` for PostgreSQL connections. The pool
manages a bounded set of connections, hands them to requests, and reconnects when a
connection is found to be broken.

#### 2.2.1 Connection Timeout

**When:** PostgreSQL is unreachable — network partition, DNS failure, the server is not
yet up.

**Client impact:**

- The query fails after the pool's connection timeout elapses.
- The client receives an error; the operation is retryable.

**Detection:** The connection attempt fails or times out.

**Recovery:**

- **Automatic:** The next request attempts a fresh connection. A client that retries
  with backoff will succeed once PostgreSQL is reachable again.
- **Client guidance:** Retry with exponential backoff.

**Connection pool state:** When a connection attempt fails, the pool discards the
broken connection rather than handing it out. The next acquisition opens a new one.

#### 2.2.2 Connection Pool Exhaustion

**When:** More concurrent queries arrive than the pool has connections, often because
slow queries hold connections longer than expected.

**Client impact:**

- A query that needs a connection waits until one is free.
- If none frees within the pool's wait timeout, the request fails (retryable with
  backoff).

**Detection:** Active connections sit at the pool maximum; requests spend time waiting
to acquire a connection.

**Recovery:**

- **Automatic:** Waiting requests proceed as in-flight queries finish and return their
  connections to the pool.
- **Manual:** Raise the pool maximum (within PostgreSQL's `max_connections`), speed up
  slow queries, or run more FraiseQL processes.

**Pool sizing considerations:**

```text
min_size:        minimum connections kept open
max_size:        maximum connections the pool will open
acquisition wait: how long a request waits for a free connection before failing
```

The product of `max_size` across all FraiseQL processes must stay within PostgreSQL's
`max_connections`. Oversizing the pool moves the bottleneck onto the database; consider
a server-side pooler such as PgBouncer for high process counts.

#### 2.2.3 Connection Closed by Database

**When:** PostgreSQL closes a connection mid-use — server restart, idle-connection
reaping, an administrative `pg_terminate_backend`, or a transient network drop.

**Client impact:**

- The in-flight query fails with a connection error (retryable).
- A read can be retried on a fresh connection. A mutation that had not committed is
  rolled back by PostgreSQL; the client must re-issue it.

**Detection:** A network/connection error occurs while reading the response; the pool
marks the connection broken.

**Recovery:**

- **Automatic:** The pool opens a replacement connection on the next acquisition.
- **Client guidance:** Retry the operation. For mutations, ensure the operation is
  idempotent or check whether it committed before retrying.

#### 2.2.4 Database Restart

**When:** Planned maintenance, a crash, or a failover.

**Client impact:**

- During the restart, every connection fails and new connections are refused.
- Queries error until PostgreSQL is back and the pool reconnects.

**Detection:** Connection attempts fail; database health checks fail.

**Recovery:**

- **Automatic (from FraiseQL's side):** Once PostgreSQL accepts connections again, the
  pool opens fresh connections and queries succeed.
- **RTO:** From a few seconds (clean restart) to several minutes (crash recovery or
  failover) — this is governed by PostgreSQL, not FraiseQL.
- **Data impact:** None for committed writes; PostgreSQL persists them durably.

---

### 2.3 Database Execution Failures

These are errors PostgreSQL returns for a query or function call. FraiseQL surfaces them
as structured GraphQL errors. See [Error Handling Model](./error-handling-model.md) for
how errors are shaped and classified.

#### 2.3.1 Statement / Query Timeout

**When:** A slow query, a missing index, or resource contention causes execution to
exceed the configured `statement_timeout`.

**Client impact:**

- PostgreSQL cancels the statement; the client receives a timeout error (retryable
  after narrowing the query).

**Detection:** Execution exceeds the timeout; p99 query time breaches your SLO.

**Recovery:**

- **Automatic:** The statement is cancelled and the error returned. No data is written
  by a cancelled read.
- **Client guidance:** Retry with a tighter filter or smaller `LIMIT`.
- **Manual:** Add an index, optimize the underlying `v_`/`tv_` view, or raise the
  timeout.

Set a `statement_timeout` (per-session or globally) so a runaway query cannot hold a
connection indefinitely and starve the pool.

#### 2.3.2 Deadlock

**When:** Two concurrent transactions acquire locks in conflicting orders.

**Client impact:**

- PostgreSQL detects the cycle, cancels one transaction as the victim, and returns a
  serialization/deadlock error (retryable).

**Detection:** PostgreSQL's deadlock detector fires; the deadlock count rises in
metrics.

**Recovery:**

- **Automatic:** The victim transaction is rolled back; the winner commits.
- **Client guidance:** Retry the victim transaction. Because writes go through `fn_`
  PostgreSQL functions, keep those functions short and acquire locks in a consistent
  order to minimize deadlocks.

**Deadlock scenario:**

```sql
-- Transaction A
UPDATE tb_user  SET balance = balance - 100 WHERE id = '...';
UPDATE tb_order SET total   = total   + 100 WHERE fk_user = '...';

-- Transaction B (opposite lock order)
UPDATE tb_order SET total   = total   -  50 WHERE fk_user = '...';
UPDATE tb_user  SET balance = balance +  50 WHERE id = '...';
```

PostgreSQL detects the circular wait, cancels one transaction, and that transaction
retries and succeeds.

#### 2.3.3 Constraint Violation

**When:** A unique, foreign-key, or check constraint rejects a write inside a `fn_`
function.

**Client impact:**

- The write is rejected; the mutation returns an error result. Not retryable without
  changing the data.

**Detection:** PostgreSQL rejects the write; the `fn_` function returns a failure
payload that maps to your `@fraiseql.error` type.

**Recovery:**

- **Client guidance:** Correct the input (use a different email, a valid foreign key,
  etc.) and re-submit.

**No automatic recovery:**

```text
mutation { createUser(input: { email: "taken@example.com" }) { ... } }
→ Unique constraint violation on email
→ Client should: use a different email
→ Retrying the same input fails identically
```

#### 2.3.4 Out of Memory (Database)

**When:** A query (large sort, hash join, or aggregate) needs more memory than
PostgreSQL has available.

**Client impact:**

- The query fails; the client receives an error (retryable after reducing query size).

**Detection:** PostgreSQL memory pressure; the statement fails before exhausting the
host.

**Recovery:**

- **Client guidance:** Paginate, add a `WHERE` filter, or simplify joins.
- **Manual:** Tune `work_mem`, optimize the view, or add memory to the database host.

#### 2.3.5 Disk Full

**When:** The database volume fills and PostgreSQL can no longer write.

**Client impact:**

- Writes fail with an error; reads generally continue to work.

**Detection:** Disk usage crosses your alert threshold; PostgreSQL rejects writes.

**Recovery:**

- **Manual:** A DBA frees space (rotate WAL/logs, prune data, grow the volume).
- **RTO:** Operational — minutes, depending on the fix.
- **Data impact:** Writes fail until space is available; committed data is intact.

---

### 2.4 Cache Failures

Caching in FraiseQL is an optional optimization. When a cache backend is unavailable or
returns nothing useful, FraiseQL falls back to executing the query against PostgreSQL —
correctness is preserved, only latency changes.

#### 2.4.1 Cache Backend Down

**When:** An external cache (for example, Redis) is unreachable.

**Client impact:**

- Reads miss the cache and execute against the database. Higher latency, but correct
  results.

**Detection:** Cache connection failures; the backend stops responding.

**Recovery:**

- **Automatic:** Requests bypass the cache and read from the database. When the cache
  returns, it repopulates on subsequent reads.
- **Data impact:** None — the database is the source of truth.

**Graceful degradation:**

```text
Cache available:    fast path (cache hit)
Cache unavailable:  slower path (database read), results still correct
Cache recovers:     cache warms again on subsequent reads
```

#### 2.4.2 Stale or Invalid Cache Entry

**When:** A cached entry no longer reflects the committed database state, or fails a
validation check.

**Client impact:**

- A brief stale read is possible until the entry is invalidated or expires.

**Detection:** TTL expiry, explicit invalidation on the relevant write, or a validation
mismatch.

**Recovery:**

- **Automatic:** Invalidate the entry and fetch fresh data from the database.

See [Consistency Model](./consistency-model.md) for the guarantees and the windows in
which a stale read can occur.

#### 2.4.3 Cache At Capacity

**When:** The cache reaches its memory limit.

**Client impact:**

- Entries are evicted (typically LRU), producing more misses and slightly slower
  queries. No errors.

**Recovery:**

- **Automatic:** Eviction keeps the cache within bounds.
- **Manual:** Raise the cache size limit or tighten TTLs.

---

### 2.5 Authentication Failures

#### 2.5.1 Auth Provider Unreachable

**When:** An external identity provider (OIDC issuer, Auth0, corporate SSO) is down.

**Client impact:** Depends on the token model:

**Self-contained JWT (signature verified with a cached public key):**

```text
The provider being unreachable does not block validation; the cached
public key (JWKS) still verifies signatures locally. Impact: minimal,
until the signing keys rotate and the cached JWKS becomes stale.
```

**Tokens requiring a live call to the provider (introspection):**

```text
Validation makes an HTTP call to the provider, which fails.
Policy decides the behaviour: deny new requests (fail closed,
recommended) or briefly accept on a short-lived cache (fail open).
Impact lasts until the provider recovers.
```

**Recommendation:** Prefer self-contained JWTs with cached JWKS for resilience against
provider outages.

#### 2.5.2 Token Expiry During Execution

**When:** A long-running request's token expires after authorization but before the
request completes.

**Client impact:** The request completes normally — authorization is evaluated at the
start of the request, not mid-execution.

**Recovery:** None needed for the in-flight request. The client must refresh its token
before the next request.

#### 2.5.3 Invalid Token

**When:** A token is malformed, expired, or its signature does not verify.

**Client impact:** The request is rejected with `401 Unauthorized`. Not retryable
without re-authenticating.

**Recovery:** The client re-authenticates to obtain a fresh token.

#### 2.5.4 Stale Authorization Context

**When:** A user's roles or permissions change after their token was issued.

**Client impact:** Until the token is refreshed, authorization is evaluated against the
permissions baked into the (still-valid) token, which may allow or deny incorrectly.

**Recovery:**

- Shorten token lifetimes so changes take effect sooner.
- Revoke and re-issue tokens for an immediate change.

#### 2.5.5 Row-Level Security (RLS) Denial

**When:** A PostgreSQL row-level security policy prevents access to rows the caller is
not entitled to.

**Client impact:** The query returns no rows for the disallowed data (or an explicit
authorization error). This is an intentional security boundary, not a fault. Not
retryable — the caller lacks permission.

**Recovery:** None automatic. A privileged operator must grant access if appropriate.

---

## 3. Cascading Failures

### 3.1 Database Down → Reads and Writes Fail

```text
PostgreSQL becomes unavailable
→ Queries and mutations fail (no connection)
→ A warm cache may still serve some reads until entries expire
→ RTO is governed by your PostgreSQL recovery/failover, not FraiseQL
```

### 3.2 Cache Down → Database Load Increases

```text
Cache backend fails
→ All reads bypass the cache and hit the database directly
→ Database CPU and I/O rise
→ Without statement timeouts and pool bounds, slow queries can pile up
Mitigation: keep statement_timeout and a bounded pool so the database
degrades gracefully rather than collapsing.
```

### 3.3 Auth Provider Down → New Sessions Blocked

```text
Provider becomes unreachable
→ Self-contained JWTs continue to validate against cached keys
→ Flows that need a live provider call (login, introspection) fail
→ Existing valid tokens keep working until they expire
```

---

## 4. Failure Recovery Procedures

### 4.1 Process Crash

**Automatic (with a supervisor configured):**

```text
1. The FraiseQL process crashes.
2. systemd / Kubernetes detects the unhealthy process.
3. It starts a replacement process.
4. The replacement re-establishes its PostgreSQL pool on first use.
5. Traffic resumes (immediately on surviving processes if you run several
   behind a load balancer; after restart for a single-process deployment).

Data loss: none (PostgreSQL holds durable state).
```

**Manual verification:**

```bash
# Inspect logs for the crash cause
kubectl logs <pod-name>      # or: journalctl -u <service>

# If OOM:           raise the memory limit or bound result sizes / cache
# If disk pressure: clear logs / temporary files
# If a bug:         capture the traceback and file an issue
```

### 4.2 Database Connection Lost (Transient)

**Automatic:**

```text
1. A query fails with a connection error.
2. The pool discards the broken connection.
3. The pool opens a fresh connection on the next acquisition.
4. The retried query succeeds.
5. Clients see a brief latency spike.

Data loss: none.
```

### 4.3 Database Unavailable (Operational Recovery)

This is a PostgreSQL operations procedure; FraiseQL simply reconnects once the database
is healthy.

```text
1. Monitoring detects PostgreSQL is not responding.
2. Page the on-call DBA.
3. Investigate database and network logs.
4. Recover:
   a. Crashed server   → restart PostgreSQL.
   b. Network issue    → restore connectivity.
   c. HA setup         → promote a replica (your HA tooling, not FraiseQL).
5. Verify with test queries; watch replication lag if applicable.
6. Ramp traffic back up and monitor.

Data loss: none for committed writes (durable in PostgreSQL).
```

Multi-region, replica promotion, and DNS failover are deployment topologies you build
and operate around FraiseQL; FraiseQL does not perform them. RPO in those scenarios
depends on your replication configuration.

---

## 5. Resilience Design Patterns

These are patterns to apply in your deployment and client code. FraiseQL does not
implement them for you unless noted.

### 5.1 Retry with Exponential Backoff

For transient failures (connection drops, deadlocks, statement timeouts), clients
should retry with increasing, jittered delays:

```text
Attempt 1: immediate
Attempt 2: ~1s  + jitter
Attempt 3: ~2s  + jitter
Attempt 4: ~4s  + jitter
Attempt 5: ~8s  + jitter

Jitter avoids a thundering herd; bound the total wait so clients fail in
reasonable time. Only retry operations that are safe to repeat (idempotent
reads, or mutations you can deduplicate).
```

### 5.2 Bounded Pools and Timeouts

Keep failures contained:

```text
- Bound the connection pool (max_size) so a spike cannot open unbounded
  connections against PostgreSQL.
- Set statement_timeout so a runaway query cannot hold a connection forever.
- Set request/keep-alive timeouts so abandoned clients release resources.
```

### 5.3 Graceful Degradation

Prefer reduced functionality over a hard outage:

```text
- When the cache is down, serve from the database (slower, still correct).
- Under heavy load, shed expensive operations before essential reads.
- Return clear, retryable errors rather than hanging the client.
```

---

## 6. Failure Testing

Validate these failure modes against a real deployment. FraiseQL's repository includes
chaos and regression tests under `tests/chaos/` and `tests/regression/`; complement
them with infrastructure-level fault injection in your environment:

```text
- Kill a FraiseQL process              → confirm the supervisor restarts it,
                                          and (if clustered) traffic continues.
- Restart PostgreSQL                    → confirm the pool reconnects and
                                          queries resume; no committed-write loss.
- Add latency to the database           → confirm statement_timeout fires and
                                          clients receive retryable errors.
- Take the cache offline                → confirm reads fall back to the database.
- Saturate the connection pool          → confirm requests wait, then fail with a
                                          retryable error rather than hanging forever.
```

**Acceptance criteria after an injected failure:**

```text
PASS if:
  - No data corruption.
  - No loss of committed writes.
  - Requests eventually succeed, or fail with a clear, retryable error.
  - The system recovers once the fault is removed.
  - Alerts fire appropriately.

FAIL if:
  - Data is corrupted or committed writes are lost.
  - The process hangs instead of returning an error.
  - Recovery does not happen after the fault is removed.
```

---

## 7. SLO and Error Budgets

Service-level objectives are properties of your deployment, not guarantees FraiseQL
makes. Define them against the behaviour you can observe and control.

### 7.1 Availability SLO (example)

```text
Target:      99.9% availability over a calendar month
Definition:  fraction of requests answered successfully (or with a clean,
             retryable error) within the latency SLO
Budget:      99.9% of ~30 days ≈ 43 minutes of allowed downtime per month
```

### 7.2 Error Budget (example)

```text
Monthly budget (99.9%):  ~43 minutes
Each incident consumes part of the budget; when it is exhausted, prioritise
reliability work over new features until the budget recovers.
```

Tie SLOs to your monitoring. See
[Performance Characteristics](../../foundation/12-performance-characteristics.md) for
latency expectations to base your SLOs on.

---

## 8. Subscriptions and Failure

FraiseQL subscriptions are delivered over a WebSocket and are scoped to a single
connection on a single process. They are **not** backed by a distributed event system,
and FraiseQL does not coordinate subscription state across processes.

**WebSocket connection lost** — network interruption, client disconnect, or the
process the connection lived on restarting:

- That connection's active subscriptions end. Any in-flight delivery stops.
- The client should reconnect and resubscribe. On a multi-process deployment the
  reconnect may land on a different process; that is transparent to the client because
  each subscription is independent and re-established from scratch.
- Events that occur while the client is disconnected are not replayed unless your
  underlying source captures them (for example, a change-log table the subscription
  reads from on reconnect). FraiseQL does not buffer per-client event history on your
  behalf.

**Process restart** drops every subscription on that process; affected clients
reconnect and resubscribe. There is no automatic migration of subscription state
between processes.

See [Subscriptions](../realtime/subscriptions.md) for the subscription model and
[Versioning Strategy](./versioning-strategy.md) for how schema changes affect
long-lived clients.

---

## Summary

A FraiseQL v1 deployment fails safely:

- **Durable writes:** committed mutations survive process and database restarts;
  in-flight mutations are atomic — they commit or roll back.
- **Self-healing connections:** the `psycopg_pool` connection pool discards broken
  connections and reconnects automatically.
- **Graceful cache fallback:** an unavailable cache costs latency, not correctness.
- **Clear errors:** failures surface as structured, classifiable errors so clients know
  whether to retry.

What FraiseQL does **not** do for you: it does not provide automatic failover,
read-replica routing, multi-instance coordination, or distributed subscriptions.
Clustering, load balancing, PostgreSQL high availability, and multi-region failover are
deployment topologies you operate around FraiseQL.

**Golden rule:** FraiseQL fails safely, reconnects to PostgreSQL automatically, and
surfaces enough detail to diagnose what happened — but durability, availability, and
failover beyond a single process are properties of how you deploy it.

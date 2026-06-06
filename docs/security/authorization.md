# Operation Authorization

FraiseQL provides a **first-class Policy Enforcement Point (PEP)** for operation-level
authorization. The framework *enforces*; the *decision* is delegated to an application-supplied
`Authorizer`. This replaces the fragile pattern of reaching into the private
`SchemaRegistry._mutations` registry to bolt on a security boundary.

> **Authentication vs. authorization.** Authentication (who the principal *is*) stays with
> your `context_getter` / auth provider. This feature is about authorization (what an operation
> is *allowed* to do). The authorizer is principal-agnostic: it reads everything it needs from
> `context`, which your `context_getter` already populates.

## Concepts

### `AuthorizationDecision`

An immutable value describing the outcome of a check:

```python
from fraiseql import AuthorizationDecision

AuthorizationDecision.allow()                                  # allow
AuthorizationDecision.allow(filters={"tenant_id": "t1"})       # allow + row scoping
AuthorizationDecision.deny()                                   # deny, code "FORBIDDEN"
AuthorizationDecision.deny(code="NO_MUTATIONS", message="read-only principal")
```

Fields: `allowed: bool`, `code: str | None`, `message: str | None`, `filters: dict | None`.

### `Authorizer`

A structural protocol — any object with an `authorize_operation` method qualifies:

```python
from fraiseql import Authorizer, AuthorizationDecision

class TenantAuthorizer:
    async def authorize_operation(
        self, *, context, operation_type, operation_name, arguments
    ) -> AuthorizationDecision | bool:
        user = context.get("user")
        if user is None:
            return AuthorizationDecision.deny(message="authentication required")
        # Scope every read to the principal's tenant.
        if operation_type == "query":
            return AuthorizationDecision.allow(filters={"tenant_id": user["tenant_id"]})
        return AuthorizationDecision.allow()
```

- The return value may be a plain `bool` (`True` → allow, `False` → deny) or an
  `AuthorizationDecision`.
- The method may be **sync or async** — the framework awaits awaitables.
- `operation_type` is `"query"`, `"mutation"`, or `"subscription"`; `operation_name` is the
  GraphQL field name; `arguments` are the (Python-named) operation arguments.

## Wiring it up

Pass `authorizer=` to the supported entry point. It gates every root query, mutation, and
subscription, the three resolver-bypass paths, and survives schema hot-reload:

```python
from fraiseql import create_fraiseql_app

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[...],
    queries=[...],
    mutations=[...],
    authorizer=TenantAuthorizer(),   # global default
)
```

With **no** `authorizer=`, behavior is byte-for-byte unchanged.

### Per-operation override

`@query` and `@mutation` accept a per-operation `authorizer=` that takes precedence over the
global default for that operation only:

```python
@fraiseql.query(authorizer=AdminOnly())
async def audit_log(info) -> list[AuditEntry]:
    ...
```

> Per-operation overrides apply on the **resolver path** only. The resolver-bypass paths
> (TurboRouter, `/graphql/rust`, APQ cache hits) consult the **global default** authorizer.

## Fail-closed semantics

Enforcement is fail-closed by construction, in a single helper every path shares:

- An authorizer that **raises** denies the operation — it never falls through to "allow".
- The raw exception is logged but **never** surfaced to the client (no internal leakage).
- A deny becomes a `GraphQLError` with `extensions={"code": ...}` and a safe message.
- An authorizer may raise its own `GraphQLError` to surface a custom error unchanged.

## Filter injection (row scoping)

A query authorizer can return `filters` to scope rows. They are AND-merged into the repository's
existing `mandatory_filters` SQL primitive — column names are validated and values are always
parameterized, so there is no injection surface.

```python
return AuthorizationDecision.allow(filters={"tenant_id": user["tenant_id"]})
```

Mechanism: `mandatory_filters` is a repository-method kwarg consumed in a *different call frame*
than the resolver (your `@query` function sits in between), so the filter cannot ride resolver
kwargs. Instead it rides the repository **context**, keyed by root field, and every read method
(`find` / `find_one` / `count` / aggregates) merges it. If a caller's `mandatory_filters` and the
authorization filters pin the **same column**, the conflict is rejected loudly rather than
silently merged.

## ⚠️ Bypass paths and their row-scoping caveat

Three execution paths reach the database (or hand off to Rust) **without invoking a Python
resolver**. All three are gated with the same fail-closed helper, but **per-row filter injection
is impossible** on them:

| Path | Gate | Row scoping |
|------|------|-------------|
| **TurboRouter / persisted queries** | enforced before the cached SQL template runs | session variables + database **RLS** |
| **`POST /graphql/rust`** (opt-in) | enforced before the Rust pipeline is called | session variables + database **RLS** |
| **APQ cached passthrough** | enforced before the cached response is served | a returned filter **bypasses the cache** and falls through to normal resolver execution (which applies the filter) |

If an authorizer returns `filters` on the turbo or rust path, the filter is **logged, not
silently dropped** — rely on session variables + RLS for row scoping there. For APQ, a returned
filter is honored by skipping the (unscoped) cache entry. `filters` are also ignored (with a
warning) on mutations and at field granularity.

> **`POST /graphql/rust` is opt-in (issue #365).** It is **off by default** — a route that
> bypasses Python resolvers entirely should not exist unless the app asks for it. Enable it
> with `enable_rust_endpoint=True` on `FraiseQLConfig` (or `FRAISEQL_ENABLE_RUST_ENDPOINT=true`).
> When disabled the route is simply not mounted (a request 404s). When enabled it is still
> authorization-gated as above; row scoping relies on session variables + RLS.
>
> **Behavior change:** apps that were calling `/graphql/rust` before this release must now set
> `enable_rust_endpoint=True`, or the endpoint returns 404.

## Field-level authorization

Field checks (`authorize_field`) speak the **same** contract: a `PermissionCheck` may return a
`bool` (legacy, unchanged) or an `AuthorizationDecision`. A deny decision surfaces its
`code`/`message`. One policy object can serve both layers via `field_authorizer_adapter`:

```python
from fraiseql.security import authorize_field, field_authorizer_adapter

@field
@authorize_field(field_authorizer_adapter(my_authorizer, field="User.email"))
async def email(self, info) -> str | None:
    return self._email
```

> A field method combined with `@authorize_field` must take `info` (`async def
> email(self, info)`): the check needs the request context, and an `async` resolver lets an
> async authorizer run without the sync→async event-loop fallback.

### Automatic field gating (opt-in)

Instead of decorating each field by hand, a type can declare which fields the configured
operation `Authorizer` should gate automatically (issue #366):

```python
@fraise_type(authorize_fields=["email", "ssn"])
class User:
    id: int
    name: str          # ungated
    email: str         # gated automatically
    ssn: str           # gated automatically
```

Each listed field is checked with `operation_type="field"` and
`operation_name="User.email"` (`"TypeName.fieldName"` — a stable identifier to write
policies against) **before its resolver runs**, so a denial means the field body never
executes. Guarantees:

- **Narrow opt-in by design.** Only the declared fields are gated; everything else carries
  zero extra cost. There is deliberately no "gate every field" switch (it would be a
  performance and blast-radius footgun).
- **No authorizer → unchanged.** The gate reads the global default authorizer live; with
  none configured it is a true no-op.
- **Fail-closed.** A raising field authorizer is normalized to a
  `FIELD_AUTHORIZATION_ERROR` deny (parity with the operation path); `filters` are ignored
  with a warning at field granularity.
- **Precedence.** An explicit `@authorize_field` on a field is **AND-combined** with the
  automatic gate — both must allow.

> **⚠️ Performance: this fires per resolved object.** For a list of *N* objects each
> exposing *M* gated fields, that is up to *N×M* authorizer calls. Keep the opt-in set
> narrow, and enable **decision caching** (see below) — the same `(principal, "field",
> "Type.field", arguments)` repeats across every object in a list, so a cache collapses the
> *N* calls per field into one within the TTL. Measure the call volume for representative
> nested-list queries before gating hot fields.

## Subscriptions

A subscription *is* an operation, so it is gated by the same PEP — enforced **once, at
subscribe time**, before the event stream is created. graphql-core calls the subscription's
`subscribe` resolver to obtain the stream; the authorizer runs there with
`operation_type="subscription"`, so a deny raises a `GraphQLError` *during the subscribe
call* and the inner generator — which is what would query the database — is never built.
This covers both the schema execution path and the websocket transport (which routes through
graphql-core's `subscribe`).

```python
@fraiseql.subscription(authorizer=AdminOnly())   # per-operation override
async def audit_stream(info) -> AsyncGenerator[AuditEntry, None]:
    ...
```

As with queries and mutations, a per-operation `@subscription(authorizer=...)` takes
precedence over the global default; with no authorizer in effect, subscriptions stream
byte-for-byte as before.

- **Filters are ignored.** A subscription stream is not a single scoped read set, so a
  returned `decision.filters` has no row-scoping meaning. It is **logged, not silently
  dropped** (mirroring the mutation path) — rely on the stream source for any scoping.
- **Subscribe-time only (for now).** Enforcement runs once, when the client subscribes — not
  per emitted event. Revoking a *live* stream when permissions change mid-flight (per-event
  re-checking) is a deliberate future opt-in, not part of this contract.

## Decision caching (optional)

An authorizer that issues a DB query or calls an external policy service adds latency to the
hot path. You can **opt in** to memoizing its decisions so an identical
`(principal, operation_type, operation_name, arguments)` is not re-evaluated within a short
TTL:

```python
from fraiseql import create_fraiseql_app, AuthorizationCacheConfig

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[...], queries=[...], mutations=[...],
    authorizer=MyAuthorizer(),
    authorization_cache=AuthorizationCacheConfig(
        principal_key=lambda ctx: ctx["user"]["id"],  # required: identify the principal
        ttl_seconds=5.0,        # keep short — a stale *allow* is a security risk
        max_entries=10_000,     # LRU bound
    ),
)
```

**Off by default.** Always-evaluate is the safe default; a stale *allow* briefly authorizes a
now-revoked principal (a stale *deny* is only an availability nuisance). Caching is never
implicit.

**⚠️ Correctness contract — the authorizer must be a pure function of the key.** A cache hit
replays a prior decision, so caching is only correct if the decision depends on **nothing
outside** `(principal_key(context), operation_type, operation_name, arguments)`. An authorizer
that also reads tenant, request IP, time-of-day, feature flags, or resource state from
`context` will be served a **wrong** decision on a hit — including a *stale allow*. This is a
correctness bug, **not** merely a TTL staleness window: such an authorizer is broken under
caching regardless of how short the TTL is. Fold the extra inputs into `principal_key`, or
leave caching off. The framework cannot detect a non-pure authorizer.

Other guarantees:

- **`principal_key` is required**, and a `None` return (anonymous/unknown principal) is
  **never cached** — an entry is never shared across unidentified principals.
- **Non-serializable arguments are never cached** — the call falls through to evaluate.
- **The whole decision is cached, including `filters`** (they are principal- and
  argument-derived, already in the key). Denies are cached too; the TTL bounds staleness.
- **A raising authorizer is never cached.** It still hits the fail-closed branch, so a
  transient policy-service error can neither pin a deny nor leak an allow.
- **TTL-only invalidation.** There is **no active invalidation hook** in this version — keep
  the TTL short. Revoke-on-event is a possible future extension.
- The cache is process-global (held on the registry) and survives schema hot-reload, which is
  exactly why `principal_key` must be present and correct.

> Hit-rate note (not a defect): the resolver path keys on `info.field_name` + resolved kwargs
> while the bypass gates derive the operation name and pass request variables, so the same
> logical op keys differently per path. This is safe (no false sharing) — just a lower hit rate.

## Migration from the registry rewrite

**Before** — coupling the security boundary to a private attribute:

```python
registry = SchemaRegistry.get_instance()
for name, fn in list(registry._mutations.items()):   # private — fragile
    registry._mutations[name] = wrap_with_guard(fn)
```

**After** — the supported entry point:

```python
app = create_fraiseql_app(..., authorizer=MyAuthorizer())
```

The legacy registry rewrite keeps working during migration (the resolver wrap composes around
whatever resolver is present at build time), but new code should use `authorizer=`.

## Cross-version note

The decision-function contract is intentionally **identical** to the v2 (Rust) counterpart
([fraiseql/fraiseql#422](https://github.com/fraiseql/fraiseql/issues/422)). The runtimes are
incompatible (v1 = Python objects + a mutable registry; v2 = Rust traits), so code cannot be
shared — but a single policy implementation can serve both runtimes.

## Out of scope

- A built-in policy DSL — only the enforcement point and decision contract are provided.

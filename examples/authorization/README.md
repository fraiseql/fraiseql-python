# Operation Authorization Example

Shows the supported first-class authorization extension point (issue #362):

- **`DenyMutationsAuthorizer`** — a cross-cutting policy ("read-only principals may not run
  mutations"), expressed through `create_fraiseql_app(authorizer=...)` instead of rewriting the
  private `SchemaRegistry._mutations` registry.
- **`TenantScopeAuthorizer`** — per-row scoping: every query is transparently limited to the
  principal's tenant via `AuthorizationDecision.allow(filters={"tenant_id": ...})`, AND-merged
  into the repository's validated, parameterized `mandatory_filters`.

The same authorizer also gates the resolver-bypass paths (TurboRouter, `POST /graphql/rust`, APQ
cache hits) and survives schema hot-reload.

```bash
python examples/authorization/app.py
```

See [docs/security/authorization.md](../../docs/security/authorization.md) for the full guide,
fail-closed semantics, and the bypass-path / RLS caveat.

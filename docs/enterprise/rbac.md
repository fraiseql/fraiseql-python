<!-- Skip to main content -->
---

title: Enterprise RBAC Documentation
description: Role, permission and user-role tables with role inheritance, and PermissionResolver to compute a user's permissions from them
keywords: []
tags: ["documentation", "reference"]
---

# Enterprise RBAC Documentation

**Topic**: Role-Based Access Control

---

## Overview

`fraiseql.enterprise.rbac` keeps roles and permissions in PostgreSQL and computes a
user's effective permissions from them:

- **Tables**: `roles` (with an optional `parent_role_id`), `permissions`
  (`resource`, `action`), `role_permissions` and `user_roles` (optionally per tenant,
  with an expiry).
- **Inheritance**: a role has the permissions of its parent, its parent's parent, and
  so on (up to 10 levels).
- **`PermissionResolver`**: computes the permissions of a user, and answers
  `has_permission` / `check_permission`.
- **SQL helpers** for row-level security policies: `user_has_role()` and
  `user_has_permission()`.

FraiseQL doesn't check these permissions on its own: call the resolver in your
resolvers (or in an `Authorizer`), or use the SQL helpers in RLS policies. For
permissions carried in the token, `@requires_permission` / `@requires_role` from
`fraiseql.auth` check `info.context["user"]` instead, without these tables.

---

## Setup

The schema is in the `migrations/` directory of the installed `fraiseql.enterprise`
package. FraiseQL doesn't apply it: run the files you need as part of your migrations.

```bash
DIR=$(python -c "import fraiseql.enterprise, pathlib; print(pathlib.Path(fraiseql.enterprise.__file__).parent / 'migrations')")
psql "$DATABASE_URL" -f "$DIR/002_rbac_tables.sql"
```

`002_rbac_tables.sql` creates the four tables, the `get_inherited_roles(role_id)`
function, and seeds five system roles and eight permissions (`user.create`,
`user.read`, `user.update`, `user.delete`, `role.assign`, `role.create`, `audit.read`,
`settings.update`). The seeded roles are chained `viewer` → `user` → `manager` →
`admin` → `super_admin`, each one the *parent* of the one before it: since a role
inherits its parent's permissions, `viewer` gets every permission granted to
`super_admin`. Give the seeded roles permissions with that in mind, or create your own
hierarchy with the most privileged roles at the bottom.

`003_rbac_cache_setup.sql` needs the `pg_fraiseql_cache` extension (see below).
`004_rbac_row_level_security.sql` adds RLS policies to tables named `users`, `orders`
and `products`, and fails (`relation "users" does not exist`) unless all three exist;
read it before applying it, or copy only the two functions at its end (see
[Row-Level Security](#row-level-security)).

### Roles, Permissions and Assignments

Plain SQL:

```sql
INSERT INTO roles (id, name) VALUES ('00000000-0000-0000-0000-0000000000a1', 'viewer_role');
INSERT INTO roles (id, name, parent_role_id) VALUES
    ('00000000-0000-0000-0000-0000000000a2', 'editor', '00000000-0000-0000-0000-0000000000a1');

INSERT INTO permissions (resource, action) VALUES ('post', 'read'), ('post', 'update');

INSERT INTO role_permissions (role_id, permission_id)
SELECT '00000000-0000-0000-0000-0000000000a1', id FROM permissions
WHERE resource = 'post' AND action = 'read';

INSERT INTO role_permissions (role_id, permission_id)
SELECT '00000000-0000-0000-0000-0000000000a2', id FROM permissions
WHERE resource = 'post' AND action = 'update';

-- editor inherits post.read from viewer_role
INSERT INTO user_roles (user_id, role_id, tenant_id, expires_at) VALUES
    ('00000000-0000-0000-0000-0000000000c1', '00000000-0000-0000-0000-0000000000a2',
     NULL, NULL);
```

A `user_roles` row with a `tenant_id` applies to that tenant only; with `NULL`, to
requests without a tenant. A row past its `expires_at` is ignored.

---

## Resolving Permissions

```python
from uuid import UUID

from fraiseql.db import FraiseQLRepository
from fraiseql.enterprise.rbac.cache import PermissionCache
from fraiseql.enterprise.rbac.resolver import PermissionResolver

# pool: the app's psycopg AsyncConnectionPool
resolver = PermissionResolver(FraiseQLRepository(pool), PermissionCache(pool))

user_id = UUID("00000000-0000-0000-0000-0000000000c1")

permissions = await resolver.get_user_permissions(user_id, tenant_id=None, use_cache=False)
print(sorted(f"{p.resource}.{p.action}" for p in permissions))
# ['post.read', 'post.update']

roles = await resolver.get_user_roles(user_id)      # direct roles: [Role(name='editor', ...)]
```

Pass the `PermissionCache` yourself: `PermissionResolver(repo)` alone fails, as it
looks for a `pool` attribute `FraiseQLRepository` doesn't have.

`has_permission(user_id, resource, action, tenant_id=None)` returns a bool, and
`check_permission(..., raise_on_deny=True)` raises `PermissionError("Permission
denied: requires post.delete")`. Both go through the cache (see the caveats below).
`RoleHierarchy(repo)` (`fraiseql.enterprise.rbac.hierarchy`) has
`get_inherited_roles(role_id)` (the role and its ancestors), `get_hierarchy_depth`,
`get_role_ancestors` and `get_role_descendants`.

In a resolver:

```python
from uuid import UUID

import fraiseql
from graphql import GraphQLError


@fraiseql.mutation
async def publish_post(info, id: UUID) -> bool:
    user = info.context["user"]
    permissions = await resolver.get_user_permissions(
        UUID(user.user_id), tenant_id=info.context.get("tenant_id"), use_cache=False
    )
    if not any(p.resource == "post" and p.action == "update" for p in permissions):
        raise GraphQLError("Forbidden", extensions={"code": "FORBIDDEN"})
    ...
    return True
```

### Caching Caveats

`PermissionCache` keeps two layers: an in-memory dict on the `PermissionCache`
instance, and rows in a `fraiseql_cache` table (`PostgresCache`). In this release:

- A permission set read back from the `fraiseql_cache` table fails with a pydantic
  `ValidationError` (`created_at` missing), so a cached call made by a second
  `PermissionCache` (another request, another process) raises.
- The in-memory layer is never cleared on its own: a resolver kept for the app's
  lifetime keeps answering with the permissions it first computed. Call
  `resolver.cache.clear_request_cache()` per request if you use it.
- `get_role_permissions(role_id)` fails (`TypeError: positional placeholders (%s)
  require a sequence of parameters`).

Until these are fixed, call `get_user_permissions(..., use_cache=False)` and check the
result yourself, as above.

With the `pg_fraiseql_cache` extension, `await setup_rbac_cache(pool)`
(`fraiseql.enterprise.rbac`) installs version triggers on the four tables, so cached
permissions are invalidated when they change; without it, it logs a warning and does
nothing.

---

## Row-Level Security

`004_rbac_row_level_security.sql` ends with two functions you can use in your own
policies (copy them if you don't apply the whole file):

```sql
-- user_has_role(user_id, role_name) and user_has_permission(user_id, resource, action)
CREATE POLICY post_update ON tb_post
    FOR UPDATE
    USING (user_has_permission(current_setting('app.user_id')::uuid, 'post', 'update'));
```

Both read the user's *direct* roles: unlike `PermissionResolver`, they don't follow
`parent_role_id`. `current_setting('app.user_id')` is the session variable FraiseQL
sets from `info.context["user_id"]` before each query (see
[Multi-tenancy](../advanced/multi-tenancy.md)).

---

## GraphQL Directives (Strawberry only)

`fraiseql.enterprise.rbac.directives` defines `requires_permission(resource, action)`
and `requires_role(role_name)` as Strawberry schema directives. Importing it needs the
`strawberry-graphql` package (without it: `ImportError: strawberry is required for
enterprise RBAC features`), and they apply to a Strawberry schema, not to the schema
FraiseQL builds. `RbacMiddleware` / `create_rbac_middleware`
(`fraiseql.enterprise.rbac.middleware`) is a Strawberry-style extension as well;
`create_fraiseql_app` has no way to install it.

---

## See Also

- [Audit Logging](./audit-logging.md)
- [Authentication](../advanced/authentication.md)

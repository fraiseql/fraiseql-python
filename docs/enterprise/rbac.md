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
`settings.update`), granted to no role. Each seeded role's parent is the one below
it: `super_admin` → `admin` → `manager` → `user` → `viewer`. Since a role inherits
its parent's permissions, `admin` has what you grant `manager`, `user` and `viewer`,
and `viewer` has only its own.

Before 1.31.0 the file seeded this chain the other way round (`viewer`'s parent was
`user`, ..., `admin`'s was `super_admin`), so `viewer` had every permission granted to
`super_admin`. Applying the current file again rewires a database that still has
exactly that seed. If you changed the parent of a seeded role, it leaves the hierarchy
alone: check it with `SELECT name, parent_role_id FROM roles WHERE is_system`.

`003_rbac_cache_setup.sql` needs the `pg_fraiseql_cache` extension (see below).
`004_rbac_row_level_security.sql` creates two helper functions for RLS policies (see
[Row-Level Security](#row-level-security)). It also holds example policies for tables
named `users`, `orders` and `products`, applied to each of these tables that exists
when the file runs (it skips the others with a `NOTICE`): tenant isolation on
`tenant_id`, and updates limited to the row's owner (`users.id`, `orders.user_id`) or
to the `admin` and `super_admin` roles. Read them before applying the file to a
database that has tables with these names.

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
from fraiseql.enterprise.rbac.resolver import PermissionResolver

# pool: the app's psycopg AsyncConnectionPool
resolver = PermissionResolver(FraiseQLRepository(pool))

user_id = UUID("00000000-0000-0000-0000-0000000000c1")

permissions = await resolver.get_user_permissions(user_id, tenant_id=None, use_cache=False)
print(sorted(f"{p.resource}.{p.action}" for p in permissions))
# ['post.read', 'post.update']

roles = await resolver.get_user_roles(user_id)      # direct roles: [Role(name='editor', ...)]
```

`PermissionResolver(repo, cache=None)` creates a `PermissionCache` on the
repository's pool when you don't pass one.

`has_permission(user_id, resource, action, tenant_id=None)` returns a bool, and
`check_permission(..., raise_on_deny=True)` raises `PermissionError("Permission
denied: requires post.delete")`. Both go through the cache (see [Caching](#caching)).
`get_role_permissions(role_id, include_inherited=True)` lists a role's permissions,
with those of its ancestors unless `include_inherited=False`.
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

### Caching

`PermissionCache` keeps two layers:

- an in-memory dict on the `PermissionCache` instance. An entry answers for
  `request_cache_ttl` (`PermissionCache(pool, request_cache_ttl=timedelta(seconds=1))`
  by default), then the next call goes back to PostgreSQL; `timedelta(0)` turns the
  layer off. `resolver.cache.clear_request_cache()` empties it.
- rows in a `fraiseql_cache` table (`PostgresCache`), kept 5 minutes, and shared by
  every resolver, request and process on the database.

A change to a user's roles or permissions therefore shows within 5 minutes, or at
once with the extension below, or after `await resolver.invalidate_user_cache(user_id,
tenant_id)` (within `request_cache_ttl` for other resolvers). Pass `use_cache=False`
where that delay is too long.

With the `pg_fraiseql_cache` extension, `await setup_rbac_cache(pool)`
(`fraiseql.enterprise.rbac`) installs version triggers on the four tables, so cached
permissions are invalidated when they change; without it, it logs a warning and does
nothing.

---

## Row-Level Security

`004_rbac_row_level_security.sql` creates two functions you can use in your own
policies:

```sql
-- user_has_role(user_id, role_name) and user_has_permission(user_id, resource, action)
CREATE POLICY post_update ON tb_post
    FOR UPDATE
    USING (user_has_permission(current_setting('app.user_id')::uuid, 'post', 'update'));
```

`user_has_permission` counts the permissions `PermissionResolver` would: those granted
to each role assigned to the user (unexpired) and to that role's ancestors, through
`get_inherited_roles()`; like the resolver, it raises an error when an assigned role has
an ancestor ten levels up. Before 1.31.1 it read the assigned roles only. `user_has_role`
checks the roles assigned to the user, as `requires_role` and
`PermissionResolver.get_user_roles()` do: a `super_admin` doesn't have the `admin` role.
Unlike the resolver, neither takes a tenant: they count the user's assignments in every
tenant. `current_setting('app.user_id')` is the session variable FraiseQL
sets from `info.context["user_id"]` before each query (see
[Multi-tenancy](../advanced/multi-tenancy.md)).

The file also applies example policies to tables named `users`, `orders` and
`products`, if they exist. Their admin checks call `user_has_role()`, wrapped in a
`SELECT` so that PostgreSQL evaluates the call once per statement:

```sql
USING (
    user_id = current_setting('app.user_id', TRUE)::UUID
    OR (SELECT user_has_role(current_setting('app.user_id', TRUE)::UUID, 'admin'))
    OR (SELECT user_has_role(current_setting('app.user_id', TRUE)::UUID, 'super_admin'))
)
```

Before 1.31.1 they read `user_roles` directly and counted expired assignments: run the
1.31.1 file again to replace them. Check role assignments the same way in your own
policies: a query on `user_roles` must also test `expires_at`.

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

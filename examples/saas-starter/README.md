# SaaS Starter Template

A multi-tenant SaaS API with FraiseQL 1.x: organizations (the tenants), their
users, and their projects. Every query and mutation is scoped to the caller's
organization, and every write is tracked (usage metrics) and logged (activity
log) inside the same PostgreSQL function.

## What's in it

| File | What it holds |
|------|---------------|
| `schema.sql` | Tables (`tb_*`), JSONB views (`v_*`), row-level security policies, sample data, and the mutation functions |
| `models.py` | The types (`Organization`, `User`, `Project`, …) and inputs |
| `main.py` | The queries, the class mutations, the tenant context, and the FastAPI app |

### API

```graphql
type Query {
  currentOrganization: Organization
  currentUser: User
  teamMembers(limit: Int, offset: Int, where: UserWhereInput, orderBy: [UserOrderByInput]): [User]
  projects(limit: Int, offset: Int, where: ProjectWhereInput, orderBy: [ProjectOrderByInput]): [Project]
  project(id: ID): Project
}

type Mutation {
  createProject(input: ProjectCreateInput!): CreateProjectResult
  updateProject(input: ProjectUpdateInput!): UpdateProjectResult
  deleteProject(input: DeleteProjectInput!): DeleteProjectResult
  updateOrganization(input: OrganizationUpdateInput!): UpdateOrganizationResult
}
```

fraiseql adds `where`, `orderBy`, `limit` and `offset` to list queries; the
resolvers pass them on to `db.find` (`projects` returns at most 50 when no `limit`
is given), and the tenant filter applies on top.

## How tenancy works

- `get_context` in `main.py` puts the caller's `organization_id` and `user_id` in
  the GraphQL context. The demo reads them from the `X-Organization-ID` and
  `X-User-ID` headers (defaulting to the sample organization and its owner); in
  production, take them from a verified token.
- Queries read the views with `mandatory_filters={"organization_id": ...}`: the
  views expose the tenant's id as a column, and a project of another organization
  is simply not found.
- Mutations are class mutations with
  `context_params={"organization_id": "p_organization_id", "user_id": "p_user_id"}`:
  fraiseql calls, for example, `create_project(organization_id, user_id, input)`.
  The function checks the project belongs to the tenant, writes, calls
  `track_usage` and `log_activity`, and returns a `mutation_response`.
- `schema.sql` also enables row-level security on the tables, for connections that
  use the `authenticated_user` role and set `app.current_tenant`. The app's own
  connection owns the tables, so it relies on the filters above.

## Running it

```bash
createdb saas_starter
psql saas_starter -f ../../migrations/trinity/005_add_mutation_response.sql
psql saas_starter -f schema.sql

pip install -r requirements.txt
DATABASE_URL=postgresql://localhost/saas_starter python main.py
```

Then, at `http://localhost:8000/graphql`:

```graphql
mutation {
  createProject(input: {name: "Docs"}) {
    __typename
    ... on ProjectSuccess { project { id name status } }
    ... on SaasError { message code }
  }
}
```

Send `X-Organization-ID: 22222222-2222-2222-2222-222222222222` and
`X-User-ID: cccccccc-cccc-cccc-cccc-cccccccccccc` to act as the second sample
organization: it sees its own project, and none of Acme Corp's.

## Building on it

`models.py` also defines types for subscriptions, team invitations, usage metrics
and the activity log, with tables in `schema.sql`. They aren't exposed yet: add a
view, a query or a class mutation backed by a SQL function the same way as for
projects.

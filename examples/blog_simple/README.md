# FraiseQL Blog Simple

🟢 BEGINNER | ⏱️ 20 min | 🎯 Content Management | 🏷️ Trinity Pattern, JSONB views

A small blog on PostgreSQL: users, posts, tags and comments. Reads come from views
with a JSONB `data` column; writes go through SQL functions that return a
`mutation_response`.

**What you'll learn:**

- Views that embed related objects (a post's author, tags and comments) so one
  GraphQL query is one SQL query
- List queries that pass fraiseql's `where`, `orderBy`, `limit` and `offset` on to
  `db.find`
- Class mutations backed by SQL functions, with success and error types
- Passing the current user from the request to SQL functions (`context_params`)
- The Trinity pattern: integer `pk_*` keys for joins, a public UUID `id`, a
  human-readable `identifier`

**Next steps:**

- [`../blog_enterprise/`](../blog_enterprise/README.md) - Domain-driven structure
- [`../saas-starter/`](../saas-starter/README.md) - Multi-tenant scoping
- [`../ecommerce/`](../ecommerce/README.md) - More business logic

## Quick Start

### With Docker Compose

```bash
docker compose up
```

PostgreSQL runs `db/setup.sql` and `db/seed_data.sql` on first start, and the
app listens on http://localhost:8000/graphql.

### By hand

```bash
# PostgreSQL
docker run -d --name blog_simple_db \
  -e POSTGRES_DB=fraiseql_blog_simple \
  -e POSTGRES_USER=fraiseql \
  -e POSTGRES_PASSWORD=fraiseql \
  -p 5432:5432 \
  postgres:16

# Schema and sample data
psql postgresql://fraiseql:fraiseql@localhost:5432/fraiseql_blog_simple -f db/setup.sql
psql postgresql://fraiseql:fraiseql@localhost:5432/fraiseql_blog_simple -f db/seed_data.sql

# Application
pip install -r requirements.txt
python app.py
```

Open http://localhost:8000/graphql for the GraphQL playground. The connection is
configured with `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` and `DB_PASSWORD`
(defaults: `localhost`, `5432`, `fraiseql_blog_simple`, `fraiseql`, `fraiseql`).

## Files

```text
blog_simple/
├── app.py              # create_fraiseql_app and the request context
├── models.py           # Types, queries, mutations
├── db/
│   ├── setup.sql       # Tables, views, mutation functions
│   └── seed_data.sql   # Four users, six tags, four posts, six comments
├── docker-compose.yml
└── Dockerfile
```

## Database

### Tables

Each table has three identifiers (the Trinity pattern):

| Column | Type | Used for |
|---|---|---|
| `pk_user`, `pk_post`, ... | `INT GENERATED ALWAYS AS IDENTITY` | Primary key and foreign keys (`fk_author`, `fk_post`, ...). Never leaves the database. |
| `id` | `UUID` | The GraphQL `id` |
| `identifier` | `TEXT UNIQUE` | Username or slug, for URLs (generated from the title or name when empty) |

`tb_user`, `tb_post`, `tb_comment`, `tb_tag` and `tb_post_tag` (post ↔ tag) are
the tables. See [the Trinity pattern guide](../../docs/core/trinity-pattern.md).

### Views

Each GraphQL type reads one view. The view has an `id` column, the columns the
queries filter on, and a `data` JSONB column holding the object:

```sql
CREATE VIEW v_post AS
SELECT
    p.pk_post,
    p.id,
    p.identifier,
    a.id AS author_id,
    jsonb_build_object(
        'id', p.id,
        'title', p.title,
        'status', p.status,
        -- ...
        'author', a.data,
        'tags', coalesce((SELECT jsonb_agg(t.data ...) ...), '[]'::jsonb),
        'comments', coalesce((SELECT jsonb_agg(c.data ...) ...), '[]'::jsonb)
    ) AS data
FROM tb_post p
JOIN v_user a ON a.pk_user = p.fk_author;
```

`v_user`, `v_tag` and `v_comment` follow the same shape. `v_post` embeds
`v_user.data` as the author, the post's tags, and its approved comments.

### Mutation functions

Each class mutation calls the SQL function named after it: `CreatePost` calls
`create_post(p_user_id uuid, input jsonb)`. The function returns a
`mutation_response` (defined at the top of the mutations section of
`setup.sql`):

- status `created` or `updated`, with the new row's `data` as `entity`: the
  success type, whose field (`post`, `comment`, `tag`) is the entity
- status `validation:…`, `not_found:…`, `forbidden:…`, `unauthorized:…` or
  `conflict:…`: the error type, with `code` 422, 404, 403, 401 or 409

## GraphQL

### Types

```python
@fraiseql.type(sql_source="v_post")
class Post:
    id: ID
    identifier: str
    slug: str
    title: str
    content: str
    excerpt: str | None
    status: PostStatus
    published_at: datetime | None
    author: User
    tags: list[Tag]
    comments: list[Comment]
    created_at: datetime
    updated_at: datetime
```

`User`, `Tag` and `Comment` are declared the same way in `models.py`. Fields read
the keys of the view's `data` column; the default `jsonb_column` is `data`.

### Queries

A query returning a list gets fraiseql's `where`, `orderBy`, `limit` and `offset`
arguments. The resolver declares them and passes them on:

```python
@fraiseql.query
async def posts(
    info, where=None, order_by=None, limit: int | None = 20, offset: int | None = None
) -> list[Post]:
    db = info.context["db"]
    return await db.find(
        "v_post",
        "posts",
        info,
        where=where,
        order_by=order_by or {"created_at": "DESC"},
        limit=limit,
        offset=offset,
    )


@fraiseql.query
async def post(info, id: ID | None = None, identifier: str | None = None) -> Post | None:
    if id is None and identifier is None:
        return None
    filters = {"id": id} if id is not None else {"identifier": identifier}
    return await info.context["db"].find_one("v_post", "post", info, mandatory_filters=filters)
```

```graphql
query {
  posts(where: { status: { eq: "published" } }, orderBy: { title: ASC }, limit: 5) {
    title
    author { username fullName }
    tags { name }
    comments { content author { username } }
  }
  post(identifier: "getting-started-with-fraiseql") { id title }
  user(identifier: "janedoe") { email role }
  tags { name color }
}
```

### Mutations

```python
@fraiseql.success
class PostSuccess:
    post: Post


@fraiseql.error
class BlogError:
    """status, message and code come from the function's mutation_response."""


@fraiseql.mutation(context_params={"user_id": "p_user_id"})
class CreatePost:
    input: CreatePostInput
    success: PostSuccess
    error: BlogError
```

`context_params` passes `info.context["user_id"]` as the function's `p_user_id`.
`app.py` puts the user in the context from the `X-User-ID` header, defaulting to
`johndoe` from the sample data; use your authentication instead in production.

```graphql
mutation {
  createPost(input: { title: "Hello", content: "First post", tagIds: ["55555555-5555-5555-5555-555555555555"] }) {
    __typename
    ... on PostSuccess { message post { id title status author { username } } }
    ... on BlogError { message code }
  }
}
```

The other mutations are `updatePost` (only the author can; another user gets a
`BlogError` with code 403), `createComment` (on a published post; new comments
are `pending` until approved) and `createTag` (a duplicate name gets code 409).

## Tests

`tests/integration/examples/test_blog_integration.py` in the repository loads
`db/setup.sql` and `db/seed_data.sql` into a fresh database and runs the queries
and mutations above through the app.

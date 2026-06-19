---
title: "Full-Stack Blog: FraiseQL v1 Python Backend + React Frontend"
description: Build a complete blog application with a FraiseQL v1 Python/PostgreSQL backend and a React frontend that consumes its GraphQL endpoint with Apollo Client.
keywords: ["tutorial", "hands-on", "fullstack", "react", "apollo", "step-by-step"]
tags: ["documentation", "tutorial"]
---

# Full-Stack Blog: FraiseQL v1 Python Backend + React Frontend

**Duration**: ~75 minutes
**Outcome**: A working blog with a FraiseQL Python backend on FastAPI and a React frontend talking to it over GraphQL
**Prerequisites**: Python 3.13+, Node.js 18+, PostgreSQL 14+
**Focus**: End-to-end flow — Python decorators define the schema, FraiseQL builds and serves it at runtime, React renders the data

---

## Overview

In this tutorial you will build a blog application in two halves:

1. **Backend** — a [FraiseQL](../index.md) Python app. You define PostgreSQL `tb_`/`v_`/`fn_`
   objects, declare GraphQL types and resolvers with `@fraiseql` decorators, and serve them
   with FastAPI. The GraphQL schema is **built in memory at app startup** — there is no
   compile step, no schema artifact, and no separate server binary.
2. **Frontend** — a React app that uses **Apollo Client** to query and mutate against the
   backend's `/graphql` endpoint at `http://localhost:8000/graphql`.

### How FraiseQL v1 works

FraiseQL v1 is a **runtime GraphQL framework for PostgreSQL**. The data model follows a CQRS split:

- **Reads** come from PostgreSQL **views** (`v_*`) that expose a `data` JSONB column. Query
  resolvers call `db.find` / `db.find_one` against those views.
- **Writes** go through PostgreSQL **functions** (`fn_*`). Mutation resolvers call them with
  `db.execute_function`; all write logic lives in the database.

```text
React (Apollo Client, :5173)
        │  HTTP POST /graphql
        ▼
FastAPI app (FraiseQL, :8000)        ← schema built in memory at startup
        │  db.find / db.find_one      (reads)
        │  db.execute_function        (writes)
        ▼
PostgreSQL (:5432)
   tb_*  write tables  (source of truth)
   v_*   read views    (expose `data` JSONB)
   fn_*  functions     (mutation write logic)
```

### What you'll build

A blog supporting:

- **Users** — blog authors
- **Posts** — create, update, delete, with an author relationship
- **Comments** — add comments to posts
- **Likes** — like and unlike posts

### Key concepts

- **PostgreSQL-first modeling** — `tb_` tables, `v_` views with `data` JSONB, `fn_` functions
- **Runtime schema** — `@fraiseql.type` / `@fraiseql.query` / `@fraiseql.mutation` assembled at startup
- **FastAPI serving** — `create_fraiseql_app(...)` returns a FastAPI app you run with `uvicorn`
- **React + Apollo Client** — queries, mutations with `Success | Error` unions, loading/error states

---

## Part 1: Project Setup

### 1.1 Directory structure

```text
fullstack-blog/
├── backend/
│   ├── app.py                # FraiseQL types, resolvers, and FastAPI app
│   ├── schema.sql            # PostgreSQL DDL: tables, views, functions, seed data
│   └── requirements.txt      # Python dependencies
└── frontend/
    ├── index.html
    ├── src/
    │   ├── components/
    │   │   ├── PostList.jsx
    │   │   ├── PostCard.jsx
    │   │   ├── PostDetail.jsx
    │   │   ├── CommentSection.jsx
    │   │   └── LikeButton.jsx
    │   ├── apollo-client.js
    │   ├── queries.js
    │   ├── App.jsx
    │   └── main.jsx
    ├── package.json
    └── .env.local
```

### 1.2 Initialize the backend

```bash
mkdir -p fullstack-blog/backend
cd fullstack-blog/backend

python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

`backend/requirements.txt`:

```text
fraiseql
uvicorn[standard]
```

### 1.3 Initialize the frontend

```bash
# From the project root
cd fullstack-blog
npm create vite@latest frontend -- --template react
cd frontend
npm install

# GraphQL client and router
npm install @apollo/client graphql react-router-dom

# Dev server runs on http://localhost:5173
npm run dev
```

---

## Part 2: PostgreSQL Schema

FraiseQL v1 reads from views that expose a `data` JSONB column and writes through functions.
Each entity uses the **trinity** identifier pattern:

- `pk_<entity>` — internal `BIGINT` primary key (fast joins, **never exposed** in GraphQL)
- `id` — public `UUID` (stable, this becomes the GraphQL `id`)
- (optionally an `identifier` slug — not used here)

Create `backend/schema.sql`:

```sql
-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Reset (development only!)
DROP VIEW IF EXISTS v_comment CASCADE;
DROP VIEW IF EXISTS v_post CASCADE;
DROP VIEW IF EXISTS v_user CASCADE;
DROP TABLE IF EXISTS tb_like CASCADE;
DROP TABLE IF EXISTS tb_comment CASCADE;
DROP TABLE IF EXISTS tb_post CASCADE;
DROP TABLE IF EXISTS tb_user CASCADE;

-- ============================================================
-- Write tables (tb_*): source of truth
-- ============================================================

CREATE TABLE tb_user (
    pk_user     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id          UUID NOT NULL UNIQUE DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    bio         TEXT,
    avatar_url  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tb_post (
    pk_post     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id          UUID NOT NULL UNIQUE DEFAULT uuid_generate_v4(),
    fk_author   BIGINT NOT NULL REFERENCES tb_user(pk_user) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    published   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tb_comment (
    pk_comment  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id          UUID NOT NULL UNIQUE DEFAULT uuid_generate_v4(),
    fk_post     BIGINT NOT NULL REFERENCES tb_post(pk_post) ON DELETE CASCADE,
    fk_author   BIGINT NOT NULL REFERENCES tb_user(pk_user) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tb_like (
    pk_like     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id          UUID NOT NULL UNIQUE DEFAULT uuid_generate_v4(),
    fk_post     BIGINT NOT NULL REFERENCES tb_post(pk_post) ON DELETE CASCADE,
    fk_user     BIGINT NOT NULL REFERENCES tb_user(pk_user) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fk_post, fk_user)   -- each user likes each post at most once
);

CREATE INDEX idx_post_author   ON tb_post(fk_author);
CREATE INDEX idx_post_published ON tb_post(published);
CREATE INDEX idx_comment_post  ON tb_comment(fk_post);
CREATE INDEX idx_like_post     ON tb_like(fk_post);

-- ============================================================
-- Read views (v_*): every view carries `id` (UUID) + a `data` JSONB.
-- Never put pk_*/fk_* inside `data`.
-- ============================================================

CREATE VIEW v_user AS
SELECT
    u.id,
    jsonb_build_object(
        'id', u.id,
        'name', u.name,
        'email', u.email,
        'bio', u.bio,
        'avatarUrl', u.avatar_url,
        'createdAt', u.created_at,
        'updatedAt', u.updated_at
    ) AS data
FROM tb_user u;

CREATE VIEW v_post AS
SELECT
    p.id,
    p.published,                                      -- filterable column
    jsonb_build_object(
        'id', p.id,
        'title', p.title,
        'content', p.content,
        'published', p.published,
        'authorName', a.name,
        'authorEmail', a.email,
        'likeCount', (SELECT count(*) FROM tb_like l WHERE l.fk_post = p.pk_post),
        'commentCount', (SELECT count(*) FROM tb_comment c WHERE c.fk_post = p.pk_post),
        'createdAt', p.created_at,
        'updatedAt', p.updated_at
    ) AS data
FROM tb_post p
JOIN tb_user a ON a.pk_user = p.fk_author;

CREATE VIEW v_comment AS
SELECT
    c.id,
    p.id AS post_id,                                  -- filterable column
    jsonb_build_object(
        'id', c.id,
        'content', c.content,
        'authorName', a.name,
        'authorAvatarUrl', a.avatar_url,
        'createdAt', c.created_at
    ) AS data
FROM tb_comment c
JOIN tb_post p ON p.pk_post = c.fk_post
JOIN tb_user a ON a.pk_user = c.fk_author;

-- ============================================================
-- Functions (fn_*): all write logic. Each takes a single JSONB
-- argument and returns a JSONB result with a `success` flag.
-- ============================================================

CREATE FUNCTION fn_create_user(input jsonb)
RETURNS jsonb AS $$
DECLARE
    new_id UUID;
BEGIN
    INSERT INTO tb_user (name, email, bio, avatar_url)
    VALUES (
        input->>'name',
        input->>'email',
        input->>'bio',
        input->>'avatarUrl'
    )
    RETURNING id INTO new_id;

    RETURN jsonb_build_object('success', true, 'id', new_id);
EXCEPTION WHEN unique_violation THEN
    RETURN jsonb_build_object('success', false, 'message', 'Email already in use');
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION fn_create_post(input jsonb)
RETURNS jsonb AS $$
DECLARE
    author_pk BIGINT;
    new_id    UUID;
BEGIN
    SELECT pk_user INTO author_pk FROM tb_user WHERE id = (input->>'authorId')::uuid;
    IF author_pk IS NULL THEN
        RETURN jsonb_build_object('success', false, 'message', 'Author not found');
    END IF;

    INSERT INTO tb_post (fk_author, title, content, published)
    VALUES (
        author_pk,
        input->>'title',
        input->>'content',
        COALESCE((input->>'published')::boolean, false)
    )
    RETURNING id INTO new_id;

    RETURN jsonb_build_object('success', true, 'id', new_id);
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION fn_update_post(input jsonb)
RETURNS jsonb AS $$
DECLARE
    target_pk BIGINT;
BEGIN
    SELECT pk_post INTO target_pk FROM tb_post WHERE id = (input->>'id')::uuid;
    IF target_pk IS NULL THEN
        RETURN jsonb_build_object('success', false, 'message', 'Post not found');
    END IF;

    UPDATE tb_post
    SET title      = COALESCE(input->>'title', title),
        content    = COALESCE(input->>'content', content),
        published  = COALESCE((input->>'published')::boolean, published),
        updated_at = now()
    WHERE pk_post = target_pk;

    RETURN jsonb_build_object('success', true, 'id', input->>'id');
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION fn_delete_post(input jsonb)
RETURNS jsonb AS $$
DECLARE
    deleted INT;
BEGIN
    DELETE FROM tb_post WHERE id = (input->>'id')::uuid;
    GET DIAGNOSTICS deleted = ROW_COUNT;
    IF deleted = 0 THEN
        RETURN jsonb_build_object('success', false, 'message', 'Post not found');
    END IF;
    RETURN jsonb_build_object('success', true, 'id', input->>'id');
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION fn_create_comment(input jsonb)
RETURNS jsonb AS $$
DECLARE
    post_pk   BIGINT;
    author_pk BIGINT;
    new_id    UUID;
BEGIN
    SELECT pk_post INTO post_pk   FROM tb_post WHERE id = (input->>'postId')::uuid;
    SELECT pk_user INTO author_pk FROM tb_user WHERE id = (input->>'userId')::uuid;
    IF post_pk IS NULL OR author_pk IS NULL THEN
        RETURN jsonb_build_object('success', false, 'message', 'Post or user not found');
    END IF;

    INSERT INTO tb_comment (fk_post, fk_author, content)
    VALUES (post_pk, author_pk, input->>'content')
    RETURNING id INTO new_id;

    RETURN jsonb_build_object('success', true, 'id', new_id);
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION fn_like_post(input jsonb)
RETURNS jsonb AS $$
DECLARE
    post_pk BIGINT;
    user_pk BIGINT;
BEGIN
    SELECT pk_post INTO post_pk FROM tb_post WHERE id = (input->>'postId')::uuid;
    SELECT pk_user INTO user_pk FROM tb_user WHERE id = (input->>'userId')::uuid;
    IF post_pk IS NULL OR user_pk IS NULL THEN
        RETURN jsonb_build_object('success', false, 'message', 'Post or user not found');
    END IF;

    INSERT INTO tb_like (fk_post, fk_user)
    VALUES (post_pk, user_pk)
    ON CONFLICT (fk_post, fk_user) DO NOTHING;

    RETURN jsonb_build_object('success', true, 'id', input->>'postId');
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION fn_unlike_post(input jsonb)
RETURNS jsonb AS $$
DECLARE
    post_pk BIGINT;
    user_pk BIGINT;
BEGIN
    SELECT pk_post INTO post_pk FROM tb_post WHERE id = (input->>'postId')::uuid;
    SELECT pk_user INTO user_pk FROM tb_user WHERE id = (input->>'userId')::uuid;

    DELETE FROM tb_like WHERE fk_post = post_pk AND fk_user = user_pk;

    RETURN jsonb_build_object('success', true, 'id', input->>'postId');
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- Seed data
-- ============================================================

INSERT INTO tb_user (name, email, bio, avatar_url) VALUES
    ('Alice Johnson', 'alice@example.com', 'Full-stack developer and tech writer', NULL),
    ('Bob Smith',     'bob@example.com',   'DevOps engineer who loves databases',  NULL),
    ('Carol White',   'carol@example.com', 'Frontend specialist and UX enthusiast', NULL);

INSERT INTO tb_post (fk_author, title, content, published) VALUES
    (1, 'Getting Started with GraphQL', 'GraphQL is a query language for APIs...', true),
    (2, 'Database Design Best Practices', 'When designing a schema...', true),
    (3, 'React Hooks Deep Dive', 'Hooks let you use state and other features...', true);

INSERT INTO tb_comment (fk_post, fk_author, content) VALUES
    (1, 2, 'Great introduction to GraphQL!'),
    (1, 3, 'This clarified queries vs mutations for me'),
    (2, 1, 'The normalization section was really clear');

INSERT INTO tb_like (fk_post, fk_user) VALUES
    (1, 2), (1, 3), (2, 1), (2, 3), (3, 1);
```

Load it into a database:

```bash
createdb blog_db
psql blog_db -f backend/schema.sql
```

---

## Part 3: FraiseQL Backend (Python)

This is the whole backend: types, query resolvers, mutation resolvers, and the FastAPI app —
all in one file, assembled in memory when the app starts.

Create `backend/app.py`:

```python
"""FraiseQL blog backend.

The GraphQL schema is built in memory at startup from the @fraiseql decorators
below and served over FastAPI. Reads come from v_* views; writes go through
fn_* PostgreSQL functions (CQRS).
"""

import os
from datetime import datetime

import uvicorn

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.types import ID

# ============================================================
# Types — each maps to a v_* view and reads from its `data` JSONB
# ============================================================


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    """A blog author or commenter."""

    id: ID
    name: str
    email: str
    bio: str | None
    avatar_url: str | None
    created_at: datetime
    updated_at: datetime


@fraiseql.type(sql_source="v_post", jsonb_column="data")
class Post:
    """A blog post with denormalized author and engagement counts."""

    id: ID
    title: str
    content: str
    published: bool
    author_name: str
    author_email: str
    like_count: int
    comment_count: int
    created_at: datetime
    updated_at: datetime


@fraiseql.type(sql_source="v_comment", jsonb_column="data")
class Comment:
    """A comment on a post."""

    id: ID
    content: str
    author_name: str
    author_avatar_url: str | None
    created_at: datetime


# ============================================================
# Inputs and result types
# ============================================================


@fraiseql.input
class CreatePostInput:
    title: str
    content: str
    author_id: ID
    published: bool = False


@fraiseql.input
class UpdatePostInput:
    id: ID
    title: str | None = None
    content: str | None = None
    published: bool | None = None


@fraiseql.input
class CreateCommentInput:
    post_id: ID
    user_id: ID
    content: str


@fraiseql.success
class PostSuccess:
    post: Post


@fraiseql.success
class CommentSuccess:
    comment: Comment


@fraiseql.success
class DeleteSuccess:
    deleted_id: ID


@fraiseql.success
class LikeSuccess:
    post: Post


@fraiseql.error
class MutationError:
    message: str
    code: str = "MUTATION_ERROR"


# ============================================================
# Queries — read from v_* views via the repository
# ============================================================


@fraiseql.query
async def users(info) -> list[User]:
    """Get all users."""
    db = info.context["db"]
    return await db.find("v_user", "users", info, order_by=[("created_at", "DESC")])


@fraiseql.query
async def user(info, id: ID) -> User | None:
    """Get a single user by id."""
    db = info.context["db"]
    return await db.find_one("v_user", "user", info, id=id)


@fraiseql.query
async def posts(info, published_only: bool = True) -> list[Post]:
    """Get posts, newest first."""
    db = info.context["db"]
    where = {"published": {"eq": True}} if published_only else {}
    return await db.find(
        "v_post", "posts", info, where=where, order_by=[("created_at", "DESC")]
    )


@fraiseql.query
async def post(info, id: ID) -> Post | None:
    """Get a single post by id."""
    db = info.context["db"]
    return await db.find_one("v_post", "post", info, id=id)


@fraiseql.query
async def comments(info, post_id: ID) -> list[Comment]:
    """Get the comments for a post."""
    db = info.context["db"]
    return await db.find(
        "v_comment",
        "comments",
        info,
        where={"post_id": {"eq": post_id}},
        order_by=[("created_at", "ASC")],
    )


# ============================================================
# Mutations — call fn_* functions; return a Success | Error union
# ============================================================


@fraiseql.mutation
async def create_post(info, input: CreatePostInput) -> PostSuccess | MutationError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_create_post",
        {
            "title": input.title,
            "content": input.content,
            "authorId": str(input.author_id),
            "published": input.published,
        },
    )
    if not result.get("success"):
        return MutationError(message=result.get("message", "Could not create post"))

    created = await db.find_one("v_post", "post", info, id=result["id"])
    return PostSuccess(post=created)


@fraiseql.mutation
async def update_post(info, input: UpdatePostInput) -> PostSuccess | MutationError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_update_post",
        {
            "id": str(input.id),
            "title": input.title,
            "content": input.content,
            "published": input.published,
        },
    )
    if not result.get("success"):
        return MutationError(message=result.get("message", "Could not update post"))

    updated = await db.find_one("v_post", "post", info, id=result["id"])
    return PostSuccess(post=updated)


@fraiseql.mutation
async def delete_post(info, id: ID) -> DeleteSuccess | MutationError:
    db = info.context["db"]
    result = await db.execute_function("fn_delete_post", {"id": str(id)})
    if not result.get("success"):
        return MutationError(message=result.get("message", "Could not delete post"))
    return DeleteSuccess(deleted_id=result["id"])


@fraiseql.mutation
async def create_comment(info, input: CreateCommentInput) -> CommentSuccess | MutationError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_create_comment",
        {
            "postId": str(input.post_id),
            "userId": str(input.user_id),
            "content": input.content,
        },
    )
    if not result.get("success"):
        return MutationError(message=result.get("message", "Could not create comment"))

    created = await db.find_one("v_comment", "comment", info, id=result["id"])
    return CommentSuccess(comment=created)


@fraiseql.mutation
async def like_post(info, post_id: ID, user_id: ID) -> LikeSuccess | MutationError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_like_post", {"postId": str(post_id), "userId": str(user_id)}
    )
    if not result.get("success"):
        return MutationError(message=result.get("message", "Could not like post"))

    updated = await db.find_one("v_post", "post", info, id=result["id"])
    return LikeSuccess(post=updated)


@fraiseql.mutation
async def unlike_post(info, post_id: ID, user_id: ID) -> LikeSuccess | MutationError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_unlike_post", {"postId": str(post_id), "userId": str(user_id)}
    )
    if not result.get("success"):
        return MutationError(message=result.get("message", "Could not unlike post"))

    updated = await db.find_one("v_post", "post", info, id=result["id"])
    return LikeSuccess(post=updated)


# ============================================================
# Build the FastAPI app (schema assembled in memory at startup)
# ============================================================

app = create_fraiseql_app(
    database_url=os.getenv("DATABASE_URL", "postgresql://localhost/blog_db"),
    types=[User, Post, Comment],
    queries=[users, user, posts, post, comments],
    mutations=[create_post, update_post, delete_post, create_comment, like_post, unlike_post],
    production=False,  # exposes the GraphQL playground at /graphql
)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

A few things to note:

- `@fraiseql.type(sql_source="v_post", jsonb_column="data")` ties the GraphQL type to a view.
  FraiseQL reads only the fields the client requested out of the `data` JSONB.
- Query resolvers receive `info`; `db = info.context["db"]` is the CQRS repository. Its read
  methods are `db.find(view, field_name, info, **filters)` and
  `db.find_one(view, field_name, info, id=...)`.
- Mutations call PostgreSQL functions with `db.execute_function("fn_x", {...})` and return a
  `Success | Error` union. FraiseQL exposes that union to GraphQL so the client can branch on
  the result with inline fragments.
- Snake_case Python fields (`author_name`, `like_count`) are exposed as camelCase in GraphQL
  (`authorName`, `likeCount`).

### 3.1 Enable CORS for the React dev server

The browser will call the API from `http://localhost:5173`, a different origin, so the backend
must allow it. FraiseQL's config exposes CORS fields — enable them through a `FraiseQLConfig`
passed to `create_fraiseql_app`:

```python
from fraiseql.fastapi import FraiseQLConfig, create_fraiseql_app

config = FraiseQLConfig(
    database_url=os.getenv("DATABASE_URL", "postgresql://localhost/blog_db"),
    cors_enabled=True,
    cors_origins=["http://localhost:5173"],
    cors_methods=["GET", "POST"],
    cors_headers=["Content-Type", "Authorization"],
)

app = create_fraiseql_app(
    config=config,
    types=[User, Post, Comment],
    queries=[users, user, posts, post, comments],
    mutations=[create_post, update_post, delete_post, create_comment, like_post, unlike_post],
    production=False,
)
```

If you prefer, you can skip the FraiseQL CORS config and add standard FastAPI CORS middleware
to the returned app instead — `create_fraiseql_app` returns a normal FastAPI instance:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)
```

### 3.2 Run the backend

```bash
cd backend
source .venv/bin/activate
export DATABASE_URL="postgresql://localhost/blog_db"

uvicorn app:app --reload
# GraphQL playground: http://localhost:8000/graphql
```

Sanity-check it with curl:

```bash
curl http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ posts { id title authorName likeCount } }"}'
```

Expected response:

```json
{
  "data": {
    "posts": [
      { "id": "…", "title": "Getting Started with GraphQL", "authorName": "Alice Johnson", "likeCount": 2 }
    ]
  }
}
```

---

## Part 4: React Frontend (Apollo Client)

The frontend is a standard React app that talks to the backend with `@apollo/client`.

### 4.1 Apollo Client setup

Create `frontend/src/apollo-client.js`:

```javascript
import { ApolloClient, InMemoryCache, HttpLink } from "@apollo/client";

const httpLink = new HttpLink({
  uri: import.meta.env.VITE_GRAPHQL_API || "http://localhost:8000/graphql",
});

const client = new ApolloClient({
  link: httpLink,
  cache: new InMemoryCache(),
});

export default client;
```

Create `frontend/.env.local`:

```env
VITE_GRAPHQL_API=http://localhost:8000/graphql
```

### 4.2 Queries and mutations

Create `frontend/src/queries.js`. Note how the mutations select on the `Success | Error`
union with inline fragments (`... on PostSuccess`, `... on MutationError`):

```javascript
import { gql } from "@apollo/client";

// ---- Queries ----

export const GET_POSTS = gql`
  query GetPosts($publishedOnly: Boolean) {
    posts(publishedOnly: $publishedOnly) {
      id
      title
      content
      published
      authorName
      likeCount
      commentCount
      createdAt
    }
  }
`;

export const GET_POST = gql`
  query GetPost($id: ID!) {
    post(id: $id) {
      id
      title
      content
      published
      authorName
      authorEmail
      likeCount
      commentCount
      createdAt
    }
  }
`;

export const GET_COMMENTS = gql`
  query GetComments($postId: ID!) {
    comments(postId: $postId) {
      id
      content
      authorName
      authorAvatarUrl
      createdAt
    }
  }
`;

// ---- Mutations (Success | Error unions) ----

export const CREATE_POST = gql`
  mutation CreatePost($input: CreatePostInput!) {
    createPost(input: $input) {
      ... on PostSuccess {
        post {
          id
          title
          published
          authorName
        }
      }
      ... on MutationError {
        message
        code
      }
    }
  }
`;

export const CREATE_COMMENT = gql`
  mutation CreateComment($input: CreateCommentInput!) {
    createComment(input: $input) {
      ... on CommentSuccess {
        comment {
          id
          content
          authorName
          createdAt
        }
      }
      ... on MutationError {
        message
      }
    }
  }
`;

export const LIKE_POST = gql`
  mutation LikePost($postId: ID!, $userId: ID!) {
    likePost(postId: $postId, userId: $userId) {
      ... on LikeSuccess {
        post {
          id
          likeCount
        }
      }
      ... on MutationError {
        message
      }
    }
  }
`;

export const UNLIKE_POST = gql`
  mutation UnlikePost($postId: ID!, $userId: ID!) {
    unlikePost(postId: $postId, userId: $userId) {
      ... on LikeSuccess {
        post {
          id
          likeCount
        }
      }
      ... on MutationError {
        message
      }
    }
  }
`;
```

---

## Part 5: React Components

### 5.1 PostList

Create `frontend/src/components/PostList.jsx`. This shows the loading and error states every
Apollo query should handle:

```javascript
import { useQuery } from "@apollo/client";
import { GET_POSTS } from "../queries";
import PostCard from "./PostCard";

export default function PostList() {
  const { loading, error, data } = useQuery(GET_POSTS, {
    variables: { publishedOnly: true },
  });

  if (loading) return <div className="loading">Loading posts…</div>;
  if (error) return <div className="error">Error: {error.message}</div>;

  const posts = data?.posts ?? [];

  return (
    <div className="post-list">
      <h1>Recent Posts</h1>
      {posts.length === 0 ? (
        <p>No posts yet. Be the first to write one!</p>
      ) : (
        <div className="posts-grid">
          {posts.map((post) => (
            <PostCard key={post.id} post={post} />
          ))}
        </div>
      )}
    </div>
  );
}
```

### 5.2 PostCard

Create `frontend/src/components/PostCard.jsx`:

```javascript
import { Link } from "react-router-dom";

export default function PostCard({ post }) {
  return (
    <div className="post-card">
      <h2>{post.title}</h2>
      <p>{post.content.slice(0, 150)}…</p>
      <div className="post-meta">
        <span>By {post.authorName}</span>
        <span>{new Date(post.createdAt).toLocaleDateString()}</span>
      </div>
      <div className="post-footer">
        <span>{post.likeCount} likes · {post.commentCount} comments</span>
        <Link to={`/post/${post.id}`}>Read more →</Link>
      </div>
    </div>
  );
}
```

### 5.3 PostDetail

Create `frontend/src/components/PostDetail.jsx`:

```javascript
import { useQuery } from "@apollo/client";
import { useParams } from "react-router-dom";
import { GET_POST } from "../queries";
import CommentSection from "./CommentSection";
import LikeButton from "./LikeButton";

export default function PostDetail() {
  const { postId } = useParams();
  const { loading, error, data } = useQuery(GET_POST, {
    variables: { id: postId },
  });

  if (loading) return <div className="loading">Loading post…</div>;
  if (error) return <div className="error">Error: {error.message}</div>;

  const post = data?.post;
  if (!post) return <div className="not-found">Post not found</div>;

  return (
    <article className="post-detail">
      <h1>{post.title}</h1>
      <div className="post-info">
        <span>{post.authorName}</span>
        <span>{new Date(post.createdAt).toLocaleString()}</span>
      </div>
      <div className="post-body">{post.content}</div>

      <div className="post-actions">
        <LikeButton postId={post.id} likeCount={post.likeCount} />
        <span>{post.commentCount} comments</span>
      </div>

      <CommentSection postId={post.id} />
    </article>
  );
}
```

### 5.4 CommentSection

Create `frontend/src/components/CommentSection.jsx`. The submit handler reads the union result
and surfaces a `MutationError.message` if the backend rejected the write:

```javascript
import { useQuery, useMutation } from "@apollo/client";
import { useState } from "react";
import { GET_COMMENTS, CREATE_COMMENT } from "../queries";

// In a real app this comes from your auth/session.
const CURRENT_USER_ID = "00000000-0000-0000-0000-000000000000";

export default function CommentSection({ postId }) {
  const [text, setText] = useState("");
  const [errorMessage, setErrorMessage] = useState(null);

  const { data, loading } = useQuery(GET_COMMENTS, { variables: { postId } });

  const [createComment] = useMutation(CREATE_COMMENT, {
    refetchQueries: [{ query: GET_COMMENTS, variables: { postId } }],
  });

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    setErrorMessage(null);

    const { data: result } = await createComment({
      variables: {
        input: { postId, userId: CURRENT_USER_ID, content: text },
      },
    });

    const payload = result.createComment;
    if (payload.__typename === "MutationError") {
      setErrorMessage(payload.message);
      return;
    }
    setText("");
  };

  const comments = data?.comments ?? [];

  return (
    <section className="comment-section">
      <h3>Comments ({comments.length})</h3>

      <form onSubmit={handleSubmit} className="comment-form">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Write a comment…"
          rows={3}
        />
        <button type="submit" disabled={!text.trim()}>
          Post Comment
        </button>
      </form>

      {errorMessage && <p className="error">{errorMessage}</p>}

      {loading ? (
        <p>Loading comments…</p>
      ) : (
        <ul className="comments-list">
          {comments.map((c) => (
            <li key={c.id}>
              <strong>{c.authorName}</strong>
              <span>{new Date(c.createdAt).toLocaleString()}</span>
              <p>{c.content}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
```

### 5.5 LikeButton

Create `frontend/src/components/LikeButton.jsx`. It reads `likeCount` straight off the
`LikeSuccess.post` returned by the mutation:

```javascript
import { useMutation } from "@apollo/client";
import { useState } from "react";
import { LIKE_POST, UNLIKE_POST } from "../queries";

const CURRENT_USER_ID = "00000000-0000-0000-0000-000000000000";

export default function LikeButton({ postId, likeCount = 0 }) {
  const [liked, setLiked] = useState(false);
  const [count, setCount] = useState(likeCount);

  const [likePost] = useMutation(LIKE_POST);
  const [unlikePost] = useMutation(UNLIKE_POST);

  const toggle = async () => {
    const mutate = liked ? unlikePost : likePost;
    const { data } = await mutate({
      variables: { postId, userId: CURRENT_USER_ID },
    });

    const payload = liked ? data.unlikePost : data.likePost;
    if (payload.__typename === "MutationError") {
      console.error(payload.message);
      return;
    }
    setCount(payload.post.likeCount);
    setLiked(!liked);
  };

  return (
    <button className={`like-button ${liked ? "liked" : ""}`} onClick={toggle}>
      ♥ {count} {count === 1 ? "like" : "likes"}
    </button>
  );
}
```

---

## Part 6: Wiring the App Together

### 6.1 App.jsx

Create `frontend/src/App.jsx`:

```javascript
import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import { ApolloProvider } from "@apollo/client";
import client from "./apollo-client";
import PostList from "./components/PostList";
import PostDetail from "./components/PostDetail";

export default function App() {
  return (
    <ApolloProvider client={client}>
      <BrowserRouter>
        <nav className="navbar">
          <Link to="/">Blog</Link>
        </nav>
        <main className="container">
          <Routes>
            <Route path="/" element={<PostList />} />
            <Route path="/post/:postId" element={<PostDetail />} />
          </Routes>
        </main>
      </BrowserRouter>
    </ApolloProvider>
  );
}
```

### 6.2 main.jsx

The Vite template generates this; make sure it renders `App`:

```javascript
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

### 6.3 package.json dependencies

After the installs from Part 1, your `frontend/package.json` should include:

```json
{
  "name": "blog-frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@apollo/client": "^3.9.0",
    "graphql": "^16.8.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-router-dom": "^6.22.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.2.0",
    "vite": "^5.0.0"
  }
}
```

---

## Part 7: Running the Full Stack

Open two terminals.

**Terminal 1 — backend:**

```bash
cd fullstack-blog/backend
source .venv/bin/activate
export DATABASE_URL="postgresql://localhost/blog_db"
uvicorn app:app --reload
# http://localhost:8000/graphql
```

**Terminal 2 — frontend:**

```bash
cd fullstack-blog/frontend
npm run dev
# http://localhost:5173
```

Open <http://localhost:5173> and you should see the seeded posts. Click a post to view its
detail, like it, and add a comment.

### End-to-end request flow

```text
1. Browser loads React at http://localhost:5173
2. ApolloProvider gives components the client pointed at /graphql
3. PostList runs GetPosts via Apollo Client
4. Apollo POSTs the query to http://localhost:8000/graphql
5. FraiseQL resolves `posts` → db.find("v_post", ...) → SELECT data FROM v_post
6. PostgreSQL returns the `data` JSONB; FraiseQL shapes it to the requested fields
7. Apollo caches and returns the result; React renders the cards
```

A write (creating a comment) follows the same path but the resolver calls
`db.execute_function("fn_create_comment", {...})`, which runs the insert inside PostgreSQL and
returns a `Success | Error` payload the component branches on.

---

## Part 8: Troubleshooting

### "Network error" / blocked by CORS in the browser console

The backend must allow the React origin. Enable CORS as shown in [Part 3.1](#31-enable-cors-for-the-react-dev-server)
(`cors_enabled=True` with `cors_origins=["http://localhost:5173"]`, or FastAPI's
`CORSMiddleware`). Verify the backend is reachable:

```bash
curl http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ __typename }"}'
```

### `relation "v_post" does not exist`

The schema wasn't loaded. Re-run it:

```bash
psql blog_db -f backend/schema.sql
```

### A query returns `null` for a field

The field name in the GraphQL query must match the camelCase form of the Python field (and the
key inside the view's `data` JSONB). For example the Python field `author_name` is `authorName`
in GraphQL and `'authorName'` in `jsonb_build_object(...)`.

### A component shows "Loading…" forever

The query is erroring. Always render the `error` branch from `useQuery`:

```javascript
const { loading, error, data } = useQuery(GET_POSTS);
if (error) {
  console.error("GraphQL error:", error);
  return <div>Error: {error.message}</div>;
}
```

---

## Part 9: Next Steps

- **Authentication** — protect resolvers with `@fraiseql.query(authorizer=...)` and read the
  user from `info.context["user"]`. Forward the JWT from Apollo Client by adding an auth header
  to the `HttpLink`. See the [authentication guide](../advanced/authentication.md).
- **Subscriptions** — stream live updates (new comments, like counts) with
  `@fraiseql.subscription` over WebSocket. See the [subscriptions docs](../architecture/realtime/subscriptions.md).
- **Caching** — FraiseQL ships PostgreSQL-backed result caching with cascade invalidation.
- **Heavy nested reads** — for deeply nested data, project into a table-backed `tv_*` view
  refreshed by triggers/functions, and point the type's `sql_source` at it.

The key idea: **you write Python decorators and SQL views/functions; FraiseQL assembles the
GraphQL schema in memory at startup and serves it over FastAPI**. There is no build step and no
separate server — `uvicorn app:app` is the whole backend.

---

## Feedback

Have questions or improvements? See [the beginner learning path](./beginner-path.md) for next steps.

**Back to:** [Tutorials: Beginner Path](./beginner-path.md) | [Documentation Home](../index.md)

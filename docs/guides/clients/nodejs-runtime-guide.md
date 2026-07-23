<!-- Skip to main content -->
---

title: Consuming a FraiseQL API from Node.js
description: Complete guide for querying a FraiseQL GraphQL server from Node.js backend services using standard GraphQL clients (graphql-request, Apollo Client, graphql-ws).
keywords: ["debugging", "implementation", "best-practices", "deployment", "tutorial"]
tags: ["documentation", "reference"]
---

# Consuming a FraiseQL API from Node.js

**Status:** ✅ Production Ready
**Audience:** Backend developers, Node.js API servers
**Reading Time:** 25-30 minutes
**Last Updated:** 2026-06-19

FraiseQL v1 is a **Python runtime GraphQL framework for PostgreSQL**. Your FraiseQL
app (built with `create_fraiseql_app` and served by Uvicorn/FastAPI) exposes a
**standard GraphQL endpoint over HTTP** at `/graphql`, plus
**GraphQL-over-WebSocket** for subscriptions (the server speaks the
`graphql-transport-ws` protocol).

There is **no FraiseQL-specific Node.js client** — and you don't need one. Any
standard GraphQL client works. This guide shows how to consume a FraiseQL endpoint
from Node.js using well-known, battle-tested libraries:

| Concern | Library | Why |
|---------|---------|-----|
| Queries & mutations over HTTP | [`graphql-request`](https://github.com/jasonkuhrt/graphql-request) | Lightweight, minimal, perfect for backend-to-backend calls |
| Queries & mutations (full client) | [`@apollo/client`](https://www.apollographql.com/docs/react/) | Caching, normalized store, richer ecosystem |
| Subscriptions over WebSocket | [`graphql-ws`](https://github.com/enisdenjo/graphql-ws) | Implements `graphql-transport-ws`, the protocol FraiseQL speaks |
| Connection reuse / pooling | [`undici`](https://github.com/nodejs/undici) `Agent` | HTTP keep-alive and connection pooling at the transport layer |

We use **`graphql-request`** as the lightweight default throughout and show
**Apollo Client** as an alternative where it adds value.

---

## Installation & Setup

### Prerequisites

- Node.js 18+ (for built-in `fetch` and `WebSocket`-friendly tooling)
- A running FraiseQL server (`uvicorn app:app`, exposing `http://localhost:8000/graphql`)
- A package manager (npm, yarn, or pnpm)

### Install Packages

```bash
# Lightweight HTTP client (default in this guide)
npm install graphql-request graphql

# WebSocket subscriptions
npm install graphql-ws ws

# (Optional) connection pooling / HTTP keep-alive
npm install undici
```

For the Apollo alternative:

```bash
npm install @apollo/client graphql
```

### Create a Client Instance (graphql-request)

```typescript
import { GraphQLClient } from 'graphql-request';

export const client = new GraphQLClient('http://localhost:8000/graphql', {
  // Optional: a default timeout via AbortSignal (Node 18+)
  // fetch is used under the hood; see the keep-alive section to customize it.
});

export default client;
```

### With Authentication

FraiseQL reads auth from standard HTTP headers (typically a `Bearer` token).
Set them once on the client, or per request:

```typescript
import { GraphQLClient } from 'graphql-request';

export const client = new GraphQLClient('http://localhost:8000/graphql', {
  headers: {
    Authorization: `Bearer ${process.env.FRAISEQL_TOKEN}`,
    'X-API-Key': process.env.API_KEY ?? '',
  },
});

export default client;
```

To set headers dynamically (e.g. per incoming request), use `setHeader` or pass
headers to the individual `request` call:

```typescript
client.setHeader('Authorization', `Bearer ${token}`);

// or per-request:
await client.request(GET_USERS, {}, { Authorization: `Bearer ${token}` });
```

### Alternative: Apollo Client

Apollo runs fine in a Node.js process (no React required). Use it when you want a
normalized cache or the broader Apollo tooling:

```typescript
import {
  ApolloClient,
  InMemoryCache,
  HttpLink,
} from '@apollo/client/core';

const httpLink = new HttpLink({
  uri: 'http://localhost:8000/graphql',
  headers: {
    Authorization: `Bearer ${process.env.FRAISEQL_TOKEN}`,
  },
  // Node 18+ has global fetch; otherwise pass `fetch` explicitly.
});

export const apolloClient = new ApolloClient({
  link: httpLink,
  cache: new InMemoryCache(),
});
```

---

## Queries

### Basic Query

```typescript
import client from './client';
import { gql } from 'graphql-request';

const GET_USERS = gql`
  query GetUsers {
    users {
      id
      name
      email
    }
  }
`;

async function fetchUsers() {
  try {
    const data = await client.request(GET_USERS);
    console.log('Users:', data.users);
    return data.users;
  } catch (error) {
    console.error('Query failed:', error);
    throw error;
  }
}
```

`graphql-request` returns the `data` object directly and throws on GraphQL errors
(see [Error Handling](#error-handling)).

### Query with Variables

```typescript
const GET_USER_BY_ID = gql`
  query GetUserById($id: ID!) {
    user(id: $id) {
      id
      name
      email
      posts {
        id
        title
      }
    }
  }
`;

async function fetchUserById(userId: string) {
  const data = await client.request(GET_USER_BY_ID, { id: userId });
  return data.user;
}
```

### Typed Queries (TypeScript)

```typescript
import { gql } from 'graphql-request';
import client from './client';

interface User {
  id: string;
  name: string;
  email: string;
}

interface GetUsersResponse {
  users: User[];
}

async function getUsers(): Promise<User[]> {
  const data = await client.request<GetUsersResponse>(GET_USERS);
  return data.users;
}

async function getUserById(id: string): Promise<User> {
  const data = await client.request<{ user: User }>(GET_USER_BY_ID, { id });
  return data.user;
}
```

> For end-to-end type safety against the live schema, generate types with
> [GraphQL Code Generator](https://the-guild.dev/graphql/codegen) pointed at your
> FraiseQL endpoint.

### Per-Request Options (timeout & headers)

`graphql-request` uses `fetch` under the hood, so you control timeouts with an
`AbortSignal` and headers per request:

```typescript
async function fetchUsersWithOptions() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000); // 30s

  try {
    const data = await client.request(
      GET_USERS,
      {},
      { 'X-Request-ID': generateRequestId() }, // per-request headers
    );
    return data.users;
  } finally {
    clearTimeout(timeout);
  }
}
```

> To enforce the abort signal, pass a custom `fetch` to the `GraphQLClient`
> constructor (`{ fetch: (url, opts) => fetch(url, { ...opts, signal: controller.signal }) }`)
> or use the `signal` option supported by your client version.

---

## Mutations

In FraiseQL, mutations call PostgreSQL `fn_` functions on the server and return a
success/error union. From Node.js, a mutation is just a standard GraphQL request.

### Basic Mutation

```typescript
import client from './client';
import { gql } from 'graphql-request';

const CREATE_POST = gql`
  mutation CreatePost($input: CreatePostInput!) {
    createPost(input: $input) {
      ... on CreatePostSuccess {
        post {
          id
          title
          content
          createdAt
        }
      }
      ... on CreatePostError {
        message
        code
      }
    }
  }
`;

interface CreatePostInput {
  title: string;
  content: string;
}

async function createPost(input: CreatePostInput) {
  const data = await client.request(CREATE_POST, { input });
  return data.createPost;
}
```

> FraiseQL mutations typically return a `Success | Error` union. Select the
> `... on XSuccess` and `... on XError` branches so you can handle both outcomes
> without throwing.

### Multiple Mutations

```typescript
const UPDATE_USER = gql`
  mutation UpdateUser($input: UpdateUserInput!) {
    updateUser(input: $input) {
      ... on UpdateUserSuccess {
        user {
          id
          name
        }
      }
      ... on UpdateUserError {
        message
        code
      }
    }
  }
`;

async function updateUserBatch(updates: Array<{ id: string; name: string }>) {
  const results = await Promise.all(
    updates.map((input) => client.request(UPDATE_USER, { input })),
  );

  return results.map((r) => r.updateUser);
}
```

### Mutation with Error Handling

Distinguish **business errors** (the `Error` branch of the union, returned in
`data`) from **transport/GraphQL errors** (thrown by the client):

```typescript
import { ClientError } from 'graphql-request';

async function safeCreatePost(input: CreatePostInput) {
  try {
    const data = await client.request(CREATE_POST, { input });
    const result = data.createPost;

    // Business error returned by the mutation union
    if (result.__typename === 'CreatePostError' || 'message' in result && !('post' in result)) {
      console.error('Mutation rejected:', result.message, result.code);
      return null;
    }

    return result.post;
  } catch (error) {
    // Transport-level or GraphQL execution error
    if (error instanceof ClientError) {
      console.error('GraphQL error:', error.response.errors);
    } else {
      console.error('Network error:', (error as Error).message);
    }
    throw error;
  }
}
```

> Add `__typename` to your union selections to make branch detection explicit.

---

## Subscriptions

FraiseQL serves subscriptions over **GraphQL-over-WebSocket** using the
`graphql-transport-ws` protocol. The standard client for this protocol is
[`graphql-ws`](https://github.com/enisdenjo/graphql-ws). On the server side, a
`@fraiseql.subscription` resolver is an async generator that yields values
(commonly backed by PostgreSQL `LISTEN/NOTIFY`); the client receives each yielded
value as it arrives.

### Create a WebSocket Client

```typescript
import { createClient } from 'graphql-ws';
import WebSocket from 'ws'; // Node needs an explicit WebSocket implementation

const wsClient = createClient({
  url: 'ws://localhost:8000/graphql',
  webSocketImpl: WebSocket,
  connectionParams: {
    // Auth is sent in the connection init payload
    Authorization: `Bearer ${process.env.FRAISEQL_TOKEN}`,
  },
  retryAttempts: 5,
});
```

### Subscribe to an Event Stream

```typescript
const ON_POST_CREATED = /* GraphQL */ `
  subscription OnPostCreated {
    postCreated {
      id
      title
      author {
        name
      }
    }
  }
`;

function subscribeToPosts() {
  const unsubscribe = wsClient.subscribe(
    { query: ON_POST_CREATED },
    {
      next: (event) => {
        console.log('New post:', event.data?.postCreated);
      },
      error: (err) => {
        console.error('Subscription error:', err);
      },
      complete: () => {
        console.log('Subscription complete');
      },
    },
  );

  // Call unsubscribe() to stop receiving events
  return unsubscribe;
}
```

### Async-Iterator Style

`graphql-ws` can also be consumed as an async iterable, which pairs well with
`for await`:

```typescript
async function consumePosts() {
  const subscription = wsClient.iterate({ query: ON_POST_CREATED });

  for await (const event of subscription) {
    if (event.data?.postCreated) {
      console.log('New post:', event.data.postCreated);
    }
  }
}
```

> Reconnection, keep-alive pings, and the `connection_init` handshake are handled
> by `graphql-ws` automatically. Use `connectionParams` (not HTTP headers) to pass
> auth, since the WebSocket upgrade can't carry custom headers in browsers.

---

## Running Independent Requests Concurrently

There is no special batch endpoint — FraiseQL exposes a standard GraphQL HTTP
endpoint. To run multiple independent operations efficiently, fire them
concurrently with `Promise.all` (each is its own HTTP request, multiplexed over a
kept-alive connection):

```typescript
const GET_STATS = gql`
  query GetStats {
    userCount
    postCount
    commentCount
  }
`;

const GET_RECENT_POSTS = gql`
  query GetRecentPosts {
    posts(limit: 10) {
      id
      title
      createdAt
    }
  }
`;

async function fetchDashboardData() {
  const [stats, recent] = await Promise.all([
    client.request(GET_STATS),
    client.request(GET_RECENT_POSTS),
  ]);

  return {
    stats,
    recentPosts: recent.posts,
  };
}
```

> If you want to combine several reads into a **single** round trip, write one
> GraphQL operation that selects all the fields you need (the server resolves them
> from your `v_`/`tv_` PostgreSQL views).

---

## Connection Pooling & Caching

### HTTP Keep-Alive with an undici Agent

"Connection pooling" for an HTTP GraphQL client means **reusing TCP/TLS
connections** via HTTP keep-alive — not a bespoke pool object. In Node.js, the
[`undici`](https://github.com/nodejs/undici) `Agent` gives you fine-grained control
over connection reuse and pool size:

```typescript
import { Agent, fetch as undiciFetch } from 'undici';
import { GraphQLClient } from 'graphql-request';

// Reuse up to 10 connections per origin, keep them alive for 60s
const agent = new Agent({
  connections: 10,
  keepAliveTimeout: 60_000,
  keepAliveMaxTimeout: 300_000,
});

export const client = new GraphQLClient('http://localhost:8000/graphql', {
  // Route graphql-request's fetch through the pooled agent
  fetch: ((input, init) =>
    undiciFetch(input as string, { ...init, dispatcher: agent })) as typeof fetch,
});
```

To make a pooled agent the global default for `fetch`, you can also call
`setGlobalDispatcher(agent)` from `undici`.

### Response Caching

`graphql-request` itself does not cache. Two common options:

1. **Apollo Client's `InMemoryCache`** — automatic normalized caching keyed by
   query + variables:

   ```typescript
   import { ApolloClient, InMemoryCache, HttpLink, gql } from '@apollo/client/core';

   const apolloClient = new ApolloClient({
     link: new HttpLink({ uri: 'http://localhost:8000/graphql' }),
     cache: new InMemoryCache(),
   });

   const GET_USERS = gql`
     query GetUsers {
       users { id name email }
     }
   `;

   // First call hits the server; subsequent calls can be served from cache
   // depending on the fetch policy.
   const { data } = await apolloClient.query({ query: GET_USERS });
   ```

2. **A small TTL cache in front of `graphql-request`** for simple backend use:

   ```typescript
   const cache = new Map<string, { value: unknown; expires: number }>();

   async function cachedRequest<T>(key: string, ttlMs: number, run: () => Promise<T>): Promise<T> {
     const hit = cache.get(key);
     if (hit && hit.expires > Date.now()) return hit.value as T;

     const value = await run();
     cache.set(key, { value, expires: Date.now() + ttlMs });
     return value;
   }

   // Usage
   const users = await cachedRequest('users', 60_000, () => client.request(GET_USERS));
   ```

> FraiseQL also performs PostgreSQL-backed result caching **on the server** (with
> cascade invalidation). Server-side caching and client-side caching are
> complementary.

---

## Error Handling

### GraphQL vs. Network Errors

`graphql-request` throws a `ClientError` when the response contains GraphQL
errors, and a regular `Error` (or `fetch` failure) for transport problems:

```typescript
import { ClientError } from 'graphql-request';

async function resilientQuery() {
  try {
    return await client.request(GET_USERS);
  } catch (error) {
    if (error instanceof ClientError) {
      // The server responded, but with GraphQL errors
      console.error('GraphQL errors:', error.response.errors);
      console.error('Partial data:', error.response.data);
    } else if (error instanceof DOMException && error.name === 'AbortError') {
      console.error('Request timed out');
    } else {
      // DNS, connection refused, TLS, etc.
      console.error('Network error:', (error as Error).message);
    }
    throw error;
  }
}
```

### Retry with Backoff

```typescript
async function requestWithRetry<T>(
  run: () => Promise<T>,
  maxRetries = 3,
): Promise<T> {
  let lastError: unknown;

  for (let i = 0; i < maxRetries; i++) {
    try {
      return await run();
    } catch (error) {
      lastError = error;

      // Exponential backoff: 1s, 2s, 4s
      const delay = 2 ** i * 1000;
      console.log(`Retry attempt ${i + 1} after ${delay}ms`);
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }

  throw lastError;
}

// Usage
const users = await requestWithRetry(() => client.request(GET_USERS));
```

> Retry **idempotent** reads freely. For mutations, prefer server-side idempotency
> keys or only retry on clearly transient transport failures.

---

## Integration with Express.js

### GraphQL Pass-Through Endpoint

```typescript
import express from 'express';
import client from './client';

const app = express();
app.use(express.json());

// Generic GraphQL pass-through to the FraiseQL server
app.post('/api/graphql', async (req, res) => {
  const { query, variables } = req.body;

  try {
    const data = await client.request(query, variables);
    res.json({ data });
  } catch (error) {
    res.status(500).json({ errors: [{ message: (error as Error).message }] });
  }
});

// Specific data endpoint
app.get('/api/users', async (_req, res) => {
  try {
    const users = await getUsers();
    res.json(users);
  } catch (error) {
    res.status(500).json({ error: (error as Error).message });
  }
});

app.listen(3000);
```

### Middleware Injecting a Request-Scoped Client

When each incoming request carries its own auth token, build a request-scoped
client so the user's token is forwarded to FraiseQL:

```typescript
import { Request, Response, NextFunction } from 'express';
import { GraphQLClient } from 'graphql-request';

export function fraiseqlMiddleware(req: Request, _res: Response, next: NextFunction) {
  const token = req.header('authorization') ?? '';
  req.fraiseqlClient = new GraphQLClient('http://localhost:8000/graphql', {
    headers: token ? { Authorization: token } : {},
  });
  next();
}

// Usage
app.use(fraiseqlMiddleware);

app.get('/api/user/:id', async (req, res) => {
  const data = await req.fraiseqlClient.request(GET_USER_BY_ID, { id: req.params.id });
  res.json(data.user);
});
```

---

## Integration with Fastify

```typescript
import Fastify from 'fastify';
import client from './client';

const fastify = Fastify();

fastify.post('/graphql', async (request) => {
  const { query, variables } = request.body as { query: string; variables?: Record<string, unknown> };

  try {
    return { data: await client.request(query, variables) };
  } catch (error) {
    throw fastify.httpErrors.internalServerError((error as Error).message);
  }
});

fastify.get('/users', async () => {
  const data = await client.request(GET_USERS);
  return data.users;
});

fastify.listen({ port: 3000 });
```

---

## Integration with Nest.js

### Create a Service

```typescript
import { Injectable } from '@nestjs/common';
import { GraphQLClient } from 'graphql-request';
import { GET_USERS, GET_USER_BY_ID } from './queries';

@Injectable()
export class UsersService {
  private readonly client = new GraphQLClient(
    process.env.FRAISEQL_URL ?? 'http://localhost:8000/graphql',
  );

  async getUsers() {
    const data = await this.client.request(GET_USERS);
    return data.users;
  }

  async getUserById(id: string) {
    const data = await this.client.request(GET_USER_BY_ID, { id });
    return data.user;
  }
}
```

### Create a Controller

```typescript
import { Controller, Get, Param } from '@nestjs/common';
import { UsersService } from './users.service';

@Controller('api/users')
export class UsersController {
  constructor(private readonly usersService: UsersService) {}

  @Get()
  getUsers() {
    return this.usersService.getUsers();
  }

  @Get(':id')
  getUserById(@Param('id') id: string) {
    return this.usersService.getUserById(id);
  }
}
```

---

## Pagination

FraiseQL queries accept the arguments your `@query` resolvers and views define
(commonly `limit`/`offset`, or cursor arguments on a `connection` type). From
Node.js, pagination is just passing those variables:

### Offset Pagination

```typescript
const GET_POSTS_PAGE = gql`
  query GetPostsPage($limit: Int!, $offset: Int!) {
    posts(limit: $limit, offset: $offset) {
      id
      title
      createdAt
    }
  }
`;

async function fetchPostsPage(page: number, pageSize = 20) {
  const data = await client.request(GET_POSTS_PAGE, {
    limit: pageSize,
    offset: page * pageSize,
  });
  return data.posts;
}
```

### Iterating All Pages

```typescript
async function* iterateAllPosts(pageSize = 50) {
  let offset = 0;
  for (;;) {
    const data = await client.request(GET_POSTS_PAGE, { limit: pageSize, offset });
    const page = data.posts as Array<{ id: string }>;
    if (page.length === 0) break;
    yield* page;
    offset += page.length;
    if (page.length < pageSize) break;
  }
}

// Usage
for await (const post of iterateAllPosts()) {
  console.log(post.id);
}
```

> If a type is exposed as a Relay-style `connection`, paginate with
> `first`/`after` cursors and read `pageInfo.hasNextPage` / `endCursor` instead.

---

## Testing

### Unit Tests with a Mocked Client

Inject the client so you can swap in a mock. With `graphql-request`, mock the
`request` method:

```typescript
import { jest } from '@jest/globals';
import { UsersService } from './users.service';

describe('UsersService', () => {
  it('should fetch users', async () => {
    const mockRequest = jest.fn().mockResolvedValueOnce({
      users: [{ id: '1', name: 'Alice', email: 'alice@example.com' }],
    });

    const service = new UsersService();
    // Replace the internal client with a mock
    (service as any).client = { request: mockRequest };

    const users = await service.getUsers();

    expect(users).toHaveLength(1);
    expect(users[0].name).toBe('Alice');
    expect(mockRequest).toHaveBeenCalledTimes(1);
  });
});
```

### Integration Tests Against a Real Server

```typescript
import { describe, it, expect } from '@jest/globals';
import client from './client';

describe('FraiseQL Integration', () => {
  it('should query users from a real server', async () => {
    const data = await client.request(GET_USERS);
    expect(Array.isArray(data.users)).toBe(true);
  });

  it('should create a post', async () => {
    const data = await client.request(CREATE_POST, {
      input: { title: 'Test Post', content: 'Test Content' },
    });

    const result = data.createPost;
    expect(result.post?.id).toBeDefined();
    expect(result.post?.title).toBe('Test Post');
  });
});
```

> Point integration tests at a disposable FraiseQL instance backed by a test
> PostgreSQL database, and roll back / truncate between runs.

---

## Performance Tips

### Request Only What You Need

GraphQL lets you select exactly the fields you use. FraiseQL resolves the selected
fields from the `data` JSONB of your `v_`/`tv_` views, so narrower selections mean
less work end to end. Avoid over-fetching nested relations you won't render.

### Reuse Connections

Keep a single long-lived `GraphQLClient` (and a single `undici` `Agent`) per
process rather than constructing one per request. This maximizes HTTP keep-alive
reuse — see [Connection Pooling](#connection-pooling--caching).

### Deduplicate Concurrent Identical Reads

For hot reads that may be requested concurrently, coalesce in-flight requests so
identical queries share one network call:

```typescript
const inFlight = new Map<string, Promise<unknown>>();

function dedupeRequest<T>(key: string, run: () => Promise<T>): Promise<T> {
  const existing = inFlight.get(key);
  if (existing) return existing as Promise<T>;

  const promise = run().finally(() => inFlight.delete(key));
  inFlight.set(key, promise);
  return promise as Promise<T>;
}

// Both callers share a single network request
const [a, b] = await Promise.all([
  dedupeRequest('users', () => client.request(GET_USERS)),
  dedupeRequest('users', () => client.request(GET_USERS)),
]);
```

> Apollo Client performs in-flight query deduplication automatically when you use
> the same query + variables.

---

## See Also

**Related Guides:**

- **[Real-Time Patterns](../patterns.md)** - Subscription architecture
- **[Authentication & Authorization](../authorization-quick-start.md)** - Securing queries
- **[Production Deployment](../production-deployment.md)** - Running FraiseQL

**GraphQL Client Documentation:**

- **[graphql-request](https://github.com/jasonkuhrt/graphql-request)** - Minimal HTTP GraphQL client
- **[Apollo Client](https://www.apollographql.com/docs/react/)** - Full-featured GraphQL client
- **[graphql-ws](https://github.com/enisdenjo/graphql-ws)** - GraphQL-over-WebSocket protocol client
- **[undici](https://github.com/nodejs/undici)** - Node.js HTTP client with connection pooling

**Server Framework Guides:**

- **[Express.js Documentation](https://expressjs.com/)**
- **[Fastify Documentation](https://www.fastify.io/)**
- **[Nest.js Documentation](https://docs.nestjs.com/)**

---

**Last Updated:** 2026-06-19

<!-- Skip to main content -->
---

title: React with Apollo Client for FraiseQL
description: Complete guide for querying FraiseQL servers from React applications using Apollo Client.
keywords: ["debugging", "implementation", "best-practices", "deployment", "tutorial"]
tags: ["documentation", "reference"]
---

# React with Apollo Client for FraiseQL

**Status:** ✅ Production Ready
**Audience:** React developers
**Reading Time:** 25-30 minutes
**Last Updated:** 2026-02-05

Complete guide for querying FraiseQL servers from React applications using Apollo Client.

---

## Installation & Setup

### Prerequisites

- React 16.8+ (hooks support)
- Node.js 16+
- FraiseQL server running (see [Full-Stack Examples](../../examples/))

### Install Dependencies

```bash
<!-- Code example in BASH -->
npm install @apollo/client graphql subscriptions-transport-ws
```text
<!-- Code example in TEXT -->

Or with Yarn:

```bash
<!-- Code example in BASH -->
yarn add @apollo/client graphql subscriptions-transport-ws
```text
<!-- Code example in TEXT -->

### Initialize Apollo Client

```typescript
<!-- Code example in TypeScript -->
import { ApolloClient, InMemoryCache, HttpLink, from } from '@apollo/client';
import { onError } from '@apollo/client/link/error';
import { WebSocketLink } from '@apollo/client/link/ws';
import { getMainDefinition } from '@apollo/client/utilities';

// Error handling link
const errorLink = onError(({ graphQLErrors, networkError }) => {
  if (graphQLErrors) {
    graphQLErrors.forEach(({ message, locations, path }) =>
      console.error(`[GraphQL error]: Message: ${message}, Path: ${path}`, locations)
    );
  }
  if (networkError) console.error(`[Network error]: ${networkError}`);
});

// HTTP link for queries/mutations
const httpLink = new HttpLink({
  uri: 'http://localhost:5000/graphql',
  credentials: 'include', // Send cookies for authentication
});

// WebSocket link for subscriptions
const wsLink = new WebSocketLink({
  uri: 'ws://localhost:5000/graphql',
  options: {
    reconnect: true,
    connectionParams: () => ({
      authorization: localStorage.getItem('token') || '',
    }),
  },
});

// Choose link based on operation type
const splitLink = from([
  errorLink,
  new (typeof window !== 'undefined' ? require('@apollo/client').split : null)?.(
    ({ query }) => {
      const definition = getMainDefinition(query);
      return (
        definition.kind === 'OperationDefinition' &&
        definition.operation === 'subscription'
      );
    },
    wsLink,
    httpLink
  ) || httpLink,
]);

// Create Apollo Client
const client = new ApolloClient({
  link: splitLink,
  cache: new InMemoryCache(),
  defaultOptions: {
    watchQuery: {
      fetchPolicy: 'cache-and-network',
    },
  },
});

export default client;
```text
<!-- Code example in TEXT -->

### Wrap App with ApolloProvider

```typescript
<!-- Code example in TypeScript -->
import { ApolloProvider } from '@apollo/client';
import client from './apolloClient';
import App from './App';

function Root() {
  return (
    <ApolloProvider client={client}>
      <App />
    </ApolloProvider>
  );
}

export default Root;
```text
<!-- Code example in TEXT -->

---

## Queries

### Basic Query Hook

```typescript
<!-- Code example in TypeScript -->
import { useQuery, gql } from '@apollo/client';

const GET_USERS = gql`
  query GetUsers {
    users {
      id
      name
      email
    }
  }
`;

export function UserList() {
  const { data, loading, error } = useQuery(GET_USERS);

  if (loading) return <div>Loading...</div>;
  if (error) return <div>Error: {error.message}</div>;

  return (
    <ul>
      {data?.users?.map((user) => (
        <li key={user.id}>{user.name} ({user.email})</li>
      ))}
    </ul>
  );
}
```text
<!-- Code example in TEXT -->

### Query with Variables

```typescript
<!-- Code example in TypeScript -->
import { useQuery, gql } from '@apollo/client';

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

interface UserDetailProps {
  userId: string;
}

export function UserDetail({ userId }: UserDetailProps) {
  const { data, loading, error } = useQuery(GET_USER_BY_ID, {
    variables: { id: userId },
  });

  if (loading) return <div>Loading...</div>;
  if (error) return <div>Error: {error.message}</div>;

  return (
    <div>
      <h1>{data?.user?.name}</h1>
      <p>Email: {data?.user?.email}</p>
      <h2>Posts:</h2>
      <ul>
        {data?.user?.posts?.map((post) => (
          <li key={post.id}>{post.title}</li>
        ))}
      </ul>
    </div>
  );
}
```text
<!-- Code example in TEXT -->

### Pagination Pattern

```typescript
<!-- Code example in TypeScript -->
const GET_POSTS_PAGINATED = gql`
  query GetPostsPaginated($limit: Int!, $offset: Int!) {
    posts(limit: $limit, offset: $offset) {
      id
      title
      createdAt
    }
    postsCount
  }
`;

export function PostList() {
  const [page, setPage] = useState(1);
  const pageSize = 10;

  const { data, loading, error, fetchMore } = useQuery(
    GET_POSTS_PAGINATED,
    {
      variables: { limit: pageSize, offset: 0 },
    }
  );

  const handleLoadMore = () => {
    fetchMore({
      variables: {
        offset: page * pageSize,
      },
      updateQuery: (prev, { fetchMoreResult }) => {
        if (!fetchMoreResult) return prev;
        return {
          posts: [...(prev.posts || []), ...(fetchMoreResult.posts || [])],
          postsCount: fetchMoreResult.postsCount,
        };
      },
    });
    setPage(page + 1);
  };

  if (loading) return <div>Loading...</div>;

  return (
    <div>
      <ul>
        {data?.posts?.map((post) => (
          <li key={post.id}>{post.title}</li>
        ))}
      </ul>
      <button onClick={handleLoadMore}>Load More</button>
      <p>Loaded {data?.posts?.length} of {data?.postsCount}</p>
    </div>
  );
}
```text
<!-- Code example in TEXT -->

### Fetch Policies

```typescript
<!-- Code example in TypeScript -->
// cache-first: Return from cache if available (default for most queries)
useQuery(GET_USERS, { fetchPolicy: 'cache-first' });

// cache-and-network: Return from cache, then refetch in background
useQuery(GET_USERS, { fetchPolicy: 'cache-and-network' });

// cache-only: Only use cache, never fetch
useQuery(GET_USERS, { fetchPolicy: 'cache-only' });

// network-only: Always fetch from server
useQuery(GET_USERS, { fetchPolicy: 'network-only' });

// no-cache: Don't use cache at all
useQuery(GET_USERS, { fetchPolicy: 'no-cache' });
```text
<!-- Code example in TEXT -->

---

## Mutations

### Basic Mutation Hook

```typescript
<!-- Code example in TypeScript -->
import { useMutation, gql } from '@apollo/client';

const CREATE_POST = gql`
  mutation CreatePost($title: String!, $content: String!) {
    createPost(title: $title, content: $content) {
      id
      title
      content
      createdAt
    }
  }
`;

export function CreatePostForm() {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');

  const [createPost, { loading, error }] = useMutation(CREATE_POST);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const result = await createPost({
        variables: { title, content },
      });
      console.log('Post created:', result.data?.createPost);
      setTitle('');
      setContent('');
    } catch (err) {
      console.error('Error creating post:', err);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Post title"
      />
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder="Post content"
      />
      <button type="submit" disabled={loading}>
        {loading ? 'Creating...' : 'Create Post'}
      </button>
      {error && <div className="error">{error.message}</div>}
    </form>
  );
}
```text
<!-- Code example in TEXT -->

### Update Cache After Mutation

```typescript
<!-- Code example in TypeScript -->
const UPDATE_USER = gql`
  mutation UpdateUser($id: ID!, $name: String!) {
    updateUser(id: $id, name: $name) {
      id
      name
      email
    }
  }
`;

export function EditUserName({ userId, currentName }: any) {
  const [newName, setNewName] = useState(currentName);

  const [updateUser] = useMutation(UPDATE_USER, {
    update(cache, { data: { updateUser } }) {
      // Update cache directly
      cache.modify({
        fields: {
          users(existingUsers = []) {
            return existingUsers.map((user: any) =>
              user.id === updateUser.id ? updateUser : user
            );
          },
        },
      });
    },
  });

  const handleSave = async () => {
    await updateUser({
      variables: { id: userId, name: newName },
    });
  };

  return (
    <div>
      <input
        value={newName}
        onChange={(e) => setNewName(e.target.value)}
      />
      <button onClick={handleSave}>Save</button>
    </div>
  );
}
```text
<!-- Code example in TEXT -->

### Optimistic Response

```typescript
<!-- Code example in TypeScript -->
const DELETE_POST = gql`
  mutation DeletePost($id: ID!) {
    deletePost(id: $id) {
      id
    }
  }
`;

export function PostActions({ post }: any) {
  const [deletePost] = useMutation(DELETE_POST, {
    optimisticResponse: {
      deletePost: { id: post.id, __typename: 'Post' },
    },
    update(cache, { data }) {
      cache.evict({ id: cache.identify(post) });
    },
  });

  return (
    <button
      onClick={() =>
        deletePost({ variables: { id: post.id } })
      }
    >
      Delete
    </button>
  );
}
```text
<!-- Code example in TEXT -->

---

## Subscriptions

### WebSocket Setup (Already done in Apollo Client initialization)

### Subscribe to Events

```typescript
<!-- Code example in TypeScript -->
import { useSubscription, gql } from '@apollo/client';

const ON_POST_CREATED = gql`
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

export function PostFeed() {
  const { data, loading, error } = useSubscription(ON_POST_CREATED);

  if (loading) return <div>Connecting...</div>;
  if (error) return <div>Error: {error.message}</div>;

  return (
    <div>
      <h2>New post created:</h2>
      {data?.postCreated && (
        <div>
          <h3>{data.postCreated.title}</h3>
          <p>by {data.postCreated.author.name}</p>
        </div>
      )}
    </div>
  );
}
```text
<!-- Code example in TEXT -->

### Handle Subscription Lifecycle

```typescript
<!-- Code example in TypeScript -->
const ON_MESSAGE = gql`
  subscription OnMessage {
    messageReceived {
      id
      text
      user { name }
    }
  }
`;

export function ChatRoom() {
  const [messages, setMessages] = useState<any[]>([]);
  const { data, loading, error } = useSubscription(ON_MESSAGE);

  useEffect(() => {
    if (data?.messageReceived) {
      setMessages((prev) => [...prev, data.messageReceived]);
    }
  }, [data?.messageReceived]);

  return (
    <div>
      <div className="messages">
        {messages.map((msg) => (
          <div key={msg.id}>
            <strong>{msg.user.name}:</strong> {msg.text}
          </div>
        ))}
      </div>
    </div>
  );
}
```text
<!-- Code example in TEXT -->

---

## Error Handling

### Global Error Handler

```typescript
<!-- Code example in TypeScript -->
const errorLink = onError(({ graphQLErrors, networkError, operation, forward }) => {
  if (graphQLErrors) {
    for (const err of graphQLErrors) {
      if (err.extensions?.code === 'UNAUTHENTICATED') {
        // Handle auth error - redirect to login
        localStorage.removeItem('token');
        window.location.href = '/login';
      }

      if (err.extensions?.code === 'FORBIDDEN') {
        console.error('Access denied:', err.message);
      }

      if (err.extensions?.code === 'VALIDATION_ERROR') {
        console.error('Validation failed:', err.message);
      }
    }
  }

  if (networkError) {
    if ('statusCode' in networkError && networkError.statusCode === 401) {
      // Redirect to login
      window.location.href = '/login';
    }

    if ('statusCode' in networkError && networkError.statusCode === 500) {
      console.error('Server error. Please try again later.');
    }
  }
});
```text
<!-- Code example in TEXT -->

### Component-Level Error Handling

```typescript
<!-- Code example in TypeScript -->
export function SafeUserList() {
  const { data, loading, error, refetch } = useQuery(GET_USERS);

  if (error) {
    return (
      <div className="error-container">
        <p>Failed to load users: {error.message}</p>
        <button onClick={() => refetch()}>Try Again</button>
      </div>
    );
  }

  if (loading) return <div>Loading...</div>;

  return (
    <ul>
      {data?.users?.map((user) => (
        <li key={user.id}>{user.name}</li>
      ))}
    </ul>
  );
}
```text
<!-- Code example in TEXT -->

---

## Caching Strategies

### Cache Management

```typescript
<!-- Code example in TypeScript -->
import { useApolloClient } from '@apollo/client';

export function CacheManager() {
  const client = useApolloClient();

  const clearCache = () => {
    client.cache.reset();
  };

  const getCache = (query: any, variables?: any) => {
    return client.cache.readQuery({
      query,
      variables,
    });
  };

  const updateCache = (query: any, variables: any, data: any) => {
    client.cache.writeQuery({
      query,
      variables,
      data,
    });
  };

  return { clearCache, getCache, updateCache };
}
```text
<!-- Code example in TEXT -->

### Custom Cache Policy per Component

```typescript
<!-- Code example in TypeScript -->
export function UserDashboard() {
  // Static user profile - use cache
  const { data: profile } = useQuery(GET_PROFILE, {
    fetchPolicy: 'cache-first',
  });

  // Real-time notifications - always fetch
  const { data: notifications } = useQuery(GET_NOTIFICATIONS, {
    fetchPolicy: 'network-only',
    pollInterval: 5000, // Refetch every 5 seconds
  });

  // Activity feed - cache + refresh
  const { data: activity } = useQuery(GET_ACTIVITY, {
    fetchPolicy: 'cache-and-network',
  });

  return (
    <div>
      <Profile data={profile} />
      <Notifications data={notifications} />
      <Activity data={activity} />
    </div>
  );
}
```text
<!-- Code example in TEXT -->

---

## Performance Optimization

### Query Splitting

```typescript
<!-- Code example in TypeScript -->
// ❌ Bad: Fetch everything at once
const DASHBOARD = gql`
  query Dashboard {
    currentUser { id name profile { bio } }
    notifications { id message }
    recentPosts { id title }
  }
`;

// ✅ Good: Split based on render priority
const GET_USER = gql`query GetUser { currentUser { id name } }`;
const GET_NOTIFICATIONS = gql`query GetNotifications { notifications { id message } }`;
const GET_POSTS = gql`query GetPosts { recentPosts { id title } }`;

// Load user immediately, notifications and posts in background
export function Dashboard() {
  const { data: user } = useQuery(GET_USER, { fetchPolicy: 'cache-first' });
  const { data: notifications } = useQuery(GET_NOTIFICATIONS, { skip: !user });
  const { data: posts } = useQuery(GET_POSTS, { skip: !user });

  return (
    <div>
      <UserInfo data={user} />
      <Suspense fallback="Loading...">
        <Notifications data={notifications} />
        <RecentPosts data={posts} />
      </Suspense>
    </div>
  );
}
```text
<!-- Code example in TEXT -->

### Request Batching

```typescript
<!-- Code example in TypeScript -->
import { BatchHttpLink } from '@apollo/client/link/batch-http';

const batchLink = new BatchHttpLink({
  uri: 'http://localhost:5000/graphql',
  batchInterval: 10, // Batch queries sent within 10ms
  batchMax: 5, // Maximum 5 queries per batch
});
```text
<!-- Code example in TEXT -->

### Lazy Queries

```typescript
<!-- Code example in TypeScript -->
import { useLazyQuery } from '@apollo/client';

export function SearchUsers() {
  const [search, setSearch] = useState('');
  const [executeSearch, { data, loading }] = useLazyQuery(SEARCH_USERS);

  const handleSearch = (term: string) => {
    setSearch(term);
    if (term.length > 2) {
      executeSearch({ variables: { term } });
    }
  };

  return (
    <div>
      <input
        value={search}
        onChange={(e) => handleSearch(e.target.value)}
        placeholder="Search users..."
      />
      {loading && <div>Searching...</div>}
      {data?.users?.map((user) => (
        <div key={user.id}>{user.name}</div>
      ))}
    </div>
  );
}
```text
<!-- Code example in TEXT -->

---

## Testing

### Mock FraiseQL Responses

```typescript
<!-- Code example in TypeScript -->
import { MockedProvider } from '@apollo/client/testing';
import { render, screen } from '@testing-library/react';

const mocks = [
  {
    request: {
      query: GET_USERS,
    },
    result: {
      data: {
        users: [
          { id: '1', name: 'Alice', email: 'alice@example.com' },
          { id: '2', name: 'Bob', email: 'bob@example.com' },
        ],
      },
    },
  },
];

describe('UserList', () => {
  it('renders user list', async () => {
    render(
      <MockedProvider mocks={mocks}>
        <UserList />
      </MockedProvider>
    );

    await screen.findByText('Alice (alice@example.com)');
    expect(screen.getByText('Bob (bob@example.com)')).toBeInTheDocument();
  });
});
```text
<!-- Code example in TEXT -->

### Test Error Handling

```typescript
<!-- Code example in TypeScript -->
const errorMocks = [
  {
    request: { query: GET_USERS },
    error: new Error('Failed to fetch users'),
  },
];

describe('UserList Error Handling', () => {
  it('displays error message', async () => {
    render(
      <MockedProvider mocks={errorMocks}>
        <UserList />
      </MockedProvider>
    );

    await screen.findByText(/Error: Failed to fetch users/);
  });
});
```text
<!-- Code example in TEXT -->

---

## See Also

**Related Guides:**

- **[Full-Stack Python + React Example](../../tutorials/fullstack-python-react.md)**
- **[Real-Time Patterns](../patterns.md)** - Subscription architecture
- **[Authentication & Authorization](../authorization-quick-start.md)** - Securing queries
- **[Production Deployment](../production-deployment.md)** - React app hosting

**Apollo Client Documentation:**

- [Official Apollo Client Docs](https://www.apollographql.com/docs/react/)
- [Apollo Client GitHub](https://github.com/apollographql/apollo-client)

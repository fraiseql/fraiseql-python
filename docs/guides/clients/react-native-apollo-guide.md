<!-- Skip to main content -->
---

title: React Native with Apollo Client for FraiseQL
description: Complete guide for querying FraiseQL servers from React Native mobile applications.
keywords: ["debugging", "implementation", "best-practices", "deployment", "tutorial"]
tags: ["documentation", "reference"]
---

# React Native with Apollo Client for FraiseQL

**Status:** ✅ Production Ready
**Audience:** React Native developers
**Reading Time:** 25-30 minutes
**Last Updated:** 2026-02-05

Complete guide for querying FraiseQL servers from React Native mobile applications.

---

## Installation & Setup

### Prerequisites

- React Native 0.68+
- Node.js 16+
- FraiseQL server running
- iOS: Xcode 14+
- Android: Android Studio, API level 21+

### Add Dependencies

```bash
<!-- Code example in BASH -->
npm install @apollo/client graphql subscriptions-transport-ws
# or
yarn add @apollo/client graphql subscriptions-transport-ws
```text
<!-- Code example in TEXT -->

For async storage:

```bash
<!-- Code example in BASH -->
npm install @react-native-async-storage/async-storage
# Link pod (iOS)
npx pod-install ios
```text
<!-- Code example in TEXT -->

### Configure Apollo Client

```typescript
<!-- Code example in TypeScript -->
// apolloClient.ts
import { ApolloClient, InMemoryCache, HttpLink, from } from '@apollo/client';
import { onError } from '@apollo/client/link/error';
import { WebSocketLink } from '@apollo/client/link/ws';
import { getMainDefinition } from '@apollo/client/utilities';
import AsyncStorage from '@react-native-async-storage/async-storage';

// Error handling
const errorLink = onError(({ graphQLErrors, networkError, operation, forward }) => {
  if (graphQLErrors) {
    graphQLErrors.forEach(({ message, locations, path }) => {
      console.error(`[GraphQL error]: ${message}`, { locations, path });
    });
  }

  if (networkError) {
    if ('statusCode' in networkError && networkError.statusCode === 401) {
      // Handle authentication error - log out user
      AsyncStorage.removeItem('token');
      // Navigation to login screen would go here
    }
    console.error(`[Network error]: ${networkError}`);
  }

  return forward(operation);
});

// HTTP link for queries and mutations
const httpLink = new HttpLink({
  uri: 'http://localhost:5000/graphql',
  fetchOptions: {
    timeout: 10000, // 10 second timeout for mobile networks
  },
  request: async (operation) => {
    const token = await AsyncStorage.getItem('token');
    if (token) {
      operation.setContext((previousContext) => ({
        ...previousContext,
        headers: {
          authorization: `Bearer ${token}`,
        },
      }));
    }
  },
});

// WebSocket link for subscriptions
const wsLink = new WebSocketLink({
  uri: 'ws://localhost:5000/graphql',
  options: {
    reconnect: true,
    inactivityTimeout: 30000,
    connectionParams: async () => ({
      authorization: `Bearer ${await AsyncStorage.getItem('token')}`,
    }),
  },
});

// Split between WebSocket (subscriptions) and HTTP (queries/mutations)
const splitLink = from([
  errorLink,
  split(
    ({ query }) => {
      const definition = getMainDefinition(query);
      return (
        definition.kind === 'OperationDefinition' &&
        definition.operation === 'subscription'
      );
    },
    wsLink,
    httpLink
  ),
]);

// Persistent cache using AsyncStorage
const cache = new InMemoryCache({
  // Optional: add persistent cache layer
});

export const apolloClient = new ApolloClient({
  link: splitLink,
  cache,
  defaultOptions: {
    watchQuery: {
      fetchPolicy: 'cache-and-network',
    },
  },
});
```text
<!-- Code example in TEXT -->

### Setup in App

```typescript
<!-- Code example in TypeScript -->
// App.tsx
import React from 'react';
import { ApolloProvider } from '@apollo/client';
import { apolloClient } from './apolloClient';
import RootNavigator from './navigation/RootNavigator';

export default function App() {
  return (
    <ApolloProvider client={apolloClient}>
      <RootNavigator />
    </ApolloProvider>
  );
}
```text
<!-- Code example in TEXT -->

---

## Queries

### Basic Query Hook

```typescript
<!-- Code example in TypeScript -->
import { useQuery, gql } from '@apollo/client';
import { View, Text, ActivityIndicator, FlatList } from 'react-native';

const GET_USERS = gql`
  query GetUsers {
    users {
      id
      name
      email
    }
  }
`;

interface User {
  id: string;
  name: string;
  email: string;
}

export function UserListScreen() {
  const { data, loading, error } = useQuery<{ users: User[] }>(GET_USERS);

  if (loading) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  if (error) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
        <Text>Error: {error.message}</Text>
      </View>
    );
  }

  return (
    <FlatList
      data={data?.users}
      keyExtractor={(item) => item.id}
      renderItem={({ item }) => (
        <View style={{ padding: 16, borderBottomWidth: 1 }}>
          <Text style={{ fontSize: 16, fontWeight: 'bold' }}>{item.name}</Text>
          <Text style={{ color: '#666' }}>{item.email}</Text>
        </View>
      )}
    />
  );
}
```text
<!-- Code example in TEXT -->

### Query with Variables

```typescript
<!-- Code example in TypeScript -->
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

interface UserDetailScreenProps {
  route: { params: { userId: string } };
}

export function UserDetailScreen({ route }: UserDetailScreenProps) {
  const { userId } = route.params;
  const { data, loading, error } = useQuery(GET_USER_BY_ID, {
    variables: { id: userId },
  });

  if (loading) return <ActivityIndicator />;
  if (error) return <Text>Error: {error.message}</Text>;

  const user = data?.user;

  return (
    <ScrollView style={{ flex: 1, padding: 16 }}>
      <Text style={{ fontSize: 24, fontWeight: 'bold' }}>{user?.name}</Text>
      <Text style={{ color: '#666', marginBottom: 16 }}>{user?.email}</Text>

      <Text style={{ fontSize: 18, fontWeight: 'bold', marginTop: 16 }}>
        Posts
      </Text>
      {user?.posts?.map((post: any) => (
        <View key={post.id} style={{ marginTop: 8, paddingLeft: 8 }}>
          <Text>{post.title}</Text>
        </View>
      ))}
    </ScrollView>
  );
}
```text
<!-- Code example in TEXT -->

### Pagination for Mobile

```typescript
<!-- Code example in TypeScript -->
export function PostListScreen() {
  const pageSize = 20;
  const [page, setPage] = useState(0);

  const { data, loading, error, fetchMore } = useQuery(
    GET_POSTS_PAGINATED,
    {
      variables: { limit: pageSize, offset: 0 },
    }
  );

  const handleLoadMore = () => {
    fetchMore({
      variables: {
        offset: (page + 1) * pageSize,
      },
      updateQuery: (prev, { fetchMoreResult }) => {
        if (!fetchMoreResult) return prev;
        setPage(page + 1);
        return {
          posts: [...prev.posts, ...fetchMoreResult.posts],
          postsCount: fetchMoreResult.postsCount,
        };
      },
    });
  };

  if (loading && page === 0) {
    return <ActivityIndicator />;
  }

  return (
    <FlatList
      data={data?.posts}
      keyExtractor={(item) => item.id}
      renderItem={({ item }) => (
        <View style={{ padding: 16, borderBottomWidth: 1 }}>
          <Text style={{ fontSize: 16 }}>{item.title}</Text>
          <Text style={{ color: '#999', fontSize: 12 }}>
            {new Date(item.createdAt).toLocaleDateString()}
          </Text>
        </View>
      )}
      onEndReached={handleLoadMore}
      onEndReachedThreshold={0.8}
      ListFooterComponent={
        loading && page > 0 ? <ActivityIndicator /> : null
      }
    />
  );
}
```text
<!-- Code example in TEXT -->

---

## Mutations

### Basic Mutation

```typescript
<!-- Code example in TypeScript -->
import { useMutation, gql } from '@apollo/client';
import { View, TextInput, TouchableOpacity, Text } from 'react-native';
import { useState } from 'react';

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

export function CreatePostScreen() {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');

  const [createPost, { loading, error }] = useMutation(CREATE_POST);

  const handleCreate = async () => {
    try {
      const result = await createPost({
        variables: { title, content },
      });
      console.log('Post created:', result.data);
      setTitle('');
      setContent('');
      // Navigate back or show success
    } catch (err) {
      console.error('Error:', err);
    }
  };

  return (
    <View style={{ flex: 1, padding: 16 }}>
      <TextInput
        value={title}
        onChangeText={setTitle}
        placeholder="Post title"
        style={{ borderBottomWidth: 1, marginBottom: 16, padding: 8 }}
      />
      <TextInput
        value={content}
        onChangeText={setContent}
        placeholder="Post content"
        multiline
        numberOfLines={6}
        style={{
          borderBottomWidth: 1,
          marginBottom: 16,
          padding: 8,
          textAlignVertical: 'top',
        }}
      />
      <TouchableOpacity
        onPress={handleCreate}
        disabled={loading}
        style={{
          backgroundColor: loading ? '#ccc' : '#007AFF',
          padding: 12,
          borderRadius: 8,
          alignItems: 'center',
        }}
      >
        <Text style={{ color: 'white', fontWeight: 'bold' }}>
          {loading ? 'Creating...' : 'Create Post'}
        </Text>
      </TouchableOpacity>
      {error && <Text style={{ color: 'red', marginTop: 16 }}>{error.message}</Text>}
    </View>
  );
}
```text
<!-- Code example in TEXT -->

### Optimistic Updates

```typescript
<!-- Code example in TypeScript -->
const DELETE_POST = gql`
  mutation DeletePost($id: ID!) {
    deletePost(id: $id) {
      id
    }
  }
`;

export function PostCard({ post, onDelete }: any) {
  const [deletePost] = useMutation(DELETE_POST, {
    optimisticResponse: {
      deletePost: { id: post.id, __typename: 'Post' },
    },
    update(cache, { data }) {
      cache.evict({ id: cache.identify(post) });
    },
  });

  return (
    <View style={{ padding: 16, borderBottomWidth: 1 }}>
      <Text style={{ fontSize: 16 }}>{post.title}</Text>
      <TouchableOpacity
        onPress={() => deletePost({ variables: { id: post.id } })}
        style={{ marginTop: 8, padding: 8 }}
      >
        <Text style={{ color: '#FF3B30' }}>Delete</Text>
      </TouchableOpacity>
    </View>
  );
}
```text
<!-- Code example in TEXT -->

---

## Subscriptions

### Real-Time Updates

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

export function PostFeedScreen() {
  const [posts, setPosts] = useState<any[]>([]);
  const { data, loading, error } = useSubscription(ON_POST_CREATED);

  useEffect(() => {
    if (data?.postCreated) {
      setPosts((prev) => [data.postCreated, ...prev]);
    }
  }, [data?.postCreated]);

  if (loading && posts.length === 0) {
    return <ActivityIndicator />;
  }

  return (
    <FlatList
      data={posts}
      keyExtractor={(item) => item.id}
      renderItem={({ item }) => (
        <View style={{ padding: 16, borderBottomWidth: 1 }}>
          <Text style={{ fontWeight: 'bold' }}>{item.title}</Text>
          <Text style={{ color: '#666', fontSize: 12 }}>
            by {item.author.name}
          </Text>
        </View>
      )}
      ListHeaderComponent={
        error ? (
          <Text style={{ color: 'red', padding: 16 }}>
            Error: {error.message}
          </Text>
        ) : null
      }
    />
  );
}
```text
<!-- Code example in TEXT -->

---

## Error Handling

### Network Error Recovery

```typescript
<!-- Code example in TypeScript -->
export function useNetworkAwareQuery<T>(document: any, options?: any) {
  const { data, loading, error, refetch } = useQuery<T>(document, {
    ...options,
    errorPolicy: 'all',
    notifyOnNetworkStatusChange: true,
  });

  const [isOffline, setIsOffline] = useState(false);

  useEffect(() => {
    const unsubscribe = NetInfo.addEventListener((state) => {
      setIsOffline(!state.isConnected);
      // Automatically retry when connection is restored
      if (state.isConnected && error) {
        refetch();
      }
    });

    return () => unsubscribe();
  }, [error, refetch]);

  return { data, loading, error, refetch, isOffline };
}

// Usage
export function ResilientUserList() {
  const { data, loading, error, isOffline } = useNetworkAwareQuery(GET_USERS);

  if (isOffline) {
    return (
      <View style={{ flex: 1, justifyContent: 'center' }}>
        <Text style={{ textAlign: 'center' }}>No internet connection</Text>
      </View>
    );
  }

  if (error) {
    return (
      <Text style={{ color: 'red', padding: 16 }}>
        Error: {error.message}
      </Text>
    );
  }

  // ... render list
}
```text
<!-- Code example in TEXT -->

---

## Offline Support

### Persist Cache to AsyncStorage

```typescript
<!-- Code example in TypeScript -->
import { persistCache } from 'apollo3-cache-persist';
import AsyncStorage from '@react-native-async-storage/async-storage';

async function createClient() {
  const cache = new InMemoryCache();

  await persistCache({
    cache,
    storage: AsyncStorage,
  });

  return new ApolloClient({
    cache,
    link: httpLink,
  });
}
```text
<!-- Code example in TEXT -->

### Queue Mutations While Offline

```typescript
<!-- Code example in TypeScript -->
export function useOfflineAwareMutation(document: any) {
  const [isOffline, setIsOffline] = useState(false);
  const [queuedMutations, setQueuedMutations] = useState<any[]>([]);

  const [mutate, result] = useMutation(document);

  useEffect(() => {
    const unsubscribe = NetInfo.addEventListener((state) => {
      const offline = !state.isConnected;
      setIsOffline(offline);

      // Process queued mutations when connection is restored
      if (!offline && queuedMutations.length > 0) {
        queuedMutations.forEach(async (mutation) => {
          await mutate({ variables: mutation });
        });
        setQueuedMutations([]);
      }
    });

    return () => unsubscribe();
  }, [queuedMutations, mutate]);

  const offlineAwareMutate = async (variables: any) => {
    if (isOffline) {
      setQueuedMutations((prev) => [...prev, variables]);
      console.log('Mutation queued for when connection is restored');
    } else {
      await mutate({ variables });
    }
  };

  return [offlineAwareMutate, result, queuedMutations] as const;
}
```text
<!-- Code example in TEXT -->

---

## Testing

### Mock Apollo Client for Tests

```typescript
<!-- Code example in TypeScript -->
import { MockedProvider } from '@apollo/client/testing';
import { render } from '@testing-library/react-native';

const mocks = [
  {
    request: {
      query: GET_USERS,
    },
    result: {
      data: {
        users: [
          { id: '1', name: 'Alice', email: 'alice@example.com' },
        ],
      },
    },
  },
];

describe('UserListScreen', () => {
  it('displays users', async () => {
    const { findByText } = render(
      <MockedProvider mocks={mocks}>
        <UserListScreen />
      </MockedProvider>
    );

    const alice = await findByText('Alice');
    expect(alice).toBeTruthy();
  });
});
```text
<!-- Code example in TEXT -->

---

## Platform-Specific Considerations

### iOS Specific

```typescript
<!-- Code example in TypeScript -->
import { Platform } from 'react-native';

// Use NSURLSession for iOS (better for mobile networks)
const httpLink = new HttpLink({
  uri: 'http://localhost:5000/graphql',
  credentials: 'include',
  // iOS automatically handles network requests efficiently
});
```text
<!-- Code example in TEXT -->

### Android Specific

```typescript
<!-- Code example in TypeScript -->
// Handle network changes on Android
import { Platform } from 'react-native';

const wsLink = new WebSocketLink({
  uri: 'ws://localhost:5000/graphql',
  options: {
    reconnect: true,
    // Android may kill background connections
    inactivityTimeout: Platform.OS === 'android' ? 45000 : 30000,
  },
});
```text
<!-- Code example in TEXT -->

---

## Deploy to App Stores

### iOS App Store

```bash
<!-- Code example in BASH -->
# Build for App Store
eas build --platform ios --auto-submit

# Or use Xcode
open ios/YourApp.xcworkspace
# Archive and Upload using Xcode's organizer
```text
<!-- Code example in TEXT -->

### Android Play Store

```bash
<!-- Code example in BASH -->

# Build for Play Store
eas build --platform android --auto-submit

# Or build locally
cd android && ./gradlew bundleRelease
# Upload to Play Console
```text
<!-- Code example in TEXT -->

---

## See Also

**Related Guides:**

- **[React + Apollo Guide](./react-apollo-guide.md)** - Web alternative
- **[Flutter Guide](./flutter-graphql-guide.md)** - Alternative mobile framework
- **[Real-Time Patterns](../patterns.md)** - Subscription architecture
- **[Authentication & Authorization](../authorization-quick-start.md)** - Securing queries

**React Native & Apollo Documentation:**

- [React Native Official Docs](https://reactnative.dev/)
- [Apollo Client for React Native](https://www.apollographql.com/docs/react/)
- [React Native AsyncStorage](https://react-native-async-storage.github.io/async-storage/)

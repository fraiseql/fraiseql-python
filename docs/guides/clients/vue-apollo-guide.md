<!-- Skip to main content -->
---

title: Vue 3 with Apollo Client for FraiseQL
description: Complete guide for querying FraiseQL servers from Vue 3 applications using Apollo Client.
keywords: ["debugging", "implementation", "best-practices", "deployment", "tutorial"]
tags: ["documentation", "reference"]
---

# Vue 3 with Apollo Client for FraiseQL

**Status:** ✅ Production Ready
**Audience:** Vue developers
**Reading Time:** 25-30 minutes
**Last Updated:** 2026-02-05

Complete guide for querying FraiseQL servers from Vue 3 applications using Apollo Client.

---

## Installation & Setup

### Prerequisites

- Vue 3.0+
- Node.js 16+
- FraiseQL server running

### Install Dependencies

```bash
npm install @vue/apollo-composable @apollo/client graphql subscriptions-transport-ws
```

### Create Apollo Client

```typescript
// apollo.config.ts
import { ApolloClient, InMemoryCache, HttpLink, from } from '@apollo/client';
import { onError } from '@apollo/client/link/error';
import { WebSocketLink } from '@apollo/client/link/ws';
import { getMainDefinition } from '@apollo/client/utilities';

const errorLink = onError(({ graphQLErrors, networkError }) => {
  if (graphQLErrors) {
    graphQLErrors.forEach(({ message, locations, path }) => {
      console.error(`[GraphQL error]: ${message}`, { locations, path });
    });
  }
  if (networkError) console.error(`[Network error]: ${networkError}`);
});

const httpLink = new HttpLink({
  uri: 'http://localhost:8000/graphql',
  credentials: 'include',
});

const wsLink = new WebSocketLink({
  uri: 'ws://localhost:8000/graphql',
  options: {
    reconnect: true,
    connectionParams: () => ({
      authorization: localStorage.getItem('token') || '',
    }),
  },
});

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

export const apolloClient = new ApolloClient({
  link: splitLink,
  cache: new InMemoryCache(),
  defaultOptions: {
    watchQuery: {
      fetchPolicy: 'cache-and-network',
    },
  },
});
```

### Register with Vue App

```typescript
// main.ts
import { createApp } from 'vue';
import { DefaultApolloClient } from '@vue/apollo-composable';
import { apolloClient } from './apollo.config';
import App from './App.vue';

const app = createApp(App);
app.provide(DefaultApolloClient, apolloClient);
app.mount('#app');
```

---

## Queries

### Basic Query with useQuery

```vue
<template>
  <div v-if="loading" class="loading">Loading users...</div>
  <div v-else-if="error" class="error">{{ error.message }}</div>
  <ul v-else>
    <li v-for="user in result?.users" :key="user.id">
      {{ user.name }} ({{ user.email }})
    </li>
  </ul>
</template>

<script setup lang="ts">
import { useQuery, gql } from '@vue/apollo-composable';
import { computed } from 'vue';

const GET_USERS = gql`
  query GetUsers {
    users {
      id
      name
      email
    }
  }
`;

const { result, loading, error } = useQuery(GET_USERS);
</script>
```

### Query with Variables

```vue
<template>
  <div>
    <div v-if="loading">Loading user...</div>
    <div v-else-if="error">{{ error.message }}</div>
    <div v-else>
      <h1>{{ user?.name }}</h1>
      <p>Email: {{ user?.email }}</p>
      <h2>Posts:</h2>
      <ul>
        <li v-for="post in user?.posts" :key="post.id">
          {{ post.title }}
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useQuery, gql } from '@vue/apollo-composable';
import { computed } from 'vue';

interface Props {
  userId: string;
}

const props = defineProps<Props>();

const GET_USER = gql`
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

const { result, loading, error } = useQuery(
  GET_USER,
  () => ({
    id: props.userId,
  }),
  () => ({
    enabled: !!props.userId,
  })
);

const user = computed(() => result.value?.user);
</script>
```

### Reactive Query Variables

```vue
<template>
  <div>
    <input v-model="searchTerm" placeholder="Search users..." />
    <ul>
      <li v-for="user in users" :key="user.id">
        {{ user.name }}
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { useQuery, gql } from '@vue/apollo-composable';
import { ref, computed } from 'vue';

const SEARCH_USERS = gql`
  query SearchUsers($term: String!) {
    searchUsers(term: $term) {
      id
      name
      email
    }
  }
`;

const searchTerm = ref('');

const { result, loading } = useQuery(
  SEARCH_USERS,
  () => ({ term: searchTerm.value }),
  () => ({
    skip: searchTerm.value.length < 2,
  })
);

const users = computed(() => result.value?.searchUsers || []);
</script>
```

### Pagination with fetchMore

```vue
<template>
  <div>
    <div class="posts">
      <div v-for="post in posts" :key="post.id" class="post">
        <h3>{{ post.title }}</h3>
        <p>{{ post.content }}</p>
      </div>
    </div>
    <button @click="loadMore" :disabled="loading || !hasMore">
      {{ loading ? 'Loading...' : 'Load More' }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { useQuery, gql } from '@vue/apollo-composable';
import { ref, computed } from 'vue';

const GET_POSTS = gql`
  query GetPosts($limit: Int!, $offset: Int!) {
    posts(limit: $limit, offset: $offset) {
      id
      title
      content
    }
    postsCount
  }
`;

const pageSize = 10;
const currentPage = ref(0);

const { result, loading, fetchMore } = useQuery(
  GET_POSTS,
  () => ({
    limit: pageSize,
    offset: 0,
  })
);

const posts = computed(() => result.value?.posts || []);
const totalCount = computed(() => result.value?.postsCount || 0);
const hasMore = computed(() => posts.value.length < totalCount.value);

const loadMore = async () => {
  currentPage.value++;
  await fetchMore({
    variables: {
      offset: currentPage.value * pageSize,
    },
    updateQuery: (prev, { fetchMoreResult }) => {
      if (!fetchMoreResult) return prev;
      return {
        posts: [...(prev?.posts || []), ...(fetchMoreResult.posts || [])],
        postsCount: fetchMoreResult.postsCount,
      };
    },
  });
};
</script>
```

---

## Mutations

### Basic Mutation with useMutation

```vue
<template>
  <form @submit.prevent="createPost">
    <input
      v-model="title"
      type="text"
      placeholder="Post title"
      required
    />
    <textarea
      v-model="content"
      placeholder="Post content"
      required
    />
    <button type="submit" :disabled="loading">
      {{ loading ? 'Creating...' : 'Create Post' }}
    </button>
    <div v-if="error" class="error">{{ error.message }}</div>
  </form>
</template>

<script setup lang="ts">
import { useMutation, gql } from '@vue/apollo-composable';
import { ref } from 'vue';

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

const title = ref('');
const content = ref('');

const { mutate: createPostMutation, loading, error } = useMutation(CREATE_POST);

const createPost = async () => {
  try {
    const result = await createPostMutation({
      title: title.value,
      content: content.value,
    });
    console.log('Post created:', result?.data?.createPost);
    title.value = '';
    content.value = '';
  } catch (err) {
    console.error('Error:', err);
  }
};
</script>
```

### Update Cache After Mutation

```vue
<template>
  <button @click="updateName" :disabled="loading">
    Update Name
  </button>
</template>

<script setup lang="ts">
import { useMutation, useQuery, gql } from '@vue/apollo-composable';
import { ref } from 'vue';

const UPDATE_USER = gql`
  mutation UpdateUser($id: ID!, $name: String!) {
    updateUser(id: $id, name: $name) {
      id
      name
    }
  }
`;

const GET_USER = gql`
  query GetUser($id: ID!) {
    user(id: $id) {
      id
      name
    }
  }
`;

interface Props {
  userId: string;
}

const props = defineProps<Props>();
const newName = ref('');

const { mutate: updateUserMutation, loading } = useMutation(UPDATE_USER, () => ({
  update: (cache, { data }) => {
    cache.writeQuery({
      query: GET_USER,
      variables: { id: props.userId },
      data: {
        user: data?.updateUser,
      },
    });
  },
}));

const updateName = async () => {
  await updateUserMutation({
    id: props.userId,
    name: newName.value,
  });
};
</script>
```

---

## Subscriptions

### Subscribe to Real-Time Events

```vue
<template>
  <div class="feed">
    <div v-if="connecting" class="status">Connecting...</div>
    <div v-else-if="error" class="error">{{ error.message }}</div>
    <div v-else>
      <h2>New Posts</h2>
      <div v-if="latestPost" class="post">
        <h3>{{ latestPost.title }}</h3>
        <p>by {{ latestPost.author.name }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useSubscription, gql } from '@vue/apollo-composable';
import { ref, computed } from 'vue';

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

const { result, loading: connecting, error } = useSubscription(ON_POST_CREATED);

const latestPost = computed(() => result.value?.postCreated);
</script>
```

### Manage Multiple Subscriptions

```vue
<template>
  <div>
    <h2>Messages ({{ messages.length }})</h2>
    <div class="messages">
      <div v-for="msg in messages" :key="msg.id" class="message">
        <strong>{{ msg.user.name }}:</strong> {{ msg.text }}
      </div>
    </div>

    <h2>Users Online ({{ onlineUsers.length }})</h2>
    <ul>
      <li v-for="user in onlineUsers" :key="user.id">
        {{ user.name }}
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { useSubscription, gql } from '@vue/apollo-composable';
import { ref, computed } from 'vue';

const ON_MESSAGE = gql`
  subscription OnMessage {
    messageReceived {
      id
      text
      user { name }
    }
  }
`;

const ON_USER_ONLINE = gql`
  subscription OnUserOnline {
    userOnline { id name }
  }
`;

const messages = ref<any[]>([]);
const onlineUsers = ref<any[]>([]);

const { result: msgResult } = useSubscription(ON_MESSAGE);
const { result: userResult } = useSubscription(ON_USER_ONLINE);

// Watch for new messages
const watchMessages = () => {
  if (msgResult.value?.messageReceived) {
    messages.value.push(msgResult.value.messageReceived);
  }
};

// Watch for user status
const watchUsers = () => {
  if (userResult.value?.userOnline) {
    onlineUsers.value = [userResult.value.userOnline];
  }
};
</script>
```

---

## Error Handling

### Global Error Handling

```typescript
// apollo.config.ts
const errorLink = onError(({ graphQLErrors, networkError, operation, forward }) => {
  if (graphQLErrors) {
    for (const err of graphQLErrors) {
      if (err.extensions?.code === 'UNAUTHENTICATED') {
        localStorage.removeItem('token');
        window.location.href = '/login';
      }

      if (err.extensions?.code === 'FORBIDDEN') {
        console.error('Access denied');
      }

      if (err.extensions?.code === 'VALIDATION_ERROR') {
        console.error('Validation failed:', err.message);
      }
    }
  }

  if (networkError) {
    if ('statusCode' in networkError && networkError.statusCode === 401) {
      window.location.href = '/login';
    }
  }
});
```

### Component-Level Error Handling

```vue
<template>
  <div>
    <div v-if="error" class="error-container">
      <p>{{ errorMessage }}</p>
      <button @click="retry">Try Again</button>
    </div>
    <div v-else-if="loading">Loading...</div>
    <UserList v-else :users="users" />
  </div>
</template>

<script setup lang="ts">
import { useQuery, gql } from '@vue/apollo-composable';
import { computed } from 'vue';

const GET_USERS = gql`query GetUsers { users { id name } }`;

const { result, loading, error, refetch } = useQuery(GET_USERS);

const users = computed(() => result.value?.users || []);

const errorMessage = computed(() => {
  if (!error.value) return '';
  if (error.value.message.includes('network')) {
    return 'Network error. Check your connection.';
  }
  return error.value.message;
});

const retry = () => refetch();
</script>
```

---

## Caching Strategies

### Cache Management

```vue
<template>
  <div>
    <button @click="clearCache">Clear Cache</button>
    <button @click="refetchQuery">Refetch Data</button>
  </div>
</template>

<script setup lang="ts">
import { useQuery, useApolloClient, gql } from '@vue/apollo-composable';

const GET_USERS = gql`query GetUsers { users { id name } }`;

const { refetch } = useQuery(GET_USERS);
const { client } = useApolloClient();

const clearCache = () => {
  client.cache.reset();
};

const refetchQuery = () => {
  refetch();
};
</script>
```

### Fetch Policies

```vue
<script setup lang="ts">
import { useQuery, gql } from '@vue/apollo-composable';

const GET_DATA = gql`query GetData { data { id } }`;

// Different fetch policies for different data types

// Static user profile - use cache
useQuery(GET_DATA, null, { fetchPolicy: 'cache-first' });

// Real-time notifications - always fetch
useQuery(GET_DATA, null, {
  fetchPolicy: 'network-only',
  pollInterval: 5000, // Refetch every 5 seconds
});

// Activity feed - cache + refresh
useQuery(GET_DATA, null, { fetchPolicy: 'cache-and-network' });
</script>
```

---

## Performance Optimization

### Lazy Query Loading

```vue
<template>
  <input
    v-model="searchTerm"
    @change="performSearch"
    placeholder="Search..."
  />
  <ul v-if="results">
    <li v-for="result in results" :key="result.id">
      {{ result.name }}
    </li>
  </ul>
</template>

<script setup lang="ts">
import { useLazyQuery, gql } from '@vue/apollo-composable';
import { ref, computed } from 'vue';

const SEARCH = gql`
  query Search($term: String!) {
    search(term: $term) { id name }
  }
`;

const searchTerm = ref('');
const { result, load } = useLazyQuery(SEARCH);
const results = computed(() => result.value?.search);

const performSearch = async () => {
  if (searchTerm.value.length > 2) {
    await load(null, { term: searchTerm.value });
  }
};
</script>
```

### Conditional Query Loading

```vue
<script setup lang="ts">
import { useQuery, gql } from '@vue/apollo-composable';
import { ref, computed } from 'vue';

const GET_PROFILE = gql`query GetProfile { profile { id name } }`;
const GET_SETTINGS = gql`query GetSettings { settings { theme } }`;

const showSettings = ref(false);

// Profile loads immediately
const { result: profileResult } = useQuery(GET_PROFILE);

// Settings only load when needed
const { result: settingsResult } = useQuery(
  GET_SETTINGS,
  null,
  { skip: computed(() => !showSettings.value) }
);
</script>
```

---

## Testing

### Test Query Component

```typescript
// UserList.spec.ts
import { describe, it, expect } from 'vitest';
import { mount } from '@vue/test-utils';
import { createMockClient } from '@vue/apollo-composable/testing';
import { gql } from '@apollo/client';
import UserList from './UserList.vue';

const mockClient = createMockClient();

describe('UserList', () => {
  it('renders user list', async () => {
    const wrapper = mount(UserList, {
      global: {
        plugins: [mockClient],
      },
    });

    await wrapper.vm.$nextTick();
    expect(wrapper.find('.users').exists()).toBe(true);
  });
});
```

### Test Mutation

```typescript
import { describe, it, expect, vi } from 'vitest';
import { useMutation, gql } from '@vue/apollo-composable';

const UPDATE_USER = gql`
  mutation UpdateUser($id: ID!, $name: String!) {
    updateUser(id: $id, name: $name) { id name }
  }
`;

describe('Mutation', () => {
  it('updates user', async () => {
    const { mutate } = useMutation(UPDATE_USER);

    const result = await mutate({
      id: '1',
      name: 'Updated Name',
    });

    expect(result?.data?.updateUser?.name).toBe('Updated Name');
  });
});
```

---

## Server-Side Rendering (Nuxt)

### Setup with Nuxt 3

```typescript
// nuxt.config.ts
export default defineNuxtConfig({
  modules: ['@nuxtjs/apollo'],
  apollo: {
    clients: {
      default: {
        httpEndpoint: 'http://localhost:8000/graphql',
        wsEndpoint: 'ws://localhost:8000/graphql',
      },
    },
  },
});
```

### Use Queries in Nuxt

```vue
<template>
  <div>
    <h1>{{ user?.name }}</h1>
  </div>
</template>

<script setup lang="ts">
import { useQuery, gql } from '@vue/apollo-composable';

const GET_USER = gql`
  query GetUser($id: ID!) {
    user(id: $id) { id name }
  }
`;

const { result } = useQuery(
  GET_USER,
  () => ({ id: useRoute().params.id }),
  { prefetch: true } // Prefetch on server
);

const user = computed(() => result.value?.user);
</script>
```

---

## See Also

**Related Guides:**

- **[React + Apollo Guide](./react-apollo-guide.md)** - For comparison
- **[Real-Time Patterns](../patterns.md)** - Subscription architecture
- **[Authentication & Authorization](../authorization-quick-start.md)** - Securing queries

**Vue & Apollo Documentation:**

- [Vue Apollo Docs](https://vue-apollo.netlify.app/)
- [Apollo Client for Vue GitHub](https://github.com/vuejs/apollo)

<!-- Skip to main content -->
---

title: Flutter with GraphQL Client for FraiseQL
description: Complete guide for querying FraiseQL servers from Flutter mobile applications.
keywords: ["debugging", "implementation", "best-practices", "deployment", "graphql", "tutorial"]
tags: ["documentation", "reference"]
---

# Flutter with GraphQL Client for FraiseQL

**Status:** ✅ Production Ready
**Audience:** Flutter/Dart developers
**Reading Time:** 25-30 minutes
**Last Updated:** 2026-02-05

Complete guide for querying FraiseQL servers from Flutter mobile applications.

---

## Installation & Setup

### Prerequisites

- Flutter 3.0+
- Dart 3.0+
- FraiseQL server running
- iOS Xcode 14+, Android API level 21+

### Add Dependencies

```yaml
<!-- Code example in YAML -->
# pubspec.yaml
dependencies:
  flutter:
    SDK: flutter
  graphql: ^5.0.0
  graphql_flutter: ^6.0.0
  hive: ^2.2.0
  hive_flutter: ^1.1.0
  get_it: ^7.5.0
  riverpod: ^2.3.0
  flutter_riverpod: ^2.3.0

dev_dependencies:
  flutter_test:
    SDK: flutter
  build_runner: ^2.4.0
```text
<!-- Code example in TEXT -->

Run `flutter pub get`

### Initialize GraphQL & Hive

```dart
<!-- Code example in DART -->
// main.dart
import 'package:flutter/material.dart';
import 'package:graphql_flutter/graphql_flutter.dart';
import 'package:hive_flutter/hive_flutter.dart';

void main() async {
  await Hive.initFlutter();

  // Initialize GraphQL
  await initHiveForFlutter();

  final HttpLink httpLink = HttpLink(
    'http://localhost:5000/graphql', // FraiseQL endpoint
  );

  final WebSocketLink wsLink = WebSocketLink(
    'ws://localhost:5000/graphql',
    config: const SocketClientConfig(
      autoReconnect: true,
      inactivityTimeout: Duration(seconds: 30),
    ),
  );

  Link link = Link.from([
    // Split between WebSocket (subscriptions) and HTTP (queries/mutations)
    split(
      (request) {
        final operationName = request.operation.operationName;
        return operationName == 'subscribe';
      },
      wsLink,
      httpLink,
    ),
  ]);

  final ValueNotifier<GraphQLClient> client = ValueNotifier(
    GraphQLClient(
      cache: GraphQLCache(store: HiveStore()),
      link: link,
    ),
  );

  runApp(MyApp(client: client));
}

class MyApp extends StatelessWidget {
  final ValueNotifier<GraphQLClient> client;

  const MyApp({required this.client});

  @override
  Widget build(BuildContext context) {
    return GraphQLProvider(
      client: client,
      child: CacheProvider(
        child: MaterialApp(
          title: 'FraiseQL App',
          theme: ThemeData(primarySwatch: Colors.blue),
          home: const HomePage(),
        ),
      ),
    );
  }
}
```text
<!-- Code example in TEXT -->

---

## Queries

### Basic Query

```dart
<!-- Code example in DART -->
import 'package:graphql_flutter/graphql_flutter.dart';

const String GET_USERS = r'''
  query GetUsers {
    users {
      id
      name
      email
    }
  }
''';

class UserList extends StatelessWidget {
  const UserList({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Query(
      options: QueryOptions(
        document: gql(GET_USERS),
        fetchPolicy: FetchPolicy.cacheAndNetwork,
      ),
      builder: (QueryResult result, {fetchMore, refetch}) {
        if (result.isLoading) {
          return const Center(child: CircularProgressIndicator());
        }

        if (result.hasException) {
          return Center(
            child: Text('Error: ${result.exception.toString()}'),
          );
        }

        final List users = result.data?['users'] ?? [];

        return ListView.builder(
          itemCount: users.length,
          itemBuilder: (context, index) {
            final user = users[index];
            return ListTile(
              title: Text(user['name']),
              subtitle: Text(user['email']),
            );
          },
        );
      },
    );
  }
}
```text
<!-- Code example in TEXT -->

### Query with Variables

```dart
<!-- Code example in DART -->
const String GET_USER_BY_ID = r'''
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
''';

class UserDetail extends StatelessWidget {
  final String userId;

  const UserDetail({required this.userId, Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Query(
      options: QueryOptions(
        document: gql(GET_USER_BY_ID),
        variables: {'id': userId},
        fetchPolicy: FetchPolicy.networkOnly,
      ),
      builder: (QueryResult result, {fetchMore, refetch}) {
        if (result.isLoading) {
          return const Center(child: CircularProgressIndicator());
        }

        final user = result.data?['user'];

        return SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(user['name'], style: Theme.of(context).textTheme.headlineMedium),
              Text(user['email']),
              const SizedBox(height: 16),
              Text('Posts', style: Theme.of(context).textTheme.titleMedium),
              ...List<Widget>.from(
                (user['posts'] as List).map(
                  (post) => ListTile(
                    title: Text(post['title']),
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}
```text
<!-- Code example in TEXT -->

### Pagination Pattern

```dart
<!-- Code example in DART -->
const String GET_POSTS_PAGINATED = r'''
  query GetPosts($limit: Int!, $offset: Int!) {
    posts(limit: $limit, offset: $offset) {
      id
      title
      createdAt
    }
    postsCount
  }
''';

class PostListPaginated extends StatefulWidget {
  const PostListPaginated({Key? key}) : super(key: key);

  @override
  State<PostListPaginated> createState() => _PostListPaginatedState();
}

class _PostListPaginatedState extends State<PostListPaginated> {
  int page = 0;
  final pageSize = 10;

  @override
  Widget build(BuildContext context) {
    return Query(
      options: QueryOptions(
        document: gql(GET_POSTS_PAGINATED),
        variables: {
          'limit': pageSize,
          'offset': page * pageSize,
        },
      ),
      builder: (QueryResult result, {fetchMore, refetch}) {
        if (result.isLoading && page == 0) {
          return const Center(child: CircularProgressIndicator());
        }

        final posts = result.data?['posts'] as List? ?? [];
        final total = result.data?['postsCount'] as int? ?? 0;

        return Column(
          children: [
            Expanded(
              child: ListView.builder(
                itemCount: posts.length,
                itemBuilder: (context, index) {
                  final post = posts[index];
                  return ListTile(
                    title: Text(post['title']),
                    subtitle: Text(post['createdAt']),
                  );
                },
              ),
            ),
            if (posts.length < total)
              Padding(
                padding: const EdgeInsets.all(16),
                child: ElevatedButton(
                  onPressed: () {
                    setState(() => page++);
                  },
                  child: const Text('Load More'),
                ),
              ),
          ],
        );
      },
    );
  }
}
```text
<!-- Code example in TEXT -->

---

## Mutations

### Basic Mutation

```dart
<!-- Code example in DART -->
const String CREATE_POST = r'''
  mutation CreatePost($title: String!, $content: String!) {
    createPost(title: $title, content: $content) {
      id
      title
      content
      createdAt
    }
  }
''';

class CreatePostForm extends StatefulWidget {
  const CreatePostForm({Key? key}) : super(key: key);

  @override
  State<CreatePostForm> createState() => _CreatePostFormState();
}

class _CreatePostFormState extends State<CreatePostForm> {
  final _titleController = TextEditingController();
  final _contentController = TextEditingController();

  @override
  Widget build(BuildContext context) {
    return Mutation(
      options: MutationOptions(
        document: gql(CREATE_POST),
      ),
      builder: (runMutation, result) {
        return SingleChildScrollView(
          child: Column(
            children: [
              TextField(
                controller: _titleController,
                decoration: const InputDecoration(labelText: 'Title'),
              ),
              TextField(
                controller: _contentController,
                decoration: const InputDecoration(labelText: 'Content'),
                minLines: 5,
                maxLines: null,
              ),
              const SizedBox(height: 16),
              ElevatedButton(
                onPressed: (result?.isLoading ?? false)
                    ? null
                    : () {
                        runMutation({
                          'title': _titleController.text,
                          'content': _contentController.text,
                        });
                      },
                child: Text(
                  (result?.isLoading ?? false) ? 'Creating...' : 'Create Post',
                ),
              ),
              if (result?.hasException ?? false)
                Padding(
                  padding: const EdgeInsets.only(top: 16),
                  child: Text(
                    'Error: ${result!.exception.toString()}',
                    style: const TextStyle(color: Colors.red),
                  ),
                ),
            ],
          ),
        );
      },
    );
  }

  @override
  void dispose() {
    _titleController.dispose();
    _contentController.dispose();
    super.dispose();
  }
}
```text
<!-- Code example in TEXT -->

### Update Cache After Mutation

```dart
<!-- Code example in DART -->
const String GET_POSTS = r'''
  query GetPosts {
    posts { id title }
  }
''';

const String ADD_POST = r'''
  mutation AddPost($title: String!) {
    addPost(title: $title) { id title }
  }
''';

class PostListWithAdd extends StatelessWidget {
  const PostListWithAdd({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Query(
      options: QueryOptions(
        document: gql(GET_POSTS),
      ),
      builder: (queryResult, {fetchMore, refetch}) {
        return Mutation(
          options: MutationOptions(
            document: gql(ADD_POST),
            update: (cache, result) {
              // Update cache with new post
              final previousData = cache.readQuery(QueryOptions(
                document: gql(GET_POSTS),
              ));

              if (previousData != null) {
                final newPost = result?.data?['addPost'];
                previousData['posts']?.add(newPost);
                cache.writeQuery(
                  QueryOptions(document: gql(GET_POSTS)),
                  previousData,
                );
              }
            },
          ),
          builder: (runMutation, mutationResult) {
            return Column(
              children: [
                ElevatedButton(
                  onPressed: () => runMutation({'title': 'New Post'}),
                  child: const Text('Add Post'),
                ),
                Expanded(
                  child: ListView.builder(
                    itemCount: queryResult.data?['posts']?.length ?? 0,
                    itemBuilder: (context, index) {
                      final post =
                          queryResult.data?['posts']?[index];
                      return ListTile(title: Text(post['title']));
                    },
                  ),
                ),
              ],
            );
          },
        );
      },
    );
  }
}
```text
<!-- Code example in TEXT -->

---

## Subscriptions

### Real-Time Subscriptions

```dart
<!-- Code example in DART -->
const String ON_POST_CREATED = r'''
  subscription OnPostCreated {
    postCreated {
      id
      title
      author {
        name
      }
    }
  }
''';

class PostFeed extends StatelessWidget {
  const PostFeed({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Subscription(
      options: SubscriptionOptions(
        document: gql(ON_POST_CREATED),
      ),
      builder: (result) {
        if (result.isLoading) {
          return const Center(child: CircularProgressIndicator());
        }

        if (result.hasException) {
          return Center(
            child: Text('Error: ${result.exception.toString()}'),
          );
        }

        final post = result.data?['postCreated'];

        if (post == null) {
          return const Center(child: Text('Waiting for posts...'));
        }

        return Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(post['title'],
                    style: Theme.of(context).textTheme.headlineSmall),
                Text('by ${post['author']['name']}'),
              ],
            ),
          ),
        );
      },
    );
  }
}
```text
<!-- Code example in TEXT -->

---

## Error Handling

### Handle Different Error Types

```dart
<!-- Code example in DART -->
class SafeQueryWidget extends StatelessWidget {
  final String query;

  const SafeQueryWidget({required this.query, Key? key}) : super(key: key);

  String _getErrorMessage(Exception? exception) {
    if (exception == null) return 'Unknown error';

    if (exception.toString().contains('SocketException')) {
      return 'Connection error. Check your network.';
    }

    if (exception.toString().contains('Unauthorized')) {
      return 'Authentication failed. Please log in again.';
    }

    if (exception.toString().contains('Forbidden')) {
      return 'You do not have permission to access this.';
    }

    return exception.toString();
  }

  @override
  Widget build(BuildContext context) {
    return Query(
      options: QueryOptions(
        document: gql(query),
        errorPolicy: ErrorPolicy.all,
      ),
      builder: (result, {fetchMore, refetch}) {
        if (result.hasException) {
          return Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(_getErrorMessage(result.exception)),
                const SizedBox(height: 16),
                ElevatedButton(
                  onPressed: refetch,
                  child: const Text('Retry'),
                ),
              ],
            ),
          );
        }

        if (result.isLoading) {
          return const Center(child: CircularProgressIndicator());
        }

        return const Center(child: Text('Success'));
      },
    );
  }
}
```text
<!-- Code example in TEXT -->

---

## State Management with Riverpod

### Query Provider

```dart
<!-- Code example in DART -->
import 'package:flutter_riverpod/flutter_riverpod.dart';

final graphqlClientProvider = Provider((ref) {
  final httpLink = HttpLink('http://localhost:5000/graphql');
  return GraphQLClient(
    cache: GraphQLCache(),
    link: httpLink,
  );
});

final usersProvider = FutureProvider((ref) async {
  final client = ref.watch(graphqlClientProvider);

  const query = r'''
    query GetUsers {
      users { id name email }
    }
  ''';

  final result = await client.query(
    QueryOptions(document: gql(query)),
  );

  return result.data?['users'] as List<dynamic>;
});

class UserListWithRiverpod extends ConsumerWidget {
  const UserListWithRiverpod({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final usersAsync = ref.watch(usersProvider);

    return usersAsync.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (error, stackTrace) => Center(child: Text('Error: $error')),
      data: (users) {
        return ListView.builder(
          itemCount: users.length,
          itemBuilder: (context, index) {
            return ListTile(
              title: Text(users[index]['name']),
            );
          },
        );
      },
    );
  }
}
```text
<!-- Code example in TEXT -->

---

## Local Caching with Hive

### Setup Hive

```dart
<!-- Code example in DART -->
import 'package:hive_flutter/hive_flutter.dart';

void main() async {
  await Hive.initFlutter();

  // Register adapters for custom objects
  Hive.registerAdapter(UserAdapter());
  Hive.registerAdapter(PostAdapter());

  runApp(const MyApp());
}

// Define models
@HiveType(typeId: 0)
class User extends HiveObject {
  @HiveField(0)
  String id;

  @HiveField(1)
  String name;

  @HiveField(2)
  String email;

  User({required this.id, required this.name, required this.email});
}

@HiveType(typeId: 1)
class Post extends HiveObject {
  @HiveField(0)
  String id;

  @HiveField(1)
  String title;

  Post({required this.id, required this.title});
}
```text
<!-- Code example in TEXT -->

### Cache GraphQL Results

```dart
<!-- Code example in DART -->
class CachedUserList extends StatefulWidget {
  const CachedUserList({Key? key}) : super(key: key);

  @override
  State<CachedUserList> createState() => _CachedUserListState();
}

class _CachedUserListState extends State<CachedUserList> {
  @override
  void initState() {
    super.initState();
    _loadFromCache();
  }

  Future<void> _loadFromCache() async {
    final userBox = Hive.box<User>('users');
    // Users are already in memory from box
  }

  @override
  Widget build(BuildContext context) {
    return Query(
      options: QueryOptions(
        document: gql(GET_USERS),
        fetchPolicy: FetchPolicy.cacheAndNetwork,
      ),
      builder: (result, {fetchMore, refetch}) {
        if (result.isLoading) {
          return const Center(child: CircularProgressIndicator());
        }

        final users = result.data?['users'] as List? ?? [];

        // Save to Hive cache
        final userBox = Hive.box<User>('users');
        for (var user in users) {
          userBox.put(
            user['id'],
            User(
              id: user['id'],
              name: user['name'],
              email: user['email'],
            ),
          );
        }

        return ListView.builder(
          itemCount: users.length,
          itemBuilder: (context, index) {
            final user = users[index];
            return ListTile(title: Text(user['name']));
          },
        );
      },
    );
  }
}
```text
<!-- Code example in TEXT -->

---

## Testing

### Mock GraphQL Responses

```dart
<!-- Code example in DART -->
import 'package:graphql_flutter/graphql_flutter.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('UserList', () {
    testWidgets('displays users', (WidgetTester tester) async {
      final mockLink = MockLink(
        requests: [
          MockedResponse(
            request: QueryOptions(document: gql(GET_USERS)),
            result: QueryResult(
              data: {
                'users': [
                  {'id': '1', 'name': 'Alice', 'email': 'alice@example.com'},
                  {'id': '2', 'name': 'Bob', 'email': 'bob@example.com'},
                ]
              },
            ),
          ),
        ],
      );

      final client = GraphQLClient(
        cache: GraphQLCache(),
        link: mockLink,
      );

      await tester.pumpWidget(
        GraphQLProvider(
          client: ValueNotifier(client),
          child: MaterialApp(
            home: Scaffold(
              body: UserList(),
            ),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('Alice'), findsOneWidget);
      expect(find.text('Bob'), findsOneWidget);
    });
  });
}
```text
<!-- Code example in TEXT -->

---

## App Store / Play Store Deployment

### Build iOS App

```bash
<!-- Code example in BASH -->
# Build iOS release
flutter build ios --release

# Upload to App Store (requires Apple Developer account)
# Use Xcode or fastlane
```text
<!-- Code example in TEXT -->

### Build Android App

```bash
<!-- Code example in BASH -->
# Build Android release APK
flutter build apk --release

# Build Android App Bundle for Play Store
flutter build appbundle --release

# Upload to Play Store (requires Google Play Developer account)
# Use Google Play Console or fastlane
```text
<!-- Code example in TEXT -->

---

## See Also

**Related Guides:**

- **[React Native Guide](./react-native-apollo-guide.md)** - Mobile web alternative
- **[Real-Time Patterns](../patterns.md)** - Subscription architecture
- **[Authentication & Authorization](../authorization-quick-start.md)** - Securing queries

**Flutter & GraphQL Documentation:**

- [Flutter GraphQL Pub Package](https://pub.dev/packages/graphql_flutter)
- [GraphQL Flutter GitHub](https://github.com/zino-app/graphql-flutter)
- [Flutter Official Docs](https://flutter.dev/docs)

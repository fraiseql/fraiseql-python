-- FraiseQL Blog Simple - Sample Data
-- Seed data for development and testing

-- Clean existing seed data to allow re-running
DELETE FROM tb_comment WHERE id IN ('71111111-1111-1111-1111-111111111111', '72222222-2222-2222-2222-222222222222', '73333333-3333-3333-3333-333333333333', '74444444-4444-4444-4444-444444444444', '75555555-5555-5555-5555-555555555555', '76666666-6666-6666-6666-666666666666');
DELETE FROM tb_post_tag WHERE fk_post IN (SELECT pk_post FROM tb_post WHERE id IN ('61111111-1111-1111-1111-111111111111', '62222222-2222-2222-2222-222222222222', '63333333-3333-3333-3333-333333333333', '64444444-4444-4444-4444-444444444444'));
DELETE FROM tb_post WHERE id IN ('61111111-1111-1111-1111-111111111111', '62222222-2222-2222-2222-222222222222', '63333333-3333-3333-3333-333333333333', '64444444-4444-4444-4444-444444444444');
DELETE FROM tb_tag WHERE id IN ('51111111-1111-1111-1111-111111111111', '52222222-2222-2222-2222-222222222222', '53333333-3333-3333-3333-333333333333', '54444444-4444-4444-4444-444444444444', '55555555-5555-5555-5555-555555555555', '56666666-6666-6666-6666-666666666666');
DELETE FROM tb_user WHERE id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', '33333333-3333-3333-3333-333333333333', '44444444-4444-4444-4444-444444444444');

-- Insert sample users
INSERT INTO tb_user (id, identifier, email, password_hash, role, profile_data) VALUES
(
    '11111111-1111-1111-1111-111111111111'::uuid,
    'admin',
    'admin@example.com',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKynicDLWvJz.lG', -- "password"
    'admin',
    '{"first_name": "Admin", "last_name": "User", "bio": "System administrator"}'::jsonb
),
(
    '22222222-2222-2222-2222-222222222222'::uuid,
    'johndoe',
    'john@example.com',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKynicDLWvJz.lG', -- "password"
    'author',
    '{"first_name": "John", "last_name": "Doe", "bio": "Tech writer and developer", "website": "https://johndoe.com"}'::jsonb
),
(
    '33333333-3333-3333-3333-333333333333'::uuid,
    'janedoe',
    'jane@example.com',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKynicDLWvJz.lG', -- "password"
    'author',
    '{"first_name": "Jane", "last_name": "Doe", "bio": "Frontend developer and UI/UX enthusiast"}'::jsonb
),
(
    '44444444-4444-4444-4444-444444444444'::uuid,
    'reader',
    'reader@example.com',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKynicDLWvJz.lG', -- "password"
    'user',
    '{"first_name": "Regular", "last_name": "Reader", "bio": "Avid blog reader"}'::jsonb
);

-- Insert sample tags
INSERT INTO tb_tag (id, name, identifier, color, description) VALUES
(
    '51111111-1111-1111-1111-111111111111'::uuid,
    'GraphQL',
    'graphql',
    '#E10098',
    'GraphQL API development and best practices'
),
(
    '52222222-2222-2222-2222-222222222222'::uuid,
    'PostgreSQL',
    'postgresql',
    '#336791',
    'PostgreSQL database tips and techniques'
),
(
    '53333333-3333-3333-3333-333333333333'::uuid,
    'FraiseQL',
    'fraiseql',
    '#6366f1',
    'FraiseQL framework tutorials and examples'
),
(
    '54444444-4444-4444-4444-444444444444'::uuid,
    'Web Development',
    'web-development',
    '#f59e0b',
    'General web development topics'
),
(
    '55555555-5555-5555-5555-555555555555'::uuid,
    'Python',
    'python',
    '#3776ab',
    'Python programming language'
),
(
    '56666666-6666-6666-6666-666666666666'::uuid,
    'FastAPI',
    'fastapi',
    '#009688',
    'FastAPI framework for building APIs'
);

-- Insert sample posts
INSERT INTO tb_post (id, title, identifier, content, excerpt, fk_author, status, published_at) VALUES
(
    '61111111-1111-1111-1111-111111111111'::uuid,
    'Getting Started with FraiseQL',
    'getting-started-with-fraiseql',
    'FraiseQL is a powerful framework for building GraphQL APIs with PostgreSQL. In this comprehensive guide, we''ll explore how to create your first FraiseQL application.

## What is FraiseQL?

FraiseQL combines the best of GraphQL and PostgreSQL to create a seamless development experience. It provides:

- **Database-first architecture**: Your PostgreSQL schema drives your GraphQL API
- **Type safety**: Full type safety from database to GraphQL
- **Performance**: Optimized queries with built-in N+1 prevention
- **Developer experience**: Clean, declarative API definitions

## Installation

Getting started with FraiseQL is easy:

```bash
pip install fraiseql[fastapi]
```

## Your First Application

Here''s a simple example of a FraiseQL application:

```python
import fraiseql
from fraiseql.fastapi import create_fraiseql_app

@fraiseql.type(sql_source="users")
class User:
    id: str
    name: str
    email: str

app = create_fraiseql_app(
    database_url="postgresql://user:pass@localhost/db",
    types=[User]
)
```

## Next Steps

Now that you have a basic understanding of FraiseQL, you can:

1. Explore the documentation
2. Try the interactive examples
3. Build your first real application

Happy coding!',
    'Learn how to get started with FraiseQL, a powerful framework for building GraphQL APIs with PostgreSQL.',
    (SELECT pk_user FROM tb_user WHERE identifier = 'johndoe'),
    'published',
    NOW() - INTERVAL '2 days'
),
(
    '62222222-2222-2222-2222-222222222222'::uuid,
    'Advanced PostgreSQL Patterns in FraiseQL',
    'advanced-postgresql-patterns-in-fraiseql',
    'PostgreSQL is more than just a database - it''s a powerful platform for building robust applications. In this article, we''ll explore advanced patterns that make FraiseQL applications shine.

## JSONB and Flexible Schemas

One of PostgreSQL''s greatest strengths is JSONB support:

```sql
CREATE TABLE posts (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT ''''{}''''::jsonb
);
```

This allows for flexible, schema-less data alongside structured columns.

## Views for Query Optimization

FraiseQL leverages PostgreSQL views for clean separation between command and query sides:

```sql
CREATE VIEW v_post_with_author AS
SELECT
    p.*,
    jsonb_build_object(
        ''''id'''', u.id,
        ''''username'''', u.username,
        ''''profile'''', u.profile_data
    ) as author
FROM posts p
JOIN users u ON p.author_id = u.id;
```

## Triggers and Functions

Automate business logic with triggers:

```sql
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

## Row Level Security

Implement authorization at the database level:

```sql
ALTER TABLE posts ENABLE ROW LEVEL SECURITY;

CREATE POLICY posts_visibility ON posts
    FOR SELECT USING (
        status = ''''published''''
        OR author_id = current_setting(''''app.current_user_id'''')::uuid
    );
```

These patterns form the foundation of scalable, secure FraiseQL applications.',
    'Explore advanced PostgreSQL patterns that power robust FraiseQL applications, from JSONB to Row Level Security.',
    (SELECT pk_user FROM tb_user WHERE identifier = 'johndoe'),
    'published',
    NOW() - INTERVAL '1 day'
),
(
    '63333333-3333-3333-3333-333333333333'::uuid,
    'Building Reactive UIs with GraphQL Subscriptions',
    'building-reactive-uis-with-graphql-subscriptions',
    'Real-time updates are essential for modern web applications. FraiseQL makes it easy to implement GraphQL subscriptions for reactive user interfaces.

## What are GraphQL Subscriptions?

GraphQL subscriptions allow clients to receive real-time updates when data changes:

```graphql
subscription PostUpdates {
    postUpdates {
        mutation
        node {
            id
            title
            status
        }
    }
}
```

## Implementation with FraiseQL

FraiseQL provides decorators for easy subscription implementation:

```python
@fraiseql.subscription
async def post_updates(info: GraphQLResolveInfo):
    """Subscribe to post updates"""
    async for update in post_stream():
        yield update
```

## WebSocket Integration

FraiseQL integrates seamlessly with WebSocket for real-time communication:

```python
from fraiseql.subscriptions import WebSocketSubscriptionServer

app.add_websocket_route("/ws", WebSocketSubscriptionServer())
```

## Frontend Integration

Connect your React application:

```typescript
import { createClient } from ''''graphql-ws'''';

const client = createClient({
    url: ''''ws://localhost:8000/ws'''',
});

const subscription = client.iterate({
    query: ''''subscription { postUpdates { id title } }''''
});

for await (const result of subscription) {
    console.log(result);
}
```

## Use Cases

Subscriptions are perfect for:

- Live comments and messaging
- Real-time analytics dashboards
- Collaborative editing
- Live notifications
- Activity feeds

Start building reactive applications today with FraiseQL subscriptions!',
    'Learn how to build real-time, reactive user interfaces using GraphQL subscriptions with FraiseQL.',
    (SELECT pk_user FROM tb_user WHERE identifier = 'janedoe'),
    'published',
    NOW() - INTERVAL '6 hours'
),
(
    '64444444-4444-4444-4444-444444444444'::uuid,
    'FraiseQL vs Other GraphQL Frameworks',
    'fraiseql-vs-other-graphql-frameworks',
    'Choosing the right GraphQL framework is crucial for project success. Let''s compare FraiseQL with other popular options and understand when to choose each.

## FraiseQL - Database-First Approach

FraiseQL''s unique selling point is its database-first approach:

**Strengths:**
- Schema driven by database structure
- Excellent PostgreSQL integration
- Built-in performance optimizations
- Type safety from database to GraphQL
- CQRS patterns built-in

**Best for:**
- PostgreSQL-based applications
- Complex business domains
- High-performance requirements
- Teams comfortable with SQL

## GraphQL-Core Python - Pure GraphQL

The reference implementation for Python:

**Strengths:**
- Maximum flexibility
- Direct GraphQL spec compliance
- Minimal overhead
- Complete control

**Best for:**
- Custom implementations
- Learning GraphQL internals
- Specific performance requirements

## Strawberry - Modern Python GraphQL

A modern, decorator-based framework:

**Strengths:**
- Clean, Pythonic syntax
- Great developer experience
- Strong typing with dataclasses
- Active development

**Best for:**
- New Python projects
- Teams preferring modern Python patterns
- Rapid prototyping

## Graphene - Mature Ecosystem

A mature framework with broad adoption:

**Strengths:**
- Large ecosystem
- Django/Flask integrations
- Proven in production
- Extensive documentation

**Best for:**
- Django applications
- Established codebases
- Teams needing ecosystem maturity

## Making the Right Choice

Choose FraiseQL when:
- You''re building on PostgreSQL
- Performance is critical
- You need CQRS patterns
- Your team thinks in database terms

Consider alternatives when:
- Using different databases
- Need maximum flexibility
- Working with existing GraphQL codebases
- Team prefers ORM-style thinking

Each framework has its place - choose based on your specific needs and constraints.',
    'A comprehensive comparison of FraiseQL with other GraphQL frameworks to help you make the right choice.',
    (SELECT pk_user FROM tb_user WHERE identifier = 'johndoe'),
    'draft',
    NULL
);

-- Insert post-tag relationships
INSERT INTO tb_post_tag (fk_post, fk_tag)
SELECT p.pk_post, t.pk_tag
FROM (VALUES
-- Getting Started with FraiseQL
('61111111-1111-1111-1111-111111111111', '51111111-1111-1111-1111-111111111111'), -- GraphQL
('61111111-1111-1111-1111-111111111111', '53333333-3333-3333-3333-333333333333'), -- FraiseQL
('61111111-1111-1111-1111-111111111111', '54444444-4444-4444-4444-444444444444'), -- Web Development

-- Advanced PostgreSQL Patterns
('62222222-2222-2222-2222-222222222222', '52222222-2222-2222-2222-222222222222'), -- PostgreSQL
('62222222-2222-2222-2222-222222222222', '53333333-3333-3333-3333-333333333333'), -- FraiseQL
('62222222-2222-2222-2222-222222222222', '55555555-5555-5555-5555-555555555555'), -- Python

-- Building Reactive UIs
('63333333-3333-3333-3333-333333333333', '51111111-1111-1111-1111-111111111111'), -- GraphQL
('63333333-3333-3333-3333-333333333333', '53333333-3333-3333-3333-333333333333'), -- FraiseQL
('63333333-3333-3333-3333-333333333333', '54444444-4444-4444-4444-444444444444'), -- Web Development

-- FraiseQL vs Other Frameworks
('64444444-4444-4444-4444-444444444444', '51111111-1111-1111-1111-111111111111'), -- GraphQL
('64444444-4444-4444-4444-444444444444', '53333333-3333-3333-3333-333333333333'), -- FraiseQL
('64444444-4444-4444-4444-444444444444', '55555555-5555-5555-5555-555555555555') -- Python
) AS pair(post_id, tag_id)
JOIN tb_post p ON p.id = pair.post_id::uuid
JOIN tb_tag t ON t.id = pair.tag_id::uuid;

-- Insert sample comments
INSERT INTO tb_comment (id, fk_post, fk_author, content, status) VALUES
(
    '71111111-1111-1111-1111-111111111111'::uuid,
    (SELECT pk_post FROM tb_post WHERE id = '61111111-1111-1111-1111-111111111111'), -- Getting Started post
    (SELECT pk_user FROM tb_user WHERE identifier = 'reader'),
    'Great introduction to FraiseQL! I''ve been looking for a GraphQL framework that works well with PostgreSQL. The database-first approach really appeals to me.',
    'approved'
),
(
    '72222222-2222-2222-2222-222222222222'::uuid,
    (SELECT pk_post FROM tb_post WHERE id = '61111111-1111-1111-1111-111111111111'), -- Getting Started post
    (SELECT pk_user FROM tb_user WHERE identifier = 'janedoe'),
    'Thanks for this tutorial! One question - how does FraiseQL handle complex joins and relationships? Looking forward to more advanced examples.',
    'approved'
),
(
    '73333333-3333-3333-3333-333333333333'::uuid,
    (SELECT pk_post FROM tb_post WHERE id = '61111111-1111-1111-1111-111111111111'), -- Getting Started post
    (SELECT pk_user FROM tb_user WHERE identifier = 'johndoe'),
    '@janedoe Great question! FraiseQL handles relationships through field resolvers and can optimize joins automatically. I''ll cover this in detail in an upcoming post.',
    'approved'
),
(
    '74444444-4444-4444-4444-444444444444'::uuid,
    (SELECT pk_post FROM tb_post WHERE id = '62222222-2222-2222-2222-222222222222'), -- Advanced PostgreSQL post
    (SELECT pk_user FROM tb_user WHERE identifier = 'reader'),
    'The JSONB examples are really helpful. I didn''t realize PostgreSQL could be so flexible while maintaining relational integrity.',
    'approved'
),
(
    '75555555-5555-5555-5555-555555555555'::uuid,
    (SELECT pk_post FROM tb_post WHERE id = '63333333-3333-3333-3333-333333333333'), -- Reactive UIs post
    (SELECT pk_user FROM tb_user WHERE identifier = 'johndoe'),
    'Subscriptions are such a powerful feature. The WebSocket integration looks seamless. Can''t wait to try this in my next project!',
    'approved'
),
-- Nested comment (reply)
(
    '76666666-6666-6666-6666-666666666666'::uuid,
    (SELECT pk_post FROM tb_post WHERE id = '63333333-3333-3333-3333-333333333333'), -- Reactive UIs post
    (SELECT pk_user FROM tb_user WHERE identifier = 'janedoe'),
    '@johndoe Definitely give it a try! The real-time updates make such a difference for user experience. Let me know if you run into any issues.',
    'approved'
);

-- Update the reply to have the correct fk_parent
UPDATE tb_comment
SET fk_parent = (SELECT pk_comment FROM tb_comment WHERE id = '75555555-5555-5555-5555-555555555555'::uuid)
WHERE id = '76666666-6666-6666-6666-666666666666'::uuid;

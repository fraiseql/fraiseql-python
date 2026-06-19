# Junior Developer Journey - Build Your First API

**Time to Complete:** 1.5 hours
**Prerequisites:** Basic Python knowledge, no GraphQL experience required
**Goal:** Build and run your first FraiseQL API with a working GraphQL endpoint

## Overview

Welcome! This journey will take you from zero to a working GraphQL API in under 2 hours. You'll learn FraiseQL's core concepts through hands-on examples, starting with simple concepts and building up to a complete application.

By the end, you'll understand:

- How to set up a FraiseQL project
- The trinity pattern (tb_/v_/tv_ naming)
- Basic GraphQL queries and mutations
- How to run and test your API

## Step-by-Step Guide

### Step 1: Installation & Setup (15 minutes)

**Goal:** Get FraiseQL running on your machine

1. **Install Python dependencies:**

   ```bash
   pip install fraiseql fastapi uvicorn
   ```

2. **Verify installation:**

   ```bash
   python -c "import fraiseql; print('FraiseQL installed successfully!')"
   ```

3. **Set up PostgreSQL:**
   - Install PostgreSQL if you haven't already
   - Create a database: `createdb my_first_api`

**Success Check:** You can import fraiseql without errors

### Step 2: Your First API - Hello World (20 minutes)

**Goal:** Create a simple API that returns "Hello World" via GraphQL

1. **Create your first schema:**

   ```python
   # hello.py
   from fraiseql import fraise_type, create_fraiseql_app
   from typing import List

   @fraise_type
   class Query:
       hello: str = "Hello World!"

   app = create_fraiseql_app()
   ```

2. **Run the server:**

   ```bash
   uvicorn hello:app --reload
   ```

3. **Test your API:**
   - Open http://localhost:8000/graphql
   - Run this query:

   ```graphql
   query {
     hello
   }
   ```

**Success Check:** You see "Hello World!" in the GraphQL response

### Step 3: Add Database Integration (25 minutes)

**Goal:** Connect to PostgreSQL and create your first data model

1. **Set up database connection:**

   ```python
   # app.py
   from fraiseql import fraise_type, create_fraiseql_app
   from typing import List
   import asyncpg

   # Database connection
   DATABASE_URL = "postgresql://localhost/my_first_api"

   @fraise_type
   class User:
       id: str
       name: str
       email: str

   @fraise_type
   class Query:
       users: List[User]

       async def resolve_users(self, info):
           conn = await asyncpg.connect(DATABASE_URL)
           rows = await conn.fetch("SELECT id, name, email FROM v_user")
           await conn.close()
           return [User(id=str(row['id']), name=row['name'], email=row['email']) for row in rows]

   app = create_fraiseql_app()
   ```

2. **Create database schema:**

   ```sql
   -- Run this in psql
   CREATE TABLE tb_user (
       id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       name TEXT NOT NULL,
       email TEXT UNIQUE NOT NULL,
       created_at TIMESTAMPTZ DEFAULT NOW()
   );

   CREATE VIEW v_user AS
   SELECT id, name, email, created_at FROM tb_user;
   ```

3. **Add sample data:**

   ```sql
   INSERT INTO tb_user (name, email) VALUES
   ('Alice Johnson', 'alice@example.com'),
   ('Bob Smith', 'bob@example.com');
   ```

**Success Check:** GraphQL query returns the user data

### Step 4: Learn the Trinity Pattern (10 minutes)

**Goal:** Understand why FraiseQL uses tb_/v_/tv_ naming

**Read:** [Trinity Pattern Guide](../core/trinity-pattern/)

**Key Concepts:**

- `tb_user` - Base table (stores data)
- `v_user` - View (what GraphQL exposes)
- `tv_user_with_posts` - Computed view (joins data)

**Why this matters:** Clear separation prevents breaking changes and enables advanced features.

**Success Check:** You can explain "tb_ tables store data, v_ views are for GraphQL"

### Step 5: Build a Complete Blog API (30 minutes)

**Goal:** Create a working blog with posts and comments

1. **Follow the blog example:**
   - Read: [Blog Simple Example](../../examples/blog_simple/README/)
   - Clone and run the example locally

2. **Key files to understand:**
   - `schema.sql` - Database schema with trinity pattern
   - `app.py` - GraphQL resolvers
   - `models.py` - Python type definitions

3. **Test the API:**
   - Create a user
   - Write a post
   - Add comments
   - Query with relationships

**Success Check:** You can create posts and comments via GraphQL

### Step 6: GraphQL Concepts (15 minutes)

**Goal:** Learn basic GraphQL operations

**Read:** [Queries and Mutations](../core/queries-and-mutations/)

**Key Concepts:**

- **Queries:** Read data (like SELECT)
- **Mutations:** Change data (like INSERT/UPDATE)
- **Resolvers:** Functions that fetch data
- **Schema:** Type definitions

**Example Query:**

```graphql
query {
  posts {
    id
    title
    author {
      name
      email
    }
    comments {
      content
      author {
        name
      }
    }
  }
}
```

**Success Check:** You can write and understand GraphQL queries

## What You've Learned

✅ **Installation:** How to set up FraiseQL
✅ **Basic API:** Hello World GraphQL endpoint
✅ **Database Integration:** PostgreSQL connection and queries
✅ **Trinity Pattern:** tb_/v_/tv_ naming convention
✅ **Complete Application:** Working blog with relationships
✅ **GraphQL Basics:** Queries, mutations, and resolvers

## Next Steps

**Ready for more? Try these:**

1. **[Backend Engineer Journey](backend-engineer/)** - Learn advanced patterns
2. **[Add Authentication](../../examples/native-auth-app/)** - Secure your API
3. **[Deploy to Production](../production/deployment/)** - Go live

**Need help?**

- Check the [examples](../../examples/) directory
- Join our [Discord community](https://discord.gg/fraiseql)
- Read the [full documentation](../README/)

## Common Issues & Solutions

**"ImportError: No module named 'fraiseql'"**

- Solution: `pip install fraiseql`

**"Connection refused" to database**

- Solution: Make sure PostgreSQL is running and database exists

**"Table doesn't exist" errors**

- Solution: Run the SQL schema creation commands

**GraphQL returns null**

- Solution: Check your resolver functions and database queries

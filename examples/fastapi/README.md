# FastAPI Integration Example

Complete example of integrating FraiseQL with FastAPI for a task management API.

## Features

This example demonstrates:

- ✅ **FastAPI Integration** - Full setup with dependency injection
- ✅ **CORS Configuration** - Enable cross-origin requests
- ✅ **Database Connection Pool** - Efficient connection management
- ✅ **CQRS Pattern** - Views for queries, PostgreSQL functions for mutations
- ✅ **Type Safety** - Python dataclasses for GraphQL types
- ✅ **Authentication Context** - Pass user context to resolvers
- ✅ **Error Handling** - Proper exception handling and responses
- ✅ **GraphQL Playground** - Interactive API explorer

## Database Schema

The example uses a task management system with:

- **Tables**: `tb_projects`, `tb_tasks`, `tb_users`
- **Views**: `v_projects`, `v_tasks`, `v_users` (for queries)
- **Functions**: `fn_create_project()`, `fn_update_task()`, `fn_assign_task()` (for mutations)

## Setup

### 1. Install Dependencies

```bash
pip install fraiseql fastapi uvicorn psycopg2-binary
```

### 2. Create Database

```bash
createdb fastapi_tasks_demo
psql fastapi_tasks_demo < schema.sql
```

### 3. Run the Server

```bash
python main.py
```

The server will start at `http://localhost:8000`

## GraphQL Playground

Visit `http://localhost:8000/graphql` to access the interactive playground.

### Example Queries

#### Get All Projects

```graphql
query GetProjects {
  projects {
    id
    name
    description
    taskCount
    tasks {
      id
      title
      status
    }
  }
}
```

#### Get Tasks by Status

```graphql
query GetTasksByStatus {
  tasks(where: { status: { eq: "in_progress" } }) {
    id
    title
    priority
    assignee {
      id
      name
      email
    }
  }
}
```

#### Get User with Tasks

```graphql
query GetUserTasks($userId: Int!) {
  user(id: $userId) {
    id
    name
    email
    assignedTasks {
      id
      title
      status
      priority
      project {
        name
      }
    }
  }
}
```

### Example Mutations

#### Create a Project

```graphql
mutation CreateProject {
  createProject(input: {
    name: "FraiseQL v2.0"
    description: "Next major release"
    ownerId: 1
  }) {
    id
    name
    description
    createdAt
  }
}
```

#### Create a Task

```graphql
mutation CreateTask {
  createTask(input: {
    projectId: 1
    title: "Implement TurboRouter v2"
    description: "Add support for mutations"
    priority: "high"
    status: "todo"
  }) {
    id
    title
    priority
    status
    createdAt
  }
}
```

#### Assign Task to User

```graphql
mutation AssignTask {
  assignTask(taskId: 1, userId: 2) {
    id
    title
    assignee {
      id
      name
      email
    }
  }
}
```

#### Update Task Status

```graphql
mutation UpdateTaskStatus {
  updateTask(id: 1, input: {
    status: "completed"
  }) {
    id
    title
    status
    completedAt
  }
}
```

## Architecture Highlights

### CQRS Pattern

**Queries** use database views (`v_projects`, `v_tasks`, `v_users`):

- Optimized for read performance
- Join-free queries where possible
- Indexed for common access patterns

**Mutations** use PostgreSQL functions:

- Encapsulate business logic in the database
- ACID guarantees
- Automatic timestamp management
- Input validation

### Dependency Injection

The `get_db()` dependency provides database connections:

```python
from fraiseql.fastapi import get_db

async def my_resolver(info, db=Depends(get_db)):
    return await db.find("v_tasks")
```

### Context Management

Pass user authentication and request metadata:

```python
async def get_context(request: Request, db=Depends(get_db)):
    return {
        "db": db,
        "user_id": request.headers.get("X-User-ID"),
        "request": request
    }
```

### Error Handling

FraiseQL automatically handles common errors:

- **Validation errors** - Type checking, required fields
- **Database errors** - Connection issues, constraint violations
- **Not found errors** - Missing records return `null`

## Performance Considerations

### Connection Pooling

FastAPI uses connection pooling by default:

```python
fastapi_app = create_app(
    app,
    database_url="postgresql://localhost/fastapi_tasks_demo",
    pool_size=20,  # Max concurrent connections
    max_overflow=10
)
```

### Query Optimization

- Views pre-join frequently accessed data
- Indexes on foreign keys and common filters
- Partial indexes for status-based queries

### N+1 Prevention

FraiseQL automatically batches nested queries:

```graphql
{
  projects {  # 1 query
    tasks {   # 1 batched query for all projects
      assignee {  # 1 batched query for all tasks
        name
      }
    }
  }
}
```

Results in **3 queries total**, not 1 + N + N*M.

## Production Deployment

### Environment Variables

```python
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/fastapi_tasks_demo")
ENABLE_PLAYGROUND = os.getenv("ENABLE_PLAYGROUND", "true").lower() == "true"
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
```

### Docker Deployment

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
CMD ["uvicorn", "main:fastapi_app", "--host", "0.0.0.0", "--port", "8000"]
```

### Health Checks

Add a health check endpoint:

```python
@fastapi_app.get("/health")
async def health():
    return {"status": "healthy"}
```

## Testing

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run tests
pytest tests/
```

Example test:

```python
from httpx import AsyncClient

async def test_create_project():
    async with AsyncClient(app=fastapi_app, base_url="http://test") as client:
        response = await client.post("/graphql", json={
            "query": """
                mutation {
                    createProject(input: {
                        name: "Test Project"
                        ownerId: 1
                    }) { id name }
                }
            """
        })
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["createProject"]["name"] == "Test Project"
```

## Next Steps

- Add authentication with JWT tokens
- Implement subscriptions for real-time updates
- Add rate limiting and caching
- Integrate with Celery for background tasks
- Add comprehensive tests

## Related Examples

- [`../turbo_router_with_complexity.py`](../turbo_router_with_complexity.py) - High-performance query optimization
- [`../enterprise_patterns/cqrs/`](../enterprise_patterns/cqrs/README.md) - Advanced CQRS patterns
- [`../documented_api.py`](../documented_api.py) - Auto-generated documentation

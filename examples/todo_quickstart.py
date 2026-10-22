"""🟢 BEGINNER | ⏱️ 5 min | 🎯 Learning Basics

Simple Todo App - Your First GraphQL API with FraiseQL

This example shows how to create a basic todo list application with GraphQL.
Perfect for learning the fundamentals of queries, mutations, and types.

The todos live in a Python dict so the example needs nothing else to run.
fraiseql still opens a database pool at startup (DATABASE_URL, by default
postgresql://localhost/todos); no query here uses it, so a connection error
in the log is harmless. The next steps read and write PostgreSQL.

LEARNING OUTCOMES:
- Basic GraphQL types, queries, and mutations
- FraiseQL's Python-first approach
- Automatic schema generation
- Computed fields with @fraiseql.field

NEXT STEPS:
- blog_simple/ - A blog with SQL-function mutations
- ecommerce/ - Real business logic
- saas-starter/ - Multi-tenant production patterns
"""

import os
from datetime import datetime
from uuid import uuid4

from graphql import GraphQLResolveInfo

import fraiseql

# First, let's define our GraphQL types using FraiseQL decorators


@fraiseql.type
class Todo:
    """A simple todo item"""

    id: str
    title: str
    completed: bool
    created_at: datetime

    @fraiseql.field
    def is_overdue(self, info: GraphQLResolveInfo) -> bool:
        """Whether the todo is still open more than 7 days after it was created"""
        return not self.completed and (datetime.now() - self.created_at).days > 7


# In a real app, this would be your database
TODOS: dict[str, Todo] = {
    todo.id: todo
    for todo in [
        Todo(id="1", title="Learn GraphQL", completed=True, created_at=datetime(2024, 1, 1, 10)),
        Todo(
            id="2",
            title="Build API with FraiseQL",
            completed=False,
            created_at=datetime(2024, 1, 2),
        ),
        Todo(id="3", title="Deploy to production", completed=False, created_at=datetime.now()),
    ]
}


# Define our GraphQL operations. Every resolver takes info first.


@fraiseql.query
async def todos(info: GraphQLResolveInfo) -> list[Todo]:
    """Get all todos"""
    return list(TODOS.values())


@fraiseql.query
async def todo(info: GraphQLResolveInfo, id: str) -> Todo | None:
    """Get a specific todo by ID"""
    return TODOS.get(id)


@fraiseql.query
async def completed_todos(info: GraphQLResolveInfo) -> list[Todo]:
    """Get only completed todos"""
    return [t for t in TODOS.values() if t.completed]


@fraiseql.mutation
async def create_todo(info: GraphQLResolveInfo, title: str) -> Todo:
    """Create a new todo"""
    new_todo = Todo(id=str(uuid4()), title=title, completed=False, created_at=datetime.now())
    TODOS[new_todo.id] = new_todo
    return new_todo


@fraiseql.mutation
async def toggle_todo(info: GraphQLResolveInfo, id: str) -> Todo | None:
    """Toggle the completed status of a todo"""
    todo_item = TODOS.get(id)
    if todo_item:
        todo_item.completed = not todo_item.completed
    return todo_item


@fraiseql.mutation
async def delete_todo(info: GraphQLResolveInfo, id: str) -> bool:
    """Delete a todo; false if there was none"""
    return TODOS.pop(id, None) is not None


# Create the FraiseQL app
app = fraiseql.create_fraiseql_app(
    database_url=os.getenv("DATABASE_URL", "postgresql://localhost/todos"),
    # Register your types; decorated queries and mutations register themselves
    types=[Todo],
    # Configuration
    title="Todo GraphQL API",
    description="Simple Todo App with FraiseQL",
    version="0.1.0",
    # Enable GraphQL Playground (default in development)
    production=False,
)


if __name__ == "__main__":
    import uvicorn

    print("🚀 Todo API starting...")
    print("📊 GraphQL Playground: http://localhost:8000/graphql")
    print()
    print("Try these queries:")
    print()
    print("Get all todos:")
    print("query { todos { id title completed createdAt isOverdue } }")
    print()
    print("Create a todo:")
    print('mutation { createTodo(title: "Learn FraiseQL") { id title completed } }')
    print()
    print("Toggle completion:")
    print('mutation { toggleTodo(id: "1") { id title completed } }')
    print()
    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104

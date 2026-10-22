"""🟢 BEGINNER | ⏱️ 5 min | 🎯 Learning Basics

Simple Todo App - Your First GraphQL API with FraiseQL

This example shows how to create a basic todo list application with GraphQL.
Perfect for learning the fundamentals of queries, mutations, and types.

LEARNING OUTCOMES:
- Basic GraphQL types, queries, and mutations
- FraiseQL's Python-first approach
- Automatic schema generation
- Type-safe database operations

NEXT STEPS:
- blog_simple/ - A blog with SQL-function mutations
- ecommerce/ - Real business logic
- saas-starter/ - Multi-tenant production patterns
"""

from datetime import datetime
from uuid import uuid4

import fraiseql

# First, let's define our GraphQL types using FraiseQL decorators


@fraiseql.type
class Todo:
    """A simple todo item"""

    id: str
    title: str
    completed: bool
    created_at: datetime

    def is_overdue(self) -> bool:
        """Check if todo is overdue (more than 7 days old)"""
        return not self.completed and (datetime.now() - self.created_at).days > 7


# Define our GraphQL operations


@fraiseql.query
async def todos() -> list[Todo]:
    """Get all todos"""
    # In a real app, this would query your database
    # For demo purposes, we'll return sample data
    return [
        Todo(
            id="1", title="Learn GraphQL", completed=True, created_at=datetime(2024, 1, 1, 10, 0, 0)
        ),
        Todo(
            id="2",
            title="Build API with FraiseQL",
            completed=False,
            created_at=datetime(2024, 1, 2, 14, 30, 0),
        ),
        Todo(
            id="3",
            title="Deploy to production",
            completed=False,
            created_at=datetime(2024, 1, 3, 9, 15, 0),
        ),
    ]


@fraiseql.query
async def todo(id: str) -> Todo | None:
    """Get a specific todo by ID"""
    # In a real app, this would query your database
    all_todos = await todos()
    return next((t for t in all_todos if t.id == id), None)


@fraiseql.query
async def completed_todos() -> list[Todo]:
    """Get only completed todos"""
    all_todos = await todos()
    return [t for t in all_todos if t.completed]


@fraiseql.mutation
async def create_todo(title: str) -> Todo:
    """Create a new todo"""
    # In a real app, this would insert into your database
    new_todo = Todo(id=str(uuid4()), title=title, completed=False, created_at=datetime.now())
    return new_todo


@fraiseql.mutation
async def toggle_todo(id: str) -> Todo | None:
    """Toggle the completed status of a todo"""
    # In a real app, this would update your database
    todo_item = await todo(id)
    if todo_item:
        todo_item.completed = not todo_item.completed
        return todo_item
    return None


@fraiseql.mutation
async def delete_todo(id: str) -> bool:
    """Delete a todo"""
    # In a real app, this would delete from your database
    todo_item = await todo(id)
    return todo_item is not None


# Create the FraiseQL app
if __name__ == "__main__":
    import uvicorn

    # This is the correct way to create a FraiseQL app
    app = fraiseql.create_fraiseql_app(
        # Database URL is optional for this demo
        # In production, use: database_url="postgresql://user:pass@localhost/dbname"
        database_url=None,
        # Register your types
        types=[Todo],
        # Configuration
        title="Todo GraphQL API",
        description="Simple Todo App with FraiseQL",
        version="0.1.0",
        # Enable GraphQL Playground (default in development)
        production=False,
    )

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
    uvicorn.run(app, host="0.0.0.0", port=8000)

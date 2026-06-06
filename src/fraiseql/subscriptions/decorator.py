"""Subscription decorator for GraphQL subscriptions."""

import inspect
from collections.abc import AsyncGenerator, Callable
from typing import Any, TypeVar, overload

from fraiseql.core.types import SubscriptionField

F = TypeVar("F", bound=Callable[..., Any])


@overload
def subscription(fn: F) -> F: ...


@overload
def subscription(*, authorizer: Any | None = None) -> Callable[[F], F]: ...


def subscription(fn: F | None = None, *, authorizer: Any | None = None) -> F | Callable[[F], F]:
    """Decorator to mark a function as a GraphQL subscription.

    Args:
        fn: The subscription function to decorate (when used without parentheses).
        authorizer: Optional per-operation :class:`~fraiseql.security.Authorizer`
            override (issue #364). It takes precedence over the global default
            authorizer for this subscription only, and is enforced once at subscribe
            time (mirroring ``@query`` / ``@mutation``).

    Example:
        @subscription
        async def task_updates(info, project_id: UUID) -> AsyncGenerator[Task, None]:
            async for task in watch_project_tasks(project_id):
                yield task
    """

    def decorator(func: F) -> F:
        if not inspect.isasyncgenfunction(func):
            msg = (
                f"Subscription {func.__name__} must be an async generator function "
                f"(use 'async def' and 'yield')"
            )
            raise TypeError(
                msg,
            )

        # Extract type hints
        hints = inspect.get_annotations(func)
        return_type = hints.get("return", Any)

        # Parse AsyncGenerator type
        if hasattr(return_type, "__origin__") and return_type.__origin__ is AsyncGenerator:
            yield_type = return_type.__args__[0] if return_type.__args__ else Any
        else:
            # Try to infer from first yield
            yield_type = Any

        # Create subscription field
        field = SubscriptionField(
            name=func.__name__,
            resolver=func,
            return_type=yield_type,
            args=hints,
            description=func.__doc__,
        )

        # Register with schema builder
        from fraiseql.gql.schema_builder import SchemaRegistry

        schema_registry = SchemaRegistry.get_instance()
        schema_registry.register_subscription(func)

        # Add metadata
        func.__fraiseql_subscription__ = True
        func._field_def = field
        # Per-operation authorizer override (issue #364); None falls back to the
        # registry default at subscribe time via resolve_authorizer.
        func.__fraiseql_authorizer__ = authorizer

        return func

    if fn is None:
        return decorator
    return decorator(fn)

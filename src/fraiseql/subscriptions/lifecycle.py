"""Lifecycle hooks for subscriptions."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from graphql import GraphQLResolveInfo

from fraiseql.utils.annotations import wraps

logger = logging.getLogger(__name__)


class SubscriptionLifecycle:
    """Manages subscription lifecycle events."""

    @staticmethod
    def on_start(func: Callable) -> Callable:
        """Hook called when subscription starts."""

        @wraps(func)
        async def wrapper(info: GraphQLResolveInfo, **kwargs: Any) -> str:
            # Record start
            start_time = datetime.now(UTC)
            subscription_id = f"{func.__name__}_{id(info)}"

            # Call hook
            await func(info, subscription_id, **kwargs)

            # Store in context
            if hasattr(info, "context") and info.context is not None:
                info.context["subscription_start"] = start_time
                info.context["subscription_id"] = subscription_id

            return subscription_id

        return wrapper

    @staticmethod
    def on_event(func: Callable) -> Callable:
        """Hook called for each subscription event."""

        @wraps(func)
        async def wrapper(info: GraphQLResolveInfo, event: Any, **kwargs: Any) -> Any:
            # Call hook
            result = await func(info, event, **kwargs)

            # Log event
            if (
                hasattr(info, "context")
                and info.context
                and info.context.get("debug_subscriptions")
            ):
                logger.debug(
                    "Subscription %s emitted: %s",
                    info.context.get("subscription_id"),
                    event,
                )

            return result

        return wrapper

    @staticmethod
    def on_complete(func: Callable) -> Callable:
        """Hook called when subscription completes."""

        @wraps(func)
        async def wrapper(info: GraphQLResolveInfo, **kwargs: Any) -> None:
            # Calculate duration
            start_time = None
            if hasattr(info, "context") and info.context is not None:
                start_time = info.context.get("subscription_start")

            if start_time:
                duration = (datetime.now(UTC) - start_time).total_seconds()
                logger.info("Subscription duration: %ss", duration)

            try:
                # Call hook
                await func(info, **kwargs)
            finally:
                # Cleanup context - always happens even if exception occurs
                if hasattr(info, "context") and info.context is not None:
                    info.context.pop("subscription_start", None)
                    info.context.pop("subscription_id", None)

        return wrapper


def with_lifecycle(
    on_start: Callable | None = None,
    on_event: Callable | None = None,
    on_complete: Callable | None = None,
) -> Callable:
    """Add lifecycle hooks to subscription.

    Usage:
        @subscription
        @with_lifecycle(
            on_start=log_subscription_start,
            on_event=validate_event,
            on_complete=cleanup_resources
        )
        async def my_subscription(info):
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable:
        @wraps(func)
        async def wrapper(info: GraphQLResolveInfo, **kwargs: Any) -> Any:
            # Call on_start
            if on_start:
                await on_start(info, func.__name__, kwargs)

            try:
                # Execute subscription
                async for value in func(info, **kwargs):
                    # Call on_event
                    if on_event:
                        value = await on_event(info, value)  # noqa: PLW2901

                    yield value

            finally:
                # Call on_complete
                if on_complete:
                    await on_complete(info, func.__name__, kwargs)

        return wrapper

    return decorator

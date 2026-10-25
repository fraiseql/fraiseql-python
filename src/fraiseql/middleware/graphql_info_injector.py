"""GraphQL Info Injector Middleware.

This middleware provides automatic injection of GraphQL info into resolver contexts.
"""

import inspect
from typing import Any, Callable, TypeVar

from fraiseql.utils.annotations import wraps

# Type variable for decorators
F = TypeVar("F", bound=Callable[..., Any])


class GraphQLInfoInjector:
    """Middleware for auto-injecting GraphQL info into resolvers."""

    @staticmethod
    def auto_inject(func: F) -> F:
        """Decorator to automatically inject GraphQL info into context.

        This decorator ensures that when a resolver function is called with
        a GraphQL info object, it is automatically injected into the context
        dict if the context exists and is a dict.

        Args:
            func: The resolver function to decorate

        Returns:
            The decorated function
        """
        # Get the function signature
        sig = inspect.signature(func)
        has_info_param = "info" in sig.parameters

        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                # Check if info is passed as an argument
                if has_info_param:
                    # Get the info object from args or kwargs
                    if "info" in kwargs:
                        info = kwargs["info"]
                    elif args and len(args) > 0:
                        # Try to find info in positional args
                        param_names = list(sig.parameters.keys())
                        if "info" in param_names:
                            info_idx = param_names.index("info")
                            if len(args) > info_idx:
                                info = args[info_idx]
                            else:
                                info = None
                        else:
                            info = None
                    else:
                        info = None

                    # Inject info into context if it's a dict
                    if (
                        info is not None
                        and hasattr(info, "context")
                        and isinstance(info.context, dict)
                    ):
                        info.context["graphql_info"] = info

                # Call the original function
                return await func(*args, **kwargs)

            return async_wrapper  # type: ignore[return-value]

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            # Check if info is passed as an argument
            if has_info_param:
                # Get the info object from args or kwargs
                if "info" in kwargs:
                    info = kwargs["info"]
                elif args and len(args) > 0:
                    # Try to find info in positional args
                    param_names = list(sig.parameters.keys())
                    if "info" in param_names:
                        info_idx = param_names.index("info")
                        if len(args) > info_idx:
                            info = args[info_idx]
                        else:
                            info = None
                    else:
                        info = None
                else:
                    info = None

                # Inject info into context if it's a dict
                if info is not None and hasattr(info, "context") and isinstance(info.context, dict):
                    info.context["graphql_info"] = info

            # Call the original function
            return func(*args, **kwargs)

        return sync_wrapper  # type: ignore[return-value]

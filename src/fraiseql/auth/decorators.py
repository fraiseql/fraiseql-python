"""Authentication decorators for GraphQL resolvers."""

from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from graphql import GraphQLError, GraphQLResolveInfo

from fraiseql.auth.base import UserContext

P = ParamSpec("P")
T = TypeVar("T")


def _is_resolve_info(info: object) -> bool:
    """Whether ``info`` is a resolver's info.

    graphql-core passes a GraphQLResolveInfo; fraiseql's multi-field path (a query
    with several root fields) passes its own stand-in with the same attributes, so
    the check is on what the decorators read rather than on the class.
    """
    return isinstance(info, GraphQLResolveInfo) or (
        hasattr(info, "context") and hasattr(info, "field_name")
    )


def requires_auth(
    func: Callable[P, Coroutine[Any, Any, T]],
) -> Callable[P, Coroutine[Any, Any, T]]:
    """Decorator to require authentication for a resolver.

    Usage:
        @requires_auth
        async def my_resolver(info, **kwargs):
            user = info.context["user"]  # Guaranteed to be authenticated
            ...
    """

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        # First argument is always info for GraphQL resolvers
        info = args[0] if args else kwargs.get("info")
        if not info:
            msg = "GraphQL resolver must have info as first argument"
            raise ValueError(msg)

        if not _is_resolve_info(info):
            msg = "First argument must be GraphQLResolveInfo"
            raise TypeError(msg)

        context = info.context
        user = context.get("user")

        if not user or not isinstance(user, UserContext):
            msg = "Authentication required"
            raise GraphQLError(msg, extensions={"code": "UNAUTHENTICATED"})

        return await func(*args, **kwargs)

    return wrapper


def requires_permission(
    permission: str,
) -> Callable[[Callable[P, Coroutine[Any, Any, T]]], Callable[P, Coroutine[Any, Any, T]]]:
    """Decorator to require a specific permission for a resolver.

    Usage:
        @requires_permission("users:write")
        async def create_user(info, input):
            ...
    """

    def decorator(
        func: Callable[P, Coroutine[Any, Any, T]],
    ) -> Callable[P, Coroutine[Any, Any, T]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # First argument is always info for GraphQL resolvers
            info = args[0] if args else kwargs.get("info")
            if not info:
                msg = "GraphQL resolver must have info as first argument"
                raise ValueError(msg)

            # Type guard to ensure info is GraphQLResolveInfo
            if not _is_resolve_info(info):
                msg = "First argument must be GraphQLResolveInfo"
                raise TypeError(msg)

            context = info.context
            user = context.get("user")

            if not user or not isinstance(user, UserContext):
                msg = "Authentication required"
                raise GraphQLError(
                    msg,
                    extensions={"code": "UNAUTHENTICATED"},
                )

            if not user.has_permission(permission):
                msg = f"Permission '{permission}' required"
                raise GraphQLError(
                    msg,
                    extensions={"code": "FORBIDDEN", "required_permission": permission},
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def requires_role(
    role: str,
) -> Callable[[Callable[P, Coroutine[Any, Any, T]]], Callable[P, Coroutine[Any, Any, T]]]:
    """Decorator to require a specific role for a resolver.

    Usage:
        @requires_role("admin")
        async def admin_mutation(info, input):
            ...
    """

    def decorator(
        func: Callable[P, Coroutine[Any, Any, T]],
    ) -> Callable[P, Coroutine[Any, Any, T]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # First argument is always info for GraphQL resolvers
            info = args[0] if args else kwargs.get("info")
            if not info:
                msg = "GraphQL resolver must have info as first argument"
                raise ValueError(msg)

            # Type guard to ensure info is GraphQLResolveInfo
            if not _is_resolve_info(info):
                msg = "First argument must be GraphQLResolveInfo"
                raise TypeError(msg)

            context = info.context
            user = context.get("user")

            if not user or not isinstance(user, UserContext):
                msg = "Authentication required"
                raise GraphQLError(
                    msg,
                    extensions={"code": "UNAUTHENTICATED"},
                )

            if not user.has_role(role):
                msg = f"Role '{role}' required"
                raise GraphQLError(
                    msg,
                    extensions={"code": "FORBIDDEN", "required_role": role},
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def requires_any_permission(
    *permissions: str,
) -> Callable[[Callable[P, Coroutine[Any, Any, T]]], Callable[P, Coroutine[Any, Any, T]]]:
    """Decorator to require any of the specified permissions.

    Usage:
        @requires_any_permission("users:write", "admin:all")
        async def update_user(info, id, input):
            ...
    """

    def decorator(
        func: Callable[P, Coroutine[Any, Any, T]],
    ) -> Callable[P, Coroutine[Any, Any, T]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # First argument is always info for GraphQL resolvers
            info = args[0] if args else kwargs.get("info")
            if not info:
                msg = "GraphQL resolver must have info as first argument"
                raise ValueError(msg)

            # Type guard to ensure info is GraphQLResolveInfo
            if not _is_resolve_info(info):
                msg = "First argument must be GraphQLResolveInfo"
                raise TypeError(msg)

            context = info.context
            user = context.get("user")

            if not user or not isinstance(user, UserContext):
                msg = "Authentication required"
                raise GraphQLError(
                    msg,
                    extensions={"code": "UNAUTHENTICATED"},
                )

            if not user.has_any_permission(list(permissions)):
                msg = f"One of these permissions required: {', '.join(permissions)}"
                raise GraphQLError(
                    msg,
                    extensions={
                        "code": "FORBIDDEN",
                        "required_permissions": list(permissions),
                    },
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def requires_any_role(
    *roles: str,
) -> Callable[[Callable[P, Coroutine[Any, Any, T]]], Callable[P, Coroutine[Any, Any, T]]]:
    """Decorator to require any of the specified roles.

    Usage:
        @requires_any_role("admin", "moderator")
        async def moderate_content(info, id):
            ...
    """

    def decorator(
        func: Callable[P, Coroutine[Any, Any, T]],
    ) -> Callable[P, Coroutine[Any, Any, T]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # First argument is always info for GraphQL resolvers
            info = args[0] if args else kwargs.get("info")
            if not info:
                msg = "GraphQL resolver must have info as first argument"
                raise ValueError(msg)

            # Type guard to ensure info is GraphQLResolveInfo
            if not _is_resolve_info(info):
                msg = "First argument must be GraphQLResolveInfo"
                raise TypeError(msg)

            context = info.context
            user = context.get("user")

            if not user or not isinstance(user, UserContext):
                msg = "Authentication required"
                raise GraphQLError(
                    msg,
                    extensions={"code": "UNAUTHENTICATED"},
                )

            if not user.has_any_role(list(roles)):
                msg = f"One of these roles required: {', '.join(roles)}"
                raise GraphQLError(
                    msg,
                    extensions={"code": "FORBIDDEN", "required_roles": list(roles)},
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator

"""Declarative filtering for subscriptions."""

import ast
from typing import Any, Callable, ClassVar

from graphql import GraphQLResolveInfo

from fraiseql.core.exceptions import FilterError
from fraiseql.utils.annotations import wraps


class FilterExpressionEvaluator:
    """Safely evaluates filter expressions."""

    ALLOWED_NAMES: ClassVar[set[str]] = {
        "user",
        "project",
        "resource",
        "context",
        "info",
        "and",
        "or",
        "not",
        "in",
        "True",
        "False",
        "None",
    }

    ALLOWED_ATTRIBUTES: ClassVar[set[str]] = {
        "is_public",
        "has_access",
        "is_owner",
        "is_member",
        "role",
        "permissions",
        "id",
        "status",
        "get",
        "context",
    }

    def __init__(self, context: dict[str, Any]) -> None:
        self.context = context

    def evaluate(self, expression: str) -> bool:
        """Safely evaluate a filter expression."""
        try:
            # Parse expression
            tree = ast.parse(expression, mode="eval")

            # Validate AST
            self._validate_ast(tree)

            # Compile and evaluate
            code = compile(tree, "<filter>", "eval")
            return eval(  # noqa: S307
                code,
                {"__builtins__": {}},
                self.context,
            )

        except Exception as e:
            msg = f"Invalid filter expression: {e}"
            raise FilterError(msg) from e

    def _validate_ast(self, node: ast.AST) -> None:
        """Validate AST nodes for safety."""
        for child in ast.walk(node):
            # Only allow specific node types
            allowed_types = (
                ast.Expression,
                ast.Compare,
                ast.BoolOp,
                ast.Name,
                ast.Attribute,
                ast.Constant,
                ast.And,
                ast.Or,
                ast.Not,
                ast.Eq,
                ast.NotEq,
                ast.In,
                ast.NotIn,
                ast.Load,
                ast.Call,
                ast.List,
                ast.Tuple,
                ast.Dict,
            )

            if not isinstance(child, allowed_types):
                msg = f"Forbidden operation: {type(child).__name__}"
                raise FilterError(msg)

            # Check names
            if isinstance(child, ast.Name) and child.id not in self.ALLOWED_NAMES:
                msg = f"Forbidden name: {child.id}"
                raise FilterError(msg)

            # Check attributes
            if isinstance(child, ast.Attribute) and child.attr not in self.ALLOWED_ATTRIBUTES:
                msg = f"Forbidden attribute: {child.attr}"
                raise FilterError(msg)


def filter(expression: str) -> Callable:  # noqa: A001
    """Decorator for declarative subscription filtering.

    Usage:
        @subscription
        @filter("project.is_public or user.has_access")
        async def project_updates(info, project_id: UUID):
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable:
        func._filter_expression = expression

        @wraps(func)
        async def wrapper(info: GraphQLResolveInfo, **kwargs: Any) -> Any:
            # Build filter context
            context = {
                "info": info,
                "user": info.context.get("user") if hasattr(info, "context") else None,
                "context": info.context if hasattr(info, "context") else {},
                **kwargs,  # Include arguments
            }

            # Load related objects if needed
            if "project_id" in kwargs and hasattr(info, "context") and "db" in info.context:
                db = info.context["db"]
                project = await db.fetch_one(
                    "SELECT * FROM projects WHERE id = $1",
                    kwargs["project_id"],
                )
                context["project"] = project

            # Evaluate filter
            evaluator = FilterExpressionEvaluator(context)
            # Add parameter names to allowed names
            evaluator.ALLOWED_NAMES = evaluator.ALLOWED_NAMES.union(kwargs.keys())
            if not evaluator.evaluate(expression):
                msg = "Filter condition not met"
                raise PermissionError(msg)

            # Execute subscription
            async for value in func(info, **kwargs):
                yield value

        return wrapper

    return decorator

"""Complexity analysis for GraphQL subscriptions."""

from dataclasses import dataclass
from typing import Any, Callable

from graphql import SelectionSetNode

from fraiseql.core.exceptions import ComplexityLimitExceededError
from fraiseql.utils.annotations import wraps


@dataclass
class ComplexityConfig:
    """Configuration for complexity analysis."""

    max_complexity: int = 1000
    max_depth: int = 10
    field_costs: dict[str, int] = None

    def __post_init__(self) -> None:
        """Initialize field costs with defaults if not provided."""
        if self.field_costs is None:
            self.field_costs = {
                "default": 1,
                "connection": 10,
                "aggregation": 50,
                "search": 20,
            }


class SubscriptionComplexityAnalyzer:
    """Analyzes subscription complexity before execution."""

    def __init__(self, config: ComplexityConfig = None) -> None:
        self.config = config or ComplexityConfig()

    def calculate_complexity(self, info: Any, field_name: str, args: dict[str, Any]) -> int:
        """Calculate complexity score for a subscription."""
        # Base cost
        cost = self.config.field_costs.get(field_name, self.config.field_costs["default"])

        # Multipliers based on arguments
        if "first" in args or "last" in args:
            limit = args.get("first", args.get("last", 10))
            cost *= min(limit, 100)  # Cap multiplier at 100

        if args.get("filter"):
            # Complex filters increase cost
            cost *= len(args["filter"].keys())

        # Check selection set depth
        if hasattr(info, "field_nodes") and info.field_nodes:
            depth = self._calculate_depth(info.field_nodes[0].selection_set)
            if depth > self.config.max_depth:
                msg = f"Query depth {depth} exceeds maximum {self.config.max_depth}"
                raise ComplexityLimitExceededError(
                    msg,
                )

            # Add cost for nested selections
            cost += self._calculate_selection_cost(
                info.field_nodes[0].selection_set,
                getattr(info, "fragments", {}),
            )

        return cost

    def _calculate_depth(
        self, selection_set: SelectionSetNode | None, current_depth: int = 0
    ) -> int:
        """Calculate maximum depth of selection set."""
        if not selection_set:
            return current_depth

        max_depth = current_depth
        for selection in selection_set.selections:
            if hasattr(selection, "selection_set"):
                depth = self._calculate_depth(selection.selection_set, current_depth + 1)
                max_depth = max(max_depth, depth)

        return max_depth

    def _calculate_selection_cost(
        self, selection_set: SelectionSetNode | None, fragments: dict[str, Any]
    ) -> int:
        """Calculate cost of selection set."""
        if not selection_set:
            return 0

        total_cost = 0
        for selection in selection_set.selections:
            if hasattr(selection, "name"):
                field_name = selection.name.value
                field_cost = self.config.field_costs.get(
                    field_name,
                    self.config.field_costs["default"],
                )
                total_cost += field_cost

                # Recursive cost for nested selections
                if hasattr(selection, "selection_set"):
                    total_cost += self._calculate_selection_cost(selection.selection_set, fragments)

        return total_cost


def complexity(score: int | None = None, max_depth: int | None = None) -> Callable:
    """Decorator to set complexity limits for subscriptions.

    Usage:
        @subscription
        @complexity(score=100, max_depth=5)
        async def expensive_subscription(info):
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable:
        # Store complexity metadata
        func._complexity_score = score
        func._max_depth = max_depth

        @wraps(func)
        async def wrapper(info: Any, **kwargs: Any) -> Any:
            # Get analyzer from context
            analyzer = info.context.get("complexity_analyzer") if hasattr(info, "context") else None
            if not analyzer:
                analyzer = SubscriptionComplexityAnalyzer()

            # Override config if specified
            if score is not None:
                analyzer.config.max_complexity = score
            if max_depth is not None:
                analyzer.config.max_depth = max_depth

            # Calculate complexity
            complexity_score = analyzer.calculate_complexity(info, func.__name__, kwargs)

            # Check limit
            if complexity_score > analyzer.config.max_complexity:
                msg = (
                    f"Subscription complexity {complexity_score} exceeds "
                    f"maximum {analyzer.config.max_complexity}"
                )
                raise ComplexityLimitExceededError(
                    msg,
                )

            # Execute subscription
            async for value in func(info, **kwargs):
                yield value

        return wrapper

    return decorator

"""Decorators for DataLoader integration."""

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, get_type_hints

from graphql import GraphQLResolveInfo

from fraiseql.optimization.dataloader import DataLoader
from fraiseql.optimization.registry import get_loader
from fraiseql.utils.annotations import set_annotations

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def dataloader_field(
    loader_class: type[DataLoader],
    *,
    key_field: str,
    description: str | None = None,
) -> Callable[[F], F]:
    """Decorator to automatically use DataLoader for field resolution.

    This decorator automatically implements DataLoader-based field resolution,
    eliminating the need to manually call get_loader() in every field resolver.

    Args:
        loader_class: DataLoader class to use for loading
        key_field: Field name on the parent object containing the key to load
        description: Optional field description for GraphQL schema

    Usage:
        @fraiseql.type
        class Post:
            author_id: UUID

            @fraiseql.dataloader_field(UserDataLoader, key_field="author_id")
            async def author(self, info) -> User | None:
                '''Load post author using DataLoader.'''
                pass  # Implementation is auto-generated

    The decorator will:
    1. Mark the method with metadata for schema building
    2. Auto-implement the method to use the specified DataLoader
    3. Handle key extraction from the parent object
    4. Return properly typed results
    """
    # Validation
    if not inspect.isclass(loader_class) or not issubclass(loader_class, DataLoader):
        msg = "loader_class must be a DataLoader subclass"
        raise ValueError(msg)

    if not key_field:
        msg = "key_field is required"
        raise ValueError(msg)

    def decorator(method: F) -> F:
        # Get method signature for validation
        sig = inspect.signature(method)
        hints = get_type_hints(method)

        # Validate method signature
        params = list(sig.parameters.keys())
        if len(params) < 2 or params[0] != "self" or params[1] != "info":
            msg = (
                f"@dataloader_field decorated method {method.__name__} must have "
                "signature (self, info) -> ReturnType"
            )
            raise ValueError(
                msg,
            )

        # Get return type for validation
        return_type = hints.get("return")
        if return_type is None:
            msg = (
                f"@dataloader_field decorated method {method.__name__} must have "
                "a return type annotation"
            )
            raise ValueError(
                msg,
            )

        # Create the auto-implemented resolver
        async def auto_resolver(self: Any, info: GraphQLResolveInfo) -> Any:
            """Auto-generated DataLoader resolver."""
            # SECURITY: Validate self object to prevent attribute injection attacks
            if not hasattr(self, key_field):
                msg = (
                    f"Object {type(self).__name__} does not have required field '{key_field}'. "
                    "This may indicate a security issue or misconfiguration."
                )
                raise AttributeError(
                    msg,
                )

            # Get the key value from the parent object with validation
            key_value = getattr(self, key_field, None)
            if key_value is None:
                return None

            # SECURITY: Validate key_value type to prevent injection
            if not isinstance(key_value, str | int | bytes | type(None)) and not hasattr(
                key_value,
                "__hash__",
            ):
                msg = f"Key field '{key_field}' must be hashable, got {type(key_value)}"
                raise ValueError(msg)

            # Get the DataLoader instance
            loader = get_loader(loader_class)

            # Load the value
            result_data = await loader.load(key_value)
            if result_data is None:
                return None

            # Convert result to proper type - SECURITY CRITICAL
            # Validate and sanitize before any type construction
            if result_data is None:
                return None

            try:
                # Handle Python 3.10+ UnionType (Type | None)
                import types

                if isinstance(return_type, types.UnionType):
                    args = getattr(return_type, "__args__", ())
                    if args:
                        # Get the non-None type
                        target_type = next((arg for arg in args if arg is not type(None)), None)
                        if target_type:
                            if hasattr(target_type, "__annotations__") and isinstance(
                                result_data,
                                dict,
                            ):
                                # Only construct if we have annotations (dataclass-like)
                                annotations = getattr(target_type, "__annotations__", {})
                                filtered_data = {
                                    k: v for k, v in result_data.items() if k in annotations
                                }
                                return target_type(**filtered_data)
                            if (
                                hasattr(target_type, "from_dict")
                                and callable(target_type.from_dict)
                                and isinstance(result_data, dict)
                            ):
                                return target_type.from_dict(result_data)
                    return result_data

                # Handle Optional[Type] and similar generic types (typing module)
                if hasattr(return_type, "__origin__"):
                    args = getattr(return_type, "__args__", ())
                    if args:
                        target_type = args[0]
                        # SECURITY: Only allow safe type construction
                        if hasattr(target_type, "__annotations__") and isinstance(
                            result_data,
                            dict,
                        ):
                            # Only construct if we have annotations (dataclass-like)
                            annotations = getattr(target_type, "__annotations__", {})
                            filtered_data = {
                                k: v for k, v in result_data.items() if k in annotations
                            }
                            return target_type(**filtered_data)
                        if (
                            hasattr(target_type, "from_dict")
                            and callable(target_type.from_dict)
                            and isinstance(result_data, dict)
                        ):
                            return target_type.from_dict(result_data)
                    return result_data

                # Handle direct type construction
                if hasattr(return_type, "__annotations__") and isinstance(result_data, dict):
                    # Only construct if we have annotations (dataclass-like)
                    annotations = getattr(return_type, "__annotations__", {})
                    filtered_data = {k: v for k, v in result_data.items() if k in annotations}
                    return return_type(**filtered_data)
                if (
                    hasattr(return_type, "from_dict")
                    and callable(return_type.from_dict)
                    and isinstance(result_data, dict)
                ):
                    return return_type.from_dict(result_data)

                # Fallback: return raw data (safer than arbitrary construction)
                return result_data

            except Exception:
                # CRITICAL: Never expose internal errors to prevent information leakage
                logger.exception("DataLoader type conversion failed")

                # For debugging, include more info about the return type
                type_info = f"{return_type}" if return_type else "unknown type"
                msg = f"DataLoader type conversion failed for {type_info}"
                raise RuntimeError(msg) from None

        # Preserve method metadata
        auto_resolver.__name__ = method.__name__
        auto_resolver.__doc__ = method.__doc__ or f"Auto-generated DataLoader field for {key_field}"
        set_annotations(auto_resolver, method.__annotations__)

        # Add DataLoader metadata for schema building
        auto_resolver.__fraiseql_dataloader__ = {
            "loader_class": loader_class,
            "key_field": key_field,
            "description": description,
            "original_method": method,
            "auto_generated": True,
        }

        # Mark as a field resolver
        auto_resolver.__fraiseql_field__ = True
        auto_resolver.__fraiseql_field_description__ = description

        return auto_resolver  # type: ignore[return-value]

    return decorator

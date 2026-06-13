"""GraphQL schema builder managing type and mutation registrations.

Provides a singleton registry to collect query types and mutation resolvers,
and builds the corresponding GraphQLObjectType instances for the schema.

Typical usage involves registering decorated Python types and resolver
functions, then composing a complete GraphQLSchema for your API.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from graphql import GraphQLObjectType, GraphQLSchema, print_schema

from fraiseql.config.schema_config import SchemaConfig
from fraiseql.gql.builders import (
    SchemaComposer,
    SchemaRegistry,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from fraiseql.security.authorization import Authorizer
    from fraiseql.security.decision_cache import DecisionCache

logger = logging.getLogger(__name__)

# The SchemaRegistry is imported from builders module


def build_fraiseql_schema(
    *,
    query_types: list[type | Callable[..., Any]] | None = None,
    mutation_resolvers: list[type | Callable[..., Any]] | None = None,
    subscription_resolvers: list[Callable[..., Any]] | None = None,
    camel_case_fields: bool = True,
    authorizer: Authorizer | None = None,
    decision_cache: DecisionCache | None = None,
) -> GraphQLSchema:
    """Compose a full GraphQL schema from query types, mutation resolvers, and subscriptions.

    Args:
        query_types: Optional list of Python types or query functions to register.
        mutation_resolvers: Optional list of mutation classes or resolver functions.
        subscription_resolvers: Optional list of subscription functions to register.
        camel_case_fields: Whether to convert snake_case field names to camelCase in GraphQL schema.
        authorizer: Optional global default operation authorizer (issue #362). When
            provided, it is installed as ``SchemaRegistry.default_authorizer`` and
            enforced around every root query/mutation operation. ``None`` leaves the
            slot cleared, so behavior is byte-for-byte unchanged.
        decision_cache: Optional authorization decision cache (issue #367). Installed as
            ``SchemaRegistry.decision_cache`` and consulted by enforcement and the bypass
            gates. ``None`` leaves the slot cleared (always-evaluate, today's behavior).

    Returns:
        A GraphQLSchema combining the registered query, mutation, and subscription types.
    """
    if mutation_resolvers is None:
        mutation_resolvers = []
    if query_types is None:
        query_types = []
    if subscription_resolvers is None:
        subscription_resolvers = []

    # Set the camelCase configuration
    SchemaConfig.set_config(camel_case_fields=camel_case_fields)

    # Clear GraphQL type cache since field names might change
    from fraiseql.core.graphql_type import _graphql_type_cache

    _graphql_type_cache.clear()

    registry = SchemaRegistry.get_instance()
    registry.set_default_authorizer(authorizer)
    registry.set_decision_cache(decision_cache)

    for typ in query_types:
        if callable(typ) and not isinstance(typ, type):
            # It's a query function
            registry.register_query(typ)
        else:
            # It's a type
            registry.register_type(typ)

    for fn in mutation_resolvers:
        registry.register_mutation(fn)

    for fn in subscription_resolvers:
        registry.register_subscription(fn)

    # Register all types with the Rust transformer for high-performance JSON transformation
    from fraiseql.core.rust_transformer import get_transformer

    rust_transformer = get_transformer()
    for typ in registry.types:
        try:
            rust_transformer.register_type(typ)
            logger.debug(f"Registered type '{typ.__name__}' with Rust transformer")
        except Exception as e:
            logger.warning(f"Failed to register type '{typ.__name__}' with Rust transformer: {e}")

    # Use the SchemaComposer to build the schema
    composer = SchemaComposer(registry)
    return composer.compose()


# Add backward compatibility methods to SchemaRegistry
def _build_query_type(self: SchemaRegistry) -> GraphQLObjectType:
    """Build the Query type using QueryTypeBuilder."""
    from fraiseql.gql.builders.query_builder import QueryTypeBuilder

    builder = QueryTypeBuilder(self)
    return builder.build()


def _build_mutation_type(self: SchemaRegistry) -> GraphQLObjectType:
    """Build the Mutation type using MutationTypeBuilder."""
    from fraiseql.gql.builders.mutation_builder import MutationTypeBuilder

    builder = MutationTypeBuilder(self)
    return builder.build()


def _build_subscription_type(self: SchemaRegistry) -> GraphQLObjectType:
    """Build the Subscription type using SubscriptionTypeBuilder."""
    from fraiseql.gql.builders.subscription_builder import SubscriptionTypeBuilder

    builder = SubscriptionTypeBuilder(self)
    return builder.build()


def _build_schema(self: SchemaRegistry) -> GraphQLSchema:
    """Build the complete schema using SchemaComposer."""
    composer = SchemaComposer(self)
    return composer.compose()


def _build_schema_string(self: SchemaRegistry) -> str:
    """Build the GraphQL schema and return it as a string."""
    schema = self.build_schema()
    return print_schema(schema)


# Patch the SchemaRegistry class to maintain backward compatibility
SchemaRegistry.build_query_type = _build_query_type
SchemaRegistry.build_mutation_type = _build_mutation_type
SchemaRegistry.build_subscription_type = _build_subscription_type
SchemaRegistry.build_schema = _build_schema
SchemaRegistry.build_schema_string = _build_schema_string

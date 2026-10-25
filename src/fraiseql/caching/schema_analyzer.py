"""GraphQL schema analyzer for automatic CASCADE rule generation.

This module analyzes FraiseQL GraphQL schemas to detect type relationships
and automatically generate CASCADE invalidation rules for the cache.

When a GraphQL type has a field that references another type (e.g., Post.author -> User),
this analyzer creates a CASCADE rule so that when the referenced type changes (User),
the caches of types that reference it (Post) are automatically invalidated.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from graphql import GraphQLObjectType, GraphQLSchema

logger = logging.getLogger(__name__)


@dataclass
class CascadeRule:
    """Represents a CASCADE invalidation rule.

    Attributes:
        source_domain: The domain that triggers invalidation when it changes
        target_domain: The domain whose caches should be invalidated
        rule_type: Either 'invalidate' or 'notify' (default: 'invalidate')
        confidence: Confidence level (0.0-1.0) for auto-generated rules
    """

    source_domain: str
    target_domain: str
    rule_type: str = "invalidate"
    confidence: float = 1.0

    def __str__(self) -> str:
        return f"{self.source_domain} → {self.target_domain}"


class SchemaAnalyzer:
    """Analyzes GraphQL schema to extract CASCADE rules for cache invalidation.

    This analyzer detects relationships between GraphQL types and generates
    CASCADE rules that ensure cache consistency when related data changes.

    Example:
        Given a schema:
        ```graphql
        type Post {
            id: ID!
            title: String!
            author: User!    # Relationship detected!
            comments: [Comment!]!
        }

        type User {
            id: ID!
            name: String!
        }

        type Comment {
            id: ID!
            content: String!
            author: User!
        }
        ```

        The analyzer generates CASCADE rules:
        - user → post (when user changes, invalidate posts)
        - post → comment (when post changes, invalidate comments)
        - user → comment (when user changes, invalidate comments)
    """

    def __init__(
        self,
        schema: GraphQLSchema,
        *,
        type_to_domain_fn: Callable[[str], str] | None = None,
        exclude_types: set[str] | None = None,
    ) -> None:
        """Initialize schema analyzer.

        Args:
            schema: GraphQL schema to analyze
            type_to_domain_fn: Optional custom function to map type names to domain names
            exclude_types: Set of type names to exclude from analysis (e.g., Query, Mutation)
        """
        self.schema = schema
        self.type_to_domain_fn = type_to_domain_fn or self._default_type_to_domain
        self.exclude_types = exclude_types or {
            "Query",
            "Mutation",
            "Subscription",
            "__Schema",
            "__Type",
            "__Field",
            "__InputValue",
            "__EnumValue",
            "__Directive",
        }

    def _default_type_to_domain(self, type_name: str) -> str:
        """Convert GraphQL type name to domain name.

        By default, converts to lowercase snake_case:
        - User → user
        - BlogPost → blog_post
        - UserPreference → user_preference

        Args:
            type_name: GraphQL type name

        Returns:
            Domain name for cache invalidation
        """
        # Convert camelCase/PascalCase to snake_case
        import re

        # Insert underscore before uppercase letters
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", type_name)
        # Insert underscore before sequences of uppercase letters
        s2 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1)
        return s2.lower()

    def _is_object_type(self, field_type: Any) -> bool:
        """Check if field type is a GraphQL object type (relationship).

        Args:
            field_type: GraphQL type to check

        Returns:
            True if this represents a relationship to another object type
        """
        # Unwrap List and NonNull wrappers
        from graphql import GraphQLList, GraphQLNonNull

        while isinstance(field_type, (GraphQLList, GraphQLNonNull)):
            field_type = field_type.of_type

        # Check if it's an object type (not a scalar or enum)
        return isinstance(field_type, GraphQLObjectType)

    def _is_list_type(self, field_type: Any) -> bool:
        """Check if field type is a list.

        Args:
            field_type: GraphQL type to check

        Returns:
            True if this field is a list of items
        """
        from graphql import GraphQLList, GraphQLNonNull

        # Unwrap NonNull first
        if isinstance(field_type, GraphQLNonNull):
            field_type = field_type.of_type

        return isinstance(field_type, GraphQLList)

    def analyze_relationships(self) -> list[CascadeRule]:
        """Extract CASCADE rules from GraphQL schema by analyzing type relationships.

        Iterates through all types in the schema and detects fields that reference
        other object types. For each relationship, creates a CASCADE rule.

        Returns:
            List of CASCADE rules to register

        Example:
            analyzer = SchemaAnalyzer(schema)
            rules = analyzer.analyze_relationships()
            for rule in rules:
                await cache.register_cascade_rule(rule.source_domain, rule.target_domain)
        """
        rules: list[CascadeRule] = []
        processed_relationships: set[tuple[str, str]] = set()

        type_map = self.schema.type_map

        for type_name, type_def in type_map.items():
            # Skip excluded types (Query, Mutation, introspection types, etc.)
            if type_name in self.exclude_types:
                continue

            # Skip non-object types
            if not isinstance(type_def, GraphQLObjectType):
                continue

            # Get domain name for this type
            target_domain = self.type_to_domain_fn(type_name)

            # Analyze fields for relationships
            for field_name, field_def in type_def.fields.items():
                field_type = field_def.type

                # Check if this field is a relationship to another object type
                if not self._is_object_type(field_type):
                    continue

                # Unwrap to get the actual object type
                from graphql import GraphQLList, GraphQLNonNull

                unwrapped_type = field_type
                while isinstance(unwrapped_type, (GraphQLList, GraphQLNonNull)):
                    unwrapped_type = unwrapped_type.of_type

                # Skip self-references (e.g., parent: User)
                if unwrapped_type.name == type_name:
                    logger.debug("Skipping self-reference: %s.%s", type_name, field_name)
                    continue

                # Get source domain (the related type)
                source_domain = self.type_to_domain_fn(unwrapped_type.name)

                # Create CASCADE rule: source → target
                # When source changes, invalidate target caches
                relationship_key = (source_domain, target_domain)

                if relationship_key not in processed_relationships:
                    is_list = self._is_list_type(field_type)

                    rule = CascadeRule(
                        source_domain=source_domain,
                        target_domain=target_domain,
                        rule_type="invalidate",
                        confidence=1.0 if not is_list else 0.9,  # Slightly lower for lists
                    )

                    rules.append(rule)
                    processed_relationships.add(relationship_key)

                    logger.debug(
                        "Detected relationship: %s.%s (%s) -> CASCADE rule: %s",
                        type_name,
                        field_name,
                        unwrapped_type.name,
                        rule,
                    )

        logger.info(
            "Schema analysis complete: found %d CASCADE rules from %d relationships",
            len(rules),
            len(processed_relationships),
        )

        return rules

    def get_domain_dependencies(self) -> dict[str, set[str]]:
        """Get dependency graph of domains.

        Returns:
            Dictionary mapping each domain to set of domains it depends on

        Example:
            {
                "post": {"user"},  # posts depend on users
                "comment": {"user", "post"},  # comments depend on users and posts
            }
        """
        dependencies: dict[str, set[str]] = {}

        rules = self.analyze_relationships()

        for rule in rules:
            if rule.target_domain not in dependencies:
                dependencies[rule.target_domain] = set()

            dependencies[rule.target_domain].add(rule.source_domain)

        return dependencies

    def print_analysis_report(self) -> None:
        """Print a detailed analysis report of CASCADE rules.

        Useful for debugging and understanding the cache invalidation structure.

        Note: This method uses print() intentionally for CLI output, which is acceptable
        per ruff configuration for report generation methods.
        """
        rules = self.analyze_relationships()
        dependencies = self.get_domain_dependencies()

        # Build report as string for logging/printing
        report_lines = [
            "",
            "=" * 80,
            "FraiseQL Cache CASCADE Rules Analysis",
            "=" * 80,
            "",
            f"Total CASCADE Rules: {len(rules)}",
            f"Domains with Dependencies: {len(dependencies)}",
            "",
            "-" * 80,
            "CASCADE Rules (Source → Target)",
            "-" * 80,
        ]

        for rule in sorted(rules, key=lambda r: (r.source_domain, r.target_domain)):
            confidence_indicator = "✓" if rule.confidence >= 0.95 else "~"
            report_lines.append(
                f"  {confidence_indicator} {rule.source_domain} → {rule.target_domain}"
            )

        report_lines.extend(
            [
                "",
                "-" * 80,
                "Domain Dependency Graph",
                "-" * 80,
            ]
        )

        for domain, deps in sorted(dependencies.items()):
            deps_str = ", ".join(sorted(deps))
            report_lines.append(f"  {domain} depends on: {deps_str}")

        report_lines.extend(["", "=" * 80, ""])

        # Log the report
        report = "\n".join(report_lines)
        logger.info(report)


async def setup_auto_cascade_rules(
    cache: Any, schema: GraphQLSchema, *, verbose: bool = False
) -> int:
    """Analyze schema and register all CASCADE rules automatically.

    This is the main entry point for auto-CASCADE setup. Call this during
    application startup to analyze your GraphQL schema and register all
    necessary CASCADE invalidation rules.

    Args:
        cache: PostgresCache instance with register_cascade_rule method
        schema: GraphQL schema to analyze
        verbose: If True, print detailed analysis report

    Returns:
        Number of CASCADE rules registered (0 when pg_fraiseql_cache isn't
        installed, as every registration is then skipped)

    Example:
        ```python
        from fraiseql.caching.schema_analyzer import setup_auto_cascade_rules

        @app.on_event("startup")
        async def setup_caching():
            await setup_auto_cascade_rules(cache, app.schema, verbose=True)
        ```
    """
    analyzer = SchemaAnalyzer(schema)

    # Print analysis report if verbose
    if verbose:
        analyzer.print_analysis_report()

    # Get CASCADE rules
    rules = analyzer.analyze_relationships()

    # Register each rule
    registered_count = 0
    for rule in rules:
        try:
            registered = await cache.register_cascade_rule(
                source_domain=rule.source_domain,
                target_domain=rule.target_domain,
                rule_type=rule.rule_type,
            )
            # False: skipped (no pg_fraiseql_cache). A backend returning None counts.
            if registered is not False:
                registered_count += 1
        except Exception as e:
            logger.error(
                "Failed to register CASCADE rule %s -> %s: %s",
                rule.source_domain,
                rule.target_domain,
                e,
            )

    logger.info("✓ Registered %d CASCADE rules for automatic cache invalidation", registered_count)

    return registered_count

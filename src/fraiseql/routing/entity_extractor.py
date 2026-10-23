"""GraphQL query analysis for entity extraction."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from graphql import (
    DocumentNode,
    FieldNode,
    GraphQLError,
    GraphQLSchema,
    OperationDefinitionNode,
    SelectionSetNode,
    parse,
    validate,
)

from fraiseql.utils.casing import to_snake_case

logger = logging.getLogger(__name__)


@dataclass
class EntityAnalysisResult:
    """Result of entity analysis for a GraphQL query."""

    entities: list[str]
    """List of entity names found in the query."""

    root_entities: list[str]
    """List of root-level entity names."""

    nested_entities: list[str]
    """List of nested entity names."""

    operation_type: str
    """The GraphQL operation type (query, mutation, subscription)."""

    complexity_score: int = 0
    """Complexity score of the query."""

    max_depth: int = 0
    """Maximum nesting depth of the query."""

    analysis_errors: list[str] = None
    """Any errors encountered during analysis."""

    def __post_init__(self) -> None:
        """Initialize analysis_errors if not provided."""
        if self.analysis_errors is None:
            self.analysis_errors = []


class EntityExtractor:
    """Extracts entity information from GraphQL queries."""

    def __init__(self, schema: GraphQLSchema) -> None:
        """Initialize the entity extractor."""
        self.schema = schema
        self._type_to_entity_cache: dict[str, str] = {}
        self._build_type_mapping()

    def _build_type_mapping(self) -> None:
        """Build a mapping from GraphQL types to entity names."""
        for type_name in self.schema.type_map:
            if not type_name.startswith("__"):
                entity_name = self._type_to_entity_name(type_name)
                self._type_to_entity_cache[type_name] = entity_name

    def _type_to_entity_name(self, type_name: str) -> str:
        """Convert GraphQL type name to entity name."""
        snake_name = to_snake_case(type_name)

        suffixes_to_remove = ["_type", "_input", "_payload", "_result", "_response", "_interface"]
        for suffix in suffixes_to_remove:
            if snake_name.endswith(suffix):
                snake_name = snake_name[: -len(suffix)]
                break

        if snake_name.endswith("ies") and len(snake_name) > 3:
            snake_name = snake_name[:-3] + "y"
        elif snake_name.endswith("ves") and len(snake_name) > 3:
            snake_name = snake_name[:-3] + "f"
        elif snake_name.endswith("ses") and len(snake_name) > 3:
            snake_name = snake_name[:-2]
        elif snake_name.endswith("s") and len(snake_name) > 1:
            singular = snake_name[:-1]
            if not singular.endswith(("s", "ss")) and singular not in ("gla", "ga", "cha"):
                snake_name = singular

        return snake_name

    def extract_entities(self, query: str) -> EntityAnalysisResult:
        """Extract entities from a GraphQL query."""
        try:
            document = parse(query)
            validation_errors = validate(self.schema, document)
            if validation_errors:
                error_messages = [str(error) for error in validation_errors]
                return EntityAnalysisResult(
                    entities=[],
                    root_entities=[],
                    nested_entities=[],
                    operation_type="unknown",
                    analysis_errors=error_messages,
                )

            operation = self._get_operation(document)
            if not operation:
                return EntityAnalysisResult(
                    entities=[],
                    root_entities=[],
                    nested_entities=[],
                    operation_type="unknown",
                    analysis_errors=["No operation found in query"],
                )

            entities_info = self._extract_entities_from_operation(operation)
            complexity = self._calculate_complexity(operation.selection_set)
            depth = self._calculate_depth(operation.selection_set)

            return EntityAnalysisResult(
                entities=entities_info["all_entities"],
                root_entities=entities_info["root_entities"],
                nested_entities=entities_info["nested_entities"],
                operation_type=operation.operation.value,
                complexity_score=complexity,
                max_depth=depth,
            )

        except GraphQLError as e:
            # The client's query doesn't parse: a result, not a failure
            return EntityAnalysisResult(
                entities=[],
                root_entities=[],
                nested_entities=[],
                operation_type="unknown",
                analysis_errors=[f"Parsing error: {e!s}"],
            )
        except Exception as e:
            # Routing falls back to NORMAL; say why instead of finding no entities
            logger.warning("Entity analysis failed, no entities extracted: %s", e, exc_info=True)
            return EntityAnalysisResult(
                entities=[],
                root_entities=[],
                nested_entities=[],
                operation_type="unknown",
                analysis_errors=[f"Analysis error: {e!s}"],
            )

    def _get_operation(self, document: DocumentNode) -> Optional[OperationDefinitionNode]:
        """Extract the operation definition from a document."""
        for definition in document.definitions:
            if isinstance(definition, OperationDefinitionNode):
                return definition
        return None

    def _extract_entities_from_operation(
        self, operation: OperationDefinitionNode
    ) -> dict[str, list[str]]:
        """Extract entities from an operation definition."""
        root_entities = []
        all_entities = set()

        for selection in operation.selection_set.selections:
            if isinstance(selection, FieldNode):
                field_name = selection.name.value
                entity_name = self._field_to_entity_name(field_name)
                if entity_name:
                    root_entities.append(entity_name)
                    all_entities.add(entity_name)

                if selection.selection_set:
                    nested = self._extract_nested_entities(selection.selection_set)
                    all_entities.update(nested)

        nested_entities = [entity for entity in all_entities if entity not in root_entities]

        return {
            "all_entities": list(all_entities),
            "root_entities": root_entities,
            "nested_entities": nested_entities,
        }

    def _extract_nested_entities(self, selection_set: SelectionSetNode) -> list[str]:
        """Extract entities from nested selections."""
        entities = []

        for selection in selection_set.selections:
            if isinstance(selection, FieldNode):
                field_name = selection.name.value

                if selection.selection_set:
                    entity_name = self._type_to_entity_name(field_name)
                    if entity_name:
                        entities.append(entity_name)

                    nested = self._extract_nested_entities(selection.selection_set)
                    entities.extend(nested)

        return entities

    def _field_to_entity_name(self, field_name: str) -> Optional[str]:
        """Convert a GraphQL field name to an entity name."""
        query_type = self.schema.type_map.get("Query")
        if not query_type:
            return None

        if field_name not in query_type.fields:
            return None

        field_def = query_type.fields[field_name]
        return_type = field_def.type

        while hasattr(return_type, "of_type"):
            return_type = return_type.of_type

        type_name = return_type.name
        if type_name in self._type_to_entity_cache:
            return self._type_to_entity_cache[type_name]

        return self._type_to_entity_name(field_name)

    def _calculate_complexity(self, selection_set: SelectionSetNode) -> int:
        """Calculate query complexity score."""
        score = 0

        for selection in selection_set.selections:
            if isinstance(selection, FieldNode):
                score += 1

                if selection.selection_set:
                    score += self._calculate_complexity(selection.selection_set) * 2

                # graphql-core 3.3 leaves an absent argument list as None
                score += len(selection.arguments or ()) * 2

        return score

    def _calculate_depth(self, selection_set: SelectionSetNode, current_depth: int = 0) -> int:
        """Calculate maximum query depth."""
        if not selection_set:
            return current_depth

        max_depth = current_depth

        for selection in selection_set.selections:
            if isinstance(selection, FieldNode) and selection.selection_set:
                depth = self._calculate_depth(selection.selection_set, current_depth + 1)
                max_depth = max(max_depth, depth)

        return max_depth

"""Query router for entity-aware execution mode determination."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from fraiseql.execution.mode_selector import ExecutionMode

if TYPE_CHECKING:
    from fraiseql.routing.config import EntityRoutingConfig
    from fraiseql.routing.entity_extractor import EntityExtractor

logger = logging.getLogger(__name__)


class QueryRouter:
    """Routes queries to optimal execution mode based on entity classification."""

    def __init__(self, config: EntityRoutingConfig, entity_extractor: EntityExtractor) -> None:
        """Initialize the query router."""
        self.config = config
        self.entity_extractor = entity_extractor

    def determine_execution_mode(self, query: str) -> Optional[ExecutionMode]:
        """Determine the optimal execution mode for a query."""
        if not self.config.auto_routing_enabled:
            return None

        try:
            entities = self.extract_query_entities(query)

            if not entities:
                return ExecutionMode.NORMAL

            classification = self.classify_entities(entities)
            return self._determine_mode_from_classification(classification)

        except Exception as e:
            logger.warning("Entity routing failed, using NORMAL: %s", e, exc_info=True)
            return ExecutionMode.NORMAL

    def _determine_mode_from_classification(
        self, classification: dict[str, list[str]]
    ) -> ExecutionMode:
        """Determine execution mode from entity classification."""
        has_turbo_entities = bool(classification["turbo_entities"])
        has_normal_entities = bool(classification["normal_entities"])
        has_unknown_entities = bool(classification["unknown_entities"])

        if has_turbo_entities and not has_normal_entities and not has_unknown_entities:
            return ExecutionMode.TURBO
        if has_normal_entities and not has_turbo_entities:
            return ExecutionMode.NORMAL
        return self._handle_mixed_entities(classification)

    def extract_query_entities(self, query: str) -> list[str]:
        """Extract entities from a GraphQL query."""
        analysis = self.entity_extractor.extract_entities(query)
        return analysis.entities

    def classify_entities(self, entities: list[str]) -> dict[str, list[str]]:
        """Classify entities into turbo, normal, and unknown categories."""
        classification = {
            "turbo_entities": [],
            "normal_entities": [],
            "unknown_entities": [],
        }

        for entity in entities:
            if self.config.is_turbo_entity(entity):
                classification["turbo_entities"].append(entity)
            elif self.config.is_normal_entity(entity):
                classification["normal_entities"].append(entity)
            else:
                classification["unknown_entities"].append(entity)

        return classification

    def _handle_mixed_entities(self, classification: dict[str, list[str]]) -> ExecutionMode:
        """Handle queries with mixed entity types."""
        strategy = self.config.mixed_query_strategy

        if strategy == "turbo":
            return ExecutionMode.TURBO
        if strategy == "normal":
            return ExecutionMode.NORMAL
        if strategy == "split":
            return ExecutionMode.NORMAL
        return ExecutionMode.NORMAL

    def get_routing_metrics(self) -> dict[str, Any]:
        """Get metrics about the routing configuration."""
        return {
            "auto_routing_enabled": self.config.auto_routing_enabled,
            "turbo_entities_count": len(self.config.turbo_entities),
            "normal_entities_count": len(self.config.normal_entities),
            "mixed_query_strategy": self.config.mixed_query_strategy,
            "turbo_entities": self.config.turbo_entities.copy(),
            "normal_entities": self.config.normal_entities.copy(),
        }

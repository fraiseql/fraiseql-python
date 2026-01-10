"""Pytest configuration for benchmark tests."""

import json
from typing import Any

import pytest


@pytest.fixture
def sample_mutation_result() -> dict[str, Any]:
    """Sample mutation result for benchmarking."""
    return {
        "status": "success",
        "message": "Operation completed successfully",
        "entity_id": "test-entity-123",
        "entity_type": "TestEntity",
        "entity": {
            "id": "test-entity-123",
            "name": "Test Entity",
            "description": "A test entity for benchmarking",
            "created_at": "2026-01-10T12:00:00Z",
            "updated_at": "2026-01-10T12:00:00Z",
            "metadata": {
                "tags": ["test", "benchmark"],
                "version": 1,
                "author": "system",
            },
        },
        "updated_fields": ["name", "description"],
        "cascade": None,
        "metadata": None,
        "is_simple_format": False,
    }


@pytest.fixture
def large_mutation_result() -> dict[str, Any]:
    """Large mutation result for stress testing."""
    base_entity = {
        "id": f"entity-{i:04d}",
        "name": f"Entity {i}",
        "description": f"Description for entity {i}",
        "value": i * 100,
        "active": i % 2 == 0,
        "metadata": {
            "index": i,
            "group": i // 100,
            "tags": [f"tag-{j}" for j in range(5)],
        },
    }

    # Create nested structure
    nested_entity = {
        "id": "nested-123",
        "name": "Nested Entity",
        "children": [base_entity.copy() for i in range(10)],
        "metadata": {
            "child_count": 10,
            "depth": 2,
        },
    }

    return {
        "status": "success",
        "message": "Large operation completed",
        "entity_id": "nested-123",
        "entity_type": "NestedEntity",
        "entity": nested_entity,
        "updated_fields": ["children", "metadata"],
        "cascade": None,
        "metadata": None,
        "is_simple_format": False,
    }


@pytest.fixture
def field_selections_simple() -> list[str]:
    """Simple field selection list."""
    return ["id", "name", "status"]


@pytest.fixture
def field_selections_moderate() -> list[str]:
    """Moderate field selection list."""
    return ["id", "name", "description", "created_at", "updated_at", "metadata"]


@pytest.fixture
def field_selections_large() -> list[str]:
    """Large field selection list."""
    return [f"field_{i}" for i in range(100)]


@pytest.fixture
def field_selections_very_large() -> list[str]:
    """Very large field selection list."""
    return [f"field_{i}" for i in range(1000)]


@pytest.fixture
def field_selections_nested() -> dict[str, Any]:
    """Nested field selection structure."""
    return {
        "id": True,
        "entity": {
            "id": True,
            "name": True,
            "metadata": {
                "tags": True,
                "version": True,
            },
        },
        "updated_fields": True,
    }

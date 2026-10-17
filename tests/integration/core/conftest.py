"""Core module test fixtures."""

import pytest

# Import database fixtures
from fraiseql.db import FraiseQLRepository


@pytest.fixture
def db_repo(class_db_pool) -> FraiseQLRepository:
    """FraiseQL repository fixture for core tests."""
    return FraiseQLRepository(class_db_pool)

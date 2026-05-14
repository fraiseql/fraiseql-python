"""Tests for CascadeMetadata type - graphql-cascade spec compliance."""

import pytest

from fraiseql.mutations.types import CascadeMetadata


class TestCascadeMetadataSpecCompliance:
    """Test CascadeMetadata adheres to graphql-cascade specification."""

    def test_required_fields(self):
        """Test all required fields per spec."""
        metadata = CascadeMetadata(
            timestamp="2025-12-15T10:00:00Z",
            affected_count=5,
            depth=2,
        )
        assert metadata.timestamp == "2025-12-15T10:00:00Z"
        assert metadata.affected_count == 5
        assert metadata.depth == 2
        assert metadata.transaction_id is None

    def test_depth_is_required(self):
        """Depth is required per spec - must be provided."""
        with pytest.raises(TypeError):
            CascadeMetadata(
                timestamp="2025-12-15T10:00:00Z",
                affected_count=3,
                # depth missing - should raise
            )

    def test_transaction_id_optional(self):
        """Transaction ID is optional per spec."""
        # Without transaction_id
        metadata1 = CascadeMetadata(
            timestamp="2025-12-15T10:00:00Z",
            affected_count=1,
            depth=0,
        )
        assert metadata1.transaction_id is None

        # With transaction_id
        metadata2 = CascadeMetadata(
            timestamp="2025-12-15T10:00:00Z",
            affected_count=1,
            depth=0,
            transaction_id="12345678",
        )
        assert metadata2.transaction_id == "12345678"

    def test_all_fields_populated(self):
        """Test all spec fields together."""
        metadata = CascadeMetadata(
            timestamp="2025-12-15T14:30:00.123Z",
            affected_count=42,
            depth=5,
            transaction_id="987654321",
        )
        assert metadata.timestamp == "2025-12-15T14:30:00.123Z"
        assert metadata.affected_count == 42
        assert metadata.depth == 5
        assert metadata.transaction_id == "987654321"

    def test_depth_minimum_zero(self):
        """Depth minimum is 0 per spec."""
        metadata = CascadeMetadata(
            timestamp="2025-12-15T10:00:00Z",
            affected_count=0,
            depth=0,
        )
        assert metadata.depth == 0

    def test_affected_count_minimum_zero(self):
        """Affected count minimum is 0 per spec."""
        metadata = CascadeMetadata(
            timestamp="2025-12-15T10:00:00Z",
            affected_count=0,
            depth=0,
        )
        assert metadata.affected_count == 0

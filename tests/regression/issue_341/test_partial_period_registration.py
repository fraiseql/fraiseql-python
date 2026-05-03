"""Tests for Issue #341 Phase 01: Registration metadata for partial-period awareness.

Verifies that:
- register_type_for_view stores fine_grain_view, time_grain_column, time_grain_trunc.
- Omitting the new keys does not affect existing registrations.
- An invalid time_grain_trunc raises ValueError at registration time.
"""

import pytest

from fraiseql.db import _table_metadata, register_type_for_view


class EventDataPoint:
    pass


class TestRegisterFineGrainMetadata:
    def setup_method(self) -> None:
        self._original = _table_metadata.copy()

    def teardown_method(self) -> None:
        _table_metadata.clear()
        _table_metadata.update(self._original)

    def test_register_with_fine_grain_view_stores_metadata(self) -> None:
        register_type_for_view(
            "v_events_month",
            EventDataPoint,
            table_columns={"date", "data"},
            aggregation={
                "dimensions": "data",
                "measures": {"data.volume": "SUM"},
                "native_dimensions": ["date"],
                "fine_grain_view": "v_events_day",
                "time_grain_column": "date",
                "time_grain_trunc": "month",
            },
        )
        meta = _table_metadata["v_events_month"]["aggregation"]
        assert meta["fine_grain_view"] == "v_events_day"
        assert meta["time_grain_column"] == "date"
        assert meta["time_grain_trunc"] == "month"

    def test_register_without_fine_grain_keys_is_unchanged(self) -> None:
        """Existing registrations must not be affected."""
        register_type_for_view(
            "v_events_month_legacy",
            EventDataPoint,
            table_columns={"date", "data"},
            aggregation={
                "dimensions": "data",
                "measures": {"data.volume": "SUM"},
            },
        )
        meta = _table_metadata["v_events_month_legacy"]["aggregation"]
        assert "fine_grain_view" not in meta
        assert "time_grain_column" not in meta
        assert "time_grain_trunc" not in meta

    def test_invalid_time_grain_trunc_raises(self) -> None:
        with pytest.raises(ValueError, match="time_grain_trunc"):
            register_type_for_view(
                "v_bad",
                EventDataPoint,
                table_columns={"date", "data"},
                aggregation={
                    "fine_grain_view": "v_events_day",
                    "time_grain_column": "date",
                    "time_grain_trunc": "fortnight",
                },
            )

    def test_all_valid_truncs_accepted(self) -> None:
        """All five valid granularities must be accepted."""
        for trunc in ("day", "week", "month", "quarter", "year"):
            register_type_for_view(
                f"v_test_{trunc}",
                EventDataPoint,
                table_columns={"date", "data"},
                aggregation={
                    "fine_grain_view": "v_events_hour",
                    "time_grain_column": "date",
                    "time_grain_trunc": trunc,
                },
            )
            assert _table_metadata[f"v_test_{trunc}"]["aggregation"]["time_grain_trunc"] == trunc

    def test_fine_grain_view_not_yet_registered_is_allowed(self) -> None:
        """fine_grain_view referencing a non-registered view is allowed at registration."""
        register_type_for_view(
            "v_coarse",
            EventDataPoint,
            table_columns={"date", "data"},
            aggregation={
                "fine_grain_view": "v_not_yet_registered",
                "time_grain_column": "date",
                "time_grain_trunc": "week",
            },
        )
        assert _table_metadata["v_coarse"]["aggregation"]["fine_grain_view"] == "v_not_yet_registered"

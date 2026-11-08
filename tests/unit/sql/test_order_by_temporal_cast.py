"""ORDER BY on a datetime / date JSONB field casts the ISO string it holds."""

from dataclasses import dataclass
from datetime import date, datetime

import pytest

from fraiseql.sql.order_by_generator import OrderBy, OrderBySet, OrderDirection


@dataclass
class _Author:
    name: str
    joined_at: datetime | None


@dataclass
class _Note:
    title: str
    count: int
    created_at: datetime
    due_on: date | None
    author: _Author
    embedding: list[float]


def _sql(order_set: OrderBySet, **kwargs) -> str:
    return order_set.to_sql("data", **kwargs).as_string(None)


@pytest.mark.unit
class TestOrderByTemporalCast:
    @pytest.mark.parametrize("direction", [OrderDirection.ASC, OrderDirection.DESC])
    def test_datetime_field_casts_to_timestamptz(self, direction: OrderDirection) -> None:
        order_set = OrderBySet([OrderBy("created_at", direction)]).with_temporal_casts(_Note)
        expected = f"ORDER BY (data ->> 'created_at')::timestamptz {direction.value.upper()}"
        assert _sql(order_set) == expected

    def test_date_field_casts_to_date(self) -> None:
        order_set = OrderBySet([OrderBy("due_on")]).with_temporal_casts(_Note)
        assert _sql(order_set) == "ORDER BY (data ->> 'due_on')::date ASC"

    def test_nested_optional_datetime_casts(self) -> None:
        order_set = OrderBySet([OrderBy("author.joined_at")]).with_temporal_casts(_Note)
        expected = "ORDER BY (data -> 'author' ->> 'joined_at')::timestamptz ASC"
        assert _sql(order_set) == expected

    @pytest.mark.parametrize("field", ["title", "count", "author.name", "missing"])
    def test_other_fields_keep_jsonb_sort(self, field: str) -> None:
        order_set = OrderBySet([OrderBy(field)])
        assert order_set.with_temporal_casts(_Note) is order_set

    def test_no_source_type_keeps_jsonb_sort(self) -> None:
        order_set = OrderBySet([OrderBy("created_at")])
        assert _sql(order_set.with_temporal_casts(None)) == "ORDER BY data -> 'created_at' ASC"

    def test_explicit_collation_keeps_text_sort(self) -> None:
        order_set = OrderBySet([OrderBy("created_at", collation="C")]).with_temporal_casts(_Note)
        assert _sql(order_set) == "ORDER BY (data ->> 'created_at') COLLATE \"C\" ASC"

    def test_flat_column_ignores_cast(self) -> None:
        order_set = OrderBySet([OrderBy("created_at")]).with_temporal_casts(_Note)
        assert _sql(order_set, native_columns={"created_at"}) == 'ORDER BY "t"."created_at" ASC'

    def test_vector_distance_untouched(self) -> None:
        order_set = OrderBySet([OrderBy("embedding.cosine_distance", value=[0.1, 0.2])])
        assert order_set.with_temporal_casts(_Note) is order_set

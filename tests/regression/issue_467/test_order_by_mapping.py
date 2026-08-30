"""Issue #467, third leg: ORDER BY on a mapped dimension path.

``native_dimensions`` (a set of column names) reached the ORDER BY generator;
the mapping (a path → column dict) did not fit that shape and was never passed.
Sorting on a mapped path therefore re-ran the whole ``jsonb_build_object`` per
row — on the aggregated path, on a key already computed natively in the SELECT
list.

The load-bearing assertion is not "it says model_category". It is that the ORDER
BY expression is **byte-identical** to the GROUP BY expression for the same path:
PostgreSQL requires a sort key to be grouped or functionally determined by the
grouping, so two different expressions for one logical field is a query that
fails to plan, not merely a slow one.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fraiseql.db import FraiseQLRepository, _table_metadata, _type_registry, register_type_for_view

COLUMNS = {"id", "data", "date", "model_category"}
MAPPING = {"dimensions.item.model.category": "model_category"}


class _Stats:
    """Stand-in for the reporter's @fraise_type analytics class."""


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    for view in [v for v in _table_metadata if v.startswith("v_467")]:
        del _table_metadata[view]
    for view in [v for v in _type_registry if v.startswith("v_467")]:
        del _type_registry[view]


def _register(view_name: str, **agg_extra: Any) -> None:
    register_type_for_view(
        view_name,
        _Stats,
        table_columns=COLUMNS,
        has_jsonb_data=True,
        jsonb_column="data",
        aggregation={
            "dimensions": "dimensions",
            "measures": {"measures.cost": "SUM"},
            "native_dimensions": ["date"],
            "native_dimension_mapping": MAPPING,
            **agg_extra,
        },
    )


def _make_pool() -> Any:
    mock_pool = MagicMock()
    ctx = mock_pool.connection.return_value
    ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
    ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_pool


async def _rendered_sql(view_name: str, **find_kwargs: Any) -> str:
    repo = FraiseQLRepository(_make_pool())
    info = MagicMock()
    info.schema = None

    with (
        patch(
            "fraiseql.core.ast_parser.extract_field_paths_from_info",
            return_value=[
                MagicMock(path=["date"]),
                MagicMock(path=["dimensions", "item", "model", "category"]),
                MagicMock(path=["measures", "cost"]),
            ],
        ),
        patch(
            "fraiseql.db.execute_via_rust_pipeline",
            new_callable=AsyncMock,
            return_value=b'{"data":{"x":[]}}',
        ) as mock_execute,
    ):
        await repo.find(view_name, info=info, **find_kwargs)

    return mock_execute.call_args[0][1].as_string(None)


def _clause(rendered: str, keyword: str) -> str:
    """Return the text of one SQL clause, up to the next clause keyword."""
    start = rendered.index(keyword) + len(keyword)
    tail = rendered[start:]
    for following in (" GROUP BY ", " ORDER BY ", " LIMIT ", " OFFSET "):
        if following in tail:
            tail = tail[: tail.index(following)]
    return tail.strip()


class TestOrderByOnAMappedPath:
    @pytest.mark.asyncio
    async def test_mapped_path_sorts_on_the_column(self) -> None:
        _register("v_467_order")

        rendered = await _rendered_sql(
            "v_467_order", order_by={"dimensions": {"item": {"model": {"category": "desc"}}}}
        )

        assert 'ORDER BY "t"."model_category" DESC' in rendered

    @pytest.mark.asyncio
    async def test_sort_key_is_identical_to_the_group_by_key(self) -> None:
        """The whole point: one logical field, one expression."""
        _register("v_467_order_match")

        rendered = await _rendered_sql(
            "v_467_order_match",
            order_by={"dimensions": {"item": {"model": {"category": "asc"}}}},
        )

        group_by = _clause(rendered, " GROUP BY ")
        order_by = _clause(rendered, " ORDER BY ")

        assert order_by == 'ORDER BY "t"."model_category" ASC'.removeprefix("ORDER BY ")
        assert order_by.removesuffix(" ASC") in group_by

    @pytest.mark.asyncio
    async def test_native_dimension_ordering_is_unaffected(self) -> None:
        _register("v_467_order_native")

        rendered = await _rendered_sql("v_467_order_native", order_by={"date": "desc"})

        assert 'ORDER BY "t"."date" DESC' in rendered

    @pytest.mark.asyncio
    async def test_unmapped_path_still_sorts_on_jsonb(self) -> None:
        """Byte-identical to today for anything the mapping does not name."""
        _register("v_467_order_unmapped")

        rendered = await _rendered_sql(
            "v_467_order_unmapped",
            order_by={"dimensions": {"item": {"model": {"name": "asc"}}}},
        )

        assert "-> 'dimensions' -> 'item' -> 'model' -> 'name' ASC" in rendered

    @pytest.mark.asyncio
    async def test_mixed_ordering_keeps_each_leg_in_its_own_shape(self) -> None:
        _register("v_467_order_mixed")

        rendered = await _rendered_sql(
            "v_467_order_mixed",
            order_by={
                "date": "desc",
                "dimensions": {"item": {"model": {"category": "asc"}}},
            },
        )

        assert 'ORDER BY "t"."date" DESC, "t"."model_category" ASC' in rendered

    @pytest.mark.asyncio
    async def test_top_level_column_mapping_reaches_order_by(self) -> None:
        """``column_mapping=`` is the peer declaration; it must reach here too."""
        register_type_for_view(
            "v_467_order_peer",
            _Stats,
            table_columns=COLUMNS,
            has_jsonb_data=True,
            jsonb_column="data",
            column_mapping=MAPPING,
            aggregation={
                "dimensions": "dimensions",
                "measures": {"measures.cost": "SUM"},
                "native_dimensions": ["date"],
            },
        )

        rendered = await _rendered_sql(
            "v_467_order_peer",
            order_by={"dimensions": {"item": {"model": {"category": "desc"}}}},
        )

        assert 'ORDER BY "t"."model_category" DESC' in rendered


class TestNonAggregatedOrdering:
    """No group_by at all — the mapping is unconditional, like fk_relationships."""

    @pytest.mark.asyncio
    async def test_mapping_applies_without_aggregation(self) -> None:
        register_type_for_view(
            "v_467_order_rows",
            _Stats,
            table_columns=COLUMNS,
            has_jsonb_data=True,
            jsonb_column="data",
            column_mapping=MAPPING,
        )

        repo = FraiseQLRepository(_make_pool())
        info = MagicMock()
        info.schema = None

        with (
            patch(
                "fraiseql.core.ast_parser.extract_field_paths_from_info",
                return_value=[MagicMock(path=["id"])],
            ),
            patch(
                "fraiseql.db.execute_via_rust_pipeline",
                new_callable=AsyncMock,
                return_value=b'{"data":{"x":[]}}',
            ) as mock_execute,
        ):
            await repo.find(
                "v_467_order_rows",
                info=info,
                order_by={"dimensions": {"item": {"model": {"category": "asc"}}}},
            )

        rendered = mock_execute.call_args[0][1].as_string(None)
        assert 'ORDER BY "t"."model_category" ASC' in rendered

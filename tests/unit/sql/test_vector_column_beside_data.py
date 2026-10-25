"""A vector distance reads the view's column on a view with a JSONB ``data`` column.

A vector inside the JSONB document can't be compared by distance, so such a
view exposes it as a column beside ``data``. ``order_by`` rendered
``data."embedding"`` (a column of a table named ``data``), and ``where`` read
``data ->> 'embedding'`` whenever the view's registered columns didn't list the
vector (``@fraiseql.type`` registers none).
"""

from fraiseql.sql.order_by_generator import OrderBy, OrderDirection
from fraiseql.where_normalization import normalize_dict_where


def _order_sql(table_ref: str, **kwargs) -> str:
    instr = OrderBy("embedding.cosine_distance", OrderDirection.ASC, value=[1.0, 0.0])
    return instr.to_sql(table_ref, **kwargs).as_string(None)


class TestOrderBy:
    def test_view_with_data_column_sorts_on_the_column(self) -> None:
        assert _order_sql("data") == "(\"embedding\") <=> '[1.0,0.0]'::vector ASC"

    def test_flat_view_keeps_the_alias(self) -> None:
        assert _order_sql("t") == "(t.\"embedding\") <=> '[1.0,0.0]'::vector ASC"

    def test_mapped_vector_field_sorts_on_its_column(self) -> None:
        sql = _order_sql("data", column_mapping={"embedding": "emb_vec"})
        assert sql == "(\"emb_vec\") <=> '[1.0,0.0]'::vector ASC"


class TestWhere:
    _FILTER = {"embedding": {"cosine_distance": {"vector": [1.0, 0.0], "threshold": 0.5}}}

    def test_columns_not_listing_the_vector_still_use_the_column(self) -> None:
        clause = normalize_dict_where(self._FILTER, "v_unregistered_vec", {"id", "data"})
        [condition] = clause.conditions
        assert (condition.lookup_strategy, condition.target_column) == ("sql_column", "embedding")

    def test_other_operators_on_the_same_view_stay_in_jsonb(self) -> None:
        clause = normalize_dict_where({"name": {"eq": "x"}}, "v_unregistered_vec", {"id", "data"})
        [condition] = clause.conditions
        assert condition.lookup_strategy == "jsonb_path"

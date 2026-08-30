"""Issue #476: an explicit ORDER BY collation must survive every resolution path.

``OrderBy.to_sql`` has three ways to render a sort key, and a collation was
honoured by none of them in a way that reaches PostgreSQL:

* the ``native_columns`` flat-column branch returned before the COLLATE block;
* the ``column_mapping`` flat-column branch mirrors it exactly (#467), so it
  dropped the collation the same way;
* the JSONB branch *emitted* ``COLLATE`` but bound it to the key literal --
  ``data -> ('name' COLLATE "x")`` -- which is a no-op, because the sort still
  compares ``jsonb``.

The last one is why these assertions check the shape of the expression and not
merely that the substring ``COLLATE`` appears somewhere. A text assertion
cannot tell an applied collation from one attached to the wrong operand; see
``tests/integration/database/sql/test_order_by_collation_execution.py`` for the
half of this that only a live database can answer.
"""

from types import SimpleNamespace

import pytest

from fraiseql.sql.graphql_order_by_generator import _convert_order_by_input_to_sql
from fraiseql.sql.order_by_generator import OrderBy, OrderBySet, OrderDirection

COLLATION = "fr_FR.utf8"


@pytest.mark.unit
class TestFlatColumnCollation:
    """The two flat-column routes: ``native_columns`` and ``column_mapping``."""

    def test_native_column_keeps_collation(self) -> None:
        ob = OrderBy(field="name", collation=COLLATION)
        assert (
            ob.to_sql(native_columns={"name"}).as_string(None)
            == '"t"."name" COLLATE "fr_FR.utf8" ASC'
        )

    def test_column_mapping_keeps_collation(self) -> None:
        ob = OrderBy(field="profile.last_name", direction=OrderDirection.DESC, collation=COLLATION)
        result = ob.to_sql(column_mapping={"profile.last_name": "last_name"}).as_string(None)
        assert result == '"t"."last_name" COLLATE "fr_FR.utf8" DESC'

    def test_both_flat_routes_agree(self) -> None:
        """The two branches deliberately match, so they must not diverge here."""
        ob = OrderBy(field="name", collation=COLLATION)
        assert ob.to_sql(native_columns={"name"}).as_string(None) == ob.to_sql(
            column_mapping={"name": "name"}
        ).as_string(None)

    def test_flat_column_without_collation_unchanged(self) -> None:
        """Regression: the no-collation flat column keeps its exact previous SQL."""
        ob = OrderBy(field="name", direction=OrderDirection.DESC)
        assert ob.to_sql(native_columns={"name"}).as_string(None) == '"t"."name" DESC'
        assert "COLLATE" not in ob.to_sql(column_mapping={"name": "name"}).as_string(None)

    def test_collation_name_is_quoted_as_an_identifier(self) -> None:
        """COLLATE takes an identifier, not a string literal -- and it is injectable."""
        ob = OrderBy(field="name", collation='x" ; DROP TABLE t --')
        result = ob.to_sql(native_columns={"name"}).as_string(None)
        assert 'COLLATE "x"" ; DROP TABLE t --"' in result

    def test_order_by_set_collates_flat_columns(self) -> None:
        obs = OrderBySet(
            [
                OrderBy(field="country", collation="C"),
                OrderBy(field="name", collation=COLLATION),
                OrderBy(field="age"),
            ]
        )
        result = obs.to_sql(native_columns={"country", "name", "age"}).as_string(None)
        assert '"t"."country" COLLATE "C" ASC' in result
        assert '"t"."name" COLLATE "fr_FR.utf8" ASC' in result
        assert '"t"."age" ASC' in result
        assert result.count("COLLATE") == 2


@pytest.mark.unit
class TestJsonbCollation:
    """A collation is a *text* ordering, so the JSONB branch must extract text."""

    def test_jsonb_collation_binds_to_the_extracted_value(self) -> None:
        """``->>`` and parentheses, so the collation applies to the value.

        ``t -> 'name' COLLATE "x"`` parses as ``t -> ('name' COLLATE "x")``:
        PostgreSQL accepts it, the result is still ``jsonb``, and the collation
        is silently ignored.
        """
        ob = OrderBy(field="name", collation=COLLATION)
        assert ob.to_sql().as_string(None) == "(t ->> 'name') COLLATE \"fr_FR.utf8\" ASC"

    def test_nested_jsonb_collation_binds_to_the_leaf(self) -> None:
        ob = OrderBy(field="profile.last_name", direction=OrderDirection.DESC, collation=COLLATION)
        assert (
            ob.to_sql().as_string(None)
            == "(t -> 'profile' ->> 'last_name') COLLATE \"fr_FR.utf8\" DESC"
        )

    def test_jsonb_without_collation_keeps_typed_extraction(self) -> None:
        """Regression: no collation means ``->``, which preserves numeric ordering."""
        assert OrderBy(field="amount").to_sql().as_string(None) == "t -> 'amount' ASC"
        assert (
            OrderBy(field="profile.age", direction=OrderDirection.DESC).to_sql().as_string(None)
            == "t -> 'profile' -> 'age' DESC"
        )

    def test_vector_distance_still_ignores_collation(self) -> None:
        ob = OrderBy(field="embedding.cosine_distance", value=[0.1, 0.2, 0.3], collation=COLLATION)
        result = ob.to_sql().as_string(None)
        assert "COLLATE" not in result
        assert "<=>" in result


@pytest.mark.unit
class TestGlobalDefaultCollationStaysInert:
    """``default_string_collation`` must not reach the SQL until it knows types.

    The setting is documented as applying to "all text fields", but nothing in
    the order_by pipeline tracks which fields are text -- it is applied to every
    field. That was harmless only while a collation was inert. Now that one
    reaches the sort, honouring a blanket default would silently make a numeric
    JSONB sort lexicographic (1, 10, 2) and would make a numeric flat column
    fail outright with "collations are not supported by type integer".

    So a collation is honoured when a caller asked for it on a field, and a
    global default is dropped -- which is exactly its effect today, making this
    a no-op for every existing deployment.
    """

    @staticmethod
    def _config() -> SimpleNamespace:
        return SimpleNamespace(default_string_collation="fr_FR.utf8")

    def test_list_of_dicts_ignores_the_global_default(self) -> None:
        order_set = _convert_order_by_input_to_sql([{"amount": "asc"}], config=self._config())
        assert order_set is not None
        assert order_set.to_sql().as_string(None) == "ORDER BY t -> 'amount' ASC"

    def test_global_default_does_not_collate_a_flat_column(self) -> None:
        """A numeric native column would raise, not merely sort oddly."""
        order_set = _convert_order_by_input_to_sql([{"amount": "asc"}], config=self._config())
        assert order_set is not None
        result = order_set.to_sql(native_columns={"amount"}).as_string(None)
        assert result == 'ORDER BY "t"."amount" ASC'
        assert "COLLATE" not in result

    def test_order_by_item_without_a_collation_attribute_ignores_the_default(self) -> None:
        item = SimpleNamespace(field="name", direction="asc")
        order_set = _convert_order_by_input_to_sql([item], config=self._config())
        assert order_set is not None
        assert "COLLATE" not in order_set.to_sql().as_string(None)

    def test_an_explicit_field_collation_is_still_honoured(self) -> None:
        """The point of #476: a deliberate per-field collation reaches the sort."""
        item = SimpleNamespace(field="name", direction="asc", collation="fr_FR.utf8")
        order_set = _convert_order_by_input_to_sql([item], config=self._config())
        assert order_set is not None
        assert (
            order_set.to_sql().as_string(None)
            == 'ORDER BY (t ->> \'name\') COLLATE "fr_FR.utf8" ASC'
        )

    def test_explicit_none_still_beats_the_default(self) -> None:
        item = SimpleNamespace(field="name", direction="asc", collation=None)
        order_set = _convert_order_by_input_to_sql([item], config=self._config())
        assert order_set is not None
        assert "COLLATE" not in order_set.to_sql().as_string(None)

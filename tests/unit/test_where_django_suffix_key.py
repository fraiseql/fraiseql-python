"""A Django-style ``"age__gte"`` where key raises instead of matching nothing.

FraiseQL's dict ``where`` puts the operator in a nested dict,
``{"age": {"gte": 18}}``. ``{"age__gte": 18}`` was read as an equality filter on
a field named ``age__gte``, which no row has, so the query returned nothing
without an error.
"""

import pytest

from fraiseql.where_normalization import normalize_dict_where


class TestDjangoSuffixKey:
    @pytest.mark.parametrize(
        ("key", "value", "hint"),
        [
            ("age__gte", 18, '{"age": {"gte": ...}}'),
            ("id__in", [1, 2], '{"id": {"in": ...}}'),
            ("name__icontains", "jo", '{"name": {"icontains": ...}}'),
            ("updated_at__gt", "2024-01-01", '{"updated_at": {"gt": ...}}'),
        ],
    )
    def test_suffix_key_raises_and_names_the_supported_form(
        self, key: str, value: object, hint: str
    ) -> None:
        with pytest.raises(ValueError, match=key) as exc:
            normalize_dict_where({key: value}, "v_unregistered_suffix", {"id", "data"})
        assert hint in str(exc.value)

    def test_suffix_key_inside_or_raises(self) -> None:
        with pytest.raises(ValueError, match="age__gte"):
            normalize_dict_where(
                {"OR": [{"age__gte": 18}, {"name": "x"}]}, "v_unregistered_suffix", {"id", "data"}
            )

    def test_real_column_with_double_underscore_is_a_field(self) -> None:
        """A view column really named ``score__lt`` is still filtered on."""
        clause = normalize_dict_where({"score__lt": 3}, "v_unregistered_suffix", {"score__lt"})
        [condition] = clause.conditions
        assert condition.field_path == ["score__lt"]
        assert condition.operator == "eq"

    def test_double_underscore_not_ending_in_an_operator_is_a_field(self) -> None:
        clause = normalize_dict_where(
            {"legacy__code": "a"}, "v_unregistered_suffix", {"id", "data"}
        )
        [condition] = clause.conditions
        assert condition.field_path == ["legacy__code"]

    def test_declared_field_with_double_underscore_is_a_field(self) -> None:
        """A field of the view's registered type is a field whatever its name."""
        import fraiseql
        from fraiseql.db import register_type_for_view

        @fraiseql.type(sql_source="v_dunder_field")
        class DunderField:
            id: int
            rank__lt: int

        register_type_for_view(
            "v_dunder_field", DunderField, table_columns={"id", "data"}, has_jsonb_data=True
        )
        clause = normalize_dict_where({"rank__lt": 3}, "v_dunder_field", {"id", "data"})
        [condition] = clause.conditions
        assert condition.field_path == ["rank__lt"]

    def test_the_supported_form_still_works(self) -> None:
        clause = normalize_dict_where({"age": {"gte": 18}}, "v_unregistered_suffix", {"id", "data"})
        [condition] = clause.conditions
        assert (condition.field_path, condition.operator, condition.value) == (["age"], "gte", 18)

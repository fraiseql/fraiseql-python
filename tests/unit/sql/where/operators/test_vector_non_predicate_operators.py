"""Vector operators that cannot be WHERE predicates must be rejected loudly (#510).

Four entries in the vector operator registry render an *expression*, not a
boolean, so they can never serve as a WHERE predicate:

``custom_distance``     a bare call to a user-supplied function
``vector_norm``         ``vector_norm(col, 'l2')`` -- pgvector's is
                        ``vector_norm(vector)``, one argument, so this does not
                        exist at any arity and errors on every execution
``quantized_distance``  a call to ``quantized_<type>_distance``, which FraiseQL
                        does not define
``reconstruct``         a call to ``reconstruct_quantized_vector``, which
                        FraiseQL does not define, returning a vector

``custom_distance`` and ``quantized_distance`` additionally concatenated
caller-supplied strings into the statement through ``psycopg.sql.SQL()``, the
raw-fragment constructor, which performs no escaping.

The rejection must raise :class:`WhereClauseError`. Dropping the four from
``OPERATOR_MAP`` instead is the tempting fix and is *worse*: an unregistered
operator makes ``get_operator_function`` raise ``ValueError``, which
``_make_filter_field_composed`` swallows with ``except ValueError: continue``.
The filter would vanish while its sibling scoping filters survived, so the
query would succeed and return rows the vector filter was meant to exclude.
Several tests below pin that distinction.
"""

from dataclasses import dataclass

import pytest
from psycopg.sql import SQL, Composed

from fraiseql.errors.exceptions import WhereClauseError
from fraiseql.sql.where.operators.vectors import (
    NON_PREDICATE_OPERATORS,
    build_custom_distance_sql,
    build_quantization_reconstruct_sql,
    build_quantized_distance_sql,
    build_vector_norm_sql,
)
from fraiseql.sql.where_generator import safe_create_where_type
from fraiseql.types.scalars.vector import QuantizedVectorField, SparseVectorField


class _Doc:
    """Bare marker class; filter fields arrive through the OR plain-dict path.

    ``FieldType.from_python_type`` has no ``VECTOR`` mapping, so ``VECTOR`` is
    reached only by field-name detection with no resolved type hint.
    """

    __annotations__ = {}


WhereType = safe_create_where_type(_Doc)


def render_dense(op: str, value: object) -> Composed | None:
    """Render one filter on a vector-ish field name through the registry path."""
    where = WhereType()
    where.OR = [{"embedding": {op: value}}]
    return where.to_sql()


@dataclass
class _SparseDoc:
    sparse_emb: SparseVectorField


@dataclass
class _QuantizedDoc:
    quantized_emb: QuantizedVectorField


class TestNonPredicateOperatorsAreRejected:
    """Every non-boolean vector operator must raise, on every field type."""

    @pytest.mark.parametrize(
        ("operator", "value"),
        [
            ("custom_distance", {"function": "my_dist", "parameters": [1.0, 2.0]}),
            ("custom_distance", {"function": "my_dist"}),
            ("vector_norm", "l2"),
            ("vector_norm", {"threshold": 2.0}),
        ],
    )
    def test_dense_vector_operator_raises(self, operator, value) -> None:
        """Reached by field-name detection with no type hint."""
        with pytest.raises(WhereClauseError):
            render_dense(operator, value)

    def test_null_operator_value_is_still_treated_as_unset(self) -> None:
        """``{"vector_norm": None}`` must keep meaning "not supplied", not "reject".

        ``_make_filter_field_composed`` skips a ``None`` operator value before
        resolving the operator at all, so the rejection is never reached. That
        is the framework-wide convention for every operator -- an unset GraphQL
        input field -- and #510 does not change it. Pinned so the rejection is
        not later widened into a behaviour change for null inputs.
        """
        assert render_dense("vector_norm", None) is None

    @pytest.mark.parametrize(
        ("operator", "value"),
        [
            ("custom_distance", {"function": "my_dist", "parameters": [1.0]}),
            ("vector_norm", "l2"),
        ],
    )
    def test_sparse_vector_operator_raises(self, operator, value) -> None:
        """``SparseVectorField`` *is* mapped in ``from_python_type``."""
        where = safe_create_where_type(_SparseDoc)()
        where.sparse_emb = {operator: value}
        with pytest.raises(WhereClauseError):
            where.to_sql()

    @pytest.mark.parametrize(
        ("operator", "value"),
        [
            ("quantized_distance", {"target_vector": [0.1, 0.2], "distance_type": "cosine"}),
            ("reconstruct", True),
        ],
    )
    def test_quantized_vector_operator_raises(self, operator, value) -> None:
        """``QuantizedVectorField`` is mapped too, so a plain type hint reaches these."""
        where = safe_create_where_type(_QuantizedDoc)()
        where.quantized_emb = {operator: value}
        with pytest.raises(WhereClauseError):
            where.to_sql()

    def test_error_names_the_operator(self) -> None:
        """The message must say which operator was refused, not just that one was."""
        with pytest.raises(WhereClauseError, match="custom_distance"):
            render_dense("custom_distance", {"function": "my_dist"})


class TestRejectionIsLoudNotSilent:
    """Unregistering the operators would drop the filter and widen the result set."""

    def test_sibling_filter_does_not_survive_alone(self) -> None:
        """A surviving scope filter with the vector filter gone is the danger (#505).

        Under the tempting fix -- deleting the four ``OPERATOR_MAP`` entries --
        this renders ``(data ->> 'tenant') = 'acme'`` on its own and executes,
        silently ignoring the vector filter.
        """
        where = WhereType()
        where.OR = [
            {"tenant": {"eq": "acme"}, "embedding": {"custom_distance": {"function": "my_dist"}}}
        ]
        with pytest.raises(WhereClauseError):
            where.to_sql()

    def test_rejection_is_not_a_value_error(self) -> None:
        """``_make_filter_field_composed`` swallows ``ValueError`` and continues."""
        with pytest.raises(WhereClauseError) as excinfo:
            render_dense("vector_norm", "l2")
        assert not isinstance(excinfo.value, ValueError)

    def test_operators_stay_registered(self) -> None:
        """Kept in the registry on purpose, so the reject reaches the caller."""
        from fraiseql.sql.where.core.field_detection import FieldType
        from fraiseql.sql.where.operators import OPERATOR_MAP

        assert (FieldType.VECTOR, "custom_distance") in OPERATOR_MAP
        assert (FieldType.VECTOR, "vector_norm") in OPERATOR_MAP
        assert (FieldType.SPARSE_VECTOR, "custom_distance") in OPERATOR_MAP
        assert (FieldType.SPARSE_VECTOR, "vector_norm") in OPERATOR_MAP
        assert (FieldType.QUANTIZED_VECTOR, "quantized_distance") in OPERATOR_MAP
        assert (FieldType.QUANTIZED_VECTOR, "reconstruct") in OPERATOR_MAP

    def test_registry_names_every_rejected_operator(self) -> None:
        """The rejection table and the registry must not drift apart."""
        assert set(NON_PREDICATE_OPERATORS) == {
            "custom_distance",
            "vector_norm",
            "quantized_distance",
            "reconstruct",
        }

    def test_every_rejected_operator_has_a_remedy(self) -> None:
        """Each entry carries the two message halves ``_reject_non_predicate`` reads."""
        for operator, (renders, remedy) in NON_PREDICATE_OPERATORS.items():
            assert renders, operator
            assert remedy, operator


class TestNoCallerStringReachesTheStatement:
    """The raw-interpolation channels must not render, whatever the payload."""

    @pytest.mark.parametrize(
        "payload",
        [
            # The function name was concatenated verbatim via SQL().
            {"function": "x) OR true --"},
            {"function": "true OR 1=1 --"},
            # 'parameters' was a second, unreported channel: SQL(str(param)).
            {"function": "strpos", "parameters": ["'x') > -1 OR true --"]},
            {"function": "my_dist", "parameters": ["0) OR true --"]},
        ],
    )
    def test_custom_distance_payload_never_renders(self, payload) -> None:
        """Both channels executed as injected SQL against live pgvector."""
        with pytest.raises(WhereClauseError):
            render_dense("custom_distance", payload)

    @pytest.mark.parametrize(
        "payload",
        [
            # 'distance_type' was interpolated into the function name.
            {"target_vector": [0.1], "distance_type": "x(1) OR true --"},
            # Each target_vector element was rendered with SQL(str(v)).
            {"target_vector": ["0.1]'::vector) OR true --"]},
        ],
    )
    def test_quantized_distance_payload_never_renders(self, payload) -> None:
        """``quantized_distance`` carried the same two channels, unreported."""
        where = safe_create_where_type(_QuantizedDoc)()
        where.quantized_emb = {"quantized_distance": payload}
        with pytest.raises(WhereClauseError):
            where.to_sql()


class TestBuildersRejectDirectly:
    """The builders are public; calling one directly must not yield SQL either."""

    @pytest.mark.parametrize(
        ("builder", "value"),
        [
            (build_custom_distance_sql, {"function": "my_dist"}),
            (build_vector_norm_sql, "l2"),
            (build_quantized_distance_sql, {"target_vector": [0.1]}),
            (build_quantization_reconstruct_sql, None),
        ],
    )
    def test_builder_raises_where_clause_error(self, builder, value) -> None:
        with pytest.raises(WhereClauseError):
            builder(SQL("(data ->> 'embedding')"), value)

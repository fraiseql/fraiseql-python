"""Tests for the 10 advanced network classification operators.

Phase 1: Registration tests (ALL_OPERATORS, SUPPORTED_OPERATORS, is_operator_dict, NetworkAddressFilter)
Phase 2: SQL generation tests (_build_cidr_check, individual operator SQL)
Phase 3: Comprehensive coverage, regression, alias equivalence
"""

import pytest
from psycopg.sql import Identifier

ADVANCED_NETWORK_OPS = [
    "isLoopback",
    "isMulticast",
    "isBroadcast",
    "isLinkLocal",
    "isDocumentation",
    "isReserved",
    "isCarrierGrade",
    "isSiteLocal",
    "isUniqueLocal",
    "isGlobalUnicast",
]


# ---------------------------------------------------------------------------
# Phase 1, Cycle 1: NETWORK_OPERATORS dict registration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("op", ADVANCED_NETWORK_OPS)
def test_advanced_op_in_all_operators(op):
    from fraiseql.where_clause import ALL_OPERATORS

    assert op in ALL_OPERATORS, f"{op} not registered in ALL_OPERATORS"


@pytest.mark.parametrize("op", ADVANCED_NETWORK_OPS)
def test_advanced_op_lowercase_alias(op):
    from fraiseql.where_clause import ALL_OPERATORS

    assert op.lower() in ALL_OPERATORS, f"{op.lower()} alias not registered"


# ---------------------------------------------------------------------------
# Phase 1, Cycle 2: SUPPORTED_OPERATORS set registration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("op", ADVANCED_NETWORK_OPS)
def test_strategy_supports_advanced_op(op):
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    assert strategy.supports_operator(op, None), f"Strategy rejects {op}"


@pytest.mark.parametrize("op", ADVANCED_NETWORK_OPS)
def test_strategy_supports_advanced_op_lowercase(op):
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    assert strategy.supports_operator(op.lower(), None), f"Strategy rejects {op.lower()}"


# ---------------------------------------------------------------------------
# Phase 1, Cycle 3: is_operator_dict() recognition
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "op",
    ["isBroadcast", "isReserved", "isSiteLocal", "isUniqueLocal", "isGlobalUnicast"],
)
def test_is_operator_dict_recognizes_advanced_op(op):
    from fraiseql.sql.where.core.sql_builder import is_operator_dict

    assert is_operator_dict({op: True}), f"is_operator_dict rejects {{{op}: True}}"


# ---------------------------------------------------------------------------
# Phase 1, Cycle 4: NetworkAddressFilter lowercase aliases
# ---------------------------------------------------------------------------


def test_network_address_filter_has_lowercase_aliases():
    from fraiseql.sql.graphql_where_generator import NetworkAddressFilter

    for op in ADVANCED_NETWORK_OPS:
        assert hasattr(NetworkAddressFilter, op.lower()), f"Missing lowercase alias: {op.lower()}"


# ---------------------------------------------------------------------------
# Phase 2, Cycle 1: _build_cidr_check helper
# ---------------------------------------------------------------------------


def test_build_cidr_check_single_range():
    from fraiseql.sql.operators.postgresql.network_operators import _build_cidr_check

    result = _build_cidr_check(Identifier("ip"), ["127.0.0.0/8"])
    sql_str = result.as_string(None)
    assert "::inet" in sql_str
    assert "127.0.0.0/8" in sql_str
    assert "<<" in sql_str


def test_build_cidr_check_multiple_ranges():
    from fraiseql.sql.operators.postgresql.network_operators import _build_cidr_check

    result = _build_cidr_check(Identifier("ip"), ["127.0.0.0/8", "::1/128"])
    sql_str = result.as_string(None)
    assert "OR" in sql_str
    assert "127.0.0.0/8" in sql_str
    assert "::1/128" in sql_str


def test_build_cidr_check_negate():
    from fraiseql.sql.operators.postgresql.network_operators import _build_cidr_check

    result = _build_cidr_check(Identifier("ip"), ["127.0.0.0/8"], negate=True)
    sql_str = result.as_string(None)
    assert "NOT" in sql_str


# ---------------------------------------------------------------------------
# Phase 2, Cycle 2: isPrivate/isPublic boolean handling bugfix
# ---------------------------------------------------------------------------


def test_isprivate_false_negates():
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    result = strategy.build_sql("isPrivate", False, Identifier("ip_address"))
    sql_str = result.as_string(None)
    assert "NOT" in sql_str


def test_isprivate_true_no_not():
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    result = strategy.build_sql("isPrivate", True, Identifier("ip_address"))
    assert "NOT" not in result.as_string(None)


def test_ispublic_true_has_not():
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    result = strategy.build_sql("isPublic", True, Identifier("ip_address"))
    assert "NOT" in result.as_string(None)


def test_ispublic_false_no_not():
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    result = strategy.build_sql("isPublic", False, Identifier("ip_address"))
    sql_str = result.as_string(None)
    assert "10.0.0.0/8" in sql_str
    assert "NOT" not in sql_str


# ---------------------------------------------------------------------------
# Phase 2, Cycles 3-11: Individual operator SQL generation
# ---------------------------------------------------------------------------


def test_isloopback_sql():
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    result = strategy.build_sql("isLoopback", True, Identifier("ip_address"))
    sql_str = result.as_string(None)
    assert "127.0.0.0/8" in sql_str
    assert "::1/128" in sql_str


def test_isloopback_false_negates():
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    result = strategy.build_sql("isLoopback", False, Identifier("ip_address"))
    assert "NOT" in result.as_string(None)


def test_ismulticast_sql():
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    sql_str = strategy.build_sql("isMulticast", True, Identifier("ip")).as_string(None)
    assert "224.0.0.0/4" in sql_str
    assert "ff00::/8" in sql_str


def test_isbroadcast_sql():
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    sql_str = strategy.build_sql("isBroadcast", True, Identifier("ip")).as_string(None)
    assert "255.255.255.255/32" in sql_str


def test_islinklocal_sql():
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    sql_str = strategy.build_sql("isLinkLocal", True, Identifier("ip")).as_string(None)
    assert "169.254.0.0/16" in sql_str
    assert "fe80::/10" in sql_str


def test_isdocumentation_has_all_rfc_ranges():
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    sql_str = strategy.build_sql("isDocumentation", True, Identifier("ip")).as_string(None)
    assert "192.0.2.0/24" in sql_str
    assert "198.51.100.0/24" in sql_str
    assert "203.0.113.0/24" in sql_str
    assert "2001:db8::/32" in sql_str


def test_isreserved_sql():
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    sql_str = strategy.build_sql("isReserved", True, Identifier("ip")).as_string(None)
    assert "0.0.0.0/8" in sql_str
    assert "240.0.0.0/4" in sql_str
    assert "::/128" in sql_str


def test_iscarriergrade_ipv4_only():
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    sql_str = strategy.build_sql("isCarrierGrade", True, Identifier("ip")).as_string(None)
    assert "100.64.0.0/10" in sql_str


def test_issitelocal_sql():
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    sql_str = strategy.build_sql("isSiteLocal", True, Identifier("ip")).as_string(None)
    assert "fec0::/10" in sql_str


def test_isuniquelocal_sql():
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    sql_str = strategy.build_sql("isUniqueLocal", True, Identifier("ip")).as_string(None)
    assert "fc00::/7" in sql_str


def test_isglobalunicast_true_excludes_all_special():
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    result = strategy.build_sql("isGlobalUnicast", True, Identifier("ip_address"))
    sql_str = result.as_string(None)
    assert "NOT" in sql_str
    for cidr in ["10.0.0.0/8", "127.0.0.0/8", "224.0.0.0/4", "169.254.0.0/16"]:
        assert cidr in sql_str, f"isGlobalUnicast missing exclusion for {cidr}"


def test_isglobalunicast_false_no_double_negation():
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    result = strategy.build_sql("isGlobalUnicast", False, Identifier("ip_address"))
    sql_str = result.as_string(None)
    assert "NOT" not in sql_str
    assert "10.0.0.0/8" in sql_str


# ---------------------------------------------------------------------------
# Phase 3: SQL output structure (all 10 operators)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("op", ADVANCED_NETWORK_OPS)
def test_advanced_op_produces_sql(op):
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    result = strategy.build_sql(op, True, Identifier("ip_address"))
    sql_str = result.as_string(None)
    assert len(sql_str) > 0
    assert "::inet" in sql_str


@pytest.mark.parametrize("op", ADVANCED_NETWORK_OPS)
def test_advanced_op_false_negates(op):
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    result_true = strategy.build_sql(op, True, Identifier("ip_address"))
    result_false = strategy.build_sql(op, False, Identifier("ip_address"))
    true_sql = result_true.as_string(None)
    false_sql = result_false.as_string(None)

    if op == "isGlobalUnicast":
        # true = NOT (special), false = (special) — no NOT
        assert "NOT" in true_sql
        assert "NOT" not in false_sql
    else:
        # true = (check), false = NOT (check)
        assert "NOT" not in true_sql
        assert "NOT" in false_sql


@pytest.mark.parametrize("op", ADVANCED_NETWORK_OPS)
def test_lowercase_alias_same_sql(op):
    from fraiseql.sql.operators.postgresql.network_operators import NetworkOperatorStrategy

    strategy = NetworkOperatorStrategy()
    camel_sql = strategy.build_sql(op, True, Identifier("ip_address")).as_string(None)
    lower_sql = strategy.build_sql(op.lower(), True, Identifier("ip_address")).as_string(None)
    assert camel_sql == lower_sql


@pytest.mark.parametrize("op", ADVANCED_NETWORK_OPS)
def test_normalize_preserves_camelcase(op):
    from fraiseql.where_normalization import _normalize_operator

    assert _normalize_operator(op) == op, f"{op} was incorrectly converted"

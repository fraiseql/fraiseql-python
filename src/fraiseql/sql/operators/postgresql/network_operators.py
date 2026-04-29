"""Network type operator strategies (INET, CIDR, IPv4, IPv6)."""

from typing import Any, Optional

from psycopg.sql import SQL, Composable

from fraiseql.sql.operators.base import BaseOperatorStrategy

# ---------------------------------------------------------------------------
# CIDR range constants (sourced from IANA Special-Purpose Address Registries)
# ---------------------------------------------------------------------------

# RFC 1122, RFC 4291
LOOPBACK_RANGES = ["127.0.0.0/8", "::1/128"]
# RFC 5771, RFC 4291
MULTICAST_RANGES = ["224.0.0.0/4", "ff00::/8"]
# RFC 919 — IPv6 has no broadcast
BROADCAST_RANGES = ["255.255.255.255/32"]
# RFC 3927, RFC 4291
LINK_LOCAL_RANGES = ["169.254.0.0/16", "fe80::/10"]
# RFC 5737, RFC 3849
DOCUMENTATION_RANGES = ["192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32"]
# RFC 1122, RFC 1112, RFC 4291 — matches Python ipaddress module behavior
RESERVED_RANGES = ["0.0.0.0/8", "240.0.0.0/4", "::/128"]
# RFC 6598 — IPv4 only
CARRIER_GRADE_RANGES = ["100.64.0.0/10"]
# RFC 3879 (deprecated) — IPv6 only
SITE_LOCAL_RANGES = ["fec0::/10"]
# RFC 4193 — IPv6 only
UNIQUE_LOCAL_RANGES = ["fc00::/7"]

# RFC 1918 + special use (used by isPrivate / isPublic)
PRIVATE_RANGES = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "fc00::/7",
    "fe80::/10",
]

# Union of all special-purpose ranges (used by isGlobalUnicast negation)
ALL_SPECIAL_PURPOSE_RANGES = sorted(
    set(
        PRIVATE_RANGES
        + LOOPBACK_RANGES
        + MULTICAST_RANGES
        + BROADCAST_RANGES
        + LINK_LOCAL_RANGES
        + DOCUMENTATION_RANGES
        + RESERVED_RANGES
        + CARRIER_GRADE_RANGES
        + SITE_LOCAL_RANGES
        + UNIQUE_LOCAL_RANGES
    )
)


def _build_cidr_check(path_sql: Composable, ranges: list[str], negate: bool = False) -> Composable:
    """Build a CIDR containment check for one or more ranges.

    Generates: ({field}::inet << inet 'r1' OR {field}::inet << inet 'r2' OR ...)
    With negate=True: NOT ({field}::inet << inet 'r1' OR ...)
    """
    casted = SQL("({})::inet").format(path_sql)
    checks = SQL(" OR ").join(SQL("{} << inet '{}'").format(casted, SQL(cidr)) for cidr in ranges)
    condition = SQL("({})").format(checks)
    if negate:
        condition = SQL("NOT ({})").format(condition)
    return condition


class NetworkOperatorStrategy(BaseOperatorStrategy):
    """Strategy for PostgreSQL network type operators.

    Supports INET, CIDR types with operators:
        - eq, neq: Equality/inequality
        - in, nin: List membership
        - isprivate: Is private network
        - ispublic: Is public network
        - insubnet: Network contains address
        - inrange: IP in CIDR range (alias for insubnet)
        - isipv4: Check if IPv4 address
        - isipv6: Check if IPv6 address
        - overlaps: Networks overlap
        - strictleft, strictright: Ordering
        - isnull: NULL checking
    """

    SUPPORTED_OPERATORS = {
        "eq",
        "neq",
        "in",
        "nin",
        "isprivate",
        "ispublic",
        "insubnet",
        "inrange",
        "isipv4",
        "isipv6",
        "overlaps",
        "strictleft",
        "strictright",
        "isnull",
        # CamelCase versions used by tests
        "isPrivate",
        "isPublic",
        "inSubnet",
        "inRange",
        "isIPv4",
        "isIPv6",
        # Advanced network classification (v1.17.0+)
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
        # Lowercase aliases for advanced operators
        "isloopback",
        "ismulticast",
        "isbroadcast",
        "islinklocal",
        "isdocumentation",
        "isreserved",
        "iscarriergrade",
        "issitelocal",
        "isuniquelocal",
        "isglobalunicast",
    }

    NETWORK_TYPES = {"IPv4Address", "IPv6Address", "IPv4Network", "IPv6Network", "IpAddress"}

    def supports_operator(self, operator: str, field_type: Optional[type]) -> bool:
        """Check if this is a network operator."""
        if operator not in self.SUPPORTED_OPERATORS:
            return False

        # Network-specific operators - support even without field_type
        # The operator name itself is a strong signal this is a network operation
        if operator in {
            "isprivate",
            "ispublic",
            "insubnet",
            "inrange",
            "isipv4",
            "isipv6",
            "overlaps",
            "strictleft",
            "strictright",
            # CamelCase versions
            "isPrivate",
            "isPublic",
            "inSubnet",
            "inRange",
            "isIPv4",
            "isIPv6",
            # Advanced network classification
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
            "isloopback",
            "ismulticast",
            "isbroadcast",
            "islinklocal",
            "isdocumentation",
            "isreserved",
            "iscarriergrade",
            "issitelocal",
            "isuniquelocal",
            "isglobalunicast",
        }:
            # Accept these operators even without field_type
            # If field_type is provided, verify it's a network type
            if field_type is not None:
                type_name = (
                    field_type.__name__ if hasattr(field_type, "__name__") else str(field_type)
                )
                # Only accept if it's actually a network type
                if not any(net_type in type_name for net_type in self.NETWORK_TYPES):
                    return False
            return True

        # Generic operators (eq, neq, in, nin) - require field type verification
        if field_type is not None:
            type_name = field_type.__name__ if hasattr(field_type, "__name__") else str(field_type)
            if any(net_type in type_name for net_type in self.NETWORK_TYPES):
                return True

        return False

    def build_sql(
        self,
        operator: str,
        value: Any,
        path_sql: Composable,
        field_type: Optional[type] = None,
        jsonb_column: Optional[str] = None,
    ) -> Optional[Composable]:
        """Build SQL for network operators."""
        # Comparison operators
        if operator == "eq":
            casted_path, casted_value = self._cast_both_sides(path_sql, str(value), "inet")
            return SQL("{} = {}").format(casted_path, casted_value)

        if operator == "neq":
            casted_path, casted_value = self._cast_both_sides(path_sql, str(value), "inet")
            return SQL("{} != {}").format(casted_path, casted_value)

        # List operators
        if operator == "in":
            # Cast field path
            casted_path = SQL("({})::inet").format(path_sql)

            # Cast each value in list
            value_list = value if isinstance(value, (list, tuple)) else [value]
            casted_values = self._cast_list_values([str(v) for v in value_list], "inet")

            # Build IN clause: field IN (val1, val2, ...)
            values_sql = SQL(", ").join(casted_values)
            return SQL("{} IN ({})").format(casted_path, values_sql)

        if operator == "nin":
            # Cast field path
            casted_path = SQL("({})::inet").format(path_sql)

            # Cast each value in list
            value_list = value if isinstance(value, (list, tuple)) else [value]
            casted_values = self._cast_list_values([str(v) for v in value_list], "inet")

            # Build NOT IN clause: field NOT IN (val1, val2, ...)
            values_sql = SQL(", ").join(casted_values)
            return SQL("{} NOT IN ({})").format(casted_path, values_sql)

        # Network-specific operators
        if operator in {"isprivate", "isPrivate"}:
            return _build_cidr_check(path_sql, PRIVATE_RANGES, negate=not value)

        if operator in {"ispublic", "isPublic"}:
            # isPublic: true = NOT private, isPublic: false = IS private
            return _build_cidr_check(path_sql, PRIVATE_RANGES, negate=bool(value))

        # Advanced network classification operators (v1.17.0+)
        if operator in {"isloopback", "isLoopback"}:
            return _build_cidr_check(path_sql, LOOPBACK_RANGES, negate=not value)

        if operator in {"ismulticast", "isMulticast"}:
            return _build_cidr_check(path_sql, MULTICAST_RANGES, negate=not value)

        if operator in {"isbroadcast", "isBroadcast"}:
            return _build_cidr_check(path_sql, BROADCAST_RANGES, negate=not value)

        if operator in {"islinklocal", "isLinkLocal"}:
            return _build_cidr_check(path_sql, LINK_LOCAL_RANGES, negate=not value)

        if operator in {"isdocumentation", "isDocumentation"}:
            return _build_cidr_check(path_sql, DOCUMENTATION_RANGES, negate=not value)

        if operator in {"isreserved", "isReserved"}:
            return _build_cidr_check(path_sql, RESERVED_RANGES, negate=not value)

        if operator in {"iscarriergrade", "isCarrierGrade"}:
            return _build_cidr_check(path_sql, CARRIER_GRADE_RANGES, negate=not value)

        if operator in {"issitelocal", "isSiteLocal"}:
            return _build_cidr_check(path_sql, SITE_LOCAL_RANGES, negate=not value)

        if operator in {"isuniquelocal", "isUniqueLocal"}:
            return _build_cidr_check(path_sql, UNIQUE_LOCAL_RANGES, negate=not value)

        if operator in {"isglobalunicast", "isGlobalUnicast"}:
            # true = NOT special purpose, false = IS special purpose (no double negation)
            return _build_cidr_check(path_sql, ALL_SPECIAL_PURPOSE_RANGES, negate=bool(value))

        if operator in {"insubnet", "inSubnet"}:
            casted_path, casted_value = self._cast_both_sides(path_sql, str(value), "inet")
            return SQL("{} <<= {}").format(casted_path, casted_value)

        if operator in {"inrange", "inRange"}:
            # inRange is an alias for inSubnet - check if IP is in CIDR range
            casted_path, casted_value = self._cast_both_sides(path_sql, str(value), "inet")
            return SQL("{} <<= {}").format(casted_path, casted_value)

        if operator in {"isipv4", "isIPv4"}:
            casted_path = SQL("({})::inet").format(path_sql)
            return SQL("family({}) = 4").format(casted_path)

        if operator in {"isipv6", "isIPv6"}:
            casted_path = SQL("({})::inet").format(path_sql)
            return SQL("family({}) = 6").format(casted_path)

        if operator == "overlaps":
            casted_path, casted_value = self._cast_both_sides(path_sql, str(value), "inet")
            return SQL("{} && {}").format(casted_path, casted_value)

        if operator == "strictleft":
            casted_path, casted_value = self._cast_both_sides(path_sql, str(value), "inet")
            return SQL("{} << {}").format(casted_path, casted_value)

        if operator == "strictright":
            casted_path, casted_value = self._cast_both_sides(path_sql, str(value), "inet")
            return SQL("{} >> {}").format(casted_path, casted_value)

        # NULL checking
        if operator == "isnull":
            return self._build_null_check(path_sql, value)

        return None

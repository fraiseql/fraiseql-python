"""Field type detection for where clause generation.

This module provides clean, testable functions to detect what type of field
we're dealing with based on field names, values, and type hints.
"""

import re
from enum import Enum
from typing import Any


class FieldType(Enum):
    """Enumeration of field types for where clause generation."""

    ANY = "any"
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    UUID = "uuid"
    DATE = "date"
    DATETIME = "datetime"
    ARRAY = "array"
    JSONB = "jsonb"
    IP_ADDRESS = "ip_address"
    MAC_ADDRESS = "mac_address"
    LTREE = "ltree"
    DATE_RANGE = "date_range"
    HOSTNAME = "hostname"
    EMAIL = "email"
    PORT = "port"
    FULLTEXT = "fulltext"
    VECTOR = "vector"

    def is_ip_address(self) -> bool:
        """Check if this field type is IP address."""
        return self == FieldType.IP_ADDRESS

    @classmethod
    def from_python_type(cls, python_type: type) -> "FieldType":
        """Convert Python type to FieldType."""
        # Try to detect FraiseQL scalar types
        try:
            from fraiseql.types.scalars.ip_address import IpAddressField

            if python_type == IpAddressField or (
                isinstance(python_type, type) and issubclass(python_type, IpAddressField)
            ):
                return cls.IP_ADDRESS
        except ImportError:
            pass

        # Try to detect other FraiseQL scalar types
        try:
            from fraiseql.types import CIDR, IpAddress, LTree, MacAddress
            from fraiseql.types.scalars.date import DateField
            from fraiseql.types.scalars.daterange import DateRangeField
            from fraiseql.types.scalars.datetime import DateTimeField

            type_mapping = {
                IpAddress: cls.IP_ADDRESS,
                CIDR: cls.IP_ADDRESS,
                MacAddress: cls.MAC_ADDRESS,
                LTree: cls.LTREE,
                DateRangeField: cls.DATE_RANGE,
                DateTimeField: cls.DATETIME,
                DateField: cls.DATE,
            }

            if python_type in type_mapping:
                return type_mapping[python_type]
        except ImportError:
            pass

        # Check for JSONB type (dict type hint often indicates JSONB)
        if python_type is dict:
            return cls.JSONB

        # Standard Python types
        from datetime import date, datetime
        from decimal import Decimal
        from typing import get_origin
        from uuid import UUID

        # Handle list types (arrays)
        if get_origin(python_type) is list:
            return cls.ARRAY

        type_mapping = {
            str: cls.STRING,
            int: cls.INTEGER,
            float: cls.FLOAT,
            Decimal: cls.FLOAT,
            bool: cls.BOOLEAN,
            UUID: cls.UUID,
            date: cls.DATE,
            datetime: cls.DATETIME,
        }

        return type_mapping.get(python_type, cls.STRING)

    @classmethod
    def from_value(cls, value: Any) -> "FieldType":
        """Detect field type from a value."""
        if value is None:
            return cls.ANY

        if isinstance(value, bool):
            return cls.BOOLEAN

        if isinstance(value, int):
            return cls.INTEGER

        if isinstance(value, float):
            return cls.FLOAT

        if isinstance(value, str):
            # Check for MAC address patterns first (before IP to avoid IPv6-like false positives)
            if _is_mac_address_value(value):
                return cls.MAC_ADDRESS

            # Check for IP address patterns
            if _is_ip_address_value(value):
                return cls.IP_ADDRESS

            # Check for LTree patterns
            if _is_ltree_value(value):
                return cls.LTREE

            # Check for DateRange patterns
            if _is_daterange_value(value):
                return cls.DATE_RANGE

            # Check for DateTime patterns (ISO 8601 with time)
            if _is_datetime_value(value):
                return cls.DATETIME

            # Check for Date patterns (ISO 8601 date only)
            if _is_date_value(value):
                return cls.DATE

            return cls.STRING

        if isinstance(value, list):
            return cls.ARRAY

        return cls.ANY


def detect_field_type(field_name: str, value: Any, field_type: type | None = None) -> FieldType:
    """Detect the type of field for where clause generation.

    Args:
        field_name: The name of the field (camelCase or snake_case)
        value: The value being filtered on
        field_type: Optional Python type hint

    Returns:
        FieldType enum indicating what type of field this is
    """
    # Check field name for FULLTEXT type specifically before type hint
    # This allows detecting tsvector fields which are often typed as str in Python
    field_lower = field_name.lower() if field_name else ""
    fulltext_patterns = [
        "search_vector",
        "searchvector",
        "tsvector",
        "ts_vector",
        "fulltext_vector",
        "fulltextvector",
        "text_search",
        "textsearch",
        "search_index",
        "searchindex",
    ]
    if any(pattern in field_lower for pattern in fulltext_patterns):
        return FieldType.FULLTEXT

    # First priority: explicit type hint
    if field_type is not None:
        return FieldType.from_python_type(field_type)

    # Second priority: field name patterns
    field_type_from_name = _detect_field_type_from_name(field_name)
    if field_type_from_name != FieldType.ANY:
        return field_type_from_name

    # Third priority: value analysis
    return FieldType.from_value(value)


def _detect_field_type_from_name(field_name: str) -> FieldType:
    """Detect field type from field name patterns."""
    if not field_name:
        return FieldType.ANY

    field_lower = field_name.lower()

    # IP address patterns - handle both snake_case and camelCase
    ip_patterns = [
        "ip_address",
        "ipaddress",
        "server_ip",
        "gateway_ip",
        "host_ip",
        "serverip",
        "gatewayip",
        "hostip",
    ]

    # Check pattern matches
    if any(pattern in field_lower for pattern in ip_patterns):
        return FieldType.IP_ADDRESS

    # Additional IP patterns that should be whole words or at start/end
    if (
        field_lower in ["ip", "host"]
        or field_lower.endswith(("_ip", "ip"))
        or field_lower.startswith(("ip_", "ip"))
    ):
        return FieldType.IP_ADDRESS

    # MAC address patterns - handle both snake_case and camelCase
    mac_patterns = [
        "mac_address",
        "macaddress",
        "device_mac",
        "mac_addr",
        "hardware_address",
        "devicemac",
        "macaddr",
        "hardwareaddress",
    ]

    # Check MAC pattern matches
    if any(pattern in field_lower for pattern in mac_patterns):
        return FieldType.MAC_ADDRESS

    # Additional MAC patterns that should be whole words or at start/end
    if (
        field_lower == "mac"
        or field_lower.endswith(("_mac", "mac"))
        or field_lower.startswith(("mac_", "mac"))
    ):
        return FieldType.MAC_ADDRESS

    # LTree path patterns - handle both snake_case and camelCase
    ltree_patterns = [
        "category_path",
        "categorypath",
        "navigation_path",
        "navigationpath",
        "tree_path",
        "treepath",
        "hierarchy_path",
        "hierarchypath",
        "taxonomy_path",
        "taxonomypath",
    ]

    # Check LTree pattern matches
    if any(pattern in field_lower for pattern in ltree_patterns):
        return FieldType.LTREE

    # Additional LTree patterns that should be whole words or at start/end
    if (
        field_lower in ["path", "tree", "hierarchy"]
        or field_lower.endswith(("_path", "path", "_tree", "tree"))
        or field_lower.startswith(("path_", "path", "tree_", "tree"))
    ):
        return FieldType.LTREE

    # DateTime patterns - handle both snake_case and camelCase
    datetime_patterns = [
        "created_at",
        "createdat",
        "updated_at",
        "updatedat",
        "timestamp",
        "event_time",
        "eventtime",
        "start_time",
        "starttime",
        "end_time",
        "endtime",
        "last_modified",
        "lastmodified",
        "last_accessed",
        "lastaccessed",
        "published_at",
        "publishedat",
    ]

    # Check DateTime pattern matches
    if any(pattern in field_lower for pattern in datetime_patterns):
        return FieldType.DATETIME

    # Additional DateTime patterns that should be whole words or at start/end
    if (
        field_lower in ["timestamp", "datetime"]
        or field_lower.endswith(("_at", "at", "_time", "time", "_timestamp", "timestamp"))
        or field_lower.startswith(("timestamp_", "timestamp", "datetime_", "datetime"))
    ):
        return FieldType.DATETIME

    # Date patterns - handle both snake_case and camelCase
    date_patterns = [
        "birth_date",
        "birthdate",
        "start_date",
        "startdate",
        "end_date",
        "enddate",
        "event_date",
        "eventdate",
        "due_date",
        "duedate",
        "expiry_date",
        "expirydate",
        "expiration_date",
        "expirationdate",
        "created_date",
        "createddate",
        "modified_date",
        "modifieddate",
    ]

    # Check Date pattern matches
    if any(pattern in field_lower for pattern in date_patterns):
        return FieldType.DATE

    # Additional Date patterns that should be whole words or at start/end
    if (
        field_lower == "date"
        or field_lower.endswith(("_date", "date"))
        or field_lower.startswith(("date_", "date"))
    ):
        return FieldType.DATE

    # Hostname patterns - handle both snake_case and camelCase
    hostname_patterns = [
        "hostname",
        "server_name",
        "servername",
        "domain_name",
        "domainname",
        "api_endpoint",
        "apiendpoint",
        "service_url",
        "serviceurl",
    ]

    # Check Hostname pattern matches
    if any(pattern in field_lower for pattern in hostname_patterns):
        return FieldType.HOSTNAME

    # Additional Hostname patterns
    if (
        field_lower in ["host", "domain", "endpoint", "url"]
        or field_lower.endswith(("_hostname", "hostname", "_host", "host", "_domain", "domain"))
        or field_lower.startswith(("hostname_", "hostname", "host_", "host", "api_", "api"))
    ):
        return FieldType.HOSTNAME

    # Email patterns - handle both snake_case and camelCase
    email_patterns = [
        "email",
        "email_address",
        "emailaddress",
        "contact_email",
        "contactemail",
        "user_email",
        "useremail",
    ]

    # Check Email pattern matches
    if any(pattern in field_lower for pattern in email_patterns):
        return FieldType.EMAIL

    # Additional Email patterns
    if (
        field_lower == "email"
        or field_lower.endswith(("_email", "email"))
        or field_lower.startswith(("email_", "email"))
    ):
        return FieldType.EMAIL

    # Port patterns - handle both snake_case and camelCase
    port_patterns = [
        "port",
        "server_port",
        "serverport",
        "service_port",
        "serviceport",
        "listen_port",
        "listenport",
    ]

    # Check Port pattern matches
    if any(pattern in field_lower for pattern in port_patterns):
        return FieldType.PORT

    # Additional Port patterns
    if (
        field_lower == "port"
        or field_lower.endswith(("_port", "port"))
        or field_lower.startswith(("port_", "port"))
    ):
        return FieldType.PORT

    # Vector embedding patterns - handle both snake_case and camelCase
    # NOTE: Vector detection must come BEFORE fulltext detection to take precedence
    vector_patterns = [
        "embedding",
        "vector",
        "_embedding",
        "_vector",
        "embedding_vector",
        "embeddingvector",
        "text_embedding",
        "textembedding",
        "image_embedding",
        "imageembedding",
    ]

    # Check vector pattern matches
    if any(pattern in field_lower for pattern in vector_patterns):
        return FieldType.VECTOR

    # Full-text search patterns - handle both snake_case and camelCase
    fulltext_patterns = [
        "search_vector",
        "searchvector",
        "tsvector",
        "ts_vector",
        "fulltext_vector",
        "fulltextvector",
        "text_search",
        "textsearch",
        "search_index",
        "searchindex",
    ]

    # Check Full-text pattern matches
    if any(pattern in field_lower for pattern in fulltext_patterns):
        return FieldType.FULLTEXT

    # Additional Full-text patterns
    if (
        field_lower in ["search", "tsvector", "fulltext"]
        or field_lower.endswith(("_search", "search", "_vector", "vector", "_index", "index"))
        or field_lower.startswith(("search_", "search", "ts_", "ts", "fulltext_", "fulltext"))
    ):
        return FieldType.FULLTEXT

    return FieldType.ANY


def _is_ip_address_value(value: str) -> bool:
    """Check if a string value looks like an IP address."""
    try:
        import ipaddress

        # Try to parse as IP address (both IPv4 and IPv6)
        try:
            ipaddress.ip_address(value)
            return True
        except ValueError:
            # Also try as CIDR network (might be used in comparisons)
            try:
                ipaddress.ip_network(value, strict=False)
                return True
            except ValueError:
                pass

        # Additional heuristic checks for common IP patterns
        # IPv4-like pattern
        if value.count(".") == 3:
            parts = value.split(".")
            if len(parts) == 4 and all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
                return True

        # IPv6-like pattern (simplified check)
        if ":" in value and value.count(":") >= 2:
            # Basic IPv6 pattern check - contains only valid hex chars and colons
            hex_chars = "0123456789abcdefABCDEF"
            return all(c in hex_chars + ":" for c in value)

    except ImportError:
        # Fallback to basic pattern matching if ipaddress module not available
        if value.count(".") == 3:
            parts = value.split(".")
            try:
                return all(0 <= int(part) <= 255 for part in parts)
            except ValueError:
                pass

    return False


def _is_mac_address_value(value: str) -> bool:
    """Check if a string value looks like a MAC address."""
    if not value:
        return False

    # Remove common separators
    mac_clean = value.replace(":", "").replace("-", "").replace(" ", "").upper()

    # MAC address should be exactly 12 hex characters
    if len(mac_clean) != 12:
        return False

    # Check if all characters are valid hex
    try:
        int(mac_clean, 16)
        return True
    except ValueError:
        return False


def _is_ltree_value(value: str) -> bool:
    """Check if a string value looks like an LTree path."""
    if not value or value.startswith(".") or value.endswith(".") or ".." in value:
        return False

    if "." not in value:
        return False  # LTree paths should be hierarchical

    # Check for valid LTree characters and patterns
    ltree_pattern = r"^[a-zA-Z0-9_-]+(\.[a-zA-Z0-9_-]+)+$"

    if not re.match(ltree_pattern, value):
        return False

    # Additional checks to avoid domain name false positives
    domain_extensions = {
        "com",
        "net",
        "org",
        "edu",
        "gov",
        "mil",
        "int",
        "co",
        "uk",
        "ca",
        "de",
        "fr",
        "jp",
        "au",
        "ru",
        "io",
        "ai",
        "dev",
        "app",
        "api",
        "www",
    }

    # If the last part is a common domain extension, probably not an LTree
    last_part = value.rsplit(".", maxsplit=1)[-1].lower()
    if last_part in domain_extensions:
        return False

    # If it looks like a URL, probably not an LTree
    if value.lower().startswith(("www.", "api.", "app.", "dev.", "test.")):
        return False

    return True


def _is_daterange_value(value: str) -> bool:
    """Check if a string value looks like a PostgreSQL DateRange."""
    if len(value) < 7:  # Minimum: '[a,b]'
        return False

    if not (value.startswith(("[", "(")) and value.endswith(("]", ")"))):
        return False

    # Extract the content between brackets
    content = value[1:-1]  # Remove brackets

    if "," not in content:
        return False

    # Split on comma and check each part looks like a date
    parts = content.split(",")
    if len(parts) != 2:
        return False

    # Basic date pattern check (YYYY-MM-DD)
    date_pattern = r"^\d{4}-\d{2}-\d{2}$"

    for part in parts:
        stripped_part = part.strip()
        if not stripped_part:  # Allow empty for infinite ranges
            continue
        if not re.match(date_pattern, stripped_part):
            return False

    return True


def _is_datetime_value(value: str) -> bool:
    """Check if a string value looks like an ISO 8601 datetime."""
    if not value or len(value) < 10:  # Minimum: YYYY-MM-DD
        return False

    # Must contain 'T' for datetime (not just date)
    if "T" not in value:
        return False

    # Basic datetime pattern: YYYY-MM-DDTHH:MM:SS with optional timezone and microseconds
    datetime_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})?$"

    if not re.match(datetime_pattern, value):
        return False

    # Additional validation: check the date part is reasonable
    date_part = value.split("T", maxsplit=1)[0]
    try:
        year, month, day = map(int, date_part.split("-"))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return False
        # Basic month/day validation
        if month in [4, 6, 9, 11] and day > 30:
            return False
        if month == 2:
            # Check leap year
            is_leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
            if day > (29 if is_leap else 28):
                return False
        return True
    except (ValueError, IndexError):
        return False


def _is_date_value(value: str) -> bool:
    """Check if a string value looks like an ISO 8601 date."""
    if not value or len(value) != 10:  # Must be exactly YYYY-MM-DD
        return False

    # Must NOT contain 'T' (that would be datetime)
    if "T" in value:
        return False

    # Basic date pattern: YYYY-MM-DD
    date_pattern = r"^\d{4}-\d{2}-\d{2}$"

    if not re.match(date_pattern, value):
        return False

    # Additional validation: check if it's a reasonable date
    try:
        year, month, day = map(int, value.split("-"))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return False
        # Basic month/day validation
        if month in [4, 6, 9, 11] and day > 30:
            return False
        if month == 2:
            # Check leap year
            is_leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
            if day > (29 if is_leap else 28):
                return False
        return True
    except ValueError:
        return False

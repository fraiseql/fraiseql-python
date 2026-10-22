"""Custom GraphQL scalar types for FraiseQL.

This module exposes reusable scalar implementations that extend GraphQL's
capabilities to support domain-specific values such as IP addresses, UUIDs,
date ranges, JSON objects, financial types, and more.

Each export is a `GraphQLScalarType` used directly in schema definitions.

Exports:
- CIDRScalar: CIDR notation for IP network ranges.
- CoordinateScalar: Geographic coordinates (latitude, longitude).
- CurrencyCodeScalar: ISO 4217 three-letter currency codes.
- CUSIPScalar: Committee on Uniform Security Identification Procedures.
- DateRangeScalar: PostgreSQL daterange values.
- DateScalar: ISO 8601 calendar date.
- DateTimeScalar: ISO 8601 datetime with timezone awareness.
- DecimalScalar: Exact decimal numbers (decimal.Decimal), serialized as strings.
- ExchangeCodeScalar: Stock exchange codes.
- ExchangeRateScalar: Currency exchange rates with high precision.
- HostnameScalar: DNS hostnames (RFC 1123 compliant).
- IpAddressScalar: IPv4 and IPv6 addresses as strings.
- ISINScalar: International Securities Identification Numbers.
- JSONScalar: Arbitrary JSON-serializable values.
- LanguageCodeScalar: ISO 639-1 two-letter language codes.
- LEIScalar: Legal Entity Identifiers.
- LocaleCodeScalar: BCP 47 locale codes (language-REGION format).
- LTreeScalar: PostgreSQL ltree path type.
- MacAddressScalar: Hardware MAC addresses.
- MICScalar: Market Identifier Codes (ISO 10383).
- MoneyScalar: Financial amounts with 4 decimal precision.
- PercentageScalar: Percentage values (0.00-100.00).
- PortScalar: Network port number (1-65535).
- SEDOLScalar: Stock Exchange Daily Official List numbers.
- StockSymbolScalar: Stock ticker symbols.
- SubnetMaskScalar: CIDR-style subnet masks.
- TimezoneScalar: IANA timezone database identifiers.
- UUIDScalar: RFC 4122 UUID values.
"""

from .airport_code import AirportCodeScalar
from .api_key import ApiKeyScalar
from .cidr import CIDRScalar
from .color import ColorScalar
from .container_number import ContainerNumberScalar
from .coordinates import CoordinateScalar
from .currency_code import CurrencyCodeScalar
from .cusip import CUSIPScalar
from .date import DateScalar
from .daterange import DateRangeScalar
from .datetime import DateTimeScalar
from .decimal import DecimalScalar
from .domain_name import DomainNameScalar
from .duration import DurationScalar
from .exchange_code import ExchangeCodeScalar
from .exchange_rate import ExchangeRateScalar
from .file import FileScalar
from .flight_number import FlightNumberScalar
from .hash_sha256 import HashSHA256Scalar
from .hostname import HostnameScalar
from .html import HTMLScalar
from .iban import IBANScalar
from .id_scalar import IDScalar
from .image import ImageScalar
from .ip_address import IpAddressScalar, SubnetMaskScalar
from .isin import ISINScalar
from .json import JSONScalar
from .language_code import LanguageCodeScalar
from .latitude import LatitudeScalar
from .lei import LEIScalar
from .license_plate import LicensePlateScalar
from .locale_code import LocaleCodeScalar
from .longitude import LongitudeScalar
from .ltree import LTreeScalar
from .mac_address import MacAddressScalar
from .markdown import MarkdownScalar
from .mic import MICScalar
from .mime_type import MimeTypeScalar
from .money import MoneyScalar
from .percentage import PercentageScalar
from .phone_number import PhoneNumberScalar
from .port import PortScalar
from .port_code import PortCodeScalar
from .postal_code import PostalCodeScalar
from .sedol import SEDOLScalar
from .semantic_version import SemanticVersionScalar
from .slug import SlugScalar
from .stock_symbol import StockSymbolScalar
from .time import TimeScalar
from .timezone import TimezoneScalar
from .tracking_number import TrackingNumberScalar
from .url import URLScalar
from .uuid import UUIDScalar
from .vector import VectorScalar
from .vin import VINScalar

__all__ = [
    "AirportCodeScalar",
    "ApiKeyScalar",
    "CIDRScalar",
    "CUSIPScalar",
    "ColorScalar",
    "ContainerNumberScalar",
    "CoordinateScalar",
    "CurrencyCodeScalar",
    "DateRangeScalar",
    "DateScalar",
    "DateTimeScalar",
    "DecimalScalar",
    "DomainNameScalar",
    "DurationScalar",
    "ExchangeCodeScalar",
    "ExchangeRateScalar",
    "FileScalar",
    "FlightNumberScalar",
    "HTMLScalar",
    "HashSHA256Scalar",
    "HostnameScalar",
    "IBANScalar",
    "IDScalar",
    "ISINScalar",
    "ImageScalar",
    "IpAddressScalar",
    "JSONScalar",
    "LEIScalar",
    "LTreeScalar",
    "LanguageCodeScalar",
    "LatitudeScalar",
    "LicensePlateScalar",
    "LocaleCodeScalar",
    "LongitudeScalar",
    "MICScalar",
    "MacAddressScalar",
    "MarkdownScalar",
    "MimeTypeScalar",
    "MoneyScalar",
    "PercentageScalar",
    "PhoneNumberScalar",
    "PortCodeScalar",
    "PortScalar",
    "PostalCodeScalar",
    "SEDOLScalar",
    "SemanticVersionScalar",
    "SlugScalar",
    "StockSymbolScalar",
    "SubnetMaskScalar",
    "TimeScalar",
    "TimezoneScalar",
    "TrackingNumberScalar",
    "URLScalar",
    "UUIDScalar",
    "VINScalar",
    "VectorScalar",
]

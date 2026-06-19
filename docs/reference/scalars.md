---
title: Custom Scalar Types Reference
description: Reference for FraiseQL v1's built-in GraphQL scalar types and their validation rules.
keywords: ["scalars", "types", "schema", "validation", "reference"]
tags: ["documentation", "reference"]
---

# Custom Scalar Types Reference

FraiseQL v1 ships a large set of domain-specific GraphQL scalar types in addition to the
GraphQL built-ins. They give you:

- **Type safety** — validation at the GraphQL boundary, before values reach PostgreSQL.
- **Format standardization** — ISO standards, RFC compliance, and domain conventions.
- **Consistent serialization** — stable JSON representations in and out.
- **Clear errors** — validation failures surface as GraphQL errors, not stack traces.

All scalars are imported from the lowercase `fraiseql.types` module:

```python
from fraiseql.types import ID, UUID, Date, DateTime, EmailAddress, Money, LTree
```

> FraiseQL v1 is **PostgreSQL only**. Read types are backed by a `data` JSONB column on a
> `v_`/`tv_` view, so a scalar's "stored" representation is whatever you place inside that
> JSONB document — there is no per-database type matrix. The schema is built in memory at
> application startup, fully at runtime.

---

## Using scalars in type definitions

Annotate fields on a `@fraiseql.type` with these scalars. The `sql_source` names the
read view; `jsonb_column` names the JSONB column that holds the row's data (defaults to
`"data"`).

```python
import fraiseql
from fraiseql.types import (
    UUID,
    DateTime,
    Date,
    EmailAddress,
    PhoneNumber,
    Money,
    CurrencyCode,
    Slug,
    Markdown,
    Coordinate,
    LTree,
)


@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    """A user in the system."""

    id: UUID
    email: EmailAddress
    phone: PhoneNumber | None = None
    created_at: DateTime
    born_date: Date | None = None


@fraiseql.type(sql_source="v_product", jsonb_column="data")
class Product:
    """A product with pricing and location."""

    id: UUID
    name: str
    slug: Slug
    price: Money
    currency: CurrencyCode = "USD"
    category_path: LTree
    location: Coordinate | None = None


@fraiseql.type(sql_source="v_blog_post", jsonb_column="data")
class BlogPost:
    """A blog post with rich content."""

    id: UUID
    title: str
    slug: Slug
    content: Markdown
    created_at: DateTime
    tags: list[str]
```

---

## Core scalars

The everyday identifiers, temporal, and structured-data types.

| Scalar | Python import | GraphQL type | Description / validation | Example |
|--------|---------------|--------------|--------------------------|---------|
| `ID` | `from fraiseql.types import ID` | `ID` | GraphQL built-in identifier; any serializable string-like value. | `"42"`, `"550e8400-..."` |
| `UUID` | `from fraiseql.types import UUID` | `UUID` | RFC 4122 UUID, hyphenated. | `550e8400-e29b-41d4-a716-446655440000` |
| `Date` | `from fraiseql.types import Date` | `Date` | ISO 8601 calendar date `YYYY-MM-DD`. | `2026-01-11` |
| `DateTime` | `from fraiseql.types import DateTime` | `DateTime` | ISO 8601 timestamp; output in UTC with `Z`. | `2026-01-11T15:30:00Z` |
| `Time` | `from fraiseql.types import Time` | `Time` | 24-hour wall-clock time `HH:MM[:SS]`. | `14:30`, `09:15:30` |
| `JSON` | `from fraiseql.types import JSON` | `JSON` | Arbitrary JSON-serializable value (object, array, scalar, null). | `{"key": "value"}` |
| `EmailAddress` | `from fraiseql.types import EmailAddress` | `EmailAddress` | RFC 5322 email address. | `user@example.com` |
| `URL` | `from fraiseql.types import URL` | `URL` | RFC 3986 URL; scheme + host required. | `https://api.example.com/v1` |
| `LTree` | `from fraiseql.types import LTree` | `LTree` | PostgreSQL `ltree` dot-separated label path (requires the `ltree` extension). | `top.science.physics` |

See [`../foundation/09-type-system.md`](../foundation/09-type-system.md) for how Python type
hints map onto GraphQL types.

---

## Network scalars

IP addresses, hosts, domains, and ports.

| Scalar | Python import | GraphQL type | Description / validation | Example |
|--------|---------------|--------------|--------------------------|---------|
| `IpAddress` | `from fraiseql.types import IpAddress` | `IpAddress` | IPv4 or IPv6 address (CIDR suffix accepted). | `192.168.1.1`, `2001:db8::1` |
| `CIDR` | `from fraiseql.types import CIDR` | `CIDR` | CIDR network range `address/prefix`. | `192.168.1.0/24`, `2001:db8::/32` |
| `MacAddress` | `from fraiseql.types import MacAddress` | `MacAddress` | 48-bit MAC address; normalized to colon form. | `00:11:22:33:44:55` |
| `Hostname` | `from fraiseql.types import Hostname` | `Hostname` | RFC 1123 hostname; TLD not required. | `api-server`, `db.internal` |
| `DomainName` | `from fraiseql.types import DomainName` | `DomainName` | RFC-compliant FQDN; TLD required. | `api.example.com` |
| `Port` | `from fraiseql.types import Port` | `Port` | Network port integer, 1–65535. | `443`, `5432` |

---

## Geographic scalars

Coordinates and individual latitude/longitude components.

| Scalar | Python import | GraphQL type | Description / validation | Example |
|--------|---------------|--------------|--------------------------|---------|
| `Coordinate` | `from fraiseql.types import Coordinate` | `Coordinate` | Lat/lng pair; serialized as `{lat, lng}`. | `37.7749,-122.4194` |
| `Latitude` | `from fraiseql.types import Latitude` | `Latitude` | Decimal degrees, -90.0 to +90.0. | `40.7128` |
| `Longitude` | `from fraiseql.types import Longitude` | `Longitude` | Decimal degrees, -180.0 to +180.0. | `-74.0060` |

---

## Money and number scalars

Monetary values, currencies, percentages, and exchange rates.

| Scalar | Python import | GraphQL type | Description / validation | Example |
|--------|---------------|--------------|--------------------------|---------|
| `Money` | `from fraiseql.types import Money` | `Money` | Fixed-precision decimal amount (4 fractional digits). | `123.45` → `123.4500` |
| `CurrencyCode` | `from fraiseql.types import CurrencyCode` | `CurrencyCode` | ISO 4217 three-letter code; uppercased. | `USD`, `EUR` |
| `Percentage` | `from fraiseql.types import Percentage` | `Percentage` | Decimal 0.00–100.00 (direct percentage). | `25.5` |
| `ExchangeRate` | `from fraiseql.types import ExchangeRate` | `ExchangeRate` | High-precision conversion rate. | `1.23456789` |

---

## Web and text scalars

URLs, slugs, colors, markup, and version strings.

| Scalar | Python import | GraphQL type | Description / validation | Example |
|--------|---------------|--------------|--------------------------|---------|
| `URL` | `from fraiseql.types import URL` | `URL` | RFC 3986 URL (also listed under core). | `https://example.com/path` |
| `Slug` | `from fraiseql.types import Slug` | `Slug` | Lowercase URL-friendly identifier; no leading/trailing or repeated hyphens. | `my-blog-post` |
| `Color` | `from fraiseql.types import Color` | `Color` | Hex color `#RGB` or `#RRGGBB`; lowercased. | `#3366cc` |
| `Markdown` | `from fraiseql.types import Markdown` | `Markdown` | Markdown text (GitHub-flavored). | `# Title\n\nBody` |
| `HTML` | `from fraiseql.types import HTML` | `HTML` | Raw HTML content; sanitize on display. | `<p>Hello</p>` |
| `MimeType` | `from fraiseql.types import MimeType` | `MimeType` | RFC 6838 media type `type/subtype`. | `application/json` |
| `SemanticVersion` | `from fraiseql.types import SemanticVersion` | `SemanticVersion` | Semver `MAJOR.MINOR.PATCH[-pre][+build]`. | `2.0.0-beta.1` |

---

## Finance and securities scalars

Standardized financial-institution and security identifiers.

| Scalar | Python import | GraphQL type | Description / validation | Example |
|--------|---------------|--------------|--------------------------|---------|
| `IBAN` | `from fraiseql.types import IBAN` | `IBAN` | ISO 13616 account number; mod-97 check; uppercased. | `DE89370400440532013000` |
| `ISIN` | `from fraiseql.types import ISIN` | `ISIN` | ISO 6166 security ID, 12 chars; Luhn check. | `US0378331005` |
| `CUSIP` | `from fraiseql.types import CUSIP` | `CUSIP` | 9-char North American security ID; check digit. | `037833100` |
| `SEDOL` | `from fraiseql.types import SEDOL` | `SEDOL` | 7-char UK security ID; check digit. | `0263494` |
| `LEI` | `from fraiseql.types import LEI` | `LEI` | ISO 17442 legal entity ID, 20 chars. | `549300E9PC51EN656011` |
| `MIC` | `from fraiseql.types import MIC` | `MIC` | ISO 10383 market identifier code, 4 chars. | `XNYS`, `XNAS` |
| `StockSymbol` | `from fraiseql.types import StockSymbol` | `StockSymbol` | Ticker symbol; optional class suffix; uppercased. | `AAPL`, `BRK.A` |
| `ExchangeCode` | `from fraiseql.types import ExchangeCode` | `ExchangeCode` | Market exchange identifier; uppercased. | `NYSE`, `NASDAQ` |

---

## Logistics and transport scalars

Codes for travel, shipping, and vehicles.

| Scalar | Python import | GraphQL type | Description / validation | Example |
|--------|---------------|--------------|--------------------------|---------|
| `AirportCode` | `from fraiseql.types import AirportCode` | `AirportCode` | IATA 3-letter airport code; uppercased. | `LAX`, `LHR` |
| `PortCode` | `from fraiseql.types import PortCode` | `PortCode` | Shipping port identifier (e.g. UN/LOCODE). | `USLA`, `JPTYO` |
| `FlightNumber` | `from fraiseql.types import FlightNumber` | `FlightNumber` | Airline + numeric flight designator. | `BA117`, `AF1680` |
| `ContainerNumber` | `from fraiseql.types import ContainerNumber` | `ContainerNumber` | ISO 6346 shipping-container number. | `MSCU1234565` |
| `TrackingNumber` | `from fraiseql.types import TrackingNumber` | `TrackingNumber` | Carrier shipment tracking number. | `1Z999AA10123456784` |
| `LicensePlate` | `from fraiseql.types import LicensePlate` | `LicensePlate` | Vehicle registration plate (format varies by country). | `AB19 CDZ` |
| `VIN` | `from fraiseql.types import VIN` | `VIN` | ISO 3779/3780 vehicle ID, 17 chars; check digit. | `1HGBH41JXMN109186` |

---

## Miscellaneous scalars

Durations, ranges, contact details, localization, files, and security values.

| Scalar | Python import | GraphQL type | Description / validation | Example |
|--------|---------------|--------------|--------------------------|---------|
| `Duration` | `from fraiseql.types import Duration` | `Duration` | ISO 8601 duration `P…T…`. | `P1Y2M3DT4H5M6S` |
| `DateRange` | `from fraiseql.types import DateRange` | `DateRange` | Date range with inclusive/exclusive bounds. | `[2026-01-01, 2026-12-31]` |
| `PhoneNumber` | `from fraiseql.types import PhoneNumber` | `PhoneNumber` | E.164 international phone number. | `+14155552671` |
| `PostalCode` | `from fraiseql.types import PostalCode` | `PostalCode` | International postal code (flexible format). | `90210`, `SW1A 1AA` |
| `LanguageCode` | `from fraiseql.types import LanguageCode` | `LanguageCode` | ISO 639-1 two-letter language code; lowercased. | `en`, `fr` |
| `LocaleCode` | `from fraiseql.types import LocaleCode` | `LocaleCode` | BCP 47 locale identifier. | `en-US`, `zh-Hant-TW` |
| `Timezone` | `from fraiseql.types import Timezone` | `Timezone` | IANA timezone identifier (case-sensitive). | `Europe/Paris`, `UTC` |
| `File` | `from fraiseql.types import File` | `File` | File reference (URL or path). | `s3://bucket/doc.pdf` |
| `Image` | `from fraiseql.types import Image` | `Image` | Image URL or path; extension-validated. | `/uploads/avatar.png` |
| `HashSHA256` | `from fraiseql.types import HashSHA256` | `HashSHA256` | 64-character SHA-256 hex digest. | `e3b0c442...b7852b855` |
| `ApiKey` | `from fraiseql.types import ApiKey` | `ApiKey` | API key / access token, 16–128 chars. Treat as sensitive. | `sk_live_ABC123xyz-def456` |

---

## Validation and serialization

- Scalars validate input at GraphQL execution time. Invalid values are rejected and
  returned as GraphQL errors before any database access.
- Output values are serialized to their canonical string/JSON form (for example, MAC
  addresses normalize to colon form and currency codes to uppercase).
- Because read data lives in a JSONB `data` column, scalar values round-trip as JSON; use
  the corresponding PostgreSQL operators (for example `ltree`, `inet`, range operators)
  inside your `v_`/`tv_` view SQL when you need server-side filtering.

## Best practices

1. Prefer a specific scalar over a bare `str`:
   - Good: `email: EmailAddress`
   - Avoid: `email: str`
2. Use precise types for money and identifiers:
   - Good: `price: Money`, `id: UUID`
   - Avoid: `price: float`, `id: str`
3. Treat `ApiKey` and `HashSHA256` as sensitive — never log them and always serve over HTTPS.
4. Sanitize `HTML` on render; it is stored as-is.

---

## See also

- [`./decorators.md`](./decorators.md) — `@fraiseql.type`, `@fraiseql.query`, and related decorators.
- [`./where-operators.md`](./where-operators.md) — PostgreSQL WHERE operators for filtering.
- [`../foundation/09-type-system.md`](../foundation/09-type-system.md) — how Python types map to GraphQL.

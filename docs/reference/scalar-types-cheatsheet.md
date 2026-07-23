<!-- Skip to main content -->
---

title: Scalar Types Cheat Sheet
description: Quick reference for all FraiseQL scalar types, mappings, and examples.
keywords: ["directives", "types", "scalars", "schema", "api"]
tags: ["documentation", "reference"]
---

# Scalar Types Cheat Sheet

**Status:** ✅ Production Ready
**Audience:** Developers, DBAs
**Reading Time:** 5-8 minutes
**Last Updated:** 2026-02-05

Quick reference for FraiseQL's PostgreSQL scalar types, their PostgreSQL column
mappings, and examples. Custom scalars are importable from `fraiseql.types`
(for example `from fraiseql.types import ID, EmailAddress, DateTime`).

## String Types

| Scalar | PostgreSQL Type | Size | Use Case | Example |
|--------|-----------------|------|----------|---------|
| `str` | TEXT / VARCHAR | Unlimited | Text, names | `"John Doe"` |
| `ID` | UUID | 36 bytes | Unique identifiers | `"550e8400-e29b-41d4-a716-446655440000"` |
| `EmailAddress` | TEXT | 254 bytes | Email validation | `"user@example.com"` |
| `URL` | TEXT | Unlimited | Web addresses | `"https://example.com/path"` |
| `PhoneNumber` | TEXT | 20 bytes | Phone numbers | `"+1-555-123-4567"` |
| `Slug` | TEXT | 255 | URL-friendly text | `"my-awesome-post"` |

## Numeric Types

| Scalar | PostgreSQL Type | Range | Use Case | Example |
|--------|-----------------|-------|----------|---------|
| `int` | INTEGER | -2.1B to 2.1B | Counts, ages | `42` |
| `int` | BIGINT | ±9.2 quintillion | Large numbers | `9223372036854775807` |
| `float` | DOUBLE PRECISION | IEEE 754 | Approximate decimals | `3.14159` |
| `Decimal` | NUMERIC | Arbitrary | Money, precise | `"99.99"` |

## Date & Time Types

| Scalar | PostgreSQL Type | Format | Use Case | Example |
|--------|-----------------|--------|----------|---------|
| `DateTime` | TIMESTAMP WITH TIME ZONE | ISO 8601 | Full date+time | `"2024-01-15T14:30:00Z"` |
| `Date` | DATE | YYYY-MM-DD | Date only | `"2024-01-15"` |
| `Time` | TIME | HH:MM:SS | Time only | `"14:30:00"` |
| `Duration` | INTERVAL | ISO 8601 | Time spans | `"PT1H30M"` |

## JSON Types

| Scalar | PostgreSQL Type | Structure | Use Case | Example |
|--------|-----------------|-----------|----------|---------|
| `JSON` | JSONB | Any JSON | Flexible / indexed data | `{"key": "value"}` |

## Binary & Hash Types

| Scalar | PostgreSQL Type | Encoding | Use Case | Example |
|--------|-----------------|----------|----------|---------|
| `bytes` | BYTEA | Base64 | File data | `"aGVsbG8gd29ybGQ="` |
| `HashSHA256` | TEXT | Hex | Checksums | `"e3b0c44298fc1c149afbf4c8996fb924..."` |

## Boolean

| Scalar | PostgreSQL Type | Values | Use Case | Example |
|--------|-----------------|--------|----------|---------|
| `bool` | BOOLEAN | true/false | Flags | `true` |

---

## PostgreSQL Type Mappings

FraiseQL is PostgreSQL-only. Python/scalar types map to PostgreSQL columns as follows:

```text
str          → TEXT
int          → INTEGER (or BIGINT)
float        → DOUBLE PRECISION
Decimal      → NUMERIC
DateTime     → TIMESTAMP WITH TIME ZONE
Date         → DATE
Time         → TIME
Duration     → INTERVAL
bool         → BOOLEAN
JSON         → JSONB
bytes        → BYTEA
ID / UUID    → UUID
```

## Domain Scalars

Beyond the core scalars above, FraiseQL ships a large set of validated domain
scalars, all importable from `fraiseql.types`. Each stores as a TEXT-family
PostgreSQL column with validation enforced at the GraphQL boundary. A selection:

| Category | Scalars |
|----------|---------|
| Network | `IpAddress`, `CIDR`, `MacAddress`, `Hostname`, `DomainName`, `Port` |
| Geo | `Coordinate`, `Latitude`, `Longitude` |
| Money / finance | `Money`, `CurrencyCode`, `Percentage`, `ExchangeRate`, `IBAN`, `ISIN` |
| Locale | `LanguageCode`, `LocaleCode`, `Timezone`, `PostalCode` |
| Web / content | `Color`, `SemanticVersion`, `Markdown`, `HTML`, `MimeType`, `File`, `Image` |
| Identifiers | `HashSHA256`, `ApiKey`, `VIN`, `LicensePlate`, `TrackingNumber` |
| Date ranges | `DateRange` |

```python
from fraiseql.types import ID, EmailAddress, DateTime, Money, IpAddress
```

---

## Size Limits

| Type | Max Size | Warning Level |
|------|----------|--------------|
| `str` | PostgreSQL limit (~1 GB) | >1MB is large |
| `EmailAddress` | 254 bytes | Don't exceed RFC spec |
| `PhoneNumber` | 20 bytes | International format |
| `Slug` | 255 bytes | URL safe |
| `JSON` | PostgreSQL limit (~1 GB) | >10MB is huge |
| `bytes` | PostgreSQL limit (~1 GB) | Prefer external storage >100MB |

---

## Schema Examples

### User Type

```python
import fraiseql
from decimal import Decimal
from fraiseql.types import ID, EmailAddress, DateTime, JSON

@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    id: ID                    # UUID primary key
    email: EmailAddress       # Email with validation
    name: str                 # User's full name
    age: int                  # Years old
    created_at: DateTime      # Account creation time
    is_active: bool           # Account status
    preferences: JSON         # User settings (JSONB column)
```

### Product Type

```python
import fraiseql
from decimal import Decimal
from fraiseql.types import ID, Date, JSON

@fraiseql.type(sql_source="v_product", jsonb_column="data")
class Product:
    id: ID
    name: str
    price: Decimal            # Use Decimal for money!
    stock_count: int
    description: str
    release_date: Date
    is_available: bool
    metadata: JSON            # Flexible data
```

### Event Type

```python
import fraiseql
from fraiseql.types import ID, DateTime, Duration, JSON

@fraiseql.type(sql_source="v_event", jsonb_column="data")
class Event:
    id: ID
    event_name: str
    timestamp: DateTime       # Use DateTime for events
    duration: Duration        # How long it lasted
    data: JSON                # Event details (JSONB column)
    created_at: DateTime
```

---

## Query Examples

### Filtering

```graphql
# String
{ users(where: { name: { eq: "John" } }) }
{ users(where: { email: { contains: "@example.com" } }) }

# Numbers
{ products(where: { price: { gt: 100 } }) }
{ users(where: { age: { gte: 18, lte: 65 } }) }

# Dates
{ orders(where: { created_at: { gt: "2024-01-01" } }) }

# Boolean
{ users(where: { is_active: { eq: true } }) }
```

### Sorting

```graphql
# Numbers
{ products(order_by: { price: DESC }) }

# Dates
{ events(order_by: { timestamp: ASC }) }

# Strings
{ users(order_by: { name: ASC }) }
```

### Aggregation

FraiseQL derives runtime auto-aggregation (SUM, AVG, COUNT, MIN, MAX, and others)
directly from selected aggregate fields against your `v_`/`tv_` views:

```graphql
# Count
{ users_aggregate { count } }

# Sum (numbers only)
{ orders_aggregate { total_price_sum: price_sum } }

# Average (numbers only)
{ products_aggregate { avg_price: price_avg } }

# Min/Max
{ orders_aggregate { min_price: price_min, max_price: price_max } }
```

---

## Common Mistakes

### ❌ Using float for Money

```python
# WRONG
@fraiseql.type(sql_source="v_order", jsonb_column="data")
class Order:
    total: float  # Rounding errors!
```

### ✅ Using Decimal for Money

```python
# RIGHT
@fraiseql.type(sql_source="v_order", jsonb_column="data")
class Order:
    total: Decimal  # Exact precision (NUMERIC)
```

---

### ❌ Using str for Boolean

```python
# WRONG
@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    is_active: str  # "true" or "false"?
```

### ✅ Using bool

```python
# RIGHT
@fraiseql.type(sql_source="v_user", jsonb_column="data")
class User:
    is_active: bool  # true or false, unambiguous
```

---

### ❌ Naive timestamps in your view

```python
# WRONG (ambiguous) — view column is TIMESTAMP WITHOUT TIME ZONE
created_at: DateTime  # Which timezone?
```

### ✅ Timezone-aware timestamps

```python
# RIGHT (unambiguous) — view column is TIMESTAMP WITH TIME ZONE
created_at: DateTime  # Always UTC, explicit
```

---

## See Also

- **[WHERE Operators Cheatsheet](./where-operators-cheatsheet.md)** - Filtering syntax
- **[Scalars Reference](./scalars.md)** - Full list of FraiseQL scalar types
- **[ltree Operators](./ltree-operators.md)** - Hierarchical path filtering

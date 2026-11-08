<!-- Skip to main content -->
---

title: WHERE Operators Cheat Sheet
description: Quick reference for all filtering operators in FraiseQL GraphQL queries.
keywords: ["directives", "types", "scalars", "schema", "api"]
tags: ["documentation", "reference"]
---

# WHERE Operators Cheat Sheet

**Status:** ✅ Production Ready
**Audience:** Developers
**Reading Time:** 5-8 minutes
**Last Updated:** 2026-02-05

Quick reference for all filtering operators in FraiseQL GraphQL queries.

## Comparison Operators

### equals

Filter for exact match.

```graphql
<!-- Code example in GraphQL -->
query {
  users(where: { status: { equals: "active" } }) {
    id name
  }
}

# SQL: WHERE status = 'active'
```
<!-- Code example in TEXT -->

### not

Filter for not equal.

```graphql
<!-- Code example in GraphQL -->
query {
  users(where: { status: { not: "deleted" } }) {
    id name
  }
}

# SQL: WHERE status != 'deleted'
```
<!-- Code example in TEXT -->

### in

Filter for any in list.

```graphql
<!-- Code example in GraphQL -->
query {
  users(where: { role: { in: ["admin", "moderator", "user"] } }) {
    id name
  }
}

# SQL: WHERE role IN ('admin', 'moderator', 'user')
```
<!-- Code example in TEXT -->

### notIn

Filter for not in list.

```graphql
<!-- Code example in GraphQL -->
query {
  users(where: { status: { notIn: ["banned", "deleted"] } }) {
    id name
  }
}

# SQL: WHERE status NOT IN ('banned', 'deleted')
```
<!-- Code example in TEXT -->

---

## String Operators

### contains

Case-insensitive substring match.

```graphql
<!-- Code example in GraphQL -->
query {
  users(where: { email: { contains: "@gmail.com" } }) {
    id name
  }
}

# SQL: WHERE email ILIKE '%@gmail.com%'
```
<!-- Code example in TEXT -->

### startsWith

String starts with.

```graphql
<!-- Code example in GraphQL -->
query {
  users(where: { name: { startsWith: "John" } }) {
    id name
  }
}

# SQL: WHERE name LIKE 'John%'
```
<!-- Code example in TEXT -->

### endsWith

String ends with.

```graphql
<!-- Code example in GraphQL -->
query {
  users(where: { email: { endsWith: "@example.com" } }) {
    id name
  }
}

# SQL: WHERE email LIKE '%@example.com'
```
<!-- Code example in TEXT -->

### regex

Regular expression match.

```graphql
<!-- Code example in GraphQL -->
query {
  users(where: { phone: { regex: "^\\+1-\\d{3}-\\d{3}-\\d{4}$" } }) {
    id name
  }
}

# SQL: WHERE phone ~ '^\+1-\d{3}-\d{3}-\d{4}$'
```
<!-- Code example in TEXT -->

---

## Numeric Operators

### greaterThan

```graphql
<!-- Code example in GraphQL -->
query {
  products(where: { price: { greaterThan: 100 } }) {
    id name price
  }
}

# SQL: WHERE price > 100
```
<!-- Code example in TEXT -->

### greaterThanOrEqual

```graphql
<!-- Code example in GraphQL -->
query {
  products(where: { price: { greaterThanOrEqual: 100 } }) {
    id name price
  }
}

# SQL: WHERE price >= 100
```
<!-- Code example in TEXT -->

### lessThan

```graphql
<!-- Code example in GraphQL -->
query {
  products(where: { price: { lessThan: 50 } }) {
    id name price
  }
}

# SQL: WHERE price < 50
```
<!-- Code example in TEXT -->

### lessThanOrEqual

```graphql
<!-- Code example in GraphQL -->
query {
  products(where: { price: { lessThanOrEqual: 50 } }) {
    id name price
  }
}

# SQL: WHERE price <= 50
```
<!-- Code example in TEXT -->

### between

```graphql
<!-- Code example in GraphQL -->
query {
  products(where: { price: { between: 50, 200 } }) {
    id name price
  }
}

# SQL: WHERE price BETWEEN 50 AND 200
```
<!-- Code example in TEXT -->

---

## Date Operators

### after

For dates after specified date.

```graphql
<!-- Code example in GraphQL -->
query {
  orders(where: { created_at: { after: "2024-01-01" } }) {
    id created_at
  }
}

# SQL: WHERE created_at > '2024-01-01'
```
<!-- Code example in TEXT -->

### before

For dates before specified date.

```graphql
<!-- Code example in GraphQL -->
query {
  orders(where: { created_at: { before: "2024-12-31" } }) {
    id created_at
  }
}

# SQL: WHERE created_at < '2024-12-31'
```
<!-- Code example in TEXT -->

### betweenDates

Between two dates.

```graphql
<!-- Code example in GraphQL -->
query {
  orders(where: { created_at: { betweenDates: "2024-01-01", "2024-12-31" } }) {
    id created_at
  }
}

# SQL: WHERE created_at >= '2024-01-01' AND created_at <= '2024-12-31'
```
<!-- Code example in TEXT -->

### dayOfWeek

Filter by day of week (1=Monday, 7=Sunday).

```graphql
<!-- Code example in GraphQL -->
query {
  events(where: { date: { dayOfWeek: 5 } }) {
    id date
  }
}

# SQL: WHERE EXTRACT(DOW FROM date) = 5 (Friday)
```
<!-- Code example in TEXT -->

### dayOfMonth

Filter by day of month (1-31).

```graphql
<!-- Code example in GraphQL -->
query {
  birthdays(where: { date: { dayOfMonth: 25 } }) {
    id date
  }
}

# SQL: WHERE EXTRACT(DAY FROM date) = 25
```
<!-- Code example in TEXT -->

### month

Filter by month (1-12).

```graphql
<!-- Code example in GraphQL -->
query {
  birthdays(where: { date: { month: 12 } }) {
    id date
  }
}

# SQL: WHERE EXTRACT(MONTH FROM date) = 12
```
<!-- Code example in TEXT -->

### year

Filter by year.

```graphql
<!-- Code example in GraphQL -->
query {
  orders(where: { created_at: { year: 2024 } }) {
    id created_at
  }
}

# SQL: WHERE EXTRACT(YEAR FROM created_at) = 2024
```
<!-- Code example in TEXT -->

---

## Boolean Operators

### AND

All conditions must be true.

```graphql
<!-- Code example in GraphQL -->
query {
  users(where: {
    AND: [
      { age: { greaterThan: 18 } }
      { status: { equals: "active" } }
    ]
  }) {
    id name age status
  }
}

# SQL: WHERE age > 18 AND status = 'active'
```
<!-- Code example in TEXT -->

### OR

Any condition can be true.

```graphql
<!-- Code example in GraphQL -->
query {
  users(where: {
    OR: [
      { role: { equals: "admin" } }
      { role: { equals: "moderator" } }
    ]
  }) {
    id name role
  }
}

# SQL: WHERE role = 'admin' OR role = 'moderator'
```
<!-- Code example in TEXT -->

### NOT

Condition is false.

```graphql
<!-- Code example in GraphQL -->
query {
  users(where: {
    NOT: { status: { equals: "deleted" } }
  }) {
    id name status
  }
}

# SQL: WHERE NOT (status = 'deleted')
```
<!-- Code example in TEXT -->

---

## NULL Operators

### isNull

Check if value is NULL.

```graphql
<!-- Code example in GraphQL -->
query {
  users(where: { deleted_at: { isNull: true } }) {
    id name
  }
}

# SQL: WHERE deleted_at IS NULL
```
<!-- Code example in TEXT -->

### isNotNull

Check if value is NOT NULL.

```graphql
<!-- Code example in GraphQL -->
query {
  users(where: { deleted_at: { isNotNull: true } }) {
    id name
  }
}

# SQL: WHERE deleted_at IS NOT NULL
```
<!-- Code example in TEXT -->

---

## Complex Examples

### Multiple Conditions (AND)

```graphql
<!-- Code example in GraphQL -->
query {
  orders(where: {
    AND: [
      { status: { in: ["pending", "processing"] } }
      { total: { greaterThan: 100 } }
      { created_at: { after: "2024-01-01" } }
    ]
  }) {
    id total status created_at
  }
}

# SQL: WHERE (status IN ('pending', 'processing'))
#      AND (total > 100)
#      AND (created_at > '2024-01-01')
```
<!-- Code example in TEXT -->

### OR Conditions

```graphql
<!-- Code example in GraphQL -->
query {
  users(where: {
    OR: [
      { email: { contains: "@gmail.com" } }
      { email: { contains: "@yahoo.com" } }
      { phone: { startsWith: "+1" } }
    ]
  }) {
    id email phone
  }
}

# SQL: WHERE (email LIKE '%@gmail.com%')
#      OR (email LIKE '%@yahoo.com%')
#      OR (phone LIKE '+1%')
```
<!-- Code example in TEXT -->

### NOT with Complex Condition

```graphql
<!-- Code example in GraphQL -->
query {
  products(where: {
    NOT: {
      OR: [
        { status: { equals: "discontinued" } }
        { stock: { equals: 0 } }
      ]
    }
  }) {
    id name status stock
  }
}

# SQL: WHERE NOT (status = 'discontinued' OR stock = 0)
```
<!-- Code example in TEXT -->

### Nested AND/OR

```graphql
<!-- Code example in GraphQL -->
query {
  orders(where: {
    AND: [
      { user_id: { equals: "123" } }
      {
        OR: [
          { status: { equals: "completed" } }
          { status: { equals: "refunded" } }
        ]
      }
      { created_at: { after: "2024-01-01" } }
    ]
  }) {
    id status created_at
  }
}

# SQL: WHERE user_id = '123'
#      AND (status = 'completed' OR status = 'refunded')
#      AND created_at > '2024-01-01'
```
<!-- Code example in TEXT -->

---

## Performance Tips

### ✅ Good Practices

```graphql
<!-- Code example in GraphQL -->
# Index frequently filtered columns
users(where: { email: { equals: "user@example.com" } })

# Use specific filters
products(where: { category: { in: ["A", "B"] } })

# Combine with pagination
users(where: { status: { equals: "active" } }, limit: 100)
```
<!-- Code example in TEXT -->

### ❌ Bad Practices

```graphql
<!-- Code example in GraphQL -->
# Avoid LIKE on unindexed columns
users(where: { name: { contains: "%" } })

# Avoid complex regex on large text
articles(where: { content: { regex: "complex.*pattern" } })

# Avoid very long IN lists (>1000 items)
users(where: { id: { in: ["id1", "id2", ... "id10000"] } })
```
<!-- Code example in TEXT -->

---

## See Also

- **[Scalar Types Cheatsheet](./scalar-types-cheatsheet.md)** - Type reference
- **[Configuration Parameters Cheatsheet](../reference/cli-commands-cheatsheet.md)** - TOML settings
- **[CLI Commands Cheatsheet](./cli-commands-cheatsheet.md)** - Command-line reference
